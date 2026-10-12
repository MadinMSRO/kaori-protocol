"""The ground claims on res 10 hexagons (earth.flood_water.v2, earth.vegetation.v2, earth.coastal_erosion.v2).

Same contracts as v1 on H3 resolution 10, with a position rule: a report stands in its key's hexagon, one of
the 6 around it, or within its GPS accuracy of it. GET /v1/truths lights a res 10 island cell with the truths
of that cell and of its ancestors (a res 8 sky truth lights all 49 of its res 10 children).
"""
from __future__ import annotations

import copy
import io
import math
from datetime import datetime, timezone
from pathlib import Path

import h3
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya, cells
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_api.generalist import ClipGeneralistValidator, ValidatorRequest
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.factory import load_claim_type
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing
from kaori_truth.primitives.truthkey import build_truthkey

SCHEMAS = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
GROUND = ("flood_water", "vegetation", "coastal_erosion")
FLOOD = "earth.flood_water.v2"
SKY = "earth.sky_cover.v1"
HERE = {"lat": 36.8969, "lon": 30.7133}                       # Antalya
CELL10 = h3.latlng_to_cell(HERE["lat"], HERE["lon"], 10)       # 8a3f6e36d35ffff
CELL8 = h3.cell_to_parent(CELL10, 8)                           # 883f6e36d3fffff
FLOOD_KEY = f"earth:flood_water:h3:{CELL10}:surface:2026-10-05T09:00Z"
SKY_KEY = f"earth:sky_cover:h3:{CELL8}:surface:2026-10-05T09:00Z"
WATER = {"water_present": True, "extent": "street"}


def _raw(name, version):
    return yaml.safe_load((SCHEMAS / "earth" / f"{name}_v{version}.yaml").read_text(encoding="utf-8"))


def _offset(lat, lon, metres_north=0.0, metres_east=0.0):
    return {"lat": lat + metres_north / 111_320.0,
            "lon": lon + metres_east / (111_320.0 * math.cos(math.radians(lat)))}


# ------------------------------------------------------------------------------------------- the contracts

@pytest.mark.parametrize("name", GROUND)
def test_v2_is_v1_on_res_10_with_a_position_rule(name):
    v1, v2 = _raw(name, 1), _raw(name, 2)
    assert (v2["id"], v2["version"]) == (f"earth.{name}.v2", 2)
    assert v2["truthkey"]["resolution"] == 10
    assert v2["truthkey"]["position"] == {"ring": 1, "max_accuracy_m": 100}
    for field in ("spatial_system", "z_index", "time_bucket"):
        assert v2["truthkey"][field] == v1["truthkey"][field]
    # everything else is v1's, unchanged
    strip = lambda raw: {k: v for k, v in raw.items() if k not in ("id", "version", "truthkey")}  # noqa: E731
    assert strip(v2) == strip(v1)
    loaded = load_claim_type(SCHEMAS / "earth" / f"{name}_v2.yaml")
    assert loaded.truthkey.resolution == 10
    assert loaded.minimum_observations() == load_claim_type(SCHEMAS / "earth" / f"{name}_v1.yaml").minimum_observations()


def test_v1_types_stay_and_sky_cover_is_unchanged():
    assert _raw("flood_water", 1)["truthkey"]["resolution"] == 8
    assert _raw("vegetation", 1)["truthkey"]["resolution"] == 6
    assert _raw("coastal_erosion", 1)["truthkey"]["resolution"] == 6
    sky = _raw("sky_cover", 1)
    assert sky["truthkey"]["resolution"] == 8 and "position" not in sky["truthkey"]


@pytest.mark.parametrize("name", GROUND)
def test_the_truthkey_is_the_res_10_hexagon_inside_the_res_8_one(name):
    raw = _raw(name, 2)
    tk = raw["truthkey"]
    key = build_truthkey(claim_type_id=raw["id"], event_time=datetime(2026, 10, 5, 9, 0, 30, tzinfo=timezone.utc),
                         location=HERE, spatial_system=tk["spatial_system"], spatial_resolution=tk["resolution"],
                         z_index=tk["z_index"], time_bucket_duration=tk["time_bucket"])
    cell = key.split(":")[3]
    assert cell == CELL10 and h3.get_resolution(cell) == 10
    assert h3.cell_to_parent(cell, 8) == CELL8                     # the sky truth's hexagon is its ancestor
    assert key.startswith(f"earth:{name}:h3:{CELL10}:surface:2026-10-05T")
    assert cells.cell_info(key) == {"cell": CELL10, "resolution": 10}


