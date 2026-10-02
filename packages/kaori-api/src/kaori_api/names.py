"""
People's names in the Antalya ledger, encrypted.

An inviter names the person they invite; the person gives their own name when they join. Kaori compares the
two in memory and records only whether they match. The names themselves are stored encrypted (AES-256-GCM,
key KAORI_NAME_KEY from Secret Manager, 64 hex characters), each bound to its place in the ledger (the AAD),
so a ciphertext cannot be moved to another record. Signals, exports and logs never carry a name in clear;
only the admin API decrypts them, for admins.
"""
from __future__ import annotations

import base64
import os
import re
import secrets
import unicodedata
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_NAME = 60


def _key() -> Optional[bytes]:
    raw = os.environ.get("KAORI_NAME_KEY", "").strip()
    if not raw:
        return None
    key = bytes.fromhex(raw)
    if len(key) != 32:
        raise ValueError("KAORI_NAME_KEY must be 32 bytes (64 hex characters)")
    return key


def clean(name: object) -> Optional[str]:
    """A name as typed, trimmed and collapsed; None if empty. Raises ValueError if it is not a usable name."""
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError("name must be text")
    text = re.sub(r"\s+", " ", name).strip()
    if not text:
        return None
    if len(text) > MAX_NAME:
        raise ValueError(f"name must be at most {MAX_NAME} characters")
    return text


def first_name(name: Optional[str]) -> Optional[str]:
    """Lower case, accents dropped, first word: "Aïsha Ibrahim" and "aisha" match."""
    if not name:
        return None
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).casefold()
    words = re.findall(r"[^\W\d_]+", plain)
    return words[0] if words else None


def same_person(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    fa, fb = first_name(a), first_name(b)
    return None if fa is None or fb is None else fa == fb


def seal(name: Optional[str], context: str) -> Optional[str]:
    """Encrypt for the ledger; None when there is no name or no key (the name is then not kept)."""
    key = _key()
    if not name or key is None:
        return None
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, name.encode("utf-8"), context.encode("utf-8"))
    return "v1:" + base64.b64encode(nonce + ct).decode("ascii")


def unseal(token: Optional[str], context: str) -> Optional[str]:
    """Decrypt, for admins. None when absent, unreadable, or sealed for another record."""
    key = _key()
    if not token or key is None or not token.startswith("v1:"):
        return None
    try:
        raw = base64.b64decode(token[3:])
        return AESGCM(key).decrypt(raw[:12], raw[12:], context.encode("utf-8")).decode("utf-8")
    except Exception:
        return None
