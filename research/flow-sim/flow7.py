"""
The 7 Principles with the Kaori compile flow as specified:

  1 submission   observers send a photo and a claim
  2 assessment   each piece of evidence is assessed on its own, blind to the claims, by the validator and the AI
                 (each is an agent with standing); provenance says how real each item is
  3 compilation  the truth is anchored on the evidence: it forms when the assessments pass the stakes threshold
                 AND a standing-weighted majority of observers agree. If the observers disagree, the cell waits
                 (it can be stalled, not flipped)
  4 signals      after compilation every agent gets a signal against the compiled truth: observers for their
                 claims, validators and the AI for each assessment. The signal flows back into standing, so a
                 conflicting claim weighs less next time and costs its author when it comes to agreement.

Kept from before: emergent bonds (shared presence and error), a learned prior, a threshold from stakes, the
memory agent, open cells, and provenance learned from population structure.
"""
import math, random, time, json
from collections import Counter, defaultdict
import coevo, topo, seed as S, blind as B, agents as A
from agents import VALS, D, form, WORTH, HOSTILE, VALIDATORS

class Flow7(B.Blind):
    def items(self, cell):
        reps, photos, val = cell
        vid, vreads = val[0], val[1]
        vflags = val[2] if len(val) > 2 else [None] * len(reps)
        out = []
        for (aid, kind, said, *_), (_, passed, ai_read), vr, fl in zip(reps, photos, vreads, vflags):
            real = self.realness(aid, passed)
            if fl is not None and 0 < real < 1:
                odds = real / (1 - real) * self.flag_lr(vid, fl); real = odds / (1 + odds)
            out.append((aid, said, real, ai_read, vr))
        return vid, out

    def evidence(self, cell, mem):
        """The truth from the evidence alone: each item assessed by its readers, weighted by realness; one knot's
        items share that knot's bonds."""
        vid, items = self.items(cell)
        owners = [it[0] for it in items if it[3] is not None or it[4] is not None]
        ai, vc = self.conf("ai"), self.conf(vid)
        L = {u: 0.0 for u in VALS}
        for aid, said, real, ai_read, vr in items:
            if ai_read is None and vr is None: continue
            pl = {u: 1.0 for u in VALS}
            for x, cf in ((ai_read, ai), (vr, vc)):
                if x is None: continue
                lk = self.lik(x, cf)
                for u in pl: pl[u] *= lk[u]
            base = sum(pl.values()) / len(pl)
            mass = sum(self.a(aid, j) for j in owners)
            for u in VALS: L[u] += math.log(real * pl[u] + (1 - real) * base) / mass
        if mem is not None and self.o["memory"]:
            lk = self.lik(mem, self.conf("mem"))
            for u in VALS: L[u] += math.log(lk[u])
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def agreement(self, cell, S_set):
        """Standing-weighted share of observers whose claim agrees with the candidate truth."""
        vid, items = self.items(cell)
        ids = [it[0] for it in items]
        yes = tot = 0.0
        for aid, said, real, ai_read, vr in items:
            c = self.conf(aid)
            w = real * (c[0] + 0.5 * c[1]) / sum(self.a(aid, j) for j in ids)
            tot += w; yes += w * (said in S_set)
        return yes / tot if tot > 0 else 0.0

    def settle(self, cell, mem, post):
        """Signals after compilation, for everyone who took part."""
        vid, items = self.items(cell)
        err = defaultdict(list)
        def learn(aid, said, w):
            e = post[said]; nr = sum(p for u, p in post.items() if D[(u, said)] == 1)
            obs = (e, nr, max(0.0, 1 - e - nr))
            for k in ("f", "s"):
                v = self.c[k][aid]
                for c in range(3): v[c] += obs[c] * w
            err[aid].append((1 - e) * w)
        for aid, said, real, ai_read, vr in items:
            learn(aid, said, real)
            if ai_read is not None: learn("ai", ai_read, real)
            if vr is not None: learn(vid, vr, real)
        if mem is not None and self.o["memory"]: learn("mem", mem, 1.0)
        E = {a: sum(v) / len(v) for a, v in err.items()}
        for a, e in E.items(): self.ne[a] += 1; self.se[a] += e
        ks = list(E)
        for x in range(len(ks)):
            for y in range(x + 1, len(ks)):
                key = tuple(sorted((ks[x], ks[y])))
                self.mij[key] += 1; self.wij[key] += E[ks[x]] * E[ks[y]]
        self._cc = {}; self._ac = {}

FULL = dict(S.FULL, timescales=False, observers_gate=True)

def run(opts, events, detail=False):
    C = Flow7(opts)
    out = Counter(); last_t = -1; kinds = {}; opened = []; last = {}
    def mem_at(p, t):
        return last[p][0] if p in last and t - last[p][1] <= S.MEM_H else None
    def resolve(cell, p, t, truth):
        mem = mem_at(p, t)
        post = C.evidence(cell, mem)
        f = form(post, C.tau, True)
        if not f: out["_ev_short"] += 1; return False
        grain, Sset = f
        if opts.get("observers_gate", True) and C.agreement(cell, Sset) <= 0.5:
            out["_held"] += 1; return False             # evidence is clear but observers disagree: the cell waits
        if truth in Sset: out["right"] += WORTH[grain]; out["right_" + grain] += 1
        else: out["wrong"] += 1
        C.settle(cell, mem, post)
        if grain == "exact": last[p] = (max(post, key=post.get), t)
        return True
    for t, p, truth, fake, reps, u, photos, val in events:
        if t != last_t:
            for h in range(last_t + 1, t + 1): C.fade(h)
            last_t = t
            still = []
            for t0, cell, p0, tr in opened:
                if resolve(cell, p0, t0, tr): out["late"] += 1
                elif t - t0 < A.OPEN_H: still.append((t0, cell, p0, tr))
                else: out["stuck"] += 1
            opened = still
        cell = (reps, photos, val)
        for aid, kind, *_ in reps: kinds.setdefault(aid, kind)
        if len(reps) >= 3:
            out["eligible"] += 1
            if not resolve(cell, p, t, truth): opened.append((t, cell, p, truth))
        C.observe(cell)
    out["stuck"] += len(opened)
    E = max(1, out["eligible"])
    def St(i): c = C.conf(i); return math.log(c[0] / c[2])
    hon = [St(a) for a, k in kinds.items() if k in ("careful", "sloppy")]
    hos = [St(a) for a, k in kinds.items() if k in HOSTILE]
    auc = sum((h > x) + 0.5 * (h == x) for h in hon for x in hos) / max(1, len(hon) * len(hos))
    res = {k: out[k] / E for k in ("right", "wrong", "stuck", "late", "right_exact", "right_band", "right_pair")}
    res["auc"] = auc
    if detail:
        tiers = defaultdict(list)
        for a, k in kinds.items(): tiers[k].append(St(a))
        res["observers"] = {k: round(sum(v) / len(v), 2) for k, v in tiers.items()}
        res["validators"] = {v[2:]: round(St(v), 2) for v in VALIDATORS}
        res["ai"] = round(St("ai"), 2)
    return res
