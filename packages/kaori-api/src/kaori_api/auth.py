"""
Kaori API — Bearer identity

Verify Authorization: Bearer <token> with one of:
- Firebase Auth (FIREBASE_PROJECT_ID set): the ID token's signature and claims, checked offline;
- Supabase Auth: GET /auth/v1/user.
Map the auth user id to agent_id `user:{id}`. Never accepts or emits profiles.id.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urljoin


class AuthError(Exception):
    """Missing or invalid Bearer token."""


def agent_id_from_user_id(user_id: str) -> str:
    """INTEGRATION.md identity: user:{auth user id} (Supabase user.id or Firebase uid)."""
    return f"user:{user_id}"


def parse_bearer(authorization: Optional[str]) -> str:
    """Extract the raw token from an Authorization header."""
    if not authorization:
        raise AuthError("Missing Bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Missing or invalid Bearer token")
    return token.strip()


def supabase_user_url(supabase_url: str) -> str:
    base = supabase_url.rstrip("/") + "/"
    return urljoin(base, "auth/v1/user")


def agent_id_from_token(token: str, supabase_url: str, publishable_key: str) -> str:
    """
    GET {SUPABASE_URL}/auth/v1/user with Bearer token + apikey.

    200 + user.id → user:{id}. Any non-200 or missing id → AuthError (HTTP 401).
    """
    if not token or not supabase_url or not publishable_key:
        raise AuthError("Invalid Bearer token")
    request = urllib.request.Request(
        supabase_user_url(supabase_url),
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": publishable_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise AuthError("Invalid Bearer token")
            payload = json.loads(response.read().decode("utf-8"))
    except AuthError:
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Invalid Bearer token") from exc

    if not isinstance(payload, dict):
        raise AuthError("Invalid Bearer token")
    user_id = payload.get("id")
    if not user_id or not isinstance(user_id, str):
        raise AuthError("Invalid Bearer token")
    return agent_id_from_user_id(user_id)


def agent_id_from_authorization(
    authorization: Optional[str],
    supabase_url: str,
    publishable_key: str,
) -> str:
    """Header → verified agent_id via Supabase Auth."""
    token = parse_bearer(authorization)
    return agent_id_from_token(token, supabase_url, publishable_key)


# --- Firebase Auth (the all-GCP deployment) ---------------------------------------------------
# A Firebase ID token is an RS256 JWT signed by Google. It is checked offline against Google's
# published certificates; nothing is sent to Firebase per request. The agent is user:{uid}.

FIREBASE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)


class FirebaseCerts:
    """Google's signing certificates, cached for as long as Google says (Cache-Control max-age)."""

    def __init__(self, fetch: Optional[Callable[[], Tuple[Dict[str, str], float]]] = None):
        self._fetch = fetch or _fetch_firebase_certs
        self._certs: Dict[str, str] = {}
        self._expires = 0.0
        self._lock = threading.Lock()

    def get(self, kid: str) -> Dict[str, str]:
        with self._lock:
            # refetch when stale, or once when a new key id appears (Google rotates keys)
            if time.time() >= self._expires or kid not in self._certs:
                certs, max_age = self._fetch()
                self._certs, self._expires = dict(certs), time.time() + max_age
            return self._certs


def _fetch_firebase_certs() -> Tuple[Dict[str, str], float]:
    with urllib.request.urlopen(FIREBASE_CERTS_URL, timeout=10) as response:
        certs = json.loads(response.read().decode("utf-8"))
        cache = response.headers.get("Cache-Control", "") or ""
    match = re.search(r"max-age=(\d+)", cache)
    return certs, float(match.group(1)) if match else 3600.0


def agent_id_from_firebase_token(token: str, project_id: str, certs: FirebaseCerts) -> str:
    """Verify a Firebase ID token for this project. Anything wrong → AuthError (HTTP 401)."""
    from google.auth import exceptions as google_exceptions
    from google.auth import jwt as google_jwt

    if not token or not project_id:
        raise AuthError("Invalid Bearer token")
    try:
        header = google_jwt.decode_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise AuthError("Invalid Bearer token")
        claims = google_jwt.decode(
            token, certs=certs.get(header["kid"]), audience=project_id, clock_skew_in_seconds=10
        )
    except AuthError:
        raise
    except (google_exceptions.GoogleAuthError, ValueError, KeyError, urllib.error.URLError, TimeoutError) as exc:
        raise AuthError("Invalid Bearer token") from exc
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise AuthError("Invalid Bearer token")
    uid = claims.get("sub")
    if not uid or not isinstance(uid, str) or len(uid) > 128:
        raise AuthError("Invalid Bearer token")
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > time.time() + 10:
        raise AuthError("Invalid Bearer token")
    return agent_id_from_user_id(uid)
