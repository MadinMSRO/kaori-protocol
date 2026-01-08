# Kaori Protocol v2.0 Release Notes

**Version:** 2.0.0 (Antigravity)
**Status:** Stable Core

---

## 📦 Distribution Packages

| Package       | Status     | Usage                                                                                                                     |
| ------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------- |
| `kaori-truth` | **Stable** | Pure deterministic Truth compiler. No runtime dependencies on DB/API/Flow layers. Safe for production verification logic. |
| `kaori-spec`  | **Stable** | Normative protocol specifications and ClaimType standards.                                                                |
| `kaori-flow`  | **Stable Core**   | Trust physics implementation (7 Rules of Trust).                                                                                             |
| `kaori-api`   | **Alpha**  | Reference orchestrator implementation.                                                                                    |

---

## 🚀 Getting Started

### Installation (Source)

```bash
git clone https://github.com/MadinMSRO/kaori-protocol.git
cd kaori-protocol
pip install -e packages/kaori-truth
```

### Installation (Pinned Git Release)

```bash
pip install "kaori-truth @ git+https://github.com/MadinMSRO/kaori-protocol.git@v2.0.0#subdirectory=packages/kaori-truth"
```

---

## Usage Pattern

The `kaori-truth` library is designed to be embedded in any Python **3.12+** application.
Python 3.12+ is required to ensure consistent typing and datetime semantics for deterministic compilation.

```python
from kaori_truth.compiler import compile_truth_state
from kaori_truth.canonical import canonical_hash

# See tests/test_determinism.py for full integration example
```

---

## ⚠️ Breaking Changes from v1

* **Removed:** All SQL/API code from Truth layer.
* **Removed:** `claim_payload` external input (claims are strictly derived).
* **Changed:** TruthKey format is now strictly validatable + canonicalized.
* **Changed:** Timestamp handling is strictly UTC bucketed.

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

The following interfaces are stable in v2.x:

* `compile_truth_state()`
* `canonicalize()` / `canonical_json()` / `canonical_hash()`
* TruthKey parsing + construction
* Canonical primitive schemas (TruthState, Observation, TrustSnapshot)

---

*Released by MSRO*
