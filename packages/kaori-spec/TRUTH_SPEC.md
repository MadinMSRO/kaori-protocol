# Kaori Protocol — Truth Standard (v2.1)

> **Status:** v2.1 (7 Laws of Truth)  
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

### 1.3 The 7 Laws of Truth (Normative)

These laws are **invariants**. They cannot be changed without a major version bump.

---

#### Law 1: Truth is Compiled, Not Declared

Truth MUST be computed from observations through a deterministic compiler, not asserted by authority.

```python
truth_state = compile(observations, trust_snapshot, policy)
```

**Implication:** No one can "declare" something true. They can only provide observations.

---

#### Law 2: The Compiler is Pure

The Truth compiler MUST be a pure function — no side effects, no external state, no network calls.

```
Same inputs → identical output (byte-for-byte)
```

**Implication:** Truth is mathematics, not consensus.

---

#### Law 3: TruthKey is the Universal Address

Every truth state MUST be addressed by a canonical TruthKey.

```
{domain}:{topic}:{spatial}:{id}:{z}:{time}
```

**Implication:** Any physical claim has exactly one address. Truth is joinable across any system.

---

#### Law 4: Evidence Precedes Verification

Truth MUST NOT be compiled without explicit observations.

```python
if len(observations) == 0:
    return TruthState(status="UNVERIFIED")
```

**Implication:** Absence of evidence is not evidence. No observations → no truth.

---

#### Law 5: Trust is Input, Not Computed

The compiler MUST receive trust as frozen snapshot, not compute it.

```python
def compile(observations, trust_snapshot):  # Trust is DATA
    # Compiler never calls flow.get_trust()
```

**Implication:** Truth layer has no opinion on who is trusted. That's Flow's job.

---

#### Law 6: Every Output is Signed

Final TruthStates MUST be cryptographically signed with full provenance.

```python
signature = sign(canonical_hash(truth_state))
```

**Implication:** Anyone can verify a truth state is authentic without trusting the verifier.

---

#### Law 7: Truth is Replayable Forever

Given the same inputs, any implementation MUST produce identical output at any future time.

```
compile(inputs) == compile(inputs)  # Always, forever
```

**Implication:** You can replay truth 100 years later and get the same answer.

---

### 1.4 Non-Goals (v2)

Kaori v2 does **NOT** attempt to:

- Verify cryptographic authenticity of media capture devices
- Prove evidence is unedited
- Solve Sybil attacks perfectly
- Define domain-specific satellite calibration schemas

---

## 2. Open-Core Architecture

### 2.1 Package Structure

Kaori is structured as a monorepo with strict dependency rules:

```
packages/
├── kaori-truth/       # Pure deterministic compiler (NO DB, NO API, NO Flow)
├── kaori-flow/        # Trust physics (MAY import kaori-truth)
├── kaori-db/          # Database schemas (MAY import truth + flow)
├── kaori-api/         # REST API (MAY import all)
└── kaori-spec/        # Protocol docs + ClaimType schemas
```

### 2.2 Dependency Rules (Normative)

| Package | MAY Import | MUST NOT Import |
|---------|------------|-----------------|
| `kaori-truth` | (none) | `kaori-flow`, `kaori-db`, `kaori-api` |
| `kaori-flow` | `kaori-truth` | `kaori-db`, `kaori-api` |
| `kaori-db` | `kaori-truth`, `kaori-flow` | `kaori-api` |
| `kaori-api` | (all) | (none) |

> [!CAUTION]
> **kaori-truth MUST NOT import kaori-flow, kaori-db, or kaori-api.** This is the foundational rule that ensures determinism.

### 2.3 Compiler Purity (Normative)

The Truth compiler (`compile_truth_state()`) **MUST** be a pure function:

```python
def compile_truth_state(
    claim_type: ClaimType,
    truth_key: str,
    observations: list[Observation],
    trust_snapshot: TrustSnapshot,  # Data, NOT provider
The Truth compiler (`compile_truth_state()`) **MUST** be a pure function:

```python
def compile_truth_state(
    claim_type: ClaimType,
    truth_key: str,
    observations: list[Observation],
    trust_snapshot: TrustSnapshot,  # Data, NOT provider
    policy_version: str,
    compiler_version: str,
    compile_time: datetime,  # REQUIRED, explicit
) -> TruthState:
    """
    Pure function: Given identical inputs, produces byte-identical output.
    """
