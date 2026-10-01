# Deploying Antalya

Everything runs in one GCP project, `msro-kaori-sandbox` (`asia-southeast1`), and one script deploys it.
Budget about an hour; most of it is waiting for the first image build and for Cloud SQL to start.

| Piece | Where |
|---|---|
| Sign-in (email and password) | Firebase Auth |
| Ledger (Signals, observations, TruthStates) | Cloud SQL Postgres 16 `kaori-antalya`, database `kaori`. Daily backups (14 kept), point-in-time recovery, deletion protection |
| Kaori API, `kaori-api-antalya` | Cloud Run, public. Kaori checks every Firebase sign-in itself |
| AI reader, `kaori-generalist-antalya` | Cloud Run, private: only the API's service account may call it |
| Photos | Private bucket `msro-kaori-sandbox-kaori-antalya` |
| Keys | Secret Manager: signing key, validator key, export token, and the two database logins |

Services that already exist in the project (`kaori-api`, `kaori-generalist`, and others) are not touched.
Everything this script creates is named `*-antalya`.

## Run it

You need an Owner on `msro-kaori-sandbox`, in Cloud Shell (console.cloud.google.com, the `>_` button):

```bash
git clone -b iac/antalya-2026 https://github.com/MadinMSRO/kaori-protocol.git
cd kaori-protocol
./deploy/antalya/deploy.sh
```

The repository is private, so `git clone` asks for a GitHub user name and a personal access token with
read access to this repository.

The script asks nothing else: every password and key is generated and goes straight into Secret Manager.
When it finishes, it prints the values for the app.

## What it does

Every step is safe to re-run. To run one step: `./deploy/antalya/deploy.sh <step>`.

| Step | Does |
|---|---|
| `check` | gcloud is signed in and can see the project |
| `apis` | Turns on Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Storage, IAM, Cloud SQL, Firebase, Identity Toolkit |
| `build` | Builds both images, tagged with the git commit. The AI image takes 10–20 minutes the first time |
| `bucket` | The private photo bucket |
| `secrets` | Generates the signing key, the validator key, the export token and both database logins. Existing ones are kept |
| `accounts` | Three service accounts, each with only what it needs: the API, the AI, and database setup |
| `sql` | The Cloud SQL instance (about 10 minutes the first time), the `kaori` database, and the schema-owner login |
| `db` | A one-off Cloud Run job that applies the ledger schema and creates the API's login. That login can only add to the ledger: no deletes, no schema changes |
| `firebase` | Adds Firebase to the project, turns on email and password sign-in, and registers the app |
| `signing` | Creates the Android signing key in Secret Manager (once; it never changes), lets GitHub Actions in `liminal-mobile` (main and `probe-*` only) read it through Workload Identity Federation, and registers its fingerprints with Firebase. The key never leaves GCP except into a build |
| `downloads` | A public bucket that only CI writes to: the signed APK, its install page and `latest.json` for in-app updates |
| `generalist` | Deploys the AI: 2 CPU, 4 GiB, one instance always warm. Lets the API call it |
| `api` | Deploys the API: one instance, always on, connected to Cloud SQL. Phones must link by hardware attestation and run MSRO's signed app (`REQUIRE_DEVICE=0` in `antalya.env` only records it) |
| `smoke` | Checks the live services (below) |
| `status` | Prints the URLs and the app's settings |

The API runs as exactly one instance on purpose. Compile locks and the AI's background reads live in the
process, so they must not be split across instances, and the CPU must stay on after a response. About
100 people fit easily.

## Smoke test

`./deploy/antalya/deploy.sh smoke` checks:
- the API is up and answers an invite lookup;
- compile refuses a caller who isn't signed in, and a fake token is refused;
- the export works with its token (so Cloud SQL is reachable) and refuses a wrong one;
- **Firebase sign-in works end to end:**
  - it creates a throwaway Firebase account;
  - Kaori accepts that account's token and turns it away as a non-member;
  - the account is deleted. Nothing is written to the ledger;
- the AI refuses outside callers and reads a photo.

The full loop (invite → photo → blind readings → VERIFIED_TRUE) is not run against the live service, because
it would write test truths into the real ledger. It is proven locally by `npm run antalya-contract` in
`liminal-mobile`, and on the live service by the Malé dry run with real phones.

## Seeds

Seeds are members without an invite. Each one creates an account in the app first, then:

```bash
./deploy/antalya/deploy.sh seed name@example.com "<callsign>"
```

This looks up their Firebase account by email and runs a one-off Cloud Run job that adds them to the
ledger. A Firebase uid works in place of the email.

## The app

`./deploy/antalya/deploy.sh status` prints the six values for `liminal-mobile/mobile/.env`. Commit them on
a `probe-antalya` branch, and GitHub Actions builds the APK and publishes it as a pre-release. The
Firebase values are public by design; they identify the project and grant nothing.

## Getting the data out

```bash
curl -H "Authorization: Bearer $(gcloud secrets versions access latest --secret=antalya-export-token)" \
  "$(gcloud run services describe kaori-api-antalya --region=asia-southeast1 --format='value(status.url)')/v1/export" > antalya.ndjson
```

## Cost (rough estimate)

| Item | Per month |
|---|---|
| AI kept warm (2 CPU, 4 GiB) | $40–60 |
| API always on (1 CPU, 1 GiB) | about $50 |
| Cloud SQL `db-g1-small` with backups | $25–35 |
| Photos, secrets, builds, Firebase email sign-in | a few dollars |

Roughly $120–150 a month while it is live. After the event, set both services to `--min-instances=0`.

## If something goes wrong

- **The `firebase` step stops:** it prints the one console action to take (adding Firebase to the project,
  or turning on Email/Password under Authentication). Do it, then run `./deploy/antalya/deploy.sh firebase`
  again. If the project has never used Firebase Auth, this step starts it through Identity Platform; email
  sign-in is free well beyond Antalya's numbers.
- **Cloud SQL creation fails with a public-IP policy error:** the organisation forbids public IPs on Cloud
  SQL (`constraints/sql.restrictPublicIp`). The instance has no authorised networks either way (only the
  Cloud Run connector can reach it), so ask an organisation admin for an exception on this project.
- **Build fails pushing the image:** Cloud Build's account lacks access. The `build` step grants
  `artifactregistry.writer`, `logging.logWriter` and `storage.objectViewer` to the default compute
  account. Check that account exists (it appears once Compute Engine is on).
- **The API returns 403 to everyone:** an organisation policy blocks public services. The `api` step
  detects this and turns off Cloud Run's invoker check instead. Kaori still requires a Firebase sign-in.
- **The API won't start:** check its logs in Cloud Run. `Kaori schema is incomplete` means the `db` step
  hasn't run.
- **Logs of the one-off jobs:** Cloud Run → Jobs → `kaori-antalya-db` or `kaori-antalya-seed`.
