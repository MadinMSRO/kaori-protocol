# Kaori Flow — Engineering Specification (v5.0 draft)

> **Status:** v5.0 draft (The 7 Rules of Trust, revised; v4.0 in git history)  
> **Maintainer:** MSRO  
> **Scope:** The "Physics of Trust" — event-sourced, emergent, deterministic trust dynamics.

---

## 0. Relationship to Kaori Truth Standard

| Specification | Scope |
|---------------|-------|
| **TRUTH_SPEC.md** | Defines *what* constitutes truth and *how* it is validated |
| **FLOW_SPEC.md** | Defines *who* does the work, *when* they do it, and *how* they earn standing |

Kaori Flow operates **on top of** Kaori Truth. Observations submitted through Flow are validated according to the Truth Standard.

> [!IMPORTANT]
> **Normative Boundary:** Truth MUST NOT require Flow primitives to compile truth. Flow provides **TrustSnapshot data** as input. Truth produces verified states independently.

---

## 1. The 7 Rules of Trust (Normative)

These rules are **invariants**. They cannot be changed without a major version bump.

> [!NOTE]
> **v5.0 draft (for review).** Rules 2 and 3 change meaning from v4.0: standing no longer grows from aligning with
> final TruthStates. The research that led here is in `research/flow-sim/` (see "What changed from v4.0" at the end
> of this section). The v4.0 text remains in the git history of this file.

---

### Rule 1: Trust is Event-Sourced

Trust MUST be computed from immutable Signals, not stored as mutable state. Membership is a Signal too: every agent
enters through a signed referral, and its lineage is part of the log.

```python
Signal = (agent_id, object_id, signal_type, payload, time, policy_version)
```

**Implications:**
- ✅ Replayable: Recompute trust at any historical point
- ✅ Auditable: See exactly how trust evolved
- ✅ Adaptive: New algorithms can reinterpret same history
- ✅ No hidden state: Complete transparency, including who brought whom in

---

### Rule 2: Everything is an Agent

Every component that emits or receives Signals is an Agent, and every Agent produces Signals.

```
user:amira           → human agent (observer, and validator once eligible)
camera:amira_phone   → the device that captured the evidence
sensor:jetson_042    → IoT agent
ai:generalist_v1     → AI validator agent
provenance:v1        → provenance agent (how real a piece of evidence is)
probe:flood_watch    → probe agent
claimtype:flood.v1   → claimtype agent
policy:flow_v1.0.0   → policy agent
```

All agents have **standing** (a quality metric, 0–1000).

An Agent's standing grows only from Signals it cannot author: what independent, blindly assigned agents render from
its own evidence. It never grows from agreeing with a TruthState it helped form.

**Validators:** All validators (human, AI, sensor) are agents with standing. They render each piece of evidence they
are assigned, blind to the claim, the TruthKey and the owner, and emit those renderings as signed Signals. Kaori
never executes validators; it only records their signed outputs. A validator's standing moves with how its
renderings fit those of other independent agents on the same evidence.

**Implications:**
- ✅ Composable: No special-case logic for different types
- ✅ Scalable: Network grows homogeneously
- ✅ Emergent governance: Authority emerges from standing, not type
- ✅ No capture by agreement: a group cannot raise its own standing by forming truths together

---

### Rule 3: Standing is the Primitive of Trust

Flow MUST reduce trust to a single canonical scalar: **standing ∈ [0, 1000]**

```python
class Agent:
    standing: float  # The only persistent trust variable
```

**Standing:** Stored, global, earned from signals.
**Trust:** Computed, local, derived from standing at query time.

Standing is a prior, never a licence: no Agent's standing can make a rendering outweigh what its own evidence shows.

**Initial Standing (new agents):**

New agents start with a FlowPolicy-defined initial standing (e.g., 100). This follows the *innocent until proven
guilty* principle — we don't assume zero trust until proven otherwise.

