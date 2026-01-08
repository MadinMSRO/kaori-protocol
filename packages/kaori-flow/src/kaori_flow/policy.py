"""
Kaori Flow — FlowPolicy

Policy configuration for trust dynamics (FLOW_SPEC v4.0 Section 4).
Rule 7: Adaptiveness Lives in Policy Interpretation.

FlowPolicy is itself an Agent with standing.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field


class StandingGainConfig(BaseModel):
    """Configuration for standing gain (Rule 5: nonlinear)."""
    coefficient: float = 5.0  # a in: ΔS = a * log(1 + q)


class SaturationConfig(BaseModel):
    """Configuration for effective standing saturation (Rule 5: nonlinear)."""
    steepness: float = 0.01      # k in logistic
    midpoint: float = 500.0      # S₀ in logistic
    max_standing: float = 1000.0


class PenaltyConfig(BaseModel):
    """Configuration for standing penalty (asymmetric: sharper than gain)."""
    coefficient: float = 5.0   # b in: ΔS = -b * log(1 + q) * λ
    amplifier: float = 2.0      # λ (must be > 1)


class BoundsConfig(BaseModel):
    """Standing bounds configuration."""
    min: float = 0.0
    max: float = 1000.0
    initial_by_role: Dict[str, float] = Field(default_factory=lambda: {
        "observer": 200.0,
        "validator": 250.0,
        "expert": 350.0,
        "authority": 500.0,
        "policy": 500.0,
    })


class ModifierConfig(BaseModel):
    """Configuration for a single context modifier."""
    enabled: bool = True


class ClaimtypeCollaboratorVouchConfig(ModifierConfig):
    """Bonus for observers vouched by claimtype collaborators."""
    max_bonus_fraction: float = 0.15
    per_vouch_fraction: float = 0.05
    edge_weight_decay_per_day: float = 0.01


class SelfDealingConfig(ModifierConfig):
    """Penalty when observer created the probe they're observing."""
    discount_factor: float = 0.5


class ProbeCreatorBonusConfig(ModifierConfig):
    """Bonus from high-standing probe creator."""
    min_creator_standing: float = 500.0
    bonus_fraction: float = 0.05


class NetworkModifiersConfig(BaseModel):
    """All network context modifiers (Rule 4: Trust is Local)."""
    claimtype_collaborator_vouch: ClaimtypeCollaboratorVouchConfig = Field(
        default_factory=ClaimtypeCollaboratorVouchConfig
    )
    self_dealing: SelfDealingConfig = Field(default_factory=SelfDealingConfig)
    probe_creator_bonus: ProbeCreatorBonusConfig = Field(
        default_factory=ProbeCreatorBonusConfig
    )


class ClaimtypeThresholdConfig(BaseModel):
    """ClaimType standing affects observer threshold (Rule 4)."""
    enabled: bool = True
    base_threshold: float = 100.0
    scale_factor: float = 2.0


class PhaseTransitionsConfig(BaseModel):
    """Phase transition thresholds (Rule 6)."""
    dormant_threshold: float = 300.0   # Below = dormant
    dominant_threshold: float = 700.0  # Above = dominant
    dormant_weight_multiplier: float = 0.1


class EdgeWeightsConfig(BaseModel):
    """Configuration for emergent edge weight computation."""
    class VouchConfig(BaseModel):
        base_weight: float = 1.0
        decay_rate_per_day: float = 0.01
    
    class CollaborateConfig(BaseModel):
        scaling_divisor: float = 5.0
    
    class ConflictConfig(BaseModel):
        base_weight: float = -0.5
    
    vouch: VouchConfig = Field(default_factory=VouchConfig)
    collaborate: CollaborateConfig = Field(default_factory=CollaborateConfig)
    conflict: ConflictConfig = Field(default_factory=ConflictConfig)


class PolicyMetadata(BaseModel):
    """Metadata for the policy."""
    description: str = ""
    maintainer: str = ""
    created_at: Optional[datetime] = None


class FlowPolicy(BaseModel):
    """
    Flow Policy configuration (FLOW_SPEC v4.0 Section 4).
    
    Rule 7: FlowPolicy is itself an Agent with standing.
    All tunable parameters live here, not hardcoded in the spec.
    """
    # Agent identity
    agent_id: str = "policy:flow_v1.0.0"
    agent_type: str = "policy"
    version: str = "1.0.0"
    
    # Metadata
    metadata: PolicyMetadata = Field(default_factory=PolicyMetadata)
    
    # Rule 5: Nonlinear updates
    standing_gain: StandingGainConfig = Field(default_factory=StandingGainConfig)
    saturation: SaturationConfig = Field(default_factory=SaturationConfig)
    penalty: PenaltyConfig = Field(default_factory=PenaltyConfig)
    
    # Rule 3: Standing bounds
    bounds: BoundsConfig = Field(default_factory=BoundsConfig)
    
    # Rule 4: Context modifiers
    network_modifiers: NetworkModifiersConfig = Field(
        default_factory=NetworkModifiersConfig
    )
    claimtype_threshold: ClaimtypeThresholdConfig = Field(
        default_factory=ClaimtypeThresholdConfig
    )
    
    # Rule 6: Phase transitions
    phase_transitions: PhaseTransitionsConfig = Field(
        default_factory=PhaseTransitionsConfig
    )
    
    # Edge weight computation
    edge_weights: EdgeWeightsConfig = Field(default_factory=EdgeWeightsConfig)
    
    @classmethod
    def load(cls, path: str | Path) -> "FlowPolicy":
        """Load policy from YAML file."""
        path = Path(path)
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
    
    @classmethod
    def default(cls) -> "FlowPolicy":
        """Get default policy with sensible defaults."""
        return cls()
    
    def save(self, path: str | Path) -> None:
        """Save policy to YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)
    
    def get_initial_standing(self, role: str) -> float:
        """Get initial standing for a role."""
        return self.bounds.initial_by_role.get(role, 200.0)
