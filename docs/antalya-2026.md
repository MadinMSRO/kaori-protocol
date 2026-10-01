# Antalya 2026 service (`kaori-api-antalya`)

The IAC sky test runs the same image as `kaori-api`, with one extra environment variable. The plan is in
`liminal-mobile/docs/ANTALYA_MVP_PLAN.md`; this page covers what the service needs.

## Turning it on

| Variable | Value | Effect |
|---|---|---|
| `KAORI_ANTALYA` | `1` | Mounts the routes below. `/v1/evidence` and `/v1/compile` accept members only (joined by invite, or seeded) |
| `KAORI_EXPORT_TOKEN` | a new secret | Bearer token for `GET /v1/export` |
| everything else | as in `deployment-runbook.md` | A new `KAORI_SIGNING_KEY` and `KAORI_SIGNING_KEY_ID` for Antalya, its own schema and bucket prefix |

Without `KAORI_ANTALYA` the API is exactly the existing `kaori-api` (the route allow-list test enforces this).

**No migration is needed.** Invites, redemptions, provenance, assignments and readings are Signals (Rule 1) in the
existing `signals` table:
`INVITE_ISSUED`, `REFERRAL_REDEEMED`, `PROVENANCE_RECORDED`, `ASSIGNMENT_ISSUED`, `READING_SUBMITTED`.

## Seeds

Seeds join without an invite. Run this with the service's `DATABASE_URL`:

```bash
python -m kaori_api.antalya seed user:<supabase-user-uuid> "<callsign>"
```

## Routes (Antalya only)

| Route | Auth | Notes |
|---|---|---|
| `POST /v1/invites` | member | Body `{callsign?}` → `{code, expires_at, qr_payload}`. Single use, 7 days. Only the hash is stored |
| `GET /v1/invites/{code}` | none | `{valid, referrer_callsign, expires_at}`, or `{valid:false, reason: unknown\|used\|expired}` |
| `POST /v1/invites/redeem` | new user | `{code, relationship, known_for, device_id}` → `{agent_id, referrer}`. One member per device (hashed) |
| `GET /v1/assignments?limit=5` | member | Blind: `{assignment_id, image_url, provenance_badge, claim_type_id, options, expires_at}` |
| `GET /v1/assignments/{id}/image` | the assigned member | The photo, re-encoded as JPEG **without EXIF** (EXIF would reveal place and time) |
| `POST /v1/assignments/{id}/reading` | the assigned member | `{cover, raining}` → `{ok}`. One reading per assignment. Records a vote on the key (plan §3.4) |
| `GET /v1/export` | `Bearer $KAORI_EXPORT_TOKEN` | NDJSON: every Signal, then every TruthState |

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
