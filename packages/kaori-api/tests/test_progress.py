"""GET /v1/progress/{key}: how many people have reported, before a TruthState exists (and after)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kaori_api import antalya
from kaori_api.app import create_app
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore

from test_devices import _h, _verify
from test_leave import CLAIM, KEY, _report

OTHER = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T11:00Z"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, evidence_store=InMemoryEvidenceStore(bucket_name="b"),
                     generalist_client=None)
    app.state.ai_reader = None
    app.state.ai_sync = True
    for who in ("madin", "aisha", "omar"):
        antalya.seed_member(flow, "user:" + who)
    return TestClient(app), flow


def _progress(client, key=KEY, who="madin", **params):
    r = client.get(f"/v1/progress/{key}", headers=_h(who), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_progress_counts_reporters_until_the_truth_compiles(env):
    client, flow = env
    signals = len(flow.store.get_all())
    assert _progress(client) == {"truthkey": KEY, "received": 0, "required": None, "status": "PENDING"}
    assert _progress(client, claim_type_id=CLAIM)["required"] == 3
    assert client.get(f"/v1/truth/{KEY}", headers=_h("madin")).status_code == 404
    assert len(flow.store.get_all()) == signals                              # read-only

    first = _report(client, "madin")
    assert first.status_code == 202
    assert _progress(client, who="madin") == {"truthkey": KEY, "received": 1, "required": 3, "status": "PENDING"}
    assert _report(client, "aisha").status_code == 202
    # the first reporter learns of the second without reporting again; any member may ask
    assert _progress(client, who="madin")["received"] == 2
    assert _progress(client, who="omar")["received"] == 2
    # the numbers match what /v1/compile told the first reporter
    assert first.json()["observation_progress"] == {"received": 1, "required": 3}

    third = _report(client, "omar")
    assert third.status_code == 200
    truth = client.get(f"/v1/truth/{KEY}", headers=_h("madin")).json()
    done = _progress(client)
    assert done["received"] == 3 and done["required"] == 3
    assert done["status"] == truth["status"] != "PENDING"
    assert _progress(client, key=OTHER)["received"] == 0


def test_people_who_left_still_count(env):
    client, _ = env
    assert _report(client, "madin").status_code == 202
    assert client.delete("/v1/me", headers=_h("madin")).status_code == 200
    assert _progress(client, who="aisha")["received"] == 1


def test_progress_needs_sign_in_and_tolerates_an_unknown_claim_type(env):
    client, _ = env
    assert client.get(f"/v1/progress/{KEY}").status_code == 401
    assert _progress(client, claim_type_id="earth.nothing.v9")["required"] is None
