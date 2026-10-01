"""
Adaptive network: the laws are agents too (Rule 7 all the way down).

One graph and one Signal log. Several laws run on them side by side; each law is an agent with one standing
number (Rule 3) and its own reading of every other agent.

  law       = standing engine x screening
              engine     counted (record against settled neighbours) | stepped (S <- S + eta (outcome - S))
              screening  mass (divide by bonded mass) | contract at theta (bonds above theta merge, transitively)
                         | none
  compile   each key's belief is the standing-weighted mixture of the laws' beliefs; it settles when the mixture
            passes the stakes minimum lam/(1+lam). Every law then learns from that truth (same Signals).
  grading   a law's prediction for a key is graded by the next truth at the same place (within MEM_H hours),
            recompiled WITHOUT that law: a law is never graded on a truth it helped make. Outcome 1 exact,
            0.5 one step off. Selection: a law that beat the population mean on that truth moves toward 1000,
            one that trailed moves toward 0 (S <- S + eta (target - S)); a tie carries no information.
  evolution every FORK_H hours the leading law forks (copies its state, changes one component). A law below the
            dormant threshold (200) drops out of the compile but stays in the record. Nothing is deleted.
"""
import copy, json, math, random, time
from collections import Counter, defaultdict
import captcha as K, battle2 as B2, seed as S, trust as T, agents as A
from agents import VALS, D, WORTH, HOSTILE, form

FORK_H, DORMANT, ETA_L, S0_L, MAX_LAWS = 50, 200.0, 0.05, 500.0, 5
ENGINES = {"counted": B2.OneCounted, "stepped": B2.OneStepped}
SCREENS = ["mass", "contract 0.5", "contract 0.7", "contract 0.9", "none"]

class Screened:
    def _components(self):
        if getattr(self, "_root_ok", False): return
        th = self.theta; parent = {}
        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
            return x
        for key in set(self.nij) | set(self.mij):
            if S.Seed.a(self, *key) > th:
                ra, rb = find(key[0]), find(key[1])
                if ra != rb: parent[ra] = rb
        self._root = {x: find(x) for x in parent}; self._root_ok = True
    def a(self, i, j):
        if i == j: return 1.0
        if self.screen == "mass": return S.Seed.a(self, i, j)
        if self.screen == "none": return 0.0
        self._components()
        return 1.0 if self._root.get(i, i) == self._root.get(j, j) else 0.0
    def fade(self, hour):
        super().fade(hour); self._root_ok = False

_CLS = {}
def make_law(engine, screen, opts):
    if engine not in _CLS:
        _CLS[engine] = type("Law_" + engine, (Screened, ENGINES[engine]), {})
    L = _CLS[engine](opts)
    L.engine, L.screen = engine, screen
    L.theta = float(screen.split()[1]) if screen.startswith("contract") else 0.5
    L.S_law = S0_L; L.name = f"{engine} + {screen}"; L.born = 0
    return L

SEED_LAWS = [("counted", "mass"), ("counted", "contract 0.5"), ("stepped", "mass"), ("counted", "none")]

def mutate(L, R, opts, t, taken):
    for _ in range(20):
        e, s = L.engine, L.screen
        if R.random() < 0.5: e = R.choice([x for x in ENGINES if x != e])
        else: s = R.choice([x for x in SCREENS if x != s])
        if (e, s) not in taken: break
    else: return None
    child = copy.deepcopy(L)
    if e != L.engine:                                 # a new engine starts its own record, keeps the shared graph
        fresh = make_law(e, s, opts)
        for k in ("n", "nij", "N", "ne", "se", "mij", "wij", "pv", "_rho"): setattr(fresh, k, copy.deepcopy(getattr(L, k)))
        child = fresh
    child.engine, child.screen = e, s
    child.theta = float(s.split()[1]) if s.startswith("contract") else 0.5
    child.name = f"{e} + {s}"; child.S_law = S0_L; child.born = t; child._root_ok = False; child._cc = {}; child._ac = {}
    return child

def law_weight(L):
    return max(0.0, T.weight(L.S_law)) if L.S_law >= DORMANT else 0.0

