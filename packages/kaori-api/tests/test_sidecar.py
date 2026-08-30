"""Sidecar HTTP contract: /v1/compile, /v1/standing/{agent_id}, /v1/truth/{truthkey}."""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from kaori_api.app import (
    LIMINAL_ORIGIN,
    LIMINAL_ORIGINS,
    LIMINAL_PREVIEW_ORIGIN,
    create_app,
    reporter_context_from_flow,
    stamp_observation,
)
from kaori_api.auth import AuthError
from kaori_db import InMemoryTruthStateStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"
CORAL_CLAIM_TYPE = "ocean.coral_bleaching.v1"
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


def test_compile_ui_schema_payload_derives_output_boolean(client: TestClient):
    """Cockpit ui_schema payload (no bleaching_present) compiles; claim is derived."""
    obs = valid_observation(payload={"depth_meters": 8.0, "bleaching_percentage": 40})
    response = client.post("/v1/compile", json=compile_body(observations=[obs]), headers=auth_header())
    assert response.status_code == 200, response.text
    claim = response.json()["claim"]
    assert claim["bleaching_present"] is True
    assert claim["bleaching_percentage"] == 40
    assert "depth_meters" not in claim


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
    assert body["evidence_refs"]
    assert all(isinstance(item, dict) for item in body["evidence_refs"])
    assert all(set(item.keys()) == {"uri", "sha256"} for item in body["evidence_refs"])
    assert {item["uri"] for item in body["evidence_refs"]} == {
        "gs://kaori-evidence/coral1.jpg",
        "gs://kaori-evidence/coral2.jpg",
    }
    assert all(len(item["sha256"]) == 64 for item in body["evidence_refs"])
    packages = body["compile_inputs"]["observations"]
    assert len(packages) == 1
    assert packages[0]["geo"] == {"lat": -8.3405, "lon": 115.0920}
    assert packages[0]["payload"]["bleaching_percentage"] == 40
    assert packages[0]["evidence_refs"][0]["uri"].endswith("coral1.jpg")
    assert packages[0]["evidence_refs"][0]["sha256"] == "a" * 64
    assert body.get("consensus") is None
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
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    emitted = flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED)
    assert len(emitted) == 1
    signal = emitted[0]
    assert signal.object_id == truthkey
    claimtype_agent = f"claimtype:{CORAL_CLAIM_TYPE}"
    assert signal.payload["contributors"] == [AGENT_ID, claimtype_agent]
    assert signal.payload["status"] == artifact["status"]
    assert signal.payload["confidence"] == artifact["confidence"]
    expected_outcome = "correct" if artifact["status"] == "VERIFIED_TRUE" else "unknown"
    assert signal.payload["outcome"] == expected_outcome
    assert AGENT_ID in flow.get_all_standings()

    standing = client.get(f"/v1/standing/{AGENT_ID}", headers=auth_header())
    assert standing.status_code == 200
    assert standing.json() == {"standing": flow.get_standing(AGENT_ID)}
    assert 0.0 <= standing.json()["standing"] <= 1000.0
    assert AGENT_ID == f"user:{AUTH_USER_ID}"

    fetched = client.get(f"/v1/truth/{truthkey}", headers=auth_header())
    assert fetched.status_code == 200
    assert fetched.json() == artifact
    assert "claim" in fetched.json()
    assert "claim" not in standing.json()


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
    assert "claimtype:ocean.made_up.v1" not in {
        s.object_id for s in flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)
    }
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    unknown_standing = client.get(
        "/v1/standing/claimtype:ocean.made_up.v1",
        headers=auth_header(),
    )
    assert unknown_standing.status_code == 404


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


def test_claimtype_standing_200_float_after_compile_unknown_still_404():
    """Existing GET /v1/standing/{agent_id} covers claimtype:{id} once registered."""
    from kaori_api.validation import claimtype_agent_id

    flow = FlowCore(store=InMemorySignalStore())
    application = create_app(flow=flow, verify_token=verify_token)
    client = TestClient(application)
    compiled_id = claimtype_agent_id(CORAL_CLAIM_TYPE)
    never_compiled_id = claimtype_agent_id("ocean.vessel_anomaly.v1")
    unknown_id = claimtype_agent_id("ocean.made_up.v1")
    paths = {getattr(route, "path", None) for route in application.router.routes}
    assert "/v1/standing/{agent_id}" in paths
    assert not any(path and "claimtype" in path for path in paths)

    before = client.get(f"/v1/standing/{compiled_id}", headers=auth_header())
    assert before.status_code == 404

    compiled = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert compiled.status_code == 200, compiled.text

    standing = client.get(f"/v1/standing/{compiled_id}", headers=auth_header())
    encoded = client.get(
        f"/v1/standing/{quote(compiled_id, safe='.')}",
        headers=auth_header(),
    )
    assert standing.status_code == 200
    assert encoded.status_code == 200
    body = standing.json()
    assert body == encoded.json()
    assert set(body) == {"standing"}
    assert "claim" not in body
    assert isinstance(body["standing"], (int, float))
    assert not isinstance(body["standing"], bool)
    rank = float(body["standing"])
    assert 0.0 <= rank <= 1000.0
    assert rank == flow.get_standing(compiled_id)

    player = client.get(f"/v1/standing/{AGENT_ID}", headers=auth_header())
    assert AGENT_ID == f"user:{AUTH_USER_ID}"
    assert player.status_code == 200
    assert set(player.json()) == {"standing"}
    assert client.get(f"/v1/standing/{compiled_id}").status_code == 401

    artifact = client.get(f"/v1/truth/{compiled.json()['truthkey']}", headers=auth_header())
    assert artifact.status_code == 200
    assert "claim" in artifact.json()
    assert artifact.json()["claim"] == compiled.json()["claim"]

    emitted = flow.store.get_by_type(SignalTypes.TRUTHSTATE_EMITTED)
    assert compiled_id in emitted[0].payload["contributors"]
    registered = [
        s
        for s in flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)
        if s.object_id == compiled_id
    ]
    assert len(registered) == 1
    assert registered[0].payload["role"] == "claimtype"

    assert client.get(f"/v1/standing/{never_compiled_id}", headers=auth_header()).status_code == 404
    assert client.get(f"/v1/standing/{unknown_id}", headers=auth_header()).status_code == 404


def test_claimtype_register_is_idempotent_across_compiles():
    from kaori_api.validation import claimtype_agent_id

    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(create_app(flow=flow, verify_token=verify_token))
    agent = claimtype_agent_id(CORAL_CLAIM_TYPE)
    first = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    second = client.post("/v1/compile", json=compile_body(), headers=auth_header())
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    registered = [
        s
        for s in flow.store.get_by_type(SignalTypes.AGENT_REGISTERED)
        if s.object_id == agent
    ]
    assert len(registered) == 1
    standing = client.get(f"/v1/standing/{agent}", headers=auth_header())
    assert standing.status_code == 200
    assert isinstance(standing.json()["standing"], (int, float))
    assert 0.0 <= float(standing.json()["standing"]) <= 1000.0
