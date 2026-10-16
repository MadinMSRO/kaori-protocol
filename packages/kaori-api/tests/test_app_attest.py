"""Linking an iPhone by Apple App Attest, and reports signed by it with assertions (app_attest.py, devices.py)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import itertools
import json
import secrets
from pathlib import Path

import cbor2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya, app_attest, devices
from kaori_api.app import create_app
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

import test_devices
from test_devices import GEO, KEY, _h, _proof, _verify

REAL = json.loads((Path(__file__).parent / "data" / "app_attest" / "real_device.json").read_text())
APP_ID = "ABCDE12345.mv.msro.liminal"


def _b(text: str) -> bytes:
    return devices._b64(text)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _sha(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# ------------------------------------------------------------------------------ a real iPhone's samples

REAL_AT = dt.datetime(2021, 4, 14, 9, 55, 20, tzinfo=dt.timezone.utc)
REAL_POLICY = app_attest.Policy(REAL["app_id"], allow_develop=True)


def _real():
    a = REAL["attestation"]
    return _b(a["attestationObject"]), _b(a["keyId"]), _b(a["clientData"])


def test_the_bundled_root_is_apples():
    [root] = app_attest.apple_roots()
    assert root.subject.rfc4514_string() == "ST=California,O=Apple Inc.,CN=Apple App Attestation Root CA"
    assert root.fingerprint(hashes.SHA256()).hex() == "1cb9823ba28ba6ad2d33a006941de2ae4f513ef1d4e831b9f7e0fa7b6242c932"


def test_a_real_iphones_attestation_verifies_to_apples_root():
    got = app_attest.verify_attestation(*_real(), REAL_POLICY, now=REAL_AT)
    key = serialization.load_der_public_key(got.public_key_spki)
    point = key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert point.hex() == REAL["public_key_x962"]
    assert (got.environment, got.counter) == ("development", 0)
    assert got.device_key_id == "sensor:ios-" + _b(REAL["attestation"]["keyId"]).hex()[:24]


def test_a_real_iphones_assertion_verifies_and_is_never_accepted_twice():
    spki = app_attest.verify_attestation(*_real(), REAL_POLICY, now=REAL_AT).public_key_spki
    a = REAL["assertion"]
    assert app_attest.verify_assertion(_b(a["assertion"]), _b(a["clientData"]), spki, REAL["app_id"]) == 3
    assert app_attest.verify_assertion(_b(a["assertion"]), _b(a["clientData"]), spki, REAL["app_id"], {1, 2, 4, 9}) == 3
    with pytest.raises(app_attest.AppAttestError, match="replay"):
        app_attest.verify_assertion(_b(a["assertion"]), _b(a["clientData"]), spki, REAL["app_id"], {3})
    with pytest.raises(app_attest.AppAttestError, match="too old"):
        app_attest.verify_assertion(_b(a["assertion"]), _b(a["clientData"]), spki, REAL["app_id"], {5000})
    with pytest.raises(app_attest.AppAttestError, match="bad signature"):
        app_attest.verify_assertion(_b(a["assertion"]), b'{"challenge":"something else"}', spki, REAL["app_id"])
    with pytest.raises(app_attest.AppAttestError, match="another app"):
        app_attest.verify_assertion(_b(a["assertion"]), _b(a["clientData"]), spki, APP_ID)


def test_counters_may_come_out_of_order_but_never_twice():
    assert app_attest.counter_problem(7, {1, 2, 9}) is None                  # a queued report, sealed earlier
    assert "replay" in app_attest.counter_problem(9, {1, 2, 9})
    assert "zero" in app_attest.counter_problem(0, set())
    assert "too old" in app_attest.counter_problem(10, {1010}, window=1000)
    assert app_attest.counter_problem(11, {1010}, window=1000) is None


@pytest.mark.parametrize("change,why", [
    ({"policy": app_attest.Policy(REAL["app_id"])}, "development build"),
    ({"policy": app_attest.Policy("35MFYY2JY5.co.chiff.other", allow_develop=True)}, "another app"),
    ({"policy": app_attest.Policy("", allow_develop=True)}, "not configured"),
    ({"client_data": b"another challenge"}, "nonce mismatch"),
    ({"key_id": _sha(b"another key")}, "key identifier"),
    ({"now": REAL_AT + dt.timedelta(days=4)}, "not valid now"),
    ({"roots": [test_devices._Ca("Not Apple").cert]}, "Apple App Attestation root"),
])
def test_a_real_attestation_is_refused_when_anything_differs(change, why):
    obj, key_id, client_data = _real()
    kw = {"key_id": key_id, "client_data": client_data, "policy": REAL_POLICY, "now": REAL_AT, "roots": None, **change}
    with pytest.raises(app_attest.AppAttestError, match=why):
        app_attest.verify_attestation(obj, kw["key_id"], kw["client_data"], kw["policy"], kw["roots"], kw["now"])


# ------------------------------------------------------------------ synthetic iPhones (our own test root)

def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _nonce_extension(nonce: bytes) -> bytes:
    # SEQUENCE { [1] EXPLICIT OCTET STRING nonce }
    return test_devices._seq(test_devices._tagged(1, test_devices._oct(nonce)))


class Apple:
    """Apple's App Attest CA under a test root: a P-384 root and intermediate, like the real ones."""

    def __init__(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.root_key = ec.generate_private_key(ec.SECP384R1())
        self.root = self._ca("Test App Attestation Root CA", self.root_key, self.root_key, _name("Test App Attestation Root CA"), now)
        self.inter_key = ec.generate_private_key(ec.SECP384R1())
        self.inter = self._ca("Test App Attestation CA 1", self.inter_key, self.root_key, self.root.subject, now)

    @staticmethod
    def _ca(cn, key, issuer_key, issuer_name, now):
        return (x509.CertificateBuilder().subject_name(_name(cn)).issuer_name(issuer_name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .sign(issuer_key, hashes.SHA384()))


class IPhone:
    """An iPhone's Secure Enclave and App Attest, made with the test CA: attests keys, makes assertions."""

    def __init__(self, apple: Apple):
        self.apple = apple
        self.counter = 0

    def attest(self, challenge: bytes, *, app_id=APP_ID, aaguid=app_attest.AAGUID_PRODUCTION, counter=0,
               nonce=None, key_id=None, cred_id=None, issuer=None, fmt="apple-appattest", with_nonce=True):
        self.key = ec.generate_private_key(ec.SECP256R1())
        point = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.key_id = _sha(point)
        self.counter = 0
        cid = cred_id if cred_id is not None else self.key_id
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: point[1:33], -3: point[33:]})
        auth = (_sha(app_id.encode()) + bytes([0x40]) + counter.to_bytes(4, "big") + aaguid
                + len(cid).to_bytes(2, "big") + cid + cose)
        now = dt.datetime.now(dt.timezone.utc)
        inter_cert, inter_key = issuer or (self.apple.inter, self.apple.inter_key)
        builder = (x509.CertificateBuilder().subject_name(_name(self.key_id.hex())).issuer_name(inter_cert.subject)
                   .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=3)))
        if with_nonce:
            n = nonce if nonce is not None else _sha(auth + _sha(challenge))
            builder = builder.add_extension(x509.UnrecognizedExtension(app_attest.NONCE_OID, _nonce_extension(n)), critical=False)
        leaf = builder.sign(inter_key, hashes.SHA256())
        obj = cbor2.dumps({"fmt": fmt, "attStmt": {
            "x5c": [leaf.public_bytes(serialization.Encoding.DER), inter_cert.public_bytes(serialization.Encoding.DER)],
            "receipt": b"receipt"}, "authData": auth})
        return {"keyId": _b64(key_id if key_id is not None else self.key_id), "attestationObject": _b64(obj)}

    def assertion(self, text: str, *, counter=None, app_id=APP_ID) -> str:
        self.counter = counter if counter is not None else self.counter + 1
        auth = _sha(app_id.encode()) + bytes([0x00]) + self.counter.to_bytes(4, "big")
        signature = self.key.sign(_sha(auth + _sha(text.encode())), ec.ECDSA(hashes.SHA256()))
        return _b64(cbor2.dumps({"signature": signature, "authenticatorData": auth}))


