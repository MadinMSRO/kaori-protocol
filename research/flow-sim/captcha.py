"""
Captcha-style validation, with two lanes, on the Kaori compile flow.

Validators are a pool of people doing micro-tasks. Each evidence item goes to 3 random validators, stripped of
hex and TruthKey, with a provenance badge instead of raw metadata. Known-answer items (drawn from already
compiled truths) are mixed in. Pool: diligent, lazy, and a farm. The farm is paid by the attacker to answer the
attacker's value whenever an item carries the attacker's signature (a recognisable object in the frame).
Otherwise it answers honestly.

Lanes:
  critical  evidence assessed by the AI and human validators
  normal    evidence assessed by the AI only. The AI has a systematic bias: it reads scattered as broken 30% of
            the time. An optional audit sends a small random share of items to the human pool.

Topology: bonds from shared presence and shared error (farms should knot); the learned prior; the stakes
threshold; the memory agent; open cells; provenance learned from population structure. Compile: the evidence
must pass the threshold and a standing-weighted majority of observers must agree. Afterwards every agent that
took part gets a signal.
"""
import math, random, time, json, sys
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo, seed as S, flow7 as F, agents as A
from agents import VALS, D, SI, STATES, form, WORTH, HOSTILE, read
from emerge import NAMES

K_PER_ITEM = 3

def pool_of(farm):
    return [f"v:dil{i}" for i in range(40 - 6 - farm)] + [f"v:lazy{i}" for i in range(6)] + [f"v:farm{i}" for i in range(farm)]

def ai_read(R, v):
    if v[0] == "scattered" and R.random() < 0.3: v = ("broken", v[1])      # systematic bias
    return read(R, v, 0.8, 0.85)

def v_read(R, vid, content, signed, fake):
    if content is None: return None
    if vid.startswith("v:farm") and signed: return fake
    if vid.startswith("v:lazy"): return read(R, content, 0.5, 0.6)
    return read(R, content, 0.9, 0.9)

def make(seed, att, lane="critical", audit=0.0):
    farm = int(round(att.get("farm", 0))); signed_rate = att.get("signed", 1.0)
    events = coevo.make_world(seed, att)
    R = random.Random(seed ^ 0xCA97)
    POOL = pool_of(farm)
    out = []
    for t, p, truth, fake, reps, u in events:
        items = []
        for aid, kind, said, shows, rel in reps:
            content = None if shows == "junk" else (truth if shows == "truth" else fake)
            passed = R.random() < (0.9 if content is None else 0.95 if shows == "truth" else 0.15)
            attack = kind in ("adv", "stolen") and said == fake
            signed = attack and R.random() < signed_rate
            reads = []
            if content is not None: reads.append(("ai", ai_read(R, content)))
            human = lane == "critical" or R.random() < audit
            if human and content is not None:
                for vid in R.sample(POOL, K_PER_ITEM): reads.append((vid, v_read(R, vid, content, signed, fake)))
            items.append((aid, said, passed, content is not None, reads))
        out.append((t, p, truth, fake, reps, u, items))
    return out, POOL

