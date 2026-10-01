"""
Battle 3: simple local rules on the graph, against the statistical winner.

Two rule systems, both one number per agent (Rule 3), both with the same compile (each reading's likelihood,
weighted by the reader's number, realness from the provenance agent):

  exchange   an agent's number is its record against the keys it touched: when a key settles, each neighbour
             takes the key's belief as its outcome (1 exact, 0.5 one step off). The item being judged is never
             in its own readers' records, so no node counts itself. (This is battle2's counted one-number
             version.)
  shape      an agent's number is where it sits in the signed graph. Two agents reading the same item gain an
             edge: +1 if they agree, -1 if they are two or more steps apart, 0 if one step. Each hour every
             spin relaxes to the signed average of its neighbours' spins (structural balance). S = 500 (1 + s).
             Nothing is graded against a compiled truth.

  contraction (both): two agents whose bond (shared presence and shared error beyond chance) is more likely than
             not are one node; merged transitively; a merged node counts once at any key.

Formation: the stakes threshold lam/(1+lam) is a minimum. "stable" also requires the leading value to be the same
as at the previous hourly evaluation (the key has stopped moving); "immediate" settles on the first pass.
"""
import json, random, time
from collections import Counter, defaultdict
from multiprocessing import Pool
import captcha as K, battle as B, battle2 as B2, trust as T, seed as S, agents as A
from agents import VALS, D, WORTH, HOSTILE, form

class Contract:
    """Mixin: bonds above 1/2 contract agents into one node (union-find over every pair ever seen together)."""
    def _components(self):
        if getattr(self, "_root_ok", False): return
        parent = {}
        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
            return x
        for key in set(self.nij) | set(self.mij):
            if S.Seed.a(self, *key) > 0.5:
                ra, rb = find(key[0]), find(key[1])
                if ra != rb: parent[ra] = rb
        self._root = {x: find(x) for x in parent}
        self._root_ok = True
    def a(self, i, j):
        if i == j: return 1.0
        self._components()
        return 1.0 if self._root.get(i, i) == self._root.get(j, j) else 0.0
    def fade(self, hour):
        super().fade(hour); self._root_ok = False

class Exchange(Contract, B2.OneCounted):
    pass

class Shape(Contract, K.Captcha):
    def __init__(self, opts):
        super().__init__(opts)
        self.J = defaultdict(float); self.spin = defaultdict(lambda: 1.0); self.nb = defaultdict(set)
    def conf(self, i):
        if i in self._cc: return self._cc[i]
        self._cc[i] = r = B2.shape((1 + self.spin[i]) / 2)
        return r
    def learn(self, aid, said, post, w, err=None):          # no grading: only the shared-error record for bonds
        if err is not None: err[aid].append((1 - post[said]) * w)
    def edges(self, cell):
        reps, items = cell
        for aid, said, passed, sky, reads in items:
            rs = [(aid, said)] + [(r, x) for r, x in reads if x is not None]
            for p in range(len(rs)):
                for q in range(p + 1, len(rs)):
                    (i, x), (j, y) = rs[p], rs[q]
                    if i == j: continue
                    d = D[(x, y)]
                    g = 1.0 if d == 0 else -1.0 if d >= 2 else 0.0
                    if g == 0.0: continue
                    k = (i, j) if i < j else (j, i)
                    self.J[k] += g; self.nb[i].add(j); self.nb[j].add(i)
    def relax(self):
        new = {}
        for i, ns in self.nb.items():
            num = den = 0.0
            for j in ns:
                w = self.J[(i, j) if i < j else (j, i)]
                num += w * self.spin[j]; den += abs(w)
            if den > 0: new[i] = num / den
        self.spin.update(new); self._cc = {}
    def observe(self, cell):
        super().observe(cell); self.edges(cell)
    def fade(self, hour):
        super().fade(hour)
        for k in self.J: self.J[k] *= 1 - S.SLOW
        self.relax()

