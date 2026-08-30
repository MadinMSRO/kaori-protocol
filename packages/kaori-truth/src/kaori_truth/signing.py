"""
Kaori Truth — Signing

Cryptographic signing for truth states.
Implements semantic_hash vs state_hash signing.

Production TruthState signing is a dedicated configuration
(KAORI_SIGNING_KEY / KAORI_SIGNING_KEY_ID). It must never silently fall
back to the repository development key when Cloud SQL is configured, and
it must stay distinct from the generalist validator HMAC
(KAORI_VALIDATOR_SIGNING_KEY).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime
from typing import Optional

from kaori_truth.primitives.truthstate import TruthState, SecurityBlock


SIGNING_METHOD = os.environ.get("KAORI_SIGNING_METHOD", "local_hmac")
DEV_SIGNING_KEY = "kaori-dev-signing-key-do-not-use-in-production"
DEV_SIGNING_KEY_ID = "local_dev_key"


class SigningConfigError(RuntimeError):
    """Production TruthState signing is missing or unsafe."""


def database_url_is_cloud_sql(url: Optional[str] = None) -> bool:
    """True when DATABASE_URL points at Postgres / Cloud SQL (not sqlite, not unset)."""
    raw = os.environ.get("DATABASE_URL", "") if url is None else url
    if not raw:
        return False
    lowered = raw.strip().lower()
    if lowered.startswith("sqlite"):
        return False
    return lowered.startswith("postgres") or "cloudsql" in lowered


def production_signing_required(url: Optional[str] = None) -> bool:
    """Cloud SQL or an explicit production environment requires a dedicated signing key."""
    environment = os.environ.get("KAORI_ENVIRONMENT", "").strip().lower()
    return database_url_is_cloud_sql(url) or environment == "production"


def _configured_signing_key() -> Optional[str]:
    value = os.environ.get("KAORI_SIGNING_KEY")
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _configured_signing_key_id() -> Optional[str]:
    value = os.environ.get("KAORI_SIGNING_KEY_ID")
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validator_signing_key() -> Optional[str]:
    for name in ("KAORI_VALIDATOR_SIGNING_KEY", "DEV_VALIDATOR_SIGNING_KEY"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def signing_config() -> tuple[bytes, str]:
    """
    Resolve the TruthState HMAC key and key id.

    Local / in-memory runs may use the development key. Any Cloud SQL
    DATABASE_URL (or KAORI_ENVIRONMENT=production) must supply a distinct
    production secret and key id.
    """
    key = _configured_signing_key()
    key_id = _configured_signing_key_id()
    validator_key = _validator_signing_key()

    if production_signing_required():
        if key is None or key == DEV_SIGNING_KEY:
            raise SigningConfigError(
                "KAORI_SIGNING_KEY must be set to a dedicated production secret "
                "when DATABASE_URL points at Cloud SQL. The repository development "
                "signing key is forbidden."
            )
        if key_id is None or key_id == DEV_SIGNING_KEY_ID:
            raise SigningConfigError(
                "KAORI_SIGNING_KEY_ID must be set to a dedicated production key id "
                "when DATABASE_URL points at Cloud SQL. local_dev_key is forbidden."
            )
        if validator_key and key == validator_key:
            raise SigningConfigError(
                "KAORI_SIGNING_KEY must be distinct from KAORI_VALIDATOR_SIGNING_KEY. "
                "TruthState signing is not the generalist validator HMAC."
            )
        return key.encode("utf-8"), key_id

    resolved_key = key or DEV_SIGNING_KEY
    if validator_key and resolved_key == validator_key and resolved_key != DEV_SIGNING_KEY:
        raise SigningConfigError(
            "KAORI_SIGNING_KEY must be distinct from KAORI_VALIDATOR_SIGNING_KEY."
        )
    return resolved_key.encode("utf-8"), key_id or DEV_SIGNING_KEY_ID


def require_production_signing_config() -> tuple[bytes, str]:
    """Fail fast at API boot when Cloud SQL is configured without production signing."""
    return signing_config()


def sign_with_hmac(data: str, key: Optional[bytes] = None) -> str:
    """Sign data using HMAC-SHA256."""
    resolved = key if key is not None else signing_config()[0]
    signature = hmac.new(resolved, data.encode("utf-8"), hashlib.sha256)
    return signature.hexdigest()


def sign_truth_state(
    truth_state: TruthState,
    sign_time: datetime,
    key_id: Optional[str] = None,
) -> TruthState:
    """
    Sign a TruthState and return with populated SecurityBlock.

    Signs the state_hash (full envelope including compile_time).
    """
    key, configured_id = signing_config()
    semantic_hash = truth_state.compute_semantic_hash()
    state_hash = truth_state.compute_state_hash()
    signature = sign_with_hmac(state_hash, key)

    truth_state.security = SecurityBlock(
        semantic_hash=semantic_hash,
        state_hash=state_hash,
        signature=signature,
        signing_method="local_hmac",
        key_id=key_id or configured_id,
        signed_at=sign_time,
    )

    return truth_state


def verify_signature(truth_state: TruthState) -> bool:
    """
    Verify the signature of a TruthState.

    Returns:
        True if signature is valid and hashes match
    """
    if not truth_state.security:
        return False

    if not truth_state.verify_hashes():
        return False

    expected = sign_with_hmac(truth_state.security.state_hash)
    return hmac.compare_digest(expected, truth_state.security.signature)


# Backward-compatible alias. Callers must not treat this as a production default.
LOCAL_SIGNING_KEY = DEV_SIGNING_KEY.encode("utf-8")
