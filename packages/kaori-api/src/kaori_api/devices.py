"""
Linking a phone (Antalya): the phone becomes its own agent, vouched for by its secure hardware.

1. The app asks for a challenge (bound to the signed-in person, ten minutes, single use).
2. The phone makes a signing key for that challenge in its secure hardware:
   - Android: the Keystore returns the key's attestation chain (attestation.py);
   - iPhone: App Attest returns a keyId and an attestationObject, made with clientDataHash =
     SHA256(challenge as UTF-8) (app_attest.py).
3. Kaori checks it. If the policy holds, DEVICE_LINKED records the phone as `sensor:android-…` or
   `sensor:ios-…` with its public key; a person has one linked phone, and linking a new one unlinks
   the old (DEVICE_UNLINKED). A refusal is a signal too (DEVICE_LINK_REFUSED), with its reasons.
4. Each report is then signed by the phone at capture time (device_proof), and Kaori checks the
   signature against the linked key and the signed fields against the report. An iPhone signs with an
   App Attest assertion over the same text (clientDataHash = SHA256(text)), whose counter is never accepted
   twice (queued reports may arrive out of order).

The two platforms are equal from here on: a verified iPhone counts exactly as a verified Android phone
(device required, device_signed), and an iPhone that cannot be verified is refused where Android is.

Policy, from the environment:
  KAORI_ANDROID_PACKAGE        the app (default mv.msro.liminal)
  KAORI_ANDROID_CERT_SHA256    MSRO's app signing certificate(s), comma-separated (deploy.sh signing)
  KAORI_APPLE_APP_ID           "<TEAM_ID>.<bundle id>", e.g. ABCDE12345.mv.msro.liminal; unset, iPhones
                               cannot be linked
  KAORI_APPLE_ALLOW_DEVELOP=1  also accept App Attest keys from development builds (Xcode, not TestFlight
                               or the App Store)
  KAORI_REQUIRE_DEVICE=1       reports and readings need a linked phone
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from kaori_flow import FlowCore
from kaori_flow.primitives.signal import Signal, SignalTypes

from kaori_api import app_attest, attestation

PLATFORMS = ("android", "ios")
CHALLENGE_TTL_SECONDS = 600
_CHALLENGE_KEY = secrets.token_bytes(32)      # per process: a restart only means asking again
_used: Dict[str, float] = {}
_used_lock = threading.Lock()
TRUST = attestation.TrustData()
APPLE_ROOTS = None                            # None: Apple's App Attestation root, bundled (tests set their own)


def policy() -> attestation.Policy:
    certs = [c.strip() for c in os.environ.get("KAORI_ANDROID_CERT_SHA256", "").split(",") if c.strip()]
    return attestation.Policy(
        package=os.environ.get("KAORI_ANDROID_PACKAGE", "mv.msro.liminal"),
        cert_sha256=certs,
        require_hardware=os.environ.get("KAORI_DEVICE_ALLOW_SOFTWARE") != "1",
        require_verified_boot=os.environ.get("KAORI_DEVICE_ALLOW_UNLOCKED") != "1",
    )


def apple_policy() -> app_attest.Policy:
    return app_attest.Policy(app_id=os.environ.get("KAORI_APPLE_APP_ID", "").strip(),
                             allow_develop=os.environ.get("KAORI_APPLE_ALLOW_DEVELOP") == "1")


def required() -> bool:
    return os.environ.get("KAORI_REQUIRE_DEVICE") == "1"


# ---------------------------------------------------------------------------------------- challenges

def _mac(agent_id: str, ts: int, nonce: str) -> str:
    return hmac.new(_CHALLENGE_KEY, f"{agent_id}|{ts}|{nonce}".encode(), hashlib.sha256).hexdigest()[:32]


def new_challenge(agent_id: str, now: Optional[float] = None) -> str:
    ts, nonce = int(now if now is not None else time.time()), secrets.token_hex(8)
    return f"{ts}.{nonce}.{_mac(agent_id, ts, nonce)}"


def take_challenge(agent_id: str, challenge: str, now: Optional[float] = None) -> bytes:
    """The challenge's bytes (what the key was made for), once; HTTP 400 if it is not ours, stale or used."""
    now = now if now is not None else time.time()
    try:
        ts_text, nonce, mac = challenge.split(".")
        ts = int(ts_text)
    except (AttributeError, ValueError):
        raise HTTPException(status_code=400, detail="Bad challenge")
    if not hmac.compare_digest(mac, _mac(agent_id, ts, nonce)) or not 0 <= now - ts <= CHALLENGE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="Challenge expired or not issued to you; ask for a new one")
    with _used_lock:
        for k in [k for k, t in _used.items() if now - t > CHALLENGE_TTL_SECONDS]:
            del _used[k]
        if challenge in _used:
            raise HTTPException(status_code=400, detail="Challenge already used; ask for a new one")
        _used[challenge] = now
    return challenge.encode()


