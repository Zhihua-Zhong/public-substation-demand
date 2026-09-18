# -*- coding: utf-8 -*-
"""手法書②(ネット潮流水準)の正本産生器。v6.6 = 稼働確率を外し、回帰に太陽光を入れた版。

`p0_phantom_lf.py`(v6.5)の後継である。違いは三点だけで、それ以外は口径を厳密に継ぐ。
  ① 水準式から稼働確率を外す      L = C × λ_a   (旧: C × λ_a × p_i)
  ② 錨の分母を全登録容量にする     λ = Σ真値 / Σ容量(全純化roster)  (旧: Σ載荷容量)
  ③ 転写回帰に太陽光密度を足す
結果として局別共変量が水準に要らなくなり、容量のある局はすべて水準を持つ。
沖縄の官方載荷錨は廃止した(§G/§I/§J の検証による)。

**離線層だけで走る。**凍結DBに触れないので再現ゲートの中に置ける。
v6.5 の錨は正本 p0 と数値が完全に一致することを検算してある(下記 assert)。

出力:
  results/numbers/station_levels_v66.csv   推計キー5,950行(utility,key,cap,lambda,level)
  results/numbers/level_model_v66.json     原稿が引用する数値の全て(ゲートが本文と突合する)

論文の対応: §3.4 Level model and the anchor hierarchy
"""
import os, sys, re, json, pathlib
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT, ENG = W/"data"/"offline", W/"results"/"numbers", W/"code"/"engine"/"analysis"/"unified"/"out"
OUT.mkdir(parents=True, exist_ok=True)
# norm2(局名正規化)は正本 stage2_engine から借りる。本スクリプトはDBに接続しない
# (qdf を呼ばない)が、凍結包の fail-closed 検査が import 時に env を要求するため
# 使われないことが分かる値を置く。roster の name_norm 列は norm2 と 2.5% 食い違うので
# 代用できない(実測 6457/6622 一致)。
os.environ.setdefault("DT_DB_CONTAINER", "offline-not-used")
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from stage2_engine import norm2

JA = {"HOKKAIDO":"Hokkaido","TOHOKU":"Tohoku","TEPCO":"Tokyo","CHUBU":"Chubu","HOKURIKU":"Hokuriku",
      "KANSAI":"Kansai","CHUGOKU":"Chugoku","SHIKOKU":"Shikoku","KYUSHU":"Kyushu","OKINAWA":"Okinawa"}
ORDER = list(JA)
rng = np.random.default_rng(20260803)
R = {}                                               # 原稿が引用する数値をここへ集める

# ══════════ 1. 純化 roster(p0 と同一規則) ══════════
def purify(u):
    r = pd.read_parquet(OFF/"haihen_roster.parquet")
    r = r[r.utility == u].copy()
    for c in ("equip_mw", "opcap_mw"):
        r[c] = pd.to_numeric(r[c], errors="coerce")
    r["cap"] = r.equip_mw.fillna(r.opcap_mw)
    r = r[r.cap.between(0.1, 150)].copy()
    r["sec"] = r.sec_kv.fillna("").astype(str)
    def bad(x):
        s = x.sec
        for v in ("500", "275", "220", "187", "154", "110", "77", "66"):
            if v in s: return True
        if re.search(r"中間|開閉", str(x["name"])): return True
        has = bool(re.search(r"6\.6|6kV|3\.3|3kV|低圧|以下", s))
        if re.search(r"22|33", s) and not has: return True
        return False
    r = r[~r.apply(bad, axis=1)].copy()
    r["key"] = r["name"].map(norm2)
    return r.sort_values(["name", "cap"], ascending=[True, False]).drop_duplicates("key")

print("=== 1) 標定区の錨 ===", flush=True)
ros = purify("TEPCO")
T  = pd.read_parquet(OFF/"truth_tepco_bank_fy2024.parquet")
km = pd.read_parquet(OFF/"station_key_map.parquet")
kmt = km[(km.utility == "TEPCO") & (km.kind == "truth")][["src_name", "key"]].drop_duplicates()
tm = (T.merge(kmt, left_on="station_norm", right_on="src_name", how="inner")
        .groupby(["key", "ts"], observed=True)["flow_mw"].sum().groupby(level=0).mean())
