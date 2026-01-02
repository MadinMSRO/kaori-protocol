"""
Kaori Core — Consensus Engine

The core implementation of the Kaori Protocol (SPEC.md v1.3).
"""

from .models import (
    AIValidationResult,
    ConfidenceBreakdown,
    ConsensusRecord,
    Domain,
    Observation,
    ReporterContext,
    SecurityBlock,
    SpatialSystem,
    Standing,
    TruthKey,
    TruthState,
    TruthStatus,
    VerificationBasis,
    Vote,
    VoteType,
)

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
    
    # Models
    "Domain",
    "SpatialSystem",
    "TruthStatus",
    "VerificationBasis",
    "Standing",
    "VoteType",
    "TruthKey",
    "ReporterContext",
    "Observation",
    "Vote",
    "ConsensusRecord",
    "AIValidationResult",
    "ConfidenceBreakdown",
    "SecurityBlock",
    "TruthState",
    
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
