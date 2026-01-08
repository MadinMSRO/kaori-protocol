# Kaori Protocol 🌸

**Real-time truth extraction and verification for high-stakes decisions.**

Kaori Protocol exists to close the most expensive gap in modern decision systems: data can be abundant, but truth and trust are not. It combines two complementary layers — Kaori Truth (the Mechanics of Verification), which deterministically compiles observations into signed, replayable TruthStates anchored by a canonical TruthKey, and Kaori Flow (the Physics of Trust), which models standing, coordination, and adversarial resilience across agents and networks. Together, they make truth operational: verifiable, auditable, and composable without requiring blind trust in any single pipeline.

Kaori transforms raw physical observations into signed, traceable Truth Records and Truth Maps that can be used operationally and defended under scrutiny.

> [!NOTE]
> This repository follows the **Open Core** architecture. The core truth compilation logic is pure, open source, and deterministic.
>
> **Scope:** Open Core includes deterministic truth compilation and canonical specifications. Production systems typically add identity, orchestration, connectors, and deployment infrastructure.

---

## 🏗️ Architecture (Open Core)

### Packages (`packages/`)

*   **`kaori-truth`**: The pure, deterministic compiler. This package has **NO runtime dependencies** on DB/Flow/API layers. It enforces the Mechanics of Verification.
*   **`kaori-flow`**: The Physics of Trust and Coordination (Standing, Probes, Signals).
*   **`kaori-spec`**: The Single Source of Truth for specifications (`TRUTH_SPEC.md`, `FLOW_SPEC.md`) and ClaimType standards.
*   **`kaori-db`**: Standard SQLAlchemy models and migrations.
*   **`kaori-api`**: Reference orchestrator and REST API implementation.

### Implementation Status

| Component | Status | Package |
| :--- | :--- | :--- |
| Truth Compiler | ✅ Production (Pure) | `kaori-truth` |
| Canonicalization | ✅ Complete | `kaori-truth` |
| Temporal Engine | ✅ Complete | `kaori-truth` |
| Specifications | ✅ v2.1 Released | `kaori-spec` |
| Flow (Trust Physics) | ✅ Core Complete | `kaori-flow` |
| API / DB | 🚧 Reference Impl | `kaori-api` |

### The 14 Laws

Kaori Protocol is governed by two complementary sets of invariant laws:

**7 Laws of Truth** (Verification)
1. Truth is Compiled, Not Declared
2. The Compiler is Pure
3. TruthKey is the Universal Address
4. Evidence Precedes Verification
5. Trust is Input, Not Computed
6. Every Output is Signed
7. Truth is Replayable Forever

**7 Rules of Trust** (Coordination)
1. Trust is Event-Sourced
2. Everything is an Agent
3. Standing is the Primitive
4. Standing Global, Trust Local
5. Nonlinear Updates
6. Phase Transitions
7. Policy Interpretation Evolves

See [TRUTH_SPEC.md](packages/kaori-spec/TRUTH_SPEC.md) and [FLOW_SPEC.md](packages/kaori-spec/FLOW_SPEC.md) for normative definitions.

---

## 🧩 The Core Concept: TruthKey

Every truth state is anchored by a canonical TruthKey — the universal join key that unifies truth across space and time:

`{domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}`

**Example:**
`earth:flood:h3:886142a8e7fffff:surface:2026-01-02T10:00Z`

See [**TRUTH_SPEC §5**](packages/kaori-spec/TRUTH_SPEC.md#5-canonical-join-key-truthkey) for normative TruthKey rules.

---

## ⚡ Quick Usage

The Truth Compiler is designed to be embedded in any Python application:

```python
from datetime import datetime, timezone
from kaori_truth.compiler import compile_truth_state

# ... (load claim_type, observations, trust_snapshot)

state = compile_truth_state(
    claim_type=claim_type,
    truth_key=truth_key,
    observations=observations,
    trust_snapshot=trust_snapshot,
    policy_version="1.0.0",
    compiler_version="2.0.0",
    compile_time=datetime(2026, 1, 7, 12, 0, tzinfo=timezone.utc),
)
```

---

## 👩‍💻 Developer Guide

### Prerequisites
*   Python 3.12+

### Installation (Monorepo)

Install the core packages in editable mode:

```bash
# Core Truth Compiler (Required)
pip install -e packages/kaori-truth
pip install -e packages/kaori-spec

# Reference Implementation (Optional)
pip install -e packages/kaori-flow
pip install -e packages/kaori-api
pip install -e packages/kaori-db
```

### Running Tests

Verify the purity and determinism of the Truth Compiler:

**Linux / macOS:**
```bash
export PYTHONPATH="packages/kaori-truth/src"
pytest packages/kaori-truth
```

**Windows PowerShell:**
```powershell
$env:PYTHONPATH="packages\kaori-truth\src"
pytest packages/kaori-truth
```

### Governance
Kaori is governed under a BDFL model led by Madin Maseeh, with MSRO serving as steward.
See [GOVERNANCE.md](GOVERNANCE.md) and [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📚 Documentation

*   [**TRUTH_SPEC.md**](packages/kaori-spec/TRUTH_SPEC.md): The Mechanics of Verification
*   [**FLOW_SPEC.md**](packages/kaori-spec/FLOW_SPEC.md): The Physics of Trust
*   [**OPEN_CORE.md**](OPEN_CORE.md): Architecture definition

## 🔐 Security & Licensing

*   [LICENSE](LICENSE) (Apache 2.0)
*   [SECURITY.md](SECURITY.md)
*   [TRADEMARKS.md](TRADEMARKS.md)

---

**Built by Maldives Space Research Organisation (MSRO)**
*Powering the Unified Data Frontier Initiative.*