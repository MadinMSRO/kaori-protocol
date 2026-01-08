"""
Kaori Flow — Reducer

Event-sourced standing computation (FLOW_SPEC v4.0).
Rule 1: Trust is Event-Sourced.
Rule 5: Trust Updates are Deterministic and Nonlinear.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .policy import FlowPolicy
from .primitives.signal import Signal, SignalTypes


@dataclass
class ReducerState:
    """
    State maintained by the reducer.
    
    This is derived state — can always be recomputed from signals.
    """
    standings: Dict[str, float] = field(default_factory=dict)
    agent_roles: Dict[str, str] = field(default_factory=dict)  # agent_id -> role


class FlowReducer:
    """
    Deterministic state reducer for Flow (FLOW_SPEC v4.0 Section 5).
    
    Rule 1: Trust is derived from signals, not stored state.
    Rule 5: Updates are deterministic and nonlinear.
    
    The reducer is a pure function: same signals + same policy → same state.
    """
    
    def __init__(self, policy: FlowPolicy):
        self.policy = policy
    
    def reduce(self, signals: List[Signal]) -> ReducerState:
        """
        Reduce signal history to current state.
        
        This is a pure function: given the same signals, produces the same state.
        """
        state = ReducerState()
        
        # Process signals in chronological order
        for signal in sorted(signals, key=lambda s: s.time):
            self._apply_signal(state, signal)
        
        return state
    
    def reduce_for_agent(self, signals: List[Signal], agent_id: str) -> float:
        """
        Reduce signals to get standing for a specific agent.
        
        Optimization: Only process signals relevant to the agent.
        """
        state = self.reduce(signals)
        return state.standings.get(agent_id, self.policy.bounds.initial_by_role.get("observer", 200.0))
    
    def _apply_signal(self, state: ReducerState, signal: Signal) -> None:
        """Apply a single signal to state."""
        match signal.signal_type:
            case SignalTypes.AGENT_REGISTERED:
                self._handle_agent_registered(state, signal)
            case SignalTypes.POLICY_REGISTERED:
                self._handle_policy_registered(state, signal)
            case SignalTypes.TRUTHSTATE_EMITTED:
                self._handle_truthstate_emitted(state, signal)
            case SignalTypes.PENALTY_APPLIED:
                self._handle_penalty(state, signal)
            case SignalTypes.ENDORSEMENT:
                self._handle_endorsement(state, signal)
            # Other signal types don't directly affect standing
            case _:
                pass
    
    def _handle_agent_registered(self, state: ReducerState, signal: Signal) -> None:
        """Bootstrap standing when agent is registered."""
        agent_id = signal.object_id
        role = signal.payload.get("role", "observer")
        
        # Only set initial standing if not already set
        if agent_id not in state.standings:
            initial = self.policy.get_initial_standing(role)
            state.standings[agent_id] = initial
            state.agent_roles[agent_id] = role
    
    def _handle_policy_registered(self, state: ReducerState, signal: Signal) -> None:
        """Register policy as an agent."""
        policy_id = signal.object_id
        if policy_id not in state.standings:
            initial = self.policy.get_initial_standing("policy")
            state.standings[policy_id] = initial
            state.agent_roles[policy_id] = "policy"
    
    def _handle_truthstate_emitted(self, state: ReducerState, signal: Signal) -> None:
        """
        Update standings based on truth outcome.
        
        Rule 5: Nonlinear updates with penalty sharper than reward.
        """
        contributors = signal.payload.get("contributors", [])
        outcome = signal.payload.get("outcome", "unknown")
        quality_score = signal.payload.get("quality_score", 50.0)
        
        for agent_id in contributors:
            if agent_id not in state.standings:
                state.standings[agent_id] = self.policy.get_initial_standing("observer")
            
            current = state.standings[agent_id]
            
            if outcome == "correct":
                # Gain: ΔS = a * log(1 + q)
                delta = self.policy.standing_gain.coefficient * math.log(1 + quality_score)
            elif outcome == "incorrect":
                # Penalty: ΔS = -b * log(1 + q) * λ (sharper than gain)
                delta = -self.policy.penalty.coefficient * math.log(1 + quality_score) * self.policy.penalty.amplifier
            else:
                delta = 0.0
            
            # Apply delta and clamp to bounds
            new_standing = current + delta
            new_standing = max(self.policy.bounds.min, min(new_standing, self.policy.bounds.max))
            state.standings[agent_id] = new_standing
        
        # Update policy standing based on truth outcome quality
        policy_id = signal.payload.get("policy_agent_id")
        if policy_id and policy_id in state.standings:
            current = state.standings[policy_id]
            # Policy gains/loses based on overall truth quality
            if outcome == "correct":
                delta = 0.5 * math.log(1 + quality_score)  # Smaller gain for policy
            elif outcome == "incorrect":
                delta = -1.0 * math.log(1 + quality_score)  # Larger penalty for policy
            else:
                delta = 0.0
            
            new_standing = current + delta
            new_standing = max(self.policy.bounds.min, min(new_standing, self.policy.bounds.max))
            state.standings[policy_id] = new_standing
    
    def _handle_penalty(self, state: ReducerState, signal: Signal) -> None:
        """Apply explicit penalty to an agent."""
        agent_id = signal.object_id
        penalty_amount = signal.payload.get("amount", 10.0)
        reason = signal.payload.get("reason", "unspecified")
        
        if agent_id not in state.standings:
            state.standings[agent_id] = self.policy.get_initial_standing("observer")
        
        current = state.standings[agent_id]
        new_standing = max(self.policy.bounds.min, current - penalty_amount)
        state.standings[agent_id] = new_standing
    
    def _handle_endorsement(self, state: ReducerState, signal: Signal) -> None:
        """
        Handle endorsement signal (creates VOUCH edge implicitly).
        
        Note: Endorsements don't directly change standing; they create edges
        that affect effective trust computation.
        """
        # Ensure both agents exist in state
        endorser_id = signal.agent_id
        endorsed_id = signal.object_id
        
        for agent_id in [endorser_id, endorsed_id]:
            if agent_id not in state.standings:
                state.standings[agent_id] = self.policy.get_initial_standing("observer")
        
        # The edge is implicit — trust computation reads endorsement signals
        # to compute edge weights at query time
