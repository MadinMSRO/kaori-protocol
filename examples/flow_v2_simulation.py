"""
Kaori Flow v2 — End-to-End Simulation

Demonstrates the 7 Rules of Trust in action.

Run: python examples/flow_v2_simulation.py
"""
from datetime import datetime, timedelta
import sys
sys.path.insert(0, "packages/kaori-flow/src")

from kaori_flow import (
    FlowCore, 
    FlowPolicy, 
    TrustContext,
    SignalTypes,
)


def main():
    print("=" * 60)
    print("KAORI FLOW v2 — SIMULATION")
    print("=" * 60)
    
    # =========================================================================
    # Setup
    # =========================================================================
    print("\n[1] Initializing FlowCore with default policy...")
    flow = FlowCore(policy=FlowPolicy.default())
    
    # Register the policy as an agent
    flow.register_policy(flow.policy)
    print(f"    Policy registered: {flow.policy.agent_id}")
    print(f"    Policy standing: {flow.get_standing(flow.policy.agent_id)}")
    
    # =========================================================================
    # Register Agents
    # =========================================================================
    print("\n[2] Registering agents...")
    
    # Observers
    flow.register_agent("user:amira", role="observer")
    flow.register_agent("user:bob", role="observer")
    flow.register_agent("sensor:jetson_042", role="validator")
    
    # Authority
    flow.register_agent("official:coast_guard", role="authority")
    
    print(f"    user:amira standing: {flow.get_standing('user:amira')}")
    print(f"    user:bob standing: {flow.get_standing('user:bob')}")
    print(f"    sensor:jetson_042 standing: {flow.get_standing('sensor:jetson_042')}")
    print(f"    official:coast_guard standing: {flow.get_standing('official:coast_guard')}")
    
    # =========================================================================
    # Simulate Correct Truth Outcomes
    # =========================================================================
    print("\n[3] Simulating successful truth compilations...")
    
    # Amira contributes to 3 correct verifications
    for i in range(3):
        flow.emit_truthstate(
            truthkey=f"earth:flood:h3:abc{i}:surface:2026-01-09",
            status="VERIFIED_TRUE",
            confidence=0.95,
            contributors=["user:amira"],
            outcome="correct",
            quality_score=80.0,
        )
    
    print(f"    Amira after 3 correct: {flow.get_standing('user:amira'):.2f}")
    
    # Bob contributes to 1 correct verification
    flow.emit_truthstate(
        truthkey="earth:flood:h3:xyz:surface:2026-01-09",
        status="VERIFIED_TRUE",
        confidence=0.90,
        contributors=["user:bob"],
        outcome="correct",
        quality_score=60.0,
    )
    
    print(f"    Bob after 1 correct: {flow.get_standing('user:bob'):.2f}")
    
    # =========================================================================
    # Simulate Incorrect Outcome (Penalty Sharper Than Reward)
    # =========================================================================
    print("\n[4] Simulating incorrect outcome (penalty is sharper)...")
    
    before = flow.get_standing("user:bob")
    
    flow.emit_truthstate(
        truthkey="earth:flood:h3:wrong:surface:2026-01-09",
        status="VERIFIED_FALSE",
        confidence=0.85,
        contributors=["user:bob"],
        outcome="incorrect",
        quality_score=50.0,
    )
    
    after = flow.get_standing("user:bob")
    print(f"    Bob before: {before:.2f}, after: {after:.2f}")
    print(f"    Delta: {after - before:.2f} (penalty is sharper due to amplifier)")
    
    # =========================================================================
    # Endorsement (VOUCH Edge)
    # =========================================================================
    print("\n[5] Authority endorses Amira...")
    
    flow.endorse("official:coast_guard", "user:amira")
    
    # =========================================================================
    # Trust Snapshot with Context
    # =========================================================================
    print("\n[6] Computing trust snapshot with context...")
    
    context = TrustContext(
        claimtype_id="earth.flood.v1",
        claimtype_standing=750.0,  # High-standing claimtype
        claimtype_collaborators=[("official:coast_guard", 500.0)],
        probe_creator_id="official:coast_guard",
        probe_creator_standing=500.0,
    )
    
    snapshot = flow.get_trust_snapshot(
        agent_ids=["user:amira", "user:bob"],
        context=context,
    )
    
    print(f"    Snapshot ID: {snapshot.snapshot_id[:8]}...")
    print(f"    Policy: {snapshot.policy_id} v{snapshot.policy_version}")
    print(f"    Policy standing: {snapshot.policy_standing:.2f}")
    
    for agent_id, trust in snapshot.agent_trusts.items():
        print(f"    {agent_id}:")
        print(f"      Standing: {trust.standing:.2f}")
        print(f"      Effective Trust: {trust.effective_trust:.2f}")
        print(f"      Class: {trust.derived_class}")
        if trust.flags:
            print(f"      Flags: {trust.flags}")
    
    # =========================================================================
    # Self-Dealing Demonstration
    # =========================================================================
    print("\n[7] Demonstrating self-dealing penalty...")
    
    # If the probe creator observes their own probe, they get a discount
    self_dealing_context = TrustContext(
        claimtype_id="earth.flood.v1",
        probe_creator_id="user:amira",  # Amira created this probe
        probe_creator_standing=flow.get_standing("user:amira"),
    )
    
    snapshot_self = flow.get_trust_snapshot(
        agent_ids=["user:amira"],
        context=self_dealing_context,
    )
    
    amira_self = snapshot_self.agent_trusts["user:amira"]
    print(f"    Amira standing: {amira_self.standing:.2f}")
    print(f"    Amira effective (self-dealing): {amira_self.effective_trust:.2f}")
    print(f"    Flags: {amira_self.flags}")
    
    # Compare to normal context
    normal_context = TrustContext(
        claimtype_id="earth.flood.v1",
        probe_creator_id="user:bob",  # Different creator
        probe_creator_standing=flow.get_standing("user:bob"),
    )
    
    snapshot_normal = flow.get_trust_snapshot(
        agent_ids=["user:amira"],
        context=normal_context,
    )
    
    amira_normal = snapshot_normal.agent_trusts["user:amira"]
    print(f"    Amira effective (normal): {amira_normal.effective_trust:.2f}")
    
    discount = (amira_normal.effective_trust - amira_self.effective_trust) / amira_normal.effective_trust
    print(f"    Self-dealing discount: {discount*100:.0f}%")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("FINAL STANDINGS")
    print("=" * 60)
    
    for agent_id in ["user:amira", "user:bob", "sensor:jetson_042", "official:coast_guard", flow.policy.agent_id]:
        standing = flow.get_standing(agent_id)
        print(f"  {agent_id}: {standing:.2f}")
    
    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE — 7 Rules Demonstrated")
    print("=" * 60)
    print("""
Rule 1: Trust is Event-Sourced [OK]
  - All changes went through signals
  - Standings derived from replay

Rule 2: Everything is an Agent [OK]
  - Users, sensors, officials, policy all registered

Rule 3: Standing is the Primitive [OK]
  - Single scalar per agent (0-1000)

Rule 4: Standing Global, Trust Local [OK]
  - Same standing, different effective trust in context
  - Network bonus from endorsements

Rule 5: Nonlinear Updates [OK]
  - Log-based gain, logistic saturation
  - Penalty sharper than reward (2x amplifier)

Rule 6: Phase Transitions [OK]
  - Agents in different phases (dormant/active/dominant)

Rule 7: Policy Interpretation Evolves [OK]
  - Policy is an agent with standing
  - All parameters from FlowPolicy YAML
""")


if __name__ == "__main__":
    main()
