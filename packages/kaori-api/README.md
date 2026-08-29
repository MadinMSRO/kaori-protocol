# Kaori API

Pattern B sidecar: a thin FastAPI wrapper around `TruthOrchestrator.compile_observations` and `FlowCore.get_standing`.

This week the HTTP surface is only:

- `POST /v1/compile`
- `GET /v1/standing/{agent_id}`

Both routes require `Authorization: Bearer <Supabase JWT>`. The sidecar maps `sub` (Supabase `auth.users.id`) to agent_id `user:{id}` and never accepts or emits `profiles.id`.

## Run locally against DATABASE_URL

Week-1 `DATABASE_URL` is the Liminal Supabase Postgres URL (Lovable project `3edd781a`). Do not create a Cloud SQL instance. Do not deploy.

1. Point `DATABASE_URL` at that Supabase database (you provide the URL; this repo does not store it).
2. Apply `kaori.signals` (or let the sidecar call `ensure_schema()` on boot). That creates schema `kaori` and table `kaori.signals` only — never `public.signals`:

```bash
psql "$DATABASE_URL" -f packages/kaori-db/src/kaori_db/schema.sql
```

3. Install packages and start the sidecar:

```bash
pip install -e packages/kaori-truth -e packages/kaori-flow -e packages/kaori-db -e packages/kaori-api
export DATABASE_URL="postgresql://…supabase…"
export SUPABASE_JWT_SECRET=your-supabase-jwt-secret
export KAORI_SCHEMA_PATH=packages/kaori-spec/schemas
uvicorn kaori_api.app:app --host 0.0.0.0 --port 8000
```

When `DATABASE_URL` is set, `FlowCore` is constructed with `PostgresSignalStore` (`kaori.signals`). Without it, the sidecar uses `InMemorySignalStore` (tests / local smoke only).

`POST /v1/compile` body is `compile_observations` args only:

```json
{
  "truth_key": "<string>",
  "claim_type_id": "ocean.coral_bleaching.v1",
  "observations": [Observation]
}
```

Observation uses `evidence_refs` (`EvidenceRef[]`). EvidenceRef requires `uri` and `sha256` (`mime_type`, `bytes_size`, `capture_time` optional). This week payload is `{depth_meters, bleaching_percentage}`. The server stamps `reporter_id` from the Bearer agent (`user:{auth.users.id}`) and `reporter_context` from Flow — the client must not mint trust. 200 TruthState uses `truthkey` (not `truth_key`); `TruthState.evidence_refs` is `string[]`. `EvidenceRef.uri` is a string pointer (Supabase `file_url` this week). No upload route and no GCS upload.

## Container image (build only)

Protocol runtime is GCP project `msro-kaori-sandbox` (`asia-southeast1`). `msro-udfi-sandbox` is off this product — do not build, tag, or push for that project.

This PR ships a Dockerfile. It does **not** deploy, enable APIs, or create Artifact Registry / Cloud Run / Cloud SQL.

Future Cloud Run service name: `kaori-api`  
Future image (do not create the registry in this PR):

`asia-southeast1-docker.pkg.dev/msro-kaori-sandbox/kaori/kaori-api`

Build locally:

```bash
docker build -t kaori-api:local .
# later, when Artifact Registry exists in msro-kaori-sandbox:
# docker tag kaori-api:local asia-southeast1-docker.pkg.dev/msro-kaori-sandbox/kaori/kaori-api:latest
```

The image runs `uvicorn kaori_api.app:app` (two routes only). ClaimType YAML is baked from `packages/kaori-spec/schemas` (`KAORI_SCHEMA_PATH`). Supply `DATABASE_URL` and `SUPABASE_JWT_SECRET` at runtime. Cloud Run sets `PORT` (image default 8080).

```bash
docker run --rm -p 8080:8080 \
  -e SUPABASE_JWT_SECRET=your-supabase-jwt-secret \
  -e DATABASE_URL="postgresql://…supabase…" \
  kaori-api:local
```

Do not `gcloud run deploy` from this repo in this PR.
