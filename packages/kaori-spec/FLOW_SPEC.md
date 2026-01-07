# Kaori Flow — Engineering Specification (v3.0)

> **Status:** v3.0 (Open-Core Architecture)  
> **Maintainer:** MSRO  
> **Scope:** Defines the "Physics of Trust" (Agents, Networks, Signals, Probes) that powers the Kaori Protocol.

---

## 0. Relationship to Kaori Truth Standard

| Specification | Scope |
|---------------|-------|
| **TRUTH_SPEC.md** (Kaori Truth Standard) | Defines *what* constitutes truth and *how* it is validated |
| **FLOW_SPEC.md** (Kaori Flow) | Defines *who* does the work, *when* they do it, and *how* they earn standing |

Kaori Flow operates **on top of** Kaori Truth. Observations submitted through Flow are validated according to the Truth Standard.

> [!IMPORTANT]
> **Normative Boundary:** Truth MUST NOT require Flow primitives to compile truth. Flow primitives (Probes, Agents, Network) are coordination mechanisms. Truth receives **TrustSnapshot data** and produces verified states independently.

---

## 1. Open-Core Architecture

### 1.1 Package Location

Flow primitives and TrustProvider live in `packages/kaori-flow/`:

```
packages/kaori-flow/
├── src/kaori_flow/
│   ├── primitives/
│   │   ├── agent.py          # Agent with continuous standing
│   │   ├── network.py        # NetworkEdge for trust graph
│   │   ├── signal.py         # Immutable Signal envelope
│   │   └── probe.py          # Probe coordination object
│   └── trust_provider.py     # TrustProvider implementation
└── tests/
```

### 1.2 Dependency Rules

| Rule | Description |
|------|-------------|
| Flow MAY import Truth | `from kaori_truth import TrustSnapshot` |
| Truth MUST NOT import Flow | Compiler is pure |
| TrustProvider lives in Flow | NOT in Truth |

### 1.3 Trust Snapshot Data vs Provider

> [!CAUTION]
> **Critical Distinction:**
> - `TrustSnapshot` (data schema) lives in `kaori-truth`
> - `TrustProvider` (implementation) lives in `kaori-flow`
> - Truth compiler receives `TrustSnapshot` as input
> - Truth compiler NEVER calls `TrustProvider`

```python
# kaori-truth defines the DATA schema
class TrustSnapshot:
    snapshot_id: str
    snapshot_time: datetime
    agent_trusts: dict[str, AgentTrust]
    snapshot_hash: str

# kaori-flow implements the PROVIDER
class TrustProvider(Protocol):
    def get_trust_snapshot(
        self,
        agent_ids: list[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        ...
```

---

## 2. Architectural Philosophy: Physics vs. Mechanics

| Layer | Responsibility | Primitives |
|-------|----------------|------------|
| **Kaori Truth** (Mechanics) | Deterministic verification of claims. Pure functions. | Observations, TruthStates, ClaimTypes |
| **Kaori Flow** (Physics) | Dynamic calculation of trust. Stateful coordination. | Agents, Network, Signals, Probes |

---

## 3. Core Primitives (The Physics Layer)

Kaori Flow is built on a **Fractal Graph Architecture**. There is no distinction between an individual and a group; both are Agents.

### 3.1 The Agent (The Cell)

The **Agent** is the atomic unit of the system. An Agent can represent a person, a sensor, a drone, a squad, or an entire organization.

**Schema:**

```python
class Agent:
    agent_id: UUID
    agent_type: AgentType        # individual, squad, sensor, official
    standing: float              # Continuous scalar (0.0 to ∞)
    qualifications: dict         # Per-domain capabilities
    isolation_metric: float      # Echo chamber detection
    created_at: datetime
    updated_at: datetime
    
    @property
    def derived_class(self) -> str:
        """Derive standing class from scalar value."""
        if self.standing < 100: return "bronze"
        elif self.standing < 250: return "silver"
        elif self.standing < 500: return "expert"
        else: return "authority"
```

#### Standing (Normative Definition)

Standing is a **continuous scalar float** (canonical representation). Standing classes are **derived** for backwards compatibility:

| Standing Value | Derived Class | Typical Role |
|----------------|---------------|--------------|
| 0 – 99 | `bronze` | New/Unverified |
| 100 – 249 | `silver` | Verified Contributor |
| 250 – 499 | `expert` | Domain Expert |
| 500+ | `authority` | Official/Calibrated Sensor |

### 3.2 The Network (The Tissue)

The **Network** defines the relationships between Agents. Trust flows through these edges.

**Edge Types:**

| Type | Direction | Description |
|------|-----------|-------------|
| `VOUCH` | A → B | A explicitly trusts B |
| `MEMBER_OF` | A → B | A is part of Squad B |
| `COLLABORATE` | A ↔ B | History of agreeing |
| `CONFLICT` | A ↔ B | History of disagreement |

### 3.3 Signals (The Chemical Gradient)

