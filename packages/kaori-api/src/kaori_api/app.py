"""
Kaori API — Pattern B sidecar.

Thin FastAPI surface Liminal can call this week:
  POST /v1/compile
  GET  /v1/standing/{agent_id}

Wraps TruthOrchestrator.compile_observations and FlowCore.get_standing.
No other HTTP routes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from kaori_api.auth import AuthError, agent_id_from_authorization
from kaori_api.orchestrator import TruthOrchestrator, UnknownClaimTypeError
from kaori_api.trust_adapter import FlowTrustProvider
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_truth.primitives.observation import Observation
from kaori_truth.primitives.truthstate import TruthState


THIS_WEEK_CLAIM_TYPE = "ocean.coral_bleaching.v1"


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


def _require_evidence_field(value: Any, field: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise HTTPException(status_code=400, detail=f"Missing EvidenceRef field: {field}")


def normalize_compile_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept Observation as it sits (evidence_refs) and the Liminal field
    observations[].evidence. Map mime → mime_type. Does not invent DTOs.
    """
    observations = body.get("observations")
    if not isinstance(observations, list):
        return body
    normalized = []
    for raw in observations:
        if not isinstance(raw, dict):
            normalized.append(raw)
            continue
        obs = dict(raw)
        if "evidence" in obs and "evidence_refs" not in obs:
            obs["evidence_refs"] = obs.pop("evidence")
        elif "evidence" in obs:
            obs.pop("evidence")
        refs = obs.get("evidence_refs")
        if isinstance(refs, list):
            mapped = []
            for ref in refs:
                if isinstance(ref, dict):
                    item = dict(ref)
                    if "mime" in item and "mime_type" not in item:
                        item["mime_type"] = item.pop("mime")
                    mapped.append(item)
                else:
                    mapped.append(ref)
            obs["evidence_refs"] = mapped
        normalized.append(obs)
    body = dict(body)
    body["observations"] = normalized
    return body


def validate_evidence_refs(observations: List[Observation]) -> None:
    """Law 4: evidence precedes verification. uri, mime, sha256 required this week."""
    if not observations:
        raise HTTPException(status_code=400, detail="At least one observation is required")
    for obs in observations:
        refs = obs.evidence_refs
        if not refs:
            raise HTTPException(status_code=400, detail="Missing EvidenceRef")
        for ref in refs:
            _require_evidence_field(getattr(ref, "uri", None), "uri")
            _require_evidence_field(getattr(ref, "mime_type", None), "mime")
            _require_evidence_field(getattr(ref, "sha256", None), "sha256")


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
        _agent_id: str = Depends(require_agent),
    ):
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        body = normalize_compile_body(raw)
        claim_type_id = body.get("claim_type_id")
        truth_key = body.get("truth_key")
        if not truth_key:
            raise HTTPException(status_code=400, detail="Missing truth_key")
        if not claim_type_id:
            raise HTTPException(status_code=400, detail="Missing claim_type_id")
        if claim_type_id != THIS_WEEK_CLAIM_TYPE:
            raise HTTPException(status_code=404, detail="Unknown claim_type_id")

        try:
            observations = [Observation.model_validate(obs) for obs in body.get("observations") or []]
        except (ValidationError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid observation or EvidenceRef") from exc

        validate_evidence_refs(observations)

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
