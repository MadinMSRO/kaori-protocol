# Kaori Flow — Engineering Specification (v4.0)

> **Status:** v4.0 (The 7 Rules of Trust)  
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

---

### Rule 1: Trust is Event-Sourced

Trust MUST be computed from immutable Signals, not stored as mutable state.

```python
Signal = (agent_id, object_id, signal_type, payload, time, policy_version)
```

**Implications:**
- ✅ Replayable: Recompute trust at any historical point
- ✅ Auditable: See exactly how trust evolved
- ✅ Adaptive: New algorithms can reinterpret same history
- ✅ No hidden state: Complete transparency

---

### Rule 2: Everything is an Agent

Every component that emits or receives signals is an Agent.

```
user:amira          → human agent
sensor:jetson_042   → IoT agent
probe:flood_watch   → probe agent
claimtype:flood.v1  → claimtype agent
policy:flow_v1.0.0  → policy agent
```

All agents have **standing** (a quality metric, 0–1000).

**Effective trust** is computed at compilation time based on:
- The agent's standing
- Their role in the specific compilation (observer, validator, etc.)
- The context (claimtype, probe, network position)

No static "trust-having" vs "non-trust-having" distinction. Trust relevance is determined by role in context.

**Implications:**
- ✅ Composable: No special-case logic for different types
- ✅ Scalable: Network grows homogeneously
- ✅ Emergent governance: Authority emerges from standing, not type

---

### Rule 3: Standing is the Primitive of Trust

Flow MUST reduce trust to a single canonical scalar: **standing ∈ [0, 1000]**

```python
class Agent:
    standing: float  # The only persistent trust variable
```

**Standing:** Stored, global, earned from signals.  
**Trust:** Computed, local, derived from standing at query time.

**Implications:**
- ✅ Minimal: One variable to track
- ✅ Robust: Hard to corrupt a single metric
- ✅ Comparable: All agents on same scale

---

### Rule 4: Standing is Global, Trust is Local (Topological)

**Standing** is the same everywhere:
```python
agent.standing = 750  # True globally
```

**Trust** depends on context:
```python
effective_trust = compute_trust(
    base_standing,
    context,        # claimtype, probe, mission
    signal_history, # for network/edge computation  
    policy          # defines which modifiers apply
)
```

**The specific modifiers are defined in FlowPolicy YAML**, not hardcoded in the spec.

**Implications:**
- ✅ Prevents gaming across domains
- ✅ Enables specialization
- ✅ Resilient to reputation laundering

---

### Rule 5: Trust Updates are Deterministic and Nonlinear

Standing evolution MUST be deterministic but nonlinear.

**Why nonlinear:**
- Linear updates are easy to exploit
- Bounded functions prevent gaming
- Diminishing returns at extremes

**Why deterministic:**
- Same signals + same policy → same output
- No randomness, no hidden state

**The specific formulas are defined in FlowPolicy YAML.**

---

### Rule 6: Trust Has Phase Transitions

Standing MUST create threshold effects that generate discrete behavioral regimes.

**Three phases (thresholds defined in FlowPolicy):**
- **Dormant:** Low influence
- **Active:** Proportional influence  
- **Dominant:** High influence but capped

**Implications:**
- ✅ Network self-organizes into tiers
- ✅ Authority emerges naturally
- ✅ Small changes near thresholds → big behavioral shifts

---

### Rule 7: Adaptiveness Lives in Policy Interpretation

Flow MUST adapt by evolving policy versions, not by rewriting history.

```
Immutable: Signal log (events never change)
Mutable: Policy version (interpretation evolves)
```

**FlowPolicy is itself an Agent:**
- `policy:flow_v1.0.0` has standing
- Good truth outcomes → policy standing increases
- Bad policies are naturally deprecated

---

## 2. The 4 Primitives

| Primitive | Role |
|-----------|------|
| **Agent** | Identity unit — everything is an agent |
| **Network** | Trust edges inferred from signal history |
| **Signal** | Immutable event envelope — sole source of truth |
| **Probe** | Coordination object for mission execution |

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

See `policies/flow_policy_v1.yaml` for the canonical schema.

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

*End of Kaori Flow Spec (v4.0)*
