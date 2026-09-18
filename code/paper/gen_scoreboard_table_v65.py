# -*- coding: utf-8 -*-
"""中核表(tab:scoreboard)の v6.5 決定版を生成し、LaTeX 行を出力する。

列ごとの出所(いずれも results/numbers/ に実体を置く):
  Stations / Measured : 台帳被覆基準(station_key_map 経由)— 本スクリプトで算出
  Annual (%)          : calc_annual_monthly_v65.py の出力
  Monthly CV raw/harm : 正本 examiner_harmonize.py の v6.5 実行結果(凍結L3の結論記録)
  Spatial r           : 正本 p3_meti_spatial.py を凍結DBで再実行した結果
  Daily / Hourly (%)  : calc_spatial_hourly_v65.py の出力(正本ファイル
                        occto_full_check_v62 と ≤0.7pt で整合することを確認済)

丸めは半上げ(round-half-up)。banker's rounding による 104.5→104 のような揺れを避ける。
"""
import sys, pathlib
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source, untagged_suffix
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)

JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu","HOKURIKU":"Hokuriku",
      "KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku","KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
ORDER = list(JA)

def half_up(x, nd=0):
    q = Decimal(10) ** -nd
    v = Decimal(str(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    return int(v) if nd == 0 else float(v)

# ── Stations / Measured(台帳被覆基準) ──
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

# ── 各列の読込 ──
ann = pd.read_csv(OUT/f"annual_monthly_{TAG}.csv").set_index("utility")
ENG_OUT = W/"code"/"engine"/"analysis"/"unified"/"out"
if TAG == "v65":
    exm = pd.read_csv(W/"results"/"frozen_inputs"/"examiner_harmonized_fy2024.csv")  # 正本(v6.5結論記録)
else:   # v6.6: output of the canonical examiner_harmonize.py rerun on the v6.6 estimate (E7)
    exm = pd.read_csv(ENG_OUT/f"examiner_harmonized_fy2024{untagged_suffix(TAG)}.csv")
exm = exm.set_index("utility")
p3 = pd.read_csv(ENG_OUT/f"p3_meti_spatial{untagged_suffix(TAG)}.csv")
p3col = [c for c in p3.columns if "corr" in c.lower() or c in ("u","utility","市町村","n_city")]
p3 = p3.set_index(p3.columns[0])
dh = pd.read_csv(OUT/f"spatial_hourly_{TAG}.csv").set_index("Area")

rows, tex = [], []
for u in ORDER:
    a = JA[u]
    st, me = int(g.at[u,"Stations"]), int(g.at[u,"Measured"])
    annual = half_up(ann.at[u,"Annual_pct"], 0)
    cvr = float(exm.at[u,"cv_raw12"]); cvh = float(exm.at[u,"cv_harm11"])
    sr = float(p3.loc[u][[c for c in p3.columns if "corr" in c][0]]) if u in p3.index else float("nan")
    dl = float(dh.at[a,"Daily_pct"]); hr = float(dh.at[a,"Hourly_pct"])
    rows.append(dict(Area=a, utility=u, Stations=st, Measured=me, Annual_pct=annual,
                     Monthly_CV_raw=round(cvr,3), Monthly_CV_harm=round(cvh,3),
                     Spatial_r=round(sr,3), Daily_pct=round(dl,1), Hourly_pct=round(hr,1)))
    st_tex = f"{st:,}".replace(",", "{,}")
    tex.append(f"{a} & {st_tex} & {me} & {annual} & {cvr:.3f} & {cvh:.3f} & {sr:.3f} & {dl:.1f} & {hr:.1f}\\\\")

res = pd.DataFrame(rows)
res.to_csv(OUT/f"scoreboard_{TAG}.csv", index=False, encoding="utf-8-sig")
(OUT/f"scoreboard_{TAG}_rows.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
print(res.to_string(index=False))
print(f"\n[出力] scoreboard_{TAG}.csv / scoreboard_{TAG}_rows.tex")
print(f"Hourly範囲: {res.Hourly_pct.min():.1f}〜{res.Hourly_pct.max():.1f} / raw CV範囲: {res.Monthly_CV_raw.min():.3f}〜{res.Monthly_CV_raw.max():.3f} / harm範囲: {res.Monthly_CV_harm.min():.3f}〜{res.Monthly_CV_harm.max():.3f}")
