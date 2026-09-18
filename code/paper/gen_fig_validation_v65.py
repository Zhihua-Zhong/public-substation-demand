# -*- coding: utf-8 -*-
"""Figure: transfer validation across the ten areas (paper section on transfer validation, Fig. 4).

The graphical companion of Table 3. It computes nothing: it reads results/numbers/scoreboard_v65.csv
(the canonical output of the baseline run) and draws it.

  (a) annual coverage of sales, with the physically expected band 102-108 %
  (b) monthly coverage error before and after harmonizing the meter-reading calendar
  (c) municipal spatial correlation

Round-1 revision (E28, R3-m9), presentation only: all three panels are dot plots (no bar whose length starts
at a truncated axis), the band is drawn and labelled in (a), the calibration area (Tokyo) is drawn with an
open marker so that the nine transfer areas read on their own, legends sit below the panels so that no data
point is covered, and the figure is drawn at print width so that no text falls below 7 pt.

Output: manuscript/figs/fig_validation.pdf
"""
import sys, pathlib
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
import sys as _sys_tag
_sys_tag.path.insert(0, str(W / "code" / "engine" / "analysis" / "unified"))
from est_source import offline_source, untagged_suffix
_, TAG = offline_source()   # PAPER_EST_FILE picks the v65 (default) or v66 inputs and output names
FIG = W / "manuscript" / "figs"
TEXT_W = 6.84                              # cas-dc \textwidth = 494.5 pt
plt.rcParams.update({"font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7.5,
                     "xtick.labelsize": 7.2, "ytick.labelsize": 7.5, "legend.fontsize": 7.2,
                     "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 600})
C_DOT, C_RAW, C_BAND = "#2b6cb0", "#c05621", "0.86"

sb = pd.read_csv(W / "results" / "numbers" / f"scoreboard_{TAG}.csv")
sb.columns = [c.lstrip("﻿") for c in sb.columns]
sb = sb.iloc[::-1].reset_index(drop=True)          # north at the top (rows are drawn from the bottom)
y = np.arange(len(sb))
cal = (sb.utility == "TEPCO").values               # the calibration area gets an open marker


def dots(ax, x, color, s=26):
    ax.scatter(x[~cal], y[~cal], s=s, color=color, zorder=3, lw=0)
    ax.scatter(x[cal], y[cal], s=s, facecolor="white", edgecolor=color, lw=1.2, zorder=3)


def rows(ax):
    ax.set_yticks(y)
    ax.set_ylim(-0.6, len(sb) - 0.4)
    ax.grid(axis="y", color="0.9", lw=0.6, zorder=0)
    ax.grid(axis="x", color="0.9", lw=0.6, zorder=0)
    ax.set_axisbelow(True)


fig, AX = plt.subplots(1, 3, figsize=(TEXT_W, 2.75), gridspec_kw=dict(width_ratios=[1.12, 1.0, 1.0]))

# (a) annual coverage and the physically expected band
ax = AX[0]
rows(ax)
if {"Band_lo_pct", "Band_hi_pct"} <= set(sb.columns):
    # v6.6 (criterion B): each area is judged against its own loss-scaled band, drawn on its row
    for yi, lo_, hi_ in zip(y, sb.Band_lo_pct, sb.Band_hi_pct):
        ax.fill_betweenx([yi - 0.38, yi + 0.38], lo_, hi_, color=C_BAND, zorder=0, lw=0)
    BAND_LB = "physically expected band of the area"
else:
    ax.axvspan(102, 108, color=C_BAND, zorder=0, lw=0)
    BAND_LB = "physically expected band (102–108 %)"
ax.axvline(100, color="0.35", lw=0.7, zorder=1)
dots(ax, sb.Annual_pct.values, C_DOT)
ax.set_yticklabels(sb.Area)
# Limits follow the data (v6.6: Okinawa at 126 %), never below the v6.5 frame of 88-112 %.
_amax = float(sb['Annual_pct'].max())
_hi = max(112.0, 5 * __import__('math').ceil((_amax + 3) / 5))
ax.set_xlim(88, _hi)
ax.set_xticks(list(range(90, int(_hi) + 1, 5 if _hi <= 115 else 10)))
ax.set_xlabel("annual coverage of sales (%)")
ax.set_title("(a) annual coverage", pad=4)
for yi, v in zip(y, sb.Annual_pct):          # labels point away from the 100 % line
    ax.annotate(f"{v:g}", (v, yi), xytext=(4 if v >= 100 else -4, 0), textcoords="offset points",
                ha="left" if v >= 100 else "right", va="center", fontsize=7.0, color="0.25")
ax.legend(handles=[Patch(color=C_BAND, label=BAND_LB),
                   Line2D([], [], ls="", marker="o", ms=5, color=C_DOT, label="other nine areas"),
                   Line2D([], [], ls="", marker="o", ms=5, mfc="white", mec=C_DOT, mew=1.2,
                          label="Tokyo (calibration area)")],
          loc="upper center", bbox_to_anchor=(0.42, -0.2), ncol=1, frameon=False,
          handlelength=1.4, labelspacing=0.25)

# (b) monthly coverage error before and after harmonizing the calendar
ax = AX[1]
rows(ax)
raw, harm = 100 * sb.Monthly_CV_raw.values, 100 * sb.Monthly_CV_harm.values
for yi, a, b in zip(y, raw, harm):
    ax.plot([a, b], [yi, yi], color="0.72", lw=1.2, zorder=2)
ax.scatter(raw, y, s=24, facecolor="white", edgecolor=C_RAW, lw=1.2, zorder=3)
dots(ax, harm, C_DOT, s=24)
ax.set_yticklabels([])
_cmax = 100 * float(sb[['Monthly_CV_raw', 'Monthly_CV_harm']].max().max())
ax.set_xlim(0, max(13.0, 1.1 * _cmax))   # follows the data (v6.6: Kyushu raw 14.1 %)
ax.set_xlabel("monthly coverage error, CV (%)")
ax.set_title("(b) monthly coverage error", pad=4)
ax.legend(handles=[Line2D([], [], ls="", marker="o", ms=5, mfc="white", mec=C_RAW, mew=1.2,
                          label="billing months (raw)"),
                   Line2D([], [], ls="", marker="o", ms=5, color=C_DOT, label="calendar-harmonized")],
          loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=1, frameon=False,
          handlelength=1.4, labelspacing=0.25)

# (c) municipal spatial correlation
ax = AX[2]
rows(ax)
dots(ax, sb.Spatial_r.values, C_DOT)
ax.set_yticklabels([])
ax.set_xlim(0.5, 1.0)
ax.set_xlabel("spatial correlation $r$")
ax.set_title("(c) municipal spatial correlation", pad=4)
for yi, v in zip(y, sb.Spatial_r):
    ax.annotate(f"{v:.2f}", (v, yi), xytext=(-5, 0), textcoords="offset points",
                ha="right", va="center", fontsize=7.0, color="0.25")

fig.tight_layout(w_pad=1.2)
fig.savefig(FIG / f"fig_validation{untagged_suffix(TAG)}.pdf", bbox_inches="tight", pad_inches=0.02)
print(f"[output] {FIG / f'fig_validation{untagged_suffix(TAG)}.pdf'}")
