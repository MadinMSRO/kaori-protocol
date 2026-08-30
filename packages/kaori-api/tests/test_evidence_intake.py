"""Authenticated evidence intake writes content-addressed private GCS references."""
from __future__ import annotations

import hashlib
from io import BytesIO

from fastapi.testclient import TestClient

from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import EvidenceStorageError, InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore

TOKEN = "valid-token"
AGENT_ID = "user:550e8400-e29b-41d4-a716-446655440000"


def _verify(token: str) -> str:
    if token != TOKEN:
        raise AuthError("invalid")
    return AGENT_ID


def test_content_addressed_upload_returns_gs_uri_and_hash():
    store = InMemoryEvidenceStore(bucket_name="kaori-observations")
    content = b"canonical evidence bytes"
    expected = hashlib.sha256(content).hexdigest()

    evidence = store.upload(
        BytesIO(content),
        filename="../../reef photo.jpg",
        content_type="image/jpeg",
        reporter_id=AGENT_ID,
        expected_sha256=expected,
    )

    assert evidence.sha256 == expected
    assert evidence.uri.startswith("gs://kaori-observations/observations/")
    assert evidence.uri.endswith(f"/{expected}/reef-photo.jpg")
    assert list(store.objects.values()) == [content]


def test_upload_rejects_client_hash_that_does_not_match_bytes():
    store = InMemoryEvidenceStore()
    try:
        store.upload(
            BytesIO(b"actual"),
            filename="evidence.jpg",
            content_type="image/jpeg",
            reporter_id=AGENT_ID,
            expected_sha256="0" * 64,
        )
    except EvidenceStorageError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("mismatched evidence hash was accepted")


def test_evidence_route_requires_bearer_and_returns_content_bound_ref():
    evidence_store = InMemoryEvidenceStore(bucket_name="kaori-observations")
    client = TestClient(
        create_app(
            flow=FlowCore(store=InMemorySignalStore()),
            verify_token=_verify,
            evidence_store=evidence_store,
        )
    )
    content = b"photo"
    expected = hashlib.sha256(content).hexdigest()

    unauthorized = client.post(
        "/v1/evidence",
        files={"file": ("reef.jpg", content, "image/jpeg")},
    )
    assert unauthorized.status_code == 401

    response = client.post(
        "/v1/evidence",
        headers={"Authorization": f"Bearer {TOKEN}"},
        files={"file": ("reef.jpg", content, "image/jpeg")},
        data={"expected_sha256": expected},
    )
    assert response.status_code == 200, response.text
    assert response.json()["sha256"] == expected
    assert response.json()["uri"].startswith("gs://kaori-observations/")