# ------------------------------------------------------------------------------------------- position rule

def test_position_rule_hexagon_ring_and_accuracy():
    rule = {"ring": 1, "max_accuracy_m": 100}
    assert cells.position_fits(CELL10, HERE["lat"], HERE["lon"], None, rule)
    neighbour = h3.cell_to_latlng(next(c for c in h3.grid_ring(CELL10, 1)))
    assert cells.position_fits(CELL10, *neighbour, None, rule)                         # GPS jitter next door
    two_away = h3.cell_to_latlng(next(c for c in h3.grid_ring(CELL10, 2)))
    assert not cells.position_fits(CELL10, *two_away, None, rule)
    cx, cy = h3.cell_to_latlng(CELL10)
    far = _offset(cx, cy, metres_north=250)
    assert h3.latlng_to_cell(far["lat"], far["lon"], 10) not in h3.grid_disk(CELL10, 1)
    assert not cells.position_fits(CELL10, far["lat"], far["lon"], 20, rule)
    assert cells.position_fits(CELL10, far["lat"], far["lon"], 180, rule) is False     # counted up to 100 m only
    # 170 m out where the ring is narrowest (between two neighbours): outside the ring, but a fix whose
    # accuracy circle reaches the hexagon still counts
    bearing = math.radians(24)
    near = _offset(cx, cy, metres_north=170 * math.cos(bearing), metres_east=170 * math.sin(bearing))
    assert h3.latlng_to_cell(near["lat"], near["lon"], 10) not in h3.grid_disk(CELL10, 1)
    assert not cells.position_fits(CELL10, near["lat"], near["lon"], None, rule)
    assert not cells.position_fits(CELL10, near["lat"], near["lon"], 50, rule)
    assert cells.position_fits(CELL10, near["lat"], near["lon"], 100, rule)


def _obs(geo):
    return Observation(claim_type=FLOOD, reported_at=datetime(2026, 10, 5, 9, 0, 30, tzinfo=timezone.utc),
                       reporter_id="user:x", reporter_context=ReporterContext(standing=Standing.BRONZE, trust_score=0.5),
                       geo=geo, payload=WATER)


def test_the_key_must_be_the_claim_types_hexagon():
    cfg = _raw("flood_water", 2)
    cells.check_report_position(cfg, FLOOD_KEY, [_obs(HERE)])
    with pytest.raises(cells.PositionError, match="resolution 10"):
        cells.check_report_position(cfg, f"earth:flood_water:h3:{CELL8}:surface:2026-10-05T09:00Z", [_obs(HERE)])
    with pytest.raises(cells.PositionError, match="earth.flood_water.v2 key"):
        cells.check_report_position(cfg, f"earth:sky_cover:h3:{CELL10}:surface:2026-10-05T09:00Z", [_obs(HERE)])
    with pytest.raises(cells.PositionError, match="H3 cell"):
        cells.check_report_position(cfg, "earth:flood_water:h3:abc:surface:2026-10-05T09:00Z", [_obs(HERE)])
    with pytest.raises(cells.PositionError, match="outside"):
        cells.check_report_position(cfg, FLOOD_KEY, [_obs(_offset(HERE["lat"], HERE["lon"], metres_east=1000))])
    # v1 types have no position rule: nothing is checked, as before
    cells.check_report_position(_raw("flood_water", 1), "earth:flood_water:h3:abc:surface:2026-10-05T09:00Z", [_obs(HERE)])


