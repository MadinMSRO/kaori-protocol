"""
Antalya MVP (IAC 2026): referral-only membership, provenance, blind readings and export.

Every event here is an immutable Signal (Rule 1). Invites, redemptions, provenance, assignments and readings are
derived from the signal log, so the test needs no new tables:

  INVITE_ISSUED        a member creates an invite              agent = referrer,  object = invite:<code hash>
  REFERRAL_REDEEMED    an invitee (or a seed) becomes a member  agent = new member, object = invite:<code hash>
  PROVENANCE_RECORDED  an observation's evidence is accepted    agent = reporter,  object = evidence:<sha256>
  ASSIGNMENT_ISSUED    a photo is assigned to a validator       agent = validator, object = assignment:<id>
  READING_SUBMITTED    a validator renders the photo            agent = validator, object = assignment:<id>

Blindness: an assignment never carries the reporter, the place, the TruthKey, the reporter's eye answer or other
readings, and the image is re-encoded without its EXIF before a validator sees it. A validator is never assigned
their own photo, nor a photo from a key they reported at.

Readings feed the proven compile path through an adapter (plan §3.4): RATIFY when the reading is within one band
of that observation's eye value and agrees on rain, otherwise REJECT. The readings themselves stay in the log for
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

from kaori_api import devices
from kaori_api.generalist_client import generalist_timeout_seconds

INVITE_TTL = timedelta(days=7)
ASSIGNMENT_TTL = timedelta(minutes=30)
READINGS_PER_PHOTO = 3
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

def is_member(flow: FlowCore, agent_id: str) -> bool:
    return any(s.agent_id == agent_id for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED))


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
    if _redemption(flow, chash) is not None:
        return {"valid": False, "reason": "used"}
    if expires_at is None or expires_at <= _now():
        return {"valid": False, "reason": "expired"}
    return {
        "valid": True,
        "referrer_callsign": issued.payload.get("callsign"),
        "expires_at": expires_at.isoformat(),
    }


def issue_invite(flow: FlowCore, agent_id: str, callsign: Optional[str] = None) -> Dict[str, Any]:
    require_member(flow, agent_id)
    code = new_code()
    chash = code_hash(code)
    expires_at = _now() + INVITE_TTL
    _emit(flow, SignalTypes.INVITE_ISSUED, agent_id, f"invite:{chash}",
          {"code_hash": chash, "expires_at": expires_at.isoformat(), "callsign": callsign})
    return {"code": code, "expires_at": expires_at.isoformat(), "qr_payload": f"liminal://join?code={code}"}


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
    status = invite_status(flow, code)
    if not status["valid"]:
        raise HTTPException(status_code=410 if status["reason"] in ("used", "expired") else 404,
                            detail=f"Invite {status['reason']}")
    chash = code_hash(code)
    issued = _invite(flow, chash)
    referrer = issued.agent_id
    if referrer == agent_id:
        raise HTTPException(status_code=400, detail="You cannot redeem your own invite")
    device_hash = _sha("device:" + device_id.strip())
    for signal in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED):
        if signal.payload.get("device_id_hash") == device_hash:
            raise HTTPException(status_code=409, detail="This device already joined")
    ensure_agent_registered(flow, agent_id, role="observer")
    _emit(flow, SignalTypes.REFERRAL_REDEEMED, agent_id, f"invite:{chash}",
          {"referrer": referrer, "relationship": relationship, "known_for": known_for,
           "device_id_hash": device_hash, "code_hash": chash})
    return {"agent_id": agent_id, "referrer": referrer}


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
                      provenance: Optional[Dict[str, Any]], device_proof: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
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
        "exif": {k: exif.get(k) for k in ("datetime_original", "offset_time", "tz_offset_min", "gps") if k in exif},
        "capture_source": provenance.get("capture_source"),
        "device": {k: device.get(k) for k in ("platform", "model", "app_version") if k in device},
        "checks": {**provenance_checks(provenance, observation.reported_at, observation.geo),
                   "device_signed": bool(device_proof and device_proof.get("verified"))},
        "device_proof": device_proof or {"device_id": None, "verified": False, "reason": "unsigned"},
    })


def provenance_badge(flow: FlowCore, sha: str) -> Dict[str, Any]:
    for signal in flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED):
        if signal.payload.get("evidence_sha256") == sha:
            checks = signal.payload.get("checks") or {}
            return {k: checks.get(k) for k in ("in_app_capture", "time_matches", "place_matches", "device_signed")}
    return {"in_app_capture": None, "time_matches": None, "place_matches": None, "device_signed": None}


# --------------------------------------------------------------------------------------------- assignments

def _photos(flow: FlowCore, observation_store: Any) -> List[Dict[str, Any]]:
    """Every observation with evidence, as (reporter, truthkey, observation, sha, eye value)."""
    out: List[Dict[str, Any]] = []
    by_key: Dict[str, List[Any]] = {}
    for signal in flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED):
        key = signal.object_id
        if key not in by_key:
            by_key[key] = observation_store.get_for_truthkey(key)
        wanted = signal.payload.get("observation_id")
        for obs in by_key[key]:
            if str(obs.observation_id) == wanted and obs.evidence_refs:
                out.append({"reporter": obs.reporter_id, "truthkey": key, "observation": obs,
                            "observation_id": wanted, "sha": obs.evidence_refs[0].sha256,
                            "claim_type_id": obs.claim_type, "submitted": signal.time})
    return out


AI_AGENT = "ai:generalist_v1"


def ai_reader(app: Any) -> Optional[Callable[[str, bytes], dict]]:
    """The AI's blind reader: app.state.ai_reader if set (tests), else the generalist service's /read."""
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
    The AI reads the photo blind, exactly as a human validator would: the same EXIF-stripped image, no
    reporter, place, key or eye answer. Its reading becomes a vote the same way.
    """
    reader = ai_reader(app)
    if reader is None or not observation.evidence_refs:
        return
    flow = app.state.flow
    sha = observation.evidence_refs[0].sha256
    assignment = _emit(flow, SignalTypes.ASSIGNMENT_ISSUED, AI_AGENT, f"assignment:{uuid.uuid4().hex}", {
        "evidence_sha256": sha, "validator": AI_AGENT, "reason": "ai",
        "truthkey": truth_key, "observation_id": str(observation.observation_id), "claim_type_id": observation.claim_type,
    })
    result = None
    for attempt in range(2):                      # one retry: a hiccup should not lose the AI's reading
        try:
            image = blind_image(app.state.evidence_store.read(observation.evidence_refs[0]))
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
    value = {"cover": values.get("cover"), "raining": bool(values.get("raining"))} if is_evidence else None
    now = _now()
    _emit(flow, SignalTypes.READING_SUBMITTED, AI_AGENT, assignment.object_id, {
        "evidence_sha256": sha, "value": value, "probs": result.get("probs"), "relevance": relevance,
        "latency_ms": int((now - assignment.time).total_seconds() * 1000),
        "truthkey": truth_key, "observation_id": str(observation.observation_id),
    }, time=now)
    vote = vote_for(value, observation.payload) if value and value.get("cover") in COVER else "REJECT"
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


