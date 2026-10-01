"""Linking a phone by Android Key Attestation, and reports signed by it (devices.py, attestation.py)."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya, attestation, devices
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

DATA = Path(__file__).parent / "data" / "attestation"
PACKAGE = "mv.msro.liminal"
APP_CERT = hashlib.sha256(b"msro app signing certificate").hexdigest()


# ------------------------------------------------------------------------------- Google's real chains

def _google_chain(name):
    return [(DATA / name / f"cert{i}.der").read_bytes() for i in range(4)]


@pytest.mark.parametrize("name", ["google_ec_tee", "google_rsa_tee"])
def test_real_google_chains_are_read_and_trusted(name):
    """Real chains from a development phone: they verify to Google's root, and its facts are read right."""
    lenient = attestation.Policy(package="", cert_sha256=[], require_verified_boot=False)
    got = attestation.verify_chain(_google_chain(name), b"abc", lenient, attestation.TrustData(fetch=False))
    assert got.ok
    assert (got.security_level, got.verified_boot_state, got.device_locked) == ("tee", "unverified", False)
    assert (got.attestation_version, got.os_patch_level) == (3, 201907)
    assert got.device_key_id.startswith("sensor:android-")


def test_real_google_chain_from_an_unlocked_phone_fails_the_policy():
    strict = attestation.Policy(package="", cert_sha256=[])
    got = attestation.verify_chain(_google_chain("google_ec_tee"), b"abc", strict, attestation.TrustData(fetch=False))
    assert got.problems == ["the phone is not running verified software with a locked bootloader (rooted or modified)"]


def test_real_google_chain_with_another_challenge_is_refused():
    with pytest.raises(attestation.AttestationError, match="challenge"):
        attestation.verify_chain(_google_chain("google_ec_tee"), b"not-abc", attestation.Policy("", []),
                                 attestation.TrustData(fetch=False))


def test_a_chain_from_an_untrusted_root_is_refused():
    chain = _google_chain("google_ec_tee")
    other_root = _Ca("Not Google")
    with pytest.raises(attestation.AttestationError, match="Google attestation root"):
        attestation.verify_chain(chain, b"abc", attestation.Policy("", []), attestation.TrustData([other_root.spki], {}))


def test_a_revoked_certificate_is_refused():
    chain = _google_chain("google_ec_tee")
    serial = format(attestation.parse_cert(chain[1]).serial, "x")
    trust = attestation.TrustData(attestation.TrustData(fetch=False).get()[0], {serial: {"status": "REVOKED"}})
    with pytest.raises(attestation.AttestationError, match="revoked"):
        attestation.verify_chain(chain, b"abc", attestation.Policy("", []), trust)


# --------------------------------------------------------------- synthetic chains (our own test root)

def _der(tag: int, body: bytes, cls: int = 0, constructed: bool = False) -> bytes:
    first = (cls << 6) | (0x20 if constructed else 0)
    if tag < 31:
        head = bytes([first | tag])
    else:
        parts = []
        while True:
            parts.insert(0, tag & 0x7F)
            tag >>= 7
            if not tag:
                break
        head = bytes([first | 0x1F] + [p | 0x80 for p in parts[:-1]] + [parts[-1]])
    n = len(body)
    length = bytes([n]) if n < 0x80 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return head + length + body


def _int(n): return _der(2, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))
def _enum(n): return _der(10, bytes([n]))
def _oct(b): return _der(4, b)
def _seq(*xs): return _der(16, b"".join(xs), constructed=True)
def _set(*xs): return _der(17, b"".join(xs), constructed=True)
def _bool(v): return _der(1, b"\xff" if v else b"\x00")
def _tagged(tag, inner): return _der(tag, inner, cls=2, constructed=True)


def key_description(challenge: bytes, *, level=1, locked=True, boot=0, package=PACKAGE, cert=APP_CERT) -> bytes:
    app_id = _seq(_set(_seq(_oct(package.encode()), _int(7))), _set(_oct(bytes.fromhex(cert))))
    software = _seq(_tagged(709, _oct(app_id)))
    hardware = _seq(
        _tagged(704, _seq(_oct(b"\x11" * 32), _bool(locked), _enum(boot), _oct(b"\x22" * 32))),
        _tagged(705, _int(150000)), _tagged(706, _int(202609)),
    )
    return _seq(_int(200), _enum(level), _int(200), _enum(level), _oct(challenge), _oct(b""), software, hardware)


class _Ca:
    def __init__(self, name, issuer=None, serial=None):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        issuer = issuer or self
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(self.name).issuer_name(issuer.name)
                     .public_key(self.key.public_key()).serial_number(serial or x509.random_serial_number())
                     .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                     .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                     .sign(issuer.key, hashes.SHA256()))
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.spki = self.key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


