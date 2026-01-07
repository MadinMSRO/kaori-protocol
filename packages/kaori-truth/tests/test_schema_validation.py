"""
Tests for claim payload schema validation.

Covers:
- Schema validation determinism
- Valid payloads pass
- Invalid payloads fail with deterministic errors
- Canonicalization of validated payloads
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from kaori_truth.validation import (
    validate_claim_payload,
    SchemaValidationError,
    ErrorCode,
)
from kaori_truth.primitives.claimtype import ClaimType, TruthKeyConfig


class TestSchemaValidation:
    """Test schema validation functionality."""
    
    def test_valid_payload_passes(self):
        """Valid payload should pass validation."""
        schema = {
            "type": "object",
            "required": ["severity", "water_level_meters"],
            "properties": {
                "severity": {"type": "string", "enum": ["low", "moderate", "high"]},
                "water_level_meters": {"type": "number", "minimum": 0},
            }
        }
        
        payload = {
            "severity": "high",
            "water_level_meters": 2.5,
        }
        
        result = validate_claim_payload(payload, schema)
        
        assert result["severity"] == "high"
        assert result["water_level_meters"] == 2.5
    
    def test_missing_required_field_fails(self):
        """Missing required field should raise SchemaValidationError."""
        schema = {
            "type": "object",
            "required": ["severity"],
            "properties": {
                "severity": {"type": "string"},
            }
        }
        
        payload = {}  # Missing severity
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_claim_payload(payload, schema)
        
        assert ErrorCode.REQUIRED in str(exc_info.value)
        assert "$.severity" in str(exc_info.value)
    
    def test_type_mismatch_fails(self):
        """Type mismatch should raise SchemaValidationError."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            }
        }
        
        payload = {"count": "not-a-number"}
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_claim_payload(payload, schema)
        
        assert ErrorCode.TYPE_MISMATCH in str(exc_info.value)
    
    def test_enum_invalid_fails(self):
        """Invalid enum value should raise SchemaValidationError."""
        schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "inactive"]},
            }
        }
        
        payload = {"status": "unknown"}
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_claim_payload(payload, schema)
        
        assert ErrorCode.ENUM_INVALID in str(exc_info.value)
    
    def test_minimum_validation(self):
        """Value below minimum should fail."""
        schema = {
            "type": "object",
            "properties": {
                "temperature": {"type": "number", "minimum": -273.15},
            }
        }
        
        payload = {"temperature": -500}
        
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_claim_payload(payload, schema)
        
        assert ErrorCode.MINIMUM in str(exc_info.value)
    
    def test_validation_is_deterministic(self):
        """Validation errors must be deterministic."""
        schema = {
            "type": "object",
            "required": ["a", "b", "c"],
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
            }
        }
        
        payload = {}  # Missing all fields
        
        # Validate multiple times
        errors_list = []
        for _ in range(10):
            try:
                validate_claim_payload(payload, schema)
            except SchemaValidationError as e:
                errors_list.append(str(e))
        
        # All error messages should be identical
        assert len(set(errors_list)) == 1, "Validation errors must be deterministic"
    
    def test_nested_object_validation(self):
        """Nested object validation should work."""
        schema = {
            "type": "object",
            "properties": {
                "location": {
                    "type": "object",
                    "required": ["lat", "lon"],
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                    }
                }
            }
        }
        
        # Valid nested object
        valid_payload = {
            "location": {"lat": 1.0, "lon": 2.0}
        }
        result = validate_claim_payload(valid_payload, schema)
        assert result["location"]["lat"] == 1.0
        
        # Invalid nested object
        invalid_payload = {
            "location": {"lat": "not-a-number"}
        }
        with pytest.raises(SchemaValidationError):
            validate_claim_payload(invalid_payload, schema)
    
    def test_array_validation(self):
        """Array validation should work."""
        schema = {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }
        
        # Valid array
        valid_payload = {"tags": ["flood", "urgent"]}
        result = validate_claim_payload(valid_payload, schema)
        assert result["tags"] == ["flood", "urgent"]
        
        # Invalid array item
        invalid_payload = {"tags": ["valid", 123]}
        with pytest.raises(SchemaValidationError):
            validate_claim_payload(invalid_payload, schema)
    
    def test_validated_payload_is_canonicalized(self):
        """Validated payload should be canonicalized."""
        schema = {"type": "object"}
        
        # Payload with unsorted keys
        payload = {"z": 1, "a": 2, "m": 3}
        
        result = validate_claim_payload(payload, schema)
        
        # Result should have sorted keys when converted to JSON
        import json
        from kaori_truth.canonical import canonical_json
        
        json_str = canonical_json(result)
        # Keys should be sorted: a, m, z
        assert json_str.index('"a"') < json_str.index('"m"')
        assert json_str.index('"m"') < json_str.index('"z"')


class TestClaimTypeOutputSchema:
    """Test ClaimType output schema integration."""
    
    def test_get_output_schema_inline(self):
        """get_output_schema should return inline schema."""
        claim_type = ClaimType(
            id="earth.flood.v1",
            version=1,
            domain="earth",
            topic="flood",
            output_schema={
                "type": "object",
                "required": ["severity"],
                "properties": {"severity": {"type": "string"}}
            }
        )
        
        schema = claim_type.get_output_schema()
        assert schema["required"] == ["severity"]
    
    def test_get_output_schema_default(self):
        """get_output_schema should return permissive default if not specified."""
        claim_type = ClaimType(
            id="earth.flood.v1",
            version=1,
            domain="earth",
            topic="flood",
        )
        
        schema = claim_type.get_output_schema()
        assert schema == {"type": "object"}
    
    def test_domain_config_validation_earth_h3(self):
        """earth domain with h3 should pass validation."""
        claim_type = ClaimType(
            id="earth.flood.v1",
            version=1,
            domain="earth",
            topic="flood",
            truthkey=TruthKeyConfig(spatial_system="h3"),
        )
        
        # Should not raise
        claim_type.validate_domain_config()
    
    def test_domain_config_validation_earth_healpix_fails(self):
        """earth domain with healpix should fail validation."""
        claim_type = ClaimType(
            id="earth.flood.v1",
            version=1,
            domain="earth",
            topic="flood",
            truthkey=TruthKeyConfig(spatial_system="healpix"),
        )
        
        with pytest.raises(ValueError) as exc_info:
            claim_type.validate_domain_config()
        
        assert "Invalid domain/spatial_system combination" in str(exc_info.value)
    
    def test_domain_config_validation_meta(self):
        """meta domain with meta spatial_system should pass."""
        claim_type = ClaimType(
            id="meta.research_artifact.v1",
            version=1,
            domain="meta",
            topic="research_artifact",
            truthkey=TruthKeyConfig(
                spatial_system="meta",
                z_index="knowledge",
                id_strategy="content_hash",
            ),
        )
        
        # Should not raise
        claim_type.validate_domain_config()
    
    def test_id_strategy_only_for_meta(self):
        """id_strategy should only apply to meta claims."""
        claim_type = ClaimType(
            id="earth.flood.v1",
            version=1,
            domain="earth",
            topic="flood",
            truthkey=TruthKeyConfig(
                spatial_system="h3",
                id_strategy="provided_id",  # Invalid for non-meta
            ),
        )
        
        with pytest.raises(ValueError) as exc_info:
            claim_type.validate_domain_config()
        
        assert "id_strategy is only applicable when spatial_system=meta" in str(exc_info.value)
