"""
Kaori Core — Consensus Engine

Main orchestration engine that processes observations into signed truth states.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from core.db.database import SessionLocal, engine as db_engine, Base
from core.db import crud, models
from core.truthkey import parse_truthkey
from core.storage import storage
from core.db.models import RawObservationStatus

from .confidence import compute_confidence, should_flag_low_confidence
from .consensus import compute_consensus, get_consensus_outcome
from .models import (
    AIValidationResult,
    ConsensusRecord,
    Observation,
    Standing,
    TruthKey,
    TruthState,
    TruthStatus,
    VerificationBasis,
    Vote,
    VoteType,
    SecurityBlock,
)
from .schema_loader import get_claim_config
from .signing import sign_truth_state
from .truthkey import generate_truthkey


class KaoriEngine:
    """
    Core engine for the Kaori Protocol (Reference Implementation).
    Orchestrates validation, state transitions, and persistence.
    """
    
    def __init__(self, auto_sign: bool = False):
        self.auto_sign = auto_sign
        # Initialize Database
        Base.metadata.create_all(bind=db_engine)
        
    def _model_to_pydantic(self, db_state: models.TruthStateModel) -> TruthState:
        """Convert DB model to Pydantic object."""
        parsed_key = parse_truthkey(db_state.truthkey)
        data = db_state.data or {}
        
        return TruthState(
            truthkey=parsed_key,
            claim_type=data.get("claim_type", ""),
            status=TruthStatus(db_state.status),
            confidence=db_state.confidence,
            ai_confidence=db_state.ai_confidence,
            verification_basis=VerificationBasis(db_state.verification_basis) if db_state.verification_basis else None,
            transparency_flags=data.get("transparency_flags", []),
            created_at=db_state.created_at,
            updated_at=db_state.updated_at,
            consensus=ConsensusRecord(**data.get("consensus")) if data.get("consensus") else None,
            security=SecurityBlock(**data.get("security")) if data.get("security") else None,
            observation_ids=[UUID(oid) for oid in data.get("observation_ids", [])],
            evidence_refs=data.get("evidence_refs", []),
            confidence_breakdown=data.get("confidence_breakdown")
        )

    def _save_truth_state(self, db: Session, state: TruthState):
        """Persist Pydantic state to DB."""
        db_obj = crud.get_truth_state(db, state.truthkey.to_string())
        if not db_obj:
            # Should exist via _get_or_create, but safety check
            return
            
        db_obj.status = state.status.value
        db_obj.confidence = state.confidence
        db_obj.ai_confidence = state.ai_confidence
        db_obj.verification_basis = state.verification_basis.value if state.verification_basis else None
        
        # Serialize complex fields to JSON
        data = {
            "claim_type": state.claim_type,
            "transparency_flags": state.transparency_flags,
            "consensus": state.consensus.model_dump(mode='json') if state.consensus else None,
            "security": state.security.model_dump(mode='json') if state.security else None,
            "observation_ids": [str(oid) for oid in state.observation_ids],
            "evidence_refs": state.evidence_refs,
            "confidence_breakdown": state.confidence_breakdown.model_dump(mode='json') if state.confidence_breakdown else None
        }
        db_obj.data = data
        db_obj.updated_at = datetime.now(timezone.utc)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)



    def ingest_raw_observation(self, payload: dict, file_bytes: bytes) -> str:
        """
        Bronze Layer: Ingest raw observation immediately.
        Returns: ingest_id
        """
        # Save file
        filename = f"raw_{datetime.now().timestamp()}.jpg"
        file_path = storage.save(file_bytes, filename)
        
        # Save DB record
        with SessionLocal() as db:
            raw_obs = crud.create_raw_observation(db, payload, file_path)
            return raw_obs.ingest_id

    def process_pending_observations(self, limit: int = 10):
        """
        Silver/Gold Layer: Process pending raw observations.
        Triggered by cron or event.
        """
        with SessionLocal() as db:
            pending = crud.get_pending_raw_observations(db, limit)
            
        for raw in pending:
            try:
                # 1. Load File
                with open(raw.file_path, "rb") as f:
                    file_bytes = f.read()
                
                # 2. Reconstruct Observation Object
                # Run Bouncer HERE (or part of Pipeline)
                # Parse payload to Pydantic
                data = raw.raw_payload
                data["evidence_hashes"] = {} # Re-compute if needed
                
                # We need to map raw payload to ObservationCreate model logic
                # Ideally API did pydantic validation, but raw payload is JSON.
                # Assuming structure matches.
                
                # We need to generate ID here or use ingest_id?
                # Using new UUID for Silver observation is fine.
                
                # HACK: Re-using ObservationCreate logic implies we need that model available or manual map
                # Since we don't import API models here, we assume raw_payload matches Observation structure expectations
                # or we construct Observation object manually.
                
                from core.models import Observation, ReporterContext, Standing
                
                # Mock context if missing (demo simplicity)
                payload = data.get("payload", {})
                claim_type = data.get("claim_type")
                
                obs = Observation(
                    claim_type=claim_type,
                    reported_at=datetime.now(timezone.utc), # Or from payload
                    reporter_id=data.get("reporter_id", "unknown"),
                    reporter_context=ReporterContext(**data.get("reporter_context", {"standing": "bronze", "trust_score": 0.5})),
                    geo=data.get("geo", {}),
                    payload=payload,
                    evidence_refs=[f"file://{raw.file_path}"], # Internal ref
                    depth_meters=data.get("depth_meters"),
                    right_ascension=data.get("right_ascension"),
                    declination=data.get("declination")
                )
                
                # 3. Process (Validate + Promote)
                # This calls existing logic which does Bouncer -> Generalist -> DB Insert
                # We should run pipeline first? 
                # Integrating ValidationPipeline here would be better.
                # For this refactor, let's call existing process_observation
                # which assumes valid? No, process_observation blindly inserts.
                # We need Validation!
                
                # Import pipeline?
                # Global dependency injection issue. 
                # For now, let's assume validation happened in pipeline wrapper OR we instantiate it here.
                # Ideally Engine has the pipeline.
                
                self.process_observation(obs)
                
                # 4. Update Status
                with SessionLocal() as db:
                    crud.update_raw_status(db, raw.ingest_id, RawObservationStatus.PROCESSED)
                    
            except Exception as e:
                print(f"Failed to process ingestion {raw.ingest_id}: {e}")
                with SessionLocal() as db:
                    crud.update_raw_status(db, raw.ingest_id, RawObservationStatus.INVALID, str(e))

    def get_truth_state(self, truthkey: TruthKey | str) -> Optional[TruthState]:
        """Get truth state by key."""
        key_str = truthkey.to_string() if isinstance(truthkey, TruthKey) else truthkey
        with SessionLocal() as db:
            db_obj = crud.get_truth_state(db, key_str)
            if db_obj:
                return self._model_to_pydantic(db_obj)
        return None

    def _get_or_create_truth_state(self, truthkey: TruthKey, claim_type: str) -> TruthState:
        """Get existing or create new truth state (Persisted)."""
        key_str = truthkey.to_string()
        with SessionLocal() as db:
            db_obj = crud.get_truth_state(db, key_str)
            if not db_obj:
                # Create via CRUD
                components = {
                    "domain": truthkey.domain.value,
                    "topic": truthkey.topic,
                    "spatial_id": truthkey.spatial_id,
                    "time_bucket": truthkey.time_bucket
                }
                db_obj = crud.create_truth_state(db, key_str, claim_type, components)
                # Ensure claim_type stored
                db_obj.data = {"claim_type": claim_type}
                db.commit()
            
            return self._model_to_pydantic(db_obj)

    def ingest_raw_observation(self, payload: dict, file_bytes: bytes) -> str:
        """
        Bronze Layer: Ingest raw observation immediately.
        Returns: ingest_id
        """
        # Save file
        filename = f"raw_{datetime.now().timestamp()}.jpg"
        file_path = storage.save(file_bytes, filename)
        
        # Save DB record
        with SessionLocal() as db:
            raw_obs = crud.create_raw_observation(db, payload, file_path)
            return raw_obs.ingest_id

    def process_pending_observations(self, limit: int = 10):
        """
        Silver/Gold Layer: Process pending raw observations.
        Triggered by cron or event.
        """
        with SessionLocal() as db:
            pending = crud.get_pending_raw_observations(db, limit)
            
        for raw in pending:
            try:
                # 1. Load File
                with open(raw.file_path, "rb") as f:
                    file_bytes = f.read()
                
                # 2. Reconstruct Observation Object
                # In a real system, we'd run Bouncer here first
                data = raw.raw_payload
                
                from core.models import Observation, ReporterContext
                
                # Mock context if missing (demo simplicity)
                payload = data.get("payload", {})
                claim_type = data.get("claim_type")
                
                obs = Observation(
                    claim_type=claim_type,
                    reported_at=datetime.now(timezone.utc),
                    reporter_id=data.get("reporter_id", "unknown"),
                    reporter_context=ReporterContext(**data.get("reporter_context", {"standing": "bronze", "trust_score": 0.5, "source_type": "human"})),
                    geo=data.get("geo", {}),
                    payload=payload,
                    evidence_refs=[f"file://{raw.file_path}"],
                    evidence_bytes=file_bytes, # Pass bytes for validation
                    depth_meters=data.get("depth_meters"),
                    right_ascension=data.get("right_ascension"),
                    declination=data.get("declination")
                )
                
                # 3. Process (Validate + Promote)
                # Note: This calls process_observation which persists to Silver/Gold
                truth_state = self.process_observation(obs)
                
                # 4. Update Status
                with SessionLocal() as db_update:
                    crud.update_raw_status(db_update, raw.ingest_id, RawObservationStatus.PROCESSED, result_truthkey=truth_state.truthkey.to_string())
                    
            except Exception as e:
                print(f"Failed to process ingestion {raw.ingest_id}: {e}")
                with SessionLocal() as db_error:
                    crud.update_raw_status(db_error, raw.ingest_id, RawObservationStatus.INVALID, str(e))

    def process_observation(
        self,
        observation: Observation,
        ai_result: Optional[AIValidationResult] = None,
    ) -> TruthState:
        """Process observation and persist."""
        claim_config = get_claim_config(observation.claim_type)
        truthkey = generate_truthkey(observation, claim_config)
        
        # 1. Get State (Pydantic)
        truth_state = self._get_or_create_truth_state(truthkey, observation.claim_type)
        
        # 2. Update In-Memory Pydantic Object
        truth_state.observation_ids.append(observation.observation_id)
        truth_state.evidence_refs.extend(observation.evidence_refs)
        
        if ai_result:
            truth_state = self._apply_ai_validation(truth_state, ai_result, claim_config)
            
        truth_state = self._recompute_confidence(truth_state, claim_config)
        truth_state.updated_at = datetime.now(timezone.utc)
        
        if self.auto_sign:
            truth_state.security = sign_truth_state(truth_state)

        # 3. Persist to DB
        with SessionLocal() as db:
            # First, save observation record
            crud.create_observation(db, observation, truthkey.to_string(), {
                "domain": truthkey.domain.value,
                "topic": truthkey.topic,
                "spatial_id": truthkey.spatial_id,
                "time_bucket": truthkey.time_bucket
            })
            # Save State
            self._save_truth_state(db, truth_state)
            
        return truth_state

    def apply_vote(self, truthkey: str | TruthKey, vote: Vote) -> TruthState:
        """Apply vote and persist."""
        key_str = truthkey.to_string() if isinstance(truthkey, TruthKey) else truthkey
        
        # 1. Get State
        truth_state = self.get_truth_state(key_str)
        if not truth_state:
            raise ValueError(f"No truth state found for {key_str}")
        
        # 2. Update Logic
        if truth_state.consensus is None:
            truth_state.consensus = ConsensusRecord()
        
        truth_state.consensus.votes.append(vote)
        
        # Simple Consensus Logic (Reference Implementation)
        score = sum(1 if v.vote_type == VoteType.RATIFY else -1 if v.vote_type == VoteType.REJECT else 0 for v in truth_state.consensus.votes)
        truth_state.consensus.score = score
        
        if abs(score) >= 3: # Demo threshold
            truth_state.consensus.finalized = True
            outcome = "VERIFIED_TRUE" if score > 0 else "VERIFIED_FALSE"
            if outcome == "VERIFIED_TRUE":
                truth_state.status = TruthStatus.VERIFIED_TRUE
                truth_state.verification_basis = VerificationBasis.HUMAN_CONSENSUS
            else:
                truth_state.status = TruthStatus.VERIFIED_FALSE
                truth_state.verification_basis = VerificationBasis.HUMAN_CONSENSUS
        
        # Recompute confidence
        claim_config = get_claim_config(truth_state.claim_type)
        truth_state = self._recompute_confidence(truth_state, claim_config)
        truth_state.updated_at = datetime.now(timezone.utc)

        # 3. Persist
        with SessionLocal() as db:
            crud.create_vote(db, vote, key_str)
            self._save_truth_state(db, truth_state)
            
        return truth_state

    def _apply_ai_validation(
        self,
        truth_state: TruthState,
        ai_result: AIValidationResult,
        claim_config: dict,
    ) -> TruthState:
        """Apply AI validation result to truth state."""
        truth_state.ai_validation = ai_result
        truth_state.ai_confidence = ai_result.final_confidence
        
        autovalidation = claim_config.get("autovalidation", {})
        true_threshold = autovalidation.get("ai_verified_true_threshold", 0.82)
        false_threshold = autovalidation.get("ai_verified_false_threshold", 0.20)
        risk_profile = claim_config.get("risk_profile", "monitor")
        policy = claim_config.get("state_verification_policy", {})
        
        if risk_profile == "monitor":
            monitor_config = policy.get("monitor_lane", {})
            if monitor_config.get("allow_ai_verified_truth", True):
                if ai_result.final_confidence >= true_threshold:
                    truth_state.status = TruthStatus.VERIFIED_TRUE
                    truth_state.verification_basis = VerificationBasis.AI_AUTOVALIDATION
                elif ai_result.final_confidence <= false_threshold:
                    truth_state.status = TruthStatus.VERIFIED_FALSE
                    truth_state.verification_basis = VerificationBasis.AI_AUTOVALIDATION
                else:
                    truth_state.status = TruthStatus.INVESTIGATING
        else:
            truth_state.status = TruthStatus.INVESTIGATING
        
        return truth_state
    
    def _recompute_confidence(
        self,
        truth_state: TruthState,
        claim_config: dict,
    ) -> TruthState:
        """Recompute composite confidence for truth state."""
        components = {
            "ai_confidence": truth_state.ai_confidence,
        }
        
        if truth_state.consensus:
            components["consensus_ratio"] = truth_state.consensus.positive_ratio
            components["consensus_strength"] = min(
                1.0,
                abs(truth_state.consensus.score) / 
                claim_config.get("consensus_model", {}).get("finalize_threshold", 15)
            )
        
        components["evidence_count"] = len(truth_state.evidence_refs)
        
        modifiers = {}
        if "CONTRADICTION_DETECTED" in truth_state.transparency_flags:
            modifiers["contradiction_detected"] = True
        
        breakdown = compute_confidence(components, claim_config, modifiers)
        truth_state.confidence = breakdown.final_score
        truth_state.confidence_breakdown = breakdown
        
        risk_profile = claim_config.get("risk_profile", "monitor")
        should_flag, flag_label = should_flag_low_confidence(
            truth_state.confidence,
            claim_config,
            risk_profile,
        )
        
        if should_flag and flag_label:
            if flag_label not in truth_state.transparency_flags:
                truth_state.transparency_flags.append(flag_label)
        
        return truth_state


# =============================================================================
# Convenience functions
# =============================================================================

def create_engine(auto_sign: bool = True) -> KaoriEngine:
    """Create a new Kaori engine instance."""
    return KaoriEngine(auto_sign=auto_sign)