class Phone:
    """A phone's secure hardware under our test root: makes keys, attests them, signs with them."""

    def __init__(self, root=None):
        self.root = root or _Ca("Test attestation root")
        self.inter = _Ca("Test intermediate", issuer=self.root)

    def make_key(self, challenge: bytes, **kd):
        self.key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.timezone.utc)
        leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Android Keystore Key")]))
                .issuer_name(self.inter.name).public_key(self.key.public_key()).serial_number(1)
                .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier(attestation.KEY_DESCRIPTION_OID),
                                                          key_description(challenge, **kd)), critical=False)
                .sign(self.inter.key, hashes.SHA256()))
        return [base64.b64encode(c).decode() for c in (leaf.public_bytes(serialization.Encoding.DER), self.inter.der, self.root.der)]

    def sign(self, text: str) -> str:
        return base64.b64encode(self.key.sign(text.encode(), ec.ECDSA(hashes.SHA256()))).decode()


@pytest.fixture
def phone(monkeypatch):
    p = Phone()
    monkeypatch.setattr(devices, "TRUST", attestation.TrustData([p.root.spki], {}))
    monkeypatch.setenv("KAORI_ANDROID_CERT_SHA256", APP_CERT)
    return p


def _verify(token: str) -> str:
    if not token.startswith("tok-"):
        raise AuthError("invalid")
    return "user:" + token[4:]


def _h(name): return {"Authorization": f"Bearer tok-{name}"}


@pytest.fixture
def env(monkeypatch, phone):
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, evidence_store=InMemoryEvidenceStore(bucket_name="b"),
                     generalist_client=None)
    app.state.ai_reader = lambda claim_type_id, image: {"values": {"cover": "overcast", "raining": False}, "probs": {}, "relevance": 0.9}
    app.state.ai_sync = True
    for who in ("madin", "aisha", "val"):
        antalya.seed_member(flow, "user:" + who, callsign=who.title())
    return TestClient(app), flow, phone


def _link(client, phone, who="madin", **kd):
    ch = client.post("/v1/devices/challenge", headers=_h(who)).json()["challenge"]
    return client.post("/v1/devices/link", headers=_h(who), json={"challenge": ch, "chain": phone.make_key(ch.encode(), **kd)})


def test_a_genuine_phone_links_and_becomes_its_own_agent(env):
    client, flow, phone = env
    r = _link(client, phone)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"].startswith("sensor:android-")
    assert (body["security_level"], body["verified_boot_state"], body["device_locked"], body["app_cert_ok"]) == ("tee", "verified", True, True)
    [linked] = flow.store.get_by_type(SignalTypes.DEVICE_LINKED)
    assert linked.agent_id == "user:madin" and linked.object_id == body["device_id"]
    me = client.get("/v1/me", headers=_h("madin")).json()
    assert me["member"] and me["device"]["device_id"] == body["device_id"]


@pytest.mark.parametrize("kd,reason", [
    ({"level": 0}, "not in secure hardware"),
    ({"locked": False}, "locked bootloader"),
    ({"boot": 2}, "locked bootloader"),
    ({"package": "com.evil.copy"}, "another app"),
    ({"cert": hashlib.sha256(b"someone else").hexdigest()}, "not signed with MSRO's key"),
])
def test_phones_that_fail_the_policy_are_refused_and_it_is_recorded(env, kd, reason):
    client, flow, phone = env
    r = _link(client, phone, **kd)
    assert r.status_code == 403
    assert any(reason in x for x in r.json()["detail"]["reasons"])
    assert not flow.store.get_by_type(SignalTypes.DEVICE_LINKED)
    [refused] = flow.store.get_by_type(SignalTypes.DEVICE_LINK_REFUSED)
    assert refused.agent_id == "user:madin" and any(reason in x for x in refused.payload["reasons"])


def test_a_challenge_works_once_and_only_for_whoever_asked(env):
    client, _, phone = env
    ch = client.post("/v1/devices/challenge", headers=_h("madin")).json()["challenge"]
    chain = phone.make_key(ch.encode())
    assert client.post("/v1/devices/link", headers=_h("aisha"), json={"challenge": ch, "chain": chain}).status_code == 400
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"challenge": ch, "chain": chain}).status_code == 200
    assert client.post("/v1/devices/link", headers=_h("madin"), json={"challenge": ch, "chain": chain}).status_code == 400


