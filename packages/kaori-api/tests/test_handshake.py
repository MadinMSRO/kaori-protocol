"""The in-person handshake: an invite QR lasts 30 minutes, the invitee asks to join, the inviter confirms them."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest

from kaori_api import antalya

from test_antalya import _h, env  # noqa: F401  (the Antalya service fixture)


@pytest.fixture(autouse=True)
def name_key(monkeypatch):
    monkeypatch.setenv("KAORI_NAME_KEY", secrets.token_hex(32))


def _invite(client, by="madin", **side):
    return client.post("/v1/invites", headers=_h(by), json={"callsign": "Mugiwara", **side}).json()


def _ask(client, code, who, device=None):
    body = {"code": code, "name": who.title(), "relationship": "friend", "known_for": "1_5y",
            "device_id": device or f"install-{who}-0001"}
    return client.post("/v1/invites/redeem", headers=_h(who), json=body)


def _mine(client, by="madin"):
    return client.get("/v1/invites/mine", headers=_h(by)).json()


def _later(monkeypatch, minutes):
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    monkeypatch.setattr(antalya, "_now", lambda: t)


def test_a_request_is_not_a_member_until_the_inviter_confirms(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = _invite(client, invitee_name="Aisha")
    assert _ask(client, made["code"], "aisha").json()["member"] is False

    me = client.get("/v1/me", headers=_h("aisha")).json()
    assert me["member"] is False and me["joining"]["state"] == "waiting" and me["joining"]["referrer_callsign"] == "Mugiwara"
    assert client.post("/v1/invites", headers=_h("aisha")).status_code == 403       # cannot invite yet
    [inv] = _mine(client)
    assert (inv["status"], inv["name_by_you"], inv["joiner_name"]) == ("joining", "Aisha", "Aisha")

    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin")).json()["status"] == "joined"
    me = client.get("/v1/me", headers=_h("aisha")).json()
    assert me["member"] is True and me["joining"] is None


def test_only_the_inviter_can_confirm_and_only_someone_who_asked(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    antalya.seed_member(flow, "user:omar")
    made = _invite(client)
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin")).status_code == 409   # nobody yet
    _ask(client, made["code"], "aisha")
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("omar")).status_code == 404
    assert client.post(f"/v1/invites/{made['id']}/promote", headers=_h("madin")).status_code == 400


def test_declined_is_not_a_member_and_the_phone_can_join_again(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    first = _invite(client)
    _ask(client, first["code"], "zed", device="install-zed-0001")
    assert client.post(f"/v1/invites/{first['id']}/decline", headers=_h("madin")).json()["status"] == "declined"
    assert client.get("/v1/me", headers=_h("zed")).json()["joining"]["state"] == "declined"
    second = _invite(client)
    assert _ask(client, second["code"], "zed", device="install-zed-0001").status_code == 200


def test_a_waiting_request_holds_until_answered(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    a, b = _invite(client), _invite(client)
    _ask(client, a["code"], "aisha")
    assert _ask(client, b["code"], "aisha", device="install-aisha-0002").status_code == 409
    assert _ask(client, b["code"], "omar", device="install-aisha-0001").status_code == 409   # same phone


def test_invite_qr_lasts_30_minutes_and_a_request_30_more(env, monkeypatch):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    old, asked = _invite(client), _invite(client)
    _ask(client, asked["code"], "aisha")
    _later(monkeypatch, 31)
    assert client.get(f"/v1/invites/{old['code']}").json() == {"valid": False, "reason": "expired"}
    assert {i["id"]: i["status"] for i in _mine(client)} == {old["id"]: "expired", asked["id"]: "expired"}
    assert client.post(f"/v1/invites/{asked['id']}/confirm", headers=_h("madin")).status_code == 409
    assert client.get("/v1/me", headers=_h("aisha")).json()["joining"]["state"] == "expired"


def test_cancel_an_unused_invite(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    made = _invite(client)
    assert client.post(f"/v1/invites/{made['id']}/cancel", headers=_h("madin")).json()["status"] == "cancelled"
    assert client.get(f"/v1/invites/{made['code']}").json() == {"valid": False, "reason": "cancelled"}
    assert _ask(client, made["code"], "aisha").status_code == 410


def test_admin_counts_invites_by_what_happened(env, monkeypatch):  # noqa: F811
    client, flow, _ = env
    monkeypatch.setenv("KAORI_ADMIN_EMAILS", "madin@msro.gov.mv")
    client.app.state.admin_claims = lambda t: {"sub": "boss", "email": "madin@msro.gov.mv", "email_verified": True}
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    joined, waiting, cancelled, joining = _invite(client), _invite(client), _invite(client), _invite(client)
    _ask(client, joined["code"], "aisha")
    client.post(f"/v1/invites/{joined['id']}/confirm", headers=_h("madin"))
    client.post(f"/v1/invites/{cancelled['id']}/cancel", headers=_h("madin"))
    _ask(client, joining["code"], "omar")
    a = {"Authorization": "Bearer t"}
    over = client.get("/v1/admin/overview", headers=a).json()
    assert over["invites_issued"] == 4 and over["members"] == 2
    assert over["invites_by_status"] == {"joined": 1, "waiting": 1, "cancelled": 1, "joining": 1}
    members = {m["agent_id"]: m for m in client.get("/v1/admin/members", headers=a).json()}
    assert "user:omar" not in members and members["user:madin"]["invites_joined"] == 1
    rows = client.get("/v1/admin/invites", headers=a).json()
    assert {r["status"] for r in rows} == {"joined", "waiting", "cancelled", "joining"}
    assert all(r["inviter_callsign"] == "Mugiwara" for r in rows)
