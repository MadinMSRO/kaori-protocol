"""
Kaori Core — ClaimType Models

Typed Pydantic models for ClaimType YAML configuration files.
These models provide structured access to claim-specific policy.
"""
from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# TruthKey Configuration
# =============================================================================

class TruthKeyConfig(BaseModel):
    """Configuration for TruthKey formation."""
    spatial_system: str = "h3"
    resolution: int = 8
    z_index: str = "surface"
    time_bucket: str = "PT1H"  # ISO 8601 duration


# =============================================================================
# Evidence Configuration
# =============================================================================

class EvidenceConfig(BaseModel):
    """Evidence requirements for claim type."""
    required: bool = True
    types: list[str] = Field(default_factory=lambda: ["photo", "video"])
    min_count: int = 1
    max_count: int = 5


class EvidenceSimilarityHash(BaseModel):
    """Hash-based duplicate detection config."""
    enabled: bool = True
    method: str = "phash"
    duplicate_threshold: int = 6
    immediate_reject_if_duplicate: bool = True


class EvidenceSimilarityEmbedding(BaseModel):
    """Embedding-based similarity config."""
    enabled: bool = True
    compute_mode: str = "on_demand"
    engine: str = "clip_v1"
    similarity_threshold: float = 0.85


class EvidenceSimilarityConfig(BaseModel):
    """Evidence similarity detection configuration."""
    enabled: bool = True
    hash: Optional[EvidenceSimilarityHash] = None
    embedding: Optional[EvidenceSimilarityEmbedding] = None


# =============================================================================
# AI Validation Routing
# =============================================================================

class AIRouterConfig(BaseModel):
    """Configuration for an AI validation tier."""
    engine: str
    checks: list[str | dict] = Field(default_factory=list)  # Can be string or dict
    prompt_context: Optional[str] = None
    routes: dict[str, str] = Field(default_factory=dict)


class AIValidationRouting(BaseModel):
    """AI validation ladder configuration."""
    enabled: bool = True
    bouncer: Optional[AIRouterConfig] = None
    generalist: Optional[AIRouterConfig] = None
    specialist: Optional[AIRouterConfig] = None


class AutovalidationConfig(BaseModel):
    """AI autovalidation thresholds."""
    ai_verified_true_threshold: float = 0.82
    ai_verified_false_threshold: float = 0.20
    uncertainty_band: dict[str, float] = Field(default_factory=lambda: {"low": 0.20, "high": 0.82})


# =============================================================================
# Human Gating
# =============================================================================

class HumanGatingConfig(BaseModel):
    """Human gating requirements."""
    always_require_human: bool = False
    required_for_risk_profiles: list[str] = Field(default_factory=lambda: ["critical"])
    min_trust_score: float = 0.35
    min_ai_confidence: float = 0.82


class ValidationFlowConfig(BaseModel):
    """Validation flow mode."""
    mode: str = "human_peer"  # auto | human_peer | human_expert | authority_gate


# =============================================================================
# Consensus Model
# =============================================================================

class ConsensusModel(BaseModel):
    """Consensus configuration for truth state finalization."""
    type: str = "weighted_threshold"
    finalize_threshold: int = 15
    reject_threshold: int = -10
    weighted_roles: dict[str, int] = Field(default_factory=lambda: {
        "bronze": 1,
        "silver": 3,
        "expert": 7,
        "authority": 10
    })
    override_allowed_roles: list[str] = Field(default_factory=lambda: ["authority"])
    vote_types: dict[str, int | str] = Field(default_factory=lambda: {
        "RATIFY": 1,
        "REJECT": -1,
        "CHALLENGE": 0,
        "OVERRIDE": "special"
    })


# =============================================================================
# Confidence Model
# =============================================================================

class ConfidenceComponent(BaseModel):
    """A single confidence component."""
    weight: float
    source: str
    normalize: Optional[dict] = None


class ConfidenceModel(BaseModel):
    """Composite confidence configuration."""
    type: str = "composite"
    components: dict[str, ConfidenceComponent] = Field(default_factory=dict)
    modifiers: dict[str, float] = Field(default_factory=lambda: {
        "contradiction_penalty": -0.20,
        "expert_bonus": 0.05
    })
    thresholds: dict[str, float] = Field(default_factory=lambda: {
        "high": 0.80,
        "medium": 0.50,
        "low": 0.30
    })


# =============================================================================
# State Verification Policy
# =============================================================================

class MonitorLaneConfig(BaseModel):
    """Monitor lane configuration."""
    allow_ai_verified_truth: bool = True
    transparency_flag_if_composite_below: float = 0.82
    flag_label: str = "LOW_COMPOSITE_CONFIDENCE"