# ------------------------------------------------------------------------------------------- linking

def _b64(text: str) -> bytes:
    """Base64, standard or URL-safe, padded or not (what Swift's Data.base64EncodedString and others send)."""
    t = text.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(t + "=" * (-len(t) % 4), validate=True)


def _emit(flow: FlowCore, signal_type: str, agent_id: str, object_id: str, payload: dict) -> Signal:
    from kaori_api.antalya import _emit as emit
    return emit(flow, signal_type, agent_id, object_id, payload)


def linked_devices(flow: FlowCore) -> Dict[str, Signal]:
    """device id -> its DEVICE_LINKED signal, for devices not since unlinked."""
    active: Dict[str, Signal] = {}
    events = sorted(flow.store.get_by_type(SignalTypes.DEVICE_LINKED) + flow.store.get_by_type(SignalTypes.DEVICE_UNLINKED),
                    key=lambda s: s.time)
    for s in events:
        if s.signal_type == SignalTypes.DEVICE_LINKED:
            active[s.object_id] = s
        else:
            active.pop(s.object_id, None)
    return active


def active_device(flow: FlowCore, agent_id: str) -> Optional[Signal]:
    mine = [s for s in linked_devices(flow).values() if s.agent_id == agent_id]
    return max(mine, key=lambda s: s.time) if mine else None