def run_rules(cls, stable):
    def go(opts, world, seed=0):
        events, POOL = world
        C = cls(opts)
        humans = True
        RG = random.Random(seed ^ 0x601D)
        out = Counter(); last_t = -1; kinds = {}; opened = []; gold = []
        def resolve(entry, truth):
            cell, prev = entry[1], entry[3]
            post = C.evidence(cell, None)
            f = form(post, C.tau, True)
            if not f: entry[3] = None; return False
            grain, Sset = f
            if stable and prev != frozenset(Sset): entry[3] = frozenset(Sset); return False
            if truth in Sset: out["right"] += WORTH[grain]
            else: out["wrong"] += 1
            C.settle(cell, None, post)
            if grain == "exact": gold.append((truth, post))
            return True
        for t, p, truth, fake, reps, u, items in events:
            if t != last_t:
                for h in range(last_t + 1, t + 1): C.fade(h)
                last_t = t
                if opts["gold"] and gold:
                    for vid in POOL:
                        if RG.random() < 0.3:
                            content, post = RG.choice(gold[-300:])
                            C.learn(vid, K.v_read(RG, vid, content, False, None), post, 1.0)
                    C._cc = {}
                still = []
                for e in opened:
                    if resolve(e, e[2]): pass
                    elif t - e[0] < A.OPEN_H: still.append(e)
                    else: out["stuck"] += 1
                opened = still
            cell = (reps, items)
            for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
            C.observe(cell)
            if len(reps) >= 3:
                out["eligible"] += 1
                e = [t, cell, truth, None]
                if not resolve(e, truth): opened.append(e)
        out["stuck"] += len(opened)
        E = max(1, out["eligible"])
        def St(i): c = C.conf(i); return c[0] - c[2]
        hon = [St(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
        hos = [St(a) for a, k in kinds.items() if k in HOSTILE]
        auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
        return {"right": out["right"] / E, "wrong": out["wrong"] / E, "contested": out["stuck"] / E,
                "implicit": 0.0, "load": 1.0, "auc": auc}
    return go

OPTS = dict(K.FULL, observers_gate=False)
NEW = {
    "exchange + contraction, stable": (run_rules(Exchange, True), OPTS),
    "exchange + contraction, immediate": (run_rules(Exchange, False), OPTS),
    "shape + contraction, stable": (run_rules(Shape, True), OPTS),
    "shape + contraction, immediate": (run_rules(Shape, False), OPTS),
}
B.VERSIONS.update(NEW)
SHOW = list(NEW) + ["DS, one number (counted)", "Dawid-Skene, no observer gate", "trust.py (current)"]

if __name__ == "__main__":
    t0 = time.time()
    prev = json.load(open("battle-result.json")); prev2 = json.load(open("battle2-result.json"))
    test = prev["test_seeds"]
    R = random.Random(prev["master_seed"] ^ 0xB3)
    suite = list(T.SUITE)
    for nm, f in (("hall of fame: trust adaptive", "trust-result.json"), ("hall of fame: captcha adaptive", "captcha-result.json")):
        suite.append((nm, json.load(open(f))["adaptive"]))
    for name, a in list(prev["evolved"].items()) + list(prev2["evolved"].items()): suite.append(("evolved vs " + name, a))
    print("### an attacker evolved against each rule system (same budget as battle.py)", flush=True)
    with Pool(4) as pool:
        new_att = {name: B.evolve_against(name, R, pool) for name in NEW}
    for name, a in new_att.items(): suite.append(("evolved vs " + name, a))
    print(f"\n### {len(SHOW)} versions x {len(suite)} attacks x {len(test)} worlds (the battle.py test worlds)", flush=True)
    with Pool(4) as pool:
        res = pool.map(B.job, [(name, s, i, a) for name in SHOW for i, (_, a) in enumerate(suite) for s in test], chunksize=4)
    k = len(test)
    cell = lambda name, i, key: sum(r[key] for n, j, r in res if n == name and j == i) / k
    own = [len(suite) - len(NEW) + n for n in range(len(NEW))]
    print(f"\n{'':36} {'right':>6} {'wrong':>6} {'worst':>6} {'contest':>7} {'AUC':>5}   wrong vs the four new attackers")
    summary = {}
    for name in SHOW:
        rs = [r for n, j, r in res if n == name]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        worst = max(cell(name, i, "wrong") for i in range(len(suite)))
        summary[name] = dict(right=m("right"), wrong=m("wrong"), worst=worst, contested=m("contested"), auc=m("auc"))
        print(f"{name:36} {m('right'):6.2f} {m('wrong'):6.3f} {worst:6.3f} {m('contested'):7.2f} {m('auc'):5.2f}   "
              + "  ".join(f"{cell(name, i, 'wrong'):.3f}" for i in own))
    print("\n### wrong per attack")
    for i, (nm, _) in enumerate(suite): print(f"  [{i:2}] {nm}")
    print(f"{'':36} " + " ".join(f"{i:>5}" for i in range(len(suite))))
    for name in SHOW:
        print(f"{name:36} " + " ".join(f"{cell(name, i, 'wrong'):5.3f}"[1:].rjust(5) for i in range(len(suite))))
    json.dump({"summary": summary, "evolved": new_att}, open("battle3-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
