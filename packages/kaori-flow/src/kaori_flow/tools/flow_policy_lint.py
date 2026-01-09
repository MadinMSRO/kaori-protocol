"""
Kaori Flow — Policy Linter

This tool validates FlowPolicy YAML files against the Constitutional Rules.
IT MUST PASS for a policy to be activated.

Checks:
1. Schema Validation (Lineage, Identity) via FlowPolicy Model
2. Compilation Integrity (Inheritance resolution, no cycles)
3. Constitutional Invariants (Strict Min/Max) via TrustPhysics Compile
"""

import sys
from kaori_flow.flow_policy import FlowPolicy

def lint_policy(policy_path: str) -> bool:
    """
    Lint a policy file.
    Returns True if valid, False/Raises if invalid.
    """
    print(f"Linting {policy_path}...")
    
    try:
        # 0. Load (Schema Check)
        print("   Checking Schema & Syntax...")
        policy = FlowPolicy.load(policy_path)
        print(f"   ✅ Schema Valid (v{policy.version})")

        # 1. Compile (Active Profile Check)
        print(f"   Compiling Active Profile: {policy.profile}...")
        physics = policy.compile()
        print(f"   ✅ Compilation Successful")
        print(f"   Physics Hash: {physics.physics_hash}")
        print(f"   Theta Min: {physics.theta_min}")
        print(f"   Strict Min Constraint: {physics.strict_min}")
        
        # 2. Check Safety Rails (Explicit opt-in)
        if not policy.safety.require_policy_lint_pass:
             raise ValueError("Policy must explicitly require lint pass (safety.require_policy_lint_pass=True)")

        print("✅ Policy PASSED all constitutional checks.")
        return True
        
    except Exception as e:
        print(f"❌ Policy FAILED lint: {e}")
        # print stack trace for debugging if needed, usually string is enough
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m kaori_flow.tools.flow_policy_lint <path_to_policy.yaml>")
        sys.exit(1)
        
    success = lint_policy(sys.argv[1])
    sys.exit(0 if success else 1)
