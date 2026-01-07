# Kaori Core — Python Reference Implementation

This directory contains the **Python reference implementation** of the Kaori Protocol.

## Modules

| Module | Purpose |
|--------|---------|
| `engine.py` | Main orchestration — processes observations into signed truth states |
| `models.py` | Pydantic data models (TruthKey, TruthState, Agent, Mission, Signal, NetworkEdge) |
| `signals.py` | Signal primitives for event-driven architecture |
| `claimtype.py` | Typed models for ClaimType YAML configuration |
| `schema_loader.py` | Loads and validates ClaimType YAML files |
| `consensus.py` | Weighted consensus computation |
| `confidence.py` | Composite confidence scoring |
| `signing.py` | Cryptographic signing of truth states (HMAC + GCP KMS) |
| `truthkey.py` | TruthKey generation and parsing (H3 spatial indexing) |
| `timeout_handler.py` | Handles review timeouts and state transitions |
| `validators/` | AI validation pipeline (Bouncer, Generalist, Specialist) |
| `db/` | SQLAlchemy database models and CRUD operations |

## Core Models

### Truth Layer
- `TruthKey` — Canonical join key for truth across space/time
- `TruthState` — The verified, signed representation of truth
- `Observation` — Raw input from reporters/sensors
- `Vote` — Validation vote from users/AI

### Flow Layer
- `Agent` — Identity holding Standing/Trust (FLOW_SPEC Section 2.1)
- `NetworkEdge` — Trust relationships between Agents (VOUCH, MEMBER_OF, etc.)
- `Mission` — Directive for agents to gather observations
- `Signal` — Event envelope for triggers (MANUAL, AUTOMATED, SCHEDULED)

## Quick Example

```python
from core import (
    KaoriEngine, Observation, ReporterContext, Standing,
    Agent, Signal, SignalType
)

# Create engine
engine = KaoriEngine(auto_sign=True)

# Submit observation
obs = Observation(
    claim_type="earth.flood.v1",
    reporter_id="reporter_001",
    reporter_context=ReporterContext(standing=Standing.BRONZE, trust_score=0.5),
    geo={"lat": 4.175, "lon": 73.509},
    payload={"water_level_cm": 45},
)

# Process → returns TruthState
truth_state = engine.process_observation(obs)
print(f"Status: {truth_state.status}")
print(f"TruthKey: {truth_state.truthkey.to_string()}")
```

## Database Schema

The `db/` module provides SQLAlchemy models compatible with PostgreSQL (Supabase):

| Table | Purpose |
|-------|---------|
| `agents` | Agent identity and standing |
| `network_edges` | Trust relationships |
| `missions` | Signal-triggered missions |
| `signal_log` | Audit trail of signals |
| `truth_states` | Gold truth states |
| `observations` | Bronze observations |
| `votes` | Consensus votes |

## See Also

- [TRUTH_SPEC.md](../TRUTH_SPEC.md) — Mechanics of verification
- [FLOW_SPEC.md](../FLOW_SPEC.md) — Physics of trust
- [schemas/](../schemas/) — ClaimType YAML contracts
