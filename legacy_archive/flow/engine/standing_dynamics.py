"""
Kaori Flow — Standing Dynamics

Implements Law 5 of FLOW_SPEC: Agent standing evolves based on verification outcomes.
This module connects Truth layer finalization to Flow layer standing updates.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from core.models import Agent, Standing, TruthStatus, VoteType
from core.db.database import SessionLocal
from core.db.models import AgentModel


# =============================================================================
# Configuration (from FLOW_SPEC Section 5)
# =============================================================================

STANDING_CONFIG = {
    "accuracy": {
        "observation_correct": 1.0,    # Standing += on verified observation
        "observation_wrong": 1.5,      # Standing -= on contradicted observation
        "vote_correct": 0.5,           # Standing += on vote aligned with outcome
        "vote_wrong": 0.8,             # Standing -= on vote against outcome
    },
    "bounds": {
        "min": 0.0,
        "max": 1000.0,
        "initial": 10.0,
    },
    "promotion_thresholds": {
        "silver": 50.0,
        "expert": 200.0,
        "authority": 500.0,  # Usually requires manual promotion
    }
}


# =============================================================================
# Standing Update Functions
# =============================================================================

def update_reporter_standing(
    reporter_id: str,
    outcome: TruthStatus,
    confidence: float,
) -> Optional[Agent]:
    """
    Update reporter standing after truth finalization.
    
    Args:
        reporter_id: The agent who submitted the observation
        outcome: The final TruthStatus (VERIFIED_TRUE, VERIFIED_FALSE, etc.)
        confidence: The confidence score of the finalized truth state
    
    Returns:
        Updated Agent or None if not found
    """
    with SessionLocal() as db:
        agent_model = db.query(AgentModel).filter(
            AgentModel.agent_id == reporter_id
        ).first()
        
        if not agent_model:
            # Create agent if doesn't exist (first-time reporter)
            agent_model = AgentModel(
                agent_id=reporter_id,
                standing="bronze",
                trust_score=0.5,
            )
            db.add(agent_model)
        
        # Determine outcome polarity
        if outcome == TruthStatus.VERIFIED_TRUE:
            # Observation was correct
            delta = confidence * STANDING_CONFIG["accuracy"]["observation_correct"]
            agent_model.trust_score = min(1.0, agent_model.trust_score + 0.02)
            agent_model.verified_observations += 1
        elif outcome == TruthStatus.VERIFIED_FALSE:
            # Observation was wrong
            delta = -confidence * STANDING_CONFIG["accuracy"]["observation_wrong"]
            agent_model.trust_score = max(0.0, agent_model.trust_score - 0.05)
        else:
            # INCONCLUSIVE, EXPIRED - no change
            delta = 0
        
        # Apply delta with bounds
        current = agent_model.trust_score * 100  # Convert to standing points
        new_standing = max(
            STANDING_CONFIG["bounds"]["min"],
            min(STANDING_CONFIG["bounds"]["max"], current + delta)
        )
        
        # Check for promotion
        agent_model.standing = _compute_standing_class(new_standing)
        agent_model.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(agent_model)
        
        return _model_to_agent(agent_model)


def update_voter_standing(
    voter_id: str,
    vote_type: VoteType,
    final_outcome: TruthStatus,
    confidence: float,
) -> Optional[Agent]:
    """
    Update voter standing after truth finalization.
    
    Args:
        voter_id: The agent who cast the vote
        vote_type: RATIFY, REJECT, etc.
        final_outcome: The final TruthStatus
        confidence: The confidence score of the finalized truth state
    """
    with SessionLocal() as db:
        agent_model = db.query(AgentModel).filter(
            AgentModel.agent_id == voter_id
        ).first()
        
        if not agent_model:
            # Voter must exist
            return None
        
        # Determine if vote was correct
        vote_aligned = _vote_aligned_with_outcome(vote_type, final_outcome)
        
        if vote_aligned:
            delta = confidence * STANDING_CONFIG["accuracy"]["vote_correct"]
            agent_model.correct_votes += 1
        else:
            delta = -confidence * STANDING_CONFIG["accuracy"]["vote_wrong"]
        
        agent_model.total_votes += 1
        
        # Apply delta
        current = agent_model.trust_score * 100
        new_standing = max(
            STANDING_CONFIG["bounds"]["min"],
            min(STANDING_CONFIG["bounds"]["max"], current + delta)
        )
        
        agent_model.standing = _compute_standing_class(new_standing)
        agent_model.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(agent_model)
        
        return _model_to_agent(agent_model)


def process_finalization_outcomes(
    reporter_ids: list[str],
    voter_ids_and_votes: list[tuple[str, VoteType]],
    final_outcome: TruthStatus,
    confidence: float,
):
    """
    Process all standing updates for a finalized TruthState.
    Called by the Truth Engine after finalization.
    """
    # Update reporters
    for reporter_id in reporter_ids:
        update_reporter_standing(reporter_id, final_outcome, confidence)
    
    # Update voters
    for voter_id, vote_type in voter_ids_and_votes:
        update_voter_standing(voter_id, vote_type, final_outcome, confidence)


# =============================================================================
# Helper Functions
# =============================================================================

def _compute_standing_class(standing_points: float) -> str:
    """Determine standing class from points."""
    thresholds = STANDING_CONFIG["promotion_thresholds"]
    
    if standing_points >= thresholds["authority"]:
        return "authority"
    elif standing_points >= thresholds["expert"]:
        return "expert"
    elif standing_points >= thresholds["silver"]:
        return "silver"
    else:
        return "bronze"


def _vote_aligned_with_outcome(vote_type: VoteType, outcome: TruthStatus) -> bool:
    """Check if vote aligned with final outcome."""
    if vote_type == VoteType.RATIFY:
        return outcome == TruthStatus.VERIFIED_TRUE
    elif vote_type == VoteType.REJECT:
        return outcome == TruthStatus.VERIFIED_FALSE
    else:
        # CHALLENGE and OVERRIDE don't have simple alignment
        return True  # No penalty


def _model_to_agent(model: AgentModel) -> Agent:
    """Convert DB model to Pydantic."""
    from core.models import AgentType
    return Agent(
        agent_id=UUID(model.agent_id),
        agent_type=AgentType(model.agent_type),
        standing=Standing(model.standing),
        trust_score=model.trust_score,
        qualifications=model.qualifications or {},
        verified_observations=model.verified_observations,
        correct_votes=model.correct_votes,
        total_votes=model.total_votes,
    )


def get_or_create_agent(agent_id: str) -> Agent:
    """Get agent by ID or create with defaults."""
    with SessionLocal() as db:
        agent_model = db.query(AgentModel).filter(
            AgentModel.agent_id == agent_id
        ).first()
        
        if not agent_model:
            agent_model = AgentModel(
                agent_id=agent_id,
                agent_type="individual",
                standing="bronze",
                trust_score=0.5,
            )
            db.add(agent_model)
            db.commit()
            db.refresh(agent_model)
        
        return _model_to_agent(agent_model)
