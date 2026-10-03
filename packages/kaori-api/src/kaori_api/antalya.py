"""
Antalya MVP (IAC 2026): referral-only membership, provenance, validators' readings and export.

Every event here is an immutable Signal (Rule 1). Invites, redemptions, provenance, assignments and readings are
derived from the signal log, so the test needs no new tables:

  INVITE_ISSUED        a member shows an invite QR (30 min)     agent = referrer,  object = invite:<code hash>
  REFERRAL_REDEEMED    the invitee asks to join with it          agent = invitee,   object = invite:<code hash>
                       (a seed joins this way with no invite)
  INVITE_CONFIRMED     the inviter, in person, confirms them     agent = referrer,  object = invite:<code hash>
  INVITE_DECLINED      the inviter says it is not who they meant agent = referrer,  object = invite:<code hash>
  INVITE_CANCELLED     the inviter withdraws an unused invite    agent = referrer,  object = invite:<code hash>
  PROVENANCE_RECORDED  an observation's evidence is accepted    agent = reporter,  object = evidence:<sha256>
  ASSIGNMENT_ISSUED    evidence is assigned to a validator      agent = validator, object = assignment:<id>
  READING_SUBMITTED    a validator answers what it shows        agent = validator, object = assignment:<id>

Validators check each report independently, without seeing whose report it is: an assignment never carries the
reporter, the place, the TruthKey, the reporter's answer or other readings, and the evidence is served with its
metadata stripped (evidence_kinds: a photo re-encoded without EXIF, data without location, time or identity
fields, a recording without container metadata). A validator is never assigned their own report, nor one from a
key they reported at. Evidence is a photo, data, audio or video.

Membership is an in-person handshake: the inviter shows a QR, the invitee scans it, installs Liminal, signs in and
asks to join; the inviter's phone then shows who is joining and they become a member only when the inviter
confirms. Invites are counted by what happened to them (waiting, joining, joined, expired, declined, cancelled).

Readings feed the proven compile path through an adapter (plan §3.4): RATIFY when every field of the ClaimType's
`validation` block agrees with that observation's answer by its rule (sky cover: within one band and the same
answer on rain), otherwise REJECT; evidence a validator marks unusable is a REJECT. The readings themselves stay in the log for
the offline v5.0 analysis.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import secrets
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from kaori_flow import FlowCore
from kaori_flow.primitives.signal import Signal, SignalTypes

from kaori_api import devices, evidence_kinds, names
from kaori_api.evidence_kinds import strip_photo
from kaori_api.generalist_client import generalist_timeout_seconds

INVITE_TTL = timedelta(minutes=30)
# the inviter confirms a join request within this (they are standing together)
CONFIRM_TTL = timedelta(minutes=30)
ASSIGNMENT_TTL = timedelta(minutes=30)
READINGS_PER_EVIDENCE = 3
MAX_ASSIGNMENTS = 20
TIME_MATCH_SECONDS = 120
PLACE_MATCH_METRES = 150.0
SEED_REFERRER = "seed:msro"

RELATIONSHIPS = ("family", "friend", "colleague", "met_at_iac", "other")
KNOWN_FOR = ("lt_1m", "1_12m", "1_5y", "gt_5y")
COVER = ("clear", "few", "scattered", "broken", "overcast")

# Typeable codes: no 0/O, 1/I/L
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_RE = re.compile(r"[^A-Z0-9]")


def enabled() -> bool:
    """The Antalya service (kaori-api-antalya) sets KAORI_ANTALYA=1: routes mount and membership is by referral."""
    return os.environ.get("KAORI_ANTALYA", "").strip().lower() in ("1", "true", "yes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_code(code: str) -> str:
    return CODE_RE.sub("", (code or "").upper())


def code_hash(code: str) -> str:
    return _sha("invite:" + normalize_code(code))


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _emit(flow: FlowCore, signal_type: str, agent_id: str, object_id: str, payload: dict, time: Optional[datetime] = None) -> Signal:
    signal = Signal(
        signal_type=signal_type,
        time=time or _now(),
        agent_id=agent_id,
        object_id=object_id,
        payload=payload,
        policy_version=flow.policy.version,
    )
    flow.emit(signal)
    return signal


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------------- membership

_RESOLUTIONS = (SignalTypes.INVITE_CONFIRMED, SignalTypes.INVITE_DECLINED, SignalTypes.INVITE_CANCELLED)


def _resolution(flow: FlowCore, chash: Optional[str]) -> Optional[Signal]:
    """The inviter's last word on an invite: confirmed, declined or cancelled."""
    if not chash:
        return None
    found = [s for kind in _RESOLUTIONS for s in flow.store.get_by_type(kind) if (s.payload or {}).get("code_hash") == chash]
    return max(found, key=lambda s: s.time) if found else None


def _admitted(flow: FlowCore, redemption: Signal) -> bool:
    """A redemption makes a member when it needs no confirmation (seeds, and joins from before the handshake)
    or when the inviter confirmed it."""
    p = redemption.payload or {}
    if not p.get("needs_confirm"):
        return True
    res = _resolution(flow, p.get("code_hash"))
    return res is not None and res.signal_type == SignalTypes.INVITE_CONFIRMED


def _pending(flow: FlowCore, redemption: Signal) -> bool:
    p = redemption.payload or {}
    return bool(p.get("needs_confirm")) and _resolution(flow, p.get("code_hash")) is None \
        and redemption.time + CONFIRM_TTL > _now()


def is_member(flow: FlowCore, agent_id: str) -> bool:
    return any(s.agent_id == agent_id and _admitted(flow, s) for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED))


