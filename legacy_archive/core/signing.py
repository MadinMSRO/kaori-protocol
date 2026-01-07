"""
Kaori Core — Truth Signing

TruthHash computation and signature generation (SPEC Section 16).

For production, use GCP KMS. For development/testing, use local HMAC signing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any

from .models import SecurityBlock, TruthState


# =============================================================================
# Configuration
# =============================================================================

# Signing method: "local_hmac" or "gcp_kms"
SIGNING_METHOD = os.environ.get("KAORI_SIGNING_METHOD", "local_hmac")

# Local HMAC key (for development/testing)
# In production, this would come from a secure secret manager
LOCAL_SIGNING_KEY = os.environ.get(
    "KAORI_SIGNING_KEY",
    "kaori-dev-signing-key-do-not-use-in-production"
).encode("utf-8")

# GCP KMS key ID (for production)
GCP_KMS_KEY_ID = os.environ.get("KAORI_KMS_KEY_ID", "")


# =============================================================================
# Canonical JSON Serialization
# =============================================================================

def canonical_json(obj: dict[str, Any]) -> str:
    """
    Serialize object to canonical JSON (sorted keys, no whitespace).
    
    This ensures deterministic hash computation.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def truth_state_to_signable(truth_state: TruthState) -> dict:
    """
    Extract the signable fields from a TruthState.
    
    Only includes fields that should be part of the hash.
    """
    return {
        "truthkey": truth_state.truthkey.to_string(),
        "claim_type": truth_state.claim_type,
        "status": truth_state.status.value,
        "verification_basis": truth_state.verification_basis.value if truth_state.verification_basis else None,
        "ai_confidence": truth_state.ai_confidence,
        "confidence": truth_state.confidence,
        "transparency_flags": truth_state.transparency_flags,
        "updated_at": truth_state.updated_at.isoformat(),
        "evidence_refs": truth_state.evidence_refs,
        "observation_ids": [str(oid) for oid in truth_state.observation_ids],
    }


# =============================================================================
# Hash Computation
# =============================================================================

def compute_truth_hash(truth_state: TruthState) -> str:
    """
    Compute SHA256 hash of a TruthState.
    
    Formula: truth_hash = SHA256(canonical_json(signable_fields))
    
    Args:
        truth_state: The TruthState to hash
        
    Returns:
        Hex-encoded SHA256 hash
    """
    signable = truth_state_to_signable(truth_state)
    canonical = canonical_json(signable)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =============================================================================
# Local HMAC Signing (Development/Testing)
# =============================================================================

def sign_with_hmac(hash_value: str, key: bytes = LOCAL_SIGNING_KEY) -> str:
    """
    Sign a hash using HMAC-SHA256.
    
    Args:
        hash_value: The hash to sign
        key: The signing key
        
    Returns:
        Hex-encoded HMAC signature
    """
    signature = hmac.new(key, hash_value.encode("utf-8"), hashlib.sha256)
    return signature.hexdigest()


def verify_hmac(hash_value: str, signature: str, key: bytes = LOCAL_SIGNING_KEY) -> bool:
    """
    Verify an HMAC signature.
    
    Args:
        hash_value: The original hash
        signature: The signature to verify
        key: The signing key
        
    Returns:
        True if signature is valid
    """
    expected = sign_with_hmac(hash_value, key)
    return hmac.compare_digest(expected, signature)


# =============================================================================
# GCP KMS Signing (Production)
# =============================================================================

def sign_with_kms(hash_value: str, key_id: str = GCP_KMS_KEY_ID) -> str:
    """
    Sign a hash using GCP KMS.
    
    Args:
        hash_value: The hash to sign
        key_id: The KMS key resource ID
        
    Returns:
        Base64-encoded signature
        
    Raises:
        ImportError: If google-cloud-kms not installed
        RuntimeError: If signing fails
    """
    try:
        from google.cloud import kms
        import base64
    except ImportError:
        raise ImportError(
            "google-cloud-kms is required for KMS signing. "
            "Install with: pip install google-cloud-kms"
        )
    
    if not key_id:
        raise RuntimeError("KAORI_KMS_KEY_ID environment variable not set")
    
    client = kms.KeyManagementServiceClient()
    
    # Hash the hash value (KMS signs digests, not raw data)
    digest = hashlib.sha256(hash_value.encode("utf-8")).digest()
    
    # Sign
    response = client.asymmetric_sign(
        request={
            "name": key_id,
            "digest": {"sha256": digest},
        }
    )
    
    return base64.b64encode(response.signature).decode("utf-8")


