"""
How expensive is it to attack as Liminal grows?

Not a world simulation: the attack is played on the graph around one TruthKey, and the graph's two growing quantities
come from the user count N:
  honest density at a key  d = N x obs_per_user_hour / active_hexes   (more people present to render the real sky)
  validator pool           0.8 N honest eligible validators            (random blind checks drawn mostly from honest)

Compile: the safest design from tip2.py: conduits grown only from own evidence, groups that keep turning up together
count once, graded rendering, provenance as a Signal on every photo. Formation: the stakes minimum lam/(1+lam).
BOND is how far the network has detected the attacker identities (observers and validators) as one group: 0 means
undetected, so every identity counts fully (the worst case); 1 means the whole group counts as one contact.

Attackers: A identities, each must earn validator eligibility through EARN honest in-app observations. At the target
key they bring a team of m (the best m for them), all rendering the same lie. Their share of blind validator readings
is s = A / (A + 0.8 N); an attacker validator answers the lie on a signed attack photo.
  with in-app capture   attack photos are real (they show the real sky) and pass provenance
  without capture       attack photos are forged (they show the lie) and pass provenance 15% of the time

For each N: the fewest identities A for a 50% chance of one false truth at one key (typical, quiet x0.1, hotspot x10),
and for capturing half of all blind checking (the total false attractor threshold).
"""
import math, random, json
from agents import VALS, D, STATES, read, form

ACTIVE_HEXES, OBS_PER_USER_HOUR, ELIG = 300, 1 / 12, 0.8
EARN = 25                  # honest observations to lift a conduit from 0.1 past the 0.6 eligibility threshold
C = {"honest": 0.80, "attacker": 0.75, "ai": 0.85, "validator": 0.80}
REAL_PASS, FAKE_PASS = 0.86, 0.055       # provenance agent's realness for a photo that passed / failed
TAU = 10 / 11
TRIALS = 300
BOND = 0.0                 # how far the network has detected the attackers as one group: 0 undetected, 1 fully

def posterior(sig):
    """sig: (emitter, group, value, realness). Group members count once (mass = group size at this key)."""
    size = {}
    for e, g, x, w in sig:
        if g: size.setdefault(g, set()).add(e)
    k = {}
    for e, *_ in sig: k[e] = k.get(e, 0) + 1
    L = {v: 0.0 for v in VALS}
    for e, g, x, w in sig:
        r = C[e.split(":")[0]] * w
        gv = {v: 1.0 if D[(x, v)] == 0 else 0.5 if D[(x, v)] == 1 else 0.0 for v in VALS}
        z = sum(gv.values())
        mass = 1 + BOND * (len(size[g]) - 1) if g else 1
        for v in VALS: L[v] += math.log((1 - r) + r * len(VALS) * gv[v] / z) / (mass * k[e])
    m = max(L.values()); Zs = sum(math.exp(x - m) for x in L.values())
    return {v: math.exp(L[v] - m) / Zs for v in VALS}

def neighbour(R, v):
    i = STATES.index(v[0])
    return (STATES[max(0, min(4, i + R.choice([-1, 1])))], v[1])

def attack_once(R, d, m, s, capture):
    truth = (STATES[R.randrange(5)], False)
    fs = (STATES.index(truth[0]) + R.choice([2, 3])) % 5
    fake = (STATES[fs], False)
    sig = []
    h = 0
    lam = d                                    # Poisson honest presence
    p, u = math.exp(-lam), R.random()
    while u > p and h < 200: h += 1; p += math.exp(-lam) * lam ** h / math.factorial(h)
    vid = [0]
    def readers(content, signed):
        out = [("ai", None, read(R, content, 0.8, 0.85))]
        for _ in range(3):
            vid[0] += 1
            if R.random() < s: out.append((f"attacker:v{vid[0]}", "team", fake if signed else read(R, content, 0.9, 0.9)))
            else: out.append((f"validator:{vid[0]}", None, read(R, content, 0.9, 0.9)))
        return out
    for i in range(h):
        eye = truth if R.random() < 0.9 else neighbour(R, truth)
        w = REAL_PASS if R.random() < 0.95 else FAKE_PASS
        sig.append((f"honest:{i}", None, eye, w))
        for e, g, x in readers(truth, False): sig.append((e, g, x, w))
    for j in range(m):
        if capture: content, w = truth, (REAL_PASS if R.random() < 0.95 else FAKE_PASS)
        else: content, w = fake, (REAL_PASS if R.random() < 0.15 else FAKE_PASS)
        sig.append((f"attacker:o{j}", "team", fake, w))
        for e, g, x in readers(content, True): sig.append((e, g, x, w))
    f = form(posterior(sig), TAU, True)
    return bool(f) and fake in f[1] and truth not in f[1]

def p_success(d, A, N, capture, seed=1):
    s = A / (A + ELIG * N)
    best = 0.0
    for m in sorted({1, 2, 3, 5, 8, 13} & set(range(1, A + 1)) | {min(A, 1)}):
        R = random.Random(seed * 7919 + m)
        p = sum(attack_once(R, d, m, s, capture) for _ in range(TRIALS)) / TRIALS
        best = max(best, p)
    return best

def min_identities(d, N, capture):
    lo, hi = 1, 1
    while p_success(d, hi, N, capture) < 0.5:
        lo, hi = hi, hi * 2
        if hi > 20 * N: return None
    while hi - lo > max(1, lo // 20):
        mid = (lo + hi) // 2
        if p_success(d, mid, N, capture) >= 0.5: hi = mid
        else: lo = mid
    return hi

if __name__ == "__main__":
    import sys
    BOND = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    Ns = [100, 300, 1000, 3000, 10000, 30000, 100000]
    rows = []
    print(f"attacker group detection BOND = {BOND}")
    print(f"{'users N':>8} {'honest/key':>10} | identities for a 50% chance of one false truth at one key"
          f" {'':>4}| capture half of blind checking")
    print(f"{'':>8} {'(typical)':>10} | {'quiet (x0.1)':>13} {'typical':>9} {'hotspot (x10)':>14} {'no capture, typ.':>17} |")
    for N in Ns:
        d = N * OBS_PER_USER_HOUR / ACTIVE_HEXES
        q, t, hs = (min_identities(d * k, N, True) for k in (0.1, 1, 10))
        nc = min_identities(d, N, False)
        total = math.ceil(ELIG * N)
        rows.append(dict(N=N, density=d, quiet=q, typical=t, hotspot=hs, no_capture=nc, total=total))
        f = lambda x: f"{x:,}" if x else "-"
        print(f"{N:>8,} {d:>10.2f} | {f(q):>13} {f(t):>9} {f(hs):>14} {f(nc):>17} | {total:>10,}")
    print(f"\neach identity must first earn eligibility: ~{EARN} honest in-app observations (about {EARN} days at one a day)")
    json.dump({"rows": rows, "assumptions": dict(ACTIVE_HEXES=ACTIVE_HEXES, OBS_PER_USER_HOUR=OBS_PER_USER_HOUR,
               ELIG=ELIG, EARN=EARN, C=C, TRIALS=TRIALS, BOND=BOND)}, open(f"scale-result-bond{BOND}.json", "w"), indent=1)
