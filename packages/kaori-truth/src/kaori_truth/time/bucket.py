"""
Kaori Truth — Temporal Bucketing

Deterministic time bucketing for TruthKey generation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Tuple

from .normalize import ensure_utc


class BucketDuration(Enum):
    """
    Standard bucket durations.
    
    Per TRUTH_SPEC Section 4.4, these are the supported time_bucket durations.
    """
    MINUTE_1 = "PT1M"      # 1 minute
    MINUTE_15 = "PT15M"    # 15 minutes
    HOUR_1 = "PT1H"        # 1 hour
    HOUR_4 = "PT4H"        # 4 hours
    HOUR_6 = "PT6H"        # 6 hours
    DAY_1 = "P1D"          # 1 day
    DAY_7 = "P7D"          # 7 days
    DAY_30 = "P30D"        # 30 days


@dataclass
class ParsedDuration:
    """Parsed ISO8601 duration components."""
    days: int = 0
    hours: int = 0
    minutes: int = 0
    
    def to_timedelta(self) -> timedelta:
        return timedelta(days=self.days, hours=self.hours, minutes=self.minutes)


def parse_bucket_duration(duration: str) -> ParsedDuration:
    """
    Parse an ISO8601 duration string.
    
    Supported formats:
    - P{n}D (days)
    - PT{n}H (hours)
    - PT{n}M (minutes)
    - PT{n}H{m}M (hours and minutes)
    
    Args:
        duration: ISO8601 duration string
        
    Returns:
        ParsedDuration with components
        
    Raises:
        ValueError: If duration format is invalid
    """
    duration = duration.upper()
    
    # Pattern: P[nD][T[nH][nM]]
    pattern = r'^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$'
    match = re.match(pattern, duration)
    
    if not match:
        raise ValueError(f"Invalid ISO8601 duration: {duration}")
    
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0)
    minutes = int(match.group(3) or 0)
    
    if days == 0 and hours == 0 and minutes == 0:
        raise ValueError(f"Duration must be non-zero: {duration}")
    
    return ParsedDuration(days=days, hours=hours, minutes=minutes)


def bucket_datetime(
    dt: datetime,
    duration: str | BucketDuration,
) -> datetime:
    """
    Truncate a datetime to a bucket boundary.
    
    Per TRUTH_SPEC Section 4.4, time_bucket MUST truncate (not round)
    to the bucket boundary.
    
    This function determines the TruthKey time_bucket from event_time.
    
    Args:
        dt: The datetime to bucket (MUST be timezone-aware)
        duration: Bucket duration (ISO8601 or BucketDuration enum)
        
    Returns:
        Datetime truncated to bucket boundary (UTC, timezone-aware)
        
    Raises:
        NaiveDatetimeError: If dt is naive
        ValueError: If duration is invalid
    """
    # Ensure UTC
    utc_dt = ensure_utc(dt)
    
    # Get duration string
    if isinstance(duration, BucketDuration):
        duration = duration.value
    
    duration = duration.upper()
    
    # Parse and truncate
    if duration == "PT1M":
        # 1 minute: truncate seconds
        return utc_dt.replace(second=0, microsecond=0)
    
    elif duration == "PT15M":
        # 15 minutes: truncate to 15-minute boundary
        minute = (utc_dt.minute // 15) * 15
        return utc_dt.replace(minute=minute, second=0, microsecond=0)
    
    elif duration == "PT1H":
        # 1 hour: truncate minutes
        return utc_dt.replace(minute=0, second=0, microsecond=0)
    
    elif duration == "PT4H":
        # 4 hours: truncate to 4-hour boundary
        hour = (utc_dt.hour // 4) * 4
        return utc_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    elif duration == "PT6H":
        # 6 hours: truncate to 6-hour boundary
        hour = (utc_dt.hour // 6) * 6
        return utc_dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    elif duration.startswith("P") and duration.endswith("D"):
        # Daily or multi-day: truncate to day start
        return utc_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    
    else:
        raise ValueError(f"Unsupported bucket duration: {duration}")


def daily_bucket(dt: datetime) -> datetime:
    """Truncate to daily bucket (P1D)."""
    return bucket_datetime(dt, BucketDuration.DAY_1)


def hourly_bucket(dt: datetime) -> datetime:
    """Truncate to hourly bucket (PT1H)."""
    return bucket_datetime(dt, BucketDuration.HOUR_1)


def format_bucket(dt: datetime) -> str:
    """
    Format a bucket datetime to canonical string.
    
    Per TRUTH_SPEC Section 4.4, format is YYYY-MM-DDTHH:MMZ (no seconds).
    
    Args:
        dt: The bucket datetime (should already be truncated)
        
    Returns:
        Canonical bucket string
    """
    utc_dt = ensure_utc(dt)
    return utc_dt.strftime("%Y-%m-%dT%H:%MZ")


def bucket_bounds(
    dt: datetime,
    duration: str | BucketDuration,
) -> Tuple[datetime, datetime]:
    """
    Get the start and end of a bucket containing the given datetime.
    
    Args:
        dt: The datetime
        duration: Bucket duration
        
    Returns:
        Tuple of (bucket_start, bucket_end)
    """
    if isinstance(duration, BucketDuration):
        duration_str = duration.value
    else:
        duration_str = duration
    
    parsed = parse_bucket_duration(duration_str)
    delta = parsed.to_timedelta()
    
    bucket_start = bucket_datetime(dt, duration)
    bucket_end = bucket_start + delta
    
    return bucket_start, bucket_end
