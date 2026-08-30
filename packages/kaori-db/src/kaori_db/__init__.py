"""
Kaori DB — Database Schemas & Migrations

This package provides the production SignalStore (kaori.signals) and
TruthState persist (kaori.truth_states). It can import from kaori-truth
and kaori-flow.
"""
from __future__ import annotations

from kaori_db.store import (
    InMemoryObservationStore,
    InMemoryTrustSnapshotStore,
    InMemoryTruthArtifactStore,
    InMemoryTruthStateStore,
    PostgresObservationStore,
    PostgresSignalStore,
    PostgresTrustSnapshotStore,
    PostgresTruthArtifactStore,
    PostgresTruthStateStore,
)

__version__ = "1.0.0"

__all__ = [
    "InMemoryObservationStore",
    "InMemoryTrustSnapshotStore",
    "InMemoryTruthArtifactStore",
    "InMemoryTruthStateStore",
    "PostgresObservationStore",
    "PostgresSignalStore",
    "PostgresTrustSnapshotStore",
    "PostgresTruthArtifactStore",
    "PostgresTruthStateStore",
]
