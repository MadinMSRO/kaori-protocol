"""Tests for truth signing."""
import pytest

from core.models import TruthKey, TruthState, TruthStatus, Domain, SpatialSystem
from core.signing import (
    compute_truth_hash,
    sign_truth_state,
    verify_truth_state,
    sign_with_hmac,
    verify_hmac,
    canonical_json,
)


class TestCanonicalJson:
    """Test canonical JSON serialization."""
    
    def test_sorted_keys(self):
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(obj)
        assert result == '{"a":2,"m":3,"z":1}'
    
    def test_no_whitespace(self):
        obj = {"key": "value", "num": 42}
        result = canonical_json(obj)
        assert " " not in result
        assert "\n" not in result
    
    def test_deterministic(self):
        obj = {"a": 1, "b": 2}
        result1 = canonical_json(obj)
        result2 = canonical_json(obj)
        assert result1 == result2


class TestTruthHash:
    """Test truth hash computation."""
    
    @pytest.fixture
    def truth_state(self):
        return TruthState(
            truthkey=TruthKey(
                domain=Domain.EARTH,
                topic="flood",
                spatial_system=SpatialSystem.H3,
                spatial_id="8928308280fffff",
                z_index="surface",
                time_bucket="2026-01-02T10:00Z",
            ),
            claim_type="earth.flood.v1",
            status=TruthStatus.VERIFIED_TRUE,
        )
    
    def test_hash_is_hex(self, truth_state):
        hash_val = compute_truth_hash(truth_state)
        assert all(c in "0123456789abcdef" for c in hash_val)
    
    def test_hash_length(self, truth_state):
        hash_val = compute_truth_hash(truth_state)
        assert len(hash_val) == 64  # SHA256 = 32 bytes = 64 hex chars
    
    def test_hash_deterministic(self, truth_state):
        hash1 = compute_truth_hash(truth_state)
        hash2 = compute_truth_hash(truth_state)
        assert hash1 == hash2
    
    def test_hash_changes_with_status(self, truth_state):
        hash1 = compute_truth_hash(truth_state)
        truth_state.status = TruthStatus.VERIFIED_FALSE
        hash2 = compute_truth_hash(truth_state)
        assert hash1 != hash2


class TestHmacSigning:
    """Test local HMAC signing."""
    
    def test_sign_and_verify(self):
        hash_val = "abc123def456"
        signature = sign_with_hmac(hash_val)
        assert verify_hmac(hash_val, signature)
    
    def test_invalid_signature(self):
        hash_val = "abc123def456"
        assert not verify_hmac(hash_val, "invalid_signature")
    
    def test_different_hashes_different_signatures(self):
        sig1 = sign_with_hmac("hash1")
        sig2 = sign_with_hmac("hash2")
        assert sig1 != sig2


class TestTruthStateSigning:
    """Test full truth state signing and verification."""
    
    @pytest.fixture
    def truth_state(self):
        return TruthState(
            truthkey=TruthKey(
                domain=Domain.EARTH,
                topic="flood",
                spatial_system=SpatialSystem.H3,
                spatial_id="8928308280fffff",
                z_index="surface",
                time_bucket="2026-01-02T10:00Z",
            ),
            claim_type="earth.flood.v1",
            status=TruthStatus.VERIFIED_TRUE,
        )
    
    def test_sign_truth_state(self, truth_state):
        security = sign_truth_state(truth_state)
        
        assert security.truth_hash is not None
        assert security.truth_signature is not None
        assert security.signing_method == "local_hmac"
        assert security.signed_at is not None
    
    def test_verify_signed_state(self, truth_state):
        truth_state.security = sign_truth_state(truth_state)
        assert verify_truth_state(truth_state) is True
    
    def test_verify_tampered_state(self, truth_state):
        truth_state.security = sign_truth_state(truth_state)
        # Tamper with the state
        truth_state.status = TruthStatus.VERIFIED_FALSE
        assert verify_truth_state(truth_state) is False
    
    def test_verify_unsigned_state(self, truth_state):
        assert verify_truth_state(truth_state) is False
