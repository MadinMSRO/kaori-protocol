"""Sidecar HTTP contract: only /v1/compile and /v1/standing/{agent_id}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kaori_api.app import (
    LIMINAL_ORIGIN,
    THIS_WEEK_CLAIM_TYPE,
    create_app,
    reporter_context_from_flow,
    stamp_observation,
)
from kaori_api.auth import AuthError
from kaori_flow import FlowCore, InMemorySignalStore


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
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


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or TOKEN}"}


def valid_observation(**overrides) -> dict:
    obs = {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": THIS_WEEK_CLAIM_TYPE,
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {"depth_meters": 8.0, "bleaching_percentage": 40},
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
        "claim_type_id": THIS_WEEK_CLAIM_TYPE,
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


def test_only_two_http_routes():
    application = create_app(
        flow=FlowCore(store=InMemorySignalStore()),
        verify_token=verify_token,
    )
    paths = {getattr(route, "path", None) for route in application.router.routes}
    paths.discard(None)
    assert paths == {"/v1/compile", "/v1/standing/{agent_id}"}


def test_cors_preflight_allows_liminal_origin_only(client: TestClient):
    allowed = client.options(
        "/v1/compile",
        headers={
            "Origin": LIMINAL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == LIMINAL_ORIGIN
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
    assert denied.headers.get("access-control-allow-origin") != LIMINAL_ORIGIN
    assert denied.headers.get("access-control-allow-origin") in (None, "null", "")


def test_cors_actual_request_echoes_liminal_origin(client: TestClient):
    response = client.get(
        f"/v1/standing/{AGENT_ID}",
        headers={**auth_header(), "Origin": LIMINAL_ORIGIN},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == LIMINAL_ORIGIN


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


def test_compile_unknown_claim_type_404(client: TestClient):
    response = client.post(
        "/v1/compile",
        json=compile_body(claim_type_id="earth.flood.v1"),
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
    assert body["claim_type"] == THIS_WEEK_CLAIM_TYPE
    assert body["security"]["signature"]
    assert body["security"]["state_hash"]
    assert body["security"]["semantic_hash"]
    assert isinstance(body["evidence_refs"], list)
    assert all(isinstance(item, str) for item in body["evidence_refs"])


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


def test_compile_registers_unknown_bearer_agent_for_standing():
    flow = FlowCore(store=InMemorySignalStore())
    assert AGENT_ID not in flow.get_all_standings()
    client = TestClient(create_app(flow=flow, verify_token=verify_token))

    compiled = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert compiled.status_code == 200, compiled.text
    assert AGENT_ID in flow.get_all_standings()

    standing = client.get(f"/v1/standing/{AGENT_ID}", headers=auth_header())
    assert standing.status_code == 200
    assert 0.0 <= standing.json()["standing"] <= 1000.0


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
