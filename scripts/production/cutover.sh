#!/usr/bin/env bash
# Operator cutover for Kaori main → Cloud Run. This Cloud Agent cannot run it.
#
# Usage (from a machine with gcloud + docker, project msro-kaori-sandbox):
#   ./scripts/production/cutover.sh preflight
#   I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh backup
#   I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh bucket
#   I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh iam
#   I_ACCEPT_PRODUCTION_CUTOVER=1 DATABASE_URL=... ./scripts/production/cutover.sh migrate
#   I_ACCEPT_PRODUCTION_CUTOVER=1 ./scripts/production/cutover.sh deploy-no-traffic
#   KAORI_SMOKE_URL=... SMOKE_TOKEN_1=... SMOKE_TOKEN_2=... SMOKE_TOKEN_3=... \
#     ./scripts/production/cutover.sh smoke
#   I_ACCEPT_PRODUCTION_CUTOVER=1 SMOKE_PASSED=1 ./scripts/production/cutover.sh promote
#
# Never deploy Liminal from this script. Never merge PR 8.

set -euo pipefail

PROJECT="${PROJECT:-msro-kaori-sandbox}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-kaori-api}"
BUCKET="${BUCKET:-msro-kaori-observations}"
AR_REPO="${AR_REPO:-asia-southeast1-docker.pkg.dev/${PROJECT}/kaori/kaori-api}"
API_SA="${API_SA:-kaori-api@${PROJECT}.iam.gserviceaccount.com}"
SIGNING_SECRET="${SIGNING_SECRET:-kaori-truthstate-signing-key}"
SIGNING_KEY_ID="${KAORI_SIGNING_KEY_ID:-msro-kaori-prod-1}"
MIN_MAIN_SHA="${MIN_MAIN_SHA:-7a313a25300e6335ae64f1a0581d91cb69a27621}"
PUBLIC_URL="${PUBLIC_URL:-https://kaori-api-27gnjsztla-as.a.run.app}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

