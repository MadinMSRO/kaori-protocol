"""
Kaori Protocol — Quick Start Demo (Reference Implementation)

This script demonstrates the core Flow functionality:
1. Booting the Engine (FlowCore + FlowPolicy)
2. Compiling Policy to Physics
3. Registering Agents
4. Processing Signals
5. Updating Standing

This serves as the canonical usage example for 'kaori-flow' v2.0.0.
"""
import sys
from pathlib import Path
from datetime import datetime
import json

# Add package root to path to allow direct execution
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "packages" / "kaori-flow" / "src"))
sys.path.insert(0, str(ROOT_DIR / "packages" / "kaori-truth" / "src"))

# Force UTF-8 for Windows Console
sys.stdout.reconfigure(encoding='utf-8')

from kaori_flow.core import FlowCore
from kaori_flow.flow_policy import FlowPolicy
from kaori_flow.trust import TrustContext

def main():
    print("🚀 KAORI FLOW — REFERENCE DEMO\n")

    # 1. Initialize Engine (Policy -> Physics Compilation happens here)
    print("--- 1. Booting Engine ---")
    policy = FlowPolicy.default()
    engine = FlowCore(policy=policy)
    
    print(f"✅ Engine Booted")
    print(f"📜 Policy Loaded: v{policy.version}")
    print(f"⚛️  Physics Compiled: {engine.physics.physics_hash[:16]}...")
    print(f"    (Strict Min: {engine.physics.strict_min})")

    # 2. Register Agents
    print("\n--- 2. Registering Agents ---")
    alice_id = "user:alice"
    engine.register_agent(alice_id, role="observer")
    
    initial_standing = engine.get_standing(alice_id)
    print(f"👤 Alice Initial Standing: {initial_standing}")
    
    # 3. Process Events (Signals)
    print("\n--- 3. Processing Events ---")
    print(f"📡 Emitting TRUTHSTATE... (Alice contributes correctly)")
    
    # Alice contributes to a truth that turns out CORRECT
    # This should boost her standing
    engine.emit_truthstate(
        truthkey="event:flood:001",
        status="verified",
        confidence=1.0,
        contributors=[alice_id],
        outcome="correct",
        quality_score=95.0
    )
    
    # 4. Check Results
    print("\n--- 4. Final State ---")
    final_standing = engine.get_standing(alice_id)
    print(f"👤 Alice Final Standing: {final_standing}")
    
    delta = final_standing - initial_standing
    if delta > 0:
        print(f"✅ SUCCESS: Standing increased by +{delta:.4f}")
    else:
        print(f"❌ FAILURE: Standing did not increase.")

    # 5. Physics Inspection
    print("\n--- 5. Trust Physics Inspection ---")
    # Simulate a trust check for Alice
    snapshot = engine.get_trust_snapshot(
        agent_ids=[alice_id],
        context=TrustContext() 
    )
    alice_trust = snapshot.agent_trusts[alice_id]
    print(f"🔍 Effective Trust (Snapshot): {alice_trust.effective_trust:.4f}")
    print(f"    (Phase: {alice_trust.derived_class})")

    print("\n✨ Demo Complete.")

if __name__ == "__main__":
    main()
