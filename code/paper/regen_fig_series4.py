#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate fig_series4.pdf (Fig. 2) only.

The original fix_round6_merge.py drew the figure and rewrote results_v63.tex in one go. The tex surgery has
already been applied, so running it again would duplicate the figure (the same situation as
regen_fig_examiner2.py). Only the drawing is kept here.

**The evaluation set is the 1,216 substations after the admission test** (aligned with v6.5 on 2026-07-29).
The three boxes of panel (d) therefore correspond to the 75 / 169 / 972 substations of Table 1.

Round-1 revision (E28, R3-m11), presentation only, same inputs and the same selection rule:
- axis labels on every panel;
- the week is shown as calendar dates on the time axis (5 to 11 August 2024);
- panel (d) has a legend entry for the dashed area-shape baseline;
- class names follow TERMS.md (Class 1 (nodal balance) / Class 2 (measured shape) / Class 3 (transferred shape));
- the class colours are the colour-blind-safe palette shared with Fig. 5;
- drawn at print width (full text width, 6.84 in) so that no text falls below 7 pt.

Prerequisite: run clean_truth_and_recompute.py first to produce results/micro/v65_micro_clean.csv.
Needs the frozen database for reading only (DT_DB_CONTAINER=iwafune_db_frozen).
"""
import sys, pathlib
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
sys.stdout.reconfigure(encoding="utf-8")
WS   = str(pathlib.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/micro"
FIG  = f"{WS}/manuscript/figs"
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import IDX, norm2, qdf
from est_source import db_source, untagged_suffix
EST_REL, EST_LIKE, TAG = db_source()   # PAPER_EST_REL, required (RERUN_PLAN_R1.md Step 3, items 4 and 6)
FS = 7.5                                   # text size in pt at print size (the figure is drawn at print width)
plt.rcParams.update({"font.size": FS, "axes.titlesize": FS, "axes.labelsize": FS,
                     "xtick.labelsize": 7.2, "ytick.labelsize": 7.2, "legend.fontsize": 7.2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6,
                     "savefig.dpi": 600})
C_T, C_E = "#111111", "#1d6fb8"
# Colour-blind-safe class palette (Okabe and Ito), shared with Fig. 5
TIERC = {"z1": "#0072B2", "z1s": "#E69F00", "z2": "#999999"}
C_BASE = "#CC79A7"                         # area-shape baseline; distinct from every class colour
TEXT_W = 6.84                              # cas-dc \textwidth = 494.5 pt

tru = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
          ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)
est = qdf(f"""SELECT station_id, src, to_char(ts,'YYYY-MM-DD HH24:00'), demand_net_mw
FROM {EST_REL} WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}'""",
["key","src","ts","mw"], ["mw"])
ew = est.pivot_table(index="ts", columns="key", values="mw", aggfunc="first")
ew.index = pd.to_datetime(ew.index); ew = ew.reindex(IDX)
# Evaluation set: the 1,216 substations after cleaning. The class (src) is carried by this file.
mic = pd.read_csv(f"{HERE}/{TAG}_micro_clean.csv")
print(f"  evaluation set {len(mic):,} substations / by class " +
      " ".join(f"{s_}={int((mic.src==s_).sum())}" for s_ in ("z1","z1s","z2")))
# Classes present in the evaluation set. Criterion F merged the measured-shape class into the transferred one
# in v6.6, so with no z1s rows there are two classes and the transferred class is Class 2 in the manuscript.
CLS = [s_ for s_ in ("z1", "z1s", "z2") if (mic.src == s_).any()]
TWO = "z1s" not in CLS
NAME = {"z1": "Class 1 (nodal balance)", "z1s": "Class 2 (measured shape)",
        "z2": f"Class {2 if TWO else 3} (transferred shape)"}
SHORT = {"z1": "Class 1", "z1s": "Class 2", "z2": f"Class {2 if TWO else 3}"}
LET = "abcd"
# Dashed reference line of the distribution panel. v6.5 keeps the published figure's area-shape baseline
# (0.697, the shape of the summed estimate). v6.6 uses the shape of the published area demand, the baseline
# that is independent of the estimator (E15; e15_station_baselines_v66.py, method area_shape_pub).
if TAG == "v65":
    BASE_R, BASE_LB = 0.697, "area-shape baseline"
else:
    b15 = pd.read_csv(f"{HERE}/e15_baselines_{TAG}.csv", encoding="utf-8-sig")
    BASE_R = float(b15[(b15.method == "area_shape_pub") & (b15.cls == "all")]["corr"].iloc[0])
    BASE_LB = "published area-shape baseline"