def _public_assignment(flow: FlowCore, signal: Signal) -> Dict[str, Any]:
    assignment_id = signal.object_id.split(":", 1)[1]
    return {
        "assignment_id": assignment_id,
        "image_url": f"/v1/assignments/{assignment_id}/image",
        "provenance_badge": provenance_badge(flow, signal.payload["evidence_sha256"]),
        "claim_type_id": signal.payload.get("claim_type_id"),
        "options": {"cover": list(COVER), "raining": [True, False]},
        "expires_at": (signal.time + ASSIGNMENT_TTL).isoformat(),
    }


def assign(flow: FlowCore, observation_store: Any, agent_id: str, limit: int, rng: Any = None) -> List[Dict[str, Any]]:
    require_member(flow, agent_id)
    limit = max(1, min(MAX_ASSIGNMENTS, int(limit)))
    rng = rng or secrets.SystemRandom()
    now = _now()
    issued = _assignments(flow)
    answered = _readings(flow)
    mine_open = [s for oid, s in issued.items() if s.agent_id == agent_id and oid not in answered
                 and s.time + ASSIGNMENT_TTL > now]
    result = [_public_assignment(flow, s) for s in mine_open[:limit]]
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
    candidates = [p for p in _photos(flow, observation_store)
                  if p["reporter"] != agent_id and p["truthkey"] not in my_keys and p["sha"] not in seen
                  and load.get(p["sha"], 0) < READINGS_PER_PHOTO]
    rng.shuffle(candidates)
    for photo in candidates[: limit - len(result)]:
        assignment_id = uuid.uuid4().hex
        signal = _emit(flow, SignalTypes.ASSIGNMENT_ISSUED, agent_id, f"assignment:{assignment_id}", {
            "evidence_sha256": photo["sha"], "validator": agent_id, "reason": "random",
            "truthkey": photo["truthkey"], "observation_id": photo["observation_id"],
            "claim_type_id": photo["claim_type_id"],
        })
        result.append(_public_assignment(flow, signal))
    return result


