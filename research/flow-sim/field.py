"""
Kaori Flow as one multiplex field, in a world with hidden physics.

The world (never shown to Kaori)
  A hexagonal map 16 x 10. A cloud field is carried by a wind at a steady speed; new weather flows in at
  the upwind edge. Halfway through the run the wind turns. People live in towns; they report the sky
  over their town (sky cover band, raining). Honest agents: careful, sloppy, lazy. Hostile: liars, a
  faker, a ring and a swarm that move together with consistent fakes. Identities are costly (no
  re-registering).

Kaori (three layers, one field)
  witness layer   standing per agent (Bayesian evidence counts that are slowly forgotten), influence
                  saturates (Rule 6), flocking and co-dissent screening (Rule 4)
  observation     agents -> TruthKeys (town, hour); weight = influence x AI photo relevance
  reality layer   TruthKey -> TruthKey couplings J[a, b, lag], learned Hebbian-style from verified truths
                  (strengthen when two towns agree more than chance at that lag, evaporate otherwise)
  truth formation Jeans collapse: needed mass grows with disagreement ("temperature"); the reality
                  layer's prediction cools or heats the field (learned physics helps the next truth form)

Measured
  truth accuracy and yield, with and without the reality feedback
  physics recovered: the wind vector read off the strongest learned couplings, against the hidden wind,
  before and after the turn
"""
import math, random, sys
from collections import Counter, defaultdict

W, H = 16, 10
BANDS = ["clear", "few", "scattered", "broken", "overcast"]

def xy(q, r): return (math.sqrt(3) * (q + r / 2), 1.5 * r)

# ------------------------------------------------------------------ the hidden world
class World:
    def __init__(self, R, hours, wind1, wind2):
        self.R, self.hours, self.winds = R, hours, (wind1, wind2)
        self.f = {(q, r): self._blob(q, r) for q in range(W) for r in range(H)}
        # towns spread over the map; each has its own residents
        self.towns = [(2, 1), (6, 2), (10, 1), (13, 3), (3, 5), (8, 5), (12, 6), (1, 8), (6, 8), (11, 8)]
    def _blob(self, q, r):
        return 2 + 1.8 * math.sin(q * 0.7 + self.R.random() * 6) * math.cos(r * 0.6 + self.R.random() * 6)
    def wind(self, t): return self.winds[0] if t < self.hours // 2 else self.winds[1]
    def step(self, t):
        dq, dr = self.wind(t)
        if not hasattr(self, "systems"):
            # weather arrives as systems: a few smooth waves with random phases that drift slowly
            self.systems = [(self.R.uniform(0.3, 0.9), self.R.uniform(0, 6.3), self.R.uniform(0.02, 0.08)) for _ in range(3)]
        new = {}
        for (q, r) in self.f:
            src = (q - dq, r - dr)
            if src in self.f:
                v = self.f[src]
            else:  # inflow at the upwind edge: coherent along the edge and in time
                s = q * dr + r * dq
                # systems grow and fade in place (standing waves): no sideways drift of the patterns
                v = 2 + sum(1.3 * math.sin(w * t + ph) * math.sin(k * s + ph * 1.7) for k, ph, w in self.systems)
            new[(q, r)] = min(4.4, max(-0.4, v + self.R.gauss(0, 0.2)))
        self.f = new
    def truth(self, cell):
        v = self.f[cell]
        return (BANDS[min(4, max(0, round(v)))], v > 3.7)

