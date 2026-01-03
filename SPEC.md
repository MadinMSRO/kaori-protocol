# Kaori Protocol — Engineering Specification (v1.3)

> **Status:** Draft v1.3 (Implementation Grade)  
> **Maintainer:** MSRO  
> **Scope:** Defines the protocol for representing, validating, compiling, signing, and serving verifiable truth states derived from ground-based observations.

---

## 0. Normative Language

The following keywords are to be interpreted as described in **RFC 2119**:

| Keyword | Meaning |
|---------|---------|
| **MUST / MUST NOT** | Absolute requirement |
| **SHOULD / SHOULD NOT** | Recommended |
| **MAY** | Optional |

---

## 1. Purpose and Design Goals

Kaori Protocol provides a universal standard to transform real-world, on-the-ground observations into:

- Deterministic truth states
- Consensus and confidence scores
- Signed immutable histories
- Signed current truth maps

### 1.1 Primary Goals

Kaori implementations **MUST** support:

1. **TruthKey standardization** to join truth across space/time
2. **ClaimType YAML contracts** to define claim-specific policy without hardcoding logic
3. **Deterministic compilation** of truth states from observations
4. **AI autovalidation ladder** to reduce expert bottlenecks
5. **Human validation** only when required
6. **Signed Silver ledger** and **signed Gold truth map** for audit-grade trust
7. **Transparent verification semantics** (what caused verification vs how confident it is)

### 1.2 Non-Goals (v1)

Kaori v1 does **NOT** attempt to:

- Verify cryptographic authenticity of media capture devices
- Prove evidence is unedited
- Solve Sybil attacks perfectly
- Provide complete standing evolution systems
- Define domain-specific satellite calibration schemas

---

## 2. Protocol Overview (Conceptual Flow)

The Kaori truth lifecycle is:

```
Mission → Observation → Processing → Candidate Truth → Validation → Final Truth
```

Kaori defines everything from **Observation** onwards.

### 2.1 Observation Sources (Phase 1 Policy)

In Phase 1, Kaori observations are limited to **ground-based sources**, including:

- Humans (MissionHub, field teams, citizens)
- Drones
- IoT sensors (water level, rain gauges, etc.)
- Official reports (authority site visits)

> [!NOTE]
> Satellite measurements (e.g., NDWI grids) are **external measurement layers**, not Kaori observations in v1. They MAY be joined later using TruthKey for evaluation and calibration, but are not part of the protocol core.

---

## 3. Core Primitives

### 3.1 Standing (Mandatory)

Standing is a **mandatory** protocol primitive for every Reporter and Validator.

**Minimum standing classes:**

| Class | Description |
|-------|-------------|
| `bronze` | New or unverified users |
| `silver` | Established contributors |
| `expert` | Domain specialists |
| `authority` | Government officials |

> [!NOTE]
> **Standing Evolution** (how users graduate between classes) is defined in the **Kaori Flow** specification, not this document. This spec (Kaori Truth Standard) only defines how standing is *used* for validation.

Standing **MUST** influence:

- Vote weight (consensus model)
- Gating privileges
- Weighting in confidence computation
- Dispute escalation pathways

---

## 4. Canonical Join Key: TruthKey

### 4.1 TruthKey String Format (Normative)

TruthKey **MUST** be representable as:

```
{domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
```

**Example:**
```
earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00Z
```

### 4.2 TruthKey Components

| Field | Description |
|-------|-------------|
| `domain` | `earth`, `ocean`, `space` (extensible) |
| `topic` | `flood`, `erosion`, `coral_bleaching`, etc. |
| `spatial_system` | `h3`, `geohash`, `healpix`, `custom` |
| `spatial_id` | Index value |
| `z_index` | `surface`, `underwater`, `altitude`, `orbital_shell` |
| `time_bucket` | ISO8601 normalized |

### 4.3 Canonical TruthKey Object

```json
{
  "domain": "earth",
  "topic": "flood",
  "spatial_system": "h3",
  "spatial_id": "8928308280fffff",
  "z_index": "surface",
  "time_bucket": "2026-01-02T10:00Z"
}
```

---

## 5. Claim Types (YAML Contracts)

### 5.1 Purpose

ClaimType YAML files define the "law" for a claim class. They **MUST** define:

- TruthKey formation
- Evidence requirements
- AI validation routing
- Evidence similarity rules (hash + optional embeddings)
- Human gating requirements
- Consensus model
- Confidence model
- State verification policy (monitor vs critical lanes)
- Dispute resolution parameters
- Temporal decay

