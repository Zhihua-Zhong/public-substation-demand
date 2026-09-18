#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真値の受入試験・被覆・考官床 — 論文 data/validation/results 節の正準値(離線版)。

正本は clean_truth_and_recompute.py + recompute_all_clean.py(凍結DB向け)。本スクリプトは
同一の定義を data/offline/*.parquet だけで再現する(DB不要・決定的)。正本との一致は
results/micro/ の出力と照合済み(検証局数・LF・est/truth・floor CV)。

定義(正本と同一):
  真値: validation.tepco_bank_fy2024_full を norm2(station_norm) で局へ集約
  推計: estimated_demand_fy2024 (TEPCO, run stage2_pvaware%) を station_id(=engine key)で
  容量: canonical.haihen_roster の equip_mw(>0優先, なければ opcap_mw)・norm2キー・重複は先頭
  受入試験: 双方 3,000時間以上重なり・真値年平均>0.5MW・年平均<=容量
  被覆率: Σ受入真値(年平均MW) / EGC販売(高+低, FY2024, 年平均MW)
  考官床: 清浄集合上の月次 truth/EGC・est/EGC・est/truth の CV(母標準偏差/平均)

出力: results/numbers/truth_coverage_v65.csv
"""
import os, pathlib, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
WS = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = WS/"data"/"offline", WS/"results"/"numbers"
# norm2(局名正規化)は正本 stage2_engine から借りる。本スクリプトはDBに接続しない
# (qdf を呼ばない)が、凍結包の fail-closed 検査が import 時に env を要求するため
# ダミー値を与える。DB接続が起きればコンテナ名不正で即失敗する=安全側。
os.environ.setdefault("DT_DB_CONTAINER", "offline-not-used")
sys.path.insert(0, str(WS/"code"/"engine"/"analysis"/"unified"))
from stage2_engine import norm2 as _norm2
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)

MONTHS = ["2024-04","2024-05","2024-06","2024-07","2024-08","2024-09",
          "2024-10","2024-11","2024-12","2025-01","2025-02","2025-03"]

# ── 真値(hourly wide) ──
t = pd.read_parquet(OFF/"truth_tepco_bank_fy2024.parquet")
t["key"] = t.station_norm.map(_norm2)
tw = t.pivot_table(index="ts", columns="key", values="flow_mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index)
IDX = pd.date_range("2024-04-01 00:00", "2025-03-31 23:00", freq="h")
tw = tw.reindex(IDX)
print(f"真値キー数: {tw.shape[1]}")

# ── 推計(hourly wide) ──
e = pd.read_parquet(OFF/EST_FILE,
                    columns=["utility","station_id","ts","demand_net_mw"])
e = e[e.utility=="TEPCO"]
ew = e.pivot_table(index="ts", columns="station_id", values="demand_net_mw", aggfunc="first")
ew.index = pd.to_datetime(ew.index)
if ew.index.tz is not None:                     # 離線層の ts は '+09' 付き文字列
    ew.index = ew.index.tz_localize(None)
ew = ew.reindex(IDX)

# ── 容量(roster) ──
# 純化: 中間変電所・開閉所は上位系統でありnorm2キーが配電局と衝突する(例: 角筈中間→角筈)。
#   p0_phantom_lf の純化規則と同じく除外する。放置すると受入試験の分母に上位系統の容量が
#   紛れ、汚染系列(配電局定格を超える真値)が素通りする。
# 決定性: 同名衝突の代表は容量最大(監査N1の規則)· sort で行順非依存にする。
ros = pd.read_parquet(OFF/"haihen_roster.parquet")
ros = ros[ros.utility=="TEPCO"].copy()
ros = ros[~ros.name.str.contains("中間|開閉", na=False)]
ros["cap"] = ros.equip_mw.fillna(0).where(ros.equip_mw.fillna(0) > 0, ros.opcap_mw.fillna(0))
ros["key"] = ros.name.map(_norm2)
ros = ros.sort_values(["key","cap"], ascending=[True,False])
cap = ros.drop_duplicates("key").set_index("key")["cap"]

# ── 受入試験(正本 clean_truth と同一) ──
rows, dropped = [], []
for k in tw.columns:
    if k not in ew.columns: continue
    tv = tw[k].values.astype(float); ev = ew[k].values.astype(float)
    m = np.isfinite(tv) & np.isfinite(ev)
    if m.sum() < 3000 or np.nanmean(tv[m]) < 0.5: continue
    mt = float(np.nanmean(tv[m])); me = float(np.nanmean(ev[m]))
    C = float(cap.get(k, np.nan))
    if not np.isfinite(C) or C <= 0:
        dropped.append(dict(key=k, mt=mt, cap=np.nan, why="no capacity")); continue
    if mt > C:
        dropped.append(dict(key=k, mt=mt, cap=C, why="truth exceeds capacity")); continue
    rows.append(dict(key=k, mt=mt, me=me, cap=C, lf=mt/C))
d = pd.DataFrame(rows).sort_values("key"); dr = pd.DataFrame(dropped)
n_pre = len(d) + len(dr)
xc = dr[dr.why=="truth exceeds capacity"] if len(dr) else dr
big = xc.nlargest(1, "mt").iloc[0] if len(xc) else None
print(f"受入前 {n_pre} → 清浄 {len(d)} (除去 {len(dr)}: 容量超過 {len(xc)})")
if big is not None:
    print(f"  超過倍率 {(xc.mt/xc.cap).min():.1f}〜{(xc.mt/xc.cap).max():.1f} / 最大例 {big.mt:.0f} MW @定格 {big.cap:.0f} MW")
print(f"LF 中央 {d.lf.median():.3f} 最大 {d.lf.max():.3f}")
print(f"est/truth 集計 {d.me.sum()/d.mt.sum():.4f}  局別比中央 {(d.me/d.mt).median():.2f}")

# ── 被覆率と考官床(EGC 高+低) ──
av = pd.read_parquet(OFF/"area_demand_by_voltage.parquet")
av = av[(av.utility=="TEPCO") & (av.voltage_class.isin(["high","low"]))
        & (av.year_month>="2024-04-01") & (av.year_month<"2025-04-01")].copy()
av["ym"] = pd.to_datetime(av.year_month).dt.strftime("%Y-%m")
hrs = {m: ((pd.Series(IDX).dt.strftime("%Y-%m")==m).sum()) for m in MONTHS}
G_m = np.array([av[av.ym==m].demand_gwh.sum()*1000.0/hrs[m] for m in MONTHS])
G_ann = float((G_m*np.array([hrs[m] for m in MONTHS])).sum()/len(IDX))
cov = 100*d.mt.sum()/G_ann
print(f"被覆 Σ真値 {d.mt.sum():.0f} MW / EGC {G_ann:.0f} MW = {cov:.1f}%")

mo = pd.Series(IDX).dt.strftime("%Y-%m").values
keys = [k for k in d.key if k in tw.columns and k in ew.columns]
T_m = np.array([np.nanmean(tw[keys].values[mo==m].sum(axis=1)) for m in MONTHS])
E_m = np.array([np.nanmean(ew[keys].values[mo==m].sum(axis=1)) for m in MONTHS])
cv = lambda v: float(np.std(v, ddof=0)/np.mean(v))
rt, re_, rr = T_m/G_m, E_m/G_m, E_m/T_m
print(f"floor: CV(truth/EGC)={cv(rt):.4f} CV(est/EGC)={cv(re_):.4f} CV(est/truth)={cv(rr):.4f} 平均est/truth={np.mean(rr):.4f}")

pd.DataFrame([dict(
    n_pre_test=n_pre, n_rejected=len(dr), n_clean=len(d),
    reject_factor_min=round(float((xc.mt/xc.cap).min()),1), reject_factor_max=round(float((xc.mt/xc.cap).max()),1),
    biggest_reject_mw=round(float(big.mt)), biggest_reject_cap=round(float(big.cap)),
    lf_median=round(float(d.lf.median()),3), lf_max=round(float(d.lf.max()),3),
    coverage_pct=round(float(cov),1),
    agg_est_truth=round(float(d.me.sum()/d.mt.sum()),4), med_est_truth=round(float((d.me/d.mt).median()),2),
    cv_truth_egc=round(cv(rt),4), cv_est_egc=round(cv(re_),4), cv_est_truth=round(cv(rr),4),
    mean_est_truth_monthly=round(float(np.mean(rr)),4),
)]).to_csv(OUT/f"truth_coverage_{TAG}.csv", index=False, encoding="utf-8-sig")
print(f"[出力] {OUT/f'truth_coverage_{TAG}.csv'}")
