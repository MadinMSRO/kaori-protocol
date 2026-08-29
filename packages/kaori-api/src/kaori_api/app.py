"""
Kaori API — Pattern B sidecar.

Thin FastAPI surface Liminal can call this week:
  POST /v1/compile
  GET  /v1/standing/{agent_id}
  GET  /v1/truth/{truthkey}

Wraps TruthOrchestrator.compile_observations and FlowCore.get_standing.
Compile 200 persists TruthState to kaori.truth_states then emits
FlowCore.emit_truthstate. CLIP validation is queued after persistence for the
separate private bouncer service. No other HTTP routes. Wire field names match
Open Core primitives. Compiler stays pure.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.agent import Agent
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthstate import TruthState, TruthStatus
from pydantic import ValidationError

from kaori_api.auth import AuthError, agent_id_from_token, parse_bearer
from kaori_api.bouncer_client import (
    BouncerClient,
    validate_persisted_truth_state,
)
from kaori_api.orchestrator import TruthOrchestrator, UnknownClaimTypeError
from kaori_api.trust_adapter import FlowTrustProvider
from kaori_api.validation import (
    agent_is_known,
    ensure_generalist_registered,
)

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


def create_stores() -> Tuple[Any, Any]:
    """Postgres stores when DATABASE_URL is set; in-memory otherwise."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from kaori_db import PostgresSignalStore, PostgresTruthStateStore

        signals = PostgresSignalStore(database_url)
        signals.ensure_schema()
        return signals, PostgresTruthStateStore(engine=signals.engine)
    from kaori_db import InMemoryTruthStateStore

    return InMemorySignalStore(), InMemoryTruthStateStore()


def create_store():
    """PostgresSignalStore when DATABASE_URL is set; in-memory otherwise."""
    signals, _ = create_stores()
    return signals


def create_flow(store=None) -> FlowCore:
    return FlowCore(store=store or create_store())


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


def validate_evidence_refs(observations: List[Observation]) -> None:
    """Law 4. EvidenceRef required fields as they sit: uri, sha256."""
    if not observations:
        raise HTTPException(status_code=400, detail="At least one observation is required")
    for obs in observations:
        refs = obs.evidence_refs
        if not refs:
            raise HTTPException(status_code=400, detail="Missing evidence_refs")
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


def persist_truth_state(truth_store: Any, state: TruthState) -> dict:
    """Upsert full TruthState.model_dump (including evidence_refs) on truthkey."""
    artifact = state.model_dump(mode="json")
    truth_store.upsert(
        truthkey=state.truthkey,
        artifact=artifact,
        compiled_at=state.compile_inputs.compile_time,
    )
    return artifact


def emit_compile_truthstate(flow: FlowCore, state: TruthState, agent_id: str) -> None:
    """Standing moves from TRUTHSTATE_EMITTED history, not register_agent."""
    status = state.status.value
    outcome = "correct" if state.status == TruthStatus.VERIFIED_TRUE else "unknown"
    flow.emit_truthstate(
        truthkey=state.truthkey,
        status=status,
        confidence=state.confidence,
        contributors=[agent_id],
        outcome=outcome,
    )


def create_app(
    *,
    flow: Optional[FlowCore] = None,
    truth_store: Optional[Any] = None,
    supabase_url: Optional[str] = None,
    publishable_key: Optional[str] = None,
    verify_token: Optional[Callable[[str], str]] = None,
    schema_path: Optional[str] = None,
    bouncer_client: Optional[BouncerClient] = None,
) -> FastAPI:
    """
    Build the sidecar. Tests inject FlowCore + verify_token + truth_store.
    Production: GET {SUPABASE_URL}/auth/v1/user with SUPABASE_PUBLISHABLE_KEY.
    DATABASE_URL is optional (in-memory stores when unset); when set it is Cloud SQL.
    """
    if flow is None:
        signal_store, default_truth_store = create_stores()
        flow = FlowCore(store=signal_store)
        if truth_store is None:
            truth_store = default_truth_store
    elif truth_store is None:
        from kaori_db import InMemoryTruthStateStore

        truth_store = InMemoryTruthStateStore()
    url = supabase_url if supabase_url is not None else os.environ.get("SUPABASE_URL") or ""
    key = publishable_key if publishable_key is not None else os.environ.get("SUPABASE_PUBLISHABLE_KEY") or ""
    if verify_token is None:
        def verify_token(token: str) -> str:
            return agent_id_from_token(token, url, key)
    orchestrator = TruthOrchestrator(
        trust_provider=FlowTrustProvider(flow),
        schema_path=schema_path or default_schema_path(),
    )
    if bouncer_client is None:
        bouncer_client = BouncerClient.from_env()
    ensure_generalist_registered(flow)

    app = FastAPI(
        title="Kaori Sidecar",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(LIMINAL_ORIGINS),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.flow = flow
    app.state.truth_store = truth_store
    app.state.verify_token = verify_token
    app.state.orchestrator = orchestrator
    app.state.bouncer_client = bouncer_client

    def require_agent(request: Request) -> str:
        try:
            token = parse_bearer(request.headers.get("Authorization"))
            return request.app.state.verify_token(token)
        except AuthError:
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

    @app.post("/v1/compile")
    async def compile_route(
        request: Request,
        background_tasks: BackgroundTasks,
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

        validate_evidence_refs(observations)
        validate_payload_fields(observations, claim_type)

        try:
            truth_state: TruthState = request.app.state.orchestrator.compile_observations(
                observations=observations,
                truth_key=truth_key,
                claim_type_id=claim_type_id,
            )
        except UnknownClaimTypeError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Invalid observation or EvidenceRef") from exc

        artifact = persist_truth_state(request.app.state.truth_store, truth_state)
        emit_compile_truthstate(flow_core, truth_state, agent_id)
        client = request.app.state.bouncer_client
        if client is not None:
            background_tasks.add_task(
                validate_persisted_truth_state,
                client=client,
                flow=flow_core,
                truthkey_id=truth_state.truthkey,
                claim_type_id=claim_type_id,
                observations=observations,
            )
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
        return stored

    return app


# Used by: uvicorn kaori_api.app:app
app = create_app()
