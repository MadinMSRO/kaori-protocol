"""Antalya MVP: referral-only membership, provenance, blind assignments and readings, export (plan §3)."""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes

CLAIM = "earth.sky_cover.v1"
KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
KEY2 = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T10:00Z"
ANTALYA = {"lat": 36.8969, "lon": 30.7133}
NEW_SIGNALS = {
    SignalTypes.INVITE_ISSUED, SignalTypes.REFERRAL_REDEEMED, SignalTypes.PROVENANCE_RECORDED,
    SignalTypes.ASSIGNMENT_ISSUED, SignalTypes.READING_SUBMITTED,
}


def _verify(token: str) -> str:
    if not token.startswith("tok-"):
        raise AuthError("invalid")
    return "user:" + token[4:]


def _h(name: str) -> dict:
    return {"Authorization": f"Bearer tok-{name}"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    monkeypatch.setenv("KAORI_EXPORT_TOKEN", "export-secret")
    flow = FlowCore(store=InMemorySignalStore())
    store = InMemoryEvidenceStore(bucket_name="kaori-observations")
    client = TestClient(create_app(flow=flow, verify_token=_verify, evidence_store=store, generalist_client=None))
    return client, flow, store


def _join(client, flow, name, referrer="seed", device=None):
    if referrer == "seed":
        antalya.seed_member(flow, "user:" + name, callsign=name.title())
        return
    code = client.post("/v1/invites", headers=_h(referrer), json={"callsign": referrer.title()}).json()["code"]
    r = client.post("/v1/invites/redeem", headers=_h(name),
                    json={"code": code, "relationship": "colleague", "known_for": "1_5y",
                          "device_id": device or f"device-{name}-0001"})
    assert r.status_code == 200, r.text


def _jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (64, 48), (120, 160, 220))
    exif = Image.Exif()
    exif[0x9003] = "2026:10:05 12:00:00"           # DateTimeOriginal (local)
    exif[0x010F] = "PhoneMaker"                     # Make
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def _report(client, name, key=KEY, cover="overcast", raining=False, provenance=True, photo=None):
    data = photo or _jpeg_with_exif() + name.encode()
    ref = client.post("/v1/evidence", headers=_h(name), files={"file": (f"{name}.jpg", data, "image/jpeg")}).json()
    reported = datetime(2026, 10, 5, 9, 0, 30, tzinfo=timezone.utc)
    obs = {"claim_type": CLAIM, "reported_at": reported.isoformat(), "geo": ANTALYA,
           "payload": {"cover": cover, "raining": raining}, "evidence_refs": [ref]}
    if provenance:
        obs["provenance"] = {"exif": {"datetime_original": "2026:10:05 12:00:00", "tz_offset_min": 180,
                                      "gps": {"lat": 36.8970, "lon": 30.7134}},
                             "capture_source": "camera",
                             "device": {"platform": "android", "model": "Pixel 8", "app_version": "0.9.0"}}
    return client.post("/v1/compile", headers=_h(name), json={"claim_type_id": CLAIM, "truth_key": key,
                                                              "observations": [obs]})


# ------------------------------------------------------------------------------------------- mounting

def test_routes_mount_only_on_the_antalya_service(monkeypatch):
    monkeypatch.delenv("KAORI_ANTALYA", raising=False)
    plain = {getattr(r, "path", None) for r in create_app(flow=FlowCore(store=InMemorySignalStore()),
                                                          verify_token=_verify).router.routes}
    assert "/v1/invites" not in plain
    monkeypatch.setenv("KAORI_ANTALYA", "1")
    live = {getattr(r, "path", None) for r in create_app(flow=FlowCore(store=InMemorySignalStore()),
                                                         verify_token=_verify).router.routes}
    assert live - plain == {
        "/v1/invites", "/v1/invites/{code}", "/v1/invites/redeem", "/v1/assignments",
        "/v1/assignments/{assignment_id}/image", "/v1/assignments/{assignment_id}/reading", "/v1/export",
    }


# ------------------------------------------------------------------------------------------- invites

