# -*- coding: utf-8 -*-
"""Generators for the numbers the response draft lists as untraceable (review item E8; response_round1.md,
Open items, "Untraceable numbers still in the text"). Offline layer only; no database.

Each definition below reproduces the v6.5 number in the text when run on the v6.5 estimate
(tests/test_e8_v65.py), which is how it was identified:
  1. National totals on the list basis: mean net, gross and behind-the-meter PV summed over the 5,950
     estimate keys of the 5,968 listed names, in GW, each rounded half up to one decimal separately
     (v6.5: 71.0 / 79.3 / 8.2; the unrounded 79.25 needs half up).
  2. Class split per listed name (v6.5: 1,356 / 872 / 3,740; 37.3 % measured).
  3. PV annual generation ratio per area: mean(max(area PV potential - curtailment, 0)) / mean(published
     PV generation), each rounded to MW first, as coverage_reconcile.py does (v6.5: 91-108 %, Tokyo 100 %).
     An engine input, not the estimate: unchanged by the rerun.
  4. Gap decomposition: (supply-demand record - summed estimate) - (extra-high-voltage sales + record -
     total sales), in percentage points of the record; "within 4 percentage points in nine of the ten
     areas" (v6.5: nine; Hokkaido lies at +4.00, on the edge, flagged).
  5. Rooftop share of installed PV against the deviation of the level model's area totals from the centre
     of the loss-scaled band, Pearson r (v6.5 levels: +0.780, p = 0.008; response item 10 asks for it on
     the new levels, which this computes from station_levels_v66.csv).
  6. Spearman rho between capacity-weighted measured coverage and the hourly error of Table 5 (v6.5:
     -0.61, p = 0.06).
Not generated here: the reverse-flow range "0.65-1.88 % by month" (no committed definition reproduces it;
see MANIFEST.md), the threshold sensitivity (gate_sensitivity_v66.py, database), the floor intervals
(floor_bootstrap_v66.py) and the Class 1 endpoint intervals (gate_endpoint_bootstrap.py, existing).

  python code/paper/e8_numbers_v66.py --run results/rerun_v66/run_a
  PAPER_EST_FILE=estimated_demand_fy2024_v66.parquet python code/paper/e8_numbers_v66.py --offline

Outputs: results/numbers/e8_numbers_<tag>.json, e8_area_<tag>.csv
"""
import argparse, pathlib, sys
import numpy as np, pandas as pd
from scipy import stats as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--run", help="v6.6 run directory")
g.add_argument("--offline", action="store_true", help="the offline estimate named by PAPER_EST_FILE")
ap.add_argument("--tag", default=None)
ap.add_argument("--hourly", help="spatial_hourly CSV (default results/numbers/spatial_hourly_<tag>.csv)")
ap.add_argument("--levels", default=str(C.W / "results" / "numbers" / "station_levels_v66.csv"))
a = ap.parse_args()

if a.run:
    run, man = C.check_run_dir(a.run)
    per, tag, source = C.per_key_run(run), a.tag or "v66", f"run:{run.name} (git {man['git_head'][:7]})"
else:
    import est_source
    f, t = est_source.offline_source()
    per, tag, source = C.per_key_offline(f), a.tag or t, f"offline:{f}"
names = C.list_basis(per)
keys = names[["utility", "key"]].drop_duplicates()
x = per.merge(keys, on=["utility", "key"])
assert (len(names), len(keys)) == (5968, 5950), (len(names), len(keys))
out = dict(source=source, basis=dict(names=len(names), keys=len(keys), engine_keys=len(per)))
area = pd.DataFrame(index=C.ORDER); area.index.name = "utility"
area["Area"] = [C.JA[u] for u in C.ORDER]

# 1. National totals
tot = {c: float(x[c].sum()) / 1000.0 for c in ("net", "gross", "pv")}
out["national_totals_gw"] = dict(net=C.half_up(tot["net"], 1), gross=C.half_up(tot["gross"], 1),
                                 pv=C.half_up(tot["pv"], 1), unrounded=tot,
                                 engine_keys_net_unrounded=float(per.net.sum()) / 1000.0,
                                 rounding="each rounded half up to one decimal separately")
area["net_mw"] = x.groupby("utility").net.sum(); area["gross_mw"] = x.groupby("utility").gross.sum()
area["pv_mw"] = x.groupby("utility").pv.sum()

# 2. Class split per listed name
n = names.merge(per[["utility", "key", "src"]], on=["utility", "key"])
cnt = n.src.value_counts()
out["class_split_names"] = {C.CLASS_NAME[s]: int(cnt.get(s, 0)) for s in C.CLASSES}
out["class_split_names"]["measured_pct"] = C.half_up(100 * (cnt.get("z1", 0) + cnt.get("z1s", 0)) / len(n), 1)
for s in C.CLASSES:
    area[f"names_{s}"] = n[n.src == s].groupby("utility").size().reindex(C.ORDER, fill_value=0)

