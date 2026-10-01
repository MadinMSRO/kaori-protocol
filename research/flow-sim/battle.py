"""
Battle: every candidate on the same worlds, against every attacker any of them provoked.

World: the captcha world (coevo.make_world plus the provenance agent, a biased AI, a 40-validator pool that may
hold a farm, signed real photos). Same fresh seeds for every version.

Versions
  trust.py                    the current model (implicit consensus with min_network_trust, then validators,
                              contested = INCONCLUSIVE with the full penalty)
  trust.py, no implicit       every eligible key goes to validators
  3 laws + <screening>        Law 1 evidence adds as log-odds of standing S, screened by bonds;
                              Law 2 a truth forms when P >= lam/(1+lam), lam from stakes (10), at the finest grain;
                              Law 3 S <- S + eta (1000 outcome - S), outcome only from compiled truths.
                              The AI is one more witness. Validators are called only when observers + AI cannot
                              form. No min_network_trust. One arm calls validators on every key (load held equal).
      screening: bonds (presence + error, divide by bonded mass) | presence only | none |
                 tuned flock exp(-mu x excess co-presence), mu from evo | GLS (inverse dependence matrix, derived)
  Dawid-Skene (captcha.py)    the seed lineage: three-number standing (breaks Rule 3), with and without the
                              observers' agreement gate

Attackers: one evolved against each version with the same budget, plus the earlier hall of fame and the suite.
Every version faces all of them.
"""
import math, random, time, json, sys
from collections import Counter, defaultdict
from multiprocessing import Pool
import numpy as np
import coevo, captcha as K, trust as T, agents as A
from agents import VALS, WORTH, HOSTILE

MU_EVO = 2.75   # flock screening strength of evo.py's champion (the one tuned constant in this file)

class ThreeLaws(T.Trust):
    def screen(self, ids):
        mode = self.o["screen"]
        if mode in ("bonds", "presence"):
            return {i: 1.0 / sum(self.a(i, j) for j in ids) for i in ids}
        if mode == "none":
            return {i: 1.0 for i in ids}
        if mode == "flock":
            N = max(self.N, 1.0); f = {}
            for i in ids:
                ex = 0.0
                for j in ids:
                    if j == i: continue
                    nij = self.nij.get(tuple(sorted((i, j))), 0.0)
                    ex += max(0.0, nij / (self.n[i] + 1) - self.n[j] / N)
                f[i] = math.exp(-MU_EVO * ex)
            return f
        if mode == "gls":
            n = len(ids)
            if n == 1: return {ids[0]: 1.0}
            C = np.eye(n)
            for x in range(n):
                for y in range(x + 1, n): C[x, y] = C[y, x] = self.a(ids[x], ids[y])
            try: inv1 = np.linalg.solve(C + 1e-6 * np.eye(n), np.ones(n))
            except np.linalg.LinAlgError: inv1 = np.ones(n)
            inv1 = np.clip(inv1, 0, None)
            share = inv1 / (inv1.max() or 1)
            return {i: float(s) for i, s in zip(ids, share)}
        raise ValueError(mode)

    def evidence(self, cell, humans):
        reps, items = cell
        ids = [it[0] for it in items]
        ev = defaultdict(float)
        sc = self.screen(ids)
        for aid, said, passed, sky, reads in items:
            ev[said] += T.weight(self.S[aid]) * self.realness_of(aid, passed, sky) * sc[aid]
        for aid, said, passed, sky, reads in items:
            real = self.realness_of(aid, passed, sky)
            rs = [(r, x) for r, x in reads if x is not None and (humans or r == "ai")]
            if not rs: continue
            rsc = self.screen([r for r, _ in rs])
            for r, x in rs: ev[x] += T.weight(self.S[r]) * real * rsc[r]
        return ev

def run3(opts, world, seed=0):
    events, POOL = world
    C = ThreeLaws(opts)
    lam = opts["stakes"]; tau = lam / (1 + lam)
    out = Counter(); last_t = -1; kinds = {}; opened = []
    def resolve(cell, truth, first):
        g = None if opts.get("always_humans") else T.grain_of(T.dominance(C.evidence(cell, False)), tau)
        humans = False
        if not g:
            if first: out["load"] += 1
            humans = True
            g = T.grain_of(T.dominance(C.evidence(cell, True)), tau)
            if not g: return False
        grain, Sset = g
        if truth in Sset: out["right"] += WORTH[grain]
        else: out["wrong"] += 1
        if not humans: out["implicit"] += 1
        C.settle_verified(cell, Sset, with_readers=humans)
        return True
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            still = []
            for t0, cell, tr in opened:
                if resolve(cell, tr, False): pass
                elif t - t0 < A.OPEN_H: still.append((t0, cell, tr))
                else:
                    out["contested"] += 1
                    C.settle_contested(cell)
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, truth, True): opened.append((t, cell, truth))
        C.observe(cell)
    out["contested"] += len(opened)
    E = max(1, out["eligible"])
    hon = [C.S[a] for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [C.S[a] for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "contested", "implicit", "load")}
    res["auc"] = auc
    return res

def run_trust(opts, world, seed=0):
    r = T.run(opts, world, seed=seed)
    r["load"] = sum(r["load"]) / 4
    return r

def run_ds(opts, world, seed=0):
    r = K.run(opts, world, seed=seed)
    return {"right": r["right"], "wrong": r["wrong"], "contested": r["stuck"], "implicit": 0.0, "load": 1.0, "auc": r["auc"]}

