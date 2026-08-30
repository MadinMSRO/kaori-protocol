# Kaori API

Pattern B sidecar: a thin FastAPI wrapper around `TruthOrchestrator.compile_observations` and `FlowCore.get_standing`.

This week the HTTP surface is only:

- `POST /v1/compile`
- `GET /v1/standing/{agent_id}`
- `GET /v1/truth/{truthkey}` (`{truthkey:path}` so colons in the key work)

All three routes require `Authorization: Bearer <token>`. The sidecar verifies with `GET {SUPABASE_URL}/auth/v1/user` (`Authorization` + `apikey: SUPABASE_PUBLISHABLE_KEY`). 200 + `user.id` → agent_id `user:{id}`. Non-200 → 401. No JWT secret. Never accepts or emits `profiles.id`.

Compile 200 upserts the full `TruthState.model_dump` (including `evidence_refs`) into `kaori.truth_states`, then calls `FlowCore.emit_truthstate` with the Bearer agent and Flow agent `claimtype:{claim_type_id}` as contributors. Standing moves from that signal history — compile does **not** call `register_agent` for the Bearer agent. On startup the sidecar registers Flow agent `ai:generalist_v1` (role `validator`) if unknown (idempotent). On compile it idempotently registers `claimtype:{claim_type_id}` (FLOW_SPEC Rule 2 role `claimtype`) if unknown. Claim-type rank uses the same `GET /v1/standing/{agent_id}` with `claimtype:{claim_type_id}` encoded in the path. Same Bearer. Response stays `{ "standing": <number> }`. Player standing stays `user:{id}`. `GET /v1/truth/{truthkey}` still returns the TruthState artifact including `claim`. No fourth path.

Truth order is observe → validate → compile. Observe does not wait on CLIP. When `KAORI_GENERALIST_URL` is set, `POST /v1/compile` records the observation package and starts the private generalist call in the background. The compiler remains pure and never executes a validator or writes a `VALIDATION_VOTE`. The generalist HTTP wait is `ai_validation_routing.generalist.timeout` (ISO-8601) on the ClaimType YAML — a new field, because it was missing (do not reuse dispute PT12H/PT24H/PT48H; never hardcode 30s). The client reads that field. A late generalist 200 still records the `VALIDATION_VOTE`. Never swallow `TimeoutError` and compile as if CLIP ran: compile does not proceed on a swallowed timeout. On every generalist response (including REJECT and a timeout-then-late 200) `kaori-generalist` and `kaori-api` log the ValidationVote JSON (`vote`, `confidence`, `truthkey_id`, `agent_id`, `timestamp`) — not evidence bytes or secrets. `compile_truth_state` / `compile_observations` run only after a vote is recorded for that TruthKey (validate before `compile_observations`). The service loads that ClaimType's existing YAML and runs one open CLIP generalist on CPU against the full observation package: image URIs plus `Observation.geo`, `ui_schema` payload fields, `claim_type_id`, and the compile TruthKey H3 cell. CLIP text/context describes that package, not only a photo prompt. Dummy/unrelated imagery and coordinates outside the TruthKey H3 cell (ClaimType `truthkey.resolution`) can each produce `REJECT` on the same `ai:generalist_v1` `VALIDATION_VOTE`. It compares the mean relevance probability with `evidence_similarity.embedding.similarity_threshold`, signs a FLOW_SPEC `ValidationSignal` as `ai:generalist_v1`, and returns it. Only `kaori-api` calls `record_validation_vote`, so it remains the single SignalStore writer. If the generalist is unset, compile proceeds as before. A `REJECT` vote still compiles 200 with a TruthState once the vote exists. Status stays a protocol TruthStatus — there is no `VALIDATION` status. Warming is ops, not a protocol skip.

Submission checks remain in the existing compile/submit 400 path and are not duplicated in Cloud Run. The generalist input is the full observation package (not images alone). Public `http://` and `https://` evidence (including Supabase public object URLs) is fetched directly; `gs://` evidence continues to use the Cloud Run service account. No new bucket is required. The service does not run submission rules, pHash, a specialist, a chat LLM, Vertex AI, or a GPU. Coral still has `always_require_human: true`; RATIFY and REJECT both leave the persisted TruthState at `PENDING_HUMAN_REVIEW`.

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

