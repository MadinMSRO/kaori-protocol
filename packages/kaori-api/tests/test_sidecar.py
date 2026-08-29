"""Sidecar HTTP contract: /v1/compile, /v1/standing/{agent_id}, /v1/truth/{truthkey}."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from kaori_api.app import (
    LIMINAL_ORIGIN,
    LIMINAL_ORIGINS,
    LIMINAL_PREVIEW_ORIGIN,
    create_app as create_api_app,
    reporter_context_from_flow,
    stamp_observation,
)
from kaori_api.auth import AuthError
from kaori_api.generalist import ValidationVote
from kaori_db import InMemoryTruthStateStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
CORAL_CLAIM_TYPE = "ocean.coral_bleaching.v1"
VALIDATION_TIME = datetime(2026, 1, 7, 12, 30, tzinfo=timezone.utc)
TRUTHSTATE_FIELDS = {
    "truthkey",
    "claim_type",
    "claim_type_hash",
    "status",
    "claim",
    "confidence",
    "compile_inputs",
    "evidence_refs",
    "observation_ids",
    "security",
}


class RatifyingGeneralistClient:
    def validate(self, *, truthkey_id, claim_type_id, observations):
        return ValidationVote(
            agent_id="ai:generalist_v1",
            truthkey_id=truthkey_id,
            window_id=f"window:{truthkey_id}",
            vote="RATIFY",
            confidence=0.9,
            timestamp=VALIDATION_TIME,
            signature="test-generalist-signature",
        )


def create_app(**kwargs):
    kwargs.setdefault("generalist_client", RatifyingGeneralistClient())
    return create_api_app(**kwargs)


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or TOKEN}"}


def valid_observation(**overrides) -> dict:
    obs = {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": CORAL_CLAIM_TYPE,
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {
            "depth_meters": 8.0,
            "bleaching_present": True,
            "bleaching_percentage": 40,
        },
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64},
            {"uri": "gs://kaori-evidence/coral2.jpg", "sha256": "b" * 64},
        ],
    }
    obs.update(overrides)
    return obs


def compile_body(**overrides) -> dict:
    body = {
        "truth_key": "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
        "claim_type_id": CORAL_CLAIM_TYPE,
        "observations": [valid_observation()],
    }
    body.update(overrides)
    return body


@pytest.fixture
def flow() -> FlowCore:
    core = FlowCore(store=InMemorySignalStore())
    core.register_agent(AGENT_ID, role="observer")
    return core


@pytest.fixture
def client(flow: FlowCore) -> TestClient:
    return TestClient(create_app(flow=flow, verify_token=verify_token))


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


def test_cors_preflight_allows_live_and_preview_origins(client: TestClient):
    assert LIMINAL_ORIGINS == [LIMINAL_ORIGIN, LIMINAL_PREVIEW_ORIGIN]
    for origin in LIMINAL_ORIGINS:
        allowed = client.options(
            "/v1/compile",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers.get("access-control-allow-origin") == origin
        allow_methods = allowed.headers.get("access-control-allow-methods", "")
        for method in ("GET", "POST", "OPTIONS"):
            assert method in allow_methods
        allow_headers = allowed.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allow_headers
        assert "content-type" in allow_headers

    denied = client.options(
        "/v1/compile",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert denied.headers.get("access-control-allow-origin") not in LIMINAL_ORIGINS
    assert denied.headers.get("access-control-allow-origin") in (None, "null", "")


def test_cors_actual_request_echoes_live_and_preview_origins(client: TestClient):
    for origin in LIMINAL_ORIGINS:
        response = client.get(
            f"/v1/standing/{AGENT_ID}",
            headers={**auth_header(), "Origin": origin},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin


def test_compile_missing_bearer_401(client: TestClient):
    response = client.post("/v1/compile", json=compile_body())
    assert response.status_code == 401


def test_compile_invalid_bearer_401(client: TestClient):
    response = client.post(
        "/v1/compile",
        json=compile_body(),
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert response.status_code == 401


def test_compile_missing_evidence_refs_400(client: TestClient):
    obs = valid_observation()
    obs.pop("evidence_refs")
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_evidence_alias_is_not_accepted_400(client: TestClient):
    obs = valid_observation()
    obs.pop("evidence_refs")
    obs["evidence"] = [{"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64}]
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_missing_uri_400(client: TestClient):
    obs = valid_observation()
    obs["evidence_refs"] = [{"sha256": "a" * 64}]
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_missing_sha256_400(client: TestClient):
    obs = valid_observation()
    obs["evidence_refs"] = [{"uri": "gs://kaori-evidence/coral1.jpg"}]
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_bad_sha256_400(client: TestClient):
    obs = valid_observation()
    obs["evidence_refs"][0]["sha256"] = "not-a-hash"
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_missing_payload_fields_400(client: TestClient):
    obs = valid_observation(payload={"depth_meters": 8.0})
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_missing_required_output_schema_field_400(client: TestClient):
    """ui_schema still has depth_meters; claim requires bleaching_present."""
    obs = valid_observation(payload={"depth_meters": 8.0, "bleaching_percentage": 40})
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "REQUIRED" in detail or "output_schema" in detail.lower() or "bleaching_present" in detail


def test_compile_open_core_flood_missing_output_schema_400(client: TestClient):
    """Flood stays Open Core and has no output_schema — compile must not guess claim keys."""
    obs = {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": "earth.flood.v1",
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": 4.175, "lon": 73.509},
        "payload": {"water_level_cm": 12},
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/flood1.jpg", "sha256": "a" * 64},
        ],
    }
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z",
            "claim_type_id": "earth.flood.v1",
            "observations": [obs],
        },
        headers=auth_header(),
    )
    assert response.status_code == 400
    assert "output_schema" in response.json()["detail"]


def test_compile_unknown_claim_type_404(client: TestClient):
    response = client.post(
        "/v1/compile",
        json=compile_body(claim_type_id="earth.made_up.v1"),
        headers=auth_header(),
    )
    assert response.status_code == 404


def test_compile_invented_claim_type_404(client: TestClient):
    response = client.post(
        "/v1/compile",
        json=compile_body(claim_type_id="ocean.made_up.v1"),
        headers=auth_header(),
    )
    assert response.status_code == 404


def test_compile_200_signed_truth_state(client: TestClient):
    response = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    body = response.json()
    for field in TRUTHSTATE_FIELDS:
        assert field in body
    assert "truth_key" not in body
    assert body["truthkey"]
    assert body["claim_type"] == CORAL_CLAIM_TYPE
    assert body["security"]["signature"]
    assert body["security"]["state_hash"]
    assert body["security"]["semantic_hash"]
    assert isinstance(body["evidence_refs"], list)
    assert all(isinstance(item, str) for item in body["evidence_refs"])
    assert "evidence_refs" in body
    assert body["claim"]["bleaching_present"] is True
    assert body["claim"]["bleaching_percentage"] == 40
    assert "depth_meters" not in body["claim"]
    assert "severity" not in body["claim"]
    assert "network_trust" not in body["claim"]
    assert "confidence" not in body["claim"]


def test_compile_200_mime_type_optional(client: TestClient):
    obs = valid_observation()
    obs["evidence_refs"][0]["mime_type"] = "image/jpeg"
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 200, response.text


def test_compile_ignores_votes_sign_and_trust_snapshot(client: TestClient):
    body = compile_body()
    body["votes"] = [{"vote": "RATIFY"}]
    body["sign"] = False
    body["trust_snapshot"] = {"agent_trusts": {}}
    response = client.post("/v1/compile", json=body, headers=auth_header())
    assert response.status_code == 200, response.text
    assert response.json()["security"]["signature"]


def test_stamp_overwrites_client_reporter_fields(flow: FlowCore):
    context = reporter_context_from_flow(flow, AGENT_ID)
    stamped = stamp_observation(
        valid_observation(
            reporter_id="user:attacker",
            reporter_context={
                "standing": "authority",
                "trust_score": 1.0,
                "source_type": "official",
            },
        ),
        AGENT_ID,
        context,
    )
    assert stamped["reporter_id"] == AGENT_ID
    assert stamped["reporter_context"]["standing"] == "bronze"
    assert stamped["reporter_context"]["trust_score"] == pytest.approx(0.2)
    assert stamped["reporter_context"]["source_type"] == "human"


def test_compile_overwrites_client_minted_trust(client: TestClient):
    obs = valid_observation(
        reporter_id="user:attacker",
        reporter_context={
            "standing": "authority",
            "trust_score": 1.0,
            "source_type": "official",
        },
    )
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 200, response.text


def test_compile_200_without_client_reporter_fields(client: TestClient):
    response = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert response.status_code == 200, response.text


def test_compile_persists_truthstate_and_standing_from_emit_not_register():
    flow = FlowCore(store=InMemorySignalStore())
    truth_store = InMemoryTruthStateStore()
    assert AGENT_ID not in flow.get_all_standings()
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, truth_store=truth_store)
    )
    body = compile_body()
    compiled = client.post("/v1/compile", json=body, headers=auth_header())
    assert compiled.status_code == 200, compiled.text
    artifact = compiled.json()
    truthkey = artifact["truthkey"]
    assert ":" in truthkey
    assert truth_store.get(truthkey) == artifact
    assert "evidence_refs" in truth_store.get(truthkey)

    registered = flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)
    assert AGENT_ID not in {s.object_id for s in registered}
    validation_votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(validation_votes) == 1
    assert validation_votes[0].payload["vote"] == "RATIFY"
    emitted = flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED)
    assert len(emitted) == 1
    signal = emitted[0]
    assert signal.object_id == truthkey
    assert signal.payload["contributors"] == [AGENT_ID]
    assert signal.payload["status"] == artifact["status"]
    assert signal.payload["confidence"] == artifact["confidence"]
    expected_outcome = "correct" if artifact["status"] == "VERIFIED_TRUE" else "unknown"
    assert signal.payload["outcome"] == expected_outcome
    assert AGENT_ID in flow.get_all_standings()

    standing = client.get(f"/v1/standing/{AGENT_ID}", headers=auth_header())
    assert standing.status_code == 200
    assert 0.0 <= standing.json()["standing"] <= 1000.0

    fetched = client.get(f"/v1/truth/{truthkey}", headers=auth_header())
    assert fetched.status_code == 200
    assert fetched.json() == artifact


def test_compile_upserts_truthstate_on_truthkey():
    flow = FlowCore(store=InMemorySignalStore())
    truth_store = InMemoryTruthStateStore()
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, truth_store=truth_store)
    )
    first = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert first.status_code == 200, first.text
    truthkey = first.json()["truthkey"]
    second = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert second.status_code == 200, second.text
    assert second.json()["truthkey"] == truthkey
    stored = truth_store.get(truthkey)
    assert stored == second.json()
    emitted = flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED)
    assert len(emitted) == 2


def test_compile_404_does_not_persist_or_emit():
    flow = FlowCore(store=InMemorySignalStore())
    truth_store = InMemoryTruthStateStore()
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, truth_store=truth_store)
    )
    body = compile_body(claim_type_id="ocean.made_up.v1")
    response = client.post("/v1/compile", json=body, headers=auth_header())
    assert response.status_code == 404
    assert truth_store.get(body["truth_key"]) is None
    assert flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED) == []
    assert AGENT_ID not in {s.object_id for s in flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)}
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []


def test_get_truth_missing_bearer_401(client: TestClient):
    response = client.get("/v1/truth/ocean:coral_bleaching:missing")
    assert response.status_code == 401


def test_get_truth_invalid_bearer_401(client: TestClient):
    response = client.get(
        "/v1/truth/ocean:coral_bleaching:missing",
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert response.status_code == 401


def test_get_truth_unknown_404(client: TestClient):
    response = client.get(
        "/v1/truth/ocean:coral_bleaching:h3:does-not-exist",
        headers=auth_header(),
    )
    assert response.status_code == 404


def test_get_truth_colon_key_200():
    flow = FlowCore(store=InMemorySignalStore())
    truth_store = InMemoryTruthStateStore()
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, truth_store=truth_store)
    )
    compiled = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert compiled.status_code == 200, compiled.text
    truthkey = compiled.json()["truthkey"]
    assert ":" in truthkey
    fetched = client.get(f"/v1/truth/{truthkey}", headers=auth_header())
    assert fetched.status_code == 200
    assert fetched.json() == compiled.json()
    assert fetched.json()["evidence_refs"] == compiled.json()["evidence_refs"]


def test_standing_missing_bearer_401(client: TestClient):
    response = client.get(f"/v1/standing/{AGENT_ID}")
    assert response.status_code == 401


def test_standing_invalid_bearer_401(client: TestClient):
    response = client.get(f"/v1/standing/{AGENT_ID}", headers={"Authorization": "Token abc"})
    assert response.status_code == 401


def test_standing_unknown_agent_404(client: TestClient):
    response = client.get("/v1/standing/user:unknown", headers=auth_header())
    assert response.status_code == 404


def test_standing_200(client: TestClient, flow: FlowCore):
    expected = flow.get_standing(AGENT_ID)
    response = client.get(f"/v1/standing/{AGENT_ID}", headers=auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body == {"standing": expected}
    assert 0.0 <= body["standing"] <= 1000.0
