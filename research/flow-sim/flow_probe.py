# Sky cover disagreements through Kaori Flow on a local sidecar: who wins the claim, what the
# status is, and how each agent's standing moves at settlement. Every photo is of a clear sky.
import hashlib, io, json, httpx, h3
from datetime import datetime, timezone, timedelta
c = httpx.Client(base_url="http://127.0.0.1:8787", timeout=60)
H = lambda who: {"Authorization": "Bearer tok-" + who}
AI = {"Authorization": "Bearer ai-generalist"}
def standing(who):
    r = c.get("/v1/standing/user:" + who, headers=H(who))
    return round(r.json()["standing"], 1) if r.status_code == 200 else None
def fmt(b, a):
    if b is None: return f"new→{a}"
    return f"{b}→{a} ({a-b:+.1f})"
def run(n, name, reports, ai_conf, human):
    t = datetime.now(timezone.utc) - timedelta(hours=n)
    lat, lon = 36.8969, 30.7133
    key = f"earth:sky_cover:h3:{h3.latlng_to_cell(lat, lon, 8)}:surface:{t.strftime('%Y-%m-%dT%H:00Z')}"
    people = [w for w, _ in reports] + [v for v, _ in human]
    before = {p: standing(p) for p in people}
    for who, cover in reports:
        photo = (f"clear sky photo {who} {name}").encode() + bytes(range(256)) * 20
        ev = c.post("/v1/evidence", headers=H(who), files={"file": (who + ".jpg", io.BytesIO(photo), "image/jpeg")}, data={"expected_sha256": hashlib.sha256(photo).hexdigest()}).json()
        body = {"truth_key": key, "claim_type_id": "earth.sky_cover.v1", "observations": [{"claim_type": "earth.sky_cover.v1", "reported_at": t.isoformat(), "geo": {"lat": lat, "lon": lon}, "payload": {"cover": cover, "raining": False}, "evidence_refs": [ev]}]}
        c.post("/v1/compile", headers=H(who), json=body).raise_for_status()
    after_ai = c.post("/v1/validate", headers=AI, json={"truth_key": key, "vote": "RATIFY", "confidence": ai_conf}).json().get("status")
    for who, vote in human:
        c.post("/v1/validate", headers=H(who), json={"truth_key": key, "vote": vote, "confidence": 0.9})
    t_ = c.get("/v1/truth/" + key, headers=H(people[0])).json()
    after = {p: standing(p) for p in people}
    print(f"\n== {name}")
    print("  reports:", ", ".join(f"{w} says {cv}" for w, cv in reports), f"| AI RATIFY {ai_conf} | human:", ", ".join(f"{v} {x}" for v, x in human))
    print("  after AI:", after_ai, "-> final:", t_.get("status"), "| claim:", json.dumps(t_.get("claim")), "| flags:", t_.get("transparency_flags"))
    print("  standing:", ", ".join(f"{p} {fmt(before[p], after[p])}" for p in people))
run(1, "S1 one wrong report, validator ratifies", [("A1", "clear"), ("B1", "clear"), ("L1", "overcast")], 0.97, [("V1", "RATIFY")])
run(2, "S2 two wrong reports outvote the true one, validator ratifies", [("A2", "clear"), ("L2", "overcast"), ("M2", "overcast")], 0.97, [("V2", "RATIFY")])
run(3, "S3 two wrong reports, validator looks at the photos and rejects", [("A3", "clear"), ("L3", "overcast"), ("M3", "overcast")], 0.97, [("V3", "REJECT")])
