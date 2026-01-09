"""
Kaori Flow — FlowPolicy & TrustPhysics

Policy configuration for trust dynamics (FLOW_SPEC v4.0 Section 4).

Architecture: Policy-to-Physics Compilation
1. FlowPolicy (Authoring/AST): Mutable, hierarchical, contains profiles.
2. TrustPhysics (Runtime/Bytecode): Frozen, resolved, hashed, executed by the engine.

The `compile()` method transforms Policy -> Physics, ensuring constitutional invariants.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict


def _canonical_json(data: Any) -> bytes:
    """Produce canonical JSON representation for hashing."""
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':')
    ).encode('utf-8')


# =============================================================================
# 1. Enums & Shared Configs
# =============================================================================

class ProfileName(str, Enum):
    OPEN = "OPEN"
    STANDARD = "STANDARD"
    STRICT = "STRICT"
    # Allow custom names for flexibility, but these are standard archetypes


# =============================================================================
# 2. Physics Components (The "Atoms" of Trust)
# =============================================================================

class ThetaMinBounds(BaseModel):
    """Constitutional bounds for theta_min."""
    strict_min: int = Field(..., ge=0)
    strict_max: int = Field(..., ge=0)
    allow_open_override: bool = False
    
    @model_validator(mode='after')
    def validate_bounds(self) -> "ThetaMinBounds":
        if self.strict_min > self.strict_max:
             raise ValueError(f"strict_min ({self.strict_min}) > strict_max ({self.strict_max})")
        return self


class InitializationConfig(BaseModel):
    """Configuration for agent initialization logic."""
    enabled: bool = True
    standing_cap: float = 50.0
    duration: str = "P14D"
    initial_by_role: Dict[str, float] = Field(default_factory=lambda: {"observer": 0.0})


class UpdateLimitsConfig(BaseModel):
    """Volatility bounds for standing updates."""
    max_delta_per_window: float = 50.0
    max_delta_per_day: float = 100.0


class DecayConfig(BaseModel):
    """Global decay configuration."""
    enabled: bool = True
    half_life: str = "P60D"
    floor: float = 1.0
    notes: Optional[str] = None


class SensitivityCurve(BaseModel):
    """Configuration for sensitivity curves."""
    enabled: bool = True
    curve: str = "sigmoid"
    midpoint: Optional[float] = None
    slope: Optional[float] = None
    exponent: Optional[float] = None
    cap: float = 20.0


class SensitivitiesConfig(BaseModel):
    confidence_penalty: SensitivityCurve
    confidence_reward: SensitivityCurve


class UpdateCoefficients(BaseModel):
    reward: Dict[str, float] = Field(default_factory=dict)
    penalty: Dict[str, float] = Field(default_factory=dict)


class TelemetryConfig(BaseModel):
    concentration_alerts: Dict[str, float] = Field(default_factory=lambda: {"top5_weight_share_max": 0.65})
    exclusion_alerts: Dict[str, float] = Field(default_factory=lambda: {"max_excluded_signals_ratio": 0.70})


class SafetyConfig(BaseModel):
    monotonic_tightening_only: bool = True
    forbid_privileged_agents: bool = True
    require_profile: bool = True
    require_policy_lint_pass: bool = True


# =============================================================================
# 3. TrustPhysics (The Compiled Artifact)
# =============================================================================

class SaturationConfig(BaseModel):
    """Logistic saturation curve configuration."""
    steepness: float = 0.01
    midpoint: float = 500.0
    max_standing: float = 1000.0


class PhaseTransitionsConfig(BaseModel):
    """Phase transition thresholds (Dormant -> Active -> Dominant)."""
    dormant_threshold: float = 200.0
    dormant_weight_multiplier: float = 0.1
    dominant_threshold: float = 850.0


class VouchModifierConfig(BaseModel):
    enabled: bool = True
    per_vouch_fraction: float = 0.05
    max_bonus_fraction: float = 0.2


class ProbeCreatorBonusConfig(BaseModel):
    enabled: bool = True
    min_creator_standing: float = 700.0
    bonus_fraction: float = 0.1


class SelfDealingConfig(BaseModel):
    enabled: bool = True
    discount_factor: float = 0.5


class NetworkModifiersConfig(BaseModel):
    claimtype_collaborator_vouch: VouchModifierConfig = Field(default_factory=VouchModifierConfig)
    probe_creator_bonus: ProbeCreatorBonusConfig = Field(default_factory=ProbeCreatorBonusConfig)
    self_dealing: SelfDealingConfig = Field(default_factory=SelfDealingConfig)


class VouchEdgeWeightConfig(BaseModel):
    base_weight: float = 1.0
    decay_rate_per_day: float = 0.05


class EdgeWeightsConfig(BaseModel):
    vouch: VouchEdgeWeightConfig = Field(default_factory=VouchEdgeWeightConfig)


# =============================================================================
# 4. TrustPhysics (The Compiled Artifact)
# =============================================================================

class TrustPhysics(BaseModel):
    """
    The Compiled trust configuration.
    FROZEN. EXECUTABLE. PROVABLE.
    
    This object is what the FlowReducer and TrustComputer actually use.
    It has no profiles, no inheritance, just raw physics constants.
    """
    model_config = ConfigDict(frozen=True)
    
    # Identity (Snapshotted from Policy)
    policy_id: str
    version: str
    physics_hash: str
    active_profile: str
    
    # Resolved Constants
    theta_min: int  # The actual scalar value (e.g. 10)
    
    # Dynamics (Resolved)
    probation: InitializationConfig
    decay: DecayConfig
    update_limits: UpdateLimitsConfig
    update: UpdateCoefficients
    sensitivities: SensitivitiesConfig
    
    # Advanced Physics (Added in v1.1)
    saturation: SaturationConfig
    phase_transitions: PhaseTransitionsConfig
    network_modifiers: NetworkModifiersConfig
    edge_weights: EdgeWeightsConfig
    
    # Bounds (Carried forward for reference/validation)
    bounds_range: Dict[str, float]  # min/max
    strict_min: int                 # The constraint that generated theta_min
    
    # Telemetry
    telemetry: Optional[TelemetryConfig] = None
    
    @property
    def canonical_hash(self) -> str:
        """Return the pre-computed physics hash."""
        return self.physics_hash
    
    def get_initial_standing(self, role: str = "default") -> float:
        """Get initial standing based on resolved probation rules."""
        # Simple default logic for physics; FlowReducer uses more complex role logic if needed
        # But for new agents, probation usually starts at 0 or low value
    def get_initial_standing(self, role: str = "default") -> float:
        """Get initial standing based on resolved probation rules."""
        return self.probation.initial_by_role.get(role, self.probation.initial_by_role.get("default", 0.0))


# =============================================================================
# 5. FlowPolicy (The Authoring AST)
# =============================================================================

class ProfileConfig(BaseModel):
    """Configuration for a single profile in the YAML."""
    description: str = ""
    extends: Optional[str] = None
    
    # Overridable settings
    theta_min_default: Optional[int] = Field(None, alias="validation_admissibility.theta_min.default") # Flattened or Nested handling?
    # Pydantic doesn't support dot notation alias easily in dict load unless flattened. 
    # Let's match YAML structure: nested dicts.
    
    validation_admissibility: Optional[Dict[str, Any]] = None
    standing_dynamics: Optional[Dict[str, Any]] = None


class ValidationAdmissibilityBounds(BaseModel):
    theta_min: ThetaMinBounds
    allow_record_only_signals: bool = True


class StandingDynamicsConfig(BaseModel):
    range: Dict[str, float]
    update_limits: UpdateLimitsConfig
    decay: DecayConfig
    update: UpdateCoefficients
    sensitivities: SensitivitiesConfig
    initialization: Optional[InitializationConfig] = None # Global default?
    
    # Advanced Physics
    saturation: SaturationConfig = Field(default_factory=SaturationConfig)
    phase_transitions: PhaseTransitionsConfig = Field(default_factory=PhaseTransitionsConfig)
    network_modifiers: NetworkModifiersConfig = Field(default_factory=NetworkModifiersConfig)
    edge_weights: EdgeWeightsConfig = Field(default_factory=EdgeWeightsConfig)


class FlowPolicyMetadata(BaseModel):
    description: str = ""
    maintainer: str = ""
    schema_version: str = "2.0"
    canonicalization: str = "json_canonical_v1"
    hash_algo: str = "sha256"


class FlowPolicy(BaseModel):
    """
    The Authoring AST (Mutable Source).
    Loads from `flow_policy_v1.yaml`.
    """
    # Identity
    policy_id: str
    version: str
    parent_version: Optional[str] = None
    effective_from: datetime
    deprecated_at: Optional[datetime] = None
    policy_hash: Optional[str] = None # Optional in raw
    
    metadata: FlowPolicyMetadata = Field(default_factory=FlowPolicyMetadata)
    
    # Active Profile Selection
    profile: str
    
    # Profile Definitions
    profiles: Dict[str, ProfileConfig]
    
    # Global Constitution (Applies to all profiles)
    validation_admissibility: ValidationAdmissibilityBounds
    standing_dynamics: StandingDynamicsConfig
    telemetry: Optional[TelemetryConfig] = None
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    
    @classmethod
    def load(cls, path: str | Path) -> "FlowPolicy":
        path = Path(path)
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        # Pre-processing to handle potential YAML structure quirks if needed
        return cls.model_validate(data)

    @classmethod
    def default(cls) -> "FlowPolicy":
        """Return a default development policy."""
        # Minimal valid config
        return cls(
            policy_id="dev.flow",
            version="1.0.0",
            effective_from=datetime.now(timezone.utc),
            profile="STANDARD",
            profiles={
                "STANDARD": ProfileConfig(
                    description="Default Dev Profile",
                    validation_admissibility={"theta_min": {"default": 10}},
                    standing_dynamics={}
                )
            },
            validation_admissibility=ValidationAdmissibilityBounds(
                theta_min=ThetaMinBounds(strict_min=0, strict_max=1000)
            ),
            standing_dynamics=StandingDynamicsConfig(
                range={"min": 0, "max": 1000},
                update_limits=UpdateLimitsConfig(),
                decay=DecayConfig(),
                initialization=InitializationConfig(
                    initial_by_role={
                        "observer": 200.0, 
                        "validator": 250.0, 
                        "authority": 500.0,
                        "policy": 500.0
                    }
                ),
                update=UpdateCoefficients(
                   reward={"correct": 3.0},
                   penalty={"incorrect": -5.0} # Used in tests
                ),
                network_modifiers=NetworkModifiersConfig(
                    self_dealing=SelfDealingConfig(discount_factor=0.5, enabled=True)
                ),
                sensitivities=SensitivitiesConfig(
                    confidence_penalty=SensitivityCurve(),
                    confidence_reward=SensitivityCurve()
                )
            )
        )

    def compile(self, override_profile: Optional[str] = None) -> TrustPhysics:
        """
        Compiles the Policy AST into Frozen TrustPhysics.
        
        1. Resolves Profile Inheritance (Base -> Extends -> Final)
        2. Merges Active Profile onto Globals
        3. Enforces Constitutional Invariants (strict_min)
        4. Freezes and Hashes
        """
        active_profile_name = override_profile or self.profile
        
        # 1. Resolve Profile Chain
        resolved_profile_config = self._resolve_profile(active_profile_name)
        
        # 2. Extract Resolved Values
        
        # Theta Min
        # Default to 0 if not specified in profile? No, must be specified or fail.
        # Check profile first
        profile_adm = resolved_profile_config.get('validation_admissibility', {})
        profile_theta = profile_adm.get('theta_min', {}).get('default')
        
        if profile_theta is None:
             # Fallback logic or error? Constitution demands clarity.
             # If strictly typed, maybe we default to strict_min?
             # For now, let's assume profiles MUST define it if they seek to override.
             # If not in profile, is there a global default? No, only strict_min.
             # Let's default to strict_min if unset.
             profile_theta = self.validation_admissibility.theta_min.strict_min

        # Probation
        # Merge global initialization with profile initialization
        global_init = self.standing_dynamics.initialization or InitializationConfig()
        profile_dyn = resolved_profile_config.get('standing_dynamics', {})
        profile_init_dict = profile_dyn.get('initialization', {}).get('probation', {})
        
        # Merge dict changes onto model
        # Using model_dump to get dict, update, then re-validate
        probation_config = global_init.model_copy(update=profile_init_dict)

        # 3. Enforce Constitutional Invariants
        strict_min = self.validation_admissibility.theta_min.strict_min
        allow_open = self.validation_admissibility.theta_min.allow_open_override
        
        if profile_theta < strict_min:
             # Only allowed if explicit constitutional exception
             if not (profile_theta == 0 and allow_open):
                  raise ValueError(
                      f"Profile '{active_profile_name}' theta_min ({profile_theta}) < strict_min ({strict_min}) "
                      f"and not exempted by allow_open_override."
                  )
        
        if profile_theta > self.validation_admissibility.theta_min.strict_max:
             raise ValueError(
                 f"Profile '{active_profile_name}' theta_min ({profile_theta}) > strict_max ({self.validation_admissibility.theta_min.strict_max})"
             )

        # 4. Construct Physics Object
        # We assume global dynamics apply unless profile override (not mostly supported in v1 schema except probation)
        
        physics_data = {
            "policy_id": self.policy_id,
            "version": self.version,
            "active_profile": active_profile_name,
            "theta_min": profile_theta,
            "probation": probation_config.model_dump(),
            "decay": self.standing_dynamics.decay.model_dump(),
            "update_limits": self.standing_dynamics.update_limits.model_dump(),
            "update": self.standing_dynamics.update.model_dump(),
            "sensitivities": self.standing_dynamics.sensitivities.model_dump(),
            "saturation": self.standing_dynamics.saturation.model_dump(),
            "phase_transitions": self.standing_dynamics.phase_transitions.model_dump(),
            "network_modifiers": self.standing_dynamics.network_modifiers.model_dump(),
            "edge_weights": self.standing_dynamics.edge_weights.model_dump(),
            "bounds_range": self.standing_dynamics.range,
            "strict_min": strict_min,
            "telemetry": self.telemetry.model_dump() if self.telemetry else None,
            "physics_hash": "" # Placeholder
        }
        
        # 5. Compute Hash (Exclude the hash field itself)
        # Canonicalize the data dict
        canonical_bytes = _canonical_json(physics_data)
        physics_hash = hashlib.sha256(canonical_bytes).hexdigest()
        
        physics_data["physics_hash"] = physics_hash
        
        return TrustPhysics(**physics_data)

    def _resolve_profile(self, profile_name: str) -> Dict[str, Any]:
        """
        Recursively resolve profile inheritance.
        Detects cycles.
        """
        chain = []
        current = profile_name
        
        # Traverse up
        visited = set()
        while current:
            if current in visited:
                 raise ValueError(f"Cyclic inheritance detected involving profile '{current}'")
            visited.add(current)
            
            if current not in self.profiles:
                 raise ValueError(f"Profile '{current}' not defined in policy.")
            
            p_config = self.profiles[current]
            chain.append(p_config)
            current = p_config.extends # Move to parent
            
        # Chain is [Child, Parent, Grandparent...]
        # We want to apply Grandparent, then Parent, then Child
        merged: Dict[str, Any] = {}
        
        for p_config in reversed(chain):
            # Merge logic: Shallow or Deep?
            # YAML usually implies deep merge for nested configs.
            # Using Pydantic's model_dump(exclude_unset=True) helps
            data = p_config.model_dump(exclude_defaults=True, exclude_unset=True)
            if 'extends' in data: del data['extends']
            if 'description' in data: del data['description']
            
            self._deep_update(merged, data)
            
        return merged

    def _deep_update(self, target: Dict[str, Any], update: Dict[str, Any]) -> None:
        """Recursive dict update."""
        for k, v in update.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                self._deep_update(target[k], v)
            else:
                target[k] = v
