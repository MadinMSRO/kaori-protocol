"""
Kaori Truth — Canonical Serialization Subsystem

This module provides deterministic, reproducible serialization for all protocol
primitives. All hashing and signing MUST go through this subsystem to ensure
byte-identical outputs across environments.

Design for extraction: This module is designed to become a standalone library
(kaori-canonical) in production deployments.
"""

from .json import canonical_json, canonicalize, canonical_dict
from .hash import canonical_hash, sha256_hex
from .datetime import canonical_datetime, ensure_utc
from .float import canonical_float, quantize_float
from .string import canonical_string, normalize_unicode
from .uri import canonical_uri, normalize_evidence_ref
from .schema import canonicalize_by_schema, CanonicalSchema

__all__ = [
    # Core API
    "canonicalize",
    "canonical_json",
    "canonical_hash",
    # JSON
    "canonical_dict",
    # Hash
    "sha256_hex",
    # DateTime
    "canonical_datetime",
    "ensure_utc",
    # Float
    "canonical_float",
    "quantize_float",
    # String
    "canonical_string",
    "normalize_unicode",
    # URI
    "canonical_uri",
    "normalize_evidence_ref",
    # Schema
    "canonicalize_by_schema",
    "CanonicalSchema",
]
