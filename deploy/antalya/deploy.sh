#!/usr/bin/env bash
# Deploys the Antalya Kaori service, all in one GCP project: Firebase Auth for sign-in, Cloud SQL for
# the ledger, Cloud Run for the API and the AI, Cloud Storage for photos, Secret Manager for keys.
# Run in Cloud Shell from the repo root (branch iac/antalya-2026), as a project Owner:
#
#   ./deploy/antalya/deploy.sh                       # everything, in order. Safe to re-run
#   ./deploy/antalya/deploy.sh <step>                # one step (see STEPS below)
#   ./deploy/antalya/deploy.sh seed <email or uid> "<callsign>"
#   ./deploy/antalya/deploy.sh status
#
# Settings default to msro-kaori-sandbox / asia-southeast1; override in deploy/antalya/antalya.env.
# Existing services in the project (kaori-api, kaori-generalist, ...) are not touched: everything
# here is named *-antalya. See deploy/antalya/README.md.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
ENV_FILE=${ENV_FILE:-$HERE/antalya.env}
STEPS="check apis build bucket secrets accounts sql db firebase generalist api smoke status"

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '\n== %s\n' "$*"; }

# shellcheck disable=SC1090
[ -f "$ENV_FILE" ] && source "$ENV_FILE"
PROJECT_ID=${PROJECT_ID:-msro-kaori-sandbox}
REGION=${REGION:-asia-southeast1}
SQL_TIER=${SQL_TIER:-db-g1-small}

API_SERVICE=kaori-api-antalya
GEN_SERVICE=kaori-generalist-antalya
DB_JOB=kaori-antalya-db
SEED_JOB=kaori-antalya-seed
API_SA=kaori-api-antalya@$PROJECT_ID.iam.gserviceaccount.com
GEN_SA=kaori-gen-antalya@$PROJECT_ID.iam.gserviceaccount.com
DBA_SA=kaori-dba-antalya@$PROJECT_ID.iam.gserviceaccount.com
BUCKET=$PROJECT_ID-kaori-antalya
SQL_INSTANCE=kaori-antalya
SQL_CONN=$PROJECT_ID:$REGION:$SQL_INSTANCE
SECRET_SIGNING=antalya-signing-key
SECRET_VALIDATOR=antalya-validator-key
SECRET_EXPORT=antalya-export-token
SECRET_DB=antalya-database-url          # the API's login (kaori_runtime only)
SECRET_DB_ADMIN=antalya-db-admin-url    # schema owner; only the db job reads it
SIGNING_KEY_ID=msro-antalya-1
FIREBASE_APP_NAME="Liminal Antalya"
FIREBASE_CONFIG=$HERE/firebase-config.json
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

# Google REST APIs (Firebase, Identity Toolkit) as the signed-in Owner.
# api <METHOD> <URL> [JSON body] -> sets API_STATUS and API_BODY (no subshell, so both survive).
API_STATUS=0
API_BODY=
api() {
  local out; out=$(mktemp)
  local args=(-sS -o "$out" -w '%{http_code}' -X "$1" "$2"
    -H "Authorization: Bearer $(gcloud auth print-access-token)"
    -H "x-goog-user-project: $PROJECT_ID" -H 'Content-Type: application/json')
  [ -n "${3:-}" ] && args+=(--data "$3")
  API_STATUS=$(curl "${args[@]}") || API_STATUS=000
  API_BODY=$(cat "$out"); rm -f "$out"
}
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

# Wait for a Firebase long-running operation.
wait_op() {
  local name=$1 body
  for _ in $(seq 1 60); do
    api GET "https://firebase.googleapis.com/v1beta1/$name"; body=$API_BODY
    if [ "$(printf '%s' "$body" | json 'd.get("done", False)')" = "True" ]; then
      printf '%s' "$body" | json '"error" in d' | grep -q True && die "Firebase operation failed: $body"
      return 0
    fi
    sleep 5
  done
  die "Firebase operation $name did not finish"
}

