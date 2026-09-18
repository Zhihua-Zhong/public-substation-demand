# -*- coding: utf-8 -*-
"""Spatial r を論文の定義どおり市区町村単位で計算する(v6.5・離線層のみ)。

論文の定義: 市町村ごとの需要規模について、推計と市町村統計(METI 6-1)の
  対数対数相関を月ごとに求め、その中央値を区域の値とする。

配変→市区町村は station_municipality(凍結DBの行政界ポリゴンとの空間結合を
離線化したもの)を使う。政令指定都市の区は市へ丸める(METI 6-1 は市単位のため)。
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
FY = pd.period_range("2024-04","2025-03",freq="M")

def norm_city(pref, city):
    """政令市の区を市へ丸め、METI 6-1 の「都道府県 市町村」形式の鍵を作る。"""
    if not isinstance(city, str) or not isinstance(pref, str): return None
    c = city
    m = re.match(r"^(.+?市).+?区$", c)          # 「堺市北区」→「堺市」
    if m: c = m.group(1)
    elif re.fullmatch(r".+?区", c):             # 東京特別区は「東京都 千代田区」のまま
        pass
    return f"{pref} {c}"

# ── 推計(台帳被覆基準)を市区町村×月へ集約 ──
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet"); km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
mp = pd.read_parquet(OFF/"station_municipality.parquet")   # utility, station_id(master), city, pref
mp["muni"] = [norm_city(p, c) for p, c in zip(mp.pref_name, mp.city_name)]
link = (km.merge(mp.rename(columns={"station_id":"src_name"}), on=["utility","src_name"])
          [["utility","key","muni"]].dropna().drop_duplicates(["utility","key"]))
est = est.merge(link.rename(columns={"key":"station_id"}), on=["utility","station_id"], how="inner")
est["ts"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo")
est["ym"] = est.ts.dt.to_period("M")
em = est.groupby(["utility","muni","ym"], observed=True)["demand_net_mw"].sum().rename("est_mwh").reset_index()
print(f"[推計→市区町村] 局{est.station_id.nunique():,} → 市区町村{em.muni.nunique():,}")

# ── METI 6-1 ──
meti = pd.read_parquet(OFF/"meti_demand_stats.parquet")
meti = meti[meti.table_source.astype(str).str.startswith("6-1")].copy()
meti["ym"] = pd.to_datetime(meti.year_month).dt.to_period("M")
meti = meti[meti.ym.isin(FY) & (meti.demand_mwh > 0)]
meti["muni"] = meti.municipality_name.str.replace("　"," ").str.strip()
mm = meti.groupby(["muni","ym"], observed=True)["demand_mwh"].sum().reset_index()

j = em.merge(mm, on=["muni","ym"], how="inner")
match = j.drop_duplicates("muni").muni.nunique(); total = em.drop_duplicates("muni").muni.nunique()
print(f"[名寄せ] 一致 {match:,} / 推計側 {total:,} 市区町村 ({100*match/total:.0f}%)")

rows = []
for u in JA:
    g = j[j.utility == u]
    rs = []
    for ym, gg in g.groupby("ym", observed=True):
        gg = gg[(gg.est_mwh > 0) & (gg.demand_mwh > 0)]
        if len(gg) >= 10:
            rs.append(np.corrcoef(np.log(gg.est_mwh), np.log(gg.demand_mwh))[0,1])
    if rs: rows.append(dict(Area=JA[u], utility=u, n_muni=g.muni.nunique(),
                            n_month=len(rs), Spatial_r=round(float(np.median(rs)), 3)))
res = pd.DataFrame(rows)
res.to_csv(OUT/f"spatial_r_muni_{TAG}.csv", index=False, encoding="utf-8-sig")

V63 = {"Hokkaido":0.940,"Tohoku":0.916,"Tokyo":0.956,"Chubu":0.945,"Hokuriku":0.870,
       "Kansai":0.916,"Chugoku":0.915,"Shikoku":0.944,"Kyushu":0.883,"Okinawa":0.941}
print(f"\n{'Area':<10}{'市区町村':>8}{'v6.3':>8}{'v6.5':>8}{'差':>8}")
for _, r in res.iterrows():
    print(f"{r.Area:<10}{r.n_muni:>8}{V63[r.Area]:>8.3f}{r.Spatial_r:>8.3f}{r.Spatial_r-V63[r.Area]:>+8.3f}")
print(f"\n[出力] {OUT/f'spatial_r_muni_{TAG}.csv'}")
