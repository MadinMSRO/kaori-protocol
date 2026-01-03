"""
Kaori API — Votes Endpoints

Submit validation votes.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from core import KaoriEngine, Vote, Standing, VoteType
from .models import VoteCreate, VoteResponse
from .deps import engine as _engine

router = APIRouter()

# Shared engine instance
# _engine is imported from deps


@router.post("/votes", response_model=VoteResponse)
async def submit_vote(data: VoteCreate):
    """
    Submit a validation vote for a truth state.
    
    Vote types:
    - RATIFY: Confirm the observation is true
    - REJECT: Claim the observation is false
    - CHALLENGE: Request more evidence
    - OVERRIDE: Authority override (requires authority standing)
    """
    # Check if truth state exists
    truth_state = _engine.get_truth_state(data.truthkey)
    if not truth_state:
        raise HTTPException(status_code=404, detail=f"Truth state not found: {data.truthkey}")
    
    # Create vote
    try:
        vote_type = VoteType(data.vote_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid vote type: {data.vote_type}")
    
    vote = Vote(
        voter_id=data.voter_id,
        voter_standing=Standing.BRONZE,  # In production, look up from user database
        vote_type=vote_type,
        voted_at=datetime.now(timezone.utc),
        comment=data.comment,
    )
    
    try:
        # Apply vote through engine
        updated_state = _engine.apply_vote(data.truthkey, vote)
        
        return VoteResponse(
            vote_id=vote.vote_id,
            truthkey=data.truthkey,
            voter_id=data.voter_id,
            vote_type=vote_type.value,
            voted_at=vote.voted_at,
            consensus_score=updated_state.consensus.score if updated_state.consensus else 0,
            consensus_finalized=updated_state.consensus.finalized if updated_state.consensus else False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/truth/{truthkey:path}/votes")
async def get_votes(truthkey: str):
    """
    Get all votes for a truth state.
    """
    truth_state = _engine.get_truth_state(truthkey)
    
    if not truth_state:
        raise HTTPException(status_code=404, detail=f"Truth state not found: {truthkey}")
    
    if not truth_state.consensus:
        return {"truthkey": truthkey, "votes": [], "total": 0}
    
    votes = [
        {
            "vote_id": str(v.vote_id),
            "voter_id": v.voter_id,
            "voter_standing": v.voter_standing.value,
            "vote_type": v.vote_type.value,
            "voted_at": v.voted_at.isoformat(),
            "comment": v.comment,
        }
        for v in truth_state.consensus.votes
    ]
    
    return {
        "truthkey": truthkey,
        "votes": votes,
        "total": len(votes),
        "consensus_score": truth_state.consensus.score,
        "consensus_finalized": truth_state.consensus.finalized,
    }