ros["truth"] = ros.key.map(tm)
ros["load"] = ros.truth.notna() & (ros.truth > 0.5)
cap_load, cap_ph = float(ros[ros.load].cap.sum()), float(ros[~ros.load].cap.sum())
truth_sum = float(ros[ros.load].truth.sum())
R.update(roster_purified=len(ros), n_loaded=int(ros.load.sum()), n_phantom=int((~ros.load).sum()),
         cap_loaded_mw=round(cap_load), cap_phantom_mw=round(cap_ph),
         cap_total_mw=round(cap_load+cap_ph),
         phantom_cap_share_pct=round(100*cap_ph/(cap_load+cap_ph), 1),
         truth_sum_mw=round(truth_sum),
         lf_real_v65=round(truth_sum/cap_load, 4),
         lambda_tepco=round(truth_sum/(cap_load+cap_ph), 4))
print(f"  純化roster {R['roster_purified']}局: 載荷{R['n_loaded']}(Σcap {R['cap_loaded_mw']}MW) / "
      f"幻影{R['n_phantom']}(Σcap {R['cap_phantom_mw']}MW={R['phantom_cap_share_pct']}%)")
print(f"  v6.5 の LF_real = {R['truth_sum_mw']} / {R['cap_loaded_mw']} = {R['lf_real_v65']}")
print(f"  ★v6.6 の λ      = {R['truth_sum_mw']} / {R['cap_total_mw']} = {R['lambda_tepco']}")
# 正本 p0_phantom_lf.py を凍結DBで実行して得た値との検算(2026-08-03)
assert (R["roster_purified"], R["n_loaded"], R["cap_loaded_mw"], R["n_phantom"],
        R["cap_phantom_mw"], R["truth_sum_mw"], R["lf_real_v65"]) == \
       (1415, 1196, 56757, 219, 9023, 23031, 0.4058), "正本 p0 と口径が合わない"
print("  検算: 正本 p0 の出力と完全一致")

# ══════════ 2. 局別共変量と太陽光(離線層から作る) ══════════
print("\n=== 2) 転写回帰(標定区の真値で当てはめ) ===", flush=True)
al = pd.read_parquet(OFF/"mesh_substation_alloc.parquet", columns=["mesh_code","utility","station_id","weight"])
ce = pd.read_parquet(OFF/"census_mesh_1km.parquet", columns=["mesh_1km","households"])
ec = pd.read_parquet(OFF/"econ_census_mesh_1km.parquet", columns=["mesh_1km","emp_total","emp_manu"])
sm = pd.read_parquet(OFF/"substation_master.parquet", columns=["utility","station_id","station_name","node_type"])
sm = sm[sm.node_type == "haihen"].copy()
sm["key"] = sm.station_name.fillna(sm.station_id).astype(str).map(norm2)
a = (al.merge(ce, left_on="mesh_code", right_on="mesh_1km", how="left")
       .merge(ec, left_on="mesh_code", right_on="mesh_1km", how="left"))
for c in ("households", "emp_total", "emp_manu"):
    a[c] = pd.to_numeric(a[c], errors="coerce").fillna(0.0)
a["hh"]   = a.weight * a.households
a["manu"] = a.weight * a.emp_manu
a["tert"] = a.weight * (a.emp_total - a.emp_manu)
cov = (a.groupby(["utility", "station_id"], as_index=False)[["hh", "manu", "tert"]].sum()
         .merge(sm[["utility", "station_id", "key"]], on=["utility", "station_id"], how="inner")
         .groupby(["utility", "key"], as_index=False)[["hh", "manu", "tert"]].sum())

pv = pd.read_parquet(OFF/"substation_pv.parquet")
pvk = (pv.merge(sm[["utility", "station_id", "key"]], on=["utility", "station_id"], how="inner")
         .groupby(["utility", "key"], as_index=False)["pv_total_kw"].sum())
pvk["pv_mw"] = pvk.pv_total_kw / 1000.0

d = ros[ros.load][["key", "cap", "truth"]].merge(
        cov[cov.utility == "TEPCO"][["key", "hh", "manu", "tert"]], on="key", how="inner").merge(
        pvk[pvk.utility == "TEPCO"][["key", "pv_mw"]], on="key", how="left")
