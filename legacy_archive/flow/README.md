# Kaori FLOW — API & Event Layer

This directory contains the **FLOW layer** — the API interface and event-driven engine for the Kaori Protocol.

## Structure

```
flow/
├── api/
│   ├── main.py          # FastAPI application entry point
│   ├── observations.py  # POST /observations/submit
│   ├── truth.py         # GET /truth/state, /truth/feed
│   ├── votes.py         # POST /votes
│   ├── missions.py      # Signal-driven mission management
│   ├── users.py         # User/standing endpoints
│   ├── schemas.py       # ClaimType schema endpoints
│   ├── auth.py          # JWT + API key authentication
│   ├── auth_routes.py   # Login/token endpoints
│   ├── config.py        # Environment configuration
│   └── models.py        # Request/response Pydantic models
└── engine/
    ├── signal_processor.py   # Converts Signals → Missions
    └── standing_dynamics.py  # Updates Agent standing on finalization
```

## Running the API

```bash
# Start the server
python -m uvicorn flow.api.main:app --reload --port 8001

# View docs
open http://localhost:8001/docs
```

## Key Endpoints

### Truth Layer
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/observations/submit` | Submit observation (multipart) |
| `GET` | `/api/v1/truth/state/{truthkey}` | Get truth state |
| `GET` | `/api/v1/truth/feed` | Get recent truth states |
| `POST` | `/api/v1/votes` | Submit validation vote |

### Flow Layer (Signal-Driven)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/missions/trigger` | Submit trigger signal → creates Mission |
| `POST` | `/api/v1/missions/{id}/approve` | Approve proposed mission (HITL) |
| `GET` | `/api/v1/missions` | List missions (filter by status) |
| `GET` | `/api/v1/missions/{id}` | Get mission details |

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/auth/token` | Get JWT token |
| `GET` | `/api/v1/schemas/{claim_type}` | Get ClaimType schema |

## Signal-Driven Architecture

All mission creation flows through the **Signal Processor**:

```
[IoT Sensor] ──→ Signal(AUTOMATED_TRIGGER) ──→ Mission(PROPOSED)
[Human Admin] ─→ Signal(MANUAL_TRIGGER) ────→ Mission(ACTIVE)
[Scheduler] ───→ Signal(SCHEDULED_TRIGGER) ─→ Mission(PROPOSED)
```

## Authentication

The API supports two auth methods:

1. **JWT Token** (for users)
   ```bash
   curl -X POST /api/v1/auth/token \
     -d '{"user_id": "expert_alice", "password": "kaori"}'
   ```

2. **API Key** (for services)
   ```bash
   curl -H "X-API-Key: dev-api-key-1" /api/v1/truth/feed
   ```

## See Also

- [FLOW_SPEC.md](../FLOW_SPEC.md) — FLOW layer specification
- [core/](../core/) — Core engine implementation
