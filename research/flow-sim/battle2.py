"""
Battle 2: can one number per agent do what Dawid-Skene's three numbers do?

Dawid-Skene (captcha.py, no observer gate) won battle.py, but its standing is three numbers per agent: how often
it was exact, one step off, far off. Rule 3 says one. Two one-number versions, same compile otherwise:

  one number, counted   p = (sum of outcomes + 1) / (count + 2), outcomes 1 exact, 0.5 one step off, 0 far;
                        the counts fade as before. (The count is how much evidence there is, not a second
                        opinion of the agent.)
  one number, stepped   p <- p + eta w (outcome - p), eta = 0.05 as in trust.py; no count at all.

Both derive the error shape from p alone (binomial): exact p^2, one step off 2p(1-p), far (1-p)^2.

Same six test worlds as battle.py, the same 19 attacks, plus one attacker evolved against each new version.
"""
import json, random, time
from collections import defaultdict
from multiprocessing import Pool
import captcha as K, battle as B, trust as T, coevo
from agents import D

def shape(p):
    p = min(max(p, 1e-3), 1 - 1e-3)
    return (p * p, 2 * p * (1 - p), (1 - p) * (1 - p))

class OneCounted(K.Captcha):
    def conf(self, i):
        if i in self._cc: return self._cc[i]
        v = self.c["s"][i]                          # [sum of outcomes, count, unused]
        self._cc[i] = r = shape((v[0] + 1.0) / (v[1] + 2.0))
        return r
    def learn(self, aid, said, post, w, err=None):
        e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
        v = self.c["s"][aid]; v[0] += (e + 0.5 * nr) * w; v[1] += w
        if err is not None: err[aid].append((1 - e) * w)

class OneStepped(K.Captcha):
    def __init__(self, opts):
        super().__init__(opts); self.p = defaultdict(lambda: 0.5)
    def conf(self, i):
        if i in self._cc: return self._cc[i]
        self._cc[i] = r = shape(self.p[i])
        return r
    def learn(self, aid, said, post, w, err=None):
        e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
        self.p[aid] += T.ETA * w * ((e + 0.5 * nr) - self.p[aid])
        if err is not None: err[aid].append((1 - e) * w)

def run_cls(cls):
    def go(opts, world, seed=0):
        orig = K.Captcha
        K.Captcha = cls
        try: r = K.run(opts, world, seed=seed)
        finally: K.Captcha = orig
        return {"right": r["right"], "wrong": r["wrong"], "contested": r["stuck"], "implicit": 0.0, "load": 1.0, "auc": r["auc"]}
    return go

NOGATE = dict(K.FULL, observers_gate=False)
NEW = {
    "DS, one number (counted)": (run_cls(OneCounted), NOGATE),
    "DS, one number (stepped)": (run_cls(OneStepped), NOGATE),
}
B.VERSIONS.update(NEW)
SHOW = ["Dawid-Skene, no observer gate", "DS, one number (counted)", "DS, one number (stepped)",
        "3 laws + bonds, validators always", "trust.py (current)"]

if __name__ == "__main__":
    t0 = time.time()
    prev = json.load(open("battle-result.json"))
    test = prev["test_seeds"]
    R = random.Random(prev["master_seed"] ^ 0xB2)
    suite = list(T.SUITE)
    for nm, f in (("hall of fame: trust adaptive", "trust-result.json"), ("hall of fame: captcha adaptive", "captcha-result.json")):
        suite.append((nm, json.load(open(f))["adaptive"]))
    for name, a in prev["evolved"].items(): suite.append(("evolved vs " + name, a))
    print("### an attacker evolved against each one-number version (same budget as battle.py)", flush=True)
    with Pool(4) as pool:
        new_att = {name: B.evolve_against(name, R, pool) for name in NEW}
    for name, a in new_att.items(): suite.append(("evolved vs " + name, a))
    print(f"\n### {len(SHOW)} versions x {len(suite)} attacks x {len(test)} worlds (the battle.py test worlds)", flush=True)
    with Pool(4) as pool:
        res = pool.map(B.job, [(name, s, i, a) for name in SHOW for i, (_, a) in enumerate(suite) for s in test], chunksize=4)
    k = len(test)
    cell = lambda name, i, key: sum(r[key] for n, j, r in res if n == name and j == i) / k
    own = {name: len(suite) - len(NEW) + n for n, name in enumerate(NEW)}
    print(f"\n{'':36} {'right':>6} {'wrong':>6} {'worst':>6} {'contest':>7} {'AUC':>5}   wrong vs the two new attackers")
    summary = {}
    for name in SHOW:
        rs = [r for n, j, r in res if n == name]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        worst = max(cell(name, i, "wrong") for i in range(len(suite)))
        newcols = [cell(name, i, "wrong") for i in own.values()]
        summary[name] = dict(right=m("right"), wrong=m("wrong"), worst=worst, contested=m("contested"), auc=m("auc"))
        print(f"{name:36} {m('right'):6.2f} {m('wrong'):6.3f} {worst:6.3f} {m('contested'):7.2f} {m('auc'):5.2f}   "
              + "  ".join(f"{x:.3f}" for x in newcols))
    print("\n### wrong per attack")
    for i, (nm, _) in enumerate(suite): print(f"  [{i:2}] {nm}")
    print(f"{'':36} " + " ".join(f"{i:>5}" for i in range(len(suite))))
    for name in SHOW:
        print(f"{name:36} " + " ".join(f"{cell(name, i, 'wrong'):5.3f}"[1:].rjust(5) for i in range(len(suite))))
    json.dump({"summary": summary, "evolved": new_att}, open("battle2-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