```yaml
# In FlowPolicy
agent_defaults:
  initial_standing: 100  # New agents start here
```

**Implications:**
- ✅ Minimal: One variable to track
- ✅ Robust: Hard to corrupt a single metric
- ✅ Comparable: All agents on same scale
- ✅ Fair start: New agents can participate meaningfully
- ✅ Not spendable: standing earned in the past cannot carry a rendering its present evidence contradicts

---

### Rule 4: Standing is Global, Trust is Local (Topological)

**Standing** is the same everywhere:
```python
agent.standing = 750  # True globally
```

**Trust** is computed per TruthKey from the local topology:
```python
effective_trust = compute_trust(
    base_standing,
    evidence,       # realness of this evidence, and its fit with the other renderings of it
    topology,       # bonds: presence, shared error, lineage, declared relationship
    policy          # defines how each of these weighs
)
```

Evidence from independent renderings adds; renderings bound by presence, shared error, lineage or declared
relationship count as one. Checks flow by lineage: a branch receives what its stalk carries, never in proportion to
how many identities hang from it. A referral's declared relationship and trust shape topology (closeness is expected
dependence), never standing.

**The specific weightings are defined in FlowPolicy YAML**, not hardcoded in the spec.

**Implications:**
- ✅ Prevents gaming across domains
- ✅ Enables specialization
- ✅ Resilient to reputation laundering
- ✅ Fakes buy nothing: the cost of an attack is counted in real members, not identities

---

### Rule 5: Trust Updates are Deterministic and Nonlinear

Standing evolution MUST be deterministic, bounded and nonlinear, and MUST learn only from Signals the updated Agent
cannot author. Unused standing decays.

**Why nonlinear:**
- Linear updates are easy to exploit
- Bounded functions prevent gaming
- Diminishing returns at extremes

**Why deterministic:**
- Same signals + same policy → same output
- No randomness, no hidden state

**Why unauthorable:**
- An Agent (or a group) that could author the Signals its standing learns from could raise it at will

**The specific formulas are defined in FlowPolicy YAML.**

---

### Rule 6: Trust Has Phase Transitions

Standing MUST create threshold effects that generate discrete behavioral regimes, and truths form by crossing a
threshold.

**Agents (thresholds defined in FlowPolicy):**
- **Dormant:** Low influence
- **Active:** Proportional influence
- **Eligible to validate:** earned only through in-person observation
- **Dominant:** High influence but capped

**Truths:** A TruthKey condenses when its evidence passes the stakes threshold the ClaimType derives (λ/(1+λ) for
stakes λ); otherwise it remains open, and a key still split when its window closes is a signed `INCONCLUSIVE`
truth. Thresholds are defined in FlowPolicy and the ClaimType; ClaimTypes may only tighten them.

**Implications:**
- ✅ Network self-organizes into tiers
- ✅ Authority emerges naturally
- ✅ Small changes near thresholds → big behavioral shifts
- ✅ Thin evidence stays open rather than forming a weak truth

---

### Rule 7: Adaptiveness Lives in Policy Interpretation

Flow MUST adapt by evolving policy and ClaimType versions, not by rewriting history.

```
Immutable: Signal log (events never change)
Mutable: Policy and ClaimType versions (interpretation evolves)
```

**Policies and ClaimTypes are Agents:**
- `policy:flow_v1.0.0` and `claimtype:sky_cover.v1` have standing
- Their standing follows the network's health Signals (trusted truths formed, keys stuck, keys contested), never
  comparison with an external answer
- Bad versions are naturally deprecated
- Any history may be recompiled under a new version into new TruthStates; nothing is deleted

---

### What changed from v4.0

