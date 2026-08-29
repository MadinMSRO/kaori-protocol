# Kaori API

Pattern B sidecar: a thin FastAPI wrapper around `TruthOrchestrator.compile_observations` and `FlowCore.get_standing`.

This week the HTTP surface is only:

- `POST /v1/compile`
- `GET /v1/standing/{agent_id}`

Both routes require `Authorization: Bearer <Supabase JWT>`. The sidecar maps `sub` (Supabase `auth.users.id`) to agent_id `user:{id}` and never accepts or emits `profiles.id`.

## Run locally against DATABASE_URL

1. Create a PostgreSQL database yourself (this repo does not provision one).
2. Apply the signals table (or let the sidecar call `ensure_schema()` on boot):

```bash
psql "$DATABASE_URL" -f packages/kaori-db/src/kaori_db/schema.sql
```

3. Install packages and start the sidecar:

```bash
pip install -e packages/kaori-truth -e packages/kaori-flow -e packages/kaori-db -e packages/kaori-api
export DATABASE_URL=postgresql://user:pass@localhost:5432/kaori
export SUPABASE_JWT_SECRET=your-supabase-jwt-secret
export KAORI_SCHEMA_PATH=packages/kaori-spec/schemas
uvicorn kaori_api.app:app --host 0.0.0.0 --port 8000
```

When `DATABASE_URL` is set, `FlowCore` is constructed with `PostgresSignalStore`. Without it, the sidecar uses `InMemorySignalStore` (tests / local smoke only).

`POST /v1/compile` body is `compile_observations` args only:

```json
{
  "truth_key": "<string>",
  "claim_type_id": "ocean.coral_bleaching.v1",
  "observations": [Observation]
}
```

Observation uses `evidence_refs` (`EvidenceRef[]`). EvidenceRef requires `uri` and `sha256` (`mime_type`, `bytes_size`, `capture_time` optional). This week payload is `{depth_meters, bleaching_percentage}`. The server stamps `reporter_id` from the Bearer agent (`user:{auth.users.id}`) and `reporter_context` from Flow — the client must not mint trust. 200 TruthState uses `truthkey` (not `truth_key`); `TruthState.evidence_refs` is `string[]`. No upload route.
