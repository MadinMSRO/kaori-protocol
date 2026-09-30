"""
Yield: sensors as agents (#1) and a value space with shape (#3), on top of the emergent-bond law (emerge.py).

Every witness, human or sensor, is the same kind of thing: an agent that is reliable with probability theta,
and noise otherwise. It contributes a likelihood over the candidate truths, divided by the bonded mass it
shares in the cell. Standing is learned from settled cells as soft counts. No agent type is trusted a priori.

#3 value space: values are points in a space, d = |band difference| + [rain differs].
   A human's report is drawn from a confusion with learned mass on exact / near (d=1) / far.
   A cell can form a coarser truth when the fine one is still open: band with rain unknown, or two adjacent bands.
#1 sensors as provenance: the phone's sensors (EXIF, attestation, in-app capture) witness that a photo is a
   real capture of this place and time. They say nothing about the value. What provenance changes is the bond:
   a photo with provenance is tied to the scene, so the AI's reading of it is a witness of its own. A photo
   without provenance is the observer's own product and fuses into the observer's knot. So a fake photo backing
   a fake claim adds nothing, and a real photo sent with a false claim testifies against its owner.
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import numpy as np
import coevo, topo
from emerge import NAMES

STATES = coevo.STATES
VALS = [(s, r) for s in STATES for r in (False, True)]
SI = {s: i for i, s in enumerate(STATES)}
def dist(u, v): return abs(SI[u[0]] - SI[v[0]]) + (u[1] != v[1])
D = {(u, v): dist(u, v) for u in VALS for v in VALS}
N1 = {u: sum(1 for v in VALS if D[(u, v)] == 1) for u in VALS}
NF = {u: sum(1 for v in VALS if D[(u, v)] >= 2) for u in VALS}

RANGES = {"a0": (0.5, 8.0), "an": (0.1, 4.0), "b0": (0.5, 8.0), "tau": (0.6, 0.995), "kappa": (0.0, 1.0), "lam": (0.0, 0.01)}
DEFAULT = {"a0": 4.0, "an": 1.0, "b0": 4.0, "tau": 0.94, "kappa": 0.26, "lam": 0.008}

# ------------------------------------------------------------------ photos, provenance and the AI's reading
# Provenance (EXIF plus device attestation, captured in the app) says whether the photo is a real capture of this
# place and time. A real sky photo passes 95% of the time (missing sensors, old phones). An AI-generated or
# gallery fake passes only when it is re-photographed off a screen (15%). A real photo of a non-sky passes, but the
# AI sees no sky, so it gives no reading. The AI (the generalist) reads a value from the photo's content,
# with its own error.
def add_sensors(events, seed, pass_real=0.95, pass_fake=0.15, ai_band=0.75, ai_rain=0.85):
    R = random.Random(seed ^ 0x5E75)
    out = []
    for t, p, truth, fake, reps, u in events:
        photos = []
        for aid, kind, said, shows, rel in reps:
            if shows == "junk":  # a real capture, but not of the sky: as a sky observation it fails
                photos.append((aid, False, None)); continue
            seen = truth if shows == "truth" else fake
            attested = R.random() < (pass_real if shows == "truth" else pass_fake)
            s = SI[seen[0]]
            if R.random() > ai_band: s = max(0, min(4, s + R.choice([-1, 1])))
            rain = seen[1] if R.random() < ai_rain else not seen[1]
            photos.append((aid, attested, (STATES[s], rain)))
        out.append((t, p, truth, fake, reps, u, photos))
    return out

# ------------------------------------------------------------------ the complex
class Complex:
    def __init__(self, P, ordinal, sensors):
        self.P, self.ordinal, self.sensors = P, ordinal, sensors
        self.E = defaultdict(float); self.Nr = defaultdict(float); self.F = defaultdict(float)  # human confusion counts
        self.St = defaultdict(float); self.Sn = defaultdict(float); self.S2 = defaultdict(float); self.Sw = defaultdict(float)
        self.n = defaultdict(float); self.nij = defaultdict(float); self.N = 0.0
        self.pv = defaultdict(lambda: [0.0, 0.0]); self.pr = [0.0, 0.0]; self.pf = [0.0, 0.0]; self._rho = None

    def fade(self):
        f = 1 - self.P["lam"]
        if f == 1: return
        for d in (self.E, self.Nr, self.F, self.St, self.Sn, self.S2, self.Sw, self.n, self.nij):
            for k in d: d[k] *= f
        self.N *= f

    def a(self, i, j):
        if i == j: return 1.0
        nij = self.nij.get((i, j) if i < j else (j, i), 0.0)
        if nij < 1: return 0.0
        pmi = math.log((nij + 0.5) * (self.N + 1) / ((self.n[i] + 1) * (self.n[j] + 1)))
        return (1 - math.exp(-max(0.0, pmi))) * nij / (nij + 3)

    # human reliability triple (exact, near, far)
    def own(self, i):
        e, nr, f = self.E[i] + self.P["a0"], self.Nr[i] + (self.P["an"] if self.ordinal else 0.0), self.F[i] + self.P["b0"]
        z = e + nr + f; return (e / z, nr / z, f / z)

    def conf(self, i, nbrs):
        pe = self.own(i)
        k = self.P["kappa"]
        ws = [(self.a(i, j), j) for j in nbrs if j != i and not j.startswith(("cam:", "sat"))]
        W = sum(w for w, _ in ws)
        if k == 0 or W < 1e-6: return pe
        m = [sum(w * self.own(j)[c] for w, j in ws) / W for c in range(3)]
        kk = k * W / (1 + W)
        return tuple((1 - kk) * pe[c] + kk * m[c] for c in range(3))

    def human_ll(self, said, c):
        e, nr, f = c
        out = {}
        for u in VALS:
            d = D[(u, said)]
            if not self.ordinal:
                out[u] = math.log(e) if d == 0 else math.log((nr + f) / (len(VALS) - 1))
            else:
                out[u] = math.log(e) if d == 0 else (math.log(nr / N1[u] + 1e-9) if d == 1 else math.log(f / NF[u]))
        return out

    def sensor(self, s):
        th = (self.St[s] + 3.0) / (self.St[s] + self.Sn[s] + 4.0)          # reliable share, prior 3:1
        var = (self.S2[s] + 1.0) / (self.Sw[s] + 2.0)                       # sigma^2, prior 0.5 band^2 ... 1
        return th, max(var, 0.05)

    def sensor_ll(self, s, x):
        th, var = self.sensor(s)
        out = {}
        for u in VALS:
            g = math.exp(-(x - SI[u[0]]) ** 2 / (2 * var)) / math.sqrt(2 * math.pi * var)
            out[u] = math.log(th * g + (1 - th) / 5.0)
        return out

    # provenance: the population of observers splits by pass rate. A two-component binomial mixture (EM) over
    # everyone's pass record gives P(pass | real capture) and P(pass | not), with no seeding and no settled outcomes.
    def rho(self):
        if self._rho is not None: return self._rho
        recs = [(p, n) for p, n in self.pv.values() if n >= 1]
        rr, rf, w = 0.9, 0.3, 0.5
        if len(recs) >= 4:
            for _ in range(30):
                resp = []
                for p, n in recs:
                    lr = w * rr ** p * (1 - rr) ** (n - p); lf = (1 - w) * rf ** p * (1 - rf) ** (n - p)
                    resp.append(lr / (lr + lf + 1e-300))
                sr = sum(resp); sf = len(resp) - sr
                rr = (sum(g * p for g, (p, n) in zip(resp, recs)) + 1) / (sum(g * n for g, (p, n) in zip(resp, recs)) + 2)
                rf = (sum((1 - g) * p for g, (p, n) in zip(resp, recs)) + 1) / (sum((1 - g) * n for g, (p, n) in zip(resp, recs)) + 2)
                w = (sr + 1) / (len(recs) + 2)
                if rr < rf: rr, rf = rf, rr; w = 1 - w
        self._rho = (rr, rf)
        return self._rho

    def realness(self, aid, passed):
        """Probability that this report is a real observation, from the provenance outcome and the observer's record."""
        rr, rf = self.rho()
        n_pass, n = self.pv[aid][0], self.pv[aid][1]
        pi = (n_pass + 1) / (n + 2)
        if sum(1 for v in self.pv.values() if v[1] >= 1) < 4: return 1.0  # nothing learned yet: take reports as they come
        q = 0.5 if rr - rf < 0.05 else min(0.98, max(0.02, (pi - rf) / (rr - rf)))  # observer's share of real captures
        lr, lf = (rr, rf) if passed else (1 - rr, 1 - rf)
        return q * lr / (q * lr + (1 - q) * lf)

    def section(self, reps, photos, nbrs_of):
        ids = [r[0] for r in reps]
        L = {u: 0.0 for u in VALS}
        ph = {o: (att, read) for o, att, read in photos} if self.sensors else {}
        ai = self.conf("ai", ())
        for aid, kind, said, *_ in reps:
            mass = sum(self.a(aid, j) for j in ids)
            r = self.realness(aid, ph[aid][0]) if aid in ph else 1.0
            for u, l in self.human_ll(said, self.conf(aid, nbrs_of(aid))).items():
                L[u] += math.log(r * math.exp(l) + (1 - r) / len(VALS)) / mass
            if aid in ph and ph[aid][1] is not None:  # the AI's reading of the photo, a witness of its own when real
                for u, l in self.human_ll(ph[aid][1], ai).items():
                    L[u] += math.log(r * math.exp(l) + (1 - r) / len(VALS)) / mass
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def observe(self, photos):
        for o, att, _ in photos:
            self.pv[o][0] += att; self.pv[o][1] += 1
        self._rho = None

    def witness(self, ids):
        self.N += 1
        for i in ids: self.n[i] += 1
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                i, j = ids[x], ids[y]
                self.nij[(i, j) if i < j else (j, i)] += 1

    def _learn(self, aid, said, post, w=1.0):
        e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
        if not self.ordinal: nr, f = 0.0, 1 - e
        else: f = 1 - e - nr
        self.E[aid] += w * e; self.Nr[aid] += w * nr; self.F[aid] += w * max(0.0, f)

    def settle(self, reps, photos, post):
        for aid, kind, said, *_ in reps: self._learn(aid, said, post)
        if self.sensors:
            for owner, att, read in photos:
                if read is None: continue
                real = sum(p for u, p in post.items() if abs(SI[u[0]] - SI[read[0]]) <= 1)  # photo shows the settled sky
                self._learn("ai", read, post, real)

