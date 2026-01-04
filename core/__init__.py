"""
Kaori Core — Consensus Engine

The core implementation of the Kaori Protocol (SPEC.md v1.3).
"""

from .models import (
    # Enums
    AgentType,
    Domain,
    EdgeType,
    ProbeStatus,
    SpatialSystem,
    Standing,
    TruthStatus,
    VerificationBasis,
    VoteType,
    # Core Models
    Agent,
    AIValidationResult,
    ConfidenceBreakdown,
    ConsensusRecord,
    Probe,
    NetworkEdge,
    Observation,
    ReporterContext,
    SecurityBlock,
    TruthKey,
    TruthState,
    Vote,
    TrustContext,
    TrustResult,
)

from .signals import Signal, SignalType

from .engine import KaoriEngine, create_engine
from .consensus import compute_consensus, get_consensus_outcome
from .confidence import compute_confidence, get_confidence_level
from .signing import (
    compute_truth_hash,
    sign_truth_state,
    verify_truth_state,
)
from .truthkey import generate_truthkey, parse_truthkey, format_truthkey
from .schema_loader import load_claim_schema, list_available_schemas

__all__ = [
    # Engine
    "KaoriEngine",
    "create_engine",
    
    # Enums
    "AgentType",
    "Domain",
    "EdgeType",
    "ProbeStatus",
    "SpatialSystem",
    "Standing",
    "TruthStatus",
    "VerificationBasis",
    "VoteType",
    "SignalType",
    
    # Core Models
    "Agent",
    "AIValidationResult",
    "ConfidenceBreakdown",
    "ConsensusRecord",
    "Probe",
    "NetworkEdge",
    "Observation",
    "ReporterContext",
    "SecurityBlock",
    "Signal",
    "TruthKey",
    "TrustContext",
    "TrustResult",
    "TruthState",
    "Vote",
    
    # Functions
    "compute_consensus",
    "get_consensus_outcome",
    "compute_confidence",
    "get_confidence_level",
    "compute_truth_hash",
    "sign_truth_state",
    "verify_truth_state",
    "generate_truthkey",
    "parse_truthkey",
    "format_truthkey",
    "load_claim_schema",
    "list_available_schemas",
]

__version__ = "0.1.0"
