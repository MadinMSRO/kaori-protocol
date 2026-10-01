"""
Tipping point, with validators earned through observation (as in Kaori: you become a validator through standing, and
standing is earned by observing). No fixed validator pool and no farm handed to the attacker.

Every observer, attackers included, becomes eligible to validate once its conduit passes THETA. Each photo goes to
K_V random eligible validators, never its owner and never anyone present at that key (blind). The AI reads every
photo as before. Honest validators read like the world's diligent validators (lazy observers like its lazy ones,
liars answer a wrong value); an attacker who is eligible answers the attack value on a signed attack photo and
reads honestly otherwise. A script cannot earn eligibility: only observing in place does.
"""
import json, random, time
from multiprocessing import Pool
import captcha as K, soup as SP, tip
from agents import read, STATES

THETA, K_V = 0.6, 3
DESIGNS = tip.DESIGNS
TEAM = [1, 2, 4, 7, 10, 14, 21]
SEEDS = tip.SEEDS

def make_transform(seed):
    R = random.Random(seed ^ 0x7E57)
    seen = {}
    stats = {"reads": 0, "attacker_reads": 0}
    def v_read(vid, kind, content, signed, fake):
        if kind in ("adv", "stolen"):
            return fake if signed else read(R, content, 0.9, 0.9)
        if kind == "lazy": return read(R, content, 0.5, 0.6)
        if kind == "liar": return (R.choice([x for x in STATES if x != content[0]]), R.random() < 0.3)
        return read(R, content, 0.9, 0.9)
    def transform(N, cell, t, truth, fake):
        reps, items = cell
        for aid, kind, *_ in reps: seen[aid] = kind
        present = {r[0] for r in reps}
        eligible = [a for a in seen if N.c[a] >= THETA and a not in present]
        new = []
        for (aid, kind, said, shows, rel), (a2, s2, passed, sky, reads) in zip(reps, items):
            content = None if shows == "junk" else (truth if shows == "truth" else fake)
            rs = [(r, x) for r, x in reads if r == "ai"]
            if content is not None and eligible:
                signed = kind in ("adv", "stolen") and said == fake
                for v in R.sample(eligible, min(K_V, len(eligible))):
                    rs.append((v, v_read(v, seen[v], content, signed, fake)))
                    stats["reads"] += 1; stats["attacker_reads"] += seen[v] in ("adv", "stolen")
            new.append((a2, s2, passed, sky, rs))
        return (reps, new)
    return transform, stats

def job(args):
    d, n, s = args
    tr, stats = make_transform(s)
    r = SP.run(d, K.make(s, tip.att(n, 0), "critical"), transform=tr)
    r["attacker_read_share"] = stats["attacker_reads"] / max(1, stats["reads"])
    return d, n, r

if __name__ == "__main__":
    t0 = time.time()
    with Pool(4) as pool:
        res = pool.map(job, [(d, n, s) for d in DESIGNS for n in TEAM for s in SEEDS], chunksize=2)
    out = {}
    print(f"validators earned through observation (threshold {THETA}, {K_V} per photo, never the owner or anyone present)\n")
    print(f"{'':42} {'team (share)':>13} {'right':>6} {'wrong@att':>9} {'wrong@min':>9} {'att:careful':>11} {'attacker share of validator reads':>34}")
    for d in DESIGNS:
        for n in TEAM:
            rs = [r for dd, nn, r in res if dd == d and nn == n]
            m = lambda k: sum(r[k] for r in rs) / len(rs)
            ratio = m("attacker_c") / max(1e-9, m("careful_c"))
            out[f"{d}|{n}"] = dict(right=m("right"), wrong_att=m("wrong_att"), wrong_min=m("wrong_min"), ratio=ratio,
                                   attacker_reads=m("attacker_read_share"))
            print(f"{d:42} {n:>3} ({n / (14 + n):4.0%})   {m('right'):6.2f} {m('wrong_att') * 100:8.1f}% {m('wrong_min') * 100:8.1f}% "
                  f"{ratio:10.2f}{'*' if ratio > 1 else ' '} {m('attacker_read_share') * 100:33.1f}%")
        print()
    json.dump(out, open("tip2-result.json", "w"), indent=1)
    print(f"{time.time() - t0:.0f}s")
