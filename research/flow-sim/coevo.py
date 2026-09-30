"""
Red Queen co-evolution: trust laws (defenders) against an adaptive attacker team.

Defender genome: evo.py's slots (one natural law per slot + constants), plus a saturating influence law
(Rule 6: dominant, but with diminishing returns).
Attacker genome: the whole strategy of one coordinated team -
  n          identities it runs (2-8)
  active     share of hours the team is out
  attack     share of active hours it attacks (otherwise it behaves honestly to build standing)
  scatter    while honest, members go to places independently (so they do not flock)
  sleep      share of the run before the first attack
  wash       re-register as fresh identities every `wash` hours (0 = never)
  steal      honest careful accounts taken over at the first attack (0-2); they then attack with the team
  truephoto  share of attacks made with a true photo and a false value (else a consistent fake photo)
Each side keeps a hall of fame; defenders must also beat every past champion attack.
"""
import math, random, sys, json, time
from collections import Counter, defaultdict
from multiprocessing import Pool
import evo

STATES = evo.STATES
evo.SLOTS["weight"] = ["linear", "phase", "power", "boltzmann", "saturating"]
evo.RANGES["sat"] = (100.0, 900.0)
evo.TODAY["sat"] = 500.0
_weight = evo.weight_of
def weight_of(S, g):
    if g["weight"] == "saturating":  # magnetisation-like: proportional at first, capped in dominance
        return 1000 * math.tanh(S / g["sat"])
    return _weight(S, g)
evo.weight_of = weight_of
evo.HOSTILE |= {"adv", "stolen"}

A_RANGES = {"n": (2, 8), "active": (0.1, 0.95), "attack": (0.05, 1.0), "scatter": (0.0, 1.0), "sleep": (0.0, 0.8),
            "wash": (0, 200), "steal": (0, 2), "truephoto": (0.0, 1.0)}