def join_state(flow: FlowCore, agent_id: str) -> Dict[str, Any]:
    """For /v1/me: member, or waiting for their inviter to confirm them, or neither."""
    if is_member(flow, agent_id):
        return {"member": True, "joining": None}
    mine = sorted((s for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) if s.agent_id == agent_id),
                  key=lambda s: s.time)
    if not mine:
        return {"member": False, "joining": None}
    last = mine[-1]
    p = last.payload or {}
    res = _resolution(flow, p.get("code_hash"))
    issued = _invite(flow, p.get("code_hash")) if p.get("code_hash") else None
    state = "waiting" if _pending(flow, last) else "declined" if res is not None else "expired"
    return {"member": False, "joining": {
        "state": state,
        "referrer_callsign": (issued.payload or {}).get("callsign") if issued else None,
        "confirm_by": (last.time + CONFIRM_TTL).isoformat(),
    }}


def require_member(flow: FlowCore, agent_id: str) -> None:
    if not is_member(flow, agent_id):
        raise HTTPException(status_code=403, detail="Members only: join with an invite")


def seed_member(flow: FlowCore, agent_id: str, callsign: Optional[str] = None) -> Signal:
    """A seed joins without an invite (admin script). Idempotent."""
    from kaori_api.validation import ensure_agent_registered

    for signal in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED):
        if signal.agent_id == agent_id:
            return signal
    ensure_agent_registered(flow, agent_id, role="observer")
    return _emit(
        flow, SignalTypes.REFERRAL_REDEEMED, agent_id, f"seed:{agent_id}",
        {"referrer": SEED_REFERRER, "relationship": None, "known_for": None, "device_id_hash": None,
         "code_hash": None, "callsign": callsign},
    )


# --------------------------------------------------------------------------------------------- invites

def _invite(flow: FlowCore, chash: str) -> Optional[Signal]:
    for signal in flow.store.get_by_type(SignalTypes.INVITE_ISSUED):
        if signal.payload.get("code_hash") == chash:
            return signal
    return None


def _redemption(flow: FlowCore, chash: str) -> Optional[Signal]:
    for signal in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED):
        if signal.payload.get("code_hash") == chash:
            return signal
    return None


def invite_status(flow: FlowCore, code: str) -> Dict[str, Any]:
    chash = code_hash(code)
    issued = _invite(flow, chash)
    if issued is None:
        return {"valid": False, "reason": "unknown"}
    expires_at = _parse_time(issued.payload.get("expires_at"))
    res = _resolution(flow, chash)
    if res is not None and res.signal_type == SignalTypes.INVITE_CANCELLED:
        return {"valid": False, "reason": "cancelled"}
    if _redemption(flow, chash) is not None:
        return {"valid": False, "reason": "used"}
    if expires_at is None or expires_at <= _now():
        return {"valid": False, "reason": "expired"}
    return {
        "valid": True,
        "referrer_callsign": issued.payload.get("callsign"),
        "expires_at": expires_at.isoformat(),
    }


def join_link(code: str) -> str:
    """What the invite QR holds: the web join page when one is configured (it opens Liminal, or installs it
    first), otherwise the app link."""
    base = os.environ.get("KAORI_JOIN_URL", "").strip()
    return f"{base}?code={code}" if base else f"liminal://join?code={code}"