def test_the_generalist_uses_the_same_tolerance():
    neighbour = h3.cell_to_latlng(next(c for c in h3.grid_ring(CELL10, 1)))
    request = ValidatorRequest(truthkey_id=FLOOD_KEY, claim_type_id=FLOOD,
                               observations=[_obs({"lat": neighbour[0], "lon": neighbour[1]})])
    assert ClipGeneralistValidator._package_outside_truthkey_h3(request, _raw("flood_water", 2)) is False
    exact = copy.deepcopy(_raw("flood_water", 2))
    del exact["truthkey"]["position"]                              # without the rule: the exact hexagon
    assert ClipGeneralistValidator._package_outside_truthkey_h3(request, exact) is True


# ------------------------------------------------------------------------------------------- through the API

def _verify(token: str) -> str:
    if not token.startswith("tok-"):
        raise AuthError("invalid")
    return "user:" + token[4:]


def _h(name):
    return {"Authorization": f"Bearer tok-{name}"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, generalist_client=None,
                     evidence_store=InMemoryEvidenceStore(bucket_name="kaori-observations"))
    app.state.ai_reader = None
    app.state.ai_sync = True
    for name in ("madin", "amira", "omar", "v1", "v2", "v3"):
        antalya.seed_member(flow, "user:" + name, callsign=name.title())
    return TestClient(app), flow


def _report(client, who, claim=FLOOD, key=FLOOD_KEY, geo=HERE, payload=None, at="2026-10-05T09:00:30.000Z"):
    img = io.BytesIO()
    Image.new("RGB", (32, 24), (90, 120, 160)).save(img, format="JPEG", comment=(who + key).encode())
    ref = client.post("/v1/evidence", headers=_h(who), files={"file": ("f.jpg", img.getvalue(), "image/jpeg")}).json()
    obs = {"claim_type": claim, "reported_at": at, "geo": geo,
           "payload": payload or WATER, "evidence_refs": [ref]}
    return client.post("/v1/compile", headers=_h(who),
                       json={"claim_type_id": claim, "truth_key": key, "observations": [obs]})


def test_a_report_is_filed_on_its_res_10_hexagon(env):
    client, _ = env
    r = _report(client, "madin")
    assert r.status_code == 202, r.text
    assert r.json()["cell"] == CELL10 and r.json()["resolution"] == 10
    progress = client.get(f"/v1/progress/{FLOOD_KEY}", headers=_h("amira")).json()
    assert progress == {"truthkey": FLOOD_KEY, "cell": CELL10, "resolution": 10,
                        "received": 1, "required": 3, "status": "PENDING"}
    # a res 8 key, a fix 1 km away, and a fix with no position are refused before anything is stored
    assert _report(client, "amira", key=f"earth:flood_water:h3:{CELL8}:surface:2026-10-05T09:00Z").status_code == 400
    far = _report(client, "amira", geo=_offset(HERE["lat"], HERE["lon"], metres_east=1000))
    assert far.status_code == 400 and "outside" in far.json()["detail"]
    assert client.get(f"/v1/progress/{FLOOD_KEY}", headers=_h("amira")).json()["received"] == 1
    # GPS jitter into the next hexagon is still this hexagon's report
    neighbour = h3.cell_to_latlng(next(c for c in h3.grid_ring(CELL10, 1)))
    assert _report(client, "amira", geo={"lat": neighbour[0], "lon": neighbour[1], "accuracy_m": 12.0}).status_code == 202


def _three_reports_and_readings(client, claim, key):
    assert _report(client, "madin", claim=claim, key=key).status_code == 202
    assert _report(client, "amira", claim=claim, key=key).status_code == 202
    third = _report(client, "omar", claim=claim, key=key)
    assert third.status_code == 200, third.text
    assert third.json()["claim"] == WATER and third.json()["claim_type"] == claim
    for validator in ("v1", "v2", "v3"):
        for item in client.get("/v1/assignments?limit=5", headers=_h(validator)).json():
            assert item["claim_type_id"] == claim
            r = client.post(f"/v1/assignments/{item['assignment_id']}/reading", headers=_h(validator),
                            json={"values": {"water_present": True, "extent": "street"}})
            assert r.json() == {"ok": True}
    return client.get(f"/v1/truth/{key}", headers=_h("madin")).json()


