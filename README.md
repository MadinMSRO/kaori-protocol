# Kaori Protocol 🌸

**The Operating System for Truth Verification.**

Kaori is an open protocol for verifying physical world events at scale. It combines AI validation, human consensus, and cryptographic signing to produce auditable, machine-readable ground truth.

---

## The Problem

Every major decision today—insurance payouts, climate credits, disaster response, AI training—depends on answering one question: **"What actually happened in the physical world?"**

But verification is broken:
- 🛰️ **Satellite data** is powerful, but can't confirm what's on the ground.
- 📱 **Crowdsourced reports** are fast, but noisy and unverifiable.
- ⛓️ **Blockchain oracles** secure digital claims, but not physical reality.

There is no standard protocol for turning raw observations into trusted, signed truth records.

**Kaori is that protocol.**

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                         KAORI PROTOCOL                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   📲 OBSERVE          🤖 VALIDATE           ✅ VERIFY               │
│   ───────────         ───────────           ─────────               │
│   Reporter submits    AI (CLIP/Bouncer)     Human validators        │
│   image + metadata    checks content        reach consensus         │
│                       safety & quality                              │
│                                                                     │
│   ────────────────────────────────────────────────────────────────  │
│                              ↓                                      │
│                    🔐 SIGNED TRUTH STATE                            │
│                    ─────────────────────                            │
│                    Immutable, auditable,                            │
│                    machine-readable record                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The ELT Pipeline

| Layer | Description |
|-------|-------------|
| **Bronze** | Raw ingestion (Images, GPS, Timestamps) |
| **Silver** | Validated observations (AI + Human checked) |
| **Gold** | Final truth states (Cryptographically signed) |

---

## Why Not Blockchain?

| | **Blockchain** | **Kaori** |
|---|---|---|
| **Solves** | "Who owns what?" | "What is true about reality?" |
| **Input** | Transactions | Physical observations |
| **Consensus** | Proof-of-Work/Stake | AI + Human Expertise |
| **Latency** | Minutes | Seconds |

> Blockchain secures *transactions*. Kaori secures *facts*. We're the trust layer that validates real-world data *before* it hits the chain.

---

## Use Cases

| Domain | Application |
|--------|-------------|
| 🌊 **Disaster Response** | Real-time, verified flood/fire/storm reports |
| 🌿 **Climate Finance** | Audit-grade evidence for carbon credits |
| 🛡️ **Insurance** | Parametric payouts based on verified sensor data |
| 🤖 **AI Training** | High-quality labeled data for earth observation models |

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
Open **http://localhost:5173** to see the "Kaori Pulse" live feed.

### 3. Simulate the Protocol
```bash
python tools/demo_lifecycle.py
```
Watch an observation get submitted → validated by AI → verified by consensus → signed.

---

## Repository Structure

```
kaori-protocol/
├── SPEC.md                 # Core Truth Protocol (v1.3)
├── FLOW_SPEC.md            # Incentive & Mission Layer (v1.0)
├── core/                   # Consensus Engine + Validators
│   ├── engine.py           # Main orchestration
│   ├── validators/         # AI Pipeline (Bouncer, Generalist)
│   └── db/                 # Persistence (SQLite, BigQuery-ready)
├── flow/api/               # FastAPI REST Endpoints
├── frontend/               # React Dashboard ("Kaori Pulse")
├── schemas/                # JSON Schema for claim types
│   ├── earth/              # Floods, Fires, Infrastructure
│   ├── ocean/              # Coral, Pollution, Depth
│   └── space/              # Debris, Satellites
├── terraform/              # GCP Deployment (Cloud Run, BigQuery, GCS)
└── tools/                  # CLI utilities
```

---

## Specifications

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | Defines claims, validation, consensus, confidence, and cryptographic signing |
| [FLOW_SPEC.md](FLOW_SPEC.md) | Defines missions, incentives, validator standing, and Kaori Credits |

---

## Built By and For

**Maldives Space Research Organisation (MSRO)**

*Building infrastructure for a world that needs to know the truth.*