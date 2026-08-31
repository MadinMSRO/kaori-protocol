"""Rule 2: score observers, validators, and claim types against final claims."""
from __future__ import annotations

from kaori_flow.settlement import (
    FINAL_FALSE,
    FINAL_TRUE,
    OUTCOME_CORRECT,
    OUTCOME_INCORRECT,
    ROLE_CLAIMTYPE,
    ROLE_OBSERVER,
    ROLE_VALIDATOR,
    participating_agent_ids,
    score_contributors,
)


def _obs(agent_id: str) -> dict:
    return {"reporter_id": agent_id}


def test_intermediate_status_does_not_settle():
    scores = score_contributors(
        status="INVESTIGATING",
        observations=[_obs("user:a")],
        votes=[{"agent_id": "ai:generalist_v1", "vote": "REJECT", "confidence": 0.2}],
        claim_type_id="ocean.vessel_anomaly.v1",
    )
    assert scores == []


def test_junk_closed_false_rewards_reject_and_penalizes_observers():
    scores = score_contributors(
        status=FINAL_FALSE,
        observations=[_obs("user:a"), _obs("user:b")],
        votes=[
            {"agent_id": "ai:generalist_v1", "vote": "REJECT", "confidence": 0.15},
            {"agent_id": "user:reviewer", "vote": "REJECT", "confidence": 0.9},
        ],
        claim_type_id="ocean.vessel_anomaly.v1",
    )
    by_id = {item.agent_id: item for item in scores}
    assert by_id["ai:generalist_v1"].outcome == OUTCOME_CORRECT
    assert by_id["ai:generalist_v1"].role == ROLE_VALIDATOR
    assert by_id["user:reviewer"].outcome == OUTCOME_CORRECT
    assert by_id["user:reviewer"].reckless is False
    assert by_id["user:a"].outcome == OUTCOME_INCORRECT
    assert by_id["user:a"].role == ROLE_OBSERVER
    assert by_id["user:b"].outcome == OUTCOME_INCORRECT
    assert by_id["claimtype:ocean.vessel_anomaly.v1"].outcome == OUTCOME_INCORRECT
    assert by_id["claimtype:ocean.vessel_anomaly.v1"].role == ROLE_CLAIMTYPE


def test_real_claim_closed_true_penalizes_wrong_validator():
    scores = score_contributors(
        status=FINAL_TRUE,
        observations=[_obs("user:a")],
        votes=[{"agent_id": "ai:generalist_v1", "vote": "REJECT", "confidence": 0.95}],
        claim_type_id="ocean.vessel_anomaly.v1",
    )
    by_id = {item.agent_id: item for item in scores}
    assert by_id["user:a"].outcome == OUTCOME_CORRECT
    assert by_id["ai:generalist_v1"].outcome == OUTCOME_INCORRECT
    assert by_id["ai:generalist_v1"].reckless is True
    assert by_id["claimtype:ocean.vessel_anomaly.v1"].outcome == OUTCOME_CORRECT


def test_abstain_is_omitted():
    scores = score_contributors(
        status=FINAL_TRUE,
        observations=[_obs("user:a")],
        votes=[{"agent_id": "user:reviewer", "vote": "ABSTAIN", "confidence": 0.4}],
        claim_type_id="ocean.vessel_anomaly.v1",
    )
    assert "user:reviewer" not in {item.agent_id for item in scores}


def test_observer_who_also_voted_is_scored_as_validator():
    scores = score_contributors(
        status=FINAL_FALSE,
        observations=[_obs("user:a")],
        votes=[{"agent_id": "user:a", "vote": "REJECT"}],
        claim_type_id="ocean.vessel_anomaly.v1",
    )
    matches = [item for item in scores if item.agent_id == "user:a"]
    assert len(matches) == 1
    assert matches[0].role == ROLE_VALIDATOR
    assert matches[0].outcome == OUTCOME_CORRECT


def test_participating_agent_ids_include_observers_voters_claimtype():
    ids = participating_agent_ids(
        observations=[_obs("user:a")],
        votes=[{"agent_id": "ai:generalist_v1", "vote": "RATIFY"}],
        claim_type_id="ocean.coral_bleaching.v1",
    )
    assert ids == [
        "ai:generalist_v1",
        "claimtype:ocean.coral_bleaching.v1",
        "user:a",
    ]
