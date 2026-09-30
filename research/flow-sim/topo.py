"""
Topology-first Kaori Flow. No law menu: a topology fixes how witnesses relate to the truth, and every law
is derived from one principle - minimise the free energy F = E - T S of that structure.

Common model: a TruthKey e holds a hidden value y_e. Witness i reports x_i with reliability theta_i;
P(x_i = y) = theta_i r_i (r_i: the AI's relevance for i's photo), otherwise one of the K-1 wrong values.
theta_i has a Beta(a0, b0) prior ("innocent until proven otherwise"), and memory fades at rate lam
(the entropy term: old evidence is forgotten because the world and people change).

Derived, the same for every topology:
  weight     w_i = log[(theta r)(K-1) / (1 - theta r)]      the log-odds of being right
  consensus  P(y = v) = softmax_v( sum_i w_i [x_i = v] + log prior(v) )
  formation  a truth forms when P(y = claim) >= tau        (disagreement and few witnesses keep P low:
                                                             Jeans-like without being written down)
  standing   theta_i <- (a0 + sum P(y = x_i)) / (a0 + b0 + n_i), soft EM counts, fading at lam

What each topology adds:
  bipartite    agents <-> TruthKeys; witnesses independent given the truth (Dawid-Skene)
  graph        agents <-> agents only; trust is the stationary flow of agreement (EigenTrust, no seeds);
               no truth nodes, so consensus is a trust-weighted plurality
  hypergraph   each TruthKey is a hyperedge; witness errors can be correlated, learned from the incidence
               history (co-presence beyond chance, co-error); weights = inverse correlation x log-odds
               (generalised least squares), so screening is derived
  simplicial   groups that co-witness far beyond chance become filled simplices and count as one witness
  multiplex    hypergraph + TruthKey <-> TruthKey in time: the last verified truth at a place is a prior,
               with persistence learned from the verified record
"""
import math, random, sys, json, time
from collections import Counter, defaultdict
from multiprocessing import Pool
import numpy as np
import coevo

TOPOLOGIES = ["graph", "bipartite", "hypergraph", "simplicial", "multiplex"]
K = 10  # 5 cover bands x raining
RANGES = {"a0": (0.5, 8.0), "b0": (0.5, 8.0), "lam": (0.0, 0.03), "tau": (0.6, 0.995),
          "dep": (0.0, 3.0), "g": (0.3, 0.95)}
DEFAULT = {"a0": 3.0, "b0": 3.0, "lam": 0.005, "tau": 0.9, "dep": 1.0, "g": 0.6}

def logodds(p):
    p = min(0.999, max(1e-4, p))
    return math.log(p * (K - 1) / (1 - p))

