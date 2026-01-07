"""
Kaori Truth — Consensus Computation

Compute consensus from votes using weighted threshold model (SPEC Section 10).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from kaori_truth.primitives.truthstate import ConsensusRecord


def compute_consensus(
    votes: List[dict],
    claim_config: dict,
) -> ConsensusRecord:
    """
    Compute consensus from a list of votes using weighted threshold model.
    
    Formula: score = Σ(weight(standing) × vote_value)
    
    Args:
        votes: List of vote dicts with voter_standing, vote_type
        claim_config: Claim configuration with consensus_model
        
    Returns:
        ConsensusRecord with computed score and finalization status
    """
    import math
    
    consensus_config = claim_config.get("consensus_model", {})
    finalize_threshold = consensus_config.get("finalize_threshold", 15)
    reject_threshold = consensus_config.get("reject_threshold", -10)
    
    # Compute score
    score = 0.0
    ratify_count = 0
    reject_count = 0
    
    for vote in votes:
        standing = vote.get("voter_standing", 10.0)
        vote_type = vote.get("vote_type", "RATIFY")
        
        # Weight from standing (logarithmic)
        weight = 1.0 + math.log2(1 + standing / 10.0)
        
        if vote_type == "RATIFY":
            score += weight
            ratify_count += 1
        elif vote_type == "REJECT":
            score -= weight
            reject_count += 1
        elif vote_type == "OVERRIDE":
            # Authority override
            if standing >= 500:
                return ConsensusRecord(
                    votes=votes,
                    score=int(score),
                    finalized=True,
                    finalize_reason=f"AUTHORITY_OVERRIDE by {vote.get('voter_id')}",
                    positive_ratio=1.0,
                )
    
    # Positive ratio
    total_votes = ratify_count + reject_count
    if total_votes > 0:
        positive_ratio = ((ratify_count - reject_count) / total_votes + 1) / 2
    else:
        positive_ratio = 0.5
    
    # Check finalization
    finalized = False
    finalize_reason = None
    
    if score >= finalize_threshold:
        finalized = True
        finalize_reason = f"THRESHOLD_REACHED (score={score:.1f})"
    elif score <= reject_threshold:
        finalized = True
        finalize_reason = f"REJECT_THRESHOLD (score={score:.1f})"
    
    return ConsensusRecord(
        votes=votes,
        score=int(score),
        finalized=finalized,
        finalize_reason=finalize_reason,
        positive_ratio=positive_ratio,
    )