@pytest.fixture
def apple():
    return Apple()


def _attest(apple, challenge=b"ch", policy=None, **kw):
    phone = IPhone(apple)
    made = phone.attest(challenge, **kw)
    got = app_attest.verify_attestation(base64.b64decode(made["attestationObject"]), base64.b64decode(made["keyId"]),
                                        challenge, policy or app_attest.Policy(APP_ID), [apple.root])
    return phone, got


def test_a_production_key_under_the_test_root_verifies(apple):
    phone, got = _attest(apple)
    assert (got.environment, got.key_id, got.app_id) == ("production", phone.key_id, APP_ID)
    assert got.summary()["platform"] == "ios" and got.summary()["security_level"] == "secure_enclave"


def test_a_development_key_needs_the_flag(apple):
    with pytest.raises(app_attest.AppAttestError, match="development build"):
        _attest(apple, aaguid=app_attest.AAGUID_DEVELOP)
    _, got = _attest(apple, aaguid=app_attest.AAGUID_DEVELOP, policy=app_attest.Policy(APP_ID, allow_develop=True))
    assert got.environment == "development"


def test_a_chain_signed_by_another_intermediate_is_refused(apple):
    stranger = Apple()          # a whole other CA: its intermediate is not Apple's
    with pytest.raises(app_attest.AppAttestError, match="Apple App Attestation root"):
        _attest(apple, issuer=(stranger.inter, stranger.inter_key))
    # a leaf signed by another key, but naming the right intermediate
    with pytest.raises(app_attest.AppAttestError, match="not signed by the next one"):
        _attest(apple, issuer=(apple.inter, stranger.inter_key))


