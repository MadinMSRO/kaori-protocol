"""HTTP + Postgres: evidence intake then 202 / 202 / 200 on the ledger."""
from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from kaori_api.app import create_app
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_db import PostgresObservationStore, PostgresSignalStore, PostgresTruthArtifactStore
from kaori_flow import FlowCore
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

TRUTHKEY = "ocean:vessel_anomaly:h3:abc:surface:2026-01-07T12:00Z"


def _postgres_url() -> str:
    for key in ("KAORI_TEST_DATABASE_URL", "DATABASE_URL"):
        url = os.environ.get(key, "")
        if url.startswith("postgres"):
            return url
    return "postgresql://ubuntu@127.0.0.1:5432/kaori_test"


@pytest.fixture(scope="module")
def postgres_url():
    url = _postgres_url()
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    return url


@pytest.fixture
def engine(postgres_url):
    engine = create_engine(postgres_url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("RESET ROLE"))
        conn.execute(text("DROP SCHEMA IF EXISTS kaori CASCADE"))
    signals = PostgresSignalStore(engine=engine)
    signals.ensure_schema()
    yield engine
    with engine.begin() as conn:
        conn.execute(text("RESET ROLE"))
        conn.execute(text("DROP SCHEMA IF EXISTS kaori CASCADE"))
    engine.dispose()


def _upload(client: TestClient, token: str, content: bytes, filename: str) -> dict:
    expected = hashlib.sha256(content).hexdigest()
    response = client.post(
        "/v1/evidence",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, "image/jpeg")},
        data={"expected_sha256": expected},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["uri"].startswith("gs://")
    assert body["sha256"] == expected
    return body


def _compile(client: TestClient, token: str, refs: list[dict], observation_id: str):
    return client.post(
        "/v1/compile",
        headers={"Authorization": f"Bearer {token}"},
        json={
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
                    "evidence_refs": refs,
                }
            ],
        },
    )


def test_evidence_then_threshold_202_202_200(engine):
    signals = PostgresSignalStore(engine=engine)
    observations = PostgresObservationStore(engine=engine)
    artifacts = PostgresTruthArtifactStore(engine=engine)
    evidence = InMemoryEvidenceStore(bucket_name="kaori-observations-test")
    client = TestClient(
        create_app(
            flow=FlowCore(store=signals),
            verify_token=lambda token: f"user:{token}",
            evidence_store=evidence,
            observation_store=observations,
            truth_store=artifacts,
        )
    )

    statuses = []
    for index, reporter in enumerate(("reporter-a", "reporter-b", "reporter-c"), start=1):
        photo = _upload(client, reporter, f"photo-{reporter}".encode(), f"{reporter}.jpg")
        context = _upload(client, reporter, f"context-{reporter}".encode(), f"{reporter}-context.jpg")
        response = _compile(
            client,
            reporter,
            [photo, context],
            f"{index}1111111-1111-1111-1111-111111111111",
        )
        statuses.append(response.status_code)
        if response.status_code == 202:
            assert response.json()["status"] == "PENDING"
            assert response.json()["observation_progress"]["received"] == index
            assert response.json()["observation_progress"]["required"] == 3

    assert statuses == [202, 202, 200], statuses
    stored = client.get(
        f"/v1/truth/{TRUTHKEY}",
        headers={"Authorization": "Bearer reporter-c"},
    )
    assert stored.status_code == 200, stored.text
    body = stored.json()
    assert body["truthkey"] == TRUTHKEY
    assert len(body["compile_inputs"]["observations"]) == 3
    assert len({item["reporter_id"] for item in body["compile_inputs"]["observations"]}) == 3
    assert body["security"]["signature"]