def link(flow: FlowCore, agent_id: str, body: Dict[str, Any], trust: Optional[attestation.TrustData] = None,
         now: Optional[float] = None) -> Dict[str, Any]:
    """POST /v1/devices/link: Android sends {challenge, chain}; an iPhone {platform: "ios", challenge, keyId,
    attestationObject}. Either way the phone is linked, or refused with its reasons, in the same shape."""
    from kaori_api.validation import ensure_agent_registered

    platform = body.get("platform", "android")
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail='platform must be "android" or "ios"')
    if platform == "ios":
        key_id_b64 = body.get("keyId", body.get("key_id"))
        object_b64 = body.get("attestationObject", body.get("attestation_object"))
        if not isinstance(key_id_b64, str) or not isinstance(object_b64, str):
            raise HTTPException(status_code=400, detail="keyId and attestationObject must be base64")
        challenge = take_challenge(agent_id, body.get("challenge"), now)
        try:
            key_id, attestation_object = _b64(key_id_b64), _b64(object_b64)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="keyId and attestationObject must be base64")
    else:
        chain_b64 = body.get("chain")
        if not isinstance(chain_b64, list) or not chain_b64 or not all(isinstance(c, str) for c in chain_b64):
            raise HTTPException(status_code=400, detail="chain must be the attestation certificates, base64, leaf first")
        challenge = take_challenge(agent_id, body.get("challenge"), now)
        try:
            chain = [base64.b64decode(c, validate=True) for c in chain_b64]
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="chain must be base64")

    def refuse(reasons: List[str], facts: Optional[Dict[str, Any]] = None) -> None:
        _emit(flow, SignalTypes.DEVICE_LINK_REFUSED, agent_id, (facts or {}).get("device_key_id") or "device:unknown",
              {"reasons": reasons, "platform": platform, **(facts or {})})
        raise HTTPException(status_code=403, detail={"message": "This phone cannot be linked", "reasons": reasons})

    if platform == "ios":
        apple = apple_policy()
        try:
            att = app_attest.verify_attestation(attestation_object, key_id, challenge, apple, APPLE_ROOTS,
                                                None if now is None else datetime.fromtimestamp(now, timezone.utc))
        except app_attest.AppAttestError as exc:
            refuse([str(exc)])
        summary = att.summary()
        stored = {"key_id": base64.b64encode(att.key_id).decode(), "app_id": att.app_id, "counter": att.counter}
    else:
        try:
            att = attestation.verify_chain(chain, challenge, policy(), trust or TRUST)
        except attestation.AttestationError as exc:
            refuse([str(exc)])
        if att.problems:
            refuse(att.problems, att.summary())
        summary = {**att.summary(), "platform": "android"}
        stored = {}

    device_id = att.device_key_id
    current = linked_devices(flow).get(device_id)
    if current is not None and current.agent_id != agent_id:
        refuse(["this phone's key is linked to someone else"], summary)
    previous = active_device(flow, agent_id)
    if previous is not None and previous.object_id != device_id:
        _emit(flow, SignalTypes.DEVICE_UNLINKED, agent_id, previous.object_id, {"reason": "replaced", "by": device_id})
    ensure_agent_registered(flow, device_id, role="observer", agent_type="sensor")
    if current is None:
        _emit(flow, SignalTypes.DEVICE_LINKED, agent_id, device_id, {
            "public_key_spki": base64.b64encode(att.public_key_spki).decode(), **summary, **stored,
        })
    return {"device_id": device_id, **summary}


def me(flow: FlowCore, agent_id: str) -> Dict[str, Any]:
    from kaori_api.antalya import join_state

    device = active_device(flow, agent_id)
    return {
        "agent_id": agent_id,
        **join_state(flow, agent_id),
        "device": None if device is None else {
            "device_id": device.object_id,
            "linked_at": device.time.isoformat(),
            "platform": device.payload.get("platform", "android"),
            **{k: device.payload.get(k) for k in ("security_level", "verified_boot_state", "os_patch_level")},
        },
        "device_required": required(),
    }


def require_device(flow: FlowCore, agent_id: str) -> None:
    if required() and active_device(flow, agent_id) is None:
        raise HTTPException(status_code=403, detail="Link this phone first")


# ---------------------------------------------------------------------------------- signed reports

_counters: Dict[str, set] = {}          # device id -> App Attest counters accepted by this process
_counter_lock = threading.Lock()


def _ledger_counters(flow: FlowCore, device_id: str) -> set:
    """The App Attest counters the ledger holds for this phone (the reports and NFC holds it signed)."""
    seen = set()
    for s in flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED):
        p = (s.payload or {}).get("device_proof") or {}
        if p.get("device_id") == device_id and isinstance(p.get("counter"), int):
            seen.add(p["counter"])
    for s in flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED):
        p = s.payload or {}
        if p.get("device_id") == device_id and isinstance(p.get("device_counter"), int):
            seen.add(p["device_counter"])
    return seen