def form(post, tau, ordinal):
    """The finest truth whose mass reaches tau: exact value, then band (rain open), then two adjacent bands."""
    u = max(post, key=post.get)
    if post[u] >= tau: return ("exact", {u})
    if not ordinal: return None
    band = Counter()
    for (s, r), p in post.items(): band[s] += p
    s, p = band.most_common(1)[0]
    if p >= tau: return ("band", {v for v in VALS if v[0] == s})
    best = max(range(4), key=lambda i: band[STATES[i]] + band[STATES[i + 1]])
    if band[STATES[best]] + band[STATES[best + 1]] >= tau:
        return ("pair", {v for v in VALS if v[0] in (STATES[best], STATES[best + 1])})
    return None

WORTH = {"exact": 1.0, "band": 0.75, "pair": 0.5}

def run(P, events, ordinal, sensors):
    C = Complex(P, ordinal, sensors)
    out = Counter(); last_t = -1; kinds = {}; nbr = defaultdict(set)
    for t, p, truth, fake, reps, u, sens in events:
        if t != last_t:
            for _ in range(max(0, t - last_t)): C.fade()
            last_t = t
        ids = [r[0] for r in reps]
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            post = C.section(reps, sens, lambda a: nbr[a])
            f = form(post, P["tau"], ordinal)
            if f:
                grain, S = f
                shown = Counter(truth if s == "truth" else fake for *_, s, _ in reps if s != "junk")
                human = (shown.most_common(1)[0][0] in S if shown else False) or u < 0.15
                if human:
                    if truth in S: out["right"] += WORTH[grain]; out["right_" + grain] += 1
                    else: out["wrong"] += 1
                    C.settle(reps, sens, post)
                else: out["stuck"] += 1
            else: out["stuck"] += 1
        C.witness(ids)
        if sensors: C.observe(sens)
        for i in ids: nbr[i].update(ids)
    E = max(1, out["eligible"])
    Sd = {i: math.log(C.conf(i, nbr[i])[0] / max(1e-9, C.conf(i, nbr[i])[2])) for i in kinds}
    hon = [Sd[a] for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [Sd[a] for a, k in kinds.items() if k in ("liar", "faker", "adv", "stolen")]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "right_exact", "right_band", "right_pair")}
    res["auc"] = auc
    if sensors: res["ai"] = [round(x, 2) for x in C.own("ai")]
    return res

