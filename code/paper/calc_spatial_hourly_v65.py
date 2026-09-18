# -*- coding: utf-8 -*-
"""中核表の残り3列(Spatial r / Daily / Hourly)を v6.5 の離線データから計算する。

論文の定義(validation_v63.tex の caption):
  Spatial r : 市町村ごとの需要規模の対数対数相関を、月ごとに求めた中央値
  Daily/Hourly (%) : 需給実績(発電端)に対する正規化RMSE。一定の楔(wedge)のもとで、
                     保守的な上限として与える

離線層のみを読む。データベースに接続しない。
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
# OCCTO の区域コード(北→南)
AREA_CODE = {1:"HOKKAIDO",2:"TOHOKU",3:"TEPCO",4:"CHUBU",5:"HOKURIKU",
             6:"KANSAI",7:"CHUGOKU",8:"SHIKOKU",9:"KYUSHU",10:"OKINAWA"}
ORDER = list(JA)

print("[読込] 推計(台帳被覆基準へ絞込) …", flush=True)
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw"])
km = pd.read_parquet(OFF/"station_key_map.parquet")
km = km[km.kind=="master"][["utility","key","src_name"]].drop_duplicates()
sm = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","node_type"])
sm = sm[sm.node_type=="haihen"][["utility","station_id"]].rename(columns={"station_id":"src_name"})
keep = (km.merge(sm, on=["utility","src_name"])[["utility","key"]]
          .drop_duplicates().rename(columns={"key":"station_id"}))
est = est.merge(keep, on=["utility","station_id"], how="inner")
est["ts"] = pd.to_datetime(est.ts, utc=True).dt.tz_convert("Asia/Tokyo")
print(f"   {est.station_id.nunique():,}局 / {len(est):,}行")

# ── 区域×時刻の合計(需給実績との突合に使う) ──
areal = est.groupby(["utility","ts"], observed=True)["demand_net_mw"].sum().rename("est_mw").reset_index()

# ── Daily / Hourly : 需給実績(OCCTO)に対する正規化RMSE ──
occ = pd.read_parquet(OFF/"occto_supply_demand.parquet")
occ["utility"] = occ.area_code.map(AREA_CODE)
occ["ts"] = pd.to_datetime(occ.ts, utc=True).dt.tz_convert("Asia/Tokyo")
fy0, fy1 = pd.Timestamp("2024-04-01", tz="Asia/Tokyo"), pd.Timestamp("2025-04-01", tz="Asia/Tokyo")
occ = occ[(occ.ts >= fy0) & (occ.ts < fy1)][["utility","ts","demand_mw"]]

j = areal.merge(occ, on=["utility","ts"], how="inner")
print(f"[突合] 時間別 {len(j):,}点 / 区域 {j.utility.nunique()}")

rows = []
for u in ORDER:
    g = j[j.utility == u]
    if len(g) < 100: rows.append(dict(Area=JA[u], Hourly_pct=np.nan, Daily_pct=np.nan)); continue
    # 一定の楔: 推計(配電端net)と需給実績(発電端)の口径差を、年平均比で一度だけ補正する
    wedge = g.demand_mw.mean() / g.est_mw.mean()
    pred_h = g.est_mw * wedge
    hourly = 100.0 * np.sqrt(((pred_h - g.demand_mw)**2).mean()) / g.demand_mw.mean()
    d = g.assign(pred=pred_h, day=g.ts.dt.date).groupby("day")[["pred","demand_mw"]].mean()
    daily = 100.0 * np.sqrt(((d.pred - d.demand_mw)**2).mean()) / d.demand_mw.mean()
    rows.append(dict(Area=JA[u], Hourly_pct=round(hourly,1), Daily_pct=round(daily,1)))
res = pd.DataFrame(rows)

# ── Spatial r : 市町村別(METI 6-1)との対数対数相関の月次中央値 ──
meti = pd.read_parquet(OFF/"meti_demand_stats.parquet")
print(f"[読込] 市町村統計 {len(meti):,}行 / utility={sorted(meti.utility.unique())[:5]}")
res.to_csv(OUT/f"spatial_hourly_{TAG}.csv", index=False, encoding="utf-8-sig")

V63 = {"Hokkaido":(0.940,3.8,8.8),"Tohoku":(0.916,7.6,15.5),"Tokyo":(0.956,11.7,21.1),
       "Chubu":(0.945,9.6,19.4),"Hokuriku":(0.870,8.2,12.6),"Kansai":(0.916,6.3,10.8),
       "Chugoku":(0.915,8.7,19.5),"Shikoku":(0.944,12.8,32.7),"Kyushu":(0.883,8.7,19.2),
       "Okinawa":(0.941,4.8,16.9)}
print(f"\n{'Area':<10}{'Daily v6.3':>11}{'v6.5':>8}{'差':>7}   {'Hourly v6.3':>12}{'v6.5':>8}{'差':>7}")
for _, r in res.iterrows():
    _, d3, h3 = V63[r.Area]
    d5 = r.Daily_pct; h5 = r.Hourly_pct
    if pd.isna(d5): print(f"{r.Area:<10}{d3:>11}{'—':>8}{'—':>7}   {h3:>12}{'—':>8}{'—':>7}"); continue
    print(f"{r.Area:<10}{d3:>11}{d5:>8}{d5-d3:>+7.1f}   {h3:>12}{h5:>8}{h5-h3:>+7.1f}")
print(f"\n[出力] {OUT/f'spatial_hourly_{TAG}.csv'}")
print("※ Spatial r は市町村統計の区域紐付け(utility列がJAPAN)を要するため次段で扱う。")
