"""
Android Key Attestation: what a phone's secure hardware vouches for about a key it made.

When Liminal links a phone it asks the Android Keystore for a new signing key, bound to a challenge
from Kaori. Android returns the key's certificate chain, which the phone's secure hardware (TEE or
StrongBox) signs and Google certifies. From it Kaori learns, without trusting the app:

- the key lives in genuine secure hardware (not software, not an emulator);
- the phone booted verified software with a locked bootloader (not rooted);
- which app asked for it, and that app's signing certificate (not a modified copy);
- that it was made just now, for this request (the challenge).

Certificates are read with a small DER reader of our own: some phones emit attestation certificates
with harmless encoding quirks that strict X.509 parsers reject, and a real phone must not be refused
for that. `cryptography` is used only to check signatures.

References: https://source.android.com/docs/security/features/keystore/attestation
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

KEY_DESCRIPTION_OID = "1.3.6.1.4.1.11129.2.1.17"
ROOTS_URL = "https://android.googleapis.com/attestation/root"
STATUS_URL = "https://android.googleapis.com/attestation/status"
BUNDLED_ROOTS = Path(__file__).with_name("android_attestation_roots.json")

SECURITY_LEVELS = {0: "software", 1: "tee", 2: "strongbox"}
BOOT_STATES = {0: "verified", 1: "self_signed", 2: "unverified", 3: "failed"}

_SIG_ALGS = {
    "1.2.840.113549.1.1.11": ("rsa", hashes.SHA256),
    "1.2.840.113549.1.1.12": ("rsa", hashes.SHA384),
    "1.2.840.113549.1.1.13": ("rsa", hashes.SHA512),
    "1.2.840.10045.4.3.2": ("ec", hashes.SHA256),
    "1.2.840.10045.4.3.3": ("ec", hashes.SHA384),
    "1.2.840.10045.4.3.4": ("ec", hashes.SHA512),
}


class AttestationError(ValueError):
    """The chain cannot be trusted, or the key it describes does not meet the policy."""


# ------------------------------------------------------------------------------------------------ DER

@dataclass
class Tlv:
    cls: int          # 0 universal, 1 application, 2 context, 3 private
    constructed: bool
    tag: int
    raw: bytes        # header and value
    value: bytes

    def children(self) -> List["Tlv"]:
        return list(read_all(self.value))


def read_tlv(buf: bytes, i: int = 0) -> Tuple[Tlv, int]:
    if i >= len(buf):
        raise AttestationError("truncated DER")
    start = i
    first = buf[i]
    i += 1
    cls, constructed, tag = first >> 6, bool(first & 0x20), first & 0x1F
    if tag == 0x1F:                       # high tag number, base 128
        tag = 0
        while True:
            if i >= len(buf):
                raise AttestationError("truncated DER tag")
            b = buf[i]
            i += 1
            tag = (tag << 7) | (b & 0x7F)
            if not b & 0x80:
                break
    if i >= len(buf):
        raise AttestationError("truncated DER length")
    length = buf[i]
    i += 1
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or n > 4 or i + n > len(buf):
            raise AttestationError("unsupported DER length")
        length = int.from_bytes(buf[i:i + n], "big")
        i += n
    end = i + length
    if end > len(buf):
        raise AttestationError("truncated DER value")
    return Tlv(cls, constructed, tag, buf[start:end], buf[i:end]), end


def read_all(buf: bytes):
    i = 0
    while i < len(buf):
        tlv, i = read_tlv(buf, i)
        yield tlv


def der_int(value: bytes) -> int:
    return int.from_bytes(value, "big", signed=True) if value else 0


def der_oid(value: bytes) -> str:
    if not value:
        raise AttestationError("empty OID")
    parts = [value[0] // 40, value[0] % 40]
    n = 0
    for b in value[1:]:
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


# ----------------------------------------------------------------------------------------- certificates

@dataclass
class Cert:
    raw: bytes
    tbs: bytes
    sig_alg: str
    signature: bytes
    serial: int
    spki: bytes
    not_after: Optional[datetime]
    extensions: Dict[str, bytes] = field(default_factory=dict)

    def public_key(self):
        return serialization.load_der_public_key(self.spki)


def _time(t: Tlv) -> Optional[datetime]:
    try:
        text = t.value.decode("ascii")
        if t.tag == 23:                                  # UTCTime YYMMDDHHMMSSZ
            year = int(text[:2])
            return datetime.strptime(("20" if year < 50 else "19") + text[:12], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)   # GeneralizedTime
    except (ValueError, UnicodeDecodeError):
        return None


def parse_cert(der: bytes) -> Cert:
    outer, _ = read_tlv(der)
    parts = outer.children()
    if len(parts) < 3:
        raise AttestationError("not a certificate")
    tbs, alg, sig = parts[0], parts[1], parts[2]
    fields = tbs.children()
    k = 1 if fields and fields[0].cls == 2 and fields[0].tag == 0 else 0     # optional [0] version
    serial = der_int(fields[k].value)
    validity = fields[k + 3].children()
    spki = fields[k + 5].raw
    extensions: Dict[str, bytes] = {}
    for f in fields[k + 6:]:
        if f.cls == 2 and f.tag == 3:
            for ext in f.children()[0].children():
                items = ext.children()
                extensions[der_oid(items[0].value)] = items[-1].value      # extnValue OCTET STRING contents
    bits = sig.value
    return Cert(
        raw=der, tbs=tbs.raw, sig_alg=der_oid(alg.children()[0].value),
        signature=bits[1:] if bits else b"", serial=serial, spki=spki,
        not_after=_time(validity[1]) if len(validity) > 1 else None, extensions=extensions,
    )


def verify_signed_by(cert: Cert, issuer: Cert) -> None:
    kind_hash = _SIG_ALGS.get(cert.sig_alg)
    if not kind_hash:
        raise AttestationError(f"unsupported signature algorithm {cert.sig_alg}")
    kind, h = kind_hash
    key = issuer.public_key()
    try:
        if kind == "rsa" and isinstance(key, rsa.RSAPublicKey):
            key.verify(cert.signature, cert.tbs, padding.PKCS1v15(), h())
        elif kind == "ec" and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(cert.signature, cert.tbs, ec.ECDSA(h()))
        else:
            raise AttestationError("signature algorithm does not match the issuer's key")
    except InvalidSignature as exc:
        raise AttestationError("a certificate in the chain is not signed by the next one") from exc


# --------------------------------------------------------------------------------- the attestation record

@dataclass
class KeyDescription:
    attestation_version: int
    attestation_security_level: str
    keymint_security_level: str
    challenge: bytes
    hardware: Dict[int, Tlv]
    software: Dict[int, Tlv]


def _auth_list(t: Tlv) -> Dict[int, Tlv]:
    out: Dict[int, Tlv] = {}
    for item in t.children():
        if item.cls == 2:
            inner = item.children()
            if inner:
                out[item.tag] = inner[0]
    return out


def parse_key_description(ext: bytes) -> KeyDescription:
    seq, _ = read_tlv(ext)
    f = seq.children()
    if len(f) < 8:
        raise AttestationError("attestation record is incomplete")
    return KeyDescription(
        attestation_version=der_int(f[0].value),
        attestation_security_level=SECURITY_LEVELS.get(der_int(f[1].value), "unknown"),
        keymint_security_level=SECURITY_LEVELS.get(der_int(f[3].value), "unknown"),
        challenge=f[4].value,
        software=_auth_list(f[6]),
        hardware=_auth_list(f[7]),
    )


def _root_of_trust(kd: KeyDescription) -> Dict[str, Any]:
    t = kd.hardware.get(704) or kd.software.get(704)
    if t is None:
        return {"present": False}
    f = t.children()
    return {
        "present": True,
        "hardware": 704 in kd.hardware,
        "device_locked": bool(f[1].value and f[1].value[0]) if len(f) > 1 else False,
        "verified_boot_state": BOOT_STATES.get(der_int(f[2].value), "unknown") if len(f) > 2 else "unknown",
    }


def _application(kd: KeyDescription) -> Dict[str, Any]:
    t = kd.software.get(709) or kd.hardware.get(709)
    if t is None:
        return {"packages": [], "signature_digests": []}
    seq, _ = read_tlv(t.value)                       # OCTET STRING holding the DER of AttestationApplicationId
    parts = seq.children()
    packages = []
    for info in parts[0].children() if parts else []:
        p = info.children()
        packages.append({"name": p[0].value.decode("utf-8", "replace"), "version": der_int(p[1].value) if len(p) > 1 else 0})
    digests = [d.value.hex() for d in parts[1].children()] if len(parts) > 1 else []
    return {"packages": packages, "signature_digests": digests}


def _int_field(kd: KeyDescription, tag: int) -> Optional[int]:
    t = kd.hardware.get(tag) or kd.software.get(tag)
    return der_int(t.value) if t is not None else None


# ----------------------------------------------------------------------------------- Google's trust data

class TrustData:
    """Google's attestation roots and revocation list: fetched, cached, with a bundled fallback for roots."""

    def __init__(self, roots: Optional[Sequence[bytes]] = None, revoked: Optional[Dict[str, Any]] = None,
                 fetch: bool = True):
        self._fixed_roots = list(roots) if roots is not None else None
        self._fixed_revoked = revoked
        self._fetch = fetch
        self._roots: List[bytes] = []
        self._revoked: Dict[str, Any] = {}
        self._loaded = 0.0
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        roots: List[bytes] = []
        revoked: Dict[str, Any] = {}
        if self._fetch:
            try:
                with urllib.request.urlopen(ROOTS_URL, timeout=10) as r:
                    roots = [_spki_of_pem(p) for p in json.loads(r.read())]
            except Exception:
                roots = []
            try:
                with urllib.request.urlopen(STATUS_URL, timeout=10) as r:
                    revoked = {k.lower(): v for k, v in json.loads(r.read()).get("entries", {}).items()}
            except Exception:
                revoked = dict(self._revoked)        # keep the last list we had
        if not roots:
            roots = [_spki_of_pem(p) for p in json.loads(BUNDLED_ROOTS.read_text())]
        self._roots, self._revoked, self._loaded = roots, revoked, time.time()

    def get(self) -> Tuple[List[bytes], Dict[str, Any]]:
        if self._fixed_roots is not None:
            return self._fixed_roots, self._fixed_revoked or {}
        with self._lock:
            if time.time() - self._loaded > 3600 or not self._roots:
                self._refresh()
            return self._roots, self._revoked


