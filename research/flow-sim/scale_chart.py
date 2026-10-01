"""Chart of scale.py's results: attacker identities needed as Liminal grows (log-log)."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

rows = json.load(open("scale-result-bond0.0.json"))["rows"]
N = [r["N"] for r in rows]
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"

fig, ax = plt.subplots(figsize=(10, 6.2), dpi=160)
fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)

def series(key):
    xs = [r["N"] for r in rows if r[key]]; ys = [r[key] for r in rows if r[key]]
    return xs, ys

lines = [
    ("total", S4, "Capture half of all blind checking\n(total false attractor)"),
    ("quiet", S1, "One false truth, quiet hex\n(in-app capture, group undetected)"),
    ("typical", S3, "One false truth, typical hex\n(in-app capture, group undetected)"),
    ("no_capture", S2, "One false truth, typical hex\n(forged photos, no in-app capture)"),
]
for key, col, label in lines:
    xs, ys = series(key)
    ax.plot(xs, ys, color=col, lw=2, marker="o", ms=8, mec=SURF, mew=2, label=label.replace("\n", " "), zorder=3)
    last = [r for r in rows if r[key]][-1]
    unreach = [r for r in rows if not r[key]]
    if unreach and unreach[0]["N"] > last["N"] and key != "typical":
        off = (10, 6) if key == "typical" else (8, -14)
        ax.annotate("unreachable beyond", (last["N"], last[key]), xytext=off, textcoords="offset points",
                    fontsize=8.5, color=INK2)

# direct labels (relief for the low-contrast aqua line)
ax.annotate("total false attractor", (100000, 80000), xytext=(-6, 10), textcoords="offset points", ha="right", fontsize=9, color=INK)
ax.annotate("quiet hex", (100000, 163840), xytext=(-6, 8), textcoords="offset points", ha="right", fontsize=9, color=INK)
ax.annotate("typical hex (unreachable beyond)", (10000, 16384), xytext=(-8, 8), textcoords="offset points", ha="right", fontsize=9, color=INK)
ax.annotate("forged photos", (3000, 8), xytext=(0, 10), textcoords="offset points", ha="center", fontsize=9, color=INK)

ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(70, 150000); ax.set_ylim(2, 400000)
ax.set_xlabel("Liminal users", color=INK2, fontsize=10)
ax.set_ylabel("Attacker identities needed (each earns validator status in person)", color=INK2, fontsize=10)
ax.set_title("How expensive an attack becomes as Liminal grows", loc="left", color=INK, fontsize=14, pad=44)
ax.text(0, 1.015, "Fewest identities for a 50% chance of one false truth at one key, or to hold half of all blind checks. "
        "With groups even half detected\n(e.g. via referral lineage), an in-app-captured lie never reaches 50% at any size.",
        transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")
fmt = lambda v, _: f"{int(v):,}"
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(fmt)); ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(fmt))
ax.tick_params(colors=INK2, labelsize=9)
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
for sp in ("left", "bottom"): ax.spines[sp].set_color(GRID)
ax.grid(True, which="major", color=GRID, lw=0.8); ax.set_axisbelow(True)
leg = ax.legend(loc="upper left", fontsize=8.5, frameon=False, labelcolor=INK)
fig.tight_layout()
fig.savefig("scale-chart.png", facecolor=SURF)
print("ok")
