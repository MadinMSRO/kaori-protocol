"""
Kaori DB — Postgres stores for Flow signals and compiled TruthStates.

Append-only SignalStore for production Flow. Satisfies kaori_flow.store.SignalStore.
DATABASE_URL is Cloud SQL Postgres. Tables live in schema `kaori`, never in
`public` (including not public.truths). Does not provision a Cloud SQL instance.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.engine import Engine

from kaori_flow.primitives.signal import Signal, SignalContext
from kaori_truth.primitives.observation import Observation
from kaori_truth.primitives.truthstate import TruthState
from kaori_truth.trust_snapshot import TrustSnapshot


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
    """Mutable Gold projection used by GET /v1/truth."""
    return Table(
        "truth_states",
        metadata,
        Column("truthkey", String, primary_key=True),
        Column("artifact", JSON, nullable=False),
        Column("compiled_at", DateTime(timezone=True), nullable=False),
        Column("state_hash", String(64), nullable=True),
        Column("revision", BigInteger, nullable=True),
        Column("artifact_id", BigInteger, nullable=True),
        schema=schema,
    )


def _observations_table(metadata: MetaData, schema: Optional[str]) -> Table:
    """Immutable Bronze observation index; evidence bytes remain in private object storage."""
    return Table(
        "observations",
        metadata,
        Column("observation_id", String(36), primary_key=True),
        Column("observation_hash", String(64), nullable=False, unique=True),
        Column("truthkey", String, nullable=False),
        Column("claim_type_id", String, nullable=False),
        Column("claim_type_hash", String(64), nullable=False),
        Column("reporter_id", String, nullable=False),
        Column("reported_at", DateTime(timezone=True), nullable=False),
        Column("received_at", DateTime(timezone=True), nullable=False),
        Column("canonical", JSON, nullable=False),
        Column("evidence_refs", JSON, nullable=False),
        Index("ix_observations_truthkey", "truthkey"),
        Index("ix_observations_truthkey_reporter", "truthkey", "reporter_id"),
        Index("ix_observations_reported_at", "reported_at"),
        schema=schema,
    )


def _trust_snapshots_table(metadata: MetaData, schema: Optional[str]) -> Table:
    """Immutable TrustSnapshot packages, addressed by unique snapshot id."""
    return Table(
        "trust_snapshots",
        metadata,
        Column("snapshot_id", String, primary_key=True),
        Column("snapshot_hash", String(64), nullable=False),
        Column("snapshot_time", DateTime(timezone=True), nullable=False),
        Column("artifact", JSON, nullable=False),
        Index("ix_trust_snapshots_hash", "snapshot_hash"),
        schema=schema,
    )


def _truth_artifacts_table(metadata: MetaData, schema: Optional[str]) -> Table:
    """Append-only Silver ledger of signed TruthState revisions."""
    artifact_id_type = BigInteger().with_variant(Integer, "sqlite")
    return Table(
        "truth_artifacts",
        metadata,
        Column("artifact_id", artifact_id_type, primary_key=True, autoincrement=True),
        Column("truthkey", String, nullable=False),
        Column("revision", BigInteger, nullable=False),
        Column("state_hash", String(64), nullable=False, unique=True),
        Column("semantic_hash", String(64), nullable=False),
        Column("claim_type_id", String, nullable=False),
        Column("claim_type_hash", String(64), nullable=False),
        Column("trust_snapshot_id", String, nullable=False),
        Column("trust_snapshot_hash", String(64), nullable=False),
        Column("status", String, nullable=False),
        Column("compiled_at", DateTime(timezone=True), nullable=False),
        Column("artifact", JSON, nullable=False),
        UniqueConstraint("truthkey", "revision", name="uq_truth_artifacts_truthkey_revision"),
        Index("ix_truth_artifacts_truthkey_compiled", "truthkey", "compiled_at"),
        Index("ix_truth_artifacts_semantic_hash", "semantic_hash"),
        schema=schema,
    )


metadata = MetaData(schema=KAORI_SCHEMA)
signals_table = _signals_table(metadata, KAORI_SCHEMA)
truth_states_table = _truth_states_table(metadata, KAORI_SCHEMA)
observations_table = _observations_table(metadata, KAORI_SCHEMA)
trust_snapshots_table = _trust_snapshots_table(metadata, KAORI_SCHEMA)
truth_artifacts_table = _truth_artifacts_table(metadata, KAORI_SCHEMA)

# SQLite (store unit tests) has no schemas; same columns, no public/kaori split.
_sqlite_metadata = MetaData()
_sqlite_signals_table = _signals_table(_sqlite_metadata, None)
_sqlite_truth_states_table = _truth_states_table(_sqlite_metadata, None)
_sqlite_observations_table = _observations_table(_sqlite_metadata, None)
_sqlite_trust_snapshots_table = _trust_snapshots_table(_sqlite_metadata, None)
_sqlite_truth_artifacts_table = _truth_artifacts_table(_sqlite_metadata, None)


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
        schema_sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.exec_driver_sql(schema_sql)
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


class InMemoryObservationStore:
    """Immutable Bronze store for tests and local smoke runs."""

    def __init__(self) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}

    def append(
        self,
        observation: Observation,
        *,
        truthkey: str,
        claim_type_hash: str,
        received_at: datetime,
    ) -> bool:
        observation_id = str(observation.observation_id)
        observation_hash = observation.hash()
        existing = self._by_id.get(observation_id)
        if existing:
            if existing["observation_hash"] != observation_hash:
                raise ValueError("observation_id already exists with different content")
            return False
        self._by_id[observation_id] = {
            "observation_hash": observation_hash,
            "truthkey": truthkey,
            "claim_type_hash": claim_type_hash,
            "reporter_id": observation.reporter_id,
            "reported_at": observation.reported_at,
            "received_at": _ensure_utc(received_at),
            "canonical": observation.canonical(),
        }
        return True

    def get_for_truthkey(self, truthkey: str) -> List[Observation]:
        rows = [row for row in self._by_id.values() if row["truthkey"] == truthkey]
        rows.sort(key=lambda row: (row["reported_at"], row["canonical"]["observation_id"]))
        return [Observation.model_validate(row["canonical"]) for row in rows]

    def count_distinct_reporters(self, truthkey: str) -> int:
        return len(
            {
                row["reporter_id"]
                for row in self._by_id.values()
                if row["truthkey"] == truthkey
            }
        )


class PostgresObservationStore:
    """Insert-only index of canonical observations whose evidence lives in object storage."""

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    def _table(self) -> Table:
        if self._engine.dialect.name == "postgresql":
            return observations_table
        return _sqlite_observations_table

    def ensure_schema(self) -> None:
        _ensure_kaori_schema(self._engine)

    def append(
        self,
        observation: Observation,
        *,
        truthkey: str,
        claim_type_hash: str,
        received_at: datetime,
    ) -> bool:
        table = self._table()
        observation_id = str(observation.observation_id)
        observation_hash = observation.hash()
        values = {
            "observation_id": observation_id,
            "observation_hash": observation_hash,
            "truthkey": truthkey,
            "claim_type_id": observation.claim_type,
            "claim_type_hash": claim_type_hash,
            "reporter_id": observation.reporter_id,
            "reported_at": _ensure_utc(observation.reported_at),
            "received_at": _ensure_utc(received_at),
            "canonical": observation.canonical(),
            "evidence_refs": [
                ref.model_dump(mode="json", exclude_none=True)
                for ref in observation.evidence_refs
            ],
        }
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(table.c.observation_hash).where(
                    table.c.observation_id == observation_id
                )
            ).first()
            if existing:
                if existing.observation_hash != observation_hash:
                    raise ValueError("observation_id already exists with different content")
                return False
            conn.execute(table.insert().values(**values))
        return True

    def get_for_truthkey(self, truthkey: str) -> List[Observation]:
        table = self._table()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(table.c.canonical)
                .where(table.c.truthkey == truthkey)
                .order_by(table.c.reported_at, table.c.observation_id)
            ).all()
        return [Observation.model_validate(row.canonical) for row in rows]

    def count_distinct_reporters(self, truthkey: str) -> int:
        table = self._table()
        with self._engine.begin() as conn:
            count = conn.execute(
                select(func.count(func.distinct(table.c.reporter_id))).where(
                    table.c.truthkey == truthkey
                )
            ).scalar_one()
        return int(count)


class InMemoryTrustSnapshotStore:
    """Immutable TrustSnapshot store for tests."""

    def __init__(self) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}

    def append(self, snapshot: TrustSnapshot) -> bool:
        if not snapshot.verify_hash():
            raise ValueError("trust snapshot hash does not match its canonical content")
        artifact = snapshot.model_dump(mode="json")
        existing = self._by_id.get(snapshot.snapshot_id)
        if existing:
            if existing != artifact:
                raise ValueError("snapshot_id already exists with different content")
            return False
        self._by_id[snapshot.snapshot_id] = artifact
        return True

    def get(self, snapshot_id: str) -> Optional[TrustSnapshot]:
        artifact = self._by_id.get(snapshot_id)
        return None if artifact is None else TrustSnapshot.model_validate(artifact)


class PostgresTrustSnapshotStore:
    """Insert-only storage for the full frozen trust input used by compilation."""

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    def _table(self) -> Table:
        if self._engine.dialect.name == "postgresql":
            return trust_snapshots_table
        return _sqlite_trust_snapshots_table

    def ensure_schema(self) -> None:
        _ensure_kaori_schema(self._engine)

    def append(self, snapshot: TrustSnapshot) -> bool:
        if not snapshot.verify_hash():
            raise ValueError("trust snapshot hash does not match its canonical content")
        table = self._table()
        artifact = snapshot.model_dump(mode="json")
        with self._engine.begin() as conn:
            existing = conn.execute(
                select(table.c.artifact).where(table.c.snapshot_id == snapshot.snapshot_id)
            ).first()
            if existing:
                if existing.artifact != artifact:
                    raise ValueError("snapshot_id already exists with different content")
                return False
            conn.execute(
                table.insert().values(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_hash=snapshot.snapshot_hash,
                    snapshot_time=_ensure_utc(snapshot.snapshot_time),
                    artifact=artifact,
                )
            )
        return True

    def get(self, snapshot_id: str) -> Optional[TrustSnapshot]:
        table = self._table()
        with self._engine.begin() as conn:
            row = conn.execute(
                select(table.c.artifact).where(table.c.snapshot_id == snapshot_id)
            ).first()
        return None if row is None else TrustSnapshot.model_validate(row.artifact)


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


def _validate_signed_artifact(state: TruthState, snapshot: TrustSnapshot) -> None:
    if not snapshot.verify_hash():
        raise ValueError("trust snapshot hash does not match its canonical content")
    if state.compile_inputs.trust_snapshot_hash != snapshot.snapshot_hash:
        raise ValueError("TruthState references a different trust snapshot")
    if not state.verify_hashes():
        raise ValueError("TruthState semantic or state hash is invalid")
    if not state.security.signature:
        raise ValueError("TruthState must be signed before persistence")


class InMemoryTruthArtifactStore:
    """Append-only Silver ledger plus a mutable Gold projection for tests."""

    def __init__(self) -> None:
        self._artifacts: Dict[str, Dict[str, Any]] = {}
        self._by_key: Dict[str, List[str]] = {}
        self._latest: Dict[str, Dict[str, Any]] = {}
        self.trust_snapshots = InMemoryTrustSnapshotStore()

    def append(self, state: TruthState, snapshot: TrustSnapshot) -> dict:
        _validate_signed_artifact(state, snapshot)
        state_hash = state.security.state_hash
        existing = self._artifacts.get(state_hash)
        if existing is not None:
            return dict(existing["artifact"])

        self.trust_snapshots.append(snapshot)
        revisions = self._by_key.setdefault(state.truthkey, [])
        artifact = state.model_dump(mode="json")
        record = {
            "artifact_id": len(self._artifacts) + 1,
            "truthkey": state.truthkey,
            "revision": len(revisions) + 1,
            "state_hash": state_hash,
            "artifact": artifact,
        }
        self._artifacts[state_hash] = record
        revisions.append(state_hash)
        self._latest[state.truthkey] = record
        return dict(artifact)

    def get(self, truthkey: str) -> Optional[dict]:
        row = self._latest.get(truthkey)
        return None if row is None else dict(row["artifact"])

    def get_history(self, truthkey: str) -> List[dict]:
        return [
            dict(self._artifacts[state_hash]["artifact"])
            for state_hash in self._by_key.get(truthkey, [])
        ]


class PostgresTruthArtifactStore:
    """
    Persist a signed TruthState to immutable Silver history and update Gold atomically.

    Idempotency is keyed by state_hash. PostgreSQL takes a per-TruthKey advisory
    transaction lock so concurrent compiles cannot allocate the same revision.
    """

    def __init__(self, database_url: Optional[str] = None, engine: Optional[Engine] = None):
        self._engine = _engine_from_url(database_url, engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def _tables(self) -> tuple[Table, Table, Table]:
        if self._engine.dialect.name == "postgresql":
            return truth_artifacts_table, truth_states_table, trust_snapshots_table
        return (
            _sqlite_truth_artifacts_table,
            _sqlite_truth_states_table,
            _sqlite_trust_snapshots_table,
        )

    def ensure_schema(self) -> None:
        _ensure_kaori_schema(self._engine)

    def append(self, state: TruthState, snapshot: TrustSnapshot) -> dict:
        _validate_signed_artifact(state, snapshot)
        artifacts, latest, snapshots = self._tables()
        artifact = state.model_dump(mode="json")
        snapshot_artifact = snapshot.model_dump(mode="json")

        with self._engine.begin() as conn:
            existing = conn.execute(
                select(artifacts.c.artifact).where(
                    artifacts.c.state_hash == state.security.state_hash
                )
            ).first()
            if existing is not None:
                return dict(existing.artifact)

            stored_snapshot = conn.execute(
                select(snapshots.c.artifact).where(
                    snapshots.c.snapshot_id == snapshot.snapshot_id
                )
            ).first()
            if stored_snapshot is None:
                conn.execute(
                    snapshots.insert().values(
                        snapshot_id=snapshot.snapshot_id,
                        snapshot_hash=snapshot.snapshot_hash,
                        snapshot_time=_ensure_utc(snapshot.snapshot_time),
                        artifact=snapshot_artifact,
                    )
                )
            elif stored_snapshot.artifact != snapshot_artifact:
                raise ValueError("snapshot_id already exists with different content")

            if self._engine.dialect.name == "postgresql":
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:truthkey))"),
                    {"truthkey": state.truthkey},
                )

            revision = conn.execute(
                select(func.coalesce(func.max(artifacts.c.revision), 0) + 1).where(
                    artifacts.c.truthkey == state.truthkey
                )
            ).scalar_one()
            inserted = conn.execute(
                artifacts.insert().values(
                    truthkey=state.truthkey,
                    revision=revision,
                    state_hash=state.security.state_hash,
                    semantic_hash=state.security.semantic_hash,
                    claim_type_id=state.claim_type,
                    claim_type_hash=state.claim_type_hash,
                    trust_snapshot_id=snapshot.snapshot_id,
                    trust_snapshot_hash=snapshot.snapshot_hash,
                    status=state.status.value,
                    compiled_at=_ensure_utc(state.compile_inputs.compile_time),
                    artifact=artifact,
                )
            )
            artifact_id = inserted.inserted_primary_key[0]

            latest_values = {
                "truthkey": state.truthkey,
                "artifact": artifact,
                "compiled_at": _ensure_utc(state.compile_inputs.compile_time),
                "state_hash": state.security.state_hash,
                "revision": revision,
                "artifact_id": artifact_id,
            }
            conn.execute(
                _upsert_stmt(
                    latest,
                    self._engine,
                    latest_values,
                    "truthkey",
                    [
                        "artifact",
                        "compiled_at",
                        "state_hash",
                        "revision",
                        "artifact_id",
                    ],
                )
            )
        return artifact

    def get(self, truthkey: str) -> Optional[dict]:
        _, latest, _ = self._tables()
        with self._engine.begin() as conn:
            row = conn.execute(
                select(latest.c.artifact).where(latest.c.truthkey == truthkey)
            ).first()
        return None if row is None else dict(row.artifact)

    def get_history(self, truthkey: str) -> List[dict]:
        artifacts, _, _ = self._tables()
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(artifacts.c.artifact)
                .where(artifacts.c.truthkey == truthkey)
                .order_by(artifacts.c.revision)
            ).all()
        return [dict(row.artifact) for row in rows]