def _inviter_side(body: Dict[str, Any]) -> Dict[str, Any]:
    """The inviter's account of the person they invite: their name, how they know them, for how long."""
    try:
        name = names.clean(body.get("invitee_name"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invitee_name: " + str(exc))
    relationship, known_for = body.get("relationship"), body.get("known_for")
    if relationship is not None and relationship not in RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="relationship must be one of " + ", ".join(RELATIONSHIPS))
    if known_for is not None and known_for not in KNOWN_FOR:
        raise HTTPException(status_code=400, detail="known_for must be one of " + ", ".join(KNOWN_FOR))
    return {"name": name, "relationship": relationship, "known_for": known_for}


def issue_invite(flow: FlowCore, agent_id: str, callsign: Optional[str] = None,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    require_member(flow, agent_id)
    side = _inviter_side(body or {})
    code = new_code()
    chash = code_hash(code)
    expires_at = _now() + INVITE_TTL
    # the inviter's answers are kept for comparison when the invite is redeemed, and never shown to the invitee
    _emit(flow, SignalTypes.INVITE_ISSUED, agent_id, f"invite:{chash}",
          {"code_hash": chash, "expires_at": expires_at.isoformat(), "callsign": callsign,
           "invitee_name_enc": names.seal(side["name"], f"invite:{chash}"),
           "relationship": side["relationship"], "known_for": side["known_for"]})
    return {"code": code, "id": chash, "expires_at": expires_at.isoformat(), "qr_payload": join_link(code)}


def agreement(inviter: Dict[str, Any], invitee: Dict[str, Any]) -> Dict[str, Optional[bool]]:
    """Whether the two independent accounts agree; None where one side did not say."""
    def known_close(a, b):
        if a not in KNOWN_FOR or b not in KNOWN_FOR:
            return None
        return abs(KNOWN_FOR.index(a) - KNOWN_FOR.index(b)) <= 1
    rel_a, rel_b = inviter.get("relationship"), invitee.get("relationship")
    return {
        "relationship": None if not rel_a or not rel_b else rel_a == rel_b,
        "known_for": known_close(inviter.get("known_for"), invitee.get("known_for")),
        "name": names.same_person(inviter.get("name"), invitee.get("name")),
    }


def redeem_invite(flow: FlowCore, agent_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    from kaori_api.validation import ensure_agent_registered

    code = body.get("code")
    relationship = body.get("relationship")
    known_for = body.get("known_for")
    device_id = body.get("device_id")
    if not isinstance(code, str) or not code.strip():
        raise HTTPException(status_code=400, detail="Missing code")
    if relationship not in RELATIONSHIPS:
        raise HTTPException(status_code=400, detail="relationship must be one of " + ", ".join(RELATIONSHIPS))
    if known_for not in KNOWN_FOR:
        raise HTTPException(status_code=400, detail="known_for must be one of " + ", ".join(KNOWN_FOR))
    if not isinstance(device_id, str) or len(device_id.strip()) < 8:
        raise HTTPException(status_code=400, detail="Missing device_id")
    if is_member(flow, agent_id):
        raise HTTPException(status_code=409, detail="Already a member")
    if any(s.agent_id == agent_id and _pending(flow, s) for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED)):
        raise HTTPException(status_code=409, detail="Waiting for your inviter to confirm you")
    status = invite_status(flow, code)
    if not status["valid"]:
        raise HTTPException(status_code=410 if status["reason"] in ("used", "expired", "cancelled") else 404,
                            detail=f"Invite {status['reason']}")
    chash = code_hash(code)
    issued = _invite(flow, chash)
    referrer = issued.agent_id
    if referrer == agent_id:
        raise HTTPException(status_code=400, detail="You cannot redeem your own invite")
    try:
        own_name = names.clean(body.get("name"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="name: " + str(exc))
    device_hash = _sha("device:" + device_id.strip())
    for signal in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED):
        # a phone joins once; a request that was declined or ran out does not hold it
        if signal.payload.get("device_id_hash") == device_hash and (_admitted(flow, signal) or _pending(flow, signal)):
            raise HTTPException(status_code=409, detail="This device already joined")
    ensure_agent_registered(flow, agent_id, role="observer")
    ip = issued.payload or {}
    inviter = {"name": names.unseal(ip.get("invitee_name_enc"), f"invite:{chash}"),
               "relationship": ip.get("relationship"), "known_for": ip.get("known_for")}
    _emit(flow, SignalTypes.REFERRAL_REDEEMED, agent_id, f"invite:{chash}",
          {"referrer": referrer, "relationship": relationship, "known_for": known_for,
           "device_id_hash": device_hash, "code_hash": chash,
           "name_enc": names.seal(own_name, f"member:{agent_id}"),
           "agreement": agreement(inviter, {"name": own_name, "relationship": relationship, "known_for": known_for}),
           "needs_confirm": True})
    return {"agent_id": agent_id, "referrer": referrer, "member": False, "joining": join_state(flow, agent_id)["joining"]}


# ------------------------------------------------------------------------------- the inviter's side

def _invite_view(flow: FlowCore, issued: Signal) -> Dict[str, Any]:
    """One invite as its inviter sees it. The joiner's own answers about the inviter are never shown."""
    p = issued.payload or {}
    chash = p.get("code_hash")
    red = _redemption(flow, chash)
    res = _resolution(flow, chash)
    expires_at = _parse_time(p.get("expires_at"))
    if res is not None:
        status = {SignalTypes.INVITE_CONFIRMED: "joined", SignalTypes.INVITE_DECLINED: "declined",
                  SignalTypes.INVITE_CANCELLED: "cancelled"}[res.signal_type]
    elif red is not None:
        status = "joining" if red.time + CONFIRM_TTL > _now() else "expired"
    else:
        status = "waiting" if expires_at and expires_at > _now() else "expired"
    return {
        "id": chash,
        "status": status,
        "created_at": issued.time.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "name_by_you": names.unseal(p.get("invitee_name_enc"), f"invite:{chash}"),
        # the name the person typed on their own phone, so the inviter can see who is joining
        "joiner_name": names.unseal((red.payload or {}).get("name_enc"), f"member:{red.agent_id}") if red else None,
        "joined_at": res.time.isoformat() if res is not None and status == "joined" else None,
        "confirm_by": (red.time + CONFIRM_TTL).isoformat() if red is not None and status == "joining" else None,
    }


def my_invites(flow: FlowCore, agent_id: str) -> List[Dict[str, Any]]:
    mine = [s for s in flow.store.get_by_type(SignalTypes.INVITE_ISSUED) if s.agent_id == agent_id]
    return [_invite_view(flow, s) for s in sorted(mine, key=lambda s: s.time, reverse=True)]


def resolve_invite(flow: FlowCore, agent_id: str, invite_id: str, action: str) -> Dict[str, Any]:
    """confirm or decline the person joining with my invite, or cancel one nobody has used yet."""
    issued = _invite(flow, invite_id)
    if issued is None or issued.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="No such invite of yours")
    view = _invite_view(flow, issued)
    kinds = {"confirm": (SignalTypes.INVITE_CONFIRMED, "joining"), "decline": (SignalTypes.INVITE_DECLINED, "joining"),
             "cancel": (SignalTypes.INVITE_CANCELLED, "waiting")}
    if action not in kinds:
        raise HTTPException(status_code=400, detail="action must be confirm, decline or cancel")
    kind, needs = kinds[action]
    if view["status"] != needs:
        raise HTTPException(status_code=409, detail=f"This invite is {view['status']}")
    red = _redemption(flow, invite_id)
    _emit(flow, kind, agent_id, f"invite:{invite_id}",
          {"code_hash": invite_id, "member": red.agent_id if red is not None else None})
    return _invite_view(flow, issued)


# --------------------------------------------------------------------------------------------- provenance

def _haversine_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


def _exif_time(exif: Dict[str, Any]) -> tuple[Optional[datetime], bool]:
    """(time, zoned). EXIF DateTimeOriginal is local and naive; an offset may come separately."""
    raw = exif.get("datetime_original")
    if not isinstance(raw, str) or not raw.strip():
        return None, False
    text = raw.strip()
    m = re.match(r"^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})", text)
    if not m:
        return None, False
    naive = datetime(*map(int, m.groups()))
    offset = exif.get("offset_time")
    if isinstance(offset, str) and re.match(r"^[+-]\d{2}:\d{2}$", offset):
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6])) * sign
        return (naive - delta).replace(tzinfo=timezone.utc), True
    tz_min = exif.get("tz_offset_min")
    if isinstance(tz_min, (int, float)):
        return (naive - timedelta(minutes=tz_min)).replace(tzinfo=timezone.utc), True
    return naive.replace(tzinfo=timezone.utc), False


