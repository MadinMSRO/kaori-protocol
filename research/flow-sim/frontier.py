"""
Which natural law yields the most truth at each level of safety?

For every nucleation family (how a truth is allowed to form) and every risk appetite (a wrong truth
costs 3, 10 or 30 right ones), evolve the other laws, then judge the winner on fresh worlds against the
whole attack suite with costly identities (no free re-registering). The result is a safety-yield
frontier per family.
"""
import json, random, sys, time
from multiprocessing import Pool
import coevo, evo

FAMILIES = {
    "critical nucleus": {"nucleate": "critical", "field": "none"},
    "Jeans collapse": {"nucleate": "jeans", "field": "none"},
    "bee quorum + cross-inhibition": {"nucleate": "quorum", "field": "none"},
    "Jeans + triggered formation": {"nucleate": "jeans", "field": "triggered"},
    "bee quorum + triggered": {"nucleate": "quorum", "field": "triggered"},
}
RISKS = [3, 10, 30]

hof = json.load(open("coevo-result.json"))["hof_a"]
SUITE = [dict(a, wash=0) for a in hof[-3:]] + [
    {"n": 3, "active": .45, "attack": 1.0, "scatter": 0, "sleep": 0, "wash": 0, "steal": 0, "truephoto": 0},      # ring
    {"n": 4, "active": .5, "attack": .3, "scatter": 1, "sleep": .6, "wash": 0, "steal": 2, "truephoto": 0},       # sleeper + theft
    {"n": 6, "active": .8, "attack": .1, "scatter": 1, "sleep": .3, "wash": 0, "steal": 0, "truephoto": .5},      # patient scatterers
    {"n": 2, "active": 0.0, "attack": 0.0, "scatter": 1, "sleep": 0, "wash": 0, "steal": 0, "truephoto": 0},      # calm: no attacker
]

def fit(g, seeds, lam):
    rs = [coevo.score(g, a, seeds) for a in SUITE]
    f = [r["right"] - lam * r["wrong"] - 0.5 * r["hurt"] + 0.3 * r["auc"] for r in rs]
    return 0.5 * sum(f) / len(f) + 0.5 * min(f), rs

def job(args):
    g, seeds, lam = args
    return fit(g, seeds, lam)[0]

def evolve(fixed, lam, R, pop_n=20, gens=15):
    pop = [dict(evo.random_genome(R), **fixed) for _ in range(pop_n)]
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48) for _ in range(2)]
            fs = pool.map(job, [(g, seeds, lam) for g in pop])
            ranked = [g for _, g in sorted(zip(fs, pop), key=lambda x: -x[0])]
            nxt = [dict(g) for g in ranked[:4]]
            while len(nxt) < pop_n:
                a, b = R.sample(ranked[:10], 2)
                nxt.append(dict(evo.mutate(evo.cross(a, b, R), R), **fixed))
            pop = nxt
    return ranked[0]

def judge(args):
    g, seeds = args
    rs = [coevo.score(g, a, seeds) for a in SUITE]
    n = len(rs)
    return {"right": sum(r["right"] for r in rs) / n, "wrong": sum(r["wrong"] for r in rs) / n,
            "worst_wrong": max(r["wrong"] for r in rs), "calm_right": rs[-1]["right"], "auc": sum(r["auc"] for r in rs) / n}

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    winners = []
    for name, fixed in FAMILIES.items():
        for lam in RISKS:
            g = evolve(fixed, lam, R)
            winners.append((name, lam, g))
            print(f"evolved {name:30} risk {lam:>2}: " + " ".join(str(g[k]) for k in evo.SLOTS), flush=True)
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    baseline = [("today", "-", dict(evo.TODAY))]
    allc = baseline + winners
    with Pool(4) as pool:
        res = pool.map(judge, [(g, test) for _, _, g in allc])
    print("\n### safety-yield frontier on fresh worlds (costly identities, full attack suite)")
    print(f"{'nucleation law':32} {'risk':>4} {'right':>6} {'wrong':>6} {'worst':>6} {'calm right':>10} {'AUC':>5}")
    for (name, lam, g), r in zip(allc, res):
        print(f"{name:32} {str(lam):>4} {r['right']:6.2f} {r['wrong']:6.3f} {r['worst_wrong']:6.3f} {r['calm_right']:10.2f} {r['auc']:5.2f}")
    json.dump([(n, l, g, r) for (n, l, g), r in zip(allc, res)], open("frontier-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
