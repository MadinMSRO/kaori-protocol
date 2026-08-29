"""CPU CLIP generalist and post-persist vote integration."""
from __future__ import annotations

import io
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.bouncer import (
    CORAL_CLAIM_TYPE,
    ClipGeneralistValidator,
    ValidationVote,
    ValidatorRequest,
    verify_validation_vote,
)
from kaori_api.bouncer_app import create_bouncer_app
from kaori_api.bouncer_client import BouncerClient
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.evidence import EvidenceRef


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
TRUTHKEY = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
CORAL_YAML = Path("packages/kaori-spec/schemas/ocean/coral_bleaching_v1.yaml")
SIGNING_KEY = b"unit-test-generalist-key"


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color=(0, 128, 255)).save(stream, format="PNG")
    return stream.getvalue()


def raw_observation() -> dict:
    return {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": CORAL_CLAIM_TYPE,
        "reported_at": "2026-01-07T12:00:00Z",
        "reporter_id": AGENT_ID,
        "reporter_context": {
            "standing": "bronze",
            "trust_score": 0.2,
            "source_type": "human",
        },
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {"depth_meters": 8.0, "bleaching_percentage": 40},
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/coral1.png", "sha256": "a" * 64},
            {"uri": "gs://kaori-evidence/coral2.png", "sha256": "b" * 64},
        ],
    }


def compile_body() -> dict:
    observation = deepcopy(raw_observation())
    observation.pop("reporter_id")
    observation.pop("reporter_context")
    return {
        "truth_key": TRUTHKEY,
        "claim_type_id": CORAL_CLAIM_TYPE,
        "observations": [observation],
    }


def validator_request() -> ValidatorRequest:
    return ValidatorRequest(
        truthkey_id=TRUTHKEY,
        claim_type_id=CORAL_CLAIM_TYPE,
        evidence_refs=[
            EvidenceRef(uri="gs://kaori-evidence/coral1.png", sha256="a" * 64),
            EvidenceRef(uri="gs://kaori-evidence/coral2.png", sha256="b" * 64),
        ],
    )


class FakeClipGeneralist:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def score(self, images, *, context, engine):
        self.calls.append(
            {
                "count": len(images),
                "context": context,
                "engine": engine,
            }
        )
        return list(self.scores)


def validator(scores) -> ClipGeneralistValidator:
    return ClipGeneralistValidator(
        schema_path=str(CORAL_YAML),
        evidence_loader=lambda _ref: png_bytes(),
        model=FakeClipGeneralist(scores),
        signing_key=SIGNING_KEY,
    )


class LocalBouncerClient:
    """Test transport that executes the separate generalist service contract."""

    def __init__(self, clip_validator: ClipGeneralistValidator):
        self.validator = clip_validator

    def validate(self, *, truthkey_id, claim_type_id, observations) -> ValidationVote:
        return self.validator.validate(
            ValidatorRequest(
                truthkey_id=truthkey_id,
                claim_type_id=claim_type_id,
                evidence_refs=[
                    ref
                    for observation in observations
                    for ref in observation.evidence_refs
                ],
            ),
            timestamp=datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc),
        )


def test_relevant_coral_evidence_ratifies_as_generalist():
    clip = FakeClipGeneralist([0.94, 0.90])
    generalist = ClipGeneralistValidator(
        schema_path=str(CORAL_YAML),
        evidence_loader=lambda _ref: png_bytes(),
        model=clip,
        signing_key=SIGNING_KEY,
    )
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            bouncer_client=LocalBouncerClient(generalist),
        )
    )

    response = client.post("/v1/compile", json=compile_body(), headers=auth_header())

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert clip.calls == [
        {
            "count": 2,
            "context": "Coral reef health assessment in tropical waters",
            "engine": "clip_v1",
        }
    ]
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].agent_id == "ai:generalist_v1"
    assert votes[0].payload["vote"] == "RATIFY"
    assert votes[0].payload["confidence"] == pytest.approx(0.92)
    assert votes[0].payload["window_id"] == f"window:{TRUTHKEY}"
    assert votes[0].payload["timestamp"] == "2026-01-07T12:30:00Z"
    assert votes[0].signature


def test_unrelated_image_rejects_and_status_stays_pending_human_review():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            bouncer_client=LocalBouncerClient(validator([0.12, 0.18])),
        )
    )

    response = client.post("/v1/compile", json=compile_body(), headers=auth_header())

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_HUMAN_REVIEW"
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].agent_id == "ai:generalist_v1"
    assert votes[0].payload["vote"] == "REJECT"
    assert votes[0].payload["confidence"] == pytest.approx(0.15)


def test_generalist_signature_covers_flow_spec_payload():
    vote = validator([0.9, 0.9]).validate(
        validator_request(),
        timestamp=datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc),
    )

    assert vote.model_dump(mode="json", exclude_none=True).keys() == {
        "agent_id",
        "truthkey_id",
        "window_id",
        "vote",
        "confidence",
        "timestamp",
        "signature",
    }
    assert vote.agent_id == "ai:generalist_v1"
    assert verify_validation_vote(vote, SIGNING_KEY)
    assert not verify_validation_vote(vote.model_copy(update={"vote": "REJECT"}), SIGNING_KEY)


def test_api_client_rejects_wrong_signer_and_tampered_vote():
    vote = validator([0.9, 0.9]).validate(validator_request())
    client = BouncerClient(
        "https://kaori-bouncer.example",
        token_provider=lambda _audience: "token",
        signing_key=SIGNING_KEY,
    )

    client._validate_vote(vote, TRUTHKEY)
    with pytest.raises(ValueError, match="unexpected agent_id"):
        client._validate_vote(
            vote.model_copy(update={"agent_id": "ai:coral_specialist_v1"}),
            TRUTHKEY,
        )
    with pytest.raises(ValueError, match="invalid signature"):
        client._validate_vote(vote.model_copy(update={"vote": "REJECT"}), TRUTHKEY)


def test_private_endpoint_accepts_no_submission_rule_payload():
    request = validator_request()
    assert set(ValidatorRequest.model_fields) == {
        "truthkey_id",
        "claim_type_id",
        "evidence_refs",
    }
    client = TestClient(create_bouncer_app(validator([0.9, 0.9])))

    response = client.post("/", json=request.model_dump(mode="json"))

    assert response.status_code == 200, response.text
    assert response.json()["agent_id"] == "ai:generalist_v1"
    assert "observations" not in response.json()
    assert "checks" not in response.json()


def test_other_claim_type_does_not_invoke_first_slice_generalist():
    class UnexpectedBouncerClient:
        def validate(self, **_kwargs):
            raise AssertionError("non-coral claim must not invoke first-slice validator")

    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            bouncer_client=UnexpectedBouncerClient(),
        )
    )
    claim_type = "earth.coastal_erosion.v1"
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": "earth:coastal_erosion:h3:abc:surface:2026-01-07T00:00Z",
            "claim_type_id": claim_type,
            "observations": [
                {
                    "observation_id": "22222222-2222-2222-2222-222222222222",
                    "claim_type": claim_type,
                    "reported_at": "2026-01-07T12:00:00Z",
                    "geo": {"lat": -8.3405, "lon": 115.092},
                    "payload": {
                        "recession_m": 1.5,
                        "scarp_present": True,
                        "stake_readings": [0.1, 0.2],
                    },
                    "evidence_refs": [
                        {"uri": "gs://kaori-evidence/a.jpg", "sha256": "a" * 64}
                    ],
                }
            ],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200, response.text
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
