#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper A 第一梯隊 B/C/D: 基線対照表 + HC順位相関の確定 + bootstrap CI。

B 基線(全て同一真値·同一指標·標定区1,249局):
   b0 capacity-proportional : 区域Σnetを容量シェアで按分(データセット不在時の実務)
   b1 covariate-only        : 水準は錨梯どおり·形状は部門曲線のみ(donor転写なし)
   b2 flat                  : 水準は錨梯·形状は年間一定(平坦)
   ours                     : v6.3 階層推計
C HC順位相関: canonical.hosting_capacity(published) と 当方thermal screenの Spearman を確定値で。
D bootstrap CI: 考官床の2つのCV·層別中央値·ours vs b0 の差。
"""
import io, subprocess, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import pathlib as _pl
WS   = str(_pl.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/micro"
FIG  = f"{WS}/manuscript/figs"
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import compute_region, IDX, norm2, qdf
from est_source import db_source
EST_REL, EST_LIKE, TAG = db_source()   # PAPER_EST_REL, required (RERUN_PLAN_R1.md Step 3, items 4 and 6)
# Part B below runs the live engine, which is v6.6 since the rerun. Paired with a v6.5 relation it
# would write v6.6 engine numbers under a v6.5 name, so only the v6.6 relation is accepted.
if TAG != "v66":
    sys.exit("[FATAL] baselines_and_ci.py runs the live (v6.6) engine in part B; "
             "set PAPER_EST_REL=lab_data.ed_rerun_v66")
import os as _os, sys as _sys
_DBC = _os.environ.get("DT_DB_CONTAINER") or _sys.exit(
    "[FATAL] 論文作業区では DT_DB_CONTAINER の明示が必須(例: iwafune_db_frozen)。生産DB誤接続の防止。")


RNG = np.random.default_rng(20260719)
def boot_ci(x, fn=np.median, n=2000, lo=2.5, hi=97.5):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 5: return (np.nan, np.nan)
    s = [fn(RNG.choice(x, len(x), replace=True)) for _ in range(n)]
    return (float(np.percentile(s, lo)), float(np.percentile(s, hi)))

# ── B) 基線対照(TEPCO標定区) ──
print("=== B) 基線対照表 (TEPCO·1,249局·通年8760h) ===", flush=True)
r = compute_region("TEPCO", blend=True)
stations, lev, x_ours, F = r["stations"], r["lev"], r["net"], r.get("F")
idx = {k: i for i, k in enumerate(stations)}
tru = qdf("SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw FROM validation.tepco_bank_fy2024_full",
          ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)

lv = np.array([float(lev.get(k, np.nan)) for k in stations])
lv = np.where(np.isfinite(lv) & (lv > 0.05), lv, np.nanmedian(lv[np.isfinite(lv)]))
area_prof = x_ours.sum(axis=0)                       # 区域Σ(時系列)
b0 = np.outer(lv/lv.sum(), area_prof)                # 容量(=水準)シェア按分
b2 = np.repeat(x_ours.mean(axis=1)[:, None], len(IDX), axis=1)   # 平坦
# b1: 形状=部門曲線のみ(donor転写を外す) → 区域平均形状で代替(実装はcompute_regionのf_srcに依存)
sect = area_prof/area_prof.mean()
b1 = np.outer(x_ours.mean(axis=1), sect)

def score(X, name):
    rows = []
    for k in tw.columns:
        if k not in idx: continue
        i = idx[k]
        t = tw[k].values.astype(float); e = X[i]
        m = np.isfinite(t) & np.isfinite(e)
        if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
        rows.append(dict(key=k,
            ape=100*abs(np.nanmean(e[m])-np.nanmean(t[m]))/np.nanmean(t[m]),
            corr=float(np.corrcoef(e[m], t[m])[0,1]) if np.std(e[m])>1e-9 else np.nan,
            cv=100*float(np.sqrt(np.mean((e[m]-t[m])**2))/np.nanmean(t[m]))))
    d = pd.DataFrame(rows)
    ci_a, ci_c = boot_ci(d.ape), boot_ci(d["corr"])
    print(f"  {name:24} n={len(d):>4} APE中央={d.ape.median():5.1f}% [{ci_a[0]:.1f},{ci_a[1]:.1f}]"
          f"  corr中央={d["corr"].median():.3f} [{ci_c[0]:.3f},{ci_c[1]:.3f}]"
          f"  CV-RMSE={d.cv.median():5.1f}%  corr>=0.8={100*(d["corr"]>=0.8).mean():.0f}%", flush=True)
    return d
d_ours = score(x_ours, "ours (tiered)")
d_b0   = score(b0,     "capacity-proportional")
d_b1   = score(b1,     "area-shape (no donor)")
d_b2   = score(b2,     "flat (level only)")
# 対応のある差(同一局)の検定用CI
j = d_ours[["key","ape","corr"]].merge(d_b0[["key","ape","corr"]], on="key", suffixes=("_o","_b"))
dc = j['corr_o'] - j['corr_b']; da = j.ape_o - j.ape_b
print(f"  [対応差 ours−capacity] corr {dc.median():+.3f} CI{np.round(boot_ci(dc),3)}"
      f" / APE {da.median():+.1f}pt CI{np.round(boot_ci(da),1)}")
j2 = d_ours[["key","corr"]].merge(d_b1[["key","corr"]], on="key", suffixes=("_o","_b"))
dc2 = j2['corr_o'] - j2['corr_b']
print(f"  [対応差 ours−area-shape] corr {dc2.median():+.3f} CI{np.round(boot_ci(dc2),3)}")
out = pd.DataFrame([
    dict(method="ours (tiered)", n=len(d_ours), ape=d_ours.ape.median(), corr=d_ours["corr"].median(),
         cv=d_ours.cv.median(), c08=100*(d_ours["corr"]>=0.8).mean()),
    dict(method="capacity-proportional", n=len(d_b0), ape=d_b0.ape.median(), corr=d_b0["corr"].median(),
         cv=d_b0.cv.median(), c08=100*(d_b0["corr"]>=0.8).mean()),
    dict(method="area-shape (no donor)", n=len(d_b1), ape=d_b1.ape.median(), corr=d_b1["corr"].median(),
         cv=d_b1.cv.median(), c08=100*(d_b1["corr"]>=0.8).mean()),
    dict(method="flat (level only)", n=len(d_b2), ape=d_b2.ape.median(), corr=d_b2["corr"].median(),
         cv=d_b2.cv.median(), c08=100*(d_b2["corr"]>=0.8).mean()),
]).round(3)
out.to_csv(f"{HERE}/{TAG}_baselines_pretest.csv", index=False, encoding="utf-8-sig")
d_ours.to_csv(f"{HERE}/{TAG}_micro_ours_pretest.csv", index=False, encoding="utf-8-sig")

# ── D) 考官床のCVにCI ──
print("\n=== D) 考官床の bootstrap CI (TEPCO·月次12点) ===", flush=True)
def q1(sql):
    p = subprocess.run(["docker","exec","-i",_DBC,"psql","-U","postgres","-d","lab_database","-A","-F","|","-tc",sql],
                       capture_output=True)
    return pd.read_csv(io.StringIO(p.stdout.decode("utf-8","replace")), sep="|", header=None)
MONTHS = ["2024-04","2024-05","2024-06","2024-07","2024-08","2024-09","2024-10","2024-11","2024-12","2025-01","2025-02","2025-03"]
_ek = set(qdf(f"SELECT DISTINCT station_id FROM {EST_REL} WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}'", ["k"]).k)
trm = qdf("""SELECT station_norm, to_char(ts,'YYYY-MM'), sum(flow_mw), count(DISTINCT to_char(ts,'YYYY-MM-DD HH24:00'))
FROM validation.tepco_bank_fy2024_full GROUP BY 1,2""", ["nm","ym","s","n"], ["s"])
trm["key"] = trm.nm.map(norm2); trm = trm[trm.key.isin(_ek)]
trm["n"] = pd.to_numeric(trm["n"])
hrs = trm.groupby("ym")["n"].max()
T = (trm.groupby("ym")["s"].sum()/hrs).reindex(MONTHS)
E = q1(f"""SELECT to_char(ts,'YYYY-MM'), sum(demand_net_mw)/count(DISTINCT ts) FROM {EST_REL}
WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}' GROUP BY 1 ORDER BY 1""")
E.columns=["ym","mw"]; E=E.set_index("ym")["mw"].reindex(MONTHS).astype(float)
G = q1("""SELECT to_char(year_month,'YYYY-MM'), sum(demand_gwh)*1000.0/max(extract(epoch FROM (year_month+interval '1 month')-year_month)/3600.0)
FROM public_data.area_demand_by_voltage WHERE utility='TEPCO' AND voltage_class IN ('high','low')
AND year_month>='2024-04-01' AND year_month<'2025-04-01' GROUP BY 1,year_month ORDER BY 1""")
G.columns=["ym","mw"]; G=G.set_index("ym")["mw"].reindex(MONTHS).astype(float)
rt, re_, rr = (T/G).values, (E/G).values, (E/T).values
cv = lambda v: float(np.std(v, ddof=0)/np.mean(v))
for nm_, v in [("truth/EGC", rt), ("est/EGC", re_), ("est/truth", rr)]:
    ci = boot_ci(v, fn=cv)
    print(f"  CV({nm_:10}) = {cv(v):.4f}  95%CI [{ci[0]:.4f}, {ci[1]:.4f}]")
