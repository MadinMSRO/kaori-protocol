"""
Kaori API — Observations Endpoints

Submit and retrieve observations.
"""
from datetime import datetime, timezone
from uuid import UUID

import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status

from core import KaoriEngine, Observation, ReporterContext, Standing, load_claim_schema
from core.validators import ValidationPipeline
from core.db.database import SessionLocal
from core.db import crud
from .models import ObservationCreate, ObservationResponse
from .deps import engine as _engine, pipeline as _pipeline

router = APIRouter()

# Shared instances (imported from deps)
# _engine and _pipeline are now singletons


@router.post("/observations/submit", status_code=status.HTTP_202_ACCEPTED)
async def submit_observation(
    payload: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Submit an observation (ELT Flow).
    
    1. Ingests Raw Data (Bronze) -> Returns Ingest ID.
    2. Processing happens asynchronously (Silver/Gold).
    """
    try:
        # Parse payload
        try:
            payload_dict = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Read file bytes
        file_bytes = await file.read()
        
        # Ingest (Bronze Layer)
        ingest_id = _engine.ingest_raw_observation(payload_dict, file_bytes)
        
        # Trigger processing immediately (Sync for Demo)
        # In production this would be a background task or separate worker
        try:
            _engine.process_pending_observations()
        except Exception as e:
            # Don't fail the request if background processing fails
            print(f"Background processing warning: {e}")

        return {"ingest_id": ingest_id, "status": "RECEIVED", "message": "Queued for processing"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observations/submit/{ingest_id}")
def get_submission_status(ingest_id: str):
    """
    Check status of an async submission.
    """
    with SessionLocal() as db:
        raw = crud.get_raw_observation(db, ingest_id)
        if not raw:
            raise HTTPException(status_code=404, detail="Ingest ID not found")
        
        return {
            "ingest_id": raw.ingest_id,
            "status": raw.status,
            "error": raw.processing_error,
            "result_truthkey": raw.result_truthkey
        }


@router.post("/observations", response_model=ObservationResponse)
async def create_observation_json(data: ObservationCreate):
    """
    Submit observation (JSON-only, assumes evidence exists).
    Skips binary validation (Bouncer) as no file is provided.
    """
    # Create observation object
    observation = Observation(
        claim_type=data.claim_type,
        reported_at=datetime.now(timezone.utc),
        reporter_id=data.reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.BRONZE,  # Default for new reporters
            trust_score=0.5,
        ),
        geo=data.geo,
        payload=data.payload,
        evidence_refs=data.evidence_refs,
        depth_meters=data.depth_meters,
        right_ascension=data.right_ascension,
        declination=data.declination,
    )
    
    try:
        # Process through engine
        truth_state = _engine.process_observation(observation)
        
        return ObservationResponse(
            observation_id=observation.observation_id,
            claim_type=observation.claim_type,
            truthkey=truth_state.truthkey.to_string(),
            status=truth_state.status.value,
            created_at=truth_state.created_at,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"Unknown claim type: {data.claim_type}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observations/{observation_id}")
async def get_observation(observation_id: UUID):
    """
    Get observation by ID.
    
    Note: In production, this would query the database.
    Currently returns a placeholder.
    """
    # In production, query Bronze table
    raise HTTPException(
        status_code=501,
        detail="Database not implemented. Observation lookup requires persistence layer."
    )