def test_invite_is_single_use_and_stored_only_as_a_hash(env):
    client, flow, _ = env
    _join(client, flow, "madin")
    made = client.post("/v1/invites", headers=_h("madin"), json={"callsign": "Heron"}).json()
    assert set(made) == {"code", "expires_at", "qr_payload"}
    assert made["qr_payload"].endswith(made["code"])
    check = client.get(f"/v1/invites/{made['code'].lower()}").json()
    assert check["valid"] and check["referrer_callsign"] == "Heron"

    body = {"code": made["code"], "relationship": "friend", "known_for": "gt_5y", "device_id": "install-aaaa-1111"}
    first = client.post("/v1/invites/redeem", headers=_h("amira"), json=body)
    assert first.status_code == 200 and first.json() == {"agent_id": "user:amira", "referrer": "user:madin"}
    again = client.post("/v1/invites/redeem", headers=_h("omar"), json=dict(body, device_id="install-bbbb-2222"))
    assert again.status_code == 410
    assert client.get(f"/v1/invites/{made['code']}").json() == {"valid": False, "reason": "used"}

    everything = json.dumps([s.model_dump(mode="json") for s in flow.store.get_all()])
    assert made["code"] not in everything and made["code"].replace("-", "") not in everything
    assert "install-aaaa-1111" not in everything


def test_invite_expires(env, monkeypatch):
    client, flow, _ = env
    _join(client, flow, "madin")
    code = client.post("/v1/invites", headers=_h("madin")).json()["code"]
    later = datetime.now(timezone.utc) + timedelta(days=8)
    monkeypatch.setattr(antalya, "_now", lambda: later)
    r = client.post("/v1/invites/redeem", headers=_h("amira"),
                    json={"code": code, "relationship": "friend", "known_for": "lt_1m", "device_id": "install-xyz-123"})
    assert r.status_code == 410


def test_one_device_one_member_and_answers_are_checked(env):
    client, flow, _ = env
    _join(client, flow, "madin")
    _join(client, flow, "amira", referrer="madin", device="install-shared-01")
    code = client.post("/v1/invites", headers=_h("madin")).json()["code"]
    bad = {"code": code, "relationship": "best_friend", "known_for": "1_5y", "device_id": "install-new-0001"}
    assert client.post("/v1/invites/redeem", headers=_h("omar"), json=bad).status_code == 400
    shared = dict(bad, relationship="friend", device_id="install-shared-01")
    assert client.post("/v1/invites/redeem", headers=_h("omar"), json=shared).status_code == 409


def test_only_members_can_invite_report_or_validate(env):
    client, flow, _ = env
    assert client.post("/v1/invites", headers=_h("stranger")).status_code == 403
    assert _report(client, "stranger").status_code == 403
    assert client.get("/v1/assignments", headers=_h("stranger")).status_code == 403


# ------------------------------------------------------------------------------------------- provenance

def test_provenance_is_recorded_with_its_checks(env):
    client, flow, _ = env
    _join(client, flow, "madin")
    assert _report(client, "madin").status_code == 202
    [signal] = flow.store.get_by_type(SignalTypes.PROVENANCE_RECORDED)
    assert signal.payload["capture_source"] == "camera"
    assert signal.payload["device"] == {"platform": "android", "model": "Pixel 8", "app_version": "0.9.0"}
    assert signal.payload["checks"] == {"in_app_capture": True, "time_matches": True, "place_matches": True}


def test_provenance_checks_catch_wrong_time_and_place():
    reported = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    far = antalya.provenance_checks({"capture_source": "gallery", "exif": {
        "datetime_original": "2026:10:04 08:00:00", "offset_time": "+03:00", "gps": {"lat": 37.5, "lon": 30.7}}},
        reported, ANTALYA)
    assert far == {"in_app_capture": False, "time_matches": False, "place_matches": False}
    unzoned = antalya.provenance_checks({"capture_source": "camera", "exif": {
        "datetime_original": "2026:10:05 12:01:00"}}, reported, ANTALYA)
    assert unzoned["time_matches"] is True and unzoned["place_matches"] is None


# ------------------------------------------------------------------------------------------- assignments

def _three_at_key(client, flow):
    for name in ("madin", "amira", "omar", "val"):
        _join(client, flow, name)
    for name, cover in (("madin", "overcast"), ("amira", "broken"), ("omar", "clear")):
        _report(client, name, cover=cover)


