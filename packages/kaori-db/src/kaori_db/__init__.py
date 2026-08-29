"""
Kaori DB — Database Schemas & Migrations

This package provides the production SignalStore and the signals table.
It can import from kaori-truth and kaori-flow.
"""
from __future__ import annotations

from kaori_db.store import PostgresSignalStore

__version__ = "1.0.0"

__all__ = [
    "PostgresSignalStore",
]
