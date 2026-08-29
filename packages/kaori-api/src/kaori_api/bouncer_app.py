"""IAM-protected Cloud Run entrypoint for the deterministic coral bouncer."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException

from kaori_api.bouncer import BouncerRequest, CoralBouncer, ValidationVote


def default_coral_schema_path() -> str:
    root = os.environ.get("KAORI_SCHEMA_PATH", "packages/kaori-spec/schemas")
    return str(Path(root) / "ocean" / "coral_bleaching_v1.yaml")


def create_bouncer_app(runner: Optional[CoralBouncer] = None) -> FastAPI:
    runner = runner or CoralBouncer(schema_path=default_coral_schema_path())
    application = FastAPI(
        title="Kaori Bouncer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.runner = runner

    # Cloud Run IAM authenticates this private endpoint before the request reaches ASGI.
    @application.post("/", response_model=ValidationVote, response_model_exclude_none=True)
    def validate(request: BouncerRequest) -> ValidationVote:
        try:
            return application.state.runner.validate(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return application


app = create_bouncer_app()
