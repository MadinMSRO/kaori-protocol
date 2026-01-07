"""
Kaori Truth — Test Suite for Canonicalization

Tests that verify canonical serialization produces identical output.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from kaori_truth.canonical import (
    canonical_json,
    canonical_hash,
    canonicalize,
)
from kaori_truth.canonical.string import (
    normalize_unicode,
    canonical_string,
    validate_canonical_id,
    to_canonical_id,
)
from kaori_truth.canonical.float import (
    canonical_float,
    quantize_float,
)
from kaori_truth.canonical.datetime import (
    canonical_datetime,
    ensure_utc,
    NaiveDatetimeError,
)
from kaori_truth.canonical.uri import (
    canonical_uri,
    normalize_evidence_ref,
    canonical_evidence_hash,
)


class TestCanonicalJSON:
    """Tests for canonical JSON serialization."""
    
    def test_sorted_keys(self):
        """Keys MUST be sorted alphabetically."""
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(obj)
        
        assert result == '{"a":2,"m":3,"z":1}'
    
    def test_minimal_separators(self):
        """Separators MUST be minimal (',', ':')."""
        obj = {"key": "value"}
        result = canonical_json(obj)
        
        assert result == '{"key":"value"}'
        assert " " not in result  # No whitespace
    
    def test_nested_objects_sorted(self):
        """Nested objects MUST also have sorted keys."""
        obj = {"outer": {"z": 1, "a": 2}}
        result = canonical_json(obj)
        
        assert result == '{"outer":{"a":2,"z":1}}'
    
    def test_same_object_twice_identical(self):
        """Same object serialized twice MUST produce identical output."""
        obj = {"key": "value", "number": 42, "nested": {"a": 1}}
        
        result1 = canonical_json(obj)
        result2 = canonical_json(obj)
        
        assert result1 == result2


class TestUnicodeNormalization:
    """Tests for Unicode normalization."""
    
    def test_nfc_normalization(self):
        """Unicode MUST be NFC normalized."""
        # é as single char vs e + combining acute
        single_char = "\u00e9"  # é
        combined = "e\u0301"  # e + ́
        
        normalized_single = normalize_unicode(single_char)
        normalized_combined = normalize_unicode(combined)
        
        # Both should normalize to the same NFC form
        assert normalized_single == normalized_combined
    
    def test_canonical_string_whitespace(self):
        """Whitespace MUST be normalized."""
        s = "  hello   world  "
        result = canonical_string(s)
        
        assert result == "hello world"


class TestFloatQuantization:
    """Tests for float quantization."""
    
    def test_float_precision(self):
        """Floats MUST be quantized to fixed precision."""
        # Different representations of "same" value
        result1 = canonical_float(0.1 + 0.2)  # 0.30000000000000004 in float
        result2 = canonical_float(0.3)
        
        assert result1 == result2
    
    def test_trailing_zeros_removed(self):
        """Trailing zeros after decimal MUST be removed."""
        result = canonical_float(1.0)
        assert result == "1"
        
        result = canonical_float(1.50)
        assert result == "1.5"
    
    def test_negative_zero(self):
        """Negative zero MUST become positive zero."""
        result = canonical_float(-0.0)
        assert result == "0"


class TestDatetimeCanonicalization:
    """Tests for datetime canonicalization."""
    
    def test_utc_output(self):
        """Output MUST always be UTC with Z suffix."""
        # UTC input
        dt = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = canonical_datetime(dt)
        
        assert result.endswith("Z")
        assert result == "2026-01-07T12:00:00Z"
    
    def test_timezone_conversion(self):
        """Non-UTC datetimes MUST be converted to UTC."""
        from datetime import timedelta
        
        # UTC+8
        tz_plus8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 1, 7, 20, 0, 0, tzinfo=tz_plus8)
        
        result = canonical_datetime(dt)
        
        # Should be converted to UTC (12:00 UTC)
        assert "12:00:00Z" in result
    
    def test_naive_datetime_rejected(self):
        """Naive datetimes MUST be rejected by default."""
        dt = datetime(2026, 1, 7, 12, 0, 0)  # No tzinfo
        
        with pytest.raises(NaiveDatetimeError):
            ensure_utc(dt)
    
    def test_same_instant_different_tz(self):
        """Same instant in different timezones MUST produce identical output."""
        from datetime import timedelta
        
        utc = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        
        tz_plus8 = timezone(timedelta(hours=8))
        local = datetime(2026, 1, 7, 20, 0, 0, tzinfo=tz_plus8)
        
        result_utc = canonical_datetime(utc)
        result_local = canonical_datetime(local)
        
        assert result_utc == result_local


class TestURICanonicalization:
    """Tests for URI canonicalization."""
    
    def test_scheme_lowercase(self):
        """Scheme MUST be lowercase."""
        result = canonical_uri("HTTPS://Example.com/path")
        assert result.startswith("https://")
    
    def test_host_lowercase(self):
        """Host MUST be lowercase."""
        result = canonical_uri("https://EXAMPLE.COM/path")
        assert "example.com" in result
    
    def test_trailing_slash_removed(self):
        """Trailing slashes MUST be removed (except root)."""
        result = canonical_uri("https://example.com/path/")
        assert not result.endswith("/")
    
    def test_query_params_sorted(self):
        """Query parameters MUST be sorted."""
        result = canonical_uri("https://example.com?z=1&a=2")
        assert "a=2" in result and "z=1" in result
        assert result.index("a=2") < result.index("z=1")
    
    def test_evidence_hash_lowercase(self):
        """Evidence hashes MUST be lowercase."""
        result = canonical_evidence_hash("ABCD" + "0" * 60)
        assert result == "abcd" + "0" * 60


class TestCanonicalID:
    """Tests for canonical ID validation."""
    
    def test_valid_ids(self):
        """Valid IDs should pass validation."""
        assert validate_canonical_id("earth.flood.v1")
        assert validate_canonical_id("agent-001")
        assert validate_canonical_id("test_value")
    
    def test_invalid_ids(self):
        """Invalid IDs should fail validation."""
        assert not validate_canonical_id("Invalid")  # Uppercase
        assert not validate_canonical_id("hello world")  # Space
        assert not validate_canonical_id("test@value")  # @
    
    def test_conversion_to_canonical(self):
        """Strings should be convertible to canonical IDs."""
        result = to_canonical_id("Hello World!")
        assert validate_canonical_id(result)
        assert result == "hello_world"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
