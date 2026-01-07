"""
Kaori Flow — Signal Primitive

Immutable event envelopes (FLOW_SPEC Section 2.3).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class SignalType(str, Enum):
    """Signal type categories."""
    AUTOMATED_TRIGGER = "AUTOMATED_TRIGGER"  # IoT, External APIs
    MANUAL_TRIGGER = "MANUAL_TRIGGER"        # Human User
    SCHEDULED_TRIGGER = "SCHEDULED_TRIGGER"  # Scheduler
    SYSTEM_ALERT = "SYSTEM_ALERT"            # Internal Logic


class Signal(BaseModel):
    """
    Immutable event envelope (FLOW_SPEC Section 2.3).
    
    Signals propagate through the Network to trigger reactions.
    Signals are immutable; Probes are stateful.
    """
    model_config = ConfigDict(frozen=True)

    signal_id: UUID = Field(default_factory=uuid4)
    type: SignalType
    source_id: str  # Emitter (Sensor, User, System)
    timestamp: datetime
    data: Dict[str, Any] = Field(default_factory=dict)  # Payload
    truthkey: Optional[str] = None  # Optional associated TruthKey
