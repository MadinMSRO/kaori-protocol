"""CPU CLIP generalist for the private kaori-generalist service."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional, Protocol, Sequence
from urllib.parse import quote, urlparse

import yaml
from kaori_truth.primitives.evidence import EvidenceRef
from pydantic import BaseModel, Field, field_validator

from kaori_api.validation import GENERALIST_AGENT_ID

VALIDATOR_SIGNING_KEY_ENV = "KAORI_VALIDATOR_SIGNING_KEY"
DEV_VALIDATOR_SIGNING_KEY = "kaori-dev-validator-key-do-not-use-in-production"
GCP_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)
CLIP_V1_MODEL = "ViT-B-32"
CLIP_V1_PRETRAINED = "openai"


class ValidatorRequest(BaseModel):
    """Private request produced from accepted observations before compilation."""

    truthkey_id: str
    claim_type_id: str
    evidence_refs: List[EvidenceRef]


class ValidationVote(BaseModel):
    """FLOW_SPEC ValidationSignal returned by the private validator service."""

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


class RelevanceModel(Protocol):
    """The single generalist model interface."""

    def score(self, images: Sequence[object], *, context: str, engine: str) -> List[float]: ...


EvidenceLoader = Callable[[EvidenceRef], bytes]


def validator_signing_key() -> bytes:
    return os.environ.get(
        VALIDATOR_SIGNING_KEY_ENV,
        DEV_VALIDATOR_SIGNING_KEY,
    ).encode("utf-8")


def canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validation_vote_signing_payload(vote: ValidationVote) -> bytes:
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
        key or validator_signing_key(),
        validation_vote_signing_payload(vote),
        hashlib.sha256,
    ).hexdigest()
    return vote.model_copy(update={"signature": signature})


def verify_validation_vote(vote: ValidationVote, key: Optional[bytes] = None) -> bool:
    if not vote.signature:
        return False
    expected = hmac.new(
        key or validator_signing_key(),
        validation_vote_signing_payload(vote),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, vote.signature)


class EvidenceContentLoader:
    """Load public HTTP(S) evidence or private gs:// evidence."""

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
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            request = urllib.request.Request(
                evidence.uri,
                headers={"User-Agent": "kaori-generalist/1"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.lstrip("/"):
            raise ValueError("validator evidence must use an http://, https://, or gs:// URI")
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


class OpenClipGeneralist:
    """Open CLIP on CPU: claim-context evidence versus unrelated imagery."""

    def __init__(self) -> None:
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import open_clip

        cache_dir = os.environ.get("KAORI_CLIP_CACHE", "/app/.cache/open_clip")
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            CLIP_V1_MODEL,
            pretrained=CLIP_V1_PRETRAINED,
            device="cpu",
            cache_dir=cache_dir,
        )
        self._tokenizer = open_clip.get_tokenizer(CLIP_V1_MODEL)
        self._model.eval()

    def score(self, images: Sequence[object], *, context: str, engine: str) -> List[float]:
        if engine != "clip_v1":
            raise ValueError(f"unsupported generalist engine: {engine}")
        self._load()
        import torch

        image_batch = torch.stack([self._preprocess(image) for image in images])
        text_batch = self._tokenizer(
            [
                f"evidence of {context}",
                f"a random image unrelated to {context}",
            ]
        )
        with torch.inference_mode():
            image_features = self._model.encode_image(image_batch)
            text_features = self._model.encode_text(text_batch)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            logits = self._model.logit_scale.exp() * image_features @ text_features.T
            relevance = logits.softmax(dim=-1)[:, 0]
        return relevance.cpu().tolist()


class ClipGeneralistValidator:
    """
    Run one CLIP generalist for claim-type relevance.

    Submission rules and specialist routing are deliberately absent. The model
    sees only evidence accepted by the API's submission checks and decides
    whether it is relevant to the ClaimType context or unrelated imagery.
    """

    def __init__(
        self,
        *,
        schema_root: str,
        evidence_loader: Optional[EvidenceLoader] = None,
        model: Optional[RelevanceModel] = None,
        signing_key: Optional[bytes] = None,
    ):
        self.schema_root = Path(schema_root).resolve()
        self._config_cache: Dict[str, dict] = {}
        self.evidence_loader = evidence_loader or EvidenceContentLoader()
        self.model = model or OpenClipGeneralist()
        self.signing_key = signing_key

    def validate(
        self,
        request: ValidatorRequest,
        *,
        timestamp: Optional[datetime] = None,
    ) -> ValidationVote:
        config = self._load_claim_type(request.claim_type_id)
        context, embedding_engine, relevance_threshold = self._generalist_settings(config)

        images = [self._load_image(self.evidence_loader(ref)) for ref in request.evidence_refs]
        relevance = self.model.score(
            images,
            context=context,
            engine=embedding_engine,
        )
        confidence = self._mean_relevance(relevance, len(images))
        vote: Literal["RATIFY", "REJECT"] = (
            "RATIFY" if confidence >= relevance_threshold else "REJECT"
        )
        unsigned = ValidationVote(
            agent_id=GENERALIST_AGENT_ID,
            truthkey_id=request.truthkey_id,
            window_id=f"window:{request.truthkey_id}",
            vote=vote,
            confidence=confidence,
            timestamp=timestamp or datetime.now(timezone.utc),
            signature="",
        )
        return sign_validation_vote(unsigned, self.signing_key)

    def _load_claim_type(self, claim_type_id: str) -> dict:
        cached = self._config_cache.get(claim_type_id)
        if cached is not None:
            return cached
        parts = claim_type_id.split(".")
        if (
            len(parts) != 3
            or not re.fullmatch(r"[a-z0-9_]+", parts[0])
            or not re.fullmatch(r"[a-z0-9_]+", parts[1])
            or not re.fullmatch(r"v[0-9]+", parts[2])
        ):
            raise ValueError("invalid claim_type_id")
        path = self.schema_root / parts[0] / f"{parts[1]}_{parts[2]}.yaml"
        try:
            with path.open("r", encoding="utf-8") as stream:
                config = yaml.safe_load(stream)
        except FileNotFoundError as exc:
            raise ValueError("unknown claim_type_id") from exc
        if not isinstance(config, dict) or config.get("id") != claim_type_id:
            raise ValueError("claim type schema id mismatch")
        self._config_cache[claim_type_id] = config
        return config

    @staticmethod
    def _generalist_settings(config: dict) -> tuple[str, str, float]:
        routing = config.get("ai_validation_routing") or {}
        generalist = routing.get("generalist") or {}
        if generalist.get("engine") != "generalist_v1":
            raise ValueError("claim type must select generalist_v1")
        context = str(generalist.get("prompt_context") or "").strip()
        if not context:
            display = (
                config.get("display_name")
                or config.get("name")
                or config.get("title")
                or str(config.get("topic") or "").replace("_", " ")
            )
            context = str(display).strip()
        if not context:
            raise ValueError("claim type display context is required")

        embedding = (config.get("evidence_similarity") or {}).get("embedding") or {}
        if not embedding.get("enabled"):
            raise ValueError("claim type must enable CLIP relevance")
        engine = str(embedding.get("engine") or "")
        threshold = float(embedding.get("similarity_threshold"))
        return context, engine, threshold

    @staticmethod
    def _load_image(content: bytes) -> object:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as source:
            source.load()
            return source.convert("RGB")

    @staticmethod
    def _mean_relevance(scores: Sequence[float], expected_count: int) -> float:
        if len(scores) != expected_count or not scores:
            raise ValueError("generalist returned invalid relevance scores")
        if not all(math.isfinite(score) and 0.0 <= score <= 1.0 for score in scores):
            raise ValueError("generalist returned invalid relevance scores")
        return round(sum(scores) / len(scores), 6)