d["pv_mw"] = d.pv_mw.fillna(0.0)
d = d[(d.hh > 0) & (d.manu > 0) & (d.tert > 0)].copy()
d["lf"]       = d.truth / d.cap
# 受入試験(§2.2)を回帰の標本にだけ当てる。錨には当てない ― この非対称は §3.4 に明記してある。
#   錨は fleet 全体の集計で、公表真値が下界であることを承知のうえで使う。
#   回帰は局を一つずつ見る当てはめなので、自分の定格を超える系列は
#   その局の負荷率ではありえない。残せば当てはまりを壊す(群馬 19MW の設備に真値 208MW)。
n_pre = len(d)
d = d[d.lf <= 1.0].copy()
R["n_reg_excluded_over_capacity"] = n_pre - len(d)
print(f"  受入試験で回帰から外した容量超過の局 {R['n_reg_excluded_over_capacity']}")
d["mfg"]      = d.manu / (d.manu + d.tert)
d["ln_hhcap"] = np.log(d.hh / d.cap)
d["pv_dens"]  = d.pv_mw / d.cap
y = np.log(d.lf).values
n = len(d)
print(f"  当てはめに使う局 {n}")
R["n_fit_stations"] = n

def ols(cols):
    X = np.column_stack([np.ones(n)] + [d[c].values for c in cols])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    tot = ((y - y.mean())**2).sum()
    r2 = 1 - ((y - X@b)**2).sum()/tot
    folds = np.array_split(np.random.default_rng(20260803).permutation(n), 5)
    pr = np.empty(n)
    for f in folds:
        tr = np.setdiff1d(np.arange(n), f)
        Xt = np.column_stack([np.ones(len(tr))] + [d[c].values[tr] for c in cols])
        bt, *_ = np.linalg.lstsq(Xt, y[tr], rcond=None)
        pr[f] = np.column_stack([np.ones(len(f))] + [d[c].values[f] for c in cols]) @ bt
    return b, r2, 1 - ((y - pr)**2).sum()/tot

b_no,  r2_no,  cv_no  = ols(["mfg", "ln_hhcap"])
b_pv,  r2_pv,  cv_pv  = ols(["mfg", "ln_hhcap", "pv_dens"])
# 総需要空間の対照(製造業比の符号の物理的な期待値を示すため)
yg = y.copy()
sf = pd.read_parquet(OFF/"station_features.parquet",
                     columns=["utility","station_key","fiscal_year","pv_mean_mw"])
sf = sf[(sf.utility=="TEPCO") & (sf.fiscal_year==2024)].groupby("station_key")["pv_mean_mw"].mean()
d["pv_gen"] = d.key.map(sf).fillna(0.0)
y = np.log((d.truth + d.pv_gen) / d.cap).values
b_gr, _, _ = ols(["mfg", "ln_hhcap"])
y = np.log(d.lf).values
R.update(reg_no_pv={"const": round(b_no[0],4), "mfg": round(b_no[1],4), "ln_hhcap": round(b_no[2],4),
                    "r2": round(r2_no,4), "cv_r2": round(cv_no,4)},
         reg_pv={"const": round(b_pv[0],4), "mfg": round(b_pv[1],4), "ln_hhcap": round(b_pv[2],4),
                 "pv_dens": round(b_pv[3],4), "r2": round(r2_pv,4), "cv_r2": round(cv_pv,4)},
         reg_gross_mfg=round(b_gr[1], 2))

# ── 太陽光の項は物理として閉じるか。原稿 §3.4 の正直な但し書きの根拠 ──
#   閉じているなら LF_net = LF_gross − k·x で、x=登録容量密度なら k は設備利用率(0.12〜0.15)、
#   x=実測発電密度なら k は恒等式より 1 でなければならない。
from scipy.optimize import least_squares
def fit_k(x, k0):
    def res(p):
        lfg = np.exp(p[0] + p[1]*d.mfg.values + p[2]*d.ln_hhcap.values)
        return np.log(np.maximum(lfg - p[3]*x, 1e-4)) - y
    return float(least_squares(res, [-2.5, -0.15, 0.23, k0]).x[3])
k_cap = fit_k(d.pv_dens.values, 0.13)
k_gen = fit_k((d.pv_gen/d.cap).values, 1.0)
R.update(pv_k_from_capacity=round(k_cap, 3), pv_k_from_generation=round(k_gen, 2),
         pv_physical_capacity_factor=round(float((d.pv_gen[d.pv_mw > 0]
                                                  / d.pv_mw[d.pv_mw > 0]).median()), 3))
print(f"  物理検定: 登録容量で当てると k={k_cap:.3f}(実測の設備利用率 "
      f"{R['pv_physical_capacity_factor']:.3f})  実測発電で当てると k={k_gen:.2f}(恒等式は 1)")
