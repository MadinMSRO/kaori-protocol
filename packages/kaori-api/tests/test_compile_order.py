"""Compile order: observation → validation vote → compilation. No new routes."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.generalist import ValidationVote
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.compiler import compile_truth_state as real_compile
from kaori_truth.primitives.truthstate import TruthStatus

AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
SRC_ROOTS = [
    Path("packages/kaori-api/src"),
    Path("packages/kaori-truth/src"),
]


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def coral_body() -> dict:
    return {
        "truth_key": "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
        "claim_type_id": "ocean.coral_bleaching.v1",
        "observations": [
            {
                "observation_id": "11111111-1111-1111-1111-111111111111",
                "claim_type": "ocean.coral_bleaching.v1",
                "reported_at": "2026-01-07T12:00:00Z",
                "geo": {"lat": -8.3405, "lon": 115.0920},
                "payload": {"depth_meters": 8.0, "bleaching_percentage": 40},
                "evidence_refs": [
                    {"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64},
                    {"uri": "gs://kaori-evidence/coral2.jpg", "sha256": "b" * 64},
                ],
            }
        ],
    }


def vessel_body() -> dict:
    return {
        "truth_key": "ocean:vessel_anomaly:h3:abc:surface:2026-01-07T12:00Z",
        "claim_type_id": "ocean.vessel_anomaly.v1",
        "observations": [
            {
                "observation_id": "11111111-1111-1111-1111-111111111111",
                "claim_type": "ocean.vessel_anomaly.v1",
                "reported_at": "2026-01-07T12:00:00Z",
                "geo": {"lat": -8.3405, "lon": 115.0920},
                "payload": {
                    "observation_duration_min": 15,
                    "vessels": [{"id": "v1"}],
                },
                "evidence_refs": [
                    {"uri": "gs://kaori-evidence/a.jpg", "sha256": "a" * 64},
                    {"uri": "gs://kaori-evidence/b.jpg", "sha256": "b" * 64},
                ],
            }
        ],
    }


class FakeGeneralistClient:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.calls = []

    def validate(self, *, truthkey_id, claim_type_id, observations):
        self.calls.append(
            {
                "truthkey_id": truthkey_id,
                "claim_type_id": claim_type_id,
                "evidence": [
                    ref.uri
                    for observation in observations
                    for ref in observation.evidence_refs
                ],
            }
        )
        if self.error:
            raise self.error
        return ValidationVote(
            agent_id="ai:generalist_v1",
            truthkey_id=truthkey_id,
            window_id=f"window:{truthkey_id}",
            vote="RATIFY",
            confidence=0.91,
            timestamp=datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc),
            signature="fake-generalist-sig",
        )


def test_only_three_http_routes():
    application = create_app(
        flow=FlowCore(store=InMemorySignalStore()),
        verify_token=verify_token,
    )
    paths = {getattr(route, "path", None) for route in application.router.routes}
    paths.discard(None)
    assert paths == {
        "/v1/compile",
        "/v1/standing/{agent_id}",
        "/v1/truth/{truthkey:path}",
    }


def test_compile_invokes_validator_before_compile_truth_state(monkeypatch):
    fake = FakeGeneralistClient()
    order = []

    def wrapped(*args, **kwargs):
        order.append("compile_truth_state")
        return real_compile(*args, **kwargs)

    monkeypatch.setattr("kaori_api.orchestrator.compile_truth_state", wrapped)

    original_validate = fake.validate

    def recording_validate(**kwargs):
        order.append("validate")
        return original_validate(**kwargs)

    fake.validate = recording_validate

    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=fake,
        )
    )
    response = client.post("/v1/compile", json=coral_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    assert order == ["validate", "compile_truth_state"]
    assert fake.calls[0]["truthkey_id"] == coral_body()["truth_key"]
    assert fake.calls[0]["claim_type_id"] == "ocean.coral_bleaching.v1"
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].payload["vote"] == "RATIFY"
    assert response.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert "VALIDATION" not in {s.value for s in TruthStatus}


def test_generalist_error_still_compiles_200(caplog):
    fake = FakeGeneralistClient(error=RuntimeError("generalist down"))
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=fake,
        )
    )
    response = client.post("/v1/compile", json=coral_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    assert response.json()["status"] != "VALIDATION"
    assert "kaori-generalist failed" in caplog.text


def test_vessel_not_pending_human_review_from_critical_alone():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(create_app(flow=flow, verify_token=verify_token))
    vessel = client.post("/v1/compile", json=vessel_body(), headers=auth_header())
    coral = client.post("/v1/compile", json=coral_body(), headers=auth_header())
    assert vessel.status_code == 200, vessel.text
    assert coral.status_code == 200, coral.text
    assert vessel.json()["status"] != "PENDING_HUMAN_REVIEW"
    assert coral.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert vessel.json()["status"] != "VALIDATION"
    assert coral.json()["status"] != "VALIDATION"


def test_no_claim_type_id_branches_in_production():
    """Production code must not fork on coral, vessel, or any claim_type id."""
    forbidden_ids = {
        "ocean.coral_bleaching.v1",
        "ocean.vessel_anomaly.v1",
        "earth.coastal_erosion.v1",
        "earth.flood.v1",
    }
    violations = []
    for root in SRC_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                literals = [
                    n.value
                    for n in node.comparators
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                ]
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                    literals.append(node.left.value)
                for literal in literals:
                    if literal in forbidden_ids:
                        violations.append(f"{path}:{node.lineno} compares to {literal}")
    assert violations == []
