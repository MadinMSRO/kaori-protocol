"""
Kaori Flow — Trust Computation

Computes effective trust from standing and context (FLOW_SPEC v4.0).
Rule 4: Standing is Global, Trust is Local (Topological).
Rule 6: Trust Has Phase Transitions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .policy import FlowPolicy
from .primitives.signal import Signal, SignalTypes


@dataclass
class TrustContext:
    """
    Context for trust computation (Rule 4).
    
    Trust is local — it depends on the specific context of compilation.
    """
    # ClaimType context
    claimtype_id: Optional[str] = None
    claimtype_standing: float = 500.0
    claimtype_collaborators: List[Tuple[str, float]] = field(default_factory=list)
    
    # Probe context
    probe_id: Optional[str] = None
    probe_creator_id: Optional[str] = None
    probe_creator_standing: float = 0.0
    
    # Snapshot time
    snapshot_time: Optional[datetime] = None


@dataclass  
class AgentTrust:
    """Trust data for a single agent in a snapshot."""
    agent_id: str
    standing: float
    effective_trust: float
    derived_class: str
    flags: List[str] = field(default_factory=list)
    
    def canonical(self) -> dict:
        """Get canonical representation for hashing."""
        return {
            "agent_id": self.agent_id,
            "standing": round(self.standing, 6),
            "effective_trust": round(self.effective_trust, 6),
            "derived_class": self.derived_class.lower(),
            "flags": sorted(self.flags),
        }


@dataclass
class TrustSnapshot:
    """
    Frozen snapshot of trust state for truth compilation.
    
    This is the interface between Flow and Truth.
    Truth treats this as immutable input.
    """
    snapshot_id: str
    snapshot_time: datetime
    policy_id: str
    policy_version: str
    policy_standing: float
    agent_trusts: Dict[str, AgentTrust] = field(default_factory=dict)
    snapshot_hash: str = ""
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of trust data."""
        import hashlib
        import json
        
        canonical = {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "agent_trusts": {
                k: v.canonical() for k, v in sorted(self.agent_trusts.items())
            }
        }
        canonical_json = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_json.encode()).hexdigest()


