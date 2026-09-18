#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WLS 裁決 (docs/WLS_PREREGISTRATION.md の門 G1-G4)。結果を見る前に基準は固定済。"""
import io, pathlib, subprocess, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
WS   = str(pathlib.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/wls"
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import IDX, norm2, qdf

def truth_wide(U):
    if U == "TEPCO":
        t = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
                ["nm","ts","mw"], ["mw"])
    else:
        t = qdf(f"""SELECT equipment_name, to_char(ts,'YYYY-MM-DD HH24:00'), sum(flow_mw)
                    FROM validation.flow_lt_truth WHERE utility='{U}' AND fiscal_year=2024 GROUP BY 1,2""",
                ["nm","ts","mw"], ["mw"])
    if t.empty: return None
    t["key"] = t.nm.map(norm2)
    w = t.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
    w.index = pd.to_datetime(w.index)
    return w.reindex(IDX)

def est_wide(U, table, run_like):
    e = qdf(f"""SELECT station_id, to_char(ts,'YYYY-MM-DD HH24:00'), demand_net_mw
                FROM {table} WHERE utility='{U}' AND run_id LIKE '{run_like}'""",
            ["key","ts","mw"], ["mw"])
    w = e.pivot_table(index="ts", columns="key", values="mw", aggfunc="first")
    w.index = pd.to_datetime(w.index)
    return w.reindex(IDX)

def metrics(ew, tw, keys):
    rows = []
    for k in keys:
        if k not in ew.columns or k not in tw.columns: continue
        e = ew[k].values.astype(float); t = tw[k].values.astype(float)
        m = np.isfinite(e) & np.isfinite(t)
        if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
        rows.append(dict(key=k,
            ape=100*abs(np.nanmean(e[m])-np.nanmean(t[m]))/np.nanmean(t[m]),
            corr=float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m])>1e-9 else np.nan,
            mt=float(np.nanmean(t[m])), me=float(np.nanmean(e[m]))))
    return pd.DataFrame(rows)

print("=== G1 点精度 (TEPCO真値) ===", flush=True)
tw = truth_wide("TEPCO")
tier = est_wide("TEPCO", "lab_data.estimated_demand_fy2024", "stage2_pvaware%")
wls  = est_wide("TEPCO", "lab_data.estimated_demand_fy2024_wls", "wls3_%")
keys = [k for k in tw.columns if k in tier.columns and k in wls.columns]
mt_, mw_ = metrics(tier, tw, keys), metrics(wls, tw, keys)
j = mt_.merge(mw_, on="key", suffixes=("_tier","_wls"))
print(f"  対象 {len(j)}局")
print(f"  APE中央  階層 {j.ape_tier.median():.1f}% → WLS {j.ape_wls.median():.1f}%")
print(f"  corr中央 階層 {j.corr_tier.median():.3f} → WLS {j.corr_wls.median():.3f}")
g1 = (j.ape_wls.median() <= j.ape_tier.median()+1.0) and (j.corr_wls.median() >= j.corr_tier.median()-0.02)
print(f"  G1: {'PASS' if g1 else 'FAIL'}")
j.to_csv(f"{HERE}/wls3_g1_tepco.csv", index=False, encoding="utf-8-sig")

def coverage(U, tw):
    sd = np.load(f"{HERE}/wls3_sd_{U}.npy")
    ks = pd.read_csv(f"{HERE}/wls3_keys_{U}.csv", header=None)[0].astype(str).tolist()
    sdm = dict(zip(ks, sd))
    ew = est_wide(U, "lab_data.estimated_demand_fy2024_wls", "wls3_%")
    hit = tot = 0; per = []
    for k in tw.columns:
        if k not in ew.columns or k not in sdm: continue
        e = ew[k].values.astype(float); t = tw[k].values.astype(float)
        m = np.isfinite(e) & np.isfinite(t)
        if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
        s = sdm[k] * 1.2816                       # 80%区間(±1.2816σ)
        lo, hi = np.nanmean(e[m]) - s, np.nanmean(e[m]) + s
        ok = lo <= np.nanmean(t[m]) <= hi
        hit += ok; tot += 1
        per.append(dict(key=k, sd=sdm[k], est=np.nanmean(e[m]), truth=np.nanmean(t[m]), inside=bool(ok)))
    return (100*hit/tot if tot else np.nan), tot, pd.DataFrame(per)

print("\n=== G2 不確実性の較正 (TEPCO·年平均水準の80%区間) ===", flush=True)
c2, n2, d2 = coverage("TEPCO", tw)
print(f"  被覆 {c2:.1f}% (n={n2})  名目80%  → G2: {'PASS' if 70<=c2<=90 else 'FAIL'}")
d2.to_csv(f"{HERE}/wls3_g2_tepco.csv", index=False, encoding="utf-8-sig")

print("\n=== G3 転写 (KANSAI真値) ===", flush=True)
tk = truth_wide("KANSAI")
if tk is None: print("  真値なし"); c3, n3 = np.nan, 0
else:
    c3, n3, d3 = coverage("KANSAI", tk)
    print(f"  被覆 {c3:.1f}% (n={n3})  経験帯は同条件13.7% → G3: {'PASS' if c3>=60 else 'FAIL'}")
    d3.to_csv(f"{HERE}/wls3_g3_kansai.csv", index=False, encoding="utf-8-sig")

print("\n=== G4 宏観(読むだけ) ===", flush=True)
for U in ("TEPCO","KANSAI"):
    s = qdf(f"""SELECT round(sum(m)) FROM (SELECT avg(demand_net_mw) m FROM lab_data.estimated_demand_fy2024_wls
        WHERE utility='{U}' GROUP BY station_id) t""", ["v"], ["v"]).v.iloc[0]
    g = qdf(f"""SELECT round(sum(demand_gwh)*1000/8760) FROM public_data.area_demand_by_voltage
        WHERE utility='{U}' AND voltage_class IN ('high','low')
          AND year_month>='2024-04-01' AND year_month<'2025-04-01'""", ["v"], ["v"]).v.iloc[0]
    print(f"  {U}: capture {100*float(s)/float(g):.0f}%")
print(f"\n判定: G1={'PASS' if g1 else 'FAIL'} G2={'PASS' if 70<=c2<=90 else 'FAIL'} "
      f"G3={'PASS' if (n3 and c3>=60) else 'FAIL'}")
