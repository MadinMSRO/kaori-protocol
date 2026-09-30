"""
Blind validation: validators never see the observers' claims. They judge each piece of evidence on its own:
what it shows, and whether it looks like a real capture (the metadata is shown as well). Their judgement of
realness is a second realness witness beside the provenance agent. Its reliability is learned from agreement
with the provenance agent across items (principle 5: not from outcomes an attacker can win).
"""
import math, random, time, json
from collections import Counter, defaultdict
from multiprocessing import Pool
import coevo, topo, seed as S, agents as A
from agents import read, STATES, VALIDATORS
from emerge import NAMES

def add_agents_blind(events, sd, pass_real=0.95, pass_fake=0.15, pass_junk=0.9):
    R = random.Random(sd ^ 0x5E75)
    out = []
    for t, p, truth, fake, reps, u in events:
        photos, vreads, vflags = [], [], []
        vid = R.choice(VALIDATORS)
        attack = any(k in ("adv", "stolen") and said == fake for _, k, said, _, _ in reps)
        for aid, kind, said, shows, rel in reps:
            content = None if shows == "junk" else (truth if shows == "truth" else fake)
            passed = R.random() < (pass_junk if content is None else pass_real if shows == "truth" else pass_fake)
            photos.append((aid, passed, None if content is None else read(R, content, 0.75, 0.85)))
            is_fake = shows == "fake"
            if vid == "v:bribed" and attack:
                vr, flag = fake, False                         # knows the fake off-channel; passes fakes as real
            elif vid == "v:hasty":                             # skims: poor reading, never spots fakes
                vr, flag = (None if content is None else read(R, content, 0.5, 0.6)), False
            else:
                vr = None if content is None else read(R, content, 0.9, 0.9)
                flag = (is_fake and R.random() < 0.5) or (not is_fake and R.random() < 0.03)
            vreads.append(vr); vflags.append(flag)
        out.append((t, p, truth, fake, reps, u, photos, (vid, vreads, vflags)))
    return out

class Blind(S.Seed):
    def __init__(self, opts):
        super().__init__(opts)
        self.fl = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])   # per validator: flags on real, n real, flags on fake, n fake

    def flag_lr(self, vid, flagged):
        c = self.fl[vid]
        tpr = (c[2] + 1) / (c[3] + 2); fpr = (c[0] + 1) / (c[1] + 2)   # P(flag | fake), P(flag | real)
        return (fpr / tpr) if flagged else ((1 - fpr) / (1 - tpr))       # likelihood ratio real : fake

    def support(self, said, ai_read, vr, vid):
        """P(the photo shows what the observer claims, within one step), from the readings of that photo."""
        if ai_read is None and vr is None: return 1.0
        post = {c: 1.0 for c in S.VALS}
        if ai_read is not None:
            lk = self.lik(ai_read, self.conf("ai"))
            for c in post: post[c] *= lk[c]
        if vr is not None:
            lk = self.lik(vr, self.conf(vid))
            for c in post: post[c] *= lk[c]
        z = sum(post.values())
        return sum(p for c, p in post.items() if S.D[(c, said)] <= 1) / z

    def items(self, cell):
        """Per observation: owner, claim, photo realness, readings of the photo, and the claim's support."""
        reps, photos, val = cell
        vid, vreads = val[0], val[1]
        vflags = val[2] if len(val) > 2 and self.o.get("blind_flags", True) else [None] * len(reps)
        out = []
        for (aid, kind, said, *_), (_, passed, ai_read), vr, fl in zip(reps, photos, vreads, vflags):
            real = self.realness(aid, passed)
            if fl is not None and 0 < real < 1:
                odds = real / (1 - real) * self.flag_lr(vid, fl); real = odds / (1 + odds)
            sky = 1.0 if ai_read is not None else 0.05
            sup = self.support(said, ai_read, vr, vid) if self.o.get("support", True) else 1.0
            out.append((aid, said, real, sky, sup, ai_read, vr))
        return vid, out

    def witnesses(self, cell, mem):
        """What each agent said, for learning its standing (every reading is a signal)."""
        vid, items = self.items(cell)
        out = []
        for aid, said, real, sky, sup, ai_read, vr in items:
            out.append((aid, said, real * sky * sup, 1))
            if ai_read is not None: out.append(("ai", ai_read, real, 1))
            if vr is not None: out.append((vid, vr, real * sky, 1))
        if mem is not None and self.o["memory"]: out.append(("mem", mem, 1.0, 1))
        return out

    def section(self, cell, mem):
        """Two witnesses per observation: the claim (what the person says) and the photo (what the scene shows,
        read through the AI and the validator). Photos share their owners' bonds."""
        if not self.o.get("photo_witness", True): return super().section(cell, mem)
        vid, items = self.items(cell)
        owners = [it[0] for it in items] + [vid]
        shooters = [it[0] for it in items if it[5] is not None or it[6] is not None]
        L = {u: 0.0 for u in S.VALS}
        ai, vc = self.conf("ai"), self.conf(vid)
        for aid, said, real, sky, sup, ai_read, vr in items:
            r = real * sky * sup
            lk = self.lik(said, self.conf(aid)); mass = sum(self.a(aid, j) for j in owners)
            for u in S.VALS: L[u] += math.log(r * lk[u] + (1 - r) / len(S.VALS)) / mass
            if ai_read is None and vr is None: continue
            pl = {u: 1.0 for u in S.VALS}
            if ai_read is not None:
                l1 = self.lik(ai_read, ai)
                for u in pl: pl[u] *= l1[u]
            if vr is not None:
                l2 = self.lik(vr, vc)
                for u in pl: pl[u] *= l2[u]
            base = sum(pl.values()) / len(pl)                     # what the readings look like if the photo is not of this sky
            mass = sum(self.a(aid, j) for j in shooters)
            for u in S.VALS: L[u] += math.log(real * pl[u] + (1 - real) * base) / mass
        if mem is not None and self.o["memory"]:
            lk = self.lik(mem, self.conf("mem"))
            for u in S.VALS: L[u] += math.log(lk[u])
        m = max(L.values()); Z = sum(math.exp(v - m) for v in L.values())
        return {u: math.exp(v - m) / Z for u, v in L.items()}

    def observe(self, cell):
        reps, photos, val = cell
        super().observe((reps, photos, val[:2]))
        if len(val) > 2:
            for (aid, passed, _), fl in zip(photos, val[2]):
                r = self.realness(aid, passed)                # the provenance agent's view of this item
                c = self.fl[val[0]]
                c[0] += r * fl; c[1] += r; c[2] += (1 - r) * fl; c[3] += 1 - r