```

The compiler **MUST** derive the `TruthState.claim` payload deterministically from observations, trust_snapshot, claim_type, and truth_key according to ClaimType policy.

Implementations **MUST NOT** accept externally provided claim output. The claim payload **MUST** be derived internally via `derive_claim_payload()`.

**Hard Requirements:**
- NO imports from database modules
- NO imports from API modules  
- NO imports from kaori-flow
- NO runtime side effects
- NO file IO (except ClaimType loading)
- NO wall-clock time access (`datetime.now()` is FORBIDDEN)
- `compile_time` MUST be explicitly provided

---

## 3. Canonicalization Subsystem (Normative)

### 3.1 Purpose

All hashing and signing **MUST** go through canonical serialization to ensure byte-identical output across environments.

### 3.2 Canonical JSON Rules

Canonical JSON **MUST** enforce:

| Rule | Requirement |
|------|-------------|
| Key Ordering | Sorted alphabetically |
| Separators | Minimal: `(',', ':')` |
| Unicode | NFC normalized |
| Whitespace | Trim + collapse |
| Floats | Quantized to 6 decimal places |
| Datetimes | UTC ISO8601 with Z suffix |
| IDs | Lowercase `[a-z0-9._-]` only |

### 3.3 Canonical API

```python
from kaori_truth.canonical import canonicalize, canonical_json, canonical_hash

# Primary API
bytes_data = canonicalize(obj)           # → bytes (UTF-8 encoded)
json_str = canonical_json(obj)           # → str
hash_hex = canonical_hash(obj)           # → str (SHA256 lowercase hex)
```

### 3.4 Primitive Canonicalization

Each primitive **MUST** have a canonical representation:

| Primitive | Canonical Form |
|-----------|----------------|
| TruthKey | `{domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}` |
| ClaimType | Canonical JSON of contract fields |
| Observation | Canonical JSON with sorted evidence_refs |
| TrustSnapshot | Canonical JSON of agent_trusts (sorted by agent_id) |
| EvidenceRef | `sha256` + normalized `uri` |

---

## 4. Temporal Index Subsystem (Normative)

### 4.1 Purpose

All datetime handling **MUST** go through the temporal subsystem to ensure determinism.

### 4.2 Rules

1. All internal datetimes **MUST** be timezone-aware
2. All datetimes **MUST** be converted to UTC immediately
3. Naive datetimes **MUST** be rejected (raise `NaiveDatetimeError`)
4. Temporal bucketing **MUST** truncate (not round) to bucket boundary

### 4.3 Four Times

| Time | Description | Source |
|------|-------------|--------|
| `event_time` | When the event occurred | Observation `reported_at` |
| `receipt_time` | When observation was received | System clock (metadata only) |
| `compile_time` | When compilation occurred | Explicit input to compiler |
| `truthkey_time_bucket` | Bucket for TruthKey | Derived from `event_time` |

> [!IMPORTANT]
> **TruthKey MUST derive from `event_time`, NOT `receipt_time`**, unless ClaimType policy explicitly specifies otherwise.

### 4.4 Temporal Bucketing

```python
from kaori_truth.time import bucket_datetime, format_bucket

# Truncate to bucket boundary
bucketed = bucket_datetime(event_time, "PT1H")  # Hourly bucket

