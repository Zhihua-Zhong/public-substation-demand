# -*- coding: utf-8 -*-
"""中核表の Monthly CV (harm.) を v6.5 から計算する。

論文の定義(validation_v63.tex §Bridge two):
  販売統計は検針の暦にのっており、暦月から約半月遅れる。系統運用者の暦どおりの月別需要
  (OCCTO)に前月を混ぜ、販売統計を最もよく再現する混合重み w を区域ごとに推定する。
  **重みは二つの検定者(OCCTO と 販売統計)の間だけで推定し、推計は一切関与しない。**
  調和後の暦で読み直すと、月別の被覆誤差は 7〜12% から 4.2〜7.5% へ下がる。

  harmonized_sales(m) = (1-w)·EGC(m) + w·EGC(m-1) に相当する暦へ推計を読み替える。
  実装は OCCTO 側で w を推定し、その w を用いて販売統計を暦月へ引き戻す。

離線層のみを読む。
"""
import sys, pathlib
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)

JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu","HOKURIKU":"Hokuriku",
      "KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku","KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
AC = {1:"HOKKAIDO",2:"TOHOKU",3:"TEPCO",4:"CHUBU",5:"HOKURIKU",6:"KANSAI",7:"CHUGOKU",8:"SHIKOKU",9:"KYUSHU",10:"OKINAWA"}
FY = pd.period_range("2024-04","2025-03",freq="M")

# ── 検定者1: 系統運用者の暦どおり月別需要(OCCTO) ──
occ = pd.read_parquet(OFF/"occto_supply_demand.parquet")
occ["utility"] = occ.area_code.map(AC)
occ["ts"] = pd.to_datetime(occ.ts, utc=True).dt.tz_convert("Asia/Tokyo")
occ["ym"] = occ.ts.dt.to_period("M")
occ_m = occ.groupby(["utility","ym"], observed=True)["demand_mw"].sum().rename("occto_mwh").reset_index()

# ── 検定者2: 販売統計(高圧+低圧) ──
egc = pd.read_parquet(OFF/"area_demand_by_voltage.parquet")
egc = egc[egc.voltage_class.isin(["high","low"])].copy()
egc["ym"] = pd.to_datetime(egc.year_month).dt.to_period("M")
egc_m = egc.groupby(["utility","ym"], observed=True)["demand_gwh"].sum().rename("egc_gwh").reset_index()
egc_m["egc_mwh"] = egc_m.egc_gwh * 1000.0

# ── 混合重み w の推定(検定者どうしのみ。推計は関与しない) ──
两 = occ_m.merge(egc_m[["utility","ym","egc_mwh"]], on=["utility","ym"], how="inner").sort_values(["utility","ym"])
weights = {}
for u, g in 两.groupby("utility", observed=True):
    g = g.sort_values("ym").reset_index(drop=True)
    g["occto_prev"] = g.occto_mwh.shift(1)
    gg = g[g.ym.isin(FY) & g.occto_prev.notna()]
    if len(gg) < 6: continue
    # ★正本(examiner_harmonize.py)と同じ目的関数: 販売統計との相関を最大にする w を選ぶ。
    #   変動係数の最小化で代用すると別の解に落ちる(実測: 0.01〜0.53 と 0.30〜0.75)。
    #   論文本文の記述だけでは目的関数が特定できず、再実装が再現しない箇所である。
    best, bw = None, None
    for w in np.arange(0.0, 1.0001, 0.01):
        mix = (1-w)*gg.occto_mwh + w*gg.occto_prev
        c = np.corrcoef(gg.egc_mwh, mix)[0,1]
        if best is None or c > best: best, bw = c, w
    weights[u] = round(float(bw), 2)

# ── 推計を調和後の暦で読む ──
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet"); km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
sm = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","node_type"])
sm = sm[sm.node_type=="haihen"][["utility","station_id"]].rename(columns={"station_id":"src_name"})
keep = km.merge(sm, on=["utility","src_name"])[["utility","key"]].drop_duplicates().rename(columns={"key":"station_id"})
est = est.merge(keep, on=["utility","station_id"], how="inner")
est["ts"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo")
est["ym"] = est.ts.dt.to_period("M")
est_m = est.groupby(["utility","ym"], observed=True)["demand_net_mw"].sum().rename("est_mwh").reset_index()

rows = []
for u in JA:
    w = weights.get(u)
    e = est_m[est_m.utility==u].sort_values("ym").reset_index(drop=True)
    s = egc_m[egc_m.utility==u].sort_values("ym").reset_index(drop=True)
    if w is None or e.empty or s.empty: continue
    e["est_prev"] = e.est_mwh.shift(1)
    j = e.merge(s[["ym","egc_mwh"]], on="ym").query("ym in @FY")
    raw = (j.est_mwh/j.egc_mwh); cv_raw = raw.std(ddof=0)/raw.mean()
    jj = j[j.est_prev.notna()]
    mix = (1-w)*jj.est_mwh + w*jj.est_prev        # 推計を販売統計の暦へ合わせる
    h = (mix/jj.egc_mwh); cv_h = h.std(ddof=0)/h.mean()
    rows.append(dict(Area=JA[u], utility=u, weight=w,
                     Monthly_CV_raw=round(float(cv_raw),3), Monthly_CV_harm=round(float(cv_h),3)))
res = pd.DataFrame(rows)
res.to_csv(OUT/f"monthly_harm_{TAG}.csv", index=False, encoding="utf-8-sig")

V63 = {"Hokkaido":(0.070,0.047),"Tohoku":(0.096,0.042),"Tokyo":(0.095,0.048),"Chubu":(0.120,0.066),
       "Hokuriku":(0.079,0.053),"Kansai":(0.119,0.055),"Chugoku":(0.104,0.054),"Shikoku":(0.112,0.075),
       "Kyushu":(0.107,0.074),"Okinawa":(0.083,0.056)}
print(f"{'Area':<10}{'w':>6}{'raw v6.3':>10}{'v6.5':>8}   {'harm v6.3':>11}{'v6.5':>8}{'差':>8}")
for _, r in res.iterrows():
    r3, h3 = V63[r.Area]
    print(f"{r.Area:<10}{r.weight:>6.2f}{r3:>10.3f}{r.Monthly_CV_raw:>8.3f}   {h3:>11.3f}{r.Monthly_CV_harm:>8.3f}{r.Monthly_CV_harm-h3:>+8.3f}")
print(f"\n重み範囲: {res.weight.min():.2f}〜{res.weight.max():.2f} (原稿: 0.30〜0.75・多くは0.5付近)")
print(f"調和後CV範囲: {res.Monthly_CV_harm.min():.3f}〜{res.Monthly_CV_harm.max():.3f} (原稿: 0.042〜0.075)")
print(f"[出力] {OUT/f'monthly_harm_{TAG}.csv'}")