S.Seed_cls = S.Seed
def run(opts, events, detail=False):
    orig = S.Seed
    S.Seed = Blind
    try: return S.run(opts, events, detail)
    finally: S.Seed = orig

FULL = dict(S.FULL, timescales=False)
ARMS = {"seed, validators see claims": ("old", FULL), "seed, blind validators": ("blind", FULL),
        "blind, no realness flags": ("blind", dict(FULL, blind_flags=False))}

def job(args):
    name, (world, opts), s, a = args
    ev = (add_agents_blind if world == "blind" else A.add_agents)(coevo.make_world(s, a), s)
    return name, run(opts, ev)

if __name__ == "__main__":
    t0 = time.time()
    test = [random.SystemRandom().getrandbits(48) for _ in range(4)]
    suite = [(nm, a) for nm, a in zip(NAMES, topo.suite()) if nm not in ("cabal 2", "cabal 3")]
    with Pool(4) as pool:
        res = pool.map(job, [(n, w, s, a) for n, w in ARMS.items() for _, a in suite for s in test])
    k = len(test)
    print(f"{'':30} {'right':>6} {'wrong':>6} {'worst':>6} {'stuck':>6} {'AUC':>5}   " + "  ".join(f"{nm.split()[0][:8]:>13}" for nm, _ in suite))
    for n in ARMS:
        rs = [r for nm, r in res if nm == n]
        per = [(sum(r["right"] for r in rs[i * k:(i + 1) * k]) / k, sum(r["wrong"] for r in rs[i * k:(i + 1) * k]) / k) for i in range(len(suite))]
        m = lambda x: sum(r[x] for r in rs) / len(rs)
        print(f"{n:30} {m('right'):6.2f} {m('wrong'):6.3f} {max(r['wrong'] for r in rs):6.3f} {m('stuck'):6.2f} {m('auc'):5.2f}   "
              + "  ".join(f"{a:.2f}/{b:.3f}".rjust(13) for a, b in per))
    print("\n### validator standing (log-odds) and fake-spotting learned, per scenario")
    for world in ("old", "blind"):
        for nm, a in suite:
            ev = (add_agents_blind if world == "blind" else A.add_agents)(coevo.make_world(test[0], a), test[0])
            orig = S.Seed; S.Seed = Blind
            try:
                C_res = S.run(FULL, ev, detail=True)
            finally: S.Seed = orig
            print(f"  {world:5} {nm[:18]:18} validators {C_res['validators']}")
    print(f"\n{time.time() - t0:.0f}s")
