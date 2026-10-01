"""
Antalya admin API: what MSRO's team needs to run the test, read from the ledger.

Admins are listed by email in KAORI_ADMIN_EMAILS (comma-separated). An admin signs in with Firebase like
anyone else; Kaori checks the token, that its email is verified (Google sign-in verifies it), and that it is
on the list. Everything here is read from Signals, except two actions, which are Signals themselves:
adding a seed (REFERRAL_REDEEMED from seed:msro) and unlinking a phone (DEVICE_UNLINKED, reason admin).

    GET  /v1/admin/me                         {email, agent_id}
    GET  /v1/admin/overview                   counts, and reports and readings per hour
    GET  /v1/admin/members                    each member: who invited them, phone, reports, readings, standing
    GET  /v1/admin/truths                     each TruthKey: reporters, readings, status
    GET  /v1/admin/devices                    linked phones, and refusals with their reasons
    POST /v1/admin/seeds                      {agent_id: "user:<firebase uid>", callsign}
    POST /v1/admin/devices/{device_id}/unlink
    GET  /v1/admin/export                     the NDJSON export, for admins
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from kaori_flow import FlowCore
from kaori_flow.primitives.signal import SignalTypes

from kaori_api import antalya, devices
from kaori_api.auth import AuthError, parse_bearer


def admin_emails() -> set:
    return {e.strip().lower() for e in os.environ.get("KAORI_ADMIN_EMAILS", "").split(",") if e.strip()}


def _iso(t) -> Optional[str]:
    return t.isoformat() if t is not None else None


def _hour(t) -> str:
    return t.strftime("%Y-%m-%dT%H:00Z")


def _callsigns(flow: FlowCore) -> Dict[str, str]:
    """A member's callsign: the one they joined with as a seed, or the latest one on an invite they issued."""
    names: Dict[str, str] = {}
    for s in sorted(flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) + flow.store.get_by_type(SignalTypes.INVITE_ISSUED),
                    key=lambda s: s.time):
        name = (s.payload or {}).get("callsign")
        if isinstance(name, str) and name.strip():
            names[s.agent_id] = name.strip()
    return names


def members(flow: FlowCore) -> List[Dict[str, Any]]:
    names = _callsigns(flow)
    linked = {s.agent_id: s for s in devices.linked_devices(flow).values()}
    reports = Counter(s.agent_id for s in flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED))
    readings = Counter(s.agent_id for s in flow.store.get_by_type(SignalTypes.READING_SUBMITTED))
    invites = Counter(s.agent_id for s in flow.store.get_by_type(SignalTypes.INVITE_ISSUED))
    out = []
    for s in sorted(flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED), key=lambda s: s.time):
        p = s.payload or {}
        device = linked.get(s.agent_id)
        out.append({
            "agent_id": s.agent_id,
            "callsign": names.get(s.agent_id),
            "seed": p.get("referrer") == antalya.SEED_REFERRER,
            "referrer": p.get("referrer"),
            "referrer_callsign": names.get(p.get("referrer")),
            "relationship": p.get("relationship"),
            "known_for": p.get("known_for"),
            "joined_at": _iso(s.time),
            "device": None if device is None else {
                "device_id": device.object_id, "linked_at": _iso(device.time),
                "security_level": device.payload.get("security_level"),
            },
            "reports": reports.get(s.agent_id, 0),
            "readings": readings.get(s.agent_id, 0),
            "invites_issued": invites.get(s.agent_id, 0),
            "standing": round(flow.get_standing(s.agent_id), 1),
        })
    return out


def truths(flow: FlowCore, truth_store: Any) -> List[Dict[str, Any]]:
    obs = defaultdict(list)
    for s in flow.store.get_by_type(SignalTypes.OBSERVATION_SUBMITTED):
        obs[s.object_id].append(s)
    readings = defaultdict(lambda: {"people": 0, "ai": 0})
    for s in flow.store.get_by_type(SignalTypes.READING_SUBMITTED):
        key = (s.payload or {}).get("truthkey")
        if key:
            readings[key]["ai" if s.agent_id == antalya.AI_AGENT else "people"] += 1
    signed = Counter()
    for s in flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED):
        if ((s.payload or {}).get("checks") or {}).get("device_signed"):
            signed[(s.payload or {}).get("truthkey")] += 1
    out = []
    for key, sigs in obs.items():
        artifact = truth_store.get(key) if truth_store is not None else None
        artifact = artifact if isinstance(artifact, dict) else {}
        out.append({
            "truthkey": key,
            "claim_type_id": (sigs[0].payload or {}).get("claim_type_id"),
            "reporters": len({s.agent_id for s in sigs}),
            "device_signed": signed.get(key, 0),
            "readings": readings[key]["people"],
            "ai_readings": readings[key]["ai"],
            "status": artifact.get("status") or "PENDING",
            "confidence": artifact.get("confidence") or artifact.get("confidence_score"),
            "claim": artifact.get("claim"),
            "first_report_at": _iso(min(s.time for s in sigs)),
        })
    return sorted(out, key=lambda t: t["first_report_at"] or "", reverse=True)


def device_report(flow: FlowCore) -> Dict[str, Any]:
    names = _callsigns(flow)
    linked = [{"device_id": s.object_id, "agent_id": s.agent_id, "callsign": names.get(s.agent_id),
               "linked_at": _iso(s.time), **{k: s.payload.get(k) for k in
               ("security_level", "verified_boot_state", "os_patch_level", "app_cert_ok")}}
              for s in devices.linked_devices(flow).values()]
    refused = [{"agent_id": s.agent_id, "callsign": names.get(s.agent_id), "at": _iso(s.time),
                "reasons": (s.payload or {}).get("reasons", []),
                "security_level": (s.payload or {}).get("security_level")}
               for s in sorted(flow.store.get_by_type(SignalTypes.DEVICE_LINK_REFUSED), key=lambda s: s.time, reverse=True)]
    return {"linked": sorted(linked, key=lambda d: d["linked_at"] or "", reverse=True), "refused": refused}


