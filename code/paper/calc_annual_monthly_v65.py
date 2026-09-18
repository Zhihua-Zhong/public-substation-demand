# -*- coding: utf-8 -*-
"""論文の中核表のうち Annual(%) と Monthly CV(raw) を v6.5 の離線データから計算する。

論文の定義(validation_v63.tex の caption より):
  Annual (%)      : 区域の推計合計 ÷ 販売統計(高圧+低圧)。理想帯は 102〜108%
                    (送電端は販売端を配電損失のぶん上回る)
  Monthly CV(raw) : 月ごとの「推計 ÷ 高圧+低圧販売」比の変動係数(検針日調和の前)

データベースには接続しない。`data/offline/*.parquet` のみを読む。
"""
import sys, pathlib
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)
OUT.mkdir(parents=True, exist_ok=True)

JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu","HOKURIKU":"Hokuriku",
      "KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku","KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
ORDER = list(JA)

# ── 推計(FY2024)。台帳被覆基準へ絞る(論文の局数定義に合わせる) ──
print("[読込] 推計 …", flush=True)
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet")
km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
sm = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","node_type"])
sm = sm[sm.node_type=="haihen"][["utility","station_id"]].rename(columns={"station_id":"src_name"})
keep = (km.merge(sm, on=["utility","src_name"])[["utility","key"]]
          .drop_duplicates().rename(columns={"key":"station_id"}))
est = est.merge(keep, on=["utility","station_id"], how="inner")
print(f"   台帳被覆基準に絞込: {est.station_id.nunique():,}局 / {len(est):,}行")

# 月別の電力量(GWh) = 平均MW × 当月時間数 ÷ 1000
est["ym"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo").dt.to_period("M")
mon_mwh = est.groupby(["utility","ym"], observed=True)["demand_net_mw"].sum()   # MW×h = MWh
est_gwh = (mon_mwh/1000.0).rename("est_gwh").reset_index()

# ── 販売統計(高圧+低圧・FY2024) ──
egc = pd.read_parquet(OFF/"area_demand_by_voltage.parquet")
egc = egc[egc.voltage_class.isin(["high","low"])].copy()
egc["ym"] = pd.to_datetime(egc.year_month).dt.to_period("M")
fy = pd.period_range("2024-04", "2025-03", freq="M")
egc = egc[egc.ym.isin(fy)]
egc_gwh = egc.groupby(["utility","ym"], observed=True)["demand_gwh"].sum().rename("egc_gwh").reset_index()

m = est_gwh.merge(egc_gwh, on=["utility","ym"], how="inner")
m["ratio"] = m.est_gwh / m.egc_gwh

rows = []
for u in ORDER:
    g = m[m.utility == u]
    if g.empty: continue
    annual = 100.0 * g.est_gwh.sum() / g.egc_gwh.sum()
    cv = g.ratio.std(ddof=0) / g.ratio.mean()
    rows.append(dict(Area=JA[u], utility=u, n_month=len(g),
                     Annual_pct=round(annual, 1), Monthly_CV_raw=round(cv, 3)))
res = pd.DataFrame(rows)
res.to_csv(OUT/f"annual_monthly_{TAG}.csv", index=False, encoding="utf-8-sig")

# ── 原稿(v6.3)との対比 ──
V63 = {"Hokkaido":(95,0.070),"Tohoku":(105,0.096),"Tokyo":(108,0.095),"Chubu":(105,0.120),
       "Hokuriku":(96,0.079),"Kansai":(104,0.119),"Chugoku":(98,0.104),"Shikoku":(97,0.112),
       "Kyushu":(101,0.107),"Okinawa":(97,0.083)}
print(f"\n{'Area':<10}{'Annual v6.3':>12}{'v6.5':>8}{'差':>7}   {'CV v6.3':>9}{'v6.5':>8}{'差':>8}")
for _, r in res.iterrows():
    a3, c3 = V63[r.Area]
    print(f"{r.Area:<10}{a3:>12}{r.Annual_pct:>8}{r.Annual_pct-a3:>+7.1f}   "
          f"{c3:>9.3f}{r.Monthly_CV_raw:>8.3f}{r.Monthly_CV_raw-c3:>+8.3f}")
print(f"\n[出力] {OUT/f'annual_monthly_{TAG}.csv'}")
print(f"月数の確認(各区域12か月であること): {sorted(res.n_month.unique())}")
