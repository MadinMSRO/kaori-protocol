"""Compiler persists the full observation package and recorded votes."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from kaori_truth import compile_truth_state
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthstate import ContentBoundEvidenceRef
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot


COMPILE_TIME = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
TRUTH_KEY = "earth:flood:h3:886142a8e7fffff:surface:2026-01-07T12:00Z"


def _claim_type() -> ClaimType:
    return ClaimType(
        id="earth.flood.v1",
        version=1,
        domain="earth",
        topic="flood",
        risk_profile="monitor",
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


def _trust() -> TrustSnapshot:
    return TrustSnapshot.create(
        snapshot_id="snapshot-001",
        snapshot_time=COMPILE_TIME,
        agent_trusts={
            "agent-001": AgentTrust(
                agent_id="agent-001",
                effective_trust=150.0,
                standing=150.0,
                derived_class="silver",
                flags=[],
            )
        },
    )


def _observation() -> Observation:
    return Observation(
        observation_id=UUID("11111111-1111-1111-1111-111111111111"),
        claim_type="earth.flood.v1",
        reported_at=COMPILE_TIME,
        reporter_id="agent-001",
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": 4.175, "lon": 73.509},
        payload={"water_level": "1.5", "severity": "moderate"},
        evidence_refs=[
            EvidenceRef(uri="gs://kaori-evidence/photo1.jpg", sha256="a" * 64)
        ],
    )


def test_compile_inputs_include_canonical_observation_package():
    observation = _observation()
    state = compile_truth_state(
        claim_type=_claim_type(),
        truth_key=TRUTH_KEY,
        observations=[observation],
        trust_snapshot=_trust(),
        policy_version="earth.flood.v1.policy.1",
        compiler_version="1.0.0",
        compile_time=COMPILE_TIME,
    )

    package = state.compile_inputs.observations[0]
    assert package["geo"] == {"lat": 4.175, "lon": 73.509}
    assert package["payload"]["water_level"] == "1.5"
    assert package["evidence_refs"] == [
        {"uri": "gs://kaori-evidence/photo1.jpg", "sha256": "a" * 64}
    ]
    assert state.compile_inputs.observation_hashes == [observation.hash()]
    assert isinstance(state.evidence_refs[0], ContentBoundEvidenceRef)
    assert state.evidence_refs[0].uri == "gs://kaori-evidence/photo1.jpg"
    assert state.evidence_refs[0].sha256 == "a" * 64
    dumped = state.model_dump(mode="json")
    assert dumped["evidence_refs"] == [
        {"uri": "gs://kaori-evidence/photo1.jpg", "sha256": "a" * 64}
    ]
    assert dumped["consensus"] is None


def test_recorded_votes_land_on_consensus_votes():
    votes = [
        {
            "agent_id": "ai:generalist_v1",
            "truthkey_id": TRUTH_KEY,
            "window_id": f"window:{TRUTH_KEY}",
            "vote": "REJECT",
            "vote_type": "REJECT",
            "confidence": 0.11,
            "timestamp": "2026-01-07T12:30:00Z",
            "signal_type": "VALIDATION_VOTE",
        }
    ]
    state = compile_truth_state(
        claim_type=_claim_type(),
        truth_key=TRUTH_KEY,
        observations=[_observation()],
        trust_snapshot=_trust(),
        policy_version="earth.flood.v1.policy.1",
        compiler_version="1.0.0",
        compile_time=COMPILE_TIME,
        votes=votes,
        ai_scores=[0.11],
    )

    assert state.consensus is not None
    assert state.consensus.votes == votes
    assert state.consensus.votes[0]["agent_id"] == "ai:generalist_v1"
    assert state.consensus.votes[0]["vote"] == "REJECT"
    dumped = state.model_dump(mode="json")
    assert dumped["consensus"]["votes"][0]["signal_type"] == "VALIDATION_VOTE"
    assert "signature" not in dumped["consensus"]["votes"][0]
