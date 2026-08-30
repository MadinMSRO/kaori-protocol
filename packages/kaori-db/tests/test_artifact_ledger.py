"""Append-only Observation intake and compiled-artifact history."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from kaori_db import (
    InMemoryArtifactLedger,
    ObservationConflict,
    PostgresArtifactLedger,
    PostgresSignalStore,
)
from kaori_db.store import KAORI_SCHEMA, artifact_ledger_table, observations_table
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing


COMPILE_TIME = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
TRUTH_KEY = "ocean:coral_bleaching:h3:89b12c6b6ffffff:underwater:2026-01-07T00:00Z"
CLAIM_TYPE = "ocean.coral_bleaching.v1"


def _observation(*, reporter_id: str, observation_id: str, depth: float = 8.0) -> Observation:
    return Observation(
        observation_id=UUID(observation_id),
        claim_type=CLAIM_TYPE,
        reported_at=COMPILE_TIME,
        reporter_id=reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.BRONZE,
            trust_score=0.2,
            source_type="human",
        ),
        geo={"lat": -8.3405, "lon": 115.092},
        payload={"depth_meters": depth, "bleaching_percentage": 40},
        evidence_refs=[{"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64}],
    )


@pytest.fixture
def store(tmp_path) -> PostgresArtifactLedger:
    url = f"sqlite:///{tmp_path / 'ledger.db'}"
    impl = PostgresArtifactLedger(url)
    impl.ensure_schema()
    return impl


def test_ledger_tables_sqlalchemy_schema_is_kaori():
    assert KAORI_SCHEMA == "kaori"
    assert observations_table.schema == "kaori"
    assert observations_table.fullname == "kaori.observations"
    assert artifact_ledger_table.schema == "kaori"
    assert artifact_ledger_table.fullname == "kaori.artifact_ledger"


def test_schema_sql_creates_ledger_tables():
    sql = Path("packages/kaori-db/src/kaori_db/schema.sql").read_text()
    assert "kaori.observations" in sql
    assert "kaori.artifact_ledger" in sql
    assert "UNIQUE (truthkey, reporter_id)" in sql
    assert "public." not in sql


@pytest.mark.parametrize("ledger_factory", ["memory", "postgres"])
def test_record_observation_is_idempotent_on_hash(tmp_path, ledger_factory):
    ledger = (
        InMemoryArtifactLedger()
        if ledger_factory == "memory"
        else PostgresArtifactLedger(f"sqlite:///{tmp_path / 'idem.db'}")
    )
    if ledger_factory == "postgres":
        ledger.ensure_schema()
    observation = _observation(
        reporter_id="user:alice",
        observation_id="11111111-1111-1111-1111-111111111111",
    )
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, observation)
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, observation)
    stored = ledger.observations_for(TRUTH_KEY)
    assert len(stored) == 1
    assert stored[0]["reporter_id"] == "user:alice"
    assert stored[0]["payload"]["depth_meters"] == 8.0


@pytest.mark.parametrize("ledger_factory", ["memory", "postgres"])
def test_record_observation_rejects_mutated_resubmit(tmp_path, ledger_factory):
    ledger = (
        InMemoryArtifactLedger()
        if ledger_factory == "memory"
        else PostgresArtifactLedger(f"sqlite:///{tmp_path / 'conflict.db'}")
    )
    if ledger_factory == "postgres":
        ledger.ensure_schema()
    first = _observation(
        reporter_id="user:alice",
        observation_id="11111111-1111-1111-1111-111111111111",
        depth=8.0,
    )
    second = _observation(
        reporter_id="user:alice",
        observation_id="22222222-2222-2222-2222-222222222222",
        depth=12.0,
    )
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, first)
    with pytest.raises(ObservationConflict):
        ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, second)
    assert ledger.observations_for(TRUTH_KEY)[0]["payload"]["depth_meters"] == 8.0


@pytest.mark.parametrize("ledger_factory", ["memory", "postgres"])
def test_observations_for_keeps_independent_reporters(tmp_path, ledger_factory):
    ledger = (
        InMemoryArtifactLedger()
        if ledger_factory == "memory"
        else PostgresArtifactLedger(f"sqlite:///{tmp_path / 'multi.db'}")
    )
    if ledger_factory == "postgres":
        ledger.ensure_schema()
    alice = _observation(
        reporter_id="user:alice",
        observation_id="11111111-1111-1111-1111-111111111111",
    )
    bob = _observation(
        reporter_id="user:bob",
        observation_id="22222222-2222-2222-2222-222222222222",
        depth=11.0,
    )
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, alice)
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, bob)
    stored = ledger.observations_for(TRUTH_KEY)
    assert [row["reporter_id"] for row in stored] == ["user:alice", "user:bob"]
    assert ledger.observations_for("ocean:other") == []


@pytest.mark.parametrize("ledger_factory", ["memory", "postgres"])
def test_append_artifact_is_append_only_and_idempotent(tmp_path, ledger_factory):
    ledger = (
        InMemoryArtifactLedger()
        if ledger_factory == "memory"
        else PostgresArtifactLedger(f"sqlite:///{tmp_path / 'arts.db'}")
    )
    if ledger_factory == "postgres":
        ledger.ensure_schema()
    first = {"truthkey": TRUTH_KEY, "confidence": 0.2}
    second = {"truthkey": TRUTH_KEY, "confidence": 0.8}
    later = datetime(2026, 1, 7, 13, 0, tzinfo=timezone.utc)
    ledger.append_artifact(TRUTH_KEY, first, COMPILE_TIME)
    ledger.append_artifact(TRUTH_KEY, first, COMPILE_TIME)
    ledger.append_artifact(TRUTH_KEY, second, later)
    history = ledger.artifacts_for(TRUTH_KEY)
    assert [row["confidence"] for row in history] == [0.2, 0.8]


def test_shares_engine_with_signal_store(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    signals = PostgresSignalStore(url)
    signals.ensure_schema()
    ledger = PostgresArtifactLedger(engine=signals.engine)
    observation = _observation(
        reporter_id="user:alice",
        observation_id="11111111-1111-1111-1111-111111111111",
    )
    ledger.record_observation(TRUTH_KEY, CLAIM_TYPE, observation)
    ledger.append_artifact(TRUTH_KEY, {"truthkey": TRUTH_KEY}, COMPILE_TIME)
    assert ledger.observations_for(TRUTH_KEY)[0]["reporter_id"] == "user:alice"
    assert ledger.artifacts_for(TRUTH_KEY) == [{"truthkey": TRUTH_KEY}]
