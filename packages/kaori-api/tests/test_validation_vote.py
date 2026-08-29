"""V4 first slice: bouncer agent + record_validation_vote. No new routes, no model."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.validation import (
    BOUNCER_AGENT_ID,
    ensure_bouncer_registered,
    record_validation_vote,
)
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
CORAL_CLAIM_TYPE = "ocean.coral_bleaching.v1"
CORAL_YAML = Path("packages/kaori-spec/schemas/ocean/coral_bleaching_v1.yaml")


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def coral_compile_body() -> dict:
    return {
        "truth_key": "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
        "claim_type_id": CORAL_CLAIM_TYPE,
        "observations": [
            {
                "observation_id": "11111111-1111-1111-1111-111111111111",
                "claim_type": CORAL_CLAIM_TYPE,
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


def test_coral_still_always_require_human():
    spec = yaml.safe_load(CORAL_YAML.read_text())
    assert spec["human_gating"]["always_require_human"] is True
    assert spec["risk_profile"] == "critical"


def test_bouncer_registered_on_startup_idempotent():
    flow = FlowCore(store=InMemorySignalStore())
    assert BOUNCER_AGENT_ID not in flow.get_all_standings()
    create_app(flow=flow, verify_token=verify_token)
    create_app(flow=flow, verify_token=verify_token)
    registered = [
        s
        for s in flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)
        if s.object_id == BOUNCER_AGENT_ID
    ]
    assert len(registered) == 1
    assert registered[0].payload["role"] == "validator"
    assert flow.get_standing(BOUNCER_AGENT_ID) == 250.0


def test_ensure_bouncer_skips_when_already_known():
    flow = FlowCore(store=InMemorySignalStore())
    flow.register_agent(BOUNCER_AGENT_ID, role="validator")
    before = len(flow.store.get_by_type(SignalTypes.AGENT_REGISTERED))
    ensure_bouncer_registered(flow)
    assert len(flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)) == before


def test_record_validation_vote_emits_flow_spec_payload():
    flow = FlowCore(store=InMemorySignalStore())
    ensure_bouncer_registered(flow)
    truthkey = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
    signal = record_validation_vote(
        flow,
        agent_id=BOUNCER_AGENT_ID,
        truthkey_id=truthkey,
        window_id="window:coral-1",
        vote="RATIFY",
        signature="sig-bouncer-1",
        confidence=0.91,
    )
    assert signal.signal_type == SignalTypes.VALIDATION_VOTE
    assert signal.object_id == truthkey
    assert signal.agent_id == BOUNCER_AGENT_ID
    assert signal.signature == "sig-bouncer-1"
    assert signal.payload == {
        "agent_id": BOUNCER_AGENT_ID,
        "truthkey_id": truthkey,
        "window_id": "window:coral-1",
        "vote": "RATIFY",
        "signature": "sig-bouncer-1",
        "confidence": 0.91,
    }
    stored = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(stored) == 1
    assert stored[0].signal_id == signal.signal_id


def test_record_validation_vote_confidence_optional():
    flow = FlowCore(store=InMemorySignalStore())
    signal = record_validation_vote(
        flow,
        agent_id=BOUNCER_AGENT_ID,
        truthkey_id="earth:coastal_erosion:h3:abc:surface:2026-01-07T00:00Z",
        window_id="window:1",
        vote="ABSTAIN",
        signature="sig",
    )
    assert "confidence" not in signal.payload
    assert signal.payload["vote"] == "ABSTAIN"


def test_record_validation_vote_rejects_bad_vote_and_missing_signature():
    flow = FlowCore(store=InMemorySignalStore())
    with pytest.raises(ValueError):
        record_validation_vote(
            flow,
            agent_id=BOUNCER_AGENT_ID,
            truthkey_id="k",
            window_id="w",
            vote="APPROVE",
            signature="sig",
        )
    with pytest.raises(ValueError):
        record_validation_vote(
            flow,
            agent_id=BOUNCER_AGENT_ID,
            truthkey_id="k",
            window_id="w",
            vote="RATIFY",
            signature="",
        )
    with pytest.raises(ValueError):
        record_validation_vote(
            flow,
            agent_id=BOUNCER_AGENT_ID,
            truthkey_id="k",
            window_id="w",
            vote="REJECT",
            signature="sig",
            confidence=1.5,
        )


def test_compile_does_not_record_validation_vote():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(create_app(flow=flow, verify_token=verify_token))
    response = client.post("/v1/compile", json=coral_compile_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []


def test_bouncer_ratify_does_not_make_coral_verified_true():
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(create_app(flow=flow, verify_token=verify_token))
    truth_key = coral_compile_body()["truth_key"]
    record_validation_vote(
        flow,
        agent_id=BOUNCER_AGENT_ID,
        truthkey_id=truth_key,
        window_id="window:coral-1",
        vote="RATIFY",
        signature="sig-bouncer-1",
        confidence=0.99,
    )
    response = client.post("/v1/compile", json=coral_compile_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] != "VERIFIED_TRUE"
    assert body["claim_type"] == CORAL_CLAIM_TYPE
    assert len(flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)) == 1


def test_no_new_http_routes_for_validation_vote():
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
    assert not any("vote" in (path or "") for path in paths)
    assert not any("bouncer" in (path or "") for path in paths)
    assert not any("validat" in (path or "") for path in paths)
