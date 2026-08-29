"""Sidecar HTTP contract: only /v1/compile and /v1/standing/{agent_id}."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from kaori_api.app import THIS_WEEK_CLAIM_TYPE, create_app
from kaori_flow import FlowCore, InMemorySignalStore


JWT_SECRET = "test-sidecar-secret"
AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"


def mint_token(sub: str = AUTH_USER_ID, extra: dict | None = None, secret: str = JWT_SECRET) -> str:
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def auth_header(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or mint_token()}"}


def valid_observation(reporter_id: str = AGENT_ID, evidence_as: str = "evidence") -> dict:
    evidence = [
        {
            "uri": "gs://kaori-evidence/coral1.jpg",
            "sha256": "a" * 64,
            "mime": "image/jpeg",
        },
        {
            "uri": "gs://kaori-evidence/coral2.jpg",
            "sha256": "b" * 64,
            "mime": "image/jpeg",
        },
    ]
    obs = {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": THIS_WEEK_CLAIM_TYPE,
        "reported_at": "2026-01-07T12:00:00Z",
        "reporter_id": reporter_id,
        "reporter_context": {
            "standing": "silver",
            "trust_score": 0.75,
            "source_type": "human",
        },
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": {"severity": "moderate", "bleaching_percentage": 40},
        "depth_meters": 8.0,
    }
    if evidence_as == "evidence":
        obs["evidence"] = evidence
    else:
        obs["evidence_refs"] = [
            {
                "uri": item["uri"],
                "sha256": item["sha256"],
                "mime_type": item["mime"],
            }
            for item in evidence
        ]
    return obs


def compile_body(**overrides) -> dict:
    body = {
        "observations": [valid_observation()],
        "truth_key": "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z",
        "claim_type_id": THIS_WEEK_CLAIM_TYPE,
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
    return TestClient(create_app(flow=flow, jwt_secret=JWT_SECRET))


def test_only_two_http_routes():
    application = create_app(flow=FlowCore(store=InMemorySignalStore()), jwt_secret=JWT_SECRET)
    paths = {getattr(route, "path", None) for route in application.router.routes}
    paths.discard(None)
    assert paths == {"/v1/compile", "/v1/standing/{agent_id}"}


def test_compile_missing_bearer_401(client: TestClient):
    response = client.post("/v1/compile", json=compile_body())
    assert response.status_code == 401


def test_compile_invalid_bearer_401(client: TestClient):
    response = client.post(
        "/v1/compile",
        json=compile_body(),
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


def test_compile_wrong_secret_401(client: TestClient):
    token = mint_token(secret="other-secret")
    response = client.post("/v1/compile", json=compile_body(), headers=auth_header(token))
    assert response.status_code == 401


def test_compile_missing_evidence_400(client: TestClient):
    obs = valid_observation()
    obs.pop("evidence", None)
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_missing_evidence_fields_400(client: TestClient):
    obs = valid_observation()
    obs["evidence"] = [{"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64}]
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 400


def test_compile_bad_sha256_400(client: TestClient):
    obs = valid_observation()
    obs["evidence"][0]["sha256"] = "not-a-hash"
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
    assert body["claim_type"] == THIS_WEEK_CLAIM_TYPE
    assert body["security"]["signature"]
    assert body["security"]["state_hash"]
    assert body["security"]["semantic_hash"]


def test_compile_200_with_primitive_evidence_refs(client: TestClient):
    body = compile_body(observations=[valid_observation(evidence_as="evidence_refs")])
    response = client.post("/v1/compile", json=body, headers=auth_header())
    assert response.status_code == 200, response.text


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
