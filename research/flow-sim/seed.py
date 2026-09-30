"""
The seed: six principles, an empty graph, and nothing tuned offline.

  1 everything is an agent; every action is a signal
  2 a witness counts as much as its evidence is real        (provenance agent, learned from population structure)
  3 a witness counts as much as it is independent          (bonds: shared presence AND shared error beyond chance)
  4 truth is the free-energy minimum; it forms at the finest grain whose mass passes the stakes threshold
  5 learn only from signals an attacker cannot author
  6 nothing is thrown away (open cells)

Nothing is tuned: every constant is learned by the network or derived.
  - forgetting: each agent has a fast and a slow memory of its record; they are weighted by how well each has
    recently predicted the agent (Bayesian model averaging). A turned account switches to fast memory by itself.
  - prior for newcomers: the population's own reliability, by empirical Bayes (method of moments).
  - formation threshold: derived from stakes. Wrong costs lam right, so form when P > lam / (1 + lam).
  - memory agent: a place's last settled truth is a witness. Its learned confusion is how persistent the sky is.
"""
import math, random, time, json, sys
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo, agents as A
from agents import VALS, D, N1, NF, SI, STATES, VALIDATORS, form, WORTH, HOSTILE, add_agents
from emerge import NAMES

FAST, SLOW, EVID = 0.03, 0.0005, 0.02   # timescales of the two memories; evidence between them fades like fast memory
STAKES = 10.0
MEM_H = 3

