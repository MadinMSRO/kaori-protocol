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


@router.post("/probes/{probe_id}/approve", response_model=ProbeResponse)
async def approve_probe(probe_id: UUID, data: ProbeApprovalRequest):
    """
    Approve a PROPOSED probe (Human-in-the-Loop Gate).
    
    Only probes in PROPOSED status can be approved.
    Requires authority standing (not enforced in demo).
    """
    # Note: Approval logic needs to be implemented in processor or here
    # For now (Phase 1), implementation pending or we use direct DB update
    # Skipping for this refactor pass to focus on renaming
    raise HTTPException(status_code=501, detail="Manual approval endpoint pending implementation")


@router.get("/probes", response_model=ProbeListResponse)
async def list_probes(
    status: str = Query(default=None, pattern="^(PROPOSED|ACTIVE|ASSIGNED|IN_PROGRESS|COMPLETED|EXPIRED|CANCELLED)?$"),
    claim_type: str = None,
    limit: int = Query(default=20, le=100),
):
    """
    List probes with optional filtering.
    """
    # TODO: Implement list method in SignalProcessor or via direct DB query here
    # For now, returning empty list as placeholder until repo layer added
    return ProbeListResponse(probes=[], total=0) 


@router.get("/probes/{probe_id}", response_model=ProbeResponse)
async def get_probe(probe_id: UUID):
    """
    Get probe details by ID.
    """
    # TODO: Implement get method
    raise HTTPException(status_code=404, detail=f"Probe not found: {probe_id}")