def make_world(seed, att, hours=400):
    R = random.Random(seed)
    mix = {"careful": 6, "sloppy": 3, "lazy": 2, "liar": 2, "faker": 1}
    presence = {"careful": .5, "sloppy": .5, "lazy": .5, "liar": .4, "faker": .4}
    n, steal = int(round(att["n"])), int(round(att["steal"]))
    wash = int(att["wash"]); t_attack = int(att["sleep"] * hours)
    sky = {p: R.randrange(5) for p in range(6)}; rain = {p: False for p in range(6)}
    memory = {}; events = []
    for t in range(hours):
        for p in sky:
            if R.random() < 0.25: sky[p] = max(0, min(4, sky[p] + R.choice([-1, 1])))
            rain[p] = sky[p] == 4 and R.random() < 0.4
        live = R.sample(range(6), 4)
        at = defaultdict(list)
        stolen_now = t >= t_attack and steal > 0
        for kind, cnt in mix.items():
            for i in range(cnt):
                if kind == "careful" and stolen_now and i < steal: continue  # taken over
                if R.random() < presence[kind]: at[R.choice(live)].append((kind, i, "self"))
        # the adversary team
        if R.random() < att["active"]:
            attacking = t >= t_attack and R.random() < att["attack"]
            gen = (t // wash) if wash > 0 else 0
            team = [("adv", f"{i}g{gen}") for i in range(n)] + ([("stolen", i) for i in range(steal)] if stolen_now else [])
            if attacking:
                target = R.choice(live)
                for kind, i in team: at[target].append((kind, i, "attack"))
            else:
                together = R.choice(live)
                for kind, i in team:
                    if kind == "stolen": continue  # stolen accounts only surface to attack
                    at[R.choice(live) if R.random() < att["scatter"] else together].append((kind, i, "honest"))
        for p in live:
            truth = (STATES[sky[p]], rain[p])
            fake_s = (sky[p] + R.choice([2, 3])) % 5
            fake = (STATES[fake_s], fake_s == 4 and R.random() < 0.5)
            true_photo_attack = R.random() < att["truephoto"]
            reps = []
            for kind, i, mode in at[p]:
                aid = f"{kind}{i}" if kind != "stolen" else f"careful{i}"
                shows, rel = "truth", (R.uniform(0.92, 1.0) if R.random() > 0.05 else R.uniform(0.78, 0.92))
                k = kind
                if mode == "attack":
                    said = fake
                    if not true_photo_attack: shows = "fake"
                elif kind in ("careful", "adv"):
                    said = truth
                elif kind == "sloppy":
                    s = sky[p]
                    if R.random() < 0.3: s = max(0, min(4, s + R.choice([-1, 1])))
                    said = (STATES[s], rain[p] if R.random() > 0.1 else not rain[p])
                elif kind == "lazy":
                    said = memory.get((aid, p), (STATES[R.randrange(5)], False))
                elif kind == "liar":
                    said = (R.choice([x for x in STATES if x != truth[0]]), R.random() < 0.3)
                else:  # faker
                    if R.random() < 0.5: said, shows, rel = (STATES[R.randrange(5)], R.random() < 0.3), "junk", R.uniform(0.0, 0.71)
                    else: said, shows = fake, "fake"
                memory[(aid, p)] = truth if kind == "lazy" else said
                reps.append((aid, k, said, shows, rel))
            events.append((t, p, truth, fake, reps, R.random()))
    return events

def score(g, att, seeds):
    ms = [evo.run(g, make_world(s, att)) for s in seeds]
    avg = {k: sum(m[k] for m in ms) / len(ms) for k in ("right", "wrong", "stuck", "undecided", "hurt", "auc")}
    won = Counter()
    for m in ms: won.update(m["won"])
    E = sum(m["eligible"] for m in ms)
    avg["adv_wins"] = (won.get("adv", 0) + won.get("stolen", 0)) / max(1, E)
    avg["tiers"] = {k: round(sum(m["tiers"].get(k, 0) for m in ms) / len(ms)) for k in ("careful", "sloppy", "lazy", "liar", "faker")}
    avg["fit"] = evo.fitness(avg)
    return avg

def job(args):
    g, att, seeds = args
    return score(g, att, seeds)

def rand_att(R): return {k: R.uniform(*r) for k, r in A_RANGES.items()}
def mut_att(a, R, rate=0.3):
    a = dict(a)
    for k, (lo, hi) in A_RANGES.items():
        if R.random() < rate: a[k] = min(hi, max(lo, a[k] + R.gauss(0, (hi - lo) * 0.2)))
    return a

def show_att(a):
    return (f"{int(round(a['n']))} ids, out {a['active']:.0%} of hours, attacks {a['attack']:.0%} of those, "
            f"scatter {a['scatter']:.0%}, sleeps {a['sleep']:.0%} of the run, "
            f"{'re-registers every %d h' % a['wash'] if a['wash'] >= 1 else 'never re-registers'}, "
            f"steals {int(round(a['steal']))} account(s), true-photo lies {a['truephoto']:.0%}")

def coevolve(gens=30, dn=24, an=16, seed=None):
    R = random.Random(seed)
    hand = dict(evo.TODAY, dyn="pheromone", couple="margin", weight="linear", evidence="linear", nucleate="critical", alpha=0.15, beta=0.02, kappa=1.0)
    prev = dict(evo.TODAY, dyn="replicator", couple="surprise", weight="boltzmann", evidence="linear", topo="both", field="continuity",
                nucleate="critical", alpha=0.56, beta=0.01, gamma=0.73, T=98.0, k=1.84, lam=1.27, kappa=1.35, mu=2.75, J=0.51, tau=7.3)
    D = [evo.random_genome(R) | {"sat": R.uniform(100, 900)} for _ in range(dn - 3)] + [dict(evo.TODAY), hand, prev]
    A = [rand_att(R) for _ in range(an)]
    hof_a, hof_d = [], []
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48) for _ in range(2)]
            opp = sorted(A, key=lambda a: -a.get("_fit", 0))[:4] + R.sample(hof_a, min(3, len(hof_a)))
            dres = pool.map(job, [(g, a, seeds) for g in D for a in opp])
            dfit = []
            for i, g in enumerate(D):
                rs = dres[i * len(opp):(i + 1) * len(opp)]
                # defenders are judged on the average and the worst attack they face
                f = 0.5 * sum(r["fit"] for r in rs) / len(rs) + 0.5 * min(r["fit"] for r in rs)
                dfit.append((f, g, rs))
            dfit.sort(key=lambda x: -x[0])
            foes = [g for _, g, _ in dfit[:3]] + R.sample(hof_d, min(2, len(hof_d)))
            ares = pool.map(job, [(g, a, seeds) for a in A for g in foes])
            for i, a in enumerate(A):
                rs = ares[i * len(foes):(i + 1) * len(foes)]
                a["_fit"] = sum(r["adv_wins"] for r in rs) / len(rs)
            A.sort(key=lambda a: -a["_fit"])
            hof_a.append(dict(A[0])); hof_d.append(dict(dfit[0][1]))
            bd, ba = dfit[0], A[0]
            wr = sum(r["wrong"] for r in bd[2]) / len(bd[2])
            print(f"gen {gen:2} | best laws fit {bd[0]:.3f} wrong {wr:.3f}: "
                  + " ".join(str(bd[1][k]) for k in evo.SLOTS) + f" | best attack wins {ba['_fit']:.3f}: {show_att(ba)}", flush=True)
            # breed
            elite = [g for _, g, _ in dfit[:5]]
            D = [dict(g) for g in elite]
            while len(D) < dn:
                a, b = R.sample(dfit[:12], 2); D.append(evo.mutate(evo.cross(a[1], b[1], R), R))
            eliteA = [dict(a) for a in A[:4]]
            A = eliteA + [mut_att(R.choice(A[:8]), R) for _ in range(an - 4 - 2)] + [rand_att(R) for _ in range(2)]
    return D, hof_a, hof_d, hand, prev

