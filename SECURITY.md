# Security Policy

## Reporting a Vulnerability

**DO NOT OPEN PUBLIC ISSUES FOR SECURITY VULNERABILITIES.**

If you discover a security vulnerability in Kaori Protocol — especially in:

- `kaori-truth` (Truth Compiler)
- `kaori-flow` (Trust / Standing Physics)
- signing / hashing / canonicalization components

please report it immediately to:

**Email:** security_kaori@msro.mv

Include the following when possible:
- affected package + version
- reproduction steps
- proof-of-concept (if safe)
- impact assessment

---

## Scope & Severity

### Critical
- Any violation of determinism or purity guarantees in `kaori-truth`
- Canonicalization inconsistencies that affect hashing or signing
- Unauthorized signature forgery or key misuse
- Any vulnerability that allows forging, mutating, or replaying TruthStates without detection

### High
- Denial-of-Service vulnerabilities in the reference implementation (`kaori-api`)
- Abuse vectors that prevent compilation, verification, or query operations at scale

---

## Safe Harbor

We support safe harbor for security researchers who:

- act in good faith
- avoid privacy violations
- avoid service disruption
- do not exploit the vulnerability beyond proof-of-concept
- report the issue promptly through the channel above

We will not pursue legal action against researchers who follow this policy.
