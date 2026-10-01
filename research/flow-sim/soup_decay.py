"""
Is any attack surface permanent? For each attack: the share of keys that formed wrong, quarter by quarter, under the
flow law and under no law (same worlds, same attack schedule). Damage that falls under the law but not without it is
the network absorbing the attack; damage that stays flat or grows under the law is a permanent surface.

Half-life: quarters until the law's wrong rate falls to half its first-quarter value (linear between quarters);
"never" if it does not within the run.
"""
import json, time
from multiprocessing import Pool
import captcha as K, trust as T, soup as SP

ARMS = ["G: flow, graded + provenance", "L: flow, local trust, graded + provenance",
        "D: flow, graded + provenance, decay 14 d", "D: flow, graded + provenance, decay 7 d",
        "G: none (no law), graded + provenance"]

def job(args):
    name, s, i, a = args
    return name, i, SP.run(name, K.make(s, a, "critical"))

def half_life(q):
    if q[0] <= 0: return "-"
    target = q[0] / 2
    for i in range(1, 4):
        if q[i] <= target:
            frac = (q[i - 1] - target) / max(1e-12, q[i - 1] - q[i])
            return f"{i - 1 + frac:.1f} q"
    return "never"

if __name__ == "__main__":
    t0 = time.time()
    prev = json.load(open("battle-result.json")); prev2 = json.load(open("battle2-result.json"))
    test = prev["test_seeds"]
    suite = list(T.SUITE)
    for nm, f in (("hall of fame: trust adaptive", "trust-result.json"), ("hall of fame: captcha adaptive", "captcha-result.json")):
        suite.append((nm, json.load(open(f))["adaptive"]))
    for name, a in list(prev["evolved"].items()) + list(prev2["evolved"].items()): suite.append(("evolved vs " + name, a))
    with Pool(4) as pool:
        res = pool.map(job, [(n, s, i, a) for n in ARMS for i, (_, a) in enumerate(suite) for s in test], chunksize=4)
    k = len(test)
    q = lambda n, i: [sum(r["wrong_q"][j] for m, ii, r in res if m == n and ii == i) / k for j in range(4)]
    f = lambda x: " -> ".join(f"{v * 100:4.1f}%" for v in x)
    allq = lambda n: [sum(q(n, i)[j] for i in range(len(suite))) / len(suite) for j in range(4)]
    print(f"{'':44} {'right':>5} {'wrong':>6} {'stuck':>5} {'careful':>7} {'attacker':>8}   {'wrong by quarter (all attacks)':>34} {'half-life':>9}")
    out = {"summary": {}, "per_attack": {}}
    for n in ARMS:
        rs = [r for m, _, r in res if m == n]
        mm = lambda x: sum(r[x] for r in rs) / len(rs)
        out["summary"][n] = dict(right=mm("right"), wrong=mm("wrong"), stuck=mm("stuck"), careful_c=mm("careful_c"),
                                 attacker_c=mm("attacker_c"), wrong_q=allq(n), half_life=half_life(allq(n)))
        print(f"{n:44} {mm('right'):5.2f} {mm('wrong'):6.3f} {mm('stuck'):5.2f} {mm('careful_c'):7.2f} {mm('attacker_c'):8.2f}   {f(allq(n)):>34} {half_life(allq(n)):>9}")
    print("\n### wrong by quarter, per attack (columns: " + " | ".join(ARMS) + ")")
    for i, (nm, _) in enumerate(suite):
        out["per_attack"][nm] = {n: q(n, i) for n in ARMS}
        print(f"{nm[:40]:40} " + "  |  ".join(f(q(n, i)) for n in ARMS))
    json.dump(out, open("soup-decay-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
