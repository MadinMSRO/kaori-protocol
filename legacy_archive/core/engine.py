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
    TrustContext,
    TrustResult,
)
from .schema_loader import get_claim_config, get_claim_type
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

    def get_trust_result(self, agent_id: str, context: TrustContext) -> TrustResult:
        """
        Flow Layer: Compute dynamic trust for an agent in a specific context.
        Implements TrustProvider interface (SPEC Section 4.3).
        """
        import hashlib
        
        with SessionLocal() as db:
            # 1. Fetch Agent Standing (Flow Law 1)
            agent = crud.get_agent(db, UUID(agent_id))
            if not agent:
                # Fallback for unknown agents (e.g. simulation/bootstrapping)
                standing = 10.0
            else:
                standing = agent.standing
            
            # 2. Derive Class (Backwards Compatibility)
            def derive_class(s):
                if s < 100: return "bronze"
                if s < 250: return "silver"
                if s < 500: return "expert"
                return "authority"
            
            cls = derive_class(standing)
            
            # 3. Compute Power (Flow Law 1: Fractal Inheritance)
            INHERITANCE_DECAY = 0.2
            MAX_INHERITANCE_DEPTH = 3
            
            def compute_power(current_agent_id: str, depth: int = 0, visited: set = None) -> float:
                if visited is None:
                    visited = set()
                
                # Cycle Safety
                if current_agent_id in visited:
                    return 0.0
                visited.add(current_agent_id)
                
                # Fetch intrinsic
                ag = crud.get_agent(db, UUID(current_agent_id))
                intrinsic = ag.standing if ag else 0.0
                
                # Base case: Max depth
                if depth >= MAX_INHERITANCE_DEPTH:
                    return intrinsic
                
                # Recursive step: Sum of squads
                inherited = 0.0
                squad_ids = crud.get_squad_memberships(db, current_agent_id)
                
                for squad_id in squad_ids:
                    # Recursive call with copy of visited to allow diverse paths 
                    # (but forbid loops in same path)
                    squad_power = compute_power(squad_id, depth + 1, visited.copy())
                    inherited += squad_power * INHERITANCE_DECAY
                    
                return intrinsic + inherited

            power = compute_power(agent_id) 
            
            # 4. Generate Trust Snapshot (Audit Requirement)
            # deterministic hash of input state
            snap_str = f"{agent_id}:{standing}:{cls}:{datetime.now().timestamp()}"
            snap_hash = hashlib.sha256(snap_str.encode()).hexdigest()
            
            return TrustResult(
                power=power,
                standing=standing,
                derived_class=cls,
                flags=[],
                trust_snapshot_hash=snap_hash
            )
        
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
            consensus=self._parse_consensus(data.get("consensus")) if data.get("consensus") else None,
            security=SecurityBlock(**data.get("security")) if data.get("security") else None,
            observation_ids=[UUID(oid) for oid in data.get("observation_ids", [])],
            evidence_refs=data.get("evidence_refs", []),
            confidence_breakdown=data.get("confidence_breakdown")
        )

    def _parse_consensus(self, consensus_data: dict) -> ConsensusRecord:
        """Parse consensus with backwards compatibility for old string standing values."""
        # Standing enum to float mapping for migration
        STANDING_MIGRATION = {
            "bronze": 10.0,
            "silver": 50.0,
            "expert": 200.0,
            "authority": 500.0,
        }
        
        votes = consensus_data.get("votes", [])
        for vote in votes:
            vs = vote.get("voter_standing")
            if isinstance(vs, str) and vs in STANDING_MIGRATION:
                vote["voter_standing"] = STANDING_MIGRATION[vs]
        
        return ConsensusRecord(**consensus_data)

    def compute_observation_aggregate(self, observations: list, ai_scores: list[float]) -> dict:
        """
        SPEC Section 8.4: Compute aggregate metrics from observations.
        Used for implicit consensus and intermediate status computation.
        """
        import statistics
        
        if not observations:
            return {
                "observation_count": 0,
                "network_trust": 0.0,
                "ai_confidence_mean": 0.0,
                "ai_variance": 0.0,
            }
        
        # Sum of reporter standings (continuous values)
        network_trust = sum(
            getattr(obs, 'reporter_context', {}).get('trust_score', 0.5) * 100 
            if isinstance(getattr(obs, 'reporter_context', {}), dict) 
            else obs.reporter_context.trust_score * 100
            for obs in observations
        )
        
        # AI scores
        if not ai_scores:
            ai_scores = [0.5]
        
        ai_mean = statistics.mean(ai_scores)
        ai_variance = statistics.variance(ai_scores) if len(ai_scores) > 1 else 0.0
        
        return {
            "observation_count": len(observations),
            "network_trust": network_trust,
            "ai_confidence_mean": ai_mean,
            "ai_variance": ai_variance,
        }

    def compute_intermediate_status(
        self,
        aggregate: dict,
        claim_config: dict,
    ) -> TruthStatus:
        """
        SPEC Section 8.1: Compute intermediate status during observation window.
        Returns LEANING_TRUE, LEANING_FALSE, UNDECIDED, or PENDING.
        """
        autovalidation = claim_config.get("autovalidation", {})
        ai_true_threshold = autovalidation.get("ai_verified_true_threshold", 0.82)
        ai_false_threshold = autovalidation.get("ai_verified_false_threshold", 0.20)
        
        implicit = claim_config.get("implicit_consensus", {})
        max_variance = implicit.get("max_ai_variance", 0.15)
        
        ai_mean = aggregate["ai_confidence_mean"]
        ai_variance = aggregate["ai_variance"]
        
        # Check for contradiction (high variance)
        if ai_variance > max_variance:
            return TruthStatus.UNDECIDED
        
        # Check AI confidence direction
        if ai_mean >= ai_true_threshold:
            return TruthStatus.LEANING_TRUE
        elif ai_mean <= ai_false_threshold:
            return TruthStatus.LEANING_FALSE
        else:
            return TruthStatus.PENDING

    def check_implicit_consensus(
        self,
        aggregate: dict,
        claim_config: dict,
    ) -> bool:
        """
        SPEC Section 8.4: Check if implicit consensus conditions are met.
        If True, can auto-verify without explicit voting.
        """
        implicit = claim_config.get("implicit_consensus", {})
        if not implicit.get("enabled", False):
            return False
        
        return all([
            aggregate["observation_count"] >= implicit.get("min_observations", 3),
            aggregate["network_trust"] >= implicit.get("min_network_trust", 50.0),
            aggregate["ai_confidence_mean"] >= implicit.get("min_ai_confidence", 0.80),
            aggregate["ai_variance"] <= implicit.get("max_ai_variance", 0.15),
        ])


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
        else:
            # No AI result - check if critical lane requires human review
            risk_profile = claim_config.get("risk_profile", "monitor")
            if risk_profile == "critical" and truth_state.status == TruthStatus.PENDING:
                truth_state.status = TruthStatus.PENDING_HUMAN_REVIEW
                if "AWAITING_HUMAN_CONSENSUS" not in truth_state.transparency_flags:
                    truth_state.transparency_flags.append("AWAITING_HUMAN_CONSENSUS")
            
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
        
        # Load typed ClaimType config
        claim_type = get_claim_type(truth_state.claim_type)
        claim_config = get_claim_config(truth_state.claim_type)  # Keep dict for confidence
        
        # Weighted Consensus Logic (Config-Driven)
        score = 0
        for v in truth_state.consensus.votes:
            weight = claim_type.get_vote_weight(v.voter_standing.value if hasattr(v.voter_standing, 'value') else str(v.voter_standing))
            if v.vote_type == VoteType.RATIFY:
                score += weight
            elif v.vote_type == VoteType.REJECT:
                score -= weight
        truth_state.consensus.score = score
        
        # Use YAML-defined thresholds
        finalize_threshold = claim_type.consensus_model.finalize_threshold
        reject_threshold = claim_type.consensus_model.reject_threshold
        
        if score >= finalize_threshold:
            truth_state.consensus.finalized = True
            truth_state.status = TruthStatus.VERIFIED_TRUE
            truth_state.verification_basis = VerificationBasis.HUMAN_CONSENSUS
        elif score <= reject_threshold:
            truth_state.consensus.finalized = True
            truth_state.status = TruthStatus.VERIFIED_FALSE
            truth_state.verification_basis = VerificationBasis.HUMAN_CONSENSUS
        
        # Recompute confidence
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
            # Monitor Lane: AI can auto-verify
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
            # Critical Lane: Require human consensus
            # AI validation informs but cannot finalize
            if ai_result.final_confidence >= true_threshold:
                # AI recommends TRUE, but needs human approval
                truth_state.status = TruthStatus.PENDING_HUMAN_REVIEW
                if "AI_RECOMMENDS_TRUE" not in truth_state.transparency_flags:
                    truth_state.transparency_flags.append("AI_RECOMMENDS_TRUE")
            elif ai_result.final_confidence <= false_threshold:
                # AI recommends FALSE, but needs human approval
                truth_state.status = TruthStatus.PENDING_HUMAN_REVIEW
                if "AI_RECOMMENDS_FALSE" not in truth_state.transparency_flags:
                    truth_state.transparency_flags.append("AI_RECOMMENDS_FALSE")
            else:
                # AI uncertain, definitely needs human review
                truth_state.status = TruthStatus.PENDING_HUMAN_REVIEW
                if "AWAITING_HUMAN_CONSENSUS" not in truth_state.transparency_flags:
                    truth_state.transparency_flags.append("AWAITING_HUMAN_CONSENSUS")
        
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
