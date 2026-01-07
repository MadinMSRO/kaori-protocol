"""
Kaori Truth — Pure Deterministic Truth Compiler

This package implements the Truth layer of the Kaori Protocol.
It is designed as a pure, deterministic compiler with ZERO external dependencies.

Package Structure:
- canonical/  - Canonicalization subsystem for deterministic serialization
- time/       - Temporal index subsystem for UTC normalization + bucketing
- primitives/ - Core protocol primitives (TruthKey, Observation, TruthState, etc.)
- compiler.py - Pure compile_truth_state() function
- trust_snapshot.py - TrustSnapshot data schema (receives from Flow)

Design Principles:
1. NO imports from kaori_db, kaori_api, or kaori_flow
2. NO runtime side effects
3. NO file IO (except ClaimType YAML loading)
4. NO wall-clock time access
5. All hashing through canonical subsystem
6. All times through time subsystem
"""
from __future__ import annotations

# Core compiler function
from kaori_truth.compiler import compile_truth_state, COMPILER_VERSION

# Trust snapshot data
from kaori_truth.trust_snapshot import TrustSnapshot, AgentTrust

# Primitives
from kaori_truth.primitives import (
    # TruthKey
    TruthKey,
    TruthKeyParts,
    canonical_truthkey,
    parse_truthkey,
    build_truthkey,
    # Observation
    Observation,
    ReporterContext,
    canonical_observation,
    observation_hash,
    # TruthState
    TruthState,
    TruthStatus,
    VerificationBasis,
    CompileInputs,
    SecurityBlock,
    # ClaimType
    ClaimType,
    canonical_claimtype,
    claimtype_hash,
    load_claimtype_yaml,
    # Evidence
    EvidenceRef,
    canonical_evidence_ref,
)

# Canonical subsystem
from kaori_truth.canonical import (
    canonicalize,
    canonical_json,
    canonical_hash,
)

# Time subsystem
from kaori_truth.time import (
    ensure_utc,
    bucket_datetime,
    format_bucket,
)

# Validation
from kaori_truth.validation import (
    validate_claim_payload,
    SchemaValidationError,
)

# Compiler errors
from kaori_truth.compiler import CompilationError

__version__ = "1.0.0"

__all__ = [
    # Compiler
    "compile_truth_state",
    "COMPILER_VERSION",
    "CompilationError",
    # Validation
    "validate_claim_payload",
    "SchemaValidationError",
    # Trust Snapshot
    "TrustSnapshot",
    "AgentTrust",
    # Primitives
    "TruthKey",
    "TruthKeyParts",
    "canonical_truthkey",
    "parse_truthkey",
    "build_truthkey",
    "Observation",
    "ReporterContext",
    "canonical_observation",
    "observation_hash",
    "TruthState",
    "TruthStatus",
    "VerificationBasis",
    "CompileInputs",
    "SecurityBlock",
    "ClaimType",
    "canonical_claimtype",
    "claimtype_hash",
    "load_claimtype_yaml",
    "EvidenceRef",
    "canonical_evidence_ref",
    # Canonical
    "canonicalize",
    "canonical_json",
    "canonical_hash",
    # Time
    "ensure_utc",
    "bucket_datetime",
    "format_bucket",
]