diff = np.array([cv(RNG.choice(re_, 12, replace=True)) - cv(RNG.choice(rt, 12, replace=True)) for _ in range(2000)])
print(f"  CV(est/EGC) − CV(truth/EGC) = {cv(re_)-cv(rt):+.4f}  95%CI [{np.percentile(diff,2.5):+.4f}, {np.percentile(diff,97.5):+.4f}]"
      f"  → {'区別できない(床に到達)' if np.percentile(diff,2.5) < 0 < np.percentile(diff,97.5) else '有意差あり'}")
pd.DataFrame(dict(month=MONTHS, truth_egc=rt, est_egc=re_, est_truth=rr)).to_csv(
    f"{HERE}/{TAG}_floor_monthly_pretest.csv", index=False, encoding="utf-8-sig")

# ── C) HC順位相関の確定 ──
print("\n=== C) hosting capacity 順位相関(確定値) ===", flush=True)
hc = q1("""SELECT utility, split_part(node_id,':',2), hc_mw FROM canonical.hosting_capacity
WHERE hc_method='published' AND hc_mw IS NOT NULL""")
if hc.empty or hc.shape[1] < 3:
    print("  published HC 取得できず→要確認")
else:
    hc.columns = ["u","sid","hc"]; hc["hc"] = pd.to_numeric(hc.hc, errors="coerce")
    scr = q1(f"""SELECT e.utility, e.station_id,
        max(r.opcap_mw) - percentile_cont(0.95) WITHIN GROUP (ORDER BY e.demand_net_mw)
      FROM {EST_REL} e
      JOIN canonical.haihen_roster r ON r.utility=e.utility AND r.name=e.station_id
      WHERE e.run_id LIKE '{EST_LIKE}' AND r.opcap_mw>0 GROUP BY 1,2""")
    scr.columns = ["u","sid","screen"]; scr["screen"] = pd.to_numeric(scr.screen, errors="coerce")
    m = hc.merge(scr, on=["u","sid"]).dropna()
    from scipy.stats import spearmanr
    if len(m) >= 30:
        rho, pv = spearmanr(m.hc, m.screen)
        print(f"  照合 {len(m)}局 / Spearman rho = {rho:.3f} (p={pv:.2e})")
        per = {u: round(float(spearmanr(g.hc, g.screen)[0]), 3)
               for u, g in m.groupby("u") if len(g) >= 20}
        print("  区域別:", per)
        m.to_csv(f"{HERE}/{TAG}_hc_match_pretest.csv", index=False, encoding="utf-8-sig")
    else:
        print(f"  照合 {len(m)}局 <30 → 相関算出せず(要名寄せ調査)")
print(f"[出力] {TAG}_*_pretest.csv (受入試験前・1,249局。清浄後の正本は recompute_all_clean.py)")
