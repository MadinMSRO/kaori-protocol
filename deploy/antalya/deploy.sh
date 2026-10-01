#!/usr/bin/env bash
# Deploys the Antalya Kaori service to a fresh GCP project, with Supabase for sign-in and the ledger.
# Run in Cloud Shell from the repo root (branch iac/antalya-2026), as a project Owner:
#
#   cp deploy/antalya/antalya.env.example deploy/antalya/antalya.env    # fill it in
#   ./deploy/antalya/deploy.sh                       # everything, in order. Safe to re-run
#   ./deploy/antalya/deploy.sh <step>                # one step: check apis build bucket secrets accounts db generalist api smoke
#   ./deploy/antalya/deploy.sh seed <supabase-user-uuid> "<callsign>"
#   ./deploy/antalya/deploy.sh status
#
# What it makes: an Artifact Registry repo, two images, a private photo bucket, four secrets,
# two service accounts with only the access they need, the ledger schema in Supabase,
# and two Cloud Run services: kaori-generalist-antalya (CLIP, private) and kaori-api-antalya (public;
# Kaori checks the Supabase sign-in itself). See deploy/antalya/README.md.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
ENV_FILE=${ENV_FILE:-$HERE/antalya.env}

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

[ -f "$ENV_FILE" ] || die "missing $ENV_FILE (copy antalya.env.example and fill it in)"
# shellcheck disable=SC1090
source "$ENV_FILE"
for v in PROJECT_ID REGION SUPABASE_URL SUPABASE_PUBLISHABLE_KEY SUPABASE_POOLER_HOST; do
  [ -n "${!v:-}" ] || die "$v is empty in $ENV_FILE"
done
SUPABASE_URL=${SUPABASE_URL%/}
SUPABASE_REF=$(printf '%s' "$SUPABASE_URL" | sed -E 's#^https://([a-z0-9]+)\.supabase\.co$#\1#')
[ "$SUPABASE_REF" != "$SUPABASE_URL" ] || die "SUPABASE_URL should look like https://<project-ref>.supabase.co"

API_SERVICE=kaori-api-antalya
GEN_SERVICE=kaori-generalist-antalya
SEED_JOB=kaori-antalya-seed
API_SA=kaori-api-antalya@$PROJECT_ID.iam.gserviceaccount.com
GEN_SA=kaori-gen-antalya@$PROJECT_ID.iam.gserviceaccount.com
BUCKET=$PROJECT_ID-kaori-antalya
SECRET_SIGNING=antalya-signing-key
SECRET_VALIDATOR=antalya-validator-key
SECRET_EXPORT=antalya-export-token
SECRET_DB=antalya-database-url
SIGNING_KEY_ID=msro-antalya-1
REPO=$REGION-docker.pkg.dev/$PROJECT_ID/kaori
TAG=${TAG:-$(git -C "$ROOT" rev-parse --short=12 HEAD)}
API_IMAGE=$REPO/kaori-api:$TAG
GEN_IMAGE=$REPO/kaori-generalist:$TAG

gc() { gcloud --project "$PROJECT_ID" --quiet "$@"; }

# New service accounts take a few seconds to be visible to IAM.
retry() {
  local n=0
  until "$@"; do
    n=$((n + 1)); [ $n -lt 6 ] || return 1
    echo "  (retrying in $((n * 5))s)"; sleep $((n * 5))
  done
}

secret_has_version() {
  [ -n "$(gc secrets versions list "$1" --filter=state=enabled --limit=1 --format='value(name)' 2>/dev/null)" ]
}

step_check() {
  say "Checking the setup"
  command -v gcloud >/dev/null || die "gcloud not found (run this in Cloud Shell)"
  local who; who=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)
  [ -n "$who" ] || die "not signed in to gcloud"
  gc projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null || die "cannot see project $PROJECT_ID as $who"
  echo "  account  $who"
  echo "  project  $PROJECT_ID ($REGION)"
  echo "  supabase $SUPABASE_REF via $SUPABASE_POOLER_HOST"
  echo "  images   :$TAG ($(git -C "$ROOT" rev-parse --abbrev-ref HEAD))"
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "  note: the checkout has uncommitted changes; they are built in, under the tag above"
  fi
}