def mix(posts, laws, skip=None):
    ws = {id(L): law_weight(L) for L in laws if L is not skip}
    tot = sum(ws.values())
    if tot <= 0:                                     # nobody has earned weight yet: equal say
        ws = {id(L): 1.0 for L in laws if L is not skip}; tot = sum(ws.values())
    out = {u: 0.0 for u in VALS}
    for L in laws:
        if id(L) not in ws: continue
        for u, p in posts[id(L)].items(): out[u] += ws[id(L)] / tot * p
    return out

def outcome(post, Sset):
    e = sum(post[u] for u in Sset)
    near = sum(post[u] for u in VALS if u not in Sset and min(D[(u, v)] for v in Sset) == 1)
    return e + 0.5 * near

def run_adaptive(opts, world, seed=0, detail=False):
    events, POOL = world
    R = random.Random(seed ^ 0xADA7)
    laws = [make_law(e, s, opts) for e, s in SEED_LAWS]
    history = []
    tau = laws[0].tau
    RG = random.Random(seed ^ 0x601D)
    out = Counter(); last_t = -1; kinds = {}; opened = []; gold = []
    pending = defaultdict(list)                      # place -> [(t, {law id: post})]
    def grade(p, t2, cell_posts):
        keep = []
        for t1, preds in pending[p]:
            if t2 <= t1: keep.append((t1, preds)); continue
            if t2 - t1 > S.MEM_H: continue
            score = {}
            for L in laws:
                if id(L) not in preds: continue
                f = form(mix(cell_posts, laws, skip=L), tau, True)
                if f: score[id(L)] = math.log(max(1e-6, outcome(preds[id(L)], f[1])))   # log score: proper, so overconfidence does not pay
            if len(score) < 2: continue
            mean = sum(score.values()) / len(score)
            for L in laws:                           # selection: only beating or trailing the population moves S
                o = score.get(id(L))
                if o is None or abs(o - mean) < 1e-6: continue
                L.S_law += ETA_L * ((1000.0 if o > mean else 0.0) - L.S_law)
        pending[p] = keep
    def resolve(cell, p, t, truth, first):
        posts = {id(L): L.evidence(cell, None) for L in laws}
        if first: pending[p].append((t, posts))
        f = form(mix(posts, laws), tau, True)
        if not f: return False
        grain, Sset = f
        if truth in Sset: out["right"] += WORTH[grain]
        else: out["wrong"] += 1
        m = mix(posts, laws)
        for L in laws: L.settle(cell, None, m)
        grade(p, t, posts)
        if grain == "exact": gold.append((truth, m))
        return True
    for t, p, truth, fake, reps, u, items in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1):
                for L in laws: L.fade(h)
                if h and h % FORK_H == 0:
                    live = [L for L in laws if L.S_law >= DORMANT]
                    lead = max(live or laws, key=lambda L: L.S_law)
                    if len(live) < MAX_LAWS:
                        child = mutate(lead, R, opts, h, {(L.engine, L.screen) for L in live})
                        if child is not None: laws.append(child)
                    history.append((h, [(L.name, round(L.S_law)) for L in laws]))
            last_t = t
            if opts["gold"] and gold:
                for vid in POOL:
                    if RG.random() < 0.3:
                        content, post = RG.choice(gold[-300:])
                        r = K.v_read(RG, vid, content, False, None)
                        for L in laws: L.learn(vid, r, post, 1.0); L._cc = {}
            still = []
            for t0, cell, p0, tr in opened:
                if resolve(cell, p0, t0, tr, False): pass
                elif t - t0 < A.OPEN_H: still.append((t0, cell, p0, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, items)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        for L in laws: L.observe(cell)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, p, t, truth, True): opened.append((t, cell, p, truth))
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    lead = max(laws, key=lambda L: L.S_law)
    def St(i): c = lead.conf(i); return c[0] - c[2]
    hon = [St(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [St(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {"right": out["right"] / E, "wrong": out["wrong"] / E, "contested": out["stuck"] / E,
           "implicit": 0.0, "load": 1.0, "auc": auc}
    if detail: res["laws"] = [(L.name, round(L.S_law), L.born) for L in laws]; res["history"] = history
    return res

OPTS = dict(K.FULL, observers_gate=False)
