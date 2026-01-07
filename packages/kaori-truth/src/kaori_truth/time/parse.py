"""
Kaori Truth — Datetime Parsing

Parse various datetime formats to timezone-aware UTC.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from .normalize import to_utc, NaiveDatetimeError


# Common datetime formats
ISO8601_PATTERNS = [
    # With timezone
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)([+-]\d{2}:?\d{2}|Z)$',
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})([+-]\d{2}:?\d{2}|Z)$',
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})([+-]\d{2}:?\d{2}|Z)$',
    # Special: Z suffix
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$',
    r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})Z$',
]


def parse_timezone_offset(offset_str: str) -> timezone:
    """
    Parse a timezone offset string.
    
    Supports:
    - Z (UTC)
    - +HH:MM / -HH:MM
    - +HHMM / -HHMM
    
    Args:
        offset_str: Timezone offset string
        
    Returns:
        timezone object
    """
    if offset_str == 'Z':
        return timezone.utc
    
    # Remove colon if present
    offset_str = offset_str.replace(':', '')
    
    # Parse sign and components
    sign = 1 if offset_str[0] == '+' else -1
    hours = int(offset_str[1:3])
    minutes = int(offset_str[3:5]) if len(offset_str) > 3 else 0
    
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(sign * delta)


def parse_iso8601(s: str) -> datetime:
    """
    Parse an ISO8601 datetime string.
    
    Accepts:
    - YYYY-MM-DDTHH:MM:SS.ffffffZ
    - YYYY-MM-DDTHH:MM:SSZ
    - YYYY-MM-DDTHH:MMZ
    - YYYY-MM-DDTHH:MM:SS+HH:MM
    - YYYY-MM-DDTHH:MM:SS-HHMM
    
    Args:
        s: The datetime string to parse
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        ValueError: If the string cannot be parsed
    """
    s = s.strip()
    
    # Try Python's fromisoformat (Python 3.11+)
    try:
        # Handle Z suffix
        if s.endswith('Z'):
            s_modified = s[:-1] + '+00:00'
            dt = datetime.fromisoformat(s_modified)
            return dt.astimezone(timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    
    # Manual parsing for edge cases
    # With microseconds and Z
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)Z$', s)
    if match:
        year, month, day, hour, minute, second, micro = match.groups()
        # Pad/truncate microseconds to 6 digits
        micro = micro[:6].ljust(6, '0')
        return datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second), int(micro),
            tzinfo=timezone.utc
        )
    
    # With seconds and Z
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$', s)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second),
            tzinfo=timezone.utc
        )
    
    # Minute precision with Z
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})Z$', s)
    if match:
        year, month, day, hour, minute = match.groups()
        return datetime(
            int(year), int(month), int(day),
            int(hour), int(minute),
            tzinfo=timezone.utc
        )
    
    raise ValueError(f"Cannot parse datetime: {s}")


def parse_datetime(
    s: str,
    *,
    assume_utc: bool = False,
) -> datetime:
    """
    Parse a datetime string with flexible format handling.
    
    This is the primary parsing function for incoming datetime strings.
    
    Args:
        s: The datetime string to parse
        assume_utc: If True and no timezone in string, assume UTC
        
    Returns:
        Timezone-aware datetime in UTC
        
    Raises:
        ValueError: If the string cannot be parsed
        NaiveDatetimeError: If naive datetime and assume_utc is False
    """
    # Try ISO8601 first
    try:
        return parse_iso8601(s)
    except ValueError:
        pass
    
    # Try Python's standard parser
    try:
        # Common formats
        for fmt in [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]:
            try:
                dt = datetime.strptime(s, fmt)
                return to_utc(dt, assume_utc=assume_utc)
            except ValueError:
                continue
    except NaiveDatetimeError:
        raise
    
    raise ValueError(f"Cannot parse datetime: {s}")
