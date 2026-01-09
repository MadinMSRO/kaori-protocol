"""
Kaori Protocol — End-to-End Demo (Reference Implementation)

This script demonstrates the full Truth Lifecycle per Constitutional Architecture:
1. FLOW: Manages the trust network via compiled TrustPhysics.
2. TRUTH: Purely compiles Observations + TrustSnapshots into verified TruthStates.

Constitutional Compliance:
- FlowPolicy is loaded from versioned YAML (hard fail if missing).
- TrustPhysics is compiled explicitly and passed to FlowCore.
- TruthKey is generated via primitive.
- ReporterContext trust fields are CLAIMED (compiler uses snapshot).
- Physics hash is anchored in trust_snapshot.snapshot_hash.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Setup paths for execution from repo root
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "packages" / "kaori-flow" / "src"))
sys.path.insert(0, str(ROOT_DIR / "packages" / "kaori-truth" / "src"))

# Force UTF-8 for Windows Console
sys.stdout.reconfigure(encoding='utf-8')

# === Imports (Constitutional Boundary) ===
from kaori_flow.core import FlowCore
from kaori_flow.flow_policy import FlowPolicy
from kaori_flow.trust import TrustContext

from kaori_truth.compiler import compile_truth_state
from kaori_truth.primitives.claimtype import ClaimType
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthkey import build_truthkey

# Path to versioned constitutional policy (Fix #2)
POLICY_PATH = ROOT_DIR / "packages" / "kaori-flow" / "policies" / "flow_policy_v1.0.0.yaml"

def main():
    print("🚀 KAORI PROTOCOL — END-TO-END DEMO (Constitutional)\n")
    
    # =========================================================================
    # 1. SETUP FLOW LAYER (The Trust Engine)
    # =========================================================================
    print("--- 1. Initializing Flow Layer ---")
    
    # Fix #3: Hard fail if policy YAML is missing (no fallback)
    if not POLICY_PATH.exists():
        raise FileNotFoundError(f"Missing constitutional policy: {POLICY_PATH}")
    
    # Load Policy from VERSIONED YAML
    flow_policy = FlowPolicy.load(POLICY_PATH)
    print(f"📜 Policy Loaded: {POLICY_PATH.name} (v{flow_policy.version})")
    
    # Compile Policy -> Physics (explicit, per Fix #1)
    physics = flow_policy.compile()
    print(f"⚛️  Physics Compiled (Hash: {physics.physics_hash[:16]}...)")
    
    # Boot Engine with PRE-COMPILED Physics (Fix #1: use physics= not policy=)
    flow = FlowCore(physics=physics)
    print(f"✅ Flow Core Online")

    # Register Agent "Alice"
    alice_id = "user:alice_verifier"
    flow.register_agent(alice_id, role="silver")
    print(f"👤 Registered Agent: {alice_id}")


    # =========================================================================
    # 2. DEFINE TRUTH CONTRACT (The ClaimType)
    # =========================================================================
    print("\n--- 2. Defining Truth Contract ---")
    
    claim_type = ClaimType(
        id="demo.weather.v1",
        version=1,
        domain="weather",
        topic="precip",
        truthkey={"spatial_system": "h3", "resolution": 8},
        output_schema={"type": "object", "properties": {"rain_mm": {"type": "number"}}}
    )
    print(f"📜 ClaimType Defined: {claim_type.id}")


    # =========================================================================
    # 3. SUBMIT OBSERVATION (The Input)
    # =========================================================================
    print("\n--- 3. Submitting Observation ---")
    
    now = datetime.now(timezone.utc)
    
    # Create Observation
    # Fix #5: ReporterContext fields are CLAIMED by reporter.
    # The compiler MUST use TrustSnapshot for actual trust, NOT these values.
    observation = Observation(
        observation_id=uuid4(),  # Fix #4: Pydantic Observation expects UUID
        claim_type=claim_type.id,
        reported_at=now,
        reporter_id=alice_id,
        reporter_context=ReporterContext(
            standing=Standing.SILVER,  # Claimed (not authoritative)
            trust_score=0.8,           # Claimed (not authoritative)
            source_type="human"
        ),
        geo={"lat": 35.6895, "lon": 139.6917},  # Tokyo
        payload={"rain_mm": 12.5}
    )
    print(f"👁️  Observation Received from {alice_id}")


    # =========================================================================
    # 4. BRIDGE: FLOW -> TRUTH (The Snapshot)
    # =========================================================================
    print("\n--- 4. Bridging Flow & Truth ---")
    
    snapshot = flow.get_trust_snapshot(
        agent_ids=[alice_id],
        context=TrustContext(claimtype_id=claim_type.id)
    )
    
    alice_trust = snapshot.agent_trusts[alice_id]
    print(f"📸 TrustSnapshot Captured")
    print(f"   Snapshot Hash: {snapshot.snapshot_hash[:16]}...")
    print(f"   Alice Effective Trust: {alice_trust.effective_trust:.4f}")


    # =========================================================================
    # 5. GENERATE TRUTHKEY (Via Primitive)
    # =========================================================================
    print("\n--- 5. Generating Canonical TruthKey ---")
    
    truth_key = build_truthkey(
        claim_type_id=claim_type.id,
        event_time=observation.reported_at,
        location=observation.geo,
        time_bucket_duration="PT1H",
        spatial_system="h3",
        spatial_resolution=8,
        z_index="surface",
    )
    print(f"🔑 TruthKey: {truth_key}")


    # =========================================================================
    # 6. COMPILE TRUTH (The Pure Function)
    # =========================================================================
    print("\n--- 6. Compiling Truth State ---")

    # EXECUTE COMPILER
    # Fix #6/#7: physics_hash is anchored in trust_snapshot.snapshot_hash
    # Compiler does not accept physics_hash directly; it uses snapshot integrity
    truth_state = compile_truth_state(
        claim_type=claim_type,
        truth_key=truth_key,
        observations=[observation],
        trust_snapshot=snapshot,
        policy_version=flow_policy.version,  # Fix #7: use authored policy version
        compile_time=now,
    )
    
    print(f"✅ Truth Compiled Successfully!")
    print(f"   Status: {truth_state.status.value}")
    print(f"   Confidence: {truth_state.confidence * 100:.1f}%")
    
    if truth_state.security:
        print(f"🔒 Signature: {truth_state.security.signature[:16]}...")
        print(f"   Semantic Hash: {truth_state.security.semantic_hash[:16]}...")

    print("\n✨ End-to-End Demo Complete.")

if __name__ == "__main__":
    main()