# Format for TruthKey
time_bucket = format_bucket(bucketed)  # "2026-01-07T12:00Z"
```

Bucket durations are ISO8601:

| Duration | Meaning | Example |
|----------|---------|---------|
| `PT1H` | Hourly | `2026-01-07T12:00Z` |
| `PT4H` | 4-hourly | `2026-01-07T08:00Z` |
| `P1D` | Daily | `2026-01-07T00:00Z` |

---

## 5. Canonical Join Key: TruthKey

### 5.1 TruthKey String Format (Normative)

TruthKey **MUST** be representable as:

```
{domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
```

**Example:**
```
earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00Z
```

### 5.2 TruthKey Canonicalization Rules

| Rule | Requirement |
|------|-------------|
| Segments | All lowercase |
| Separator | Colon (`:`) only |
| Charset | `[a-z0-9._-]` only |
| time_bucket | ISO8601 UTC `YYYY-MM-DDTHH:MMZ` |

### 5.3 TruthKey Components

| Field | Description |
|-------|-------------|
| `domain` | `earth`, `ocean`, `space`, `meta` (extensible) |
| `topic` | `flood`, `erosion`, `research_artifact`, etc. |
| `spatial_system` | `h3`, `healpix`, `meta` |
| `spatial_id` | H3/HEALPix index or meta artifact hash |
| `z_index` | `surface`, `underwater`, `knowledge`, etc. |
| `time_bucket` | Bucket start boundary in UTC derived from bucket duration |

### 5.4 Domain → Spatial System Mapping (Normative)

| Domain | Spatial System | z_index Examples | spatial_id Source |
|--------|----------------|------------------|-------------------|
| `earth` | `h3` | `surface` | H3 cell index |
| `ocean` | `h3` | `underwater`, `seabed` | H3 cell index |
| `space` | `healpix` | `orbital_shell` | HEALPix pixel |
| `meta` | `meta` | `knowledge`, `na` | `id_strategy` governs |

### 5.5 Meta Namespace (Non-Spatial Claims)

For research artifacts, datasets, and non-physical claims:

```yaml
truthkey:
  spatial_system: meta
  z_index: knowledge
  id_strategy: content_hash | provided_id | hybrid
```

| Strategy | spatial_id Source |
|----------|-------------------|
| `content_hash` (default) | SHA256 of artifact content (truncated to 32 chars) |
| `provided_id` | User-supplied stable identifier |
| `hybrid` | content_hash if present, else provided_id |

**Example Meta TruthKey:**
```
meta:research_artifact:meta:abc123def456789012345678901234:knowledge:2026-01-07T00:00Z
```

> [!IMPORTANT]
> `id_strategy` is ONLY applicable when `spatial_system == "meta"`. 
> Earth/Ocean/Space domains MUST use H3/HEALPix.

---

## 6. Claim Types (YAML Contracts)

### 6.1 Purpose

ClaimType YAML files define the "law" for a claim class. They **MUST** define:

- TruthKey formation
- Evidence requirements
- AI validation routing
- Consensus model
- Confidence model
- Temporal decay

### 6.2 ClaimType ID Format (Normative)

```
{namespace}.{name}.v{major}
```

Examples: `earth.flood.v1`, `ocean.coral_bleaching.v2`

### 6.3 ClaimType Hash (Normative)

Every ClaimType **MUST** have a canonical hash:

```python
claim_type_hash = canonical_hash(claim_type.canonical())
```

This hash **MUST** be stored in TruthState for auditability.

### 6.4 Versioning and Immutability

Released claim types **MUST** be immutable:

- `*_v1.yaml` **MUST NOT** be modified
- Changes require `*_v2.yaml`

### 6.5 Output Schema (Normative)

Every ClaimType **MUST** define an output schema that TruthState.claim must satisfy:

```yaml
# Inline schema
output_schema:
  type: object
  required: [severity, water_level_meters]
  properties:
    severity:
      type: string
      enum: [low, moderate, high, critical]
    water_level_meters:
      type: number
      minimum: 0

# OR reference to external schema
output_schema_ref: schemas/output/flood_v1.json
```

**Validation Requirements:**
1. Schema validation MUST occur BEFORE hashing/signing
2. Invalid payloads MUST fail compilation deterministically
3. Validation errors MUST use stable error codes (not locale-dependent messages)

```python
from kaori_truth.validation import validate_claim_payload, SchemaValidationError

try:
    validated = validate_claim_payload(payload, schema)
except SchemaValidationError as e:
    # Deterministic error with error codes and paths
    raise CompilationError(f"Schema validation failed: {e}")
```

---

## 7. Observations (Bronze)

### 7.1 Canonical Observation Schema (Normative)

Every observation **MUST** include:

```json
{
  "observation_id": "uuid",
  "claim_type": "earth.flood.v1",
  "reported_at": "2026-01-07T12:00:00Z",
  "reporter_id": "agent-001",
  "reporter_context": {
    "standing": "silver",
    "trust_score": 0.75,
    "source_type": "human"
  },
  "geo": { "lat": 4.175, "lon": 73.509 },
  "payload": {},
  "evidence_refs": [
    {
      "uri": "gs://kaori-evidence/photo1.jpg",
      "sha256": "abc123..."
    }
  ]
}
```

### 7.2 Observation Hash (Normative)

Every observation **MUST** have a canonical hash:

```python
observation_hash = canonical_hash(observation.canonical())
```

---

## 8. Evidence Handling (Normative)

### 8.1 EvidenceRef Schema

EvidenceRef **MUST** include content-binding:

```json
{
  "uri": "gs://bucket/path/file.jpg",
  "sha256": "lowercase_hex_64_chars",
  "mime_type": "image/jpeg",
  "capture_time": "2026-01-07T11:30:00Z"
}
```

### 8.2 Evidence Identity

Evidence identity is determined by `sha256` hash, NOT URI.

The URI is a non-canonical pointer to fetch content; the hash is the canonical identity.

---

## 9. TrustSnapshot (Data Schema)

### 9.1 Purpose

TrustSnapshot is a frozen snapshot of trust state provided by Flow to Truth for compilation.

> [!IMPORTANT]
> **TrustSnapshot is DATA, not a provider.** Truth receives TrustSnapshot as input; it NEVER calls TrustProvider directly.

### 9.2 Schema

```python
class TrustSnapshot:
    snapshot_id: str
    snapshot_time: datetime
    agent_trusts: dict[str, AgentTrust]
    snapshot_hash: str  # SHA256 of canonical agent_trusts
```

### 9.3 Determinism Requirement

TrustSnapshot hash **MUST** be deterministic:

```python
snapshot_hash = canonical_hash({
    k: v.canonical() 
    for k, v in sorted(agent_trusts.items())
})
```

---

## 10. Truth States (Gold)

### 10.1 Status Values (Normative)

#### Intermediate Statuses (during window)

| Status | Description |
|--------|-------------|
| `PENDING` | Initial state |
| `LEANING_TRUE` | Evidence trending true |
| `LEANING_FALSE` | Evidence trending false |
| `UNDECIDED` | Conflicting evidence |
| `PENDING_HUMAN_REVIEW` | Escalated |

#### Final Statuses (at window end, MUST be signed)

| Status | Description |
|--------|-------------|
| `VERIFIED_TRUE` | Confirmed true |
| `VERIFIED_FALSE` | Confirmed false |
| `INCONCLUSIVE` | Could not determine |
| `EXPIRED` | Window closed |

### 10.2 TruthState Schema (Normative)

```python
class TruthState:
    truthkey: str
    claim_type: str
    claim_type_hash: str           # Hash of ClaimType contract
    status: TruthStatus
    verification_basis: VerificationBasis
    
    # Claim output payload (REQUIRED)
    # MUST be validated against ClaimType.output_schema
    # MUST be included in semantic_hash computation
    claim: dict
    
    # Confidence
    ai_confidence: float
    confidence: float
    confidence_breakdown: ConfidenceBreakdown
    
    # Transparency
    transparency_flags: list[str]
    
    # Audit fields
    compile_inputs: CompileInputs
    
    # Evidence
    evidence_refs: list[str]
    observation_ids: list[str]
    
    # Security
    security: SecurityBlock
```

### 10.3 CompileInputs (Normative)

Every TruthState **MUST** store explicit compile inputs:

```python
class CompileInputs:
    observation_ids: list[str]
    claim_type_id: str
    claim_type_hash: str
    policy_version: str
    compiler_version: str
    trust_snapshot_hash: str
    compile_time: datetime
```

---

## 11. Semantic Hash vs State Hash (Normative)

### 11.1 Purpose

Two hashes are required for different use cases:

| Hash | Stability | Use Case |
|------|-----------|----------|
| `semantic_hash` | Stable across `compile_time` | Comparing semantic equivalence |
| `state_hash` | Changes with `compile_time` | Full audit trail |

### 11.2 Semantic Hash Computation

Semantic hash depends ONLY on:
- `truthkey`
- `claim_type` + `claim_type_hash`
- `claim` payload (schema-validated)
- `status`
- `verification_basis`
- `confidence` values
- `transparency_flags`
- `observation_ids`
- `trust_snapshot_hash`
- `policy_version`

It does NOT include `compile_time` or `compiler_version`.

> [!IMPORTANT]
> The `claim` payload MUST be included in semantic_hash. This binds the truth output to the signature.

### 11.3 State Hash Computation

State hash includes ALL of semantic content PLUS:
- `compile_time`
- `compiler_version`

### 11.4 SecurityBlock Schema (Normative)

```python
class SecurityBlock:
    semantic_hash: str      # Stable content hash
    state_hash: str         # Full envelope hash
    signature: str          # Signature over state_hash
    signing_method: str     # "local_hmac" | "gcp_kms"
    key_id: str
    signed_at: datetime     # Explicit, not wall-clock
```

> [!IMPORTANT]
> **Temporal Integrity:** For deterministic compilation, `signed_at` **MUST** equal `compile_time` unless explicitly overridden by orchestrator policy. Any override **MUST** be stored in compile inputs to preserve auditability.

---

## 12. TruthHash and TruthSignature (Mandatory Signing)

### 12.1 Signing Requirement

Every Silver and Gold record **MUST** contain a signature:

```
signature = Sign(state_hash)
```

### 12.2 Signature Verification

Consumers **MUST** verify:
1. `semantic_hash` matches computed semantic content
2. `state_hash` matches computed full envelope
3. `signature` verifies against `state_hash`

---

## 13. Consensus Model (YAML-defined)

Consensus **MUST** be computed strictly from ClaimType YAML.

For **weighted threshold**:

```
score = Σ(weight(standing) × vote_value)
```

---

## 14. Confidence Model (YAML-defined)

Composite confidence **MUST** be computed deterministically:

```
confidence = Σ(component_weight × component_value) + Σ(modifiers)
confidence = clamp(confidence, 0.0, 1.0)
```

---

## 15. Two-Lane Verification Policy

### 15.1 Monitor Lane (Optimistic)

For `risk_profile: monitor`:
- AI **MAY** auto-verify if confidence threshold met
- Composite confidence **MUST** be computed

### 15.2 Critical Lane (Strict)

For `risk_profile: critical`:
- Human consensus **MUST** be required
- Authority escalation **MUST** be defined

---

## 16. Orchestrator Pattern (Normative)

### 16.1 Purpose

The Orchestrator is the ONLY component that:
1. Reads from database
2. Calls TrustProvider to get TrustSnapshots
3. Calls the pure Truth compiler
4. Persists TruthState to database

### 16.2 Location

The Orchestrator lives in `kaori-api`, NOT in `kaori-truth`.

```python
# kaori_api/orchestrator.py

class TruthOrchestrator:
    def compile_observations(
        self,
        observations: list[Observation],
        truth_key: str,
        claim_type_id: str,
        compile_time: datetime,
    ) -> TruthState:
        # 1. Load ClaimType from DB/file
        claim_type = self.load_claim_type(claim_type_id)
        
        # 2. Get TrustSnapshot from Flow
        trust_snapshot = self.trust_provider.get_trust_snapshot(...)
        
        # 3. Call PURE compiler
        state = compile_truth_state(
            claim_type=claim_type,
            truth_key=truth_key,
            observations=observations,
            trust_snapshot=trust_snapshot,
            policy_version=claim_type.policy_version,
            compile_time=compile_time,
        )
        
        # 4. Sign and persist
        state = sign_truth_state(state, compile_time)
        self.persist(state)
        
        return state
```

---

## 17. Storage Model (Medallion)

| Layer | Description |
|-------|-------------|
| **Bronze** | Raw observations and evidence refs |
| **Silver** | Append-only signed truth history |
| **Gold** | Signed latest truth state map |

---

## 18. Compatibility Requirements

An implementation is **Kaori-compatible** if it satisfies:

- [x] Canonical TruthKey
- [x] Canonical JSON serialization for all hashing
- [x] Pure compiler with no hidden dependencies
- [x] Semantic/state hash split
- [x] Explicit compile inputs stored in TruthState
- [x] Signed Gold truth states
- [x] Signed append-only Silver history
- [x] TrustSnapshot as data input (not provider call)

---

## 19. Reference Implementation

The reference implementation is available at:

```
packages/kaori-truth/     # Pure compiler
packages/kaori-flow/      # Trust physics
packages/kaori-api/       # Orchestrator
```

Install:
```bash
pip install kaori-truth kaori-flow kaori-api
```

---

*End of Kaori Truth Standard (v2.0)*