L3 = dict(T.FULL, stakes=10.0, contest_outcome=0.0, error_bonds=True)
VERSIONS = {
    "trust.py (current)": (run_trust, T.FULL),
    "trust.py, no implicit consensus": (run_trust, dict(T.FULL, min_trust=float("inf"))),
    "3 laws + bonds (presence+error)": (run3, dict(L3, screen="bonds")),
    "3 laws + presence-only bonds": (run3, dict(L3, screen="presence", error_bonds=False)),
    "3 laws + tuned flock (mu=2.75)": (run3, dict(L3, screen="flock")),
    "3 laws + GLS screening (derived)": (run3, dict(L3, screen="gls")),
    "3 laws, no screening": (run3, dict(L3, screen="none")),
    "3 laws + bonds, validators always": (run3, dict(L3, screen="bonds", always_humans=True)),
    "Dawid-Skene + observer gate": (run_ds, K.FULL),
    "Dawid-Skene, no observer gate": (run_ds, dict(K.FULL, observers_gate=False)),
}

def play(name, s, att):
    fn, opts = VERSIONS[name]
    return fn(opts, K.make(s, att, "critical"), seed=s)

def fitness(rs):
    m = lambda k: sum(r[k] for r in rs) / len(rs)
    return m("wrong") + 0.1 * m("contested") + 0.2 * (1 - m("auc"))

def attack_fit(args):
    name, a, seeds = args
    return fitness([play(name, s, a) for s in seeds])

RNG = dict(coevo.A_RANGES, farm=(0, 12), signed=(0.0, 1.0))

def evolve_against(name, R, pool, pop_n=16, gens=10):
    def rand(): return {k: R.uniform(*r) for k, r in RNG.items()}
    def mut(a):
        b = dict(a)
        for k, (lo, hi) in RNG.items():
            if R.random() < 0.3: b[k] = min(hi, max(lo, b[k] + R.gauss(0, (hi - lo) * 0.2)))
        return b
    pop = [rand() for _ in range(pop_n - 1)] + [dict(K.FARM_ATTACK)]
    best_f = 0.0
    for g in range(gens):
        seeds = [R.getrandbits(48) for _ in range(2)]
        fs = pool.map(attack_fit, [(name, a, seeds) for a in pop])
        ranked = [a for _, a in sorted(zip(fs, pop), key=lambda x: -x[0])]
        best_f = max(fs)
        nxt = [dict(a) for a in ranked[:4]]
        while len(nxt) < pop_n: nxt.append(mut(R.choice(ranked[:8])))
        pop = nxt
    print(f"  vs {name:34} best attacker fitness {best_f:.3f}  {coevo.show_att(ranked[0])}, farm {round(ranked[0]['farm'])}, signed {ranked[0]['signed']:.0%}", flush=True)
    return ranked[0]

def job(args):
    name, s, i, att = args
    return name, i, play(name, s, att)

if __name__ == "__main__":
    t0 = time.time()
    master = random.SystemRandom().getrandbits(48)
    R = random.Random(master)
    print(f"master seed {master}")
    suite = list(T.SUITE)
    for nm, f in (("hall of fame: trust adaptive", "trust-result.json"), ("hall of fame: captcha adaptive", "captcha-result.json")):
        suite.append((nm, json.load(open(f))["adaptive"]))
    print("\n### phase 1: an attacker evolved against each version (16 x 10 generations x 2 worlds each)", flush=True)
    evolved = {}
    with Pool(4) as pool:
        for name in VERSIONS:
            evolved[name] = evolve_against(name, R, pool)
    for name, a in evolved.items(): suite.append(("evolved vs " + name, a))
    test = [R.getrandbits(48) for _ in range(6)]
    print(f"\n### phase 2: every version x {len(suite)} attacks x {len(test)} fresh worlds", flush=True)
    with Pool(4) as pool:
        res = pool.map(job, [(name, s, i, a) for name in VERSIONS for i, (_, a) in enumerate(suite) for s in test], chunksize=4)
    k = len(test)
    cell = lambda name, i, key: sum(r[key] for n, j, r in res if n == name and j == i) / k
    print(f"\n{'':36} {'right':>6} {'wrong':>6} {'worst':>6} {'own':>6} {'contest':>7} {'implicit':>8} {'load':>5} {'AUC':>5}")
    own_idx = {name: len(suite) - len(VERSIONS) + n for n, name in enumerate(VERSIONS)}
    summary = {}
    for name in VERSIONS:
        rs = [r for n, j, r in res if n == name]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        worst = max(cell(name, i, "wrong") for i in range(len(suite)))
        own = cell(name, own_idx[name], "wrong")
        summary[name] = dict(right=m("right"), wrong=m("wrong"), worst=worst, own=own, contested=m("contested"),
                             implicit=m("implicit"), load=m("load"), auc=m("auc"))
        print(f"{name:36} {m('right'):6.2f} {m('wrong'):6.3f} {worst:6.3f} {own:6.3f} {m('contested'):7.2f} {m('implicit'):8.2f} {m('load'):5.2f} {m('auc'):5.2f}")
    print("\n### wrong per attack (rows: versions; columns: attacks)")
    for i, (nm, _) in enumerate(suite):
        print(f"  [{i:2}] {nm}")
    print(f"{'':36} " + " ".join(f"{i:>5}" for i in range(len(suite))))
    for name in VERSIONS:
        print(f"{name:36} " + " ".join(f"{cell(name, i, 'wrong'):5.3f}"[1:].rjust(5) for i in range(len(suite))))
    print("\n### right per attack")
    print(f"{'':36} " + " ".join(f"{i:>5}" for i in range(len(suite))))
    for name in VERSIONS:
        print(f"{name:36} " + " ".join(f"{cell(name, i, 'right'):5.2f}" for i in range(len(suite))))
    json.dump({"master_seed": master, "test_seeds": test, "summary": summary,
               "evolved": evolved}, open("battle-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