print(f"  太陽光なし: mfg={b_no[1]:+.4f}  CV R²={cv_no:.4f}")
print(f"  太陽光あり: mfg={b_pv[1]:+.4f}  pv={b_pv[3]:+.4f}  CV R²={cv_pv:.4f}")
print(f"  総需要空間の mfg = {b_gr[1]:+.2f}(物理の期待は正)")

# ══════════ 3. 区域の λ_a と水準表 ══════════
print("\n=== 3) 区域負荷率と水準表 ===", flush=True)
wl = pd.read_csv(OUT/"ledger_whitelist_v65.csv")
wl.columns = [c.lstrip("﻿") for c in wl.columns]
wl = wl.rename(columns={"u": "utility", "sid": "key"})
caps = []
for u in ORDER:
    r = purify(u)[["key", "cap"]].copy(); r["utility"] = u
    caps.append(r)
caps = pd.concat(caps, ignore_index=True)
lv = wl.merge(caps, on=["utility", "key"], how="left")
assert lv.cap.notna().all(), f"容量の引けない局が {int(lv.cap.isna().sum())} 局ある"

v5 = pd.read_csv(ENG/"national_verdict_v5.csv").set_index("u")
capA = lv.groupby("utility")["cap"].sum()
pvA  = pvk.merge(wl, on=["utility", "key"], how="inner").groupby("utility")["pv_mw"].sum()
idx = {u: float(np.exp(b_pv[0] + b_pv[1]*float(v5.at[u, "manu_share"])
                       + b_pv[2]*np.log(float(v5.at[u, "hh_per_cap"]))
                       + b_pv[3]*float(pvA.get(u, 0.0))/float(capA[u]))) for u in ORDER}
LAM = {u: R["lambda_tepco"] * idx[u] / idx["TEPCO"] for u in ORDER}
lv["lambda"] = lv.utility.map(LAM)
lv["level"]  = lv.cap * lv["lambda"]
R.update(lambda_min=round(min(LAM.values()), 4), lambda_max=round(max(LAM.values()), 4),
         n_keys=len(lv), lambda_by_area={JA[u]: round(LAM[u], 4) for u in ORDER})
print(f"{'区域':<10}{'太陽光密度':>10}{'λ_a':>9}{'東京=1':>9}{'Σlevel MW':>12}")
for u in ORDER:
    print(f"{JA[u]:<10}{float(pvA.get(u,0))/float(capA[u]):>10.3f}{LAM[u]:>9.4f}"
          f"{LAM[u]/LAM['TEPCO']:>9.4f}{lv[lv.utility==u].level.sum():>12.0f}")
print(f"  λ_a の幅 {R['lambda_min']} 〜 {R['lambda_max']}")

# 台帳名への展開(前端が表示する 5,968)
kmm = km[km.kind == "master"][["utility", "key", "src_name"]].drop_duplicates()
smh = sm[["utility", "station_id"]].rename(columns={"station_id": "src_name"}).drop_duplicates()
names = kmm.merge(smh, on=["utility", "src_name"]).merge(lv[["utility", "key"]], on=["utility", "key"])
R["n_ledger_names"] = len(names)
print(f"  推計キー {R['n_keys']} → 台帳名 {R['n_ledger_names']}")

# 共変量の無い局(旧版が落としていた集合)。水準模型が容量だけを読む理由の実証
nocov = lv.merge(cov[["utility", "key"]].assign(has=1), on=["utility", "key"], how="left")
nocov = nocov[nocov.has.isna()]
R.update(n_no_alloc=len(nocov), no_alloc_mean_cap_mw=round(float(nocov.cap.mean())),
         national_median_cap_mw=round(float(lv.cap.median())))
print(f"  共変量の付かない局 {R['n_no_alloc']}(平均容量 {R['no_alloc_mean_cap_mw']}MW / "
      f"全国中央 {R['national_median_cap_mw']}MW)")

lv[["utility", "key", "cap", "lambda", "level"]].sort_values(["utility", "key"]).to_csv(
    OUT/"station_levels_v66.csv", index=False, encoding="utf-8-sig")
(OUT/"level_model_v66.json").write_text(json.dumps(R, ensure_ascii=False, indent=2, sort_keys=True),
                                        encoding="utf-8")
print(f"\n[出力] {OUT/'station_levels_v66.csv'} ({len(lv)}行)")
print(f"[出力] {OUT/'level_model_v66.json'}")
