"""Product ClaimTypes compile from on-disk YAML. Do not invent ids."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kaori_api.auth import AuthError
from kaori_api.app import create_app
from kaori_flow import FlowCore, InMemorySignalStore


AUTH_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
AGENT_ID = f"user:{AUTH_USER_ID}"
TOKEN = "valid-supabase-token"

PRODUCT_CLAIMS = [
    (
        "earth.coastal_erosion.v1",
        "earth:coastal_erosion:h3:abc:surface:2026-01-07T00:00Z",
        {"recession_m": 1.5, "scarp_present": True, "stake_readings": [0.1, 0.2]},
    ),
    (
        "earth.infrastructure.v1",
        "earth:infrastructure:h3:abc:surface:2026-01-07T00:00Z",
        {
            "perimeter_gps": {"type": "Point", "coordinates": [115.0, -8.3]},
            "structures": [{"name": "pier"}],
            "vegetation_map": {"cover": "sparse"},
        },
    ),
    (
        "earth.vegetation.v1",
        "earth:vegetation:h3:abc:surface:2026-01-07T00:00Z",
        {
            "health_assessment": "moderate",
            "human_activity": False,
            "transect_photos": ["gs://kaori-evidence/t1.jpg"],
        },
    ),
    (
        "ocean.reef_recovery.v1",
        "ocean:reef_recovery:h3:abc:10m_depth:2026-01-07T00:00Z",
        {"coral_cover_pct": 42.0, "quadrat_data": [{"cover": 40}], "recruitment_count": 7},
    ),
    (
        "ocean.sea_temperature.v1",
        "ocean:sea_temperature:h3:abc:3m_depth:2026-01-07T12:00Z",
        {"depth_temps": {"3m": 28.1}, "readings": [28.0, 28.1, 28.2]},
    ),
    (
        "ocean.vessel_anomaly.v1",
        "ocean:vessel_anomaly:h3:abc:surface:2026-01-07T12:00Z",
        {"observation_duration_min": 15, "vessels": [{"id": "v1"}]},
    ),
    (
        "space.debris_track.v1",
        "space:debris_track:h3:abc:orbital_shell:2026-01-07T12:00Z",
        {
            "first_visible": "2026-01-07T12:00:00Z",
            "last_visible": "2026-01-07T12:05:00Z",
            "observations": [{"az": 12}],
        },
    ),
    (
        "space.light_pollution.v1",
        "space:light_pollution:h3:abc:surface:2026-01-07T12:00Z",
        {"sky_quality": "poor", "sqm_value": 18.5, "weather": "clear"},
    ),
    (
        "space.satellite_pass.v1",
        "space:satellite_pass:h3:abc:orbital_shell:2026-01-07T12:00Z",
        {
            "bearing": "NE",
            "first_visible": "2026-01-07T12:00:00Z",
            "last_visible": "2026-01-07T12:05:00Z",
            "max_elevation": 45.0,
        },
    ),
]


def verify_token(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return AGENT_ID


def auth_header() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def observation(claim_type: str, payload: dict) -> dict:
    return {
        "observation_id": "11111111-1111-1111-1111-111111111111",
        "claim_type": claim_type,
        "reported_at": "2026-01-07T12:00:00Z",
        "geo": {"lat": -8.3405, "lon": 115.0920},
        "payload": payload,
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/a.jpg", "sha256": "a" * 64},
            {"uri": "gs://kaori-evidence/b.jpg", "sha256": "b" * 64},
            {"uri": "gs://kaori-evidence/c.jpg", "sha256": "c" * 64},
            {"uri": "gs://kaori-evidence/d.jpg", "sha256": "d" * 64},
            {"uri": "gs://kaori-evidence/e.jpg", "sha256": "e" * 64},
        ],
    }


@pytest.fixture
def client() -> TestClient:
    flow = FlowCore(store=InMemorySignalStore())
    return TestClient(create_app(flow=flow, verify_token=verify_token))


@pytest.mark.parametrize("claim_type_id,truth_key,payload", PRODUCT_CLAIMS)
def test_product_claim_type_compiles_200(client: TestClient, claim_type_id, truth_key, payload):
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": truth_key,
            "claim_type_id": claim_type_id,
            "observations": [observation(claim_type_id, payload)],
        },
        headers=auth_header(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claim_type"] == claim_type_id
    assert body["truthkey"]
    for key, value in payload.items():
        assert key in body["claim"], f"TruthState.claim missing output_schema field {key}"
        assert body["claim"][key] == value
    assert "severity" not in body["claim"]
    assert "network_trust" not in body["claim"]
    fetched = client.get(f"/v1/truth/{body['truthkey']}", headers=auth_header())
    assert fetched.status_code == 200
    assert fetched.json() == body
    assert fetched.json()["claim"] == body["claim"]
    standing = client.get(f"/v1/standing/claimtype:{claim_type_id}", headers=auth_header())
    assert standing.status_code == 200
    assert 0.0 <= float(standing.json()["standing"]) <= 1000.0


def test_product_claim_missing_ui_schema_field_400(client: TestClient):
    payload = {"scarp_present": True, "stake_readings": []}
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": "earth:coastal_erosion:h3:abc:surface:2026-01-07T00:00Z",
            "claim_type_id": "earth.coastal_erosion.v1",
            "observations": [observation("earth.coastal_erosion.v1", payload)],
        },
        headers=auth_header(),
    )
    assert response.status_code == 400


def test_does_not_invent_earth_flood_or_orbital_debris_as_product_ids():
    ids = {row[0] for row in PRODUCT_CLAIMS}
    assert "earth.flood.v1" not in ids
    assert "space.orbital_debris.v1" not in ids
    assert "ocean.coral_bleaching.v1" not in ids


def test_unknown_yaml_still_404(client: TestClient):
    response = client.post(
        "/v1/compile",
        json={
            "truth_key": "earth:made_up:h3:abc:surface:2026-01-07T00:00Z",
            "claim_type_id": "earth.made_up.v1",
            "observations": [observation("earth.made_up.v1", {"x": 1})],
        },
        headers=auth_header(),
    )
    assert response.status_code == 404
