"""
Kaori Truth — Test Suite for Temporal Index

Tests for timezone conversion, temporal bucketing, and time normalization.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from kaori_truth.time import (
    ensure_utc,
    bucket_datetime,
    format_bucket,
    BucketDuration,
    parse_datetime,
)
from kaori_truth.time.normalize import (
    NaiveDatetimeError,
    to_utc,
    is_naive,
    is_utc,
)
from kaori_truth.time.bucket import (
    parse_bucket_duration,
    daily_bucket,
    hourly_bucket,
    bucket_bounds,
)


class TestTimezoneNormalization:
    """Tests for timezone normalization."""
    
    def test_utc_passthrough(self):
        """UTC datetimes should pass through unchanged."""
        dt = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        result = ensure_utc(dt)
        
        assert result == dt
        assert is_utc(result)
    
    def test_local_to_utc(self):
        """Local times should be converted to UTC."""
        tz_plus8 = timezone(timedelta(hours=8))
        local = datetime(2026, 1, 7, 20, 0, 0, tzinfo=tz_plus8)
        
        result = ensure_utc(local)
        
        assert is_utc(result)
        assert result.hour == 12  # 20:00+08:00 = 12:00Z
    
    def test_naive_rejected(self):
        """Naive datetimes MUST be rejected."""
        naive = datetime(2026, 1, 7, 12, 0, 0)
        
        with pytest.raises(NaiveDatetimeError):
            ensure_utc(naive)
    
    def test_naive_with_assume_utc(self):
        """Naive datetimes can be converted if assume_utc=True."""
        naive = datetime(2026, 1, 7, 12, 0, 0)
        
        result = to_utc(naive, assume_utc=True)
        
        assert is_utc(result)
        assert result.hour == 12
    
    def test_dst_boundary(self):
        """DST transitions should be handled correctly."""
        # Note: This test uses a fixed-offset timezone for reliability
        tz_minus5 = timezone(timedelta(hours=-5))
        local = datetime(2026, 3, 8, 2, 30, 0, tzinfo=tz_minus5)
        
        result = ensure_utc(local)
        
        assert is_utc(result)
        assert result.hour == 7  # 2:30-05:00 = 7:30Z


class TestTemporalBucketing:
    """Tests for temporal bucketing."""
    
    def test_hourly_bucket(self):
        """PT1H should truncate to hour boundary."""
        dt = datetime(2026, 1, 7, 12, 37, 42, tzinfo=timezone.utc)
        
        result = bucket_datetime(dt, "PT1H")
        
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0
    
    def test_15_minute_bucket(self):
        """PT15M should truncate to 15-minute boundary."""
        dt = datetime(2026, 1, 7, 12, 37, 42, tzinfo=timezone.utc)
        
        result = bucket_datetime(dt, "PT15M")
        
        assert result.minute == 30  # 37 -> 30
        assert result.second == 0
    
    def test_4_hour_bucket(self):
        """PT4H should truncate to 4-hour boundary."""
        dt = datetime(2026, 1, 7, 10, 37, 42, tzinfo=timezone.utc)
        
        result = bucket_datetime(dt, "PT4H")
        
        assert result.hour == 8  # 10 -> 8
    
    def test_daily_bucket(self):
        """P1D should truncate to day boundary."""
        dt = datetime(2026, 1, 7, 12, 37, 42, tzinfo=timezone.utc)
        
        result = bucket_datetime(dt, "P1D")
        
        assert result.hour == 0
        assert result.minute == 0
    
    def test_midnight_boundary(self):
        """Times at 23:59:59 should bucket to current day."""
        dt = datetime(2026, 1, 7, 23, 59, 59, tzinfo=timezone.utc)
        
        result = daily_bucket(dt)
        
        assert result.day == 7
        assert result.hour == 0
    
    def test_format_bucket(self):
        """Bucket format should be YYYY-MM-DDTHH:MMZ."""
        dt = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
        
        result = format_bucket(dt)
        
        assert result == "2026-01-07T12:00Z"
        assert ":" in result  # Has time separator
        assert result.endswith("Z")
    
    def test_bucket_bounds(self):
        """Should return start and end of bucket."""
        dt = datetime(2026, 1, 7, 12, 37, 42, tzinfo=timezone.utc)
        
        start, end = bucket_bounds(dt, "PT1H")
        
        assert start.hour == 12
        assert end.hour == 13


class TestDatetimeParsing:
    """Tests for datetime parsing."""
    
    def test_parse_iso8601_z(self):
        """Should parse ISO8601 with Z suffix."""
        result = parse_datetime("2026-01-07T12:00:00Z")
        
        assert is_utc(result)
        assert result.hour == 12
    
    def test_parse_minute_precision(self):
        """Should parse minute-precision timestamps."""
        result = parse_datetime("2026-01-07T12:00Z")
        
        assert is_utc(result)
        assert result.minute == 0
    
    def test_parse_with_microseconds(self):
        """Should parse timestamps with microseconds."""
        result = parse_datetime("2026-01-07T12:00:00.123456Z")
        
        assert is_utc(result)
        assert result.microsecond == 123456


class TestLocalTimeDifference:
    """Tests that same local time in different timezones bucket correctly."""
    
    def test_same_utc_instant_different_tz(self):
        """Same UTC instant should produce same bucket."""
        tz_utc = timezone.utc
        tz_plus8 = timezone(timedelta(hours=8))
        
        utc_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=tz_utc)
        local_time = datetime(2026, 1, 7, 20, 30, 0, tzinfo=tz_plus8)
        
        bucket_utc = bucket_datetime(utc_time, "PT1H")
        bucket_local = bucket_datetime(local_time, "PT1H")
        
        # Both should produce the same bucket
        assert bucket_utc == bucket_local
    
    def test_event_time_used_for_truthkey(self):
        """TruthKey should be derived from event_time, not receipt_time."""
        # Event happened at 11:30 UTC
        event_time = datetime(2026, 1, 7, 11, 30, 0, tzinfo=timezone.utc)
        # Received at 12:05 UTC
        receipt_time = datetime(2026, 1, 7, 12, 5, 0, tzinfo=timezone.utc)
        
        # TruthKey should use event_time
        bucket = bucket_datetime(event_time, "PT1H")
        
        assert bucket.hour == 11  # Based on event_time, not receipt_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
