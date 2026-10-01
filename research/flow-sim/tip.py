"""
Tipping point: at what attacker share does the network fall into a TOTAL false attractor?

Local wrong truths where attackers outnumber everyone are expected. A total false attractor has two signatures:
  spillover  the lie forms where attackers are a MINORITY of the observers present (their influence has outgrown
             their numbers: the compounding a total attractor needs)
  inversion  attackers end with thicker conduits than careful observers (the network trusts them over reality's
             renderers): inverted when attacker / careful thickness > 1

Sweep: attacker team size n (share of observers n / (14 + n)) x validator farm (of 40, signing every attack photo).
Attack: active 90% of hours, attacks half of those, half the time scattered when not attacking, no sleep, half the
attack photos real (lie on a real photo), half forged.
"""
import json, time
from multiprocessing import Pool
import captcha as K, soup as SP

DESIGNS = ["G: flow, graded + provenance", "T1: grow only from own evidence", "T2: own evidence + together counts once"]
TEAM = [1, 2, 4, 7, 10, 14, 21]
FARM = [0, 8, 16, 24]
SEEDS = [11, 22, 33, 44]

def att(n, farm):
    return {"n": n, "active": 0.9, "attack": 0.5, "scatter": 0.5, "sleep": 0.0, "wash": 0, "steal": 0,
            "truephoto": 0.5, "farm": farm, "signed": 1.0}

def job(args):
    d, n, f, s = args
    r = SP.run(d, K.make(s, att(n, f), "critical"))
    return d, n, f, r

if __name__ == "__main__":
    t0 = time.time()
    with Pool(4) as pool:
        res = pool.map(job, [(d, n, f, s) for d in DESIGNS for n in TEAM for f in FARM for s in SEEDS], chunksize=2)
    out = {}
    for d in DESIGNS:
        print(f"\n### {d}")
        print("cells: wrong where attackers present / wrong where they are a minority / attacker:careful thickness (* = inverted)")
        print(f"{'team (share)':>14} " + "".join(f"{'farm ' + str(f) + '/40':>26}" for f in FARM))
        for n in TEAM:
            row = []
            for f in FARM:
                rs = [r for dd, nn, ff, r in res if dd == d and nn == n and ff == f]
                m = lambda k: sum(r[k] for r in rs) / len(rs)
                ratio = m("attacker_c") / max(1e-9, m("careful_c"))
                out[f"{d}|{n}|{f}"] = dict(wrong_att=m("wrong_att"), wrong_min=m("wrong_min"), ratio=ratio,
                                          right=m("right"), stuck=m("stuck"))
                row.append(f"{m('wrong_att') * 100:5.1f}% {m('wrong_min') * 100:4.1f}% {ratio:4.2f}{'*' if ratio > 1 else ' '}")
            print(f"{n:>3} ({n / (14 + n):4.0%})    " + "".join(f"{c:>26}" for c in row))
    json.dump(out, open("tip-result.json", "w"), indent=1)
    print(f"\n{time.time() - t0:.0f}s")
