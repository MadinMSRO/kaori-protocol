"""Leaving Liminal (DELETE /v1/me): membership ends by a new signal, nothing in the ledger is changed or removed."""
from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya
from kaori_api.app import create_app
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

from test_admin import _a, _claims
from test_devices import _h, _link, _verify
from test_devices import phone  # noqa: F401  (fixture)

CLAIM = "earth.sky_cover.v1"
KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
GEO = {"lat": 36.8969, "lon": 30.7133}
NAME_KEY = "11" * 32


@pytest.fixture
def env(monkeypatch, phone):  # noqa: F811
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    monkeypatch.setenv("KAORI_ADMIN_EMAILS", "madin@msro.gov.mv")
    monkeypatch.setenv("KAORI_NAME_KEY", NAME_KEY)
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, evidence_store=InMemoryEvidenceStore(bucket_name="b"),
                     generalist_client=None)
    app.state.admin_claims = _claims
    app.state.ai_reader = None               # people's readings only: the desk is about human validators
    app.state.ai_sync = True
    for who in ("madin", "aisha", "val"):
        antalya.seed_member(flow, "user:" + who, callsign=who.title())
    return TestClient(app), flow, phone


def _leave(client, who):
    r = client.delete("/v1/me", headers=_h(who))
    assert r.status_code == 200, r.text
    return r.json()


def _me(client, who):
    return client.get("/v1/me", headers=_h(who)).json()


def _invite(client, who, invitee_name=None):
    body = {"callsign": who.title()}
    if invitee_name:
        body["invitee_name"] = invitee_name
    return client.post("/v1/invites", headers=_h(who), json=body).json()


def _redeem(client, who, code, device, name=None):
    return client.post("/v1/invites/redeem", headers=_h(who), json={
        "code": code, "relationship": "friend", "known_for": "1_5y", "device_id": device, "name": name})


def _join(client, who, by, device, name=None):
    made = _invite(client, by, invitee_name=name)
    assert _redeem(client, who, made["code"], device, name=name).status_code == 200
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h(by)).status_code == 200
    return made


def _report(client, who, key=KEY):
    img = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 160, 220)).save(img, format="JPEG", comment=who.encode())
    up = client.post("/v1/evidence", headers=_h(who), files={"file": ("s.jpg", img.getvalue(), "image/jpeg")})
    if up.status_code != 200:
        return up
    obs = {"claim_type": CLAIM, "reported_at": "2026-10-05T09:00:30.000Z", "geo": GEO,
           "payload": {"cover": "overcast", "raining": False}, "evidence_refs": [up.json()]}
    return client.post("/v1/compile", headers=_h(who), json={"claim_type_id": CLAIM, "truth_key": key,
                                                             "observations": [obs]})


def test_leaving_ends_membership(env):
    client, flow, _ = env
    assert _me(client, "madin")["member"] is True
    out = _leave(client, "madin")
    assert (out["member"], out["left"], out["appended"]) == (False, True, [SignalTypes.MEMBERSHIP_ENDED])
    me = _me(client, "madin")
    assert (me["member"], me["joining"], me["device"]) == (False, None, None)
    [ended] = flow.store.get_by_type(SignalTypes.MEMBERSHIP_ENDED)
    assert (ended.agent_id, ended.object_id, ended.payload) == (
        "user:madin", "member:user:madin", {"reason": "left", "was_member": True})


def test_who_left_cannot_report_validate_or_invite(env):
    client, _, _ = env
    assert _report(client, "madin").status_code == 202
    _leave(client, "madin")
    assert _report(client, "madin").status_code == 403
    assert client.post("/v1/invites", headers=_h("madin"), json={}).status_code == 403
    assert client.get("/v1/assignments", headers=_h("madin")).status_code == 403
    assert client.post("/v1/validate", headers=_h("madin"),
                       json={"truth_key": KEY, "vote": "RATIFY"}).status_code == 403
    assert client.post("/v1/devices/challenge", headers=_h("madin")).status_code == 403


def test_their_phone_is_unlinked(env):
    client, flow, phone = env
    device_id = _link(client, phone, who="aisha").json()["device_id"]
    out = _leave(client, "aisha")
    assert out["appended"] == [SignalTypes.DEVICE_UNLINKED, SignalTypes.MEMBERSHIP_ENDED]
    [unlinked] = flow.store.get_by_type(SignalTypes.DEVICE_UNLINKED)
    assert (unlinked.agent_id, unlinked.object_id, unlinked.payload) == ("user:aisha", device_id, {"reason": "left"})
    assert client.get("/v1/admin/devices", headers=_a()).json()["linked"] == []


def test_their_open_invites_and_pending_joins_are_cancelled(env):
    client, flow, _ = env
    unused = _invite(client, "madin")
    waiting_on_madin = _invite(client, "madin", invitee_name="Amira")
    assert _redeem(client, "amira", waiting_on_madin["code"], "dev-amira-0001", name="Amira").status_code == 200
    # omar asked to join with aisha's invite and leaves before she confirms
    from_aisha = _invite(client, "aisha", invitee_name="Omar")
    assert _redeem(client, "omar", from_aisha["code"], "dev-omar-00001", name="Omar").status_code == 200

    out = _leave(client, "madin")
    assert out["appended"] == [SignalTypes.INVITE_CANCELLED, SignalTypes.INVITE_CANCELLED, SignalTypes.MEMBERSHIP_ENDED]
    assert client.get(f"/v1/invites/{unused['code']}").json() == {"valid": False, "reason": "cancelled"}
    assert _me(client, "amira")["joining"]["state"] == "declined"
    assert client.post(f"/v1/invites/{waiting_on_madin['id']}/confirm", headers=_h("madin")).status_code in (403, 404, 409)

    out = _leave(client, "omar")
    assert out["appended"] == [SignalTypes.INVITE_CANCELLED, SignalTypes.MEMBERSHIP_ENDED]
    [view] = client.get("/v1/invites/mine", headers=_h("aisha")).json()
    assert (view["status"], view["joiner_name"], view["name_by_you"]) == ("cancelled", None, None)
    assert client.post(f"/v1/invites/{from_aisha['id']}/confirm", headers=_h("aisha")).status_code == 409
    assert _me(client, "omar") == {**_me(client, "omar"), "member": False, "joining": None}


