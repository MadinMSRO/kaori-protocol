"""
Kaori Flow — Trust Physics & Orchestration

This package implements the Flow layer of the Kaori Protocol.
It handles dynamic trust calculation, agent management, and signal processing.

Package Structure:
- primitives/  - Flow primitives (Agent, Network, Signal, Probe)
- trust_provider.py - TrustProvider implementation
- signal_processor.py - Signal → Probe logic
- standing_dynamics.py - Trust evolution

Dependency Rule:
- kaori-flow MAY import kaori-truth
- kaori-truth MUST NOT import kaori-flow
"""
from __future__ import annotations

from kaori_flow.trust_provider import TrustProvider, create_trust_snapshot
from kaori_flow.primitives import (
    Agent,
    AgentType,
    NetworkEdge,
    EdgeType,
    Signal,
    SignalType,
    Probe,
    ProbeStatus,
)

__version__ = "1.0.0"

__all__ = [
    # Trust Provider
    "TrustProvider",
    "create_trust_snapshot",
    # Primitives
    "Agent",
    "AgentType",
    "NetworkEdge",
    "EdgeType",
    "Signal",
    "SignalType",
    "Probe",
    "ProbeStatus",
]