def test_a_key_made_for_another_challenge_is_refused(env):
    client, _, phone = env
    ch = client.post("/v1/devices/challenge", headers=_h("madin")).json()["challenge"]
    r = client.post("/v1/devices/link", headers=_h("madin"), json={"challenge": ch, "chain": phone.make_key(b"old challenge")})
    assert r.status_code == 403 and "challenge" in r.json()["detail"]["reasons"][0]


def test_a_new_phone_replaces_the_old_one(env):
    client, flow, _ = env
    first = _link(client, env[2]).json()["device_id"]
    second = _link(client, env[2]).json()["device_id"]      # the same test root, a new key: a new phone
    assert first != second
    [unlinked] = flow.store.get_by_type(SignalTypes.DEVICE_UNLINKED)
    assert unlinked.object_id == first and unlinked.payload == {"reason": "replaced", "by": second}
    assert client.get("/v1/me", headers=_h("madin")).json()["device"]["device_id"] == second


def test_non_members_cannot_link(env):
    client, _, _ = env
    assert client.post("/v1/devices/challenge", headers=_h("stranger")).status_code == 403


# ------------------------------------------------------------------------------------- signed reports

KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
GEO = {"lat": 36.8969, "lon": 30.7133}


def _report(client, phone, who="madin", *, device_id=None, tamper=None, sign=True):
    img = io.BytesIO()
    Image.new("RGB", (32, 24), (120, 160, 220)).save(img, format="JPEG", comment=who.encode())
    data = img.getvalue()
    ref = client.post("/v1/evidence", headers=_h(who), files={"file": ("s.jpg", data, "image/jpeg")}).json()
    obs = {"claim_type": "earth.sky_cover.v1", "reported_at": "2026-10-05T09:00:30.000Z", "geo": GEO,
           "payload": {"cover": "overcast", "raining": False}, "evidence_refs": [ref]}
    if sign:
        said = {"truth_key": KEY, "claim_type": obs["claim_type"], "reported_at": obs["reported_at"], "geo": GEO,
                "payload": obs["payload"], "evidence_sha256": ref["sha256"], **(tamper or {})}
        text = json.dumps(said, separators=(",", ":"))
        obs["device_proof"] = {"device_id": device_id, "signed": text, "signature": phone.sign(text)}
    return client.post("/v1/compile", headers=_h(who), json={"truth_key": KEY, "claim_type_id": "earth.sky_cover.v1", "observations": [obs]})


def _proof(flow):
    return [s.payload["device_proof"] for s in flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED)]


def test_a_report_signed_by_the_linked_phone_is_marked_device_signed(env):
    client, flow, phone = env
    device_id = _link(client, phone).json()["device_id"]
    r = _report(client, phone, device_id=device_id)
    assert r.status_code == 202, r.text
    assert _proof(flow) == [{"device_id": device_id, "verified": True, "reason": None}]
    [prov] = flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED)
    assert prov.payload["checks"]["device_signed"] is True


@pytest.mark.parametrize("tamper,why", [
    ({"payload": {"cover": "clear", "raining": False}}, "payload"),
    ({"geo": {"lat": 0.0, "lon": 0.0}}, "geo"),
    ({"reported_at": "2026-10-05T08:00:30.000Z"}, "reported_at"),
    ({"truth_key": "earth:sky_cover:h3:other:surface:2026-10-05T09:00Z"}, "truth_key"),
])
def test_a_signature_over_something_else_does_not_count(env, tamper, why):
    client, flow, phone = env
    device_id = _link(client, phone).json()["device_id"]
    assert _report(client, phone, device_id=device_id, tamper=tamper).status_code == 202
    [p] = _proof(flow)
    assert not p["verified"] and why in p["reason"]


def test_someone_elses_phone_or_a_forged_signature_does_not_count(env):
    client, flow, phone = env
    madins = _link(client, phone).json()["device_id"]
    other = Phone(phone.root)
    other.make_key(b"x")                                     # a key that was never linked
    assert _report(client, other, who="aisha", device_id=madins).status_code == 202
    assert _proof(flow)[-1]["reason"] == "not this person's linked phone"


def test_when_required_reports_and_readings_need_a_linked_phone(env, monkeypatch):
    client, flow, phone = env
    monkeypatch.setenv("KAORI_REQUIRE_DEVICE", "1")
    assert client.post("/v1/evidence", headers=_h("aisha"), files={"file": ("s.jpg", b"x", "image/jpeg")}).status_code == 403
    device_id = _link(client, phone).json()["device_id"]
    assert _report(client, phone, device_id=device_id).status_code == 202
    r = _report(client, phone, device_id=device_id, tamper={"payload": {"cover": "clear", "raining": False}})
    assert r.status_code == 403 and "signed" in r.json()["detail"]
    assert client.get("/v1/me", headers=_h("madin")).json()["device_required"] is True
