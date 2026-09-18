#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E15 (R1-M6, R2-M4.1): a population-proportional baseline for the municipal spatial check.

The canonical spatial r (p3_meti_spatial.py) is the median over months of the log-log
correlation between estimated and statistical municipal demand. Municipalities differ in size by
orders of magnitude, so size alone produces a high r. Two baselines that know nothing of any
substation estimate:
  pop       municipal demand proportional to census population
  hh8emp    proportional to households + 8 x employment, the allocation weight p3 itself uses
Both are built from the same mesh allocation and the same substations as the estimate, so the
only difference is the substation estimate. Because the log r, the Spearman correlation and the
dispersion of log(estimate / statistic) are all invariant to a constant per area and month, the
baselines need no area total: no reference statistic enters them.

Per area (median over the 12 months, same filters as p3: both sides > 0.1 MW, >= 10 munis):
  r_log, rho (Spearman), rsd_logratio (1.4826 x MAD of log(x / statistic)).
The estimate's rows come from the canonical output p3_meti_spatial_muni{SFX}.csv and must
reproduce p3_meti_spatial{SFX}.csv (asserted); the baseline weights are rebuilt from the offline
layer, and the generator first checks that they reproduce the estimate's municipal values from the
offline station estimates (asserted for the matched rows).

Output: results/numbers/e15_spatial_baseline_{TAG}.csv.
"""
import sys
import numpy as np, pandas as pd, pyarrow.parquet as pq, pyarrow.compute as pc
from scipy.stats import spearmanr
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io
from est_source import untagged_suffix

io.banner("E15 spatial baseline")
SFX = untagged_suffix(io.TAG)
ENG = io.ENG_OUT_IN
j = pd.read_csv(ENG / f"p3_meti_spatial_muni{SFX}.csv", encoding="utf-8-sig")
p3 = pd.read_csv(ENG / f"p3_meti_spatial{SFX}.csv", encoding="utf-8-sig").set_index("u")

# ── weights per (utility, key, city), as the p3 SQL ──
al = pd.read_parquet(io.OFF / "mesh_substation_alloc.parquet", columns=["mesh_code", "utility", "station_id", "weight"])
sm = pd.read_parquet(io.OFF / "substation_master.parquet", columns=["utility", "station_id", "station_name"])
cm = pd.read_parquet(io.OFF / "mesh_city_map.parquet", columns=["mesh_1km", "city_key"]).dropna(subset=["city_key"])
ce = pd.read_parquet(io.OFF / "census_mesh_1km.parquet", columns=["mesh_1km", "households", "population"])
ec = pd.read_parquet(io.OFF / "econ_census_mesh_1km.parquet", columns=["mesh_1km", "emp_total"])
a = (al.merge(sm, on=["utility", "station_id"]).merge(cm, left_on="mesh_code", right_on="mesh_1km")
       .drop(columns="mesh_1km").merge(ce, left_on="mesh_code", right_on="mesh_1km", how="left")
       .drop(columns="mesh_1km").merge(ec, left_on="mesh_code", right_on="mesh_1km", how="left"))
for c in ("households", "population", "emp_total"):
    a[c] = pd.to_numeric(a[c], errors="coerce").fillna(0.0)
a["sid"] = a.station_name.fillna(a.station_id)
names = a.sid.unique()
a["key"] = a.sid.map(dict(zip(names, [io.norm2(x) for x in names])))
a["hh"] = a.weight * (a.households + 8.0 * a.emp_total)
a["pop"] = a.weight * a.population
w = a.groupby(["utility", "key", "city_key"], as_index=False)[["hh", "pop"]].sum()
w = w[w.hh > 0].rename(columns={"utility": "u", "city_key": "city"})
w["share"] = w.hh / w.groupby(["u", "key"])["hh"].transform("sum")

# ── check: offline station monthly means x share reproduce the canonical municipal estimate ──
tb = pq.read_table(io.OFF / io.EST_FILE, columns=["utility", "station_id", "ts", "demand_net_mw"])
tb = tb.append_column("ym", pc.utf8_slice_codeunits(tb["ts"], 0, 7)).drop(["ts"])
em = tb.group_by(["utility", "station_id", "ym"]).aggregate([("demand_net_mw", "mean")]).to_pandas()
em.columns = ["u", "key", "ym", "mw"]
x = em.merge(w[["u", "key", "city", "share"]], on=["u", "key"])
x["v"] = x.mw * x.share
ce_ = x.groupby(["u", "city", "ym"], as_index=False)["v"].sum()
chk = j.merge(ce_, on=["u", "city", "ym"], how="left")
bad = ~np.isclose(chk.v, chk.est_mw, rtol=1e-6, atol=1e-6)
assert not bad.any(), f"weights do not reproduce the canonical municipal estimate for {int(bad.sum())} of {len(chk)} rows"
print(f"  check: offline weights reproduce the canonical municipal estimate on all {len(chk)} rows")

# baselines on the estimate's substation set
ekeys = em[["u", "key"]].drop_duplicates()
b = w.merge(ekeys, on=["u", "key"]).groupby(["u", "city"], as_index=False)[["hh", "pop"]].sum()
j = j.merge(b, on=["u", "city"], how="left")

def per_month(g, col):
    g = g[(g.est_mw > 0.1) & (g.mw > 0.1) & (g[col] > 0)]
    if len(g) < 10: return None
    lr = np.log(g[col] / g.mw)
    return (float(np.corrcoef(np.log(g[col]), np.log(g.mw))[0, 1]), float(spearmanr(g[col], g.mw)[0]), io.rsd(lr))
rows = []
for u, gu in j.groupby("u", sort=True):
    rec = dict(utility=u, n_muni=gu.city.nunique())
    for name, col in [("est", "est_mw"), ("pop", "pop"), ("hh8emp", "hh")]:
        ms = [per_month(gg, col) for _, gg in gu.groupby("ym", sort=True)]
        ms = np.array([m for m in ms if m is not None])
        rec.update({f"r_log_{name}": float(np.median(ms[:, 0])), f"rho_{name}": float(np.median(ms[:, 1])),
                    f"rsd_logratio_{name}": float(np.median(ms[:, 2]))})
    rows.append(rec)
r = pd.DataFrame(rows)
chk2 = r.set_index("utility").r_log_est.round(3)
assert (np.abs(chk2 - p3.sp_corr_med.reindex(chk2.index)) <= 0.0015).all(), \
    f"estimate r does not reproduce p3_meti_spatial{SFX}.csv"
r.to_csv(io.out("numbers", f"e15_spatial_baseline_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 220)
print(r.round(3).to_string(index=False))
print(f"[output] e15_spatial_baseline_{io.TAG}.csv")