Signals are immutable event envelopes that propagate through the Network.

> [!IMPORTANT]
> **Signals are immutable. Probes are stateful.** A Signal MUST NOT contain an embedded Probe.

```python
class Signal:
    signal_id: UUID
    type: SignalType          # AUTOMATED_TRIGGER, MANUAL_TRIGGER, SCHEDULED_TRIGGER, SYSTEM_ALERT
    source_id: str            # Emitter
    timestamp: datetime
    data: dict                # Payload
    
    class Config:
        frozen = True  # Signals are immutable
```

### 3.4 Probes (The Coordination Object)

> [!IMPORTANT]
> **Probe is a first-class primitive of Kaori Flow (Normative).**
> - Flow MUST define and manage Probe creation, dedupe, lifecycle.
> - Truth MUST NOT require Probes to compile truth.
> - Truth MAY reference `probe_id` only as optional provenance metadata.

A **Probe** is a persistent, stateful coordination object that directs agents to gather observations.

```python
class Probe:
    probe_id: UUID
    probe_key: str              # Deterministic dedupe key
    claim_type: str
    status: ProbeStatus
    scope: dict
    created_by_signal: UUID
    active_signals: list[UUID]
    requirements: dict
    expires_at: datetime
```

#### ProbeKey (Deterministic Dedupe Key)

ProbeKey MUST be derived deterministically:

```
ProbeKey = hash(claim_type + spatial_id + z_index + time_bucket)
```

---

## 4. The Laws of Physics (Trust Dynamics)

Trust is calculated dynamically at runtime via the **TrustProvider** interface.

### 4.1 Law 1: Fractal Inheritance (Bounded)

An Agent's effective power is the sum of their Intrinsic Standing and the standing inherited from their Network Context.

> `Power(A) = Intrinsic(A) + (Power(Squad) * InheritanceDecay)`

**Bounds (Mandatory):**
```yaml
constants:
  inheritance_decay: 0.2      # 20% per hop
  max_inheritance_depth: 3    # Maximum hops
```

**Cycle Safety:**
Traversal MUST maintain a visited set to prevent infinite loops.

### 4.2 Law 2: Shared Liability

If an Agent acts maliciously, the penalty propagates up the `MEMBER_OF` edges to their Squads.

> `Damage(Squad) = Damage(Agent) * LiabilityFactor`

### 4.3 Law 3: Isolation Dampening (Immunity)

Agents that form strictly internal loops ("Echo Chambers") receive a penalty.

> `EffectivePower = Power * (1 - IsolationMetric)`

**Isolation Metric:**
```python
IsolationMetric = internal_collabs / (internal_collabs + external_collabs + 1)
```

### 4.4 Law 4: Grounding

Agreement with High-Assurance Agents clears Isolation penalties.

**High-Assurance Agents:**
- `official` type agents
- Calibrated `sensor` type agents

### 4.5 Law 5: Accuracy Dynamics

Agent standing evolves based on verification outcomes.

> `Δ Standing = Outcome × Magnitude × AccuracyFactor`

---

## 5. TrustProvider Interface (Normative)

### 5.1 Location

TrustProvider **MUST** be implemented in `kaori-flow`, NOT in `kaori-truth`.

```python
# packages/kaori-flow/src/kaori_flow/trust_provider.py

class TrustProvider(Protocol):
    """
    Protocol for providing trust data to Truth compilation.
    Truth NEVER calls this directly - Orchestrator does.
    """
    
    def get_trust_snapshot(
        self,
        agent_ids: list[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        """
        Get a frozen trust snapshot for the given agents.
        
        Args:
            agent_ids: List of agent IDs to include
            claim_type: The claim type for context-specific trust
            snapshot_time: The time to snapshot (MUST be explicit)
            
        Returns:
            TrustSnapshot with computed hash
        """
        ...
    
    def get_power(
        self,
        agent_id: str,
        claim_type: str,
    ) -> float:
        """Get effective power for an agent."""
        ...
```

### 5.2 TrustSnapshot Determinism (Audit Requirement)

> [!IMPORTANT]
> **For audit-grade verification, TrustSnapshot MUST be deterministic.**

TrustSnapshot hash MUST be computed from canonical representation:

```python
snapshot_hash = canonical_hash({
    k: v.canonical()
    for k, v in sorted(agent_trusts.items())
})
```

Truth MUST store this hash in TruthState for replay verification.

### 5.3 In-Memory Implementation

A reference in-memory implementation is provided:

