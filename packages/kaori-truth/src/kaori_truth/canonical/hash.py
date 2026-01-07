"""
Kaori Truth — Canonical Hashing

SHA256 hashing over canonical representations.
All protocol hashing MUST use this module to ensure determinism.
"""
from __future__ import annotations

import hashlib
from typing import Any, Union

from .json import canonicalize, canonical_json


def sha256_hex(data: Union[bytes, str]) -> str:
    """
    Compute SHA256 hash and return as lowercase hex string.
    
    Args:
        data: Bytes or string to hash (strings are UTF-8 encoded)
        
    Returns:
        64-character lowercase hex string
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    return hashlib.sha256(data).hexdigest()


def sha256_bytes(data: Union[bytes, str]) -> bytes:
    """
    Compute SHA256 hash and return as bytes.
    
    Args:
        data: Bytes or string to hash (strings are UTF-8 encoded)
        
    Returns:
        32-byte hash digest
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    
    return hashlib.sha256(data).digest()


def canonical_hash(
    obj: Any,
    *,
    schema: str | None = None,
    float_precision: int = 6,
) -> str:
    """
    Compute SHA256 hash of an object's canonical representation.
    
    This is the primary hashing API for all protocol primitives.
    
    Args:
        obj: The object to hash
        schema: Optional schema identifier
        float_precision: Decimal precision for floats
        
    Returns:
        64-character lowercase hex hash
    """
    canonical_bytes = canonicalize(obj, schema=schema, float_precision=float_precision)
    return sha256_hex(canonical_bytes)


def hash_combine(*hashes: str) -> str:
    """
    Combine multiple hashes into a single hash.
    
    Concatenates hex strings and hashes the result.
    
    Args:
        *hashes: Hex hash strings to combine
        
    Returns:
        64-character lowercase hex hash
    """
    combined = '|'.join(hashes)
    return sha256_hex(combined)


def verify_hash(obj: Any, expected_hash: str, **kwargs) -> bool:
    """
    Verify that an object's canonical hash matches expected.
    
    Args:
        obj: The object to verify
        expected_hash: The expected hash (lowercase hex)
        **kwargs: Additional arguments passed to canonical_hash
        
    Returns:
        True if hashes match
    """
    actual_hash = canonical_hash(obj, **kwargs)
    return actual_hash == expected_hash.lower()
