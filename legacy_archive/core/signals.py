"""
Kaori Core — Signal Primitives

Signals are the universal events that propagate through the Network to trigger reactions.
Everything is a Signal: Sensor alerts, internal system flags, and human requests.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    """
    Categorization of signal sources.
    """
    AUTOMATED_TRIGGER = "AUTOMATED_TRIGGER"  # IoT, API feeds
    MANUAL_TRIGGER = "MANUAL_TRIGGER"        # Human intent (Admin/User)
    SCHEDULED_TRIGGER = "SCHEDULED_TRIGGER"  # Cron/Time-based
    SYSTEM_ALERT = "SYSTEM_ALERT"            # Internal logic (Contradiction/Low Confidence)


class Signal(BaseModel):
    """
    Immutable event envelope for all system triggers.
    """
    signal_id: UUID = Field(default_factory=uuid4)
    type: SignalType
    source_id: str  # ReporterID (Human) or ComponentID (System/Sensor)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Context
    truthkey: Optional[str] = None  # If related to a specific truth state
    
    # Payload (Flexible)
    # For MANUAL: contains desired mission params (scope, bounty)
    # For AUTOMATED: contains raw sensor data
    data: dict[str, Any] = Field(default_factory=dict)
