"""
Kaori Flow — Signal Primitive

Immutable event envelopes (FLOW_SPEC v4.0 Section 3).
Rule 1: Trust is Event-Sourced — signals are the only source of truth.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class SignalContext(BaseModel):
    """Optional context for a signal."""
    model_config = ConfigDict(frozen=True)
    
    mission_id: Optional[str] = None
    probe_id: Optional[str] = None
    claimtype_id: Optional[str] = None


class Signal(BaseModel):
    """
    Immutable event envelope (FLOW_SPEC v4.0 Section 3).
    
    Signals are the only source of truth. All standing/trust is derived
    from replaying signals through a versioned policy.
    """
    model_config = ConfigDict(frozen=True)

    # Identity (computed from canonical content)
    signal_id: str = Field(default="")  # SHA256 hash, computed on creation
    
    # Type
    signal_type: str  # e.g., "OBSERVATION_SUBMITTED", "TRUTHSTATE_EMITTED"
    
    # Temporal
    time: datetime  # UTC, explicit (not wall clock)
    
    # Origin
    agent_id: str  # Emitter (e.g., "user:amira", "sensor:jetson_042")
    
    # Target
    object_id: str  # Entity being acted on (e.g., "probe:flood-001")
    
    # Context (optional)
    context: Optional[SignalContext] = None
    
    # Payload
    payload: Dict[str, Any] = Field(default_factory=dict)
    
    # Policy version
    policy_version: str = "1.0.0"
    
    # Integrity (optional)
    signature: Optional[str] = None
    
    def model_post_init(self, __context: Any) -> None:
        """Compute signal_id if not provided."""
        if not self.signal_id:
            object.__setattr__(self, 'signal_id', self.compute_id())
    
    def compute_id(self) -> str:
        """Compute deterministic signal ID from canonical content."""
        canonical = self.canonical_dict()
        canonical_json = json.dumps(canonical, sort_keys=True, default=str)
        return hashlib.sha256(canonical_json.encode()).hexdigest()
    
    def canonical_dict(self) -> dict:
        """Get canonical representation for hashing (excludes signal_id and signature)."""
        return {
            "signal_type": self.signal_type,
            "time": self.time.isoformat(),
            "agent_id": self.agent_id,
            "object_id": self.object_id,
            "context": self.context.model_dump() if self.context else None,
            "payload": self.payload,
            "policy_version": self.policy_version,
        }


# Common signal type constants
class SignalTypes:
    """Standard signal types for Kaori Flow."""
    # Agent lifecycle
    AGENT_REGISTERED = "AGENT_REGISTERED"
    ROLE_GRANTED = "ROLE_GRANTED"
    
    # Probe/Mission lifecycle
    MISSION_CREATED = "MISSION_CREATED"
    PROBE_CREATED = "PROBE_CREATED"
    OBSERVER_ASSIGNED = "OBSERVER_ASSIGNED"
    
    # Observations
    OBSERVATION_SUBMITTED = "OBSERVATION_SUBMITTED"
    
    # Validation
    VALIDATION_VOTE = "VALIDATION_VOTE"
    
    # Truth outcomes
    TRUTHSTATE_EMITTED = "TRUTHSTATE_EMITTED"
    
    # Trust dynamics
    ENDORSEMENT = "ENDORSEMENT"
    DISPUTE_RAISED = "DISPUTE_RAISED"
    PENALTY_APPLIED = "PENALTY_APPLIED"
    
    # Policy
    POLICY_REGISTERED = "POLICY_REGISTERED"
