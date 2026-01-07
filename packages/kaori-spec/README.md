# Kaori Protocol — Specification Package

This package contains the canonical protocol specifications and ClaimType schemas.

## Contents

- **TRUTH_SPEC.md** — Kaori Truth Standard v2.0
- **FLOW_SPEC.md** — Kaori Flow Standard v3.0
- **schemas/** — ClaimType YAML contracts

## Specifications

### Truth Standard (v2.0)

Defines:
- Canonical TruthKey format
- ClaimType YAML contracts
- Deterministic compilation
- Canonicalization subsystem
- Temporal index subsystem
- Semantic/state hash split
- TruthState schema

### Flow Standard (v3.0)

Defines:
- Agent, Network, Signal, Probe primitives
- TrustProvider interface
- Trust dynamics (Laws of Physics)
- TrustSnapshot data schema

## Schema Structure

```
schemas/
├── earth/
│   ├── flood_v1.yaml
│   └── landslide_v1.yaml
├── ocean/
│   └── coral_bleaching_v1.yaml
└── space/
    └── debris_v1.yaml
```

## ClaimType ID Format

```
{namespace}.{name}.v{major}
```

Examples: `earth.flood.v1`, `ocean.coral_bleaching.v2`
