# Kaori Truth

**The Mechanics of Verification** — Pure, deterministic truth compilation.

## Status

**v2.1.0** — Production-ready. Implements the 7 Laws of Truth (TRUTH_SPEC v2.1).

## The 7 Laws of Truth

1. **Truth is Compiled, Not Declared** — Computed from observations, not asserted
2. **The Compiler is Pure** — No side effects, no external state
3. **TruthKey is the Universal Address** — Canonical join key for all truth
4. **Evidence Precedes Verification** — No observations → no truth
5. **Trust is Input, Not Computed** — TrustSnapshot is data, not a call
6. **Every Output is Signed** — Cryptographic provenance
7. **Truth is Replayable Forever** — 100 years from now, same answer

## Quick Start

```python
from datetime import datetime, timezone
from kaori_truth.compiler import compile_truth_state

# Compile truth from observations
state = compile_truth_state(
    claim_type=claim_type,
    truth_key=truth_key,
    observations=observations,
    trust_snapshot=trust_snapshot,
    policy_version="1.0.0",
    compiler_version="2.1.0",
    compile_time=datetime(2026, 1, 9, 12, 0, tzinfo=timezone.utc),
)

# Result is deterministic and signed
print(state.compilation_hash)  # Same inputs → same hash
```

## Key Guarantees

- **Deterministic:** Same inputs → byte-identical output
- **Pure:** No DB, no API, no network calls
- **Auditable:** Every input is explicit and stored
- **Signed:** Cryptographic verification

## Package Structure

```
kaori-truth/
├── src/kaori_truth/
│   ├── compiler.py       # compile_truth_state()
│   ├── canonical/        # Hash, URI, datetime, float canonicalization
│   ├── primitives/       # TruthKey, TruthState, Observation, ClaimType
│   ├── consensus.py      # Weighted consensus algorithms
│   ├── confidence.py     # Confidence score computation
│   ├── validation.py     # Claim validation logic
│   ├── trust_snapshot.py # TrustSnapshot interface (from Flow)
│   └── signing.py        # Signature generation
└── tests/
```

## Specification

See [TRUTH_SPEC.md](../kaori-spec/TRUTH_SPEC.md) for the normative specification.

---

*Part of Kaori Protocol by MSRO*
