"""
Adapter so FlowCore satisfies the TrustProvider protocol TruthOrchestrator calls.

Does not compute trust in the compiler. Trust remains a Flow input.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from kaori_flow import FlowCore, TrustContext
from kaori_truth.trust_snapshot import TrustSnapshot


class FlowTrustProvider:
    """TrustProvider that reads standings from FlowCore."""

    def __init__(self, flow: FlowCore):
        self.flow = flow

    def get_trust_snapshot(
        self,
        agent_ids: List[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        return self.flow.get_trust_snapshot(
            agent_ids=agent_ids,
            context=TrustContext(
                claimtype_id=claim_type,
                snapshot_time=snapshot_time,
            ),
        )

    def get_power(self, agent_id: str, claim_type: str) -> float:
        snapshot = self.get_trust_snapshot(
            [agent_id], claim_type, datetime.now(timezone.utc)
        )
        return snapshot.get_trust(agent_id)
