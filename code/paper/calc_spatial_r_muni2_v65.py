# -*- coding: utf-8 -*-
"""Spatial r(市区町村・月次中央値)を正本 p3_meti_spatial.py と同じ方法で計算する。

正本の方法(p3の docstring と実装より):
  局→市町村の配分行列 = mesh_substation_allocation × mesh_city_map、
  重み = a.weight × (世帯 + 8×従業者)   ← 映射v2(預登録・掃引なし)
  市町村×月の推計 = Σ_局 share(局→市町村) × 推計(局,月)
  指標 = 市町村横断の log-log 相関の月別中央値

前回の点内包(配変の座標が落ちる市町村へ全量を割る)は粗すぎて相関が過小に出た。
本実装は離線層のみを読む。
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
FY = pd.period_range("2024-04","2025-03",freq="M")

# ── 配分行列: (utility, station_id[master], city_key) → share ──
al = pd.read_parquet(OFF/"mesh_substation_alloc.parquet")           # mesh_code, utility, station_id, weight
cm = pd.read_parquet(OFF/"mesh_city_map.parquet")                    # mesh_1km, city_key
cen = pd.read_parquet(OFF/"census_mesh_1km.parquet")                 # mesh_1km, households
eco = pd.read_parquet(OFF/"econ_census_mesh_1km.parquet")            # mesh_1km, emp_total
m = (al.rename(columns={"mesh_code":"mesh_1km"})
       .merge(cm[["mesh_1km","city_key"]], on="mesh_1km", how="inner")
       .merge(cen[["mesh_1km","households"]], on="mesh_1km", how="left")
       .merge(eco[["mesh_1km","emp_total"]], on="mesh_1km", how="left"))
m["w"] = m.weight * (m.households.fillna(0) + 8.0*m.emp_total.fillna(0))
mat = m.groupby(["utility","station_id","city_key"], observed=True)["w"].sum().reset_index()
tot = mat.groupby(["utility","station_id"], observed=True)["w"].transform("sum")
mat["share"] = np.where(tot > 0, mat.w/tot, 0.0)
print(f"[配分行列] {len(mat):,}セル / 局 {mat.station_id.nunique():,} / 市町村 {mat.city_key.nunique():,}")

# ── 推計(局×月) : エンジンID → master へ橋渡ししてから行列を掛ける ──
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet"); km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
est = est.merge(km.rename(columns={"key":"station_id"}), on=["utility","station_id"], how="inner")
est["ts"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo")
est["ym"] = est.ts.dt.to_period("M")
sm_mon = (est.groupby(["utility","src_name","ym"], observed=True)["demand_net_mw"].sum()
             .rename("est_mwh").reset_index().rename(columns={"src_name":"station_id"}))
print(f"[推計 局×月] {len(sm_mon):,}行")

city_est = (sm_mon.merge(mat[["utility","station_id","city_key","share"]],
                         on=["utility","station_id"], how="inner"))
city_est["mwh"] = city_est.est_mwh * city_est.share
ce = city_est.groupby(["utility","city_key","ym"], observed=True)["mwh"].sum().reset_index()

# ── METI 6-1(muni = 県+市を空白なしで連結し city_key に合わせる) ──
meti = pd.read_parquet(OFF/"meti_demand_stats.parquet")
meti = meti[meti.table_source.astype(str).str.startswith("6-1")].copy()
meti["ym"] = pd.to_datetime(meti.year_month).dt.to_period("M")
meti = meti[meti.ym.isin(FY) & (meti.demand_mwh > 0)]
meti["city_key"] = meti.municipality_name.str.replace("　"," ").str.replace(" ","",regex=False).str.strip()
mm = meti.groupby(["city_key","ym"], observed=True)["demand_mwh"].sum().reset_index()

j = ce.merge(mm, on=["city_key","ym"], how="inner")
print(f"[名寄せ] 一致市町村 {j.city_key.nunique():,} / 推計側 {ce.city_key.nunique():,}")

rows = []
for u in JA:
    g = j[j.utility == u]
    rs = []
    for ym, gg in g.groupby("ym", observed=True):
        gg = gg[(gg.mwh > 0) & (gg.demand_mwh > 0)]
        if len(gg) >= 10:
            rs.append(np.corrcoef(np.log(gg.mwh), np.log(gg.demand_mwh))[0,1])
    if rs: rows.append(dict(Area=JA[u], utility=u, n_muni=g.city_key.nunique(),
                            n_month=len(rs), Spatial_r=round(float(np.median(rs)), 3)))
res = pd.DataFrame(rows)
res.to_csv(OUT/f"spatial_r_muni_{TAG}.csv", index=False, encoding="utf-8-sig")

V63 = {"Hokkaido":0.940,"Tohoku":0.916,"Tokyo":0.956,"Chubu":0.945,"Hokuriku":0.870,
       "Kansai":0.916,"Chugoku":0.915,"Shikoku":0.944,"Kyushu":0.883,"Okinawa":0.941}
print(f"\n{'Area':<10}{'市町村':>7}{'v6.3':>8}{'v6.5':>8}{'差':>8}")
for _, r in res.iterrows():
    print(f"{r.Area:<10}{r.n_muni:>7}{V63[r.Area]:>8.3f}{r.Spatial_r:>8.3f}{r.Spatial_r-V63[r.Area]:>+8.3f}")
print(f"\n[出力] {OUT/f'spatial_r_muni_{TAG}.csv'}")
