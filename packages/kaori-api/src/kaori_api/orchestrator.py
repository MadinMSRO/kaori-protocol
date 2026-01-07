"""
Kaori API — Orchestrator

The orchestrator is the ONLY place that:
1. Reads from DB (observations, claimtypes)
2. Calls Flow TrustProvider to get TrustSnapshots
3. Calls Truth compiler
4. Persists TruthState into DB

This keeps the Truth compiler pure.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

# Import from Truth (pure)
from kaori_truth import (
    compile_truth_state,
    TruthState,
    Observation,
    ClaimType,
    load_claimtype_yaml,
)
from kaori_truth.signing import sign_truth_state

# Import from Flow
from kaori_flow import TrustProvider, create_trust_snapshot
from kaori_flow.primitives import Agent

# Import from DB (this is the only place Truth/Flow touches DB)
# from kaori_db import ...  # Would be imported in production


class TruthOrchestrator:
    """
    Orchestrator for truth compilation.
    
    This class bridges the pure Truth compiler with:
    - Database (for observations, claimtypes, persistence)
    - Flow (for trust snapshots)
    
    The Truth compiler itself remains pure.
    """
    
    def __init__(
        self,
        trust_provider: TrustProvider,
        schema_path: str = "schemas",
    ):
        """
        Initialize orchestrator.
        
        Args:
            trust_provider: TrustProvider implementation
            schema_path: Path to ClaimType YAML schemas
        """
        self.trust_provider = trust_provider
        self.schema_path = schema_path
        self._claimtype_cache: dict[str, ClaimType] = {}
    
    def compile_observations(
        self,
        observations: List[Observation],
        truth_key: str,
        claim_type_id: str,
        compile_time: Optional[datetime] = None,
        *,
        ai_scores: Optional[List[float]] = None,
        votes: Optional[List[dict]] = None,
        sign: bool = True,
    ) -> TruthState:
        """
        Compile observations into a signed TruthState.
        
        This method:
        1. Loads ClaimType config
        2. Gets TrustSnapshot from Flow
        3. Calls pure Truth compiler
        4. Optionally signs the result
        
        Args:
            observations: List of observations to compile
            truth_key: Canonical TruthKey string
            claim_type_id: Claim type ID (e.g., "earth.flood.v1")
            compile_time: Explicit compile time (uses current UTC if None)
            ai_scores: Optional AI confidence scores
            votes: Optional vote records
            sign: Whether to sign the TruthState
            
        Returns:
            Compiled (and optionally signed) TruthState
        """
        # 1. Load ClaimType
        claim_type = self._get_claim_type(claim_type_id)
        
        # 2. Get TrustSnapshot from Flow
        # Gather all reporter IDs
        agent_ids = list(set(obs.reporter_id for obs in observations))
        
        # Use explicit compile_time or current UTC
        if compile_time is None:
            compile_time = datetime.now(timezone.utc)
        
        trust_snapshot = self.trust_provider.get_trust_snapshot(
            agent_ids=agent_ids,
            claim_type=claim_type_id,
            snapshot_time=compile_time,
        )
        
        # 3. Call pure Truth compiler
        truth_state = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=observations,
            trust_snapshot=trust_snapshot,
            policy_version=claim_type.policy_version,
            compile_time=compile_time,
            ai_scores=ai_scores,
            votes=votes,
        )
        
        # 4. Sign if requested
        if sign:
            truth_state = sign_truth_state(truth_state, compile_time)
        
        return truth_state
    
    def _get_claim_type(self, claim_type_id: str) -> ClaimType:
        """Load ClaimType from cache or file."""
        if claim_type_id not in self._claimtype_cache:
            # Parse claim type ID to path
            parts = claim_type_id.split('.')
            if len(parts) >= 3:
                domain = parts[0]
                topic = parts[1]
                version = parts[2]
                path = f"{self.schema_path}/{domain}/{topic}_{version}.yaml"
            else:
                path = f"{self.schema_path}/{claim_type_id}.yaml"
            
            try:
                self._claimtype_cache[claim_type_id] = load_claimtype_yaml(path)
            except FileNotFoundError:
                # Create default ClaimType
                from kaori_truth.primitives.claimtype import ClaimType
                self._claimtype_cache[claim_type_id] = ClaimType(
                    id=claim_type_id,
                    version=1,
                    domain=parts[0] if parts else "earth",
                    topic=parts[1] if len(parts) > 1 else "unknown",
                )
        
        return self._claimtype_cache[claim_type_id]


class DatabaseOrchestrator(TruthOrchestrator):
    """
    Full orchestrator with database integration.
    
    This is what production API uses.
    """
    
    def __init__(
        self,
        trust_provider: TrustProvider,
        db_session,  # SQLAlchemy session
        schema_path: str = "schemas",
    ):
        super().__init__(trust_provider, schema_path)
        self.db = db_session
    
    def process_observation_from_db(
        self,
        observation_id: str,
        compile_time: Optional[datetime] = None,
    ) -> TruthState:
        """
        Load observation from DB and compile.
        
        Args:
            observation_id: UUID of observation
            compile_time: Explicit compile time
            
        Returns:
            Compiled TruthState
        """
        # Would load observation from DB
        # observation = self.db.query(ObservationModel).filter_by(id=observation_id).first()
        # Convert to Pydantic and compile
        raise NotImplementedError("DB integration not yet implemented")
    
    def persist_truth_state(self, truth_state: TruthState) -> None:
        """
        Persist TruthState to database.
        
        Args:
            truth_state: The TruthState to persist
        """
        # Would persist to DB
        # self.db.add(TruthStateModel.from_pydantic(truth_state))
        # self.db.commit()
        raise NotImplementedError("DB integration not yet implemented")
