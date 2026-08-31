"""
Kaori API — Pattern B sidecar.

Thin FastAPI surface Liminal can call this week:
  POST /v1/compile
  POST /v1/validate
  GET  /v1/standing/{agent_id}
  GET  /v1/truth/{truthkey}

Wraps TruthOrchestrator.compile_observations and FlowCore.get_standing.
Truth order: observe → validate → compile. Observe/record can stay async
internally. POST /v1/compile 200 is returned only after VALIDATION_VOTE is
recorded and the full TruthState is persisted (GET /v1/truth shape, not
{truthkey}). A late generalist 200 still records VALIDATION_VOTE. YAML
timeout with no vote does not compile and does not return 200. No 422.
CLIP stays private. Compiler stays pure.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.agent import Agent
from kaori_flow.primitives.signal import SignalTypes
from kaori_flow.settlement import (
    OUTCOME_UNKNOWN,
    RECKLESS_PENALTY_DEFAULT,
    participating_agent_ids,
    quality_score_from_confidence,
    score_contributors,
)
from kaori_truth.compiler import CompilationError
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthstate import TruthState, TruthStatus
from kaori_truth.signing import production_signing_required
from pydantic import ValidationError

from kaori_api.auth import AuthError, agent_id_from_token, parse_bearer
from kaori_api.evidence_store import (
    EvidenceStorageError,
    GcsEvidenceStore,
    InMemoryEvidenceStore,
)
from kaori_api.claims import attach_claim_agents
from kaori_api.generalist import (
    ValidationVote,
    sign_validation_vote,
)
from kaori_api.generalist_client import (
    GeneralistClient,
    compiler_votes_for_truthkey,
    generalist_timeout_seconds,
    start_validate_and_record,
    vote_as_compiler_record,
    votes_for_truthkey,
)
from kaori_api.orchestrator import TruthOrchestrator, UnknownClaimTypeError
from kaori_api.trust_adapter import FlowTrustProvider
from kaori_api.validation import (
    VALIDATION_VOTES,
    agent_is_known,
    ensure_agent_registered,
    ensure_claimtype_registered,
    ensure_generalist_registered,
    record_observation_submitted,
    record_validation_vote,
)

LOGGER = logging.getLogger(__name__)
LIMINAL_ORIGIN = "https://kind-keepsake-kingdom.lovable.app"
LIMINAL_PREVIEW_ORIGIN = (
    "https://id-preview--3edd781a-00a9-4e58-88be-c21405c611ee.lovable.app"
)
LIMINAL_ORIGINS = [LIMINAL_ORIGIN, LIMINAL_PREVIEW_ORIGIN]
SOURCE_TYPE_BY_AGENT_TYPE = {
    "individual": "human",
    "sensor": "sensor",
    "official": "official",
}


def extra_cors_origins() -> List[str]:
    """Optional extra browser origins from KAORI_CORS_ORIGINS. Never '*'."""
    origins: List[str] = []
    for part in os.environ.get("KAORI_CORS_ORIGINS", "").split(","):
        origin = part.strip().rstrip("/")
        if not origin or origin == "*":
            continue
        origins.append(origin)
    return origins


def cors_origins() -> List[str]:
    """Lovable live/preview plus any extra production or local origins."""
    seen: List[str] = []
    for origin in [*LIMINAL_ORIGINS, *extra_cors_origins()]:
        if origin not in seen:
            seen.append(origin)
    return seen


def default_schema_path() -> str:
    env = os.environ.get("KAORI_SCHEMA_PATH")
    if env:
        return env
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "kaori-spec" / "schemas",
        Path.cwd() / "packages" / "kaori-spec" / "schemas",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return str(candidate)
    return "packages/kaori-spec/schemas"


def create_stores() -> Tuple[Any, Any, Any]:
    """Signal, Bronze observation, and signed artifact stores.

    Cloud SQL connections check that the schema already exists. They do not
    apply DDL — run `python -m kaori_db.migrate` as the migration owner.
    """
    database_url = os.environ.get("DATABASE_URL")
    if os.environ.get("KAORI_ENVIRONMENT", "").strip().lower() == "production" and not database_url:
        raise RuntimeError("DATABASE_URL is required when KAORI_ENVIRONMENT=production")
    if database_url:
        from kaori_db import (
            PostgresObservationStore,
            PostgresSignalStore,
            PostgresTruthArtifactStore,
        )
        from kaori_db.store import require_kaori_schema
        from kaori_truth.signing import require_production_signing_config

        signals = PostgresSignalStore(database_url)
        if signals.engine.dialect.name == "postgresql":
            require_production_signing_config()
            require_kaori_schema(signals.engine)
        else:
            # SQLite is a unit-test store only. Cloud SQL never reaches here.
            signals.ensure_schema()
        return (
            signals,
            PostgresObservationStore(engine=signals.engine),
            PostgresTruthArtifactStore(engine=signals.engine),
        )
    from kaori_db import InMemoryObservationStore, InMemoryTruthArtifactStore

    return InMemorySignalStore(), InMemoryObservationStore(), InMemoryTruthArtifactStore()


def create_store():
    """PostgresSignalStore when DATABASE_URL is set; in-memory otherwise."""
    signals, _, _ = create_stores()
    return signals


def create_flow(store=None) -> FlowCore:
    return FlowCore(store=store or create_store())


def create_evidence_store():
    """Use private GCS in production and memory only for local/test runs."""
    if os.environ.get("KAORI_OBSERVATIONS_BUCKET"):
        return GcsEvidenceStore.from_env()
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "KAORI_OBSERVATIONS_BUCKET is required when DATABASE_URL is configured"
        )
    return InMemoryEvidenceStore()


def _source_type_from_flow(flow: FlowCore, agent_id: str) -> str:
    for signal in flow.store.get_for_agent(agent_id):
        if signal.signal_type == SignalTypes.AGENT_REGISTERED and signal.object_id == agent_id:
            agent_type = (signal.payload or {}).get("agent_type", "individual")
            return SOURCE_TYPE_BY_AGENT_TYPE.get(agent_type, "human")
    return "human"


def reporter_context_from_flow(flow: FlowCore, agent_id: str) -> ReporterContext:
    """Build ReporterContext from Flow standing. Client must not mint trust."""
    standing = flow.get_standing(agent_id)
    derived = Agent(agent_id=agent_id, standing=standing).derived_class
    return ReporterContext(
        standing=Standing(derived),
        trust_score=round(min(1.0, max(0.0, standing / 1000.0)), 6),
        source_type=_source_type_from_flow(flow, agent_id),
    )


def stamp_observation(
    raw: Dict[str, Any],
    agent_id: str,
    context: ReporterContext,
) -> Dict[str, Any]:
    """Overwrite reporter_id and reporter_context. Do not accept field aliases."""
    stamped = dict(raw)
    stamped["reporter_id"] = agent_id
    stamped["reporter_context"] = context.model_dump(mode="json")
    return stamped


def _require_field(value: Any, field: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise HTTPException(status_code=400, detail=f"Missing EvidenceRef field: {field}")


def validate_evidence_refs(observations: List[Observation], claim_type=None) -> None:
    """Law 4 plus per-Observation evidence counts from the ClaimType contract."""
    if not observations:
        raise HTTPException(status_code=400, detail="At least one observation is required")
    evidence_policy = {}
    if claim_type is not None:
        evidence_policy = (claim_type.get_config() or {}).get("evidence") or {}
    minimum = int(evidence_policy.get("min_count", 1))
    maximum = evidence_policy.get("max_count")
    for obs in observations:
        refs = obs.evidence_refs
        if len(refs) < minimum:
            raise HTTPException(
                status_code=400,
                detail=f"Observation requires at least {minimum} evidence_refs",
            )
        if maximum is not None and len(refs) > int(maximum):
            raise HTTPException(
                status_code=400,
                detail=f"Observation allows at most {int(maximum)} evidence_refs",
            )
        for ref in refs:
            _require_field(getattr(ref, "uri", None), "uri")
            _require_field(getattr(ref, "sha256", None), "sha256")


def required_payload_fields(claim_type) -> List[str]:
    """Required observation payload names from ClaimType ui_schema (required: true)."""
    config = claim_type.get_config() if hasattr(claim_type, "get_config") else {}
    fields = ((config or {}).get("ui_schema") or {}).get("fields") or []
    names: List[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        if field.get("required") is True and field.get("name"):
            names.append(str(field["name"]))
    return names


def validate_payload_fields(observations: List[Observation], claim_type) -> None:
    """Required payload fields come from the loaded spec ui_schema, not a hardcoded claim type."""
    required = required_payload_fields(claim_type)
    for obs in observations:
        payload = obs.payload or {}
        for field in required:
            if field not in payload or payload[field] is None:
                raise HTTPException(status_code=400, detail=f"Missing payload field: {field}")


class TruthKeyLocks:
    """One compile lock per TruthKey so recompile does not serialize the world."""

    def __init__(self) -> None:
        self._meta = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}

    def get(self, truth_key: str) -> threading.Lock:
        with self._meta:
            lock = self._locks.get(truth_key)
            if lock is None:
                lock = threading.Lock()
                self._locks[truth_key] = lock
            return lock


def compile_after_vote(
    *,
    orchestrator: TruthOrchestrator,
    truth_store: Any,
    flow: FlowCore,
    observations: List[Observation],
    truth_key: str,
    claim_type_id: str,
    agent_id: str,
    votes: Optional[List[dict]] = None,
    ai_scores: Optional[List[float]] = None,
) -> dict:
    """compile_truth_state only after a VALIDATION_VOTE exists for this TruthKey."""
    if not votes_for_truthkey(flow, truth_key):
        raise RuntimeError("compile_truth_state forbidden without a recorded vote")
    recorded = compiler_votes_for_truthkey(flow, truth_key)
    merged = _merge_vote_records(recorded, votes)
    for agent in participating_agent_ids(
        observations=observations,
        votes=merged,
        claim_type_id=claim_type_id,
    ):
        if agent.startswith("ai:") or agent.startswith("validator:"):
            ensure_agent_registered(flow, agent, role="validator")
        elif agent.startswith("claimtype:"):
            ensure_claimtype_registered(flow, claim_type_id)
        else:
            ensure_agent_registered(flow, agent, role="observer")
    truth_state, trust_snapshot = orchestrator.compile_observations_with_snapshot(
        observations=observations,
        truth_key=truth_key,
        claim_type_id=claim_type_id,
        ai_scores=ai_scores,
        votes=merged,
    )
    artifact = persist_truth_state(
        truth_store, truth_state, trust_snapshot, claim_type_id
    )
    emit_compile_truthstate(flow, truth_state, observations, claim_type_id)
    return artifact


def _merge_vote_records(
    recorded: List[dict], extra: Optional[List[dict]]
) -> List[dict]:
    merged: List[dict] = []
    seen: set[tuple] = set()
    for record in [*(recorded or []), *(extra or [])]:
        key = (
            record.get("agent_id"),
            record.get("vote") or record.get("vote_type"),
            record.get("timestamp"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def persist_truth_state(
    truth_store: Any,
    state: TruthState,
    trust_snapshot: Any,
    claim_type_id: Optional[str] = None,
) -> dict:
    """Append signed Silver revision and atomically refresh the Gold projection."""
    artifact = state.model_dump(mode="json")
    if claim_type_id:
        artifact = attach_claim_agents(artifact, trust_snapshot, claim_type_id, state)
    if hasattr(truth_store, "append"):
        stored = truth_store.append(state, trust_snapshot)
        if claim_type_id and isinstance(stored, dict):
            return attach_claim_agents(stored, trust_snapshot, claim_type_id, state)
        return stored
    # Compatibility for injected legacy stores while integrations migrate.
    truth_store.upsert(
        truthkey=state.truthkey,
        artifact=artifact,
        compiled_at=state.compile_inputs.compile_time,
    )
    return artifact


def emit_compile_truthstate(
    flow: FlowCore,
    state: TruthState,
    observations: List[Observation],
    claim_type_id: str,
) -> None:
    """Standing moves from TRUTHSTATE_EMITTED history, not a minted number."""
    ensure_claimtype_registered(flow, claim_type_id)
    votes = list((state.consensus.votes if state.consensus else None) or [])
    status = state.status.value
    quality = quality_score_from_confidence(state.confidence)
    scores = score_contributors(
        status=status,
        observations=observations,
        votes=votes,
        claim_type_id=claim_type_id,
    )
    if not scores:
        contributors = participating_agent_ids(
            observations=observations,
            votes=votes,
            claim_type_id=claim_type_id,
        )
        flow.emit_truthstate(
            truthkey=state.truthkey,
            status=status,
            confidence=state.confidence,
            contributors=contributors,
            outcome=OUTCOME_UNKNOWN,
            quality_score=quality,
        )
        return
    for score in scores:
        flow.emit_truthstate(
            truthkey=state.truthkey,
            status=status,
            confidence=state.confidence,
            contributors=[score.agent_id],
            outcome=score.outcome,
            quality_score=quality,
        )
        if score.reckless:
            amount = min(50.0, RECKLESS_PENALTY_DEFAULT)
            flow.apply_penalty(
                score.agent_id,
                amount,
                "reckless_confidence",
                truthkey=state.truthkey,
            )


def enrich_truth_artifact(stored: Dict[str, Any], truth_store: Any) -> Dict[str, Any]:
    """Attach agents[] from the frozen snapshot. Does not remint standing."""
    payload = {key: value for key, value in stored.items() if key != "agents"}
    try:
        state = TruthState.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return stored
    snapshot = None
    getter = getattr(truth_store, "get_trust_snapshot", None)
    if callable(getter):
        snapshot = getter(state.truthkey)
    return attach_claim_agents(dict(stored), snapshot, state.claim_type, state)


def create_app(
    *,
    flow: Optional[FlowCore] = None,
    evidence_store: Optional[Any] = None,
    observation_store: Optional[Any] = None,
    truth_store: Optional[Any] = None,
    supabase_url: Optional[str] = None,
    publishable_key: Optional[str] = None,
    verify_token: Optional[Callable[[str], str]] = None,
    schema_path: Optional[str] = None,
    generalist_client: Optional[GeneralistClient] = None,
) -> FastAPI:
    """
    Build the sidecar. Tests inject FlowCore + verify_token + truth_store.
    Production: GET {SUPABASE_URL}/auth/v1/user with SUPABASE_PUBLISHABLE_KEY.
    DATABASE_URL is optional (in-memory stores when unset); when set it is Cloud SQL
    and requires a dedicated production TruthState signing key plus a pre-applied
    schema. The API runtime never applies migrations.
    """
    if flow is None:
        signal_store, default_observation_store, default_truth_store = create_stores()
        flow = FlowCore(store=signal_store)
        if observation_store is None:
            observation_store = default_observation_store
        if truth_store is None:
            truth_store = default_truth_store
    else:
        if observation_store is None:
            from kaori_db import InMemoryObservationStore

            observation_store = InMemoryObservationStore()
        if truth_store is None:
            from kaori_db import InMemoryTruthArtifactStore

            truth_store = InMemoryTruthArtifactStore()
    url = supabase_url if supabase_url is not None else os.environ.get("SUPABASE_URL") or ""
    key = publishable_key if publishable_key is not None else os.environ.get("SUPABASE_PUBLISHABLE_KEY") or ""
    if verify_token is None:
        def verify_token(token: str) -> str:
            return agent_id_from_token(token, url, key)
    orchestrator = TruthOrchestrator(
        trust_provider=FlowTrustProvider(flow),
        schema_path=schema_path or default_schema_path(),
    )
    if generalist_client is None:
        generalist_client = GeneralistClient.from_env()
    ensure_generalist_registered(flow)

    app = FastAPI(
        title="Kaori Sidecar",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.flow = flow
    app.state.evidence_store = evidence_store or create_evidence_store()
    app.state.observation_store = observation_store
    app.state.truth_store = truth_store
    app.state.verify_token = verify_token
    app.state.orchestrator = orchestrator
    app.state.generalist_client = generalist_client
    app.state.compile_lock = TruthKeyLocks()
    app.state.validate_threads = []

    def require_agent(request: Request) -> str:
        try:
            token = parse_bearer(request.headers.get("Authorization"))
            return request.app.state.verify_token(token)
        except AuthError:
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

    @app.post("/v1/evidence")
    async def evidence_route(
        file: UploadFile = File(...),
        expected_sha256: Optional[str] = Form(default=None),
        agent_id: str = Depends(require_agent),
    ):
        try:
            evidence_ref = app.state.evidence_store.upload(
                file.file,
                filename=file.filename or "evidence",
                content_type=file.content_type,
                reporter_id=agent_id,
                expected_sha256=expected_sha256,
            )
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return evidence_ref.model_dump(mode="json", exclude_none=True)

    @app.post("/v1/compile")
    async def compile_route(
        request: Request,
        agent_id: str = Depends(require_agent),
    ):
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        # compile_observations args only — ignore votes / sign / trust snapshot on the wire
        claim_type_id = raw.get("claim_type_id")
        truth_key = raw.get("truth_key")
        raw_observations = raw.get("observations")
        if not truth_key:
            raise HTTPException(status_code=400, detail="Missing truth_key")
        if not claim_type_id:
            raise HTTPException(status_code=400, detail="Missing claim_type_id")
        if not isinstance(raw_observations, list) or not raw_observations:
            raise HTTPException(status_code=400, detail="At least one observation is required")

        try:
            claim_type = request.app.state.orchestrator.get_claim_type(claim_type_id)
        except UnknownClaimTypeError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")

        flow_core: FlowCore = request.app.state.flow
        context = reporter_context_from_flow(flow_core, agent_id)
        stamped = []
        for item in raw_observations:
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail="Invalid observation or EvidenceRef")
            stamped.append(stamp_observation(item, agent_id, context))

        try:
            observations = [Observation.model_validate(obs) for obs in stamped]
        except (ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid observation or EvidenceRef") from exc

        if any(obs.claim_type != claim_type_id for obs in observations):
            raise HTTPException(
                status_code=400,
                detail="Observation claim_type must match claim_type_id",
            )
        validate_evidence_refs(observations, claim_type)
        validate_payload_fields(observations, claim_type)
        try:
            for observation in observations:
                for evidence_ref in observation.evidence_refs:
                    app.state.evidence_store.verify(
                        evidence_ref,
                        reporter_id=agent_id,
                    )
        except EvidenceStorageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        received_at = datetime.now(timezone.utc)
        try:
            for observation in observations:
                inserted = request.app.state.observation_store.append(
                    observation,
                    truthkey=truth_key,
                    claim_type_hash=claim_type.hash(),
                    received_at=received_at,
                )
                if inserted:
                    record_observation_submitted(
                        flow_core,
                        observer_id=agent_id,
                        truthkey_id=truth_key,
                        observation_id=str(observation.observation_id),
                        observation_hash=observation.hash(),
                        claim_type_id=claim_type_id,
                    )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        observations = request.app.state.observation_store.get_for_truthkey(truth_key)
        validate_evidence_refs(observations, claim_type)
        validate_payload_fields(observations, claim_type)
        distinct_reporters = request.app.state.observation_store.count_distinct_reporters(
            truth_key
        )
        try:
            required_observations = claim_type.minimum_observations()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if distinct_reporters < required_observations:
            return JSONResponse(
                status_code=202,
                content={
                    "truthkey": truth_key,
                    "status": "PENDING",
                    "observation_progress": {
                        "received": distinct_reporters,
                        "required": required_observations,
                    },
                },
            )

        client = request.app.state.generalist_client
        if client is None and production_signing_required():
            raise HTTPException(
                status_code=503,
                detail="generalist unavailable",
            )
        if client is not None:
            timeout = generalist_timeout_seconds(claim_type)
            lock = request.app.state.compile_lock.get(truth_key)
            loop = asyncio.get_running_loop()
            finished = asyncio.Event()
            outcome: Dict[str, Any] = {}

            def signal_done() -> None:
                loop.call_soon_threadsafe(finished.set)

            def on_vote(vote) -> None:
                votes = [vote_as_compiler_record(vote)]
                ai_scores = None
                if vote.confidence is not None:
                    ai_scores = [float(vote.confidence)] * len(observations)
                with lock:
                    try:
                        outcome["artifact"] = compile_after_vote(
                            orchestrator=request.app.state.orchestrator,
                            truth_store=request.app.state.truth_store,
                            flow=flow_core,
                            observations=observations,
                            truth_key=truth_key,
                            claim_type_id=claim_type_id,
                            agent_id=agent_id,
                            votes=votes,
                            ai_scores=ai_scores,
                        )
                    except CompilationError as exc:
                        LOGGER.exception(
                            "compile after generalist vote failed for truthkey %s",
                            truth_key,
                        )
                        outcome["compile_error"] = exc
                    except (UnknownClaimTypeError, FileNotFoundError, ValidationError) as exc:
                        LOGGER.exception(
                            "compile after generalist vote failed for truthkey %s",
                            truth_key,
                        )
                        outcome["error"] = exc
                signal_done()

            def on_timeout() -> None:
                outcome["timeout"] = True
                signal_done()

            def on_error(exc: BaseException) -> None:
                outcome["error"] = exc
                signal_done()

            thread = start_validate_and_record(
                client=client,
                flow=flow_core,
                truthkey_id=truth_key,
                claim_type_id=claim_type_id,
                observations=observations,
                timeout=timeout,
                on_vote=on_vote,
                on_timeout=on_timeout,
                on_error=on_error,
            )
            request.app.state.validate_threads.append(thread)
            # Observe/record stays async internally. HTTP 200 waits for the
            # recorded vote and the persisted TruthState artifact.
            await finished.wait()
            if "artifact" in outcome:
                return JSONResponse(status_code=200, content=outcome["artifact"])
            if outcome.get("timeout"):
                raise HTTPException(
                    status_code=504,
                    detail="generalist exceeded ClaimType timeout",
                )
            if "compile_error" in outcome:
                raise HTTPException(status_code=400, detail=str(outcome["compile_error"]))
            raise HTTPException(status_code=500, detail="generalist failed")

        recorded = compiler_votes_for_truthkey(flow_core, truth_key)
        if recorded:
            with request.app.state.compile_lock.get(truth_key):
                artifact = compile_after_vote(
                    orchestrator=request.app.state.orchestrator,
                    truth_store=request.app.state.truth_store,
                    flow=flow_core,
                    observations=observations,
                    truth_key=truth_key,
                    claim_type_id=claim_type_id,
                    agent_id=agent_id,
                    votes=recorded,
                )
            return JSONResponse(status_code=200, content=artifact)

        try:
            truth_state, trust_snapshot = (
                request.app.state.orchestrator.compile_observations_with_snapshot(
                observations=observations,
                truth_key=truth_key,
                claim_type_id=claim_type_id,
                )
            )
        except UnknownClaimTypeError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        except CompilationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Invalid observation or EvidenceRef") from exc

        artifact = persist_truth_state(
            request.app.state.truth_store,
            truth_state,
            trust_snapshot,
            claim_type_id,
        )
        emit_compile_truthstate(flow_core, truth_state, observations, claim_type_id)
        return JSONResponse(status_code=200, content=artifact)

    @app.post("/v1/validate")
    async def validate_route(
        request: Request,
        agent_id: str = Depends(require_agent),
    ):
        """Authenticated ValidationSignal ingest and recompile. Not a public vote arcade."""
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        truth_key = raw.get("truth_key")
        vote = raw.get("vote")
        if not truth_key or not isinstance(truth_key, str):
            raise HTTPException(status_code=400, detail="Missing truth_key")
        if vote not in VALIDATION_VOTES:
            raise HTTPException(
                status_code=400, detail="vote must be RATIFY, REJECT, or ABSTAIN"
            )
        confidence = raw.get("confidence")
        if confidence is not None:
            try:
                confidence = float(confidence)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="Invalid confidence") from exc
            if not 0.0 <= confidence <= 1.0:
                raise HTTPException(status_code=400, detail="Invalid confidence")

        observations = request.app.state.observation_store.get_for_truthkey(truth_key)
        if not observations:
            stored = request.app.state.truth_store.get(truth_key)
            if stored is None:
                raise HTTPException(status_code=404, detail="Unknown truthkey")
            raise HTTPException(status_code=409, detail="No observations for truthkey")

        flow = request.app.state.flow
        claim_type_id = observations[0].claim_type
        ensure_agent_registered(flow, agent_id, role="observer")
        now = datetime.now(timezone.utc)
        signed = sign_validation_vote(
            ValidationVote(
                agent_id=agent_id,
                truthkey_id=truth_key,
                window_id=f"window:{truth_key}",
                vote=vote,
                confidence=confidence,
                timestamp=now,
                signature="pending",
            )
        )
        record_validation_vote(
            flow,
            agent_id=agent_id,
            truthkey_id=truth_key,
            window_id=signed.window_id,
            vote=vote,
            confidence=confidence,
            time=now,
            signature=signed.signature,
        )
        recorded = compiler_votes_for_truthkey(flow, truth_key)
        ai_scores = None
        ai_confidences = [
            float(item["confidence"])
            for item in recorded
            if item.get("confidence") is not None
            and not str(item.get("agent_id", "")).startswith(("user:", "human:"))
        ]
        if ai_confidences:
            ai_scores = [sum(ai_confidences) / len(ai_confidences)] * len(observations)
        try:
            with request.app.state.compile_lock.get(truth_key):
                artifact = compile_after_vote(
                    orchestrator=request.app.state.orchestrator,
                    truth_store=request.app.state.truth_store,
                    flow=flow,
                    observations=observations,
                    truth_key=truth_key,
                    claim_type_id=claim_type_id,
                    agent_id=agent_id,
                    votes=recorded,
                    ai_scores=ai_scores,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CompilationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(status_code=200, content=artifact)

    @app.get("/v1/standing/{agent_id}")
    def standing_route(
        agent_id: str,
        request: Request,
        _caller: str = Depends(require_agent),
    ):
        flow_core: FlowCore = request.app.state.flow
        if not agent_is_known(flow_core, agent_id):
            raise HTTPException(status_code=404, detail="Unknown agent")
        standing = flow_core.get_standing(agent_id)
        return {"standing": standing}

    @app.get("/v1/truth/{truthkey:path}")
    def truth_route(
        truthkey: str,
        request: Request,
        _caller: str = Depends(require_agent),
    ):
        stored = request.app.state.truth_store.get(truthkey)
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown truthkey")
        return enrich_truth_artifact(stored, request.app.state.truth_store)

    return app


# Used by: uvicorn kaori_api.app:app
app = create_app()
