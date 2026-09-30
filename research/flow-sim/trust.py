"""
Rules 3 and 4 made literal, with contested truths.

Standing (Rule 3): one global number per agent, S in [0, 1000], and the only persistent trust variable.
  Every signal moves it by a bounded, nonlinear step (Rule 5): S <- S + eta * (1000 * outcome - S).
  outcome is 1 for exact, 0.5 for one step off, 0 otherwise. Initial standing is 500 (neutral; the seed is left
  for later).
Trust (Rule 4): local to one claim. T_i = S_i x realness of i's evidence x how well i's own photo supports the
  claim (the AI's reading), divided by i's bonded mass among this TruthKey's observers.
One trust score per value: the summed T of the observers backing it. High trust outweighs.

Compile per TruthKey:
  implicit   the leading value's trust >= min_network_trust and its share of all trust >= the stakes share
             -> VERIFIED (IMPLICIT_CONSENSUS)
  escalate   otherwise captcha validators assess every item blind. Trust per value = summed S x realness of
             the readings (the AI and validators), divided by bonded mass -> VERIFIED if the share passes
  contested  still split when the window closes -> INCONCLUSIVE (a signed truth), and every observer gets a
             penalty signal
Signals after VERIFIED: observers for their claims; validators and the AI for each reading.
Bonds: shared presence and shared error beyond chance. Realness: the provenance agent (EM over pass records).
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo, seed as S, captcha as K, agents as A
from agents import VALS, D, STATES, WORTH, HOSTILE
from emerge import NAMES

S0, ETA = 500.0, 0.05
KV = len(VALS)

def weight(S):
    """Evidence a witness with standing S adds for the value it backs: log-odds of being right over chance."""
    p = min(max(S / 1000.0, 1e-3), 1 - 1e-3)
    return max(0.0, math.log(p * (KV - 1) / (1 - p)))

def dominance(ev):
    """Share of each value from summed evidence (softmax over all values; values nobody backs have 0)."""
    m = max(list(ev.values()) + [0.0])
    z = sum(math.exp(ev.get(v, 0.0) - m) for v in VALS)
    return {v: math.exp(ev.get(v, 0.0) - m) / z for v in VALS}

def grain_of(share, tau):
    """The finest grain whose trust share passes tau: exact value, band (rain open), or two adjacent bands."""
    u = max(share, key=share.get)
    if share[u] >= tau: return "exact", {u}
    band = Counter()
    for (s, r), p in share.items(): band[s] += p
    s, p = band.most_common(1)[0]
    if p >= tau: return "band", {v for v in VALS if v[0] == s}
    i = max(range(4), key=lambda i: band[STATES[i]] + band[STATES[i + 1]])
    if band[STATES[i]] + band[STATES[i + 1]] >= tau: return "pair", {v for v in VALS if v[0] in (STATES[i], STATES[i + 1])}
    return None

class Trust(S.Seed):
    def __init__(self, opts):
        super().__init__(opts)
        self.S = defaultdict(lambda: S0)

    def signal(self, aid, outcome, err=None):
        self.S[aid] += ETA * (1000.0 * outcome - self.S[aid])
        if err is not None: err[aid] = 1 - outcome

    def outcome(self, said, Sset):
        if said in Sset: return 1.0
        return 0.5 if min(D[(said, v)] for v in Sset) == 1 else 0.0

    def ai_support(self, said, reads):
        ai = [x for r, x in reads if r == "ai" and x is not None]
        if not ai: return 1.0
        return 1.0 if D[(ai[0], said)] <= 1 else 0.0 if self.S["ai"] >= 500 else 0.5

    def realness_of(self, aid, passed, sky):
        return self.realness(aid, passed) * (1.0 if sky else 0.05)

    def observer_trust(self, cell):
        reps, items = cell
        ids = [it[0] for it in items]
        tv = defaultdict(float); ev = defaultdict(float)
        for aid, said, passed, sky, reads in items:
            f = self.realness_of(aid, passed, sky) * self.ai_support(said, reads) / sum(self.a(aid, j) for j in ids)
            tv[said] += self.S[aid] * f; ev[said] += weight(self.S[aid]) * f
        return tv, ev

    def reader_trust(self, cell):
        reps, items = cell
        ev = defaultdict(float)
        for aid, said, passed, sky, reads in items:
            real = self.realness_of(aid, passed, sky)
            readers = [r for r, _ in reads]
            for r, x in reads:
                if x is None: continue
                ev[x] += weight(self.S[r]) * real / sum(self.a(r, o) for o in readers)
        return ev

    def settle_verified(self, cell, Sset, with_readers):
        reps, items = cell
        err = {}
        for aid, said, passed, sky, reads in items:
            self.signal(aid, self.outcome(said, Sset), err)
            for r, x in reads:
                if x is None or (r != "ai" and not with_readers): continue
                self.signal(r, self.outcome(x, Sset), err)
        self.bond_errors(err)

    def settle_contested(self, cell):
        reps, items = cell
        err = {}
        for aid, *_ in items: self.signal(aid, self.o["contest_outcome"] * self.S[aid] / 1000.0 if self.o["contest_outcome"] is not None else self.S[aid] / 1000.0, err)
        self.bond_errors(err)

    def bond_errors(self, err):
        for a, e in err.items(): self.ne[a] += 1; self.se[a] += e
        ks = list(err)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = tuple(sorted((ks[x], ks[y])))
                self.mij[key] += 1; self.wij[key] += err[ks[x]] * err[ks[y]]
        self._ac = {}

    def observe(self, cell):
        reps, items = cell
        ids = [r[0] for r in reps]
        self.N += 1
        for i in ids: self.n[i] += 1
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                self.nij[tuple(sorted((ids[x], ids[y])))] += 1
        for aid, said, passed, sky, reads in items: self.pv[aid][0] += passed; self.pv[aid][1] += 1
        self._rho = None; self._ac = {}

    def fade(self, hour):   # standing already forgets through its update; bonds forget slowly
        self._ac = {}
        for d in (self.n, self.nij, self.ne, self.se, self.mij, self.wij):
            for k in d: d[k] *= 1 - S.SLOW
        self.N *= 1 - S.SLOW

FULL = {"min_trust": 1500.0, "stakes_implicit": 3.0, "stakes_validated": 10.0, "contest_outcome": 0.0,
        "error_bonds": True, "memory": False, "timescales": False, "eb_prior": False, "derived_tau": True}

def run(opts, world, seed=0, detail=False):
    events, POOL = world
    C = Trust(opts)
    tau_i = opts["stakes_implicit"] / (1 + opts["stakes_implicit"])
    tau_v = opts["stakes_validated"] / (1 + opts["stakes_validated"])
    out = Counter(); last_t = -1; kinds = {}; opened = []
    T = events[-1][0] + 1 if events else 1
    load = Counter(); tot = Counter(); hon_hist = []
    def resolve(cell, t, truth, first):
        tv, ev = C.observer_trust(cell)
        if tv:
            g = grain_of(dominance(ev), tau_i)
            if g and sum(tv.get(v, 0.0) for v in g[1]) >= opts["min_trust"]:
                grain, Sset = g
                out["right" if truth in Sset else "wrong"] += WORTH[grain] if truth in Sset else 1
                out["implicit"] += 1
                if truth not in Sset: out["wrong_implicit"] += 1; out["wi_q%d" % min(3, 4 * t // T)] += 1
                C.settle_verified(cell, Sset, with_readers=False)
                return True
        if first: load[min(3, 4 * t // T)] += 1
        rv = C.reader_trust(cell)
        if rv:
            g = grain_of(dominance(rv), tau_v)
            if g:
                grain, Sset = g
                out["right" if truth in Sset else "wrong"] += WORTH[grain] if truth in Sset else 1
                C.settle_verified(cell, Sset, with_readers=True)
                return True
        return False
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            still = []
            for t0, cell, tr in opened:
                if resolve(cell, t0, tr, False): pass
                elif t - t0 < A.OPEN_H: still.append((t0, cell, tr))
                else:
                    out["contested"] += 1
                    if opts["contest_outcome"] is not None: C.settle_contested(cell)
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1; tot[min(3, 4 * t // T)] += 1
            if not resolve(cell, t, truth, True): opened.append((t, cell, truth))
        C.observe(cell)
    out["contested"] += len(opened)
    E = max(1, out["eligible"])
    hon = [C.S[a] for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [C.S[a] for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "contested", "implicit", "wrong_implicit")}
    res["wrong_implicit_by_quarter"] = [out["wi_q%d" % q] for q in range(4)]
    res["auc"] = auc
    res["load"] = [load[q] / max(1, tot[q]) for q in range(4)]
    res["careful_S"] = sum(C.S[a] for a, k in kinds.items() if k == "careful") / max(1, sum(1 for k in kinds.values() if k == "careful"))
    hk = [C.S[a] for a, k in kinds.items() if k in ("adv", "stolen")]
    res["attacker_S"] = sum(hk) / len(hk) if hk else float("nan")
    if detail:
        tiers = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(C.S[a])
        for v in POOL: tiers[v.rstrip("0123456789")].append(C.S[v])
        res["standing"] = {k: round(sum(v) / len(v)) for k, v in tiers.items()}
        res["standing"]["ai"] = round(C.S["ai"])
    return res

ARMS = {
    "contest = no signal": dict(FULL, contest_outcome=None),
    "contest = mild penalty (standing x 0.5)": dict(FULL, contest_outcome=0.5),
    "contest = full penalty (standing -> 0)": dict(FULL, contest_outcome=0.0),
}
SUITE = K.suite() + [("wash every 48 h", dict(topo.suite()[3], farm=0, signed=0, wash=48, truephoto=1.0, n=6))]

def job(args):
    arm, s, i = args
    return arm, i, run(ARMS[arm], K.make(s, SUITE[i][1], "critical"), seed=s)

def attack_fit(args):
    a, seeds = args
    rs = [run(ARMS["contest = full penalty (standing -> 0)"], K.make(s, a, "critical"), seed=s) for s in seeds]
    m = lambda k: sum(r[k] for r in rs) / len(rs)
    return m("wrong") + 0.1 * m("contested") + 0.2 * (1 - m("auc"))

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

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    print("### attackers evolving against the full contest penalty (wrong truths, contests, or dragging honest standing)", flush=True)
    best = evolve_attackers(R)
    print("  adaptive attacker:", coevo.show_att(best), f"farm {round(best['farm'])} of 40, signed {best['signed']:.0%}")
    SUITE.append(("adaptive (vs contest penalty)", best))
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    with Pool(4) as pool:
        res = pool.map(job, [(arm, s, i) for arm in ARMS for i in range(len(SUITE)) for s in test])
    k = len(test)
    print(f"\n{'':42} {'right':>6} {'wrong':>6} {'worst':>6} {'contest':>7} {'implicit':>8} {'AUC':>5} {'careful S':>9} {'attacker S':>10}  validator load by quarter")
    for arm in ARMS:
        rs = [r for a, j, r in res if a == arm]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        worst = max(sum(r["wrong"] for a, j, r in res if a == arm and j == i) / k for i in range(len(SUITE)))
        att = [r["attacker_S"] for r in rs if r["attacker_S"] == r["attacker_S"]]
        load = [sum(r["load"][q] for r in rs) / len(rs) for q in range(4)]
        print(f"{arm:42} {m('right'):6.2f} {m('wrong'):6.3f} {worst:6.3f} {m('contested'):7.2f} {m('implicit'):8.2f} {m('auc'):5.2f} {m('careful_S'):9.0f} {sum(att) / len(att):10.0f}  "
              + " -> ".join(f"{x:.0%}" for x in load))
    print("\n### right / wrong / contested per scenario")
    print(f"{'':42} " + "  ".join(f"{nm[:16]:>16}" for nm, _ in SUITE))
    for arm in ARMS:
        cells = []
        for i in range(len(SUITE)):
            rs = [r for a, j, r in res if a == arm and j == i]
            cells.append(f"{sum(r['right'] for r in rs) / k:.2f}/{sum(r['wrong'] for r in rs) / k:.3f}/{sum(r['contested'] for r in rs) / k:.2f}")
        print(f"{arm:42} " + "  ".join(c.rjust(16) for c in cells))
    print("\n### standing by type at the end (full contest penalty, one fresh world)")
    for nm, a in SUITE:
        r = run(ARMS["contest = full penalty (standing -> 0)"], K.make(test[0], a, "critical"), seed=test[0], detail=True)
        print(f"  {nm[:24]:24} {r['standing']}")
    json.dump({"adaptive": best}, open("trust-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
