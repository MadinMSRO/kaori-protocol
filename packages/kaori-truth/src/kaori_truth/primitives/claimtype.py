"""
Kaori Truth — ClaimType Primitive

YAML contract definition with canonicalization and version pinning.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from kaori_truth.canonical import canonical_hash, canonical_json
from kaori_truth.canonical.json import canonical_dict


class TruthKeyConfig(BaseModel):
    """Configuration for TruthKey formation."""
    spatial_system: str = "h3"  # h3, healpix, meta
    resolution: int = 8
    z_index: str = "surface"
    time_bucket: str = "PT1H"
    
    # id_strategy: ONLY applicable when spatial_system == "meta"
    # content_hash (default): spatial_id from artifact/dataset hash
    # provided_id: spatial_id from user-supplied stable id
    # hybrid: content_hash if present, else provided_id
    id_strategy: str = "content_hash"


class ConsensusModel(BaseModel):
    """Consensus configuration for truth state finalization."""
    type: str = "weighted_threshold"
    finalize_threshold: int = 15
    reject_threshold: int = -10
    weighted_roles: Dict[str, int] = Field(default_factory=lambda: {
        "bronze": 1, "silver": 3, "expert": 7, "authority": 10
    })


class AutovalidationConfig(BaseModel):
    """AI autovalidation thresholds."""
    ai_verified_true_threshold: float = 0.82
    ai_verified_false_threshold: float = 0.20


class TemporalDecayConfig(BaseModel):
    """Temporal decay configuration."""
    half_life: str = "PT6H"
    max_validity: str = "P3D"


class ClaimType(BaseModel):
    """
    ClaimType YAML contract with canonicalization.
    
    Canonical form: {namespace}.{name}.v{major}
    ClaimType hash is computed over canonical contract payload.
    """
    id: str  # e.g., "earth.flood.v1"
    version: int
    domain: str
    topic: str
    risk_profile: str = "monitor"
    
    # Configuration blocks
    truthkey: TruthKeyConfig = Field(default_factory=TruthKeyConfig)
    consensus_model: ConsensusModel = Field(default_factory=ConsensusModel)
    autovalidation: AutovalidationConfig = Field(default_factory=AutovalidationConfig)
    temporal_decay: TemporalDecayConfig = Field(default_factory=TemporalDecayConfig)
    
    # Output schema (NEW): validates TruthState.claim payload
    # Either inline schema or reference to external file
    output_schema: Optional[Dict[str, Any]] = None
    output_schema_ref: Optional[str] = None
    
    
    # Full config storage
    _raw_config: Dict[str, Any] = {}
    
    def canonical(self) -> dict:
        """
        Get canonical representation for hashing.
        
        Canonicalization includes:
        - Stable ordering of contract fields
        - Normalized numeric thresholds
        - Explicit policy version binding
        """
        truthkey_config = {
            "spatial_system": self.truthkey.spatial_system.lower(),
            "resolution": self.truthkey.resolution,
            "z_index": self.truthkey.z_index.lower(),
            "time_bucket": self.truthkey.time_bucket.upper(),
        }
        
        # Include id_strategy only for meta claims
        if self.truthkey.spatial_system.lower() == "meta":
            truthkey_config["id_strategy"] = self.truthkey.id_strategy.lower()
        
        return canonical_dict({
            "id": self.id.lower(),
            "version": self.version,
            "domain": self.domain.lower(),
            "topic": self.topic.lower(),
            "risk_profile": self.risk_profile.lower(),
            "truthkey": truthkey_config,
            "consensus_model": {
                "type": self.consensus_model.type,
                "finalize_threshold": self.consensus_model.finalize_threshold,
                "reject_threshold": self.consensus_model.reject_threshold,
            },
            "autovalidation": {
                "ai_verified_true_threshold": self.autovalidation.ai_verified_true_threshold,
                "ai_verified_false_threshold": self.autovalidation.ai_verified_false_threshold,
            },
            "temporal_decay": {
                "half_life": self.temporal_decay.half_life.upper(),
                "max_validity": self.temporal_decay.max_validity.upper(),
            },
        })
    
    def hash(self) -> str:
        """
        Compute canonical hash of this ClaimType.
        
        This hash identifies the exact contract version.
        """
        return canonical_hash(self.canonical())
    
    @property
    def policy_version(self) -> str:
        """Get policy version string."""
        return f"{self.id}.policy.{self.version}"
    
    def get_output_schema(self) -> Dict[str, Any]:
        """
        Get output schema for claim payload validation.
        
        Returns inline schema or loads from reference.
        """
        if self.output_schema:
            return self.output_schema
        if self.output_schema_ref:
            from kaori_truth.validation import load_schema
            return load_schema(self.output_schema_ref)
        # Default permissive schema
        return {"type": "object"}
    
    def validate_domain_config(self) -> None:
        """
        Validate that domain and spatial_system are compatible.
        
        Raises:
            ValueError: If invalid combination detected
        """
        domain = self.domain.lower()
        spatial = self.truthkey.spatial_system.lower()
        
        # Domain -> spatial_system rules
        valid_combos = {
            "earth": ["h3"],
            "ocean": ["h3"],
            "space": ["healpix"],
            "meta": ["meta"],
        }
        
        if domain in valid_combos:
            allowed = valid_combos[domain]
            if spatial not in allowed:
                raise ValueError(
                    f"Invalid domain/spatial_system combination: "
                    f"domain={domain} requires spatial_system in {allowed}, got {spatial}"
                )
        
        # id_strategy only valid for meta
        if spatial != "meta" and self.truthkey.id_strategy != "content_hash":
            raise ValueError(
                f"id_strategy is only applicable when spatial_system=meta, "
                f"got spatial_system={spatial}"
            )
    
    def get_config(self) -> Dict[str, Any]:
        """Get full raw configuration."""
        return self._raw_config or self.model_dump()
    def get_vote_weight(self, standing: str) -> int:
        """Get vote weight for a standing class."""
        return self.consensus_model.weighted_roles.get(standing.lower(), 1)


def load_claimtype_yaml(path: str | Path) -> ClaimType:
    """
    Load a ClaimType from YAML file.
    
    Args:
        path: Path to the YAML file
        
    Returns:
        ClaimType with parsed configuration
    """
    path = Path(path)
    
    with open(path, 'r', encoding='utf-8') as f:
        raw_config = yaml.safe_load(f)
    
    # Parse into ClaimType
    claim_type = ClaimType(
        id=raw_config.get("id", ""),
        version=raw_config.get("version", 1),
        domain=raw_config.get("domain", "earth"),
        topic=raw_config.get("topic", ""),
        risk_profile=raw_config.get("risk_profile", "monitor"),
        truthkey=TruthKeyConfig(**raw_config.get("truthkey", {})),
        consensus_model=ConsensusModel(**raw_config.get("consensus_model", {})),
        autovalidation=AutovalidationConfig(**raw_config.get("autovalidation", {})),
        temporal_decay=TemporalDecayConfig(**raw_config.get("temporal_decay", {})),
    )
    claim_type._raw_config = raw_config
    
    return claim_type


def canonical_claimtype(claim_type: ClaimType) -> dict:
    """
    Get canonical representation of a ClaimType.
    
    Args:
        claim_type: The ClaimType to canonicalize
        
    Returns:
        Canonical dictionary representation
    """
    return claim_type.canonical()


def claimtype_hash(claim_type: ClaimType) -> str:
    """
    Compute canonical hash of a ClaimType.
    
    Args:
        claim_type: The ClaimType to hash
        
    Returns:
        SHA256 hex hash
    """
    return claim_type.hash()


class CanonicalClaimType(BaseModel):
    """
    Immutable canonical representation of a ClaimType.
    
    Used for hash computation and audit.
    """
    id: str
    version: int
    domain: str
    topic: str
    hash: str
    
    @classmethod
    def from_claim_type(cls, ct: ClaimType) -> "CanonicalClaimType":
        """Create from ClaimType."""
        return cls(
            id=ct.id.lower(),
            version=ct.version,
            domain=ct.domain.lower(),
            topic=ct.topic.lower(),
            hash=ct.hash(),
        )