@pytest.mark.parametrize("kw,why", [
    ({"nonce": b"\x00" * 32}, "nonce mismatch"),
    ({"with_nonce": False}, "carries no nonce"),
    ({"app_id": "ZZZZZ99999.mv.msro.liminal"}, "another app"),
    ({"counter": 1}, "counter is not zero"),
    ({"aaguid": b"\x00" * 16}, "unknown AAGUID"),
    ({"key_id": _sha(b"not the key")}, "key identifier"),
    ({"cred_id": _sha(b"not the key")}, "credential id"),
    ({"fmt": "packed"}, "not an App Attest"),
])
def test_synthetic_attestations_that_differ_are_refused(apple, kw, why):
    with pytest.raises(app_attest.AppAttestError, match=why):
        _attest(apple, **kw)


def test_the_attestation_must_be_cbor_and_complete(apple):
    for junk in (b"", b"\xff\xff", cbor2.dumps([1, 2]), cbor2.dumps({"fmt": "apple-appattest", "attStmt": {}, "authData": b""})):
        with pytest.raises(app_attest.AppAttestError):
            app_attest.verify_attestation(junk, b"k", b"ch", app_attest.Policy(APP_ID), [apple.root])
    short = cbor2.dumps({"fmt": "apple-appattest", "attStmt": {"x5c": [b"a", b"b"]}, "authData": b"\x00" * 40})
    with pytest.raises(app_attest.AppAttestError, match="no credential"):
        app_attest.verify_attestation(short, b"k", b"ch", app_attest.Policy(APP_ID), [apple.root])


def test_assertions_check_signature_app_and_counter(apple):
    phone, got = _attest(apple)
    spki = got.public_key_spki
    a1 = base64.b64decode(phone.assertion("report one"))
    assert app_attest.verify_assertion(a1, b"report one", spki, APP_ID) == 1
    with pytest.raises(app_attest.AppAttestError, match="replay"):
        app_attest.verify_assertion(a1, b"report one", spki, APP_ID, {1})
    with pytest.raises(app_attest.AppAttestError, match="bad signature"):
        app_attest.verify_assertion(a1, b"report two", spki, APP_ID)
    other, _ = _attest(apple)
    with pytest.raises(app_attest.AppAttestError, match="bad signature"):
        app_attest.verify_assertion(base64.b64decode(other.assertion("report one")), b"report one", spki, APP_ID)
    with pytest.raises(app_attest.AppAttestError, match="another app"):
        app_attest.verify_assertion(base64.b64decode(phone.assertion("x", app_id="Z.other")), b"x", spki, APP_ID)
    with pytest.raises(app_attest.AppAttestError):
        app_attest.verify_assertion(cbor2.dumps({"authenticatorData": b"\x00" * 37}), b"x", spki, APP_ID)


