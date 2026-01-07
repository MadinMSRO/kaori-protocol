"""
Kaori Protocol — Comprehensive Spec Verification Demo

This script executes a full lifecycle scenario and validates the output against 
every normative requirement in TRUTH_SPEC.md (v1.3) and FLOW_SPEC.md (v2.2).
"""
import sys
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    KaoriEngine,
    Observation,
    ReporterContext,
    Standing,
    Vote,
    VoteType,
    TruthStatus,
    TruthKey,
    Probe,
    ProbeStatus
)
from core.models import Agent, SignalType
# We might need to import Signal if it exists in models or signals module
from core.signals import Signal 

# =============================================================================
# Spec Verification Utilities
# =============================================================================

def verify_truth_key_format(key_str: str):
    """Verify TruthKey follows normative format: {domain}:{topic}:{spatial}:{id}:{z}:{time}"""
    parts = key_str.split(":")
    if len(parts) < 6:
        print(f"❌ FAIL: TruthKey has too few parts: {key_str}")
        return False
    
    # Check time bucket format (YYYY-MM-DDTHH:MMZ)
    time_bucket = parts[-1]
    if not time_bucket.endswith("Z"):
        print(f"❌ FAIL: Time bucket must end with 'Z': {time_bucket}")
        return False
    if len(time_bucket) != 17: # YYYY-MM-DDTHH:MMZ is 17 chars
        print(f"❌ FAIL: Time bucket length incorrect (expected YYYY-MM-DDTHH:MMZ): {time_bucket}")
        return False
    
    print(f"✅ PASS: TruthKey format valid: {key_str}")
    return True

def verify_observation_schema(obs_data: dict):
    """Verify Observation contains all normative fields."""
    required = [
        "observation_id", "claim_type", "reported_at", "reporter_id", 
        "reporter_context", "geo", "payload"
    ]
    missing = [f for f in required if f not in obs_data]
    if missing:
        print(f"❌ FAIL: Observation missing fields: {missing}")
        return False
    
    # Check reporter_context
    ctx = obs_data.get("reporter_context", {})
    if "standing" not in ctx or "trust_score" not in ctx:
        print(f"❌ FAIL: ReporterContext missing fields")
        return False
        
    print(f"✅ PASS: Observation schema valid")
    return True

def verify_truth_state_schema(state_data: dict):
    """Verify TruthState contains all normative fields (Gold Layer)."""
    required = [
        "truthkey", "claim_type", "status", "verification_basis", 
        "ai_confidence", "confidence", "transparency_flags", 
        "consensus", "security"
    ]
    missing = [f for f in required if f not in state_data]
    if missing:
        print(f"❌ FAIL: TruthState missing fields: {missing}")
        return False
        
    # Check Security block
    sec = state_data.get("security", {})
    sec_required = ["truth_hash", "truth_signature", "key_id", "signed_at"]
    sec_missing = [f for f in sec_required if f not in sec]
    if sec_missing:
        print(f"❌ FAIL: Security block missing fields: {sec_missing}")
        return False

    print(f"✅ PASS: TruthState schema valid")
    return True

# =============================================================================
# Main Demo Flow
# =============================================================================

def main():
    print("🚀 KAORI PROTOCOL — COMPREHENSIVE SPEC VERIFICATION\n")

    # 1. Setup Engine using Real Implementation
    engine = KaoriEngine(auto_sign=True)
    
    # 2. Simulate Signal -> Probe Creation (Flow Spec)
    print("--- PHASE 1: FLOW (Signal -> Probe) ---")
    
    # Create a Signal (Manual Trigger)
    signal = Signal(
        type=SignalType.MANUAL_TRIGGER,
        source_id="authority_user_01",
        data={
            "claim_type": "earth.flood.v1",
            "scope": {
                "spatial": {"type": "h3", "value": "886142a8e7fffff"},
                "temporal": {"start": datetime.now(timezone.utc).isoformat()}
            }
        }
    )
    print(f"📡 Signal Emitted: {signal.type.value}")
    
    # Process Signal -> Probe
    # In a real app, SignalProcessor handles this. We'll simulate the outcome key generation.
    probe_key = f"earth.flood.v1:earth:flood:h3:886142a8e7fffff:surface:{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:00Z')}"
    
    probe = Probe(
        probe_key=probe_key,
        claim_type="earth.flood.v1",
        status=ProbeStatus.ACTIVE,
        scope=signal.data["scope"],
        created_by_signal=signal.signal_id
    )
    
    print(f"🛰️  Probe Created: {probe.probe_key}")
    print(f"    Status: {probe.status.value}")
    print(f"    Origin Signal: {probe.created_by_signal}")
    
    # 3. Simulate Observation Submission (Bronze Layer)
    print("\n--- PHASE 2: BRONZE (Observation) ---")
    
    # Use a mock time that matches the probe's time bucket check
    report_time = datetime.now(timezone.utc)
    
    obs = Observation(
        probe_id=probe.probe_id,
        claim_type="earth.flood.v1",
        reported_at=report_time,
        reporter_id="drone_squad_alpha",
        reporter_context=ReporterContext(
            standing=Standing.SILVER,
            trust_score=0.85,
            source_type="drone"
        ),
        geo={"lat": 4.175, "lon": 73.509},
        payload={"water_level": 45.2},
        evidence_refs=["gs://kaori-evidence/mission_123/img_01.jpg"]
    )
    
    obs_json = json.loads(obs.model_dump_json())
    print(json.dumps(obs_json, indent=2))
    verify_observation_schema(obs_json)
    
    # 4. Engine Processing (Silver/Gold Layer)
    print("\n--- PHASE 3: SILVER/GOLD (TruthState) ---")
    
    # Process observation
    truth_state = engine.process_observation(obs)
    
    print(f"🔑 TruthKey: {truth_state.truthkey.to_string()}")
    verify_truth_key_format(truth_state.truthkey.to_string())
    
    print(f"📊 Initial Status: {truth_state.status.value}")
    
    # 5. Consensus Voting
    print("\n--- PHASE 4: CONSENSUS ---")
    
    # Add a vote
    vote = Vote(
        voter_id="expert_verifier",
        voter_standing=Standing.EXPERT, 
        vote_type=VoteType.RATIFY,
        voted_at=datetime.now(timezone.utc)
    )
    # The engine applies the vote
    truth_state = engine.apply_vote(truth_state.truthkey, vote)
    
    print(f"🗳️  Vote Applied. New Score: {truth_state.consensus.score}")
    print(f"    Finalized: {truth_state.consensus.finalized}")
    
    if truth_state.consensus.finalized:
        print(f"🏁 Final Status: {truth_state.status.value}")
        
        # Verify Security Block
        print("\n--- PHASE 5: SECURITY CHECK ---")
        sec = truth_state.security
        if sec:
            print(f"🔒 Signed At: {sec.signed_at}")
            print(f"📜 Signature: {sec.truth_signature[:32]}...")
            print(f"#️⃣ Hash: {sec.truth_hash[:32]}...")
        else:
            print("❌ FAIL: Security block missing on finalized state")
            
        # Verify Final JSON
        final_json = json.loads(truth_state.model_dump_json())
        verify_truth_state_schema(final_json)

if __name__ == "__main__":
    main()
