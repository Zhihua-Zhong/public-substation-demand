#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tier門の閾値に対する感度(査読対策·本文で約束した数字を実測する)。

方針: 閾値は掃引して選ばない(=判官への過拟合を避ける)。ただし
「動かしたら何が起きるか」は報告する義務がある。標定区の真値で、
門を動かした場合の (a)層別人口 (b)層別APE/corr中央 を測る。
"""
import io, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import pathlib as _pl
WS   = str(_pl.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/micro"
FIG  = f"{WS}/manuscript/figs"
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import compute_region, IDX, norm2, qdf

r = compute_region("TEPCO", blend=False)          # blend前: R と lev を素で得る
stations, lev, R = r["stations"], r["lev"], r["R"]
x0 = r["net"]; PV = r["pv"]
tru = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
          ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)
idx = {k: i for i, k in enumerate(stations)}
CLEAN = set(pd.read_csv(f"{HERE}/v65_micro_clean.csv").key)

def evaluate(lo, hi, cap4):
    """門(lo,hi,cap4)で層を決め、標定区真値に対する層別中央値を返す。"""
    rows = []
    n1 = n2 = n3 = 0
    for k in stations:
        i = idx[k]
        q = None
        if R is not None and k in R.columns:
            L = float(lev.get(k, np.nan)); rm = float(R[k].mean())
            if np.isfinite(L) and L > 0.5 and rm > 0.5: q = rm / L
        if q is not None and lo <= q <= hi:
            tier, e = 1, R[k].values.astype(float)
            n1 += 1
        elif q is not None and hi < q <= cap4:
            tier = 2; base = R[k].values.astype(float)
            e = float(lev.get(k)) * base / base.mean()
            n2 += 1
        else:
            tier, e = 3, x0[i]
            n3 += 1
        if k not in tw.columns or k not in CLEAN: continue
        t = tw[k].values.astype(float)
        m = np.isfinite(t) & np.isfinite(e)
        if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
        rows.append(dict(tier=tier,
            ape=100*abs(np.nanmean(e[m])-np.nanmean(t[m]))/np.nanmean(t[m]),
            corr=float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m]) > 1e-9 else np.nan))
    d = pd.DataFrame(rows)
    return dict(n1=n1, n2=n2, n3=n3, n_eval=len(d),
                ape=round(float(d.ape.median()), 1),
                corr=round(float(d["corr"].median()), 3))

grid = [(0.6, 1.4, 4.0), (0.5, 1.5, 4.0), (0.7, 1.3, 4.0),
        (0.6, 1.4, 3.0), (0.6, 1.4, 6.0)]
out = []
for lo, hi, c4 in grid:
    res = evaluate(lo, hi, c4)
    res.update(lo=lo, hi=hi, cap=c4)
    out.append(res)
    print(f"gate[{lo},{hi}] cap={c4}: tier1={res['n1']:>4} tier2={res['n2']:>4} tier3={res['n3']:>5} "
          f"| APE中央={res['ape']:.1f}% corr中央={res['corr']:.3f} (n={res['n_eval']})", flush=True)
pd.DataFrame(out).to_csv(f"{HERE}/v65_gate_sensitivity.csv", index=False, encoding="utf-8-sig")
print("[出力] v63_gate_sensitivity.csv")
