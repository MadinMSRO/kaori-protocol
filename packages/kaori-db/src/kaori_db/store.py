"""
Kaori DB — Postgres stores for Flow signals, compiled TruthStates, and the
append-only observation / artifact ledger.

Append-only SignalStore for production Flow. Satisfies kaori_flow.store.SignalStore.
DATABASE_URL is Cloud SQL Postgres. Tables live in schema `kaori`, never in
`public` (including not public.truths). Does not provision a Cloud SQL instance.
"""
from __future__ import annotations

import hashlib
import json
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
    UniqueConstraint,
    create_engine,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine

from kaori_flow.primitives.signal import Signal, SignalContext
from kaori_truth.primitives.observation import Observation


KAORI_SCHEMA = "kaori"


class ObservationConflict(ValueError):
    """Same reporter already recorded a different Observation on this TruthKey."""


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


def _observations_table(metadata: MetaData, schema: Optional[str]) -> Table:
    return Table(
        "observations",
        metadata,
        Column("observation_hash", String(64), primary_key=True),
        Column("truthkey", String, nullable=False),
        Column("reporter_id", String(255), nullable=False),
        Column("claim_type_id", String(255), nullable=False),
        Column("observation", JSON, nullable=False),
        Column("recorded_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("truthkey", "reporter_id", name="uq_observations_truthkey_reporter"),
        Index("ix_observations_truthkey", "truthkey"),
        schema=schema,
    )


def _artifact_ledger_table(metadata: MetaData, schema: Optional[str]) -> Table:
    return Table(
        "artifact_ledger",
        metadata,
        Column("ledger_id", String(64), primary_key=True),
        Column("truthkey", String, nullable=False),
        Column("artifact", JSON, nullable=False),
        Column("compiled_at", DateTime(timezone=True), nullable=False),
        Index("ix_artifact_ledger_truthkey", "truthkey"),
        Index("ix_artifact_ledger_compiled_at", "compiled_at"),
        schema=schema,
    )


metadata = MetaData(schema=KAORI_SCHEMA)
signals_table = _signals_table(metadata, KAORI_SCHEMA)
truth_states_table = _truth_states_table(metadata, KAORI_SCHEMA)
observations_table = _observations_table(metadata, KAORI_SCHEMA)
artifact_ledger_table = _artifact_ledger_table(metadata, KAORI_SCHEMA)

# SQLite (store unit tests) has no schemas; same columns, no public/kaori split.
_sqlite_metadata = MetaData()
_sqlite_signals_table = _signals_table(_sqlite_metadata, None)
_sqlite_truth_states_table = _truth_states_table(_sqlite_metadata, None)
_sqlite_observations_table = _observations_table(_sqlite_metadata, None)
_sqlite_artifact_ledger_table = _artifact_ledger_table(_sqlite_metadata, None)


def _ledger_id(truthkey: str, artifact: dict, compiled_at: datetime) -> str:
    payload = json.dumps(
        {
            "artifact": artifact,
            "compiled_at": _ensure_utc(compiled_at).isoformat(),
            "truthkey": truthkey,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        """Create schema kaori and kaori tables if missing."""
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


class InMemoryArtifactLedger:
    """Observation intake and artifact history when DATABASE_URL is unset."""

    def __init__(self) -> None:
        self._observations: Dict[str, Dict[str, Any]] = {}
        self._reporter_hash: Dict[tuple[str, str], str] = {}
        self._artifacts: List[Dict[str, Any]] = []

    def record_observation(
        self,
        truthkey: str,
        claim_type_id: str,
        observation: Observation,
        recorded_at: Optional[datetime] = None,
    ) -> None:
        digest = observation.hash()
        reporter_key = (truthkey, observation.reporter_id)
        existing = self._reporter_hash.get(reporter_key)
        if existing is not None and existing != digest:
            raise ObservationConflict(
                f"Observation already recorded for {observation.reporter_id} on {truthkey}"
            )
        if digest in self._observations:
            return
        self._observations[digest] = {
            "observation_hash": digest,
            "truthkey": truthkey,
            "reporter_id": observation.reporter_id,
            "claim_type_id": claim_type_id,
            "observation": observation.model_dump(mode="json"),
            "recorded_at": _ensure_utc(recorded_at or datetime.now(timezone.utc)),
        }
        self._reporter_hash[reporter_key] = digest

    def observations_for(self, truthkey: str) -> List[dict]:
        rows = [row for row in self._observations.values() if row["truthkey"] == truthkey]
        rows.sort(key=lambda row: (row["recorded_at"], row["observation_hash"]))
        return [dict(row["observation"]) for row in rows]

    def append_artifact(self, truthkey: str, artifact: dict, compiled_at: datetime) -> None:
        compiled_at = _ensure_utc(compiled_at)
        ledger_id = _ledger_id(truthkey, artifact, compiled_at)
        if any(row["ledger_id"] == ledger_id for row in self._artifacts):
            return
        self._artifacts.append(
            {
                "ledger_id": ledger_id,
                "truthkey": truthkey,
                "artifact": dict(artifact),
                "compiled_at": compiled_at,
            }
        )

    def artifacts_for(self, truthkey: str) -> List[dict]:
        rows = [row for row in self._artifacts if row["truthkey"] == truthkey]
        rows.sort(key=lambda row: (row["compiled_at"], row["ledger_id"]))
        return [dict(row["artifact"]) for row in rows]


class PostgresArtifactLedger:
    """
    Append-only Observation intake and compiled-artifact history.

    Production tables: kaori.observations (one immutable Observation per
    reporter per TruthKey) and kaori.artifact_ledger (every persisted
    TruthState). Never writes product tables.
    """

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def _is_postgres(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    def _observation_table(self) -> Table:
        return observations_table if self._is_postgres() else _sqlite_observations_table

    def _ledger_table(self) -> Table:
        return artifact_ledger_table if self._is_postgres() else _sqlite_artifact_ledger_table

    def ensure_schema(self) -> None:
        _ensure_kaori_schema(self._engine)

    def record_observation(
        self,
        truthkey: str,
        claim_type_id: str,
        observation: Observation,
        recorded_at: Optional[datetime] = None,
    ) -> None:
        table = self._observation_table()
        digest = observation.hash()
        recorded_at = _ensure_utc(recorded_at or datetime.now(timezone.utc))
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(table.c.observation_hash).where(
                    table.c.truthkey == truthkey,
                    table.c.reporter_id == observation.reporter_id,
                )
            ).first()
            if existing is not None:
                if existing.observation_hash != digest:
                    raise ObservationConflict(
                        f"Observation already recorded for {observation.reporter_id} on {truthkey}"
                    )
                return
            conn.execute(
                table.insert().values(
                    observation_hash=digest,
                    truthkey=truthkey,
                    reporter_id=observation.reporter_id,
                    claim_type_id=claim_type_id,
                    observation=observation.model_dump(mode="json"),
                    recorded_at=recorded_at,
                )
            )

    def observations_for(self, truthkey: str) -> List[dict]:
        table = self._observation_table()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table)
                .where(table.c.truthkey == truthkey)
                .order_by(table.c.recorded_at, table.c.observation_hash)
            ).all()
        packed = []
        for row in rows:
            payload = row.observation
            packed.append(dict(payload) if payload is not None else {})
        return packed

    def append_artifact(self, truthkey: str, artifact: dict, compiled_at: datetime) -> None:
        table = self._ledger_table()
        compiled_at = _ensure_utc(compiled_at)
        values = {
            "ledger_id": _ledger_id(truthkey, artifact, compiled_at),
            "truthkey": truthkey,
            "artifact": artifact,
            "compiled_at": compiled_at,
        }
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(table.c.ledger_id).where(table.c.ledger_id == values["ledger_id"])
            ).first()
            if existing:
                return
            conn.execute(table.insert().values(**values))

    def artifacts_for(self, truthkey: str) -> List[dict]:
        table = self._ledger_table()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table)
                .where(table.c.truthkey == truthkey)
                .order_by(table.c.compiled_at, table.c.ledger_id)
            ).all()
        packed = []
        for row in rows:
            payload = row.artifact
            packed.append(dict(payload) if payload is not None else {})
        return packed
