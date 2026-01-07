"""
Kaori Truth — Observation Primitive

Bronze layer observation with canonicalization.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from kaori_truth.canonical import canonical_hash, canonical_json
from kaori_truth.canonical.datetime import canonical_datetime
from kaori_truth.canonical.schema import CanonicalSchema, canonicalize_by_schema
from kaori_truth.time import ensure_utc

from .evidence import EvidenceRef


class Standing(str, Enum):
    """User standing classes."""
    BRONZE = "bronze"
    SILVER = "silver"
    EXPERT = "expert"
    AUTHORITY = "authority"


class ReporterContext(BaseModel):
    """Context about the reporter submitting an observation."""
    standing: Standing
    trust_score: float = Field(ge=0.0, le=1.0)
    source_type: str = "human"  # human, sensor, drone, official
    
    def canonical(self) -> dict:
        """Get canonical representation."""
        return {
            "source_type": self.source_type.lower(),
            "standing": self.standing.value,
            "trust_score": self.trust_score,
        }


class Observation(BaseModel):
    """
    Bronze layer observation (SPEC Section 6).
    
    Raw input from reporters/sensors before validation.
    Observations MUST be canonical for deterministic hashing.
    """
    observation_id: UUID = Field(default_factory=uuid4)
    probe_id: Optional[UUID] = None  # Optional link to Flow Probe
    claim_type: str  # e.g., "earth.flood.v1"
    reported_at: datetime  # Event time (MUST be timezone-aware)
    reporter_id: str
    reporter_context: ReporterContext
    geo: Dict[str, float]  # {"lat": ..., "lon": ...}
    payload: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    
    # Legacy evidence fields (for backwards compatibility)
    evidence_hashes: Dict[str, str] = Field(default_factory=dict)
    
    # Optional domain-specific fields
    depth_meters: Optional[float] = None  # Ocean domain
    right_ascension: Optional[float] = None  # Space domain
    declination: Optional[float] = None  # Space domain
    
    @field_validator('reported_at')
    @classmethod
    def validate_reported_at(cls, v: datetime) -> datetime:
        """Ensure reported_at is timezone-aware UTC."""
        return ensure_utc(v)
    
    def canonical(self) -> dict:
        """
        Get canonical representation for hashing.
        
        Per protocol requirements, observation hash MUST be deterministic.
        """
        result = {
            "observation_id": str(self.observation_id),
            "claim_type": self.claim_type.lower(),
            "reported_at": canonical_datetime(self.reported_at),
            "reporter_id": self.reporter_id,
            "reporter_context": self.reporter_context.canonical(),
            "geo": self._canonical_geo(),
            "payload": self._canonical_payload(),
            "evidence_refs": [ref.canonical() for ref in self.evidence_refs],
        }
        
        # Optional fields only if present
        if self.probe_id:
            result["probe_id"] = str(self.probe_id)
        if self.depth_meters is not None:
            result["depth_meters"] = round(self.depth_meters, 2)
        if self.right_ascension is not None:
            result["right_ascension"] = round(self.right_ascension, 6)
        if self.declination is not None:
            result["declination"] = round(self.declination, 6)
        
        return result
    
    def _canonical_geo(self) -> dict:
        """Canonicalize geo coordinates with rounding."""
        return {
            "lat": round(self.geo.get("lat", 0), 6),
            "lon": round(self.geo.get("lon", 0), 6),
        }
    
    def _canonical_payload(self) -> dict:
        """Canonicalize payload (sort keys, normalize values)."""
        from kaori_truth.canonical.json import canonical_dict
        return canonical_dict(self.payload)
    
    def hash(self) -> str:
        """
        Compute canonical hash of this observation.
        
        observation_hash = SHA256(canonical observation payload)
        """
        return canonical_hash(self.canonical())


def canonical_observation(obs: Observation) -> dict:
    """
    Get canonical representation of an Observation.
    
    Args:
        obs: The Observation to canonicalize
        
    Returns:
        Canonical dictionary representation
    """
    return obs.canonical()


def observation_hash(obs: Observation) -> str:
    """
    Compute canonical hash of an Observation.
    
    Args:
        obs: The Observation to hash
        
    Returns:
        SHA256 hex hash
    """
    return obs.hash()