def _spki_of_pem(pem: str) -> bytes:
    body = "".join(line for line in pem.strip().splitlines() if "-----" not in line)
    import base64
    return parse_cert(base64.b64decode(body)).spki


# ----------------------------------------------------------------------------------------------- verify

@dataclass
class Policy:
    package: str
    cert_sha256: List[str]                 # allowed app signing certificates (hex, lower case)
    require_hardware: bool = True          # TEE or StrongBox, not software
    require_verified_boot: bool = True     # verified boot and a locked bootloader


@dataclass
class Attested:
    public_key_spki: bytes
    device_key_id: str
    security_level: str
    verified_boot_state: str
    device_locked: bool
    package: Optional[str]
    app_cert_ok: bool
    os_version: Optional[int]
    os_patch_level: Optional[int]
    attestation_version: int
    problems: List[str]

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self) -> Dict[str, Any]:
        return {
            "device_key_id": self.device_key_id, "security_level": self.security_level,
            "verified_boot_state": self.verified_boot_state, "device_locked": self.device_locked,
            "package": self.package, "app_cert_ok": self.app_cert_ok, "os_version": self.os_version,
            "os_patch_level": self.os_patch_level, "attestation_version": self.attestation_version,
        }


def device_key_id(spki: bytes) -> str:
    """The phone's agent id (a sensor, FLOW_SPEC Rule 2), from the public key its secure hardware holds."""
    return "sensor:android-" + hashlib.sha256(spki).hexdigest()[:24]