step_apis() {
  say "Turning on the GCP services"
  gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com compute.googleapis.com
}

step_build() {
  say "Building both images with Cloud Build (the AI image takes 10-20 minutes the first time)"
  gc artifacts repositories describe kaori --location="$REGION" >/dev/null 2>&1 \
    || gc artifacts repositories create kaori --repository-format=docker --location="$REGION" \
         --description="Kaori images"
  if gc artifacts docker images describe "$API_IMAGE" >/dev/null 2>&1 \
     && gc artifacts docker images describe "$GEN_IMAGE" >/dev/null 2>&1; then
    echo "  both images already built for $TAG"; return
  fi
  # Cloud Build runs as the default compute account in new projects (the legacy Cloud Build account
  # in older ones); it needs to push images and write logs.
  local num; num=$(gc projects describe "$PROJECT_ID" --format='value(projectNumber)')
  for sa in "$num-compute@developer.gserviceaccount.com" "$num@cloudbuild.gserviceaccount.com"; do
    for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
      gc projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$sa" --role="$role" \
        --condition=None >/dev/null 2>&1 || true
    done
  done
  local cfg; cfg=$(mktemp --suffix=.yaml)
  cat >"$cfg" <<'YAML'
steps:
  - name: gcr.io/cloud-builders/docker
    args: [build, --file, Dockerfile, --tag, $_API, .]
  - name: gcr.io/cloud-builders/docker
    args: [build, --file, Dockerfile.generalist, --tag, $_GEN, .]
images: [$_API, $_GEN]
options:
  machineType: E2_HIGHCPU_8
timeout: 3600s
YAML
  gc builds submit "$ROOT" --config="$cfg" --substitutions="_API=$API_IMAGE,_GEN=$GEN_IMAGE"
  rm -f "$cfg"
}

step_bucket() {
  say "Private photo bucket gs://$BUCKET"
  gc storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 \
    || gc storage buckets create "gs://$BUCKET" --location="$REGION" \
         --uniform-bucket-level-access --public-access-prevention
}

step_secrets() {
  say "Secrets (generated here; nobody types them)"
  local name
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT" "$SECRET_DB"; do
    gc secrets describe "$name" >/dev/null 2>&1 || gc secrets create "$name" --replication-policy=automatic
  done
  # The TruthState key and the validator key must differ (the API refuses to start otherwise).
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT"; do
    if secret_has_version "$name"; then echo "  $name: kept"; else
      openssl rand -hex 32 | tr -d '\n' | gc secrets versions add "$name" --data-file=- >/dev/null
      echo "  $name: generated"
    fi
  done
  echo "  $SECRET_DB: filled by the db step"
}

step_accounts() {
  say "Service accounts and their access"
  gc iam service-accounts describe "$API_SA" >/dev/null 2>&1 \
    || gc iam service-accounts create kaori-api-antalya --display-name="Kaori API (Antalya)"
  gc iam service-accounts describe "$GEN_SA" >/dev/null 2>&1 \
    || gc iam service-accounts create kaori-gen-antalya --display-name="Kaori AI reader (Antalya)"
  local name
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT" "$SECRET_DB"; do
    retry gc secrets add-iam-policy-binding "$name" --member="serviceAccount:$API_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done
  retry gc secrets add-iam-policy-binding "$SECRET_VALIDATOR" --member="serviceAccount:$GEN_SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  retry gc storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$API_SA" \
    --role=roles/storage.objectAdmin >/dev/null
  echo "  API: its four secrets, the photo bucket (and calling the AI, granted in the generalist step)"
  echo "  AI:  the validator key only"
}