if __name__ == "__main__":
    t0 = time.time()
    D, hof_a, hof_d, hand, prev = coevolve(gens=int(sys.argv[1]) if len(sys.argv) > 1 else 30, seed=random.SystemRandom().getrandbits(48))
    # judgement: every champion attack ever found, plus classic ones, on fresh worlds
    classic = {
        "ring (no evasion)": {"n": 3, "active": .45, "attack": 1.0, "scatter": 0, "sleep": 0, "wash": 0, "steal": 0, "truephoto": 0},
        "sybil swarm": {"n": 6, "active": .5, "attack": 1.0, "scatter": 0, "sleep": 0, "wash": 40, "steal": 0, "truephoto": 0},
        "sleeper + stolen accounts": {"n": 4, "active": .5, "attack": .3, "scatter": 1, "sleep": .6, "wash": 0, "steal": 2, "truephoto": 0},
        "patient scatterers": {"n": 6, "active": .8, "attack": .1, "scatter": 1, "sleep": .3, "wash": 0, "steal": 0, "truephoto": .5},
    }
    attacks = list(classic.items()) + [(f"champion {i}", a) for i, a in enumerate(hof_a[-6:])]
    test = [random.SystemRandom().getrandbits(48) for _ in range(3)]
    cands = [("today", dict(evo.TODAY)), ("hand-built", hand), ("evolved before (no adaptive attacker)", prev)] + [(f"co-evolved {i+1}", g) for i, g in enumerate(D[:3])]
    with Pool(4) as pool:
        res = pool.map(job, [(g, a, test) for _, g in cands for _, a in attacks])
    print("\n### judgement: fresh worlds, every attack (classic and every recent champion)")
    print(f"{'laws':40} {'avg wrong':>9} {'worst wrong':>11} {'right':>6} {'AUC':>5}  worst attack")
    for i, (name, g) in enumerate(cands):
        rs = res[i * len(attacks):(i + 1) * len(attacks)]
        worst = max(range(len(rs)), key=lambda j: rs[j]["wrong"])
        print(f"{name:40} {sum(r['wrong'] for r in rs)/len(rs):9.3f} {rs[worst]['wrong']:11.3f} {sum(r['right'] for r in rs)/len(rs):6.2f} {sum(r['auc'] for r in rs)/len(rs):5.2f}  {attacks[worst][0]}")
    for name, g in cands[3:4]:
        print(f"\nbest co-evolved laws: " + ", ".join(f"{k}={g[k]}" for k in evo.SLOTS) + " | " + ", ".join(f"{k}={g[k]:.2f}" for k in list(evo.RANGES)))
    print("\nstrongest attacks found:")
    for i, a in enumerate(hof_a[-6:]): print(f"  champion {i}: {show_att(a)}")
    json.dump({"cands": cands, "hof_a": hof_a}, open("coevo-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
