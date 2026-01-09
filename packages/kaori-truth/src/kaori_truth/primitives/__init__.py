"""
Kaori Truth — Primitives

Core protocol primitives for the Truth layer.
"""

from .truthkey import TruthKey, TruthKeyParts, canonical_truthkey, parse_truthkey, build_truthkey
from .observation import Observation, ReporterContext, canonical_observation, observation_hash
from .truthstate import TruthState, TruthStatus, VerificationBasis, CompileInputs, SecurityBlock
from .claimtype import (
    ClaimType,
    canonical_claimtype,
    claimtype_hash,
)

from .evidence import EvidenceRef, canonical_evidence_ref

__all__ = [
    # TruthKey
    "TruthKey",
    "TruthKeyParts",
    "canonical_truthkey",
    "parse_truthkey",
    "build_truthkey",
    # Observation
    "Observation",
    "ReporterContext",
    "canonical_observation",
    "observation_hash",
    # TruthState
    "TruthState",
    "TruthStatus",
    "VerificationBasis",
    "CompileInputs",
    "SecurityBlock",
    # ClaimType
    "ClaimType",
    "canonical_claimtype",
    "claimtype_hash",
    "load_claimtype_yaml",
    # Evidence
    "EvidenceRef",
    "canonical_evidence_ref",
]