### 5.2 Versioning and Immutability

Released claim types **MUST** be immutable:

- `*_v1.yaml` **MUST NOT** be modified
- Changes require `*_v2.yaml`

### 5.3 Required ClaimType YAML Fields (Normative)

```yaml
id: earth.flood.v1
version: 1
domain: earth
topic: flood

truthkey:
  spatial_system: h3
  resolution: 8
  z_index: surface
  time_bucket: PT1H

risk_profile: monitor | critical

ui_schema:
  fields: []

evidence:
  required: true
  types: ["photo", "video", "sensor_log"]
  min_count: 1
  storage:
    canonical_scheme: "gs://"
    bucket: "kaori-evidence"

evidence_similarity:
  enabled: true
  hash:
    enabled: true
    method: phash
    duplicate_threshold: 6
    immediate_reject_if_duplicate: true
  embedding:
    enabled: true
    compute_mode: on_demand     # ALWAYS | ON_DEMAND | OFF
    engine: clip_v1
    similarity_threshold: 0.85
    trigger_conditions:
      - ai_confidence_below: 0.80
      - requires_semantic_corroboration: true

ai_validation_routing:
  enabled: true
  bouncer:
    engine: bouncer_v1
    routes:
      fail: reject
      pass: generalist
  generalist:
    engine: generalist_v1
    routes:
      high_confidence: accept
      low_confidence: specialist
  specialist:
    engine: specialist_v1
    routes:
      pass: accept
      fail: human_review

autovalidation:
  ai_verified_true_threshold: 0.82
  ai_verified_false_threshold: 0.20
  uncertainty_band:
    low: 0.20
    high: 0.82

human_gating:
  always_require_human: false
  required_for_risk_profiles: ["critical"]
  min_trust_score: 0.35
  min_ai_confidence: 0.82

validation_flow:
  mode: auto | human_peer | human_expert | authority_gate

consensus_model:
  type: weighted_threshold
  finalize_threshold: 15
  reject_threshold: -10
  weighted_roles:
    bronze: 1
    silver: 3
    expert: 7
    authority: 10
  override_allowed_roles: ["authority"]
  vote_types:
    RATIFY: +1
    REJECT: -1
    CHALLENGE: 0
    OVERRIDE: special

confidence_model:
  type: composite
  components: {}
  modifiers: {}
  thresholds: {}

state_verification_policy:
  monitor_lane:
    allow_ai_verified_truth: true
    transparency_flag_if_composite_below: 0.82
    flag_label: LOW_COMPOSITE_CONFIDENCE
  critical_lane:
    require_human_consensus_for_verified_true: true

dispute_resolution:
  quorum:
    min_votes: 3
  timeout:
    peer_review: PT12H
    expert_review: PT24H
    authority_escalation: PT48H
  default_action_on_timeout: maintain_state | downgrade_to_investigating

contradiction_rules:
  enabled: true
  trusted_sources:
    min_standing: expert
    min_trust_score: 0.70
  contradiction_trigger:
    min_confidence_gap: 0.40
    action: flag_and_escalate

temporal_decay:
  half_life: PT6H
  max_validity: P3D

incentives:
  enabled: false
  base_credit: 10
  verified_bonus: 20
  rejected_penalty: -5
```

---

## 6. Observations (Bronze)

### 6.1 Canonical Observation Schema (Normative)

Every observation **MUST** include:

- `observation_id`
- `claim_type`
- `reported_at`
- `reporter_id`
- `reporter_context.standing`
- `reporter_context.trust_score`
- `geo` (or spatial reference)
- `payload`
- `evidence` references (if required by claim type)

```json
{
  "observation_id": "uuid",
  "claim_type": "earth.flood.v1",
  "reported_at": "ISO8601",
  "reporter_id": "string",
  "reporter_context": {
    "standing": "bronze",
    "trust_score": 0.52,
    "source_type": "human|sensor|drone|official"
  },
  "geo": { "lat": 4.175, "lon": 73.509 },
  "payload": {},
  "evidence_refs": ["gs://kaori-evidence/.../photo1.jpg"],
  "evidence_hashes": { "phash": "0xA92F..." }
}
```

---

## 7. Evidence Handling (Normative)

### 7.1 Evidence Objects

Evidence objects **MUST** be stored in GCS (or another object store, but `gs://` is canonical for v1).