# ------------------------------------------------------------------------------- through the API

@pytest.fixture
def ienv(monkeypatch, apple):
    monkeypatch.setattr(devices, "APPLE_ROOTS", [apple.root])
    monkeypatch.setattr(devices, "_counters", {})
    monkeypatch.setenv("KAORI_APPLE_APP_ID", APP_ID)
    monkeypatch.delenv("KAORI_APPLE_ALLOW_DEVELOP", raising=False)
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    monkeypatch.setenv("KAORI_NAME_KEY", secrets.token_hex(32))
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, evidence_store=InMemoryEvidenceStore(bucket_name="b"),
                     generalist_client=None)
    app.state.ai_reader = lambda claim_type_id, image: {"values": {"cover": "overcast", "raining": False}, "probs": {}, "relevance": 0.9}
    app.state.ai_sync = True
    for who in ("madin", "aisha"):
        antalya.seed_member(flow, "user:" + who, callsign=who.title())
    return TestClient(app), flow, IPhone(apple)


def _link_ios(client, phone, who="madin", **kw):
    ch = client.post("/v1/devices/challenge", headers=_h(who)).json()["challenge"]
    return client.post("/v1/devices/link", headers=_h(who), json={"platform": "ios", "challenge": ch, **phone.attest(ch.encode(), **kw)})


class _Signer:
    """test_devices._report signs with phone.sign(text); an iPhone sends an assertion in its place."""

    def __init__(self, phone, **kw):
        self.phone, self.kw, self.last = phone, kw, None

    def sign(self, text):
        self.last = text
        return self.phone.assertion(text, **self.kw)


_HOURS = itertools.count()       # one report per person per truth key: each report its own hour


def _report(client, signer, who="madin", *, device_id=None, tamper=None, sign=True, field="assertion"):
    """test_devices._report, each time with a new photo in a new hour (a new truth key)."""
    hour = next(_HOURS) % 24
    key = KEY.replace("T09:00Z", f"T{hour:02d}:00Z")
    img = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 160, 220)).save(img, format="JPEG", comment=secrets.token_bytes(8))
    ref = client.post("/v1/evidence", headers=_h(who), files={"file": ("s.jpg", img.getvalue(), "image/jpeg")}).json()
    obs = {"claim_type": "earth.sky_cover.v1", "reported_at": f"2026-10-05T{hour:02d}:00:30.000Z", "geo": GEO,
           "payload": {"cover": "overcast", "raining": False}, "evidence_refs": [ref]}
    if sign:
        said = {"truth_key": key, "claim_type": obs["claim_type"], "reported_at": obs["reported_at"], "geo": GEO,
                "payload": obs["payload"], "evidence_sha256": ref["sha256"], **(tamper or {})}
        text = json.dumps(said, separators=(",", ":"))
        obs["device_proof"] = {"platform": "ios", "device_id": device_id, "signed": text, field: signer.sign(text)}
    return client.post("/v1/compile", headers=_h(who), json={"truth_key": key, "claim_type_id": "earth.sky_cover.v1", "observations": [obs]})


def _report_ios(client, phone, device_id, who="madin", **kw):
    return _report(client, _Signer(phone, **kw), who=who, device_id=device_id)


def test_an_iphone_links_like_an_android_phone(ienv):
    client, flow, phone = ienv
    r = _link_ios(client, phone)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] == "sensor:ios-" + phone.key_id.hex()[:24]
    assert (body["platform"], body["security_level"], body["app_attest_environment"], body["app_cert_ok"]) == \
        ("ios", "secure_enclave", "production", True)
    [linked] = flow.store.get_by_type(SignalTypes.DEVICE_LINKED)
    assert linked.agent_id == "user:madin" and linked.object_id == body["device_id"]
    assert (linked.payload["counter"], linked.payload["app_id"], base64.b64decode(linked.payload["key_id"])) == (0, APP_ID, phone.key_id)
    me = client.get("/v1/me", headers=_h("madin")).json()
    assert me["device"]["device_id"] == body["device_id"] and me["device"]["platform"] == "ios"


