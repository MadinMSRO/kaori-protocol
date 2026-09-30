"""
Kaori Flow where everything is an agent and every action is a signal.

Agents (none trusted a priori, all learn standing the same way):
  observers   report a value and submit a photo              -> the report is a witness; presence feeds bonds
  provenance  the phone's sensors (EXIF, attestation) report  -> pass/fail on every photo; its own standing is
              whether a photo is a real capture                  P(pass | real) and P(pass | fake), learned from the
                                                                  population's pass records (EM), not from outcomes
  AI          the generalist reads each photo: a value, or      -> a witness per photo; "no sky" is a signal too
              "no sky"
  validators  humans who look at the photos and read a value    -> a witness per photo, with standing like anyone's
              (two diligent, one hasty, one bribed)

One law acts on each observation cell. A witness's likelihood is a mixture: with the probability that its
evidence is a real observation of this sky, it speaks through its learned confusion; otherwise it says nothing.
It is divided by the bonded mass it shares in the cell: its bonds to others (co-presence beyond chance, which
emerges) plus itself. So several readings by one agent count as one witness. The cell forms when the section
reaches tau. No gates.

Every action leaves a signal:
  presence -> bonds; provenance -> the observer's realness record and the provenance agent's standing;
  readings and reports -> confusion counts when the cell settles. A cell that does not form stays open for a
  day and is re-read as standing evolves, so no report is thrown away.

Value space (#3): values are points, d = |band difference| + [rain differs]. Confusion has exact, near and
far mass, and a coarser truth can form (band with rain open, or two adjacent bands).
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo
from emerge import NAMES

STATES = coevo.STATES
VALS = [(s, r) for s in STATES for r in (False, True)]
SI = {s: i for i, s in enumerate(STATES)}
D = {(u, v): abs(SI[u[0]] - SI[v[0]]) + (u[1] != v[1]) for u in VALS for v in VALS}
N1 = {u: sum(1 for v in VALS if D[(u, v)] == 1) for u in VALS}
NF = {u: sum(1 for v in VALS if D[(u, v)] >= 2) for u in VALS}
VALIDATORS = ["v:diligent0", "v:diligent1", "v:hasty", "v:bribed"]
OPEN_H = 24

RANGES = {"a0": (0.5, 8.0), "an": (0.1, 4.0), "b0": (0.5, 8.0), "tau": (0.6, 0.995), "kappa": (0.0, 1.0), "lam": (0.0, 0.01)}
DEFAULT = {"a0": 4.0, "an": 1.0, "b0": 4.0, "tau": 0.94, "kappa": 0.26, "lam": 0.008}

# ------------------------------------------------------------------ what the agents do in the world
def read(R, v, band_acc, rain_acc):
    s = SI[v[0]]
    if R.random() > band_acc: s = max(0, min(4, s + R.choice([-1, 1])))
    return (STATES[s], v[1] if R.random() < rain_acc else not v[1])

def add_agents(events, seed, pass_real=0.95, pass_fake=0.15, pass_junk=0.9):
    """Photos: (owner, provenance passed, AI reading or None). Validator: (id, readings aligned with photos)."""
    R = random.Random(seed ^ 0x5E75)
    out = []
    for t, p, truth, fake, reps, u in events:
        photos, vreads = [], []
        vid = R.choice(VALIDATORS)
        attack = any(k in ("adv", "stolen") and said == fake for _, k, said, _, _ in reps)
        majority = Counter(said for _, _, said, _, _ in reps).most_common(1)[0][0] if reps else None
        hasty_skips = R.random() < 0.6
        for aid, kind, said, shows, rel in reps:
            content = None if shows == "junk" else (truth if shows == "truth" else fake)
            passed = R.random() < (pass_junk if content is None else pass_real if shows == "truth" else pass_fake)
            photos.append((aid, passed, None if content is None else read(R, content, 0.75, 0.85)))
            if vid == "v:bribed" and attack: vr = fake
            elif vid == "v:hasty" and hasty_skips: vr = majority          # does not look; echoes the claims
            else: vr = None if content is None else read(R, content, 0.9, 0.9)
            vreads.append(vr)
        out.append((t, p, truth, fake, reps, u, photos, (vid, vreads)))
    return out

# ------------------------------------------------------------------ the complex
class Complex:
    def __init__(self, P, ordinal, provenance):
        self.P, self.ordinal, self.prov = P, ordinal, provenance
        self.E = defaultdict(float); self.Nr = defaultdict(float); self.F = defaultdict(float)
        self.n = defaultdict(float); self.nij = defaultdict(float); self.N = 0.0
        self.pv = defaultdict(lambda: [0.0, 0.0]); self._rho = None; self._cc = {}

    def fade(self):
        f = 1 - self.P["lam"]; self._cc = {}
        for d in (self.E, self.Nr, self.F, self.n, self.nij):
            for k in d: d[k] *= f
        self.N *= f

    # bonds: co-presence beyond chance
    def a(self, i, j):
        if i == j: return 1.0
        nij = self.nij.get((i, j) if i < j else (j, i), 0.0)
        if nij < 1: return 0.0
        pmi = math.log((nij + 0.5) * (self.N + 1) / ((self.n[i] + 1) * (self.n[j] + 1)))
        return (1 - math.exp(-max(0.0, pmi))) * nij / (nij + 3)

    # standing: learned confusion (exact, near, far), relaxed along bonds
    def own(self, i):
        e = self.E[i] + self.P["a0"]; nr = self.Nr[i] + (self.P["an"] if self.ordinal else 0.0); f = self.F[i] + self.P["b0"]
        z = e + nr + f; return (e / z, nr / z, f / z)

    def conf(self, i, nbrs=()):
        key = (i, len(nbrs))
        if key in self._cc: return self._cc[key]
        self._cc[key] = c = self._conf(i, nbrs)
        return c

    def _conf(self, i, nbrs):
        pe = self.own(i)
        ws = [(self.a(i, j), j) for j in nbrs if j != i]
        W = sum(w for w, _ in ws)
        if self.P["kappa"] == 0 or W < 1e-6: return pe
        m = [sum(w * self.own(j)[c] for w, j in ws) / W for c in range(3)]
        k = self.P["kappa"] * W / (1 + W)
        return tuple((1 - k) * pe[c] + k * m[c] for c in range(3))

    def lik(self, said, c):
        e, nr, f = c
        if not self.ordinal:
            return {u: e if D[(u, said)] == 0 else (nr + f) / (len(VALS) - 1) for u in VALS}
        return {u: e if D[(u, said)] == 0 else (nr / N1[u] if D[(u, said)] == 1 else f / NF[u]) for u in VALS}

    # the provenance agent's standing: P(pass | real capture), P(pass | not), by EM over everyone's pass record
    def rho(self):
        if self._rho is not None: return self._rho
        recs = [(p, n) for p, n in self.pv.values() if n >= 1]
        rr, rf, w = 0.9, 0.3, 0.5
        for _ in range(30 if len(recs) >= 4 else 0):
            resp = []
            for p, n in recs:
                lr = w * rr ** p * (1 - rr) ** (n - p); lf = (1 - w) * rf ** p * (1 - rf) ** (n - p)
                resp.append(lr / (lr + lf + 1e-300))
            rr = (sum(g * p for g, (p, n) in zip(resp, recs)) + 1) / (sum(g * n for g, (p, n) in zip(resp, recs)) + 2)
            rf = (sum((1 - g) * p for g, (p, n) in zip(resp, recs)) + 1) / (sum((1 - g) * n for g, (p, n) in zip(resp, recs)) + 2)
            w = (sum(resp) + 1) / (len(recs) + 2)
            if rr < rf: rr, rf, w = rf, rr, 1 - w
        self._rho = (rr, rf, len(recs))
        return self._rho

    def realness(self, aid, passed):
        if not self.prov: return 1.0
        rr, rf, n_obs = self.rho()
        if n_obs < 4 or rr - rf < 0.05: return 1.0      # the provenance agent has not learned anything yet
        pi = (self.pv[aid][0] + 1) / (self.pv[aid][1] + 2)
        q = min(0.98, max(0.02, (pi - rf) / (rr - rf)))
        lr, lf = (rr, rf) if passed else (1 - rr, 1 - rf)
        return q * lr / (q * lr + (1 - q) * lf)

    def section(self, cell, nbrs_of):
        reps, photos, (vid, vreads) = cell
        ids = [r[0] for r in reps] + [vid]
        L = {u: 0.0 for u in VALS}
        def add(lk, r, mass):
            for u in VALS: L[u] += math.log(r * lk[u] + (1 - r) / len(VALS)) / mass
        n_ai = sum(1 for _, _, x in photos if x is not None) or 1
        n_v = sum(1 for x in vreads if x is not None) or 1
        ai, vc = self.conf("ai"), self.conf(vid, nbrs_of(vid))
        for (aid, kind, said, *_), (_, passed, ai_read), vr in zip(reps, photos, vreads):
            real = self.realness(aid, passed)
            sky = 1.0 if ai_read is not None else 0.05     # the AI says whether the photo shows a sky at all
            add(self.lik(said, self.conf(aid, nbrs_of(aid))), real * sky, sum(self.a(aid, j) for j in ids))
            if ai_read is not None: add(self.lik(ai_read, ai), real, n_ai)
            if vr is not None: add(self.lik(vr, vc), real * sky, n_v)
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def observe(self, cell):
        reps, photos, (vid, _) = cell
        ids = [r[0] for r in reps] + [vid]
        self.N += 1
        for i in ids: self.n[i] += 1
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                i, j = sorted((ids[x], ids[y])); self.nij[(i, j)] += 1
        for o, passed, _ in photos: self.pv[o][0] += passed; self.pv[o][1] += 1
        self._rho = None

    def _learn(self, aid, said, post, w=1.0):
        e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1) if self.ordinal else 0.0
        self.E[aid] += w * e; self.Nr[aid] += w * nr; self.F[aid] += w * max(0.0, 1 - e - nr)

    def settle(self, cell, post):
        self._cc = {}
        reps, photos, (vid, vreads) = cell
        n_ai = sum(1 for _, _, x in photos if x is not None) or 1
        n_v = sum(1 for x in vreads if x is not None) or 1
        for (aid, kind, said, *_), (_, passed, ai_read), vr in zip(reps, photos, vreads):
            real = self.realness(aid, passed)
            self._learn(aid, said, post)
            if ai_read is not None: self._learn("ai", ai_read, post, real / n_ai)
            if vr is not None: self._learn(vid, vr, post, real / n_v)

def form(post, tau, ordinal):
    u = max(post, key=post.get)
    if post[u] >= tau: return ("exact", {u})
    if not ordinal: return None
    band = Counter()
    for (s, r), p in post.items(): band[s] += p
    s, p = band.most_common(1)[0]
    if p >= tau: return ("band", {v for v in VALS if v[0] == s})
    i = max(range(4), key=lambda i: band[STATES[i]] + band[STATES[i + 1]])
    if band[STATES[i]] + band[STATES[i + 1]] >= tau:
        return ("pair", {v for v in VALS if v[0] in (STATES[i], STATES[i + 1])})
    return None

WORTH = {"exact": 1.0, "band": 0.75, "pair": 0.5}
HOSTILE = ("liar", "faker", "adv", "stolen")

def run(P, events, ordinal, provenance, detail=False):
    C = Complex(P, ordinal, provenance)
    out = Counter(); last_t = -1; kinds = {}; nbr = defaultdict(set); opened = []
    def resolve(cell, truth, post):
        f = form(post, P["tau"], ordinal)
        if not f: return False
        grain, S = f
        if truth in S: out["right"] += WORTH[grain]; out["right_" + grain] += 1
        else: out["wrong"] += 1
        C.settle(cell, post)
        return True
    for t, p, truth, fake, reps, u, photos, val in events:
        if t != last_t:
            for _ in range(max(0, t - last_t)): C.fade()
            last_t = t
            still = []                                     # open cells are re-read as standing evolves
            for t0, cell, tr in opened:
                if resolve(cell, tr, C.section(cell, lambda a: nbr[a])): out["late"] += 1
                elif t - t0 < OPEN_H: still.append((t0, cell, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, photos, val)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, truth, C.section(cell, lambda a: nbr[a])): opened.append((t, cell, truth))
        C.observe(cell)
        ids = [r[0] for r in reps] + [val[0]]
        for i in ids: nbr[i].update(ids)
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    def S(i): c = C.conf(i, nbr[i]); return math.log(c[0] / c[2])
    hon = [S(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [S(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "late", "right_exact", "right_band", "right_pair")}
    res["auc"] = auc
    if detail:
        res["validators"] = {v[2:]: round(S(v), 2) for v in VALIDATORS}
        res["ai"] = round(math.log(C.own("ai")[0] / C.own("ai")[2]), 2)
        rr, rf, _ = C.rho(); res["provenance"] = (round(rr, 2), round(rf, 2))
        tiers = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(S(a))
        res["observers"] = {k: round(sum(v) / len(v), 2) for k, v in tiers.items()}
    return res

# ------------------------------------------------------------------ evaluation
KEYS = ("right", "wrong", "stuck", "late", "right_exact", "right_band", "right_pair", "auc")
def evaluate(args):
    P, seeds, lam_risk, ordinal, prov = args
    rs = [run(P, add_agents(coevo.make_world(s, a), s), ordinal, prov) for a in topo.suite() for s in seeds]
    f = [r["right"] - lam_risk * r["wrong"] + 0.3 * r["auc"] for r in rs]
    agg = {k: sum(r[k] for r in rs) / len(rs) for k in KEYS}
    agg["worst_wrong"] = max(r["wrong"] for r in rs)
    agg["per"] = [(r["right"], r["wrong"]) for r in rs]
    agg["fit"] = 0.5 * sum(f) / len(f) + 0.5 * min(f)
    return agg

def evolve(R, ordinal, prov, lam_risk=10, pop_n=16, gens=12):
    pop = [dict(DEFAULT)] + [{k: R.uniform(*r) for k, r in RANGES.items()} for _ in range(pop_n - 1)]
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48)]
            fs = pool.map(evaluate, [(P, seeds, lam_risk, ordinal, prov) for P in pop])
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

ARMS = {"agents, flat values": (False, False), "+ value space (#3)": (True, False),
        "+ provenance agent (#1)": (False, True), "+ both": (True, True)}

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    best = {}
    for name, (o, s) in ARMS.items():
        best[name] = evolve(R, o, s)
        print(f"evolved {name:25}: " + ", ".join(f"{k}={v:.3f}" for k, v in best[name].items()), flush=True)
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    with Pool(4) as pool:
        res = pool.map(evaluate, [(best[n], test, 10, o, s) for n, (o, s) in ARMS.items()])
    print("\n### fresh worlds, full attack suite (right counts exact 1, band 0.75, two bands 0.5)")
    print(f"{'':26} {'right':>6} {'exact':>6} {'band':>5} {'pair':>5} {'late':>5} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}")
    for n, r in zip(ARMS, res):
        print(f"{n:26} {r['right']:6.2f} {r['right_exact']:6.2f} {r['right_band']:5.2f} {r['right_pair']:5.2f} {r['late']:5.2f} "
              f"{r['wrong']:6.3f} {r['worst_wrong']:6.3f} {r['stuck']:6.2f} {r['auc']:5.2f}")
    print("\n### right / wrong per scenario (mean over test worlds)")
    k = len(test)
    for n, r in zip(ARMS, res):
        per = r["per"]
        cells = [(sum(x[0] for x in per[i * k:(i + 1) * k]) / k, sum(x[1] for x in per[i * k:(i + 1) * k]) / k) for i in range(len(NAMES))]
        print(f"{n:26} " + "  ".join(f"{nm.split()[0][:8]} {a:.2f}/{b:.3f}" for nm, (a, b) in zip(NAMES, cells) if nm not in ("cabal 2", "cabal 3")))
    print("\n### standing every agent earned (+ both, one fresh world per scenario; log-odds exact vs far)")
    for nm, a in zip(NAMES, topo.suite()):
        if nm in ("cabal 2", "cabal 3"): continue
        r = run(best["+ both"], add_agents(coevo.make_world(test[0], a), test[0]), True, True, detail=True)
        print(f"[{nm}] observers {r['observers']}  validators {r['validators']}  AI {r['ai']}  provenance P(pass|real,fake) {r['provenance']}")
    json.dump({"best": best, "res": dict(zip(ARMS, res))}, open("agents-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
