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
    ContentBoundEvidenceRef,
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


def _content_bound_ref(ref) -> ContentBoundEvidenceRef:
    """Keep uri + sha256. Drop URI-only strings."""
    if hasattr(ref, "uri") and hasattr(ref, "sha256") and ref.sha256:
        return ContentBoundEvidenceRef(uri=ref.uri, sha256=ref.sha256)
    if isinstance(ref, dict) and ref.get("uri") and ref.get("sha256"):
        return ContentBoundEvidenceRef(uri=ref["uri"], sha256=ref["sha256"])
    raise CompilationError("EvidenceRef must be content-bound (uri + sha256)")


def _content_bound_evidence_refs(observations: List[Observation]) -> List[ContentBoundEvidenceRef]:
    refs: List[ContentBoundEvidenceRef] = []
    seen = set()
    for obs in observations:
        for ref in obs.evidence_refs:
            bound = _content_bound_ref(ref)
            key = (bound.uri, bound.sha256)
            if key in seen:
                continue
            seen.add(key)
            refs.append(bound)
    refs.sort(key=lambda item: (item.sha256, item.uri))
    return refs


def _observation_compile_package(obs: Observation) -> dict:
    """Canonical observation with content-bound evidence_refs — enough to replay."""
    package = obs.canonical()
    package["evidence_refs"] = [
        {"uri": bound.uri, "sha256": bound.sha256}
        for bound in (_content_bound_ref(ref) for ref in obs.evidence_refs)
    ]
    return package


def _consensus_record(votes: Optional[List[dict]], claim_type: ClaimType) -> Optional[ConsensusRecord]:
    """Record compiler vote inputs on ConsensusRecord.votes. No invented field."""
    if not votes:
        return None
    return compute_consensus(votes, claim_type.get_config())


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
    observation_hashes = sorted(obs.hash() for obs in observations)
    observation_packages = sorted(
        (_observation_compile_package(obs) for obs in observations),
        key=lambda package: package["observation_id"],
    )
    evidence_refs = _content_bound_evidence_refs(observations)
    
    compile_inputs = CompileInputs(
        observation_ids=observation_ids,
        observation_hashes=observation_hashes,
        observations=observation_packages,
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
        consensus=_consensus_record(votes, claim_type),
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
        power = trust_snapshot.get_trust(obs.reporter_id)
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


def _human_gating(claim_type: ClaimType) -> dict:
    """Read human_gating from the ClaimType YAML (via raw config)."""
    config = claim_type.get_config() if hasattr(claim_type, "get_config") else {}
    gating = (config or {}).get("human_gating") or {}
    return gating if isinstance(gating, dict) else {}


def _vote_field(vote: dict, *names: str, default=None):
    for name in names:
        if name in vote and vote[name] is not None:
            return vote[name]
    return default


def _vote_value(vote: dict) -> str:
    return str(_vote_field(vote, "vote", "vote_type", default="") or "").upper()


def _vote_agent_id(vote: dict) -> str:
    return str(_vote_field(vote, "agent_id", "voter_id", default="") or "")


def _is_human_vote(vote: dict) -> bool:
    """FLOW_SPEC: user:/human: agents are human; ai: validators are not."""
    agent_id = _vote_agent_id(vote)
    return agent_id.startswith("user:") or agent_id.startswith("human:")


def _recorded_ai_mean(votes: List[dict], fallback: float) -> float:
    """Use recorded vote confidence when present; otherwise compile aggregate."""
    scores = []
    for vote in votes:
        confidence = _vote_field(vote, "confidence")
        if confidence is None:
            continue
        try:
            scores.append(float(confidence))
        except (TypeError, ValueError):
            continue
    if not scores:
        return fallback
    import statistics
    return round(statistics.mean(scores), 6)


def _has_human_consensus(votes: List[dict]) -> bool:
    """Human RATIFY/REJECT recorded as votes. AI RATIFY is not human consensus."""
    human = [vote for vote in votes if _is_human_vote(vote)]
    return any(_vote_value(vote) in ("RATIFY", "REJECT") for vote in human)


def _determine_status(
    aggregate: dict,
    claim_type: ClaimType,
    votes: List[dict],
) -> tuple[TruthStatus, Optional[VerificationBasis], List[str]]:
    """
    Determine truth status from ClaimType YAML + recorded votes.

    YAML is the law:
    - always_require_human true → PENDING_HUMAN_REVIEW even after RATIFY
    - always_require_human false → do not stamp PENDING_HUMAN_REVIEW from
      risk_profile alone; use autovalidation thresholds + recorded votes
    - required_for_risk_profiles: those lanes need human consensus before
      VERIFIED_TRUE / VERIFIED_FALSE (TRUTH_SPEC §15.2). Status stays
      intermediate (LEANING_* / INVESTIGATING), not an invented VALIDATION.
    """
    transparency_flags: List[str] = []
    gating = _human_gating(claim_type)
    always_require_human = bool(gating.get("always_require_human"))
    required_profiles = gating.get("required_for_risk_profiles") or []
    if not isinstance(required_profiles, list):
        required_profiles = []

    autovalidation = claim_type.autovalidation
    ai_true_threshold = autovalidation.ai_verified_true_threshold
    ai_false_threshold = autovalidation.ai_verified_false_threshold
    min_ai = gating.get("min_ai_confidence")
    if min_ai is not None:
        try:
            ai_true_threshold = max(ai_true_threshold, float(min_ai))
        except (TypeError, ValueError):
            pass

    ai_mean = _recorded_ai_mean(votes, aggregate.get("ai_confidence_mean", 0.0))
    ai_variance = aggregate.get("ai_variance", 0.0)

    if ai_variance > 0.15:
        transparency_flags.append("CONTRADICTION_DETECTED")
        return TruthStatus.UNDECIDED, None, transparency_flags

    if always_require_human:
        if ai_mean >= ai_true_threshold:
            transparency_flags.append("AI_RECOMMENDS_TRUE")
        elif ai_mean <= ai_false_threshold:
            transparency_flags.append("AI_RECOMMENDS_FALSE")
        transparency_flags.append("AWAITING_HUMAN_CONSENSUS")
        return TruthStatus.PENDING_HUMAN_REVIEW, None, transparency_flags

    human_required_to_verify = claim_type.risk_profile in required_profiles
    has_human = _has_human_consensus(votes)

    if ai_mean >= ai_true_threshold:
        if human_required_to_verify and not has_human:
            transparency_flags.append("AI_RECOMMENDS_TRUE")
            return TruthStatus.LEANING_TRUE, None, transparency_flags
        basis = (
            VerificationBasis.HUMAN_CONSENSUS
            if has_human
            else VerificationBasis.AI_AUTOVALIDATION
        )
        return TruthStatus.VERIFIED_TRUE, basis, transparency_flags

    if ai_mean <= ai_false_threshold:
        if human_required_to_verify and not has_human:
            transparency_flags.append("AI_RECOMMENDS_FALSE")
            return TruthStatus.LEANING_FALSE, None, transparency_flags
        basis = (
            VerificationBasis.HUMAN_CONSENSUS
            if has_human
            else VerificationBasis.AI_AUTOVALIDATION
        )
        return TruthStatus.VERIFIED_FALSE, basis, transparency_flags

    return TruthStatus.INVESTIGATING, None, transparency_flags


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
