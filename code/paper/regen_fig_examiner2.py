#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate fig_examiner2.pdf (Fig. 3) only: the benchmark-noise floor test in the calibration area.

Reads the clean floor series (results/micro/v65_floor_monthly.csv) and prints the canonical coefficients of
variation from results/micro/v65_clean_all.json (section "floor"). Does not rewrite any tex.

Round-1 revision (E28, R3-m8): the former panel (a), the meter-reading calendar bridge by area, is removed
because it showed the same quantity as Fig. 4b. The figure is now the single floor-test panel, drawn at
single-column width (3.30 in) so that no text falls below 7 pt. Coefficients of variation are printed as
percentages (E29).
"""
import sys, json, pathlib
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding="utf-8")
WS   = str(pathlib.Path(__file__).resolve().parents[2])
HERE = f"{WS}/results/micro"
import sys as _sys_tag
_sys_tag.path.insert(0, str(__import__("pathlib").Path(WS) / "code" / "engine" / "analysis" / "unified"))
from est_source import offline_source, untagged_suffix
_, TAG = offline_source()   # PAPER_EST_FILE picks the v65 (default) or v66 inputs and output names
FIG  = f"{WS}/manuscript/figs"
COL_W = 3.30                               # cas-dc \columnwidth = (494.5 pt - 18 pt) / 2 = 238.3 pt
plt.rcParams.update({"font.size": 7.5, "axes.labelsize": 7.5, "xtick.labelsize": 7.2,
                     "ytick.labelsize": 7.2, "legend.fontsize": 7.2,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.6, "savefig.dpi": 600})
C_T, C_E, C_R = "#111111", "#1d6fb8", "#0f9d58"
fl = pd.read_csv(f"{HERE}/{TAG}_floor_monthly.csv")
fl.columns = [c.lstrip("﻿") for c in fl.columns]
cv = json.load(open(f"{HERE}/{TAG}_clean_all.json", encoding="utf-8"))["floor"]
pct = lambda v: f"{100*v:.1f} %"

fig, ax = plt.subplots(figsize=(COL_W, 2.35))
x = np.arange(12)
lab = [pd.Timestamp(m + "-01").strftime("%b") for m in fl.month]
ax.axhline(1.0, color="#999", lw=0.7, ls=":")
ax.plot(x, fl.truth_egc, "-o", ms=3.2, color=C_T, lw=1.5, label=f"ground truth / sales (CV {pct(cv['cv_truth_egc'])})")
ax.plot(x, fl.est_egc,   "-s", ms=3.0, color=C_E, lw=1.5, label=f"estimate / sales (CV {pct(cv['cv_est_egc'])})")
ax.plot(x, fl.est_truth, "-^", ms=3.0, color=C_R, lw=1.5, label=f"estimate / ground truth (CV {pct(cv['cv_est_truth'])})")
ax.set_xticks(x); ax.set_xticklabels(lab)
ax.set_xlim(-0.5, 11.5)
ax.set_xlabel("month of fiscal year 2024 (April 2024 to March 2025)")
ax.set_ylabel("monthly ratio")
ax.legend(frameon=False, loc="upper center", ncol=1, handlelength=2.2, borderaxespad=0.2, labelspacing=0.3)
ax.set_ylim(0.64, 1.52)
fig.tight_layout(pad=0.3)
fig.savefig(f"{FIG}/fig_examiner2{untagged_suffix(TAG)}.pdf", bbox_inches="tight", pad_inches=0.02); plt.close(fig)
print(f"[output] fig_examiner2.pdf (single column; mean est/truth={fl.est_truth.mean():.3f}, "
      f"truth/sales={fl.truth_egc.mean():.3f}, est/sales={fl.est_egc.mean():.3f})")