die() { echo "cutover: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

require_accept() {
  [[ "${I_ACCEPT_PRODUCTION_CUTOVER:-}" == "1" ]] || \
    die "refusing to mutate GCP. Re-run with I_ACCEPT_PRODUCTION_CUTOVER=1"
}

gcloud_ok() {
  need gcloud
  gcloud auth print-identity-token >/dev/null 2>&1 || \
    die "gcloud is not authenticated for this principal"
  local active
  active="$(gcloud config get-value project 2>/dev/null || true)"
  if [[ -n "$active" && "$active" != "$PROJECT" ]]; then
    echo "cutover: gcloud project is ${active}; commands will pass --project=${PROJECT}"
  fi
}

git_ok() {
  local head
  head="$(git rev-parse HEAD)"
  git merge-base --is-ancestor "$MIN_MAIN_SHA" HEAD || \
    die "HEAD ${head} does not contain ${MIN_MAIN_SHA} (Kaori main with the ledger). Do not build PR 8."
  if git rev-parse --verify origin/cursor/artifact-ledger-d7b6 >/dev/null 2>&1; then
    if [[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/cursor/artifact-ledger-d7b6)" ]]; then
      die "HEAD is PR 8 (cursor/artifact-ledger-d7b6). Stop."
    fi
  fi
  echo "cutover: HEAD $(git rev-parse --short HEAD) contains required ${MIN_MAIN_SHA:0:8}"
}

sql_instance() {
  if [[ -n "${CLOUD_SQL_INSTANCE:-}" ]]; then
    echo "$CLOUD_SQL_INSTANCE"
    return
  fi
  local names
  names="$(gcloud sql instances list --project="$PROJECT" --format='value(name)')"
  local count
  count="$(printf '%s\n' "$names" | grep -c . || true)"
  [[ "$count" == "1" ]] || \
    die "set CLOUD_SQL_INSTANCE (found ${count} Cloud SQL instances)"
  printf '%s' "$names"
}

service_env_has() {
  local key="$1"
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT" --region="$REGION" --format=json \
    | python3 - "$key" <<'PY'
import json, sys
key = sys.argv[1]
spec = json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]
env = spec.get("env") or []
names = set()
for item in env:
    names.add(item.get("name"))
sys.exit(0 if key in names else 1)
PY
}

cmd_preflight() {
  need python3
  git_ok
  echo "cutover: checking live public URL ${PUBLIC_URL}"
  local evidence_code compile_code
  evidence_code="$(curl -sS -o /tmp/kaori-evidence.json -w '%{http_code}' \
    -X POST "${PUBLIC_URL}/v1/evidence" || true)"
  compile_code="$(curl -sS -o /tmp/kaori-compile.json -w '%{http_code}' \
    -X POST "${PUBLIC_URL}/v1/compile" || true)"
  echo "cutover: POST /v1/evidence -> ${evidence_code}"
  echo "cutover: POST /v1/compile  -> ${compile_code}"
  if [[ "$evidence_code" == "404" ]]; then
    echo "cutover: live production is still pre-ledger. Do not deploy Liminal. Continue with a no-traffic revision."
  elif [[ "$evidence_code" == "401" ]]; then
    echo "cutover: live /v1/evidence exists (401 unauthenticated). Still smoke a no-traffic revision before promote."
  else
    echo "cutover: unexpected evidence status ${evidence_code}; inspect before mutating traffic"
  fi
  if command -v gcloud >/dev/null 2>&1 && gcloud auth print-identity-token >/dev/null 2>&1; then
    echo "cutover: gcloud authenticated as $(gcloud config get-value account 2>/dev/null)"
    gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" \
      --format='yaml(status.traffic,status.url,spec.template.spec.serviceAccountName)' \
      || die "cannot describe Cloud Run service ${SERVICE}"
    if ! service_env_has KAORI_GENERALIST_URL; then
      echo "cutover: WARNING KAORI_GENERALIST_URL is not on the current service — 200 can arrive without votes"
    fi
    if ! service_env_has DATABASE_URL; then
      echo "cutover: WARNING DATABASE_URL is not on the current service — production boot will fail without it"
    fi
  else
    echo "cutover: gcloud not authenticated in this shell — GCP stages will stop here"
    exit 2
  fi
}

cmd_backup() {
  require_accept
  gcloud_ok
  local instance
  instance="$(sql_instance)"
  echo "cutover: on-demand backup of Cloud SQL ${instance}"
  gcloud sql backups create --project="$PROJECT" --instance="$instance"
  gcloud sql backups list --project="$PROJECT" --instance="$instance" --limit=3
}

cmd_bucket() {
  require_accept
  gcloud_ok
  if gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT" >/dev/null 2>&1; then
    echo "cutover: bucket gs://${BUCKET} already exists"
  else
    gcloud storage buckets create "gs://${BUCKET}" \
      --project="$PROJECT" \
      --location="$REGION" \
      --uniform-bucket-level-access
  fi
  gcloud storage buckets update "gs://${BUCKET}" \
    --project="$PROJECT" \
    --public-access-prevention
  echo "cutover: confirm no allUsers / allAuthenticatedUsers on gs://${BUCKET}"
  gcloud storage buckets get-iam-policy "gs://${BUCKET}" --project="$PROJECT"
}

cmd_iam() {
  require_accept
  gcloud_ok
  local sa_id="kaori-api"
  if ! gcloud iam service-accounts describe "$API_SA" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$sa_id" \
      --project="$PROJECT" \
      --display-name="Kaori API runtime"
  fi
  local instance
  instance="$(sql_instance)"
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${API_SA}" \
    --role="roles/cloudsql.client" \
    --condition="None" >/dev/null
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --project="$PROJECT" \
    --member="serviceAccount:${API_SA}" \
    --role="roles/storage.objectAdmin"
  echo "cutover: grant secretAccessor on ${SIGNING_SECRET} and the generalist signing secret out of band if not already bound"
  echo "cutover: bind roles/run.invoker on kaori-generalist only"
  echo "cutover: Cloud SQL instance=${instance} serviceAccount=${API_SA}"
}

cmd_secrets() {
  require_accept
  gcloud_ok
  [[ "$SIGNING_KEY_ID" != "local_dev_key" ]] || die "KAORI_SIGNING_KEY_ID must not be local_dev_key"
  if gcloud secrets describe "$SIGNING_SECRET" --project="$PROJECT" >/dev/null 2>&1; then
    echo "cutover: secret ${SIGNING_SECRET} exists (value not printed)"
    return
  fi
  [[ -n "${KAORI_SIGNING_KEY_VALUE:-}" ]] || \
    die "create ${SIGNING_SECRET} first, or set KAORI_SIGNING_KEY_VALUE for one-time create"
  printf '%s' "$KAORI_SIGNING_KEY_VALUE" | gcloud secrets create "$SIGNING_SECRET" \
    --project="$PROJECT" \
    --data-file=-
  echo "cutover: created ${SIGNING_SECRET} (value not printed)"
}

cmd_migrate() {
  require_accept
  [[ -n "${DATABASE_URL:-}" ]] || \
    die "set DATABASE_URL to the kaori_migration_owner Cloud SQL URL (not kaori_runtime)"
  if [[ "$DATABASE_URL" == *"kaori_runtime"* ]]; then
    die "DATABASE_URL looks like the runtime role — migrate as kaori_migration_owner"
  fi
  python3 -m kaori_db.migrate --database-url "$DATABASE_URL"
  python3 - <<'PY'
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])
required = ("signals", "observations", "trust_snapshots", "truth_artifacts", "truth_states")
with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'kaori' ORDER BY 1"
    )).fetchall()
