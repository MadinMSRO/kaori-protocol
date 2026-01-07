"""
Kaori Truth — Trust Snapshot Data

TrustSnapshot is data provided BY Flow TO Truth for compilation.
The TrustSnapshot schema lives in kaori-truth, but TrustProvider
implementation lives in kaori-flow.

Truth receives TrustSnapshot as input, never calls TrustProvider directly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from kaori_truth.canonical import canonical_hash, canonical_json
from kaori_truth.canonical.datetime import canonical_datetime


class AgentTrust(BaseModel):
    """
    Trust data for a single agent at snapshot time.
    
    This is a frozen snapshot of an agent's trust state.
    """
    agent_id: str
    effective_power: float  # Computed power including inheritance
    standing: float  # Raw standing value
    derived_class: str  # "bronze" | "silver" | "expert" | "authority"
    flags: List[str] = Field(default_factory=list)  # e.g., ["ISOLATED", "HIGH_ASSURANCE"]
    
    def canonical(self) -> dict:
        """Get canonical representation."""
        return {
            "agent_id": self.agent_id,
            "effective_power": round(self.effective_power, 6),
            "standing": round(self.standing, 6),
            "derived_class": self.derived_class.lower(),
            "flags": sorted(self.flags),
        }


class TrustSnapshot(BaseModel):
    """
    Canonical frozen snapshot of trust state.
    
    This is provided by Flow to Truth for deterministic compilation.
    The hash is computed over the canonical JSON of all agent trusts.
    
    INVARIANT: Given identical agent_trusts, the snapshot_hash MUST be identical.
    """
    snapshot_id: str  # Unique identifier for this snapshot
    snapshot_time: datetime  # When the snapshot was taken
    agent_trusts: Dict[str, AgentTrust] = Field(default_factory=dict)  # {agent_id: trust}
    snapshot_hash: str  # SHA256 of canonical JSON
    
    def canonical_trusts(self) -> dict:
        """Get canonical representation of agent trusts."""
        return {
            k: v.canonical()
            for k, v in sorted(self.agent_trusts.items())
        }
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of trust data."""
        return canonical_hash(self.canonical_trusts())
    
    def verify_hash(self) -> bool:
        """Verify that stored hash matches computed hash."""
        return self.snapshot_hash == self.compute_hash()
    
    @classmethod
    def create(
        cls,
        snapshot_id: str,
        snapshot_time: datetime,
        agent_trusts: Dict[str, AgentTrust],
    ) -> "TrustSnapshot":
        """
        Create a TrustSnapshot with computed hash.
        
        Args:
            snapshot_id: Unique ID for this snapshot
            snapshot_time: When the snapshot was taken
            agent_trusts: Map of agent_id to AgentTrust
            
        Returns:
            TrustSnapshot with computed hash
        """
        snapshot = cls(
            snapshot_id=snapshot_id,
            snapshot_time=snapshot_time,
            agent_trusts=agent_trusts,
            snapshot_hash="",  # Placeholder
        )
        snapshot.snapshot_hash = snapshot.compute_hash()
        return snapshot
    
    def get_agent_trust(self, agent_id: str) -> Optional[AgentTrust]:
        """Get trust data for a specific agent."""
        return self.agent_trusts.get(agent_id)
    
    def get_power(self, agent_id: str) -> float:
        """Get effective power for an agent (0 if not found)."""
        trust = self.agent_trusts.get(agent_id)
        return trust.effective_power if trust else 0.0
