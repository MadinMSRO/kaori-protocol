"""PostgreSQL migration, immutability, replay, concurrency, and rollback."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from kaori_db import PostgresObservationStore, PostgresTruthArtifactStore
from kaori_truth import compile_truth_state
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.signing import sign_truth_state
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot
from sqlalchemy import create_engine, text

COMPILE_TIME = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
TRUTHKEY = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"


def _postgres_url() -> str | None:
    for key in ("KAORI_TEST_DATABASE_URL", "DATABASE_URL"):
        url = os.environ.get(key, "")
        if url.startswith("postgres"):
            return url
    return "postgresql://ubuntu@127.0.0.1:5432/kaori_test"


@pytest.fixture(scope="module")
def postgres_url():
    url = _postgres_url()
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")
    return url


@pytest.fixture
def engine(postgres_url):
    engine = create_engine(postgres_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS kaori CASCADE"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS kaori CASCADE"))
    engine.dispose()


def _claim_type() -> ClaimType:
    return ClaimType(
        id="earth.flood.v1",
        version=1,
        domain="earth",
        topic="flood",
        output_schema={
            "type": "object",
            "properties": {
                "severity": {"type": "string"},
                "water_level_meters": {"type": "number"},
                "observation_count": {"type": "integer"},
                "network_trust": {"type": "number"},
            },
        },
    )


def _observation(observation_id: str, reporter_id: str = "agent-001") -> Observation:
    return Observation(
        observation_id=UUID(observation_id),
        claim_type="earth.flood.v1",
        reported_at=COMPILE_TIME,
        reporter_id=reporter_id,
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": 4.175, "lon": 73.509},
        payload={"water_level": "1.5", "severity": "moderate"},
        evidence_refs=[
            EvidenceRef(
                uri=f"gs://kaori-observations/{observation_id}.jpg",
                sha256=observation_id.replace("-", "") * 2,
            )
        ],
    )


def _snapshot(snapshot_id: str, snapshot_time: datetime) -> TrustSnapshot:
    return TrustSnapshot.create(
        snapshot_id=snapshot_id,
        snapshot_time=snapshot_time,
        agent_trusts={
            "agent-001": AgentTrust(
                agent_id="agent-001",
                effective_trust=150.0,
                standing=150.0,
                derived_class="silver",
            )
        },
    )


def _signed_state(snapshot: TrustSnapshot, compile_time: datetime, reporter_id: str = "agent-001"):
    state = compile_truth_state(
        claim_type=_claim_type(),
        truth_key=TRUTHKEY,
        observations=[_observation("11111111-1111-1111-1111-111111111111", reporter_id)],
        trust_snapshot=snapshot,
        policy_version="earth.flood.v1.policy.1",
        compiler_version="2.0.0",
        compile_time=compile_time,
    )
    return sign_truth_state(state, compile_time)


def test_postgres_schema_migration_is_idempotent(engine):
    store = PostgresTruthArtifactStore(engine=engine)
    store.ensure_schema()
    store.ensure_schema()
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'kaori'"
                )
            )
        }
        triggers = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgname LIKE '%reject_mutation'"
                )
            )
        }
    assert {
        "signals",
        "observations",
        "trust_snapshots",
        "truth_artifacts",
        "truth_states",
    } <= tables
    assert {
        "signals_reject_mutation",
        "observations_reject_mutation",
        "trust_snapshots_reject_mutation",
        "truth_artifacts_reject_mutation",
    } <= triggers


def test_postgres_rejects_update_and_delete_on_immutable_tables(engine):
    observations = PostgresObservationStore(engine=engine)
    observations.ensure_schema()
    observations.append(
        _observation("11111111-1111-1111-1111-111111111111"),
        truthkey=TRUTHKEY,
        claim_type_hash="a" * 64,
        received_at=COMPILE_TIME,
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO kaori.signals "
                "(signal_id, signal_type, time, agent_id, object_id, payload, policy_version) "
                "VALUES ('sig-1', 'TEST', now(), 'agent-001', 'obj-1', '{}'::jsonb, '1')"
            )
        )
    for sql in (
        "UPDATE kaori.observations SET truthkey = 'mutated'",
        "DELETE FROM kaori.observations",
        "UPDATE kaori.signals SET agent_id = 'mutated'",
        "DELETE FROM kaori.signals",
    ):
        with engine.connect() as conn:
            with pytest.raises(Exception, match="append-only"):
                conn.execute(text(sql))
            conn.rollback()


def test_postgres_replay_returns_silver_history_in_revision_order(engine):
    store = PostgresTruthArtifactStore(engine=engine)
    store.ensure_schema()
    first_snapshot = _snapshot("snapshot-001", COMPILE_TIME)
    second_time = COMPILE_TIME + timedelta(hours=1)
    second_snapshot = _snapshot("snapshot-002", second_time)
    first = _signed_state(first_snapshot, COMPILE_TIME)
    second = _signed_state(second_snapshot, second_time)

    store.append(first, first_snapshot)
    store.append(second, second_snapshot)

    history = store.get_history(TRUTHKEY)
    assert [item["security"]["state_hash"] for item in history] == [
        first.security.state_hash,
        second.security.state_hash,
    ]
    assert store.get(TRUTHKEY)["security"]["state_hash"] == second.security.state_hash
    assert store.get(TRUTHKEY)["security"]["state_hash"] == history[-1]["security"]["state_hash"]


def test_postgres_rollback_leaves_gold_untouched_on_invalid_signature(engine):
    store = PostgresTruthArtifactStore(engine=engine)
    store.ensure_schema()
    snapshot = _snapshot("snapshot-001", COMPILE_TIME)
    valid = _signed_state(snapshot, COMPILE_TIME)
    store.append(valid, snapshot)

    unsigned = compile_truth_state(
        claim_type=_claim_type(),
        truth_key=TRUTHKEY,
        observations=[_observation("11111111-1111-1111-1111-111111111111")],
        trust_snapshot=snapshot,
        policy_version="earth.flood.v1.policy.1",
        compiler_version="2.0.0",
        compile_time=COMPILE_TIME + timedelta(hours=2),
    )
    with pytest.raises(ValueError, match="signed"):
        store.append(unsigned, snapshot)

    assert store.get(TRUTHKEY)["security"]["state_hash"] == valid.security.state_hash
    assert len(store.get_history(TRUTHKEY)) == 1
    with engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM kaori.truth_artifacts")).scalar_one()
    assert int(count) == 1


def test_postgres_concurrent_compiles_allocate_distinct_revisions(engine):
    store = PostgresTruthArtifactStore(engine=engine)
    store.ensure_schema()
    first_time = COMPILE_TIME
    second_time = COMPILE_TIME + timedelta(minutes=5)
    first_snapshot = _snapshot("snapshot-001", first_time)
    second_snapshot = _snapshot("snapshot-002", second_time)
    first = _signed_state(first_snapshot, first_time)
    second = _signed_state(second_snapshot, second_time)
    errors: list[BaseException] = []

    def write(state, snapshot) -> None:
        try:
            store.append(state, snapshot)
        except BaseException as exc:  # noqa: BLE001 — collect worker failures
            errors.append(exc)

    workers = [
        threading.Thread(target=write, args=(first, first_snapshot)),
        threading.Thread(target=write, args=(second, second_snapshot)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()

    assert errors == []
    history = store.get_history(TRUTHKEY)
    assert {item["security"]["state_hash"] for item in history} == {
        first.security.state_hash,
        second.security.state_hash,
    }
    with engine.begin() as conn:
        revisions = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT revision FROM kaori.truth_artifacts "
                    "WHERE truthkey = :truthkey ORDER BY revision"
                ),
                {"truthkey": TRUTHKEY},
            )
        ]
    assert revisions == [1, 2]


def test_postgres_observation_idempotency_and_conflict(engine):
    store = PostgresObservationStore(engine=engine)
    store.ensure_schema()
    observation = _observation("11111111-1111-1111-1111-111111111111")
    assert store.append(
        observation,
        truthkey=TRUTHKEY,
        claim_type_hash="a" * 64,
        received_at=COMPILE_TIME,
    )
    assert not store.append(
        observation,
        truthkey=TRUTHKEY,
        claim_type_hash="a" * 64,
        received_at=COMPILE_TIME,
    )
    changed = observation.model_copy(update={"payload": {"severity": "high"}})
    with pytest.raises(ValueError, match="different content"):
        store.append(
            changed,
            truthkey=TRUTHKEY,
            claim_type_hash="a" * 64,
            received_at=COMPILE_TIME,
        )
    assert store.count_distinct_reporters(TRUTHKEY) == 1