def verify_signed(flow: FlowCore, linked: Signal, message: bytes, proof: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    (verified, reason, counter): did the linked phone sign `message`? Android sends `signature` (ECDSA over
    the message); an iPhone sends `assertion` (App Attest, CBOR, base64). An assertion's counter must never
    have been accepted for that key before (app_attest.counter_problem: reports queued offline may come out of
    order, an exact replay never counts); it is then remembered here and recorded by the caller in the
    ledger, so it survives a restart and other instances see it. The platform is the linked phone's, not
    whatever the proof says.
    """
    if linked.payload.get("platform", "android") != "ios":
        signature = proof.get("signature")
        if not isinstance(signature, str):
            return False, "malformed proof", None
        try:
            spki = base64.b64decode(linked.payload["public_key_spki"])
            sig = base64.b64decode(signature, validate=True)
        except (KeyError, binascii.Error, ValueError):
            return False, "malformed proof", None
        return (True, None, None) if attestation.verify_signature(spki, message, sig) else (False, "bad signature", None)

    assertion_b64 = proof.get("assertion", proof.get("signature"))
    if not isinstance(assertion_b64, str):
        return False, "malformed proof", None
    try:
        spki = base64.b64decode(linked.payload["public_key_spki"])
        assertion = _b64(assertion_b64)
        app_id = linked.payload["app_id"]
    except (KeyError, binascii.Error, ValueError):
        return False, "malformed proof", None
    device_id = linked.object_id
    with _counter_lock:
        seen = _counters.setdefault(device_id, set())
        try:
            counter = app_attest.verify_assertion(assertion, message, spki, app_id,
                                                  seen | _ledger_counters(flow, device_id))
        except app_attest.AppAttestError as exc:
            return False, str(exc), None
        seen.add(counter)
        for old in [c for c in seen if c <= max(seen) - app_attest.COUNTER_WINDOW]:
            seen.discard(old)                 # refused as stale anyway: keep the remembered set bounded
    return True, None, counter


def _same_number(a: Any, b: Any) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(float(a), float(b), abs_tol=1e-7)


def check_proof(flow: FlowCore, agent_id: str, proof: Any, *, truth_key: str, observation: Any) -> Dict[str, Any]:
    """
    {device_id, verified, reason} (and counter, for an iPhone). The phone signs a JSON text of what it saw,
    at capture:
      {"truth_key", "claim_type", "reported_at", "geo": {"lat","lon"}, "payload", "evidence_sha256"}
    and sends {device_id, signed: that text, signature} (Android) or {device_id, signed, assertion} (iPhone).
    Kaori checks the signature with the linked key, then that the text says what the report says.
    """
    if not isinstance(proof, dict):
        return {"device_id": None, "verified": False, "reason": "unsigned"}
    device_id, signed = proof.get("device_id"), proof.get("signed")
    out: Dict[str, Any] = {"device_id": device_id if isinstance(device_id, str) else None, "verified": False}
    linked = linked_devices(flow).get(device_id) if isinstance(device_id, str) else None
    if linked is None or linked.agent_id != agent_id:
        return {**out, "reason": "not this person's linked phone"}
    if not isinstance(signed, str):
        return {**out, "reason": "malformed proof"}
    ok, reason, counter = verify_signed(flow, linked, signed.encode("utf-8"), proof)
    if counter is not None:
        out["counter"] = counter          # an iPhone's App Attest counter, kept in the ledger
    if not ok:
        return {**out, "reason": reason}
    try:
        said = json.loads(signed)
    except ValueError:
        return {**out, "reason": "malformed proof"}
    from kaori_api.antalya import _parse_time

    geo = said.get("geo") or {}
    evidence = observation.evidence_refs[0].sha256 if observation.evidence_refs else None
    mismatches = [name for name, same in (
        ("truth_key", said.get("truth_key") == truth_key),
        ("claim_type", said.get("claim_type") == observation.claim_type),
        ("reported_at", _parse_time(said.get("reported_at")) == observation.reported_at),
        ("geo", _same_number(geo.get("lat"), observation.geo.get("lat")) and _same_number(geo.get("lon"), observation.geo.get("lon"))),
        ("payload", said.get("payload") == observation.payload),
        ("evidence", said.get("evidence_sha256") == evidence),
    ) if not same]
    if mismatches:
        return {**out, "reason": "signed text differs from the report: " + ", ".join(mismatches)}
    return {**out, "verified": True, "reason": None}
