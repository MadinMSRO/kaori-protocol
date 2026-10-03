"""The NFC hold: the joiner's phone shows a fresh secret over NFC while the two phones are held together, and the
inviter confirms with it, so Kaori knows the confirm came from touching the right phone."""
from __future__ import annotations

import secrets

import pytest
from kaori_flow.primitives.signal import SignalTypes

from kaori_api import antalya

import test_devices
from test_antalya import _h, env  # noqa: F401  (the Antalya service fixture)


@pytest.fixture(autouse=True)
def name_key(monkeypatch):
    monkeypatch.setenv("KAORI_NAME_KEY", secrets.token_hex(32))


def _join(client, flow, who="aisha"):
    antalya.seed_member(flow, "user:madin", callsign="Mugiwara")
    made = client.post("/v1/invites", headers=_h("madin"), json={"callsign": "Mugiwara", "invitee_name": who.title()}).json()
    body = {"code": made["code"], "name": who.title(), "relationship": "friend", "known_for": "1_5y", "device_id": f"install-{who}-0001"}
    assert client.post("/v1/invites/redeem", headers=_h(who), json=body).status_code == 200
    return made


def _confirm(client, invite_id, proof=None, by="madin"):
    return client.post(f"/v1/invites/{invite_id}/confirm", headers=_h(by), json={"proof": proof} if proof else None)


def test_a_hold_with_the_joiners_secret_confirms_them_in_person(env):  # noqa: F811
    client, flow, _ = env
    made = _join(client, flow)
    hold = client.post("/v1/joining/hold", headers=_h("aisha")).json()
    assert hold["invite_id"] == made["id"] and len(hold["nonce"]) > 20 and hold["hold_ms"] == 3000
    [opened] = flow.store.get_by_type(SignalTypes.INVITE_HOLD_OPENED)
    assert hold["nonce"] not in str(opened.payload)          # only its hash is kept

    r = _confirm(client, made["id"], {"method": "nfc_hold", "nonce": hold["nonce"], "hold_ms": 3080})
    assert r.status_code == 200 and r.json()["status"] == "joined"
    [confirmed] = flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert confirmed.payload["in_person"] == "nfc_hold" and confirmed.payload["hold_ms"] == 3080
    assert confirmed.payload["device_verified"] is False
    assert client.get("/v1/me", headers=_h("aisha")).json()["member"] is True


def test_a_hold_with_another_phone_or_too_short_is_refused_and_nothing_is_confirmed(env):  # noqa: F811
    client, flow, _ = env
    made = _join(client, flow)
    hold = client.post("/v1/joining/hold", headers=_h("aisha")).json()
    assert _confirm(client, made["id"], {"method": "nfc_hold", "nonce": "someone-elses", "hold_ms": 3000}).status_code == 409
    assert _confirm(client, made["id"], {"method": "nfc_hold", "nonce": hold["nonce"], "hold_ms": 900}).status_code == 400
    assert _confirm(client, made["id"], {"method": "tap", "nonce": hold["nonce"], "hold_ms": 3000}).status_code == 400
    assert not flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert client.get("/v1/me", headers=_h("aisha")).json()["member"] is False


def test_a_confirm_without_a_hold_still_works_as_before(env):  # noqa: F811
    client, flow, _ = env
    made = _join(client, flow)
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin")).json()["status"] == "joined"
    [confirmed] = flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert "in_person" not in confirmed.payload


def test_only_someone_waiting_can_open_a_hold(env):  # noqa: F811
    client, flow, _ = env
    antalya.seed_member(flow, "user:madin")
    assert client.post("/v1/joining/hold", headers=_h("madin")).status_code == 409
    assert client.post("/v1/joining/hold", headers=_h("nobody")).status_code == 409


@pytest.fixture
def denv(monkeypatch, phone):
    monkeypatch.setenv("KAORI_NAME_KEY", secrets.token_hex(32))
    # the linked-phone service of test_devices, with someone new to invite
    from fastapi.testclient import TestClient
    from kaori_flow import FlowCore, InMemorySignalStore

    monkeypatch.setenv("KAORI_ANTALYA", "1")
    flow = FlowCore(store=InMemorySignalStore())
    app = test_devices.create_app(flow=flow, verify_token=test_devices._verify,
                                  evidence_store=test_devices.InMemoryEvidenceStore(bucket_name="b"), generalist_client=None)
    antalya.seed_member(flow, "user:madin", callsign="Madin")
    return TestClient(app), flow, phone


phone = test_devices.phone


def test_a_hold_signed_by_the_inviters_linked_phone_is_verified(denv):
    client, flow, phone = denv
    linked = test_devices._link(client, phone, who="madin").json()
    made = client.post("/v1/invites", headers=test_devices._h("madin"), json={"callsign": "Madin", "invitee_name": "Zara"}).json()
    body = {"code": made["code"], "name": "Zara", "relationship": "friend", "known_for": "1_5y", "device_id": "install-zara-0001"}
    assert client.post("/v1/invites/redeem", headers=test_devices._h("zara"), json=body).status_code == 200
    hold = client.post("/v1/joining/hold", headers=test_devices._h("zara")).json()
    text = antalya.HOLD_TEXT.format(invite=made["id"], nonce=hold["nonce"], hold_ms=3000)
    proof = {"method": "nfc_hold", "nonce": hold["nonce"], "hold_ms": 3000,
             "device": {"device_id": linked["device_id"], "signature": phone.sign(text)}}
    r = client.post(f"/v1/invites/{made['id']}/confirm", headers=test_devices._h("madin"), json={"proof": proof})
    assert r.status_code == 200 and r.json()["status"] == "joined"
    [confirmed] = flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert confirmed.payload["device_verified"] is True and confirmed.payload["device_id"] == linked["device_id"]


def test_a_forged_device_signature_is_recorded_as_unverified(denv):
    client, flow, phone = denv
    linked = test_devices._link(client, phone, who="madin").json()
    made = client.post("/v1/invites", headers=test_devices._h("madin"), json={"callsign": "Madin", "invitee_name": "Zara"}).json()
    body = {"code": made["code"], "name": "Zara", "relationship": "friend", "known_for": "1_5y", "device_id": "install-zara-0001"}
    client.post("/v1/invites/redeem", headers=test_devices._h("zara"), json=body)
    hold = client.post("/v1/joining/hold", headers=test_devices._h("zara")).json()
    proof = {"method": "nfc_hold", "nonce": hold["nonce"], "hold_ms": 3000,
             "device": {"device_id": linked["device_id"], "signature": phone.sign("something else")}}
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=test_devices._h("madin"), json={"proof": proof}).status_code == 200
    [confirmed] = flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert confirmed.payload["device_verified"] is False
