"""
Kaori Flow — Agent Primitive

The atomic unit of the Kaori Flow system (FLOW_SPEC Section 2.1).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """Type of agent in the network."""
    INDIVIDUAL = "individual"
    SQUAD = "squad"
    SENSOR = "sensor"
    OFFICIAL = "official"


class Agent(BaseModel):
    """
    The atomic unit of the Kaori Flow system (FLOW_SPEC Section 2.1).
    Represents a person, sensor, drone, squad, or organization.
    
    Standing is a continuous scalar float (0.0 to ∞).
    Standing classes are derived for backwards compatibility.
    """
    agent_id: UUID = Field(default_factory=uuid4)
    agent_type: AgentType = AgentType.INDIVIDUAL
    standing: float = Field(default=10.0, ge=0.0)  # Continuous scalar
    
    # Per-domain qualifications ("Genome")
    qualifications: Dict[str, str] = Field(default_factory=dict)  # {"earth.flood": "expert"}
    
    # Stats
    verified_observations: int = 0
    correct_votes: int = 0
    total_votes: int = 0
    
    # Isolation metric for echo chamber detection
    isolation_metric: float = 0.0
    
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def derived_class(self) -> str:
        """
        Derive standing class from scalar value.
        Per FLOW_SPEC Section 2.1.
        """
        if self.standing < 100:
            return "bronze"
        elif self.standing < 250:
            return "silver"
        elif self.standing < 500:
            return "expert"
        else:
            return "authority"
    
    @property
    def is_high_assurance(self) -> bool:
        """Check if agent is high-assurance (official or calibrated sensor)."""
        return self.agent_type in (AgentType.OFFICIAL, AgentType.SENSOR)
    
    def compute_effective_power(
        self,
        inherited_power: float = 0.0,
        isolation_penalty: float = 0.0,
    ) -> float:
        """
        Compute effective power for voting/observation.
        
        Power = (Intrinsic + Inherited) * (1 - IsolationPenalty)
        """
        raw_power = self.standing + inherited_power
        return raw_power * (1 - isolation_penalty)
