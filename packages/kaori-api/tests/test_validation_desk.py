"""Validation desk: validators check photo, data, audio and video evidence, without seeing whose report it is."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from kaori_api import antalya, evidence_kinds
from kaori_api.app import create_app
from kaori_api.auth import AuthError
from kaori_api.evidence_store import InMemoryEvidenceStore
from kaori_flow import FlowCore, InMemorySignalStore
from kaori_flow.primitives.signal import SignalTypes
from kaori_truth.factory import load_claim_type

SCHEMAS = Path(__file__).resolve().parents[2] / "kaori-spec" / "schemas"
SKY = "earth.sky_cover.v1"
FLOOD = "earth.flood_water.v1"
SKY_KEY = "earth:sky_cover:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
FLOOD_KEY = "earth:flood_water:h3:883f6e36d3fffff:surface:2026-10-05T09:00Z"
ANTALYA = {"lat": 36.8969, "lon": 30.7133}
COVER_LABELS = {"clear": "None", "few": "A little", "scattered": "About half", "broken": "Most", "overcast": "All"}

SAMPLES = {
    "photo": [("image/jpeg", "p.jpg"), ("image/png", "p.png"), ("image/heic", "p.heic"), ("image/webp", "p.webp")],
    "data": [("application/json", "d.json"), ("text/csv", "d.csv")],
    "audio": [("audio/mpeg", "a.mp3"), ("audio/mp4", "a.m4a"), ("audio/aac", "a.aac"), ("audio/wav", "a.wav"),
              ("audio/x-wav", "a.wav"), ("audio/ogg", "a.ogg"), ("audio/webm", "a.weba")],
    "video": [("video/mp4", "v.mp4"), ("video/quicktime", "v.mov"), ("video/webm", "v.webm")],
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
    flow = FlowCore(store=InMemorySignalStore())
    app = create_app(flow=flow, verify_token=_verify, generalist_client=None,
                     evidence_store=InMemoryEvidenceStore(bucket_name="kaori-observations"))
    app.state.ai_reader = None          # no AI reader: only people's readings in these tests
    app.state.ai_sync = True
    for name in ("madin", "amira", "omar", "val"):
        antalya.seed_member(flow, "user:" + name, callsign=name.title())
    return TestClient(app), flow


def _jpeg_with_exif(salt: bytes = b"") -> bytes:
    img = Image.new("RGB", (64, 48), (120, 160, 220))
    exif = Image.Exif()
    exif[0x9003] = "2026:10:05 12:00:00"
    exif[0x010F] = "PhoneMaker"
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue() + salt


def _upload(client, name, data: bytes, mime: str, filename: str):
    return client.post("/v1/evidence", headers=_h(name), files={"file": (filename, data, mime)})


def _report(client, name, refs, claim=SKY, key=SKY_KEY, payload=None):
    obs = {"claim_type": claim, "reported_at": datetime(2026, 10, 5, 9, 0, 30, tzinfo=timezone.utc).isoformat(),
           "geo": ANTALYA, "payload": payload or {"cover": "overcast", "raining": False}, "evidence_refs": refs}
    r = client.post("/v1/compile", headers=_h(name), json={"claim_type_id": claim, "truth_key": key,
                                                           "observations": [obs]})
    assert r.status_code in (200, 202), r.text
    return r


def _photo_report(client, name="madin", **kw):
    ref = _upload(client, name, _jpeg_with_exif(name.encode()), "image/jpeg", f"{name}.jpg").json()
    return _report(client, name, [ref], **kw)


# ------------------------------------------------------------------------------------------- assignment shape

def test_assignment_has_evidence_questions_and_the_older_fields(env):
    client, _ = env
    _photo_report(client)
    [item] = client.get("/v1/assignments", headers=_h("val")).json()
    aid = item["assignment_id"]
    assert set(item) == {"assignment_id", "claim_type_id", "title", "provenance_badge", "expires_at", "evidence",
                         "questions", "image_url", "options"}
    assert item["claim_type_id"] == SKY and item["title"] == "Sky cover"
    assert item["evidence"] == [{"kind": "photo", "mime": "image/jpeg", "url": f"/v1/assignments/{aid}/evidence/0"}]
    assert item["questions"] == [
        {"name": "cover", "type": "select", "label": "How much of the sky is cloud?",
         "options": ["clear", "few", "scattered", "broken", "overcast"], "option_labels": COVER_LABELS},
        {"name": "raining", "type": "boolean", "label": "Is it raining here?"},
    ]
    assert item["image_url"] == f"/v1/assignments/{aid}/image"
    assert item["options"] == {"cover": ["clear", "few", "scattered", "broken", "overcast"], "raining": [True, False]}
    text = json.dumps(item)
    assert SKY_KEY not in text and "user:" not in text and "36.89" not in text


# ------------------------------------------------------------------------------------------- upload

@pytest.mark.parametrize("kind,mime,filename", [(k, m, f) for k, items in SAMPLES.items() for m, f in items])
def test_each_evidence_kind_is_accepted(env, kind, mime, filename):
    client, _ = env
    r = _upload(client, "madin", f"{kind}:{mime}".encode(), mime, filename)
    assert r.status_code == 200, r.text
    assert r.json()["mime_type"] == mime
    assert evidence_kinds.kind_of(mime) == kind


@pytest.mark.parametrize("mime", ["application/zip", "text/html", "image/gif", "application/octet-stream"])
def test_an_unsupported_type_is_refused(env, mime):
    client, _ = env
    r = _upload(client, "madin", b"anything", mime, "x.bin")
    assert r.status_code == 415
    assert "cannot be used as evidence" in r.json()["detail"]


def test_data_has_its_own_size_limit(env):
    client, _ = env
    big = b"[" + b"1," * (1024 * 1024) + b"1]"
    assert _upload(client, "madin", big, "application/json", "big.json").status_code == 400
    assert _upload(client, "madin", big, "image/jpeg", "big.jpg").status_code == 200   # a photo keeps the store's limit


# ------------------------------------------------------------------------------------------- serving

def _assigned_with(client, refs):
    _report(client, "madin", refs)
    [item] = client.get("/v1/assignments", headers=_h("val")).json()
    return item


def test_photo_and_data_are_served_without_place_time_or_person(env):
    client, _ = env
    photo = _upload(client, "madin", _jpeg_with_exif(), "image/jpeg", "s.jpg").json()
    doc = {"cover_pct": 82, "lat": 36.9, "lon": 30.7, "timestamp": "2026-10-05T09:00:00Z", "user_id": "u1",
           "deviceId": "pixel", "readings": [{"value": 3.2, "time": "09:00", "location": "pier"}]}
    data = _upload(client, "madin", json.dumps(doc).encode(), "application/json", "d.json").json()
    table = "depth_m,Latitude,longitude,reported_at,reporter,note\n4.5,36.9,30.7,2026-10-05,madin,clear\n"
    sheet = _upload(client, "madin", table.encode(), "text/csv", "d.csv").json()
    item = _assigned_with(client, [photo, data, sheet])
    assert [e["kind"] for e in item["evidence"]] == ["photo", "data", "data"]
    assert [e["mime"] for e in item["evidence"]] == ["image/jpeg", "application/json", "text/csv"]

    assert client.get(item["evidence"][0]["url"], headers=_h("amira")).status_code == 404   # validator only
    r = client.get(item["evidence"][0]["url"], headers=_h("val"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(r.content)) as img:
        assert not dict(img.getexif())

    r = client.get(item["evidence"][1]["url"], headers=_h("val"))
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"cover_pct": 82, "readings": [{"value": 3.2}]}

    r = client.get(item["evidence"][2]["url"], headers=_h("val"))
    assert r.headers["content-type"].startswith("text/csv")
    assert list(csv.reader(io.StringIO(r.text))) == [["depth_m", "note"], ["4.5", "clear"]]

    assert client.get(f"/v1/assignments/{item['assignment_id']}/evidence/3", headers=_h("val")).status_code == 404


def test_data_only_evidence_is_assigned_and_has_no_image(env):
    client, _ = env
    data = _upload(client, "madin", b'{"cover_pct": 10}', "application/json", "d.json").json()
    item = _assigned_with(client, [data])
    assert item["evidence"][0]["kind"] == "data" and item["image_url"] is None
    assert client.get(f"/v1/assignments/{item['assignment_id']}/image", headers=_h("val")).status_code == 404


def test_recordings_are_served_as_stored_when_ffmpeg_is_missing(env, monkeypatch, caplog):
    client, _ = env
    monkeypatch.setattr(evidence_kinds.shutil, "which", lambda name: None)
    monkeypatch.setattr(evidence_kinds, "_warned_no_ffmpeg", False)
    audio = _upload(client, "madin", b"ID3-audio-bytes", "audio/mpeg", "a.mp3").json()
    video = _upload(client, "madin", b"mp4-video-bytes", "video/mp4", "v.mp4").json()
    item = _assigned_with(client, [audio, video])
    assert [e["kind"] for e in item["evidence"]] == ["audio", "video"]
    with caplog.at_level("WARNING"):
        a = client.get(item["evidence"][0]["url"], headers=_h("val"))
        v = client.get(item["evidence"][1]["url"], headers=_h("val"))
    assert (a.content, a.headers["content-type"]) == (b"ID3-audio-bytes", "audio/mpeg")
    assert (v.content, v.headers["content-type"]) == (b"mp4-video-bytes", "video/mp4")
    assert sum("ffmpeg" in rec.message for rec in caplog.records) == 1


# ------------------------------------------------------------------------------------------- readings

def _assignment(client, validator="val"):
    [item] = client.get("/v1/assignments", headers=_h(validator)).json()
    return f"/v1/assignments/{item['assignment_id']}/reading"


def _human_reading(flow, who="user:val"):
    [r] = [r for r in flow.store.get_by_type(SignalTypes.READING_SUBMITTED) if r.agent_id == who]
    return r


def _human_vote(flow, who="user:val"):
    [v] = [v for v in flow.store.get_by_type(SignalTypes.VALIDATION_VOTE) if v.agent_id == who]
    return v.payload["vote"]


def test_reading_with_values(env):
    client, flow = env
    _photo_report(client)
    url = _assignment(client)
    assert client.post(url, headers=_h("val"), json={"values": {"cover": "broken"}}).status_code == 400
    assert client.post(url, headers=_h("val"), json={"values": {"cover": "broken", "raining": "no"}}).status_code == 400
    assert client.post(url, headers=_h("val"), json={"values": "overcast"}).status_code == 400
    r = client.post(url, headers=_h("val"), json={"values": {"cover": "broken", "raining": False}})
    assert r.json() == {"ok": True}
    assert _human_reading(flow).payload["value"] == {"cover": "broken", "raining": False}
    assert _human_vote(flow) == "RATIFY"


def test_reading_with_the_older_body(env):
    client, flow = env
    _photo_report(client)
    url = _assignment(client)
    assert client.post(url, headers=_h("val"), json={"cover": "grey", "raining": False}).status_code == 400
    assert client.post(url, headers=_h("val"), json={"cover": "clear", "raining": False}).json() == {"ok": True}
    assert _human_reading(flow).payload["value"] == {"cover": "clear", "raining": False}
    assert _human_vote(flow) == "REJECT"


def test_unusable_evidence_is_a_reject(env):
    client, flow = env
    _photo_report(client)
    url = _assignment(client)
    assert client.post(url, headers=_h("val"), json={"values": None, "unusable": True}).json() == {"ok": True}
    reading = _human_reading(flow)
    assert reading.payload["unusable"] is True and reading.payload["value"] is None
    assert _human_vote(flow) == "REJECT"
    assert client.post(url, headers=_h("val"), json={"values": None, "unusable": True}).status_code == 409


# ------------------------------------------------------------------------------------------- agreement

def _secchi(agree=None):
    field = {"name": "depth_m", "type": "number", "label": "Secchi depth", "required": True,
             "unit": "m", "min": 0, "max": 60, "step": 0.1}
    cfg = {"id": "ocean.secchi.v1", "topic": "secchi", "ui_schema": {"fields": [field]}}
    if agree is not None:
        cfg["validation"] = {"fields": [{"name": "depth_m", "agree": agree}]}
    return cfg


def test_number_agreement_within_an_absolute_amount():
    cfg = _secchi({"within": 0.5})
    assert antalya.vote_for({"depth_m": 4.5}, {"depth_m": 4.0}, cfg) == "RATIFY"
    assert antalya.vote_for({"depth_m": 3.5}, {"depth_m": 4.0}, cfg) == "RATIFY"
    assert antalya.vote_for({"depth_m": 4.6}, {"depth_m": 4.0}, cfg) == "REJECT"
    assert antalya.vote_for({"depth_m": 4.0}, {}, cfg) == "REJECT"


def test_number_agreement_within_a_percentage_and_the_default_rule():
    assert antalya.vote_for({"depth_m": 11}, {"depth_m": 10}, _secchi({"within_pct": 10})) == "RATIFY"
    assert antalya.vote_for({"depth_m": 11.5}, {"depth_m": 10}, _secchi({"within_pct": 10})) == "REJECT"
    derived = _secchi()                                      # no validation block: a number within 10 percent
    assert antalya.validation_fields(derived) == [{"name": "depth_m", "agree": {"within_pct": 10}}]
    assert antalya.vote_for({"depth_m": 9.0}, {"depth_m": 10}, derived) == "RATIFY"
    assert antalya.vote_for({"depth_m": 8.9}, {"depth_m": 10}, derived) == "REJECT"


def test_number_questions_carry_unit_and_range_and_are_checked():
    cfg = _secchi({"within": 0.5})
    assert antalya.questions(cfg) == [{"name": "depth_m", "type": "number", "label": "Secchi depth",
                                       "unit": "m", "min": 0, "max": 60, "step": 0.1}]
    assert antalya.check_values({"depth_m": 12.3}, cfg) == {"depth_m": 12.3}
    for bad in (61, -1, float("inf"), float("nan"), "4", True):
        with pytest.raises(Exception) as exc:
            antalya.check_values({"depth_m": bad}, cfg)
        assert exc.value.status_code == 400


def test_sky_cover_agreement_is_unchanged():
    def before(reading, eye):          # the rule before the validation block: one band, same rain
        cover = ("clear", "few", "scattered", "broken", "overcast")
        close = abs(cover.index(reading["cover"]) - cover.index(eye["cover"])) <= 1
        return "RATIFY" if close and reading["raining"] == eye["raining"] else "REJECT"

    sky = load_claim_type(SCHEMAS / "earth" / "sky_cover_v1.yaml")
    assert antalya.validation_fields(sky) == [{"name": "cover", "agree": {"within_steps": 1}},
                                              {"name": "raining", "agree": "equal"}]
    assert antalya.questions(sky)[0]["option_labels"] == COVER_LABELS
    for a in antalya.COVER:
        for b in antalya.COVER:
            for ra in (True, False):
                for rb in (True, False):
                    reading, eye = {"cover": a, "raining": ra}, {"cover": b, "raining": rb}
                    assert antalya.vote_for(reading, eye, sky) == before(reading, eye)
                    assert antalya.vote_for(reading, eye) == before(reading, eye)
    assert antalya.vote_for({"cover": "overcast", "raining": False}, {"cover": "grey", "raining": False}, sky) == "REJECT"


def test_flood_readings_can_ratify(env):
    flood = load_claim_type(SCHEMAS / "earth" / "flood_water_v1.yaml")
    assert antalya.validation_fields(flood) == [{"name": "water_present", "agree": "equal"},
                                                {"name": "extent", "agree": {"within_steps": 1}}]
    eye = {"water_present": True, "extent": "street"}
    assert antalya.vote_for({"water_present": True, "extent": "block"}, eye, flood) == "RATIFY"
    assert antalya.vote_for({"water_present": False, "extent": "street"}, eye, flood) == "REJECT"
    assert antalya.vote_for({"water_present": True, "extent": "widespread"}, eye, flood) == "REJECT"

    client, flow = env
    ref = _upload(client, "madin", _jpeg_with_exif(b"flood"), "image/jpeg", "f.jpg").json()
    _report(client, "madin", [ref], claim=FLOOD, key=FLOOD_KEY, payload=eye)
    [item] = client.get("/v1/assignments", headers=_h("val")).json()
    assert item["title"] == "Flood water"
    assert [q["name"] for q in item["questions"]] == ["water_present", "extent"]
    r = client.post(f"/v1/assignments/{item['assignment_id']}/reading", headers=_h("val"),
                    json={"values": {"water_present": True, "extent": "street"}})
    assert r.json() == {"ok": True}
    assert _human_vote(flow) == "RATIFY"