def zoom_check(provenance: Dict[str, Any], capture: Optional[Dict[str, Any]]) -> Optional[bool]:
    """The ClaimType's camera zoom (evidence.capture.camera_zoom), if it sets one: the app must declare that
    zoom, and the photo's EXIF DigitalZoomRatio, when present, must agree (0 or 1 means no digital zoom)."""
    want = (capture or {}).get("camera_zoom")
    if want is None:
        return None
    camera = provenance.get("camera") if isinstance(provenance.get("camera"), dict) else {}
    exif = provenance.get("exif") if isinstance(provenance.get("exif"), dict) else {}
    declared = camera.get("zoom")
    ratio = exif.get("digital_zoom")
    if isinstance(ratio, (int, float)) and ratio not in (0, 1) and abs(ratio - float(want)) > 0.01:
        return False
    if not isinstance(declared, (int, float)):
        return None if ratio is None else abs(float(ratio or 1) - float(want)) <= 0.01
    return abs(float(declared) - float(want)) <= 0.01


def provenance_checks(provenance: Dict[str, Any], reported_at: datetime, geo: Dict[str, float]) -> Dict[str, Any]:
    exif = provenance.get("exif") if isinstance(provenance.get("exif"), dict) else {}
    in_app = provenance.get("capture_source") == "camera"
    time_matches: Optional[bool] = None
    shot, zoned = _exif_time(exif)
    if shot is not None:
        delta = abs((shot - reported_at).total_seconds())
        if zoned:
            time_matches = delta <= TIME_MATCH_SECONDS
        else:   # no offset known: accept a whole quarter-hour timezone shift
            time_matches = any(abs(delta - k * 900) <= TIME_MATCH_SECONDS for k in range(0, 57))
    place_matches: Optional[bool] = None
    gps = exif.get("gps") if isinstance(exif.get("gps"), dict) else None
    if gps and isinstance(gps.get("lat"), (int, float)) and isinstance(gps.get("lon"), (int, float)) \
            and isinstance(geo, dict) and "lat" in geo and "lon" in geo:
        place_matches = _haversine_m({"lat": gps["lat"], "lon": gps["lon"]}, geo) <= PLACE_MATCH_METRES
    return {"in_app_capture": in_app, "time_matches": time_matches, "place_matches": place_matches}


def record_provenance(flow: FlowCore, *, reporter_id: str, observation: Any, truth_key: str,
                      provenance: Optional[Dict[str, Any]], device_proof: Optional[Dict[str, Any]] = None,
                      capture: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
    if not observation.evidence_refs:
        return None
    provenance = provenance if isinstance(provenance, dict) else {}
    device = provenance.get("device") if isinstance(provenance.get("device"), dict) else {}
    exif = provenance.get("exif") if isinstance(provenance.get("exif"), dict) else {}
    sha = observation.evidence_refs[0].sha256
    return _emit(flow, SignalTypes.PROVENANCE_RECORDED, reporter_id, f"evidence:{sha}", {
        "observation_id": str(observation.observation_id),
        "truthkey": truth_key,
        "claim_type_id": observation.claim_type,
        "evidence_sha256": sha,
        "exif": {k: exif.get(k) for k in ("datetime_original", "offset_time", "tz_offset_min", "gps", "digital_zoom") if k in exif},
        "capture_source": provenance.get("capture_source"),
        "camera": {k: provenance["camera"].get(k) for k in ("zoom",)} if isinstance(provenance.get("camera"), dict) else None,
        "device": {k: device.get(k) for k in ("platform", "model", "app_version") if k in device},
        "checks": {**provenance_checks(provenance, observation.reported_at, observation.geo),
                   "zoom_matches": zoom_check(provenance, capture),
                   "device_signed": bool(device_proof and device_proof.get("verified"))},
        "device_proof": device_proof or {"device_id": None, "verified": False, "reason": "unsigned"},
    })


BADGE = ("in_app_capture", "time_matches", "place_matches", "zoom_matches", "device_signed")


def provenance_badge(flow: FlowCore, sha: str) -> Dict[str, Any]:
    for signal in flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED):
        if signal.payload.get("evidence_sha256") == sha:
            checks = signal.payload.get("checks") or {}
            return {k: checks.get(k) for k in BADGE}
    return {k: None for k in BADGE}


# --------------------------------------------------------------------------------------------- questions and agreement

SKY_COVER = "earth.sky_cover.v1"
# The sky ClaimType's questions and rule, used when its YAML cannot be loaded (and by vote_for without one).
_SKY: Dict[str, Any] = {
    "id": SKY_COVER,
    "topic": "sky_cover",
    "ui_schema": {"fields": [
        {"name": "cover", "type": "select", "label": "How much of the sky is cloud?", "required": True,
         "options": list(COVER),
         "option_labels": {"clear": "None", "few": "A little", "scattered": "About half", "broken": "Most",
                           "overcast": "All"}},
        {"name": "raining", "type": "boolean", "label": "Is it raining here?", "required": True},
    ]},
    "validation": {"fields": [{"name": "cover", "agree": {"within_steps": 1}},
                              {"name": "raining", "agree": "equal"}]},
}
DEFAULT_WITHIN_PCT = 10


def _config(claim_type: Any) -> Dict[str, Any]:
    """The raw ClaimType config: a loaded ClaimType, a dict, or the sky's built-in one for None."""
    if claim_type is None:
        return _SKY
    if isinstance(claim_type, dict):
        return claim_type
    try:
        return claim_type.get_config() or {}
    except Exception:
        return {}


def _resolve(claim_types: Optional[Callable[[str], Any]], claim_type_id: Optional[str]) -> Dict[str, Any]:
    found = None
    if claim_types is not None and claim_type_id:
        try:
            found = claim_types(claim_type_id)
        except Exception:
            found = None
    if found is None:
        return _SKY if claim_type_id in (None, SKY_COVER) else {"id": claim_type_id}
    return _config(found)


