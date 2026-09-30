"""
Evolutionary search over trust physics for Kaori Flow.

A genome picks one natural law for each slot, plus its constants. Genomes breed and mutate; fitness is
measured on fresh random worlds each generation (so nothing is tuned to one world), and the winners
are finally judged on harsher worlds they never saw.

Slots and candidate laws
  dyn      how standing moves when a truth settles, and how it fades
           additive   - today's Kaori: +c / -1.67c, clamped, linear fade          (engineering baseline)
           pheromone  - latent trail x, S = 1000 sigmoid(x); reinforce, evaporate   (ant trails, Physarum)
           magnet     - S += K tanh(a*drive), linear fade                          (whitepaper 17.1, magnetisation)
           bayes      - Beta(a, b) evidence counts that are slowly forgotten       (Bayesian memory, radioactive decay)
           replicator - S grows with fitness above the group's mean               (evolutionary game theory)
  couple   what drives an observer's change
           flat       - every agreement counts the same
           margin     - scaled by how decisive the weighted field was             (force ~ field strength)
           surprise   - right when others were wrong earns more; wrong against a clear field costs more (information)
  weight   standing -> influence in the vote
           linear | phase (today) | power S^g (scale-free) | boltzmann exp(S/T) (thermal)
  evidence the AI's per-photo assessment
           flatmean   - today: AI averages all photos, weights untouched (one junk photo can block)
           linear     - weight x relevance, AI confidence trust-weighted
           power      - weight x relevance^k
  topo     independence of a witness
           none | codissent (immune memory: pairs that are repeatedly wrong together screen each other)
  nucleate how much support a truth needs to exist
           none | critical (1 - exp(-net / (kappa * typical weight)) >= 1/2, self-scaling like a critical nucleus)

World: 6 places, 4 observed per hour, weather persists hour to hour (Markov). 22 agents:
  honest    careful x6, sloppy x3 (30% one band off), lazy x2 (copy what they said here last time)
  hostile   liar x2 (true photo, false value), faker (junk or a photo of another sky),
            ring x3 (move together, same fake), sybil swarm x4 (move together, fake, and re-register as
            fresh identities every 60 h), infiltrator (careful for 60% of the run, then fakes)
AI per-photo relevance follows what the real CLIP model measured; a photo of another sky fools it.
Validator: rejects when the claim does not match what most photos show; rubber-stamps 15%.
"""
import math, random, sys, json, time
from collections import Counter, defaultdict
from multiprocessing import Pool

STATES = ["clear", "few", "scattered", "broken", "overcast"]
SLOTS = {
    "dyn": ["additive", "pheromone", "magnet", "bayes", "replicator"],
    "couple": ["flat", "margin", "surprise"],
    "weight": ["linear", "phase", "power", "boltzmann"],
    "evidence": ["flatmean", "linear", "power"],
    "topo": ["none", "codissent", "flocking", "both"],
    "field": ["none", "continuity", "triggered"],
    "nucleate": ["none", "critical", "jeans", "quorum"],
}
RANGES = {"alpha": (0.02, 0.6), "beta": (0.0, 0.06), "gamma": (0.5, 3.0), "T": (40.0, 400.0),
          "k": (0.5, 4.0), "lam": (0.0, 3.0), "kappa": (0.2, 3.0), "mu": (0.0, 4.0), "J": (0.0, 3.0), "tau": (1.0, 24.0),
          "phi": (0.0, 0.9), "T0": (0.05, 1.0), "a_j": (0.5, 3.0), "chi": (0.0, 3.0)}
TODAY = {"dyn": "additive", "couple": "flat", "weight": "phase", "evidence": "flatmean", "topo": "none",
         "nucleate": "none", "field": "none", "alpha": 0.15, "beta": 0.0, "gamma": 1.0, "T": 200.0, "k": 1.0, "lam": 0.0, "kappa": 1.0, "mu": 0.0, "J": 0.0, "tau": 6.0,
         "phi": 0.0, "T0": 0.3, "a_j": 1.5, "chi": 1.0}
HONEST = {"careful", "sloppy"}
HOSTILE = {"liar", "faker", "ring", "sybil", "infiltrator"}

