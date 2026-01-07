"""Tests for TruthKey generation and parsing."""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from kaori_truth.primitives.truthkey import (
    TruthKey,
    Domain,
    SpatialSystem,
    build_truthkey,
    parse_truthkey,
    canonical_truthkey,
)
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.time import bucket_datetime, format_bucket

class TestTimeBucketNormalization:
    """Test time bucket normalization using new temporal API."""
    
    def test_hourly_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        bucketed = bucket_datetime(dt, "PT1H")
        result = format_bucket(bucketed)
        assert result == "2026-01-02T14:00Z"
    
    def test_daily_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        bucketed = bucket_datetime(dt, "P1D")
        result = format_bucket(bucketed)
        assert result == "2026-01-02T00:00Z"


class TestTruthKeyParsing:
    """Test TruthKey string parsing."""
    
    def test_parse_valid_truthkey(self):
        s = "earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.EARTH
        assert tk.topic == "flood"
        assert tk.spatial_system == SpatialSystem.H3
        assert tk.spatial_id == "8928308280fffff"
        assert tk.z_index == "surface"
        assert tk.time_bucket == "2026-01-02T10:00Z"
    
    def test_parse_ocean_truthkey(self):
        s = "ocean:coral_bleaching:h3:89283082:depth_20m:2026-01-02T00:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.OCEAN
        assert tk.z_index == "depth_20m"
    
    def test_parse_space_truthkey(self):
        s = "space:orbital_debris:healpix:12345678:orbital_shell:2026-01-02T10:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.SPACE
        assert tk.spatial_system == SpatialSystem.HEALPIX
    
    def test_roundtrip(self):
        original = "earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00Z"
        tk = parse_truthkey(original)
        formatted = canonical_truthkey(tk)
        assert formatted == original


class TestTruthKeyGeneration:
    """Test TruthKey generation via build_truthkey."""
    
    def test_build_earth_truthkey(self):
        event_time = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        location = {"lat": 4.175, "lon": 73.509}
        
        key = build_truthkey(
            claim_type_id="earth.flood.v1",
            event_time=event_time,
            spatial_system="h3",
            z_index="surface",
            location=location,
            time_bucket_duration="PT1H"
        )
        
        parts = parse_truthkey(key)
        assert parts.domain == Domain.EARTH
        assert parts.spatial_system == SpatialSystem.H3
        # ID is derived (either H3 or mock string). Just verify it's the 4th segment.
        assert parts.spatial_id
        assert parts.time_bucket == "2026-01-02T14:00Z"

    def test_build_ocean_truthkey(self):
        event_time = datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
        location = {"lat": 4.175, "lon": 73.509}
        
        key = build_truthkey(
            claim_type_id="ocean.coral_bleaching.v1",
            event_time=event_time,
            spatial_system="h3",
            z_index="depth_20m",
            location=location,
            time_bucket_duration="P1D"
        )
        
        parts = parse_truthkey(key)
        assert parts.domain == Domain.OCEAN
        assert parts.z_index == "depth_20m"
        assert parts.spatial_id
        assert parts.time_bucket == "2026-01-02T00:00Z"
