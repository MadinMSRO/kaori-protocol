"""IAM-protected Cloud Run entrypoint for the CPU CLIP generalist."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException

from kaori_api.bouncer import ClipGeneralistValidator, ValidationVote, ValidatorRequest


def default_schema_root() -> str:
    return str(Path(os.environ.get("KAORI_SCHEMA_PATH", "packages/kaori-spec/schemas")))


def create_bouncer_app(validator: Optional[ClipGeneralistValidator] = None) -> FastAPI:
    validator = validator or ClipGeneralistValidator(schema_root=default_schema_root())
    application = FastAPI(
        title="Kaori Bouncer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.validator = validator

    # Cloud Run IAM authenticates this private endpoint before the request reaches ASGI.
    @application.post("/", response_model=ValidationVote, response_model_exclude_none=True)
    def validate(request: ValidatorRequest) -> ValidationVote:
        try:
            return application.state.validator.validate(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return application


app = create_bouncer_app()
