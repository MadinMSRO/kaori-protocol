# Kaori Protocol — Truth Standard

> **⚠️ This specification has been updated.**

The canonical specification is now located at:

**[packages/kaori-spec/TRUTH_SPEC.md](packages/kaori-spec/TRUTH_SPEC.md)**

## Version History

| Version | Description |
|---------|-------------|
| v1.3 | Original implementation-grade specification |
| v2.0 | Open-core architecture with canonicalization and pure compiler |

## Quick Links

- [Truth Spec v2.0](packages/kaori-spec/TRUTH_SPEC.md) — Canonical specification
- [Flow Spec v3.0](packages/kaori-spec/FLOW_SPEC.md) — Trust physics specification
- [kaori-truth Package](packages/kaori-truth/) — Pure compiler implementation
- [kaori-flow Package](packages/kaori-flow/) — TrustProvider implementation
- [kaori-api Package](packages/kaori-api/) — Orchestrator implementation

## Key Changes in v2.0

1. **Open-Core Architecture** — Strict package boundaries with dependency rules
2. **Canonicalization Subsystem** — All hashing through deterministic serialization
3. **Temporal Index Subsystem** — Strict UTC enforcement
4. **Pure Compiler** — `compile_truth_state()` has ZERO DB/API/Flow imports
5. **Semantic/State Hash Split** — Stable identity across compile_time differences
6. **TrustSnapshot as Data** — Truth receives data, never calls provider