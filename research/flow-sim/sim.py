# Agent simulation of earth.sky_cover.v1 on a fresh local Kaori (kaori-api, in-memory), with the
# real CLIP generalist judging the real photos. Every actor is an agent: 10 observers, the AI
# generalist and one human validator. Randomness comes from the OS entropy pool (SystemRandom);
# every event is logged so a run can be audited afterwards.
#
#   python sim.py ROUNDS
import hashlib, io, json, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import SystemRandom
from uuid import UUID

import h3, httpx
from PIL import Image, ImageEnhance

R = SystemRandom()
HERE = Path(__file__).resolve().parent
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
c = httpx.Client(base_url="http://127.0.0.1:8787", timeout=120)
H = lambda who: {"Authorization": "Bearer tok-" + who}
LOG = open(HERE / "sim-log.jsonl", "w")
def log(**e): LOG.write(json.dumps(e) + "\n"); LOG.flush()

# ---------- the world: places, and a true sky per place per hour ----------
PLACES = {  # name: (lat, lon)
    "Antalya expo": (36.8969, 30.7133), "Antalya old town": (36.8841, 30.7056), "Antalya beach": (36.8580, 30.7560),
    "Malé north": (4.1780, 73.5090), "Hulhumalé": (4.2190, 73.5400),
}
STATES = {  # true state -> (cover, raining, photos that show it)
    "clear": ("clear", False, ["skyar-sunny.jpg", "horizon-clear-treeline.jpg"]),
    "overcast": ("overcast", False, ["skyar-cloudy.jpg", "horizon-overcast-roofline.jpg"]),
    "storm": ("overcast", True, ["skyar-rainy.jpg", "horizon-storm-treeline.jpg"]),
    "scattered": ("scattered", False, ["skyar-sunset.jpg", "horizon-sunset-roofline.jpg"]),
}
BANDS = ["clear", "few", "scattered", "broken", "overcast"]
JUNK = ["dog.jpg", "fruits.jpg", "black-frame.jpg", "building.jpg"]

def photo_bytes(name, sub="sky"):
    """A fresh 'phone photo': random crop, brightness and quality, so no two uploads are identical."""
    im = Image.open(HERE / "photos" / sub / name).convert("RGB")
    w, h = im.size; f = R.uniform(0.8, 1.0); cw, ch = int(w * f), int(h * f)
    x, y = R.randint(0, w - cw), R.randint(0, h - ch)
    im = ImageEnhance.Brightness(im.crop((x, y, x + cw, y + ch))).enhance(R.uniform(0.85, 1.15))
    out = io.BytesIO(); im.save(out, "JPEG", quality=R.randint(80, 95)); return out.getvalue()

# ---------- the agents ----------
# kind: careful (always right) · sloppy (30% one band off) · liar (right photo, random wrong value)
#       faker (junk photo, or a stock photo of another sky with the matching false value)
#       colluder (a pair: same place, same stock photo of the same false sky)
AGENTS = {"care1": "careful", "care2": "careful", "care3": "careful", "slop1": "sloppy", "slop2": "sloppy",
          "liar1": "liar", "liar2": "liar", "fake1": "faker", "coll1": "colluder", "coll2": "colluder"}

def report(agent, truth):
    kind = AGENTS[agent]; cover, rain, photos = STATES[truth]
    if kind == "careful":
        return cover, rain, ("sky", R.choice(photos)), truth
    if kind == "sloppy":
        i = BANDS.index(cover)
        if R.random() < 0.3: i = min(4, max(0, i + R.choice([-1, 1])))
        return BANDS[i], rain, ("sky", R.choice(photos)), truth
    if kind == "liar":
        return R.choice([b for b in BANDS if b != cover]), R.random() < 0.5, ("sky", R.choice(photos)), truth
    fake = R.choice([s for s in STATES if s != truth])
    fcover, frain, fphotos = STATES[fake]
    if kind == "faker" and R.random() < 0.5:
        return R.choice(BANDS), R.random() < 0.5, ("other", R.choice(JUNK)), "junk"
    return fcover, frain, ("sky", fphotos[0]), fake  # a consistent fake: photo and value agree, but not with the sky

# ---------- the AI generalist: Kaori's own validator code on the real CLIP model ----------
sys.argv = [sys.argv[0]]
exec((HERE / "ai_check.py").read_text().split("print(f\"{'photo'")[0])  # defines v (ClipGeneralistValidator), files, obs loader
from kaori_api.generalist import ValidatorRequest
from kaori_truth.primitives.evidence import EvidenceRef
from kaori_truth.primitives.observation import Observation, ReporterContext, Standing

def standing(a):
    r = c.get("/v1/standing/" + a, headers=H("x"))
    return round(r.json()["standing"], 1) if r.status_code == 200 else 200.0