class Captcha(F.Flow7):
    def cell_items(self, cell):
        reps, items = cell
        out = []
        for aid, said, passed, sky, reads in items:
            out.append((aid, said, self.realness(aid, passed) * (1.0 if sky else 0.05), reads))
        return out

    def evidence(self, cell, mem):
        its = self.cell_items(cell)
        owners = [aid for aid, _, _, reads in its if reads]
        L = {u: 0.0 for u in VALS}
        for aid, said, real, reads in its:
            if not reads: continue
            readers = [r for r, _ in reads]
            ll = {u: 0.0 for u in VALS}
            for r, x in reads:
                if x is None: continue
                lk = self.lik(x, self.conf(r))
                m = sum(self.a(r, o) for o in readers)                   # bonded readers of one item share a vote
                for u in VALS: ll[u] += math.log(lk[u]) / m
            mx = max(ll.values()); pl = {u: math.exp(v - mx) for u, v in ll.items()}
            base = sum(pl.values()) / len(pl)
            mass = sum(self.a(aid, j) for j in owners)
            for u in VALS: L[u] += math.log(real * pl[u] + (1 - real) * base) / mass
        if mem is not None and self.o["memory"]:
            lk = self.lik(mem, self.conf("mem"))
            for u in VALS: L[u] += math.log(lk[u])
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def agreement(self, cell, S_set):
        its = self.cell_items(cell)
        ids = [i[0] for i in its]
        yes = tot = 0.0
        for aid, said, real, reads in its:
            c = self.conf(aid)
            w = real * (c[0] + 0.5 * c[1]) / sum(self.a(aid, j) for j in ids)
            tot += w; yes += w * (said in S_set)
        return yes / tot if tot > 0 else 0.0

    def learn(self, aid, said, post, w, err=None):
        e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
        obs = (e, nr, max(0.0, 1 - e - nr))
        v = self.c["s"][aid]
        for c in range(3): v[c] += obs[c] * w
        if err is not None: err[aid].append((1 - e) * w)

    def settle(self, cell, mem, post):
        err = defaultdict(list)
        for aid, said, real, reads in self.cell_items(cell):
            self.learn(aid, said, post, real, err)
            for r, x in reads:
                if x is not None: self.learn(r, x, post, real, err)
        if mem is not None and self.o["memory"]: self.learn("mem", mem, post, 1.0, err)
        E = {a: sum(v) / len(v) for a, v in err.items()}
        for a, e in E.items(): self.ne[a] += 1; self.se[a] += e
        ks = list(E)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = tuple(sorted((ks[x], ks[y])))
                self.mij[key] += 1; self.wij[key] += E[ks[x]] * E[ks[y]]
        self._cc = {}; self._ac = {}

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

FULL = dict(S.FULL, timescales=False, gold=True, observers_gate=True)