# ------------------------------------------------------------------ Kaori as a multiplex field
class Kaori:
    def __init__(self, P, towns, feedback=True):
        self.P, self.towns, self.feedback = P, towns, feedback
        self.A, self.B = defaultdict(float), defaultdict(float)       # evidence counts per agent
        self.co_n, self.co_d, self.seen = defaultdict(float), defaultdict(float), defaultdict(float)
        self.last_seen = {}
        self.J = defaultdict(float)                                    # reality layer: (a, b, lag) -> coupling
        self.verified = {}                                             # (town, hour) -> band index
        self.mu, self.var = {}, {}                                     # each town's running mean and variance
    def standing(self, a): return 1000 * (self.A[a] + 2) / (self.A[a] + self.B[a] + 10)
    def influence(self, a): return 1000 * math.tanh(self.standing(a) / self.P["sat"])
    def fade(self):
        k = 1 - self.P["beta"]
        for d in (self.A, self.B):
            for a in d: d[a] *= k
        ev = 1 - self.P["evap"]
        for e in self.J: self.J[e] *= ev
    def corr(self, a, b, lag):
        c = self.J.get((a, b, lag), 0.0)
        return c / math.sqrt((self.var.get(a, 1.0) or 1e-9) * (self.var.get(b, 1.0) or 1e-9))
    def predict(self, town, t):
        """The reality layer's forecast: a regression on verified truths upstream in time, as a band distribution."""
        mu_b = self.mu.get(town, 2.0)
        num = den = 0.0
        for a in self.towns:
            for lag in range(1, self.P["maxlag"] + 1):
                if (a, t - lag) not in self.verified: continue
                r = self.corr(a, town, lag)
                if r <= 0.2: continue
                x = self.verified[(a, t - lag)] - self.mu.get(a, 2.0)
                num += r * r * x; den += r * r
        if den == 0: return None
        centre = mu_b + num / den
        weights = {k: math.exp(-((k - centre) ** 2) / 2) for k in range(5)}
        z = sum(weights.values())
        return {k: v / z for k, v in weights.items()}
    def learn(self, town, t, band):
        """The reality layer as a fading covariance field over (town, town, lag)."""
        g = self.P["eta"]
        self.mu[town] = self.mu.get(town, 2.0) + g * (band - self.mu.get(town, 2.0))
        self.var[town] = self.var.get(town, 1.0) + g * ((band - self.mu[town]) ** 2 - self.var.get(town, 1.0))
        for lag in range(0, self.P["maxlag"] + 1):
            for a in self.towns:
                if a == town and lag == 0: continue
                if (a, t - lag) in self.verified:
                    prod = (self.verified[(a, t - lag)] - self.mu.get(a, 2.0)) * (band - self.mu[town])
                    key = (a, town, lag)
                    self.J[key] = self.J.get(key, 0.0) + g * (prod - self.J.get(key, 0.0))
    def compile(self, town, t, reps, u):
        P = self.P
        ids = [r[0] for r in reps]
        w = {a: self.influence(a) for a in ids}
        for a in ids:  # topology of the witness layer
            flock = sum(max(0.0, (self.co_n[(a, b)] + 0.25) / (self.seen[a] + 1) - 0.25) for b in ids if b != a)
            dis = sum(self.co_d[(a, b)] / (self.co_n[(a, b)] + 1) for b in ids if b != a)
            w[a] *= math.exp(-P["mu"] * flock - P["lam"] * dis)
        rel = {r[0]: r[4] for r in reps}
        wv = {a: w[a] * rel[a] for a in ids}
        tot = sum(w.values()) or 1e-12
        ai = sum(w[a] * rel[a] for a in ids) / tot
        tally = defaultdict(float)
        for aid, kind, said, shows, r_ in reps: tally[said] += wv[aid]
        claim = max(tally, key=lambda s: (tally[s], s))
        Wt = sum(tally.values()) or 1e-12
        # Jeans collapse, with the reality layer heating or cooling the field
        recent = [a for a, tt in self.last_seen.items() if t - tt <= 48]
        typical = (sum(self.influence(a) for a in recent) / max(1, len(recent))) or 1e-12
        temp = 1 - tally[claim] / Wt
        pred = self.predict(town, t) if self.feedback else None
        if pred:
            p_claim = pred.get(BANDS.index(claim[0]), 0.0)
            temp = max(0.0, temp + P["zeta"] * (0.2 - p_claim))   # against chance among five bands
        m_j = P["kappa"] * typical * (temp + P["T0"]) ** P["a_j"] / math.sqrt(len(ids) / 3)
        formed = ai >= 0.82 and tally[claim] >= m_j
        for a in ids:
            self.seen[a] += 1; self.last_seen[a] = t
            for b in ids:
                if a != b: self.co_n[(a, b)] += 1
        return claim, formed, tally, Wt
    def settle(self, town, t, claim, reps, tally, Wt):
        for aid, kind, said, shows, r_ in reps:
            if said == claim: self.A[aid] += 1 - tally[said] / Wt + 0.1
            else: self.B[aid] += tally[claim] / Wt
        for aid, _, said, _, _ in reps:
            for bid, _, said_b, _, _ in reps:
                if aid != bid and said != claim and said == said_b: self.co_d[(aid, bid)] += 1
        band = BANDS.index(claim[0])
        self.verified[(town, t)] = band
        self.learn(town, t, band)
    def wind_estimate(self):
        """Beamforming, as seismic and radio arrays do. Transport shows as the antisymmetric part of lagged
        correlation (A now predicts B later better than B now predicts A later). For every candidate
        flow v, predict the travel time between every pair of towns and add up how well the observed
        flux agrees; the flow that explains all pairs together wins."""
        best, best_v = -1e9, (0.0, 0.0)
        maxlag = self.P["maxlag"]
        pairs = [(a, b, xy(*b)[0] - xy(*a)[0], xy(*b)[1] - xy(*a)[1]) for a in self.towns for b in self.towns if a != b]
        for deg in range(0, 360, 5):
            ux, uy = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            for speed in (0.8, 1.2, 1.73, 2.5, 3.5):
                score = 0.0
                for a, b, dx, dy in pairs:
                    tau = (dx * ux + dy * uy) / speed          # hours for the flow to carry a's sky to b
                    lag = round(tau)
                    if 1 <= lag <= maxlag and abs(tau - lag) < 0.5:
                        score += self.corr(a, b, lag) - self.corr(b, a, lag)
                if score > best: best, best_v = score, (ux * speed, uy * speed)
        return best_v

# ------------------------------------------------------------------ agents
def residents(R):
    kinds = {"careful": 30, "sloppy": 12, "lazy": 6, "liar": 6, "faker": 3}
    people = []
    for k, n in kinds.items():
        for i in range(n): people.append((f"{k}{i}", k))
    return people

