"""
Kaori Truth — Schema Validation

Deterministic JSON Schema validation for claim payloads.

INVARIANT: Validation errors MUST be deterministic (stable ordering, error codes).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from kaori_truth.canonical import canonicalize
from kaori_truth.canonical.json import canonical_dict


class SchemaValidationError(Exception):
    """
    Raised when claim payload fails schema validation.
    
    Error format is deterministic for reproducibility.
    """
    
    def __init__(
        self,
        message: str,
        errors: List[Dict[str, Any]],
    ):
        self.message = message
        self.errors = errors  # Sorted, deterministic error list
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format deterministic error message."""
        error_strs = []
        for err in self.errors:
            path = err.get("path", "$")
            code = err.get("code", "UNKNOWN")
            error_strs.append(f"[{code}] {path}")
        return f"{self.message}: {'; '.join(error_strs)}"


# Error codes for determinism (not locale-dependent messages)
class ErrorCode:
    REQUIRED = "REQUIRED"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    ENUM_INVALID = "ENUM_INVALID"
    MIN_LENGTH = "MIN_LENGTH"
    MAX_LENGTH = "MAX_LENGTH"
    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"
    PATTERN = "PATTERN"
    FORMAT = "FORMAT"
    ADDITIONAL_PROPERTIES = "ADDITIONAL_PROPERTIES"
    UNKNOWN = "UNKNOWN"


def validate_claim_payload(
    payload: Dict[str, Any],
    schema: Dict[str, Any],
    *,
    allow_additional_properties: bool = False,
) -> Dict[str, Any]:
    """
    Validate claim payload against JSON Schema.
    
    MUST be called BEFORE canonicalization and hashing.
    Returns canonicalized payload if valid.
    
    Args:
        payload: The claim payload to validate
        schema: JSON Schema definition
        allow_additional_properties: Whether to allow extra fields
        
    Returns:
        Canonicalized payload (if valid)
        
    Raises:
        SchemaValidationError: If validation fails (deterministic errors)
    """
    errors = _validate_object(payload, schema, "$", allow_additional_properties)
    
    if errors:
        # Sort errors for determinism
        sorted_errors = sorted(errors, key=lambda e: (e.get("path", ""), e.get("code", "")))
        raise SchemaValidationError(
            "Claim payload failed schema validation",
            sorted_errors,
        )
    
    # Return canonicalized payload
    return canonical_dict(payload)


def _validate_object(
    data: Any,
    schema: Dict[str, Any],
    path: str,
    allow_additional: bool,
) -> List[Dict[str, Any]]:
    """Recursively validate data against schema."""
    errors = []
    
    schema_type = schema.get("type")
    
    # Type validation
    if schema_type:
        if not _check_type(data, schema_type):
            errors.append({
                "path": path,
                "code": ErrorCode.TYPE_MISMATCH,
                "expected": schema_type,
                "actual": type(data).__name__,
            })
            return errors  # Stop on type mismatch
    
    # Object validation
    if schema_type == "object" and isinstance(data, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional_props = schema.get("additionalProperties", True)
        
        # Check required fields
        for field in required:
            if field not in data:
                errors.append({
                    "path": f"{path}.{field}",
                    "code": ErrorCode.REQUIRED,
                })
        
        # Validate properties
        for key, value in data.items():
            prop_path = f"{path}.{key}"
            if key in properties:
                errors.extend(_validate_object(
                    value, properties[key], prop_path, allow_additional
                ))
            elif not additional_props and not allow_additional:
                errors.append({
                    "path": prop_path,
                    "code": ErrorCode.ADDITIONAL_PROPERTIES,
                })
    
    # Array validation
    elif schema_type == "array" and isinstance(data, list):
        items_schema = schema.get("items", {})
        for i, item in enumerate(data):
            errors.extend(_validate_object(
                item, items_schema, f"{path}[{i}]", allow_additional
            ))
    
    # String validation
    elif schema_type == "string" and isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append({
                "path": path,
                "code": ErrorCode.MIN_LENGTH,
                "min": schema["minLength"],
            })
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append({
                "path": path,
                "code": ErrorCode.MAX_LENGTH,
                "max": schema["maxLength"],
            })
        if "enum" in schema and data not in schema["enum"]:
            errors.append({
                "path": path,
                "code": ErrorCode.ENUM_INVALID,
                "allowed": schema["enum"],
            })
        if "pattern" in schema:
            import re
            if not re.match(schema["pattern"], data):
                errors.append({
                    "path": path,
                    "code": ErrorCode.PATTERN,
                    "pattern": schema["pattern"],
                })
    
    # Number validation
    elif schema_type in ("number", "integer") and isinstance(data, (int, float)):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append({
                "path": path,
                "code": ErrorCode.MINIMUM,
                "min": schema["minimum"],
            })
        if "maximum" in schema and data > schema["maximum"]:
            errors.append({
                "path": path,
                "code": ErrorCode.MAXIMUM,
                "max": schema["maximum"],
            })
    
    return errors


def _check_type(data: Any, expected: str) -> bool:
    """Check if data matches expected JSON Schema type."""
    if expected == "string":
        return isinstance(data, str)
    elif expected == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    elif expected == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    elif expected == "boolean":
        return isinstance(data, bool)
    elif expected == "array":
        return isinstance(data, list)
    elif expected == "object":
        return isinstance(data, dict)
    elif expected == "null":
        return data is None
    return True


def load_schema(schema_ref: str, base_path: str = "") -> Dict[str, Any]:
    """
    Load JSON Schema from file reference.
    
    Args:
        schema_ref: Path to schema file (relative or absolute)
        base_path: Base path for relative references
        
    Returns:
        Parsed JSON Schema
    """
    from pathlib import Path
    
    if base_path:
        schema_path = Path(base_path) / schema_ref
    else:
        schema_path = Path(schema_ref)
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_output_schema(claim_type_config: Dict[str, Any], schema_base_path: str = "") -> Dict[str, Any]:
    """
    Get output schema from ClaimType configuration.
    
    Supports:
    - output_schema: Inline JSON Schema
    - output_schema_ref: Path to external schema file
    
    Args:
        claim_type_config: ClaimType YAML configuration
        schema_base_path: Base path for schema references
        
    Returns:
        JSON Schema for output validation
        
    Raises:
        ValueError: If no output schema is defined
    """
    if "output_schema" in claim_type_config:
        return claim_type_config["output_schema"]
    
    if "output_schema_ref" in claim_type_config:
        return load_schema(claim_type_config["output_schema_ref"], schema_base_path)
    
    # Default permissive schema (any object)
    return {"type": "object"}