@pytest.mark.parametrize("kw,env,why", [
    ({"app_id": "ZZZZZ99999.mv.msro.liminal"}, {}, "another app"),
    ({"aaguid": app_attest.AAGUID_DEVELOP}, {}, "development build"),
    ({}, {"KAORI_APPLE_APP_ID": ""}, "not configured"),
    ({"nonce": b"\x01" * 32}, {}, "nonce mismatch"),
])
def test_iphones_that_fail_are_refused_and_it_is_recorded(ienv, monkeypatch, kw, env, why):
    client, flow, phone = ienv
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    r = _link_ios(client, phone, **kw)
    assert r.status_code == 403
    assert why in r.json()["detail"]["reasons"][0]
    assert not flow.store.get_by_type(SignalTypes.DEVICE_LINKED)
    [refused] = flow.store.get_by_type(SignalTypes.DEVICE_LINK_REFUSED)
    assert refused.payload["platform"] == "ios" and why in refused.payload["reasons"][0]


def test_a_development_build_links_when_allowed(ienv, monkeypatch):
    client, _, phone = ienv
    monkeypatch.setenv("KAORI_APPLE_ALLOW_DEVELOP", "1")
    r = _link_ios(client, phone, aaguid=app_attest.AAGUID_DEVELOP)
    assert r.status_code == 200 and r.json()["app_attest_environment"] == "development"


def test_an_iphone_link_needs_its_challenge_and_its_fields(ienv):
    client, _, phone = ienv
    ch = client.post("/v1/devices/challenge", headers=_h("madin")).json()["challenge"]
    made = phone.attest(ch.encode())
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"platform": "ios", "challenge": ch}).status_code == 400
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"platform": "windows", "challenge": ch, **made}).status_code == 400
    assert client.post("/v1/devices/link", headers=_h("aisha"), json={"platform": "ios", "challenge": ch, **made}).status_code == 400
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"platform": "ios", "challenge": ch, **made}).status_code == 200
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"platform": "ios", "challenge": ch, **made}).status_code == 400


def test_a_report_signed_by_the_linked_iphone_is_device_signed_and_its_counter_kept(ienv):
    client, flow, phone = ienv
    device_id = _link_ios(client, phone).json()["device_id"]
    assert _report_ios(client, phone, device_id).status_code == 202
    assert _proof(flow) == [{"device_id": device_id, "verified": True, "reason": None, "counter": 1}]
    [prov] = flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED)
    assert prov.payload["checks"]["device_signed"] is True
    assert _report_ios(client, phone, device_id, who="madin").status_code == 202
    assert _proof(flow)[-1]["verified"] is True and _proof(flow)[-1]["counter"] == 2


def test_queued_reports_may_arrive_out_of_order_but_a_replay_never_counts_even_after_a_restart(ienv, monkeypatch):
    client, flow, phone = ienv
    device_id = _link_ios(client, phone).json()["device_id"]
    assert _report_ios(client, phone, device_id, counter=5).status_code == 202
    monkeypatch.setattr(devices, "_counters", {})          # a new process: the ledger still knows 5
    assert _report_ios(client, phone, device_id, counter=5).status_code == 202      # replayed
    assert _report_ios(client, phone, device_id, counter=4).status_code == 202      # sealed earlier, sent later
    assert _report_ios(client, phone, device_id, counter=4).status_code == 202      # replayed
    assert _report_ios(client, phone, device_id, counter=2000).status_code == 202
    assert _report_ios(client, phone, device_id, counter=6).status_code == 202      # far too old
    assert [(p["verified"], p.get("counter")) for p in _proof(flow)] == \
        [(True, 5), (False, None), (True, 4), (False, None), (True, 2000), (False, None)]
    assert "replay" in _proof(flow)[1]["reason"] and "replay" in _proof(flow)[3]["reason"]
    assert "too old" in _proof(flow)[5]["reason"]


