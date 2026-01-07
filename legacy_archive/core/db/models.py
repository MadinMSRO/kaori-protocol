from sqlalchemy import Column, String, Float, DateTime, JSON, ForeignKey, Integer, Index, Enum as SQLEnum
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime, timezone
import enum

class RawObservationStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    INVALID = "INVALID"

class RawObservationModel(Base):
    __tablename__ = "raw_observations"
    
    ingest_id = Column(String, primary_key=True, index=True)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String, default=RawObservationStatus.RECEIVED.value, index=True)
    raw_payload = Column(JSON) # Stores payload, claim_type, reporter info
    file_path = Column(String) # Path to evidence file (Local or GCS URI)
    processing_error = Column(String, nullable=True)
    result_truthkey = Column(String, nullable=True)

class TruthStateModel(Base):
    __tablename__ = "truth_states"

    truthkey = Column(String, primary_key=True, index=True)
    
    # Normalized components for fast lookup
    domain = Column(String, index=True)      # e.g. "earth"
    topic = Column(String, index=True)       # e.g. "flood"
    spatial_id = Column(String, index=True)  # e.g. "8861..."
    time_bucket = Column(DateTime, index=True)
    
    status = Column(String)
    confidence = Column(Float, default=0.0)
    ai_confidence = Column(Float, default=0.0)
    verification_basis = Column(String, nullable=True)
    
    # JSON data for complex structures (consensus, flags, security)
    data = Column(JSON, default={})
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relations
    observations = relationship("ObservationModel", back_populates="truth_state")
    votes = relationship("VoteModel", back_populates="truth_state")

class ObservationModel(Base):
    __tablename__ = "observations"

    observation_id = Column(String, primary_key=True, index=True)
    truthkey = Column(String, ForeignKey("truth_states.truthkey"), index=True)
    
    # Normalized components (New Request)
    domain = Column(String, index=True)
    topic = Column(String, index=True)
    spatial_id = Column(String, index=True)
    time_bucket = Column(DateTime, index=True)
    
    claim_type = Column(String)
    reporter_id = Column(String, index=True)
    reported_at = Column(DateTime)
    
    # JSON data for payload, geo, evidence refs
    data = Column(JSON)
    
    truth_state = relationship("TruthStateModel", back_populates="observations")

class VoteModel(Base):
    __tablename__ = "votes"

    vote_id = Column(String, primary_key=True, index=True)
    truthkey = Column(String, ForeignKey("truth_states.truthkey"), index=True)
    
    voter_id = Column(String, index=True)
    voter_type = Column(String, default="HUMAN") # HUMAN, AI_GENERALIST, AI_SPECIALIST
    vote_type = Column(String) # RATIFY, REJECT
    weight = Column(Float, default=1.0)
    
    voted_at = Column(DateTime)
    comment = Column(String, nullable=True)
    
    data = Column(JSON, default={})
    
    truth_state = relationship("TruthStateModel", back_populates="votes")


# =============================================================================
# Agent Model (FLOW_SPEC Section 2.1)
# =============================================================================

class AgentModel(Base):
    __tablename__ = "agents"
    
    agent_id = Column(String, primary_key=True, index=True)
    agent_type = Column(String, default="individual")  # individual, squad, sensor, official
    standing = Column(String, default="bronze", index=True)
    trust_score = Column(Float, default=0.5)
    
    # Per-domain qualifications
    qualifications = Column(JSON, default={})
    
    # Stats
    verified_observations = Column(Integer, default=0)
    correct_votes = Column(Integer, default=0)
    total_votes = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# =============================================================================
# Network Edge Model (FLOW_SPEC Section 2.2)
# =============================================================================

class NetworkEdgeModel(Base):
    __tablename__ = "network_edges"
    
    edge_id = Column(String, primary_key=True, index=True)
    edge_type = Column(String, index=True)  # VOUCH, MEMBER_OF, COLLABORATE, CONFLICT
    source_agent_id = Column(String, ForeignKey("agents.agent_id"), index=True)
    target_agent_id = Column(String, ForeignKey("agents.agent_id"), index=True)
    weight = Column(Float, default=1.0)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)  # CONFLICT edges never expire


# =============================================================================
# Probe Model (Flow Primitive)
# =============================================================================

class ProbeModel(Base):
    __tablename__ = "probes"
    
    probe_id = Column(String, primary_key=True, index=True)
    probe_key = Column(String, index=True, nullable=False)  # Deterministic Key
    claim_type = Column(String, index=True)
    status = Column(String, default="PROPOSED", index=True)
    
    # Scope
    scope = Column(JSON)  # { "spatial": ..., "temporal": ... }
    
    # Origin
    created_by_signal = Column(String, nullable=True)
    active_signals = Column(JSON, default=[])
    
    # Requirements
    requirements = Column(JSON, default={})
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)


# =============================================================================
# Signal Log Model (Audit Trail)
# =============================================================================

class SignalLogModel(Base):
    __tablename__ = "signal_log"
    
    signal_id = Column(String, primary_key=True, index=True)
    signal_type = Column(String, index=True)  # AUTOMATED_TRIGGER, MANUAL_TRIGGER, etc.
    source_id = Column(String, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    truthkey = Column(String, nullable=True, index=True)
    data = Column(JSON, default={})
