"""
Status comes from ClaimType YAML human_gating + autovalidation + votes.

No claim_type id forks. No invented VALIDATION status.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from kaori_truth import compile_truth_state
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthstate import TruthStatus
from kaori_truth.trust_snapshot import AgentTrust, TrustSnapshot

SCHEMAS = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
COMPILE_TIME = datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc)
PROTOCOL_STATUSES = {status.value for status in TruthStatus}


def _observation(*, claim_type: str, payload: dict) -> Observation:
    return Observation(
        observation_id=UUID("11111111-1111-1111-1111-111111111111"),
        claim_type=claim_type,
        reported_at=COMPILE_TIME,
        reporter_id="agent-001",
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.75,
            source_type="human",
        ),
        geo={"lat": -8.3405, "lon": 115.0920},
        payload=payload,
        evidence_refs=[EvidenceRef(uri="gs://kaori-evidence/a.jpg", sha256="a" * 64)],
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


def _compile(claim_type: ClaimType, payload: dict, *, votes=None, ai_scores=None):
    return compile_truth_state(
        claim_type=claim_type,
        truth_key="ocean:topic:h3:abc:surface:2026-01-07T00:00Z",
        observations=[_observation(claim_type=claim_type.id, payload=payload)],
        trust_snapshot=_trust(),
        policy_version=claim_type.policy_version,
        compile_time=COMPILE_TIME,
        votes=votes,
        ai_scores=ai_scores,
    )


def test_no_validation_status_in_protocol_enum():
    assert "VALIDATION" not in PROTOCOL_STATUSES
    assert TruthStatus.PENDING_HUMAN_REVIEW.value == "PENDING_HUMAN_REVIEW"


def test_always_require_human_false_critical_is_not_forced_review():
    """risk_profile critical is not enough. YAML always_require_human is the gate."""
    claim_type = ClaimType(
        id="earth.generic.v1",
        version=1,
        domain="earth",
        topic="generic",
        risk_profile="critical",
        output_schema={
            "type": "object",
            "properties": {"amount": {"type": "number"}},
        },
    )
    claim_type._raw_config = {
        "human_gating": {
            "always_require_human": False,
            "required_for_risk_profiles": ["critical"],
            "min_trust_score": 0.35,
            "min_ai_confidence": 0.82,
        }
    }
    state = _compile(claim_type, {"amount": 1.0})
    assert state.status != TruthStatus.PENDING_HUMAN_REVIEW
    assert state.status.value in PROTOCOL_STATUSES
    assert state.status != "VALIDATION"


def test_always_require_human_true_stays_review_after_ratify():
    claim_type = ClaimType(
        id="earth.generic.v1",
        version=1,
        domain="earth",
        topic="generic",
        risk_profile="monitor",
        output_schema={
            "type": "object",
            "properties": {"amount": {"type": "number"}},
        },
    )
    claim_type._raw_config = {
        "human_gating": {
            "always_require_human": True,
            "required_for_risk_profiles": ["critical"],
        }
    }
    state = _compile(
        claim_type,
        {"amount": 1.0},
        votes=[{"agent_id": "ai:generalist_v1", "vote": "RATIFY", "confidence": 0.99}],
        ai_scores=[0.99],
    )
    assert state.status == TruthStatus.PENDING_HUMAN_REVIEW


def test_vessel_yaml_critical_is_not_pending_human_review():
    claim_type = load_claim_type(SCHEMAS / "ocean" / "vessel_anomaly_v1.yaml")
    assert claim_type.risk_profile == "critical"
    assert claim_type.get_config()["human_gating"]["always_require_human"] is False
    state = _compile(
        claim_type,
        {"observation_duration_min": 15, "vessels": [{"id": "v1"}]},
    )
    assert state.status != TruthStatus.PENDING_HUMAN_REVIEW
    assert state.status.value in PROTOCOL_STATUSES


def test_coral_yaml_always_require_human_is_pending_human_review():
    claim_type = load_claim_type(SCHEMAS / "ocean" / "coral_bleaching_v1.yaml")
    assert claim_type.get_config()["human_gating"]["always_require_human"] is True
    state = _compile(
        claim_type,
        {"depth_meters": 8.0, "bleaching_percentage": 40},
        votes=[{"agent_id": "ai:generalist_v1", "vote": "RATIFY", "confidence": 0.99}],
        ai_scores=[0.99],
    )
    assert state.status == TruthStatus.PENDING_HUMAN_REVIEW


def test_coral_human_ratify_after_ai_closes_verified_true():
    claim_type = load_claim_type(SCHEMAS / "ocean" / "coral_bleaching_v1.yaml")
    state = _compile(
        claim_type,
        {"depth_meters": 8.0, "bleaching_percentage": 40},
        votes=[
            {"agent_id": "ai:generalist_v1", "vote": "RATIFY", "confidence": 0.99},
            {"agent_id": "user:reviewer", "vote": "RATIFY", "confidence": 0.8},
        ],
        ai_scores=[0.99],
    )
    assert state.status == TruthStatus.VERIFIED_TRUE


def test_vessel_human_reject_closes_verified_false():
    claim_type = load_claim_type(SCHEMAS / "ocean" / "vessel_anomaly_v1.yaml")
    state = _compile(
        claim_type,
        {"observation_duration_min": 15, "vessels": [{"id": "v1"}]},
        votes=[
            {"agent_id": "ai:generalist_v1", "vote": "REJECT", "confidence": 0.1},
            {"agent_id": "user:reviewer", "vote": "REJECT", "confidence": 0.85},
        ],
        ai_scores=[0.1],
    )
    assert state.status == TruthStatus.VERIFIED_FALSE


def test_human_confidence_is_not_treated_as_ai_mean():
    claim_type = load_claim_type(SCHEMAS / "ocean" / "coral_bleaching_v1.yaml")
    state = _compile(
        claim_type,
        {"depth_meters": 8.0, "bleaching_percentage": 40},
        votes=[{"agent_id": "user:reviewer", "vote": "RATIFY", "confidence": 0.99}],
    )
    # Human 0.99 must not be read as AI mean (that would VERIFIED_TRUE).
    assert state.status != TruthStatus.VERIFIED_TRUE
