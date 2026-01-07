"""
Kaori Flow — Network Edge Primitive

Trust edges between Agents (FLOW_SPEC Section 2.2).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    """Type of edge in the trust network."""
    VOUCH = "VOUCH"           # A explicitly trusts B
    MEMBER_OF = "MEMBER_OF"   # A belongs to Squad B
    COLLABORATE = "COLLABORATE"  # History of agreement
    CONFLICT = "CONFLICT"     # History of disagreement


class NetworkEdge(BaseModel):
    """
    Edge in the trust network (FLOW_SPEC Section 2.2).
    Defines relationships between Agents.
    """
    edge_id: UUID = Field(default_factory=uuid4)
    edge_type: EdgeType
    source_agent_id: UUID
    target_agent_id: UUID
    weight: float = Field(default=1.0, ge=0.0)  # Coupling strength
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None  # CONFLICT edges never expire
    
    @property
    def is_trust_edge(self) -> bool:
        """Check if this is a trust-transferring edge."""
        return self.edge_type in (EdgeType.VOUCH, EdgeType.MEMBER_OF)
    
    @property
    def is_signal_edge(self) -> bool:
        """Check if this is a signal/relationship edge."""
        return self.edge_type in (EdgeType.COLLABORATE, EdgeType.CONFLICT)