def claim_type_resolver(app: Any) -> Callable[[str], Any]:
    return lambda claim_type_id: app.state.orchestrator.get_claim_type(claim_type_id)


def _ui_fields(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    fields = ((cfg.get("ui_schema") or {}).get("fields") or [])
    return {f["name"]: f for f in fields if isinstance(f, dict) and isinstance(f.get("name"), str)}


def validation_fields(claim_type: Any) -> List[Dict[str, Any]]:
    """[{name, agree}] from the ClaimType's `validation` block, or derived from its required ui_schema fields:
    select and boolean must be equal, a number within 10 percent."""
    cfg = _config(claim_type)
    ui = _ui_fields(cfg)
    declared = (cfg.get("validation") or {}).get("fields")
    if isinstance(declared, list) and declared:
        return [{"name": f["name"], "agree": f.get("agree", "equal")} for f in declared
                if isinstance(f, dict) and f.get("name") in ui]
    out = []
    for name, field in ui.items():
        if not field.get("required"):
            continue
        if field.get("type") in ("select", "boolean"):
            out.append({"name": name, "agree": "equal"})
        elif field.get("type") == "number":
            out.append({"name": name, "agree": {"within_pct": DEFAULT_WITHIN_PCT}})
    return out


def questions(claim_type: Any) -> List[Dict[str, Any]]:
    """What a validator answers: one question per validation field, from its ui_schema field."""
    ui = _ui_fields(_config(claim_type))
    out = []
    for rule in validation_fields(claim_type):
        field = ui[rule["name"]]
        q: Dict[str, Any] = {"name": rule["name"], "type": field.get("type"),
                             "label": field.get("label") or rule["name"].replace("_", " ").capitalize()}
        if field.get("type") == "select":
            q["options"] = list(field.get("options") or [])
            if isinstance(field.get("option_labels"), dict):
                q["option_labels"] = dict(field["option_labels"])
        if field.get("type") == "number":
            q.update({k: field[k] for k in ("unit", "min", "max", "step") if field.get(k) is not None})
        out.append(q)
    return out


def _title(cfg: Dict[str, Any], claim_type_id: Optional[str]) -> str:
    if isinstance(cfg.get("title"), str) and cfg["title"].strip():
        return cfg["title"].strip()
    topic = cfg.get("topic") or ((claim_type_id or "").split(".")[1] if (claim_type_id or "").count(".") >= 2 else "")
    return topic.replace("_", " ").capitalize() or (claim_type_id or "")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _agrees(question: Dict[str, Any], agree: Any, seen: Any, claimed: Any) -> bool:
    kind = question.get("type")
    rule = agree if isinstance(agree, dict) else {}
    if "within_steps" in rule:
        options = question.get("options") or []
        if seen not in options or claimed not in options:
            return False
        return abs(options.index(seen) - options.index(claimed)) <= rule["within_steps"]
    if "within" in rule or "within_pct" in rule:
        if not _is_number(seen) or not _is_number(claimed):
            return False
        allowed = float(rule["within"]) if "within" in rule else abs(float(claimed)) * float(rule["within_pct"]) / 100
        return abs(float(seen) - float(claimed)) <= allowed + 1e-9
    if kind == "boolean":
        return bool(seen) == bool(claimed)
    if kind == "number":
        return _is_number(seen) and _is_number(claimed) and float(seen) == float(claimed)
    return seen == claimed


def vote_for(values: Optional[Dict[str, Any]], observation_payload: Dict[str, Any], claim_type: Any = None) -> str:
    """RATIFY when every validation field of the validator's values agrees with the observation by its rule,
    otherwise REJECT. Sky cover: within one cover band and the same answer on rain."""
    if not values:
        return "REJECT"
    by_name = {q["name"]: q for q in questions(claim_type)}
    rules = validation_fields(claim_type)
    if not rules:
        return "REJECT"
    payload = observation_payload or {}
    for rule in rules:
        name = rule["name"]
        if name not in values or (name not in payload and by_name[name].get("type") != "boolean"):
            return "REJECT"
        if not _agrees(by_name[name], rule["agree"], values.get(name), payload.get(name)):
            return "REJECT"
    return "RATIFY"


def check_values(values: Any, claim_type: Any) -> Dict[str, Any]:
    """The validator's answers, one per question, or 400 with a plain sentence."""
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="values must be an object with one answer per question")
    out: Dict[str, Any] = {}
    for q in questions(claim_type):
        name = q["name"]
        if name not in values or values[name] is None:
            raise HTTPException(status_code=400, detail=f"Answer every question: {name} is missing")
        value = values[name]
        if q["type"] == "select":
            if value not in q.get("options", []):
                raise HTTPException(status_code=400, detail=f"{name} must be one of " + ", ".join(map(str, q.get("options", []))))
        elif q["type"] == "boolean":
            if not isinstance(value, bool):
                raise HTTPException(status_code=400, detail=f"{name} must be true or false")
        elif q["type"] == "number":
            if not _is_number(value):
                raise HTTPException(status_code=400, detail=f"{name} must be a number")
            low, high = q.get("min"), q.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                raise HTTPException(status_code=400, detail=f"{name} must be between {low} and {high}")
        out[name] = value
    if not out:
        raise HTTPException(status_code=400, detail="This claim has no questions for validators")
    return out


def parse_reading(body: Dict[str, Any], claim_type: Any) -> tuple[Optional[Dict[str, Any]], bool]:
    """(values, unusable). Body `{values: {...}}`, `{values: null, unusable: true}` when the evidence cannot be
    checked, or the older top-level answers (`{cover, raining}`)."""
    if body.get("unusable") is True:
        return None, True
    if "values" in body:
        return check_values(body.get("values"), claim_type), False
    return check_values({q["name"]: body.get(q["name"]) for q in questions(claim_type)}, claim_type), False


# --------------------------------------------------------------------------------------------- assignments

