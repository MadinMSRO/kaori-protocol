"""
Kaori DB — Postgres stores for Flow signals and compiled TruthStates.

Append-only SignalStore for production Flow. Satisfies kaori_flow.store.SignalStore.
DATABASE_URL is Cloud SQL Postgres. Tables live in schema `kaori`, never in
`public` (including not public.truths). Does not provision a Cloud SQL instance.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine

from kaori_flow.primitives.signal import Signal, SignalContext


KAORI_SCHEMA = "kaori"


def _signals_table(metadata: MetaData, schema: Optional[str]) -> Table:
    return Table(
        "signals",
        metadata,
        Column("signal_id", String(64), primary_key=True),
        Column("signal_type", String(64), nullable=False),
        Column("time", DateTime(timezone=True), nullable=False),
        Column("agent_id", String(255), nullable=False),
        Column("object_id", String(255), nullable=False),
        Column("context", JSON, nullable=True),
        Column("payload", JSON, nullable=False),
        Column("policy_version", String(64), nullable=False),
        Column("signature", String(255), nullable=True),
        Index("ix_signals_time", "time"),
        Index("ix_signals_agent_id", "agent_id"),
        Index("ix_signals_object_id", "object_id"),
        Index("ix_signals_signal_type", "signal_type"),
        schema=schema,
    )


def _truth_states_table(metadata: MetaData, schema: Optional[str]) -> Table:
    # Production column artifact is JSONB (see schema.sql). SQLAlchemy JSON
    # maps to JSONB on Postgres and JSON on SQLite unit tests.
    return Table(
        "truth_states",
        metadata,
        Column("truthkey", String, primary_key=True),
        Column("artifact", JSON, nullable=False),
        Column("compiled_at", DateTime(timezone=True), nullable=False),
        schema=schema,
    )


metadata = MetaData(schema=KAORI_SCHEMA)
signals_table = _signals_table(metadata, KAORI_SCHEMA)
truth_states_table = _truth_states_table(metadata, KAORI_SCHEMA)

# SQLite (store unit tests) has no schemas; same columns, no public/kaori split.
_sqlite_metadata = MetaData()
_sqlite_signals_table = _signals_table(_sqlite_metadata, None)
_sqlite_truth_states_table = _truth_states_table(_sqlite_metadata, None)


def _ensure_utc(value: datetime) -> datetime:
    """Normalize store datetimes to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_to_signal(row: Any) -> Signal:
    context = None
    if row.context:
        context = SignalContext.model_validate(row.context)
    return Signal(
        signal_id=row.signal_id,
        signal_type=row.signal_type,
        time=_ensure_utc(row.time),
        agent_id=row.agent_id,
        object_id=row.object_id,
        context=context,
        payload=row.payload or {},
        policy_version=row.policy_version,
        signature=row.signature,
    )


def _signal_values(signal: Signal) -> dict:
    return {
        "signal_id": signal.signal_id,
        "signal_type": signal.signal_type,
        "time": _ensure_utc(signal.time),
        "agent_id": signal.agent_id,
        "object_id": signal.object_id,
        "context": signal.context.model_dump() if signal.context else None,
        "payload": signal.payload,
        "policy_version": signal.policy_version,
        "signature": signal.signature,
    }


def _engine_from_url(database_url: Optional[str] = None, engine: Optional[Engine] = None) -> Engine:
    if engine is not None:
        return engine
    url = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is required")
    return create_engine(url)


def _ensure_kaori_schema(engine: Engine) -> None:
    """
    Create schema kaori and kaori tables if missing.
    Does not provision a database or Cloud SQL instance.
    """
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS kaori"))
        metadata.create_all(engine)
        return
    _sqlite_metadata.create_all(engine)


def _upsert_stmt(table: Table, engine: Engine, values: dict, conflict_col: str, update_cols: List[str]):
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(table).values(**values)
    return stmt.on_conflict_do_update(
        index_elements=[conflict_col],
        set_={col: getattr(stmt.excluded, col) for col in update_cols},
    )


