# Antalya 2026 service (`kaori-api-antalya`)

The IAC sky test runs the same image as `kaori-api`, with one extra environment variable. The plan is in
`liminal-mobile/docs/ANTALYA_MVP_PLAN.md`; this page covers what the service needs.

## Turning it on

| Variable | Value | Effect |
|---|---|---|
| `KAORI_ANTALYA` | `1` | Mounts the routes below. `/v1/evidence` and `/v1/compile` accept members only (joined by invite, or seeded) |
| `KAORI_EXPORT_TOKEN` | a new secret | Bearer token for `GET /v1/export` |
| `KAORI_GENERALIST_URL` | the `kaori-generalist` service URL | **Required.** The AI reads every photo blind through its `POST /read` |
| `FIREBASE_PROJECT_ID` | the GCP project id | Sign-in is Firebase Auth: Kaori verifies each ID token offline (Google's signature, this project as audience and issuer) and the agent is `user:{firebase uid}`. Unset, Kaori uses Supabase Auth as before |
| everything else | set by `deploy/antalya/deploy.sh` | Cloud SQL ledger, a private bucket, new signing keys |

**Deploying:** `deploy/antalya/README.md`. Everything lives in one GCP project: Firebase Auth, Cloud SQL, Cloud Run,
Cloud Storage and Secret Manager. The schema, the roles and the API's append-only login are as in
`deployment-runbook.md`; the schema is applied by a one-off Cloud Run job (`python -m kaori_db.provision`).
`DATABASE_URL` must name its driver (`postgresql+psycopg2://`): SQLAlchemy 2.1 otherwise picks psycopg 3, which the
image doesn't have.

Without `KAORI_ANTALYA` the API is exactly the existing `kaori-api` (the route allow-list test enforces this).

**No migration is needed.** Invites, redemptions, provenance, assignments and readings are Signals (Rule 1) in the
existing `signals` table:
`INVITE_ISSUED`, `REFERRAL_REDEEMED`, `PROVENANCE_RECORDED`, `ASSIGNMENT_ISSUED`, `READING_SUBMITTED`.

## Seeds

Seeds join without an invite. On the deployed service: `./deploy/antalya/deploy.sh seed <email> "<callsign>"`. Directly, with the
service's `DATABASE_URL`:

```bash
python -m kaori_api.antalya seed user:<firebase-uid> "<callsign>"
```

## Routes (Antalya only)

| Route | Auth | Notes |
|---|---|---|
| `POST /v1/invites` | member | Body `{callsign?}` → `{code, expires_at, qr_payload}`. Single use, 7 days. Only the hash is stored |
| `GET /v1/invites/{code}` | none | `{valid, referrer_callsign, expires_at}`, or `{valid:false, reason: unknown\|used\|expired}` |
| `POST /v1/invites/redeem` | new user | `{code, name, relationship, known_for, device_id}` (the invitee's own account, given without seeing the inviter's) → `{agent_id, referrer}`. One member per device (hashed) |
| `GET /v1/assignments?limit=5` | member | Blind: `{assignment_id, image_url, provenance_badge, claim_type_id, options, expires_at}` |
| `GET /v1/assignments/{id}/image` | the assigned member | The photo, re-encoded as JPEG **without EXIF** (EXIF would reveal place and time) |
| `POST /v1/assignments/{id}/reading` | the assigned member | `{cover, raining}` → `{ok}`. One reading per assignment. Records a vote on the key (plan §3.4) |
| `GET /v1/export` | `Bearer $KAORI_EXPORT_TOKEN` | NDJSON: every Signal, then every TruthState |
| `GET /v1/me` | signed in | `{agent_id, member, device, device_required}` |
| `POST /v1/devices/challenge` | member | `{challenge, package, expires_in}`: single use, ten minutes, bound to the caller |
| `POST /v1/devices/link` | member | `{challenge, chain: [base64 DER, leaf first]}` → `{device_id: "sensor:android-…", security_level, verified_boot_state, …}` or 403 with `reasons` |

`/v1/compile` observations may carry a `provenance` block beside the observation:
`{exif:{datetime_original, offset_time?, tz_offset_min?, gps:{lat,lon}}, capture_source:"camera", device:{platform, model, app_version}}`.
It is recorded as `PROVENANCE_RECORDED`, with the checks behind the validator's badge: in-app capture, time within
120 s, place within 150 m.

## Where this differs from the plan

- **Image URL.** The plan says a short-lived signed URL. The image is served instead through
  `/v1/assignments/{id}/image`: bearer auth, the assignee only, no caching, and EXIF stripped. A signed GCS URL
  would hand the validator the original file with its GPS. The app loads it with the Authorization header.
- **Members-only gate** on evidence and compile, so sign-up really is referral-only on this service.
- **Readings compile only once the key has its reporters.** Before that the vote is recorded and used when the
  third report arrives.

## Linked phones (hardware attestation)

A member links their phone once, after signing up. The phone's Android Keystore makes a signing key for a
Kaori challenge, and Kaori checks the key's attestation chain (`attestation.py`). The checks:

- the chain ends at one of Google's hardware attestation roots and nothing in it is revoked;
- the key is in secure hardware (TEE or StrongBox);
- the phone booted verified software with a locked bootloader;
- the key was made by `mv.msro.liminal`, signed with MSRO's certificate (`KAORI_ANDROID_CERT_SHA256`).

The phone becomes an agent, `sensor:android-…` (`DEVICE_LINKED`). Each person has one linked phone: a new one
unlinks the old (`DEVICE_UNLINKED`). Refusals are recorded with their reasons (`DEVICE_LINK_REFUSED`). Each report
carries a `device_proof`: the phone signs, at capture time, a JSON text of the truth key, claim type, capture time,
place, readings and photo hash. Kaori checks the signature against the linked key and that the text matches the
report. The result is recorded in `PROVENANCE_RECORDED` and shown to validators as a `device_signed` tick. With
`KAORI_REQUIRE_DEVICE=1`, the deploy default, evidence, reports and readings need a linked phone, and a report
whose signature does not check out is refused.

Certificates are read with Kaori's own DER reader, not a strict X.509 parser: some phones emit attestation
certificates with harmless encoding quirks. It is tested on Google's real sample chains
(`tests/data/attestation`).

## The AI reads every photo blind

Every accepted photo is also assigned to `ai:generalist_v1`. Kaori sends `kaori-generalist` (`POST /read`) the
same EXIF-stripped image a person sees. CLIP reads it zero-shot over the ClaimType's `generalist.readings`
prompts, and says whether it is a sky at all (the ClaimType's relevance threshold). The reading is recorded like
anyone's (`ASSIGNMENT_ISSUED`, `READING_SUBMITTED` with the probabilities) and becomes a vote. The old key-level AI
call is skipped on this service. Reads are serialised and the model loads at service start; a failed read is
retried once.

`sky_cover` uses `verification.rule: weighted_readings`: a reading backs the key when its photo shows the claimed
value (within one band); each agent counts once per key, weighted by its standing in the frozen TrustSnapshot;
verified at `finalize_threshold` (15). No AI-only threshold. At starting standing the AI alone (about 5.7) cannot
verify a key; with two or three people it can.

**Check before deploying:** `kaori-generalist` must be built from this branch (it needs the `/read` route). Its
image downloads the CLIP weights at build time (Hugging Face), which Cloud Build can reach.

Locally, with real CLIP, the contract passes: the AI read all three photos (2 to 4 s each), voted RATIFY, RATIFY
and REJECT (one photo showed rain its reporter did not report), and the key verified with 12 votes.

## Admin API (the admin panel's contract)

For MSRO's team. Admins sign in with Firebase (Google) in the same project; Kaori verifies the ID token and
requires a verified email listed in `KAORI_ADMIN_EMAILS`. Otherwise 401 (no or bad token) or 403 (not an admin).
The panel's web addresses must be in `KAORI_CORS_ORIGINS` and in Firebase's authorized domains (deploy.sh sets
both from `ADMIN_ORIGINS`).

| Route | Returns |
|---|---|
| `GET /v1/admin/me` | `{email, agent_id}` |
| `GET /v1/admin/overview` | `{members, seeds, invites_issued, invites_redeemed, phones_linked, phones_refused, reports, reports_device_signed, readings, ai_readings, truthkeys, truths_by_status: {STATUS: n}, per_hour: [{hour, reports, readings}], device_required}` |
| `GET /v1/admin/members` | `[{agent_id, callsign, seed, referrer, referrer_callsign, relationship, known_for, joined_at, device: {device_id, linked_at, security_level} \| null, reports, readings, invites_issued, standing}]` |
| `GET /v1/admin/truths` | `[{truthkey, claim_type_id, reporters, device_signed, readings, ai_readings, status, confidence, claim, first_report_at}]`, newest first. `status` is `PENDING` until the key compiles |
| `GET /v1/admin/devices` | `{linked: [{device_id, agent_id, callsign, linked_at, security_level, verified_boot_state, os_patch_level, app_cert_ok}], refused: [{agent_id, callsign, at, reasons, security_level}]}` |
| `POST /v1/admin/seeds` | body `{agent_id: "user:<firebase uid>", callsign?}` → `{agent_id, seeded_at, by}`. Adds a member without an invite (REFERRAL_REDEEMED from `seed:msro`). Idempotent |
| `POST /v1/admin/devices/{device_id}/unlink` | `{device_id, unlinked: true}`. DEVICE_UNLINKED, reason `admin`; the person links a phone again |
| `GET /v1/admin/export` | The NDJSON export (every Signal, then every TruthState), as a download |

Callsigns come from the ledger: a seed's, or the one on the latest invite a member issued. Kaori holds no
emails for members; a member is `user:<firebase uid>`.

## Two-sided introductions

Each invite carries two independent accounts of the same relationship. The inviter names the person they invite
and says how they know them and for how long; the invitee, without seeing those answers, gives their own name
and their own answers. At redemption Kaori records `agreement: {relationship, known_for (within one step),
name (first name, accents and case ignored)}`, each true, false, or null when a side did not say. A
disagreement is recorded, not refused.

Names are encrypted (AES-256-GCM, `KAORI_NAME_KEY` from Secret Manager), each bound to its record, so no name is
in clear in a Signal, the export or a log. `GET /v1/admin/members` decrypts them for admins: `name` (the
member's own), `name_by_inviter`, `inviter_relationship`, `inviter_known_for` and `agreement`.

The invite QR holds `KAORI_JOIN_URL?code=…`, a web page that opens Liminal straight into Join, or installs it first.

## Sky photos at 1x

`earth.sky_cover.v1` declares `evidence.capture.camera_zoom: 1`. The app takes sky photos with its own camera
held at 1x and says so in the provenance block (`camera: {zoom: 1}`, plus EXIF `digital_zoom` when the photo
has it). Kaori records `checks.zoom_matches` and validators see it among the provenance ticks.
