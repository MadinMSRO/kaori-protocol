# Kaori API

Pattern B sidecar: authenticated evidence intake plus the Kaori orchestrator.

Protocol HTTP surface:

- `POST /v1/evidence`
- `POST /v1/compile`
- `POST /v1/validate`
- `GET /v1/standing/{agent_id}`
- `GET /v1/truth/{truthkey}` (`{truthkey:path}` so colons work)

All routes require `Authorization: Bearer <token>`. Supabase Auth maps the
verified user to `user:{id}`; `profiles.id` is never accepted as identity.

`POST /v1/evidence` computes SHA-256 from the uploaded bytes and writes once to
the private `KAORI_OBSERVATIONS_BUCKET`. It returns a content-bound
`{uri, sha256}` reference with a stable `gs://` URI.

`POST /v1/compile` admits incoming observations to immutable Bronze storage,
counts distinct authenticated reporters, and returns `202 PENDING` until the
ClaimType's `implicit_consensus.min_observations` is met. This is separate from
`evidence.min_count`, which applies inside one Observation, and validator vote
quorum, which applies later.

After the threshold, validation runs before `compile_observations`. With
`KAORI_GENERALIST_URL`, 200 is returned only after a `VALIDATION_VOTE` is
recorded. A timeout does not compile; a late vote is recorded without
retroactively completing the timed-out request. There is no `/v1/vote` route.
Authenticated `POST /v1/validate` records a human (or other agent) vote and
recompiles. Production without a generalist client does not compile.

The orchestrator freezes and persists the full TrustSnapshot, calls the pure
compiler, appends the signed TruthState to `kaori.truth_artifacts`, and refreshes
the Gold `kaori.truth_states` projection in the same transaction. `GET
/v1/truth/{truthkey}` returns that latest full artifact, including
`compile_inputs.observations`, content-bound evidence refs, and consensus votes.

CORS always allows the Liminal live and preview origins. Add more hosts with
`KAORI_CORS_ORIGINS` (comma-separated). `*` is ignored.

## Run locally against DATABASE_URL

`DATABASE_URL` is Cloud SQL Postgres. Do not provision a Cloud SQL instance from this repo. Do not deploy.

1. Point `DATABASE_URL` at Cloud SQL as the **runtime** role (you provide the URL; this repo does not store it).
2. Apply schema and grants as the **migration owner** before starting the API.
   The sidecar does not call `ensure_schema()` on boot and must not be given
   schema-owner privileges.

```bash
# migration owner — DDL only, not the API process
python -m kaori_db.migrate
# equivalent:
# psql "$MIGRATION_DATABASE_URL" -f packages/kaori-db/src/kaori_db/schema.sql
# psql "$MIGRATION_DATABASE_URL" -f packages/kaori-db/src/kaori_db/roles.sql
```

This creates immutable `kaori.signals`, `kaori.observations`,
`kaori.trust_snapshots`, and `kaori.truth_artifacts`, plus the mutable Gold
projection `kaori.truth_states`—never `public.signals` or `public.truths`.

3. Install packages and start the sidecar:

```bash
pip install -e packages/kaori-truth -e packages/kaori-flow -e packages/kaori-db -e packages/kaori-api
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key
# optional — in-memory stores when unset
# export DATABASE_URL="postgresql://…cloud-sql…"
# required whenever DATABASE_URL is set
# export KAORI_OBSERVATIONS_BUCKET="msro-kaori-observations"
# export KAORI_SIGNING_KEY="dedicated-truthstate-hmac"
# export KAORI_SIGNING_KEY_ID="msro-kaori-prod-1"
# KAORI_VALIDATOR_SIGNING_KEY must be a different secret
export KAORI_SCHEMA_PATH=packages/kaori-spec/schemas
uvicorn kaori_api.app:app --host 0.0.0.0 --port 8000
```

When `DATABASE_URL` is set, the sidecar uses PostgreSQL Bronze/Silver/Gold
stores. Without it, the same contracts use in-memory stores for tests.

`POST /v1/compile` body is `compile_observations` args only:

```json
{
  "truth_key": "<string>",
  "claim_type_id": "ocean.coral_bleaching.v1",
  "observations": [Observation]
}
```

Observation uses `evidence_refs` (`EvidenceRef[]`). Upload each object through
`POST /v1/evidence` first and store the returned private `gs://` reference.
Required payload fields and evidence counts come from the loaded ClaimType. The
server stamps reporter identity/context; clients cannot mint trust. A successful
compile returns a signed TruthState, while an unmet distinct-reporter threshold
returns 202 with `observation_progress`.

`GET /v1/truth/{truthkey}` returns the stored TruthState artifact. Unknown truthkey → 404.

After persist, emit uses `outcome="correct"` only when `status` is `VERIFIED_TRUE`; otherwise `"unknown"`.

## Container images

Protocol runtime is GCP project `msro-kaori-sandbox` (`asia-southeast1`). `msro-udfi-sandbox` is off this product — do not build, tag, or push for that project.

`Dockerfile` builds `kaori-api`; `Dockerfile.generalist` builds the private CPU CLIP generalist and bakes the open `ViT-B-32`/`openai` weights into the image. The existing Artifact Registry repository is `asia-southeast1-docker.pkg.dev/msro-kaori-sandbox/kaori`.

Build locally:

```bash
docker build -t kaori-api:local .
docker build -f Dockerfile.generalist -t kaori-generalist:local .
```

The API image runs `uvicorn kaori_api.app:app` with its authenticated protocol
routes. The generalist image remains private behind Cloud Run IAM. ClaimType
YAML is baked into both images. Cloud Run sets `PORT` (image default 8080).

```bash
docker run --rm -p 8080:8080 \
  -e SUPABASE_URL=https://your-project.supabase.co \
  -e SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key \
  kaori-api:local
```

## Cloud Run / GCP

Do not execute Cloud Run, Cloud SQL, GCS, IAM, or Secret Manager commands from
a Cloud Agent that lacks GCP credentials. The ordered production plan is
[`docs/deployment-runbook.md`](../../docs/deployment-runbook.md). Operator
entrypoints: `scripts/production/cutover.sh` and
`scripts/production/smoke_ledger.py`.

When `KAORI_ENVIRONMENT=production`, the API refuses to boot without
`DATABASE_URL`. Cloud SQL runtime never applies DDL. `KAORI_OBSERVATIONS_BUCKET`
is required whenever `DATABASE_URL` is set. TruthState signing must use a
dedicated production secret, not `kaori-dev-signing-key-do-not-use-in-production`
and not `KAORI_VALIDATOR_SIGNING_KEY`.