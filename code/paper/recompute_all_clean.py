#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""★汚染除去後の全数値再計算 (査読前の必須修正·2026-07-22)。

真値表の上位変混入(31-39局)を物理判据(年平均 <= 変圧器容量)で除去し、
真値に依存する本文の全数値を再計算する:
  A. 考官床(月次比 truth/EGC, est/EGC, est/truth) + bootstrap CI
  B. 層別精度(Table 1)
  C. 基線対照(Table 2)
  D. 飽和率の真値監査(7.1節)
  E. CBD局の真値レンジ(5.3節)
出力: v65_clean_all.json (本文が引く単一真相源)
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
RNG = np.random.default_rng(20260722)
MONTHS = ["2024-04","2024-05","2024-06","2024-07","2024-08","2024-09",
          "2024-10","2024-11","2024-12","2025-01","2025-02","2025-03"]
out = {}

# ── 清浄な検証局集合 ──
clean = pd.read_csv(f"{HERE}/{TAG}_micro_clean.csv")
keys = set(clean.key)
print(f"清浄検証局 {len(keys)}")

tru = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
          ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tru = tru[tru.key.isin(keys)]
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)
est = qdf(f"""SELECT station_id, src, to_char(ts,'YYYY-MM-DD HH24:00'), demand_net_mw
FROM {EST_REL} WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}'""",
["key","src","ts","mw"], ["mw"])
srcmap = est[["key","src"]].drop_duplicates().set_index("key")["src"]
ew_all = est.pivot_table(index="ts", columns="key", values="mw", aggfunc="first")
ew_all.index = pd.to_datetime(ew_all.index); ew_all = ew_all.reindex(IDX)
ew = ew_all[[c for c in ew_all.columns if c in keys]]

# ── A. 考官床(同一の清浄局集合で truth と est を集計) ──
mo = pd.Series(IDX).dt.strftime("%Y-%m").values
T_m = np.array([np.nanmean(tw.values[mo == m].sum(axis=1)) for m in MONTHS])
E_m = np.array([np.nanmean(ew.values[mo == m].sum(axis=1)) for m in MONTHS])
G = qdf("""SELECT to_char(year_month,'YYYY-MM'), sum(demand_gwh)*1000.0/max(extract(epoch FROM
 (year_month+interval '1 month')-year_month)/3600.0) FROM public_data.area_demand_by_voltage
 WHERE utility='TEPCO' AND voltage_class IN ('high','low') AND year_month>='2024-04-01'
 AND year_month<'2025-04-01' GROUP BY 1, year_month ORDER BY 1""", ["ym","mw"], ["mw"])
G_m = G.set_index("ym")["mw"].reindex(MONTHS).values.astype(float)
cv = lambda v: float(np.std(v, ddof=0)/np.mean(v))
def bci(v, fn=cv, n=2000):
    s = [fn(RNG.choice(v, len(v), replace=True)) for _ in range(n)]
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]
rt, re_, rr = T_m/G_m, E_m/G_m, E_m/T_m
print("\n=== A. 考官床(清浄集合) ===")
for nm_, v in [("truth/EGC", rt), ("est/EGC", re_), ("est/truth", rr)]:
    print(f"  CV({nm_:10}) = {cv(v):.4f}  CI{bci(v)}   平均比={np.mean(v):.4f}")
out["floor"] = dict(cv_truth_egc=round(cv(rt),4), ci_truth_egc=bci(rt),
                    cv_est_egc=round(cv(re_),4), ci_est_egc=bci(re_),
                    cv_est_truth=round(cv(rr),4), ci_est_truth=bci(rr),
                    mean_est_truth=round(float(np.mean(rr)),4),
                    note="1,218 clean stations; truth and est aggregated over the same set")
# ★fig_floorが読む月次系列を清浄集合で上書き(汚染前全真値版と食い違っていた不整合の是正)
pd.DataFrame({"month": MONTHS, "truth_egc": rt, "est_egc": re_, "est_truth": rr}).to_csv(
    f"{HERE}/{TAG}_floor_monthly.csv", index=False, encoding="utf-8-sig")
print(f"[出力] {TAG}_floor_monthly.csv (清浄1216·mean est/truth={np.mean(rr):.3f})")

# ── B. 層別(Table 1) ──
g = clean.groupby("src").agg(n=("key","size"), ape=("ape","median"), corr=("corr","median"),
                             cv=("cv","median"), c08=("corr", lambda s: 100*(s>=0.8).mean()))
out["tiers"] = {s: dict(n=int(r.n), ape=round(r.ape,1), corr=round(r["corr"],3),
                        cvrmse=round(r.cv,1), c08=round(r.c08)) for s, r in g.iterrows()}
