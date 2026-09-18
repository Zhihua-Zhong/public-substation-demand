# -*- coding: utf-8 -*-
"""中核表の Spatial r(市町村別需要の対数対数相関・月次中央値)を v6.5 から計算する。

論文の定義: 市町村ごとの需要規模について、推計と市町村統計(METI 6-1)の
  対数対数相関を月ごとに求め、その中央値を区域の値とする。

市町村統計の `utility` 列は `JAPAN` 固定なので、`municipality_name` の先頭にある
都道府県名から区域へ紐付ける。離線層のみを読む。
"""
import sys, pathlib, re
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)

JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu","HOKURIKU":"Hokuriku",
      "KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku","KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
PREF2U = {  # 都道府県 → 供給区域(電力10社の管轄。県境をまたぐ例外は主たる区域へ寄せる)
 "北海道":"HOKKAIDO",
 "青森":"TOHOKU","岩手":"TOHOKU","宮城":"TOHOKU","秋田":"TOHOKU","山形":"TOHOKU","福島":"TOHOKU","新潟":"TOHOKU",
 "茨城":"TEPCO","栃木":"TEPCO","群馬":"TEPCO","埼玉":"TEPCO","千葉":"TEPCO","東京":"TEPCO","神奈川":"TEPCO","山梨":"TEPCO",
 "長野":"CHUBU","岐阜":"CHUBU","静岡":"CHUBU","愛知":"CHUBU","三重":"CHUBU",
 "富山":"HOKURIKU","石川":"HOKURIKU","福井":"HOKURIKU",
 "滋賀":"KANSAI","京都":"KANSAI","大阪":"KANSAI","兵庫":"KANSAI","奈良":"KANSAI","和歌山":"KANSAI",
 "鳥取":"CHUGOKU","島根":"CHUGOKU","岡山":"CHUGOKU","広島":"CHUGOKU","山口":"CHUGOKU",
 "徳島":"SHIKOKU","香川":"SHIKOKU","愛媛":"SHIKOKU","高知":"SHIKOKU",
 "福岡":"KYUSHU","佐賀":"KYUSHU","長崎":"KYUSHU","熊本":"KYUSHU","大分":"KYUSHU","宮崎":"KYUSHU","鹿児島":"KYUSHU",
 "沖縄":"OKINAWA"}

def pref_of(name):
    s = str(name).strip()
    for p in PREF2U:
        if s.startswith(p): return p
    return None

# ── 市町村統計(6-1) ──
meti = pd.read_parquet(OFF/"meti_demand_stats.parquet")
meti = meti[meti.table_source.astype(str).str.startswith("6-1")].copy()
meti["pref"] = meti.municipality_name.map(pref_of)
meti["utility"] = meti.pref.map(PREF2U)
meti["ym"] = pd.to_datetime(meti.year_month).dt.to_period("M")
fy = pd.period_range("2024-04","2025-03",freq="M")
meti = meti[meti.ym.isin(fy) & meti.utility.notna() & (meti.demand_mwh > 0)]
print(f"[市町村統計] {len(meti):,}行 / 市町村 {meti.municipality_name.nunique():,} / 区域 {meti.utility.nunique()}")

# ── 推計を市町村へ集約(配変→市区町村は station_features に無いため、台帳の pref で県級に落とす) ──
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet"); km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
ros = pd.read_parquet(OFF/"haihen_roster.parquet", columns=["utility","legacy_sid","pref","name"])
sm  = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","node_type"])
sm  = sm[sm.node_type=="haihen"][["utility","station_id"]].rename(columns={"station_id":"src_name"})
link = (km.merge(sm, on=["utility","src_name"])
          .merge(ros.rename(columns={"legacy_sid":"src_name"}), on=["utility","src_name"], how="left"))
link = link[["utility","key","pref"]].dropna().drop_duplicates("key")
est = est.merge(link.rename(columns={"key":"station_id"}), on=["utility","station_id"], how="inner")
est["ts"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo")
est["ym"] = est.ts.dt.to_period("M")
est["pref2"] = est.pref.map(lambda s: pref_of(s) or None)
est_pref = est.groupby(["utility","pref2","ym"], observed=True)["demand_net_mw"].sum().rename("est_mwh").reset_index()
print(f"[推計の県級集約] {len(est_pref):,}行 / 県 {est_pref.pref2.nunique()}")

# 市町村統計も県級へ
meti["pref2"] = meti.pref
meti_pref = meti.groupby(["utility","pref2","ym"], observed=True)["demand_mwh"].sum().reset_index()

j = est_pref.merge(meti_pref, on=["utility","pref2","ym"], how="inner")
rows = []
for u, g in j.groupby("utility", observed=True):
    rs = []
    for ym, gg in g.groupby("ym", observed=True):
        gg = gg[(gg.est_mwh > 0) & (gg.demand_mwh > 0)]
        if len(gg) >= 3:
            rs.append(np.corrcoef(np.log(gg.est_mwh), np.log(gg.demand_mwh))[0,1])
    if rs: rows.append(dict(Area=JA[u], utility=u, n_month=len(rs), n_unit=g.pref2.nunique(),
                            Spatial_r=round(float(np.median(rs)), 3)))
res = pd.DataFrame(rows)
res.to_csv(OUT/f"spatial_r_{TAG}.csv", index=False, encoding="utf-8-sig")

V63 = {"Hokkaido":0.940,"Tohoku":0.916,"Tokyo":0.956,"Chubu":0.945,"Hokuriku":0.870,
       "Kansai":0.916,"Chugoku":0.915,"Shikoku":0.944,"Kyushu":0.883,"Okinawa":0.941}
print(f"\n{'Area':<10}{'v6.3':>8}{'v6.5':>8}{'差':>8}{'県数':>6}")
for _, r in res.iterrows():
    print(f"{r.Area:<10}{V63[r.Area]:>8.3f}{r.Spatial_r:>8.3f}{r.Spatial_r-V63[r.Area]:>+8.3f}{r.n_unit:>6}")
print(f"\n[出力] {OUT/f'spatial_r_{TAG}.csv'}")
print("※ 原稿は市町村単位。ここは県単位での近似であり、単位が粗いぶん相関は高く出る。")
print("   厳密な再現には配変→市区町村の割付が要る(mesh_substation_alloc から構成可能)。")