class TrustComputer:
    """
    Computes effective trust from standing and context.
    
    Rule 4: Standing is global, trust is local.
    Rule 6: Trust has phase transitions.
    """
    
    def __init__(self, policy: FlowPolicy):
        self.policy = policy
    
    def compute_effective_trust(
        self,
        agent_id: str,
        base_standing: float,
        context: TrustContext,
        signals: List[Signal],
    ) -> float:
        """
        Compute effective trust for an agent in context.
        
        This implements Rule 4 (local topology) using modifiers from FlowPolicy.
        """
        # Step 1: Apply saturation curve (Rule 5)
        base_effective = self._apply_saturation(base_standing)
        
        # Step 2: Network bonuses (from policy configuration)
        network_bonus = self._compute_network_bonus(
            agent_id, base_effective, context, signals
        )
        
        # Step 3: Probe creator bonus
        probe_bonus = self._compute_probe_bonus(
            agent_id, base_effective, context
        )
        
        # Step 4: Self-dealing penalty
        self_dealing_factor = self._compute_self_dealing_factor(agent_id, context)
        
        # Step 5: Combine
        effective = (base_effective + network_bonus + probe_bonus) * self_dealing_factor
        
        # Step 6: Apply phase transition (Rule 6)
        effective = self._apply_phase_transition(effective)
        
        # Clamp to bounds
        return max(0.0, min(effective, self.policy.saturation.max_standing))
    
    def _apply_saturation(self, standing: float) -> float:
        """
        Apply logistic saturation curve (Rule 5).
        
        E(S) = max / (1 + e^(-k(S - S₀)))
        """
        k = self.policy.saturation.steepness
        s0 = self.policy.saturation.midpoint
        max_s = self.policy.saturation.max_standing
        
        return max_s / (1 + math.exp(-k * (standing - s0)))
    
    def _compute_network_bonus(
        self,
        agent_id: str,
        base_effective: float,
        context: TrustContext,
        signals: List[Signal],
    ) -> float:
        """
        Compute network bonus from claimtype collaborators (Rule 4).
        """
        config = self.policy.network_modifiers.claimtype_collaborator_vouch
        if not config.enabled:
            return 0.0
        
        bonus = 0.0
        
        for collab_id, collab_standing in context.claimtype_collaborators:
            # Check if collaborator vouched for this agent
            edge_weight = self._compute_vouch_edge_weight(
                collab_id, agent_id, signals
            )
            
            if edge_weight > 0:
                bonus += edge_weight * config.per_vouch_fraction * base_effective
        
        # Cap at max bonus
        max_bonus = config.max_bonus_fraction * base_effective
        return min(bonus, max_bonus)
    
    def _compute_vouch_edge_weight(
        self,
        voucher_id: str,
        vouchee_id: str,
        signals: List[Signal],
    ) -> float:
        """
        Compute edge weight for VOUCH relationship.
        
        Weight decays over time (from policy configuration).
        """
        config = self.policy.edge_weights.vouch
        
        # Find endorsement signals
        endorsements = [
            s for s in signals
            if s.signal_type == SignalTypes.ENDORSEMENT
            and s.agent_id == voucher_id
            and s.object_id == vouchee_id
        ]
        
        if not endorsements:
            return 0.0
        
        # Use most recent endorsement
        latest = max(endorsements, key=lambda s: s.time)
        
        # Weight decays over time
        now = datetime.utcnow()
        age_days = (now - latest.time).total_seconds() / 86400
        
        weight = config.base_weight * math.exp(-config.decay_rate_per_day * age_days)
        return max(0.0, weight)
    
    def _compute_probe_bonus(
        self,
        agent_id: str,
        base_effective: float,
        context: TrustContext,
    ) -> float:
        """
        Compute bonus from high-standing probe creator (if different person).
        """
        config = self.policy.network_modifiers.probe_creator_bonus
        if not config.enabled:
            return 0.0
        
        if not context.probe_creator_id:
            return 0.0
        
        # No bonus if observer is the creator (handled by self-dealing)
        if context.probe_creator_id == agent_id:
            return 0.0
        
        # Only apply if creator has high standing
        if context.probe_creator_standing < config.min_creator_standing:
            return 0.0
        
        return config.bonus_fraction * base_effective
    
    def _compute_self_dealing_factor(
        self,
        agent_id: str,
        context: TrustContext,
    ) -> float:
        """
        Compute self-dealing discount (Rule 4).
        
        If observer created the probe they're observing, apply discount.
        """
        config = self.policy.network_modifiers.self_dealing
        if not config.enabled:
            return 1.0
        
        if context.probe_creator_id == agent_id:
            return config.discount_factor
        
        return 1.0
    
    def _apply_phase_transition(self, effective: float) -> float:
        """
        Apply phase transition thresholds (Rule 6).
        
        Three phases: dormant, active, dominant.
        """
        config = self.policy.phase_transitions
        
        # Normalize to 0-1 for phase calculation
        normalized = effective / self.policy.saturation.max_standing
        
        if normalized < config.dormant_threshold / self.policy.saturation.max_standing:
            # Dormant phase: minimal influence
            return effective * config.dormant_weight_multiplier
        elif normalized > config.dominant_threshold / self.policy.saturation.max_standing:
            # Dominant phase: diminishing returns
            # Cap the benefit above dominant threshold
            threshold = config.dominant_threshold
            excess = effective - threshold
            return threshold + excess * 0.3  # 30% of excess above threshold
        else:
            # Active phase: proportional
            return effective
    
    def build_trust_snapshot(
        self,
        agent_standings: Dict[str, float],
        context: TrustContext,
        signals: List[Signal],
        policy_standing: float = 500.0,
    ) -> TrustSnapshot:
        """
        Build a complete trust snapshot for truth compilation.
        """
        import uuid
        
        agent_trusts = {}
        
        for agent_id, standing in agent_standings.items():
            effective = self.compute_effective_trust(
                agent_id, standing, context, signals
            )
            
            # Derive class from standing
            derived_class = self._derive_class(standing)
            
            # Collect flags
            flags = []
            if context.probe_creator_id == agent_id:
                flags.append("SELF_DEALING")
            
            agent_trusts[agent_id] = AgentTrust(
                agent_id=agent_id,
                standing=standing,
                effective_trust=effective,
                derived_class=derived_class,
                flags=flags,
            )
        
        snapshot = TrustSnapshot(
            snapshot_id=str(uuid.uuid4()),
            snapshot_time=context.snapshot_time or datetime.utcnow(),
            policy_id=self.policy.agent_id,
            policy_version=self.policy.version,
            policy_standing=policy_standing,
            agent_trusts=agent_trusts,
        )
        snapshot.snapshot_hash = snapshot.compute_hash()
        
        return snapshot
    
    def _derive_class(self, standing: float) -> str:
        """Derive standing class from value."""
        if standing < 300:
            return "bronze"
        elif standing < 500:
            return "silver"
        elif standing < 700:
            return "expert"
        else:
            return "authority"
