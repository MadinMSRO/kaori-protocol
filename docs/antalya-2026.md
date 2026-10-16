# Antalya 2026 service (`kaori-api-antalya`)

The IAC sky test runs the same image as `kaori-api`, with one extra environment variable. The plan is in
`liminal-mobile/docs/ANTALYA_MVP_PLAN.md`; this page covers what the service needs.

## Turning it on

| Variable | Value | Effect |
|---|---|---|
| `KAORI_ANTALYA` | `1` | Mounts the routes below. `/v1/evidence` and `/v1/compile` accept members only (joined by invite, or seeded) |
| `KAORI_EXPORT_TOKEN` | a new secret | Bearer token for `GET /v1/export` |
| `KAORI_GENERALIST_URL` | the `kaori-generalist` service URL | **Required.** The AI reads every photo through its `POST /read`, as a validator does |
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
| `GET /v1/assignments?limit=5` | member | Without whose report it is, where or when: `[{assignment_id, claim_type_id, title, provenance_badge, expires_at, evidence: [{kind, mime, url}], questions: [{name, type, label, options?, option_labels?, unit?, min?, max?, step?}], image_url, options}]`. `image_url` (first photo, or null) and `options` are kept for older app builds |
| `GET /v1/assignments/{id}/evidence/{i}` | the assigned member | One piece of evidence with its metadata stripped: a photo re-encoded as JPEG **without EXIF**; JSON or CSV without location, time or identity keys and columns; audio and video remuxed without metadata (`ffmpeg -map_metadata -1`; served as stored, with a logged warning, when ffmpeg is missing) |
| `GET /v1/assignments/{id}/image` | the assigned member | The first photo, re-encoded as JPEG **without EXIF** (EXIF would reveal place and time) |
| `POST /v1/assignments/{id}/reading` | the assigned member | `{values: {<question>: <answer>}}`, or `{values: null, unusable: true}` when the evidence can't be checked (a REJECT); the older `{cover, raining}` still works → `{ok}`. One reading per assignment. Records a vote on the key (plan §3.4) |
| `GET /v1/export` | `Bearer $KAORI_EXPORT_TOKEN` | NDJSON: every Signal, then every TruthState |
| `GET /v1/me` | signed in | `{agent_id, member, device, device_required}` |
| `DELETE /v1/me` | signed in | `{agent_id, member: false, left: true, appended}`. Leaves: MEMBERSHIP_ENDED, DEVICE_UNLINKED, INVITE_CANCELLED for open invites and a waiting join. Idempotent |
| `GET /v1/progress/{truthkey}` | signed in | `{truthkey, cell, resolution, received, required, status}`. Reporters so far; `PENDING` until a TruthState exists. `cell`/`resolution`: the key's H3 cell (null for a non-H3 key). Read-only, never 404 |
| `GET /v1/truths?cells=<h3>,<h3>…` | signed in | `{cells, truths: [{truthkey, claim_type_id, cell, resolution, time_bucket, status, claim, confidence, lights}]}`. Truths whose cell is a requested cell, an ancestor of one or a descendant of one; `lights` = the requested cells it covers (a res 8 sky truth lights its res 10 children). Also `&cell=` (repeatable), `&claim_type_id=a,b`, `&since=<ISO time>` (time buckets starting then or later). Up to 5000 cells. Read-only |
| `POST /v1/devices/challenge` | member | `{challenge, package, expires_in}`: single use, ten minutes, bound to the caller |
| `POST /v1/devices/link` | member | `{challenge, chain: [base64 DER, leaf first]}` → `{device_id: "sensor:android-…", security_level, verified_boot_state, …}` or 403 with `reasons` |

`/v1/compile` observations may carry a `provenance` block beside the observation:
`{exif:{datetime_original, offset_time?, tz_offset_min?, gps:{lat,lon}}, capture_source:"camera", device:{platform, model, app_version}}`.
It is recorded as `PROVENANCE_RECORDED`, with the checks behind the validator's badge: in-app capture, time within
120 s, place within 150 m.

### Hexagon sizes

Each ClaimType keeps its own H3 resolution. Sky cover (`earth.sky_cover.v1`) is res 8. The ground claims are
res 10 from their v2 on: `earth.flood_water.v2`, `earth.vegetation.v2`, `earth.coastal_erosion.v2` (the app's
shoreline); their v1 types stay registered and their truths stay in the ledger. The map draws islands as res 10
hexagons and lights each truth's res 10 children, from `GET /v1/truths`.

