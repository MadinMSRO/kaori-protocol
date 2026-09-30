# Fast model of Kaori Flow for comparing trust physics. Same world and agents as sim.py (the full
# Kaori + real CLIP run); the AI's per-photo relevance is drawn from what the real model measured
# (sky photos 0.92-1.00, junk 0.00-0.71; a photo of another sky looks like a sky to it).
#
# Models
#   current  - Kaori as implemented: weight = phase(logistic(S)), hard AI mean >= 0.82,
#              settlement +3 ln(1+q) / -5 ln(1+q) per agreeing / disagreeing agent
#   field    - one topological law from the whitepaper (see TOPOLOGY below)
import math, sys
from collections import Counter, defaultdict
from random import Random, SystemRandom

STATES = {"clear": ("clear", False), "overcast": ("overcast", False), "storm": ("overcast", True), "scattered": ("scattered", False)}
BANDS = ["clear", "few", "scattered", "broken", "overcast"]
PLACES = 5
MIX = {"careful": 3, "sloppy": 2, "liar": 2, "faker": 1, "colluder": 2}

def world(rng, hours):
    """The same event stream for every model: who stood where, what they said, what their photo shows."""
    agents = [f"{k}{i}" for k, n in MIX.items() for i in range(n)]
    kind = {a: a.rstrip("0123456789") for a in agents}
    events = []
    for t in range(hours):
        live = rng.sample(range(PLACES), 3)
        truth = {p: rng.choices(list(STATES), weights=[35, 30, 15, 20])[0] for p in live}
        group = rng.choice(live)
        coll_fake = rng.choice([s for s in STATES if s != truth[group]])
        at = {a: (group if kind[a] == "colluder" else rng.choice(live)) for a in agents}
        for p in live:
            reps = []
            for a in [a for a in agents if at[a] == p]:
                k, tr = kind[a], truth[p]
                cover, rain = STATES[tr]
                if k == "careful": said, shows = (cover, rain), tr
                elif k == "sloppy":
                    i = BANDS.index(cover)
                    if rng.random() < 0.3: i = min(4, max(0, i + rng.choice([-1, 1])))
                    said, shows = (BANDS[i], rain), tr
                elif k == "liar": said, shows = (rng.choice([b for b in BANDS if b != cover]), rng.random() < 0.5), tr
                elif k == "faker":
                    if rng.random() < 0.5: said, shows = (rng.choice(BANDS), rng.random() < 0.5), "junk"
                    else:
                        f = rng.choice([s for s in STATES if s != tr]); said, shows = STATES[f], f
                else: said, shows = STATES[coll_fake], coll_fake
                rel = rng.uniform(0.0, 0.71) if shows == "junk" else rng.uniform(0.92, 1.0)
                reps.append((a, said, shows, rel))
            events.append((t, p, truth[p], reps, rng.random(), rng.random()))
    return agents, kind, events

def logistic(S): return 1000 / (1 + math.exp(-0.01 * (S - 500)))
def phase(E): return E * 0.1 if E < 200 else (850 + (E - 850) * 0.3 if E > 850 else E)