### 7.2 Evidence References

Evidence references **MUST** be stored in observations and propagated into Silver/Gold truth states.

EvidenceRef **MUST** use canonical format:
```
gs://bucket/path/file
```

### 7.3 Evidence Hashing

If enabled in claim YAML, perceptual hash **MUST** be computed for each evidence item.

---

## 8. Truth States (Gold) and Truth History (Silver)

### 8.1 Allowed Status Values (Normative)

`TruthState.status` **MUST** be one of:

| Status | Description |
|--------|-------------|
| `PENDING` | Awaiting processing |
| `INVESTIGATING` | Under review |
| `VERIFIED_TRUE` | Confirmed true |
| `VERIFIED_FALSE` | Confirmed false |
| `DISPUTED` | Conflicting evidence |
| `EXPIRED` | Past validity window |

### 8.2 Canonical TruthState JSON (Normative)

TruthState **MUST** include:

- TruthKey
- status
- ai_confidence
- composite confidence
- verification basis
- transparency flags
- consensus record
- evidence refs
- TruthHash and TruthSignature (KMS)

```json
{
  "truthkey": "...",
  "claim_type": "...",
  "status": "VERIFIED_TRUE",
  "verification_basis": "AI_AUTOVALIDATION",
  "ai_confidence": 0.88,
  "confidence": 0.64,
  "transparency_flags": ["LOW_COMPOSITE_CONFIDENCE"],
  "updated_at": "ISO8601",
  "evidence_refs": ["gs://..."],
  "ai_validation": {},
  "consensus": {},
  "confidence_breakdown": {},
  "security": {
    "truth_hash": "...",
    "truth_signature": "...",
    "kms_key_id": "...",
    "signed_at": "ISO8601"
  }
}
```

### 8.3 Silver Ledger Requirement

Silver **MUST** be append-only and **MUST** store full truth snapshots for every transition.

---

## 9. AI Autovalidation (Bouncer / Generalist / Specialist)

### 9.1 Bouncer (Gatekeeper) — Normative

Bouncer **MUST** execute first and **MUST** decide routing based on YAML.

Bouncer responsibilities **SHOULD** include:

- Evidence quality checks
- Duplicate detection (hash)
- Basic plausibility filters

### 9.2 Generalist and Specialist

Generalist and Specialist models **MAY** be used based on ClaimType YAML routing.

### 9.3 Embeddings

Embeddings **MAY** be computed only if YAML conditions trigger (recommended: `ON_DEMAND`).

---

## 10. Consensus Model (YAML-defined, Normative)

Consensus **MUST** be computed strictly from ClaimType YAML.

For **weighted threshold**:

```
score = Σ(weight(role) × vote_value)
```

**Finalize rules:**

- If `score >= finalize_threshold` → `VERIFIED_TRUE` (for critical lane only after human gate)
- If `score <= reject_threshold` → `VERIFIED_FALSE`

Override **MUST** finalize immediately if allowed and **MUST** set verification basis accordingly.

---

## 11. Confidence Model (YAML-defined, Normative)

Composite confidence **MUST** be computed deterministically from ClaimType YAML.

**General form:**

```
confidence = Σ(component_weight × component_value) + Σ(modifiers)
confidence = clamp(confidence, 0.0, 1.0)
```

Confidence breakdown **MUST** be stored.

---

## 12. Two-Lane Verification Policy (Normative)

### 12.1 Monitor Lane (Optimistic)

For `risk_profile: monitor`:

- Kaori **MAY** set `status = VERIFIED_TRUE` if `ai_confidence >= ai_verified_true_threshold`
- Kaori **MUST** compute composite confidence
- If composite confidence < `transparency_flag_if_composite_below`, Kaori **MUST** set:
  ```
  transparency_flags += ["LOW_COMPOSITE_CONFIDENCE"]
  ```

This ensures the state is transparently verifiable yet reviewable later.

### 12.2 Critical Lane (Strict)

For `risk_profile: critical`:

Kaori **MUST NOT** finalize `VERIFIED_TRUE` unless:

1. Human gating requirements are satisfied, **AND**
2. Consensus `finalize_threshold` is met

---

## 13. Human Gating (Normative)

Human validation is **REQUIRED** if **ANY** of the following holds:

- `risk_profile` is `critical`
- `validation_flow` mode ≠ `auto`
- `ai_confidence < min_ai_confidence`
- `trust_score < min_trust_score`
- Contradiction detected
- `always_require_human` is `true`