step_check() {
  say "Checking the setup"
  command -v gcloud >/dev/null || die "gcloud not found (run this in Cloud Shell)"
  local who; who=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)
  [ -n "$who" ] || die "not signed in to gcloud"
  gc projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null || die "cannot see project $PROJECT_ID as $who"
  echo "  account  $who"
  echo "  project  $PROJECT_ID ($REGION)"
  echo "  images   :$TAG ($(git -C "$ROOT" rev-parse --abbrev-ref HEAD))"
  if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "  note: the checkout has uncommitted changes; they are built in, under the tag above"
  fi
}

step_apis() {
  say "Turning on the GCP services"
  gc services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com compute.googleapis.com \
    sqladmin.googleapis.com firebase.googleapis.com identitytoolkit.googleapis.com apikeys.googleapis.com
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
  say "Secrets (generated here; nobody types or sees them)"
  local name
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT" "$SECRET_DB" "$SECRET_DB_ADMIN"; do
    gc secrets describe "$name" >/dev/null 2>&1 || gc secrets create "$name" --replication-policy=automatic
  done
  # The TruthState key and the validator key must differ (the API refuses to start otherwise).
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT"; do
    if secret_has_version "$name"; then echo "  $name: kept"; else
      openssl rand -hex 32 | tr -d '\n' | gc secrets versions add "$name" --data-file=- >/dev/null
      echo "  $name: generated"
    fi
  done
  # Database logins: hex passwords, so the URLs need no escaping. Cloud Run reaches Cloud SQL through
  # the socket it mounts at /cloudsql/<connection name>.
  if secret_has_version "$SECRET_DB_ADMIN"; then echo "  $SECRET_DB_ADMIN: kept"; else
    printf 'postgresql+psycopg2://kaori_admin:%s@/kaori?host=/cloudsql/%s' "$(openssl rand -hex 24)" "$SQL_CONN" \
      | gc secrets versions add "$SECRET_DB_ADMIN" --data-file=- >/dev/null
    echo "  $SECRET_DB_ADMIN: generated"
  fi
  if secret_has_version "$SECRET_DB"; then echo "  $SECRET_DB: kept"; else
    printf 'postgresql+psycopg2://kaori_api_antalya:%s@/kaori?host=/cloudsql/%s' "$(openssl rand -hex 24)" "$SQL_CONN" \
      | gc secrets versions add "$SECRET_DB" --data-file=- >/dev/null
    echo "  $SECRET_DB: generated"
  fi
}

