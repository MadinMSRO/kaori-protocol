# Kaori Flow Policy Guide — The Physics of Trust

> **Status:** Draft / Institutional Memory  
> **Audience:** Operators, Governance, Auditors  
> **Scope:** Why the `flow_policy.yaml` exists and how to govern it safely.
> **Philosophy:** Kaori treats policy as physics: it must be bounded, replayable, and governable.

---

## 1. The Mental Model: Courts vs. Credibility

To understand Kaori, you must separate **Truth** (the Court) from **Flow** (the Legal System).

*   **TRUTH (`kaori-truth`) is the Court Verdict.**
    It is a deterministic machine. Given rigid evidence and rules, it produces a signed verdict. It does not care about politics, nuance, or "who you are." It blindly checks signatures and timestamps.

*   **FLOW (`kaori-flow`) is the Credibility System.**
    It decides *who is allowed to testify* and *how much their testimony weighs*. It manages the messy reality of reputation, history, and trust.

**FlowPolicy** is the **Constitution** of that credibility system. It defines:
*   Who is a "credible witness"?
*   How do you earn credibility?
*   What happens if you lie (perjury)?
*   Who is allowed to enter the courtroom?

If you change the FlowPolicy, you change the laws of the universe for all agents in the network.

---

## 2. Constitutional Architecture

The FlowPolicy is not just a config file. It is a **Constitution** that enforces a hierarchy of safety.

### The Two Constitutional Restrictions
1.  **Monotonic Tightening:** Downstream actors (ClaimTypes, Probes) can only **TIGHTEN** security, never loosen it.
2.  **Outcome Neutrality:** Policy may govern admissibility and trust dynamics, but it **may not encode truth outcomes** or content-based reweighting. (e.g., "Always trust Agent X" is unconstitutional).

### Recorded vs. Admissible
*   **Recorded:** Every valid signal is recorded in the ledger transparency, even if the agent has low standing.
*   **Admissible:** Only signals meeting the `theta_min` threshold are admissible for truth compilation. We record the "noise" so we can audit why it was excluded.

```
FLOW Constitution (Global)
    │
    │  "Minimum standing allowed is 10."
    │
    ▼
ClaimType (Domain: "Medical")
    │
    │  "Medical claims need standing 50 (Stricter)."
    │  ALLOWED ✅
    │
    │  "Medical claims need standing 0 (Looser)."
    │  FORBIDDEN ❌
    │
    ▼
Probe (Mission: "Heart Surgery")
        
       "This specific mission needs standing 200."
       ALLOWED ✅
       
       "This mission accepts anyone (standing 0)."
       FORBIDDEN ❌
```

This prevents a malicious mission or domain from bypassing global safety rules.

---

## 3. Profiles: The Operator Interface

Operators should **not** tune the raw physics coefficients (rewards/penalties) directly. That leads to chaos.

Instead, we provide **Profiles**:

| Profile | θ_min | Description |
| :--- | :--- | :--- |
| **OPEN** | 0 | **Sandbox.** Anyone can participate. Useful for testnets or low-stakes "public square" data. |
| **STANDARD** | 10 | **Default.** "Earn-to-influence." New agents usually start on probation and must earn their way in. |
| **STRICT** | 50 | **High Stakes.** For financial or critical infrastructure. Fast decay for inactivity. |

> **Definition:** **θ_min (Theta Min)** is the minimum standing required for an agent’s signal to be admissible for aggregation.

### Inheritance
Profiles inherit from each other. `STANDARD` extends `OPEN`, and `STRICT` extends `STANDARD`. This makes the "diff" between security levels readable.

---

## 4. Standing Dynamics & Epistemic Humility

Kaori incentivizes **Epistemic Humility**: knowing what you don't know.

### The Confidence Game

*   **Confident + Right:** High Reward (`calibrated_confidence`)
*   **Unsure + Right:** Moderate Reward
*   **Unsure + Wrong:** Small Penalty
*   **Confident + Wrong:** **Massive Penalty** (`reckless_confidence`)

We explicitly punish "bluffing." If an agent reports 99% confidence and is wrong, they lose significantly more standing than if they had reported 50% confidence.

### Half-Life Decay
Standing is not owned — it is **rented from reality**. It decays over time (e.g., `half_life: P60D`). This prevents "zombie agents" from accumulating power in 2025 and dominating the network in 2030 without doing any work.

---

## 5. Footguns: Common Policy Mistakes

### The "Zero Threshold + Probation" Illusion
*   **Mistake:** Setting `theta_min: 0` while having a Probation period.
*   **Result:** Probation effectively does nothing, because standing 0 is admissible anyway.
*   **Fix:** If you want Probation to matter, `theta_min` must be > 0.

### The "Linear Penalty" Trap
*   **Mistake:** Setting massive linear penalties for being wrong.
*   **Result:** Validators stop voting because one mistake wipes out months of work.
*   **Fix:** Use calibrated penalties. Allow "Abstain" signals to be safe.

### The "Too High θ_min" Collapse
*   **Mistake:** Setting `theta_min` so high that only a tiny elite can influence truth.
*   **Result:** Centralization, fragility, and capture risk. Network looks "dead."
*   **Fix:** Monitor concentration metrics. Use `STRICT` profile only when the mission explicitly demands it.

---

## 6. Linter & Simulation

Before any Policy ID is activated, it must pass the **Linter**. The Linter runs archetypal simulations:

1.  **Honest Validator:** Should trend upward toward a stable high standing.
2.  **Spammer:** Should trend flat or zero.
3.  **Reckless Guesser:** Should trend downwards rapidly.
4.  **Malicious Monolith:** Should trigger concentration alerts.

If a policy configuration causes the "Honest Validator" to lose standing, the linter rejects it.

---

## 7. Version Lineage & Replay

A FlowPolicy file is not "the truth." It is just a record.

### Policy ID + Version
Policies form a **lineage**.
*   `version: 1.0.0`
*   `version: 1.1.0` (points to `parent: 1.0.0`)

### Policy Hash
When a Validation Window opens, it **snapshots the Policy Hash**.
Even if the governance votes to change the policy tomorrow, the TruthState compiled today is forever anchored to the Policy Hash of today.

This allows **Counterfactual Audits**:
> "What would the election result have looked like if we used the stricter v1.2 policy instead of v1.0?"

We can replay the exact same signals against a different policy physics engine to see the divergence.

---

## 8. Policy Change Discipline (Governance Hygiene)

Policy changes are dangerous because they change the laws of trust physics.

**Rules:**

1.  **Immutable:** Policies are locked once deployed. No sneaking edits.
2.  **Lineage:** New policies require a new version and explicit `parent_version` linkage.
3.  **Shadowing:** A policy must run in "shadow mode" (simulation) for N windows before activation.
4.  **Telemetry:** Drift telemetry must be monitored for M days after activation.
5.  **Rollback:** Emergency rollback must be possible to `parent_version`.

This gives us operational safety and prevents "governance by commit."

---

*This guide serves as the institutional memory for Kaori's Governance Engineering.*
