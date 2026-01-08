"""
Kaori Flow — Primitives

The 4 primitives of Kaori Flow (FLOW_SPEC v4.0 Section 2):
- Agent: Identity unit
- Network: Trust edges (inferred from signals)
- Signal: Immutable event envelope
- Probe: Coordination object
"""
from .agent import Agent, AgentType, create_agent_id, STANDING_MIN, STANDING_MAX
from .network import NetworkEdge, EdgeType
from .probe import Probe, ProbeStatus
from .signal import Signal, SignalContext, SignalTypes

__all__ = [
    "Agent",
    "AgentType",
    "create_agent_id",
    "STANDING_MIN",
    "STANDING_MAX",
    "NetworkEdge",
    "EdgeType",
    "Probe",
    "ProbeStatus",
    "Signal",
    "SignalContext",
    "SignalTypes",
]