# ------------------------------------------------------------------ the world
def make_world(seed, hours=400, harsh=False):
    R = random.Random(seed)
    mix = {"careful": 6, "sloppy": 3, "lazy": 2, "liar": 2, "faker": 1, "ring": 4 if harsh else 3,
           "sybil": 6 if harsh else 4, "infiltrator": 1}
    presence = {"careful": .5, "sloppy": .5, "lazy": .5, "liar": .6 if harsh else .4, "faker": .6 if harsh else .4,
                "ring": .6 if harsh else .45, "sybil": .5 if harsh else .35, "infiltrator": .6}
    whitewash = 40 if harsh else 60
    agents = [(k, i) for k, n in mix.items() for i in range(n)]
    sky = {p: R.randrange(5) for p in range(6)}
    rain = {p: False for p in range(6)}
    memory = {}
    events = []
    for t in range(hours):
        for p in sky:  # weather drifts
            if R.random() < 0.25: sky[p] = max(0, min(4, sky[p] + R.choice([-1, 1])))
            rain[p] = sky[p] == 4 and R.random() < 0.4
        live = R.sample(range(6), 4)
        ring_at, syb_at = R.choice(live), R.choice(live)
        ring_on, syb_on = R.random() < presence["ring"], R.random() < presence["sybil"]
        gen = t // whitewash
        at = defaultdict(list)
        for kind, i in agents:
            if kind == "ring":
                if ring_on: at[ring_at].append((kind, i))
            elif kind == "sybil":
                if syb_on: at[syb_at].append((kind, i))
            elif R.random() < presence[kind]:
                at[R.choice(live)].append((kind, i))
        for p in live:
            truth = (STATES[sky[p]], rain[p])
            fake_s = (sky[p] + R.choice([2, 3])) % 5
            fake = (STATES[fake_s], fake_s == 4 and R.random() < 0.5)
            reps = []
            for kind, i in at[p]:
                aid = f"{kind}{i}" + (f"g{gen}" if kind == "sybil" else "")
                shows, rel = "truth", R.uniform(0.92, 1.0) if R.random() > 0.05 else R.uniform(0.78, 0.92)
                if kind == "careful" or (kind == "infiltrator" and t < 0.6 * hours):
                    said = truth
                elif kind == "sloppy":
                    s = sky[p]
                    if R.random() < 0.3: s = max(0, min(4, s + R.choice([-1, 1])))
                    said = (STATES[s], rain[p] if R.random() > 0.1 else not rain[p])
                elif kind == "lazy":
                    said = memory.get((aid, p), (STATES[R.randrange(5)], False))
                elif kind == "liar":
                    said = (R.choice([x for x in STATES if x != truth[0]]), R.random() < 0.3)
                elif kind == "faker" and R.random() < 0.5:
                    said, shows, rel = (STATES[R.randrange(5)], R.random() < 0.3), "junk", R.uniform(0.0, 0.71)
                else:  # faker (other sky), ring, sybil, infiltrator after the turn: a consistent fake
                    said, shows = fake, "fake"
                memory[(aid, p)] = truth if kind == "lazy" else said
                reps.append((aid, kind, said, shows, rel))
            events.append((t, p, truth, fake, reps, R.random()))
    return events

# ------------------------------------------------------------------ laws
def sig(x): return 1 / (1 + math.exp(-max(-40, min(40, x))))

class Standing:
    def __init__(self, g):
        self.g = g; self.S = {}; self.x = {}; self.a = {}; self.b = {}
    def get(self, a):
        return self.S.get(a, 200.0)
    def settle(self, drives):  # drives: list of (agent, d) with d in [-1, 1]
        g, dyn, al = self.g, self.g["dyn"], self.g["alpha"]
        if dyn == "replicator":
            fbar = sum(d for _, d in drives) / max(1, len(drives))
        for a, d in drives:
            S = self.get(a)
            if dyn == "additive":
                S += (13.5 if d > 0 else 22.5) * d * (al / 0.15)
            elif dyn == "pheromone":
                x = self.x.get(a, math.log(200 / 800)) + al * d * 3; self.x[a] = x; S = 1000 * sig(x)
            elif dyn == "magnet":
                S += 40 * math.tanh(al * d * 6)
            elif dyn == "bayes":
                if d > 0: self.a[a] = self.a.get(a, 0) + d * al * 6
                else: self.b[a] = self.b.get(a, 0) - d * al * 6
                A, B = self.a.get(a, 0), self.b.get(a, 0); S = 1000 * (A + 2) / (A + B + 10)
            elif dyn == "replicator":
                S *= 1 + al * (d - fbar)
            self.S[a] = min(1000.0, max(0.5, S))
    def fade(self):
        bt = self.g["beta"]
        if bt <= 0: return
        dyn = self.g["dyn"]
        x0 = math.log(200 / 800)
        for a in list(self.S):
            if dyn == "pheromone":
                self.x[a] = x0 + (self.x.get(a, x0) - x0) * (1 - bt); self.S[a] = 1000 * sig(self.x[a])
            elif dyn == "bayes":
                self.a[a] = self.a.get(a, 0) * (1 - bt); self.b[a] = self.b.get(a, 0) * (1 - bt)
                self.S[a] = 1000 * (self.a[a] + 2) / (self.a[a] + self.b[a] + 10)
            else:
                self.S[a] += bt * (200 - self.S[a])

