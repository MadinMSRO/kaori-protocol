"""
Implicit consensus gated by earned standing, with escalation to captcha validators.

Implicit path (no validators): only observers whose reliability the network is sure of can form it. That means
the lower credible bound of their exact-or-near share is at least `elig` (a ClaimType parameter). Each eligible
observer's claim counts by standing x realness x how well its own photo supports it (the AI's reading),
divided by bonded mass. The AI's readings of their photos count too. Disagreement simply lowers the posterior.
The truth forms implicitly when there are at least `min_obs` effective independent eligible observers and
the posterior passes the stakes threshold.
Otherwise the TruthKey escalates: captcha validators assess every item blind, and the truth compiles from the
evidence (with no observer veto).
Either way, every agent that took part gets a signal against the compiled truth, newcomers included, so
standing is earned.
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo, seed as S, captcha as K, agents as A
from agents import VALS, D, form, WORTH, HOSTILE
from emerge import NAMES

class Hybrid(K.Captcha):
    def earned(self, aid):
        """Lower credible bound (about 10%) of the share of exact-or-near reports, from compiled signals only."""
        v = self.c["s"][aid]
        a = v[0] + v[1]; b = v[2]
        n = a + b
        if n < 1: return 0.0
        a += 1; b += 1; n += 2                       # uniform prior: no benefit of the doubt for the gate
        m = a / n; sd = math.sqrt(m * (1 - m) / (n + 1))
        return m - 1.28 * sd

    def ai_support(self, said, reads):
        ai = [x for r, x in reads if r == "ai" and x is not None]
        if not ai: return 1.0
        lk = self.lik(ai[0], self.conf("ai")); z = sum(lk.values())
        return sum(p for c, p in lk.items() if D[(c, said)] <= 1) / z

    def implicit(self, cell, mem):
        its = self.cell_items(cell)
        elig = [(aid, said, real, reads) for aid, said, real, reads in its if self.earned(aid) >= self.o["elig"]]
        ids = [e[0] for e in elig]
        n_eff = sum(real / sum(self.a(aid, j) for j in ids) for aid, said, real, reads in elig)
        if n_eff < self.o["min_obs"]: return None
        L = {u: 0.0 for u in VALS}
        for aid, said, real, reads in elig:
            mass = sum(self.a(aid, j) for j in ids)
            r = real * self.ai_support(said, reads)
            lk = self.lik(said, self.conf(aid))
            for u in VALS: L[u] += math.log(r * lk[u] + (1 - r) / len(VALS)) / mass
            for rd, x in reads:
                if rd == "ai" and x is not None:
                    lk = self.lik(x, self.conf("ai"))
                    for u in VALS: L[u] += math.log(real * lk[u] + (1 - real) / len(VALS)) / mass
        if mem is not None:
            lk = self.lik(mem, self.conf("mem"))
            for u in VALS: L[u] += math.log(lk[u])
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def settle_ai_only(self, cell, mem, post):
        """Implicit compile: the items were never shown to validators, so only observers, the AI and memory learn."""
        reps, items = cell
        stripped = (reps, [(aid, said, passed, sky, [(r, x) for r, x in reads if r == "ai"]) for aid, said, passed, sky, reads in items])
        self.settle(stripped, mem, post)

FULL = dict(S.FULL, timescales=False, gold=False, observers_gate=False, elig=0.6, min_obs=3.0, stakes_implicit=3.0)

def run(opts, world, seed=0, detail=False):
    events, POOL = world
    C = Hybrid(opts)
    tau_imp = opts["stakes_implicit"] / (1 + opts["stakes_implicit"])
    out = Counter(); last_t = -1; kinds = {}; opened = []; last = {}; load = Counter(); tot = Counter()
    T = events[-1][0] + 1 if events else 1
    def mem_at(p, t): return last[p][0] if p in last and t - last[p][1] <= S.MEM_H else None
    def resolve(cell, p, t, truth, first):
        mem = mem_at(p, t)
        q = min(3, 4 * t // T)
        if opts["mode"] in ("hybrid", "implicit"):
            post = C.implicit(cell, mem)
            if post is not None:
                f = form(post, tau_imp, True)
                if f:
                    grain, Sset = f
                    if truth in Sset: out["right"] += WORTH[grain]; out["right_" + grain] += 1
                    else: out["wrong"] += 1
                    out["implicit"] += 1
                    C.settle_ai_only(cell, mem, post)
                    if grain == "exact": last[p] = (max(post, key=post.get), t)
                    return True
            if opts["mode"] == "implicit": return False
        if first: load[q] += 1                         # escalated to validators
        post = C.evidence(cell, mem)
        f = form(post, C.tau, True)
        if not f: return False
        grain, Sset = f
        if truth in Sset: out["right"] += WORTH[grain]; out["right_" + grain] += 1
        else: out["wrong"] += 1
        C.settle(cell, mem, post)
        if grain == "exact": last[p] = (max(post, key=post.get), t)
        return True
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            still = []
            for t0, cell, p0, tr in opened:
                if resolve(cell, p0, t0, tr, False): out["late"] += 1
                elif t - t0 < A.OPEN_H: still.append((t0, cell, p0, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1; tot[min(3, 4 * t // T)] += 1
            if not resolve(cell, p, t, truth, True): opened.append((t, cell, p, truth))
        C.observe(cell)
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    def St(i): c = C.conf(i); return math.log(c[0] / c[2])
    hon = [St(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [St(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "implicit")}
    res["auc"] = auc
    res["load"] = [load[q] / max(1, tot[q]) for q in range(4)]
    if detail:
        el = defaultdict(list)
        for a, k in kinds.items(): el[k].append(C.earned(a) >= opts["elig"])
        res["eligible_share"] = {k: round(sum(v) / len(v), 2) for k, v in el.items()}
    return res

ARMS = {
    "validators on everything (evidence only)": dict(FULL, mode="validators"),
    "implicit only, everyone counts (AI only)": dict(FULL, mode="implicit", elig=-1.0),
    "hybrid, everyone counts": dict(FULL, mode="hybrid", elig=-1.0),
    "HYBRID, earned standing gate": dict(FULL, mode="hybrid"),
}

def job(args):
    arm, s, i = args
    nm, a = SUITE[i]
    return arm, i, run(ARMS[arm], K.make(s, a, "critical"), seed=s)

def attack_fit(args):
    a, seeds = args
    rs = [run(ARMS["HYBRID, earned standing gate"], K.make(s, a, "critical"), seed=s) for s in seeds]
    return sum(r["wrong"] for r in rs) / len(rs) + 0.1 * sum(r["stuck"] for r in rs) / len(rs) + 0.05 * sum(r["load"][3] for r in rs) / len(rs)

def evolve_attackers(R, pop_n=16, gens=10):
    rng = dict(coevo.A_RANGES, farm=(0, 12), signed=(0.0, 1.0))
    def rand(): return {k: R.uniform(*r) for k, r in rng.items()}
    def mut(a):
        b = dict(a)
        for k, (lo, hi) in rng.items():
            if R.random() < 0.3: b[k] = min(hi, max(lo, b[k] + R.gauss(0, (hi - lo) * 0.2)))
        return b
    pop = [rand() for _ in range(pop_n - 1)] + [dict(K.FARM_ATTACK)]
    with Pool(4) as pool:
        for g in range(gens):
            seeds = [R.getrandbits(48) for _ in range(2)]
            fs = pool.map(attack_fit, [(a, seeds) for a in pop])
            ranked = [a for _, a in sorted(zip(fs, pop), key=lambda x: -x[0])]
            print(f"  gen {g}: best attacker fitness {max(fs):.3f}", flush=True)
            nxt = [dict(a) for a in ranked[:4]]
            while len(nxt) < pop_n: nxt.append(mut(R.choice(ranked[:8])))
            pop = nxt
    return ranked[0]

SUITE = K.suite() + [("wash every 48 h", dict(topo.suite()[3], farm=0, signed=0, wash=48, truephoto=1.0, n=6))]

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    print("### attackers evolving against the hybrid (they may also try to flood validators)", flush=True)
    best = evolve_attackers(R)
    print("  adaptive attacker:", coevo.show_att(best), f"farm {round(best['farm'])} of 40, signed {best['signed']:.0%}")
    SUITE.append(("adaptive (vs hybrid)", best))
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    with Pool(4) as pool:
        res = pool.map(job, [(arm, s, i) for arm in ARMS for i in range(len(SUITE)) for s in test])
    k = len(test)
    print(f"\n{'':42} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5} {'implicit':>8}  validator load by quarter of the run")
    for arm in ARMS:
        rs = [r for a, j, r in res if a == arm]
        per = [(sum(r["right"] for r in rs2) / k, sum(r["wrong"] for r in rs2) / k) for rs2 in ([r for a, j, r in res if a == arm and j == i] for i in range(len(SUITE)))]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        load = [sum(r["load"][q] for r in rs) / len(rs) for q in range(4)]
        print(f"{arm:42} {m('right'):6.2f} {m('wrong'):6.3f} {max(w for _, w in per):6.3f} {m('stuck'):6.2f} {m('auc'):5.2f} {m('implicit'):8.2f}  "
              + " -> ".join(f"{x:.0%}" for x in load))
    print("\n### right / wrong per scenario")
    print(f"{'':42} " + "  ".join(f"{nm[:12]:>12}" for nm, _ in SUITE))
    for arm in ARMS:
        cells = []
        for i in range(len(SUITE)):
            rs = [r for a, j, r in res if a == arm and j == i]
            cells.append(f"{sum(r['right'] for r in rs) / k:.2f}/{sum(r['wrong'] for r in rs) / k:.3f}")
        print(f"{arm:42} " + "  ".join(c.rjust(12) for c in cells))
    print("\n### who could form implicit consensus by the end (hybrid, one fresh world)")
    for nm, a in SUITE:
        r = run(ARMS["HYBRID, earned standing gate"], K.make(test[0], a, "critical"), seed=test[0], detail=True)
        print(f"  {nm[:24]:24} {r['eligible_share']}")
    json.dump({"adaptive": best}, open("hybrid-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
