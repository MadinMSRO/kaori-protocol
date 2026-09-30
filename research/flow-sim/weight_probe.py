# Does standing outweigh numbers? Build one reporter's record (E) through verified truths, then
# replay scenario 2: E says clear, two newcomers say overcast, on clear photos.
import hashlib, io, json, httpx, h3
from datetime import datetime, timezone, timedelta
c = httpx.Client(base_url="http://127.0.0.1:8787", timeout=60)
H = lambda w: {"Authorization": "Bearer tok-" + w}
def standing(w):
    r = c.get("/v1/standing/user:" + w, headers=H(w)); return round(r.json()["standing"], 1) if r.status_code == 200 else 200.0
t0 = datetime.now(timezone.utc) - timedelta(days=2)
def truth(i, reports, human="RATIFY"):
    lat, lon = 36.80 + i * 0.01, 30.70
    t = t0 + timedelta(hours=i)
    key = f"earth:sky_cover:h3:{h3.latlng_to_cell(lat, lon, 8)}:surface:{t.strftime('%Y-%m-%dT%H:00Z')}"
    for who, cover in reports:
        photo = f"sky {who} {i}".encode() + bytes(range(256)) * 20
        ev = c.post("/v1/evidence", headers=H(who), files={"file": (who + ".jpg", io.BytesIO(photo), "image/jpeg")}, data={"expected_sha256": hashlib.sha256(photo).hexdigest()}).json()
        c.post("/v1/compile", headers=H(who), json={"truth_key": key, "claim_type_id": "earth.sky_cover.v1", "observations": [{"claim_type": "earth.sky_cover.v1", "reported_at": t.isoformat(), "geo": {"lat": lat, "lon": lon}, "payload": {"cover": cover, "raining": False}, "evidence_refs": [ev]}]}).raise_for_status()
    c.post("/v1/validate", headers={"Authorization": "Bearer ai-generalist"}, json={"truth_key": key, "vote": "RATIFY", "confidence": 0.97})
    c.post("/v1/validate", headers=H("VAL"), json={"truth_key": key, "vote": human, "confidence": 0.9})
    return c.get("/v1/truth/" + key, headers=H(reports[0][0])).json()
print("round  E standing")
for i in range(1, 41):
    truth(i, [("E", "clear"), (f"h{i}a", "clear"), (f"h{i}b", "clear")])
    if i in (1, 5, 10, 20, 30, 40): print(f"{i:5}  {standing('E')}")
    if i in (10, 20, 40):
        n = 100 + i
        before = {w: standing(w) for w in ("E", f"n{n}a", f"n{n}b")}
        t = truth(n, [("E", "clear"), (f"n{n}a", "overcast"), (f"n{n}b", "overcast")])
        w = {a["agent_id"].split(':')[1]: round(a["effective_trust"], 1) for a in t.get("agents", []) if a["agent_id"].startswith("user:")}
        after = {k: standing(k) for k in before}
        print(f"   ↳ E at {before['E']} (weight {w.get('E')}) vs two newcomers (weight {w.get(f'n{n}a')} each): claim {t['claim']['cover']!r}; "
              + ", ".join(f"{k} {before[k]}→{after[k]}" for k in before))
