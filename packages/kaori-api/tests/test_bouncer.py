"""Deterministic coral runner and post-persist bouncer integration."""
from __future__ import annotations

import io
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.bouncer import (
    CORAL_CLAIM_TYPE,
    BouncerRequest,
    CoralBouncer,
    ValidationVote,
    verify_validation_vote,
)
from kaori_api.bouncer_app import create_bouncer_app
from kaori_api.bouncer_client import BouncerClient
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.observation import Observation
from PIL import Image

AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
TRUTHKEY = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
CORAL_YAML = Path("packages/kaori-spec/schemas/ocean/coral_bleaching_v1.yaml")
SIGNING_KEY = b"unit-test-bouncer-key"


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (1, 1), color=(0, 128, 255)).save(stream, format="PNG")
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
            {
                "uri": "gs://kaori-evidence/coral1.png",
                "sha256": "a" * 64,
                "mime_type": "image/png",
            },
            {
                "uri": "gs://kaori-evidence/coral2.png",
                "sha256": "b" * 64,
                "mime_type": "image/png",
            },
        ],
    }


def compile_body(observation: dict | None = None) -> dict:
    raw = deepcopy(observation or raw_observation())
    raw.pop("reporter_id", None)
    raw.pop("reporter_context", None)
    return {
        "truth_key": TRUTHKEY,
        "claim_type_id": CORAL_CLAIM_TYPE,
        "observations": [raw],
    }


def bouncer_request(observation: dict | None = None, truthkey: str = TRUTHKEY) -> BouncerRequest:
    return BouncerRequest(
        truthkey_id=truthkey,
        claim_type_id=CORAL_CLAIM_TYPE,
        observations=[Observation.model_validate(observation or raw_observation())],
    )


def runner(loader=None) -> CoralBouncer:
    return CoralBouncer(
        schema_path=str(CORAL_YAML),
        evidence_loader=loader or (lambda _ref: png_bytes()),
        signing_key=SIGNING_KEY,
    )


class LocalBouncerClient:
    """Test transport that still executes the separate runner contract."""

    def __init__(self, coral_runner: CoralBouncer):
        self.runner = coral_runner

    def validate(self, *, truthkey_id, claim_type_id, observations) -> ValidationVote:
        return self.runner.validate(
            BouncerRequest(
                truthkey_id=truthkey_id,
                claim_type_id=claim_type_id,
                observations=observations,
            ),
            timestamp=datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc),
        )


def test_pass_ratifies_with_signed_flow_validation_signal():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            bouncer_client=LocalBouncerClient(runner()),
        )
    )

    response = client.post("/v1/compile", json=compile_body(), headers=auth_header())

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_HUMAN_REVIEW"
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].agent_id == "ai:bouncer_v1"
    assert votes[0].payload["vote"] == "RATIFY"
    assert votes[0].payload["window_id"] == f"window:{TRUTHKEY}"
    assert votes[0].payload["timestamp"] == "2026-01-07T12:30:00Z"
    assert votes[0].signature


def test_fail_rejects_and_truth_state_remains_pending_human_review():
    observation = raw_observation()
    observation["evidence_refs"][1]["sha256"] = observation["evidence_refs"][0]["sha256"]
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            bouncer_client=LocalBouncerClient(runner()),
        )
    )

    response = client.post(
        "/v1/compile",
        json=compile_body(observation),
        headers=auth_header(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PENDING_HUMAN_REVIEW"
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].payload["vote"] == "REJECT"


def test_runner_signature_covers_flow_spec_payload():
    timestamp = datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc)
    vote = runner().validate(bouncer_request(), timestamp=timestamp)

    assert vote.model_dump(mode="json", exclude_none=True).keys() == {
        "agent_id",
        "truthkey_id",
        "window_id",
        "vote",
        "timestamp",
        "signature",
    }
    assert vote.agent_id == "ai:bouncer_v1"
    assert vote.vote == "RATIFY"
    assert verify_validation_vote(vote, SIGNING_KEY)
    assert not verify_validation_vote(vote.model_copy(update={"vote": "REJECT"}), SIGNING_KEY)


def test_api_client_rejects_a_tampered_bouncer_vote():
    vote = runner().validate(bouncer_request())
    client = BouncerClient(
        "https://kaori-bouncer.example",
        token_provider=lambda _audience: "token",
        signing_key=SIGNING_KEY,
    )

    client._validate_vote(vote, TRUTHKEY)
    with pytest.raises(ValueError, match="invalid signature"):
        client._validate_vote(vote.model_copy(update={"vote": "REJECT"}), TRUTHKEY)


def test_private_runner_endpoint_returns_only_validation_signal_fields():
    client = TestClient(create_bouncer_app(runner()))

    response = client.post("/", json=bouncer_request().model_dump(mode="json"))

    assert response.status_code == 200, response.text
    assert response.json().keys() == {
        "agent_id",
        "truthkey_id",
        "window_id",
        "vote",
        "timestamp",
        "signature",
    }


def test_other_claim_type_does_not_invoke_bouncer():
    class UnexpectedBouncerClient:
        def validate(self, **_kwargs):
            raise AssertionError("non-coral claim must not invoke bouncer")

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


@pytest.mark.parametrize(
    ("mutation", "truthkey", "loader"),
    [
        (
            lambda observation: observation.update(
                {"evidence_refs": observation["evidence_refs"][:1]}
            ),
            TRUTHKEY,
            None,
        ),
        (lambda _observation: None, TRUTHKEY, lambda _ref: b""),
        (
            lambda observation: observation["evidence_refs"][1].update(
                {"sha256": observation["evidence_refs"][0]["sha256"]}
            ),
            TRUTHKEY,
            None,
        ),
        (
            lambda observation: observation.update({"geo": {"lat": 91.0, "lon": 115.092}}),
            TRUTHKEY,
            None,
        ),
        (
            lambda _observation: None,
            TRUTHKEY.replace(":underwater:", ":surface:"),
            None,
        ),
    ],
    ids=[
        "evidence-present",
        "evidence-quality-min",
        "duplicate-hash",
        "geolocation-plausibility",
        "depth-consistency",
    ],
)
def test_each_configured_check_can_reject(mutation, truthkey, loader):
    observation = raw_observation()
    mutation(observation)

    vote = runner(loader).validate(bouncer_request(observation, truthkey))

    assert vote.vote == "REJECT"
    assert verify_validation_vote(vote, SIGNING_KEY)
