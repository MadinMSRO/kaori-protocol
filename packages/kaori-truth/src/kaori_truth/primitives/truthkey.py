"""
Kaori Truth — TruthKey Primitive

Canonical join key for truth across space/time (SPEC Section 4).
Implements strict canonicalization per protocol requirements.
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import NamedTuple, Optional

from pydantic import BaseModel, Field, field_validator

from kaori_truth.canonical import canonical_hash
from kaori_truth.canonical.string import validate_canonical_id, to_canonical_id
from kaori_truth.time import bucket_datetime, format_bucket


class Domain(str, Enum):
    """Spatial domains supported by Kaori."""
    EARTH = "earth"
    OCEAN = "ocean"
    SPACE = "space"
    META = "meta"  # Non-spatial domain for research artifacts


class SpatialSystem(str, Enum):
    """Spatial indexing systems."""
    H3 = "h3"           # Earth/Ocean
    GEOHASH = "geohash"
    HEALPIX = "healpix" # Space
    META = "meta"       # Non-spatial (artifacts, datasets)
    CUSTOM = "custom"


# Canonical TruthKey segment pattern: lowercase alphanumeric, dots, underscores, hyphens
SEGMENT_PATTERN = re.compile(r'^[a-z0-9._-]+$')


class TruthKeyParts(NamedTuple):
    """Parsed TruthKey components."""
    domain: str
    topic: str
    spatial_system: str
    spatial_id: str
    z_index: str
    time_bucket: str


class TruthKey(BaseModel):
    """
    Canonical join key for truth across space/time (SPEC Section 4).
    
    Format: {domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
    
    All segments MUST be lowercase and contain only valid characters.
    """
    domain: Domain
    topic: str
    spatial_system: SpatialSystem
    spatial_id: str
    z_index: str
    time_bucket: str  # Canonical format: YYYY-MM-DDTHH:MMZ
    
    @field_validator('topic', 'spatial_id', 'z_index')
    @classmethod
    def validate_segment(cls, v: str) -> str:
        """Validate and normalize segment to canonical form."""
        v = v.lower()
        if not SEGMENT_PATTERN.match(v):
            raise ValueError(f"Invalid TruthKey segment: {v}. Must match [a-z0-9._-]+")
        return v
    
    def to_string(self) -> str:
        """Convert to canonical string format."""
        return canonical_truthkey(self.to_parts())
    
    def to_parts(self) -> TruthKeyParts:
        """Convert to TruthKeyParts tuple."""
        return TruthKeyParts(
            domain=self.domain.value,
            topic=self.topic,
            spatial_system=self.spatial_system.value,
            spatial_id=self.spatial_id,
            z_index=self.z_index,
            time_bucket=self.time_bucket,
        )
    
    @classmethod
    def from_string(cls, s: str) -> TruthKey:
        """Parse from canonical string format."""
        parts = parse_truthkey(s)
        return cls(
            domain=Domain(parts.domain),
            topic=parts.topic,
            spatial_system=SpatialSystem(parts.spatial_system),
            spatial_id=parts.spatial_id,
            z_index=parts.z_index,
            time_bucket=parts.time_bucket,
        )
    
    def hash(self) -> str:
        """Compute canonical hash of this TruthKey."""
        return canonical_hash(self.to_string())


def canonical_truthkey(parts: TruthKeyParts) -> str:
    """
    Convert TruthKeyParts to canonical string.
    
    Canonical rules:
    1. All segments lowercase
    2. Colon separator only
    3. Strict segment charset: [a-z0-9._-]
    4. time_bucket in canonical UTC format
    
    Args:
        parts: TruthKey components
        
    Returns:
        Canonical TruthKey string
    """
    segments = [
        parts.domain.lower(),
        parts.topic.lower(),
        parts.spatial_system.lower(),
        parts.spatial_id.lower(),
        parts.z_index.lower(),
        parts.time_bucket,  # Already canonical format
    ]
    
    return ':'.join(segments)


def parse_truthkey(key: str) -> TruthKeyParts:
    """
    Parse a TruthKey string into components.
    
    Args:
        key: The TruthKey string to parse
        
    Returns:
        TruthKeyParts with parsed components
        
    Raises:
        ValueError: If the format is invalid
    """
    # Use maxsplit=5 to preserve colons in timestamp
    parts = key.split(':', maxsplit=5)
    
    if len(parts) != 6:
        raise ValueError(f"Invalid TruthKey format: {key}. Expected 6 segments.")
    
    return TruthKeyParts(
        domain=parts[0].lower(),
        topic=parts[1].lower(),
        spatial_system=parts[2].lower(),
        spatial_id=parts[3].lower(),
        z_index=parts[4].lower(),
        time_bucket=parts[5],
    )


def build_truthkey(
    claim_type_id: str,
    event_time: datetime,
    location: dict = None,
    *,
    time_bucket_duration: str = "PT1H",
    spatial_system: str = "h3",
    spatial_resolution: int = 8,
    z_index: str = "surface",
    id_strategy: str = "content_hash",
    artifact_id: str = None,
    content_hash: str = None,
) -> str:
    """
    Build a canonical TruthKey from event parameters.
    
    This is the primary function for generating TruthKeys from observations.
    TruthKey derives from event_time, not receipt_time.
    
    For spatial claims (earth, ocean, space):
        - Uses H3/HEALPix based on domain
        - location MUST be provided
    
    For meta claims (artifacts, datasets):
        - Uses id_strategy to derive spatial_id
        - Either content_hash or artifact_id MUST be provided
    
    Args:
        claim_type_id: Claim type ID (e.g., "earth.flood.v1", "meta.research_artifact.v1")
        event_time: The event timestamp (MUST be timezone-aware)
        location: Location dict with lat/lon (required for spatial claims)
        time_bucket_duration: ISO8601 duration for bucketing
        spatial_system: Spatial indexing system (h3, healpix, meta)
        spatial_resolution: Resolution for spatial system
        z_index: Vertical index (surface, underwater, knowledge, etc.)
        id_strategy: For meta claims: content_hash | provided_id | hybrid
        artifact_id: User-provided stable ID (for provided_id strategy)
        content_hash: Content hash (for content_hash strategy)
        
    Returns:
        Canonical TruthKey string
    """
    # Parse claim type to extract domain and topic
    parts = claim_type_id.split('.')
    if len(parts) < 2:
        raise ValueError(f"Invalid claim_type_id format: {claim_type_id}")
    
    domain = parts[0].lower()
    topic = parts[1].lower()
    
    # Bucket the event time
    bucketed_time = bucket_datetime(event_time, time_bucket_duration)
    time_bucket = format_bucket(bucketed_time)
    
    # Compute spatial ID based on spatial_system
    if spatial_system == "h3":
        if not location:
            raise ValueError("location required for H3 spatial system")
        spatial_id = _compute_h3_index(
            location.get("lat", 0),
            location.get("lon", 0),
            spatial_resolution
        )
    elif spatial_system == "healpix":
        if not location:
            raise ValueError("location required for HEALPix spatial system")
        spatial_id = _compute_healpix_index(
            location.get("ra", 0),
            location.get("dec", 0),
            spatial_resolution
        )
    elif spatial_system == "meta":
        # Meta claims use id_strategy to derive spatial_id
        spatial_id = _compute_meta_id(
            id_strategy=id_strategy,
            content_hash=content_hash,
            artifact_id=artifact_id,
        )
    else:
        spatial_id = "unknown"
    
    key_parts = TruthKeyParts(
        domain=domain,
        topic=topic,
        spatial_system=spatial_system,
        spatial_id=spatial_id,
        z_index=z_index,
        time_bucket=time_bucket,
    )
    
    return canonical_truthkey(key_parts)


def _compute_h3_index(lat: float, lon: float, resolution: int) -> str:
    """Compute H3 index for lat/lon."""
    try:
        import h3
        return h3.latlng_to_cell(lat, lon, resolution)
    except ImportError:
        return f"mock_h3_{resolution}_{lat:.3f}_{lon:.3f}"


def _compute_healpix_index(ra: float, dec: float, nside: int = 4096) -> str:
    """Compute HEALPix index for RA/Dec."""
    try:
        from astropy_healpix import HEALPix
        import astropy.units as u
        hp = HEALPix(nside=nside, order='ring')
        pixel = hp.lonlat_to_healpix(ra * u.deg, dec * u.deg)
        return str(pixel)
    except ImportError:
        return f"mock_healpix_{nside}_{ra:.3f}_{dec:.3f}"


def _compute_meta_id(
    id_strategy: str,
    content_hash: str = None,
    artifact_id: str = None,
) -> str:
    """
    Compute spatial_id for meta claims using id_strategy.
    
    Args:
        id_strategy: content_hash | provided_id | hybrid
        content_hash: SHA256 hash of artifact content
        artifact_id: User-provided stable identifier
        
    Returns:
        Canonical spatial_id (lowercase)
        
    Raises:
        ValueError: If required fields are missing for strategy
    """
    id_strategy = id_strategy.lower()
    
    if id_strategy == "content_hash":
        if not content_hash:
            raise ValueError("content_hash required for content_hash id_strategy")
        return content_hash.lower()[:32]  # Truncate for readability
    
    elif id_strategy == "provided_id":
        if not artifact_id:
            raise ValueError("artifact_id required for provided_id id_strategy")
        return artifact_id.lower()
    
    elif id_strategy == "hybrid":
        # Prefer content_hash, fall back to artifact_id
        if content_hash:
            return content_hash.lower()[:32]
        elif artifact_id:
            return artifact_id.lower()
        else:
            raise ValueError(
                "Either content_hash or artifact_id required for hybrid id_strategy"
            )
    
    else:
        raise ValueError(f"Unknown id_strategy: {id_strategy}")
