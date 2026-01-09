"""
Kaori Flow — Trust Provider

TrustProvider implementation that creates TrustSnapshots for Truth compilation.

This module bridges Flow (dynamic trust) and Truth (deterministic compilation).
The TrustProvider interface lives here, NOT in kaori-truth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Protocol
from uuid import uuid4

# Import TrustSnapshot schema from Truth (data only, not provider)
from kaori_truth.trust_snapshot import TrustSnapshot, AgentTrust

from kaori_flow.primitives.agent import Agent


class TrustProvider(Protocol):
    """
    Protocol for providing trust data to Truth compilation.
    
    Implementations query the trust graph and return frozen snapshots.
    Truth never calls this directly - orchestrator does.
    """
    
    def get_trust_snapshot(
        self,
        agent_ids: List[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        """
        Get a frozen trust snapshot for the given agents.
        
        Args:
            agent_ids: List of agent IDs to include
            claim_type: The claim type for context-specific trust
            snapshot_time: The time to snapshot (MUST be explicit)
            
        Returns:
            TrustSnapshot with computed hash
        """
        ...
    
    def get_power(
        self,
        agent_id: str,
        claim_type: str,
    ) -> float:
        """Get effective power for an agent."""
        ...


class InMemoryTrustProvider:
    """
    Simple in-memory TrustProvider for testing and development.
    
    Production implementations would query a database.
    """
    
    def __init__(self):
        self._agents: Dict[str, Agent] = {}
        self._squads: Dict[str, List[str]] = {}  # agent_id -> [squad_ids]
    
    def register_agent(self, agent: Agent) -> None:
        """Register an agent."""
        self._agents[str(agent.agent_id)] = agent
    
    def add_squad_membership(self, agent_id: str, squad_id: str) -> None:
        """Add squad membership."""
        if agent_id not in self._squads:
            self._squads[agent_id] = []
        self._squads[agent_id].append(squad_id)
    
    def get_trust_snapshot(
        self,
        agent_ids: List[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        """Create a trust snapshot for the given agents."""
        agent_trusts = {}
        
        for agent_id in agent_ids:
            agent = self._agents.get(agent_id)
            if agent:
                power = self._compute_power(agent_id)
                agent_trusts[agent_id] = AgentTrust(
                    agent_id=agent_id,
                    effective_trust=power,
                    standing=agent.standing,
                    derived_class=agent.derived_class,
                    flags=["HIGH_ASSURANCE"] if agent.is_high_assurance else [],
                )
            else:
                # Unknown agent gets minimal trust
                agent_trusts[agent_id] = AgentTrust(
                    agent_id=agent_id,
                    effective_trust=10.0,
                    standing=10.0,
                    derived_class="bronze",
                    flags=[],
                )
        
        return TrustSnapshot.create(
            snapshot_id=str(uuid4()),
            snapshot_time=snapshot_time,
            agent_trusts=agent_trusts,
        )
    
    def get_power(self, agent_id: str, claim_type: str = "") -> float:
        """Get effective power for an agent."""
        return self._compute_power(agent_id)
    
    def _compute_power(
        self,
        agent_id: str,
        visited: Optional[set] = None,
        depth: int = 0,
    ) -> float:
        """
        Compute effective power with fractal inheritance.
        
        Power(A) = Intrinsic(A) + (Power(Squad) * InheritanceDecay)
        """
        INHERITANCE_DECAY = 0.2
        MAX_DEPTH = 3
        
        if visited is None:
            visited = set()
        
        # Cycle safety
        if agent_id in visited or depth >= MAX_DEPTH:
            return 0.0
        visited.add(agent_id)
        
        agent = self._agents.get(agent_id)
        if not agent:
            return 10.0  # Default for unknown
        
        intrinsic = agent.standing
        inherited = 0.0
        
        # Get squad memberships
        squad_ids = self._squads.get(agent_id, [])
        for squad_id in squad_ids:
            squad_power = self._compute_power(squad_id, visited.copy(), depth + 1)
            inherited += squad_power * INHERITANCE_DECAY
        
        return intrinsic + inherited


def create_trust_snapshot(
    agents: Dict[str, Agent],
    agent_ids: List[str],
    snapshot_time: datetime,
) -> TrustSnapshot:
    """
    Convenience function to create a TrustSnapshot.
    
    Args:
        agents: Dict of agent_id -> Agent
        agent_ids: List of agent IDs to include
        snapshot_time: Snapshot time
        
    Returns:
        TrustSnapshot with computed hash
    """
    provider = InMemoryTrustProvider()
    for agent in agents.values():
        provider.register_agent(agent)
    
    return provider.get_trust_snapshot(agent_ids, "", snapshot_time)
