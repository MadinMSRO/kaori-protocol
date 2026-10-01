# Deploying Antalya

A fresh deployment: one GCP project, one Supabase project. About an hour, most of it waiting for the
first image build.

| Piece | Where |
|---|---|
| Sign-in (email and password) | Supabase Auth |
| Ledger (Signals, observations, TruthStates) | Supabase Postgres, schema `kaori` (not exposed through Supabase's API) |
| Kaori API, `kaori-api-antalya` | Cloud Run, public (Kaori checks each Supabase sign-in itself) |
| AI reader, `kaori-generalist-antalya` | Cloud Run, private: only the API's service account may call it |
| Photos | Private bucket `<project>-kaori-antalya` |
| Keys | Secret Manager: `antalya-signing-key`, `antalya-validator-key`, `antalya-export-token`, `antalya-database-url` |

## Before you start

**Supabase** (supabase.com, new project):
1. Region **Southeast Asia (Singapore)**, Pro plan (free projects pause after a week idle).
2. Keep the database password you set; the script asks for it once.
3. Authentication -> Sign In / Providers -> Email: on. Turn **Confirm email off**. The app has no
   web page to land on after the confirmation link, and joining is already invite-only.
4. Note, for `antalya.env`: the project URL and publishable key (Project Settings -> API), and the
   **Session pooler** host (Connect button -> Session pooler; for example
   `aws-0-ap-southeast-1.pooler.supabase.com`).

**GCP**: the project id, billing on, and an Owner who can open Cloud Shell.

## Run it

In Cloud Shell:

```bash
git clone -b iac/antalya-2026 https://github.com/MadinMSRO/kaori-protocol.git
cd kaori-protocol
cp deploy/antalya/antalya.env.example deploy/antalya/antalya.env
nano deploy/antalya/antalya.env       # fill in the four values
./deploy/antalya/deploy.sh
```

The repository is private, so the clone asks for a GitHub user name and a personal access token
(read access to this repo is enough).

It runs these steps in order, and every step is safe to re-run:

| Step | Does |
|---|---|
| `check` | gcloud is signed in and can see the project |
| `apis` | Turns on Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Storage, IAM |
| `build` | Builds both images (tagged with the git commit). The AI image takes 10-20 min the first time |
| `bucket` | The private photo bucket |
| `secrets` | Generates the signing key, validator key and export token. Existing ones are kept |
| `accounts` | Two service accounts, each with only its own secrets (the API also gets the bucket) |
| `db` | Asks for the Supabase password, applies the ledger schema, creates the API's own login (append-only, no DDL) and stores its URL as a secret |
| `generalist` | Deploys the AI: 2 CPU, 4 GiB, one instance always warm. Lets the API call it |
| `api` | Deploys the API: one instance, always on |
| `smoke` | Checks the live services (below) |
| `status` | Prints the URLs and the values for the app |

Run one step with `./deploy/antalya/deploy.sh <step>`.

The API runs as exactly one instance on purpose. Compile locks and the AI's background reads live in
the process, so they must not be split across instances, and the CPU must stay on after a response.
About 100 people fit easily.

## Smoke test

`./deploy/antalya/deploy.sh smoke` checks:
- the API is up and answers an invite lookup;
- compile refuses a caller who isn't signed in;
- Supabase rejects a fake token;
- the export works with its token (so the ledger is reachable) and refuses a wrong one;
- the AI refuses outside callers;
- the AI reads a photo.

The full loop (invite -> photo -> blind readings -> VERIFIED_TRUE) is not run against the live service,
because it would write test truths into the real ledger. It is proven locally by
`npm run antalya-contract` in `liminal-mobile`, and on the live service by the Malé dry run with real phones.

## Seeds

Seeds are members without an invite. Each one first creates an account in the app. Then copy their UID
from Supabase -> Authentication -> Users, and run:

```bash
./deploy/antalya/deploy.sh seed <uid> "<callsign>"
```

This runs a one-off Cloud Run job with the API's own login.

## The app

`./deploy/antalya/deploy.sh status` prints the four values for `liminal-mobile/mobile/.env`. Commit them
on a `probe-antalya` branch; GitHub Actions builds the APK and publishes it as a pre-release.

## Getting the data out

```bash
curl -H "Authorization: Bearer $(gcloud secrets versions access latest --secret=antalya-export-token)" \
  "$(gcloud run services describe kaori-api-antalya --region=asia-southeast1 --format='value(status.url)')/v1/export" > antalya.ndjson
```

## If something goes wrong

- **Build fails pushing the image:** Cloud Build's account lacks access. The `build` step grants
  `artifactregistry.writer`, `logging.logWriter` and `storage.objectViewer` to the default compute
  account. Check that account exists (it appears once Compute Engine is on).
- **The API returns 403 to everyone:** an organisation policy blocks public services. The `api` step
  detects this and turns off Cloud Run's invoker check instead (Kaori still requires a Supabase sign-in).
- **The API won't start:** check its logs in Cloud Run. `Kaori schema is incomplete` means the `db` step
  hasn't run. `password authentication failed` means the login was re-keyed without redeploying: run `api`.
- **New database password for the API:** `REKEY=1 ./deploy/antalya/deploy.sh db`, then
  `./deploy/antalya/deploy.sh api`.
