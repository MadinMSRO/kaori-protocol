"""Projection of a compiled claim: confidence plus every participating agent."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from kaori_flow.settlement import (
    claimtype_agent_id,
    observer_ids,
    participating_agent_ids,
    role_for,
    voter_ids,
)
from kaori_truth.primitives.truthstate import TruthState
from kaori_truth.trust_snapshot import TrustSnapshot


def claim_agent_rows(
    state: TruthState,
    snapshot: TrustSnapshot,
    claim_type_id: str,
) -> List[Dict[str, Any]]:
    """Dataset rows: agent_id, role, standing, effective_trust. No minted numbers."""
    observations = list(state.compile_inputs.observations or [])
    votes = list((state.consensus.votes if state.consensus else None) or [])
    observers = observer_ids(observations)
    voters = voter_ids(votes)
    claimtype_id = claimtype_agent_id(claim_type_id)
    rows: List[Dict[str, Any]] = []
    for agent_id in participating_agent_ids(
        observations=observations,
        votes=votes,
        claim_type_id=claim_type_id,
    ):
        trust = snapshot.get_agent_trust(agent_id)
        rows.append(
            {
                "agent_id": agent_id,
                "role": role_for(
                    agent_id,
                    observers=observers,
                    voters=voters,
                    claimtype_id=claimtype_id,
                ),
                "standing": None if trust is None else trust.standing,
                "effective_trust": None if trust is None else trust.effective_trust,
            }
        )
    return rows


def attach_claim_agents(
    artifact: Dict[str, Any],
    snapshot: Optional[TrustSnapshot],
    claim_type_id: str,
    state: Optional[TruthState] = None,
) -> Dict[str, Any]:
    """Add agents[] to a dumped TruthState. Does not change signed hashes."""
    if snapshot is None or state is None:
        artifact.setdefault("agents", [])
        return artifact
    artifact["agents"] = claim_agent_rows(state, snapshot, claim_type_id)
    return artifact
