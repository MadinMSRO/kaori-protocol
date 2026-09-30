import sys, math
from collections import Counter, defaultdict
from random import Random, SystemRandom
import physics_sim as ps
P = {"K": 25.0, "alpha": 2.0, "beta": 0.002, "S0": 200.0, "m0": 0.5, "k": 3.0, "mass_scale": 0.5, "alpha2": 0.15}
master = SystemRandom(); worlds = [ps.world(Random(master.getrandbits(64)), 300) for _ in range(3)]
for b, ev in ((0.02, 0.0), (0.02, 0.01), (0.02, 0.03)):
    P["beta2"] = b; P["evap"] = ev; tot = Counter(); fin = defaultdict(list); mh = 0
    for agents, kind, events in worlds:
        st, tr, m, S = ps.run("field2", agents, kind, events, P); tot.update(st); mh += m
        for a in agents: fin[kind[a]].append(S[a])
        fin["AI"].append(S["AI"])
    v = tot["VERIFIED_TRUE"]
    print(f"beta {b} evap {ev:<5} wrong {100*tot['verified WRONG']/max(1,v):.1f}%  verified {v} stuck {tot['INVESTIGATING']}  | " + "  ".join(f"{k} {sum(x)/len(x):.0f}" for k, x in fin.items()))
