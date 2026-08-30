"""Focused GCS evidence client tests. No live bucket is required."""
from __future__ import annotations

import hashlib
from io import BytesIO

import pytest

from kaori_api.evidence_store import (
    DEFAULT_MAX_EVIDENCE_BYTES,
    EvidenceStorageError,
    GcsEvidenceStore,
    evidence_object_name,
    reporter_scope,
)
from kaori_truth.primitives.evidence import EvidenceRef

REPORTER = "user:550e8400-e29b-41d4-a716-446655440000"
BUCKET = "msro-kaori-observations"


class PreconditionFailed(Exception):
    """Mirrors google.api_core.exceptions.PreconditionFailed by class name."""


class FakeBlob:
    def __init__(self, objects: dict[str, dict], name: str):
        self._objects = objects
        self.name = name
        stored = objects.get(name)
        self.metadata = dict(stored["metadata"]) if stored else {}
        self.cache_control = None

    def upload_from_file(self, stream, size=None, content_type=None, if_generation_match=None):
        if if_generation_match == 0 and self.name in self._objects:
            raise PreconditionFailed("object already exists")
        data = stream.read(size) if size is not None else stream.read()
        self._objects[self.name] = {
            "bytes": data,
            "metadata": dict(self.metadata),
            "content_type": content_type,
        }

    def download_as_bytes(self) -> bytes:
        return self._objects[self.name]["bytes"]


class FakeBucket:
    def __init__(self, objects: dict[str, dict]):
        self._objects = objects

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self._objects, name)

    def get_blob(self, name: str) -> FakeBlob | None:
        if name not in self._objects:
            return None
        return FakeBlob(self._objects, name)


class FakeGcsClient:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def bucket(self, _name: str) -> FakeBucket:
        return FakeBucket(self.objects)


def _store(client: FakeGcsClient | None = None, max_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES) -> GcsEvidenceStore:
    return GcsEvidenceStore(BUCKET, client=client or FakeGcsClient(), max_bytes=max_bytes)


def test_upload_uses_reporter_scoped_content_addressed_path_and_metadata():
    client = FakeGcsClient()
    content = b"reef-photo-bytes"
    digest = hashlib.sha256(content).hexdigest()
    store = _store(client)

    ref = store.upload(
        BytesIO(content),
        filename="../../reef photo.jpg",
        content_type="image/jpeg",
        reporter_id=REPORTER,
        expected_sha256=digest,
    )

    expected_name = evidence_object_name(REPORTER, digest, "reef photo.jpg")
    assert ref.uri == f"gs://{BUCKET}/{expected_name}"
    assert ref.sha256 == digest
    assert expected_name.startswith(f"observations/{reporter_scope(REPORTER)}/{digest}/")
    stored = client.objects[expected_name]
    assert stored["bytes"] == content
    assert stored["metadata"] == {"sha256": digest}
    store.verify(ref, reporter_id=REPORTER)


def test_idempotent_precondition_re_verifies_existing_object():
    client = FakeGcsClient()
    content = b"same-bytes"
    digest = hashlib.sha256(content).hexdigest()
    store = _store(client)
    first = store.upload(
        BytesIO(content),
        filename="evidence.jpg",
        content_type="image/jpeg",
        reporter_id=REPORTER,
    )
    second = store.upload(
        BytesIO(content),
        filename="evidence.jpg",
        content_type="image/jpeg",
        reporter_id=REPORTER,
    )
    assert first.uri == second.uri
    assert list(client.objects.values())[0]["bytes"] == content


def test_idempotent_precondition_rejects_hash_mismatch_on_existing_object():
    client = FakeGcsClient()
    content = b"canonical"
    digest = hashlib.sha256(content).hexdigest()
    store = _store(client)
    store.upload(
        BytesIO(content),
        filename="evidence.jpg",
        content_type="image/jpeg",
        reporter_id=REPORTER,
    )
    name = evidence_object_name(REPORTER, digest, "evidence.jpg")
    client.objects[name]["bytes"] = b"tampered"
    with pytest.raises(EvidenceStorageError, match="stored object bytes"):
        store.upload(
            BytesIO(content),
            filename="evidence.jpg",
            content_type="image/jpeg",
            reporter_id=REPORTER,
        )


def test_verify_rejects_missing_object():
    store = _store()
    digest = hashlib.sha256(b"missing").hexdigest()
    ref = EvidenceRef(
        uri=f"gs://{BUCKET}/{evidence_object_name(REPORTER, digest, 'gone.jpg')}",
        sha256=digest,
    )
    with pytest.raises(EvidenceStorageError, match="does not exist"):
        store.verify(ref, reporter_id=REPORTER)


def test_verify_rejects_path_or_hash_mismatch_and_foreign_reporter():
    client = FakeGcsClient()
    content = b"scoped"
    digest = hashlib.sha256(content).hexdigest()
    store = _store(client)
    ref = store.upload(
        BytesIO(content),
        filename="evidence.jpg",
        content_type="image/jpeg",
        reporter_id=REPORTER,
    )

    other = "user:00000000-0000-0000-0000-000000000099"
    with pytest.raises(EvidenceStorageError, match="storage scope"):
        store.verify(ref, reporter_id=other)

    wrong_hash = EvidenceRef(uri=ref.uri, sha256="0" * 64)
    with pytest.raises(EvidenceStorageError, match="path does not match"):
        store.verify(wrong_hash, reporter_id=REPORTER)

    wrong_path = EvidenceRef(
        uri=f"gs://{BUCKET}/observations/{reporter_scope(REPORTER)}/{digest}/other.jpg",
        sha256=digest,
    )
    with pytest.raises(EvidenceStorageError, match="does not exist"):
        store.verify(wrong_path, reporter_id=REPORTER)

    name = evidence_object_name(REPORTER, digest, "evidence.jpg")
    client.objects[name]["metadata"] = {"sha256": "f" * 64}
    with pytest.raises(EvidenceStorageError, match="metadata"):
        store.verify(ref, reporter_id=REPORTER)


def test_upload_rejects_oversize_and_client_hash_mismatch():
    store = _store(max_bytes=8)
    with pytest.raises(EvidenceStorageError, match="exceeds"):
        store.upload(
            BytesIO(b"0123456789"),
            filename="big.bin",
            content_type="application/octet-stream",
            reporter_id=REPORTER,
        )
    with pytest.raises(EvidenceStorageError, match="does not match uploaded content"):
        store.upload(
            BytesIO(b"tiny"),
            filename="tiny.bin",
            content_type="application/octet-stream",
            reporter_id=REPORTER,
            expected_sha256="0" * 64,
        )
