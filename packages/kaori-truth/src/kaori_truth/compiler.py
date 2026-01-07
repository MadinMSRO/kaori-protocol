"""
Kaori Truth — Pure Truth Compiler

Deterministic, pure function compiler for truth states.

INVARIANT: Given identical inputs, produces byte-identical output.

This compiler:
- Has ZERO imports from kaori-db, kaori-api, kaori-flow
- Has NO runtime side effects
- Has NO file IO
- Has NO wall-clock time access
- Accepts TrustSnapshot data only (never calls TrustProvider)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from kaori_truth.canonical import canonical_hash
from kaori_truth.canonical.datetime import canonical_datetime
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.observation import Observation
from kaori_truth.primitives.truthkey import build_truthkey, TruthKey
from kaori_truth.primitives.truthstate import (
    TruthState,
    TruthStatus,
    VerificationBasis,
    CompileInputs,
    SecurityBlock,
    ConfidenceBreakdown,
    ConsensusRecord,
)
from kaori_truth.trust_snapshot import TrustSnapshot
from kaori_truth.confidence import compute_confidence
from kaori_truth.consensus import compute_consensus
from kaori_truth.validation import validate_claim_payload, SchemaValidationError
from kaori_truth.claim_derivation import derive_claim_payload, ClaimDerivationError


# Compiler version - bump when algorithm changes
COMPILER_VERSION = "1.0.0"


class CompilationError(Exception):
    """Error during truth compilation."""
    pass


def compile_truth_state(
    claim_type: ClaimType,
    truth_key: str,
    observations: List[Observation],
    trust_snapshot: TrustSnapshot,
    policy_version: str,
    compiler_version: str = COMPILER_VERSION,
    compile_time: datetime = None,
    *,
    ai_scores: Optional[List[float]] = None,
    votes: Optional[List[dict]] = None,
) -> TruthState:
    """
    Pure function: Compile observations into a TruthState.
    
    INVARIANT: Given identical inputs, produces byte-identical output.
    
    This is the core contract that production repos depend on.
    
    Args:
        claim_type: The ClaimType YAML contract
        truth_key: Canonical TruthKey string
        observations: List of observations to compile
        trust_snapshot: Frozen snapshot of trust state (from Flow)
        policy_version: Version of the policy being applied
        compiler_version: Version of this compiler
        compile_time: Explicit compile timestamp (REQUIRED for determinism)
        ai_scores: Optional list of AI confidence scores per observation
        votes: Optional list of vote records
        
    Returns:
        Signed TruthState with all audit fields populated
        
    Raises:
        CompilationError: If compile_time is not provided, schema validation fails, etc.
    """
    # =========================================================================
    # 1. Validation
    # =========================================================================
    
    if compile_time is None:
        raise CompilationError(
            "compile_time MUST be explicitly provided for determinism. "
            "Do not use wall-clock time."
        )
    
    if not observations:
        raise CompilationError("At least one observation is required")
    
    # Verify trust snapshot
    if not trust_snapshot.verify_hash():
        raise CompilationError(
            f"TrustSnapshot hash mismatch. Expected {trust_snapshot.compute_hash()}, "
            f"got {trust_snapshot.snapshot_hash}"
        )
    
    # =========================================================================
    # 2. Gather compile inputs
    # =========================================================================
    
    observation_ids = sorted([str(obs.observation_id) for obs in observations])
    evidence_refs = []
    for obs in observations:
        for ref in obs.evidence_refs:
            if hasattr(ref, 'uri'):
                evidence_refs.append(ref.uri)
            else:
                evidence_refs.append(str(ref))
    evidence_refs = sorted(set(evidence_refs))
    
    compile_inputs = CompileInputs(
        observation_ids=observation_ids,
        claim_type_id=claim_type.id,
        claim_type_hash=claim_type.hash(),
        policy_version=policy_version,
        compiler_version=compiler_version,
        trust_snapshot_hash=trust_snapshot.snapshot_hash,
        compile_time=compile_time,
    )

    # =========================================================================
    # 3. Compute aggregate metrics
    # =========================================================================
    
    aggregate = _compute_observation_aggregate(observations, trust_snapshot, ai_scores)

    # =========================================================================
    # 3b. Derive claim payload (Deterministic)
    # =========================================================================
    
    # =========================================================================
    # 3b. Derive claim payload (Deterministic)
    # =========================================================================
    
    try:
        raw_payload = derive_claim_payload(
            observations=observations,
            trust_snapshot=trust_snapshot,
            claim_type=claim_type,
            truth_key=truth_key,
            aggregate=aggregate,
        )
    except ClaimDerivationError as e:
        raise CompilationError(f"Claim derivation failed: {e}")

    # =========================================================================
    # 3c. Validate claim payload against output schema
    # =========================================================================
    
    try:
        output_schema = claim_type.get_output_schema()
        validated_payload = validate_claim_payload(raw_payload, output_schema)
    except SchemaValidationError as e:
        raise CompilationError(f"Claim payload schema validation failed: {e}")
    
    # =========================================================================
    # 4. Determine status and verification basis
    # =========================================================================
    
    status, verification_basis, transparency_flags = _determine_status(
        aggregate=aggregate,
        claim_type=claim_type,
        votes=votes or [],
    )
    
    # =========================================================================
    # 5. Compute confidence
    # =========================================================================
    
    confidence_breakdown = _compute_confidence(
        aggregate=aggregate,
        claim_type=claim_type,
        votes=votes or [],
        transparency_flags=transparency_flags,
    )
    
    # =========================================================================
    # 6. Build TruthState (without security block)
    # =========================================================================
    
    # Create a minimal security block for intermediate construction
    temp_security = SecurityBlock(
        semantic_hash="",
        state_hash="",
        signature="",
        signing_method="pending",
        key_id="pending",
        signed_at=compile_time,
    )
    
    truth_state = TruthState(
        truthkey=truth_key,
        claim_type=claim_type.id,
        claim_type_hash=claim_type.hash(),
        status=status,
        verification_basis=verification_basis,
        claim=validated_payload,  # Schema-validated and canonicalized
        ai_confidence=aggregate.get("ai_confidence_mean", 0.0),
        confidence=confidence_breakdown.final_score,
        confidence_breakdown=confidence_breakdown,
        transparency_flags=transparency_flags,
        compile_inputs=compile_inputs,
        evidence_refs=evidence_refs,
        observation_ids=observation_ids,
        consensus=None,  # Would be populated if votes present
        security=temp_security,
    )
    
    # =========================================================================
    # 7. Compute hashes
    # =========================================================================
    
    semantic_hash = truth_state.compute_semantic_hash()
    state_hash = truth_state.compute_state_hash()
    
    # Update security block with computed hashes
    # Signature will be applied by signing module
    truth_state.security = SecurityBlock(
        semantic_hash=semantic_hash,
        state_hash=state_hash,
        signature="",  # To be filled by signing
        signing_method="pending",
        key_id="pending",
        signed_at=compile_time,
    )
    
    return truth_state


def _compute_observation_aggregate(
    observations: List[Observation],
    trust_snapshot: TrustSnapshot,
    ai_scores: Optional[List[float]],
) -> dict:
    """Compute aggregate metrics from observations."""
    import statistics
    
    if not observations:
        return {
            "observation_count": 0,
            "network_trust": 0.0,
            "ai_confidence_mean": 0.0,
            "ai_variance": 0.0,
        }
    
    # Sum of reporter powers from trust snapshot
    network_trust = 0.0
    for obs in observations:
        power = trust_snapshot.get_power(obs.reporter_id)
        network_trust += power
    
    # AI scores
    if not ai_scores:
        ai_scores = [0.5] * len(observations)
    
    ai_mean = statistics.mean(ai_scores) if ai_scores else 0.5
    ai_variance = statistics.variance(ai_scores) if len(ai_scores) > 1 else 0.0
    
    return {
        "observation_count": len(observations),
        "network_trust": network_trust,
        "ai_confidence_mean": round(ai_mean, 6),
        "ai_variance": round(ai_variance, 6),
    }


def _determine_status(
    aggregate: dict,
    claim_type: ClaimType,
    votes: List[dict],
) -> tuple[TruthStatus, Optional[VerificationBasis], List[str]]:
    """Determine truth status based on aggregate and config."""
    
    transparency_flags = []
    
    autovalidation = claim_type.autovalidation
    ai_true_threshold = autovalidation.ai_verified_true_threshold
    ai_false_threshold = autovalidation.ai_verified_false_threshold
    
    ai_mean = aggregate.get("ai_confidence_mean", 0.0)
    ai_variance = aggregate.get("ai_variance", 0.0)
    
    # Check for contradiction (high variance)
    if ai_variance > 0.15:
        transparency_flags.append("CONTRADICTION_DETECTED")
        return TruthStatus.UNDECIDED, None, transparency_flags
    
    # Risk profile determines lane
    risk_profile = claim_type.risk_profile
    
    if risk_profile == "monitor":
        # Monitor Lane: AI can auto-verify
        if ai_mean >= ai_true_threshold:
            return TruthStatus.VERIFIED_TRUE, VerificationBasis.AI_AUTOVALIDATION, transparency_flags
        elif ai_mean <= ai_false_threshold:
            return TruthStatus.VERIFIED_FALSE, VerificationBasis.AI_AUTOVALIDATION, transparency_flags
        else:
            return TruthStatus.INVESTIGATING, None, transparency_flags
    else:
        # Critical Lane: Require human consensus
        if ai_mean >= ai_true_threshold:
            transparency_flags.append("AI_RECOMMENDS_TRUE")
        elif ai_mean <= ai_false_threshold:
            transparency_flags.append("AI_RECOMMENDS_FALSE")
        transparency_flags.append("AWAITING_HUMAN_CONSENSUS")
        return TruthStatus.PENDING_HUMAN_REVIEW, None, transparency_flags


def _compute_confidence(
    aggregate: dict,
    claim_type: ClaimType,
    votes: List[dict],
    transparency_flags: List[str],
) -> ConfidenceBreakdown:
    """Compute composite confidence."""
    
    components = {
        "ai_confidence": aggregate.get("ai_confidence_mean", 0.0),
    }
    
    modifiers = {}
    if "CONTRADICTION_DETECTED" in transparency_flags:
        modifiers["contradiction_detected"] = True
    
    # Simple confidence computation (would use claim_type.get_config() for full)
    raw_score = components.get("ai_confidence", 0.0)
    
    # Apply contradiction penalty
    if modifiers.get("contradiction_detected"):
        raw_score -= 0.2
    
    final_score = max(0.0, min(1.0, raw_score))
    
    return ConfidenceBreakdown(
        components=components,
        modifiers={k: -0.2 for k, v in modifiers.items() if v},
        raw_score=raw_score,
        final_score=final_score,
    )
