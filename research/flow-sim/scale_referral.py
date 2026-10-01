"""
Referral-only sign-up: how many REAL members must an attacker corrupt as Liminal grows?

Everyone joins through a referral by an existing member, so every identity has a lineage. An attacker can create any
number of fake identities (the worst case: unlimited, each still earning validator status in person), but every fake
hangs off a real member the attacker has corrupted: an attack edge. Fakes under the same attack edge share a short
lineage, so the network counts them as one group (bond B_IN; 0.9 allows for imperfect detection). Fakes under
different attack edges came through different real people and count as independent.

A referral may also declare how the referrer knows the person and how much they would vouch. In this design those
declarations shape topology (closeness = expected dependence = stronger bond), never standing: an attacker who
declares closeness bonds their fakes tighter, one who declares distance is still bonded by lineage. So declarations
cannot buy influence, and the model only needs lineage.

Everything else is scale.py: honest density and the blind validator pool grow with N, compile with groups counting
once, in-app capture (attack photos are real), one false truth at one key with 50% chance, and capture of half of all
independent blind checking. The attacker brings unlimited fakes (FAKES_PER_USER x N of them); the cost is k, the
real members corrupted.
"""
import json, math, random, sys
import scale as SC
from agents import STATES, read, form

B_IN = 0.9
ASSIGN = "identity"           # "identity": blind validators drawn uniformly over identities (fakes flood the pool)
                              # "lineage":  drawn by referral branch first, so a fake subtree gets checks in proportion
                              #             to its attack edges (the real people it came through), not its fakes
FAKES_PER_USER = 5.0          # unlimited in effect: attacker validators dominate the pool, s -> 0.86

def posterior_groups(sig):
    size = {}
    for e, g, x, w in sig:
        if g is not None: size.setdefault(g, set()).add(e)
    k = {}
    for e, *_ in sig: k[e] = k.get(e, 0) + 1
    L = {v: 0.0 for v in SC.VALS}
    for e, g, x, w in sig:
        r = SC.C[e.split(":")[0]] * w
        gv = {v: 1.0 if SC.D[(x, v)] == 0 else 0.5 if SC.D[(x, v)] == 1 else 0.0 for v in SC.VALS}
        z = sum(gv.values())
        mass = 1 + B_IN * (len(size[g]) - 1) if g is not None else 1
        for v in SC.VALS: L[v] += math.log((1 - r) + r * len(SC.VALS) * gv[v] / z) / (mass * k[e])
    m = max(L.values()); Zs = sum(math.exp(x - m) for x in L.values())
    return {v: math.exp(L[v] - m) / Zs for v in SC.VALS}

def attack_once(R, d, team, s, kedges):
    truth = (STATES[R.randrange(5)], False)
    fake = (STATES[(STATES.index(truth[0]) + R.choice([2, 3])) % 5], False)
    sig = []
    lam = d; pmf = math.exp(-lam); p, u, h = pmf, R.random(), 0
    while u > p and h < 400: h += 1; pmf *= lam / h; p += pmf
    vid = [0]
    def readers(content, signed):
        out = [("ai", None, read(R, content, 0.8, 0.85))]
        for _ in range(3):
            vid[0] += 1
            if R.random() < s:
                out.append((f"attacker:v{vid[0]}", R.randrange(kedges), SC.STATES and (fake if signed else read(R, content, 0.9, 0.9))))
            else:
                out.append((f"validator:{vid[0]}", None, read(R, content, 0.9, 0.9)))
        return out
    for i in range(h):
        eye = truth if R.random() < 0.9 else SC.neighbour(R, truth)
        w = SC.REAL_PASS if R.random() < 0.95 else SC.FAKE_PASS
        sig.append((f"honest:{i}", None, eye, w))
        for e, g, x in readers(truth, False): sig.append((e, g, x, w))
    for j in range(team):
        w = SC.REAL_PASS if R.random() < 0.95 else SC.FAKE_PASS
        sig.append((f"attacker:o{j}", R.randrange(kedges), fake, w))
        for e, g, x in readers(truth, True): sig.append((e, g, x, w))
    f = form(posterior_groups(sig), SC.TAU, True)
    return bool(f) and fake in f[1] and truth not in f[1]

def p_success(d, k, N, seed=1):
    if ASSIGN == "lineage": s = k / (k + SC.ELIG * N)
    else:
        A = FAKES_PER_USER * N
        s = A / (A + SC.ELIG * N)
    best = 0.0
    for team in (1, 2, 3, 5, 8, 13, 21):
        R = random.Random(seed * 7919 + team * 31 + k)
        p = sum(attack_once(R, d, team, s, k) for _ in range(SC.TRIALS)) / SC.TRIALS
        best = max(best, p)
        if best >= 0.5: break
    return best

def min_edges(d, N):
    lo, hi = 1, 1
    while p_success(d, hi, N) < 0.5:
        lo, hi = hi, hi * 2
        if hi > 4 * N: return None
    while hi - lo > max(1, lo // 20):
        mid = (lo + hi) // 2
        if p_success(d, mid, N) >= 0.5: hi = mid
        else: lo = mid
    return hi

if __name__ == "__main__":
    ASSIGN = sys.argv[1] if len(sys.argv) > 1 else "identity"
    Ns = [100, 300, 1000, 3000, 10000, 30000, 100000]
    rows = []
    print(f"referral-only sign-up; validators drawn by {ASSIGN}; fakes unlimited ({FAKES_PER_USER:g} per user); "
          f"lineage bond within an attack edge {B_IN}")
    print(f"{'users N':>8} {'honest/key':>10} | real members to corrupt for a 50% chance of one false truth | capture half of")
    print(f"{'':>8} {'(typical)':>10} | {'quiet (x0.1)':>13} {'typical':>9} {'hotspot (x10)':>14} {'':>21}| independent checking")
    for N in Ns:
        d = N * SC.OBS_PER_USER_HOUR / SC.ACTIVE_HEXES
        q, t, hs = (min_edges(d * x, N) for x in (0.1, 1, 10))
        # half of all blind checking: by identity, fakes alone reach it (one corrupted member suffices in principle);
        # by lineage, it needs as many attack edges as there are honest eligible validators
        total = math.ceil(SC.ELIG * N) if ASSIGN == "lineage" else 1
        rows.append(dict(N=N, density=d, quiet=q, typical=t, hotspot=hs, total=total))
        f = lambda x: f"{x:,}" if x else "-"
        print(f"{N:>8,} {d:>10.2f} | {f(q):>13} {f(t):>9} {f(hs):>14} {'':>21}| {total:>10,}", flush=True)
    json.dump({"rows": rows, "assumptions": dict(B_IN=B_IN, FAKES_PER_USER=FAKES_PER_USER, TRIALS=SC.TRIALS)},
              open(f"scale-referral-{ASSIGN}.json", "w"), indent=1)
