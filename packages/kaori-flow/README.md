# Kaori Flow

**The Physics of Trust** — Event-sourced, emergent, deterministic trust dynamics.

## Status

**v2.0.0** — Core implementation complete. Implements the 7 Rules of Trust (FLOW_SPEC v4.0).

## The 7 Rules of Trust

1. **Trust is Event-Sourced** — Computed from immutable signals, not stored state
2. **Everything is an Agent** — Uniform participation model
3. **Standing is the Primitive** — Single scalar (0-1000) per agent
4. **Standing Global, Trust Local** — Contextual topology affects effective trust
5. **Nonlinear Updates** — Penalty sharper than reward
6. **Phase Transitions** — Discrete behavioral regimes
7. **Policy Interpretation Evolves** — FlowPolicy is an agent with standing

## Quick Start

```python
from kaori_flow import FlowCore, FlowPolicy, TrustContext

# Initialize
flow = FlowCore(policy=FlowPolicy.default())

# Register agents
flow.register_agent("user:amira", role="observer")

# Get standing
standing = flow.get_standing("user:amira")  # 200.0

# After contributing to correct truth outcomes
flow.emit_truthstate(
    truthkey="earth:flood:h3:abc:surface:2026-01-09",
    status="VERIFIED_TRUE",
    confidence=0.95,
    contributors=["user:amira"],
    outcome="correct",
    quality_score=80.0,
)

standing = flow.get_standing("user:amira")  # ~222 (increased)

# Get trust snapshot for truth compilation
snapshot = flow.get_trust_snapshot(
    agent_ids=["user:amira"],
    context=TrustContext(claimtype_id="earth.flood.v1"),
)
```

## Production Integration

The core library provides abstract `SignalStore` protocol. Production implementations inject backends:

```python
# Development (in-memory)
flow = FlowCore(policy=FlowPolicy.default())

# Production (inject your storage)
from your_app.storage import PostgresSignalStore

flow = FlowCore(
    store=PostgresSignalStore(connection),
    policy=FlowPolicy.load("flow_policy_v1.yaml"),
)
```

## Package Structure

```
kaori-flow/
├── src/kaori_flow/
│   ├── core.py           # FlowCore main entry point
│   ├── policy.py         # FlowPolicy (YAML agent)
│   ├── reducer.py        # Event-sourced standing computation
│   ├── trust.py          # Contextual trust computation
│   ├── store.py          # SignalStore abstraction
│   └── primitives/       # Agent, Signal, Probe, Network
├── policies/
│   └── flow_policy_v1.yaml
└── tests/
```

## Configuration

All parameters are configurable via FlowPolicy YAML — no hardcoded magic numbers.

See `policies/flow_policy_v1.yaml` for the complete schema.

## Specification

See [FLOW_SPEC.md](../kaori-spec/FLOW_SPEC.md) for the normative specification.

---

*Part of Kaori Protocol by MSRO*