def verify_kms(hash_value: str, signature: str, key_id: str = GCP_KMS_KEY_ID) -> bool:
    """
    Verify a KMS signature.
    
    Args:
        hash_value: The original hash
        signature: The base64-encoded signature
        key_id: The KMS key resource ID
        
    Returns:
        True if signature is valid
    """
    try:
        from google.cloud import kms
        import base64
    except ImportError:
        return False
    
    if not key_id:
        return False
    
    client = kms.KeyManagementServiceClient()
    
    # Get public key
    public_key_response = client.get_public_key(request={"name": key_id})
    
    # Verify using cryptography library
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, utils
    
    public_key = serialization.load_pem_public_key(
        public_key_response.pem.encode("utf-8")
    )
    
    digest = hashlib.sha256(hash_value.encode("utf-8")).digest()
    sig_bytes = base64.b64decode(signature)
    
    try:
        public_key.verify(
            sig_bytes,
            digest,
            padding.PKCS1v15(),
            utils.Prehashed(hashes.SHA256()),
        )
        return True
    except Exception:
        return False


# =============================================================================
# Unified Signing Interface
# =============================================================================

def sign_truth_hash(hash_value: str) -> tuple[str, str, str]:
    """
    Sign a truth hash using configured signing method.
    
    Args:
        hash_value: The hash to sign
        
    Returns:
        Tuple of (signature, signing_method, key_id)
    """
    if SIGNING_METHOD == "gcp_kms" and GCP_KMS_KEY_ID:
        signature = sign_with_kms(hash_value, GCP_KMS_KEY_ID)
        return signature, "gcp_kms", GCP_KMS_KEY_ID
    else:
        signature = sign_with_hmac(hash_value)
        return signature, "local_hmac", "local_dev_key"


def verify_truth_signature(
    hash_value: str,
    signature: str,
    signing_method: str,
    key_id: str,
) -> bool:
    """
    Verify a truth signature.
    
    Args:
        hash_value: The original hash
        signature: The signature to verify
        signing_method: "local_hmac" or "gcp_kms"
        key_id: The key identifier
        
    Returns:
        True if signature is valid
    """
    if signing_method == "gcp_kms":
        return verify_kms(hash_value, signature, key_id)
    else:
        return verify_hmac(hash_value, signature)


def sign_truth_state(truth_state: TruthState) -> SecurityBlock:
    """
    Compute hash and sign a TruthState.
    
    Args:
        truth_state: The TruthState to sign
        
    Returns:
        SecurityBlock with hash, signature, and metadata
    """
    truth_hash = compute_truth_hash(truth_state)
    signature, method, key_id = sign_truth_hash(truth_hash)
    
    return SecurityBlock(
        truth_hash=truth_hash,
        truth_signature=signature,
        signing_method=method,
        key_id=key_id,
        signed_at=datetime.now(timezone.utc),
    )


def verify_truth_state(truth_state: TruthState) -> bool:
    """
    Verify the signature of a TruthState.
    
    Args:
        truth_state: The TruthState to verify
        
    Returns:
        True if signature is valid and hash matches
    """
    if not truth_state.security:
        return False
    
    # Recompute hash
    current_hash = compute_truth_hash(truth_state)
    
    # Check hash matches
    if current_hash != truth_state.security.truth_hash:
        return False
    
    # Verify signature
    return verify_truth_signature(
        truth_state.security.truth_hash,
        truth_state.security.truth_signature,
        truth_state.security.signing_method,
        truth_state.security.key_id,
    )