def overview(flow: FlowCore, truth_store: Any) -> Dict[str, Any]:
    m = members(flow)
    t = truths(flow, truth_store)
    by_type = lambda kind: flow.store.get_by_type(kind)  # noqa: E731
    reports_h = Counter(_hour(s.time) for s in by_type(SignalTypes.OBSERVATION_SUBMITTED))
    readings_h = Counter(_hour(s.time) for s in by_type(SignalTypes.READING_SUBMITTED) if s.agent_id != antalya.AI_AGENT)
    hours = sorted(set(reports_h) | set(readings_h))
    statuses = Counter(x["status"] for x in t)
    redeemed = by_type(SignalTypes.REFERRAL_REDEEMED)
    return {
        "members": len(m),
        "seeds": sum(1 for x in m if x["seed"]),
        "invites_issued": len(by_type(SignalTypes.INVITE_ISSUED)),
        "invites_redeemed": sum(1 for s in redeemed if (s.payload or {}).get("code_hash")),
        "phones_linked": sum(1 for x in m if x["device"]),
        "phones_refused": len(by_type(SignalTypes.DEVICE_LINK_REFUSED)),
        "reports": len(by_type(SignalTypes.OBSERVATION_SUBMITTED)),
        "reports_device_signed": sum(x["device_signed"] for x in t),
        "readings": sum(readings_h.values()),
        "ai_readings": sum(1 for s in by_type(SignalTypes.READING_SUBMITTED) if s.agent_id == antalya.AI_AGENT),
        "truthkeys": len(t),
        "truths_by_status": dict(statuses),
        "per_hour": [{"hour": h, "reports": reports_h.get(h, 0), "readings": readings_h.get(h, 0)} for h in hours],
        "device_required": devices.required(),
    }


def add_routes(app: Any) -> None:
    from kaori_api.auth import FirebaseCerts, firebase_claims

    certs = FirebaseCerts()

    def require_admin(request: Request) -> Dict[str, str]:
        try:
            token = parse_bearer(request.headers.get("Authorization"))
        except AuthError:
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
        override: Optional[Callable[[str], Dict[str, Any]]] = getattr(request.app.state, "admin_claims", None)
        project = os.environ.get("FIREBASE_PROJECT_ID", "").strip()
        try:
            if override is not None:
                claims = override(token)
            elif project:
                claims = firebase_claims(token, project, certs)
            else:
                raise HTTPException(status_code=403, detail="Admin needs Firebase sign-in")
        except AuthError:
            raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
        email = str(claims.get("email") or "").lower()
        if not email or not claims.get("email_verified") or email not in admin_emails():
            raise HTTPException(status_code=403, detail="Not an admin")
        return {"email": email, "agent_id": "user:" + str(claims.get("sub"))}

    @app.get("/v1/admin/me")
    def admin_me(admin: Dict[str, str] = Depends(require_admin)):
        return admin

    @app.get("/v1/admin/overview")
    def admin_overview(_: Dict[str, str] = Depends(require_admin)):
        return overview(app.state.flow, app.state.truth_store)

    @app.get("/v1/admin/members")
    def admin_members(_: Dict[str, str] = Depends(require_admin)):
        return members(app.state.flow)

    @app.get("/v1/admin/truths")
    def admin_truths(_: Dict[str, str] = Depends(require_admin)):
        return truths(app.state.flow, app.state.truth_store)

    @app.get("/v1/admin/devices")
    def admin_devices(_: Dict[str, str] = Depends(require_admin)):
        return device_report(app.state.flow)

    @app.post("/v1/admin/seeds")
    async def admin_seed(request: Request, admin: Dict[str, str] = Depends(require_admin)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        agent_id = body.get("agent_id") if isinstance(body, dict) else None
        callsign = body.get("callsign") if isinstance(body, dict) else None
        if not isinstance(agent_id, str) or not agent_id.startswith("user:") or len(agent_id) < 8:
            raise HTTPException(status_code=400, detail='agent_id must be "user:<firebase uid>"')
        if callsign is not None and (not isinstance(callsign, str) or len(callsign) > 40):
            raise HTTPException(status_code=400, detail="callsign must be text, at most 40 characters")
        signal = antalya.seed_member(app.state.flow, agent_id, callsign=(callsign or "").strip() or None)
        return {"agent_id": agent_id, "seeded_at": _iso(signal.time), "by": admin["email"]}

    @app.post("/v1/admin/devices/{device_id}/unlink")
    def admin_unlink(device_id: str, admin: Dict[str, str] = Depends(require_admin)):
        linked = devices.linked_devices(app.state.flow).get(device_id)
        if linked is None:
            raise HTTPException(status_code=404, detail="No such linked phone")
        devices._emit(app.state.flow, SignalTypes.DEVICE_UNLINKED, linked.agent_id, device_id,
                      {"reason": "admin", "by": admin["email"]})
        return {"device_id": device_id, "unlinked": True}

    @app.get("/v1/admin/export")
    def admin_export(_: Dict[str, str] = Depends(require_admin)):
        return StreamingResponse(antalya.export_lines(app.state.flow, app.state.truth_store),
                                 media_type="application/x-ndjson",
                                 headers={"Content-Disposition": 'attachment; filename="antalya.ndjson"'})