| Rule | v4.0 | v5.0 draft | Evidence (`research/flow-sim/`) |
|---|---|---|---|
| 1 | Signals only | Membership (referral lineage) is a Signal too | `scale_referral.py`: validators drawn by lineage cost an attacker about one corrupted real member per user; drawn by identity, 4 to 26 members win a quiet hex |
| 2 | Validators' standing rises when their signals align with final TruthStates | Standing grows only from what independent, blind agents render from your own evidence | `tip2.py`: growing standing from formed truths let a coordinated group capture 78% of validator readings; growing it from own evidence held attackers to 24% at half the population, with no total false attractor |
| 3 | One scalar | One scalar, and it is a prior, never a licence | `battle2.py`: one number per agent matched three; `soup_decay.py`: damage grew over time while global memory outweighed local evidence |
| 4 | Context modifiers | Fit with the other renderings of the same evidence; groups count once; checks flow by lineage | `soup.py`, `tip.py`, `scale_referral.py` |
| 5 | Deterministic, nonlinear | Also: learn only from unauthorable Signals | `tip2.py` |
| 6 | Dormant / active / dominant | Adds validator eligibility earned by observation, and truth formation at the stakes threshold | `tip2.py`, `trust.py` |
| 7 | Policy is an agent | Policies and ClaimTypes are agents judged by health Signals; history can be recompiled | Design decision |

All evidence comes from simulated worlds whose provenance and accuracy rates are assumptions; the IAC sky test is
where they get measured.

---

## 2. The 4 Primitives

| Primitive | Role |
|-----------|------|
| **Agent** | Identity unit — everything is an agent |
| **Network** | Trust edges inferred from signal history |
| **Signal** | Immutable event envelope — sole source of truth |
| **Probe** | Coordination object for mission execution |

### 2.1 Probe Specification

A Probe is the **mission runtime agent** that coordinates validation and signs control-plane events.

**Role:**
- Owns mission execution policy
- Defines `ValidationWindowPolicy`
- Signs all `WindowEvents` (WINDOW_OPENED, WINDOW_CLOSED, etc.)
- Acts as the canonical identity for mission operations

**Mission Hub vs Probe:**
- Mission Hub is the **user interface** (visualization, control panel)
- Probe is the **agent** (identity, signer, policy owner)
- Actions triggered via Mission Hub are signed by the probe

**Probe structure:**
```yaml
probe:
  id: probe:flood_watch_001
  owner_agent: user:amira
  claimtypes: [earth.flood.v1, earth.coastal_erosion.v1]
  
  validation_window:
    mode: fixed                    # fixed | rolling | quorum | manual
    open_trigger: first_observation
    duration_seconds: 3600         # 1 hour
    close_trigger: time_elapsed    # time_elapsed | quorum_reached | manual
    quorum:
      min_signals: 5
      required_agent_types: ["user", "ai"]
    ai_validators: ["ai:bouncer_v1", "ai:generalist_v1"]
    theta_min_override: null       # If set, tightens (raises) standing threshold
```

**Key invariants:**
- Probe may tighten θ_min, never loosen below ClaimType minimum
- All WindowEvents are signed by the probe identity
- Resolved policy is committed in `WINDOW_OPENED.policy_hash`

---

## 3. Canonical Signal Envelope

```python
class Signal(BaseModel):
    model_config = ConfigDict(frozen=True)
    
    signal_id: str          # SHA256 of canonical content
    signal_type: str        # e.g., "OBSERVATION_SUBMITTED"
    time: datetime          # UTC, explicit
    agent_id: str           # Emitter
    object_id: str          # Entity being acted on
    context: Optional[dict] # mission_id, probe_id, claimtype_id
    payload: dict           # Signal-specific data
    policy_version: str     # FlowPolicy version
    signature: Optional[str]
```

---

## 4. FlowPolicy (YAML Agent)

FlowPolicy is a YAML configuration that is itself an agent with standing.

**All tunable parameters live in FlowPolicy**, including:
- Standing gain/penalty coefficients
- Saturation curve parameters
- Phase transition thresholds
- Context modifier settings
- Edge weight decay rates
- **Default θ_min** (minimum standing for admissible signals)

