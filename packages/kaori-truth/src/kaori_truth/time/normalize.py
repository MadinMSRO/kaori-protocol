"""
Kaori Truth — Datetime Normalization

Strict UTC normalization for deterministic time handling.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


class NaiveDatetimeError(ValueError):
    """
    Raised when a naive datetime is provided without explicit timezone.
    
    Per protocol requirements, all datetimes MUST be timezone-aware.
    Naive datetimes are rejected unless explicit conversion is requested.
    """
    pass


def is_naive(dt: datetime) -> bool:
    """Check if a datetime is naive (no timezone info)."""
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def reject_naive(dt: datetime) -> datetime:
    """
    Reject naive datetimes.
    
    Args:
        dt: The datetime to check
        
    Returns:
        The same datetime if it's timezone-aware
        
    Raises:
        NaiveDatetimeError: If the datetime is naive
    """
    if is_naive(dt):
        raise NaiveDatetimeError(
            f"Naive datetime not allowed: {dt}. "
            "All datetimes must be timezone-aware. "
            "Use to_utc() with explicit timezone if needed."
        )
    return dt


def to_utc(
    dt: datetime,
    *,
    assume_utc: bool = False,
    source_tz: Optional[timezone] = None,
) -> datetime:
    """
    Convert a datetime to UTC.
    
    This is the primary conversion function for incoming datetimes.
    
    Args:
        dt: The datetime to convert
        assume_utc: If True and dt is naive, assume it's UTC
        source_tz: If provided and dt is naive, use this timezone
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        NaiveDatetimeError: If dt is naive and no assumption is provided
    """
    if is_naive(dt):
        if assume_utc:
            dt = dt.replace(tzinfo=timezone.utc)
        elif source_tz is not None:
            dt = dt.replace(tzinfo=source_tz)
        else:
            raise NaiveDatetimeError(
                f"Cannot convert naive datetime to UTC: {dt}. "
                "Provide assume_utc=True or source_tz parameter."
            )
    
    # Convert to UTC
    return dt.astimezone(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """
    Ensure a datetime is in UTC.
    
    Unlike to_utc(), this function:
    - Rejects naive datetimes (no assumptions)
    - Returns the datetime in UTC timezone
    
    Args:
        dt: The datetime to normalize
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        NaiveDatetimeError: If the datetime is naive
    """
    reject_naive(dt)
    return dt.astimezone(timezone.utc)


def utc_now() -> datetime:
    """
    Get the current time in UTC.
    
    This is provided for convenience but SHOULD NOT be used in
    truth compilation code. Compilation should receive explicit times.
    
    Returns:
        Current time as timezone-aware UTC datetime
    """
    return datetime.now(timezone.utc)


def is_utc(dt: datetime) -> bool:
    """
    Check if a datetime is in UTC timezone.
    
    Args:
        dt: The datetime to check
        
    Returns:
        True if the datetime is in UTC
    """
    if is_naive(dt):
        return False
    return dt.utcoffset() == timezone.utc.utcoffset(None)
