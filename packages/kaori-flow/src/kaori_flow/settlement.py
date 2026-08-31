"""
Score every participating agent against a final TruthState.

FLOW_SPEC Rule 2: standing moves when signals align with VERIFIED_TRUE /
VERIFIED_FALSE, not when a validator first votes. Intermediate statuses
do not settle.

An Observation is an implicit RATIFY of the claim. A ValidationSignal is
explicit RATIFY / REJECT / ABSTAIN. ABSTAIN is omitted (safe).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Set

FINAL_TRUE = "VERIFIED_TRUE"
FINAL_FALSE = "VERIFIED_FALSE"
FINAL_STATUSES = frozenset({FINAL_TRUE, FINAL_FALSE})

ROLE_OBSERVER = "observer"
ROLE_VALIDATOR = "validator"
ROLE_CLAIMTYPE = "claimtype"

OUTCOME_CORRECT = "correct"
OUTCOME_INCORRECT = "incorrect"
OUTCOME_UNKNOWN = "unknown"

RECKLESS_CONFIDENCE_FLOOR = 0.7
RECKLESS_PENALTY_DEFAULT = 7.0


@dataclass(frozen=True)
class AgentScore:
    """One agent's alignment with a compiled claim."""

    agent_id: str
    role: str
    outcome: str
    reckless: bool = False
    confidence: Optional[float] = None


def _vote_field(vote: dict, *names: str, default=None):
    for name in names:
        if name in vote and vote[name] is not None:
            return vote[name]
    return default


def vote_agent_id(vote: dict) -> str:
    return str(_vote_field(vote, "agent_id", "voter_id", default="") or "")


def vote_value(vote: dict) -> str:
    return str(_vote_field(vote, "vote", "vote_type", default="") or "").upper()


def vote_confidence(vote: dict) -> Optional[float]:
    raw = _vote_field(vote, "confidence")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def is_human_agent(agent_id: str) -> bool:
    return agent_id.startswith("user:") or agent_id.startswith("human:")


def observer_ids(observations: Sequence[Any]) -> Set[str]:
    ids: Set[str] = set()
    for observation in observations:
        reporter_id = getattr(observation, "reporter_id", None)
        if reporter_id is None and isinstance(observation, dict):
            reporter_id = observation.get("reporter_id")
        if reporter_id:
            ids.add(str(reporter_id))
    return ids


def voter_ids(votes: Optional[Iterable[dict]]) -> Set[str]:
    ids: Set[str] = set()
    for vote in votes or []:
        agent_id = vote_agent_id(vote)
        if agent_id:
            ids.add(agent_id)
    return ids


def claimtype_agent_id(claim_type_id: str) -> str:
    if claim_type_id.startswith("claimtype:"):
        return claim_type_id
    return f"claimtype:{claim_type_id}"


def role_for(
    agent_id: str,
    *,
    observers: Set[str],
    voters: Set[str],
    claimtype_id: str,
) -> str:
    if agent_id == claimtype_id:
        return ROLE_CLAIMTYPE
    if agent_id in voters:
        return ROLE_VALIDATOR
    if agent_id in observers:
        return ROLE_OBSERVER
    return ROLE_OBSERVER


def _align_implicit_ratify(status: str) -> str:
    if status == FINAL_TRUE:
        return OUTCOME_CORRECT
    if status == FINAL_FALSE:
        return OUTCOME_INCORRECT
    return OUTCOME_UNKNOWN


def _align_vote(status: str, vote: str) -> Optional[str]:
    if vote == "ABSTAIN":
        return None
    if vote not in ("RATIFY", "REJECT"):
        return None
    if status == FINAL_TRUE:
        return OUTCOME_CORRECT if vote == "RATIFY" else OUTCOME_INCORRECT
    if status == FINAL_FALSE:
        return OUTCOME_CORRECT if vote == "REJECT" else OUTCOME_INCORRECT
    return OUTCOME_UNKNOWN


def score_contributors(
    *,
    status: str,
    observations: Sequence[Any],
    votes: Optional[Sequence[dict]],
    claim_type_id: str,
) -> List[AgentScore]:
    """
    Per-agent outcomes for a compiled status.

    Intermediate statuses return an empty list — the caller emits a single
    unknown TRUTHSTATE_EMITTED for audit. Final statuses return one score
    per participating agent.
    """
    status_value = getattr(status, "value", status)
    if status_value not in FINAL_STATUSES:
        return []

    observers = observer_ids(observations)
    votes_list = list(votes or [])
    voters = voter_ids(votes_list)
    claimtype_id = claimtype_agent_id(claim_type_id)
    latest_vote: dict[str, dict] = {}
    for vote in votes_list:
        agent_id = vote_agent_id(vote)
        if agent_id:
            latest_vote[agent_id] = vote

    scores: List[AgentScore] = []
    seen: Set[str] = set()

    for agent_id, vote in latest_vote.items():
        outcome = _align_vote(status_value, vote_value(vote))
        if outcome is None:
            continue
        confidence = vote_confidence(vote)
        reckless = (
            outcome == OUTCOME_INCORRECT
            and confidence is not None
            and confidence >= RECKLESS_CONFIDENCE_FLOOR
        )
        scores.append(
            AgentScore(
                agent_id=agent_id,
                role=ROLE_VALIDATOR,
                outcome=outcome,
                reckless=reckless,
                confidence=confidence,
            )
        )
        seen.add(agent_id)

    for agent_id in sorted(observers):
        if agent_id in seen:
            continue
        scores.append(
            AgentScore(
                agent_id=agent_id,
                role=ROLE_OBSERVER,
                outcome=_align_implicit_ratify(status_value),
            )
        )
        seen.add(agent_id)

    if claimtype_id not in seen:
        scores.append(
            AgentScore(
                agent_id=claimtype_id,
                role=ROLE_CLAIMTYPE,
                outcome=_align_implicit_ratify(status_value),
            )
        )
    return scores


def quality_score_from_confidence(confidence: float) -> float:
    """Map TruthState.confidence onto the reducer quality term."""
    value = float(confidence)
    if value <= 1.0:
        return max(0.0, value) * 100.0
    return max(0.0, value)


def participating_agent_ids(
    *,
    observations: Sequence[Any],
    votes: Optional[Sequence[dict]],
    claim_type_id: str,
) -> List[str]:
    """Stable agent id list for a TrustSnapshot: observers, voters, claim type."""
    ids = observer_ids(observations) | voter_ids(votes)
    ids.add(claimtype_agent_id(claim_type_id))
    return sorted(ids)