# ------------------------------------------------------------------ evaluation
KEYS = ("right", "wrong", "stuck", "right_exact", "right_band", "right_pair", "auc")
def evaluate(args):
    P, seeds, lam_risk, ordinal, sensors = args
    rs = [run(P, add_sensors(coevo.make_world(s, a), s), ordinal, sensors) for a in topo.suite() for s in seeds]
    f = [r["right"] - lam_risk * r["wrong"] + 0.3 * r["auc"] for r in rs]
    agg = {k: sum(r[k] for r in rs) / len(rs) for k in KEYS}
    agg["worst_wrong"] = max(r["wrong"] for r in rs)
    agg["per"] = [(round(r["right"], 2), round(r["wrong"], 3)) for r in rs]
    agg["fit"] = 0.5 * sum(f) / len(f) + 0.5 * min(f)
    return agg

def evolve(R, ordinal, sensors, lam_risk=10, pop_n=16, gens=12):
    pop = [dict(DEFAULT)] + [{k: R.uniform(*r) for k, r in RANGES.items()} for _ in range(pop_n - 1)]
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48)]
            fs = pool.map(evaluate, [(P, seeds, lam_risk, ordinal, sensors) for P in pop])
            ranked = [P for _, P in sorted(zip([f["fit"] for f in fs], pop), key=lambda x: -x[0])]
            nxt = [dict(P) for P in ranked[:4]]
            while len(nxt) < pop_n:
                a, b = R.sample(ranked[:8], 2)
                c = {k: (a[k] if R.random() < 0.5 else b[k]) for k in a}
                for k, (lo, hi) in RANGES.items():
                    if R.random() < 0.3: c[k] = min(hi, max(lo, c[k] + R.gauss(0, (hi - lo) * 0.15)))
                nxt.append(c)
            pop = nxt
    return ranked[0]

