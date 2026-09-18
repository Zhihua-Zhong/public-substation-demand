#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2つの整合性チェック(投稿前の必須確認):
 ①飽和率31%は真値で裏付くか: 標定区の真値局で「昼間5%点<=0」の実測比率 vs 当方推計の比率。
   これが合えば headroom claim は真値裏付きになり、naive基線比較より遥かに強い。
 ②published HC の照合が21局しか無い理由: 区域別·node_id形式の診断。
   照合が本当に少ないなら、論文のHC比較節は撤回または大幅限定する(誠実性)。
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
from stage2_engine import IDX, norm2, qdf
from est_source import db_source
EST_REL, EST_LIKE, TAG = db_source()   # PAPER_EST_REL, required (RERUN_PLAN_R1.md Step 3, items 4 and 6)
import os as _os, sys as _sys
_DBC = _os.environ.get("DT_DB_CONTAINER") or _sys.exit(
    "[FATAL] 論文作業区では DT_DB_CONTAINER の明示が必須(例: iwafune_db_frozen)。生産DB誤接続の防止。")


def q(sql):
    p = subprocess.run(["docker","exec","-e","PGOPTIONS=-c max_parallel_workers_per_gather=0",
        "-i",_DBC,"psql","-U","postgres","-d","lab_database","-A","-F","|","-tc",sql], capture_output=True)
    s = p.stdout.decode("utf-8","replace")
    return pd.read_csv(io.StringIO(s), sep="|", header=None) if s.strip() else pd.DataFrame()

print("=== ① 昼間逆転(飽和)率: 真値 vs 推計 (標定区) ===", flush=True)
tru = qdf("""SELECT station_norm, to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw
FROM validation.tepco_bank_fy2024_full""", ["nm","ts","mw"], ["mw"])
tru["key"] = tru.nm.map(norm2)
tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
tw.index = pd.to_datetime(tw.index); tw = tw.reindex(IDX)
day = (IDX.hour >= 9) & (IDX.hour <= 15)
est = q(f"""SELECT station_id,
   percentile_cont(0.05) WITHIN GROUP (ORDER BY demand_net_mw)
     FILTER (WHERE extract(hour FROM ts) BETWEEN 9 AND 15)
FROM {EST_REL} WHERE utility='TEPCO' AND run_id LIKE '{EST_LIKE}'
GROUP BY 1""")
est.columns = ["key","p05"]; est["p05"] = pd.to_numeric(est.p05, errors="coerce")
em = est.set_index("key")["p05"]
rows = []
for k in tw.columns:
    if k not in em.index: continue
    t = tw[k].values.astype(float)
    m = np.isfinite(t)
    if m.sum() < 3000 or np.nanmean(t[m]) < 0.5: continue
    td = t[day & m]
    if len(td) < 500: continue
    rows.append(dict(key=k, truth_p05=float(np.percentile(td, 5)), est_p05=float(em[k]),
                     truth_mean=float(np.nanmean(t[m]))))
d = pd.DataFrame(rows)
st_t = 100*(d.truth_p05 <= 0).mean(); st_e = 100*(d.est_p05 <= 0).mean()
print(f"  対象 {len(d)}局")
print(f"  昼間5%点<=0 の比率: 真値 {st_t:.1f}%  推計 {st_e:.1f}%")
tp = int(((d.truth_p05<=0) & (d.est_p05<=0)).sum()); fp = int(((d.truth_p05>0) & (d.est_p05<=0)).sum())
fn = int(((d.truth_p05<=0) & (d.est_p05>0)).sum()); tn = int(((d.truth_p05>0) & (d.est_p05>0)).sum())
print(f"  混同行列: TP={tp} FP={fp} FN={fn} TN={tn}")
if tp+fp > 0 and tp+fn > 0:
    prec, rec = tp/(tp+fp), tp/(tp+fn)
    print(f"  適合率={100*prec:.0f}%  再現率={100*rec:.0f}%  正解率={100*(tp+tn)/len(d):.0f}%")
print(f"  相関(昼間5%点·真値vs推計) r={np.corrcoef(d.truth_p05, d.est_p05)[0,1]:.3f}")
d.to_csv(f"{HERE}/{TAG}_saturation_check.csv", index=False, encoding="utf-8-sig")

print("\n=== ② published HC の照合診断 ===", flush=True)
hc = q("""SELECT utility, split_part(node_id,':',2), hc_mw FROM canonical.hosting_capacity
WHERE hc_method='published' AND hc_mw IS NOT NULL""")
hc.columns = ["u","sid","hc"]
print("  published HC 区域別:", hc.u.value_counts().to_dict())
es = q(f"""SELECT utility, count(DISTINCT station_id) FROM {EST_REL}
WHERE run_id LIKE '{EST_LIKE}' GROUP BY 1""")
es.columns = ["u","n"]
esk = q(f"""SELECT utility, station_id FROM {EST_REL}
WHERE run_id LIKE '{EST_LIKE}' GROUP BY 1,2""")
esk.columns = ["u","sid"]
hc["k"] = hc.sid.map(norm2); esk["k"] = esk.sid.map(norm2)
mm = hc.merge(esk, on=["u","k"], suffixes=("_hc","_est"))
print("  norm2照合 区域別:", mm.u.value_counts().to_dict())
print(f"  照合合計 {len(mm)} / published {len(hc)} ({100*len(mm)/len(hc):.0f}%)")
print("  未照合の例(HC側):", hc[~hc.k.isin(set(mm.k))].sid.head(8).tolist())
mm.to_csv(f"{HERE}/{TAG}_hc_join_diag.csv", index=False, encoding="utf-8-sig")
