"""Two-sided invites: each person describes the other independently; names are encrypted in the ledger."""
from __future__ import annotations

import json
import secrets

import pytest

from kaori_api import antalya, names
from kaori_flow.primitives.signal import SignalTypes

from test_antalya import _h, env  # noqa: F401  (the Antalya service fixture)

KEY = secrets.token_hex(32)


@pytest.fixture(autouse=True)
def name_key(monkeypatch):
    monkeypatch.setenv("KAORI_NAME_KEY", KEY)


def _invite(client, by="madin", **side):
    return client.post("/v1/invites", headers=_h(by), json={"callsign": "Mugiwara", **side}).json()


def _redeem(client, code, who, **side):
    body = {"code": code, "relationship": "friend", "known_for": "1_5y", "device_id": f"install-{who}-0001", **side}
    return client.post("/v1/invites/redeem", headers=_h(who), json=body)


# ------------------------------------------------------------------------------------------- names

def test_names_are_sealed_to_their_place_in_the_ledger():
    token = names.seal("Aisha Ibrahim", "invite:abc")
    assert token.startswith("v1:") and "Aisha" not in token
    assert names.unseal(token, "invite:abc") == "Aisha Ibrahim"
    assert names.unseal(token, "invite:other") is None          # moved to another record: unreadable


def test_without_a_key_names_are_not_kept(monkeypatch):
    monkeypatch.delenv("KAORI_NAME_KEY")
    assert names.seal("Aisha", "x") is None


@pytest.mark.parametrize("a,b,same", [
    ("Aïsha Ibrahim", "aisha", True), ("  AISHA  ", "Aisha I.", True), ("Aisha", "Amira", False), ("", "Aisha", None),
])
def test_first_names_are_compared_loosely(a, b, same):
    assert names.same_person(names.clean(a), names.clean(b)) is same


# ------------------------------------------------------------------------------------- introductions

def test_both_sides_agree_and_no_name_is_stored_in_clear(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = _invite(client, invitee_name="Aisha Ibrahim", relationship="friend", known_for="gt_5y")
    # the invitee cannot see the inviter's answers
    assert set(client.get(f"/v1/invites/{made['code']}").json()) == {"valid", "referrer_callsign", "expires_at"}
    assert _redeem(client, made["code"], "aisha", name="Aisha", relationship="friend", known_for="1_5y").status_code == 200

    [r] = [s for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) if s.agent_id == "user:aisha"]
    assert r.payload["agreement"] == {"relationship": True, "known_for": True, "name": True}
    ledger = json.dumps([s.model_dump(mode="json") for s in flow.store.get_all()])
    assert "Aisha" not in ledger and "aisha" not in ledger.replace("user:aisha", "").replace("install-aisha", "")


def test_disagreement_is_recorded_not_refused(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = _invite(client, invitee_name="Omar", relationship="family", known_for="gt_5y")
    assert _redeem(client, made["code"], "zed", name="Zed", relationship="met_at_iac", known_for="lt_1m").status_code == 200
    [r] = [s for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) if s.agent_id == "user:zed"]
    assert r.payload["agreement"] == {"relationship": False, "known_for": False, "name": False}


def test_an_old_style_invite_still_works_and_agreement_is_unknown(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = _invite(client)
    assert _redeem(client, made["code"], "amira").status_code == 200
    [r] = [s for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) if s.agent_id == "user:amira"]
    assert r.payload["agreement"] == {"relationship": None, "known_for": None, "name": None}


def test_bad_answers_are_refused(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    assert client.post("/v1/invites", headers=_h("madin"), json={"relationship": "enemy"}).status_code == 400
    assert client.post("/v1/invites", headers=_h("madin"), json={"invitee_name": "x" * 61}).status_code == 400


def test_admins_see_both_sides_decrypted(env, monkeypatch):  # noqa: F811
    client, flow, _ = env
    monkeypatch.setenv("KAORI_ADMIN_EMAILS", "madin@msro.gov.mv")
    client.app.state.admin_claims = lambda t: {"sub": "boss", "email": "madin@msro.gov.mv", "email_verified": True}
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = _invite(client, invitee_name="Aisha Ibrahim", relationship="friend", known_for="gt_5y")
    _redeem(client, made["code"], "aisha", name="Aisha", relationship="friend", known_for="1_5y")
    client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin"))
    [m] = [m for m in client.get("/v1/admin/members", headers={"Authorization": "Bearer t"}).json() if m["agent_id"] == "user:aisha"]
    assert (m["name"], m["name_by_inviter"], m["inviter_relationship"], m["inviter_known_for"]) == ("Aisha", "Aisha Ibrahim", "friend", "gt_5y")
    assert m["agreement"] == {"relationship": True, "known_for": True, "name": True}


def test_the_qr_opens_the_web_join_page_when_configured(env, monkeypatch):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    assert _invite(client)["qr_payload"].startswith("liminal://join?code=")
    monkeypatch.setenv("KAORI_JOIN_URL", "https://example.org/join.html")
    made = _invite(client)
    assert made["qr_payload"] == f"https://example.org/join.html?code={made['code']}"
