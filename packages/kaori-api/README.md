# Kaori API

Pattern B sidecar: a thin FastAPI wrapper around `TruthOrchestrator.compile_observations` and `FlowCore.get_standing`.

This week the HTTP surface is only:

- `POST /v1/compile`
- `GET /v1/standing/{agent_id}`
- `GET /v1/truth/{truthkey}` (`{truthkey:path}` so colons in the key work)

All three routes require `Authorization: Bearer <token>`. The sidecar verifies with `GET {SUPABASE_URL}/auth/v1/user` (`Authorization` + `apikey: SUPABASE_PUBLISHABLE_KEY`). 200 + `user.id` → agent_id `user:{id}`. Non-200 → 401. No JWT secret. Never accepts or emits `profiles.id`.

Compile 200 upserts the full `TruthState.model_dump` (including `evidence_refs`) into `kaori.truth_states`, then calls `FlowCore.emit_truthstate` with the Bearer agent as the sole contributor. Standing moves from that signal history — compile does **not** call `register_agent`. `GET /v1/standing/{agent_id}` already reads Flow; there are no Flow HTTP routes.

CORS allows origins `https://kind-keepsake-kingdom.lovable.app` (live) and `https://id-preview--3edd781a-00a9-4e58-88be-c21405c611ee.lovable.app` (preview), methods `GET`, `POST`, `OPTIONS`, and headers `Authorization` and `Content-Type`. No extra routes.

## Run locally against DATABASE_URL

`DATABASE_URL` is Cloud SQL Postgres. Do not provision a Cloud SQL instance from this repo. Do not deploy.

1. Point `DATABASE_URL` at Cloud SQL (you provide the URL; this repo does not store it).
2. Apply schema (or let the sidecar call `ensure_schema()` on boot). That creates schema `kaori` and tables `kaori.signals` + `kaori.truth_states` — never `public.signals` or `public.truths`:

```bash
psql "$DATABASE_URL" -f packages/kaori-db/src/kaori_db/schema.sql
```

3. Install packages and start the sidecar:

```bash
pip install -e packages/kaori-truth -e packages/kaori-flow -e packages/kaori-db -e packages/kaori-api
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key
# optional — in-memory stores when unset
# export DATABASE_URL="postgresql://…cloud-sql…"
export KAORI_SCHEMA_PATH=packages/kaori-spec/schemas
uvicorn kaori_api.app:app --host 0.0.0.0 --port 8000
```

When `DATABASE_URL` is set, `FlowCore` uses `PostgresSignalStore` (`kaori.signals`) and compile persist uses `PostgresTruthStateStore` (`kaori.truth_states`). Without it, the sidecar uses in-memory stores.

`POST /v1/compile` body is `compile_observations` args only:

```json
{
  "truth_key": "<string>",
  "claim_type_id": "ocean.coral_bleaching.v1",
  "observations": [Observation]
}
```

Observation uses `evidence_refs` (`EvidenceRef[]`). EvidenceRef requires `uri` and `sha256` (`mime_type`, `bytes_size`, `capture_time` optional). This week payload is `{depth_meters, bleaching_percentage}`. The server stamps `reporter_id` from the Bearer agent (`user:{auth.users.id}`) and `reporter_context` from Flow — the client must not mint trust. 200 TruthState uses `truthkey` (not `truth_key`); `TruthState.evidence_refs` is `string[]`. `EvidenceRef.uri` is a string pointer (Supabase `file_url` this week). No upload route and no GCS upload.

`GET /v1/truth/{truthkey}` returns the stored TruthState artifact. Unknown truthkey → 404.

After persist, emit uses `outcome="correct"` only when `status` is `VERIFIED_TRUE`; otherwise `"unknown"`.

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

The image runs `uvicorn kaori_api.app:app` (three routes only). ClaimType YAML is baked from `packages/kaori-spec/schemas` (`KAORI_SCHEMA_PATH`). Supply `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` at runtime. `DATABASE_URL` is optional (Cloud SQL when set). Cloud Run sets `PORT` (image default 8080).

```bash
docker run --rm -p 8080:8080 \
  -e SUPABASE_URL=https://your-project.supabase.co \
  -e SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key \
  kaori-api:local
```

Do not `gcloud run deploy` from this repo in this PR.
