"""Tests for TruthKey generation and parsing."""
import pytest
from datetime import datetime, timezone

from core.models import Domain, SpatialSystem, TruthKey, Observation, ReporterContext, Standing
from core.truthkey import (
    generate_truthkey,
    parse_truthkey,
    format_truthkey,
    normalize_time_bucket,
)


class TestTimeBucketNormalization:
    """Test time bucket normalization."""
    
    def test_hourly_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        result = normalize_time_bucket(dt, "PT1H")
        assert result == "2026-01-02T14:00:00Z"
    
    def test_daily_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        result = normalize_time_bucket(dt, "P1D")
        assert result == "2026-01-02T00:00:00Z"
    
    def test_15min_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        result = normalize_time_bucket(dt, "PT15M")
        assert result == "2026-01-02T14:30:00Z"
    
    def test_4hour_bucket(self):
        dt = datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc)
        result = normalize_time_bucket(dt, "PT4H")
        assert result == "2026-01-02T12:00:00Z"


class TestTruthKeyParsing:
    """Test TruthKey string parsing."""
    
    def test_parse_valid_truthkey(self):
        s = "earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.EARTH
        assert tk.topic == "flood"
        assert tk.spatial_system == SpatialSystem.H3
        assert tk.spatial_id == "8928308280fffff"
        assert tk.z_index == "surface"
        assert tk.time_bucket == "2026-01-02T10:00:00Z"
    
    def test_parse_ocean_truthkey(self):
        s = "ocean:coral_bleaching:h3:89283082:depth_20m:2026-01-02T00:00:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.OCEAN
        assert tk.z_index == "depth_20m"
    
    def test_parse_space_truthkey(self):
        s = "space:orbital_debris:healpix:12345678:orbital_shell:2026-01-02T10:00:00Z"
        tk = parse_truthkey(s)
        
        assert tk.domain == Domain.SPACE
        assert tk.spatial_system == SpatialSystem.HEALPIX
    
    def test_parse_invalid_format(self):
        with pytest.raises(ValueError):
            parse_truthkey("invalid:format")
    
    def test_roundtrip(self):
        original = "earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00:00Z"
        tk = parse_truthkey(original)
        formatted = format_truthkey(tk)
        assert formatted == original


class TestTruthKeyGeneration:
    """Test TruthKey generation from observations."""
    
    def test_generate_earth_truthkey(self):
        obs = Observation(
            claim_type="earth.flood.v1",
            reported_at=datetime(2026, 1, 2, 14, 35, 22, tzinfo=timezone.utc),
            reporter_id="user123",
            reporter_context=ReporterContext(
                standing=Standing.BRONZE,
                trust_score=0.5,
            ),
            geo={"lat": 4.175, "lon": 73.509},
        )
        
        claim_config = {
            "domain": "earth",
            "topic": "flood",
            "truthkey": {
                "spatial_system": "h3",
                "resolution": 8,
                "z_index": "surface",
                "time_bucket": "PT1H",
            },
        }
        
        tk = generate_truthkey(obs, claim_config)
        
        assert tk.domain == Domain.EARTH
        assert tk.topic == "flood"
        assert tk.spatial_system == SpatialSystem.H3
        assert tk.z_index == "surface"
        assert tk.time_bucket == "2026-01-02T14:00:00Z"
    
    def test_generate_ocean_with_depth(self):
        obs = Observation(
            claim_type="ocean.coral_bleaching.v1",
            reported_at=datetime(2026, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            reporter_id="diver456",
            reporter_context=ReporterContext(
                standing=Standing.SILVER,
                trust_score=0.6,
            ),
            geo={"lat": 4.175, "lon": 73.509},
            depth_meters=25.5,
        )
        
        claim_config = {
            "domain": "ocean",
            "topic": "coral_bleaching",
            "truthkey": {
                "spatial_system": "h3",
                "resolution": 9,
                "z_index": "underwater",
                "time_bucket": "P1D",
            },
        }
        
        tk = generate_truthkey(obs, claim_config)
        
        assert tk.domain == Domain.OCEAN
        assert tk.z_index == "depth_20m"  # 25.5 rounds down to 20m bucket
        assert tk.time_bucket == "2026-01-02T00:00:00Z"