def test_the_desk_stops_assigning_to_them_and_frees_their_slots(env):
    client, flow, _ = env
    for who in ("v1", "v2", "v3", "v4"):
        antalya.seed_member(flow, "user:" + who)
    assert _report(client, "madin").status_code == 202
    held = {who: client.get("/v1/assignments", headers=_h(who)).json() for who in ("v1", "v2", "v3")}
    assert all(len(a) == 1 for a in held.values())
    assert client.get("/v1/assignments", headers=_h("v4")).json() == []      # three readers per report

    _leave(client, "v1")
    assert client.get("/v1/assignments", headers=_h("v1")).status_code == 403
    reading = client.post(f"/v1/assignments/{held['v1'][0]['assignment_id']}/reading", headers=_h("v1"),
                          json={"values": {"cover": "overcast", "raining": False}})
    assert reading.status_code == 403
    assert not flow.store.get_by_type(SignalTypes.READING_SUBMITTED)
    assert len(client.get("/v1/assignments", headers=_h("v4")).json()) == 1   # v1's slot went to someone else


def test_they_can_be_invited_again_and_the_latest_signal_wins(env):
    client, flow, _ = env
    _join(client, "amira", by="madin", device="dev-amira-0001", name="Amira")
    _leave(client, "amira")
    assert _me(client, "amira")["member"] is False
    # the same account, the same phone: invited again, redeemed normally, confirmed
    _join(client, "amira", by="aisha", device="dev-amira-0001", name="Amira K")
    assert _me(client, "amira")["member"] is True
    assert _report(client, "amira").status_code == 202
    listed = [m for m in client.get("/v1/admin/members", headers=_a()).json() if m["agent_id"] == "user:amira"]
    assert len(listed) == 1 and (listed[0]["referrer"], listed[0]["name"]) == ("user:aisha", "Amira K")
    # and a new account on that phone after leaving again
    _leave(client, "amira")
    _join(client, "amira2", by="aisha", device="dev-amira-0001")
    assert _me(client, "amira2")["member"] is True and _me(client, "amira")["member"] is False


def test_leaving_twice_is_fine_and_appends_nothing_more(env):
    client, flow, _ = env
    first = _leave(client, "val")
    before = len(flow.store.get_all())
    second = _leave(client, "val")
    assert second == {**first, "appended": []}
    assert len(flow.store.get_all()) == before
    # someone who never joined can delete their account too
    assert _leave(client, "stranger")["appended"] == []


def test_unauthenticated_is_refused(env):
    client, _, _ = env
    assert client.delete("/v1/me").status_code == 401
    assert client.delete("/v1/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_seeds_can_leave_and_be_seeded_again(env):
    client, flow, _ = env
    _leave(client, "madin")
    assert antalya.seed_member(flow, "user:madin", callsign="Heron").payload["referrer"] == antalya.SEED_REFERRER
    assert _me(client, "madin")["member"] is True
    assert len([s for s in flow.store.get_by_type(SignalTypes.REFERRAL_REDEEMED) if s.agent_id == "user:madin"]) == 2


def test_their_names_are_never_decrypted_again_and_nothing_is_changed(env):
    client, flow, _ = env
    _join(client, "amira", by="madin", device="dev-amira-0001", name="Amira Hassan")
    by_id = {m["agent_id"]: m for m in client.get("/v1/admin/members", headers=_a()).json()}
    assert by_id["user:amira"]["name"] == "Amira Hassan"
    assert _report(client, "amira").status_code == 202
    before = {s.signal_id: s.model_dump(mode="json") for s in flow.store.get_all()}

    _leave(client, "amira")
    after = {s.signal_id: s.model_dump(mode="json") for s in flow.store.get_all()}
    assert all(after[k] == v for k, v in before.items())                    # appended to, never changed

    members = client.get("/v1/admin/members", headers=_a()).json()
    assert "user:amira" not in {m["agent_id"] for m in members}
    for path in ("/v1/admin/members", "/v1/admin/invites", "/v1/admin/devices"):
        assert "Amira" not in client.get(path, headers=_a()).text
    assert "Amira" not in client.get("/v1/invites/mine", headers=_h("madin")).text
    overview = client.get("/v1/admin/overview", headers=_a()).json()
    assert (overview["members"], overview["members_left"], overview["reports"]) == (3, 1, 1)
    # the report stays, under the agent id only
    [truth] = client.get("/v1/admin/truths", headers=_a()).json()
    assert truth["reporters"] == 1
    assert "Amira" not in json.dumps(truth)


def test_admin_access_is_by_email_and_unaffected(env):
    client, _, _ = env
    _leave(client, "boss")                     # the admin's own Firebase account (user:boss) leaves
    assert client.get("/v1/admin/overview", headers=_a()).status_code == 200
