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
    voter_standing: str = Field(default="bronze", pattern="^(bronze|silver|expert|authority)$")
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
# Probe Models (Flow Primitive)
# =============================================================================

class SignalTriggerRequest(BaseModel):
    """Request model for submitting a trigger signal (creates a Probe Proposal)."""
    type: str = Field(..., pattern="^(MANUAL_TRIGGER|AUTOMATED_TRIGGER|SCHEDULED_TRIGGER)$")
    source_standing: str = Field(default="bronze", pattern="^(bronze|silver|expert|authority)$")
    claim_type: str = Field(..., example="earth.flood.v1")
    scope: dict[str, Any] = Field(..., example={"type": "h3", "value": "8928308280fffff"})
    # Optional: link to existing TruthKey if investigating
    truthkey: Optional[str] = None
    # Optional requirements override
    requirements: dict[str, Any] = Field(default_factory=dict)


class ProbeApprovalRequest(BaseModel):
    """Request model for approving a proposed probe."""
    approver_id: str


class ProbeResponse(BaseModel):
    """Response model for probe (aligned with core.models.Probe)."""
    probe_id: UUID
    probe_key: str
    claim_type: str
    status: str
    scope: dict[str, Any]
    active_signals: list[UUID]
    requirements: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime]


class ProbeListResponse(BaseModel):
    """List response for probes."""
    probes: list[ProbeResponse]
    total: int


# Legacy model kept for backwards compatibility
class MissionCreate(BaseModel):
    """[DEPRECATED] Use SignalTriggerRequest instead."""
    claim_type: str
    scope: dict[str, Any]
    requirements: dict[str, Any] = Field(default_factory=dict)
    rewards: dict[str, Any] = Field(default_factory=dict)


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
