"""
Emergent topology for Kaori Flow. Nothing about the network's shape is chosen.

Start: every observer is an isolated point with the same standing. No edges, no groups, no seeding.
One local law acts on each observation cell (a place and hour, with the witnesses there):

  1. Bonds.  A bond between two observers is the information their co-presence carries beyond chance
     (pointwise mutual information of turning up together). Independent people keep a bond near zero.
     Anyone whose presence is tied to someone else's grows a bond. a_ij = 1 - exp(-PMI+).
  2. Section.  The cell's value is the free-energy minimum over the witnesses. Each witness contributes
     log-odds precision divided by the bonded mass it shares in the cell, sum_j a_ij, so a fused clique
     counts as about one witness, continuously and without a threshold.
  3. Standing.  Precision is learned as Beta counts from settled cells. Standing then relaxes along bonds
     (whitepaper §17.6, L = sum w_ij (S_i - S_j)^2): bonded observers come to share their fate.

After the run, the shape that formed is read out: which observers fused, how tightly, where standing sits.
"""
import math, random, sys, json, time
from collections import Counter, defaultdict
from multiprocessing import Pool
import numpy as np
import coevo, topo

K = 10
def logodds(p): p = min(max(p, 1e-4), 1 - 1e-4); return math.log(p * (K - 1) / (1 - p))

RANGES = {"a0": (0.5, 8.0), "b0": (0.5, 8.0), "tau": (0.6, 0.995), "kappa": (0.0, 1.0), "lam": (0.0, 0.01)}
DEFAULT = {"a0": 2.0, "b0": 2.0, "tau": 0.85, "kappa": 0.5, "lam": 0.002}

class Complex:
    def __init__(self, P, bonds=True):
        self.P, self.bonds = P, bonds
        self.A = defaultdict(float); self.B = defaultdict(float)
        self.n = defaultdict(float); self.nij = defaultdict(float); self.N = 0.0

    def fade(self):
        f = 1 - self.P["lam"]
        if f == 1: return
        for d in (self.A, self.B, self.n, self.nij):
            for k in d: d[k] *= f
        self.N *= f

    def a(self, i, j):
        if not self.bonds or i == j: return 1.0 if i == j else 0.0
        nij = self.nij.get((i, j) if i < j else (j, i), 0.0)
        if nij < 1: return 0.0
        pmi = math.log((nij + 0.5) * (self.N + 1) / ((self.n[i] + 1) * (self.n[j] + 1)))
        conf = nij / (nij + 3)
        return (1 - math.exp(-max(0.0, pmi))) * conf

    def theta0(self, i): return (self.A[i] + self.P["a0"]) / (self.A[i] + self.B[i] + self.P["a0"] + self.P["b0"])

    def standing(self, i, nbrs):
        s = logodds(self.theta0(i))
        if self.P["kappa"] == 0 or not nbrs: return s
        ws = [(self.a(i, j), j) for j in nbrs if j != i]
        W = sum(w for w, _ in ws)
        if W < 1e-6: return s
        mean = sum(w * logodds(self.theta0(j)) for w, j in ws) / W
        k = self.P["kappa"] * W / (1 + W)
        return (1 - k) * s + k * mean

    def section(self, reps, nbrs_of):
        ids = [r[0] for r in reps]
        L = defaultdict(float)
        for aid, kind, said, shows, rel in reps:
            mass = sum(self.a(aid, j) for j in ids)
            L[said] += self.standing(aid, nbrs_of(aid)) / mass
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values()) + (K - len(L)) * math.exp(-m)
        post = {v: math.exp(x - m) / Z for v, x in L.items()}
        claim = max(post, key=post.get)
        return claim, post

    def witness(self, ids):
        self.N += 1
        for i in ids: self.n[i] += 1
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                i, j = ids[x], ids[y]
                self.nij[(i, j) if i < j else (j, i)] += 1

    def settle(self, reps, post):
        for aid, kind, said, *_ in reps:
            p = post.get(said, 0.0)
            self.A[aid] += p; self.B[aid] += 1 - p