step_db() {
  say "Ledger schema in Supabase"
  local venv=$HOME/.kaori-antalya-venv
  if [ ! -x "$venv/bin/python" ]; then
    python3 -m venv "$venv"
    "$venv/bin/pip" install -q "sqlalchemy>=2.0.0" "psycopg2-binary>=2.9.0" "pydantic>=2.0.0" "pyyaml>=6.0"
  fi
  local pw
  read -rsp "  Supabase database password (Project Settings -> Database): " pw; echo
  [ -n "$pw" ] || die "no password given"
  local enc; enc=$(PW="$pw" "$venv/bin/python" -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["PW"], safe=""))')
  local admin="postgresql+psycopg2://postgres.$SUPABASE_REF:$enc@$SUPABASE_POOLER_HOST:5432/postgres?sslmode=require"
  local pypath="$ROOT/packages/kaori-db/src:$ROOT/packages/kaori-flow/src:$ROOT/packages/kaori-truth/src"
  if secret_has_version "$SECRET_DB" && [ "${REKEY:-0}" != "1" ]; then
    # Re-keying would lock the running API out until it is redeployed, so only on request.
    ADMIN_DATABASE_URL="$admin" MIGRATE_ONLY=1 PYTHONPATH="$pypath" "$venv/bin/python" "$HERE/db_setup.py"
    echo "  API login kept (REKEY=1 to replace its password, then run the api step)"
  else
    local runtime
    runtime=$(ADMIN_DATABASE_URL="$admin" RUNTIME_LOGIN="kaori_api_antalya.$SUPABASE_REF" PYTHONPATH="$pypath" \
      "$venv/bin/python" "$HERE/db_setup.py")
    [[ "$runtime" == postgresql+psycopg2://* ]] || die "database setup did not return a URL"
    printf '%s' "$runtime" | gc secrets versions add "$SECRET_DB" --data-file=- >/dev/null
    echo "  API login stored in $SECRET_DB"
  fi
}

step_generalist() {
  say "AI reader: $GEN_SERVICE (private; only the API may call it)"
  retry gc run deploy "$GEN_SERVICE" --image="$GEN_IMAGE" --region="$REGION" \
    --service-account="$GEN_SA" --no-allow-unauthenticated \
    --cpu=2 --memory=4Gi --min-instances=1 --max-instances=2 --concurrency=4 --timeout=300 --cpu-boost \
    --set-env-vars=KAORI_GENERALIST_WARM=1 \
    --set-secrets="KAORI_VALIDATOR_SIGNING_KEY=$SECRET_VALIDATOR:latest"
  retry gc run services add-iam-policy-binding "$GEN_SERVICE" --region="$REGION" \
    --member="serviceAccount:$API_SA" --role=roles/run.invoker >/dev/null
}

service_url() { gc run services describe "$1" --region="$REGION" --format='value(status.url)'; }

step_api() {
  say "Kaori API: $API_SERVICE"
  local gen_url; gen_url=$(service_url "$GEN_SERVICE")
  [ -n "$gen_url" ] || die "deploy the generalist first"
  secret_has_version "$SECRET_DB" || die "run the db step first"
  # One instance: compile locks and the AI's background reads live in the process, so it must not
  # be split across instances, and its CPU must stay on after a response (--no-cpu-throttling).
  # Antalya's ~100 people fit easily.
  retry gc run deploy "$API_SERVICE" --image="$API_IMAGE" --region="$REGION" \
    --service-account="$API_SA" --allow-unauthenticated \
    --cpu=1 --memory=1Gi --min-instances=1 --max-instances=1 --concurrency=40 --timeout=120 \
    --no-cpu-throttling --cpu-boost \
    --set-env-vars="KAORI_ANTALYA=1,KAORI_ENVIRONMENT=production,KAORI_SIGNING_KEY_ID=$SIGNING_KEY_ID,KAORI_OBSERVATIONS_BUCKET=$BUCKET,KAORI_GENERALIST_URL=$gen_url,SUPABASE_URL=$SUPABASE_URL,SUPABASE_PUBLISHABLE_KEY=$SUPABASE_PUBLISHABLE_KEY" \
    --set-secrets="KAORI_SIGNING_KEY=$SECRET_SIGNING:latest,KAORI_VALIDATOR_SIGNING_KEY=$SECRET_VALIDATOR:latest,KAORI_EXPORT_TOKEN=$SECRET_EXPORT:latest,DATABASE_URL=$SECRET_DB:latest"
  local url; url=$(service_url "$API_SERVICE")
  # Some organisations forbid public (allUsers) access; Cloud Run can skip its own check instead.
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$url/v1/invites/AAAA-AAAA")" = "403" ]; then
    echo "  public access was blocked by policy; turning off Cloud Run's invoker check instead"
    gc run services update "$API_SERVICE" --region="$REGION" --no-invoker-iam-check
  fi
}