print(f"  classes {CLS}; baseline line r = {BASE_R:.3f} ({BASE_LB})")
picks = []
for i_, s in enumerate(CLS):
    lb = f"({LET[i_]}) {NAME[s]}"
    g = mic[(mic.src == s) & mic["corr"].notna()]
    med = g["corr"].median()
    # The representative substation is chosen by closeness to the class median of correlation among
    # substations whose level error is also within 5 points of the class median; a class with fewer than
    # five such substations falls back to the old rule (exclude the top decile of APE).
    g2 = g[(g.ape - g.ape.median()).abs() <= 5]
    if len(g2) < 5:
        g2 = g[g.ape < g.ape.quantile(0.9)]
    k = g2.iloc[(g2["corr"] - med).abs().argsort()].iloc[0]
    picks.append((k.key, lb, float(k["corr"]), float(k.ape)))
wk = (IDX >= "2024-08-05") & (IDX < "2024-08-12")
days = IDX[wk]
print(f"  week shown: {days[0]:%a %d %b %Y %H:%M} to {days[-1]:%a %d %b %Y %H:%M} ({wk.sum()} hours)")
# Major ticks at midnight; every second day is labelled at its noon with its day of month, taken from the
# index (labelling all seven made "10" and "11" touch at print size)
tick_l = [f"{days[24*d].day}" if d % 2 == 0 else "" for d in range(7)]
month_l = f"{days[0]:%B %Y}"

NP = len(picks)
fig, axes = plt.subplots(1, NP + 1, figsize=(TEXT_W, 2.35),
                         gridspec_kw={"width_ratios": [1] * NP + [1.02]})
for ax, (k, lb, cr, ap) in zip(axes[:NP], picks):
    t = tw[k].values[wk]; e = ew[k].values[wk]
    hh = np.arange(len(t))/24.0
    ax.plot(hh, t, color=C_T, lw=1.1, label="measured")
    ax.plot(hh, e, color=C_E, lw=1.1, ls="--", label="estimated")
    ax.set_title(f"{lb}\n$r$ = {cr:.2f}, APE = {ap:.0f} %", pad=3)
    ax.set_xticks(range(0, 8)); ax.set_xticklabels([])
    ax.set_xticks(np.arange(7) + 0.5, minor=True); ax.set_xticklabels(tick_l, minor=True)
    ax.tick_params(axis="x", which="minor", length=0)
    ax.grid(False, axis="x", which="minor")
    ax.set_xlim(0, 7)
    ax.set_xlabel(f"day of {month_l}")
    ax.set_ylabel("net load (MW)", labelpad=1)
    ax.set_ylim(0, 46)
axes[NP - 1].legend(frameon=False, ncol=1, loc="upper left", handlelength=1.8, labelspacing=0.25, borderpad=0.1)

# last panel: distribution of hourly correlation by class
ax = axes[NP]
data_c = [mic[mic.src == s]["corr"].dropna().values for s in CLS]
# Whiskers keep matplotlib's default (1.5 times the interquartile range, clipped to the data), as in the
# published version; the caption must say so.
bp = ax.boxplot(data_c, vert=False, widths=0.55, showfliers=False, patch_artist=True,
                medianprops=dict(color="black", lw=1.1))
for p_, c in zip(bp["boxes"], [TIERC[s] for s in CLS]):
    p_.set_facecolor(c); p_.set_alpha(0.85); p_.set_linewidth(0.6)
ax.axvline(BASE_R, color=C_BASE, ls="--", lw=1.2)
ax.set_yticks(range(1, len(CLS) + 1)); ax.set_yticklabels([SHORT[s] for s in CLS])
ax.set_ylim(0.45, len(CLS) + 1.05)
ax.set_ylabel("observability class", labelpad=1)
ax.set_xticks([0.0, 0.5, 1.0])
ax.set_xlabel("hourly correlation $r$")
ax.set_title(f"({LET[NP]}) all {len(mic):,} evaluated\nsubstations", pad=3)
ax.legend(handles=[Line2D([], [], color=C_BASE, ls="--", lw=1.2, label=BASE_LB)],
          loc="upper left", frameon=True, facecolor="white", edgecolor="none", framealpha=1,
          handlelength=2.0, borderpad=0.2, borderaxespad=0.2)
fig.tight_layout(w_pad=0.7)
fig.savefig(f"{FIG}/fig_series4{untagged_suffix(TAG)}.pdf", bbox_inches="tight", pad_inches=0.02)
plt.close(fig)
print(f"[output] fig_series4{untagged_suffix(TAG)}.pdf (four panels, full width)")