def _own_assignment(flow: FlowCore, agent_id: str, assignment_id: str) -> Signal:
    if not re.fullmatch(r"[0-9a-f]{32}", assignment_id or ""):
        raise HTTPException(status_code=404, detail="Unknown assignment")
    signal = _assignments(flow).get(f"assignment:{assignment_id}")
    if signal is None or signal.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Unknown assignment")
    return signal


def blind_image(raw: bytes) -> bytes:
    """Re-encode without metadata (EXIF GPS and time would reveal the place)."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1600, 1600))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def assignment_image(flow: FlowCore, observation_store: Any, evidence_store: Any, agent_id: str, assignment_id: str) -> bytes:
    signal = _own_assignment(flow, agent_id, assignment_id)
    observations = observation_store.get_for_truthkey(signal.payload["truthkey"])
    for obs in observations:
        if str(obs.observation_id) == signal.payload["observation_id"]:
            raw = evidence_store.read(obs.evidence_refs[0])
            try:
                return blind_image(raw)
            except Exception as exc:
                raise HTTPException(status_code=415, detail="Evidence is not a readable image") from exc
    raise HTTPException(status_code=404, detail="Evidence not found")


def vote_for(reading: Dict[str, Any], eye: Dict[str, Any]) -> str:
    """Plan §3.4: RATIFY when within one cover band of the observation's eye value and agreeing on rain."""
    try:
        close = abs(COVER.index(reading["cover"]) - COVER.index(eye.get("cover"))) <= 1
    except ValueError:
        close = False
    return "RATIFY" if close and bool(reading["raining"]) == bool(eye.get("raining")) else "REJECT"


def submit_reading(flow: FlowCore, observation_store: Any, agent_id: str, assignment_id: str,
                   body: Dict[str, Any], vote_and_compile: Callable[[str, str, str], Any]) -> Dict[str, Any]:
    from kaori_api.devices import require_device

    require_device(flow, agent_id)
    signal = _own_assignment(flow, agent_id, assignment_id)
    if f"assignment:{assignment_id}" in _readings(flow):
        raise HTTPException(status_code=409, detail="Already answered")
    if signal.time + ASSIGNMENT_TTL <= _now():
        raise HTTPException(status_code=410, detail="Assignment expired")
    cover = body.get("cover")
    raining = body.get("raining")
    if cover not in COVER:
        raise HTTPException(status_code=400, detail="cover must be one of " + ", ".join(COVER))
    if not isinstance(raining, bool):
        raise HTTPException(status_code=400, detail="raining must be true or false")
    now = _now()
    _emit(flow, SignalTypes.READING_SUBMITTED, agent_id, signal.object_id, {
        "evidence_sha256": signal.payload["evidence_sha256"], "value": {"cover": cover, "raining": raining},
        "latency_ms": int((now - signal.time).total_seconds() * 1000),
        "truthkey": signal.payload["truthkey"], "observation_id": signal.payload["observation_id"],
    }, time=now)
    eye = {}
    for obs in observation_store.get_for_truthkey(signal.payload["truthkey"]):
        if str(obs.observation_id) == signal.payload["observation_id"]:
            eye = obs.payload
    vote = vote_for({"cover": cover, "raining": raining}, eye)
    vote_and_compile(agent_id, signal.payload["truthkey"], vote, {"cover": cover, "raining": raining})
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
            return issue_invite(app.state.flow, agent_id, callsign=(callsign or "")[:40] or None)

    @app.get("/v1/invites/{code}")
    def check_invite(code: str):
        return invite_status(app.state.flow, code)

    @app.post("/v1/invites/redeem")
    async def redeem(request: Request, agent_id: str = Depends(require_agent)):
        body = await _json(request)
        with lock:
            return redeem_invite(app.state.flow, agent_id, body)

    @app.get("/v1/assignments")
    def assignments(limit: int = 5, agent_id: str = Depends(require_agent)):
        with lock:
            return assign(app.state.flow, app.state.observation_store, agent_id, limit)

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
                                  lambda a, k, v, r=None: vote_and_compile(app, a, k, v, r))

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
