"""Deterministic coral bouncer checks and ValidationSignal signing."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional
from urllib.parse import quote, urlparse

import yaml
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation
from kaori_truth.primitives.truthkey import parse_truthkey
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from kaori_api.validation import BOUNCER_AGENT_ID

CORAL_CLAIM_TYPE = "ocean.coral_bleaching.v1"
BOUNCER_SIGNING_KEY_ENV = "KAORI_BOUNCER_SIGNING_KEY"
DEV_BOUNCER_SIGNING_KEY = "kaori-dev-bouncer-key-do-not-use-in-production"
GCP_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class BouncerRequest(BaseModel):
    """Private service request produced after a TruthState has been persisted."""

    truthkey_id: str
    claim_type_id: str
    observations: List[Observation]


class ValidationVote(BaseModel):
    """FLOW_SPEC ValidationSignal returned by the private bouncer service."""

    agent_id: str
    truthkey_id: str
    window_id: str
    vote: Literal["RATIFY", "REJECT", "ABSTAIN"]
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime
    signature: str

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


EvidenceLoader = Callable[[EvidenceRef], bytes]


def bouncer_signing_key() -> bytes:
    """Read the bouncer HMAC key at call time so secret rotation is observable."""
    return os.environ.get(BOUNCER_SIGNING_KEY_ENV, DEV_BOUNCER_SIGNING_KEY).encode("utf-8")


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validation_vote_signing_payload(vote: ValidationVote) -> bytes:
    """Canonical bytes signed by ai:bouncer_v1 (signature itself is excluded)."""
    payload = {
        "agent_id": vote.agent_id,
        "truthkey_id": vote.truthkey_id,
        "window_id": vote.window_id,
        "vote": vote.vote,
        "timestamp": canonical_timestamp(vote.timestamp),
    }
    if vote.confidence is not None:
        payload["confidence"] = vote.confidence
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_validation_vote(vote: ValidationVote, key: Optional[bytes] = None) -> ValidationVote:
    signature = hmac.new(
        key or bouncer_signing_key(),
        validation_vote_signing_payload(vote),
        hashlib.sha256,
    ).hexdigest()
    return vote.model_copy(update={"signature": signature})


def verify_validation_vote(vote: ValidationVote, key: Optional[bytes] = None) -> bool:
    if not vote.signature:
        return False
    expected = hmac.new(
        key or bouncer_signing_key(),
        validation_vote_signing_payload(vote),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, vote.signature)


class GcsEvidenceLoader:
    """Load private gs:// evidence with the Cloud Run service account."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def _access_token(self) -> str:
        request = urllib.request.Request(
            GCP_METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("access_token")
        if not token:
            raise ValueError("metadata server did not return an access token")
        return str(token)

    def __call__(self, evidence: EvidenceRef) -> bytes:
        parsed = urlparse(evidence.uri)
        if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.lstrip("/"):
            raise ValueError("bouncer evidence must use a gs:// URI")
        object_name = quote(parsed.path.lstrip("/"), safe="")
        url = (
            "https://storage.googleapis.com/download/storage/v1/b/"
            f"{quote(parsed.netloc, safe='')}/o/{object_name}?alt=media"
        )
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._access_token()}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()


