#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E15 (R1-M6): single-lambda null for the annual coverage of Table 5.

The level model gives each area its own load factor lambda_a (0.31 to 0.35 in v6.6) through the
transfer regression. The null gives every area Tokyo's anchor: class 2 and 3 substations get
L_i = C_i x lambda_Tokyo (0.3501), class 1 keeps its read level. If the null lands as close to
the physically expected bands as the model, the regression adds nothing to Table 5.

Annual coverage follows calc_annual_monthly_v65.py exactly (list-coverage basis, sum of hourly
net load over FY2024 divided by high + low voltage sales); the model column must reproduce
results/numbers/annual_monthly_{TAG}.csv (asserted). The null needs only annual sums, so it is
computed from the class-2 and class-3 capacity: C from station_levels_v66.csv (keys without a
capacity keep their own level). Bands: criterion B of ACCEPTANCE_CRITERIA_R1.md,
experiments/level_validation/O_loss_adjusted.csv; the signed gap is 0 inside the band,
negative below, positive above, in percentage points.

In v6.6 the class-2 and class-3 annual mean equals C x lambda_a exactly (run check
max_abs_mean_net_minus_level_class23), so the null is the model rescaled by lambda_T / lambda_a
on that part. For v6.5, whose levels carried an operating probability, the null is the same
v6.6-style C x 0.3501 and is shown only to test the generator.

Output: results/numbers/e15_single_lambda_{TAG}.csv.
"""
import sys
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E15 single-lambda null")
JA = {"HOKKAIDO": "Hokkaido", "TOHOKU": "Tohoku", "TEPCO": "Tokyo", "CHUBU": "Chubu", "HOKURIKU": "Hokuriku",
      "KANSAI": "Kansai", "CHUGOKU": "Chugoku", "SHIKOKU": "Shikoku", "KYUSHU": "Kyushu", "OKINAWA": "Okinawa"}
tb = pq.read_table(io.OFF / io.EST_FILE, columns=["utility", "station_id", "src", "demand_net_mw"])
g = tb.group_by(["utility", "station_id", "src"]).aggregate([("demand_net_mw", "sum"), ("demand_net_mw", "count")])
st = g.to_pandas().rename(columns={"station_id": "key", "demand_net_mw_sum": "mwh", "demand_net_mw_count": "hours"})
assert not st.duplicated(["utility", "key"]).any(), "a station has two classes"
st = st.merge(io.list_coverage(), on=["utility", "key"], how="inner")
cap = io.engine_capacity()
st = st.merge(cap[["utility", "key", "cap", "lambda"]], on=["utility", "key"], how="left")
lam_T = float(io.level_model()["lambda_tepco"])
z23 = st.src.isin(["z1s", "z2"]) & st.cap.notna()
st["mwh_null"] = np.where(z23, st.cap * lam_T * st.hours, st.mwh)

s = pd.read_parquet(io.OFF / "area_demand_by_voltage.parquet")
s = s[s.voltage_class.isin(["high", "low"])].copy()
s["ym"] = pd.to_datetime(s.year_month).dt.strftime("%Y-%m")
sales = s[s.ym.isin(io.MONTHS)].groupby("utility")["demand_gwh"].sum() * 1000.0     # MWh
band = pd.read_csv(io.WS / "experiments" / "level_validation" / "O_loss_adjusted.csv", encoding="utf-8-sig").set_index("utility")
ref = pd.read_csv(io.NUM_IN / f"annual_monthly_{io.TAG}.csv", encoding="utf-8-sig").set_index("utility")

def gap(v, lo, hi):
    return 0.0 if lo <= v <= hi else (v - hi if v > hi else v - lo)
rows = []
for u in JA:
    a = st[st.utility == u]
    lo, hi = 100 * band.at[u, "band_lo"], 100 * band.at[u, "band_hi"]
    am = 100 * a.mwh.sum() / sales[u]; an = 100 * a.mwh_null.sum() / sales[u]
    assert abs(round(am, 1) - ref.at[u, "Annual_pct"]) < 0.051, f"{u}: annual {am:.2f} vs canonical {ref.at[u, 'Annual_pct']}"
    rows.append(dict(Area=JA[u], utility=u, stations=len(a), lambda_a=float(a["lambda"].dropna().iloc[0]),
                     share_z23_pct=100 * float(a[a.src.isin(["z1s", "z2"])].mwh.sum() / a.mwh.sum()),
                     band_lo=lo, band_hi=hi,
                     annual_model=am, gap_model=gap(am, lo, hi), annual_null=an, gap_null=gap(an, lo, hi)))
r = pd.DataFrame(rows)
r["in_band_model"] = r.gap_model == 0; r["in_band_null"] = r.gap_null == 0
nine = r[r.utility != "TEPCO"]
summ = pd.DataFrame([dict(Area="Nine areas", utility="NINE_AREAS",
                          annual_model=nine.annual_model.std(ddof=1), annual_null=nine.annual_null.std(ddof=1),
                          gap_model=float(np.mean(np.abs(nine.gap_model))), gap_null=float(np.mean(np.abs(nine.gap_null))),
                          in_band_model=int(nine.in_band_model.sum()), in_band_null=int(nine.in_band_null.sum()))])
out = pd.concat([r, summ], ignore_index=True)
out.to_csv(io.out("numbers", f"e15_single_lambda_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
pd.set_option("display.width", 220)
print(out.round(3).to_string(index=False))
print("  last row: annual columns = SD across the nine areas; gap columns = mean |gap| (pp); in_band = count")
print(f"[output] e15_single_lambda_{io.TAG}.csv")