def _evidence(observation: Any) -> List[Any]:
    """An observation's evidence refs that validators can check (photo, data, audio, video), in order."""
    return [ref for ref in (observation.evidence_refs or []) if evidence_kinds.ref_kind(ref) is not None]


def _evidence_items(flow: FlowCore, observation_store: Any) -> List[Dict[str, Any]]:
    """Every observation with evidence of any kind, as (reporter, truthkey, observation, sha of its first
    evidence). The sha identifies the observation's evidence for the per-evidence reader cap."""
    out: List[Dict[str, Any]] = []
    by_key: Dict[str, List[Any]] = {}
    for signal in flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED):
        key = signal.object_id
        if key not in by_key:
            by_key[key] = observation_store.get_for_truthkey(key)
        wanted = signal.payload.get("observation_id")
        for obs in by_key[key]:
            refs = _evidence(obs) if str(obs.observation_id) == wanted else []
            if refs:
                out.append({"reporter": obs.reporter_id, "truthkey": key, "observation": obs,
                            "observation_id": wanted, "sha": refs[0].sha256,
                            "claim_type_id": obs.claim_type, "submitted": signal.time})
    return out


AI_AGENT = "ai:generalist_v1"


def ai_reader(app: Any) -> Optional[Callable[[str, bytes], dict]]:
    """The AI's reader: app.state.ai_reader if set (tests), else the generalist service's /read."""
    reader = getattr(app.state, "ai_reader", None)
    if reader is not None:
        return reader
    client = getattr(app.state, "generalist_client", None)
    if client is None:
        return None
    def read(claim_type_id: str, image: bytes) -> dict:
        try:
            timeout = generalist_timeout_seconds(app.state.orchestrator.get_claim_type(claim_type_id))
        except Exception:
            timeout = 120.0
        return client.read(claim_type_id=claim_type_id, image=image, timeout=timeout)

    return read


def ai_read(app: Any, observation: Any, truth_key: str, vote_and_compile: Callable[..., Any]) -> None:
    """
    The AI reads the photo exactly as a human validator would: the same EXIF-stripped image, without the
    reporter, place, key or the reporter's answer. Its reading becomes a vote the same way. Photos only.
    """
    reader = ai_reader(app)
    photo = next((ref for ref in (observation.evidence_refs or []) if evidence_kinds.ref_kind(ref) == "photo"), None)
    if reader is None or photo is None:
        return
    flow = app.state.flow
    sha = photo.sha256
    cfg = _resolve(claim_type_resolver(app), observation.claim_type)
    assignment = _emit(flow, SignalTypes.ASSIGNMENT_ISSUED, AI_AGENT, f"assignment:{uuid.uuid4().hex}", {
        "evidence_sha256": sha, "validator": AI_AGENT, "reason": "ai",
        "truthkey": truth_key, "observation_id": str(observation.observation_id), "claim_type_id": observation.claim_type,
    })
    result = None
    for attempt in range(2):                      # one retry: a hiccup should not lose the AI's reading
        try:
            image = strip_photo(app.state.evidence_store.read(photo))
            result = reader(observation.claim_type, image)
            break
        except Exception:
            import logging

            logging.getLogger(__name__).exception("AI reading failed for %s (attempt %d)", sha, attempt + 1)
    if result is None:
        return
    values = result.get("values") or {}
    relevance = result.get("relevance")
    is_evidence = bool(result.get("evidence", relevance is None or relevance >= 0.5))
    value = None
    if is_evidence:
        value = {q["name"]: bool(values.get(q["name"])) if q["type"] == "boolean" else values.get(q["name"])
                 for q in questions(cfg)}
    now = _now()
    _emit(flow, SignalTypes.READING_SUBMITTED, AI_AGENT, assignment.object_id, {
        "evidence_sha256": sha, "value": value, "probs": result.get("probs"), "relevance": relevance,
        "latency_ms": int((now - assignment.time).total_seconds() * 1000),
        "truthkey": truth_key, "observation_id": str(observation.observation_id),
    }, time=now)
    vote = vote_for(value, observation.payload, cfg) if value else "REJECT"
    vote_and_compile(AI_AGENT, truth_key, vote, value)


def start_ai_read(app: Any, observation: Any, truth_key: str, vote_and_compile: Callable[..., Any]) -> None:
    if getattr(app.state, "ai_sync", False):
        ai_read(app, observation, truth_key, vote_and_compile)
        return
    thread = threading.Thread(target=ai_read, args=(app, observation, truth_key, vote_and_compile),
                              name="kaori-ai-read", daemon=True)
    thread.start()


def _assignments(flow: FlowCore) -> Dict[str, Signal]:
    return {s.object_id: s for s in flow.store.get_by_type(SignalTypes.ASSIGNMENT_ISSUED)}


def _readings(flow: FlowCore) -> Dict[str, Signal]:
    return {s.object_id: s for s in flow.store.get_by_type(SignalTypes.READING_SUBMITTED)}


def _observation(observation_store: Any, signal: Signal) -> Optional[Any]:
    for obs in observation_store.get_for_truthkey(signal.payload["truthkey"]):
        if str(obs.observation_id) == signal.payload["observation_id"]:
            return obs
    return None


