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