class Field:
    def __init__(self, topo, P):
        self.topo, self.P = topo, P
        self.A, self.B = defaultdict(float), defaultdict(float)
        self.co_n, self.co_err, self.seen, self.err = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        self.agree = defaultdict(float)            # graph topology: agreement edges
        self.trust = {}                            # graph topology: stationary flow
        self.last = {}                             # multiplex: place -> (hour, value)
        self.persist = [1.0, 1.0]                  # multiplex: Beta counts that the value persisted hour to hour
        self.groups = {}                           # simplicial: agent -> group id
    def theta(self, a):
        return (self.A[a] + self.P["a0"]) / (self.A[a] + self.B[a] + self.P["a0"] + self.P["b0"])
    def fade(self):
        k = 1 - self.P["lam"]
        for d in (self.A, self.B, self.agree):
            for key in d: d[key] *= k
    # ---- graph topology: trust as the stationary distribution of agreement flow (power iteration)
    def refresh_trust(self, agents):
        agents = list(agents)
        if not agents: return
        idx = {a: i for i, a in enumerate(agents)}
        M = np.full((len(agents), len(agents)), 1e-3)
        for (a, b), v in self.agree.items():
            if a in idx and b in idx and v > 0: M[idx[b], idx[a]] += v
        M /= M.sum(axis=0, keepdims=True)
        t = np.full(len(agents), 1 / len(agents))
        for _ in range(30): t = 0.85 * M @ t + 0.15 / len(agents)
        self.trust = {a: float(t[idx[a]]) * len(agents) for a in agents}
    # ---- hypergraph: dependence between two witnesses, learned from the incidence history
    def dependence(self, a, b):
        pres = max(0.0, (self.co_n[(a, b)] + 0.25) / (self.seen[a] + 1) - 0.25) / 0.75   # co-presence beyond chance
        cerr = self.co_err[(a, b)] / (min(self.err[a], self.err[b]) + 1)                 # errors made together
        return min(0.95, self.P["dep"] * (0.5 * pres + 0.5 * cerr))
    def compile(self, place, t, reps):
        ids = [r[0] for r in reps]
        vals = [r[2] for r in reps]
        rel = [r[4] for r in reps]
        if self.topo == "graph":
            w = np.array([self.trust.get(a, 1.0) * r for a, r in zip(ids, rel)])
            tally = defaultdict(float)
            for v, wi in zip(vals, w): tally[v] += wi
            claim = max(tally, key=lambda v: (tally[v], v))
            post = {v: tally[v] / (sum(tally.values()) or 1e-12) for v in tally}
            return claim, post
        w0 = np.array([logodds(self.theta(a) * r) for a, r in zip(ids, rel)])
        if self.topo == "simplicial":
            # collapse each filled simplex present here into one witness (its members' majority, its mean weight)
            gid = [self.groups.get(a, a) for a in ids]
            by = defaultdict(list)
            for i, gg in enumerate(gid): by[gg].append(i)
            w = np.zeros(len(ids))
            for gg, members in by.items():
                if len(members) == 1: w[members[0]] = w0[members[0]]; continue
                share = w0[members].mean() / len(members)       # one witness' worth, split across members
                for i in members: w[i] = share
        elif self.topo in ("hypergraph", "multiplex"):
            n = len(ids)
            C = np.eye(n)
            for i in range(n):
                for j in range(i + 1, n):
                    d = self.dependence(ids[i], ids[j]); C[i, j] = C[j, i] = d
            try:
                inv1 = np.linalg.solve(C + 1e-6 * np.eye(n), np.ones(n))
            except np.linalg.LinAlgError:
                inv1 = np.ones(n)
            inv1 = np.clip(inv1, 0, None)
            share = inv1 / (inv1.max() or 1)                  # 1 for an independent witness, less when screened
            w = w0 * share
        else:
            w = w0
        L = defaultdict(float)
        for v, wi in zip(vals, w): L[v] += wi
        if self.topo == "multiplex" and place in self.last:
            th, prev = self.last[place]
            pi = self.persist[0] / sum(self.persist)
            stay = pi ** max(1, t - th)                         # persistence decays with elapsed hours
            for v in set(vals) | {prev}:
                L[v] += math.log((stay if v == prev else (1 - stay) / (K - 1)) * K + 1e-9)
        m = max(L.values())
        Z = sum(math.exp(x - m) for x in L.values()) + (K - len(L)) * math.exp(-m)  # unseen values have L = 0
        post = {v: math.exp(x - m) / Z for v, x in L.items()}
        claim = max(post, key=lambda v: (post[v], v))
        return claim, post
    def settle(self, place, t, reps, claim, post):
        ids = [r[0] for r in reps]
        for aid, _, said, _, _ in reps:
            p = post.get(said, 0.0)
            self.A[aid] += p; self.B[aid] += 1 - p
            if said != claim: self.err[aid] += 1
        for aid, _, sa, _, _ in reps:
            for bid, _, sb, _, _ in reps:
                if aid == bid: continue
                self.agree[(aid, bid)] += 1.0 if sa == sb else 0.0
                if sa != claim and sa == sb: self.co_err[(aid, bid)] += 1
        if self.topo == "multiplex":
            if place in self.last:
                th, prev = self.last[place]
                if t - th == 1: self.persist[0 if prev == claim else 1] += 1
            self.last[place] = (t, claim)
    def witness(self, reps):
        ids = [r[0] for r in reps]
        for a in ids:
            self.seen[a] += 1
            for b in ids:
                if a != b: self.co_n[(a, b)] += 1
        if self.topo == "simplicial":
            for a in ids:  # join the strongest co-presence group beyond the threshold (union of filled simplices)
                for b in ids:
                    if a < b and self.co_n[(a, b)] >= 4 and self.co_n[(a, b)] / max(1, min(self.seen[a], self.seen[b])) >= self.P["g"]:
                        ga, gb = self.groups.get(a, a), self.groups.get(b, b)
                        for x, gx in list(self.groups.items()):
                            if gx == gb: self.groups[x] = ga
                        self.groups[a] = ga; self.groups[b] = ga