def test_an_iphone_signature_over_something_else_or_from_another_key_does_not_count(ienv, apple):
    client, flow, phone = ienv
    device_id = _link_ios(client, phone).json()["device_id"]
    r = _report(client, _Signer(phone), device_id=device_id, tamper={"payload": {"cover": "clear", "raining": False}})
    assert r.status_code == 202 and "payload" in _proof(flow)[-1]["reason"]
    other = IPhone(apple)
    other.attest(b"never linked")
    assert _report_ios(client, other, device_id).status_code == 202
    assert _proof(flow)[-1] == {"device_id": device_id, "verified": False, "reason": "bad signature"}


def test_when_required_an_iphone_is_held_to_the_android_rules(ienv, monkeypatch):
    client, flow, phone = ienv
    monkeypatch.setenv("KAORI_REQUIRE_DEVICE", "1")
    # unlinked: no evidence, no reports
    assert client.post("/v1/evidence", headers=_h("madin"), files={"file": ("s.jpg", b"x", "image/jpeg")}).status_code == 403
    # a refused iPhone stays unlinked
    assert _link_ios(client, phone, app_id="ZZZZZ99999.mv.msro.liminal").status_code == 403
    assert client.post("/v1/evidence", headers=_h("madin"), files={"file": ("s.jpg", b"x", "image/jpeg")}).status_code == 403
    device_id = _link_ios(client, phone).json()["device_id"]
    assert _report_ios(client, phone, device_id).status_code == 202
    r = _report_ios(client, phone, device_id, counter=1)                 # a replayed counter
    assert r.status_code == 403 and "signed" in r.json()["detail"]
    r = _report(client, phone, device_id=device_id, sign=False)
    assert r.status_code == 403


def test_an_iphone_replaces_an_android_phone(ienv, monkeypatch):
    client, flow, iphone = ienv
    android = test_devices.Phone()
    monkeypatch.setattr(devices, "TRUST", test_devices.attestation.TrustData([android.root.spki], {}))
    monkeypatch.setenv("KAORI_ANDROID_CERT_SHA256", test_devices.APP_CERT)
    first = test_devices._link(client, android).json()
    assert first["platform"] == "android"
    second = _link_ios(client, iphone).json()["device_id"]
    [unlinked] = flow.store.get_by_type(SignalTypes.DEVICE_UNLINKED)
    assert unlinked.object_id == first["device_id"] and unlinked.payload["by"] == second


def test_an_nfc_hold_signed_by_the_inviters_iphone_is_verified(ienv):
    client, flow, phone = ienv
    linked = _link_ios(client, phone).json()
    made = client.post("/v1/invites", headers=_h("madin"), json={"callsign": "Madin", "invitee_name": "Zara"}).json()
    body = {"code": made["code"], "name": "Zara", "relationship": "friend", "known_for": "1_5y", "device_id": "install-zara-0001"}
    assert client.post("/v1/invites/redeem", headers=_h("zara"), json=body).status_code == 200
    hold = client.post("/v1/joining/hold", headers=_h("zara")).json()
    text = antalya.HOLD_TEXT.format(invite=made["id"], nonce=hold["nonce"], hold_ms=3000)
    proof = {"method": "nfc_hold", "nonce": hold["nonce"], "hold_ms": 3000,
             "device": {"platform": "ios", "device_id": linked["device_id"], "assertion": phone.assertion(text)}}
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h("madin"), json={"proof": proof}).status_code == 200
    [confirmed] = flow.store.get_by_type(SignalTypes.INVITE_CONFIRMED)
    assert confirmed.payload["device_verified"] is True and confirmed.payload["device_counter"] == 1
    # the hold's counter is in the ledger: a report with the same counter is a replay
    devices._counters.clear()
    assert _report_ios(client, phone, linked["device_id"], counter=1).status_code == 202
    assert "replay" in _proof(flow)[-1]["reason"]


def test_assertions_may_be_url_safe_base64(ienv):
    client, flow, phone = ienv
    device_id = _link_ios(client, phone).json()["device_id"]

    class UrlSafe(_Signer):
        def sign(self, text):
            return super().sign(text).replace("+", "-").replace("/", "_").rstrip("=")

    assert _report(client, UrlSafe(phone), device_id=device_id, field="signature").status_code == 202
    assert _proof(flow)[-1]["verified"] is True