# ---------- run ----------
t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=ROUNDS + 2)
stats = Counter(); per_round = []
traj = defaultdict(list)
started = time.time()
for rnd in range(ROUNDS):
    t = t0 + timedelta(hours=rnd)
    live = R.sample(list(PLACES), 3)                      # three places are being observed this hour
    truth_at = {p: R.choices(list(STATES), weights=[35, 30, 15, 20])[0] for p in live}
    where = {}
    group = R.choice(live)
    for a in AGENTS:
        where[a] = group if AGENTS[a] == "colluder" else R.choice(live)
    coll_fake = R.choice([s for s in STATES if s != truth_at[group]])
    for place in live:
        people = [a for a in AGENTS if where[a] == place]
        truth = truth_at[place]
        lat, lon = PLACES[place]
        key = f"earth:sky_cover:h3:{h3.latlng_to_cell(lat, lon, 8)}:surface:{t.strftime('%Y-%m-%dT%H:00Z')}"
        package = []
        for a in people:
            cover, rain, (sub, name), shown = report(a, truth)
            if AGENTS[a] == "colluder":
                cover, rain, _ = STATES[coll_fake]; name, sub, shown = STATES[coll_fake][2][0], "sky", coll_fake
            data = photo_bytes(name, sub)
            jlat, jlon = lat + R.uniform(-0.0015, 0.0015), lon + R.uniform(-0.0015, 0.0015)
            if h3.latlng_to_cell(jlat, jlon, 8) != key.split(":")[3]: jlat, jlon = lat, lon
            ev = c.post("/v1/evidence", headers=H(a), files={"file": (f"{a}.jpg", io.BytesIO(data), "image/jpeg")}, data={"expected_sha256": hashlib.sha256(data).hexdigest()}).json()
            files[ev["uri"]] = data
            obs_body = {"claim_type": "earth.sky_cover.v1", "reported_at": (t + timedelta(minutes=R.randint(1, 55))).isoformat(), "geo": {"lat": jlat, "lon": jlon}, "payload": {"cover": cover, "raining": rain}, "evidence_refs": [ev]}
            res = c.post("/v1/compile", headers=H(a), json={"truth_key": key, "claim_type_id": "earth.sky_cover.v1", "observations": [obs_body]})
            package.append((a, obs_body, shown))
            log(round=rnd, place=place, truth=truth, agent=a, kind=AGENTS[a], said=[cover, rain], photo=f"{sub}/{name}", photo_shows=shown, status=res.status_code)
        if len(people) < 3:
            stats["too few reporters"] += 1; continue
        # the AI generalist judges the whole package (real CLIP on the real photos)
        req = ValidatorRequest(truthkey_id=key, claim_type_id="earth.sky_cover.v1", observations=[
            Observation(observation_id=UUID(int=R.getrandbits(128)), claim_type="earth.sky_cover.v1", reported_at=datetime.fromisoformat(o["reported_at"]),
                        reporter_id="user:" + a, reporter_context=ReporterContext(standing=Standing.BRONZE, trust_score=0.2, source_type="human"),
                        geo=o["geo"], payload=o["payload"], evidence_refs=[EvidenceRef(uri=o["evidence_refs"][0]["uri"], sha256=o["evidence_refs"][0]["sha256"])]) for a, o, _ in package])
        vote = v.validate(req)
        c.post("/v1/validate", headers={"Authorization": "Bearer ai-generalist"}, json={"truth_key": key, "vote": vote.vote, "confidence": vote.confidence})
        # the human validator looks at the photos: ratifies when the compiled claim matches what most
        # of the sky photos show; 15% of the time rubber-stamps
        mid = c.get("/v1/truth/" + key, headers=H("x")).json()
        shows = Counter(s for _, _, s in package if s != "junk")
        seen = shows.most_common(1)[0][0] if shows else None
        claim = mid.get("claim") or {}
        looks_right = seen is not None and (claim.get("cover"), claim.get("raining")) == STATES[seen][:2]
        hv = "RATIFY" if (looks_right or R.random() < 0.15) else "REJECT"
        c.post("/v1/validate", headers=H("VAL"), json={"truth_key": key, "vote": hv, "confidence": 0.9})
        final = c.get("/v1/truth/" + key, headers=H("x")).json()
        fc = final.get("claim") or {}
        right = (fc.get("cover"), fc.get("raining")) == STATES[truth][:2]
        st = final.get("status")
        stats[st] += 1
        if st == "VERIFIED_TRUE": stats["verified & right" if right else "verified & WRONG"] += 1
        log(round=rnd, place=place, truth=truth, key=key, ai=[vote.vote, round(vote.confidence, 3)], validator=hv, status=st, claim=fc, right=right)
        per_round.append((rnd, place, truth, len(people), vote.vote, round(vote.confidence, 2), hv, st, f"{fc.get('cover')}/{'rain' if fc.get('raining') else 'dry'}", right))
    if rnd % 5 == 4 or rnd == ROUNDS - 1:
        for a in AGENTS: traj[a].append(standing("user:" + a))
        traj["AI"].append(standing("ai:generalist_v1")); traj["VAL"].append(standing("user:VAL"))

print(f"{ROUNDS} hours simulated in {time.time() - started:.0f}s\n")
print(f"{'rd':>3} {'place':17} {'true sky':9} {'n':>2} {'AI':12} {'human':7} {'status':15} claim")
for r in per_round:
    print(f"{r[0]:>3} {r[1]:17} {r[2]:9} {r[3]:>2} {r[4]+' '+str(r[5]):12} {r[6]:7} {r[7]:15} {r[8]:15} {'✓' if r[9] else ('✗' if r[7] == 'VERIFIED_TRUE' else '')}")
print("\noutcomes:", dict(stats))
print("\nstanding every 5 hours (start 200; AI and validator start 250):")
for a, kind in list(AGENTS.items()) + [("AI", "ai generalist"), ("VAL", "human validator")]:
    print(f"  {a:6} {kind:16} " + " → ".join(f"{x:.0f}" for x in traj[a]))