class Seed:
    def __init__(self, opts):
        self.o = opts
        self.c = {"f": defaultdict(lambda: [0.0, 0.0, 0.0]), "s": defaultdict(lambda: [0.0, 0.0, 0.0])}
        self.ev = defaultdict(float)                              # log evidence fast - slow, per agent
        self.n = defaultdict(float); self.nij = defaultdict(float); self.N = 0.0
        self.ne = defaultdict(float); self.se = defaultdict(float); self.mij = defaultdict(float); self.wij = defaultdict(float)
        self.pv = defaultdict(lambda: [0.0, 0.0]); self._rho = None; self._cc = {}; self._ac = {}
        self.prior = (1.0, 1.0, 1.0)
        st = opts.get("stakes", STAKES)
        self.tau = st / (1 + st) if opts.get("derived_tau", True) else opts["tau"]

    # ---------------- time
    def fade(self, hour):
        self._cc = {}; self._ac = {}
        for k, lam in (("f", FAST), ("s", SLOW)):
            if k == "f" and not self.o["timescales"]: continue
            for v in self.c[k].values():
                for i in range(3): v[i] *= 1 - lam
        for k in self.ev: self.ev[k] *= 1 - EVID
        for d in (self.n, self.nij, self.ne, self.se, self.mij, self.wij):
            for k in d: d[k] *= 1 - SLOW
        self.N *= 1 - SLOW
        if hour % 24 == 0 and self.o["eb_prior"]: self.learn_prior()

    def learn_prior(self):
        recs = [v for v in self.c["s"].values() if sum(v) >= 5]
        if len(recs) < 5: return
        shares = [[x / sum(v) for x in v] for v in recs]
        m = [sum(s[i] for s in shares) / len(shares) for i in range(3)]
        var = sum((s[0] - m[0]) ** 2 for s in shares) / len(shares)
        strength = min(30.0, max(1.0, m[0] * (1 - m[0]) / max(var, 1e-4) - 1))
        self.prior = tuple(strength * x + 1e-3 for x in m)

    # ---------------- bonds: shared presence and shared error, beyond chance
    def a(self, i, j):
        if i == j: return 1.0
        key = (i, j) if i < j else (j, i)
        if key in self._ac: return self._ac[key]
        x = 0.0
        nij = self.nij.get(key, 0.0)
        if nij >= 1:
            pmi = math.log((nij + 0.5) * (self.N + 1) / ((self.n[i] + 1) * (self.n[j] + 1)))
            x += max(0.0, pmi) * nij / (nij + 3)
        if self.o["error_bonds"]:
            m, w = self.mij.get(key, 0.0), self.wij.get(key, 0.0)
            if m >= 1 and self.ne[i] > 0 and self.ne[j] > 0:
                exp = m * (self.se[i] / self.ne[i]) * (self.se[j] / self.ne[j])
                pmi = math.log((w + 0.05) / (exp + 0.05))
                x += max(0.0, pmi) * w / (w + 1)
        self._ac[key] = r = 1 - math.exp(-x)
        return r

    # ---------------- standing: two memories, weighted by recent predictive success
    def _shares(self, v):
        p = self.prior
        e, nr, f = v[0] + p[0], v[1] + p[1], v[2] + p[2]; z = e + nr + f
        return (e / z, nr / z, f / z)

    def wfast(self, i):
        return 1 / (1 + math.exp(-self.ev[i])) if self.o["timescales"] else 0.0

    def conf(self, i):
        if i in self._cc: return self._cc[i]
        s = self._shares(self.c["s"][i])
        if self.o["timescales"]:
            f = self._shares(self.c["f"][i]); w = self.wfast(i)
            s = tuple(w * f[k] + (1 - w) * s[k] for k in range(3))
        self._cc[i] = s
        return s

    lik = A.Complex.lik
    ordinal = True

    # ---------------- provenance agent (as in agents.py)
    rho = A.Complex.rho
    def realness(self, aid, passed):
        rr, rf, n_obs = self.rho()
        if n_obs < 4 or rr - rf < 0.05: return 1.0
        pi = (self.pv[aid][0] + 1) / (self.pv[aid][1] + 2)
        q = min(0.98, max(0.02, (pi - rf) / (rr - rf)))
        lr, lf = (rr, rf) if passed else (1 - rr, 1 - rf)
        return q * lr / (q * lr + (1 - q) * lf)

    # ---------------- the section
    def witnesses(self, cell, mem):
        """(agent, reading, realness, n readings by this agent in the cell)"""
        reps, photos, (vid, vreads) = cell
        out = []
        n_ai = sum(1 for _, _, x in photos if x is not None) or 1
        n_v = sum(1 for x in vreads if x is not None) or 1
        for (aid, kind, said, *_), (_, passed, ai_read), vr in zip(reps, photos, vreads):
            real = self.realness(aid, passed); sky = 1.0 if ai_read is not None else 0.05
            out.append((aid, said, real * sky, 1))
            if ai_read is not None: out.append(("ai", ai_read, real, n_ai))
            if vr is not None: out.append((vid, vr, real * sky, n_v))
        if mem is not None and self.o["memory"]: out.append(("mem", mem, 1.0, 1))
        return out

    def section(self, cell, mem):
        W = self.witnesses(cell, mem)
        agents = list({w[0] for w in W})
        L = {u: 0.0 for u in VALS}
        for aid, said, r, k in W:
            mass = k * sum(self.a(aid, j) for j in agents)
            lk = self.lik(said, self.conf(aid))
            for u in VALS: L[u] += math.log(r * lk[u] + (1 - r) / len(VALS)) / mass
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def observe(self, cell):
        reps, photos, (vid, _) = cell
        ids = [r[0] for r in reps] + [vid]
        self.N += 1
        for i in ids: self.n[i] += 1
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                self.nij[tuple(sorted((ids[x], ids[y])))] += 1
        for o, passed, _ in photos: self.pv[o][0] += passed; self.pv[o][1] += 1
        self._rho = None; self._ac = {}

    def settle(self, cell, mem, post):
        W = self.witnesses(cell, mem)
        err = defaultdict(list)
        for aid, said, r, k in W:
            e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
            obs = (e, nr, max(0.0, 1 - e - nr))
            if self.o["timescales"]:   # which memory predicted this better?
                pf, ps = self._shares(self.c["f"][aid]), self._shares(self.c["s"][aid])
                self.ev[aid] += sum(obs[c] * (math.log(pf[c]) - math.log(ps[c])) for c in range(3)) * r / k
            for mem_k in ("f", "s"):
                v = self.c[mem_k][aid]
                for c in range(3): v[c] += obs[c] * r / k
            err[aid].append((1 - e) * r)
        E = {a: sum(v) / len(v) for a, v in err.items()}
        for a, e in E.items(): self.ne[a] += 1; self.se[a] += e
        ks = list(E)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = tuple(sorted((ks[x], ks[y])))
                self.mij[key] += 1; self.wij[key] += E[ks[x]] * E[ks[y]]
        self._cc = {}; self._ac = {}

