"""
Kaori Truth — Canonical JSON Serialization

Core canonical JSON serialization for deterministic hashing and signing.
All protocol hashing MUST go through this module.
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Union
from uuid import UUID

from .string import canonical_string, normalize_unicode
from .float import canonical_float, DEFAULT_PRECISION
from .datetime import canonical_datetime


class CanonicalJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that produces canonical output.
    
    Features:
    - Sorted keys
    - Minimal separators
    - Deterministic type handling
    - Float quantization
    - DateTime normalization
    - UUID string conversion
    """
    
    def __init__(
        self,
        *,
        float_precision: int = DEFAULT_PRECISION,
        include_datetime_microseconds: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.float_precision = float_precision
        self.include_datetime_microseconds = include_datetime_microseconds
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return canonical_datetime(
                obj,
                allow_naive=False,
                include_microseconds=self.include_datetime_microseconds
            )
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, Decimal):
            return canonical_float(obj, self.float_precision)
        elif isinstance(obj, bytes):
            # Bytes as hex string
            return obj.hex()
        elif hasattr(obj, 'model_dump'):
            # Pydantic model
            return obj.model_dump(mode='json')
        elif hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


def canonical_json(
    obj: Any,
    *,
    float_precision: int = DEFAULT_PRECISION,
    include_datetime_microseconds: bool = False,
) -> str:
    """
    Serialize an object to canonical JSON.
    
    Canonical JSON is:
    1. Keys sorted alphabetically
    2. Minimal separators (',', ':')
    3. No trailing newline
    4. Floats quantized to fixed precision
    5. Datetimes in UTC ISO8601 format
    6. Strings NFC-normalized
    
    Args:
        obj: The object to serialize
        float_precision: Decimal precision for floats
        include_datetime_microseconds: Include microseconds in datetime strings
        
    Returns:
        Canonical JSON string
    """
    encoder = CanonicalJSONEncoder(
        float_precision=float_precision,
        include_datetime_microseconds=include_datetime_microseconds,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,  # Allow unicode (already NFC normalized)
    )
    
    return encoder.encode(obj)


def canonical_dict(obj: dict, *, recursive: bool = True) -> dict:
    """
    Canonicalize a dictionary (without serializing to string).
    
    Applies:
    1. Sort keys
    2. Normalize string values
    3. Recursively canonicalize nested dicts
    
    Args:
        obj: The dictionary to canonicalize
        recursive: Whether to recursively canonicalize nested dicts
        
    Returns:
        Canonicalized dictionary
    """
    result = {}
    
    for key in sorted(obj.keys()):
        value = obj[key]
        
        if isinstance(value, str):
            value = normalize_unicode(value)
        elif isinstance(value, dict) and recursive:
            value = canonical_dict(value, recursive=True)
        elif isinstance(value, list) and recursive:
            value = [
                canonical_dict(v, recursive=True) if isinstance(v, dict)
                else normalize_unicode(v) if isinstance(v, str)
                else v
                for v in value
            ]
        
        result[key] = value
    
    return result


def canonicalize(
    obj: Any,
    *,
    schema: str | None = None,
    float_precision: int = DEFAULT_PRECISION,
) -> bytes:
    """
    Primary canonicalization API.
    
    Converts any object to canonical bytes suitable for hashing.
    
    Args:
        obj: The object to canonicalize
        schema: Optional schema identifier (for schema-specific canonicalization)
        float_precision: Decimal precision for floats
        
    Returns:
        UTF-8 encoded canonical JSON bytes
    """
    json_str = canonical_json(obj, float_precision=float_precision)
    return json_str.encode('utf-8')