class CoralBouncer:
    """Execute only the checks listed in coral ai_validation_routing.bouncer."""

    def __init__(
        self,
        *,
        schema_path: str,
        evidence_loader: Optional[EvidenceLoader] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.schema_path = Path(schema_path)
        self.evidence_loader = evidence_loader or GcsEvidenceLoader()
        self.signing_key = signing_key
        with self.schema_path.open("r", encoding="utf-8") as stream:
            self.config = yaml.safe_load(stream)
        if self.config.get("id") != CORAL_CLAIM_TYPE:
            raise ValueError("bouncer schema must be ocean.coral_bleaching.v1")
        routing = (self.config.get("ai_validation_routing") or {}).get("bouncer") or {}
        self.checks = routing.get("checks") or []
        if not self.checks:
            raise ValueError("coral bouncer checks are required")

    def validate(
        self,
        request: BouncerRequest,
        *,
        timestamp: Optional[datetime] = None,
    ) -> ValidationVote:
        if request.claim_type_id != CORAL_CLAIM_TYPE:
            raise ValueError("bouncer only supports ocean.coral_bleaching.v1")

        check_results = [
            self._run_configured_check(check, request)
            for check in self.checks
        ]
        passed = all(check_results)
        unsigned = ValidationVote(
            agent_id=BOUNCER_AGENT_ID,
            truthkey_id=request.truthkey_id,
            window_id=f"window:{request.truthkey_id}",
            vote="RATIFY" if passed else "REJECT",
            timestamp=timestamp or datetime.now(timezone.utc),
            signature="",
        )
        return sign_validation_vote(unsigned, self.signing_key)

    def _run_configured_check(self, configured: object, request: BouncerRequest) -> bool:
        if isinstance(configured, str):
            name, argument = configured, None
        elif isinstance(configured, dict) and len(configured) == 1:
            name, argument = next(iter(configured.items()))
        else:
            raise ValueError("invalid coral bouncer check configuration")

        checks = {
            "evidence_present": lambda: self._evidence_present(request),
            "evidence_quality_min": lambda: self._evidence_quality_min(request, float(argument)),
            "duplicate_hash_check": lambda: self._duplicate_hash_check(request),
            "geolocation_plausibility": lambda: self._geolocation_plausibility(request),
            "depth_consistency": lambda: self._depth_consistency(request),
        }
        if name not in checks:
            raise ValueError(f"unsupported coral bouncer check: {name}")
        return checks[name]()

    def _all_evidence(self, request: BouncerRequest) -> List[EvidenceRef]:
        return [ref for observation in request.observations for ref in observation.evidence_refs]

    def _evidence_present(self, request: BouncerRequest) -> bool:
        evidence_config = self.config.get("evidence") or {}
        count = len(self._all_evidence(request))
        minimum = int(evidence_config.get("min_count", 1))
        maximum = int(evidence_config.get("max_count", count))
        return bool(request.observations) and minimum <= count <= maximum

    def _evidence_quality_min(self, request: BouncerRequest, minimum: float) -> bool:
        refs = self._all_evidence(request)
        if not refs:
            return False
        usable = 0
        for ref in refs:
            try:
                content = self.evidence_loader(ref)
                is_usable = self._usable_evidence(ref, content)
            except (OSError, TypeError, ValueError, TimeoutError, urllib.error.URLError):
                continue
            if is_usable:
                usable += 1
        return usable / len(refs) >= minimum

    @staticmethod
    def _usable_evidence(ref: EvidenceRef, content: bytes) -> bool:
        if not content:
            return False
        suffix = Path(urlparse(ref.uri).path).suffix.lower()
        is_image = (ref.mime_type or "").lower().startswith("image/") or suffix in IMAGE_SUFFIXES
        if not is_image:
            return True
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            return True
        except (OSError, UnidentifiedImageError):
            return False

    def _duplicate_hash_check(self, request: BouncerRequest) -> bool:
        hashes = [ref.sha256.lower() for ref in self._all_evidence(request)]
        return len(hashes) == len(set(hashes))

    @staticmethod
    def _geolocation_plausibility(request: BouncerRequest) -> bool:
        for observation in request.observations:
            lat = observation.geo.get("lat")
            lon = observation.geo.get("lon")
            if (
                isinstance(lat, bool)
                or isinstance(lon, bool)
                or not isinstance(lat, (int, float))
                or not isinstance(lon, (int, float))
                or not math.isfinite(float(lat))
                or not math.isfinite(float(lon))
                or not -90.0 <= float(lat) <= 90.0
                or not -180.0 <= float(lon) <= 180.0
            ):
                return False
        return bool(request.observations)

    def _depth_consistency(self, request: BouncerRequest) -> bool:
        try:
            key = parse_truthkey(request.truthkey_id)
        except ValueError:
            return False
        truthkey_config = self.config.get("truthkey") or {}
        if key.z_index != truthkey_config.get("z_index"):
            return False

        depth_field: Dict[str, object] = {}
        for field in ((self.config.get("ui_schema") or {}).get("fields") or []):
            if field.get("name") == "depth_meters":
                depth_field = field
                break
        bounds = depth_field.get("validation") or {}
        minimum = float(bounds.get("min", float("-inf")))
        maximum = float(bounds.get("max", float("inf")))
        for observation in request.observations:
            depth = (observation.payload or {}).get("depth_meters")
            if (
                isinstance(depth, bool)
                or not isinstance(depth, (int, float))
                or not math.isfinite(float(depth))
                or not minimum <= float(depth) <= maximum
            ):
                return False
            if (
                observation.depth_meters is not None
                and float(observation.depth_meters) != float(depth)
            ):
                return False
        return bool(request.observations)
