"""Runtime catch-up: snapshot agents, unique observer, validate, settlement."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.generalist import ValidationVote
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

TOKEN = "valid-supabase-token"
CORAL_KEY = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
VESSEL_KEY = "ocean:vessel_anomaly:h3:abc:surface:2026-01-07T12:00Z"


def verify_token(token: str) -> str:
    if token == TOKEN:
        return "user:550e8400-e29b-41d4-a716-446655440000"
    if token.startswith("reporter-") or token.startswith("reviewer-"):
        return f"user:{token}"
    raise AuthError("Invalid Bearer token")


def auth(token: str = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def coral_obs(observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "claim_type": "ocean.coral_bleaching.v1",
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {"depth_meters": 8.0, "bleaching_percentage": 40},
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64},
            {"uri": "gs://kaori-evidence/coral2.jpg", "sha256": "b" * 64},
        ],
    }


def vessel_obs(observation_id: str) -> dict:
    return {
        "observation_id": observation_id,
        "claim_type": "ocean.vessel_anomaly.v1",
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {"observation_duration_min": 15, "vessels": [{"id": "v1"}]},
        "evidence_refs": [
            {"uri": f"gs://kaori-evidence/{observation_id}.jpg", "sha256": "c" * 64},
            {"uri": f"gs://kaori-evidence/{observation_id}-c.jpg", "sha256": "d" * 64},
        ],
    }


class FakeGeneralist:
    def __init__(self, vote: str = "RATIFY", confidence: float = 0.91):
        self.vote = vote
        self.confidence = confidence

    def validate(self, *, truthkey_id, claim_type_id, observations, timeout=None, on_late_vote=None):
        return ValidationVote(
            agent_id="ai:generalist_v1",
            truthkey_id=truthkey_id,
            window_id=f"window:{truthkey_id}",
            vote=self.vote,
            confidence=self.confidence,
            timestamp=datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc),
            signature="fake-generalist-sig",
        )


def test_production_without_generalist_does_not_compile(monkeypatch):
    monkeypatch.setenv("KAORI_ENVIRONMENT", "production")
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(create_app(flow=flow, verify_token=verify_token, generalist_client=None))
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": CORAL_KEY,
            "claim_type_id": "ocean.coral_bleaching.v1",
            "observations": [coral_obs("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
        },
        headers=auth(),
    )
    assert response.status_code == 503
    assert flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED) == []


def test_second_observation_from_same_observer_is_409():
    client = TestClient(
        create_app(flow=FlowCore(store=InMemorySignalStore()), verify_token=verify_token)
    )
    first = client.post(
        "/v1/compile",
        json={
            "truth_key": CORAL_KEY,
            "claim_type_id": "ocean.coral_bleaching.v1",
            "observations": [coral_obs("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
        },
        headers=auth(),
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/v1/compile",
        json={
            "truth_key": CORAL_KEY,
            "claim_type_id": "ocean.coral_bleaching.v1",
            "observations": [coral_obs("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")],
        },
        headers=auth(),
    )
    assert second.status_code == 409


def test_compile_snapshot_and_artifact_include_validator_and_claimtype():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=FakeGeneralist(),
        )
    )
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": CORAL_KEY,
            "claim_type_id": "ocean.coral_bleaching.v1",
            "observations": [coral_obs("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
        },
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["status"] == "PENDING_HUMAN_REVIEW"
    agent_ids = {row["agent_id"] for row in artifact["agents"]}
    assert "ai:generalist_v1" in agent_ids
    assert "claimtype:ocean.coral_bleaching.v1" in agent_ids
    assert any(row["role"] == "validator" for row in artifact["agents"])
    fetched = client.get(f"/v1/truth/{CORAL_KEY}", headers=auth())
    assert fetched.status_code == 200
    assert {row["agent_id"] for row in fetched.json()["agents"]} == agent_ids


def test_validate_human_ratify_closes_coral_and_settles_standing():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=FakeGeneralist("RATIFY", 0.99),
        )
    )
    compiled = client.post(
        "/v1/compile",
        json={
            "truth_key": CORAL_KEY,
            "claim_type_id": "ocean.coral_bleaching.v1",
            "observations": [coral_obs("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")],
        },
        headers=auth(),
    )
    assert compiled.status_code == 200, compiled.text
    before = flow.get_standing("user:550e8400-e29b-41d4-a716-446655440000")
    closed = client.post(
        "/v1/validate",
        json={"truth_key": CORAL_KEY, "vote": "RATIFY", "confidence": 0.8},
        headers=auth("reviewer-1"),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "VERIFIED_TRUE"
    after = flow.get_standing("user:550e8400-e29b-41d4-a716-446655440000")
    clip = flow.get_standing("ai:generalist_v1")
    reviewer = flow.get_standing("user:reviewer-1")
    assert after > before
    assert clip > 200.0
    assert reviewer > 200.0
    outcomes = {
        signal.payload["contributors"][0]: signal.payload["outcome"]
        for signal in flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED)
        if signal.payload.get("outcome") != "unknown"
    }
    assert outcomes["ai:generalist_v1"] == "correct"
    assert outcomes["user:550e8400-e29b-41d4-a716-446655440000"] == "correct"


def test_validate_human_reject_settles_vessel_observers_incorrect():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(
            flow=flow,
            verify_token=verify_token,
            generalist_client=FakeGeneralist("REJECT", 0.1),
        )
    )
    ids = (
        ("reporter-a", "11111111-1111-1111-1111-111111111111"),
        ("reporter-b", "22222222-2222-2222-2222-222222222222"),
        ("reporter-c", "33333333-3333-3333-3333-333333333333"),
    )
    last = None
    for token, observation_id in ids:
        last = client.post(
            "/v1/compile",
            json={
                "truth_key": VESSEL_KEY,
                "claim_type_id": "ocean.vessel_anomaly.v1",
                "observations": [vessel_obs(observation_id)],
            },
            headers=auth(token),
        )
    assert last is not None
    assert last.status_code == 200, last.text
    assert last.json()["status"] in {"LEANING_FALSE", "INVESTIGATING"}
    before = flow.get_standing("user:reporter-a")
    closed = client.post(
        "/v1/validate",
        json={"truth_key": VESSEL_KEY, "vote": "REJECT", "confidence": 0.4},
        headers=auth("reviewer-1"),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "VERIFIED_FALSE"
    assert flow.get_standing("user:reporter-a") < before
    assert flow.get_standing("ai:generalist_v1") > 200.0
    assert flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED)
    assert len(flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED)) == 3
