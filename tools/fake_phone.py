"""
A stand-in for a phone's secure chip, for local end-to-end runs only (tools/antalya_dev_server.py with
KAORI_DEV_FAKE_PHONE=1). It makes EC P-256 keys and attestation chains under its own test root, shaped
like a real Android Keystore's: secure hardware (TEE), verified boot, a locked bootloader, made by
mv.msro.liminal signed with FAKE_APP_CERT. The dev server trusts only this root; a deployed Kaori trusts
only Google's.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

KEY_DESCRIPTION_OID = "1.3.6.1.4.1.11129.2.1.17"
FAKE_APP_CERT = hashlib.sha256(b"liminal dev signing certificate").hexdigest()


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
    size = (n.bit_length() + 7) // 8
    return head + (bytes([n]) if n < 0x80 else bytes([0x80 | size]) + n.to_bytes(size, "big")) + body


def _int(n): return _der(2, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))
def _enum(n): return _der(10, bytes([n]))
def _oct(b): return _der(4, b)
def _seq(*xs): return _der(16, b"".join(xs), constructed=True)
def _set(*xs): return _der(17, b"".join(xs), constructed=True)
def _bool(v): return _der(1, b"\xff" if v else b"\x00")
def _tagged(tag, inner): return _der(tag, inner, cls=2, constructed=True)


def key_description(challenge: bytes, package: str = "mv.msro.liminal", cert: str = FAKE_APP_CERT) -> bytes:
    app_id = _seq(_set(_seq(_oct(package.encode()), _int(1))), _set(_oct(bytes.fromhex(cert))))
    software = _seq(_tagged(709, _oct(app_id)))
    hardware = _seq(_tagged(704, _seq(_oct(b"\x11" * 32), _bool(True), _enum(0), _oct(b"\x22" * 32))),
                    _tagged(705, _int(150000)), _tagged(706, _int(202609)))
    return _seq(_int(200), _enum(1), _int(200), _enum(1), _oct(challenge), _oct(b""), software, hardware)


class _Ca:
    def __init__(self, name: str, issuer: "_Ca | None" = None):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        issuer = issuer or self
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(self.name).issuer_name(issuer.name)
                     .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                     .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650))
                     .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                     .sign(issuer.key, hashes.SHA256()))
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.spki = self.key.public_key().public_bytes(serialization.Encoding.DER,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo)


class FakeChip:
    def __init__(self):
        self.root = _Ca("Liminal dev attestation root (not Google)")
        self.inter = _Ca("Liminal dev attestation intermediate", issuer=self.root)
        self.keys: dict[str, ec.EllipticCurvePrivateKey] = {}

    def generate(self, alias: str, challenge: bytes) -> dict:
        key = ec.generate_private_key(ec.SECP256R1())
        self.keys[alias] = key
        now = dt.datetime.now(dt.timezone.utc)
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Android Keystore Key")]))
                .issuer_name(self.inter.name).public_key(key.public_key()).serial_number(1)
                .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier(KEY_DESCRIPTION_OID),
                                                          key_description(challenge)), critical=False)
                .sign(self.inter.key, hashes.SHA256()))
        chain = [leaf.public_bytes(serialization.Encoding.DER), self.inter.der, self.root.der]
        return {"chain": [base64.b64encode(c).decode() for c in chain], "strongBox": False}

    def sign(self, alias: str, text: str) -> str:
        return base64.b64encode(self.keys[alias].sign(text.encode(), ec.ECDSA(hashes.SHA256()))).decode()
