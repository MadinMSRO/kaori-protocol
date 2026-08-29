"""Bearer maps to user:{supabase auth user.id} via GET /auth/v1/user. Never profiles.id."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from kaori_api.app import create_app
from kaori_api.auth import (
    AuthError,
    agent_id_from_authorization,
    agent_id_from_token,
    supabase_user_url,
)
from kaori_flow import FlowCore, InMemorySignalStore


AUTH_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROFILE_ID = "profile-row-should-never-be-used"
SUPABASE_URL = "https://example.supabase.co"
PUBLISHABLE_KEY = "sb-publishable-test"
TOKEN = "supabase-access-token"


class _FakeResponse:
    def __init__(self, status: int, body: dict | bytes):
        self.status = status
        if isinstance(body, bytes):
            self._raw = body
        else:
            self._raw = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_supabase_user_url():
    assert supabase_user_url("https://example.supabase.co") == "https://example.supabase.co/auth/v1/user"
    assert supabase_user_url("https://example.supabase.co/") == "https://example.supabase.co/auth/v1/user"


def test_200_user_id_maps_to_user_prefixed_auth_id(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["apikey"] = request.get_header("apikey") or request.get_header("Apikey")
        captured["timeout"] = timeout
        return _FakeResponse(200, {"id": AUTH_USER_ID, "profile_id": PROFILE_ID})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    agent_id = agent_id_from_token(TOKEN, SUPABASE_URL, PUBLISHABLE_KEY)
    assert agent_id == f"user:{AUTH_USER_ID}"
    assert PROFILE_ID not in agent_id
    assert captured["url"] == "https://example.supabase.co/auth/v1/user"
    assert captured["authorization"] == f"Bearer {TOKEN}"
    assert captured["apikey"] == PUBLISHABLE_KEY


def test_authorization_header_maps_via_user_id(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(200, {"id": AUTH_USER_ID}),
    )
    agent_id = agent_id_from_authorization(f"Bearer {TOKEN}", SUPABASE_URL, PUBLISHABLE_KEY)
    assert agent_id == f"user:{AUTH_USER_ID}"
    assert not agent_id.startswith("profile:")


def test_non_200_is_invalid(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(AuthError):
        agent_id_from_token(TOKEN, SUPABASE_URL, PUBLISHABLE_KEY)


def test_200_without_id_is_invalid_even_with_profile_id(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(200, {"profile_id": PROFILE_ID}),
    )
    with pytest.raises(AuthError):
        agent_id_from_token(TOKEN, SUPABASE_URL, PUBLISHABLE_KEY)


def test_missing_env_is_invalid():
    with pytest.raises(AuthError):
        agent_id_from_token(TOKEN, "", PUBLISHABLE_KEY)
    with pytest.raises(AuthError):
        agent_id_from_token(TOKEN, SUPABASE_URL, "")


def test_missing_bearer_raises():
    with pytest.raises(AuthError):
        agent_id_from_authorization(None, SUPABASE_URL, PUBLISHABLE_KEY)
    with pytest.raises(AuthError):
        agent_id_from_authorization("Basic abc", SUPABASE_URL, PUBLISHABLE_KEY)


def test_compile_stamps_reporter_id_from_bearer_not_profile_id():
    from kaori_api.app import reporter_context_from_flow, stamp_observation

    flow = FlowCore(store=InMemorySignalStore())
    mapped = f"user:{AUTH_USER_ID}"
    flow.register_agent(mapped, role="observer")
    context = reporter_context_from_flow(flow, mapped)
    stamped = stamp_observation(
        {
            "reporter_id": PROFILE_ID,
            "reporter_context": {
                "standing": "authority",
                "trust_score": 1.0,
                "source_type": "official",
            },
        },
        mapped,
        context,
    )
    assert stamped["reporter_id"] == mapped
    assert PROFILE_ID not in stamped["reporter_id"]
    assert stamped["reporter_context"]["standing"] != "authority"


def _verify(token: str) -> str:
    if token != TOKEN:
        raise AuthError("Invalid Bearer token")
    return f"user:{AUTH_USER_ID}"


def test_http_standing_uses_mapped_agent_id_not_profile_id():
    flow = FlowCore(store=InMemorySignalStore())
    mapped = f"user:{AUTH_USER_ID}"
    flow.register_agent(mapped, role="observer")
    client = TestClient(create_app(flow=flow, verify_token=_verify))

    response = client.get(
        f"/v1/standing/{mapped}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["standing"] == flow.get_standing(mapped)

    unknown = client.get(
        f"/v1/standing/{PROFILE_ID}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert unknown.status_code == 404