def _public_assignment(flow: FlowCore, observation_store: Any, signal: Signal,
                       claim_types: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """What a validator receives: the evidence and the questions. Never the reporter, place, time, key or the
    reporter's answer."""
    assignment_id = signal.object_id.split(":", 1)[1]
    claim_type_id = signal.payload.get("claim_type_id")
    cfg = _resolve(claim_types, claim_type_id)
    obs = _observation(observation_store, signal)
    refs = _evidence(obs) if obs is not None else []
    evidence = [{"kind": evidence_kinds.ref_kind(ref),
                 "mime": evidence_kinds.normalize_mime(ref.mime_type) or "image/jpeg",
                 "url": f"/v1/assignments/{assignment_id}/evidence/{i}"} for i, ref in enumerate(refs)]
    asked = questions(cfg)
    return {
        "assignment_id": assignment_id,
        "claim_type_id": claim_type_id,
        "title": _title(cfg, claim_type_id),
        "provenance_badge": provenance_badge(flow, signal.payload["evidence_sha256"]),
        "expires_at": (signal.time + ASSIGNMENT_TTL).isoformat(),
        "evidence": evidence,
        "questions": asked,
        # kept for older app builds: the first photo, and the answer options of select and boolean questions
        "image_url": f"/v1/assignments/{assignment_id}/image" if any(e["kind"] == "photo" for e in evidence) else None,
        "options": {q["name"]: list(q["options"]) if q["type"] == "select" else [True, False]
                    for q in asked if q["type"] in ("select", "boolean")},
    }


def assign(flow: FlowCore, observation_store: Any, agent_id: str, limit: int, rng: Any = None,
           claim_types: Optional[Callable[[str], Any]] = None) -> List[Dict[str, Any]]:
    require_member(flow, agent_id)
    limit = max(1, min(MAX_ASSIGNMENTS, int(limit)))
    rng = rng or secrets.SystemRandom()
    now = _now()
    issued = _assignments(flow)
    answered = _readings(flow)
    mine_open = [s for oid, s in issued.items() if s.agent_id == agent_id and oid not in answered
                 and s.time + ASSIGNMENT_TTL > now]
    result = [_public_assignment(flow, observation_store, s, claim_types) for s in mine_open[:limit]]
    if len(result) >= limit:
        return result

    my_keys = {s.object_id for s in flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED) if s.agent_id == agent_id}
    seen = {s.payload.get("evidence_sha256") for s in issued.values() if s.agent_id == agent_id}
    load: Dict[str, int] = {}
    for oid, s in issued.items():
        if s.agent_id == AI_AGENT:
            continue                                    # the AI reads every photo; it takes no human slot
        live = oid in answered or s.time + ASSIGNMENT_TTL > now
        if live:
            load[s.payload.get("evidence_sha256")] = load.get(s.payload.get("evidence_sha256"), 0) + 1
    candidates = [p for p in _evidence_items(flow, observation_store)
                  if p["reporter"] != agent_id and p["truthkey"] not in my_keys and p["sha"] not in seen
                  and load.get(p["sha"], 0) < READINGS_PER_EVIDENCE]
    rng.shuffle(candidates)
    for item in candidates[: limit - len(result)]:
        assignment_id = uuid.uuid4().hex
        signal = _emit(flow, SignalTypes.ASSIGNMENT_ISSUED, agent_id, f"assignment:{assignment_id}", {
            "evidence_sha256": item["sha"], "validator": agent_id, "reason": "random",
            "truthkey": item["truthkey"], "observation_id": item["observation_id"],
            "claim_type_id": item["claim_type_id"],
        })
        result.append(_public_assignment(flow, observation_store, signal, claim_types))
    return result


def _own_assignment(flow: FlowCore, agent_id: str, assignment_id: str) -> Signal:
    if not re.fullmatch(r"[0-9a-f]{32}", assignment_id or ""):
        raise HTTPException(status_code=404, detail="Unknown assignment")
    signal = _assignments(flow).get(f"assignment:{assignment_id}")
    if signal is None or signal.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Unknown assignment")
    return signal


def assignment_evidence(flow: FlowCore, observation_store: Any, evidence_store: Any, agent_id: str,
                        assignment_id: str, index: int) -> tuple[bytes, str]:
    """(bytes, content type) of one piece of an assignment's evidence, for its validator only, with anything
    that reveals place, time or person removed."""
    signal = _own_assignment(flow, agent_id, assignment_id)
    obs = _observation(observation_store, signal)
    refs = _evidence(obs) if obs is not None else []
    if not 0 <= index < len(refs):
        raise HTTPException(status_code=404, detail="Evidence not found")
    ref = refs[index]
    kind = evidence_kinds.ref_kind(ref)
    try:
        return evidence_kinds.prepare(evidence_store.read(ref), kind, ref.mime_type)
    except evidence_kinds.EvidenceNotReadable as exc:
        raise HTTPException(status_code=415, detail=f"This evidence could not be prepared for checking: {exc}") from exc


def assignment_image(flow: FlowCore, observation_store: Any, evidence_store: Any, agent_id: str, assignment_id: str) -> bytes:
    """The assignment's first photo (older app builds)."""
    signal = _own_assignment(flow, agent_id, assignment_id)
    obs = _observation(observation_store, signal)
    if obs is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    photo = next((ref for ref in _evidence(obs) if evidence_kinds.ref_kind(ref) == "photo"), None)
    if photo is None:
        raise HTTPException(status_code=404, detail="This assignment has no photo")
    try:
        return strip_photo(evidence_store.read(photo))
    except Exception as exc:
        raise HTTPException(status_code=415, detail="Evidence is not a readable image") from exc