See `policies/flow_policy_v1.yaml` for the canonical schema.

---

## 4.1 ValidationSignal and WindowEvent Types

### ValidationSignal

Emitted by validators (human, AI, sensor) during a Validation Window:

```python
class ValidationSignal(BaseModel):
    agent_id: str               # Validator identity
    truthkey_id: str            # TruthKey being validated
    window_id: str              # Must reference an open window
    vote: Literal["RATIFY", "REJECT", "ABSTAIN"]
    confidence: Optional[float] # 0.0–1.0
    timestamp: datetime
    signature: str              # Agent's signature
```

### WindowEvent

Emitted by probes to define admissibility bounds:

```python
class WindowEvent(BaseModel):
    event_type: Literal["WINDOW_OPENED", "WINDOW_CLOSED", "WINDOW_EXTENDED", "WINDOW_ABORTED"]
    window_id: str              # Created by WINDOW_OPENED
    truthkey_id: str
    probe_id: str               # Probe signs all window events
    timestamp: datetime
    policy_hash: Optional[str]  # Hash of resolved ValidationWindowPolicy (on OPEN)
    t_open: Optional[datetime]  # Start bound (on OPEN)
    t_close: Optional[datetime] # End bound (on CLOSE)
    signature: str              # Probe's signature
```

**Why WindowEvents exist:**
- Provable admissibility boundaries (not narrative)
- Replayable compilation (load `window_events[]`)
- Dispute resolution for late votes / boundary issues

---

## 4.2 θ_min Resolution (Signal Admissibility)

**θ_min** determines the minimum standing required for a signal to be admissible in compilation.

### Resolution Hierarchy

1. **FLOW policy** provides default θ_min (governance baseline)
2. **ClaimType** may override (domain-specific tightening)
3. **Probe** may further tighten (mission-specific rules)

> **Probes may only raise θ_min, never lower it below ClaimType minimum.**

The resolved θ_min is committed in `WINDOW_OPENED.policy_hash`.

### Admissibility Rule

A ValidationSignal is **admissible** iff:
- It references the correct `window_id`
- It is signed by a registered agent
- Its timestamp is within `t_open` and `t_close`
- `standing(agent, claimtype) ≥ θ_min`

**Non-admissible signals** may still be recorded for audit and learning but are excluded from consensus aggregation.

---

## 5. Storage Abstraction

The core library defines **abstract interfaces** for storage:

```python
class SignalStore(Protocol):
    def append(self, signal: Signal) -> None: ...
    def get_all(self) -> list[Signal]: ...
    def get_for_agent(self, agent_id: str) -> list[Signal]: ...
    def get_since(self, since: datetime) -> list[Signal]: ...
```

**Reference implementations:**
- `InMemorySignalStore` — for testing
- `JSONLSignalStore` — for simple deployments

**Production implementations (external):**
- PostgreSQL
- BigQuery
- Pub/Sub (as write path)

---

## 6. Integration Pattern

```
┌──────────────────────────────┐
│       MissionHub App         │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│      Kaori Flow Core         │  ← This package
│  (FlowCore, FlowPolicy)      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     SignalStore (abstract)   │
│  ┌─────────┐  ┌──────────┐  │
│  │ Postgres│  │ BigQuery │  │  ← Production injects these
│  └─────────┘  └──────────┘  │
└──────────────────────────────┘
```

---

## 7. Public API

```python
class FlowCore:
    def __init__(self, store: SignalStore, policy: FlowPolicy): ...
    
    def emit(self, signal: Signal) -> None:
        """Append signal to store."""
    
    def get_standing(self, agent_id: str) -> float:
        """Get current standing for agent."""
    
    def get_trust_snapshot(
        self, 
        agent_ids: list[str], 
        context: TrustContext
    ) -> TrustSnapshot:
        """Compute trust snapshot for truth compilation."""
```

---

*End of Kaori Flow Spec (v5.0 draft)*
