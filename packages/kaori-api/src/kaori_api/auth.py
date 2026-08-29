"""
Kaori API — Bearer identity

Maps Authorization: Bearer <Supabase JWT> to agent_id `user:{auth.users.id}`.
Never accepts or emits profiles.id.
"""
from __future__ import annotations

from typing import Optional

from jose import JWTError, jwt


class AuthError(Exception):
    """Missing or invalid Bearer token."""


def agent_id_from_user_id(user_id: str) -> str:
    """INTEGRATION.md identity: user:{supabase auth user.id}."""
    return f"user:{user_id}"


def parse_bearer(authorization: Optional[str]) -> str:
    """Extract the raw JWT from an Authorization header."""
    if not authorization:
        raise AuthError("Missing Bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Missing or invalid Bearer token")
    return token.strip()


def agent_id_from_jwt(token: str, secret: str) -> str:
    """
    Verify a Supabase JWT and map `sub` (auth user id) to agent_id.

    Ignores profiles.id / profile_id claims if present.
    """
    if not secret:
        raise AuthError("Invalid Bearer token")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise AuthError("Invalid Bearer token") from exc

    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise AuthError("Invalid Bearer token")
    return agent_id_from_user_id(user_id)


def agent_id_from_authorization(authorization: Optional[str], secret: str) -> str:
    """Header → verified agent_id."""
    token = parse_bearer(authorization)
    return agent_id_from_jwt(token, secret)