def submit_reading(flow: FlowCore, observation_store: Any, agent_id: str, assignment_id: str,
                   body: Dict[str, Any], vote_and_compile: Callable[..., Any],
                   claim_types: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    from kaori_api.devices import require_device

    require_device(flow, agent_id)
    signal = _own_assignment(flow, agent_id, assignment_id)
    if f"assignment:{assignment_id}" in _readings(flow):
        raise HTTPException(status_code=409, detail="Already answered")
    if signal.time + ASSIGNMENT_TTL <= _now():
        raise HTTPException(status_code=410, detail="Assignment expired")
    cfg = _resolve(claim_types, signal.payload.get("claim_type_id"))
    values, unusable = parse_reading(body, cfg)
    now = _now()
    payload = {
        "evidence_sha256": signal.payload["evidence_sha256"], "value": values,
        "latency_ms": int((now - signal.time).total_seconds() * 1000),
        "truthkey": signal.payload["truthkey"], "observation_id": signal.payload["observation_id"],
    }
    if unusable:
        payload["unusable"] = True
    _emit(flow, SignalTypes.READING_SUBMITTED, agent_id, signal.object_id, payload, time=now)
    obs = _observation(observation_store, signal)
    vote = "REJECT" if unusable else vote_for(values, obs.payload if obs is not None else {}, cfg)
    vote_and_compile(agent_id, signal.payload["truthkey"], vote, values)
    return {"ok": True}


# --------------------------------------------------------------------------------------------- export

def export_lines(flow: FlowCore, truth_store: Any) -> Iterable[str]:
    keys: List[str] = []
    for signal in sorted(flow.store.get_all(), key=lambda s: s.time):
        yield json.dumps({"kind": "signal", **signal.model_dump(mode="json")}, sort_keys=True) + "\n"
        if signal.signal_type in (SignalTypes.TRUTHSTATE_EMITTED, SignalTypes.OBSERVATION_SUBMITTED) \
                and signal.object_id not in keys:
            keys.append(signal.object_id)
    for key in keys:
        artifact = truth_store.get(key)
        if artifact is not None:
            yield json.dumps({"kind": "truthstate", "truthkey": key, "artifact": artifact}, sort_keys=True, default=str) + "\n"


def check_export_token(request: Request) -> None:
    token = os.environ.get("KAORI_EXPORT_TOKEN", "")
    given = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    if not token or not secrets.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=403, detail="Export requires the admin token")


# --------------------------------------------------------------------------------------------- routes

def add_routes(app: Any, require_agent: Callable, vote_and_compile: Callable[..., Any]) -> None:
    from fastapi import Depends

    lock = threading.Lock()

    async def _json(request: Request) -> Dict[str, Any]:
        try:
            raw = await request.json()
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    @app.post("/v1/invites")
    async def create_invite(request: Request, agent_id: str = Depends(require_agent)):
        body = await _json(request)
        callsign = body.get("callsign") if isinstance(body.get("callsign"), str) else None
        with lock:
            return issue_invite(app.state.flow, agent_id, callsign=(callsign or "")[:40] or None, body=body)

    @app.get("/v1/invites/mine")
    def list_my_invites(agent_id: str = Depends(require_agent)):
        return my_invites(app.state.flow, agent_id)

    @app.get("/v1/invites/{code}")
    def check_invite(code: str):
        return invite_status(app.state.flow, code)

    @app.post("/v1/invites/{invite_id}/{action}")
    def resolve(invite_id: str, action: str, agent_id: str = Depends(require_agent)):
        with lock:
            return resolve_invite(app.state.flow, agent_id, invite_id, action)

    @app.post("/v1/invites/redeem")
    async def redeem(request: Request, agent_id: str = Depends(require_agent)):
        body = await _json(request)
        with lock:
            return redeem_invite(app.state.flow, agent_id, body)

    @app.get("/v1/assignments")
    def assignments(limit: int = 5, agent_id: str = Depends(require_agent)):
        with lock:
            return assign(app.state.flow, app.state.observation_store, agent_id, limit,
                          claim_types=claim_type_resolver(app))

    @app.get("/v1/assignments/{assignment_id}/evidence/{index}")
    def evidence(assignment_id: str, index: int, agent_id: str = Depends(require_agent)):
        data, mime = assignment_evidence(app.state.flow, app.state.observation_store, app.state.evidence_store,
                                         agent_id, assignment_id, index)
        return Response(content=data, media_type=mime, headers={"Cache-Control": "private, no-store"})

    @app.get("/v1/assignments/{assignment_id}/image")
    def image(assignment_id: str, agent_id: str = Depends(require_agent)):
        data = assignment_image(app.state.flow, app.state.observation_store, app.state.evidence_store,
                                agent_id, assignment_id)
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @app.post("/v1/assignments/{assignment_id}/reading")
    async def reading(assignment_id: str, request: Request, agent_id: str = Depends(require_agent)):
        body = await _json(request)
        with lock:
            return submit_reading(app.state.flow, app.state.observation_store, agent_id, assignment_id, body,
                                  lambda a, k, v, r=None: vote_and_compile(app, a, k, v, r),
                                  claim_types=claim_type_resolver(app))

    @app.get("/v1/me")
    def whoami(agent_id: str = Depends(require_agent)):
        return devices.me(app.state.flow, agent_id)

    @app.post("/v1/devices/challenge")
    def device_challenge(agent_id: str = Depends(require_agent)):
        require_member(app.state.flow, agent_id)
        return {"challenge": devices.new_challenge(agent_id), "package": devices.policy().package,
                "expires_in": devices.CHALLENGE_TTL_SECONDS}

    @app.post("/v1/devices/link")
    async def device_link(request: Request, agent_id: str = Depends(require_agent)):
        body = await _json(request)
        require_member(app.state.flow, agent_id)
        with lock:
            return devices.link(app.state.flow, agent_id, body)

    @app.get("/v1/export")
    def export(request: Request):
        check_export_token(request)
        return StreamingResponse(export_lines(app.state.flow, app.state.truth_store),
                                 media_type="application/x-ndjson")


# --------------------------------------------------------------------------------------------- admin script

def main(argv: List[str]) -> int:
    """python -m kaori_api.antalya seed <agent_id> [callsign]  (uses DATABASE_URL like the API)"""
    if len(argv) < 2 or argv[0] != "seed":
        print(main.__doc__)
        return 2
    # the ledger only: importing kaori_api.app would build the whole API (bucket, auth)
    from kaori_db import PostgresSignalStore
    from kaori_db.store import require_kaori_schema

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required")
        return 2
    signal_store = PostgresSignalStore(url)
    require_kaori_schema(signal_store.engine)
    flow = FlowCore(store=signal_store)
    signal = seed_member(flow, argv[1], argv[2] if len(argv) > 2 else None)
    print(f"seeded {argv[1]} ({signal.signal_id[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
