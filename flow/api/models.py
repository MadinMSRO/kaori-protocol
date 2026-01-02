"""
Kaori API — Request/Response Models

Pydantic models for API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# =============================================================================
# Observation Models
# =============================================================================

class ObservationCreate(BaseModel):
    """Request model for creating an observation."""
    claim_type: str = Field(..., example="earth.flood.v1")
    reporter_id: str
    geo: dict[str, float] = Field(..., example={"lat": 4.175, "lon": 73.509})
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    
    # Optional for specific domains
    depth_meters: Optional[float] = None
    right_ascension: Optional[float] = None
    declination: Optional[float] = None


class ObservationResponse(BaseModel):
    """Response model for observation."""
    observation_id: UUID
    claim_type: str
    truthkey: str
    status: str
    created_at: datetime


# =============================================================================
# Truth Models
# =============================================================================

class TruthStateResponse(BaseModel):
    """Response model for truth state."""
    truthkey: str
    claim_type: str
    status: str
    confidence: float
    ai_confidence: float
    verification_basis: Optional[str] = None
    transparency_flags: list[str] = Field(default_factory=list)
    observation_count: int
    created_at: datetime
    updated_at: datetime
    
    # Security
    is_signed: bool
    truth_hash: Optional[str] = None


class TruthHistoryResponse(BaseModel):
    """Response model for truth history (Silver ledger)."""
    truthkey: str
    history: list[dict[str, Any]]


# =============================================================================
# Vote Models
# =============================================================================

class VoteCreate(BaseModel):
    """Request model for submitting a vote."""
    truthkey: str
    voter_id: str
    vote_type: str = Field(..., pattern="^(RATIFY|REJECT|CHALLENGE|OVERRIDE)$")
    comment: Optional[str] = None


class VoteResponse(BaseModel):
    """Response model for vote."""
    vote_id: UUID
    truthkey: str
    voter_id: str
    vote_type: str
    voted_at: datetime
    consensus_score: int
    consensus_finalized: bool


# =============================================================================
# Mission Models
# =============================================================================

class MissionCreate(BaseModel):
    """Request model for creating a mission."""
    claim_type: str
    scope: dict[str, Any]
    requirements: dict[str, Any] = Field(default_factory=dict)
    rewards: dict[str, Any] = Field(default_factory=dict)


class MissionResponse(BaseModel):
    """Response model for mission."""
    mission_id: UUID
    claim_type: str
    status: str
    scope: dict[str, Any]
    requirements: dict[str, Any]
    rewards: dict[str, Any]
    created_at: datetime


class MissionListResponse(BaseModel):
    """Response model for listing missions."""
    missions: list[MissionResponse]
    total: int


# =============================================================================
# User Models
# =============================================================================

class UserStandingResponse(BaseModel):
    """Response model for user standing."""
    user_id: str
    standing: str
    trust_score: float
    verified_observations: int
    validation_accuracy: float
    tenure_days: int


class UserCreditsResponse(BaseModel):
    """Response model for user credits."""
    user_id: str
    total_credits: int
    available_credits: int
    lifetime_earned: int


# =============================================================================
# Schema Models
# =============================================================================

class SchemaListResponse(BaseModel):
    """Response model for listing schemas."""
    schemas: list[str]


class SchemaDetailResponse(BaseModel):
    """Response model for schema details."""
    id: str
    version: int
    domain: str
    topic: str
    risk_profile: str
    config: dict[str, Any]


# =============================================================================
# Common Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None
    code: str
