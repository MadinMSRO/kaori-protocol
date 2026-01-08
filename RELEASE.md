# Kaori Protocol v2.1 Release Notes

**Version:** 2.1.0 (The Resonance Release)
**Status:** Stable Core (Truth & Flow)

---

## What's New in v2.1

### The 14 Laws

Kaori Protocol is now governed by two complementary sets of invariant laws:

**7 Laws of Truth** (TRUTH_SPEC v2.1)
1. Truth is Compiled, Not Declared
2. The Compiler is Pure
3. TruthKey is the Universal Address
4. Evidence Precedes Verification
5. Trust is Input, Not Computed
6. Every Output is Signed
7. Truth is Replayable Forever

**7 Rules of Trust** (FLOW_SPEC v4.0)
1. Trust is Event-Sourced
2. Everything is an Agent
3. Standing is the Primitive
4. Standing Global, Trust Local
5. Nonlinear Updates
6. Phase Transitions
7. Policy Interpretation Evolves

### Kaori Flow Core Complete

- `FlowCore` with 3-function API: `emit()`, `get_standing()`, `get_trust_snapshot()`
- `FlowPolicy` as YAML configuration (policy is itself an agent)
- `FlowReducer` for event-sourced standing computation
- `TrustComputer` for contextual trust with network modifiers
- `SignalStore` abstraction with reference implementations
- 18 new tests (108 total across packages)

---

## 📦 Distribution Packages

| Package       | Status          | Usage                                                                 |
| ------------- | --------------- | --------------------------------------------------------------------- |
| `kaori-truth` | **Stable**      | Pure deterministic Truth compiler. No runtime dependencies on DB/API/Flow. |
| `kaori-spec`  | **Stable**      | Normative specifications (TRUTH_SPEC v2.1, FLOW_SPEC v4.0).          |
| `kaori-flow`  | **Stable Core** | Trust physics implementation (7 Rules of Trust).                     |
| `kaori-api`   | **Alpha**       | Reference orchestrator implementation.                               |

---

## 🚀 Getting Started

### Installation (Source)

```bash
git clone https://github.com/MadinMSRO/kaori-protocol.git
cd kaori-protocol
pip install -e packages/kaori-truth
pip install -e packages/kaori-flow
```

### Installation (Pinned Git Release)

```bash
pip install "kaori-truth @ git+https://github.com/MadinMSRO/kaori-protocol.git@v2.1.0#subdirectory=packages/kaori-truth"
pip install "kaori-flow @ git+https://github.com/MadinMSRO/kaori-protocol.git@v2.1.0#subdirectory=packages/kaori-flow"
```

---

## Usage

### Truth Compilation

```python
from kaori_truth.compiler import compile_truth_state

state = compile_truth_state(
    claim_type=claim_type,
    truth_key=truth_key,
    observations=observations,
    trust_snapshot=trust_snapshot,
    policy_version="1.0.0",
    compiler_version="2.1.0",
    compile_time=datetime.now(timezone.utc),
)
```

### Flow Core

```python
from kaori_flow import FlowCore, FlowPolicy, TrustContext

flow = FlowCore(policy=FlowPolicy.default())
flow.register_agent("user:amira", role="observer")
standing = flow.get_standing("user:amira")
snapshot = flow.get_trust_snapshot(["user:amira"], TrustContext())
```

---

## ⚠️ Breaking Changes from v2.0

* **TRUTH_SPEC:** Section numbering changed (1.2 → 1.3 for Laws, 1.3 → 1.4 for Non-Goals)
* **kaori-flow:** New module structure (`core.py`, `policy.py`, `reducer.py`, `trust.py`, `store.py`)
* **Removed:** `legacy_archive/` directory (preserved in v2.1.0 tag)

---

## 🛡️ Stability Guarantees

We guarantee that `compile_truth_state(inputs)` produces **byte-identical output** for the same:

* compiler version
* canonicalized inputs
* ClaimType contract version
* TrustSnapshot hash
* compile_time

---

## ✅ Stable API Surface (Guaranteed)

**kaori-truth:**
* `compile_truth_state()`
* `canonicalize()` / `canonical_json()` / `canonical_hash()`
* TruthKey parsing + construction
* Canonical primitive schemas

**kaori-flow:**
* `FlowCore.emit()`, `FlowCore.get_standing()`, `FlowCore.get_trust_snapshot()`
* `FlowPolicy.load()`, `FlowPolicy.default()`
* `SignalStore` protocol
* `Signal`, `TrustSnapshot`, `TrustContext` schemas

---

## 📚 Documentation

* [TRUTH_SPEC.md](packages/kaori-spec/TRUTH_SPEC.md) — The 7 Laws of Truth
* [FLOW_SPEC.md](packages/kaori-spec/FLOW_SPEC.md) — The 7 Rules of Trust
* [INTEGRATION.md](INTEGRATION.md) — Production integration guide

---

*Released by MSRO — Maldives Space Research Organisation*
