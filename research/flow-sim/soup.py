"""
Soup: start from scratch and watch what condenses.

Inspired by "Reality as Rendering" (Madin Maseeh): Infinity + Constraint -> Rendered Reality -> Stable Compressions
-> Attractors. The world is the infinity (a hidden sky). Every entity renders it through its constraints and emits
Signals. Kaori sees only Signals: who emitted what about which object. No kinds, no roles, no labels.

Kernel   emitters and objects (items of evidence, the keys they belong to). A Signal is an edge.
Law      (placeholder, the one thing given) conduit reinforcement, as in mycelium:
         every emitter has one conduit thickness c (Rule 3's one number), starting thin (0.1).
         When a truth forms, each emitter that rendered that object carries flow into it: c moves toward its outcome
         (1 matched, 0.5 one step off, 0 far) in proportion to that truth's trust. Unused conduits thin slowly.
Entanglement  two emitters dissenting from a formed truth together, beyond what their own dissent rates explain,
         are adjacent in the kernel (correlation the rendered map does not explain).
Trust    a value's trust at an object is the conduit flow reaching it through independent renderings: each
         emitter's thickness divided by its entangled mass, so an entangled group renders once.
         Snapshot = 1 - exp(-trust). A truth forms when its share of all trust passes lam/(1+lam) (the minimum),
         carrying its snapshot; low thickness everywhere means low-trust truths at first.

Variants (what is given): none (no law: every conduit stays at 0.1) | flow | flow + entanglement |
flow + entanglement + provenance (the provenance agent's realness reading weights each item).

Second round (G:): dissent is grounded in the evidence (each emitter against the readings of the other items at its
key, never against a formed truth), rendering is graded (one step off half-supports; a thin conduit is uninformed,
not anti-informative), and the trust snapshot is the thickness-weighted share of independent support behind the
truth (bounded). The AI and blind validators were emitters from the start; their readings are now the anchor.

Measured from outside only (the network never sees it): right / wrong / stuck; whether trust snapshots separate
true truths from false ones; how trust grows (an attractor); the conduit thickness each hidden kind ends with.
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import captcha as K, trust as T, seed as S, agents as A
from agents import VALS, D, WORTH, HOSTILE, form

C0, ETA, THIN, STAKES = 0.1, 0.05, S.SLOW, 10.0

class Soup:
    def __init__(self, law, entangle, provenance, grounded=False, graded=False):
        self.law, self.entangle, self.provenance = law, entangle, provenance
        self.grounded, self.graded = grounded, graded
        self.c = defaultdict(lambda: C0)
        self.ne = defaultdict(float); self.se = defaultdict(float); self.mij = defaultdict(float); self.wij = defaultdict(float)
        self._ac = {}
        self.pv = defaultdict(lambda: [0.0, 0.0]); self._rho = None
    # ---- the provenance agent (only in the last variant)
    rho = A.Complex.rho
    realness = S.Seed.realness
    # ---- entanglement: shared dissent beyond chance
    def a(self, i, j):
        if i == j: return 1.0
        if not self.entangle: return 0.0
        key = (i, j) if i < j else (j, i)
        if key in self._ac: return self._ac[key]
        x = 0.0
        m, w = self.mij.get(key, 0.0), self.wij.get(key, 0.0)
        if m >= 1 and self.ne[i] > 0 and self.ne[j] > 0:
            exp = m * (self.se[i] / self.ne[i]) * (self.se[j] / self.ne[j])
            x = max(0.0, math.log((w + 0.05) / (exp + 0.05))) * w / (w + 1)
        self._ac[key] = r = 1 - math.exp(-x)
        return r
    def signals(self, cell):
        """Every Signal at this object: (emitter, value, item weight)."""
        reps, items = cell
        out = []
        for aid, said, passed, sky, reads in items:
            w = self.realness(aid, passed) * (1.0 if sky else 0.05) if self.provenance else 1.0
            out.append((aid, said, w))
            for r, x in reads:
                if x is not None: out.append((r, x, w))
        return out
    def trust(self, sig):
        em = list({e for e, _, _ in sig})
        mass = {e: sum(self.a(e, f) for f in em) for e in em}
        k = Counter(e for e, _, _ in sig)
        tv = defaultdict(float)
        for e, x, w in sig: tv[x] += self.c[e] * w / (mass[e] * k[e])
        return tv
    def posterior(self, sig):
        """Graded rendering: a signal supports its value, half-supports one step off; a thin conduit is uninformed."""
        em = list({e for e, _, _ in sig})
        mass = {e: sum(self.a(e, f) for f in em) for e in em}
        k = Counter(e for e, _, _ in sig)
        L = {v: 0.0 for v in VALS}
        for e, x, w in sig:
            r = self.c[e] * w
            g = {v: 1.0 if D[(x, v)] == 0 else 0.5 if D[(x, v)] == 1 else 0.0 for v in VALS}
            z = sum(g.values())
            for v in VALS: L[v] += math.log((1 - r) + r * len(VALS) * g[v] / z) / (mass[e] * k[e])
        m = max(L.values()); Z = sum(math.exp(x - m) for x in L.values())
        return {v: math.exp(L[v] - m) / Z for v in VALS}, mass, k
    def snapshot(self, sig, Sset, mass, k):
        """Trust snapshot: the independent support behind the truth, weighted by conduit thickness, as a share of all
        independent support present (bounded in [0, 1])."""
        sup = tot = 0.0
        for e, x, w in sig:
            u = w / (mass[e] * k[e]); tot += u
            if x in Sset: sup += self.c[e] * u
        return sup / tot if tot > 0 else 0.0
    def ground(self, cell):
        """Grounded dissent: each emitter against the readings of OTHER items at this key (never its own item, never
        a formed truth), weighted by the readers' thickness and the items' realness. Feeds entanglement."""
        reps, items = cell
        if len(items) < 2: return
        reads = []                                   # (item index, reader, value, weight)
        for n, (aid, said, passed, sky, rs) in enumerate(items):
            w = self.realness(aid, passed) * (1.0 if sky else 0.05) if self.provenance else 1.0
            for r, x in rs:
                if x is not None: reads.append((n, r, x, self.c[r] * w))
        sig = [(n, aid, said) for n, (aid, said, *_ ) in enumerate(items)] + [(n, r, x) for n, r, x, _ in reads]
        dis = {}
        for n, e, x in sig:
            p = defaultdict(float); tot = 0.0
            for m, r, y, w in reads:
                if m == n or r == e: continue
                p[y] += w; tot += w
            if tot <= 0: continue
            agree = sum(q * (1.0 if D[(x, y)] == 0 else 0.5 if D[(x, y)] == 1 else 0.0) for y, q in p.items()) / tot
            dis[e] = max(dis.get(e, 0.0), 1.0 - agree)
        if len(dis) < 2: return
        # what the rendered reality explains: the key's own ambiguity (everyone's mean dissent here). Only dissent
        # beyond it is the emitter's own, and only shared excess dissent is entanglement.
        mean = sum(dis.values()) / len(dis)
        res = {e: max(0.0, d - mean) for e, d in dis.items()}
        for e, d in res.items(): self.ne[e] += 1; self.se[e] += d
        ks = list(res)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = (ks[x], ks[y]) if ks[x] < ks[y] else (ks[y], ks[x])
                self.mij[key] += 1; self.wij[key] += res[ks[x]] * res[ks[y]]
        self._ac = {}
    def settle(self, sig, Sset, snap):
        err = {}
        for e, x, w in sig:
            o = 1.0 if x in Sset else 0.5 if min(D[(x, v)] for v in Sset) == 1 else 0.0
            if self.law: self.c[e] += ETA * snap * w * (o - self.c[e])
            err[e] = max(err.get(e, 0.0), 1.0 - o)
        if self.grounded: return
        for e, d in err.items(): self.ne[e] += 1; self.se[e] += d
        ks = list(err)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = (ks[x], ks[y]) if ks[x] < ks[y] else (ks[y], ks[x])
                self.mij[key] += 1; self.wij[key] += err[ks[x]] * err[ks[y]]
        self._ac = {}
    def observe(self, cell):
        reps, items = cell
        for aid, said, passed, sky, reads in items: self.pv[aid][0] += passed; self.pv[aid][1] += 1
        self._rho = None
        if self.grounded and self.entangle: self.ground(cell)
    def fade(self):
        if self.law:
            for e in self.c: self.c[e] *= 1 - THIN
        for d in (self.ne, self.se, self.mij, self.wij):
            for k in d: d[k] *= 1 - S.SLOW
        self._ac = {}

VARIANTS = {
    "none (no law)": (False, False, False),
    "flow": (True, False, False),
    "flow + entanglement": (True, True, False),
    "flow + entanglement + provenance": (True, True, True),
    # second round: entanglement grounded in the evidence, graded rendering, bounded snapshot
    "G: none (no law), graded + provenance": (False, False, True, True, True),
    "G: flow, graded + provenance": (True, False, True, True, True),
    "G: flow + grounded entanglement, graded": (True, True, False, True, True),
    "G: flow + grounded entanglement, graded + provenance": (True, True, True, True, True),
}

def run(name, world, detail=False):
    events, POOL = world
    N = Soup(*VARIANTS[name])
    tau = STAKES / (1 + STAKES)
    out = Counter(); last_t = -1; kinds = {}; opened = []
    snaps = []                                    # (quarter, snapshot, truth was right)
    Tn = events[-1][0] + 1 if events else 1
    def resolve(cell, t, truth):
        sig = N.signals(cell)
        if N.graded:
            share, mass, kk = N.posterior(sig)
        else:
            tv = N.trust(sig)
            tot = sum(tv.values())
            if tot <= 0: return False
            share = {v: tv.get(v, 0.0) / tot for v in VALS}
        f = form(share, tau, True)
        if not f: return False
        grain, Sset = f
        snap = N.snapshot(sig, Sset, mass, kk) if N.graded else 1 - math.exp(-sum(tv.get(v, 0.0) for v in Sset))
        ok = truth in Sset
        if ok: out["right"] += WORTH[grain]
        else: out["wrong"] += 1
        snaps.append((min(3, 4 * t // Tn), snap, ok))
        N.settle(sig, Sset, snap)
        return True
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): N.fade()
            last_t = t
            still = []
            for t0, cell, tr in opened:
                if resolve(cell, t0, tr): pass
                elif t - t0 < A.OPEN_H: still.append((t0, cell, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        N.observe(cell)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, t, truth): opened.append((t, cell, truth))
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    rs = [s for _, s, ok in snaps if ok]; ws = [s for _, s, ok in snaps if not ok]
    sep = (sum((x > y) + 0.5 * (x == y) for x in rs for y in ws) / (len(rs) * len(ws))) if rs and ws else float("nan")
    hon = [N.c[a] for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [N.c[a] for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {"right": out["right"] / E, "wrong": out["wrong"] / E, "stuck": out["stuck"] / E, "sep": sep, "auc": auc,
           "snap_q": [sum(s for q, s, _ in snaps if q == i) / max(1, sum(1 for q, *_ in snaps if q == i)) for i in range(4)],
           "snap_right": sum(rs) / max(1, len(rs)), "snap_wrong": sum(ws) / max(1, len(ws))}
    if detail:
        tiers = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(N.c[a])
        for v in POOL: tiers[v.rstrip("0123456789")].append(N.c[v])
        tiers["ai"].append(N.c["ai"])
        res["thickness"] = {k: round(sum(v) / len(v), 2) for k, v in tiers.items()}
    return res

def job(args):
    name, s, i, att = args
    return name, i, run(name, K.make(s, att, "critical"))

if __name__ == "__main__":
    t0 = time.time()
    prev = json.load(open("battle-result.json")); prev2 = json.load(open("battle2-result.json"))
    test = prev["test_seeds"]
    suite = list(T.SUITE)
    for nm, f in (("hall of fame: trust adaptive", "trust-result.json"), ("hall of fame: captcha adaptive", "captcha-result.json")):
        suite.append((nm, json.load(open(f))["adaptive"]))
    for name, a in list(prev["evolved"].items()) + list(prev2["evolved"].items()): suite.append(("evolved vs " + name, a))
    print(f"### {len(VARIANTS)} variants x {len(suite)} attacks x {len(test)} worlds (the battle test worlds)", flush=True)
    with Pool(4) as pool:
        res = pool.map(job, [(n, s, i, a) for n in VARIANTS for i, (_, a) in enumerate(suite) for s in test], chunksize=4)
    k = len(test)
    cell = lambda n, i, key: sum(r[key] for m, j, r in res if m == n and j == i) / k
    nan = lambda xs: [x for x in xs if x == x]
    print(f"\n{'':34} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} | {'trust of true':>13} {'of false':>8} {'sep':>5} | {'kind AUC':>8} | trust by quarter")
    summary = {}
    for n in VARIANTS:
        rs = [r for m, j, r in res if m == n]
        mm = lambda x: sum(r[x] for r in rs) / len(rs)
        sep = nan([r["sep"] for r in rs]); sep = sum(sep) / len(sep) if sep else float("nan")
        worst = max(cell(n, i, "wrong") for i in range(len(suite)))
        q = [sum(r["snap_q"][i] for r in rs) / len(rs) for i in range(4)]
        summary[n] = dict(right=mm("right"), wrong=mm("wrong"), worst=worst, stuck=mm("stuck"), sep=sep, auc=mm("auc"),
                          snap_right=mm("snap_right"), snap_wrong=mm("snap_wrong"), snap_q=q)
        print(f"{n:34} {mm('right'):6.2f} {mm('wrong'):6.3f} {worst:6.3f} {mm('stuck'):6.2f} | {mm('snap_right'):13.2f} {mm('snap_wrong'):8.2f} {sep:5.2f} | {mm('auc'):8.2f} | "
              + " -> ".join(f"{x:.2f}" for x in q))
    print("\n### wrong per attack")
    for i, (nm, _) in enumerate(suite): print(f"  [{i:2}] {nm}")
    print(f"{'':34} " + " ".join(f"{i:>5}" for i in range(len(suite))))
    for n in VARIANTS:
        print(f"{n:34} " + " ".join(f"{cell(n, i, 'wrong'):5.3f}"[1:].rjust(5) for i in range(len(suite))))
    print("\n### conduit thickness each hidden kind ended with (one world per attack, first test seed)")
    for nm, a in [suite[0], suite[1], suite[5], suite[8]]:
        for n in list(VARIANTS)[1:]:
            r = run(n, K.make(test[0], a, "critical"), detail=True)
            print(f"  [{nm[:22]:22}] {n:34} {r['thickness']}")
    json.dump({"summary": summary}, open("soup-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
