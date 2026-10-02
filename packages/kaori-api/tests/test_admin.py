"""Antalya admin API: verified admin emails only; views read from the ledger; seeding and unlinking are Signals."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kaori_api import antalya
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

from test_devices import Phone, _h, _link, _report, _verify  # noqa: F401  (fixtures below reuse the phone)
from test_devices import phone  # noqa: F401

ADMINS = {
    "adm-ok": {"sub": "boss", "email": "madin@msro.gov.mv", "email_verified": True},
    "adm-unverified": {"sub": "x", "email": "madin@msro.gov.mv", "email_verified": False},
    "adm-other": {"sub": "y", "email": "someone@example.com", "email_verified": True},
}


def _claims(token):
    if token not in ADMINS:
        raise AuthError("invalid")
    return ADMINS[token]


@pytest.fixture
def env(monkeypatch, phone):  # noqa: F811
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    monkeypatch.setenv("KAORI_ADMIN_EMAILS", "Madin@MSRO.gov.mv, ops@msro.gov.mv")
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, evidence_store=InMemoryEvidenceStore(bucket_name="b"),
                     generalist_client=None)
    app.state.admin_claims = _claims
    app.state.ai_reader = lambda c, i: {"values": {"cover": "overcast", "raining": False}, "probs": {}, "relevance": 0.9}
    app.state.ai_sync = True
    antalya.seed_member(flow, "user:madin", callsign="Heron")
    return TestClient(app), flow, phone


def _a(token="adm-ok"):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("token,code", [(None, 401), ("nonsense", 401), ("adm-unverified", 403), ("adm-other", 403)])
def test_only_verified_listed_admins_get_in(env, token, code):
    client, _, _ = env
    headers = _a(token) if token else {}
    assert client.get("/v1/admin/overview", headers=headers).status_code == code
    assert client.get("/v1/admin/me", headers=_a()).json() == {"email": "madin@msro.gov.mv", "agent_id": "user:boss"}


def test_members_show_who_invited_whom_and_their_phone(env):
    client, flow, phone = env
    made = client.post("/v1/invites", headers=_h("madin"), json={"callsign": "Heron"}).json()
    assert client.post("/v1/invites/redeem", headers=_h("aisha"),
                       json={"code": made["code"], "relationship": "met_at_iac", "known_for": "lt_1m", "device_id": "dev-aisha-001"}).status_code == 200
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin")).status_code == 200
    device_id = _link(client, phone, who="aisha").json()["device_id"]
    by_id = {m["agent_id"]: m for m in client.get("/v1/admin/members", headers=_a()).json()}
    assert by_id["user:madin"]["seed"] and by_id["user:madin"]["callsign"] == "Heron"
    aisha = by_id["user:aisha"]
    assert (aisha["referrer"], aisha["referrer_callsign"], aisha["relationship"]) == ("user:madin", "Heron", "met_at_iac")
    assert aisha["device"]["device_id"] == device_id and aisha["device"]["security_level"] == "tee"
    assert by_id["user:madin"]["invites_issued"] == 1


def test_overview_truths_and_devices_follow_the_ledger(env):
    client, flow, phone = env
    device_id = _link(client, phone).json()["device_id"]
    assert _report(client, phone, device_id=device_id).status_code == 202
    o = client.get("/v1/admin/overview", headers=_a()).json()
    assert (o["members"], o["seeds"], o["phones_linked"], o["reports"], o["reports_device_signed"]) == (1, 1, 1, 1, 1)
    assert o["ai_readings"] == 1 and o["truthkeys"] == 1 and sum(h["reports"] for h in o["per_hour"]) == 1
    [t] = client.get("/v1/admin/truths", headers=_a()).json()
    assert (t["reporters"], t["device_signed"], t["ai_readings"], t["status"]) == (1, 1, 1, "PENDING")
    d = client.get("/v1/admin/devices", headers=_a()).json()
    assert [x["device_id"] for x in d["linked"]] == [device_id] and d["refused"] == []


def test_refused_phones_are_listed_with_their_reasons(env):
    client, _, phone = env
    assert _link(client, phone, locked=False).status_code == 403
    [r] = client.get("/v1/admin/devices", headers=_a()).json()["refused"]
    assert r["agent_id"] == "user:madin" and "locked bootloader" in r["reasons"][0]


def test_admins_add_seeds_and_unlink_phones_as_signals(env):
    client, flow, phone = env
    r = client.post("/v1/admin/seeds", headers=_a(), json={"agent_id": "user:newseed123", "callsign": "Tern"})
    assert r.status_code == 200 and antalya.is_member(flow, "user:newseed123")
    assert client.post("/v1/admin/seeds", headers=_a(), json={"agent_id": "bob"}).status_code == 400
    device_id = _link(client, phone).json()["device_id"]
    assert client.post(f"/v1/admin/devices/{device_id}/unlink", headers=_a()).json()["unlinked"]
    [u] = flow.store.get_by_type(SignalTypes.DEVICE_UNLINKED)
    assert u.payload == {"reason": "admin", "by": "madin@msro.gov.mv"}
    assert client.get("/v1/me", headers=_h("madin")).json()["device"] is None
    assert client.post(f"/v1/admin/devices/{device_id}/unlink", headers=_a()).status_code == 404


def test_admin_export_is_the_full_ledger(env):
    client, _, _ = env
    r = client.get("/v1/admin/export", headers=_a())
    assert r.status_code == 200 and '"REFERRAL_REDEEMED"' in r.text
    assert client.get("/v1/admin/export", headers=_a("adm-other")).status_code == 403
