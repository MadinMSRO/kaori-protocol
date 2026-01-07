"""
Kaori Truth — TruthState Primitive

Gold layer truth state with semantic/state hash split and full audit trail.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from kaori_truth.canonical import canonical_hash, canonical_json
from kaori_truth.canonical.datetime import canonical_datetime
from kaori_truth.canonical.schema import CanonicalSchema


class TruthStatus(str, Enum):
    """
    Truth state status values (SPEC Section 8.1).
    
    Intermediate: May change during observation window.
    Final: Set only at window end, immutable and signed.
    """
    # Intermediate statuses (during time_bucket window)
    PENDING = "PENDING"
    LEANING_TRUE = "LEANING_TRUE"
    LEANING_FALSE = "LEANING_FALSE"
    UNDECIDED = "UNDECIDED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    INVESTIGATING = "INVESTIGATING"
    
    # Final statuses (at window end, must be signed)
    VERIFIED_TRUE = "VERIFIED_TRUE"
    VERIFIED_FALSE = "VERIFIED_FALSE"
    INCONCLUSIVE = "INCONCLUSIVE"
    EXPIRED = "EXPIRED"


class VerificationBasis(str, Enum):
    """What caused the verification."""
    AI_AUTOVALIDATION = "AI_AUTOVALIDATION"
    HUMAN_CONSENSUS = "HUMAN_CONSENSUS"
    AUTHORITY_OVERRIDE = "AUTHORITY_OVERRIDE"
    IMPLICIT_CONSENSUS = "IMPLICIT_CONSENSUS"
    TIMEOUT_DEFAULT = "TIMEOUT_DEFAULT"
    TIMEOUT_INCONCLUSIVE = "TIMEOUT_INCONCLUSIVE"


class CompileInputs(BaseModel):
    """
    Explicit record of all inputs to truth compilation.
    
    Per protocol requirements, TruthState MUST store enough
    information to replay compilation.
    """
    observation_ids: List[str]  # UUIDs as strings
    claim_type_id: str
    claim_type_hash: str  # Hash of claim type contract
    policy_version: str
    compiler_version: str
    trust_snapshot_hash: str  # Hash of trust snapshot at compile time
    compile_time: datetime  # Explicit compile time (NOT wall-clock)
    
    def canonical(self) -> dict:
        """Get canonical representation."""
        return {
            "observation_ids": sorted(self.observation_ids),  # Sort for determinism
            "claim_type_id": self.claim_type_id.lower(),
            "claim_type_hash": self.claim_type_hash.lower(),
            "policy_version": self.policy_version,
            "compiler_version": self.compiler_version,
            "trust_snapshot_hash": self.trust_snapshot_hash.lower(),
            "compile_time": canonical_datetime(self.compile_time),
        }


class SecurityBlock(BaseModel):
    """
    Cryptographic security for truth state (SPEC Section 16).
    
    Implements semantic_hash vs state_hash split:
    - semantic_hash: Stable across compile_time differences
    - state_hash: Full envelope including compile_time, compiler_version, etc.
    """
    semantic_hash: str  # Hash of truth content (stable)
    state_hash: str  # Hash of full signed envelope
    signature: str  # Signature over state_hash
    signing_method: str = "local_hmac"  # or "gcp_kms"
    key_id: str
    signed_at: datetime
    
    def canonical(self) -> dict:
        """Get canonical representation."""
        return {
            "semantic_hash": self.semantic_hash.lower(),
            "state_hash": self.state_hash.lower(),
            "signature": self.signature,
            "signing_method": self.signing_method,
            "key_id": self.key_id,
            "signed_at": canonical_datetime(self.signed_at),
        }


class ConfidenceBreakdown(BaseModel):
    """Breakdown of composite confidence calculation."""
    components: Dict[str, float] = Field(default_factory=dict)
    modifiers: Dict[str, float] = Field(default_factory=dict)
    raw_score: float = 0.0
    final_score: float = 0.0


class ConsensusRecord(BaseModel):
    """Record of consensus computation."""
    votes: List[Dict[str, Any]] = Field(default_factory=list)
    score: int = 0
    finalized: bool = False
    finalize_reason: Optional[str] = None
    positive_ratio: float = 0.5


class TruthState(BaseModel):
    """
    Gold layer truth state (SPEC Section 8).
    
    The verified, signed representation of truth.
    Includes full audit trail for replay.
    """
    truthkey: str  # Canonical TruthKey string
    claim_type: str
    claim_type_hash: str  # Hash of ClaimType contract
    status: TruthStatus = TruthStatus.PENDING
    verification_basis: Optional[VerificationBasis] = None
    
    # Claim output payload (schema-validated and canonicalized)
    # This is the actual truth output - REQUIRED
    claim: Dict[str, Any] = Field(default_factory=dict)
    
    # Confidence
    ai_confidence: float = 0.0
    confidence: float = 0.0
    confidence_breakdown: Optional[ConfidenceBreakdown] = None
    
    # Transparency
    transparency_flags: List[str] = Field(default_factory=list)
    
    # Audit fields for determinism
    compile_inputs: CompileInputs
    
    # Evidence
    evidence_refs: List[str] = Field(default_factory=list)
    observation_ids: List[str] = Field(default_factory=list)
    
    # Consensus
    consensus: Optional[ConsensusRecord] = None
    
    # Security (required for Silver/Gold)
    security: SecurityBlock
    
    def semantic_content(self) -> dict:
        """
        Get semantic content for hashing.
        
        This is stable across compile_time differences.
        Used for semantic_hash computation.
        
        INCLUDES claim payload (schema-validated output).
        """
        from kaori_truth.canonical.json import canonical_dict
        
        return {
            "truthkey": self.truthkey,
            "claim_type": self.claim_type.lower(),
            "claim_type_hash": self.claim_type_hash.lower(),
            "claim": canonical_dict(self.claim),  # Schema-validated claim payload
            "status": self.status.value,
            "verification_basis": self.verification_basis.value if self.verification_basis else None,
            "ai_confidence": round(self.ai_confidence, 6),
            "confidence": round(self.confidence, 6),
            "transparency_flags": sorted(self.transparency_flags),
            "evidence_refs": sorted(self.evidence_refs),
            "observation_ids": sorted(self.observation_ids),
            "trust_snapshot_hash": self.compile_inputs.trust_snapshot_hash.lower(),
            "policy_version": self.compile_inputs.policy_version,
        }
    
    def full_envelope(self) -> dict:
        """
        Get full envelope for state_hash computation.
        
        Includes compile_time, compiler_version, and other metadata.
        """
        semantic = self.semantic_content()
        return {
            **semantic,
            "compile_time": canonical_datetime(self.compile_inputs.compile_time),
            "compiler_version": self.compile_inputs.compiler_version,
        }
    
    def compute_semantic_hash(self) -> str:
        """Compute semantic hash (stable across compile_time)."""
        return canonical_hash(self.semantic_content())
    
    def compute_state_hash(self) -> str:
        """Compute full state hash (includes compile_time)."""
        return canonical_hash(self.full_envelope())
    
    def verify_hashes(self) -> bool:
        """Verify that stored hashes match computed hashes."""
        return (
            self.security.semantic_hash == self.compute_semantic_hash() and
            self.security.state_hash == self.compute_state_hash()
        )
