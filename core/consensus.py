"""
Kaori Core — Consensus Computation

Compute consensus from votes using weighted threshold model (SPEC Section 10).
"""
from __future__ import annotations

from .models import (
    ConsensusRecord,
    Standing,
    Vote,
    VoteType,
)


# Default weights per standing
DEFAULT_WEIGHTS = {
    Standing.BRONZE: 1,
    Standing.SILVER: 3,
    Standing.EXPERT: 7,
    Standing.AUTHORITY: 10,
}

# Default vote values
DEFAULT_VOTE_VALUES = {
    VoteType.RATIFY: 1,
    VoteType.REJECT: -1,
    VoteType.CHALLENGE: 0,
    VoteType.OVERRIDE: 0,  # Special handling
}


def compute_consensus(
    votes: list[Vote],
    claim_config: dict,
) -> ConsensusRecord:
    """
    Compute consensus from a list of votes using weighted threshold model.
    
    Formula: score = Σ(weight(role) × vote_value)
    
    Args:
        votes: List of Vote objects
        claim_config: Claim configuration with consensus_model
        
    Returns:
        ConsensusRecord with computed score and finalization status
    """
    consensus_config = claim_config.get("consensus_model", {})
    
    # Get thresholds
    finalize_threshold = consensus_config.get("finalize_threshold", 15)
    reject_threshold = consensus_config.get("reject_threshold", -10)
    
    # Get weights per role
    weighted_roles = consensus_config.get("weighted_roles", {})
    weights = {
        Standing.BRONZE: weighted_roles.get("bronze", DEFAULT_WEIGHTS[Standing.BRONZE]),
        Standing.SILVER: weighted_roles.get("silver", DEFAULT_WEIGHTS[Standing.SILVER]),
        Standing.EXPERT: weighted_roles.get("expert", DEFAULT_WEIGHTS[Standing.EXPERT]),
        Standing.AUTHORITY: weighted_roles.get("authority", DEFAULT_WEIGHTS[Standing.AUTHORITY]),
    }
    
    # Get vote values
    vote_types_config = consensus_config.get("vote_types", {})
    vote_values = {
        VoteType.RATIFY: vote_types_config.get("RATIFY", DEFAULT_VOTE_VALUES[VoteType.RATIFY]),
        VoteType.REJECT: vote_types_config.get("REJECT", DEFAULT_VOTE_VALUES[VoteType.REJECT]),
        VoteType.CHALLENGE: vote_types_config.get("CHALLENGE", DEFAULT_VOTE_VALUES[VoteType.CHALLENGE]),
        VoteType.OVERRIDE: vote_types_config.get("OVERRIDE", DEFAULT_VOTE_VALUES[VoteType.OVERRIDE]),
    }
    
    # Get override roles
    override_roles = consensus_config.get("override_allowed_roles", ["authority"])
    override_standings = [Standing(r) for r in override_roles]
    
    # Compute score
    score = 0
    ratify_count = 0
    reject_count = 0
    has_override = False
    override_vote: Vote | None = None
    
    for vote in votes:
        # Check for override
        if vote.vote_type == VoteType.OVERRIDE:
            if vote.voter_standing in override_standings:
                has_override = True
                override_vote = vote
                continue
        
        # Normal vote processing
        weight = weights.get(vote.voter_standing, 1)
        value = vote_values.get(vote.vote_type, 0)
        score += weight * value
        
        if vote.vote_type == VoteType.RATIFY:
            ratify_count += 1
        elif vote.vote_type == VoteType.REJECT:
            reject_count += 1
    
    # Calculate positive ratio
    total_votes = ratify_count + reject_count
    if total_votes > 0:
        positive_ratio = (ratify_count - reject_count) / total_votes
        positive_ratio = (positive_ratio + 1) / 2  # Normalize to 0-1
    else:
        positive_ratio = 0.5
    
    # Determine finalization
    finalized = False
    finalize_reason = None
    
    if has_override and override_vote:
        finalized = True
        finalize_reason = f"AUTHORITY_OVERRIDE by {override_vote.voter_id}"
    elif score >= finalize_threshold:
        finalized = True
        finalize_reason = f"THRESHOLD_REACHED (score={score} >= {finalize_threshold})"
    elif score <= reject_threshold:
        finalized = True
        finalize_reason = f"REJECT_THRESHOLD (score={score} <= {reject_threshold})"
    
    return ConsensusRecord(
        votes=votes,
        score=score,
        finalized=finalized,
        finalize_reason=finalize_reason,
        positive_ratio=positive_ratio,
    )


def is_consensus_finalized(consensus: ConsensusRecord) -> bool:
    """Check if consensus has reached a final decision."""
    return consensus.finalized


def get_consensus_outcome(
    consensus: ConsensusRecord,
    claim_config: dict,
) -> str | None:
    """
    Get the outcome of a finalized consensus.
    
    Returns:
        "VERIFIED_TRUE", "VERIFIED_FALSE", or None if not finalized
    """
    if not consensus.finalized:
        return None
    
    consensus_config = claim_config.get("consensus_model", {})
    finalize_threshold = consensus_config.get("finalize_threshold", 15)
    reject_threshold = consensus_config.get("reject_threshold", -10)
    
    # Override always verifies true
    if consensus.finalize_reason and "OVERRIDE" in consensus.finalize_reason:
        return "VERIFIED_TRUE"
    
    if consensus.score >= finalize_threshold:
        return "VERIFIED_TRUE"
    elif consensus.score <= reject_threshold:
        return "VERIFIED_FALSE"
    
    return None
