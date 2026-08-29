"""
Internal Flow helpers for V4 validation signals.

Kaori records signed validator output. It does not execute validators inside
the compiler. record_validation_vote is not an HTTP route.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kaori_flow import FlowCore
from kaori_flow.primitives.signal import Signal, SignalTypes


BOUNCER_AGENT_ID = "ai:bouncer_v1"
VALIDATION_VOTES = ("RATIFY", "REJECT", "ABSTAIN")


def agent_is_known(flow: FlowCore, agent_id: str) -> bool:
    if agent_id in flow.get_all_standings():
        return True
    return bool(flow.store.get_for_agent(agent_id))


def ensure_bouncer_registered(flow: FlowCore) -> None:
    """Register Flow agent ai:bouncer_v1 (role validator) if unknown. Idempotent."""
    if not agent_is_known(flow, BOUNCER_AGENT_ID):
        flow.register_agent(BOUNCER_AGENT_ID, role="validator")


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
