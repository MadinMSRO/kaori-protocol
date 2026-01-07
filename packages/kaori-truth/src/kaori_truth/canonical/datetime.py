"""
Kaori Truth — Canonical DateTime Serialization

Timezone-aware UTC normalization for deterministic timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Union


class NaiveDatetimeError(ValueError):
    """Raised when a naive datetime is provided without explicit timezone."""
    pass


def ensure_utc(dt: datetime, *, allow_naive: bool = False, assume_utc: bool = False) -> datetime:
    """
    Ensure a datetime is timezone-aware and convert to UTC.
    
    Args:
        dt: The datetime to normalize
        allow_naive: If True, accept naive datetimes (default: False)
        assume_utc: If True and datetime is naive, assume it's UTC (default: False)
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        NaiveDatetimeError: If datetime is naive and allow_naive is False
    """
    if dt.tzinfo is None:
        if not allow_naive:
            raise NaiveDatetimeError(
                f"Naive datetime not allowed: {dt}. "
                "Provide timezone-aware datetime or set allow_naive=True with assume_utc=True."
            )
        if assume_utc:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            raise NaiveDatetimeError(
                f"Naive datetime provided but assume_utc=False: {dt}"
            )
    
    # Convert to UTC
    return dt.astimezone(timezone.utc)


def canonical_datetime(
    dt: datetime,
    *,
    allow_naive: bool = False,
    assume_utc: bool = False,
    include_microseconds: bool = False,
) -> str:
    """
    Convert a datetime to its canonical string representation.
    
    Format: YYYY-MM-DDTHH:MM:SSZ (or with microseconds: YYYY-MM-DDTHH:MM:SS.ffffffZ)
    
    Args:
        dt: The datetime to canonicalize
        allow_naive: Allow naive datetimes
        assume_utc: Assume naive datetimes are UTC
        include_microseconds: Include microseconds in output
        
    Returns:
        ISO8601 UTC timestamp string
    """
    # Ensure UTC
    utc_dt = ensure_utc(dt, allow_naive=allow_naive, assume_utc=assume_utc)
    
    # Format
    if include_microseconds:
        # Full precision: YYYY-MM-DDTHH:MM:SS.ffffffZ
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        # Second precision: YYYY-MM-DDTHH:MM:SSZ
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_datetime_minute(
    dt: datetime,
    *,
    allow_naive: bool = False,
    assume_utc: bool = False,
) -> str:
    """
    Convert a datetime to minute-precision canonical representation.
    
    Format: YYYY-MM-DDTHH:MMZ (per TRUTH_SPEC Section 4.4)
    
    Args:
        dt: The datetime to canonicalize
        allow_naive: Allow naive datetimes
        assume_utc: Assume naive datetimes are UTC
        
    Returns:
        ISO8601 UTC timestamp string (minute precision)
    """
    utc_dt = ensure_utc(dt, allow_naive=allow_naive, assume_utc=assume_utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%MZ")


def parse_canonical_datetime(s: str) -> datetime:
    """
    Parse a canonical datetime string.
    
    Accepts:
    - YYYY-MM-DDTHH:MM:SSZ
    - YYYY-MM-DDTHH:MM:SS.ffffffZ
    - YYYY-MM-DDTHH:MMZ
    
    Args:
        s: The datetime string to parse
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        ValueError: If the string format is invalid
    """
    # Remove trailing Z and add +00:00 for parsing
    if not s.endswith('Z'):
        raise ValueError(f"Canonical datetime must end with 'Z': {s}")
    
    s = s[:-1]  # Remove Z
    
    # Try formats in order of specificity
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f",  # With microseconds
        "%Y-%m-%dT%H:%M:%S",     # With seconds
        "%Y-%m-%dT%H:%M",        # Minute precision
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    
    raise ValueError(f"Cannot parse datetime: {s}Z")


def datetime_to_deterministic_bytes(dt: datetime) -> bytes:
    """
    Convert a datetime to deterministic bytes for hashing.
    
    Uses canonical string representation encoded as UTF-8.
    
    Args:
        dt: The datetime to convert
        
    Returns:
        UTF-8 encoded canonical representation
    """
    return canonical_datetime(dt, include_microseconds=True).encode('utf-8')