def run(opts, events, detail=False):
    C = Seed(opts)
    out = Counter(); last_t = -1; kinds = {}; opened = []; last = {}
    def mem_at(p, t):
        if p in last and t - last[p][1] <= MEM_H: return last[p][0]
        return None
    def resolve(cell, p, t, truth):
        mem = mem_at(p, t)
        post = C.section(cell, mem)
        f = form(post, C.tau, True)
        if not f: return False
        grain, S = f
        if truth in S: out["right"] += WORTH[grain]; out["right_" + grain] += 1
        else: out["wrong"] += 1
        C.settle(cell, mem, post)
        if grain == "exact": last[p] = (max(post, key=post.get), t)
        return True
    for t, p, truth, fake, reps, u, photos, val in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            still = []
            for t0, cell, p0, tr in opened:
                if resolve(cell, p0, t0, tr): out["late"] += 1
                elif t - t0 < A.OPEN_H: still.append((t0, cell, p0, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, photos, val)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, p, t, truth): opened.append((t, cell, p, truth))
        C.observe(cell)
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    def S(i): c = C.conf(i); return math.log(c[0] / c[2])
    hon = [S(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [S(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "late", "right_exact", "right_band", "right_pair")}
    res["auc"] = auc
    if detail:
        tiers = defaultdict(list); fast = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(S(a)); fast[k].append(C.wfast(a))
        res["observers"] = {k: round(sum(v) / len(v), 2) for k, v in tiers.items()}
        res["fast_memory"] = {k: round(sum(v) / len(v), 2) for k, v in fast.items()}
        res["validators"] = {v[2:]: round(S(v), 2) for v in VALIDATORS}
        res["ai"] = round(S("ai"), 2)
        res["memory_agent"] = [round(x, 2) for x in C.conf("mem")]
        res["prior"] = [round(x, 2) for x in C.prior]
        rr, rf, _ = C.rho(); res["provenance"] = (round(rr, 2), round(rf, 2))
        # strongest bonds to each validator: which kinds are they bound to?
        vb = {}
        for v in VALIDATORS:
            b = defaultdict(list)
            for a, k in kinds.items(): b[k].append(C.a(v, a))
            vb[v[2:]] = {k: round(max(x), 2) for k, x in b.items() if max(x) > 0.2}
        res["validator_bonds"] = vb
    return res

FULL = {"timescales": True, "eb_prior": True, "error_bonds": True, "memory": True, "derived_tau": True}
ARMS = {
    "seed (all six + three)": FULL,
    "  without error bonds": dict(FULL, error_bonds=False),
    "  without two memories": dict(FULL, timescales=False),
    "  without learned prior": dict(FULL, eb_prior=False),
    "  without memory agent": dict(FULL, memory=False),
}

def job(args):
    name, opts, s, a = args
    return name, run(opts, add_agents(coevo.make_world(s, a), s))

def champion_job(args):
    P, s, a = args
    return A.run(P, add_agents(coevo.make_world(s, a), s), True, True)

if __name__ == "__main__":
    t0 = time.time()
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    suite = [(nm, a) for nm, a in zip(NAMES, topo.suite()) if nm not in ("cabal 2", "cabal 3")]
    champ = json.load(open("agents-result.json"))["best"]["+ both"]
    with Pool(4) as pool:
        cres = pool.map(champion_job, [(champ, s, a) for _, a in suite for s in test])
        jobs = [(n, o, s, a) for n, o in ARMS.items() for _, a in suite for s in test]
        res = pool.map(job, jobs)
    k = len(test); ns = len(suite)
    def summarise(rs):
        agg = {x: sum(r[x] for r in rs) / len(rs) for x in ("right", "wrong", "stuck", "late", "auc", "right_pair", "right_band")}
        agg["worst"] = max(r["wrong"] for r in rs)
        agg["per"] = [(sum(r["right"] for r in rs[i * k:(i + 1) * k]) / k, sum(r["wrong"] for r in rs[i * k:(i + 1) * k]) / k) for i in range(ns)]
        return agg
    table = {"evolved champion (offline)": summarise(cres)}
    for n in ARMS: table[n] = summarise([r for nm, r in res if nm == n])
    print("### fresh worlds, full attack suite; seed arms have NO offline tuning")
    print(f"{'':28} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'late':>5} {'AUC':>5}   " + "  ".join(f"{nm.split()[0][:8]:>13}" for nm, _ in suite))
    for n, r in table.items():
        print(f"{n:28} {r['right']:6.2f} {r['wrong']:6.3f} {r['worst']:6.3f} {r['stuck']:6.2f} {r['late']:5.2f} {r['auc']:5.2f}   "
              + "  ".join(f"{a:.2f}/{b:.3f}".rjust(13) for a, b in r["per"]))
    print("\n### what the seed learned by itself (one fresh world per scenario)")
    for nm, a in suite:
        r = run(FULL, add_agents(coevo.make_world(test[0], a), test[0]), detail=True)
        print(f"\n[{nm}] right {r['right']:.2f} wrong {r['wrong']:.3f}")
        print("  observers standing:", r["observers"])
        print("  weight on fast memory:", r["fast_memory"])
        print("  validators:", r["validators"], " AI", r["ai"])
        print("  validator bonds (>0.2):", r["validator_bonds"])
        print("  memory agent confusion (exact, near, far):", r["memory_agent"], " learned prior:", r["prior"], " provenance:", r["provenance"])
    json.dump(table, open("seed-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
