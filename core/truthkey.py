"""
Kaori Core — TruthKey Generation

Functions for generating and parsing TruthKeys as defined in SPEC.md Section 4.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import (
    Domain,
    Observation,
    SpatialSystem,
    TruthKey,
)


def normalize_time_bucket(dt: datetime, duration: str) -> str:
    """
    Normalize a datetime to a time bucket based on ISO8601 duration.
    
    Supported durations:
    - PT1H (hourly)
    - PT15M (15-minute)
    - PT1M (1-minute)
    - P1D (daily)
    
    Returns ISO8601 timestamp truncated to bucket boundary.
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    # Parse duration
    if duration == "PT1H":
        # Truncate to hour
        truncated = dt.replace(minute=0, second=0, microsecond=0)
    elif duration == "PT15M":
        # Truncate to 15-minute boundary
        minute = (dt.minute // 15) * 15
        truncated = dt.replace(minute=minute, second=0, microsecond=0)
    elif duration == "PT1M":
        # Truncate to minute
        truncated = dt.replace(second=0, microsecond=0)
    elif duration == "P1D":
        # Truncate to day
        truncated = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif duration == "PT4H":
        # Truncate to 4-hour boundary
        hour = (dt.hour // 4) * 4
        truncated = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif duration == "PT6H":
        # Truncate to 6-hour boundary
        hour = (dt.hour // 6) * 6
        truncated = dt.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif duration.startswith("P") and duration.endswith("D"):
        # P7D, P30D etc - truncate to day
        truncated = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # Default to hourly
        truncated = dt.replace(minute=0, second=0, microsecond=0)
    
    return truncated.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_h3_index(lat: float, lon: float, resolution: int) -> str:
    """
    Compute H3 index for a lat/lon coordinate.
    
    Requires h3 library. Returns hex string.
    """
    try:
        import h3
        # h3 v4.x API
        return h3.latlng_to_cell(lat, lon, resolution)
    except ImportError:
        # Fallback for testing without h3
        return f"mock_h3_{resolution}_{lat:.3f}_{lon:.3f}"


def compute_healpix_index(ra: float, dec: float, nside: int = 4096) -> str:
    """
    Compute HEALPix index for RA/Dec coordinates.
    
    Uses astropy-healpix (preferred, Windows compatible) or healpy as fallback.
    Returns string pixel index.
    """
    try:
        # Try astropy-healpix first (works on Windows)
        from astropy_healpix import HEALPix
        import astropy.units as u
        
        hp = HEALPix(nside=nside, order='ring')
        # Use lonlat_to_healpix: lon=RA, lat=Dec
        pixel = hp.lonlat_to_healpix(ra * u.deg, dec * u.deg)
        return str(pixel)
    except ImportError:
        pass
    
    try:
        # Fallback to healpy (requires C compiler)
        import healpy as hp
        import numpy as np
        theta = np.radians(90 - dec)  # Dec to co-latitude
        phi = np.radians(ra)
        pixel = hp.ang2pix(nside, theta, phi)
        return str(pixel)
    except ImportError:
        # Fallback for testing without either library
        return f"mock_healpix_{nside}_{ra:.3f}_{dec:.3f}"


def generate_truthkey(observation: Observation, claim_config: dict) -> TruthKey:
    """
    Generate a TruthKey from an observation and claim configuration.
    
    Args:
        observation: The Bronze observation
        claim_config: Loaded claim YAML configuration
        
    Returns:
        TruthKey with normalized spatial and temporal components
    """
    # Extract truthkey config
    tk_config = claim_config.get("truthkey", {})
    
    # Domain
    domain = Domain(claim_config.get("domain", "earth"))
    
    # Topic
    topic = claim_config.get("topic", "unknown")
    
    # Spatial system
    spatial_system = SpatialSystem(tk_config.get("spatial_system", "h3"))
    resolution = tk_config.get("resolution", 8)
    
    # Compute spatial ID based on system
    if spatial_system == SpatialSystem.H3:
        lat = observation.geo.get("lat", 0)
        lon = observation.geo.get("lon", 0)
        spatial_id = compute_h3_index(lat, lon, resolution)
    elif spatial_system == SpatialSystem.HEALPIX:
        ra = observation.right_ascension or 0
        dec = observation.declination or 0
        spatial_id = compute_healpix_index(ra, dec, nside=2**resolution)
    else:
        # Fallback
        spatial_id = "unknown"
    
    # Z-index
    z_index = tk_config.get("z_index", "surface")
    if z_index == "underwater" and observation.depth_meters is not None:
        # Include depth range in z_index
        depth_bucket = int(observation.depth_meters // 10) * 10  # 10m buckets
        z_index = f"depth_{depth_bucket}m"
    
    # Time bucket
    time_bucket_duration = tk_config.get("time_bucket", "PT1H")
    time_bucket = normalize_time_bucket(observation.reported_at, time_bucket_duration)
    
    return TruthKey(
        domain=domain,
        topic=topic,
        spatial_system=spatial_system,
        spatial_id=spatial_id,
        z_index=z_index,
        time_bucket=time_bucket,
    )


def parse_truthkey(truthkey_string: str) -> TruthKey:
    """Parse a TruthKey from its canonical string format."""
    return TruthKey.from_string(truthkey_string)


def format_truthkey(truthkey: TruthKey) -> str:
    """Format a TruthKey to its canonical string format."""
    return truthkey.to_string()
