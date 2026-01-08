"""
Kaori Flow — Agent Primitive

The atomic unit of the Kaori Flow system (FLOW_SPEC v4.0 Section 2).
Rule 2: Everything is an Agent.
Rule 3: Standing is the Primitive of Trust.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """Type of agent in the network (FLOW_SPEC v4.0 Rule 2)."""
    INDIVIDUAL = "individual"   # Human observers
    SENSOR = "sensor"           # IoT devices, satellites, calibrated sensors
    VALIDATOR = "validator"     # Vote on observations
    OFFICIAL = "official"       # Authority / government / calibrated
    CLAIMTYPE = "claimtype"     # Verification contract agents
    PROBE = "probe"             # Coordination object agents
    MISSION = "mission"         # High-level coordination agents
    POLICY = "policy"           # FlowPolicy agents
    SYSTEM = "system"           # Genesis / orchestrator


# Standing bounds (FLOW_SPEC v4.0 Rule 3)
STANDING_MIN = 0.0
STANDING_MAX = 1000.0
STANDING_DEFAULT = 200.0


class Agent(BaseModel):
    """
    The atomic unit of the Kaori Flow system (FLOW_SPEC v4.0).
    
    Rule 2: Everything is an Agent — all entities participate uniformly.
    Rule 3: Standing is the only persistent trust primitive.
    Rule 4: Standing is global; trust is local (computed at query time).
    """
    agent_id: str  # Canonical ID (e.g., "user:amira", "sensor:jetson_042")
    agent_type: AgentType = AgentType.INDIVIDUAL
    
    # Rule 3: Standing is the only persistent scalar
    standing: float = Field(
        default=STANDING_DEFAULT, 
        ge=STANDING_MIN, 
        le=STANDING_MAX
    )
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @property
    def derived_class(self) -> str:
        """
        Derive standing class from scalar value.
        Thresholds based on 0-1000 range.
        """
        if self.standing < 300:
            return "bronze"
        elif self.standing < 500:
            return "silver"
        elif self.standing < 700:
            return "expert"
        else:
            return "authority"
    
    @property
    def is_high_assurance(self) -> bool:
        """Check if agent is high-assurance (official or calibrated sensor)."""
        return self.agent_type in (AgentType.OFFICIAL, AgentType.SENSOR)
    
    def clamp_standing(self) -> None:
        """Ensure standing stays within bounds."""
        self.standing = max(STANDING_MIN, min(self.standing, STANDING_MAX))


def create_agent_id(agent_type: AgentType, identifier: str) -> str:
    """
    Create canonical agent ID.
    
    Examples:
        create_agent_id(AgentType.INDIVIDUAL, "amira") -> "user:amira"
        create_agent_id(AgentType.SENSOR, "jetson_042") -> "sensor:jetson_042"
    """
    type_prefixes = {
        AgentType.INDIVIDUAL: "user",
        AgentType.SENSOR: "sensor",
        AgentType.VALIDATOR: "validator",
        AgentType.OFFICIAL: "official",
        AgentType.CLAIMTYPE: "claimtype",
        AgentType.PROBE: "probe",
        AgentType.MISSION: "mission",
        AgentType.POLICY: "policy",
        AgentType.SYSTEM: "system",
    }
    prefix = type_prefixes.get(agent_type, "agent")
    return f"{prefix}:{identifier}"
