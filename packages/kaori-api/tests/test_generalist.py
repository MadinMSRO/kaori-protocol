"""CPU CLIP generalist and post-persist vote integration."""
from __future__ import annotations

import io
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.generalist import (
    ClipGeneralistValidator,
    EvidenceContentLoader,
    ValidationVote,
    ValidatorRequest,
    verify_validation_vote,
)
from kaori_api.generalist_app import create_generalist_app
from kaori_api.generalist_client import GeneralistClient
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.primitives.evidence import EvidenceRef
from PIL import Image

AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
CORAL_CLAIM_TYPE = "ocean.coral_bleaching.v1"
TRUTHKEY = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
CORAL_YAML = Path("packages/kaori-spec/schemas/ocean/coral_bleaching_v1.yaml")
SCHEMA_ROOT = CORAL_YAML.parents[1]
SIGNING_KEY = b"unit-test-generalist-key"
PRODUCT_CLAIM_TYPES = [
    "earth.coastal_erosion.v1",
    "earth.infrastructure.v1",
    "earth.vegetation.v1",
    "ocean.coral_bleaching.v1",
    "ocean.reef_recovery.v1",
    "ocean.sea_temperature.v1",
    "ocean.vessel_anomaly.v1",
    "space.debris_track.v1",
    "space.light_pollution.v1",
    "space.satellite_pass.v1",
]


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.content


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
            {
                "uri": "https://project.supabase.co/storage/v1/object/public/lm-012/coral1.png",
                "sha256": "a" * 64,
            },
            {
                "uri": "https://project.supabase.co/storage/v1/object/public/lm-012/coral2.png",
                "sha256": "b" * 64,
            },
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
            EvidenceRef(
                uri="https://project.supabase.co/storage/v1/object/public/lm-012/coral1.png",
                sha256="a" * 64,
            ),
            EvidenceRef(
                uri="https://project.supabase.co/storage/v1/object/public/lm-012/coral2.png",
                sha256="b" * 64,
            ),
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
        schema_root=str(SCHEMA_ROOT),
        evidence_loader=lambda _ref: png_bytes(),
        model=FakeClipGeneralist(scores),
        signing_key=SIGNING_KEY,
    )


@pytest.mark.parametrize(
    "uri",
    [
        "https://project.supabase.co/storage/v1/object/public/lm-012/photo.jpg",
        "http://project.supabase.co/storage/v1/object/public/lm-012/photo.jpg",
    ],
)
def test_evidence_loader_fetches_http_urls_directly(monkeypatch, uri):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(b"supabase-photo")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    content = EvidenceContentLoader(timeout=4.0)(
        EvidenceRef(uri=uri, sha256="a" * 64)
    )

    assert content == b"supabase-photo"
    assert requests[0][0].full_url == uri
    assert requests[0][0].get_header("User-agent") == "kaori-generalist/1"
    assert requests[0][1] == 4.0


def test_evidence_loader_preserves_authenticated_gcs_download(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if request.full_url.startswith("http://metadata.google.internal"):
            return FakeResponse(b'{"access_token":"gcs-token"}')
        return FakeResponse(b"gcs-photo")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    content = EvidenceContentLoader(timeout=4.0)(
        EvidenceRef(uri="gs://kaori-evidence/path/photo.jpg", sha256="a" * 64)
    )

    assert content == b"gcs-photo"
    assert requests[1][0].full_url.endswith(
        "/download/storage/v1/b/kaori-evidence/o/path%2Fphoto.jpg?alt=media"
    )
    assert requests[1][0].get_header("Authorization") == "Bearer gcs-token"


class LocalGeneralistClient:
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
        schema_root=str(SCHEMA_ROOT),
        evidence_loader=lambda _ref: png_bytes(),
        model=clip,
        signing_key=SIGNING_KEY,
    )
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=LocalGeneralistClient(generalist),
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
            generalist_client=LocalGeneralistClient(validator([0.12, 0.18])),
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
    client = GeneralistClient(
        "https://kaori-generalist.example",
        token_provider=lambda _audience: "token",
        signing_key=SIGNING_KEY,
    )

    client._validate_vote(vote, TRUTHKEY)
    with pytest.raises(ValueError, match="unexpected agent_id"):
        client._validate_vote(
            vote.model_copy(update={"agent_id": "ai:other_validator"}),
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
    client = TestClient(create_generalist_app(validator([0.9, 0.9])))

    response = client.post("/", json=request.model_dump(mode="json"))

    assert response.status_code == 200, response.text
    assert response.json()["agent_id"] == "ai:generalist_v1"
    assert "observations" not in response.json()
    assert "checks" not in response.json()


def test_all_product_claim_types_load_their_generalist_config():
    generalist = validator([0.9, 0.9])
    request = validator_request()

    votes = [
        generalist.validate(request.model_copy(update={"claim_type_id": claim_type_id}))
        for claim_type_id in PRODUCT_CLAIM_TYPES
    ]

    assert {vote.agent_id for vote in votes} == {"ai:generalist_v1"}
    assert {vote.vote for vote in votes} == {"RATIFY"}


def test_prompt_context_falls_back_to_claim_topic_display():
    context, engine, threshold = ClipGeneralistValidator._generalist_settings(
        {
            "topic": "coastal_erosion",
            "ai_validation_routing": {"generalist": {"engine": "generalist_v1"}},
            "evidence_similarity": {
                "embedding": {
                    "enabled": True,
                    "engine": "clip_v1",
                    "similarity_threshold": 0.85,
                }
            },
        }
    )

    assert context == "coastal erosion"
    assert engine == "clip_v1"
    assert threshold == pytest.approx(0.85)


def test_non_coral_compile_gets_post_persist_generalist_vote():
    clip = FakeClipGeneralist([0.91])
    generalist = ClipGeneralistValidator(
        schema_root=str(SCHEMA_ROOT),
        evidence_loader=lambda _ref: png_bytes(),
        model=clip,
        signing_key=SIGNING_KEY,
    )

    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=LocalGeneralistClient(generalist),
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
    assert clip.calls == [
        {
            "count": 1,
            "context": "Coastal erosion monitoring",
            "engine": "clip_v1",
        }
    ]
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].agent_id == "ai:generalist_v1"
    assert votes[0].object_id == response.json()["truthkey"]
    assert votes[0].payload["vote"] == "RATIFY"