expect() {  # expect <label> <expected> <actual>
  if [ "$2" = "$3" ]; then echo "  ok    $1"; else echo "  FAIL  $1 (expected $2, got $3)"; SMOKE_FAILED=1; fi
}

step_smoke() {
  say "Smoke test"
  SMOKE_FAILED=0
  local api gen code body token
  api=$(service_url "$API_SERVICE"); gen=$(service_url "$GEN_SERVICE")
  body=$(curl -s "$api/v1/invites/AAAA-AAAA")
  expect "API is up and answers invites" '{"valid":false,"reason":"unknown"}' "$(printf '%s' "$body" | tr -d ' ')"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$api/v1/compile" -H 'Content-Type: application/json' -d '{}')
  expect "compile refuses a caller with no sign-in" 401 "$code"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api/v1/assignments" -H 'Authorization: Bearer not-a-token')
  expect "Supabase rejects a fake token" 401 "$code"
  token=$(gc secrets versions access latest --secret="$SECRET_EXPORT")
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api/v1/export" -H "Authorization: Bearer $token")
  expect "export works with its token (ledger reachable)" 200 "$code"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api/v1/export" -H "Authorization: Bearer wrong")
  expect "export refuses a wrong token" 403 "$code"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$gen/read" -H 'Content-Type: application/json' -d '{}')
  case "$code" in 401|403) code=refused ;; esac
  expect "the AI refuses callers without access" refused "$code"
  body=$(printf '{"claim_type_id":"earth.sky_cover.v1","image_b64":"%s"}' "$(base64 -w0 "$HERE/smoke-sky.jpg")")
  body=$(curl -s -X POST "$gen/read" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H 'Content-Type: application/json' -d "$body")
  case "$body" in *'"relevance"'*) expect "the AI reads a photo" yes yes ;; *) expect "the AI reads a photo" '{...relevance...}' "$body" ;; esac
  [ "$SMOKE_FAILED" = 0 ] && echo "  all checks passed" || die "smoke test failed (see above)"
}

step_seed() {
  local uuid=${1:-} callsign=${2:-}
  [[ "$uuid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] \
    || die "usage: deploy.sh seed <supabase-user-uuid> \"<callsign>\" (the UID from Supabase -> Authentication -> Users)"
  [ -n "$callsign" ] && [[ "$callsign" != *"|"* ]] || die "give a callsign (no '|')"
  say "Seeding user:$uuid as $callsign"
  gc run jobs deploy "$SEED_JOB" --image="$API_IMAGE" --region="$REGION" --service-account="$API_SA" \
    --set-secrets="DATABASE_URL=$SECRET_DB:latest" --max-retries=0 --task-timeout=120 \
    --command=python --args="^|^-m|kaori_api.antalya|seed|user:$uuid|$callsign" \
    --execute-now --wait
}

step_status() {
  local api; api=$(service_url "$API_SERVICE" 2>/dev/null || true)
  say "Antalya"
  echo "  API       ${api:-not deployed}"
  echo "  AI        $(service_url "$GEN_SERVICE" 2>/dev/null || echo 'not deployed')"
  echo "  photos    gs://$BUCKET"
  echo "  export    curl -H \"Authorization: Bearer \$(gcloud secrets versions access latest --secret=$SECRET_EXPORT --project=$PROJECT_ID)\" $api/v1/export"
  echo
  echo "  For the app (liminal-mobile mobile/.env, branch probe-antalya):"
  echo "    EXPO_PUBLIC_SUPABASE_URL=$SUPABASE_URL"
  echo "    EXPO_PUBLIC_SUPABASE_KEY=$SUPABASE_PUBLISHABLE_KEY"
  echo "    EXPO_PUBLIC_KAORI_URL=${api:-<API url>}"
  echo "    EXPO_PUBLIC_ANTALYA=1"
}

cd "$ROOT"
case "${1:-all}" in
  all)
    step_check; step_apis; step_build; step_bucket; step_secrets; step_accounts; step_db
    step_generalist; step_api; step_smoke; step_status ;;
  check|apis|build|bucket|secrets|accounts|db|generalist|api|smoke|status) "step_$1" ;;
  seed) shift; step_seed "$@" ;;
  *) die "unknown step '$1' (all check apis build bucket secrets accounts db generalist api smoke seed status)" ;;
esac
