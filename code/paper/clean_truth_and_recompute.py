#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★検証集合の汚染除去と全微視数値の再計算 (2026-07-22·査読前の必須修正)。

発見: validation.tepco_bank_fy2024_full は特高/一次変電所を含む(新野田1,956MW·
新富士1,824MW等)。norm2同名で配変とマッチしてしまい、検証集合1,249局のうち
大局側が上位変で汚染されていた(真値>20MW群の Σest/Σtruth=0.504=物理的にあり得ない)。
配変の年平均需要が自局の変圧器容量を超えることは物理的に不可能なので、
  truth_annual_mean <= C_i   (負荷率100%上限)
を判定条件として除去する。これは閾値調整ではなく物理制約である。

出力: v65_micro_clean.csv / v65_tier_clean.csv / v65_closure_clean.json
"""
import io, json, os, pathlib, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
WS   = str(pathlib.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/micro"
os.makedirs(HERE, exist_ok=True)
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import IDX, norm2, qdf
from est_source import db_source
EST_REL, EST_LIKE, TAG = db_source()   # PAPER_EST_REL, required (RERUN_PLAN_R1.md Step 3, items 4 and 6)

# 真値
tru = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
          ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)
# 推計
est = qdf(f"""SELECT station_id, src, to_char(ts,'YYYY-MM-DD HH24:00'), demand_net_mw
FROM {EST_REL} WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}'""",
["key","src","ts","mw"], ["mw"])
ew = est.pivot_table(index="ts", columns="key", values="mw", aggfunc="first")
ew.index = pd.to_datetime(ew.index); ew = ew.reindex(IDX)
srcmap = est[["key","src"]].drop_duplicates().set_index("key")["src"]
# 容量(roster·純化済)
ros = qdf("""SELECT name, coalesce(equip_mw,0), coalesce(opcap_mw,0) FROM canonical.haihen_roster
WHERE utility='TEPCO'""", ["nm","e","o"], ["e","o"])
ros["cap"] = ros.e.where(ros.e > 0, ros.o)
ros["key"] = ros.nm.map(norm2)
# E5 (determinism of the evaluation population): the query above is unsorted, so drop_duplicates
# kept whichever row the database returned first. Intermediate and switching stations (中間|開閉)
# share a key with the distribution substation of the same name (for example 戸越 / 戸越中間) and,
# kept by row order, change the evaluated set (1,216 against 1,218). Apply the purification of
# CLAUDE.md and build_level_v66.py, then keep the larger capacity after a stable sort.
ros = ros[~ros.nm.str.contains("中間|開閉", regex=True)]
ros = ros.sort_values(["key", "cap", "nm"], ascending=[True, False, True], kind="mergesort")
cap = ros.drop_duplicates("key").set_index("key")["cap"]

rows, dropped = [], []
for k in tw.columns:
    if k not in ew.columns: continue
    t = tw[k].values.astype(float); e = ew[k].values.astype(float)
    m = np.isfinite(t) & np.isfinite(e)
    if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
    mt = float(np.nanmean(t[m])); me = float(np.nanmean(e[m]))
    C = float(cap.get(k, np.nan))
    if not np.isfinite(C) or C <= 0:
        dropped.append(dict(key=k, mt=mt, cap=np.nan, why="no capacity")); continue
    if mt > C:                                  # 物理不可能 = 上位変の混入
        dropped.append(dict(key=k, mt=mt, cap=C, why="truth exceeds capacity")); continue
    r = float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m]) > 1e-9 else np.nan
    rows.append(dict(key=k, src=srcmap.get(k, "?"), mt=mt, me=me, cap=C,
                     lf=mt/C, ape=100*abs(me-mt)/mt, corr=r,
                     cv=100*float(np.sqrt(np.mean((e[m]-t[m])**2))/mt)))
d = pd.DataFrame(rows); dr = pd.DataFrame(dropped)
print(f"検証局: 汚染除去前 {len(d)+len(dr)} → 後 {len(d)}  (除去 {len(dr)})")
print(f"  除去内訳: 容量超過 {int((dr.why=='truth exceeds capacity').sum())} / 容量なし {int((dr.why=='no capacity').sum())}")
if len(dr):
    top = dr.nlargest(5, "mt")[["key","mt","cap"]]
    print("  除去の上位:", [(r.key, round(r.mt), round(r.cap) if np.isfinite(r.cap) else None) for r in top.itertuples()])
print(f"\n清浄集合: Σtruth={d.mt.sum():.0f} MW  Σest={d.me.sum():.0f} MW  est/truth={d.me.sum()/d.mt.sum():.4f}")
print(f"  負荷率(真値/容量) 中央={d.lf.median():.3f}  最大={d.lf.max():.3f}")
print(f"  APE中央={d.ape.median():.1f}%  corr中央={d['corr'].median():.3f}  CV-RMSE中央={d.cv.median():.1f}%")
g = d.groupby("src").agg(n=("key","size"), ape=("ape","median"), corr=("corr","median"),
                         cv=("cv","median"), c08=("corr", lambda s: 100*(s>=0.8).mean())).round(2)
print("\n層別:\n", g.to_string())
d.to_csv(f"{HERE}/{TAG}_micro_clean.csv", index=False, encoding="utf-8-sig")
dr.to_csv(f"{HERE}/{TAG}_truth_dropped.csv", index=False, encoding="utf-8-sig")
g.to_csv(f"{HERE}/{TAG}_tier_clean.csv", encoding="utf-8-sig")
G = float(qdf("""SELECT sum(demand_gwh)*1000/8760 FROM public_data.area_demand_by_voltage
 WHERE utility='TEPCO' AND voltage_class IN ('high','low')
 AND year_month>='2024-04-01' AND year_month<'2025-04-01'""", ["v"], ["v"]).v.iloc[0])
json.dump(dict(n_clean=len(d), n_dropped=len(dr),
               sum_truth=round(d.mt.sum()), sum_est=round(d.me.sum()),
               est_over_truth=round(d.me.sum()/d.mt.sum(), 4),
               ape_med=round(d.ape.median(), 1), corr_med=round(float(d["corr"].median()), 3),
               egc_hl=round(G)),
          open(f"{HERE}/{TAG}_closure_clean.json", "w"), indent=1)
print(f"\n[出力] {TAG}_micro_clean.csv / {TAG}_truth_dropped.csv / {TAG}_tier_clean.csv / {TAG}_closure_clean.json")
