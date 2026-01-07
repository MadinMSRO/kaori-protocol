"""
Tests for meta namespace claims and TruthKey generation.

Covers:
- Meta claims with content_hash id_strategy
- Meta claims with provided_id id_strategy
- Meta claims with hybrid id_strategy
- Domain/spatial_system validation
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from kaori_truth.primitives.truthkey import (
    build_truthkey,
    parse_truthkey,
    _compute_meta_id,
    Domain,
    SpatialSystem,
)


class TestMetaIdStrategy:
    """Test meta claim id_strategy computation."""
    
    def test_content_hash_strategy(self):
        """content_hash strategy should use hash prefix."""
        result = _compute_meta_id(
            id_strategy="content_hash",
            content_hash="abc123def456789012345678901234567890",
        )
        
        # Should be truncated to 32 chars, lowercase
        assert result == "abc123def45678901234567890123456"
        assert len(result) == 32
    
    def test_provided_id_strategy(self):
        """provided_id strategy should use artifact_id."""
        result = _compute_meta_id(
            id_strategy="provided_id",
            artifact_id="my-artifact-v1",
        )
        
        assert result == "my-artifact-v1"
    
    def test_hybrid_strategy_prefers_content_hash(self):
        """hybrid strategy should prefer content_hash if available."""
        result = _compute_meta_id(
            id_strategy="hybrid",
            content_hash="abc123def456789012345678901234567890",
            artifact_id="fallback-id",
        )
        
        assert result == "abc123def45678901234567890123456"
    
    def test_hybrid_strategy_falls_back_to_artifact_id(self):
        """hybrid strategy should fall back to artifact_id."""
        result = _compute_meta_id(
            id_strategy="hybrid",
            content_hash=None,
            artifact_id="fallback-id",
        )
        
        assert result == "fallback-id"
    
    def test_content_hash_missing_fails(self):
        """content_hash strategy without hash should fail."""
        with pytest.raises(ValueError) as exc_info:
            _compute_meta_id(
                id_strategy="content_hash",
                content_hash=None,
            )
        
        assert "content_hash required" in str(exc_info.value)
    
    def test_provided_id_missing_fails(self):
        """provided_id strategy without id should fail."""
        with pytest.raises(ValueError) as exc_info:
            _compute_meta_id(
                id_strategy="provided_id",
                artifact_id=None,
            )
        
        assert "artifact_id required" in str(exc_info.value)
    
    def test_hybrid_both_missing_fails(self):
        """hybrid strategy without either should fail."""
        with pytest.raises(ValueError) as exc_info:
            _compute_meta_id(
                id_strategy="hybrid",
                content_hash=None,
                artifact_id=None,
            )
        
        assert "Either content_hash or artifact_id required" in str(exc_info.value)
    
    def test_unknown_strategy_fails(self):
        """Unknown strategy should fail."""
        with pytest.raises(ValueError) as exc_info:
            _compute_meta_id(
                id_strategy="unknown",
                content_hash="abc",
            )
        
        assert "Unknown id_strategy" in str(exc_info.value)


class TestBuildTruthKeyMeta:
    """Test build_truthkey for meta claims."""
    
    def test_build_meta_truthkey(self):
        """Should build valid meta TruthKey."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        key = build_truthkey(
            claim_type_id="meta.research_artifact.v1",
            event_time=event_time,
            spatial_system="meta",
            z_index="knowledge",
            id_strategy="content_hash",
            content_hash="abc123def456789012345678901234567890",
        )
        
        parts = parse_truthkey(key)
        
        assert parts.domain == "meta"
        assert parts.topic == "research_artifact"
        assert parts.spatial_system == "meta"
        assert parts.spatial_id == "abc123def45678901234567890123456"
        assert parts.z_index == "knowledge"
        assert parts.time_bucket == "2026-01-07T12:00Z"
    
    def test_build_meta_truthkey_with_provided_id(self):
        """Should build meta TruthKey with provided_id."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        key = build_truthkey(
            claim_type_id="meta.dataset_snapshot.v1",
            event_time=event_time,
            spatial_system="meta",
            z_index="knowledge",
            id_strategy="provided_id",
            artifact_id="dataset-2026-q1-final",
        )
        
        parts = parse_truthkey(key)
        
        assert parts.domain == "meta"
        assert parts.topic == "dataset_snapshot"
        assert parts.spatial_id == "dataset-2026-q1-final"
    
    def test_meta_truthkey_is_deterministic(self):
        """Same inputs should produce identical TruthKey."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        kwargs = {
            "claim_type_id": "meta.research_artifact.v1",
            "event_time": event_time,
            "spatial_system": "meta",
            "z_index": "knowledge",
            "id_strategy": "content_hash",
            "content_hash": "abc123def456789012345678901234567890",
        }
        
        key1 = build_truthkey(**kwargs)
        key2 = build_truthkey(**kwargs)
        
        assert key1 == key2


class TestBuildTruthKeyEarth:
    """Test build_truthkey for earth claims (H3)."""
    
    def test_build_earth_truthkey(self):
        """Should build valid earth TruthKey with H3."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        key = build_truthkey(
            claim_type_id="earth.flood.v1",
            event_time=event_time,
            location={"lat": 4.175, "lon": 73.509},
            spatial_system="h3",
            z_index="surface",
        )
        
        parts = parse_truthkey(key)
        
        assert parts.domain == "earth"
        assert parts.topic == "flood"
        assert parts.spatial_system == "h3"
        assert parts.z_index == "surface"
        # H3 index is computed (or mocked)
        assert parts.spatial_id.startswith("mock_h3") or len(parts.spatial_id) == 15
    
    def test_earth_without_location_fails(self):
        """Earth claims require location."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        with pytest.raises(ValueError) as exc_info:
            build_truthkey(
                claim_type_id="earth.flood.v1",
                event_time=event_time,
                location=None,  # Missing!
                spatial_system="h3",
            )
        
        assert "location required" in str(exc_info.value)


class TestBuildTruthKeySpace:
    """Test build_truthkey for space claims (HEALPix)."""
    
    def test_build_space_truthkey(self):
        """Should build valid space TruthKey with HEALPix."""
        event_time = datetime(2026, 1, 7, 12, 30, 0, tzinfo=timezone.utc)
        
        key = build_truthkey(
            claim_type_id="space.debris.v1",
            event_time=event_time,
            location={"ra": 180.0, "dec": 45.0},
            spatial_system="healpix",
            z_index="orbital_shell",
        )
        
        parts = parse_truthkey(key)
        
        assert parts.domain == "space"
        assert parts.topic == "debris"
        assert parts.spatial_system == "healpix"
        assert parts.z_index == "orbital_shell"


class TestDomainSpatialSystemEnums:
    """Test Domain and SpatialSystem enums."""
    
    def test_domain_includes_meta(self):
        """Domain enum should include META."""
        assert Domain.META.value == "meta"
    
    def test_spatial_system_includes_meta(self):
        """SpatialSystem enum should include META."""
        assert SpatialSystem.META.value == "meta"
    
    def test_spatial_system_includes_healpix(self):
        """SpatialSystem enum should include HEALPIX for space."""
        assert SpatialSystem.HEALPIX.value == "healpix"
