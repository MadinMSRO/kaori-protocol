# Kaori Flow — Engineering Specification (v1.0)

> **Status:** Draft v1.0 (Implementation Grade)  
> **Maintainer:** MSRO  
> **Scope:** Defines the operational layer for mission creation, reward distribution, standing evolution, and work assignment within the Kaori Protocol ecosystem.

---

## 0. Relationship to Kaori Truth Standard

| Specification | Scope |
|---------------|-------|
| **SPEC.md** (Kaori Truth Standard) | Defines *what* constitutes truth and *how* it is validated |
| **FLOW_SPEC.md** (Kaori Flow) | Defines *who* does the work, *when* they do it, and *how* they earn standing and credits |

Kaori Flow operates **on top of** Kaori Truth. Observations submitted through Flow are validated according to the Truth Standard.

---

## 1. Normative Language

The following keywords are to be interpreted as described in **RFC 2119**:

| Keyword | Meaning |
|---------|---------|
| **MUST / MUST NOT** | Absolute requirement |
| **SHOULD / SHOULD NOT** | Recommended |
| **MAY** | Optional |

---

## 2. Core Primitives

### 2.1 Mission

A **Mission** is a request for ground truth observations within a defined spatial and temporal scope.

```json
{
  "mission_id": "uuid",
  "claim_type": "earth.flood.v1",
  "created_by": "system|authority|partner",
  "created_at": "ISO8601",
  "status": "open|assigned|completed|expired|cancelled",
  
  "scope": {
    "spatial": {
      "system": "h3",
      "cells": ["8928308280fffff", "8928308281fffff"],
      "resolution": 8
    },
    "temporal": {
      "start": "ISO8601",
      "end": "ISO8601"
    }
  },
  
  "requirements": {
    "min_observations": 3,
    "min_standing": "bronze",
    "evidence_required": true
  },
  
  "rewards": {
    "base_credits": 20,
    "priority_level": "standard|urgent|critical",
    "bonus_multiplier": 1.0
  }
}
```

### 2.2 Assignment

An **Assignment** links a Mission to a specific Reporter.

```json
{
  "assignment_id": "uuid",
  "mission_id": "uuid",
  "reporter_id": "uuid",
  "assigned_at": "ISO8601",
  "status": "pending|submitted|verified|rejected|expired",
  "observation_id": "uuid|null"
}
```

### 2.3 Standing

**Standing** represents a user's trust level within the Kaori ecosystem.

| Class | Weight | Privileges |
|-------|--------|------------|
| `bronze` | 1 | Submit observations, vote on non-critical claims |
| `silver` | 3 | Vote on all claims, access priority missions, unlock badges |
| `expert` | 7 | Specialist validation, dispute resolution, train AI, access research data |
| `authority` | 10 | Override votes, escalation endpoint, policy changes |

### 2.4 Kaori Credits

**Kaori Credits** are the internal unit of contribution within the ecosystem. Credits are **non-transferable** and **non-monetary**. They represent accumulated contribution value.

Credits unlock:
- Standing promotions
- Priority mission access
- Ecosystem privileges
- Recognition badges
- Access to premium features

---

## 3. Mission Lifecycle

### 3.1 Mission States

```
DRAFT → OPEN → ASSIGNED → COMPLETED
                ↓
             EXPIRED
```

| State | Description |
|-------|-------------|
| `draft` | Created but not yet published |
| `open` | Published and accepting assignments |
| `assigned` | All slots filled, awaiting observations |
| `completed` | Required observations submitted and verified |
| `expired` | Temporal window closed without completion |
| `cancelled` | Manually cancelled by creator |

### 3.2 Mission Creation

Missions **MAY** be created by:

1. **System (Automated):**
   - IoT sensor triggers (e.g., water level > threshold)
   - Satellite anomaly detection
   - Scheduled monitoring tasks

2. **Authority (Manual):**
   - Disaster response coordination
   - Policy verification requirements

3. **Partners (API):**
   - Research institutions needing ground truth
   - Conservation organizations
   - International monitoring bodies

### 3.3 Mission Triggers (Normative)