def run(topo, P, events):
    F = Field(topo, P)
    out = Counter(); last_t = -1; seen_agents = {}
    for t, p, truth, fake, reps, u in events:
        if t != last_t:
            for _ in range(max(0, t - last_t)): F.fade()
            if topo == "graph" and t % 6 == 0: F.refresh_trust(seen_agents)
            last_t = t
        for aid, kind, *_ in reps: seen_agents[aid] = kind
        if len(reps) < 3: continue
        out["eligible"] += 1
        claim, post = F.compile(p, t, reps)
        F.witness(reps)
        shown = Counter(truth if s == "truth" else fake for *_, s, _ in reps if s != "junk")
        human = (shown.most_common(1)[0][0] == claim if shown else False) or u < 0.15
        ai = sum(r[4] for r in reps) / len(reps)
        formed = post[claim] >= P["tau"]
        if formed and human:
            out["right" if claim == truth else "WRONG"] += 1
            F.settle(p, t, reps, claim, post)
        else:
            out["stuck"] += 1
    E = max(1, out["eligible"])
    score = (lambda a: F.trust.get(a, 1.0)) if topo == "graph" else F.theta
    hon = [score(a) for a, k in seen_agents.items() if k in ("careful", "sloppy")]
    hos = [score(a) for a, k in seen_agents.items() if k in ("liar", "faker", "adv", "stolen")]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    return {"right": out["right"] / E, "wrong": out["WRONG"] / E, "stuck": out["stuck"] / E, "auc": auc}

# ------------------------------------------------------------------ evaluation and evolution
SUITE = None
def suite():
    global SUITE
    if SUITE is None:
        hof = json.load(open("coevo-result.json"))["hof_a"]
        SUITE = [dict(a, wash=0) for a in hof[-3:]] + [
            {"n": 3, "active": .45, "attack": 1.0, "scatter": 0, "sleep": 0, "wash": 0, "steal": 0, "truephoto": 0},
            {"n": 4, "active": .5, "attack": .3, "scatter": 1, "sleep": .6, "wash": 0, "steal": 2, "truephoto": 0},
            {"n": 6, "active": .8, "attack": .1, "scatter": 1, "sleep": .3, "wash": 0, "steal": 0, "truephoto": .5},
            {"n": 2, "active": 0.0, "attack": 0.0, "scatter": 1, "sleep": 0, "wash": 0, "steal": 0, "truephoto": 0}]
    return SUITE

def evaluate(args):
    topo, P, seeds, lam_risk = args
    rs = [run(topo, P, coevo.make_world(s, a)) for a in suite() for s in seeds]
    f = [r["right"] - lam_risk * r["wrong"] + 0.3 * r["auc"] for r in rs]
    agg = {k: sum(r[k] for r in rs) / len(rs) for k in ("right", "wrong", "stuck", "auc")}
    agg["worst_wrong"] = max(r["wrong"] for r in rs)
    agg["fit"] = 0.5 * sum(f) / len(f) + 0.5 * min(f)
    return agg

def evolve(topo, R, lam_risk=10, pop_n=16, gens=12):
    pop = [dict(DEFAULT)] + [{k: R.uniform(*r) for k, r in RANGES.items()} for _ in range(pop_n - 1)]
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48)]
            fs = pool.map(evaluate, [(topo, P, seeds, lam_risk) for P in pop])
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

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    best = {}
    for topo in TOPOLOGIES:
        best[topo] = evolve(topo, R)
        print(f"evolved {topo:11}: " + ", ".join(f"{k}={v:.3f}" for k, v in best[topo].items()), flush=True)
    test = [random.SystemRandom().getrandbits(48) for _ in range(3)]
    with Pool(4) as pool:
        res = pool.map(evaluate, [(t, best[t], test, 10) for t in TOPOLOGIES])
    print("\n### topologies on fresh worlds (costly identities, full attack suite); laws derived, only structure constants evolved")
    print(f"{'topology':12} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}")
    for t, r in zip(TOPOLOGIES, res):
        print(f"{t:12} {r['right']:6.2f} {r['wrong']:6.3f} {r['worst_wrong']:6.3f} {r['stuck']:6.2f} {r['auc']:5.2f}")
    json.dump({"best": best, "res": dict(zip(TOPOLOGIES, res))}, open("topo-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
