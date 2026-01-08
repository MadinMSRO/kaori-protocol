"""
Kaori Flow — Signal Store Abstraction

Abstract interface for signal storage (FLOW_SPEC v4.0 Section 5).
Rule 1: Trust is Event-Sourced — signals are append-only.

The core library provides reference implementations.
Production implementations (PostgreSQL, BigQuery, Pub/Sub) are external.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Protocol, runtime_checkable

from .primitives.signal import Signal


@runtime_checkable
class SignalStore(Protocol):
    """
    Abstract interface for signal storage.
    
    Implementations must guarantee:
    - Append-only semantics (signals never modified or deleted)
    - Ordered replay by time
    - Indexing by agent_id for efficient queries
    """
    
    def append(self, signal: Signal) -> None:
        """Append a signal to the store. Must be idempotent on signal_id."""
        ...
    
    def get_all(self) -> List[Signal]:
        """Get all signals, ordered by time."""
        ...
    
    def get_for_agent(self, agent_id: str) -> List[Signal]:
        """Get all signals where agent_id is emitter or object_id."""
        ...
    
    def get_since(self, since: datetime) -> List[Signal]:
        """Get signals since a given time, ordered by time."""
        ...
    
    def get_by_type(self, signal_type: str) -> List[Signal]:
        """Get signals of a specific type."""
        ...


class InMemorySignalStore:
    """
    In-memory signal store for testing and development.
    
    NOT suitable for production (no persistence, no durability).
    """
    
    def __init__(self) -> None:
        self._signals: List[Signal] = []
        self._by_id: dict[str, Signal] = {}
    
    def append(self, signal: Signal) -> None:
        """Append signal. Idempotent on signal_id."""
        if signal.signal_id in self._by_id:
            return  # Already exists, ignore (idempotent)
        self._signals.append(signal)
        self._by_id[signal.signal_id] = signal
    
    def get_all(self) -> List[Signal]:
        """Get all signals, ordered by time."""
        return sorted(self._signals, key=lambda s: s.time)
    
    def get_for_agent(self, agent_id: str) -> List[Signal]:
        """Get signals where agent_id matches emitter or object_id."""
        return sorted(
            [s for s in self._signals if s.agent_id == agent_id or s.object_id == agent_id],
            key=lambda s: s.time
        )
    
    def get_since(self, since: datetime) -> List[Signal]:
        """Get signals since a given time."""
        return sorted(
            [s for s in self._signals if s.time >= since],
            key=lambda s: s.time
        )
    
    def get_by_type(self, signal_type: str) -> List[Signal]:
        """Get signals of a specific type."""
        return sorted(
            [s for s in self._signals if s.signal_type == signal_type],
            key=lambda s: s.time
        )
    
    def __len__(self) -> int:
        return len(self._signals)
    
    def clear(self) -> None:
        """Clear all signals (for testing only)."""
        self._signals.clear()
        self._by_id.clear()


class JSONLSignalStore:
    """
    JSONL file-based signal store for simple deployments.
    
    Each line is a JSON-serialized signal.
    Append-only by design (only appends to file).
    """
    
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Create file if doesn't exist
        if not self._path.exists():
            self._path.touch()
    
    def append(self, signal: Signal) -> None:
        """Append signal to JSONL file."""
        # Check for duplicate (idempotent)
        existing_ids = {s.signal_id for s in self._iter_signals()}
        if signal.signal_id in existing_ids:
            return
        
        with open(self._path, 'a') as f:
            f.write(signal.model_dump_json() + '\n')
    
    def get_all(self) -> List[Signal]:
        """Get all signals, ordered by time."""
        return sorted(list(self._iter_signals()), key=lambda s: s.time)
    
    def get_for_agent(self, agent_id: str) -> List[Signal]:
        """Get signals where agent_id matches emitter or object_id."""
        return sorted(
            [s for s in self._iter_signals() if s.agent_id == agent_id or s.object_id == agent_id],
            key=lambda s: s.time
        )
    
    def get_since(self, since: datetime) -> List[Signal]:
        """Get signals since a given time."""
        return sorted(
            [s for s in self._iter_signals() if s.time >= since],
            key=lambda s: s.time
        )
    
    def get_by_type(self, signal_type: str) -> List[Signal]:
        """Get signals of a specific type."""
        return sorted(
            [s for s in self._iter_signals() if s.signal_type == signal_type],
            key=lambda s: s.time
        )
    
    def _iter_signals(self) -> Iterator[Signal]:
        """Iterate over all signals in the file."""
        with open(self._path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    yield Signal.model_validate_json(line)