For automated mission creation, the system **MUST** support:

```yaml
triggers:
  iot_threshold:
    sensor_type: "water_level"
    condition: "value > 150"  # cm
    claim_type: "earth.flood.v1"
    spatial_expansion: 1      # Include neighboring H3 cells
    priority: "urgent"
    
  satellite_anomaly:
    source: "copernicus_ndwi"
    condition: "delta > 0.3"
    claim_type: "earth.flood.v1"
    priority: "critical"
    
  scheduled:
    cron: "0 6 * * *"         # Daily at 6 AM
    claim_type: "ocean.coral_health.v1"
    scope: "all_monitored_reefs"
    priority: "standard"
```

---

## 4. Assignment and Notification

### 4.1 Assignment Algorithm

When a Mission opens, the system **MUST**:

1. **Identify eligible reporters** within the spatial scope
2. **Filter by standing** (>= `min_standing`)
3. **Rank by:**
   - Proximity to mission center
   - Trust score (higher = priority)
   - Recent activity (active users preferred)
   - Standing class (higher = priority for critical missions)

4. **Assign slots** up to `max_assignments` (default: 2× `min_observations`)

### 4.2 Notification Delivery

Notifications **MUST** be delivered via:

| Channel | Priority | Latency |
|---------|----------|---------|
| Push notification | High | < 30 seconds |
| In-app alert | High | < 1 minute |
| Email | Low | < 5 minutes |
| SMS (critical only) | Critical | < 1 minute |

### 4.3 Assignment Acceptance

```json
{
  "type": "assignment_offer",
  "mission_id": "uuid",
  "claim_type": "earth.flood.v1",
  "location": { "lat": 4.175, "lon": 73.509 },
  "expires_at": "ISO8601",
  "reward_credits": 20,
  "priority": "urgent",
  "accept_url": "/api/v1/assignments/{id}/accept",
  "decline_url": "/api/v1/assignments/{id}/decline"
}
```

Reporters **MUST** accept or decline within `assignment_expiry` (default: 15 minutes).

Unaccepted assignments **MUST** be reassigned to next eligible reporter.

---

## 5. Standing Evolution

### 5.1 Trust Score

Every user has a **trust_score** (0.0 to 1.0) computed from:

```
trust_score = base_score 
            + (verified_observations × verification_weight)
            - (rejected_observations × rejection_penalty)
            + (validation_accuracy × validation_weight)
            + (tenure_bonus)
```

**Default weights:**

| Component | Weight |
|-----------|--------|
| `base_score` | 0.30 |
| `verification_weight` | +0.02 per verified observation |
| `rejection_penalty` | -0.05 per rejected observation |
| `validation_weight` | +0.01 per correct validation vote |
| `tenure_bonus` | +0.001 per day active (max +0.10) |

### 5.2 Standing Transitions (Normative)

Users **MUST** meet these criteria to advance:

| Transition | Requirements |
|------------|--------------|
| `bronze` → `silver` | trust_score ≥ 0.50 **AND** verified_observations ≥ 10 **AND** total_credits ≥ 200 **AND** tenure ≥ 7 days |
| `silver` → `expert` | trust_score ≥ 0.70 **AND** verified_observations ≥ 50 **AND** total_credits ≥ 1000 **AND** validation_accuracy ≥ 0.85 **AND** domain_certification = true |
| `expert` → `authority` | Manual appointment only (government officials) |

### 5.3 Standing Demotion

Users **MAY** be demoted if:

- trust_score falls below threshold for current standing
- 3+ consecutive rejected observations
- Inactivity > 90 days (demote by one level)
- Manual action by authority (fraud, abuse)

### 5.4 Domain Certification

For `expert` standing, users **MUST** complete domain certification:

1. **Training module** (claim-type specific)
2. **Qualification test** (≥ 80% accuracy on test observations)
3. **Supervised period** (10 observations reviewed by existing expert)

---

## 6. Kaori Credits System

### 6.1 Purpose

Kaori Credits are the **sole incentive mechanism** within the ecosystem. They are:

