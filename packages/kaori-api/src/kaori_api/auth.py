"""
Kaori API — Bearer identity

Verify Authorization: Bearer <token> via Supabase Auth GET /auth/v1/user.
Map user.id to agent_id `user:{id}`. Never accepts or emits profiles.id.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urljoin


class AuthError(Exception):
    """Missing or invalid Bearer token."""


def agent_id_from_user_id(user_id: str) -> str:
    """INTEGRATION.md identity: user:{supabase auth user.id}."""
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