step_accounts() {
  say "Service accounts and their access"
  local sa name
  for sa in "kaori-api-antalya:Kaori API (Antalya)" "kaori-gen-antalya:Kaori AI reader (Antalya)" \
            "kaori-dba-antalya:Kaori database setup (Antalya)"; do
    gc iam service-accounts describe "${sa%%:*}@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 \
      || gc iam service-accounts create "${sa%%:*}" --display-name="${sa#*:}"
  done
  for name in "$SECRET_SIGNING" "$SECRET_VALIDATOR" "$SECRET_EXPORT" "$SECRET_DB"; do
    retry gc secrets add-iam-policy-binding "$name" --member="serviceAccount:$API_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done
  retry gc secrets add-iam-policy-binding "$SECRET_VALIDATOR" --member="serviceAccount:$GEN_SA" \
    --role=roles/secretmanager.secretAccessor >/dev/null
  for name in "$SECRET_DB" "$SECRET_DB_ADMIN"; do
    retry gc secrets add-iam-policy-binding "$name" --member="serviceAccount:$DBA_SA" \
      --role=roles/secretmanager.secretAccessor >/dev/null
  done
  for sa in "$API_SA" "$DBA_SA"; do
    retry gc projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$sa" \
      --role=roles/cloudsql.client --condition=None >/dev/null
  done
  retry gc storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$API_SA" \
    --role=roles/storage.objectAdmin >/dev/null
  echo "  API:         its four secrets, Cloud SQL, the photo bucket (and the AI, granted in the generalist step)"
  echo "  AI:          the validator key only"
  echo "  db setup:    the two database secrets and Cloud SQL"
}

step_sql() {
  say "Cloud SQL: $SQL_INSTANCE (Postgres 16, $SQL_TIER, daily backups, point-in-time recovery)"
  if ! gc sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
    echo "  creating the instance (about 10 minutes)"
    gc sql instances create "$SQL_INSTANCE" --database-version=POSTGRES_16 --edition=enterprise \
      --tier="$SQL_TIER" --region="$REGION" --availability-type=zonal \
      --storage-type=SSD --storage-size=10 --storage-auto-increase \
      --backup-start-time=19:00 --enable-point-in-time-recovery --retained-backups-count=14 \
      --deletion-protection
  fi
  gc sql databases describe kaori --instance="$SQL_INSTANCE" >/dev/null 2>&1 \
    || gc sql databases create kaori --instance="$SQL_INSTANCE"
  local pw
  pw=$(gc secrets versions access latest --secret="$SECRET_DB_ADMIN" | sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#')
  if gc sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx kaori_admin; then
    gc sql users set-password kaori_admin --instance="$SQL_INSTANCE" --password="$pw" >/dev/null
  else
    gc sql users create kaori_admin --instance="$SQL_INSTANCE" --password="$pw" >/dev/null
  fi
  echo "  database kaori, schema owner kaori_admin"
}

step_db() {
  say "Ledger schema and the API's login (a one-off Cloud Run job)"
  retry gc run jobs deploy "$DB_JOB" --image="$API_IMAGE" --region="$REGION" --service-account="$DBA_SA" \
    --set-cloudsql-instances="$SQL_CONN" --max-retries=0 --task-timeout=300 \
    --set-secrets="ADMIN_DATABASE_URL=$SECRET_DB_ADMIN:latest,RUNTIME_DATABASE_URL=$SECRET_DB:latest" \
    --command=python --args="-m,kaori_db.provision" --execute-now --wait
}

step_firebase() {
  say "Firebase Auth (email and password) and the app's Firebase settings"
  local body
  api GET "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID"; body=$API_BODY
  if [ "$API_STATUS" != 200 ]; then
    echo "  adding Firebase to $PROJECT_ID"
    api POST "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID:addFirebase" '{}'; body=$API_BODY
    [ "$API_STATUS" = 200 ] || die "could not add Firebase ($API_STATUS): $body
  Do it once by hand: console.firebase.google.com -> Add project -> pick $PROJECT_ID. Then re-run this step."
    wait_op "$(printf '%s' "$body" | json 'd["name"]')"
  fi
  echo "  Firebase: on"

  local cfg='{"signIn":{"email":{"enabled":true,"passwordRequired":true}}}'
  local url="https://identitytoolkit.googleapis.com/admin/v2/projects/$PROJECT_ID/config?updateMask=signIn.email.enabled,signIn.email.passwordRequired"
  api PATCH "$url" "$cfg"; body=$API_BODY
  if [ "$API_STATUS" != 200 ] && printf '%s' "$body" | grep -q CONFIGURATION_NOT_FOUND; then
    echo "  starting Firebase Auth for the project"
    api POST "https://identitytoolkit.googleapis.com/v2/projects/$PROJECT_ID/identityPlatform:initializeAuth" '{}'
    api PATCH "$url" "$cfg"; body=$API_BODY
  fi
  [ "$API_STATUS" = 200 ] || die "could not turn on email sign-in ($API_STATUS): $body
  Do it once by hand: console.firebase.google.com -> $PROJECT_ID -> Authentication -> Get started ->
  Sign-in method -> Email/Password -> Enable. Then re-run this step."
  echo "  email and password sign-in: on"

  local apps app_id
  api GET "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID/webApps"; apps=$API_BODY
  app_id=$(printf '%s' "$apps" | json "next((a['appId'] for a in d.get('apps', []) if a.get('displayName') == '$FIREBASE_APP_NAME' and a.get('state') == 'ACTIVE'), '')")
  if [ -z "$app_id" ]; then
    echo "  registering the app with Firebase"
    api POST "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID/webApps" "{\"displayName\":\"$FIREBASE_APP_NAME\"}"; body=$API_BODY
    [ "$API_STATUS" = 200 ] || die "could not register the app ($API_STATUS): $body"
    wait_op "$(printf '%s' "$body" | json 'd["name"]')"
    api GET "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID/webApps"; apps=$API_BODY
    app_id=$(printf '%s' "$apps" | json "next((a['appId'] for a in d.get('apps', []) if a.get('displayName') == '$FIREBASE_APP_NAME'), '')")
  fi
  [ -n "$app_id" ] || die "the Firebase app was not found after registering it"
  api GET "https://firebase.googleapis.com/v1beta1/projects/$PROJECT_ID/webApps/$app_id/config"; body=$API_BODY
  [ "$API_STATUS" = 200 ] || die "could not read the app's Firebase settings ($API_STATUS): $body"
  printf '%s' "$body" > "$FIREBASE_CONFIG"
  echo "  app settings saved to deploy/antalya/firebase-config.json (public values, not secrets)"
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
  # One instance: compile locks and the AI's background reads live in the process, so it must not
  # be split across instances, and its CPU must stay on after a response (--no-cpu-throttling).
  # Antalya's ~100 people fit easily.
  retry gc run deploy "$API_SERVICE" --image="$API_IMAGE" --region="$REGION" \
    --service-account="$API_SA" --allow-unauthenticated --set-cloudsql-instances="$SQL_CONN" \
    --cpu=1 --memory=1Gi --min-instances=1 --max-instances=1 --concurrency=40 --timeout=120 \
    --no-cpu-throttling --cpu-boost \
    --set-env-vars="KAORI_ANTALYA=1,KAORI_ENVIRONMENT=production,KAORI_SIGNING_KEY_ID=$SIGNING_KEY_ID,KAORI_OBSERVATIONS_BUCKET=$BUCKET,KAORI_GENERALIST_URL=$gen_url,FIREBASE_PROJECT_ID=$PROJECT_ID" \
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
  local api_url gen code body token key email idtoken
  api_url=$(service_url "$API_SERVICE"); gen=$(service_url "$GEN_SERVICE")
  body=$(curl -s "$api_url/v1/invites/AAAA-AAAA")
  expect "API is up and answers invites" '{"valid":false,"reason":"unknown"}' "$(printf '%s' "$body" | tr -d ' ')"
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$api_url/v1/compile" -H 'Content-Type: application/json' -d '{}')
  expect "compile refuses a caller with no sign-in" 401 "$code"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api_url/v1/assignments" -H 'Authorization: Bearer not-a-token')
  expect "a fake token is refused" 401 "$code"
  token=$(gc secrets versions access latest --secret="$SECRET_EXPORT")
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api_url/v1/export" -H "Authorization: Bearer $token")
  expect "export works with its token (ledger reachable)" 200 "$code"
  code=$(curl -s -o /dev/null -w '%{http_code}' "$api_url/v1/export" -H "Authorization: Bearer wrong")
  expect "export refuses a wrong token" 403 "$code"

  # A throwaway Firebase account: signed in, but not a member, so Kaori must say "Members only".
  # Nothing is written to the ledger; the account is deleted afterwards.
  [ -f "$FIREBASE_CONFIG" ] || die "run the firebase step first"
  key=$(json 'd["apiKey"]' < "$FIREBASE_CONFIG")
  email="smoke-$(openssl rand -hex 4)@example.com"
  body=$(curl -s -X POST "https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=$key" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$email\",\"password\":\"$(openssl rand -hex 12)\",\"returnSecureToken\":true}")
  idtoken=$(printf '%s' "$body" | json 'd.get("idToken", "")')
  expect "Firebase creates an account" yes "$([ -n "$idtoken" ] && echo yes || echo "no: $body")"
  if [ -n "$idtoken" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' "$api_url/v1/assignments" -H "Authorization: Bearer $idtoken")
    expect "Kaori accepts the Firebase sign-in and turns away a non-member" 403 "$code"
    curl -s -o /dev/null -X POST "https://identitytoolkit.googleapis.com/v1/accounts:delete?key=$key" \
      -H 'Content-Type: application/json' -d "{\"idToken\":\"$idtoken\"}"
  fi

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
  local who=${1:-} callsign=${2:-} uid body
  [ -n "$who" ] && [ -n "$callsign" ] || die "usage: deploy.sh seed <email or Firebase uid> \"<callsign>\""
  [[ "$callsign" != *"|"* ]] || die "the callsign cannot contain '|'"
  if [[ "$who" == *@* ]]; then
    api POST "https://identitytoolkit.googleapis.com/v1/projects/$PROJECT_ID/accounts:lookup" "{\"email\":[\"$who\"]}"; body=$API_BODY
    uid=$(printf '%s' "$body" | json '(d.get("users") or [{}])[0].get("localId", "")')
    [ -n "$uid" ] || die "no Firebase account for $who (they sign up in the app first)"
  else
    uid=$who
  fi
  [[ "$uid" =~ ^[A-Za-z0-9_-]{6,128}$ ]] || die "that does not look like a Firebase uid: $uid"
  say "Seeding user:$uid as $callsign"
  retry gc run jobs deploy "$SEED_JOB" --image="$API_IMAGE" --region="$REGION" --service-account="$API_SA" \
    --set-cloudsql-instances="$SQL_CONN" --set-secrets="DATABASE_URL=$SECRET_DB:latest" \
    --max-retries=0 --task-timeout=120 \
    --command=python --args="^|^-m|kaori_api.antalya|seed|user:$uid|$callsign" \
    --execute-now --wait
}

step_status() {
  local api_url fb=""
  api_url=$(service_url "$API_SERVICE" 2>/dev/null || true)
  [ -f "$FIREBASE_CONFIG" ] && fb=$(cat "$FIREBASE_CONFIG")
  fbv() { [ -n "$fb" ] && printf '%s' "$fb" | json "d.get('$1', '')" || echo "<run the firebase step>"; }
  say "Antalya"
  echo "  API       ${api_url:-not deployed}"
  echo "  AI        $(service_url "$GEN_SERVICE" 2>/dev/null || echo 'not deployed')"
  echo "  ledger    Cloud SQL $SQL_CONN, database kaori"
  echo "  photos    gs://$BUCKET"
  echo "  export    curl -H \"Authorization: Bearer \$(gcloud secrets versions access latest --secret=$SECRET_EXPORT --project=$PROJECT_ID)\" $api_url/v1/export"
  echo
  echo "  For the app (liminal-mobile mobile/.env, branch probe-antalya):"
  echo "    EXPO_PUBLIC_FIREBASE_API_KEY=$(fbv apiKey)"
  echo "    EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN=$(fbv authDomain)"
  echo "    EXPO_PUBLIC_FIREBASE_PROJECT_ID=$(fbv projectId)"
  echo "    EXPO_PUBLIC_FIREBASE_APP_ID=$(fbv appId)"
  echo "    EXPO_PUBLIC_KAORI_URL=${api_url:-<API url>}"
  echo "    EXPO_PUBLIC_ANTALYA=1"
}

cd "$ROOT"
case "${1:-all}" in
  all) for s in $STEPS; do "step_$s"; done ;;
  seed) shift; step_seed "$@" ;;
  *) [[ " $STEPS " == *" $1 "* ]] || die "unknown step '$1' (steps: $STEPS, seed)"; "step_$1" ;;
esac
