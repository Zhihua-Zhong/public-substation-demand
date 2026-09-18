#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figure stub for E9 (proposed Fig. 2e): estimated against true load factor, 1,216 Tokyo substations.

Reads only results/micro/e9_station_{TAG}.csv (run e9_level_skill_v66.py first). Each point is
one substation: x = true annual mean / capacity, y = estimated annual mean / capacity, coloured by
class. The dashed line is the capacity x constant baseline (y = anchor), the dotted line y = x.
The Pearson r of the load factors is printed in the panel. Single column width (3.5 in).
Output: manuscript/figs/fig_lf_scatter{SFX}.pdf (SFX '' for v6.5, '_v66' for v6.6).
"""
import sys
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io
from est_source import untagged_suffix

d = pd.read_csv(io.MICRO_OUT / f"e9_station_{io.TAG}.csv", encoding="utf-8-sig")
c0 = io.anchor_constant()
plt.rcParams.update({"font.size": 8, "font.family": "serif"})
fig, ax = plt.subplots(figsize=(3.5, 3.1))
# Two classes once criterion F merged the measured-shape class into the transferred one (no z1s rows):
# the transferred class is then Class 2 in the manuscript's numbering.
TWO = not (d.src == "z1s").any()
style = {"z2": ("#9a9a9a", 6, f"Class {2 if TWO else 3} (transferred shape)"),
         "z1s": ("#2e7bd6", 9, "Class 2 (measured shape)"),
         "z1": ("#0b6b3a", 11, "Class 1 (nodal balance)")}
for c in ["z2", "z1s", "z1"]:
    g = d[d.src == c]
    col, s, lab = style[c]
    ax.scatter(g.lf_true, g.lf_est, s=s, c=col, alpha=0.7, linewidths=0, label=f"{lab}, n = {len(g)}")
lim = [0, max(1.0, float(np.nanmax(d[["lf_true", "lf_est"]].values)) * 1.02)]
ax.plot(lim, lim, ls=":", c="k", lw=0.8, label="equality")
ax.axhline(c0, ls="--", c="#b2182b", lw=0.9, label=f"capacity x constant ({c0:.3f})")
r = np.corrcoef(d.lf_est, d.lf_true)[0, 1] if d.lf_est.std() > 1e-9 else np.nan
ax.text(0.97, 0.04, f"r = {r:.2f}", transform=ax.transAxes, ha="right", va="bottom")
ax.set_xlim(lim); ax.set_ylim(lim)
ax.set_xlabel("True load factor (annual mean / capacity)")
ax.set_ylabel("Estimated load factor")
ax.legend(loc="upper left", fontsize=6.5, frameon=False, handletextpad=0.3, borderaxespad=0.3)
fig.tight_layout()
p = io.FIG_OUT / f"fig_lf_scatter{untagged_suffix(io.TAG)}.pdf"
p.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(p, bbox_inches="tight")
print(f"[output] {p}")
