# Kaori Protocol 🌸

**Real-time truth extraction and verification for high-stakes decisions.**

Kaori transforms raw physical observations into signed, traceable **Truth Records** and **Truth Maps** that can be used operationally and defended under scrutiny.

> *"The system that compiles real-world observations into signed, traceable truth states — enabling operational use, defensibility, and scalable verification at national and global levels."*

---

## What Problem Kaori Solves

In high-stakes domains (disasters, coastal erosion, subsidence, marine incidents), information is often:

- 🔀 **Fragmented** across agencies and communities  
- ❓ **Difficult to verify** and unify  
- � **Slow to validate**  
- ⚔️ **Politically contested**  
- � **Hard to defend** in audits, courts, or funding evaluations  

**Kaori solves this** by producing standardized, signed truth objects and truth histories from observations — with transparent verification and confidence semantics.

---

## What Kaori Produces

Kaori produces two primary artifacts:

### 🥇 Gold Truth Map (Current State)
A signed latest truth state for each location/time/topic.  
> *"What is the current verified state of reality here?"*

### 🥈 Silver Truth Ledger (Full History)
An append-only, signed history of how truth evolved over time.  
> *"How did we arrive at this truth, and who/what validated it?"*

These artifacts can be consumed by:
- **GeoHub** map layers  
- **Operational systems** (emergency response, enforcement)  
- **Satellite companies** (truth-as-a-service)  
- **UN / Climate fund audits**  
- **Legal and enforcement workflows**

---

## How Kaori Works

```
Observation → Processing → Candidate Truth → Validation → Final Truth
```

| Step | Description |
|------|-------------|
| **1. Observe** | Observations submitted by humans, drones, IoT sensors, or official sources |
| **2. Compile** | Kaori compiles them deterministically into a candidate truth state |
| **3. Validate** | Routed through AI ladder (Bouncer → Generalist → Specialist) + Human gating |
| **4. Finalize** | Consensus and confidence rules applied per ClaimType YAML |
| **5. Sign** | Every truth transition is hashed and signed for audit-grade records |

---

## The Core Concept: TruthKey

Every truth state is anchored by a canonical **TruthKey** — the universal join key that unifies truth across space and time:

```
{domain}:{topic}:{spatial_system}:{spatial_id}:{z_index}:{time_bucket}
```

**Example:**
```
earth:flood:h3:8928308280fffff:surface:2026-01-02T10:00Z
```

TruthKey enables:
- ⚡ **Scalable indexing** across regions  
- 🔗 **Deterministic retrieval** and compilation  
- 🌐 **Interoperability** across systems  

---

## Trust & Validation Model

Kaori assumes adversarial environments and mitigates abuse through:

### Standing-Based Trust
Every reporter/validator has **standing** (bronze → silver → expert → authority) which influences:
- Vote weight  
- Gating privileges  
- Confidence computation  
- Dispute escalation  

### Two-Lane Verification

| Lane | Speed | Use Case |
|------|-------|----------|
| **Monitor Lane** | Fast | AI-verified truth with transparency flags |
| **Critical Lane** | Deliberate | Human gating + weighted consensus required |

This enables both **speed** (for monitoring) and **defensibility** (for high-stakes decisions).

---

## Security & Defensibility

Kaori produces cryptographically signed truth states:

- Each truth transition generates a **TruthHash**  
- TruthHash is signed using **KMS**  
- Consumers must **verify signatures** before trusting  

This makes Kaori truth artifacts:
- ✅ **Tamper-evident**  
- ✅ **Auditable**  
- ✅ **Defensible** in high-scrutiny contexts  

---

## What Kaori Does NOT Solve (v1)

Kaori v1 focuses on **governance and verification**, not cryptographic perfection:

| Not in Scope | How Kaori Mitigates |
|--------------|---------------------|
| Device attestation | Standing + thresholds |
| Proof of unedited media | Contradiction detection |
| Perfect Sybil resistance | Dispute resolution + signed audit history |

---

## Quick Start

### 1. Run the API
```bash
uvicorn flow.api.main:app --port 8001
```

### 2. Run the Visual Dashboard
```bash
cd frontend && npm run dev
```
Open **http://localhost:5173** to see **Kaori Pulse** — the real-time truth feed.

### 3. Simulate the Full Protocol
```bash
python tools/demo_lifecycle.py
```
Watch an observation get submitted → validated by AI → verified by consensus → signed.

---

## API Reference

| Endpoint | Description |
|----------|-------------|
| `POST /observations/submit` | Submit observation (multipart) |
| `GET /truth/state/{truthkey}` | Get current signed truth |
| `GET /truth/history/{truthkey}` | Get signed truth history |
| `GET /truth/feed` | Get recent truth states (dashboard) |
| `POST /votes` | Submit validator vote |

See [SPEC.md](SPEC.md) for full protocol specification.

---

## Repository Structure

```
kaori-protocol/
├── SPEC.md                 # Core Truth Protocol (v1.3)
├── FLOW_SPEC.md            # Incentive & Mission Layer (v1.0)
├── core/                   # Consensus Engine + Validators
│   ├── engine.py           # Main orchestration
│   ├── validators/         # AI Pipeline (Bouncer, Generalist)
│   └── db/                 # Persistence (Bronze/Silver/Gold)
├── flow/api/               # FastAPI REST Endpoints
├── frontend/               # React Dashboard ("Kaori Pulse")
├── schemas/                # ClaimType YAML definitions
├── terraform/              # GCP Deployment (Cloud Run, BigQuery)
└── tools/                  # CLI utilities + demo scripts
```

---

## Why Kaori Matters

Kaori enables **Truth as a Service**:

| Consumer | Value |
|----------|-------|
| **Satellite companies** | Signed ground truth feeds |
| **Governments** | Verified evidence packs |
| **Climate funds** | Audit-grade truth history |
| **Enforcement agencies** | Defensible decision records |

> **Kaori turns ground truth into a national capability and a strategic export.**

---

## Built By and For

**Maldives Space Research Organisation (MSRO)**

Powering the **Unified Data Frontier Initiative**:  
*GeoHub • DataHub • MissionHub*

*Building infrastructure for a world that needs to know the truth.*