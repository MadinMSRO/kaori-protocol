"""
Kaori Flow — Signal Processor

The central nervous system that reacts to Signals and manages Probe lifecycles.
Persists all data to database.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from uuid import UUID
import hashlib
import json

from core.models import Probe, ProbeStatus
from core.signals import Signal, SignalType
from core.db.database import SessionLocal
from core.db.models import ProbeModel, SignalLogModel


class SignalProcessor:
    """
    Reflexively processes signals into actions (Probes).
    Persists all data to database.
    """

    def process_signal(self, signal: Signal) -> Probe:
        """
        Main entry point for the Event Bus.
        """
        with SessionLocal() as db:
            # 1. Log the signal for audit
            self._log_signal(db, signal)
            
            # 2. Compute Deterministic Probe Key
            # Default scope/claim from signal data or fallbacks
            claim_type = signal.data.get("claim_type", "earth.flood.v1")
            scope = signal.data.get("scope", {"type": "h3", "value": "unknown"})
            probe_key = self._compute_probe_key(claim_type, scope)
            
            # 3. Deduplication: Check if Active probe exists for this key
            existing_probe_model = db.query(ProbeModel).filter(
                ProbeModel.probe_key == probe_key,
                ProbeModel.status.in_([ProbeStatus.ACTIVE, ProbeStatus.ASSIGNED, ProbeStatus.IN_PROGRESS])
            ).first()
            
            if existing_probe_model:
                # Mutation: Link signal to existing probe
                return self._update_existing_probe(db, existing_probe_model, signal)
            else:
                # Creation: Create new Probe
                probe = self._construct_probe_from_signal(signal, probe_key, claim_type, scope)
                
                # 4. Apply Policy (Auto-Active vs Proposed)
                probe.status = self._apply_activation_policy(signal)
                
                # 5. Persist to DB
                return self._save_new_probe(db, probe)

    def _log_signal(self, db, signal: Signal):
        """Log signal to audit trail."""
        log_entry = SignalLogModel(
            signal_id=str(signal.signal_id),
            signal_type=signal.type.value,
            source_id=signal.source_id,
            timestamp=signal.timestamp,
            truthkey=signal.truthkey,
            data=signal.data,
        )
        db.add(log_entry)
        db.commit()

    def _compute_probe_key(self, claim_type: str, scope: dict) -> str:
        """Compute deterministic probe key from claim_type and scope."""
        scope_str = json.dumps(scope, sort_keys=True)
        raw = f"{claim_type}:{scope_str}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _update_existing_probe(self, db, probe_model: ProbeModel, signal: Signal) -> Probe:
        """Update existing probe with new signal."""
        # Append signal ID to active_signals
        current_signals = probe_model.active_signals or []
        if str(signal.signal_id) not in current_signals:
            current_signals.append(str(signal.signal_id))
            probe_model.active_signals = current_signals
            probe_model.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(probe_model)
            
        # Convert back to Pydantic
        return self._model_to_pydantic(probe_model)

    def _save_new_probe(self, db, probe: Probe) -> Probe:
        """Persist new probe to database."""
        probe_model = ProbeModel(
            probe_id=str(probe.probe_id),
            probe_key=probe.probe_key,
            claim_type=probe.claim_type,
            status=probe.status.value,
            scope=probe.scope,
            created_by_signal=str(probe.created_by_signal) if probe.created_by_signal else None,
            active_signals=[str(uid) for uid in probe.active_signals],
            requirements=probe.requirements,
            created_at=probe.created_at,
            updated_at=probe.updated_at,
            expires_at=probe.expires_at
        )
        db.add(probe_model)
        db.commit()
        return probe

    def _construct_probe_from_signal(self, signal: Signal, probe_key: str, claim_type: str, scope: dict) -> Probe:
        """Derive standard Probe parameters from signal."""
        requirements = signal.data.get("requirements", {})
        
        return Probe(
            probe_key=probe_key,
            claim_type=claim_type,
            scope=scope,
            created_by_signal=signal.signal_id,
            active_signals=[signal.signal_id],
            requirements=requirements,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
        )

    def _apply_activation_policy(self, signal: Signal) -> ProbeStatus:
        """
        Decide if probe needs human approval.
        """
        # Policy: Manual triggers from Authority/Expert are Auto-Active
        # For simulation simplicity, MANUAL_TRIGGER is always Active
        if signal.type == SignalType.MANUAL_TRIGGER:
            return ProbeStatus.ACTIVE
            
        # Automated triggers depend on severity (mock logic)
        if signal.type == SignalType.AUTOMATED_TRIGGER:
            severity = signal.data.get("severity", "low")
            if severity == "critical":
                return ProbeStatus.ACTIVE
                
        return ProbeStatus.PROPOSED
        
    def _model_to_pydantic(self, model: ProbeModel) -> Probe:
        """Convert DB model to Pydantic."""
        return Probe(
            probe_id=UUID(model.probe_id),
            probe_key=model.probe_key,
            claim_type=model.claim_type,
            status=ProbeStatus(model.status),
            scope=model.scope or {},
            created_by_signal=UUID(model.created_by_signal) if model.created_by_signal else None,
            active_signals=[UUID(s) for s in (model.active_signals or [])],
            requirements=model.requirements or {},
            created_at=model.created_at,
            updated_at=model.updated_at,
            expires_at=model.expires_at
        )

processor = SignalProcessor()
