"""
Kaori DB — Database Schemas & Migrations

This package provides the production SignalStore (kaori.signals),
TruthState persist (kaori.truth_states), and the append-only observation
/ artifact ledger. It can import from kaori-truth and kaori-flow.
"""
from __future__ import annotations

from kaori_db.store import (
    InMemoryArtifactLedger,
    InMemoryTruthStateStore,
    ObservationConflict,
    PostgresArtifactLedger,
    PostgresSignalStore,
    PostgresTruthStateStore,
)

__version__ = "1.0.0"

__all__ = [
    "InMemoryArtifactLedger",
    "InMemoryTruthStateStore",
    "ObservationConflict",
    "PostgresArtifactLedger",
    "PostgresSignalStore",
    "PostgresTruthStateStore",
]
