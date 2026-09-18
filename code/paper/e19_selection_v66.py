#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E19 (R2-M7): ground-truth selection in Tokyo.

(a) Covariate balance. Tokyo substations on the list-coverage basis with an engine capacity are
    split into evaluated (the canonical 1,216), screened out by the admission test (33 in v6.5)
    and not evaluated (no usable truth series). For capacity, the three level covariates, the
    estimated load factor and the class, the table gives the means and the standardised mean
    difference, evaluated against not evaluated (|SMD| > 0.1 is the usual flag).
(b) Sensitivity of the Table 1 statistics (median APE, r, CV-RMSE per class, canonical
    definitions) to the admission rule: canonical (truth LF <= 1), stricter (truth LF <= 0.8,
    R2's example) and inclusive (the 33 screened-out series added back, scored from the hourly
    data exactly as the canonical script scores the others).

Outputs: results/micro/e19_balance_{TAG}.csv, e19_sensitivity_{TAG}.csv.
"""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E19 selection")
pop, dr = io.population(), io.screened_out()
dr = dr[dr.why == "truth exceeds capacity"]
e = io.est_long("TEPCO", ("demand_net_mw",))
cls = io.est_classes(e)
lvl = e.groupby("station_id", sort=True)["demand_net_mw"].mean()
lc = io.list_coverage()
cap = io.engine_capacity(); cap = cap[cap.utility == "TEPCO"].set_index("key")["cap"]
keys = [k for k in sorted(set(lc[lc.utility == "TEPCO"].key) & set(cls.index)) if k in cap.index]
b = pd.DataFrame({"key": keys})
b["cap"] = b.key.map(cap)
b["group"] = np.where(b.key.isin(set(pop.key)), "evaluated", np.where(b.key.isin(set(dr.key)), "screened_out", "not_evaluated"))
cov = io.tokyo_covariates()
b = b.merge(cov, on="key", how="left")
b["mfg"] = b.manu / (b.manu + b.tert)
b["ln_hhcap"] = np.log(b.hh.where(b.hh > 0) / b.cap)
b["pv_dens"] = b.pv_mw / b.cap
b["lf_est"] = b.key.map(lvl) / b.cap
for c in io.CLASSES:
    b[f"is_{c}"] = (b.key.map(cls) == c).astype(float)
b["has_cov"] = b.hh.notna().astype(float)
VARS = ["cap", "mfg", "ln_hhcap", "pv_dens", "lf_est"] + [f"is_{c}" for c in io.CLASSES] + ["has_cov"]
rows = []
for v in VARS:
    x1 = b.loc[b.group == "evaluated", v].dropna(); x0 = b.loc[b.group == "not_evaluated", v].dropna()
    xs = b.loc[b.group == "screened_out", v].dropna()
    sd = np.sqrt((x1.var(ddof=1) + x0.var(ddof=1)) / 2)
    rows.append(dict(variable=v, n_eval=len(x1), n_not=len(x0), n_screened=len(xs),
                     mean_eval=float(x1.mean()), mean_not=float(x0.mean()), mean_screened=float(xs.mean()) if len(xs) else np.nan,
                     smd=float((x1.mean() - x0.mean()) / sd) if sd > 0 else np.nan))
bal = pd.DataFrame(rows)
print(f"  groups: {b.group.value_counts().to_dict()}")
bal.to_csv(io.out("micro", f"e19_balance_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# (b) sensitivity of Table 1
add = [k for k in dr.key if k in set(e.station_id)]
T = io.tokyo_truth(add); E = io.est_wide(e, add, "demand_net_mw")
ex = []
for j, k in enumerate(add):
    s = io.station_metric(E[:, j], T[:, j])
    if s and s["mt"] >= 0.5:
        ex.append(dict(key=k, src=cls[k], **s))
ex = pd.DataFrame(ex)
print(f"  screened-out series scored: {len(ex)} of {len(dr)}")
V = {"canonical": pop, "strict_lf_le_0.8": pop[pop.lf <= 0.8],
     "inclusive_plus_screened": pd.concat([pop, ex], ignore_index=True)}
sr = []
for name, d in V.items():
    for c in ["all"] + io.CLASSES:
        g = d if c == "all" else d[d.src == c]
        sr.append(dict(variant=name, cls=c, n=len(g), ape=float(g.ape.median()), corr=float(g["corr"].median()),
                       cv=float(g.cv.median()), signed_lr_med=float(np.median(np.log(g.me / g.mt))),
                       sum_est_over_truth=float(g.me.sum() / g.mt.sum())))
sen = pd.DataFrame(sr)
sen.to_csv(io.out("micro", f"e19_sensitivity_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 200)
print(bal.round(3).to_string(index=False))
print(sen.round(3).to_string(index=False))
print(f"[output] e19_balance_{io.TAG}.csv, e19_sensitivity_{io.TAG}.csv")
