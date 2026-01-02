from sqlalchemy.orm import Session
from .models import TruthStateModel, ObservationModel, VoteModel, RawObservationModel, RawObservationStatus
from datetime import datetime, timezone
import json
import uuid

def create_raw_observation(db: Session, raw_payload: dict, file_path: str) -> RawObservationModel:
    db_obj = RawObservationModel(
        ingest_id=str(uuid.uuid4()),
        status=RawObservationStatus.RECEIVED.value,
        raw_payload=raw_payload,
        file_path=file_path
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_pending_raw_observations(db: Session, limit: int = 100):
    return db.query(RawObservationModel).filter(
        RawObservationModel.status == RawObservationStatus.RECEIVED.value
    ).limit(limit).all()

def get_raw_observation(db: Session, ingest_id: str):
    return db.query(RawObservationModel).filter(RawObservationModel.ingest_id == ingest_id).first()

def update_raw_status(db: Session, ingest_id: str, status: RawObservationStatus, error: str = None, result_truthkey: str = None):
    db_obj = db.query(RawObservationModel).filter(RawObservationModel.ingest_id == ingest_id).first()
    if db_obj:
        db_obj.status = status.value
        db_obj.processing_error = error
        if result_truthkey:
            db_obj.result_truthkey = result_truthkey
        db.commit()
        db.refresh(db_obj)
    return db_obj

def get_truth_state(db: Session, truthkey: str):
    return db.query(TruthStateModel).filter(TruthStateModel.truthkey == truthkey).first()

def create_truth_state(db: Session, truthkey: str, claim_type: str, components: dict):
    db_obj = TruthStateModel(
        truthkey=truthkey,
        status="PENDING", # Default status
        domain=components.get("domain"),
        topic=components.get("topic"),
        spatial_id=components.get("spatial_id"),
        time_bucket=datetime.fromisoformat(components.get("time_bucket").replace("Z", "+00:00")) if components.get("time_bucket") else None,
        confidence=0.0,
        data=components.get("data", {}) # Pass data if provided (e.g. claim_type)
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def update_truth_state(db: Session, truthkey: str, status: str, confidence: float, data: dict, ai_confidence: float = 0.0, verification_basis: str = None):
    db_obj = get_truth_state(db, truthkey)
    if db_obj:
        db_obj.status = status
        db_obj.confidence = confidence
        db_obj.data = data # Store complex objects as JSON
        db_obj.ai_confidence = ai_confidence
        db_obj.verification_basis = verification_basis
        db.commit()
        db.refresh(db_obj)
    return db_obj

def create_observation(db: Session, obs_data: dict, truthkey: str, payload: dict):
    # Flatten components for columns
    # obs_data comes from Observation Pydantic model
    db_obj = ObservationModel(
        observation_id=str(obs_data.measurement_id) if hasattr(obs_data, 'measurement_id') else str(obs_data.observation_id),
        truthkey=truthkey,
        domain=payload.get("domain", "unknown"),
        topic=payload.get("topic", "unknown"),
        spatial_id=payload.get("spatial_id", "unknown"),
        time_bucket=datetime.fromisoformat(payload.get("time_bucket").replace("Z", "+00:00")) if payload.get("time_bucket") else None,
        claim_type=obs_data.claim_type,
        reporter_id=obs_data.reporter_id,
        reported_at=obs_data.reported_at,
        data=obs_data.model_dump(mode='json') # Store full object
    )
    db.add(db_obj)
    db.commit()
    return db_obj

def create_vote(db: Session, vote_data, truthkey: str):
    db_obj = VoteModel(
        vote_id=str(vote_data.vote_id),
        truthkey=truthkey,
        voter_id=vote_data.voter_id,
        voter_type=getattr(vote_data, 'voter_type', 'HUMAN'),
        vote_type=vote_data.vote_type.value if hasattr(vote_data.vote_type, 'value') else vote_data.vote_type,
        weight=1.0, # Implement weighting logic later
        voted_at=vote_data.voted_at,
        comment=vote_data.comment,
        data={"voter_standing": str(vote_data.voter_standing)}
    )
    db.add(db_obj)
    db.commit()
    return db_obj

def get_recent_truth_states(db: Session, limit: int = 50):
    return db.query(TruthStateModel).order_by(TruthStateModel.updated_at.desc()).limit(limit).all()