def weight_of(S, g):
    w = g["weight"]
    if w == "linear": return S
    if w == "phase":
        E = 1000 / (1 + math.exp(-0.01 * (S - 500)))
        return E * 0.1 if E < 200 else (850 + (E - 850) * 0.3 if E > 850 else E)
    if w == "power": return 1000 * (S / 1000) ** g["gamma"]
    return math.exp(min(60, S / g["T"]))

# ------------------------------------------------------------------ one run
def run(g, events, harsh_note=False):
    st = Standing(g)
    co_n, co_d = defaultdict(float), defaultdict(float)   # pair co-occurrence, pair co-dissent (immune memory)
    seen_n = defaultdict(float)                           # how often each agent has reported
    last_seen = {}                                        # agent -> last hour they reported
    last_truth = {}                                       # place -> (hour, claim) of the last verified truth
    out = Counter(); honest_hurt = 0.0; last_t = -1
    for t, p, truth, fake, reps, u in events:
        if t != last_t:
            for _ in range(t - last_t if last_t >= 0 else 0): st.fade()
            last_t = t
        if len(reps) < 3:
            out["too few"] += 1; continue
        out["eligible"] += 1
        ids = [r[0] for r in reps]
        w = {a: weight_of(st.get(a), g) for a in ids}
        if g["topo"] in ("codissent", "both") and g["lam"] > 0:
            for a in ids:
                pres = sum(co_d[(a, b)] / (co_n[(a, b)] + 1) for b in ids if b != a)
                w[a] *= math.exp(-g["lam"] * pres)
        if g["topo"] in ("flocking", "both") and g["mu"] > 0:
            # screening: a witness who keeps arriving with the same companions is not independent of them.
            # excess co-presence over chance (~1/4 for 4 live places) shares their weight out
            for a in ids:
                ex = sum(max(0.0, (co_n[(a, b)] + 0.25) / (seen_n[a] + 1) - 0.25) for b in ids if b != a)
                w[a] *= math.exp(-g["mu"] * ex)
        rel = {r[0]: r[4] for r in reps}
        if g["evidence"] == "flatmean":
            wv = dict(w); ai = sum(rel.values()) / len(rel)
        else:
            k = g["k"] if g["evidence"] == "power" else 1.0
            wv = {a: w[a] * rel[a] ** k for a in ids}
            tot = sum(w.values()) or 1e-12
            ai = sum(w[a] * rel[a] for a in ids) / tot
        tally = defaultdict(float)
        for aid, kind, said, shows, r in reps: tally[said] += wv[aid]
        claim = max(tally, key=lambda s: (tally[s], s))
        W = sum(tally.values()) or 1e-12
        margin = (2 * tally[claim] - W) / W
        # status (critical lane: AI and a human both needed)
        shown = Counter(truth if s == "truth" else fake for _, _, _, s, _ in reps if s != "junk")
        seen = shown.most_common(1)[0][0] if shown else None
        human = seen == claim or u < 0.15
        ok_mass = True
        if g["field"] == "continuity" and p in last_truth and g["J"] > 0:
            # Ising-like coupling to the last verified truth here: a far jump needs more support
            th, prev = last_truth[p]
            jump = abs(STATES.index(claim[0]) - STATES.index(prev[0])) / 4 + (0.25 if claim[1] != prev[1] else 0)
            ai *= math.exp(-g["J"] * jump * math.exp(-(t - th) / g["tau"]))
        if g["nucleate"] != "none":
            # every nucleation law is measured against the network, not the truth's own participants:
            # the typical weight of agents active in the last 48 h
            recent = [a for a, tt in last_seen.items() if t - tt <= 48]
            typical = (sum(weight_of(st.get(a), g) for a in recent) / max(1, len(recent))) or 1e-12
            net = max(0.0, 2 * tally[claim] - W)
            need = g["kappa"] * typical
            if g["field"] == "triggered" and p in last_truth:
                # triggered star formation: a recent verified truth here lowers the barrier for a
                # consistent one (same state), fading with time
                th, prev = last_truth[p]
                if prev == claim: need *= 1 - g["phi"] * math.exp(-(t - th) / g["tau"])
            if g["nucleate"] == "critical":
                ok_mass = 1 - math.exp(-min(50.0, net / need)) >= 0.5
            elif g["nucleate"] == "jeans":
                # Jeans collapse: M > M_J ~ T^a / sqrt(rho). Temperature = disagreement in the field
                # (1 - winning share), density = independent witnesses here relative to three
                temp = 1 - tally[claim] / W
                rho = len(ids) / 3
                m_j = need * (temp + g["T0"]) ** g["a_j"] / math.sqrt(rho)
                ok_mass = tally[claim] >= m_j
            elif g["nucleate"] == "quorum":
                # honeybee nest choice: support for the winner minus cross-inhibition from every rival
                # option must reach a quorum
                rivals = W - tally[claim]
                ok_mass = tally[claim] - g["chi"] * rivals >= need
        if ai < 0.82 or not ok_mass: out["stuck"] += 1; verified = False
        elif not human: out["undecided"] += 1; verified = False
        else: verified = True
        for a in ids: seen_n[a] += 1; last_seen[a] = t
        for a in ids:
            for b in ids:
                if a != b: co_n[(a, b)] += 1
        if verified:
            last_truth[p] = (t, claim)
            right = claim == truth
            out["right" if right else "WRONG"] += 1
            if not right:
                kinds = {k for _, k, s, _, _ in reps if s == claim}
                for k in kinds & HOSTILE: out["won:" + k] += 1
            drives = []
            for aid, kind, said, shows, r in reps:
                agree = 1 if said == claim else -1
                if g["couple"] == "flat": d = agree
                elif g["couple"] == "margin": d = agree * max(0.0, margin)
                else:
                    share = tally[said] / W
                    d = (1 - share) if agree > 0 else -tally[claim] / W
                drives.append((aid, d))
                if kind in HONEST and said == truth and d < 0: honest_hurt += -d
            st.settle(drives)
            for aid, _, said, _, _ in reps:
                for bid, _, said_b, _, _ in reps:
                    if aid != bid and said != claim and said_b != claim and said == said_b: co_d[(aid, bid)] += 1
    # separation of honest vs hostile by final standing (AUC)
    fin = defaultdict(list)
    for t, p, truth, fake, reps, u in events[-1:]:
        pass
    seen_agents = {}
    for _, _, _, _, reps, _ in events:
        for aid, kind, *_ in reps: seen_agents[aid] = kind
    hon = [st.get(a) for a, k in seen_agents.items() if k in HONEST]
    hos = [st.get(a) for a, k in seen_agents.items() if k in HOSTILE and not a.startswith("sybil")]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    tiers = {k: round(sum(st.get(a) for a, kk in seen_agents.items() if kk == k) / max(1, sum(1 for kk in seen_agents.values() if kk == k))) for k in ("careful", "sloppy", "lazy", "liar", "faker", "ring", "sybil", "infiltrator")}
    E = max(1, out["eligible"])
    return {"right": out["right"] / E, "wrong": out["WRONG"] / E, "stuck": out["stuck"] / E, "undecided": out["undecided"] / E,
            "hurt": honest_hurt / E, "auc": auc, "tiers": tiers, "won": {k[4:]: v for k, v in out.items() if k.startswith("won:")},
            "wrong_n": out["WRONG"], "right_n": out["right"], "eligible": E}

