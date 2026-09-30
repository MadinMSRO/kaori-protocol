# Plays the phone's flood flow against a Kaori sidecar: evidence, compile x3, validate, truth.
import hashlib, io, json, sys, httpx
from datetime import datetime, timezone
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"
KEY = "earth:flood:h3:886142a8e7fffff:surface:" + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00Z")
c = httpx.Client(base_url=BASE, timeout=60)
H = lambda who: {"Authorization": "Bearer tok-" + who}

def report(who, level):
    photo = ("flood photo from " + who).encode() + bytes(range(256)) * 40
    sha = hashlib.sha256(photo).hexdigest()
    r = c.post("/v1/evidence", headers=H(who), files={"file": (who + ".jpg", io.BytesIO(photo), "image/jpeg")}, data={"expected_sha256": sha})
    print("evidence", who, r.status_code, r.text[:160]); r.raise_for_status()
    body = {"truth_key": KEY, "claim_type_id": "earth.flood.v1", "observations": [{
        "claim_type": "earth.flood.v1",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "geo": {"lat": 4.1755, "lon": 73.5093},
        "payload": {"water_level_cm": level, "flow_velocity": "slow", "affected_structures": True},
        "evidence_refs": [r.json()],
    }]}
    r = c.post("/v1/compile", headers=H(who), json=body)
    print("compile ", who, r.status_code, r.text[:300])
    return r

print("key", KEY)
report("A", 30); report("B", 35); report("C", 28)
r = c.post("/v1/validate", headers={"Authorization": "Bearer ai-generalist"}, json={"truth_key": KEY, "vote": "RATIFY", "confidence": 0.9})
print("ai vote ", r.status_code, r.json().get("status"), r.json().get("transparency_flags"))
r = c.post("/v1/validate", headers=H("V"), json={"truth_key": KEY, "vote": "RATIFY", "confidence": 0.9})
print("validate", r.status_code, r.text[:400])
r = c.get("/v1/truth/" + KEY, headers=H("A"))
t = r.json() if r.status_code == 200 else {}
print("truth   ", r.status_code, json.dumps({k: t.get(k) for k in ("status", "confidence_score", "truthkey")})[:300])
print("keys    ", sorted(t.keys())[:40])
print("votes   ", json.dumps((t.get("consensus") or {}).get("votes"))[:300])
