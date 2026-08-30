"""Compile order: observation → validation vote → compilation. No new routes."""
from __future__ import annotations

import ast
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.generalist import ValidationVote
from kaori_api.generalist_client import generalist_timeout_seconds, iso8601_duration_seconds
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.compiler import compile_truth_state as real_compile
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.truthstate import TruthStatus

INTEGRATION_MD = Path("INTEGRATION.md")
SIDECAR_README = Path("packages/kaori-api/README.md")

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
    def __init__(self, *, error: Exception | None = None, gate: threading.Event | None = None):
        self.error = error
        self.gate = gate
        self.calls = []
        self.started = threading.Event()

    def validate(self, *, truthkey_id, claim_type_id, observations, timeout=None):
        self.started.set()
        self.calls.append(
            {
                "truthkey_id": truthkey_id,
                "claim_type_id": claim_type_id,
                "timeout": timeout,
                "evidence": [
                    ref.uri
                    for observation in observations
                    for ref in observation.evidence_refs
                ],
            }
        )
        if self.gate is not None:
            self.gate.wait(5)
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


def join_validate_threads(application, timeout: float = 2.0) -> None:
    for thread in list(getattr(application.state, "validate_threads", [])):
        thread.join(timeout)


def wait_for_truth(client: TestClient, truthkey: str, *, timeout: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/v1/truth/{truthkey}", headers=auth_header())
        if last.status_code == 200:
            return last
        time.sleep(0.02)
    raise AssertionError(
        f"compile did not finish: {getattr(last, 'status_code', None)} "
        f"{getattr(last, 'text', None)}"
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
    join_validate_threads(client.app)
    compiled = wait_for_truth(client, coral_body()["truth_key"])
    assert order == ["validate", "compile_truth_state"]
    assert fake.calls[0]["truthkey_id"] == coral_body()["truth_key"]
    assert fake.calls[0]["claim_type_id"] == "ocean.coral_bleaching.v1"
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].payload["vote"] == "RATIFY"
    assert compiled.json()["status"] == "PENDING_HUMAN_REVIEW"
    assert "VALIDATION" not in {s.value for s in TruthStatus}


def test_timeout_error_does_not_compile_without_vote(monkeypatch, caplog):
    fake = FakeGeneralistClient(error=TimeoutError("CLIP wait exceeded YAML timeout"))
    order = []

    def wrapped(*args, **kwargs):
        order.append("compile_truth_state")
        return real_compile(*args, **kwargs)

    monkeypatch.setattr("kaori_api.orchestrator.compile_truth_state", wrapped)
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
    join_validate_threads(client.app)
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    assert order == []
    missing = client.get(f"/v1/truth/{coral_body()['truth_key']}", headers=auth_header())
    assert missing.status_code == 404
    assert "not compiling without a vote" in caplog.text


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


def test_integration_describes_pre_compile_validation_vote():
    """INTEGRATION.md (and sidecar README) must match vote-before-compile, not post-persist CLIP."""
    integration = INTEGRATION_MD.read_text()
    readme = SIDECAR_README.read_text()
    stale = (
        "After any ClaimType persists",
        "post-persist",
        "post-response",
        "After any ClaimType compiles",
    )
    for phrase in stale:
        assert phrase not in integration
        assert phrase not in readme
    assert (
        "observation checks → `VALIDATION_VOTE` → `TruthOrchestrator.compile_observations` "
        "→ persist → `FlowCore.emit_truthstate`"
    ) in integration
    order = integration[integration.index("`POST /v1/compile` order:"):]
    vote_at = order.index("VALIDATION_VOTE")
    compile_at = order.index("compile_observations")
    persist_at = order.index("persist `TruthState.model_dump`")
    emit_at = order.index("FlowCore.emit_truthstate")
    assert vote_at < compile_at < persist_at < emit_at
    assert "before `compile_observations`" in readme
    assert "VALIDATION" not in {s.value for s in TruthStatus}
    assert "`GET` | `/v1/standing/{agent_id}`" in integration
    assert "/v1/standing/claimtype:" not in integration
    assert "Player standing stays" in integration
    assert "Artifact `claim` still comes from `GET /v1/truth/{truthkey}`" in integration
    assert "same `{standing}` body" in integration
    assert "No fourth path" in integration
    assert "No fourth path" in readme
    assert "Player standing stays `user:{id}`" in readme
    assert "full observation package" in integration
    assert "CLIP relevance" in integration
    assert "TruthKey H3" in integration
    assert "before `compile_truth_state`" in integration
    assert "full observation package" in readme
    assert "Observe does not wait on CLIP" in integration
    assert "ai_validation_routing.generalist.timeout" in integration
    assert "new field" in integration
    assert "Never swallow `TimeoutError`" in integration
    assert "compile does not proceed on a swallowed timeout" in integration
    assert "compile does not proceed on a swallowed timeout" in readme
    assert "late generalist 200" in integration
    assert "only after a vote is recorded" in integration
    assert "never hardcode 30s" in integration
    assert "Warming is ops" in integration
    assert "Observe does not wait on CLIP" in readme
    assert "timeout: float = 30.0" not in Path(
        "packages/kaori-api/src/kaori_api/generalist_client.py"
    ).read_text()


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


def test_timeout_is_read_from_claimtype_yaml_not_hardcoded_30():
    coastal = load_claim_type(
        "packages/kaori-spec/schemas/earth/coastal_erosion_v1.yaml"
    )
    coral = load_claim_type(
        "packages/kaori-spec/schemas/ocean/coral_bleaching_v1.yaml"
    )
    assert generalist_timeout_seconds(coastal) == 120.0
    assert generalist_timeout_seconds(coral) == 120.0
    assert iso8601_duration_seconds("PT90S") == 90.0
    assert iso8601_duration_seconds("PT2M") == 120.0
    dispute = {"peer_review": "PT12H", "expert_review": "PT24H", "authority_escalation": "PT48H"}
    assert coastal.get_config()["dispute_resolution"]["timeout"] == dispute
    assert coastal.get_config()["ai_validation_routing"]["generalist"]["timeout"] != "PT12H"

    fake = FakeGeneralistClient()
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, generalist_client=fake)
    )
    response = client.post("/v1/compile", json=coral_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    join_validate_threads(client.app)
    assert fake.calls[0]["timeout"] == 120.0
    assert fake.calls[0]["timeout"] != 30.0


def test_late_generalist_200_still_records_vote_then_compiles(monkeypatch):
    gate = threading.Event()
    fake = FakeGeneralistClient(gate=gate)
    order = []

    def wrapped(*args, **kwargs):
        order.append("compile_truth_state")
        return real_compile(*args, **kwargs)

    monkeypatch.setattr("kaori_api.orchestrator.compile_truth_state", wrapped)
    flow = FlowCore(store=InMemorySignalStore())
    client = TestClient(
        create_app(flow=flow, verify_token=verify_token, generalist_client=fake)
    )
    body = coral_body()
    response = client.post("/v1/compile", json=body, headers=auth_header())
    assert response.status_code == 200, response.text
    assert fake.started.wait(1.0)
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    assert order == []
    assert client.get(f"/v1/truth/{body['truth_key']}", headers=auth_header()).status_code == 404

    gate.set()
    join_validate_threads(client.app)
    compiled = wait_for_truth(client, body["truth_key"])
    votes = flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)
    assert len(votes) == 1
    assert votes[0].payload["vote"] == "RATIFY"
    assert order == ["compile_truth_state"]
    assert compiled.status_code == 200
    assert compiled.json()["status"] != "VALIDATION"


def test_compile_without_vote_is_forbidden(monkeypatch):
    fake = FakeGeneralistClient(error=TimeoutError())
    order = []

    def wrapped(*args, **kwargs):
        order.append("compile_truth_state")
        return real_compile(*args, **kwargs)

    monkeypatch.setattr("kaori_api.orchestrator.compile_truth_state", wrapped)
    flow = FlowCore(store=InMemorySignalStore())
    application = create_app(
        flow=flow, verify_token=verify_token, generalist_client=fake
    )
    client = TestClient(application)
    response = client.post("/v1/compile", json=coral_body(), headers=auth_header())
    assert response.status_code == 200, response.text
    join_validate_threads(application)
    assert order == []
    assert flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) == []
    assert client.get(
        f"/v1/truth/{coral_body()['truth_key']}", headers=auth_header()
    ).status_code == 404
