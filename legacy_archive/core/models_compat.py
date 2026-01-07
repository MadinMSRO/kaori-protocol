"""
Kaori Core — Compatibility Shim for models.py

This module re-exports primitives from the new package structure
for backwards compatibility. New code should import directly from
kaori_truth and kaori_flow packages.

DEPRECATION WARNING: This shim will be removed in version 2.0.
Import from kaori_truth or kaori_flow instead.
"""
from __future__ import annotations

import warnings

# Issue deprecation warning on import
warnings.warn(
    "Importing from 'core.models' is deprecated. "
    "Import from 'kaori_truth' or 'kaori_flow' instead. "
    "This compatibility shim will be removed in version 2.0.",
    DeprecationWarning,
    stacklevel=2,
)

# =============================================================================
# Re-exports from kaori_truth
# =============================================================================

try:
    from kaori_truth.primitives.truthkey import (
        Domain,
        SpatialSystem,
        TruthKey,
        TruthKeyParts,
    )
    from kaori_truth.primitives.truthstate import (
        TruthStatus,
        VerificationBasis,
        TruthState,
        SecurityBlock,
        ConfidenceBreakdown,
        ConsensusRecord,
    )
    from kaori_truth.primitives.observation import (
        Observation,
        ReporterContext,
        Standing,
    )
    from kaori_truth.trust_snapshot import (
        TrustSnapshot as TrustResult,  # Legacy name
        AgentTrust as TrustContext,  # Legacy name
    )
except ImportError:
    # Fall back to original if packages not installed
    pass

# =============================================================================
# Re-exports from kaori_flow
# =============================================================================

try:
    from kaori_flow.primitives.agent import (
        Agent,
        AgentType,
    )
    from kaori_flow.primitives.network import (
        NetworkEdge,
        EdgeType,
    )
    from kaori_flow.primitives.probe import (
        Probe,
        ProbeStatus,
    )
    from kaori_flow.primitives.signal import (
        Signal,
        SignalType,
    )
except ImportError:
    # Fall back to original if packages not installed
    pass


# =============================================================================
# Legacy exports (keep original names for compatibility)
# =============================================================================

__all__ = [
    # Enums
    "Domain",
    "SpatialSystem",
    "TruthStatus",
    "VerificationBasis",
    "AgentType",
    "EdgeType",
    "SignalType",
    "ProbeStatus",
    "Standing",
    # Truth Primitives
    "TruthKey",
    "TruthKeyParts",
    "TruthState",
    "Observation",
    "ReporterContext",
    "SecurityBlock",
    "ConfidenceBreakdown",
    "ConsensusRecord",
    # Flow Primitives
    "Agent",
    "NetworkEdge",
    "Probe",
    "Signal",
    # Legacy names
    "TrustResult",
    "TrustContext",
]
