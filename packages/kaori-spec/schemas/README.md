# Kaori Schemas — ClaimType Contracts

This directory contains **ClaimType YAML contracts** that define validation rules for different observation types.

## Structure

```
schemas/
├── earth/
│   ├── flood_v1.yaml            # Open Core example (no output_schema)
│   ├── flood_water_v1.yaml      # product flood contract (Liminal), res 8
│   ├── flood_water_v2.yaml      # the same on the res 10 hexagon (what Liminal files now)
│   ├── sky_cover_v1.yaml        # cloud cover and rain, doable anywhere (Liminal)
│   ├── coastal_erosion_v1.yaml
│   ├── coastal_erosion_v2.yaml  # res 10 (Liminal's shoreline)
│   ├── infrastructure_v1.yaml
│   ├── vegetation_v1.yaml
│   ├── vegetation_v2.yaml       # res 10
│   ├── nakaiy_v1.yaml
│   ├── sentinel2_scene_v1.yaml
│   └── sentinel1_sar_v1.yaml
├── ocean/
│   ├── coral_bleaching_v1.yaml
│   ├── reef_recovery_v1.yaml
│   ├── sea_temperature_v1.yaml
│   ├── vessel_anomaly_v1.yaml
│   ├── sentinel2_water_v1.yaml
│   └── sentinel3_olci_v1.yaml
├── space/
│   ├── orbital_debris_v1.yaml
│   ├── debris_track_v1.yaml
│   ├── light_pollution_v1.yaml
│   ├── satellite_pass_v1.yaml
│   ├── asteroid_occultation_v1.yaml
│   └── lunar_occultation_v1.yaml
└── meta/
    └── claimtype.schema.json    # JSON Schema for validation
```

## What ClaimType Defines

Each YAML file specifies:

| Section | Purpose |
|---------|---------|
| `truthkey` | How observations are bucketed (H3 resolution, time bucket); optional `position` (where a report may stand, below) |
| `risk_profile` | `monitor` (AI can auto-verify) or `critical` (requires human) |
| `evidence` | Required evidence types, min/max count |
| `ai_validation_routing` | Bouncer → Generalist → Specialist pipeline |
| `consensus_model` | Vote weights, finalize/reject thresholds |
| `confidence_model` | Component weights for composite confidence |
| `human_gating` | When human approval is required |
| `temporal_decay` | Confidence decay over time |

## Hexagon sizes, parents and children

Each ClaimType keeps the H3 resolution that suits it: sky cover is res 8 (~460 m), the ground claims
(`earth.flood_water.v2`, `earth.vegetation.v2`, `earth.coastal_erosion.v2`) are res 10 (~66 m centre to
edge). The Liminal map draws islands as res 10 hexagons; a truth lights every res 10 child of its cell
(a res 8 truth lights its 49 children). `GET /v1/truths?cells=...` returns the truths whose cell is a
requested cell, one of its ancestors or one of its descendants, each with `resolution` and `lights`.

`truthkey.position` (optional) makes `POST /v1/compile` check each report's GPS fix against the key's
hexagon: accepted inside the hexagon or its `ring` of neighbours (k=1: the 6 around it), or when the
fix's accuracy circle (`geo.accuracy_m`, counted up to `max_accuracy_m`) reaches the hexagon. The key
must also be a valid H3 cell at the ClaimType's resolution, for the ClaimType's domain and topic.

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