- **Non-transferable** between users
- **Non-exchangeable** for external value
- **Earned** through verified contributions
- **Spent** on ecosystem privileges

### 6.2 Credit Events

| Event | Credits |
|-------|---------|
| Observation verified as TRUE | +20 |
| Observation verified as FALSE (valid negative) | +15 |
| Observation rejected (spam/fraud) | -10 |
| Validation vote (correct) | +5 |
| Validation vote (incorrect) | -2 |
| Standing promotion | +50 |
| Mission completion bonus (first responder) | +10 |
| Urgent mission completion | +15 (bonus) |
| Critical mission completion | +25 (bonus) |
| Streak bonus (7 consecutive days) | +20 |
| Referral (new user reaches silver) | +25 |

### 6.3 Credit Multipliers

| Standing | Multiplier |
|----------|------------|
| `bronze` | 1.0× |
| `silver` | 1.2× |
| `expert` | 1.5× |
| `authority` | 2.0× |

### 6.4 Ecosystem Benefits (Credit Unlocks)

| Benefit | Credit Cost | Description |
|---------|-------------|-------------|
| Priority Queue | 100 / month | First access to new missions |
| Extended Deadline | 50 / use | +30 minutes on assignment |
| Profile Badge | 200 | Display achievement on profile |
| Data Export | 500 | Export personal contribution history |
| Research Access | 1000 | Access aggregated (anonymized) truth data |
| Beta Features | 250 | Early access to new features |
| Custom Alert Radius | 150 | Expand notification radius |

### 6.5 Leaderboards

The system **SHOULD** maintain:

- **Weekly leaderboard** (credits earned this week)
- **Monthly leaderboard** (credits earned this month)
- **All-time leaderboard** (total credits earned)
- **Domain leaderboards** (per claim type)

Leaderboard position unlocks recognition badges.

---

## 7. Recognition System

### 7.1 Badges

Badges are **permanent** achievements displayed on user profiles.

| Badge | Criteria | Credits Awarded |
|-------|----------|-----------------|
| 🌊 First Responder | First to verify an urgent mission | +10 |
| 🎯 Sharpshooter | 10 consecutive verified observations | +25 |
| 🔬 Specialist | Complete domain certification | +50 |
| 🏆 Top Contributor | Reach #1 on weekly leaderboard | +100 |
| 🌍 Global Guardian | 100 verified observations | +75 |
| 🔍 Truth Seeker | 50 correct validation votes | +30 |
| 📅 Dedicated | 30-day activity streak | +50 |
| 🚀 Early Adopter | Join during beta period | +25 |

### 7.2 Titles

Users earn titles based on cumulative achievements:

| Title | Requirements |
|-------|--------------|
| Observer | Default (all users) |
| Contributor | 10+ verified observations |
| Guardian | 50+ verified observations + Silver standing |
| Sentinel | 100+ verified observations + Expert standing |
| Champion | Top 10 all-time leaderboard |

---

## 8. API Contract (Normative)

A Kaori Flow implementation **MUST** expose:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/missions` | GET | List available missions |
| `/api/v1/missions` | POST | Create new mission |
| `/api/v1/missions/{id}` | GET | Get mission details |
| `/api/v1/missions/{id}/assignments` | GET | List assignments for mission |
| `/api/v1/assignments/{id}/accept` | POST | Accept assignment |
| `/api/v1/assignments/{id}/decline` | POST | Decline assignment |
| `/api/v1/assignments/{id}/submit` | POST | Submit observation for assignment |
| `/api/v1/users/{id}/standing` | GET | Get user standing and trust score |
| `/api/v1/users/{id}/credits` | GET | Get user credit balance and history |
| `/api/v1/users/{id}/badges` | GET | Get user badges |
| `/api/v1/users/{id}/history` | GET | Get observation/validation history |
| `/api/v1/leaderboard` | GET | Get leaderboard rankings |
| `/api/v1/benefits` | GET | List available credit unlocks |
| `/api/v1/benefits/{id}/redeem` | POST | Redeem credits for benefit |

---

## 9. Notification Templates

### 9.1 Mission Assignment

```
🌊 New Mission Available

