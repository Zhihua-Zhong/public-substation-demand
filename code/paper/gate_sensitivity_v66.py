# -*- coding: utf-8 -*-
"""Sensitivity of the class limits (discussion section 5.3), ported from gate_sensitivity.py for v6.6.

Policy, unchanged: the limits are not swept to choose them; what moving them does is reported. The
calibration-area ground truth measures, for each limit set, (a) the class populations and (b) the median
APE and r by class. The function evaluate() is gate_sensitivity.py's, verbatim.

Changes from gate_sensitivity.py, and nothing else:
  - the grid is the two-class one (ceiling = upper limit), because criterion F merged the measured-shape
    class; the ceiling rows of the three-class grid no longer describe the estimator;
  - every engine query passes the production guard (v66_common.guard_engine: SELECT only, no ground truth,
    no reference statistics, no earlier estimate); the ground truth is read after the estimator has
    returned, from the offline layer (the export of validation.tepco_bank_fy2024_full; the harness test
    shows the canonical metrics reproduce from it);
  - the screened set is <tag>_micro_clean.csv (was hard-coded v65), and the output carries the tag
    (was hard-coded v65_gate_sensitivity.csv, with a misprinted v63 name);
  - the output goes through v66_common.out_path.

  DT_DB_CONTAINER=iwafune_db_frozen OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    python code/paper/gate_sensitivity_v66.py
Output: results/micro/v66_gate_sensitivity.csv. Writes no table.
"""
import argparse, pathlib, sys
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
C.require_frozen_db()
sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="v66")
a = ap.parse_args()

import stage2_engine as E
from stage2_engine import compute_region, IDX, norm2
queries = C.guard_engine(E)
r = compute_region("TEPCO", blend=False)          # before blending: R and lev as they are
stations, lev, R = r["stations"], r["lev"], r["R"]
x0 = r["net"]; PV = r["pv"]
tw = C.truth_wide(IDX, norm2)
idx = {k: i for i, k in enumerate(stations)}
mic = C.W / "results" / "micro"
pop_tag = a.tag if (mic / f"{a.tag}_micro_clean.csv").exists() else "v65"
CLEAN = set(pd.read_csv(mic / f"{pop_tag}_micro_clean.csv").key)
print(f"[population] {pop_tag}_micro_clean.csv: {len(CLEAN)} screened substations; {len(queries)} engine queries")

def evaluate(lo, hi, cap4):
    """Classes under limits (lo, hi, cap4); medians by class against calibration-area ground truth."""
    rows = []
    n1 = n2 = n3 = 0
    for k in stations:
        i = idx[k]
        q = None
        if R is not None and k in R.columns:
            L = float(lev.get(k, np.nan)); rm = float(R[k].mean())
            if np.isfinite(L) and L > 0.5 and rm > 0.5: q = rm / L
        if q is not None and lo <= q <= hi:
            tier, e = 1, R[k].values.astype(float)
            n1 += 1
        elif q is not None and hi < q <= cap4:
            tier = 2; base = R[k].values.astype(float)
            e = float(lev.get(k)) * base / base.mean()
            n2 += 1
        else:
            tier, e = 3, x0[i]
            n3 += 1
        if k not in tw.columns or k not in CLEAN: continue
        t = tw[k].values.astype(float)
        m = np.isfinite(t) & np.isfinite(e)
        if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
        rows.append(dict(tier=tier,
            ape=100*abs(np.nanmean(e[m])-np.nanmean(t[m]))/np.nanmean(t[m]),
            corr=float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m]) > 1e-9 else np.nan))
    d = pd.DataFrame(rows)
    return dict(n1=n1, n2=n2, n3=n3, n_eval=len(d),
                ape=round(float(d.ape.median()), 1),
                corr=round(float(d["corr"].median()), 3))

# Two classes since criterion F merged the measured-shape class: the ceiling equals the upper limit, so no
# substation falls in hi < q <= cap and every one outside [lo, hi] gets the transferred shape. The first row
# is the estimator as run and must reproduce the canonical medians of <tag>_micro_clean.csv.
grid = [(0.6, 1.4, 1.4), (0.5, 1.5, 1.5), (0.7, 1.3, 1.3)]
out = []
for lo, hi, c4 in grid:
    res = evaluate(lo, hi, c4)
    res.update(lo=lo, hi=hi, cap=c4)
    out.append(res)
    print(f"limits [{lo},{hi}] ceiling {c4}: class1={res['n1']:>4} class2={res['n2']:>4} class3={res['n3']:>5} "
          f"| median APE {res['ape']:.1f}% r {res['corr']:.3f} (n={res['n_eval']})", flush=True)
po = C.out_path("results/micro", f"{a.tag}_gate_sensitivity.csv", a.tag)
pd.DataFrame(out).to_csv(po, index=False, encoding="utf-8-sig")
print(f"[out] {po}")
