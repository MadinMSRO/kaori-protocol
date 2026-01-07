"""
Kaori API — Probes Endpoints (Flow Primitive)

Probe discovery and management via unified Signal triggers.
All probe creation flows through the Signal Processor.
"""
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from core.signals import Signal, SignalType
from flow.engine.signal_processor import SignalProcessor

from .models import (
    SignalTriggerRequest,
    ProbeApprovalRequest,
    ProbeResponse,
    ProbeListResponse,
)

router = APIRouter()
processor = SignalProcessor()  # Instantiate processor


def _probe_to_response(probe) -> ProbeResponse:
    """Convert core.models.Probe to API response."""
    # Convert active_signals UUIDs to list if needed
    active_signals = probe.active_signals
    if active_signals and isinstance(active_signals[0], str):
        active_signals = [UUID(s) for s in active_signals]
        
    return ProbeResponse(
        probe_id=probe.probe_id,
        probe_key=probe.probe_key,
        claim_type=probe.claim_type,
        status=probe.status.value if hasattr(probe.status, 'value') else probe.status,
        scope=probe.scope,
        active_signals=active_signals,
        requirements=probe.requirements,
        created_at=probe.created_at,
        updated_at=probe.updated_at,
        expires_at=probe.expires_at
    )


@router.post("/probes/trigger", response_model=ProbeResponse, status_code=201)
async def submit_trigger(data: SignalTriggerRequest):
    """
    Submit a trigger signal to create a Probe Proposal.
    
    This is the unified entry point for probe creation:
    - MANUAL_TRIGGER: Human intent (Admin clicks "Create Probe")
    - AUTOMATED_TRIGGER: IoT/Sensor alert
    - SCHEDULED_TRIGGER: Time-based cron job
    """
    # Convert API request to Signal
    signal = Signal(
        type=SignalType(data.type),
        source_id="api_user",  # In prod: extract from JWT
        truthkey=data.truthkey,
        data={
            "claim_type": data.claim_type,
            "scope": data.scope,
            "requirements": data.requirements,
            "source_standing": data.source_standing,
        }
    )
    
    # Process through the Signal Processor (persists to DB)
    probe = processor.process_signal(signal)
    
    return _probe_to_response(probe)


from core.db.database import SessionLocal
from core.db.models import ProbeModel
from core.models import ProbeStatus

@router.post("/probes/{probe_id}/approve", response_model=ProbeResponse)
async def approve_probe(probe_id: UUID, data: ProbeApprovalRequest):
    """
    Approve a PROPOSED probe (Human-in-the-Loop Gate).
    
    Only probes in PROPOSED status can be approved.
    Requires authority standing (not enforced in demo).
    """
    with SessionLocal() as db:
        probe_model = db.query(ProbeModel).filter(ProbeModel.probe_id == str(probe_id)).first()
        if not probe_model:
            raise HTTPException(status_code=404, detail="Probe not found")
            
        if probe_model.status != ProbeStatus.PROPOSED.value:
            raise HTTPException(status_code=400, detail=f"Cannot approve probe in status {probe_model.status}")
            
        # Update status
        probe_model.status = ProbeStatus.ACTIVE.value
        probe_model.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(probe_model)
        
        # Convert to Pydantic for response
        return processor._model_to_pydantic(probe_model)


@router.get("/probes", response_model=ProbeListResponse)
async def list_probes(
    status: str = Query(default=None, pattern="^(PROPOSED|ACTIVE|ASSIGNED|IN_PROGRESS|COMPLETED|EXPIRED|CANCELLED)?$"),
    claim_type: str = None,
    limit: int = Query(default=20, le=100),
):
    """
    List probes with optional filtering.
    """
    with SessionLocal() as db:
        query = db.query(ProbeModel)
        
        if status:
            query = query.filter(ProbeModel.status == status)
        if claim_type:
            query = query.filter(ProbeModel.claim_type == claim_type)
            
        total = query.count()
        probes_models = query.order_by(ProbeModel.updated_at.desc()).limit(limit).all()
        
        # Convert to response format
        probes = [processor._model_to_pydantic(p) for p in probes_models]
        
        # Convert to API response format (handling UUIDs etc via helper if needed, 
        # but _probe_to_response does it nicely)
        response_probes = [_probe_to_response(p) for p in probes]
        
        return ProbeListResponse(probes=response_probes, total=total)


@router.get("/probes/{probe_id}", response_model=ProbeResponse)
async def get_probe(probe_id: UUID):
    """
    Get probe details by ID.
    """
    with SessionLocal() as db:
        probe_model = db.query(ProbeModel).filter(ProbeModel.probe_id == str(probe_id)).first()
        if not probe_model:
            raise HTTPException(status_code=404, detail=f"Probe not found: {probe_id}")
            
        probe = processor._model_to_pydantic(probe_model)
        return _probe_to_response(probe)