def angle(v):
    return math.degrees(math.atan2(v[1], v[0]))

def run(seed, hours=600, feedback=True, P=None, hostile=True, quiet=False):
    R = random.Random(seed)
    P = P or {"sat": 250.0, "beta": 0.004, "evap": 0.01, "eta": 0.05, "maxlag": 6, "mu": 2.5, "lam": 1.2,
              "kappa": 0.9, "T0": 0.3, "a_j": 1.5, "zeta": 0.8}
    wind1, wind2 = (1, 0), (0, 1)  # east, then turning to south-east-ish (down the map)
    world = World(R, hours, wind1, wind2)
    K = Kaori(P, world.towns, feedback)
    people = residents(R)
    home = {a: R.choice(world.towns) for a, _ in people}
    ring = [f"ring{i}" for i in range(3)]; swarm = [f"swarm{i}" for i in range(4)]
    out = Counter(); wind_log = []
    memory = {}
    for t in range(hours):
        world.step(t)
        at = defaultdict(list)
        for a, k in people:
            if R.random() < 0.55: at[home[a]].append((a, k))
        if hostile:
            if R.random() < 0.45: at[R.choice(world.towns)] += [(a, "ring") for a in ring]
            if R.random() < 0.35: at[R.choice(world.towns)] += [(a, "swarm") for a in swarm]
        for town in world.towns:
            if len(at[town]) < 3: continue
            truth = world.truth(town)
            fb = (BANDS.index(truth[0]) + R.choice([2, 3])) % 5
            fake = (BANDS[fb], fb == 4)
            reps = []
            for a, k in at[town]:
                rel, shows = R.uniform(0.92, 1.0), "truth"
                if k == "careful": said = truth
                elif k == "sloppy":
                    i = BANDS.index(truth[0])
                    if R.random() < 0.3: i = min(4, max(0, i + R.choice([-1, 1])))
                    said = (BANDS[i], truth[1])
                elif k == "lazy": said = memory.get(a, truth)
                elif k == "liar": said = (R.choice([b for b in BANDS if b != truth[0]]), R.random() < 0.3)
                elif k == "faker" and R.random() < 0.5: said, shows, rel = (R.choice(BANDS), False), "junk", R.uniform(0, 0.71)
                else: said, shows = fake, "fake"
                memory[a] = said
                reps.append((a, k, said, shows, rel))
            out["eligible"] += 1
            claim, formed, tally, Wt = K.compile(town, t, reps, R.random())
            shown = Counter(truth if s == "truth" else fake for *_, s, _ in [(r[0], r[1], r[2], r[3], r[4]) for r in reps] if s != "junk")
            human = (shown.most_common(1)[0][0] == claim if shown else False) or R.random() < 0.15
            if formed and human:
                out["right" if claim == truth else "WRONG"] += 1
                K.settle(town, t, claim, reps, tally, Wt)
            else:
                out["stuck"] += 1
        K.fade()
        if t % 50 == 49:
            est = K.wind_estimate(); tw = xy(*world.wind(t)); tw = (tw[0], tw[1])
            err = (angle(est) - angle(tw) + 180) % 360 - 180
            wind_log.append((t + 1, est, tw, err))
    E = max(1, out["eligible"])
    hon = [K.standing(a) for a, k in people if k in ("careful", "sloppy")]
    hos = [K.standing(a) for a in ring + swarm] + [K.standing(a) for a, k in people if k in ("liar", "faker")]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    return {"right": out["right"] / E, "wrong": out["WRONG"] / E, "stuck": out["stuck"] / E, "auc": auc, "wind": wind_log, "K": K, "world": world}

if __name__ == "__main__":
    seeds = [random.SystemRandom().getrandbits(48) for _ in range(int(sys.argv[1]) if len(sys.argv) > 1 else 3)]
    for fb in (False, True):
        rs = [run(s, feedback=fb) for s in seeds]
        n = len(rs)
        print(f"\n== reality feedback {'ON ' if fb else 'OFF'}: right {sum(r['right'] for r in rs)/n:.3f}  wrong {sum(r['wrong'] for r in rs)/n:.4f}  "
              f"stuck {sum(r['stuck'] for r in rs)/n:.3f}  AUC {sum(r['auc'] for r in rs)/n:.2f}")
    print("\nwind read off the reality layer (hidden wind: east until hour 300, then turns 60 degrees down the map)")
    print(f"{'hour':>5}  {'hidden wind':>12}  " + "  ".join(f"{'world '+str(i+1)+' estimate':>22}" for i in range(len(rs))))
    for k in range(len(rs[0]["wind"])):
        t, _, tw, _ = rs[0]["wind"][k]
        cells = []
        for r in rs:
            _, est, _, err = r["wind"][k]
            spd = math.hypot(*est) / math.hypot(*tw)
            cells.append(f"{angle(est):6.0f}° ({err:+4.0f}°) x{spd:.2f}")
        print(f"{t:>5}  {angle(tw):10.0f}°  " + "  ".join(f"{c:>22}" for c in cells))