def fitness(m):
    # right truths are the goal; a wrong truth costs ten right ones; honest reporters must not be hurt;
    # honest and hostile agents should end up clearly apart
    return m["right"] - 10 * m["wrong"] - 0.5 * m["hurt"] + 0.3 * m["auc"]

def evaluate(args):
    g, seeds, harsh = args
    ms = [run(g, make_world(s, harsh=harsh)) for s in seeds]
    avg = {k: sum(m[k] for m in ms) / len(ms) for k in ("right", "wrong", "stuck", "undecided", "hurt", "auc")}
    avg["tiers"] = {k: round(sum(m["tiers"][k] for m in ms) / len(ms)) for k in ms[0]["tiers"]}
    won = Counter()
    for m in ms: won.update(m["won"])
    avg["won"] = dict(won)
    avg["fit"] = fitness(avg)
    return avg

# ------------------------------------------------------------------ evolution
def random_genome(R):
    g = {s: R.choice(v) for s, v in SLOTS.items()}
    g.update({p: R.uniform(*r) for p, r in RANGES.items()})
    return g

def mutate(g, R, rate=0.25):
    g = dict(g)
    for s, v in SLOTS.items():
        if R.random() < rate / 2: g[s] = R.choice(v)
    for p, (lo, hi) in RANGES.items():
        if R.random() < rate: g[p] = min(hi, max(lo, g[p] + R.gauss(0, (hi - lo) * 0.15)))
    return g

