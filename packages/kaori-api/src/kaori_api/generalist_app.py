"""IAM-protected Cloud Run entrypoint for the CPU CLIP generalist."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import base64

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from kaori_api.generalist import (
    ClipGeneralistValidator,
    ValidationVote,
    ValidatorRequest,
    log_validation_vote,
)


class ReadRequest(BaseModel):
    """A blind reading request: the claim type and the photo exactly as a human validator sees it."""

    claim_type_id: str
    image_b64: str


def default_schema_root() -> str:
    return str(Path(os.environ.get("KAORI_SCHEMA_PATH", "packages/kaori-spec/schemas")))


def create_generalist_app(validator: Optional[ClipGeneralistValidator] = None) -> FastAPI:
    validator = validator or ClipGeneralistValidator(schema_root=default_schema_root())
    application = FastAPI(
        title="Kaori Generalist",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.validator = validator

    @application.on_event("startup")
    def warm_model() -> None:
        # load CLIP before the first photo arrives (a cold load can outlast a request timeout)
        warm = getattr(application.state.validator.model, "warm", None)
        if warm is not None and os.environ.get("KAORI_GENERALIST_WARM", "1") == "1":
            warm()

    # Cloud Run IAM authenticates this private endpoint before the request reaches ASGI.
    @application.post("/", response_model=ValidationVote, response_model_exclude_none=True)
    def validate(request: ValidatorRequest) -> ValidationVote:
        try:
            vote = application.state.validator.validate(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        log_validation_vote(vote, source="kaori-generalist")
        return vote

    # A blind reading of one photo (Antalya): the same image a human validator sees, EXIF removed.
    @application.post("/read")
    def read(request: ReadRequest) -> dict:
        try:
            image = base64.b64decode(request.image_b64, validate=True)
            return application.state.validator.read(request.claim_type_id, image)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return application


app = create_generalist_app()
