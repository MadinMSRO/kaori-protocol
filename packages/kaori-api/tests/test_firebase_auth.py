"""Firebase ID tokens map to user:{uid}, verified offline against Google's certificates."""
from __future__ import annotations

import datetime as dt
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt, jwt

from kaori_api.app import create_app
from kaori_api.auth import AuthError, FirebaseCerts, agent_id_from_firebase_token
from kaori_flow import FlowCore, InMemorySignalStore

PROJECT = "msro-kaori-sandbox"
UID = "Xq3fK9pLm2RtYw7vBn4cJd8sHa1z"


def _key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.system.gserviceaccount.com")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return pem_key, cert.public_bytes(serialization.Encoding.PEM).decode()


KEY_PEM, CERT_PEM = _key_and_cert()
OTHER_KEY_PEM, _ = _key_and_cert()


def _token(kid="k1", key=KEY_PEM, **overrides):
    now = int(time.time())
    claims = {"iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT, "sub": UID,
              "user_id": UID, "auth_time": now - 60, "iat": now - 30, "exp": now + 3000}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(crypt.RSASigner.from_string(key, key_id=kid), claims).decode()


class _Fetch:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"k1": CERT_PEM}, 3600.0


def test_valid_token_maps_to_uid():
    assert agent_id_from_firebase_token(_token(), PROJECT, FirebaseCerts(_Fetch())) == f"user:{UID}"


@pytest.mark.parametrize("bad", [
    {"aud": "someone-elses-project"},
    {"iss": "https://securetoken.google.com/someone-elses-project"},
    {"iss": "https://accounts.google.com"},
    {"exp": int(time.time()) - 100, "iat": int(time.time()) - 4000},
    {"sub": ""},
    {"auth_time": int(time.time()) + 3600},
    {"auth_time": None},
])
def test_wrong_claims_are_refused(bad):
    with pytest.raises(AuthError):
        agent_id_from_firebase_token(_token(**bad), PROJECT, FirebaseCerts(_Fetch()))


def test_wrong_signature_and_unknown_key_are_refused():
    certs = FirebaseCerts(_Fetch())
    with pytest.raises(AuthError):
        agent_id_from_firebase_token(_token(key=OTHER_KEY_PEM), PROJECT, certs)
    with pytest.raises(AuthError):
        agent_id_from_firebase_token(_token(kid="not-a-google-key"), PROJECT, certs)
    for junk in ["", "not.a.jwt", "a.b"]:
        with pytest.raises(AuthError):
            agent_id_from_firebase_token(junk, PROJECT, certs)


def test_certificates_are_cached_and_refetched_for_a_new_key():
    fetch = _Fetch()
    certs = FirebaseCerts(fetch)
    for _ in range(5):
        agent_id_from_firebase_token(_token(), PROJECT, certs)
    assert fetch.calls == 1
    with pytest.raises(AuthError):
        agent_id_from_firebase_token(_token(kid="rotated"), PROJECT, certs)
    assert fetch.calls == 2


def test_api_uses_firebase_when_configured(monkeypatch):
    monkeypatch.setenv("FIREBASE_PROJECT_ID", PROJECT)
    monkeypatch.setattr("kaori_api.auth._fetch_firebase_certs", lambda: ({"k1": CERT_PEM}, 3600.0))
    client = TestClient(create_app(flow=FlowCore(store=InMemorySignalStore()), generalist_client=None))
    ok = client.get("/v1/standing/ai:generalist_v1", headers={"Authorization": f"Bearer {_token()}"})
    assert ok.status_code == 200, ok.text
    bad = client.get("/v1/standing/ai:generalist_v1", headers={"Authorization": f"Bearer {_token(aud='x')}"})
    assert bad.status_code == 401
