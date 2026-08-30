"""Private, content-addressed evidence storage for Kaori observations."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import PurePath
from typing import BinaryIO, Optional
from urllib.parse import urlparse

from kaori_truth.primitives.evidence import EvidenceRef

DEFAULT_MAX_EVIDENCE_BYTES = 25 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


class EvidenceStorageError(Exception):
    """Evidence could not be validated or stored."""


def _safe_filename(filename: str) -> str:
    name = PurePath(filename or "evidence").name
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return normalized[:128] or "evidence"


def _digest_and_size(stream: BinaryIO, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise EvidenceStorageError(f"evidence exceeds {max_bytes} byte limit")
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest(), size


class InMemoryEvidenceStore:
    """Content-addressed evidence store for API tests."""

    def __init__(self, bucket_name: str = "kaori-observations-test", max_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES):
        self.bucket_name = bucket_name
        self.max_bytes = max_bytes
        self.objects: dict[str, bytes] = {}

    def upload(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        content_type: Optional[str],
        reporter_id: str,
        expected_sha256: Optional[str] = None,
    ) -> EvidenceRef:
        sha256, size = _digest_and_size(stream, self.max_bytes)
        if expected_sha256 and expected_sha256.lower() != sha256:
            raise EvidenceStorageError("evidence sha256 does not match uploaded content")
        reporter_scope = hashlib.sha256(reporter_id.encode("utf-8")).hexdigest()[:16]
        object_name = f"observations/{reporter_scope}/{sha256}/{_safe_filename(filename)}"
        self.objects.setdefault(object_name, stream.read())
        stream.seek(0)
        return EvidenceRef(
            uri=f"gs://{self.bucket_name}/{object_name}",
            sha256=sha256,
            mime_type=content_type,
            bytes_size=size,
        )

    def verify(self, evidence: EvidenceRef, *, reporter_id: str) -> None:
        """Tests may inject protocol-valid external refs without object bytes."""
        if not evidence.uri.startswith("gs://") or not evidence.sha256:
            raise EvidenceStorageError("evidence must be a content-bound gs:// reference")


class GcsEvidenceStore:
    """Upload evidence to a private GCS bucket without overwriting existing bytes."""

    def __init__(
        self,
        bucket_name: str,
        *,
        client=None,
        max_bytes: int = DEFAULT_MAX_EVIDENCE_BYTES,
    ):
        if not bucket_name:
            raise ValueError("KAORI_OBSERVATIONS_BUCKET is required")
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.bucket_name = bucket_name
        self.client = client
        self.max_bytes = max_bytes

    @classmethod
    def from_env(cls) -> "GcsEvidenceStore":
        bucket = os.environ.get("KAORI_OBSERVATIONS_BUCKET", "")
        max_bytes = int(
            os.environ.get("KAORI_MAX_EVIDENCE_BYTES", str(DEFAULT_MAX_EVIDENCE_BYTES))
        )
        return cls(bucket, max_bytes=max_bytes)

    def upload(
        self,
        stream: BinaryIO,
        *,
        filename: str,
        content_type: Optional[str],
        reporter_id: str,
        expected_sha256: Optional[str] = None,
    ) -> EvidenceRef:
        sha256, size = _digest_and_size(stream, self.max_bytes)
        if expected_sha256 and expected_sha256.lower() != sha256:
            raise EvidenceStorageError("evidence sha256 does not match uploaded content")

        reporter_scope = hashlib.sha256(reporter_id.encode("utf-8")).hexdigest()[:16]
        object_name = f"observations/{reporter_scope}/{sha256}/{_safe_filename(filename)}"
        blob = self.client.bucket(self.bucket_name).blob(object_name)
        blob.metadata = {"sha256": sha256}
        blob.cache_control = "private, no-store"
        try:
            blob.upload_from_file(
                stream,
                size=size,
                content_type=content_type or "application/octet-stream",
                if_generation_match=0,
            )
        except Exception as exc:
            from google.api_core.exceptions import PreconditionFailed

            if not isinstance(exc, PreconditionFailed):
                raise EvidenceStorageError("failed to store evidence") from exc
        finally:
            stream.seek(0)

        return EvidenceRef(
            uri=f"gs://{self.bucket_name}/{object_name}",
            sha256=sha256,
            mime_type=content_type,
            bytes_size=size,
        )

    def verify(self, evidence: EvidenceRef, *, reporter_id: str) -> None:
        parsed = urlparse(evidence.uri)
        object_name = parsed.path.lstrip("/")
        reporter_scope = hashlib.sha256(reporter_id.encode("utf-8")).hexdigest()[:16]
        required_prefix = f"observations/{reporter_scope}/"
        if (
            parsed.scheme != "gs"
            or parsed.netloc != self.bucket_name
            or not object_name.startswith(required_prefix)
        ):
            raise EvidenceStorageError(
                "evidence URI is outside the authenticated reporter's Kaori storage scope"
            )
        blob = self.client.bucket(self.bucket_name).get_blob(object_name)
        if blob is None:
            raise EvidenceStorageError("evidence object does not exist")
        stored_sha256 = (blob.metadata or {}).get("sha256", "").lower()
        if stored_sha256 != evidence.sha256.lower():
            raise EvidenceStorageError("evidence hash does not match stored object metadata")
