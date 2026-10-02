"""
Linking a phone (Antalya): the phone becomes its own agent, vouched for by its secure hardware.

1. The app asks for a challenge (bound to the signed-in person, ten minutes, single use).
2. The phone's Android Keystore makes a signing key for that challenge and returns its attestation chain.
3. Kaori checks the chain (attestation.py). If the policy holds, DEVICE_LINKED records the phone as
   `sensor:android-…` with its public key; a person has one linked phone, and linking a new one unlinks
   the old (DEVICE_UNLINKED). A refusal is a signal too (DEVICE_LINK_REFUSED), with its reasons.
4. Each report is then signed by the phone at capture time (device_proof), and Kaori checks the
   signature against the linked key and the signed fields against the report.

Policy, from the environment:
  KAORI_ANDROID_PACKAGE        the app (default mv.msro.liminal)
  KAORI_ANDROID_CERT_SHA256    MSRO's app signing certificate(s), comma-separated (deploy.sh signing)
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
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from kaori_flow import FlowCore
from kaori_flow.primitives.signal import Signal, SignalTypes

from kaori_api import attestation

CHALLENGE_TTL_SECONDS = 600
_CHALLENGE_KEY = secrets.token_bytes(32)      # per process: a restart only means asking again
_used: Dict[str, float] = {}
_used_lock = threading.Lock()
TRUST = attestation.TrustData()


def policy() -> attestation.Policy:
    certs = [c.strip() for c in os.environ.get("KAORI_ANDROID_CERT_SHA256", "").split(",") if c.strip()]
    return attestation.Policy(
        package=os.environ.get("KAORI_ANDROID_PACKAGE", "mv.msro.liminal"),
        cert_sha256=certs,
        require_hardware=os.environ.get("KAORI_DEVICE_ALLOW_SOFTWARE") != "1",
        require_verified_boot=os.environ.get("KAORI_DEVICE_ALLOW_UNLOCKED") != "1",
    )


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
    from kaori_api.validation import ensure_agent_registered

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
              {"reasons": reasons, **(facts or {})})
        raise HTTPException(status_code=403, detail={"message": "This phone cannot be linked", "reasons": reasons})

    try:
        att = attestation.verify_chain(chain, challenge, policy(), trust or TRUST)
    except attestation.AttestationError as exc:
        refuse([str(exc)])
    if att.problems:
        refuse(att.problems, att.summary())

    device_id = att.device_key_id
    current = linked_devices(flow).get(device_id)
    if current is not None and current.agent_id != agent_id:
        refuse(["this phone's key is linked to someone else"], att.summary())
    previous = active_device(flow, agent_id)
    if previous is not None and previous.object_id != device_id:
        _emit(flow, SignalTypes.DEVICE_UNLINKED, agent_id, previous.object_id, {"reason": "replaced", "by": device_id})
    ensure_agent_registered(flow, device_id, role="observer", agent_type="sensor")
    if current is None:
        _emit(flow, SignalTypes.DEVICE_LINKED, agent_id, device_id, {
            "public_key_spki": base64.b64encode(att.public_key_spki).decode(), **att.summary(),
        })
    return {"device_id": device_id, **att.summary()}


def me(flow: FlowCore, agent_id: str) -> Dict[str, Any]:
    from kaori_api.antalya import join_state

    device = active_device(flow, agent_id)
    return {
        "agent_id": agent_id,
        **join_state(flow, agent_id),
        "device": None if device is None else {
            "device_id": device.object_id,
            "linked_at": device.time.isoformat(),
            **{k: device.payload.get(k) for k in ("security_level", "verified_boot_state", "os_patch_level")},
        },
        "device_required": required(),
    }


def require_device(flow: FlowCore, agent_id: str) -> None:
    if required() and active_device(flow, agent_id) is None:
        raise HTTPException(status_code=403, detail="Link this phone first")


# ---------------------------------------------------------------------------------- signed reports

def _same_number(a: Any, b: Any) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isclose(float(a), float(b), abs_tol=1e-7)


def check_proof(flow: FlowCore, agent_id: str, proof: Any, *, truth_key: str, observation: Any) -> Dict[str, Any]:
    """
    {device_id, verified, reason}. The phone signs a JSON text of what it saw, at capture:
      {"truth_key", "claim_type", "reported_at", "geo": {"lat","lon"}, "payload", "evidence_sha256"}
    Kaori checks the signature with the linked key, then that the text says what the report says.
    """
    if not isinstance(proof, dict):
        return {"device_id": None, "verified": False, "reason": "unsigned"}
    device_id, signed, signature = proof.get("device_id"), proof.get("signed"), proof.get("signature")
    out = {"device_id": device_id if isinstance(device_id, str) else None, "verified": False}
    linked = linked_devices(flow).get(device_id) if isinstance(device_id, str) else None
    if linked is None or linked.agent_id != agent_id:
        return {**out, "reason": "not this person's linked phone"}
    if not isinstance(signed, str) or not isinstance(signature, str):
        return {**out, "reason": "malformed proof"}
    try:
        spki = base64.b64decode(linked.payload["public_key_spki"])
        sig = base64.b64decode(signature, validate=True)
    except (KeyError, binascii.Error, ValueError):
        return {**out, "reason": "malformed proof"}
    if not attestation.verify_signature(spki, signed.encode("utf-8"), sig):
        return {**out, "reason": "bad signature"}
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
