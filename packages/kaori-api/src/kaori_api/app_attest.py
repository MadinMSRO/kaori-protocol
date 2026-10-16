"""
Apple App Attest: what an iPhone's Secure Enclave vouches for about a key it made for our app.

The iPhone counterpart of attestation.py (Android Key Attestation). When Liminal links an iPhone it asks
DCAppAttestService for a new key and has Apple attest it for a challenge from Kaori. From the attestation
Kaori learns, without trusting the app:

- the key lives in a genuine Apple device's Secure Enclave and cannot leave it;
- it was made by our app, signed by our team and unmodified (the App ID: "<TEAM_ID>.<bundle id>");
- it was made just now, for this request (the challenge);
- whether it is a production key or one from a development build (the AAGUID).

Each report is then signed with an assertion: the Secure Enclave signs the report text with the key, and
a counter the Secure Enclave increments; Kaori never accepts the same counter twice for a key, so an
assertion cannot be replayed (reports queued offline may arrive out of order: see counter_problem).

Apple's steps, followed in order below:
https://developer.apple.com/documentation/devicecheck/validating-apps-that-connect-to-your-server

Lengths in authenticator data (WebAuthn layout): rpIdHash 32 | flags 1 | signCount 4 (big endian)
| attested credential data (attestations only): aaguid 16 | credentialId length 2 | credentialId | COSE key.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Sequence

import cbor2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from kaori_api.attestation import AttestationError, read_tlv

FORMAT = "apple-appattest"
NONCE_OID = x509.ObjectIdentifier("1.2.840.113635.100.8.2")
AAGUID_PRODUCTION = b"appattest" + b"\x00" * 7
AAGUID_DEVELOP = b"appattestdevelop"
BUNDLED_ROOT = Path(__file__).with_name("apple_app_attestation_root.pem")
FLAG_ATTESTED_CREDENTIAL_DATA = 0x40
MAX_CBOR_BYTES = 64 * 1024
# how far below the newest counter a queued report may still arrive: well beyond any offline outbox
COUNTER_WINDOW = 1000


class AppAttestError(AttestationError):
    """The attestation or assertion cannot be trusted."""


_bundled: Optional[List[x509.Certificate]] = None


def apple_roots() -> List[x509.Certificate]:
    """The Apple App Attestation Root CA, bundled with the package (it is valid until 2045)."""
    global _bundled
    if _bundled is None:
        _bundled = x509.load_pem_x509_certificates(BUNDLED_ROOT.read_bytes())
    return _bundled


# ----------------------------------------------------------------------------------- authenticator data

@dataclass
class AuthData:
    raw: bytes
    rp_id_hash: bytes
    flags: int
    counter: int
    aaguid: Optional[bytes] = None
    credential_id: Optional[bytes] = None


def parse_auth_data(raw: Any, *, attested: bool) -> AuthData:
    if not isinstance(raw, bytes) or len(raw) < 37:
        raise AppAttestError("authenticator data is too short")
    out = AuthData(raw=raw, rp_id_hash=raw[:32], flags=raw[32], counter=int.from_bytes(raw[33:37], "big"))
    if attested:
        if not out.flags & FLAG_ATTESTED_CREDENTIAL_DATA or len(raw) < 55:
            raise AppAttestError("authenticator data carries no credential")
        n = int.from_bytes(raw[53:55], "big")
        if len(raw) < 55 + n:
            raise AppAttestError("authenticator data is truncated")
        out.aaguid, out.credential_id = raw[37:53], raw[55:55 + n]
    return out


def _cbor_map(data: bytes, what: str) -> Dict[Any, Any]:
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_CBOR_BYTES:
        raise AppAttestError(f"{what} is missing or too large")
    try:
        obj = cbor2.loads(bytes(data))
    except Exception as exc:                      # cbor2 raises several types for malformed input
        raise AppAttestError(f"{what} is not CBOR") from exc
    if not isinstance(obj, dict):
        raise AppAttestError(f"{what} is not a CBOR map")
    return obj


# ------------------------------------------------------------------------------------------ the chain

def _check_chain(x5c: Sequence[bytes], roots: Sequence[x509.Certificate], now: datetime) -> x509.Certificate:
    """credCert, then the intermediate(s), each issued by the next and the last by an Apple root; all in date."""
    try:
        certs = [x509.load_der_x509_certificate(bytes(c)) for c in x5c]
    except (TypeError, ValueError) as exc:
        raise AppAttestError("unreadable certificate in x5c") from exc
    for cert in certs:
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise AppAttestError("a certificate in the chain is not valid now")
    for cert in certs[1:]:
        try:
            if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                raise AppAttestError("an intermediate certificate is not a CA")
        except x509.ExtensionNotFound as exc:
            raise AppAttestError("an intermediate certificate is not a CA") from exc

    def issued_by(child: x509.Certificate, parent: x509.Certificate) -> bool:
        try:
            child.verify_directly_issued_by(parent)
            return True
        except (ValueError, TypeError, InvalidSignature):
            return False

    for child, parent in zip(certs, certs[1:]):
        if not issued_by(child, parent):
            raise AppAttestError("a certificate in the chain is not signed by the next one")
    top = certs[-1]
    if not any(issued_by(top, root) and root.not_valid_before_utc <= now <= root.not_valid_after_utc for root in roots):
        raise AppAttestError("the chain does not end at the Apple App Attestation root")
    return certs[0]


def _nonce_in(cred_cert: x509.Certificate) -> bytes:
    """The extension 1.2.840.113635.100.8.2: SEQUENCE { [1] EXPLICIT OCTET STRING nonce }."""
    try:
        ext = cred_cert.extensions.get_extension_for_oid(NONCE_OID).value
    except x509.ExtensionNotFound as exc:
        raise AppAttestError("the credential certificate carries no nonce") from exc
    try:
        seq, _ = read_tlv(ext.value)
        for item in seq.children():
            if item.cls == 2 and item.tag == 1:
                inner = item.children()
                if inner and inner[0].tag == 4:
                    return inner[0].value
    except (AttestationError, IndexError, AttributeError) as exc:
        raise AppAttestError("the credential certificate's nonce is unreadable") from exc
    raise AppAttestError("the credential certificate's nonce is unreadable")


# --------------------------------------------------------------------------------------------- policy

@dataclass
class Policy:
    app_id: str                      # "<TEAM_ID>.<bundle id>"
    allow_develop: bool = False      # accept keys from development builds (AAGUID "appattestdevelop")


@dataclass
class Attested:
    public_key_spki: bytes
    key_id: bytes
    device_key_id: str
    environment: str                 # "production" or "development"
    counter: int
    app_id: str

    def summary(self) -> Dict[str, Any]:
        # the same fields Android reports, so the app and the admin pages read either platform alike
        return {
            "device_key_id": self.device_key_id, "platform": "ios", "security_level": "secure_enclave",
            "verified_boot_state": None, "device_locked": None, "package": self.app_id.split(".", 1)[-1],
            "app_cert_ok": True, "os_version": None, "os_patch_level": None, "attestation_version": None,
            "app_attest_environment": self.environment,
        }


def device_key_id(key_id: bytes) -> str:
    """The iPhone's agent id (a sensor, FLOW_SPEC Rule 2), from App Attest's key identifier."""
    return "sensor:ios-" + key_id.hex()[:24]


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def verify_attestation(attestation_object: bytes, key_id: bytes, client_data: bytes, policy: Policy,
                       roots: Optional[Sequence[x509.Certificate]] = None, now: Optional[datetime] = None) -> Attested:
    """
    Check an attestation from DCAppAttestService.attestKey(keyId, clientDataHash: SHA256(client_data)).
    Raises AppAttestError on any failure; there are no soft policy problems on iOS.
    """
    if not policy.app_id:
        raise AppAttestError("iPhones cannot be linked: the App ID is not configured")
    now = now or datetime.now(timezone.utc)
    obj = _cbor_map(attestation_object, "the attestation")
    if obj.get("fmt") != FORMAT:
        raise AppAttestError("not an App Attest attestation")
    stmt = obj.get("attStmt")
    x5c = stmt.get("x5c") if isinstance(stmt, dict) else None
    if not isinstance(x5c, list) or not 2 <= len(x5c) <= 5 or not all(isinstance(c, bytes) for c in x5c):
        raise AppAttestError("the attestation carries no certificate chain")
    auth = parse_auth_data(obj.get("authData"), attested=True)

    # 1. the chain: credCert and intermediate, to Apple's root
    cred_cert = _check_chain(x5c, roots if roots is not None else apple_roots(), now)
    # 2-4. nonce = SHA256(authData || SHA256(clientData)) is the one in credCert
    if _nonce_in(cred_cert) != _sha256(auth.raw + _sha256(client_data)):
        raise AppAttestError("the key was not made for this request (nonce mismatch)")
    # 5. the key identifier is the SHA256 of credCert's public key (uncompressed point)
    pub = cred_cert.public_key()
    if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
        raise AppAttestError("the credential key is not P-256")
    point = pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    if _sha256(point) != key_id:
        raise AppAttestError("the key identifier does not match the attested key")
    # 6. made by our app
    if auth.rp_id_hash != _sha256(policy.app_id.encode("utf-8")):
        raise AppAttestError("the key was made by another app")
    # 7. a new key has never signed anything
    if auth.counter != 0:
        raise AppAttestError("the key's counter is not zero")
    # 8. production, or a development build where allowed
    if auth.aaguid == AAGUID_PRODUCTION:
        environment = "production"
    elif auth.aaguid == AAGUID_DEVELOP:
        if not policy.allow_develop:
            raise AppAttestError("the key is from a development build of the app")
        environment = "development"
    else:
        raise AppAttestError("the key is not from App Attest (unknown AAGUID)")
    # 9. the credential is the key
    if auth.credential_id != key_id:
        raise AppAttestError("the credential id does not match the key identifier")

    spki = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return Attested(public_key_spki=spki, key_id=key_id, device_key_id=device_key_id(key_id),
                    environment=environment, counter=0, app_id=policy.app_id)


def counter_problem(counter: int, seen: Collection[int], window: int = COUNTER_WINDOW) -> Optional[str]:
    """
    Why this counter cannot be accepted, or None. Reports are signed when sealed and may upload later and out
    of order (the offline outbox), so a counter need not be above the highest seen; it must only never have
    been seen (an exact replay), and not be more than `window` below the highest seen (so the set of counters
    to remember stays bounded: anything older than the window is refused as stale, not looked up).
    """
    if counter < 1:
        return "the assertion's counter is zero"
    if counter in seen:
        return "the assertion's counter was already used (a replay)"
    if seen and counter <= max(seen) - window:
        return "the assertion is too old (its counter is far below the newest seen)"
    return None


def verify_assertion(assertion: bytes, client_data: bytes, public_key_spki: bytes, app_id: str,
                     seen: Collection[int] = (), window: int = COUNTER_WINDOW) -> int:
    """
    Check an assertion from DCAppAttestService.generateAssertion(keyId, clientDataHash: SHA256(client_data)).
    Returns its counter, which must pass counter_problem against the counters already `seen` for the key;
    raises AppAttestError otherwise.
    """
    obj = _cbor_map(assertion, "the assertion")
    signature, raw = obj.get("signature"), obj.get("authenticatorData")
    if not isinstance(signature, bytes):
        raise AppAttestError("the assertion carries no signature")
    auth = parse_auth_data(raw, attested=False)
    nonce = _sha256(auth.raw + _sha256(client_data))
    try:
        key = serialization.load_der_public_key(public_key_spki)
    except ValueError as exc:
        raise AppAttestError("the stored key is unreadable") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise AppAttestError("the stored key is not an EC key")
    try:
        # the Secure Enclave signs nonce with ECDSA-SHA256 (checked against a real device's assertion in the tests)
        key.verify(signature, nonce, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise AppAttestError("bad signature") from exc
    if auth.rp_id_hash != _sha256(app_id.encode("utf-8")):
        raise AppAttestError("the assertion is for another app")
    problem = counter_problem(auth.counter, seen, window)
    if problem:
        raise AppAttestError(problem)
    return auth.counter