class CriticalLaneConfig(BaseModel):
    """Critical lane configuration."""
    require_human_consensus_for_verified_true: bool = True


class StateVerificationPolicy(BaseModel):
    """State verification policy configuration."""
    monitor_lane: Optional[MonitorLaneConfig] = None
    critical_lane: Optional[CriticalLaneConfig] = None


# =============================================================================
# Dispute Resolution
# =============================================================================

class DisputeResolutionConfig(BaseModel):
    """Dispute resolution configuration."""
    quorum: dict[str, int] = Field(default_factory=lambda: {"min_votes": 3})
    timeout: dict[str, str] = Field(default_factory=lambda: {
        "peer_review": "PT12H",
        "expert_review": "PT24H",
        "authority_escalation": "PT48H"
    })
    default_action_on_timeout: str = "downgrade_to_investigating"


# =============================================================================
# Contradiction Rules
# =============================================================================

class ContradictionRulesConfig(BaseModel):
    """Contradiction detection configuration."""
    enabled: bool = True
    trusted_sources: dict[str, str | float] = Field(default_factory=lambda: {
        "min_standing": "expert",
        "min_trust_score": 0.70
    })
    contradiction_trigger: dict[str, str | float] = Field(default_factory=lambda: {
        "min_confidence_gap": 0.40,
        "action": "flag_and_escalate"
    })


# =============================================================================
# Temporal Decay
# =============================================================================

class TemporalDecayConfig(BaseModel):
    """Temporal decay configuration."""
    half_life: str = "PT4H"      # ISO 8601 duration
    max_validity: str = "P1D"    # ISO 8601 duration


# =============================================================================
# Credits (FLOW_SPEC)
# =============================================================================

class CreditsConfig(BaseModel):
    """Kaori Credits configuration."""
    enabled: bool = True
    base_reward: int = 20
    verified_false_reward: int = 15
    rejected_penalty: int = -10
    priority_bonus: dict[str, int] = Field(default_factory=lambda: {
        "urgent": 15,
        "critical": 25
    })
    quality_multiplier: dict[str, float] = Field(default_factory=lambda: {
        "high_confidence": 1.25,
        "standard": 1.0
    })


# =============================================================================
# Root ClaimType Model
# =============================================================================

class ClaimType(BaseModel):
    """
    Root model for ClaimType YAML configuration.
    
    This provides typed access to all claim-specific policy including:
    - TruthKey formation
    - Evidence requirements
    - AI validation routing
    - Human gating
    - Consensus model
    - Confidence model
    - Dispute resolution
    - Temporal decay
    """
    id: str
    version: int
    domain: str
    topic: str
    
    risk_profile: Literal["monitor", "critical"] = "monitor"
    
    truthkey: TruthKeyConfig = Field(default_factory=TruthKeyConfig)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    evidence_similarity: Optional[EvidenceSimilarityConfig] = None
    
    ai_validation_routing: AIValidationRouting = Field(default_factory=AIValidationRouting)
    autovalidation: AutovalidationConfig = Field(default_factory=AutovalidationConfig)
    
    human_gating: HumanGatingConfig = Field(default_factory=HumanGatingConfig)
    validation_flow: ValidationFlowConfig = Field(default_factory=ValidationFlowConfig)
    
    consensus_model: ConsensusModel = Field(default_factory=ConsensusModel)
    confidence_model: ConfidenceModel = Field(default_factory=ConfidenceModel)
    
    state_verification_policy: Optional[StateVerificationPolicy] = None
    dispute_resolution: Optional[DisputeResolutionConfig] = None
    contradiction_rules: Optional[ContradictionRulesConfig] = None
    temporal_decay: Optional[TemporalDecayConfig] = None
    
    credits: Optional[CreditsConfig] = None
    
    # UI Schema (passthrough, not typed)
    ui_schema: Optional[dict] = None
    
    # --- Convenience Methods ---
    
    def is_critical(self) -> bool:
        """Check if this claim type requires critical lane processing."""
        return self.risk_profile == "critical"
    
    def requires_human_gate(self) -> bool:
        """Check if human gating is required for this claim type."""
        if self.human_gating.always_require_human:
            return True
        if self.risk_profile in self.human_gating.required_for_risk_profiles:
            return True
        return False
    
    def get_vote_weight(self, standing: str) -> int:
        """Get vote weight for a standing class."""
        return self.consensus_model.weighted_roles.get(standing.lower(), 1)
    
    def get_ai_threshold(self, threshold_type: str) -> float:
        """Get AI autovalidation threshold."""
        if threshold_type == "true":
            return self.autovalidation.ai_verified_true_threshold
        elif threshold_type == "false":
            return self.autovalidation.ai_verified_false_threshold
        return 0.5