A v2 ground claim's `truthkey.position` makes `/v1/compile` refuse (400) a key that is not a res 10 H3 cell of
that claim's topic, and a report whose `geo` is not in the key's hexagon or one of the 6 around it (165-200 m from
the centre). A fix just outside that ring still counts when `geo.accuracy_m` (counted up to 100 m) reaches the
hexagon. v1 types are not checked.

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

### iPhones (Apple App Attest)

An iPhone links through the same two endpoints. `POST /v1/devices/challenge` is unchanged. The app calls
`DCAppAttestService.generateKey()`, then `attestKey(keyId, clientDataHash: SHA256(challenge as UTF-8))`, and
sends `POST /v1/devices/link` with `{"platform": "ios", "challenge", "keyId", "attestationObject"}` (base64;
`key_id` / `attestation_object` are accepted too). Kaori follows Apple's steps (`app_attest.py`):

- the attestation is CBOR, format `apple-appattest`, and its `x5c` chain (credential certificate, then
  intermediate) ends at Apple's App Attestation Root CA, bundled with the package; every certificate is in date;
- the nonce in the credential certificate (OID 1.2.840.113635.100.8.2) is SHA256(authData || SHA256(challenge));
- SHA256 of the certificate's public key is the `keyId`, and so is the credential id in authData;
- authData's rpIdHash is SHA256 of the App ID, `KAORI_APPLE_APP_ID` (`<TEAM_ID>.mv.msro.liminal`); unset, no
  iPhone can link;
- the counter is 0, and the AAGUID is `appattest` (production: TestFlight, App Store). `appattestdevelop`
  (an Xcode build) is refused unless `KAORI_APPLE_ALLOW_DEVELOP=1`.

The phone becomes `sensor:ios-<first 24 hex of keyId>`; `DEVICE_LINKED` holds its public key, `key_id`, `app_id`
and `counter` 0, with `platform: "ios"` and `security_level: "secure_enclave"`. Everything else is as for
Android: one phone per person (an iPhone replaces an Android phone and the other way round), refusals recorded,
and `KAORI_REQUIRE_DEVICE` applies unchanged.

Reports: the iPhone signs the same JSON text an Android phone signs, with
`generateAssertion(keyId, clientDataHash: SHA256(text))`, and sends
`device_proof: {"platform": "ios", "device_id", "signed": text, "assertion": base64}` (an assertion sent as
`signature` is accepted too; the platform is taken from the linked phone, not the proof). Kaori checks the
assertion's signature over SHA256(authenticatorData || SHA256(text)) with the linked key, that its rpIdHash is the
App ID, and its counter. Reports are signed when sealed and may upload later, out of order (the offline outbox),
so the counter need not be the highest yet: it must never have been accepted for that key before (an exact replay
never counts) and must be within 1000 of the highest seen (older is refused as stale, which keeps the set of
remembered counters bounded). Accepted counters are kept in the ledger (`device_proof.counter` in
`PROVENANCE_RECORDED`, `device_counter` in `INVITE_CONFIRMED`), so a replay is refused after a restart and on other
instances too. NFC holds are signed the same way: `device: {"platform": "ios", "device_id", "assertion"}` over
`liminal-hold:v1:<invite>:<nonce>:<hold_ms>`. The
verifier is tested on a real iPhone's attestation and assertion (`tests/data/app_attest`) and on a test CA.

## The AI reads every photo as a validator does

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

## What validators check

Validators check any kind of evidence: photo, data (numbers and readings), audio or video. Each report is checked
independently, without seeing whose report it is, where or when it was made, or what the reporter said. Any
report with evidence can be assigned (never your own, nor one from a key you reported at; at most three people per
report). The questions come from the ClaimType: its `validation` block names the fields a validator answers and
how each is compared with the report, `equal`, `{within_steps: n}` (index distance in a select's options),
`{within: x}` (absolute, in the field's unit) or `{within_pct: p}`. Without a `validation` block every required
`ui_schema` field is asked: select and boolean must be equal, a number within 10 percent. A reading is RATIFY when
every field agrees, otherwise REJECT. Sky cover: cover within one band and the same answer on rain.

`ui_schema` select fields may carry `option_labels` (sky cover: None, A little, About half, Most, All) and number
fields `unit`, `min`, `max` and `step`. The AI reads photos only.

## Sky photos at 1x

`earth.sky_cover.v1` declares `evidence.capture.camera_zoom: 1`. The app takes sky photos with its own camera
held at 1x and says so in the provenance block (`camera: {zoom: 1}`, plus EXIF `digital_zoom` when the photo
has it). Kaori records `checks.zoom_matches` and validators see it among the provenance ticks.
