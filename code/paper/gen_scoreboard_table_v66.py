# -*- coding: utf-8 -*-
"""Table 5 (tab:scoreboard) in the v6.6 format. A patched copy of gen_scoreboard_table_v65.py, which stays
unchanged for the v6.5 targets of the reproduction gate.

Changes from gen_scoreboard_table_v65.py, and nothing else (SUPERVISOR_DECISIONS_R1.md, rulings of
2026-09-15, "Table 5"; ACCEPTANCE_CRITERIA_R1.md, criterion B):
  1. The annual column of the LaTeX rows becomes the signed gap, in percentage points, between the
     estimate-to-sales ratio and the area's loss-scaled band (v66_common.loss_band): 0 inside the band,
     negative below, positive above, one decimal. The ratio itself stays in scoreboard_<tag>.csv
     (Annual_pct) for the text and Fig. 4, next to the band edges and the gap.
  2. Monthly CV raw and harmonized are printed in per cent with one decimal (were fractions, three
     decimals). The CSV keeps the fractions and adds the per-cent columns.
  3. Outputs go through v66_common.out_path, so a v6.5-tagged table never lands in the workspace.
Sources and rounding of every other column are unchanged: Stations / Measured on the list basis;
Monthly CV from the canonical examiner_harmonize.py output; Spatial r from p3_meti_spatial.py;
Daily / Hourly from calc_spatial_hourly_v65.py. Rounding is half up throughout.
"""
import sys, pathlib
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
W = C.W
OFF, NUM = W / "data" / "offline", W / "results" / "numbers"
from est_source import offline_source, untagged_suffix   # v66_common puts the engine directory on sys.path
EST_FILE, TAG = offline_source()   # PAPER_EST_FILE=estimated_demand_fy2024_v66.parquet for v6.6

JA = C.JA
ORDER = list(JA)
half_up = C.half_up

# ── Stations / Measured (list basis, via station_key_map) ── unchanged
est = pd.read_parquet(OFF/EST_FILE, columns=["utility","station_id","src"])
per = est.groupby(["utility","station_id"], observed=True)["src"].max().reset_index()
km = pd.read_parquet(OFF/"station_key_map.parquet")
km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
sm = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","node_type"])
sm = sm[sm.node_type=="haihen"][["utility","station_id"]].rename(columns={"station_id":"src_name"})
d = (per.merge(km, left_on=["utility","station_id"], right_on=["utility","key"])
        .merge(sm, on=["utility","src_name"]).drop_duplicates(["utility","src_name"]))
g = d.groupby("utility").agg(Stations=("src_name","size"),
                             Measured=("src", lambda s: int(s.isin(["z1","z1s"]).sum())))

# ── Columns ── unchanged sources
ann = pd.read_csv(NUM/f"annual_monthly_{TAG}.csv").set_index("utility")
ENG_OUT = W/"code"/"engine"/"analysis"/"unified"/"out"
if TAG == "v65":
    exm = pd.read_csv(W/"results"/"frozen_inputs"/"examiner_harmonized_fy2024.csv")
else:   # v6.6: output of the canonical examiner_harmonize.py rerun on the v6.6 estimate (E7)
    exm = pd.read_csv(ENG_OUT/f"examiner_harmonized_fy2024{untagged_suffix(TAG)}.csv")
exm = exm.set_index("utility")
p3 = pd.read_csv(ENG_OUT/f"p3_meti_spatial{untagged_suffix(TAG)}.csv")
p3 = p3.set_index(p3.columns[0])
dh = pd.read_csv(NUM/f"spatial_hourly_{TAG}.csv").set_index("Area")
band = C.loss_band()                                   # change 1: the area's loss-scaled band

rows, tex = [], []
for u in ORDER:
    a = JA[u]
    st, me = int(g.at[u,"Stations"]), int(g.at[u,"Measured"])
    annual_1dp = float(ann.at[u,"Annual_pct"])
    annual = half_up(annual_1dp, 0)
    lo, hi = float(band.at[u, "band_lo"]), float(band.at[u, "band_hi"])
    gap = C.signed_gap_pp(annual_1dp, lo, hi)
    gap1 = half_up(gap, 1)
    cvr = float(exm.at[u,"cv_raw12"]); cvh = float(exm.at[u,"cv_harm11"])
    cvr_pct, cvh_pct = half_up(100 * cvr, 1), half_up(100 * cvh, 1)          # change 2
    sr = float(p3.loc[u][[c for c in p3.columns if "corr" in c][0]]) if u in p3.index else float("nan")
    dl = float(dh.at[a,"Daily_pct"]); hr = float(dh.at[a,"Hourly_pct"])
    rows.append(dict(Area=a, utility=u, Stations=st, Measured=me, Annual_pct=annual,
                     Monthly_CV_raw=round(cvr,3), Monthly_CV_harm=round(cvh,3),
                     Spatial_r=round(sr,3), Daily_pct=round(dl,1), Hourly_pct=round(hr,1),
                     Annual_pct_1dp=annual_1dp, Band_lo_pct=round(100 * lo, 1), Band_hi_pct=round(100 * hi, 1),
                     Gap_pp=gap1, In_band=bool(gap == 0.0),
                     Monthly_CV_raw_pct=cvr_pct, Monthly_CV_harm_pct=cvh_pct))
    st_tex = f"{st:,}".replace(",", "{,}")
    gap_tex = "0" if gap == 0.0 else (f"$+{gap1:.1f}$" if gap > 0 else f"$-{abs(gap1):.1f}$")
    tex.append(f"{a} & {st_tex} & {me} & {gap_tex} & {cvr_pct:.1f} & {cvh_pct:.1f} & {sr:.3f} & {dl:.1f} & {hr:.1f}\\\\")

res = pd.DataFrame(rows)
res.to_csv(C.out_path("results/numbers", f"scoreboard_{TAG}.csv", TAG), index=False, encoding="utf-8-sig")
C.out_path("results/numbers", f"scoreboard_{TAG}_rows.tex", TAG).write_text("\n".join(tex) + "\n", encoding="utf-8")
print(res.to_string(index=False))
print(f"\n[out] scoreboard_{TAG}.csv / scoreboard_{TAG}_rows.tex under {C.OUT_ROOT / 'results' / 'numbers'}")
print(f"areas inside their band: {int(res.In_band.sum())} / 10; Hourly {res.Hourly_pct.min():.1f} to "
      f"{res.Hourly_pct.max():.1f}; raw CV {res.Monthly_CV_raw_pct.min():.1f} to {res.Monthly_CV_raw_pct.max():.1f} %; "
      f"harmonized {res.Monthly_CV_harm_pct.min():.1f} to {res.Monthly_CV_harm_pct.max():.1f} %")