def run(P, events, bonds=True, readout=False):
    C = Complex(P, bonds)
    out = Counter(); last_t = -1; kinds = {}
    nbr = defaultdict(set)
    for t, p, truth, fake, reps, u in events:
        if t != last_t:
            for _ in range(max(0, t - last_t)): C.fade()
            last_t = t
        ids = [r[0] for r in reps]
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            claim, post = C.section(reps, lambda a: nbr[a])
            shown = Counter(truth if s == "truth" else fake for *_, s, _ in reps if s != "junk")
            human = (shown.most_common(1)[0][0] == claim if shown else False) or u < 0.15
            if post[claim] >= P["tau"] and human:
                out["right" if claim == truth else "WRONG"] += 1
                C.settle(reps, post)
            else:
                out["stuck"] += 1
        C.witness(ids)
        for i in ids: nbr[i].update(ids)
    E = max(1, out["eligible"])
    S = {i: C.standing(i, nbr[i]) for i in kinds}
    hon = [S[a] for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [S[a] for a, k in kinds.items() if k in ("liar", "faker", "adv", "stolen")]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {"right": out["right"] / E, "wrong": out["WRONG"] / E, "stuck": out["stuck"] / E, "auc": auc}
    if readout: res["shape"] = shape(C, kinds, S)
    return res

def role(k): return {"adv": "ring", "stolen": "stolen"}.get(k, k)

def shape(C, kinds, S):
    ids = sorted(kinds)
    M = np.array([[C.a(i, j) if i != j else 0.0 for j in ids] for i in ids])
    roles = [role(kinds[i]) for i in ids]
    # bond strength between role groups
    blocks = defaultdict(list)
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            blocks[tuple(sorted((roles[x], roles[y])))].append(M[x, y])
    blk = {f"{a}-{b}": round(float(np.mean(v)), 3) for (a, b), v in blocks.items()}
    # clusters that fused: connected components at a > 0.5
    seen, comps = set(), []
    for s in range(len(ids)):
        if s in seen: continue
        stack, comp = [s], []
        while stack:
            u = stack.pop()
            if u in seen: continue
            seen.add(u); comp.append(u)
            stack += [v for v in range(len(ids)) if M[u, v] > 0.5 and v not in seen]
        if len(comp) > 1: comps.append(sorted(Counter(roles[c] for c in comp).items()))
    # spectral dimension of the bond network: participation ratio of the Laplacian spectrum
    Lap = np.diag(M.sum(1)) - M
    ev = np.linalg.eigvalsh(Lap)
    b0 = int((ev < 1e-3).sum())
    tiers = defaultdict(list)
    for i in ids: tiers[role(kinds[i])].append(S[i])
    return {"bonds": blk, "fused": comps, "b0": b0, "n": len(ids),
            "standing": {k: round(float(np.mean(v)), 2) for k, v in tiers.items()}}

# ------------------------------------------------------------------ evaluation
def evaluate(args):
    P, seeds, lam_risk, bonds = args
    rs = [run(P, coevo.make_world(s, a), bonds) for a in topo.suite() for s in seeds]
    f = [r["right"] - lam_risk * r["wrong"] + 0.3 * r["auc"] for r in rs]
    agg = {k: sum(r[k] for r in rs) / len(rs) for k in ("right", "wrong", "stuck", "auc")}
    agg["worst_wrong"] = max(r["wrong"] for r in rs)
    agg["fit"] = 0.5 * sum(f) / len(f) + 0.5 * min(f)
    return agg

def evolve(R, bonds, lam_risk=10, pop_n=16, gens=12):
    pop = [dict(DEFAULT)] + [{k: R.uniform(*r) for k, r in RANGES.items()} for _ in range(pop_n - 1)]
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48)]
            fs = pool.map(evaluate, [(P, seeds, lam_risk, bonds) for P in pop])
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

NAMES = ["cabal (co-evolved)", "cabal 2", "cabal 3", "ring", "sleeper + theft", "patient scatterers", "calm"]

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    arms = {"no bonds (points only)": False, "emergent bonds": True}
    best = {}
    for name, b in arms.items():
        best[name] = evolve(R, b)
        print(f"evolved {name:24}: " + ", ".join(f"{k}={v:.3f}" for k, v in best[name].items()), flush=True)
    test = [random.SystemRandom().getrandbits(48) for _ in range(3)]
    with Pool(4) as pool:
        res = pool.map(evaluate, [(best[n], test, 10, b) for n, b in arms.items()])
    print("\n### fresh worlds, full attack suite")
    print(f"{'':26} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}")
    for n, r in zip(arms, res):
        print(f"{n:26} {r['right']:6.2f} {r['wrong']:6.3f} {r['worst_wrong']:6.3f} {r['stuck']:6.2f} {r['auc']:5.2f}")
    print("\n### the shape that emerged (emergent bonds, one fresh world per scenario)")
    P = best["emergent bonds"]
    shapes = {}
    for nm, a in zip(NAMES, topo.suite()):
        r = run(P, coevo.make_world(test[0], a), True, readout=True)
        shapes[nm] = r
        s = r["shape"]
        print(f"\n[{nm}] right {r['right']:.2f} wrong {r['wrong']:.3f}  components b0={s['b0']} of {s['n']}")
        print("  bonds:", ", ".join(f"{k} {v}" for k, v in sorted(s["bonds"].items(), key=lambda x: -x[1])[:6]))
        print("  fused:", s["fused"])
        print("  standing:", s["standing"])
    json.dump({"best": best, "res": dict(zip(arms, res)), "shapes": shapes}, open("emerge-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