def run(opts, world, detail=False, seed=0):
    events, POOL = world
    C = Captcha(opts)
    humans = any(r.startswith("v:") for ev in events[:200] for it in ev[6] for r, _ in it[4])
    RG = random.Random(seed ^ 0x601D)
    out = Counter(); last_t = -1; kinds = {}; opened = []; last = {}; gold = []
    def mem_at(p, t): return last[p][0] if p in last and t - last[p][1] <= S.MEM_H else None
    def resolve(cell, p, t, truth):
        mem = mem_at(p, t)
        post = C.evidence(cell, mem)
        f = form(post, C.tau, True)
        if not f: return False
        grain, Sset = f
        if opts["observers_gate"] and C.agreement(cell, Sset) <= 0.5: return False
        if truth in Sset: out["right"] += WORTH[grain]; out["right_" + grain] += 1
        else: out["wrong"] += 1
        C.settle(cell, mem, post)
        if grain == "exact":
            last[p] = (max(post, key=post.get), t)
            gold.append((truth, post))                     # a compiled item, reused later as a known answer
        return True
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            if opts["gold"] and gold and humans:
                for vid in POOL:                           # each validator gets a known-answer item now and then
                    if RG.random() < 0.3:
                        content, post = RG.choice(gold[-300:])
                        C.learn(vid, v_read(RG, vid, content, False, None), post, 1.0)
                C._cc = {}
            still = []
            for t0, cell, p0, tr in opened:
                if resolve(cell, p0, t0, tr): out["late"] += 1
                elif t - t0 < A.OPEN_H: still.append((t0, cell, p0, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, p, t, truth): opened.append((t, cell, p, truth))
        C.observe(cell)
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    def St(i): c = C.conf(i); return math.log(c[0] / c[2])
    hon = [St(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [St(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "late")}
    res["auc"] = auc
    if detail:
        tiers = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(St(a))
        for v in POOL: tiers[v.rstrip("0123456789")].append(St(v))
        res["standing"] = {k: round(sum(v) / len(v), 2) for k, v in tiers.items()}
        res["ai"] = round(St("ai"), 2)
        farm = [v for v in POOL if v.startswith("v:farm")]; dil = [v for v in POOL if v.startswith("v:dil")][:12]
        pair = lambda g: [C.a(x, y) for i, x in enumerate(g) for y in g[i + 1:]]
        res["bonds"] = {"farm-farm": round(sum(pair(farm)) / max(1, len(pair(farm))), 2),
                        "diligent-diligent": round(sum(pair(dil)) / max(1, len(pair(dil))), 2)}
    return res

# ---------------------------------------------------------------- scenarios and arena
FARM_ATTACK = {"n": 5, "active": .7, "attack": .8, "scatter": .5, "sleep": .2, "wash": 0, "steal": 1, "truephoto": 1.0,
               "farm": 6, "signed": 1.0}

def suite():
    base = [(nm, dict(a, farm=0, signed=0)) for nm, a in zip(NAMES, topo.suite()) if nm not in ("cabal 2", "cabal 3")]
    return base + [("farm + signed real photos", FARM_ATTACK)]

ARMS = {
    "critical lane (AI + captcha humans)": ("critical", 0.0, FULL),
    "  without error bonds": ("critical", 0.0, dict(FULL, error_bonds=False)),
    "  without known-answer items": ("critical", 0.0, dict(FULL, gold=False)),
    "  without observers' agreement": ("critical", 0.0, dict(FULL, observers_gate=False)),
    "normal lane (AI only, stakes 10)": ("normal", 0.0, FULL),
    "normal lane (AI only, stakes 3)": ("normal", 0.0, dict(FULL, stakes=3.0)),
    "normal lane, stakes 3, 5% human audit": ("normal", 0.05, dict(FULL, stakes=3.0)),
}

def job(args):
    arm, s, i = args
    lane, audit, opts = ARMS[arm]
    nm, a = SUITE[i]
    return arm, i, run(opts, make(s, a, lane, audit), seed=s)

def attack_fit(args):
    a, seeds = args
    rs = [run(FULL, make(s, a, "critical"), seed=s) for s in seeds]
    return sum(r["wrong"] for r in rs) / len(rs) + 0.1 * sum(r["stuck"] for r in rs) / len(rs)

def evolve_attackers(R, pop_n=16, gens=10):
    rng = dict(coevo.A_RANGES, farm=(0, 12), signed=(0.0, 1.0))
    def rand(): return {k: R.uniform(*r) for k, r in rng.items()}
    def mut(a):
        b = dict(a)
        for k, (lo, hi) in rng.items():
            if R.random() < 0.3: b[k] = min(hi, max(lo, b[k] + R.gauss(0, (hi - lo) * 0.2)))
        return b
    pop = [rand() for _ in range(pop_n - 1)] + [dict(FARM_ATTACK)]
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

SUITE = suite()

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    print("### attackers evolving against the critical lane (incl. farm size and signed photos)", flush=True)
    best = evolve_attackers(R)
    print("  adaptive attacker:", coevo.show_att(best), f"farm {round(best['farm'])} of 40, signed {best['signed']:.0%}")
    SUITE.append(("adaptive (vs captcha)", best))
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    with Pool(4) as pool:
        res = pool.map(job, [(arm, s, i) for arm in ARMS for i in range(len(SUITE)) for s in test])
    k = len(test)
    print(f"\n{'':38} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}   " + "  ".join(f"{nm[:12]:>12}" for nm, _ in SUITE))
    for arm in ARMS:
        per = []
        for i in range(len(SUITE)):
            rs = [r for a, j, r in res if a == arm and j == i]
            per.append((sum(r["right"] for r in rs) / k, sum(r["wrong"] for r in rs) / k))
        rs = [r for a, j, r in res if a == arm]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        print(f"{arm:38} {m('right'):6.2f} {m('wrong'):6.3f} {max(w for _, w in per):6.3f} {m('stuck'):6.2f} {m('auc'):5.2f}   "
              + "  ".join(f"{a:.2f}/{w:.3f}".rjust(12) for a, w in per))
    print("\n### what the network learned (critical lane, one fresh world)")
    for nm, a in SUITE[-2:]:
        r = run(FULL, make(test[0], a, "critical"), detail=True, seed=test[0])
        print(f"[{nm}] standing {r['standing']}  AI {r['ai']}  bonds {r['bonds']}")
    r = run(dict(FULL, stakes=3.0), make(test[0], SUITE[4][1], "normal"), detail=True, seed=test[0])
    print(f"[calm, normal lane] AI standing {r['ai']} (graded by truths it compiled itself)")
    json.dump({"adaptive": best}, open("captcha-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