A flood verification is needed near your location.

📍 Location: Malé, North Malé Atoll
⏰ Deadline: 2 hours
⭐ Reward: 20 Credits (+15 urgent bonus)
🏅 Priority: URGENT

[Accept] [Decline]
```

### 9.2 Observation Verified

```
✅ Observation Verified

Your flood report has been verified as TRUE.

📍 Cell: 8928308280fffff
⭐ Credits earned: +24 (20 base × 1.2 silver multiplier)
📈 Trust score: 0.62 (+0.02)

Total credits: 847
```

### 9.3 Standing Promotion

```
🎉 Congratulations!

You've been promoted to SILVER standing.

New privileges:
• Vote on all claim types
• Priority mission access
• 1.2× credit multiplier
• Unlock new badges

+50 bonus credits awarded!

Keep contributing to reach EXPERT level!
```

### 9.4 Badge Earned

```
🏆 New Badge Unlocked!

You earned: 🎯 Sharpshooter
"10 consecutive verified observations"

+25 bonus credits awarded!

View your badges in your profile.
```

---

## 10. Fraud Prevention

### 10.1 Sybil Resistance

Kaori Flow **MUST** implement:

- Phone number verification (one account per number)
- Device fingerprinting
- Geographic consistency checks (can't report from 2 locations simultaneously)
- Velocity limits (max observations per hour)

### 10.2 Collusion Detection

The system **SHOULD** flag:

- Multiple users submitting identical evidence (same photo hash)
- Unusual voting patterns (always agreeing with same users)
- Rapid-fire submissions from clustered accounts

### 10.3 Evidence Provenance

For high-stakes claims, evidence **SHOULD** include:

- GPS coordinates (embedded in EXIF)
- Timestamp verification (within mission window)
- Device attestation (if available)

### 10.4 Credit Fraud Prevention

To prevent gaming:

- Credits are **non-transferable**
- Negative credit balance triggers review
- Unusual earning patterns flagged for manual review
- Benefit redemptions rate-limited

---

## 11. Integration with Kaori Truth

### 11.1 Observation Submission Flow

```
Reporter accepts Mission
        ↓
Reporter submits Observation (Bronze)
        ↓
Kaori Truth validates Observation
        ↓
    ┌───┴───┐
  VERIFIED  REJECTED
    ↓          ↓
Credits     Credits
awarded     deducted
    ↓          ↓
Standing    Standing
updated     updated
```

### 11.2 Validation Request Flow

```
TruthState enters INVESTIGATING
        ↓
Kaori Flow assigns Validators
        ↓
Validators submit votes
        ↓
Kaori Truth computes consensus
        ↓
Validators credited/debited
```

---

## 12. Configuration Schema

Flow behavior **MUST** be configurable per-deployment:

```yaml
flow_config:
  assignment:
    expiry_minutes: 15
    max_per_mission: 10
    reassignment_enabled: true
    
  standing:
    evolution_enabled: true
    demotion_enabled: true
    certification_required_for_expert: true
    
  credits:
    enabled: true
    base_observation_reward: 20
    multipliers_enabled: true
    negative_balance_allowed: false
    
  benefits:
    enabled: true
    redemption_enabled: true
    
  notifications:
    push_enabled: true
    sms_enabled: false
    email_enabled: true
    
  fraud:
    velocity_limit_per_hour: 10
    duplicate_evidence_check: true
    device_fingerprint_required: false
    
  leaderboards:
    enabled: true
    refresh_interval_minutes: 15
```

---

## 13. Compatibility Requirements

An implementation is **Kaori Flow-compatible** if it satisfies:

- [ ] Mission CRUD with defined states
- [ ] Assignment lifecycle management
- [ ] Standing tracking and evolution
- [ ] Trust score computation
- [ ] Kaori Credits ledger (earn/spend)
- [ ] Notification delivery (at least one channel)
- [ ] Minimal API contract exposed
- [ ] Integration with Kaori Truth for observation validation

---

*End of Kaori Flow Spec (v1.0)*