def test_assignments_are_blind_and_never_your_own(env):
    client, flow, _ = env
    _three_at_key(client, flow)
    mine = client.get("/v1/assignments?limit=5", headers=_h("madin")).json()
    assert mine == []                                   # every photo is from a key madin reported at
    got = client.get("/v1/assignments?limit=5", headers=_h("val")).json()
    assert len(got) == 3
    for item in got:
        assert set(item) == {"assignment_id", "image_url", "provenance_badge", "claim_type_id", "options", "expires_at"}
        assert set(item["provenance_badge"]) == {"in_app_capture", "time_matches", "place_matches"}
        assert KEY not in json.dumps(item) and "user:" not in json.dumps(item)
    again = client.get("/v1/assignments?limit=5", headers=_h("val")).json()
    assert sorted(a["assignment_id"] for a in again) == sorted(a["assignment_id"] for a in got)


def test_each_photo_gets_at_most_three_readers(env):
    client, flow, _ = env
    _three_at_key(client, flow)
    for name in ("r1", "r2", "r3", "r4"):
        _join(client, flow, name)
    counts = [len(client.get("/v1/assignments?limit=5", headers=_h(n)).json()) for n in ("val", "r1", "r2", "r3")]
    assert counts == [3, 3, 3, 0]


def test_image_is_served_only_to_its_validator_and_without_exif(env):
    client, flow, _ = env
    _three_at_key(client, flow)
    [first, *_] = client.get("/v1/assignments", headers=_h("val")).json()
    assert client.get(first["image_url"], headers=_h("madin")).status_code == 404
    r = client.get(first["image_url"], headers=_h("val"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(r.content)) as img:
        assert not dict(img.getexif())


def test_reading_records_a_signal_and_a_vote_once(env):
    client, flow, _ = env
    _three_at_key(client, flow)
    [first, *_] = client.get("/v1/assignments", headers=_h("val")).json()
    url = f"/v1/assignments/{first['assignment_id']}/reading"
    assert client.post(url, headers=_h("madin"), json={"cover": "overcast", "raining": False}).status_code == 404
    assert client.post(url, headers=_h("val"), json={"cover": "grey", "raining": False}).status_code == 400
    assert client.post(url, headers=_h("val"), json={"cover": "overcast", "raining": False}).json() == {"ok": True}
    assert client.post(url, headers=_h("val"), json={"cover": "overcast", "raining": False}).status_code == 409
    [reading] = flow.store.get_by_type(SignalTypes.READING_SUBMITTED)
    assert reading.payload["value"] == {"cover": "overcast", "raining": False}
    votes = [s for s in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) if s.agent_id == "user:val"]
    assert len(votes) == 1 and votes[0].object_id == KEY


def test_reading_to_vote_adapter():
    eye = {"cover": "broken", "raining": False}
    assert antalya.vote_for({"cover": "overcast", "raining": False}, eye) == "RATIFY"
    assert antalya.vote_for({"cover": "scattered", "raining": False}, eye) == "RATIFY"
    assert antalya.vote_for({"cover": "few", "raining": False}, eye) == "REJECT"
    assert antalya.vote_for({"cover": "broken", "raining": True}, eye) == "REJECT"


# ------------------------------------------------------------------------------------------- export

def test_export_requires_the_admin_token_and_holds_every_signal_type(env):
    client, flow, _ = env
    _join(client, flow, "madin")
    _join(client, flow, "amira", referrer="madin")
    for name in ("omar", "val"):
        _join(client, flow, name)
    for name in ("madin", "amira", "omar"):
        _report(client, name)
    for item in client.get("/v1/assignments", headers=_h("val")).json():
        client.post(f"/v1/assignments/{item['assignment_id']}/reading", headers=_h("val"),
                    json={"cover": "overcast", "raining": False})
    assert client.get("/v1/export").status_code == 403
    assert client.get("/v1/export", headers={"Authorization": "Bearer nope"}).status_code == 403
    r = client.get("/v1/export", headers={"Authorization": "Bearer export-secret"})
    assert r.status_code == 200
    rows = [json.loads(line) for line in r.text.splitlines()]
    types = {row["signal_type"] for row in rows if row["kind"] == "signal"}
    assert NEW_SIGNALS <= types
    assert any(row["kind"] == "truthstate" and row["truthkey"] == KEY for row in rows)
