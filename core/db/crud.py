from sqlalchemy.orm import Session
from .models import (
    TruthStateModel, ObservationModel, VoteModel, RawObservationModel, RawObservationStatus,
    AgentModel, NetworkEdgeModel, ProbeModel, SignalLogModel
)
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


# =============================================================================
# Agent CRUD
# =============================================================================

def get_agent(db: Session, agent_id: str):
    return db.query(AgentModel).filter(AgentModel.agent_id == agent_id).first()

def create_agent(db: Session, agent_id: str, agent_type: str = "individual", standing: str = "bronze"):
    db_obj = AgentModel(
        agent_id=agent_id,
        agent_type=agent_type,
        standing=standing,
        trust_score=0.5,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def update_agent_standing(db: Session, agent_id: str, standing: str, trust_score: float):
    db_obj = get_agent(db, agent_id)
    if db_obj:
        db_obj.standing = standing
        db_obj.trust_score = trust_score
        db_obj.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_obj)
    return db_obj

def get_or_create_agent(db: Session, agent_id: str) -> AgentModel:
    agent = get_agent(db, agent_id)
    if not agent:
        agent = create_agent(db, agent_id)
    return agent


# =============================================================================
# Mission CRUD
# =============================================================================

def create_probe(db: Session, probe_data: dict):
    db_obj = ProbeModel(**probe_data)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_probe(db: Session, probe_id: str):
    return db.query(ProbeModel).filter(ProbeModel.probe_id == probe_id).first()

def update_probe_status(db: Session, probe_id: str, status: str):
    db_obj = get_probe(db, probe_id)
    if db_obj:
        db_obj.status = status
        db_obj.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(db_obj)
    return db_obj

def get_probes_by_status(db: Session, status: str, limit: int = 50):
    return db.query(ProbeModel).filter(ProbeModel.status == status).limit(limit).all()

def get_squad_memberships(db: Session, agent_id: str) -> list[str]:
    """Get list of Squad IDs this agent is a MEMBER_OF."""
    edges = db.query(NetworkEdgeModel).filter(
        NetworkEdgeModel.source_agent_id == agent_id,
        NetworkEdgeModel.edge_type == "MEMBER_OF"  # Assuming string or enum value
    ).all()
    return [edge.target_agent_id for edge in edges]


# =============================================================================
# Network Edge CRUD
# =============================================================================

def create_network_edge(db: Session, edge_data: dict):
    db_obj = NetworkEdgeModel(**edge_data)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_edges_for_agent(db: Session, agent_id: str):
    return db.query(NetworkEdgeModel).filter(
        (NetworkEdgeModel.source_agent_id == agent_id) | 
        (NetworkEdgeModel.target_agent_id == agent_id)
    ).all()


# =============================================================================
# Signal Log CRUD
# =============================================================================

def log_signal(db: Session, signal_data: dict):
    db_obj = SignalLogModel(**signal_data)
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_signals_for_truthkey(db: Session, truthkey: str, limit: int = 50):
    return db.query(SignalLogModel).filter(SignalLogModel.truthkey == truthkey).limit(limit).all()
