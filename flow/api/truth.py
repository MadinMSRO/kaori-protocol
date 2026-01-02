"""
Kaori API — Truth Endpoints

Query truth states and history.
"""
from fastapi import APIRouter, HTTPException

from core import KaoriEngine
from core.db.database import SessionLocal
from core.db import crud
from .models import TruthStateResponse, TruthHistoryResponse
from .deps import engine as _engine

router = APIRouter()

# Shared engine instance
# _engine imported from deps


@router.get("/truth/state/{truthkey:path}", response_model=TruthStateResponse)
async def get_truth_state(truthkey: str):
    """
    Get current truth state for a TruthKey.
    
    The TruthKey format: {domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
    Example: earth:flood:h3:886142a8e7fffff:surface:2026-01-02T10:00:00Z
    """
    truth_state = _engine.get_truth_state(truthkey)
    
    if not truth_state:
        raise HTTPException(status_code=404, detail=f"Truth state not found: {truthkey}")
    
    return TruthStateResponse(
        truthkey=truth_state.truthkey.to_string(),
        claim_type=truth_state.claim_type,
        status=truth_state.status.value,
        confidence=truth_state.confidence,
        ai_confidence=truth_state.ai_confidence,
        verification_basis=truth_state.verification_basis.value if truth_state.verification_basis else None,
        transparency_flags=truth_state.transparency_flags,
        observation_count=len(truth_state.observation_ids),
        created_at=truth_state.created_at,
        updated_at=truth_state.updated_at,
        is_signed=truth_state.security is not None,
        truth_hash=truth_state.security.truth_hash if truth_state.security else None,
    )


@router.get("/truth/history/{truthkey:path}", response_model=TruthHistoryResponse)
async def get_truth_history(truthkey: str):
    """
    Get truth history (Silver ledger) for a TruthKey.
    
    Note: Requires persistence layer for full history.
    Currently returns current state only.
    """
    truth_state = _engine.get_truth_state(truthkey)
    
    if not truth_state:
        raise HTTPException(status_code=404, detail=f"Truth state not found: {truthkey}")
    
    # In production, query Silver table for full history
    # For now, return current state as single history entry
    history = [
        {
            "timestamp": truth_state.updated_at.isoformat(),
            "status": truth_state.status.value,
            "confidence": truth_state.confidence,
            "truth_hash": truth_state.security.truth_hash if truth_state.security else None,
        }
    ]
    
    return TruthHistoryResponse(
        truthkey=truthkey,
        history=history,
    )


@router.get("/truth/feed", response_model=list[TruthStateResponse])
async def get_truth_feed(limit: int = 50):
    """
    Get recent truth states for the dashboard feed.
    """
    with SessionLocal() as db:
        states = crud.get_recent_truth_states(db, limit)
        domain_states = [_engine._model_to_pydantic(s) for s in states]
        
        return [
            TruthStateResponse(
                truthkey=s.truthkey.to_string(),
                claim_type=s.claim_type,
                status=s.status.value,
                confidence=s.confidence,
                ai_confidence=s.ai_confidence,
                verification_basis=s.verification_basis.value if s.verification_basis else None,
                transparency_flags=s.transparency_flags,
                observation_count=len(s.observation_ids),
                created_at=s.created_at,
                updated_at=s.updated_at,
                is_signed=s.security is not None,
                truth_hash=s.security.truth_hash if s.security else None,
            )
            for s in domain_states
        ]