def cross(a, b, R):
    return {k: (a[k] if R.random() < 0.5 else b[k]) for k in a}

def evolve(pop_n=32, gens=18, worlds=3, seed=None):
    R = random.Random(seed)
    pop = [random_genome(R) for _ in range(pop_n - 2)] + [dict(TODAY)] + [dict(TODAY, dyn="pheromone", couple="margin", weight="linear", evidence="linear", nucleate="critical", alpha=0.15, beta=0.02, kappa=1.0)]
    history = []
    with Pool(4) as pool:
        for gen in range(gens):
            seeds = [R.getrandbits(48) for _ in range(worlds)]  # fresh worlds every generation
            scores = pool.map(evaluate, [(g, seeds, False) for g in pop])
            ranked = sorted(zip(scores, pop), key=lambda x: -x[0]["fit"])
            best = ranked[0]
            history.append((gen, best[0]["fit"], {k: best[1][k] for k in SLOTS}))
            print(f"gen {gen:2}  best {best[0]['fit']:.3f}  right {best[0]['right']:.2f} wrong {best[0]['wrong']:.3f} auc {best[0]['auc']:.2f}  "
                  + " ".join(best[1][k] for k in SLOTS), flush=True)
            elite = [g for _, g in ranked[:6]]
            nxt = [dict(g) for g in elite]
            while len(nxt) < pop_n:
                a, b = R.sample(ranked[:14], 2)
                nxt.append(mutate(cross(a[1], b[1], R), R))
            pop = nxt
    return pop, history

if __name__ == "__main__":
    t0 = time.time()
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    finalists = []
    for r in range(runs):
        print(f"\n### evolution run {r + 1}")
        pop, hist = evolve(seed=random.SystemRandom().getrandbits(48))
        finalists += pop[:3]
    # held-out judgement: harsher worlds nobody evolved on
    test = [random.SystemRandom().getrandbits(48) for _ in range(6)]
    field2 = dict(TODAY, dyn="pheromone", couple="margin", weight="linear", evidence="linear", nucleate="critical", alpha=0.15, beta=0.02, kappa=1.0)
    cands = [("today", TODAY), ("hand-built law", field2)] + [(f"evolved {i+1}", g) for i, g in enumerate(finalists)]
    with Pool(4) as pool:
        res = pool.map(evaluate, [(g, test, True) for _, g in cands])
    print("\n### held-out harsh worlds (6 x 400 h, bigger ring and swarm, faster whitewashing)")
    for (name, g), m in zip(cands, res):
        print(f"\n{name:15} fit {m['fit']:.3f} | right {m['right']:.2f} wrong {m['wrong']:.3f} stuck {m['stuck']:.2f} undecided {m['undecided']:.2f} honest-hurt {m['hurt']:.3f} AUC {m['auc']:.2f}")
        print("   laws: " + ", ".join(f"{k}={g[k]}" for k in SLOTS) + " | " + ", ".join(f"{k}={g[k]:.2f}" for k in RANGES))
        print("   standing: " + " ".join(f"{k} {v}" for k, v in m["tiers"].items()) + " | wrong truths won by: " + json.dumps(m["won"]))
    json.dump([(n, g, m) for (n, g), m in zip(cands, res)], open("evo-result.json", "w"), indent=1, default=str)
    print(f"\n{time.time() - t0:.0f}s")
