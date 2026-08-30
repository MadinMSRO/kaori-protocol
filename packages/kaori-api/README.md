# Kaori API

Pattern B sidecar: authenticated evidence intake plus the Kaori orchestrator.

Protocol HTTP surface:

- `POST /v1/evidence`
- `POST /v1/compile`
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

The orchestrator freezes and persists the full TrustSnapshot, calls the pure
compiler, appends the signed TruthState to `kaori.truth_artifacts`, and refreshes
the Gold `kaori.truth_states` projection in the same transaction. `GET
/v1/truth/{truthkey}` returns that latest full artifact, including
`compile_inputs.observations`, content-bound evidence refs, and consensus votes.

CORS is restricted to the configured Liminal live and preview origins.

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