tables = {row[0] for row in rows}
missing = [name for name in required if name not in tables]
if missing:
    raise SystemExit(f"missing kaori tables: {missing}")
print("cutover: kaori tables present:", ", ".join(sorted(tables)))
PY
}

cmd_deploy_no_traffic() {
  require_accept
  gcloud_ok
  need docker
  git_ok
  service_env_has DATABASE_URL || die "current ${SERVICE} has no DATABASE_URL — attach Cloud SQL before deploy"
  service_env_has KAORI_GENERALIST_URL || die "current ${SERVICE} has no KAORI_GENERALIST_URL — do not deploy without it"
  local sha image
  sha="$(git rev-parse --short=12 HEAD)"
  image="${AR_REPO}:${sha}"
  echo "cutover: building ${image}"
  docker build -t "$image" "$ROOT"
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  docker push "$image"
  gcloud run deploy "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --image="$image" \
    --no-traffic \
    --service-account="$API_SA" \
    --update-env-vars="KAORI_ENVIRONMENT=production,KAORI_OBSERVATIONS_BUCKET=${BUCKET},KAORI_SIGNING_KEY_ID=${SIGNING_KEY_ID}" \
    --update-secrets="KAORI_SIGNING_KEY=${SIGNING_SECRET}:latest"
  echo "cutover: describe the new revision URL, then smoke it. Do not promote yet."
  gcloud run revisions list --project="$PROJECT" --region="$REGION" --service="$SERVICE" --limit=3
}

cmd_smoke() {
  need python3
  [[ -n "${KAORI_SMOKE_URL:-}" ]] || die "set KAORI_SMOKE_URL to the no-traffic revision URL"
  python3 "${ROOT}/scripts/production/smoke_ledger.py"
}

cmd_promote() {
  require_accept
  gcloud_ok
  [[ "${SMOKE_PASSED:-}" == "1" ]] || \
    die "refusing to promote. Re-run 1/retry/2/3 smoke, then SMOKE_PASSED=1"
  local revision
  revision="${PROMOTE_REVISION:-}"
  if [[ -z "$revision" ]]; then
    revision="$(gcloud run revisions list --project="$PROJECT" --region="$REGION" \
      --service="$SERVICE" --limit=1 --format='value(name)')"
  fi
  [[ -n "$revision" ]] || die "set PROMOTE_REVISION"
  echo "cutover: routing 100% traffic to ${revision}"
  gcloud run services update-traffic "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --to-revisions="${revision}=100"
  echo "cutover: re-smoke the public URL before deploying Liminal"
  echo "  KAORI_SMOKE_URL=${PUBLIC_URL} ./scripts/production/cutover.sh smoke"
  echo "cutover: do not merge or deploy Liminal if the first reporter still gets 200"
}

usage() {
  sed -n '2,18p' "$0"
  echo "commands: preflight | backup | bucket | iam | secrets | migrate | deploy-no-traffic | smoke | promote"
}

cmd="${1:-preflight}"
case "$cmd" in
  preflight) cmd_preflight ;;
  backup) cmd_backup ;;
  bucket) cmd_bucket ;;
  iam) cmd_iam ;;
  secrets) cmd_secrets ;;
  migrate) cmd_migrate ;;
  deploy-no-traffic) cmd_deploy_no_traffic ;;
  smoke) cmd_smoke ;;
  promote) cmd_promote ;;
  -h|--help|help) usage ;;
  *) die "unknown command: ${cmd}" ;;
esac