ARMS = {"emergent bonds (before)": (False, False), "+ value space (#3)": (True, False),
        "+ provenance (#1)": (False, True), "+ both": (True, True)}

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    best = {}
    for name, (o, s) in ARMS.items():
        best[name] = evolve(R, o, s)
        print(f"evolved {name:26}: " + ", ".join(f"{k}={v:.3f}" for k, v in best[name].items()), flush=True)
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    with Pool(4) as pool:
        res = pool.map(evaluate, [(best[n], test, 10, o, s) for n, (o, s) in ARMS.items()])
    print("\n### fresh worlds, full attack suite (right counts exact 1, band 0.75, two bands 0.5)")
    print(f"{'':27} {'right':>6} {'exact':>6} {'band':>5} {'pair':>5} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}")
    for n, r in zip(ARMS, res):
        print(f"{n:27} {r['right']:6.2f} {r['right_exact']:6.2f} {r['right_band']:5.2f} {r['right_pair']:5.2f} "
              f"{r['wrong']:6.3f} {r['worst_wrong']:6.3f} {r['stuck']:6.2f} {r['auc']:5.2f}")
    print("\n### right / wrong per scenario (mean over test worlds)")
    for n, r in zip(ARMS, res):
        per = r["per"]; k = len(test)
        cells = [(sum(x[0] for x in per[i * k:(i + 1) * k]) / k, sum(x[1] for x in per[i * k:(i + 1) * k]) / k) for i in range(len(NAMES))]
        print(f"{n:27} " + "  ".join(f"{nm.split()[0][:8]} {a:.2f}/{b:.3f}" for nm, (a, b) in zip(NAMES, cells)))
    json.dump({"best": best, "res": dict(zip(ARMS, res))}, open("sense-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