def test_consensus_on_a_res_10_key_is_the_same_as_on_v1(env):
    client, flow = env
    # the AI reads each photo as a validator does (it sees the same water), as in production
    client.app.state.ai_reader = lambda claim_type_id, image: {"values": dict(WATER), "probs": {}, "relevance": 0.95}
    v2 = _three_reports_and_readings(client, FLOOD, FLOOD_KEY)
    votes = [(s.agent_id, s.payload["vote"]) for s in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE)]
    assert [v for a, v in votes if a.startswith("user:")] == ["RATIFY"] * 9
    assert [v for a, v in votes if a == antalya.AI_AGENT] == ["RATIFY"] * 3
    assert v2["consensus"]["finalized"] is True and v2["claim"] == WATER

    v1 = _three_reports_and_readings(client, "earth.flood_water.v1",
                                     f"earth:flood_water:h3:{CELL8}:surface:2026-10-05T09:00Z")
    for field in ("status", "claim", "confidence", "verification_basis"):
        assert v2[field] == v1[field], field
    assert (v2["consensus"]["score"], v2["consensus"]["finalized"]) == (v1["consensus"]["score"], v1["consensus"]["finalized"])


def test_truths_light_res_10_cells_from_their_own_cell_and_ancestors(env):
    client, _ = env
    sky = {"cover": "overcast", "raining": False}
    for who in ("madin", "amira", "omar"):
        _report(client, who)
        _report(client, who, claim=SKY, key=SKY_KEY, payload=sky)
    children = h3.cell_to_children(CELL8, 10)
    assert len(children) == 49 and CELL10 in children
    other_child = next(c for c in children if c != CELL10)
    outside = h3.cell_to_center_child(h3.grid_ring(CELL8, 1)[0], 10)    # under the next res 8 hexagon

    r = client.get("/v1/truths", headers=_h("v1"), params={"cells": f"{CELL10},{other_child},{outside}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cells"] == [CELL10, other_child, outside]
    by_claim = {t["claim_type_id"]: t for t in body["truths"]}
    assert set(by_claim) == {FLOOD, SKY}
    assert by_claim[SKY]["cell"] == CELL8 and by_claim[SKY]["resolution"] == 8
    assert by_claim[SKY]["lights"] == [CELL10, other_child]          # a res 8 truth lights its res 10 children
    assert by_claim[FLOOD]["cell"] == CELL10 and by_claim[FLOOD]["resolution"] == 10
    assert by_claim[FLOOD]["lights"] == [CELL10]
    assert by_claim[FLOOD]["truthkey"] == FLOOD_KEY and by_claim[FLOOD]["claim"] == WATER
    assert by_claim[FLOOD]["time_bucket"] == "2026-10-05T09:00Z"
    assert set(by_claim[FLOOD]) == {"truthkey", "claim_type_id", "cell", "resolution", "time_bucket", "status",
                                    "claim", "confidence", "lights"}

    # repeated cell=, a claim filter, a coarser requested cell, since, and nothing outside
    only = client.get("/v1/truths", headers=_h("v1"), params=[("cell", other_child), ("claim_type_id", SKY)]).json()
    assert [t["claim_type_id"] for t in only["truths"]] == [SKY]
    coarse = client.get("/v1/truths", headers=_h("v1"), params={"cells": CELL8}).json()
    assert {t["claim_type_id"]: t["lights"] for t in coarse["truths"]} == {FLOOD: [CELL8], SKY: [CELL8]}
    later = client.get("/v1/truths", headers=_h("v1"), params={"cells": CELL10, "since": "2026-10-05T10:00:00Z"}).json()
    assert later["truths"] == []
    assert client.get("/v1/truths", headers=_h("v1"), params={"cells": outside}).json()["truths"] == []


def test_truths_needs_cells_and_sign_in(env):
    client, _ = env
    assert client.get("/v1/truths", params={"cells": CELL10}).status_code == 401
    assert client.get("/v1/truths", headers=_h("v1")).status_code == 400
    assert client.get("/v1/truths", headers=_h("v1"), params={"cells": "nothex"}).status_code == 400