Observation uses `evidence_refs` (`EvidenceRef[]`). EvidenceRef requires `uri` and `sha256` (`mime_type`, `bytes_size`, `capture_time` optional). Required observation payload fields come from the loaded ClaimType `ui_schema` (`required: true`). The sidecar loads YAML for whatever `claim_type_id` arrives; missing YAML → 404. Do not invent ClaimType ids. Existing `ocean.coral_bleaching.v1` YAML is unchanged. The server stamps `reporter_id` from the Bearer agent (`user:{auth.users.id}`) and `reporter_context` from Flow — the client must not mint trust. 200 TruthState uses `truthkey` (not `truth_key`); `TruthState.evidence_refs` is `string[]`. `EvidenceRef.uri` is a string pointer (Supabase `file_url` this week). No upload route and no GCS upload.

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

The API image runs `uvicorn kaori_api.app:app` with its existing three authenticated routes. The generalist image runs `uvicorn kaori_api.generalist_app:app`; Cloud Run IAM protects its sole internal POST endpoint and unauthenticated invocation is disabled. ClaimType YAML is baked into both images. Cloud Run sets `PORT` (image default 8080).

```bash
docker run --rm -p 8080:8080 \
  -e SUPABASE_URL=https://your-project.supabase.co \
  -e SUPABASE_PUBLISHABLE_KEY=your-supabase-publishable-key \
  kaori-api:local
```

## Cloud Run deployment

These commands deploy both revisions in `msro-kaori-sandbox` / `asia-southeast1`, preserve the API's existing Cloud SQL configuration, and grant invocation only to the service account already used by `kaori-api`.

```bash
export PROJECT=msro-kaori-sandbox
export REGION=asia-southeast1
export REPOSITORY=kaori
export GENERALIST_SERVICE=kaori-generalist
export GENERALIST_SA="kaori-generalist@${PROJECT}.iam.gserviceaccount.com"
export PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
export API_SA="$(gcloud run services describe kaori-api --region="$REGION" --project="$PROJECT" --format='value(spec.template.spec.serviceAccountName)')"
test -n "$API_SA" || export API_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud iam service-accounts create kaori-generalist \
  --display-name="Kaori V4 CLIP generalist" \
  --project="$PROJECT"

openssl rand -hex 32 | gcloud secrets create kaori-generalist-signing-key \
  --data-file=- \
  --replication-policy=automatic \
  --project="$PROJECT"

gcloud secrets add-iam-policy-binding kaori-generalist-signing-key \
  --member="serviceAccount:${GENERALIST_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="$PROJECT"
gcloud secrets add-iam-policy-binding kaori-generalist-signing-key \
  --member="serviceAccount:${API_SA}" \
  --role=roles/secretmanager.secretAccessor \
  --project="$PROJECT"
export TAG="$(git rev-parse --short HEAD)"
export GENERALIST_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/kaori-generalist:${TAG}"
export API_IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPOSITORY}/kaori-api:${TAG}"

gcloud builds submit . \
  --config=cloudbuild.generalist.yaml \
  --substitutions="_IMAGE=${GENERALIST_IMAGE}" \
  --project="$PROJECT"
gcloud builds submit . \
  --tag="$API_IMAGE" \
  --project="$PROJECT"

gcloud run deploy "$GENERALIST_SERVICE" \
  --image="$GENERALIST_IMAGE" \
  --region="$REGION" \
  --service-account="$GENERALIST_SA" \
  --cpu=2 \
  --memory=4Gi \
  --concurrency=1 \
  --set-secrets=KAORI_VALIDATOR_SIGNING_KEY=kaori-generalist-signing-key:latest \
  --no-allow-unauthenticated \
  --project="$PROJECT"

export GENERALIST_URL="$(gcloud run services describe "$GENERALIST_SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)')"
gcloud run services add-iam-policy-binding "$GENERALIST_SERVICE" \
  --region="$REGION" \
  --member="serviceAccount:${API_SA}" \
  --role=roles/run.invoker \
  --project="$PROJECT"

gcloud run services update kaori-api \
  --image="$API_IMAGE" \
  --region="$REGION" \
  --update-env-vars="KAORI_GENERALIST_URL=${GENERALIST_URL}" \
  --update-secrets=KAORI_VALIDATOR_SIGNING_KEY=kaori-generalist-signing-key:latest \
  --project="$PROJECT"
```

For any existing private GCS bucket referenced by a `gs://` EvidenceRef, separately grant `roles/storage.objectViewer` on that bucket to `$GENERALIST_SA`. Supabase public object URLs need no storage IAM or GCS bucket.

If the service account or secret already exists, skip its create command; add a rotated key with:

```bash
openssl rand -hex 32 | gcloud secrets versions add kaori-generalist-signing-key \
  --data-file=- \
  --project=msro-kaori-sandbox
```
