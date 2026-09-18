#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E17 (R1-M8, R2 minor 4): audit of the two screens of Section 5.1 on the canonical 1,216.

Reverse-flow margin: the 5th percentile of daytime (09-15 h) net load; a substation is flagged
when it is <= 0 (canonical saturation audit, recompute_all_clean.py part D). Measured label:
the same statistic of the ground truth (base rate 20.6 % in v6.5).
Load margin: capacity minus the 95th percentile of net load (gen_headroom_v65.py); flagged
below 10 MW, the threshold of that script. Measured label: the same with the ground truth.
Capacity is the canonical capacity of micro_clean for both sides.

Scored for the estimate and two baselines that use no substation information:
  kva_net     C_i / sum C x the area's hourly net total (the "naive" baseline of gen_headroom,
              which cannot reverse by construction unless the whole area does)
  kva_gross   C_i / sum C x the area's hourly gross total minus the substation's own allocated
              PV v_i(t): the fair baseline of R1-M6, same PV registry, no substation shape
Metrics: AUC of the margin as a ranking of the measured label, precision in the top decile
(the 10 % with the smallest margin) and its lift over the base rate, precision and recall at
the operating threshold, Spearman between estimated and measured margins. For the estimate the
operating-point precision and recall must reproduce the canonical 47 % and 65 % (asserted).
Not done here: propagating the level error into the margins (R1-M8), and a statement on the
non-coincident sums (a wording matter).

Output: results/micro/e17_screen_audit_{TAG}.csv.
"""
import sys, json
import numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E17 screen audit")
pop = io.population()
keys = list(pop.key)
T = io.tokyo_truth(keys)
e = io.est_long("TEPCO", ("demand_net_mw", "demand_gross_mw", "pv_mw"))
E = io.est_wide(e, keys, "demand_net_mw")
PV = io.est_wide(e, keys, "pv_mw")
io.check_population(pop, T, E)
lc = io.list_coverage()
cap = io.engine_capacity(); cap = cap[cap.utility == "TEPCO"].set_index("key")["cap"]
lc_keys = [k for k in sorted(set(lc[lc.utility == "TEPCO"].key) & set(e.station_id.unique())) if k in cap.index]
A, _ = io.area_total(e, lc_keys, "demand_net_mw")
G, _ = io.area_total(e, lc_keys, "demand_gross_mw")
sumC = float(cap.reindex(lc_keys).sum())
Ce = pop.key.map(cap).values
V = np.isfinite(T) & np.isfinite(E)
C = pop.cap.values
TH = 10.0

def stats(X):
    p5 = np.full(len(keys), np.nan); p95 = np.full(len(keys), np.nan)
    for j in range(len(keys)):
        d = io.DAY & V[:, j]
        if d.sum() >= 500:
            p5[j] = np.percentile(X(j)[d], 5)
        p95[j] = np.percentile(X(j)[V[:, j]], 95)
    return p5, C - p95
X = {"truth": lambda j: T[:, j], "ours": lambda j: E[:, j],
     "kva_net": lambda j: Ce[j] / sumC * A, "kva_gross": lambda j: Ce[j] / sumC * G - np.nan_to_num(PV[:, j])}
S = {k: stats(f) for k, f in X.items()}
lab_rev = S["truth"][0] <= 0
lab_load = S["truth"][1] < TH

def audit(score, label, truth_score, flag):
    ok = np.isfinite(score) & np.isfinite(truth_score)
    s, l, ts, f = score[ok], label[ok], truth_score[ok], flag[ok]
    n10 = int(np.ceil(0.1 * len(s)))
    top = np.argsort(s, kind="mergesort")[:n10]
    tp = int((f & l).sum())
    return dict(n=int(ok.sum()), base_rate=100 * float(l.mean()), flagged=100 * float(f.mean()),
                auc=io.auc(-s, l), top10_precision=100 * float(l[top].mean()),
                top10_lift=float(l[top].mean() / l.mean()),
                precision=100 * tp / max(int(f.sum()), 1), recall=100 * tp / max(int(l.sum()), 1),
                spearman=float(spearmanr(s, ts)[0]) if np.std(s) > 0 else np.nan)
rows = []
for m in ["ours", "kva_net", "kva_gross"]:
    p5, lm = S[m]
    rows.append(dict(screen="reverse_flow_margin", method=m, **audit(p5, lab_rev, S["truth"][0], p5 <= 0)))
    rows.append(dict(screen="load_margin", method=m, **audit(lm, lab_load, S["truth"][1], lm < TH)))
r = pd.DataFrame(rows)
ref = json.loads((io.MICRO_IN / f"{io.TAG}_clean_all.json").read_text(encoding="utf-8"))["saturation"]
o = r[(r.screen == "reverse_flow_margin") & (r.method == "ours")].iloc[0]
assert round(o.precision) == ref["precision"] and round(o.recall) == ref["recall"], "reverse-flow screen does not reproduce the canonical audit"
r.to_csv(io.out("micro", f"e17_screen_audit_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 220)
print(r.round(3).to_string(index=False))
print(f"[output] e17_screen_audit_{io.TAG}.csv")