```python
class InMemoryTrustProvider:
    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._squads: dict[str, list[str]] = {}
    
    def register_agent(self, agent: Agent):
        self._agents[str(agent.agent_id)] = agent
    
    def get_trust_snapshot(
        self,
        agent_ids: list[str],
        claim_type: str,
        snapshot_time: datetime,
    ) -> TrustSnapshot:
        agent_trusts = {}
        for agent_id in agent_ids:
            agent = self._agents.get(agent_id)
            if agent:
                power = self._compute_power(agent_id)
                agent_trusts[agent_id] = AgentTrust(
                    agent_id=agent_id,
                    effective_power=power,
                    standing=agent.standing,
                    derived_class=agent.derived_class,
                    flags=[],
                )
        return TrustSnapshot.create(
            snapshot_id=str(uuid4()),
            snapshot_time=snapshot_time,
            agent_trusts=agent_trusts,
        )
```

---

## 6. Integration with Kaori Truth

### 6.1 Data Flow

```
┌─────────────────┐
│ Orchestrator    │ (kaori-api)
└────────┬────────┘
         │
    ┌────▼────┐
    │  Flow   │ → TrustSnapshot (data)
    └────┬────┘
         │
    ┌────▼────┐
    │  Truth  │ → TruthState (pure compilation)
    └─────────┘
```

### 6.2 TrustContext (Input)

```python
class TrustContext:
    action: str           # "vote" | "observe" | "trigger_probe"
    claim_type: str       # e.g., "earth.flood.v1"
    domain: str           # e.g., "earth"
    scope: dict           # { spatial: {...}, temporal: {...} }
```

### 6.3 AgentTrust (Output)

```python
class AgentTrust:
    agent_id: str
    effective_power: float       # Computed power
    standing: float              # Raw standing value
    derived_class: str           # "bronze" | "silver" | "expert" | "authority"
    flags: list[str]             # e.g., ["ISOLATED", "HIGH_ASSURANCE"]
    
    def canonical(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "effective_power": round(self.effective_power, 6),
            "standing": round(self.standing, 6),
            "derived_class": self.derived_class.lower(),
            "flags": sorted(self.flags),
        }
```

---

## 7. Signal Processor (The Reflex Arc)

The **Signal Processor** transmutes Signals into Probe mutations.

**Workflow:**
1. **Ingest:** Receive `Signal` from any source
2. **Authenticate:** Check `source_id` standing
3. **Compute ProbeKey:** Derive deterministic key
4. **Deduplicate:** Check for existing Probe
5. **React:**
   - No active Probe: Create new
   - Active Probe exists: Link signal
6. **Route:** Emit assignments

**Action Outputs:**

| Action | Trigger |
|--------|---------|
| `CREATE_PROBE` | New ProbeKey, sufficient authority |
| `ESCALATE_REVIEW` | Low confidence detected |
| `ISSUE_ALERT` | Urgent sensor signal |
| `FREEZE_AGENT` | Malicious behavior |
| `REQUEST_EVIDENCE` | Additional observation needed |

---

## 8. Configuration (The Constants)

```yaml
# schemas/flow/physics_v1.yaml

constants:
  inheritance_decay: 0.2         # 20% of Squad's power
  max_inheritance_depth: 3       # Maximum hops
  liability_factor: 0.5          # Squad takes 50% of member's damage
  isolation_penalty: 0.9         # 90% power reduction if isolated

thresholds:
  squad_formation: 5             # Collaborations to form squad
  conflict_persistence: permanent

standing_thresholds:
  bronze_max: 99
  silver_max: 249
  expert_max: 499
  # authority: 500+

standing_dynamics:
  accuracy:
    observation_correct: 1.0
    observation_wrong: 1.5
    vote_correct: 0.5
    vote_wrong: 0.8
  bounds:
    min: 0.0
    max: 1000.0
    initial: 10.0
```

---

## 9. Production-Only Features

The following are NOT part of the open-core specification and remain production-specific:

| Feature | Description |
|---------|-------------|
| Advanced Sybil Resistance | Proprietary detection algorithms |
| Multi-Tenant Identity | Enterprise RBAC |
| Network Propagation Optimization | Scaling for millions of agents |
| AI Validators | Model weights and routing |
| Real-Time Dashboards | Infrastructure monitoring |

---

## 10. Reference Implementation

Install:
```bash
pip install kaori-flow
```

Usage:
```python
from kaori_flow import TrustProvider, InMemoryTrustProvider, Agent

# Create provider
provider = InMemoryTrustProvider()

# Register agents
provider.register_agent(Agent(
    agent_id=uuid4(),
    standing=150.0,
))

# Get snapshot for Truth compilation
snapshot = provider.get_trust_snapshot(
    agent_ids=["agent-001"],
    claim_type="earth.flood.v1",
    snapshot_time=datetime.now(timezone.utc),
)

# Pass to Truth compiler
from kaori_truth import compile_truth_state
state = compile_truth_state(
    ...,
    trust_snapshot=snapshot,  # Data, not provider
    ...
)
```

---

## 11. Out of Scope (Deferred)

The following are explicitly **not** part of Kaori Flow v3.0:

- **Credits:** Non-transferable energy for work
- **Payments:** Financial incentives
- **Reputation Tokens:** On-chain reputation

---

*End of Kaori Flow Spec (v3.0)*
