"""Antalya MVP: referral-only membership, provenance, validators' assignments and readings, export (plan §3)."""
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
AI_SEES = {"values": {"cover": "overcast", "raining": False}, "probs": {}, "relevance": 0.97}
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
    app = create_app(flow=flow, verify_token=_verify, evidence_store=store, generalist_client=None)
    app.state.ai_reader = lambda claim_type_id, image: dict(AI_SEES)   # stands in for CLIP's reading
    app.state.ai_sync = True
    client = TestClient(app)
    return client, flow, store


def _join(client, flow, name, referrer="seed", device=None):
    if referrer == "seed":
        antalya.seed_member(flow, "user:" + name, callsign=name.title())
        return
    made = client.post("/v1/invites", headers=_h(referrer), json={"callsign": referrer.title()}).json()
    r = client.post("/v1/invites/redeem", headers=_h(name),
                    json={"code": made["code"], "relationship": "colleague", "known_for": "1_5y",
                          "device_id": device or f"device-{name}-0001"})
    assert r.status_code == 200, r.text
    # the in-person handshake: the inviter confirms who is joining
    assert client.post(f"/v1/invites/{made['id']}/confirm", headers=_h(referrer)).status_code == 200


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
        "/v1/invites", "/v1/invites/{code}", "/v1/invites/redeem", "/v1/invites/mine",
        "/v1/invites/{invite_id}/{action}", "/v1/joining/hold", "/v1/admin/invites", "/v1/assignments",
        "/v1/assignments/{assignment_id}/image", "/v1/assignments/{assignment_id}/evidence/{index}",
        "/v1/assignments/{assignment_id}/reading", "/v1/export",
        "/v1/me", "/v1/devices/challenge", "/v1/devices/link",
        "/v1/admin/me", "/v1/admin/overview", "/v1/admin/members", "/v1/admin/truths", "/v1/admin/devices",
        "/v1/admin/seeds", "/v1/admin/devices/{device_id}/unlink", "/v1/admin/export",
    }


# ------------------------------------------------------------------------------------------- invites

def test_invite_is_single_use_and_stored_only_as_a_hash(env):
    client, flow, _ = env
    _join(client, flow, "madin")
    made = client.post("/v1/invites", headers=_h("madin"), json={"callsign": "Heron"}).json()
    assert set(made) == {"code", "id", "expires_at", "qr_payload"}
    assert made["qr_payload"].endswith(made["code"])
    check = client.get(f"/v1/invites/{made['code'].lower()}").json()
    assert check["valid"] and check["referrer_callsign"] == "Heron"

    body = {"code": made["code"], "relationship": "friend", "known_for": "gt_5y", "device_id": "install-aaaa-1111"}
    first = client.post("/v1/invites/redeem", headers=_h("amira"), json=body)
    assert first.status_code == 200
    assert (first.json()["agent_id"], first.json()["referrer"], first.json()["member"]) == ("user:amira", "user:madin", False)
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
    later = datetime.now(timezone.utc) + timedelta(minutes=31)   # an invite QR lasts 30 minutes
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
    assert signal.payload["checks"] == {"in_app_capture": True, "time_matches": True, "place_matches": True,
                                        "zoom_matches": None, "device_signed": False}


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


def test_assignments_hide_the_reporter_and_are_never_your_own(env):
    client, flow, _ = env
    _three_at_key(client, flow)
    mine = client.get("/v1/assignments?limit=5", headers=_h("madin")).json()
    assert mine == []                                   # every photo is from a key madin reported at
    got = client.get("/v1/assignments?limit=5", headers=_h("val")).json()
    assert len(got) == 3
    for item in got:
        assert set(item) == {"assignment_id", "claim_type_id", "title", "provenance_badge", "expires_at", "evidence",
                             "questions", "image_url", "options"}
        assert set(item["provenance_badge"]) == {"in_app_capture", "time_matches", "place_matches", "zoom_matches", "device_signed"}
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
    [reading] = [r for r in flow.store.get_by_type(SignalTypes.READING_SUBMITTED) if r.agent_id == "user:val"]
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


# ------------------------------------------------------------------------------------------- key-level compile

def _read_all(client, validator, choose):
    for item in client.get("/v1/assignments?limit=5", headers=_h(validator)).json():
        cover = choose(item)
        client.post(f"/v1/assignments/{item['assignment_id']}/reading", headers=_h(validator),
                    json={"cover": cover, "raining": False})


def _ai_vote(client, confidence=0.9):
    """The generalist's vote, as the critical lane records it in production (AI >= 0.82 plus humans)."""
    from kaori_api.app import record_vote
    record_vote(client.app, "ai:generalist_v1", KEY, "RATIFY", confidence)


def _status(client):
    return client.get(f"/v1/truth/{KEY}", headers=_h("madin")).json()["status"]


def test_per_observation_votes_ratify_the_key(env):
    client, flow, _ = env
    for name in ("madin", "amira", "omar", "v1", "v2", "v3"):
        _join(client, flow, name)
    for name in ("madin", "amira", "omar"):
        _report(client, name, cover="overcast")
    assert _status(client) != "VERIFIED_TRUE"          # no human ratification yet
    for v in ("v1", "v2", "v3"):
        _read_all(client, v, lambda item: "overcast")
    assert _status(client) == "VERIFIED_TRUE"