out["overall"] = dict(n=len(clean), ape=round(float(clean.ape.median()),1),
                      corr=round(float(clean["corr"].median()),3),
                      sum_truth=round(float(clean.mt.sum())), sum_est=round(float(clean.me.sum())),
                      est_over_truth=round(float(clean.me.sum()/clean.mt.sum()),4))
print("\n=== B. 層別 ===\n", g.round(2).to_string())

# ── C. 基線(同一清浄集合) ──
print("\n=== C. 基線対照 ===", flush=True)
lev_all = ew_all.mean(axis=0)
area = ew_all.sum(axis=1).values
res = {}
for name, mk in [("ours", None), ("area_shape", "area"), ("capacity", "cap"), ("flat", "flat")]:
    rows = []
    for k in clean.key:
        if k not in ew.columns: continue
        t = tw[k].values.astype(float)
        if mk is None: e = ew[k].values.astype(float)
        elif mk == "flat": e = np.full(len(IDX), float(ew[k].mean()))
        else: e = float(ew[k].mean()) * area/area.mean()
        m = np.isfinite(t) & np.isfinite(e)
        if m.sum() < 3000: continue
        c = float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m]) > 1e-9 else np.nan
        rows.append(dict(ape=100*abs(np.nanmean(e[m])-np.nanmean(t[m]))/np.nanmean(t[m]), corr=c))
    d = pd.DataFrame(rows)
    res[name] = dict(n=len(d), ape=round(float(d.ape.median()),1),
                     corr=(None if d["corr"].isna().all() else round(float(d["corr"].median()),3)),
                     c08=round(100*float((d["corr"]>=0.8).mean())))
    print(f"  {name:12} n={res[name]['n']} APE={res[name]['ape']} corr={res[name]['corr']} c08={res[name]['c08']}")
out["baselines"] = res

# ── D. 飽和率の真値監査 ──
day = (IDX.hour >= 9) & (IDX.hour <= 15)
rows = []
for k in clean.key:
    if k not in ew.columns: continue
    t = tw[k].values.astype(float); e = ew[k].values.astype(float)
    m = np.isfinite(t) & np.isfinite(e)
    if (day & m).sum() < 500: continue
    rows.append(dict(key=k, t5=float(np.percentile(t[day & m], 5)), e5=float(np.percentile(e[day & m], 5))))
s = pd.DataFrame(rows)
tp = int(((s.t5<=0)&(s.e5<=0)).sum()); fp = int(((s.t5>0)&(s.e5<=0)).sum())
fn = int(((s.t5<=0)&(s.e5>0)).sum()); tn = int(((s.t5>0)&(s.e5>0)).sum())
out["saturation"] = dict(n=len(s), truth_pct=round(100*float((s.t5<=0).mean()),1),
    est_pct=round(100*float((s.e5<=0).mean()),1),
    precision=round(100*tp/max(tp+fp,1)), recall=round(100*tp/max(tp+fn,1)),
    accuracy=round(100*(tp+tn)/len(s)), r=round(float(np.corrcoef(s.t5, s.e5)[0,1]),3))
print(f"\n=== D. 飽和率 ===\n  truth {out['saturation']['truth_pct']}% vs est {out['saturation']['est_pct']}%  "
      f"適合率{out['saturation']['precision']}% 再現率{out['saturation']['recall']}% r={out['saturation']['r']}")

# ── E. CBD局の真値レンジ ──
cbd = ["丸の内","銀座","東銀座","西銀座","鍛冶橋","白魚橋","日本橋","京橋","八重洲","有楽町",
       "神田","岩本町","本銀町","小舟町","茅場町","西茅場","兜町","蔵前","湯島","駿河台",
       "お茶の水","九段","麹町","霞ケ関","内幸町","東内幸町","新橋","愛宕","虎ノ門","赤坂","溜池"]
cb = clean[clean.key.isin([norm2(x) for x in cbd])]
if len(cb):
    out["cbd"] = dict(n=len(cb), min=round(float(cb.mt.min()),1), max=round(float(cb.mt.max()),1),
                      cap_min=round(float(cb.cap.min())), cap_max=round(float(cb.cap.max())))
    print(f"\n=== E. CBD {len(cb)}局: 真値 {out['cbd']['min']}〜{out['cbd']['max']} MW  "
          f"容量 {out['cbd']['cap_min']}〜{out['cbd']['cap_max']} MW")
json.dump(out, open(f"{HERE}/{TAG}_clean_all.json","w"), ensure_ascii=False, indent=1)
print(f"\n[出力] {TAG}_clean_all.json")
