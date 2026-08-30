"""Bronze observations, frozen trust, and Silver revisions are immutable records."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from kaori_db import (
    PostgresObservationStore,
    PostgresTrustSnapshotStore,
    PostgresTruthArtifactStore,
)
from kaori_truth import compile_truth_state
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.signing import sign_truth_state
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot

COMPILE_TIME = datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc)
TRUTHKEY = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"


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


def _signed_state(snapshot: TrustSnapshot, compile_time: datetime):
    state = compile_truth_state(
        claim_type=_claim_type(),
        truth_key=TRUTHKEY,
        observations=[
            _observation("11111111-1111-1111-1111-111111111111")
        ],
        trust_snapshot=snapshot,
        policy_version="earth.flood.v1.policy.1",
        compiler_version="2.0.0",
        compile_time=compile_time,
    )
    return sign_truth_state(state, compile_time)


def test_observations_are_idempotent_but_conflicting_content_is_rejected(tmp_path):
    store = PostgresObservationStore(f"sqlite:///{tmp_path / 'bronze.db'}")
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


def test_distinct_reporters_ignore_repeat_observations_from_same_reporter(tmp_path):
    store = PostgresObservationStore(f"sqlite:///{tmp_path / 'reporters.db'}")
    store.ensure_schema()
    for observation_id in (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ):
        store.append(
            _observation(observation_id),
            truthkey=TRUTHKEY,
            claim_type_hash="a" * 64,
            received_at=COMPILE_TIME,
        )
    store.append(
        _observation(
            "33333333-3333-3333-3333-333333333333",
            reporter_id="agent-002",
        ),
        truthkey=TRUTHKEY,
        claim_type_hash="a" * 64,
        received_at=COMPILE_TIME,
    )

    assert len(store.get_for_truthkey(TRUTHKEY)) == 3
    assert store.count_distinct_reporters(TRUTHKEY) == 2


def test_same_trust_hash_can_be_frozen_at_multiple_snapshot_times(tmp_path):
    store = PostgresTrustSnapshotStore(f"sqlite:///{tmp_path / 'trust.db'}")
    store.ensure_schema()
    first = _snapshot("snapshot-001", COMPILE_TIME)
    second = _snapshot("snapshot-002", COMPILE_TIME + timedelta(hours=1))

    assert first.snapshot_hash == second.snapshot_hash
    assert store.append(first)
    assert store.append(second)
    assert store.get("snapshot-001") == first
    assert store.get("snapshot-002") == second


def test_signed_truth_states_append_silver_revisions_and_refresh_gold(tmp_path):
    store = PostgresTruthArtifactStore(f"sqlite:///{tmp_path / 'ledger.db'}")
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


def test_ledger_rejects_mismatched_snapshot(tmp_path):
    store = PostgresTruthArtifactStore(f"sqlite:///{tmp_path / 'mismatch.db'}")
    store.ensure_schema()
    snapshot = _snapshot("snapshot-001", COMPILE_TIME)
    state = _signed_state(snapshot, COMPILE_TIME)
    mismatched = TrustSnapshot.create(
        snapshot_id="snapshot-other",
        snapshot_time=COMPILE_TIME,
        agent_trusts={},
    )

    with pytest.raises(ValueError, match="different trust snapshot"):
        store.append(state, mismatched)