def verify_chain(chain_der: Sequence[bytes], challenge: bytes, policy: Policy, trust: TrustData) -> Attested:
    """
    Check a chain (leaf first) from a phone. Raises AttestationError when the chain itself cannot be
    trusted; returns the facts, with `problems` listing every policy the key fails.
    """
    if not chain_der or len(chain_der) > 10:
        raise AttestationError("expected a certificate chain")
    try:
        certs = [parse_cert(bytes(c)) for c in chain_der]
    except (AttestationError, IndexError) as exc:
        raise AttestationError(f"unreadable certificate: {exc}") from exc
    for child, parent in zip(certs, certs[1:]):
        verify_signed_by(child, parent)
    roots, revoked = trust.get()
    if certs[-1].spki not in roots:
        raise AttestationError("the chain does not end at a Google attestation root")
    for c in certs:
        if format(c.serial, "x") in revoked:
            raise AttestationError("a certificate in the chain has been revoked by Google")
    leaf = certs[0]
    ext = leaf.extensions.get(KEY_DESCRIPTION_OID)
    if ext is None:
        raise AttestationError("the key carries no attestation record")
    kd = parse_key_description(ext)
    if kd.challenge != challenge:
        raise AttestationError("the key was not made for this request (challenge mismatch)")

    rot = _root_of_trust(kd)
    app = _application(kd)
    problems: List[str] = []
    if policy.require_hardware and (kd.attestation_security_level == "software" or kd.keymint_security_level == "software"):
        problems.append("the key is not in secure hardware (an emulator or an unsupported phone)")
    if policy.require_verified_boot:
        if not rot.get("present") or not rot.get("hardware"):
            problems.append("the phone did not report its boot state from secure hardware")
        elif rot.get("verified_boot_state") != "verified" or not rot.get("device_locked"):
            problems.append("the phone is not running verified software with a locked bootloader (rooted or modified)")
    package_names = [p["name"] for p in app["packages"]]
    if policy.package and policy.package not in package_names:
        problems.append("the key was made by another app")
    allowed = {c.lower().replace(":", "") for c in policy.cert_sha256 if c}
    app_cert_ok = bool(allowed) and any(d in allowed for d in app["signature_digests"])
    if allowed and not app_cert_ok:
        problems.append("the app is not signed with MSRO's key (a modified copy)")
    return Attested(
        public_key_spki=leaf.spki, device_key_id=device_key_id(leaf.spki),
        security_level=kd.attestation_security_level, verified_boot_state=rot.get("verified_boot_state", "unknown"),
        device_locked=bool(rot.get("device_locked")), package=package_names[0] if package_names else None,
        app_cert_ok=app_cert_ok, os_version=_int_field(kd, 705), os_patch_level=_int_field(kd, 706),
        attestation_version=kd.attestation_version, problems=problems,
    )


def verify_signature(spki: bytes, message: bytes, signature: bytes) -> bool:
    """A device signature (ECDSA P-256 / SHA-256 from the Android Keystore, or RSA PKCS#1 v1.5)."""
    try:
        key = serialization.load_der_public_key(spki)
        if isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        elif isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        else:
            return False
        return True
    except (InvalidSignature, ValueError):
        return False