# 3. PV annual generation ratio (coverage_reconcile.py:66-70, 83-86)
pvg = pd.read_parquet(C.OFF / "pv_regional_gen.parquet")
pvg = pvg[(pvg.ts >= "2024-04-01") & (pvg.ts < "2025-04-01")]
cur = pd.read_parquet(C.OFF / "pv_curtailment_fy2024.parquet", columns=["utility", "ts", "pv_curtail_mw"])
j = pvg.merge(cur, on=["utility", "ts"], how="left")
j["pv1"] = (j.pv_potential_mw - j.pv_curtail_mw.fillna(0.0)).clip(lower=0.0)
pv1 = j.groupby("utility").pv1.mean()
occ = pd.read_parquet(C.OFF / "occto_supply_demand.parquet")
occ = occ[(occ.ts >= "2024-04-01") & (occ.ts < "2025-04-01")]
occp = occ.groupby("area_code").pv_actual_mw.mean()
area["pv_ratio_pct"] = [round(100 * round(pv1[u]) / round(occp[C.AREA_CODE[u]])) for u in C.ORDER]
out["pv_annual_ratio_pct"] = dict(min=int(area.pv_ratio_pct.min()), max=int(area.pv_ratio_pct.max()),
                                  tokyo=int(area.at["TEPCO", "pv_ratio_pct"]),
                                  note="engine input, unchanged by the rerun")

# 4. Gap decomposition
b = C.loss_band()
est = x.groupby("utility").net.sum().reindex(C.ORDER)
gap = b.occto_mw - est
pred = b.xh_sales_mw + (b.occto_mw - b.all_sales_mw)
area["gap_mw"] = gap; area["gap_predicted_mw"] = pred
area["gap_residual_pp_of_record"] = 100 * (gap - pred) / b.occto_mw
r4 = area.gap_residual_pp_of_record
out["gap_decomposition"] = dict(
    n_within_4pp=int((r4.abs() <= 4.0).sum()), n_within_4pp_at_1dp=int((r4.round(1).abs() <= 4.0).sum()),
    outside=area[r4.abs() > 4.0].Area.tolist(),
    near_edge=area[(r4.abs() - 4.0).abs() < 0.05].Area.tolist(),
    definition="residual = (record - summed estimate) - (extra-high-voltage sales + record - all sales), "
               "in percentage points of the record")

# 5. Rooftop share against the level model's deviation from the band centre
lv = pd.read_csv(a.levels, encoding="utf-8-sig")
lev = lv.groupby("utility")["level"].sum().reindex(C.ORDER)
ctr = np.sqrt(b.band_lo * b.band_hi)
dev = np.log((lev / b.hl_sales_mw) / ctr)
pvs = pd.read_parquet(C.OFF / "substation_pv.parquet")
sm = pd.read_parquet(C.OFF / "substation_master.parquet", columns=["utility", "station_id", "node_type"])
sm = sm[sm.node_type == "haihen"][["utility", "station_id"]]
pa = pvs.merge(sm, on=["utility", "station_id"], how="inner").groupby("utility")[["pv_res_kw", "pv_total_kw"]].sum()
roof = (pa.pv_res_kw / pa.pv_total_kw).reindex(C.ORDER)
r5, p5 = st.pearsonr(roof, dev)
area["rooftop_share"] = roof; area["level_dev_from_band_centre_log"] = dev
out["rooftop_share_correlation"] = dict(pearson_r=round(float(r5), 3), p=round(float(p5), 3),
                                        levels=pathlib.Path(a.levels).name, levels_sha256=C.sha256(a.levels))

# 6. Spearman rho: capacity-weighted measured coverage against the hourly error
hp = pathlib.Path(a.hourly) if a.hourly else C.W / "results" / "numbers" / f"spatial_hourly_{tag}.csv"
xc = x.merge(lv[["utility", "key", "cap"]], on=["utility", "key"], how="left")
assert xc.cap.notna().all()
xc["meas"] = xc.src.isin(["z1", "z1s"])
area["measured_coverage_capw"] = xc.groupby("utility").apply(
    lambda d: float((d.cap * d.meas).sum() / d.cap.sum()), include_groups=False).reindex(C.ORDER)
if hp.exists():
    h = pd.read_csv(hp, encoding="utf-8-sig").set_index("Area").Hourly_pct
    area["hourly_pct"] = [float(h[C.JA[u]]) for u in C.ORDER]
    rho, p6 = st.spearmanr(area.measured_coverage_capw, area.hourly_pct)
    out["coverage_hourly_spearman"] = dict(rho=round(float(rho), 2), p=round(float(p6), 2),
                                           rho_raw=float(rho), p_raw=float(p6), hourly=hp.name)
else:
    out["coverage_hourly_spearman"] = dict(status=f"pending: {hp.name} not found (calc_spatial_hourly_v65.py "
                                                  "with PAPER_EST_FILE on the v6.6 file writes it)")

out["reverse_flow_by_month"] = dict(status="not generated: no committed definition reproduces 0.65-1.88 %; "
                                           "see MANIFEST.md")
p1 = C.out_path("results/numbers", f"e8_numbers_{tag}.json", tag)
p2 = C.out_path("results/numbers", f"e8_area_{tag}.csv", tag)
C.write_json(p1, out)
area.reset_index().to_csv(p2, index=False, encoding="utf-8-sig", lineterminator="\n", float_format="%.6g")
import json
print(json.dumps({k: v for k, v in out.items()}, ensure_ascii=False, indent=1, default=str))
print(f"[out] {p1}\n[out] {p2}")