class PostgresSignalStore:
    """
    SQL SignalStore backed by DATABASE_URL (Cloud SQL Postgres).

    Production table is kaori.signals (SQLAlchemy schema='kaori').
    Does not use public and does not invent product tables.
    SQLite URLs remain for store unit tests only.
    """

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    @classmethod
    def from_env(cls) -> "PostgresSignalStore":
        """Construct from DATABASE_URL."""
        return cls()

    def _is_postgres(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    def _table(self) -> Table:
        return signals_table if self._is_postgres() else _sqlite_signals_table

    def ensure_schema(self) -> None:
        """Create schema kaori, kaori.signals, and kaori.truth_states if missing."""
        _ensure_kaori_schema(self._engine)

    def append(self, signal: Signal) -> None:
        """Append signal. Idempotent on signal_id."""
        table = self._table()
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(table.c.signal_id).where(table.c.signal_id == signal.signal_id)
            ).first()
            if existing:
                return
            conn.execute(table.insert().values(**_signal_values(signal)))

    def get_all(self) -> List[Signal]:
        """Get all signals, ordered by time."""
        table = self._table()
        with self._engine.begin() as conn:
            rows = conn.execute(select(table).order_by(table.c.time)).all()
        return [_row_to_signal(row) for row in rows]

    def get_for_agent(self, agent_id: str) -> List[Signal]:
        """Get signals where agent_id matches emitter or object_id."""
        table = self._table()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table)
                .where(or_(table.c.agent_id == agent_id, table.c.object_id == agent_id))
                .order_by(table.c.time)
            ).all()
        return [_row_to_signal(row) for row in rows]

    def get_since(self, since: datetime) -> List[Signal]:
        """Get signals since a given time, ordered by time."""
        table = self._table()
        since = _ensure_utc(since)
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table).where(table.c.time >= since).order_by(table.c.time)
            ).all()
        return [_row_to_signal(row) for row in rows]

    def get_by_type(self, signal_type: str) -> List[Signal]:
        """Get signals of a specific type, ordered by time."""
        table = self._table()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table)
                .where(table.c.signal_type == signal_type)
                .order_by(table.c.time)
            ).all()
        return [_row_to_signal(row) for row in rows]


class InMemoryTruthStateStore:
    """TruthState persist used when DATABASE_URL is unset (tests / local smoke)."""

    def __init__(self) -> None:
        self._by_key: Dict[str, Dict[str, Any]] = {}

    def upsert(self, truthkey: str, artifact: dict, compiled_at: datetime) -> None:
        self._by_key[truthkey] = {
            "artifact": dict(artifact),
            "compiled_at": _ensure_utc(compiled_at),
        }

    def get(self, truthkey: str) -> Optional[dict]:
        row = self._by_key.get(truthkey)
        return None if row is None else dict(row["artifact"])


class PostgresTruthStateStore:
    """
    Persist compiled TruthState artifacts in kaori.truth_states.

    Production columns: truthkey PK, artifact JSONB (full TruthState.model_dump
    including evidence_refs), compiled_at. Upsert on truthkey.
    Never writes to public.truths.
    """

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def _is_postgres(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    def _table(self) -> Table:
        return truth_states_table if self._is_postgres() else _sqlite_truth_states_table

    def ensure_schema(self) -> None:
        _ensure_kaori_schema(self._engine)

    def upsert(self, truthkey: str, artifact: dict, compiled_at: datetime) -> None:
        table = self._table()
        values = {
            "truthkey": truthkey,
            "artifact": artifact,
            "compiled_at": _ensure_utc(compiled_at),
        }
        stmt = _upsert_stmt(table, self._engine, values, "truthkey", ["artifact", "compiled_at"])
        with self._engine.begin() as conn:
            conn.execute(stmt)

    def get(self, truthkey: str) -> Optional[dict]:
        table = self._table()
        with self._engine.begin() as conn:
            row = conn.execute(
                select(table.c.artifact).where(table.c.truthkey == truthkey)
            ).first()
        if row is None:
            return None
        artifact = row.artifact
        return dict(artifact) if artifact is not None else None