def test_an_unread_observation_does_not_block_its_key(env, monkeypatch):
    client, flow, _ = env
    for name in ("madin", "amira", "omar", "v1", "v2", "v3"):
        _join(client, flow, name)
    for name in ("madin", "amira", "omar"):
        _report(client, name, cover="overcast")
    omar = {p["sha"] for p in antalya._evidence_items(flow, client.app.state.observation_store) if p["reporter"] == "user:omar"}
    real = antalya._evidence_items
    monkeypatch.setattr(antalya, "_evidence_items", lambda f, s: [p for p in real(f, s) if p["sha"] not in omar])
    for v in ("v1", "v2", "v3"):
        _read_all(client, v, lambda item: "overcast")
    readings = [r for r in flow.store.get_by_type(SignalTypes.READING_SUBMITTED) if r.agent_id.startswith("user:")]
    assert len(readings) == 6 and not omar & {r.payload["evidence_sha256"] for r in readings}
    assert _status(client) == "VERIFIED_TRUE"


def test_a_rejected_lie_does_not_flip_the_key_whatever_the_order(env):
    """Two honest photos and one eye lie: 6 RATIFY and 3 REJECT must verify, even if the REJECTs come last."""
    client, flow, _ = env
    for name in ("madin", "amira", "omar", "v1", "v2", "v3"):
        _join(client, flow, name)
    _report(client, "madin", cover="overcast")
    _report(client, "amira", cover="overcast")
    _report(client, "omar", cover="clear")             # the photo shows overcast; the eye says clear
    liar = {p["sha"] for p in antalya._evidence_items(flow, client.app.state.observation_store) if p["reporter"] == "user:omar"}
    later = []
    for v in ("v1", "v2", "v3"):
        for item in client.get("/v1/assignments?limit=5", headers=_h(v)).json():
            sig = flow.store.get_by_type(SignalTypes.ASSIGNMENT_ISSUED)
            sha = next(s.payload["evidence_sha256"] for s in sig if s.object_id.endswith(item["assignment_id"]))
            (later if sha in liar else []).append((v, item)) if sha in liar else client.post(
                f"/v1/assignments/{item['assignment_id']}/reading", headers=_h(v), json={"cover": "overcast", "raining": False})
    for v, item in later:                               # the lie's REJECTs arrive last
        client.post(f"/v1/assignments/{item['assignment_id']}/reading", headers=_h(v), json={"cover": "overcast", "raining": False})
    votes = [s.payload.get("vote") for s in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) if s.agent_id.startswith("user:")]
    assert votes.count("RATIFY") == 6 and votes.count("REJECT") == 3 and votes[-1] == "REJECT"
    assert _status(client) == "VERIFIED_TRUE"


def test_the_ai_reads_every_photo_like_a_validator_and_alone_cannot_verify(env):
    client, flow, store = env
    seen = []
    client.app.state.ai_reader = lambda claim_type_id, image: seen.append(image) or dict(AI_SEES)
    for name in ("madin", "amira", "omar"):
        _join(client, flow, name)
        _report(client, name, cover="overcast")
    ai = [r for r in flow.store.get_by_type(SignalTypes.READING_SUBMITTED) if r.agent_id == antalya.AI_AGENT]
    assert len(ai) == 3 and all(r.payload["value"] == {"cover": "overcast", "raining": False} for r in ai)
    for image in seen:                                       # the AI gets what a human gets: no EXIF
        with Image.open(io.BytesIO(image)) as img:
            assert not dict(img.getexif())
    assert _status(client) != "VERIFIED_TRUE"               # one agent, counted once, cannot reach the threshold


def test_an_ai_that_sees_no_sky_backs_nothing(env):
    client, flow, _ = env
    client.app.state.ai_reader = lambda claim_type_id, image: {"values": {"cover": "clear", "raining": False}, "relevance": 0.1}
    _join(client, flow, "madin")
    _report(client, "madin", cover="clear")
    [r] = [r for r in flow.store.get_by_type(SignalTypes.READING_SUBMITTED) if r.agent_id == antalya.AI_AGENT]
    assert r.payload["value"] is None
    [v] = [v for v in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) if v.agent_id == antalya.AI_AGENT]
    assert v.payload["vote"] == "REJECT"


def test_seed_command_needs_only_the_ledger(monkeypatch, capsys):
    # the seed job runs with DATABASE_URL alone (no bucket, no Supabase), so it must not build the API
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert antalya.main(["seed", "user:someone"]) == 2
    assert "DATABASE_URL is required" in capsys.readouterr().out



@pytest.mark.parametrize("provenance,expected", [
    ({"camera": {"zoom": 1}}, True),                                     # the app's camera, held at 1x
    ({"camera": {"zoom": 1}, "exif": {"digital_zoom": 1.0}}, True),
    ({"camera": {"zoom": 1}, "exif": {"digital_zoom": 0}}, True),        # 0 = no digital zoom (EXIF)
    ({"camera": {"zoom": 2}}, False),
    ({"camera": {"zoom": 1}, "exif": {"digital_zoom": 3.2}}, False),     # declared 1x, the photo says otherwise
    ({"exif": {"digital_zoom": 2.0}}, False),
    ({"exif": {"digital_zoom": 1.0}}, True),
    ({}, None),                                                          # nothing to go on
])
def test_sky_photos_must_be_taken_at_1x(provenance, expected):
    assert antalya.zoom_check(provenance, {"camera_zoom": 1}) is expected
    assert antalya.zoom_check(provenance, None) is None                  # a ClaimType without the rule


def test_the_sky_claimtype_declares_1x():
    from pathlib import Path
    from kaori_truth.factory import load_claim_type
    spec = Path(__file__).parents[2] / "kaori-spec/schemas"
    ct = load_claim_type(spec / "earth/sky_cover_v1.yaml", str(spec))
    assert ct.get_config()["evidence"]["capture"] == {"camera_zoom": 1}
