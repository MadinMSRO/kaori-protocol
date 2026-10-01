"""Chart of scale_referral.py: real members an attacker must corrupt as Liminal grows (log-log)."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

lin = json.load(open("scale-referral-lineage.json"))["rows"]
ide = json.load(open("scale-referral-identity.json"))["rows"]
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"

fig, ax = plt.subplots(figsize=(10, 6.2), dpi=160)
fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
series = [
    (lin, "total", S4, "Capture half of all blind checking (validators drawn by lineage)"),
    (lin, "quiet", S1, "One false truth, quiet hex (validators drawn by lineage)"),
    (lin, "typical", S3, "One false truth, typical hex (validators drawn by lineage)"),
    (ide, "quiet", S2, "One false truth, quiet hex (validators drawn by identity: the contrast)"),
]
for rows, key, col, label in series:
    xs = [r["N"] for r in rows if r[key]]; ys = [r[key] for r in rows if r[key]]
    ax.plot(xs, ys, color=col, lw=2, marker="o", ms=8, mec=SURF, mew=2, label=label, zorder=3)

ax.annotate("capture half of checking", (30000, 24000), xytext=(8, -10), textcoords="offset points", ha="left", va="top", fontsize=9, color=INK)
ax.annotate("quiet hex", (100000, 151552), xytext=(-6, 8), textcoords="offset points", ha="right", fontsize=9, color=INK)
ax.annotate("typical hex (unreachable beyond)", (10000, 14848), xytext=(-8, 8), textcoords="offset points", ha="right", fontsize=9, color=INK)
ax.annotate("drawn by identity: a handful of corrupted members\nplus unlimited fakes win a quiet hex", (100000, 26),
            xytext=(-6, 12), textcoords="offset points", ha="right", fontsize=9, color=INK)

ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(70, 150000); ax.set_ylim(2, 400000)
ax.set_xlabel("Liminal users (everyone joins by referral)", color=INK2, fontsize=10)
ax.set_ylabel("Real members an attacker must corrupt", color=INK2, fontsize=10)
ax.set_title("Referral-only Liminal: the cost of an attack in real people", loc="left", color=INK, fontsize=14, pad=44)
ax.text(0, 1.015, "Fewest corrupted real members for a 50% chance of one false truth at one key, or to hold half of all blind checks. "
        "Fakes are\nunlimited; each fake hangs off the real member it came through. In-app capture on; groups under one member count once.",
        transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")
fmt = lambda v, _: f"{int(v):,}"
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(fmt)); ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(fmt))
ax.tick_params(colors=INK2, labelsize=9)
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
for sp in ("left", "bottom"): ax.spines[sp].set_color(GRID)
ax.grid(True, which="major", color=GRID, lw=0.8); ax.set_axisbelow(True)
ax.legend(loc="upper left", fontsize=8.5, frameon=False, labelcolor=INK)
fig.tight_layout()
fig.savefig("scale-referral-chart.png", facecolor=SURF)
print("ok")
