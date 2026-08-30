"""Validation unlocks only after ClaimType distinct-reporter observations are stored."""
from __future__ import annotations

from fastapi.testclient import TestClient

from kaori_api.app import create_app
from kaori_flow import FlowCore, InMemorySignalStore

TRUTHKEY = "ocean:vessel_anomaly:h3:abc:surface:2026-01-07T12:00Z"


def _body(observation_id: str) -> dict:
    return {
        "truth_key": TRUTHKEY,
        "claim_type_id": "ocean.vessel_anomaly.v1",
        "observations": [
            {
                "observation_id": observation_id,
                "claim_type": "ocean.vessel_anomaly.v1",
                "reported_at": "2026-01-07T12:00:00Z",
                "geo": {"lat": -8.3405, "lon": 115.0920},
                "payload": {
                    "observation_duration_min": 15,
                    "vessels": [{"id": "v1"}],
                },
                "evidence_refs": [
                    {
                        "uri": f"gs://kaori-observations/{observation_id}.jpg",
                        "sha256": observation_id.replace("-", "") * 2,
                    },
                    {
                        "uri": f"gs://kaori-observations/{observation_id}-context.jpg",
                        "sha256": "f" * 64,
                    },
                ],
            }
        ],
    }


def _headers(reporter: str) -> dict:
    return {"Authorization": f"Bearer {reporter}"}


def test_same_reporter_retries_do_not_unlock_distinct_reporter_gate():
    client = TestClient(
        create_app(
            flow=FlowCore(store=InMemorySignalStore()),
            verify_token=lambda token: f"user:{token}",
        )
    )

    first = client.post(
        "/v1/compile",
        json=_body("11111111-1111-1111-1111-111111111111"),
        headers=_headers("reporter-a"),
    )
    assert first.status_code == 202
    assert first.json()["observation_progress"] == {"received": 1, "required": 3}

    retry = client.post(
        "/v1/compile",
        json=_body("11111111-1111-1111-1111-111111111111"),
        headers=_headers("reporter-a"),
    )
    assert retry.status_code == 202
    assert retry.json()["observation_progress"] == {"received": 1, "required": 3}


def test_third_distinct_reporter_unlocks_validation_and_compile():
    client = TestClient(
        create_app(
            flow=FlowCore(store=InMemorySignalStore()),
            verify_token=lambda token: f"user:{token}",
        )
    )

    responses = []
    for reporter, observation_id in (
        ("reporter-a", "11111111-1111-1111-1111-111111111111"),
        ("reporter-b", "22222222-2222-2222-2222-222222222222"),
        ("reporter-c", "33333333-3333-3333-3333-333333333333"),
    ):
        responses.append(
            client.post(
                "/v1/compile",
                json=_body(observation_id),
                headers=_headers(reporter),
            )
        )

    assert [response.status_code for response in responses[:2]] == [202, 202]
    assert responses[2].status_code == 200, responses[2].text
    artifact = responses[2].json()
    assert len(artifact["compile_inputs"]["observations"]) == 3
    assert len({item["reporter_id"] for item in artifact["compile_inputs"]["observations"]}) == 3
