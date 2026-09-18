#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E15 (R1-M6, R2-M2, R2-M4): stronger baselines on the canonical evaluation set, skill scores,
and a negative control for the benchmark-noise floor test.

Baselines, all scored with the canonical station metric on the same 1,216 Tokyo substations:
  kva         load allocation of the area total by capacity: C_i / sum C x A(t). A(t) is the
              estimate's hourly total over list coverage, sum C the engine capacity over the
              same keys. Level and shape both come from capacity and the area; no substation
              information is used. This is the kVA allocation of DSO practice applied to the
              area total, the only upstream flow that is public for every substation.
  area_shape  our level x A_all(t) / mean A_all, as recompute_all_clean.py part C (A_all over
              every estimate key of the area). Its "capacity" row there is the same formula;
              that duplicate is what R1-M6 objected to, so it is not repeated here.
  flat        our level, constant in time (as part C).
  area_shape_pub
              our level x O(t) / mean O, where O(t) is the operator's published hourly area
              demand (public_data.occto_supply_demand, Tokyo = area code 3, half-hours averaged
              to the hour). area_shape takes its shape from the sum of the estimates, which in
              v6.5 carried the Tokyo residual corrections fitted on ground truth (removed in
              v6.6), so that baseline was partly fitted. The published record is independent of
              the estimator (the engine's query guard refuses it) and is used here for
              evaluation only. This is the fair area-shape baseline.
Skill: 1 - CV-RMSE_model / CV-RMSE_baseline, as the ratio of medians, as the pooled MSE ratio
1 - mean(cv_m^2) / mean(cv_b^2), and as the share of stations where the model wins; paired
bootstrap intervals (stations resampled). By class as well.

Floor negative control: the monthly ratios of recompute_all_clean.py part A (truth, estimate
and each baseline summed over the evaluation set, divided by high + low voltage sales) with the
CV of each, an i.i.d. and a circular block bootstrap interval (block 3, the reported design),
and the block-bootstrap interval of CV(x / sales) - CV(truth / sales). A baseline whose
interval also contains 0 "reaches the floor" as well, so the test does not separate
estimators (R2-M2.2).

Inputs: offline estimate (PAPER_EST_FILE) and Tokyo truth, results/micro/{TAG}_micro_clean.csv,
results/numbers/station_levels_v66.csv, offline sales.
Outputs: results/micro/e15_baselines_{TAG}.csv, e15_skill_{TAG}.csv, e15_floor_negctrl_{TAG}.csv,
e15_floor_monthly_{TAG}.csv.
"""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E15 station baselines")
rng = np.random.default_rng(20260916)
pop = io.population()
keys = list(pop.key)
T = io.tokyo_truth(keys)
e = io.est_long("TEPCO", ("demand_net_mw",))
E = io.est_wide(e, keys, "demand_net_mw")
io.check_population(pop, T, E)

lc = io.list_coverage()
lc_keys = sorted(set(lc[lc.utility == "TEPCO"].key) & set(e.station_id.unique()))
cap = io.engine_capacity()
cap = cap[cap.utility == "TEPCO"].set_index("key")["cap"]
lc_keys = [k for k in lc_keys if k in cap.index]
A_lc, _ = io.area_total(e, lc_keys, "demand_net_mw")
A_all, _ = io.area_total(e, sorted(e.station_id.unique()), "demand_net_mw")
sumC = float(cap.reindex(lc_keys).sum())
C = pop.key.map(cap).values
print(f"  area total over {len(lc_keys)} list-coverage keys (sum C {sumC:.0f} MW); "
      f"{int(np.isnan(C).sum())} evaluated stations without an engine capacity")

oc = pd.read_parquet(io.OFF / "occto_supply_demand.parquet", columns=["area_code", "ts", "demand_mw"])
oc = oc[oc.area_code == 3].copy()
oc["h"] = oc.ts.str.slice(0, 13)
O = oc.groupby("h")["demand_mw"].mean().reindex(io.IDX.strftime("%Y-%m-%d %H")).values.astype(float)
assert np.isfinite(O).all() and 25000 < O.mean() < 40000, "published Tokyo area demand missing or not Tokyo"
print(f"  published Tokyo area demand: 8,760 hours, mean {O.mean():.0f} MW; corr with the estimate's "
      f"area total {np.corrcoef(O, A_all)[0, 1]:.3f}")

lev = np.nanmean(E, axis=0)                                  # our annual level (all hours)
BASE = {
    "ours": lambda j: E[:, j],
    "kva": lambda j: C[j] / sumC * A_lc,
    "area_shape": lambda j: lev[j] * A_all / A_all.mean(),
    "area_shape_pub": lambda j: lev[j] * O / O.mean(),
    "flat": lambda j: np.full(io.H, lev[j]),
}
M = {}
for name, f in BASE.items():
    rows = []
    for j, k in enumerate(keys):
        s = io.station_metric(f(j), T[:, j])
        rows.append(dict(key=k, src=pop.src[j], **(s or dict(mt=np.nan, me=np.nan, ape=np.nan, corr=np.nan, cv=np.nan))))
    M[name] = pd.DataFrame(rows)
# the ours row must be the canonical Table 1 row
assert np.allclose(M["ours"].cv.values, pop.cv.values), "ours does not reproduce the canonical CV-RMSE"
# per-substation metrics of every method, so that paired statistics (win share, skill) can be inspected
pd.concat({m: d.set_index("key")[["src", "ape", "corr", "cv"]] for m, d in M.items()}, axis=1).to_csv(
    io.out("micro", f"e15_station_cv_{io.TAG}.csv"), encoding="utf-8-sig")

def summary(d):
    n = len(d)
    return dict(n=n, ape=float(d.ape.median()), ape_lo=io.boot_ci(lambda i: np.median(d.ape.values[i]), n, rng, 1000)[0],
                ape_hi=io.boot_ci(lambda i: np.median(d.ape.values[i]), n, rng, 1000)[1],
                corr=float(d["corr"].median()) if d["corr"].notna().any() else np.nan,
                cv=float(d.cv.median()), c08=100 * float((d["corr"] >= 0.8).mean()),
                p90_ape=float(d.ape.quantile(0.9)),
                signed_lr_med=float(np.median(np.log(d.me / d.mt))))
tab = pd.DataFrame([dict(method=m, cls=c, **summary(M[m] if c == "all" else M[m][M[m].src == c]))
                    for m in BASE for c in ["all"] + io.CLASSES])
tab.to_csv(io.out("micro", f"e15_baselines_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

sk = []
for b in ["kva", "area_shape", "area_shape_pub", "flat"]:
    for c in ["all"] + io.CLASSES:
        mo, mb = M["ours"], M[b]
        sel = np.ones(len(mo), bool) if c == "all" else (mo.src == c).values
        co, cb = mo.cv.values[sel], mb.cv.values[sel]
        n = len(co)
        f_med = lambda i: 1 - np.median(co[i]) / np.median(cb[i])
        f_mse = lambda i: 1 - np.mean(co[i] ** 2) / np.mean(cb[i] ** 2)
        ro, rb = mo["corr"].values[sel], mb["corr"].values[sel]
        sk.append(dict(baseline=b, cls=c, n=n,
                       skill_median_cv=f_med(np.arange(n)), skill_median_cv_ci=io.boot_ci(f_med, n, rng, 1000),
                       skill_mse=f_mse(np.arange(n)), skill_mse_ci=io.boot_ci(f_mse, n, rng, 1000),
                       win_share_cv=100 * float(np.mean(co < cb)),
                       d_corr_median=float(np.nanmedian(ro - rb)) if np.isfinite(rb).any() else np.nan))
sk = pd.DataFrame(sk)
for c in ("skill_median_cv_ci", "skill_mse_ci"):
    sk[c + "_lo"] = sk[c].str[0]; sk[c + "_hi"] = sk[c].str[1]
sk = sk.drop(columns=["skill_median_cv_ci", "skill_mse_ci"])
sk.to_csv(io.out("micro", f"e15_skill_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# ── floor negative control (recompute_all_clean.py part A, same aggregation) ──
G = io.monthly_sales_mw("TEPCO")
def monthly(X):                                               # nanmean over hours of the row sum
    return np.array([np.nanmean(X[io.MO == m].sum(axis=1)) for m in io.MONTHS])
T_m = monthly(T)
series = {"truth": T_m, "ours": monthly(E)}
for b in ["kva", "area_shape", "area_shape_pub", "flat"]:
    series[b] =monthly(np.column_stack([BASE[b](j) for j in range(len(keys))]))
cv = lambda v: float(np.std(v, ddof=0) / np.mean(v))
fl = pd.read_csv(io.MICRO_IN / f"{io.TAG}_floor_monthly.csv", encoding="utf-8-sig")
assert np.allclose(series["ours"] / T_m, fl.est_truth.values, rtol=1e-9), "floor: est/truth differs from the canonical file"
assert np.allclose(T_m / G, fl.truth_egc.values, rtol=1e-9), "floor: truth/sales differs from the canonical file"
NB = 2000
bidx = [io.block_boot_idx(rng) for _ in range(NB)]
iidx = [rng.integers(0, 12, 12) for _ in range(NB)]
rt = T_m / G
out = []
for name, S in series.items():
    rs, rr = S / G, S / T_m
    bb = np.array([cv(rs[i]) for i in bidx]); ib = np.array([cv(rs[i]) for i in iidx])
    dd = np.array([cv(rs[i]) - cv(rt[i]) for i in bidx])
    out.append(dict(series=name, mean_ratio_sales=float(rs.mean()), cv_sales=cv(rs),
                    cv_sales_block_lo=float(np.percentile(bb, 2.5)), cv_sales_block_hi=float(np.percentile(bb, 97.5)),
                    cv_sales_iid_lo=float(np.percentile(ib, 2.5)), cv_sales_iid_hi=float(np.percentile(ib, 97.5)),
                    cv_truth=cv(rr), ratio_cv_to_truth_cv=cv(rs) / cv(rt),
                    d_cv_block_lo=float(np.percentile(dd, 2.5)), d_cv_block_hi=float(np.percentile(dd, 97.5)),
                    reaches_floor=bool(np.percentile(dd, 2.5) < 0 < np.percentile(dd, 97.5)) if name != "truth" else None))
fn = pd.DataFrame(out)
fn.to_csv(io.out("micro", f"e15_floor_negctrl_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
pd.DataFrame({"month": io.MONTHS, "sales_mw": G, **{f"{k}_mw": v for k, v in series.items()}}).to_csv(
    io.out("micro", f"e15_floor_monthly_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

pd.set_option("display.width", 220)
print(tab.round(3).to_string(index=False))
print(sk.round(3).to_string(index=False))
print(fn.round(4).to_string(index=False))
print(f"[output] e15_baselines_{io.TAG}.csv, e15_skill_{io.TAG}.csv, e15_floor_negctrl_{io.TAG}.csv, "
      f"e15_floor_monthly_{io.TAG}.csv")
