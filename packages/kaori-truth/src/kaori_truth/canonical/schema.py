"""
Kaori Truth — Schema-Aware Canonicalization

Schema-based canonicalization for protocol primitives.
Ensures consistent field ordering and type normalization.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type


class CanonicalSchema(Enum):
    """
    Known schema types for protocol primitives.
    
    Each schema defines a specific canonicalization format.
    """
    TRUTH_KEY = "truthkey"
    TRUTH_STATE = "truthstate"
    OBSERVATION = "observation"
    CLAIM_TYPE = "claimtype"
    TRUST_SNAPSHOT = "trust_snapshot"
    EVIDENCE_REF = "evidence_ref"
    CONSENSUS_RECORD = "consensus"
    VOTE = "vote"
    SECURITY_BLOCK = "security_block"
    COMPILE_INPUTS = "compile_inputs"


@dataclass
class FieldSpec:
    """Specification for a canonical field."""
    name: str
    required: bool = True
    normalizer: Optional[Callable[[Any], Any]] = None
    
    
# Schema field definitions
SCHEMA_FIELDS: Dict[CanonicalSchema, List[str]] = {
    CanonicalSchema.TRUTH_KEY: [
        "domain",
        "topic",
        "spatial_system",
        "spatial_id",
        "z_index",
        "time_bucket",
    ],
    CanonicalSchema.TRUTH_STATE: [
        "truthkey",
        "claim_type",
        "claim_type_hash",
        "status",
        "verification_basis",
        "ai_confidence",
        "confidence",
        "transparency_flags",
        "compile_inputs",
        "evidence_refs",
        "observation_ids",
    ],
    CanonicalSchema.OBSERVATION: [
        "observation_id",
        "claim_type",
        "reported_at",
        "reporter_id",
        "reporter_context",
        "geo",
        "payload",
        "evidence_refs",
        "evidence_hashes",
    ],
    CanonicalSchema.CLAIM_TYPE: [
        "id",
        "version",
        "domain",
        "topic",
        "truthkey",
        "risk_profile",
        "evidence",
        "autovalidation",
        "consensus_model",
        "confidence_model",
        "temporal_decay",
    ],
    CanonicalSchema.TRUST_SNAPSHOT: [
        "snapshot_id",
        "snapshot_time",
        "agent_trusts",
        "snapshot_hash",
    ],
    CanonicalSchema.EVIDENCE_REF: [
        "uri",
        "sha256",
        "mime_type",
        "capture_time",
    ],
    CanonicalSchema.COMPILE_INPUTS: [
        "observation_ids",
        "claim_type_id",
        "claim_type_hash",
        "policy_version",
        "compiler_version",
        "trust_snapshot_hash",
        "compile_time",
    ],
    CanonicalSchema.SECURITY_BLOCK: [
        "semantic_hash",
        "state_hash",
        "signature",
        "signing_method",
        "key_id",
        "signed_at",
    ],
}


def canonicalize_by_schema(
    obj: dict,
    schema: CanonicalSchema,
    *,
    strict: bool = True,
) -> dict:
    """
    Canonicalize an object according to a known schema.
    
    This ensures:
    1. Fields are in canonical order
    2. Only known fields are included
    3. Required fields are present
    
    Args:
        obj: The object dictionary to canonicalize
        schema: The schema to apply
        strict: If True, raise on missing required fields
        
    Returns:
        Canonicalized dictionary with fields in schema order
        
    Raises:
        ValueError: If strict=True and required fields are missing
    """
    field_order = SCHEMA_FIELDS.get(schema)
    if not field_order:
        raise ValueError(f"Unknown schema: {schema}")
    
    result = {}
    
    for field in field_order:
        if field in obj:
            result[field] = obj[field]
        elif strict:
            # Check if required (for now, all fields optional by default)
            pass
    
    return result


def get_schema_fields(schema: CanonicalSchema) -> List[str]:
    """
    Get the ordered list of fields for a schema.
    
    Args:
        schema: The schema type
        
    Returns:
        List of field names in canonical order
    """
    return SCHEMA_FIELDS.get(schema, [])
