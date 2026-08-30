"""PostgresTruthStateStore upserts kaori.truth_states (not public.truths)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kaori_db import PostgresTruthStateStore
from kaori_db.store import KAORI_SCHEMA, PostgresSignalStore, truth_states_table


def test_truth_states_table_sqlalchemy_schema_is_kaori():
    assert KAORI_SCHEMA == "kaori"
    assert truth_states_table.schema == "kaori"
    assert truth_states_table.fullname == "kaori.truth_states"


def test_schema_sql_creates_kaori_truth_states_not_public():
    sql = Path("packages/kaori-db/src/kaori_db/schema.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS kaori" in sql
    assert "kaori.signals" in sql
    assert "kaori.observations" in sql
    assert "kaori.trust_snapshots" in sql
    assert "kaori.truth_artifacts" in sql
    assert "kaori.truth_states" in sql
    assert "artifact" in sql and "JSONB" in sql
    assert "public." not in sql


def test_upsert_and_get_by_truthkey(tmp_path):
    url = f"sqlite:///{tmp_path / 'truths.db'}"
    store = PostgresTruthStateStore(url)
    store.ensure_schema()
    compiled_at = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
    artifact = {
        "truthkey": "ocean:coral_bleaching:h3:abc:underwater:2026-01-07T00:00Z",
        "status": "PENDING_HUMAN_REVIEW",
        "evidence_refs": [
            {"uri": "gs://kaori-evidence/coral1.jpg", "sha256": "a" * 64}
        ],
        "confidence": 0.4,
    }
    store.upsert(artifact["truthkey"], artifact, compiled_at)
    stored = store.get(artifact["truthkey"])
    assert stored == artifact
    assert stored["evidence_refs"] == artifact["evidence_refs"]


def test_upsert_overwrites_on_truthkey(tmp_path):
    url = f"sqlite:///{tmp_path / 'truths.db'}"
    store = PostgresTruthStateStore(url)
    store.ensure_schema()
    key = "ocean:coral_bleaching:h3:abc:underwater:2026-01-07T00:00Z"
    first_at = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
    second_at = datetime(2026, 1, 7, 13, 0, tzinfo=timezone.utc)
    store.upsert(key, {"truthkey": key, "confidence": 0.1, "evidence_refs": []}, first_at)
    store.upsert(
        key,
        {
            "truthkey": key,
            "confidence": 0.9,
            "evidence_refs": [{"uri": "gs://kaori-evidence/a.jpg", "sha256": "a" * 64}],
        },
        second_at,
    )
    stored = store.get(key)
    assert stored["confidence"] == 0.9
    assert stored["evidence_refs"] == [
        {"uri": "gs://kaori-evidence/a.jpg", "sha256": "a" * 64}
    ]


def test_get_unknown_returns_none(tmp_path):
    url = f"sqlite:///{tmp_path / 'truths.db'}"
    store = PostgresTruthStateStore(url)
    store.ensure_schema()
    assert store.get("ocean:missing") is None


def test_shares_engine_with_signal_store(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    signals = PostgresSignalStore(url)
    signals.ensure_schema()
    truths = PostgresTruthStateStore(engine=signals.engine)
    truths.upsert(
        "ocean:k",
        {
            "truthkey": "ocean:k",
            "evidence_refs": [{"uri": "gs://kaori-evidence/u.jpg", "sha256": "c" * 64}],
        },
        datetime(2026, 1, 7, tzinfo=timezone.utc),
    )
    assert truths.get("ocean:k")["evidence_refs"] == [
        {"uri": "gs://kaori-evidence/u.jpg", "sha256": "c" * 64}
    ]
