# Kaori Protocol — Demo Simulations

This directory contains simulation and testing scripts for the Kaori Protocol.

## Scripts

| Script | Description |
|--------|-------------|
| `simulation_demo.py` | Full simulation with multiple agents and observations |
| `e2e_demo.py` | End-to-end test coverage |
| `comprehensive_demo.py` | Comprehensive feature demonstration |
| `demo_lifecycle.py` | Probe lifecycle demonstration |
| `system_test.py` | System integration tests |
| `validate_claims.py` | ClaimType validation |
| `lock_claim.py` | ClaimType locking utility |
| `new_claim.py` | Create new ClaimType |
| `inspect_state.py` | Inspect TruthState |
| `verify_generalist.py` | AI generalist verification |

## Running

```bash
cd examples/demo-sim
python simulation_demo.py
```

## Note

These are demo/testing scripts and NOT part of the open-core packages. They demonstrate how to use the protocol packages:

```python
# Production code imports from packages
from kaori_truth import compile_truth_state, Observation
from kaori_flow import TrustProvider
from kaori_api import TruthOrchestrator
```
