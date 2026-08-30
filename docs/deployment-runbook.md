# Kaori production deployment runbook

This document is the ordered rollout plan. Runtime image must be built from
**Kaori `main` at `7a313a25300e6335ae64f1a0581d91cb69a27621` or a later
descendant**. Do not build or promote PR 8
(`cursor/artifact-ledger-d7b6`).

A Cloud Agent without `gcloud` Application Default Credentials cannot
execute these steps. On a machine that is authenticated to
`msro-kaori-sandbox`, use the operator scripts (they still refuse to
promote until smoke passes):

```bash
./scripts/production/cutover.sh preflight
I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh backup
I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh bucket
I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh iam
I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh secrets
I_ACCEPT_PRODUCTION_CUTOVER=1 DATABASE_URL='postgresql://kaori_migration_owner@...' \
  ./scripts/production/cutover.sh migrate
I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh deploy-no-traffic
KAORI_SMOKE_URL='https://<revision-url>' \
  SMOKE_TOKEN_1=... SMOKE_TOKEN_2=... SMOKE_TOKEN_3=... \
  ./scripts/production/cutover.sh smoke
I_ACCEPT_PRODUCTION_CUTOVER=1 SMOKE_PASSED=1 PROMOTE_REVISION='<revision>' \
  ./scripts/production/cutover.sh promote
```

`scripts/production/smoke_ledger.py` is the 1 / retry / 2 / 3-reporter
contract. It fails if the first reporter receives `200`, if evidence is not
`gs://msro-kaori-observations/...`, if `security.key_id` is `local_dev_key`,
or if the `200` artifact has no `consensus.votes`.

## Preconditions

- Cloud SQL instance already exists in `msro-kaori-sandbox` / `asia-southeast1`.
- Artifact Registry repository `asia-southeast1-docker.pkg.dev/msro-kaori-sandbox/kaori` exists.
- Liminal (`kind-keepsake-kingdom`) is **not** deployed until step 8.

## 1. Cloud SQL backup and migration

1. Take an on-demand Cloud SQL backup and record the backup id.
2. Connect as the **migration owner** login (a user granted
   `kaori_migration_owner`, or the current Cloud SQL admin used only for DDL).
3. Apply schema and grants. Do not use the API process for this:

   ```bash
   export DATABASE_URL="postgresql://kaori_migration_owner@/cloudsql/msro-kaori-sandbox:asia-southeast1:<INSTANCE>/<DB>"
   python -m kaori_db.migrate
   ```

4. Confirm `kaori.signals`, `kaori.observations`, `kaori.trust_snapshots`,
   `kaori.truth_artifacts`, and `kaori.truth_states` exist.
5. Confirm `kaori_runtime` has `SELECT, INSERT` on immutable tables and
   `SELECT, INSERT, UPDATE` on `kaori.truth_states` only.
6. The API Cloud Run service account / DB user must be granted `kaori_runtime`
   and must **not** be granted `CREATE` on schema `kaori`.

Rollback: restore the Cloud SQL backup taken in this step. Do not roll
forward a partial schema with the API runtime user.

## 2. Dedicated private observations bucket

Create (out of band) a **new** private bucket named exactly:

`msro-kaori-observations`

Requirements:

- Location: `asia-southeast1`
- Uniform bucket-level access
- Public access prevention enforced
- No allUsers / allAuthenticatedUsers bindings
- Object versioning optional; default object ACL private
- Path convention written by the API only:
  `observations/{sha256(reporter_id)[:16]}/{sha256}/{filename}`

Do not reuse a public product-evidence bucket. Do not put browser-readable
objects in this bucket.

## 3. Dedicated `kaori-api` service account and least-privilege IAM

Use a dedicated service account, for example:

`kaori-api@msro-kaori-sandbox.iam.gserviceaccount.com`

Grant only:

- `roles/cloudsql.client` on the Cloud SQL instance
- `roles/secretmanager.secretAccessor` on the TruthState signing secret
  **and** (separately) the generalist validator secret
- `roles/storage.objectAdmin` **restricted to**
  `msro-kaori-observations` (create + read objects; no bucket IAM admin)
- `roles/run.invoker` on `kaori-generalist` only

Do not grant `roles/storage.admin`, `roles/cloudsql.admin`, or project
Editor. Do not put GCS HMAC or JSON keys in Liminal or the browser.

