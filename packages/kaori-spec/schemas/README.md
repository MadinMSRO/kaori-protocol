# Kaori Schemas — ClaimType Contracts

This directory contains **ClaimType YAML contracts** that define validation rules for different observation types.

## Structure

```
schemas/
├── earth/
│   ├── flood_v1.yaml
│   ├── coastal_erosion_v1.yaml
│   ├── infrastructure_v1.yaml
│   └── vegetation_v1.yaml
├── ocean/
│   ├── coral_bleaching_v1.yaml
│   ├── reef_recovery_v1.yaml
│   ├── sea_temperature_v1.yaml
│   └── vessel_anomaly_v1.yaml
├── space/
│   ├── orbital_debris_v1.yaml
│   ├── debris_track_v1.yaml
│   ├── light_pollution_v1.yaml
│   └── satellite_pass_v1.yaml
└── meta/
    └── claimtype.schema.json    # JSON Schema for validation
```

## What ClaimType Defines

Each YAML file specifies:

| Section | Purpose |
|---------|---------|
| `truthkey` | How observations are bucketed (H3 resolution, time bucket) |
| `risk_profile` | `monitor` (AI can auto-verify) or `critical` (requires human) |
| `evidence` | Required evidence types, min/max count |
| `ai_validation_routing` | Bouncer → Generalist → Specialist pipeline |
| `consensus_model` | Vote weights, finalize/reject thresholds |
| `confidence_model` | Component weights for composite confidence |
| `human_gating` | When human approval is required |
| `temporal_decay` | Confidence decay over time |

## Example: flood_v1.yaml

```yaml
id: earth.flood.v1
version: 1
domain: earth
topic: flood
risk_profile: critical  # Requires human consensus

consensus_model:
  finalize_threshold: 15
  reject_threshold: -10
  weighted_roles:
    bronze: 1
    silver: 3
    expert: 7
    authority: 10
```

## Creating New ClaimTypes

1. Copy an existing YAML as a template
2. Modify for your domain/topic
3. Place in appropriate folder (`earth/`, `ocean/`, `space/`)
4. Use `{domain}.{topic}.v{version}` as the `id`

## See Also

- [SPEC.md](../SPEC.md) — Protocol specification (Section 5: ClaimTypes)
- [core/claimtype.py](../core/claimtype.py) — Typed Python models