def run(model, agents, kind, events, P):
    S = defaultdict(lambda: 200.0); S["AI"] = S["VAL"] = 250.0
    X = defaultdict(lambda: math.log(200 / 800))          # latent trust; S = 1000 * sigmoid(X)
    X["AI"] = X["VAL"] = math.log(250 / 750)
    edge = defaultdict(float)       # agreement graph: +1 agree, -1 disagree per co-assertion (symmetric)
    stats = Counter(); traj = defaultdict(list); minority_hits = 0
    for n, (t, p, truth, reps, u_val, u_stamp) in enumerate(events):
        if len(reps) < 3: stats["too few"] += 1; continue
        # ---------- weights ----------
        if model == "current":
            w = {a: phase(logistic(S[a])) for a, *_ in reps}
            wobs = {a: w[a] for a, *_ in reps}
            ai_conf = sum(r for *_, r in reps) / len(reps)
        else:
            w = {a: weight_field(a, S, edge, P) for a, *_ in reps}
            # the AI's assessment of each photo is an edge on that observation: evidence scales it
            wobs = {a: w[a] * rel for a, _, _, rel in reps}
            tot = sum(w.values()) or 1e-9
            ai_conf = sum(w[a] * rel for a, _, _, rel in reps) / tot     # trust-weighted, not a flat mean
        tally = defaultdict(float)
        for a, said, *_ in reps: tally[said] += wobs[a]
        claim = max(tally, key=lambda k: (tally[k], repr(k)))
        W = sum(tally.values()) or 1e-9
        margin = (tally[claim] - (W - tally[claim])) / W                 # -1..1: how decisive the field is
        # ---------- status: AI + human (critical lane) ----------
        shows = Counter(s for _, _, s, _ in reps if s != "junk")
        seen = shows.most_common(1)[0][0] if shows else None
        human = "RATIFY" if ((seen and STATES[seen] == claim) or u_stamp < 0.15) else "REJECT"
        if model == "current":
            if ai_conf < 0.82: status = "INVESTIGATING"
            elif human == "REJECT": status = "UNDECIDED"
            else: status = "VERIFIED_TRUE"
        else:
            # confidence of the truth: evidence (trust-weighted AI) x decisiveness x mass of the field
            Mbar = P["mass_scale"] * (sum(weight_field(a, S, edge, P) for a in agents) / len(agents))
            mass = 1 - math.exp(-max(0.0, tally[claim] - (W - tally[claim])) / (Mbar or 1e-9))
            conf = ai_conf * mass
            if human == "REJECT": status = "UNDECIDED" if conf >= 0.5 else "INVESTIGATING"
            elif conf >= 0.5: status = "VERIFIED_TRUE"
            else: status = "INVESTIGATING"
        stats[status] += 1
        right = claim == STATES[truth]
        if status == "VERIFIED_TRUE": stats["verified right" if right else "verified WRONG"] += 1
        # ---------- settlement ----------
        if status == "VERIFIED_TRUE":
            q = 90.0
            if model == "current":
                for a, said, *_ in reps:
                    S[a] = min(1000, max(0, S[a] + (3 if said == claim else -5) * math.log(1 + q)))
                    if said != claim and said == STATES[truth]: minority_hits += 1
                for v in ("AI", "VAL"): S[v] = min(1000, S[v] + 3 * math.log(1 + q))
            elif model == "field2":
                for a, said, _, rel in reps:
                    agree = 1 if said == claim else -1
                    X[a] += P["alpha2"] * margin * agree
                    if agree < 0 and said == STATES[truth]: minority_hits += 1
                # assessors are credited for work: how contested the case was, signed by whether their
                # vote matched the outcome (the AI's vote: ratify if its trust-weighted relevance cleared the bar)
                work = 1 - abs(margin)
                X["AI"] += P["alpha2"] * work * (1 if ai_conf >= 0.82 else -1)
                X["VAL"] += P["alpha2"] * work * (1 if human == "RATIFY" else -1)
            else:
                for a, said, _, rel in reps:
                    agree = 1 if said == claim else -1
                    # whitepaper 17.1: dS = K tanh(alpha * Delta) - beta (S - S0); Delta scaled by how decisive
                    # the field was, so a contested outcome moves nobody much
                    d = P["K"] * math.tanh(P["alpha"] * margin * agree)
                    S[a] = min(1000, max(0, S[a] + d))
                    if agree < 0 and said == STATES[truth] and d < -1: minority_hits += 1
                for v in ("AI", "VAL"): S[v] = min(1000, max(0, S[v] + P["K"] * math.tanh(P["alpha"] * margin)))
        if model != "current":
            # agreement graph (whitepaper 17.2): COLLABORATE / CONFLICT edges from co-assertions
            for key in list(edge): edge[key] *= (1 - P.get("evap", 0.0))   # pheromone evaporation
            for i, (a, sa, *_) in enumerate(reps):
                for b, sb, *_ in reps[i + 1:]:
                    x = 1.0 if sa == sb else -1.0
                    edge[(a, b)] += x; edge[(b, a)] += x
            if model == "field2":
                x0 = math.log(P["S0"] / (1000 - P["S0"]))              # relax toward the newcomer baseline
                for a in list(X): X[a] = x0 + (X[a] - x0) * (1 - P["beta2"]); S[a] = 1000 / (1 + math.exp(-X[a]))
            else:
                for a in list(S): S[a] -= P["beta"] * (S[a] - P["S0"])        # relaxation toward baseline
        if n % 30 == 0:
            for a in agents: traj[a].append(S[a])
            traj["AI"].append(S["AI"])
    return stats, traj, minority_hits, S

TOPOLOGY = """
w_i = phi(S_i) * m_i
  phi(S) = S                      smooth, proportional (the phase curve is emergent from S's own dynamics)
  m_i    = independence of i's corroboration in the agreement graph:
           (sum_j max(A_ij,0) * n_j) / (sum_j |A_ij| * n_j + k),   n_j = 1 / (1 + positive partners of j)
"""

def weight_field(a, S, edge, P):
    pos = [(b, x) for (u, b), x in edge.items() if u == a]
    if not pos: return S[a] * P["m0"]
    num = den = 0.0
    for b, x in pos:
        n_b = 1.0 / (1 + sum(1 for (u, c), y in edge.items() if u == b and y > 0))
        num += max(x, 0) * (1 - n_b); den += abs(x)
    m = (num + P["m0"] * P["k"]) / (den + P["k"])
    return S[a] * m

if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    P = {"K": 25.0, "alpha": 2.0, "beta": 0.002, "S0": 200.0, "m0": 0.5, "k": 3.0, "mass_scale": 0.5}
    master = SystemRandom()
    P.update({"alpha2": 0.15, "beta2": 0.02})
    totals = {m: Counter() for m in ("current", "field2")}
    finals = {m: defaultdict(list) for m in totals}
    minority = Counter()
    for s in range(seeds):
        seed = master.getrandbits(64)
        agents, kind, events = world(Random(seed), hours)
        for m in totals:
            stats, traj, mh, S = run(m, agents, kind, events, P)
            totals[m].update(stats); minority[m] += mh
            for a in agents: finals[m][kind[a]].append(S[a])
            finals[m]["AI"].append(S["AI"])
    for m in totals:
        t = totals[m]; v = t["VERIFIED_TRUE"]
        print(f"\n== {m}: {seeds} worlds x {hours} h")
        print(f"   verified {v}  right {t['verified right']}  WRONG {t['verified WRONG']} ({100*t['verified WRONG']/max(1,v):.1f}%)  stuck {t['INVESTIGATING']}  undecided {t['UNDECIDED']}  honest reporters penalised for being right {minority[m]}")
        print("   final standing: " + "  ".join(f"{k} {sum(x)/len(x):.0f}" for k, x in finals[m].items()))
