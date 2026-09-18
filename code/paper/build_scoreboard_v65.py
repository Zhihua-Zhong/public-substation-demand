# -*- coding: utf-8 -*-
"""論文の中核表(Table: scoreboard)を v6.5 の離線データから作り直す。

原稿(v6.3)の同表と列を揃える:
  Area / Stations / Measured tier / Annual (%) / Monthly CV raw / Monthly CV harm.
  / Spatial r / Daily (%) / Hourly (%)

このスクリプトはデータベースに接続しない。`data/offline/*.parquet` だけを読む。
そのため実行のたびに同じ結果になる(行順はファイルが権威)。
"""
import sys, pathlib, json
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)
OUT.mkdir(parents=True, exist_ok=True)

AREA_JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu",
           "HOKURIKU":"Hokuriku","KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku",
           "KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
ORDER = ["HOKKAIDO","TOHOKU","TEPCO","CHUBU","HOKURIKU","KANSAI","CHUGOKU","SHIKOKU","KYUSHU","OKINAWA"]

print("[読込] 推計結果(v6.5)...", flush=True)
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id","ts","demand_net_mw","src"])
print(f"   {len(est):,}行")

# ── Stations / Measured tier ──
per = est.groupby(["utility","station_id"], observed=True)["src"].max().reset_index()
stations = per.groupby("utility").size().rename("Stations")
measured = per[per.src.isin(["z1","z1s"])].groupby("utility").size().rename("Measured")

# ── Annual (%) = Σ推計 ÷ 販売統計(高圧+低圧) ──
egc = pd.read_parquet(OFF/"area_demand_by_voltage.parquet")
print(f"[読込] 販売統計 列: {list(egc.columns)}")

# ── 月別の被覆誤差(CV) ──
est["ym"] = pd.to_datetime(est.ts).dt.to_period("M")
mon = est.groupby(["utility","ym"], observed=True)["demand_net_mw"].mean().reset_index()

res = pd.DataFrame(index=ORDER)
res["Area"] = [AREA_JA[u] for u in ORDER]
res["Stations"] = stations.reindex(ORDER).values
res["Measured"] = measured.reindex(ORDER).values

# 年平均(MW)= 区域の推計総量
ann = est.groupby("utility", observed=True)["demand_net_mw"].sum() / 8760
res["Est_annual_mean_MW"] = ann.reindex(ORDER).round(1).values

res.to_csv(OUT/f"scoreboard_{TAG}_partial.csv", index=False, encoding="utf-8-sig")
print(f"\n[出力] {OUT/f'scoreboard_{TAG}_partial.csv'}")
print(res.to_string(index=False))
print("\n※ Annual(%)・Spatial r・Daily/Hourly は検証系の照合が要る。次段で追加する。")
