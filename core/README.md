# Kaori Core — Python Reference Implementation

This directory contains the **Python reference implementation** of the Kaori Protocol.

## Modules

| Module | Purpose |
|--------|---------|
| `engine.py` | Main orchestration engine — processes observations into signed truth states |
| `models.py` | Pydantic data models for all protocol primitives (TruthKey, TruthState, Vote, etc.) |
| `claimtype.py` | Typed models for ClaimType YAML configuration |
| `schema_loader.py` | Loads and validates ClaimType YAML files |
| `consensus.py` | Weighted consensus computation |
| `confidence.py` | Composite confidence scoring |
| `signing.py` | Cryptographic signing of truth states |
| `truthkey.py` | TruthKey generation and parsing |
| `validators/` | AI validation pipeline (Bouncer, Generalist, Specialist) |
| `db/` | Database models and CRUD operations (SQLAlchemy) |

## Quick Example

```python
from core import KaoriEngine, Observation, ReporterContext, Standing

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

## See Also

- [SPEC.md](../SPEC.md) — Protocol specification
- [schemas/](../schemas/) — ClaimType YAML contracts
