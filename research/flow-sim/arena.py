"""
Arena: the 7 Principles against the best system from every earlier run, on the same fresh worlds.

Phase 1: every system, every scenario in the attack suite, fresh seeds.
Phase 2: attackers evolve against the 7 Principles only (they aim for wrong truths, then for stalls).
         The best of them join the suite, and every system faces them.
Each system uses the signals it was designed for. The older ones use the world's human gate; the newer ones
use the agents built into the world (provenance, AI, validators).
"""
import json, random, time, sys
from multiprocessing import Pool
import coevo, evo, topo, emerge, agents as A, seed as S, blind as B
from emerge import NAMES

front = {(n, l): g for n, l, g, r in json.load(open("frontier-result.json"))}
cands = dict(json.load(open("coevo-result.json"))["cands"])
TOPO = json.load(open("topo-result.json"))["best"]["simplicial"]
EMER = json.load(open("emerge-result.json"))["best"]["emergent bonds"]
CHAMP = json.load(open("agents-result.json"))["best"]["+ both"]

def sys_evo(g):
    return lambda s, a: evo.run(g, coevo.make_world(s, a))

SYSTEMS = {
    "today's Flow": sys_evo(dict(evo.TODAY, sat=500.0)),
    "Red Queen co-evolved laws": sys_evo(cands["co-evolved 1"]),
    "Jeans collapse (frontier)": sys_evo(front[("Jeans collapse", 10)]),
    "bee quorum (frontier)": sys_evo(front[("bee quorum + cross-inhibition", 3)]),
    "simplicial complex (hand-picked)": lambda s, a: topo.run("simplicial", TOPO, coevo.make_world(s, a)),
    "emergent bonds": lambda s, a: emerge.run(EMER, coevo.make_world(s, a)),
    "all agents, evolved champion": lambda s, a: A.run(CHAMP, A.add_agents(coevo.make_world(s, a), s), True, True),
    "seed, untuned": lambda s, a: S.run(S.FULL, A.add_agents(coevo.make_world(s, a), s)),
    "7 PRINCIPLES": lambda s, a: B.run(B.FULL, B.add_agents_blind(coevo.make_world(s, a), s)),
}

def job(args):
    name, s, ai, a = args
    r = SYSTEMS[name](s, a)
    r.setdefault("right_exact", r["right"])
    return name, ai, {k: r.get(k, 0.0) for k in ("right", "wrong", "stuck", "auc", "right_exact")}

# ---------------- phase 2: attackers evolve against the 7 Principles
def attack_fit(args):
    a, seeds = args
    rs = [B.run(B.FULL, B.add_agents_blind(coevo.make_world(s, a), s)) for s in seeds]
    w = sum(r["wrong"] for r in rs) / len(rs); st = sum(r["stuck"] for r in rs) / len(rs)
    return w + 0.1 * st

def evolve_attackers(R, pop_n=16, gens=10):
    pop = [coevo.rand_att(R) for _ in range(pop_n - 2)] + [dict(x) for x in topo.suite()[:1] + topo.suite()[3:4]]
    with Pool(4) as pool:
        for g in range(gens):
            seeds = [R.getrandbits(48) for _ in range(2)]
            fs = pool.map(attack_fit, [(a, seeds) for a in pop])
            ranked = [a for _, a in sorted(zip(fs, pop), key=lambda x: -x[0])]
            print(f"  gen {g}: best attacker fitness {max(fs):.3f}", flush=True)
            nxt = [dict(a) for a in ranked[:4]]
            while len(nxt) < pop_n: nxt.append(coevo.mut_att(dict(R.choice(ranked[:8])), R))
            pop = nxt
    return ranked[:2]

if __name__ == "__main__":
    t0 = time.time()
    R = random.Random(random.SystemRandom().getrandbits(48))
    print("### phase 2 first: attackers evolving against the 7 Principles", flush=True)
    adaptive = evolve_attackers(R)
    for a in adaptive: print("  adaptive attacker:", coevo.show_att(a))
    suite = [(nm, a) for nm, a in zip(NAMES, topo.suite()) if nm not in ("cabal 2", "cabal 3")]
    suite += [("adaptive A", adaptive[0]), ("adaptive B", adaptive[1])]
    test = [random.SystemRandom().getrandbits(48) for _ in range(5)]
    jobs = [(n, s, i, a) for n in SYSTEMS for i, (_, a) in enumerate(suite) for s in test]
    with Pool(4) as pool:
        res = pool.map(job, jobs, chunksize=4)
    table = {}
    for n in SYSTEMS:
        per = []
        for i in range(len(suite)):
            rs = [r for nm, ai, r in res if nm == n and ai == i]
            per.append({k: sum(r[k] for r in rs) / len(rs) for k in rs[0]})
        allr = [r for nm, ai, r in res if nm == n]
        agg = {k: sum(r[k] for r in allr) / len(allr) for k in allr[0]}
        agg["worst"] = max(p["wrong"] for p in per)
        table[n] = (agg, per)
    print("\n### every system, same fresh worlds (5 seeds x 7 scenarios incl. 2 attackers evolved against the 7 Principles)")
    print(f"{'':34} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}")
    for n, (agg, per) in table.items():
        print(f"{n:34} {agg['right']:6.2f} {agg['wrong']:6.3f} {agg['worst']:6.3f} {agg['stuck']:6.2f} {agg['auc']:5.2f}")
    print("\n### right / wrong per scenario")
    print(f"{'':34} " + "  ".join(f"{nm.split()[0][:10]:>12}" if not nm.startswith('adaptive') else f"{nm:>12}" for nm, _ in suite))
    for n, (agg, per) in table.items():
        print(f"{n:34} " + "  ".join(f"{p['right']:.2f}/{p['wrong']:.3f}".rjust(12) for p in per))
    json.dump({"adaptive": adaptive, "table": {n: {"agg": a, "per": p} for n, (a, p) in table.items()}},
              open("arena-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
