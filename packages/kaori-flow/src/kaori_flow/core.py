"""
Kaori Flow — Core Library

Main entry point for the Kaori Flow trust layer (FLOW_SPEC v4.0).
Implements the 7 Rules of Trust.

This is the core library for Kaori Protocol — not a production implementation.
Production implementations inject storage backends (PostgreSQL, BigQuery, Pub/Sub).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Protocol, runtime_checkable

from .policy import FlowPolicy
from .primitives.signal import Signal, SignalTypes
from .reducer import FlowReducer, ReducerState
from .store import SignalStore, InMemorySignalStore
from .trust import TrustComputer, TrustContext, TrustSnapshot


class FlowCore:
    """
    Core Flow engine implementing the 7 Rules of Trust.
    
    Public API:
        - emit(signal): Append signal to store
        - get_standing(agent_id): Get current standing for agent
        - get_trust_snapshot(agent_ids, context): Compute trust snapshot
    
    Integration:
        Production implementations inject storage backends at construction.
        The core logic (reducer, trust computation) is the same regardless.
    
    Example:
        # Development (in-memory)
        flow = FlowCore(policy=FlowPolicy.default())
        
        # Production (PostgreSQL)
        flow = FlowCore(
            store=PostgresSignalStore(connection),
            policy=FlowPolicy.load("flow_policy_v1.yaml")
        )
    """
    
    def __init__(
        self,
        store: Optional[SignalStore] = None,
        policy: Optional[FlowPolicy] = None,
    ):
        """
        Initialize FlowCore.
        
        Args:
            store: Signal store implementation. Defaults to InMemorySignalStore.
            policy: FlowPolicy configuration. Defaults to FlowPolicy.default().
        """
        self.store = store or InMemorySignalStore()
        self.policy = policy or FlowPolicy.default()
        self.reducer = FlowReducer(self.policy)
        self.trust_computer = TrustComputer(self.policy)
        
        # Cache for standings (optimization, can be invalidated)
        self._standings_cache: Optional[Dict[str, float]] = None
        self._cache_valid = False
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def emit(self, signal: Signal) -> None:
        """
        Emit a signal to the store.
        
        Rule 1: Trust is Event-Sourced — all changes go through signals.
        """
        self.store.append(signal)
        self._cache_valid = False  # Invalidate cache
    
    def get_standing(self, agent_id: str) -> float:
        """
        Get current standing for an agent.
        
        Rule 3: Standing is the only persistent scalar.
        """
        standings = self._get_all_standings()
        return standings.get(
            agent_id, 
            self.policy.get_initial_standing("observer")
        )
    
    def get_trust_snapshot(
        self,
        agent_ids: List[str],
        context: Optional[TrustContext] = None,
    ) -> TrustSnapshot:
        """
        Compute trust snapshot for truth compilation.
        
        Rule 4: Standing is global, trust is local.
        
        Args:
            agent_ids: List of agent IDs to include in snapshot.
            context: Trust context (claimtype, probe, collaborators).
        
        Returns:
            TrustSnapshot with effective trust for each agent.
        """
        context = context or TrustContext()
        standings = self._get_all_standings()
        signals = self.store.get_all()
        
        # Get standings for requested agents
        agent_standings = {
            aid: standings.get(aid, self.policy.get_initial_standing("observer"))
            for aid in agent_ids
        }
        
        # Get policy standing
        policy_standing = standings.get(self.policy.agent_id, 500.0)
        
        return self.trust_computer.build_trust_snapshot(
            agent_standings=agent_standings,
            context=context,
            signals=signals,
            policy_standing=policy_standing,
        )
    
    def get_all_standings(self) -> Dict[str, float]:
        """Get all agent standings."""
        return self._get_all_standings().copy()
    
    # =========================================================================
    # Helper Methods for Signal Emission
    # =========================================================================
    
    def register_agent(
        self,
        agent_id: str,
        role: str = "observer",
        agent_type: str = "individual",
    ) -> Signal:
        """
        Emit AGENT_REGISTERED signal.
        
        Convenience method for bootstrapping agents.
        """
        signal = Signal(
            signal_type=SignalTypes.AGENT_REGISTERED,
            time=datetime.utcnow(),
            agent_id="system:flow",
            object_id=agent_id,
            payload={
                "role": role,
                "agent_type": agent_type,
            },
            policy_version=self.policy.version,
        )
        self.emit(signal)
        return signal
    
    def register_policy(self, policy: FlowPolicy) -> Signal:
        """
        Emit POLICY_REGISTERED signal.
        
        Rule 7: FlowPolicy is itself an agent.
        """
        signal = Signal(
            signal_type=SignalTypes.POLICY_REGISTERED,
            time=datetime.utcnow(),
            agent_id="system:flow",
            object_id=policy.agent_id,
            payload={
                "version": policy.version,
                "agent_type": "policy",
            },
            policy_version=policy.version,
        )
        self.emit(signal)
        return signal
    
    def submit_observation(
        self,
        observer_id: str,
        probe_id: str,
        payload: dict,
        claimtype_id: Optional[str] = None,
    ) -> Signal:
        """Emit OBSERVATION_SUBMITTED signal."""
        from .primitives.signal import SignalContext
        
        signal = Signal(
            signal_type=SignalTypes.OBSERVATION_SUBMITTED,
            time=datetime.utcnow(),
            agent_id=observer_id,
            object_id=probe_id,
            context=SignalContext(
                probe_id=probe_id,
                claimtype_id=claimtype_id,
            ) if claimtype_id else None,
            payload=payload,
            policy_version=self.policy.version,
        )
        self.emit(signal)
        return signal
    
    def emit_truthstate(
        self,
        truthkey: str,
        status: str,
        confidence: float,
        contributors: List[str],
        outcome: str = "correct",
        quality_score: float = 50.0,
    ) -> Signal:
        """
        Emit TRUTHSTATE_EMITTED signal.
        
        This updates standings for contributors based on outcome.
        """
        signal = Signal(
            signal_type=SignalTypes.TRUTHSTATE_EMITTED,
            time=datetime.utcnow(),
            agent_id="system:truth",
            object_id=truthkey,
            payload={
                "status": status,
                "confidence": confidence,
                "contributors": contributors,
                "outcome": outcome,
                "quality_score": quality_score,
                "policy_agent_id": self.policy.agent_id,
            },
            policy_version=self.policy.version,
        )
        self.emit(signal)
        return signal
    
    def endorse(self, endorser_id: str, endorsed_id: str) -> Signal:
        """
        Emit ENDORSEMENT signal (creates VOUCH edge).
        """
        signal = Signal(
            signal_type=SignalTypes.ENDORSEMENT,
            time=datetime.utcnow(),
            agent_id=endorser_id,
            object_id=endorsed_id,
            payload={},
            policy_version=self.policy.version,
        )
        self.emit(signal)
        return signal
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    def _get_all_standings(self) -> Dict[str, float]:
        """Get all standings, using cache if valid."""
        if self._cache_valid and self._standings_cache is not None:
            return self._standings_cache
        
        signals = self.store.get_all()
        state = self.reducer.reduce(signals)
        
        self._standings_cache = state.standings
        self._cache_valid = True
        
        return state.standings
    
    def invalidate_cache(self) -> None:
        """Invalidate standings cache."""
        self._cache_valid = False
        self._standings_cache = None
    
    def replay_at(self, timestamp: datetime) -> Dict[str, float]:
        """
        Replay signals up to a timestamp.
        
        Rule 1: Trust is replayable at any historical point.
        """
        signals = [s for s in self.store.get_all() if s.time <= timestamp]
        state = self.reducer.reduce(signals)
        return state.standings
