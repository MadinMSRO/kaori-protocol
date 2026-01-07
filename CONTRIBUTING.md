# Contributing to Kaori

We welcome contributions to the Open Core.

Kaori is a protocol-first project. Please read the purity rules carefully before submitting changes to the Truth compiler.

---

## 1. Purity Rules (Strict)

If modifying `packages/kaori-truth`:

- **NO** new runtime dependencies.
- **NO** I/O operations (file, network, database).
- **NO** imports from `kaori-flow`, `kaori-db`, or `kaori-api`.
- **MUST** pass determinism + boundary tests:
  - `test_determinism.py`
  - `test_import_boundaries.py`

> The Truth compiler is deterministic mathematics. These rules are enforced to preserve replayability and auditability.

---

## 2. Spec Changes vs Code Changes

- Changes to protocol rules, schemas, and semantics must be proposed via PRs to `packages/kaori-spec`.
- Changes to implementation logic must preserve the normative guarantees defined in the spec.

Breaking changes require a SemVer bump and migration notes.

---

## 3. Developer Certificate of Origin (DCO)

By contributing, you certify you have the right to submit your code under the Apache 2.0 license.

Please sign your commits:

```bash
git commit -s -m "Your message"
```

---

## 4. Testing

Run the Truth package tests before submitting:

```bash
pytest packages/kaori-truth
```

---

## 5. Code Style

* Python 3.12+ features encouraged.
* Strict type hints required.
* Format with `black` and `isort`.
