"""
Kaori Flow — The Physics of Trust

Event-sourced, emergent, deterministic trust dynamics.
Implements the 7 Rules of Trust (FLOW_SPEC v4.0).

Core Library API:
    FlowCore: Main entry point
    FlowPolicy: Configuration (YAML agent)
    Signal: Immutable event envelope
    TrustSnapshot: Frozen trust state for truth compilation

Example:
    from kaori_flow import FlowCore, FlowPolicy
    
    # Initialize with default policy
    flow = FlowCore(policy=FlowPolicy.default())
    
    # Register an agent
    flow.register_agent("user:amira", role="observer")
    
    # Get standing
    standing = flow.get_standing("user:amira")
    
    # Get trust snapshot for truth compilation
    snapshot = flow.get_trust_snapshot(
        agent_ids=["user:amira"],
        context=TrustContext(claimtype_id="earth.flood.v1"),
    )
"""
from .core import FlowCore
from .policy import FlowPolicy
from .primitives.agent import Agent, AgentType, create_agent_id, STANDING_MIN, STANDING_MAX
from .primitives.signal import Signal, SignalContext, SignalTypes
from .reducer import FlowReducer, ReducerState
from .store import SignalStore, InMemorySignalStore, JSONLSignalStore
from .trust import TrustComputer, TrustContext, TrustSnapshot, AgentTrust

__all__ = [
    # Core
    "FlowCore",
    "FlowPolicy",
    
    # Primitives
    "Agent",
    "AgentType",
    "Signal",
    "SignalContext",
    "SignalTypes",
    
    # Trust
    "TrustComputer",
    "TrustContext",
    "TrustSnapshot",
    "AgentTrust",
    
    # Storage
    "SignalStore",
    "InMemorySignalStore",
    "JSONLSignalStore",
    
    # Reducer
    "FlowReducer",
    "ReducerState",
    
    # Helpers
    "create_agent_id",
    "STANDING_MIN",
    "STANDING_MAX",
]

__version__ = "2.0.0"
