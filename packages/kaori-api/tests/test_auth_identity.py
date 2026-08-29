"""Bearer JWT maps to user:{supabase auth user.id}. Never profiles.id."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from kaori_api.app import create_app
from kaori_api.auth import AuthError, agent_id_from_authorization, agent_id_from_jwt
from kaori_flow import FlowCore, InMemorySignalStore


SECRET = "identity-test-secret"
AUTH_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROFILE_ID = "profile-row-should-never-be-used"


def mint(sub=AUTH_USER_ID, extra=None, secret=SECRET) -> str:
    payload = {
        "sub": sub,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm="HS256")


def test_jwt_sub_maps_to_user_prefixed_auth_id():
    token = mint()
    assert agent_id_from_jwt(token, SECRET) == f"user:{AUTH_USER_ID}"


def test_authorization_header_maps_to_user_prefixed_auth_id():
    token = mint()
    agent_id = agent_id_from_authorization(f"Bearer {token}", SECRET)
    assert agent_id == f"user:{AUTH_USER_ID}"
    assert PROFILE_ID not in agent_id
    assert not agent_id.startswith("profile:")


def test_profile_id_claim_is_ignored():
    token = mint(extra={"profile_id": PROFILE_ID, "profiles.id": PROFILE_ID})
    assert agent_id_from_jwt(token, SECRET) == f"user:{AUTH_USER_ID}"


def test_missing_sub_is_invalid_even_with_profile_id():
    token = mint(sub=None, extra={"sub": None, "profile_id": PROFILE_ID})
    # python-jose will still encode sub=None; decode must reject missing sub
    token = jwt.encode(
        {
            "profile_id": PROFILE_ID,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        agent_id_from_jwt(token, SECRET)


def test_missing_bearer_raises():
    with pytest.raises(AuthError):
        agent_id_from_authorization(None, SECRET)
    with pytest.raises(AuthError):
        agent_id_from_authorization("Basic abc", SECRET)


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


def test_http_standing_uses_mapped_agent_id_not_profile_id():
    flow = FlowCore(store=InMemorySignalStore())
    mapped = f"user:{AUTH_USER_ID}"
    flow.register_agent(mapped, role="observer")
    client = TestClient(create_app(flow=flow, jwt_secret=SECRET))

    token = mint(extra={"profile_id": PROFILE_ID})
    response = client.get(
        f"/v1/standing/{mapped}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["standing"] == flow.get_standing(mapped)

    # Looking up a profiles.id is unknown — we never map to it
    unknown = client.get(
        f"/v1/standing/{PROFILE_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert unknown.status_code == 404
