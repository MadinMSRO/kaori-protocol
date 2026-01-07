"""
Kaori Truth — Signing

Cryptographic signing for truth states.
Implements semantic_hash vs state_hash signing.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime

from kaori_truth.primitives.truthstate import TruthState, SecurityBlock


# Signing configuration
SIGNING_METHOD = os.environ.get("KAORI_SIGNING_METHOD", "local_hmac")
LOCAL_SIGNING_KEY = os.environ.get(
    "KAORI_SIGNING_KEY",
    "kaori-dev-signing-key-do-not-use-in-production"
).encode("utf-8")


def sign_with_hmac(data: str, key: bytes = LOCAL_SIGNING_KEY) -> str:
    """Sign data using HMAC-SHA256."""
    signature = hmac.new(key, data.encode("utf-8"), hashlib.sha256)
    return signature.hexdigest()


def sign_truth_state(
    truth_state: TruthState,
    sign_time: datetime,
    key_id: str = "local_dev_key",
) -> TruthState:
    """
    Sign a TruthState and return with populated SecurityBlock.
    
    Signs the state_hash (full envelope including compile_time).
    
    Args:
        truth_state: The TruthState to sign
        sign_time: Explicit signing time (NOT wall-clock)
        key_id: Key identifier
        
    Returns:
        TruthState with populated SecurityBlock
    """
    # Compute hashes
    semantic_hash = truth_state.compute_semantic_hash()
    state_hash = truth_state.compute_state_hash()
    
    # Sign the state_hash
    signature = sign_with_hmac(state_hash)
    
    # Update security block
    truth_state.security = SecurityBlock(
        semantic_hash=semantic_hash,
        state_hash=state_hash,
        signature=signature,
        signing_method="local_hmac",
        key_id=key_id,
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
    
    # Verify hashes match
    if not truth_state.verify_hashes():
        return False
    
    # Verify signature
    expected = sign_with_hmac(truth_state.security.state_hash)
    return hmac.compare_digest(expected, truth_state.security.signature)
