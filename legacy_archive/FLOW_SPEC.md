# Kaori Protocol — Flow Standard

> **⚠️ This specification has been updated.**

The canonical specification is now located at:

**[packages/kaori-spec/FLOW_SPEC.md](packages/kaori-spec/FLOW_SPEC.md)**

## Version History

| Version | Description |
|---------|-------------|
| v2.2 | Probe-First Architecture |
| v3.0 | Open-core architecture with TrustProvider in Flow |

## Quick Links

- [Flow Spec v3.0](packages/kaori-spec/FLOW_SPEC.md) — Canonical specification
- [Truth Spec v2.0](packages/kaori-spec/TRUTH_SPEC.md) — Truth compilation specification
- [kaori-flow Package](packages/kaori-flow/) — TrustProvider implementation
- [kaori-truth Package](packages/kaori-truth/) — Pure compiler implementation

## Key Changes in v3.0

1. **TrustProvider in Flow** — Provider implementation lives in kaori-flow, not kaori-truth
2. **TrustSnapshot as Data** — Schema in Truth, implementation in Flow
3. **Clear Boundary** — Truth receives TrustSnapshot data, never calls provider
4. **Reference Implementation** — InMemoryTrustProvider for testing/development
5. **Production Guidance** — Clear separation of open-core vs production features