The Cloud SQL database user mapped to this service should be a member of
`kaori_runtime` only.

## 4. Production TruthState signing configuration

Create a **new** Secret Manager secret, for example
`kaori-truthstate-signing-key`, with a high-entropy HMAC secret.

Cloud Run env / secrets for the API revision:

| Variable | Source | Notes |
|---|---|---|
| `KAORI_SIGNING_KEY` | `kaori-truthstate-signing-key:latest` | TruthState HMAC. Never the repo `kaori-dev-signing-key-do-not-use-in-production`. |
| `KAORI_SIGNING_KEY_ID` | env string, e.g. `msro-kaori-prod-1` | Must not be `local_dev_key`. |
| `KAORI_VALIDATOR_SIGNING_KEY` | existing `kaori-generalist-signing-key` | Generalist request HMAC only. **Must differ** from `KAORI_SIGNING_KEY`. |
| `KAORI_OBSERVATIONS_BUCKET` | `msro-kaori-observations` | Required whenever `DATABASE_URL` is set. |
| `DATABASE_URL` | Cloud SQL unix socket URL as `kaori_runtime` | Presence of this URL forbids the development signing key. |
| `KAORI_ENVIRONMENT` | `production` | Optional extra fail-fast. |

The API process refuses to boot if Cloud SQL is configured and the
development signing key or key id is used, or if the TruthState key equals
the validator key.

## 5. Cloud Run revision with no traffic

1. Build and push `kaori-api` from `main` at `7a313a25` or later (not PR 8).
2. Deploy a **new revision** of `kaori-api` with `--no-traffic` (or
   `--to-revisions <current>=100,<new>=0`).
3. Attach Cloud SQL, the runtime DB user, the production signing secret,
   `KAORI_OBSERVATIONS_BUCKET`, and the existing generalist URL.
4. Do not update the production traffic split yet.
5. Confirm the new revision becomes Ready and that startup logs do **not**
   contain schema-application statements.

## 6. Authenticated one-, two-, and three-reporter smoke tests

Call the **no-traffic revision URL** with three distinct Supabase users
against one TruthKey whose ClaimType `implicit_consensus.min_observations`
is 3 (for example `ocean.vessel_anomaly.v1`).

For each reporter:

1. `POST /v1/evidence` with real bytes. Expect `{uri, sha256}` where `uri`
   is `gs://msro-kaori-observations/observations/...`.
2. `POST /v1/compile` with that private EvidenceRef. Do not send product
   HTTPS file URLs.

Expected contract:

| Reporter | Distinct count | HTTP | Body |
|---|---|---|---|
| 1 | 1 | `202` | `PENDING`, `observation_progress.received=1`, `required=3` |
| 1 retry | 1 | `202` | `received` still `1` |
| 2 | 2 | `202` | `received=2` |
| 3 | 3 | `200` | signed TruthState compiled from the **full ledger**, not the last payload |

Reject smoke if:

- a single reporter receives `200`
- `202` is treated as compiled
- compile uses only the last request body
- evidence upload accepts a hash/path mismatch
- the revision applied DDL
- `security.key_id` is `local_dev_key`

## 7. Traffic promotion and rollback

Promotion:

1. Move 100% traffic to the new revision.
2. Re-run the 1/2/3-reporter smoke against the public URL.
3. Watch 4xx/5xx and Cloud SQL connections.

Rollback (do not wait for a second deploy):

1. Route 100% traffic back to the previous revision.
2. If migration 1 was applied and is incompatible with the previous
   revision, restore the Cloud SQL backup from step 1. Bronze/Silver rows
   appended after the backup are lost — that is the documented tradeoff
   versus attempting in-place DDL downgrade.
3. Leave the unused revision in place until the incident is closed.

## 8. Liminal only after the Kaori 202/200 contract passes

Deploy `kind-keepsake-kingdom` only after step 6 passes on the promoted
revision.

Liminal must:

- upload bytes through `POST /v1/evidence` (no GCP credentials in the browser)
- call `POST /v1/compile` on every authenticated reporter submit
- treat `202` as recorded progress, never as mission `completed`
- treat `200` as compiled only when the stored artifact has a recorded vote
- keep `mission_evidence` / missions as UI indexes, not the protocol ledger

If Kaori still returns `200` for the first reporter, **do not** ship
Liminal. That is the PR 8 contract and is unsafe.
