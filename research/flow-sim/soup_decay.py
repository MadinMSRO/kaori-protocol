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

ARMS = ["G: flow, graded + provenance", "G: none (no law), graded + provenance"]

def job(args):
    name, s, i, a = args
    return name, i, SP.run(name, K.make(s, a, "critical"))["wrong_q"]

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
    q = lambda n, i: [sum(r[j] for m, ii, r in res if m == n and ii == i) / k for j in range(4)]
    print(f"{'attack':40} {'flow law: wrong by quarter':>34} {'half-life':>9}   {'no law: wrong by quarter':>32}")
    out = {}
    for i, (nm, _) in enumerate(suite):
        a, b = q(ARMS[0], i), q(ARMS[1], i)
        out[nm] = {"law": a, "none": b, "half_life": half_life(a)}
        f = lambda x: " -> ".join(f"{v * 100:4.1f}%" for v in x)
        print(f"{nm[:40]:40} {f(a):>34} {half_life(a):>9}   {f(b):>32}")
    allq = lambda n: [sum(q(n, i)[j] for i in range(len(suite))) / len(suite) for j in range(4)]
    print(f"\n{'all attacks (mean)':40} {' -> '.join(f'{v * 100:4.1f}%' for v in allq(ARMS[0])):>34} {half_life(allq(ARMS[0])):>9}   "
          f"{' -> '.join(f'{v * 100:4.1f}%' for v in allq(ARMS[1])):>32}")
    json.dump(out, open("soup-decay-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
