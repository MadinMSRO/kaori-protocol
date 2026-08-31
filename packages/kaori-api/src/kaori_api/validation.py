"""
Internal Flow helpers for V4 validation signals.

Kaori records signed validator output. It does not execute validators inside
the compiler. HTTP ingest is POST /v1/validate — not a public map vote.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kaori_flow import FlowCore
from kaori_flow.primitives.agent import AgentType, create_agent_id
from kaori_flow.primitives.signal import Signal, SignalTypes

GENERALIST_AGENT_ID = "ai:generalist_v1"
# FLOW_SPEC Rule 2: claimtype:{id} is a claimtype agent. AgentType already names this.
CLAIMTYPE_ROLE = AgentType.CLAIMTYPE.value
VALIDATION_VOTES = ("RATIFY", "REJECT", "ABSTAIN")


def agent_is_known(flow: FlowCore, agent_id: str) -> bool:
    if agent_id in flow.get_all_standings():
        return True
    return bool(flow.store.get_for_agent(agent_id))


def ensure_agent_registered(
    flow: FlowCore,
    agent_id: str,
    *,
    role: str,
    agent_type: str | None = None,
) -> None:
    """Register any Flow agent if unknown. Idempotent. Role must already exist in FLOW_SPEC."""
    if not agent_is_known(flow, agent_id):
        if agent_type is None:
            flow.register_agent(agent_id, role=role)
        else:
            flow.register_agent(agent_id, role=role, agent_type=agent_type)


def ensure_validator_registered(flow: FlowCore, agent_id: str) -> None:
    """Register the selected validator agent if unknown. Idempotent."""
    ensure_agent_registered(flow, agent_id, role="validator")


def ensure_generalist_registered(flow: FlowCore) -> None:
    """Register the CLIP generalist voter. Idempotent."""
    ensure_validator_registered(flow, GENERALIST_AGENT_ID)


def claimtype_agent_id(claim_type_id: str) -> str:
    """FLOW_SPEC Rule 2 / AgentType.CLAIMTYPE: claimtype:{claim_type_id}."""
    return create_agent_id(AgentType.CLAIMTYPE, claim_type_id)


def ensure_claimtype_registered(flow: FlowCore, claim_type_id: str) -> str:
    """
    Register Flow agent claimtype:{claim_type_id} if unknown. Idempotent.

    Generic over whatever claim_type_id compile already loaded from YAML.
    Does not mint standing — GET /v1/standing reads reducer output from signals.
    """
    agent_id = claimtype_agent_id(claim_type_id)
    ensure_agent_registered(
        flow,
        agent_id,
        role=CLAIMTYPE_ROLE,
        agent_type=AgentType.CLAIMTYPE.value,
    )
    return agent_id


def record_validation_vote(
    flow: FlowCore,
    *,
    agent_id: str,
    truthkey_id: str,
    window_id: str,
    vote: str,
    signature: str,
    confidence: Optional[float] = None,
    time: Optional[datetime] = None,
) -> Signal:
    """
    Emit SignalTypes.VALIDATION_VOTE into the existing SignalStore.

    Payload matches FLOW_SPEC ValidationSignal. object_id is the truthkey.
    Does not compile, does not change HTTP surface, does not run a model.
    """
    if vote not in VALIDATION_VOTES:
        raise ValueError("vote must be RATIFY, REJECT, or ABSTAIN")
    if signature is None or (isinstance(signature, str) and not signature.strip()):
        raise ValueError("signature is required")
    if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
        raise ValueError("confidence must be between 0 and 1")

    emitted_at = time or datetime.now(timezone.utc)
    payload = {
        "agent_id": agent_id,
        "truthkey_id": truthkey_id,
        "window_id": window_id,
        "vote": vote,
        "timestamp": emitted_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "signature": signature,
    }
    if confidence is not None:
        payload["confidence"] = float(confidence)

    signal = Signal(
        signal_type=SignalTypes.VALIDATION_VOTE,
        time=emitted_at,
        agent_id=agent_id,
        object_id=truthkey_id,
        payload=payload,
        policy_version=flow.policy.version,
        signature=signature,
    )
    flow.emit(signal)
    return signal


def record_observation_submitted(
    flow: FlowCore,
    *,
    observer_id: str,
    truthkey_id: str,
    observation_id: str,
    observation_hash: str,
    claim_type_id: str,
) -> Signal:
    """Emit OBSERVATION_SUBMITTED after Bronze admit. Does not move standing."""
    from kaori_flow.primitives.signal import SignalContext

    signal = Signal(
        signal_type=SignalTypes.OBSERVATION_SUBMITTED,
        time=datetime.now(timezone.utc),
        agent_id=observer_id,
        object_id=truthkey_id,
        context=SignalContext(claimtype_id=claim_type_id),
        payload={
            "observation_id": observation_id,
            "observation_hash": observation_hash,
            "claim_type_id": claim_type_id,
        },
        policy_version=flow.policy.version,
    )
    flow.emit(signal)
    return signal
