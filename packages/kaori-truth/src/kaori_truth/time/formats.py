"""
Kaori Truth — Datetime Formats

Canonical format constants and formatting functions.
"""
from __future__ import annotations

from datetime import datetime

from .normalize import ensure_utc


# Canonical format: YYYY-MM-DDTHH:MM:SS.ffffffZ (full precision)
CANONICAL_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# Canonical format: YYYY-MM-DDTHH:MM:SSZ (second precision)
CANONICAL_DATETIME_SECONDS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Canonical format: YYYY-MM-DDTHH:MMZ (minute precision, for buckets)
CANONICAL_BUCKET_FORMAT = "%Y-%m-%dT%H:%MZ"

# Canonical date format: YYYY-MM-DD
CANONICAL_DATE_FORMAT = "%Y-%m-%d"


def format_canonical(
    dt: datetime,
    *,
    include_microseconds: bool = False,
) -> str:
    """
    Format a datetime to canonical string.
    
    Args:
        dt: The datetime to format (MUST be timezone-aware)
        include_microseconds: Whether to include microseconds
        
    Returns:
        Canonical datetime string in UTC
    """
    utc_dt = ensure_utc(dt)
    
    if include_microseconds:
        return utc_dt.strftime(CANONICAL_DATETIME_FORMAT)
    else:
        return utc_dt.strftime(CANONICAL_DATETIME_SECONDS_FORMAT)


def format_bucket(dt: datetime) -> str:
    """
    Format a datetime to bucket string (minute precision).
    
    Per TRUTH_SPEC Section 4.4: YYYY-MM-DDTHH:MMZ
    
    Args:
        dt: The datetime to format
        
    Returns:
        Canonical bucket string
    """
    utc_dt = ensure_utc(dt)
    return utc_dt.strftime(CANONICAL_BUCKET_FORMAT)


def format_date(dt: datetime) -> str:
    """
    Format a datetime to date string.
    
    Args:
        dt: The datetime to format
        
    Returns:
        Date string YYYY-MM-DD
    """
    utc_dt = ensure_utc(dt)
    return utc_dt.strftime(CANONICAL_DATE_FORMAT)
