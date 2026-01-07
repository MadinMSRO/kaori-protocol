"""
Kaori Core — Compatibility Shim for engine.py

This module provides a backwards-compatible wrapper around the new
pure Truth compiler and API orchestrator.

DEPRECATION WARNING: This shim will be removed in version 2.0.
Use kaori_truth.compile_truth_state() or kaori_api.TruthOrchestrator instead.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID

warnings.warn(
    "Importing from 'core.engine' is deprecated. "
    "Use 'kaori_truth.compile_truth_state()' for pure compilation or "
    "'kaori_api.TruthOrchestrator' for full orchestration. "
    "This compatibility shim will be removed in version 2.0.",
    DeprecationWarning,
    stacklevel=2,
)


class KaoriEngine:
    """
    DEPRECATED: Compatibility wrapper for the old KaoriEngine interface.
    
    New code should use:
    - kaori_truth.compile_truth_state() for pure compilation
    - kaori_api.TruthOrchestrator for full orchestration with DB
    
    This shim provides the old interface for gradual migration.
    """
    
    def __init__(
        self,
        schema_dir: str = "schemas",
        db_url: str = "sqlite:///kaori.db",
    ):
        warnings.warn(
            "KaoriEngine is deprecated. Use TruthOrchestrator from kaori_api instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        
        self.schema_dir = schema_dir
        self.db_url = db_url
        
        # Try to use new packages
        try:
            from kaori_flow import InMemoryTrustProvider
            from kaori_api import TruthOrchestrator
            
            self._trust_provider = InMemoryTrustProvider()
            self._orchestrator = TruthOrchestrator(
                trust_provider=self._trust_provider,
                schema_path=schema_dir,
            )
            self._use_new = True
        except ImportError:
            # Fall back to old implementation
            self._use_new = False
    
    def process_observation(
        self,
        observation_data: dict,
        compile_time: Optional[datetime] = None,
    ) -> Any:
        """
        DEPRECATED: Process an observation.
        
        New code should use TruthOrchestrator.compile_observations().
        """
        warnings.warn(
            "process_observation() is deprecated. "
            "Use TruthOrchestrator.compile_observations() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        
        if not self._use_new:
            raise NotImplementedError(
                "Legacy engine not available. Install kaori-truth and kaori-api packages."
            )
        
        # Convert old format to new format
        from kaori_truth import Observation, build_truthkey
        from kaori_truth.primitives.observation import ReporterContext, Standing
        
        # Build observation
        obs = Observation(
            claim_type=observation_data.get("claim_type", "earth.unknown.v1"),
            reported_at=observation_data.get("reported_at", datetime.now(timezone.utc)),
            reporter_id=observation_data.get("reporter_id", "unknown"),
            reporter_context=ReporterContext(
                standing=Standing.BRONZE,
                trust_score=0.5,
                source_type="human",
            ),
            geo=observation_data.get("geo", {"lat": 0, "lon": 0}),
            payload=observation_data.get("payload", {}),
        )
        
        # Build truth key
        truth_key = build_truthkey(
            claim_type_id=obs.claim_type,
            event_time=obs.reported_at,
            location=obs.geo,
        )
        
        # Compile
        compile_time = compile_time or datetime.now(timezone.utc)
        result = self._orchestrator.compile_observations(
            observations=[obs],
            truth_key=truth_key,
            claim_type_id=obs.claim_type,
            compile_time=compile_time,
        )
        
        return result
    
    def get_trust_result(
        self,
        agent_id: str,
        claim_type: str = "",
    ) -> Any:
        """
        DEPRECATED: Get trust result for an agent.
        
        New code should use TrustProvider.get_trust_snapshot().
        """
        warnings.warn(
            "get_trust_result() is deprecated. "
            "Use kaori_flow.TrustProvider.get_trust_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        
        if not self._use_new:
            raise NotImplementedError("Legacy engine not available.")
        
        return self._trust_provider.get_trust_snapshot(
            agent_ids=[agent_id],
            claim_type=claim_type,
            snapshot_time=datetime.now(timezone.utc),
        )