---

## 14. Contradictions (Ground Signals Only in v1)

### 14.1 Purpose

Contradiction is a primary escalation trigger.

Contradiction detection in v1 applies to **ground signal sources** (e.g., multiple humans, IoT sensors, drone evidence).

> [!NOTE]
> Satellite contradictions are handled outside the Kaori protocol spec in Phase 1 and may be added as an extension later.

### 14.2 Signal Observation Standard

Kaori **MAY** ingest non-human ground signals (IoT/drone) as observations with structured payloads.

Contradiction triggers **MUST** follow YAML `contradiction_rules`.

If contradiction triggers, Kaori **MUST** add:
```
transparency_flags += ["CONTRADICTION_DETECTED"]
```

and **MUST** escalate according to `dispute_resolution` policy.

---

## 15. Dispute Resolution (Normative)

### 15.1 Dispute Triggers

TruthState **MUST** enter `DISPUTED` if:

- Contradiction triggers AND confidence falls below threshold, **OR**
- `CHALLENGE` vote is received from authorized role, **OR**
- Validators split beyond a configured band

### 15.2 Quorum

ClaimType **MUST** define quorum parameters. Implementations **MUST** enforce quorum before finalization.

### 15.3 Timeouts

If unresolved after timeout:

- Maintain current state with `REQUIRES_HUMAN_REVIEW`, **OR**
- Downgrade to `INVESTIGATING`, per YAML policy

### 15.4 Authority Escalation

If unresolved after expert timeout, Kaori **MUST** escalate to authority if enabled.

---

## 16. TruthHash and TruthSignature (Mandatory Signing)

### 16.1 TruthHash (Required)

For every truth state transition:

```
truth_hash = SHA256(canonical_json(truthkey + truth_state + updated_at))
```

### 16.2 TruthSignature (Required for Silver + Gold)

Every Silver and Gold record **MUST** contain a TruthSignature produced by signing TruthHash using GCP KMS:

```
truth_signature = Sign_KMS(truth_hash)
```

`TruthState.security` **MUST** include:

- `truth_hash`
- `truth_signature`
- `kms_key_id`
- `signed_at`

> [!IMPORTANT]
> Consumers **MUST** verify the signature before trusting the truth state.

---

## 17. Threat Model & Adversarial Assumptions (Normative)

Kaori **MUST** assume adversarial environments including:

- Spam and Sybil attacks
- Duplicate and replay attacks
- Evidence forgery
- Validator collusion
- Insider tampering

### 17.1 Required Mitigations

Kaori implementations **MUST** include:

- Standing requirement
- Hash-based duplicate suppression (if enabled)
- Transparent confidence + contradiction flags
- Immutable signed Silver ledger
- Signed Gold truth states
- Rate limiting (recommended)

### 17.2 Explicit Non-Goals

Kaori v1 does **not** guarantee:

- Device attestation
- Proof of unedited media
- Perfect Sybil resistance

---

## 18. Storage Model (Medallion)

Kaori defines four layers:

| Layer | Description |
|-------|-------------|
| **Bronze** | Raw observations and evidence refs |
| **Silver** | Append-only signed truth history |
| **Gold** | Signed latest truth state map |

---

## 19. Minimal API Contract (Normative)

A Kaori implementation **MUST** expose:

| Endpoint | Description |
|----------|-------------|
| `POST /observation` | Submit a new observation |
| `GET /truth/state?truthkey=...` | Get current truth state |
| `GET /truth/history?truthkey=...` | Get truth history (Silver) |
| `GET /claim/schema/{claim_type}` | Get claim type YAML |
| `POST /validator/vote` | Submit a validation vote |

---

## 20. Governance & CI (Normative)

CI **MUST** enforce:

- YAML validity
- Required fields present
- Immutability of released claim schemas
- Mandatory TruthSignature fields
- Mandatory consensus and confidence blocks
- Mandatory `state_verification_policy`

---

## 21. Compatibility Requirements

An implementation is **Kaori-compatible** if it satisfies:

- [ ] Canonical TruthKey
- [ ] YAML-driven claim contracts
- [ ] Deterministic compilation and routing
- [ ] Signed Gold truth states
- [ ] Signed append-only Silver history
- [ ] Consensus and confidence computed per YAML
- [ ] Minimal API contract exposed

---

*End of Kaori Protocol Spec (v1.3)*