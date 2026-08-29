"""
Kaori API — Pattern B sidecar.

Thin FastAPI surface Liminal can call this week:
  POST /v1/compile
  GET  /v1/standing/{agent_id}

Wraps TruthOrchestrator.compile_observations and FlowCore.get_standing.
No other HTTP routes. Wire field names match Open Core primitives.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from kaori_api.auth import AuthError, agent_id_from_authorization
from kaori_api.orchestrator import TruthOrchestrator, UnknownClaimTypeError
from kaori_api.trust_adapter import FlowTrustProvider
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.agent import Agent
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthstate import TruthState


THIS_WEEK_CLAIM_TYPE = "ocean.coral_bleaching.v1"
LIMINAL_ORIGIN = "https://kind-keepsake-kingdom.lovable.app"
CORAL_PAYLOAD_FIELDS = ("depth_meters", "bleaching_percentage")
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


def create_store():
    """PostgresSignalStore when DATABASE_URL is set; in-memory otherwise."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        from kaori_db import PostgresSignalStore

        store = PostgresSignalStore(database_url)
        store.ensure_schema()
        return store
    return InMemorySignalStore()


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


def validate_coral_payload(observations: List[Observation]) -> None:
    """This week ocean.coral_bleaching.v1 payload is {depth_meters, bleaching_percentage}."""
    for obs in observations:
        payload = obs.payload or {}
        for field in CORAL_PAYLOAD_FIELDS:
            if field not in payload or payload[field] is None:
                raise HTTPException(status_code=400, detail=f"Missing payload field: {field}")


def agent_is_known(flow: FlowCore, agent_id: str) -> bool:
    if agent_id in flow.get_all_standings():
        return True
    return bool(flow.store.get_for_agent(agent_id))


def create_app(
    *,
    flow: Optional[FlowCore] = None,
    jwt_secret: Optional[str] = None,
    schema_path: Optional[str] = None,
) -> FastAPI:
    """
    Build the sidecar. Tests inject FlowCore + jwt_secret.
    Production: DATABASE_URL selects PostgresSignalStore; SUPABASE_JWT_SECRET verifies Bearer.
    """
    flow = flow or create_flow()
    secret = jwt_secret
    if secret is None:
        secret = os.environ.get("SUPABASE_JWT_SECRET") or os.environ.get("KAORI_JWT_SECRET") or ""
    orchestrator = TruthOrchestrator(
        trust_provider=FlowTrustProvider(flow),
        schema_path=schema_path or default_schema_path(),
    )

    app = FastAPI(
        title="Kaori Sidecar",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[LIMINAL_ORIGIN],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.flow = flow
    app.state.jwt_secret = secret
    app.state.orchestrator = orchestrator

    def require_agent(request: Request) -> str:
        try:
            return agent_id_from_authorization(
                request.headers.get("Authorization"),
                request.app.state.jwt_secret,
            )
        except AuthError:
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

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
        if claim_type_id != THIS_WEEK_CLAIM_TYPE:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")
        if not isinstance(raw_observations, list) or not raw_observations:
            raise HTTPException(status_code=400, detail="At least one observation is required")

        context = reporter_context_from_flow(request.app.state.flow, agent_id)
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
        validate_coral_payload(observations)

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

        return JSONResponse(status_code=200, content=truth_state.model_dump(mode="json"))

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

    return app


# Used by: uvicorn kaori_api.app:app
app = create_app()
