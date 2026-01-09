# Kaori Protocol — Integration Guide

This guide describes how to integrate Kaori Protocol into a production application.

> [!NOTE]
> The core library provides reference implementations (in-memory, JSONL).
> Production deployments implement storage backends for their infrastructure.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Your Application                           │
│                    (MissionHub, Dashboard)                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Kaori Flow Core                             │
│                                                                 │
│   FlowCore(store=YourSignalStore, policy=FlowPolicy.load(...)) │
│                                                                 │
│   Public API:                                                   │
│   • emit(signal)              → Append signal                   │
│   • get_standing(agent_id)    → Current standing                │
│   • get_trust_snapshot(...)   → For truth compilation           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Kaori Truth Core                            │
│                                                                 │
│   compile_truth_state(observations, trust_snapshot, ...)       │
│                                                                 │
│   Output: Deterministic, signed TruthState                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Integration Patterns

### Pattern A: Embedded Library

Direct integration into your Python application.

```python
from kaori_flow import FlowCore, FlowPolicy
from kaori_truth.compiler import compile_truth_state

# Initialize with your storage backend
flow = FlowCore(
    store=YourPostgresSignalStore(connection),
    policy=FlowPolicy.load("flow_policy_v1.yaml"),
)

# Use directly
flow.register_agent("user:amira", role="observer")
standing = flow.get_standing("user:amira")
```

**Best for:** Single-service architectures, Python backends.

---

### Pattern B: Sidecar Service

Kaori runs as a separate service with REST/gRPC API.

```
Your App ──HTTP──▶ Kaori Service ──▶ Storage
```

**Best for:** Polyglot environments, microservices.

---

### Pattern C: Event-Driven

Signals flow through a message queue.

```
Your App ──Pub/Sub──▶ Signal Consumer ──▶ Storage
                              │
Your App ◀────────── Query API ◀──────┘
```

**Best for:** High-throughput, async requirements.

---

## Storage Backends

The core library defines the `SignalStore` protocol:

```python
class SignalStore(Protocol):
    def append(self, signal: Signal) -> None: ...
    def get_all(self) -> List[Signal]: ...
    def get_for_agent(self, agent_id: str) -> List[Signal]: ...
    def get_since(self, since: datetime) -> List[Signal]: ...
```

### Reference Implementations (Included)

| Implementation | Use Case |
|----------------|----------|
| `InMemorySignalStore` | Testing, development |
| `JSONLSignalStore` | Simple deployments, prototyping |

### Production Implementations (You Build)

| Backend | Purpose |
|---------|---------|
| PostgreSQL | Hot path (operational queries, low latency) |
| BigQuery | Cold path (analytics, historical replay) |
| Pub/Sub + Consumer | Async ingestion at scale |

---

## What You Need to Implement

### 1. Signal Store (Required)

Implement `SignalStore` for your database:

```python
class PostgresSignalStore:
    def append(self, signal: Signal) -> None:
        # INSERT INTO signals ...
    
    def get_all(self) -> List[Signal]:
        # SELECT * FROM signals ORDER BY time
```

### 2. Identity Layer (Required)

Map your auth system to Kaori agent IDs:

```python
def get_agent_id(user: YourUser) -> str:
    return f"user:{user.id}"
```

### 3. Orchestration (Application-Specific)

- Probe lifecycle management
- Mission assignment
- ClaimType registration
- Observer assignment

---

## Deployment Considerations

| Consideration | Recommendation |
|---------------|----------------|
| **Database** | PostgreSQL 14+ with append-only constraints |
| **Caching** | Optional — standings can be cached, invalidated on signal |
| **Scaling** | Signal store is the bottleneck — scale writes first |
| **Replay** | Keep full signal history for audit/replay |

---

## Example: Minimal Integration

```python
from kaori_flow import FlowCore, FlowPolicy, TrustContext
from kaori_truth.compiler import compile_truth_state

# 1. Initialize Flow
flow = FlowCore(policy=FlowPolicy.default())

# 2. Register agents
flow.register_agent("user:amira", role="observer")
flow.register_agent("sensor:sat_001", role="validator")

# 3. Application logic creates observations
observation = create_observation(...)

# 4. Get trust snapshot
snapshot = flow.get_trust_snapshot(
    agent_ids=["user:amira", "sensor:sat_001"],
    context=TrustContext(claimtype_id="earth.flood.v1"),
)

# 5. Compile truth
truth_state = compile_truth_state(
    claim_type=flood_claim_type,
    truth_key="earth:flood:h3:abc:surface:2026-01-09T10:00Z",
    observations=[observation],
    trust_snapshot=snapshot,
    policy_version="1.0.0",
    compiler_version="2.1.0",
    compile_time=datetime.now(timezone.utc),
)

# 6. Emit truth outcome (updates standings)
flow.emit_truthstate(
    truthkey=truth_state.truth_key,
    status=truth_state.status,
    confidence=truth_state.confidence_score,
    contributors=["user:amira"],
    outcome="correct" if truth_state.status == "VERIFIED_TRUE" else "unknown",
)
```

---

## Enterprise Support

For production deployments, MSRO uses:

- Optimized storage implementations
- Deployment blueprints
- Performance tuning
- Custom ClaimType development
- Integration consulting


---

*Part of Kaori Protocol by MSRO*
