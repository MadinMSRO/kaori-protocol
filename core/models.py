"""
Kaori Core — Data Models

Pydantic models for all protocol primitives as defined in SPEC.md v1.3.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class Domain(str, Enum):
    """Spatial domains supported by Kaori."""
    EARTH = "earth"
    OCEAN = "ocean"
    SPACE = "space"


class SpatialSystem(str, Enum):
    """Spatial indexing systems."""
    H3 = "h3"
    GEOHASH = "geohash"
    HEALPIX = "healpix"
    CUSTOM = "custom"


class TruthStatus(str, Enum):
    """Allowed truth state status values (SPEC Section 8.1)."""
    PENDING = "PENDING"
    INVESTIGATING = "INVESTIGATING"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"  # Critical lane: awaiting human consensus
    VERIFIED_TRUE = "VERIFIED_TRUE"
    VERIFIED_FALSE = "VERIFIED_FALSE"
    INCONCLUSIVE = "INCONCLUSIVE"  # Review timed out without reaching consensus
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"


class VerificationBasis(str, Enum):
    """What caused the verification."""
    AI_AUTOVALIDATION = "AI_AUTOVALIDATION"
    HUMAN_CONSENSUS = "HUMAN_CONSENSUS"
    AUTHORITY_OVERRIDE = "AUTHORITY_OVERRIDE"
    TIMEOUT_DEFAULT = "TIMEOUT_DEFAULT"
    TIMEOUT_INCONCLUSIVE = "TIMEOUT_INCONCLUSIVE"  # Review timed out


class Standing(str, Enum):
    """User standing classes."""
    BRONZE = "bronze"
    SILVER = "silver"
    EXPERT = "expert"
    AUTHORITY = "authority"


class VoteType(str, Enum):
    """Vote type options."""
    RATIFY = "RATIFY"
    REJECT = "REJECT"
    CHALLENGE = "CHALLENGE"
    OVERRIDE = "OVERRIDE"


# =============================================================================
# TruthKey
# =============================================================================

class TruthKey(BaseModel):
    """
    Canonical join key for truth across space/time (SPEC Section 4).
    
    Format: {domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
    """
    domain: Domain
    topic: str
    spatial_system: SpatialSystem
    spatial_id: str
    z_index: str
    time_bucket: str  # ISO8601 normalized
    
    def to_string(self) -> str:
        """Convert to canonical string format."""
        return f"{self.domain.value}:{self.topic}:{self.spatial_system.value}:{self.spatial_id}:{self.z_index}:{self.time_bucket}"
    
    @classmethod
    def from_string(cls, s: str) -> TruthKey:
        """Parse from canonical string format."""
        # Use maxsplit=5 to preserve colons in timestamp
        parts = s.split(":", maxsplit=5)
        if len(parts) != 6:
            raise ValueError(f"Invalid TruthKey format: {s}")
        return cls(
            domain=Domain(parts[0]),
            topic=parts[1],
            spatial_system=SpatialSystem(parts[2]),
            spatial_id=parts[3],
            z_index=parts[4],
            time_bucket=parts[5],
        )


# =============================================================================
# Reporter Context
# =============================================================================

class ReporterContext(BaseModel):
    """Context about the reporter submitting an observation."""
    standing: Standing
    trust_score: float = Field(ge=0.0, le=1.0)
    source_type: str = "human"  # human, sensor, drone, official


# =============================================================================
# Observation (Bronze)
# =============================================================================

class Observation(BaseModel):
    """
    Bronze layer observation (SPEC Section 6).
    
    Raw input from reporters/sensors before validation.
    """
    observation_id: UUID = Field(default_factory=uuid4)
    claim_type: str  # e.g., "earth.flood.v1"
    reported_at: datetime
    reporter_id: str
    reporter_context: ReporterContext
    geo: dict[str, float]  # {"lat": ..., "lon": ...}
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_hashes: dict[str, str] = Field(default_factory=dict)
    
    # Optional depth for ocean domain
    depth_meters: Optional[float] = None
    
    # Optional celestial coords for space domain
    right_ascension: Optional[float] = None
    declination: Optional[float] = None


# =============================================================================
# Vote
# =============================================================================

class Vote(BaseModel):
    """A validation vote from a user."""
    vote_id: UUID = Field(default_factory=uuid4)
    voter_id: str
    voter_standing: Standing
    vote_type: VoteType
    voted_at: datetime
    comment: Optional[str] = None


# =============================================================================
# Consensus Record
# =============================================================================

class ConsensusRecord(BaseModel):
    """Record of consensus computation (SPEC Section 10)."""
    votes: list[Vote] = Field(default_factory=list)
    score: int = 0
    finalized: bool = False
    finalize_reason: Optional[str] = None
    positive_ratio: float = 0.0  # (ratify - reject) / total


# =============================================================================
# AI Validation Result
# =============================================================================

class AIValidationResult(BaseModel):
    """Result from AI validation pipeline."""
    bouncer_passed: bool = False
    generalist_confidence: Optional[float] = None
    specialist_confidence: Optional[float] = None
    final_confidence: float = 0.0
    routed_to_human: bool = False
    rejection_reason: Optional[str] = None


# =============================================================================
# Confidence Breakdown
# =============================================================================

class ConfidenceBreakdown(BaseModel):
    """Breakdown of composite confidence calculation (SPEC Section 11)."""
    components: dict[str, float] = Field(default_factory=dict)
    modifiers: dict[str, float] = Field(default_factory=dict)
    raw_score: float = 0.0
    final_score: float = 0.0  # After clamping


# =============================================================================
# Security Block
# =============================================================================

class SecurityBlock(BaseModel):
    """Cryptographic security for truth state (SPEC Section 16)."""
    truth_hash: str
    truth_signature: str
    signing_method: str = "local_hmac"  # or "gcp_kms"
    key_id: str
    signed_at: datetime


# =============================================================================
# Truth State (Gold)
# =============================================================================

class TruthState(BaseModel):
    """
    Gold layer truth state (SPEC Section 8).
    
    The verified, signed representation of truth.
    """
    truthkey: TruthKey
    claim_type: str
    status: TruthStatus = TruthStatus.PENDING
    verification_basis: Optional[VerificationBasis] = None
    
    # Confidence
    ai_confidence: float = 0.0
    confidence: float = 0.0
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    
    # Transparency
    transparency_flags: list[str] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Validation
    ai_validation: Optional[AIValidationResult] = None
    consensus: Optional[ConsensusRecord] = None
    
    # Evidence
    evidence_refs: list[str] = Field(default_factory=list)
    observation_ids: list[UUID] = Field(default_factory=list)
    
    # Security (required for Silver/Gold)
    security: Optional[SecurityBlock] = None
