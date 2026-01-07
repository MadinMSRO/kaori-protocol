# Kaori Protocol Governance

## 1. Governance Model
Kaori Protocol follows a **Benevolent Dictator for Life (BDFL)** model.

- **BDFL:** Madin Maseeh  
- **Steward:** Maldives Space Research Organisation (MSRO)

The steward exists to ensure long-term continuity of the protocol and to protect the core truth invariants.

---

## 2. Decision Making

### 2.1 Final Authority
The BDFL retains final authority over:

- **Protocol Specification:** `kaori-spec` (TRUTH_SPEC, FLOW_SPEC, normative schemas)
- **Core Truth Invariants:** Any changes affecting determinism, purity, canonicalization, hashing, signing, or TruthKey format

MSRO, as steward, ensures the protocol remains coherent and stable across time.

### 2.2 Community Contributions
We welcome community participation through:

- Pull requests
- RFC proposals
- Ecosystem tools and integrations

Contributions are reviewed by maintainers and may be merged if aligned with protocol intent and compatibility guarantees.

### 2.3 Breaking Changes
Breaking changes MUST include:

- SemVer bump
- Migration notes
- Updated tests demonstrating determinism + compatibility

---

## 3. Roles

### BDFL
The BDFL is responsible for:

- setting and protecting protocol direction
- approving changes to invariants
- final decisions in disputed PRs and RFCs

### Maintainers
Maintainers have commit access and are appointed by the BDFL, with MSRO stewardship.

They are responsible for review, triage, release preparation, and issue moderation.

### Contributors
Contributors are community members who submit pull requests, issues, or RFC proposals.

---

## 4. Release Process

- Core packages (especially `kaori-truth`) follow strict SemVer.
- Releases MUST include determinism and boundary tests.
- Protocol and core releases are tagged and published through GitHub Releases.

---

## 5. Continuity
If the BDFL becomes inactive for an extended period, MSRO (as steward) may appoint a successor BDFL or governance process to ensure continuity of the protocol.
