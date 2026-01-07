"""
Kaori Flow — Probe Primitive

Coordination object (FLOW_SPEC Section 2.4).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProbeStatus(str, Enum):
    """Status of a probe."""
    PROPOSED = "PROPOSED"      # Created by low-standing signal, awaiting approval
    ACTIVE = "ACTIVE"          # Approved and open for assignment
    ASSIGNED = "ASSIGNED"      # Linked to an Agent
    IN_PROGRESS = "IN_PROGRESS" # Observation received
    COMPLETED = "COMPLETED"    # TruthState finalized
    EXPIRED = "EXPIRED"        # Time window closed
    CANCELLED = "CANCELLED"    # Administratively cancelled


class Probe(BaseModel):
    """
    Persistent coordination object (FLOW_SPEC Section 2.4).
    Directs agents to gather observations.
    
    ProbeKey is deterministic: hash(claim_type + scope)
    """
    probe_id: UUID = Field(default_factory=uuid4)
    probe_key: str  # Deterministic key for dedupe
    claim_type: str
    status: ProbeStatus = ProbeStatus.PROPOSED
    
    # Scope
    scope: Dict[str, Any] = Field(default_factory=dict)
    
    # Origin
    created_by_signal: Optional[UUID] = None
    active_signals: List[UUID] = Field(default_factory=list)
    
    # Requirements
    requirements: Dict[str, Any] = Field(default_factory=dict)
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    def is_active(self) -> bool:
        """Check if probe is in an active state."""
        return self.status in (
            ProbeStatus.ACTIVE,
            ProbeStatus.ASSIGNED,
            ProbeStatus.IN_PROGRESS,
        )
