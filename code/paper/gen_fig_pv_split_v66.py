#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Figure stub for E16 (appendix): validation of the PV split on the 1,216 Tokyo substations.

(a) Share of substations whose daytime 5th-percentile net load is <= 0, by month, measured and
    estimated. (b) Median net-load bias by hour for each season, in per cent of the annual true
    mean, with the shape-only bias (level removed) as thin lines.
Reads results/micro/e16_reverse_monthly_{TAG}.csv and e16_bias_hour_season_{TAG}.csv (run
e16_pv_split_v66.py first). Double column width (7.2 in).
Output: manuscript/figs/fig_pv_split{SFX}.pdf.
"""
import sys
import pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io
from est_source import untagged_suffix

rv = pd.read_csv(io.MICRO_OUT / f"e16_reverse_monthly_{io.TAG}.csv", encoding="utf-8-sig")
bs = pd.read_csv(io.MICRO_OUT / f"e16_bias_hour_season_{io.TAG}.csv", encoding="utf-8-sig")
rv = rv[(rv.cls == "all") & (rv.month != "annual")]
bs = bs[bs.cls == "all"]
# Same typography as the other figures: sans text at print size, drawn at the full text width (6.84 in)
plt.rcParams.update({"font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7.5,
                     "xtick.labelsize": 7.2, "ytick.labelsize": 7.2, "legend.fontsize": 7.2,
                     "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 600})
fig, ax = plt.subplots(1, 2, figsize=(6.84, 2.5))
x = range(len(rv))
ax[0].plot(x, rv.share_true, "o-", c="k", ms=3, lw=1, label="ground truth")
ax[0].plot(x, rv.share_est, "s--", c="#b2182b", ms=3, lw=1, label="estimate")
ax[0].set_xticks(list(x))
ax[0].set_xticklabels([pd.Timestamp(m + "-01").strftime("%b") for m in rv.month])
ax[0].set_xlabel("month of fiscal year 2024 (April 2024 to March 2025)")
ax[0].set_ylabel("substations in reverse flow (%)")
ax[0].set_title("(a) reverse-flow share by month", pad=3)
ax[0].legend(frameon=False)
cols = {"MAM": ("#1b9e77", "spring"), "JJA": ("#d95f02", "summer"), "SON": ("#7570b3", "autumn"),
        "DJF": ("#2c7bb6", "winter")}
for s, (c, name) in cols.items():
    g = bs[bs.season == s].sort_values("hour")
    ax[1].plot(g.hour, g.bias_med, c=c, lw=1.2, label=name)
    ax[1].plot(g.hour, g.shape_bias_med, c=c, lw=0.7, ls=":")
ax[1].axhline(0, c="k", lw=0.5)
ax[1].set_xlabel("hour of day"); ax[1].set_ylabel("median bias of net load\n(% of metered annual mean)")
ax[1].set_xticks(range(0, 24, 3))
ax[1].set_title("(b) bias by hour and season (dotted: level removed)", pad=3)
lo, hi = ax[1].get_ylim()
ax[1].set_ylim(lo - 0.22 * (hi - lo), hi)                    # room for the legend below the curves
ax[1].legend(frameon=False, ncol=4, loc="lower center", handlelength=1.4, columnspacing=1.0)
fig.tight_layout()
p = io.FIG_OUT / f"fig_pv_split{untagged_suffix(io.TAG)}.pdf"
p.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(p, bbox_inches="tight")
print(f"[output] {p}")
