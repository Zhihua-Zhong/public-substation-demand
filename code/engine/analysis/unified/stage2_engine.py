#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""統一エンジン Stage2 (PV-aware): 全国配変の net/gross/PV 三分解を単一実装で生成。

このモジュールが推計定義の唯一の正本。検証(stage2_monthly_blend.py)と持久化
(persist_stage2_fy2024.py)は必ずここから import すること(定義の漂移防止)。

物理構成:
  PV_n(t)   = pvcap_n × g_u(t),  g_u = (pv1発生 − 出力制御) × 可見率 / Σpvcap
  R_gross   = R_net + PV_obs(t)                    ← 既知のPVを左辺へ移項(net非平稳の除去)
  f_u(t)    = 3部門NNLS(世帯/製造/三次) on R_gross  ← 可観測局のみ·覆蓋帯のみ
  D_gross   = (level_n + pvcap_n·mean(g)) × shape_n(t)
  D_net     = D_gross − PV_n(t)                    ← EGC/真値と同口径
  src='z1'  : 可観測かつ門[0.6,1.4]内 → D_net := R_n(t) (実測KCLで置換)
  src='z2'  : それ以外 → 上式のprior

情報防火壁(推計に不使用): EGC / METI / OCCTO / LT真値。
  使用源: 公開潮流(flow_estimation_input=LT遮蔽済) / 銘牌容量(haihen_roster) /
          国勢調査·経済センサス1kmメッシュ / FIT由来配変級PV容量 / pv1(気象) / 出力制御実績。
"""
import hashlib, io, os, pathlib, re, subprocess, sys
import numpy as np, pandas as pd
from scipy.optimize import nnls

# ★凍結・再現用: DBコンテナ名を環境変数で差し替え可能にする(既定は現行の開発DB)。
#   凍結版は DT_DB_CONTAINER=iwafune_db_frozen を与えて隔離DBへ向ける。
def _resolve_db_container():
    """接続先の解決。★凍結包(FREEZE.marker あり)では既定値を持たない=fail-closed。
    環境変数の付け忘れで本番DBへ接続し、DELETE/DROP を走らせる事故を構造的に防ぐ。"""
    import os, pathlib as _p, sys as _s
    v = os.environ.get("DT_DB_CONTAINER")
    if v: return v
    for _d in _p.Path(__file__).resolve().parents:
        if (_d / "FREEZE.marker").exists():
            _s.exit("[FATAL] 凍結包では DT_DB_CONTAINER の明示が必須である(既定値を持たない)。 "
                    "例: DT_DB_CONTAINER=iwafune_db_frozen <コマンド> / "
                    "本番DBへの誤接続と破壊を防ぐための fail-closed 設計である。")
    return "iwafune_db"
_DB_CONTAINER = _resolve_db_container()



ROOT = str(pathlib.Path(__file__).resolve().parents[2])  # クリーンルーム: リポジトリ相対

def _require(rel, why):
    """必須入力の明示的検査。★暗黙の劣化の禁止(2026-07-28 移植監査): 入力欠落を
       握り潰して劣化した結果を返すのが最も危険。欠落は必ず起動時に落とす。"""
    p = pathlib.Path(ROOT) / rel
    if not p.exists():
        sys.exit(f"[input] 必須入力が不在: {rel}\n  用途: {why}\n"
                 f"  → 復旧せずに実行してはならない(結果が静かに劣化する)。")
    return str(p)
REGIONS = ["TEPCO","KANSAI","CHUBU","TOHOKU","KYUSHU","CHUGOKU","HOKKAIDO","HOKURIKU","SHIKOKU","OKINAWA"]
IDX = pd.date_range("2024-04-01", periods=8760, freq="h")
Z1_GATE = (0.6, 1.4)                 # 実測採用門(=[0.5,2]はk=2束線が混入して悪化·実証済)
PV_GAMMA = 1.0                       # PV集中度阻尼指数(1=無阻尼·TEPCO真値でグリッド標定)
GEN_PAT = re.compile(r"水力|火力|原子力|地熱|風力|発電|変換所|太陽光|ソーラー|需要家")
TIE_PAT = re.compile(r"連絡|連系")
UPPER_KV = ("500","275","220","187","154","110","77","66")
TRT = str.maketrans("ヶッ⾧ＡＢＣＤＥＦ０１２３４５６７８９","ケツ長ABCDEF0123456789")

def norm2(s):
    if s is None or (isinstance(s,float) and np.isnan(s)): return ""
    s = str(s).translate(TRT); s = re.sub(r"[\s　'\"]","",s); s = re.sub(r"^(\d+)","",s)
    s = re.sub(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?kV","",s)      # 電圧注記「77/6kV」(北陸master流儀)
    s = re.sub(r"(直配|直流)$","",s)
    s = re.sub(r"(変電所|開閉所|開閉器柱|\(開B\)|（開B）|\(変\)|（変）|\(開\)|（開）)","",s)
    m = re.search(r"[（(]([^（()）]*変電所[^（()）]*)[)）]", s)
    if m: s = m.group(1)
    s = re.sub(r"(変電所|配電塔|変換所|SS)$","",s)
    s = s.replace("が","ケ").replace("ヶ","ケ").replace("ガ","ケ")
    s = re.sub(r"(局配|中間)$","",s); s = re.sub(r"局$","",s)
    s = re.sub(r"変$","",s)
    return re.sub(r"配変\d*号?$","",s)

def qdf(sql, names, num=()):
    p = subprocess.run(["docker","exec","-i",_DB_CONTAINER,"psql","-U","postgres","-d","lab_database","-tAc",
                        f"COPY ({sql}) TO STDOUT WITH CSV"], capture_output=True)
    if p.returncode: print("SQL ERR:", p.stderr.decode("utf-8","replace")[:400]); sys.exit(1)
    df = pd.read_csv(io.StringIO(p.stdout.decode("utf-8","replace")), names=names, dtype=str)
    for c in num: df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# v6.6 level model (RERUN_PLAN_R1.md Section 2; ACCEPTANCE_CRITERIA_R1.md, change 1):
#   L_i = C_i x lambda_a, one rule for every key.
# The level input is the single file that code/paper/build_level_v66.py writes inside the
# reproduction gate, read by its workspace path. No copy is kept in out/: E5 was caused by a
# second level file (station_levels_v6.csv) that drifted without trace. The v6.5 inputs
# station_levels_v6.csv and national_verdict_v5.csv are no longer read by the engine.
# The file is read on the first roster_levels() call, not at import, so that build_level_v66.py
# can import norm2 from this module while it regenerates the file.
# Criterion G (ACCEPTANCE_CRITERIA_R1.md): the screened-anchor sensitivity runs this same engine on a
# variant level file named by PAPER_LEVEL_FILE. Only the two files below are accepted, and the default
# is the canonical file, so an unset variable reproduces the main run exactly.
LEVEL_FILES = ("results/numbers/station_levels_v66.csv",
               "results/numbers/station_levels_v66_screened.csv")
_level_rel = os.environ.get("PAPER_LEVEL_FILE", LEVEL_FILES[0])
if _level_rel not in LEVEL_FILES:
    sys.exit(f"[FATAL] PAPER_LEVEL_FILE must be one of {LEVEL_FILES}; got {_level_rel!r}")
LEVEL_FILE = pathlib.Path(ROOT).parents[1] / _level_rel
_LV66 = None
ROSTER_CAP = {}                      # utility -> purified roster capacity per key (for the run files)
def level_input():
    """The v6.6 level table (utility, key, cap, lambda, level) and the sha256 of the bytes read."""
    global _LV66
    if _LV66 is None:
        if not LEVEL_FILE.exists():
            sys.exit(f"[input] required input missing: {LEVEL_FILE}\n"
                     "  Regenerate it with ./reproduce_paper.sh (code/paper/build_level_v66.py).")
        raw = LEVEL_FILE.read_bytes()
        _LV66 = (pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig"), hashlib.sha256(raw).hexdigest())
    return _LV66
_bc = pd.read_csv(_require("analysis/pv_zerofit/fit_regional_capacity_202409.csv",
                           "③FIT規模別AC容量 → 可見率VIS(配電側から見えるPVの割合)"),
                  encoding="utf-8-sig").set_index("utility")
VIS = ((_bc["ac_lt10_mw"]+_bc["ac_10_50_mw"]+_bc["ac_50_2000_mw"]) /
       (_bc["ac_lt10_mw"]+_bc["ac_10_50_mw"]+_bc["ac_50_2000_mw"]+_bc["ac_ge2000_mw"])).to_dict()

def covariates(U):
    c = qdf(f"""SELECT coalesce(m.station_name, m.station_id),
           sum(a.weight*coalesce(c.households,0)) hh,
           sum(a.weight*coalesce(e.emp_manu,0)) manu,
           sum(a.weight*(coalesce(e.emp_total,0)-coalesce(e.emp_manu,0))) tert
      FROM canonical.mesh_substation_allocation a
      JOIN lab_data.substation_master m ON m.utility=a.utility AND m.station_id=a.station_id
      LEFT JOIN public_data.census_mesh_1km c ON c.mesh_1km=a.mesh_code
      LEFT JOIN public_data.econ_census_mesh_1km e ON e.mesh_1km=a.mesh_code
      WHERE a.utility='{U}' GROUP BY 1 ORDER BY 1""", ["sid","hh","manu","tert"], ["hh","manu","tert"])
    # E5 tie-break (RERUN_PLAN_R1.md Section 4, rank 3; supervisor decision of 2026-09-15, item 2).
    # A name can carry several master stations, each with its own PV row (14 Kansai names). Keep the
    # station with the largest substation capacity, then the smallest station_id. Colliding names
    # of one key then keep the first name in sorted order, as roster_levels() does. Before, both
    # choices depended on the SQL row order.
    pv = qdf(f"""SELECT coalesce(m.station_name, m.station_id), coalesce(p.pv_total_kw,0)/1000.0,
             coalesce(p.pv_res_kw,0)/1000.0, coalesce(p.pv_com_kw,0)/1000.0,
             coalesce(m.opcap_mva,0), m.station_id
      FROM canonical.substation_pv p JOIN lab_data.substation_master m
        ON m.utility=p.utility AND m.station_id=p.station_id WHERE p.utility='{U}'
      ORDER BY 1, 5 DESC, 6""",
      ["sid","pv_mw","pv_res_mw","pv_com_mw","opcap","msid"], ["pv_mw","pv_res_mw","pv_com_mw","opcap"])
    pv = (pv.sort_values(["sid","opcap","msid"], ascending=[True,False,True], kind="mergesort")
            .drop_duplicates("sid")[["sid","pv_mw","pv_res_mw","pv_com_mw"]])
    c = c.sort_values("sid", kind="mergesort")
    c = c.merge(pv, on="sid", how="left").fillna({"pv_mw":0.0,"pv_res_mw":0.0,"pv_com_mw":0.0})
    c["key"] = c["sid"].map(norm2)
    return c[c.key!=""].drop_duplicates("key").set_index("key")[["hh","manu","tert","pv_mw","pv_res_mw","pv_com_mw"]]

def roster_levels(U):
    """載荷純度規則(TEPCO予算封閉考証由来)で純化した配変の水準 [MW]"""
    r = qdf(f"""SELECT name, coalesce(equip_mw,0) emw, coalesce(opcap_mw,0) omw,
                       coalesce(sec_kv,'') sec FROM canonical.haihen_roster
                WHERE utility='{U}' AND (coalesce(equip_mw,0)>0 OR coalesce(opcap_mw,0)>0)
                ORDER BY 1,2,3,4""",
            ["nm","emw","omw","sec"], ["emw","omw"])
    r["cap"] = r["emw"].where(r["emw"]>0, r["omw"])
    def bad(x):
        s = str(x.sec)
        for v in UPPER_KV:
            if v in s: return True                                   # ①上位(二次側≥66kV)
        if x.cap > 150: return True                                  # ①上位(TEPCO実測配変最大137MW)
        if re.search(r"中間|開閉", str(x.nm)): return True            # ③開閉/中間
        has_dist = bool(re.search(r"6\.6|6kV|3\.3|3kV|低圧|以下", s))
        if re.search(r"22|33", s) and not has_dist: return True      # ②特高spot(EGC高+低の口径外)
        return False
    r = r[~r.apply(bad, axis=1)].copy()
    r["key"] = r["nm"].map(norm2)
    # E5 tie-break (RERUN_PLAN_R1.md Section 4, rank 4): a colliding key keeps the first row after
    # sorting by name and descending capacity, the rule of p0_phantom_lf.py and build_level_v66.py.
    # Before, the row kept depended on the SQL row order.
    r = r.sort_values(["nm","cap"], ascending=[True,False], kind="mergesort")
    r = r[r.key!=""].drop_duplicates("key").set_index("key")
    ROSTER_CAP[U] = r["cap"].copy()
    # v6.6: L = C x lambda_a. Keys in the level file take its level. Engine keys outside list
    # coverage (320 nationally) take the same rule with the engine's own capacity (supervisor
    # decision of 2026-09-15, "Technical decisions for the rerun", item 1).
    lv_all, _ = level_input()
    lv = lv_all[lv_all.utility == U].set_index("key")
    assert lv.index.is_unique, f"{U}: duplicate keys in {LEVEL_FILE.name}"
    missing = sorted(set(lv.index) - set(r.index))
    assert not missing, f"{U}: {len(missing)} level-file keys are not engine keys, e.g. {missing[:5]}"
    lam = lv["lambda"].unique()
    assert len(lam) == 1, f"{U}: lambda_a is not unique in {LEVEL_FILE.name}: {lam}"
    s = lv["level"].reindex(r.index)
    s = s.fillna(r["cap"] * float(lam[0]))
    return s.rename("level")

def pv_profile(U, idx=IDX):
    """区域PV発生(配変下流=可見分) [MW]"""
    g = qdf(f"""SELECT to_char(p.ts,'YYYY-MM-DD HH24:00'),
                       greatest(p.pv_potential_mw - coalesce(c.pv_curtail_mw,0), 0)
                FROM lab_data.pv_regional_gen p
                LEFT JOIN public_data.pv_curtailment_fy2024 c ON c.utility=p.utility AND c.ts=p.ts
                WHERE p.utility='{U}' AND p.ts>='2024-04-01' AND p.ts<'2025-04-01'
                ORDER BY 1""",
            ["ts","mw"], ["mw"])
    s = g.set_index(pd.to_datetime(g["ts"]))["mw"].reindex(idx).fillna(0.0)
    return s * VIS.get(U, 1.0)

def residuals(U):
    """可観測局のKCL残差 R_net(n,t) [MW]·norm2名前空間·LT遮蔽view由来"""
    ln = qdf(f"""SELECT equipment_id, equipment_name, flow_positive_dir,
                        to_char(ts,'YYYY-MM-DD HH24:00'), flow_mw
                 FROM public_data.flow_estimation_input
                 WHERE utility='{U}' AND fiscal_year=2024 AND equipment_type='line'
                 ORDER BY 1, 4""",
             ["eid","nm","dir","ts","mw"], num=["mw"])
    if ln.empty: return pd.DataFrame()
    # E5 (RERUN_PLAN_R1.md Section 4, rank 5): drop_duplicates("eid") and aggfunc="first" pick by
    # row order. Both are inert on the frozen data (0 lines with two names or directions, 0 repeated
    # line-hours), so stop rather than let a future snapshot activate them silently.
    if ln[["eid","nm","dir"]].drop_duplicates().eid.duplicated().any():
        sys.exit(f"[input] {U}: a line carries more than one name or direction")
    if ln.duplicated(["eid","ts"]).any():
        sys.exit(f"[input] {U}: a line has the same hour twice")
    meta = ln[["eid","nm","dir"]].drop_duplicates("eid").set_index("eid")
    wide = ln.pivot_table(index="ts", columns="eid", values="mw", aggfunc="first").fillna(0.0)
    wide.index = pd.to_datetime(wide.index); wide = wide.sort_index()
    din, dout = {}, {}
    if U == "TEPCO":
        # ★A行列v1(2026-07-18): 原始表頭「測定局(変) - 線名」の線名=遠端局を解読した辺表で
        #   全拓扑KCL。R(S)=Σ自局測定線(流入正) − Σ他局測定·遠端=S の線。
        #   同局A/B裁決: 旧z2→新z1でAPE26.5→17.8%·corr0.516→0.640。own_allはfallback。
        # ★暗黙の劣化の禁止(2026-07-28 移植監査): 旧版はこの CSV が無いと黙って own_all へ落ちた。
        #   own_all は上の実証どおり APE 17.8→26.5%·corr 0.640→0.516 と明確に劣化する。TEPCOは
        #   全国の負荷率を標定する基準区域なので、劣化が全10区域へ伝播する。既定では落とす。
        #   意図的に own_all で走らせる実験時のみ DT_ALLOW_TEPCO_OWNALL=1 を明示すること。
        _edges = pathlib.Path(f"{ROOT}/analysis/unified/out/tepco_edges_raw.csv")
        if not _edges.exists() and os.environ.get("DT_ALLOW_TEPCO_OWNALL") != "1":
            sys.exit("[input] 必須入力が不在: analysis/unified/out/tepco_edges_raw.csv\n"
                     "  用途: TEPCO 全拓扑KCL(A行列v1)。欠落時のown_all代替は APE 17.8→26.5%·corr 0.640→0.516 と劣化し、\n"
                     "        TEPCOは全国標定の基準区域のため劣化が10区域へ伝播する。\n"
                     "  → 意図的にown_allで実験する場合のみ DT_ALLOW_TEPCO_OWNALL=1 を明示すること。")
        try:
            ed = pd.read_csv(_edges)
            ed = ed[ed.is_line.astype(str)=="True"].copy()
            ed["eid"] = ed.dirn + "/" + ed.stem + "_line#" + ed.colidx.astype(str)
            ed["meas_key"] = ed.meas.map(norm2)
            for _, r0 in ed.iterrows():
                if r0.eid not in wide.columns: continue
                if GEN_PAT.search(str(r0.raw)) or TIE_PAT.search(str(r0.raw)): continue
                if r0.meas_key: din.setdefault(r0.meas_key, []).append(r0.eid)
                if str(r0.far_hit)=="True" and isinstance(r0.far,str) and r0.far and r0.far != r0.meas_key:
                    dout.setdefault(r0.far, []).append(r0.eid)   # 遠端: −flow=流入
        except FileNotFoundError:
            sys.stderr.write("[warn] tepco_edges_raw.csv 不在 → own_all代替(DT_ALLOW_TEPCO_OWNALL=1 で明示許可済·精度劣化)\n")
            for e in wide.columns:                       # fallback: own_all
                nm = str(meta.at[e,"nm"]) if pd.notna(meta.at[e,"nm"]) else ""
                if GEN_PAT.search(nm) or TIE_PAT.search(nm): continue
                k = norm2(nm)
                if k: din.setdefault(k, []).append(e)
        # R_own(own_all·純粋自局測定) = KNN donor専用の清浄residual
        din_own = {}
        for e in wide.columns:
            nm = str(meta.at[e,"nm"]) if pd.notna(meta.at[e,"nm"]) else ""
            if GEN_PAT.search(nm) or TIE_PAT.search(nm): continue
            k = norm2(nm)
            if k: din_own.setdefault(k, []).append(e)
        R_own = pd.DataFrame({n: sum(wide[e] for e in es) for n, es in din_own.items()})
        R_own = R_own.loc[:, R_own.mean() > 0.5]
    else:
        for e in wide.columns:
            dr = meta.at[e,"dir"]
            if pd.isna(dr) or "→" not in str(dr) or TIE_PAT.search(str(dr)): continue
            a, b = str(dr).split("→")[0], str(dr).split("→")[-1]
            if re.search(r"線(No\.?\d*)?$", b.strip()): continue
            ka, kb = norm2(a), norm2(b)
            if ka and not GEN_PAT.search(a): dout.setdefault(ka, []).append(e)
            if kb and not GEN_PAT.search(b): din.setdefault(kb, []).append(e)
    nodes = sorted(set(din) | set(dout))
    R = pd.DataFrame(0.0, index=wide.index, columns=nodes)
    for n in nodes:
        for e in din.get(n, []):  R[n] += wide[e]
        for e in dout.get(n, []): R[n] -= wide[e]
    mu = R.mean()
    flip = mu < -0.5                                    # 常時負=計器向き反転(物理)
    R.loc[:, flip] = -R.loc[:, flip]
    R = R.loc[:, R.mean() > 0.5]
    R.attrs["far_keys"] = set(dout)
    if U == "TEPCO":
        R.attrs["own_R"] = R_own                        # donor専用の清浄residual(own_all)
    return R

def fit_f(X, Y):
    """時刻ごと横截面NNLS(相対誤差空間·共線爆発防止)"""
    sc = np.maximum(Y.mean(axis=0), 1e-6)
    Xn, Yn = X/sc[:,None], Y/sc
    F = np.empty((X.shape[1], Yn.shape[0]))
    for t in range(Yn.shape[0]):
        F[:,t], _ = nnls(Xn, Yn[t])
    return F

_f_cache = {}
def compute_region(U, blend=True):
    """区域の net/gross/PV を返す。
       returns dict(stations, net(n,T), gross(n,T), pv(n,T), src(n,), R, cov, lev, f_src, covered)"""
    cov = covariates(U)
    lev = roster_levels(U)
    R = residuals(U).reindex(IDX).fillna(0.0)
    obs = [c for c in R.columns if c in cov.index and c in lev.index]
    covered = ((R[obs].abs() > 0.1).mean(axis=1) > 0.5).values if obs else np.zeros(len(IDX), bool)
    # PV配分の特高空間集中補正: 屋根置きres=常に可見·mega solar含むcomは w_com で減衰
    #   w_com は「区域可見PV総量との整合」から解く(leak-free·B表可見率+FIT res/com構造のみ)
    res_t, com_t = float(cov["pv_res_mw"].sum()), float(cov["pv_com_mw"].sum())
    #   目標可見容量 = B表可見率 × 全体。res(屋根置き<50kW)は常に可見 → com側の可見分:
    #   w_com = (VIS×(res+com) − res)/com。特高mega solarの空間集中(高com局)を構造的に控除。
    vis_target = VIS.get(U, 1.0) * (res_t + com_t)
    w_com = min(1.0, max(0.0, (vis_target - res_t)/max(com_t, 1e-6)))
    cov = cov.copy()
    cov["pv_eff_mw"] = cov["pv_res_mw"] + w_com*cov["pv_com_mw"]
    # 集中度阻尼(TEPCO真値標定·転写): mega solarのmesh集中はfeeder実装を過大表現
    #   x=pv/level を x^γ に圧縮(γ<1)·Σは可見総量へ再規格化
    lv_al = lev.reindex(cov.index).fillna(0.0)
    x = (cov["pv_eff_mw"] / lv_al.clip(lower=1e-6)).clip(0, 50)
    damp = lv_al * np.power(x, PV_GAMMA)
    damp[lv_al <= 0] = cov.loc[lv_al <= 0, "pv_eff_mw"]
    cov["pv_eff_mw"] = damp
    gph = (pv_profile(U) / max(float(cov["pv_eff_mw"].sum()), 1e-6)).values   # g(t) per 有効MW
    # 注: pv_profile は可見率適用済 → Σ_n pv_eff×g = 区域可見PV(総量保存·配分重みのみ変更)
    # ── f(t)較正(gross空間·3部門) ──
    # ★容量列の撤去(2026-07-28·先生裁定): 旧版は第4列に設備容量を置き「基底負荷」を担わせていたが、
    #   ①VIFは1.07-1.23で古典的共線性は無し ②非負制約下で容量が世帯の説明力を奪い、世帯係数が
    #   81%の時刻で零に張り付く(0.009kW/世帯=実態の1/30) ③外しても出力は全区域で差0.00%
    #   (TEPCO真値: 水準APE 20.8%不変·波形相関 0.7741不変)。解釈可能性のみ改善するため撤去。
    #   撤去後: 世帯0.097kW/世帯·零張り付き0.6%·寄与 世帯12%/製造58%/三次30%。
    if len(obs) >= 30 and covered.sum() >= 4000:
        X = cov.loc[obs, ["hh","manu","tert"]].values.astype(float)
        Yg = R[obs].values + np.outer(gph, cov.loc[obs, "pv_eff_mw"].values) # R_gross
        Y = Yg[covered]
        F = np.zeros((3, len(IDX)))
        Fc = fit_f(X, Y)
        rel = np.abs((X@Fc).T - Y).mean(axis=0)/np.maximum(Y.mean(axis=0),1e-6)
        mad = np.median(np.abs(rel-np.median(rel)))
        kp = rel <= np.median(rel)+3*1.4826*mad                             # ロバスト外れ値除去
        Fc = fit_f(X[kp], Y[:,kp])
        F[:, covered] = Fc
        f_src = f"自区域({int(kp.sum())}局·覆蓋{covered.mean()*100:.0f}%)"
    else:
        F, f_src = None, "TEPCO fallback"
    _f_cache[U] = (F, covered)
    # ── 全局へ転写 ──
    # ★被覆bug修正(2026-07-18): 座標なし局(master lat無→mesh配分無→covariates無)が全国406局/2.2GWを
    #   静默脱落させていた(東京CBD 620MW=丸の内/銀座級·都心偏差-0.58の真因の一部)。
    #   roster=dedup済金標準を正とし、無共変量局は区域中位共変量でfallback(pvはmesh不明のため0=保守)。
    _fb = [k for k in lev.index if k not in cov.index]
    if _fb:
        _med = cov[["hh","manu","tert"]].median()
        _fbdf = pd.DataFrame({"hh": _med.hh, "manu": _med.manu, "tert": _med.tert,
                              "pv_mw": 0.0, "pv_res_mw": 0.0, "pv_com_mw": 0.0}, index=_fb)
        for _c in cov.columns:
            if _c not in _fbdf.columns: _fbdf[_c] = 0.0
        cov = pd.concat([cov, _fbdf[cov.columns]])
    common = [k for k in lev.index if k in cov.index]
    Xa = cov.loc[common, ["hh","manu","tert"]].values.astype(float)
    pvc = cov.loc[common, "pv_eff_mw"].values
    Ft, cov_t = _f_cache.get("TEPCO", (None, None))
    if Ft is None:
        raise RuntimeError("TEPCO を先に compute_region してください(fallback基底)")
    prof_t = Xa @ Ft
    if F is not None:
        prof = Xa @ F
        if (~covered).any() and covered.any():                              # 未覆蓋はTEPCO形状で接続
            s_own = prof[:, covered].mean(axis=1, keepdims=True)
            s_tep = prof_t[:, covered].mean(axis=1, keepdims=True).clip(min=1e-9)
            prof[:, ~covered] = prof_t[:, ~covered] * (s_own/s_tep)
    else:
        prof = prof_t
    pm = prof.mean(axis=1, keepdims=True)
    ok = (pm[:,0] > 1e-6)
    shape = np.ones_like(prof); shape[ok] = prof[ok]/pm[ok]
    # ── KNN形状転写(TEPCO真値裁決で採用: z2 corr 0.538→0.745·corr≥0.8 6%→39%) ──
    #    ドナー=可観測健全局(R/level∈[0.5,2])のgross実測形状·特徴=部門混合+PV密度·k=5距離加重
    dk, dsh = [], []
    hrs_ = IDX.hour.values
    mid_m = np.isin(hrs_, [11,12,13,14]) & covered
    sho_m = np.isin(hrs_, [9,10,15,16]) & covered
    Rd = R.attrs.get("own_R", R)                        # donor源: TEPCO=own_all清浄版·他=R
    for k in sorted(Rd.columns):                        # E5: donors in sorted key order (tie-break below)
        if k not in cov.index or k not in lev.index: continue
        l0 = float(lev.loc[k]); rm = float(Rd[k].mean())
        if l0 > 0 and 0.5 <= rm/l0 <= 2.0:
            g0 = Rd[k].values + float(cov.at[k,"pv_eff_mw"])*gph
            mg = g0[covered].mean() if covered.any() else g0.mean()
            if mg <= 0.5: continue
            # gross腹部検験: gross需要は正午に深く凹まない(凹む=PV除去不完全な汚染donor)
            if sho_m.any() and g0[sho_m].mean() > 1e-6 and                1 - g0[mid_m].mean()/g0[sho_m].mean() > 0.15: continue   # 重度PV汚染donorのみ排除
            dsh.append(g0/mg); dk.append(k)
    if len(dk) >= 10:
        DS = np.vstack(dsh)
        def _fm(keys):
            c0 = cov.loc[keys]
            return np.column_stack([np.log1p(c0.hh), np.log1p(c0.manu), np.log1p(c0.tert),
                (c0.pv_mw/np.maximum(lev.loc[keys].values/0.4, 1e-6)).clip(0,3)])
        FD = _fm(dk); mu_, sd_ = FD.mean(0), FD.std(0)+1e-9
        FDn = (FD-mu_)/sd_; FT = (_fm(common)-mu_)/sd_
        for i in range(len(common)):
            d2 = ((FDn-FT[i])**2).sum(1)
            # E5 (RERUN_PLAN_R1.md Section 4, rank 6): argpartition is not a stable selection, and
            # keys without a mesh allocation share covariates, so exact distance ties occur. Rank by
            # distance, then by position in the sorted donor list. Same five donors unless tied.
            nn = np.lexsort((np.arange(len(dk)), d2))[:5]
            w = 1/(np.sqrt(d2[nn])+0.1); w /= w.sum()
            ks = (DS[nn]*w[:,None]).sum(0)
            if (~covered).any() and covered.any():
                # 未覆蓋時間帯はdonor形状が欠測→部門曲線形状で接続(平均比合わせ)
                s_prev = shape[i]
                sc = ks[covered].mean()/max(s_prev[covered].mean(), 1e-9)
                ks = ks.copy(); ks[~covered] = s_prev[~covered]*sc
            m_ = ks.mean()
            if m_ > 1e-9: shape[i] = ks/m_
    lev_gross = lev.loc[common].values + pvc*gph.mean()
    PVmat = np.outer(pvc, gph)
    gross = shape * lev_gross[:,None]
    net = gross - PVmat
    # E3, option (iv), ruled 2026-09-15 (ACCEPTANCE_CRITERIA_R1.md, change 2): the Tokyo residual
    # corrections (12 monthly factors and 24 x 4 hour-by-season factors, fitted on Tokyo ground
    # truth and applied to Tokyo class 3 only) are removed from the estimator, so one rule serves
    # all ten areas. The per-area monthly_factor_dd.json branch is removed too, so that no future
    # file can switch a single-area correction back on. monthly_factor_tepco.json and
    # hourshape_factor_tepco.json stay in out/ as v6.5 records, for the cost-of-E3 comparison only.
    src = np.array(["z2"]*len(common), dtype=object)
    if blend:
        for i, k in enumerate(common):
            if k in R.columns:
                l = float(lev.loc[k]); rm = float(R[k].mean())
                if l <= 0 or rm <= 0.5: continue
                q = rm/l
                if Z1_GATE[0] <= q <= Z1_GATE[1]:
                    net[i] = R[k].values
                    gross[i] = net[i] + PVmat[i]
                    src[i] = "z1"
                # Criterion F (ACCEPTANCE_CRITERIA_R1.md, "Outcome of criterion F", 2026-09-15): the
                # measured shape of transit-dominated balances (1.4 < q <= 4, formerly Class 2, "z1s")
                # never beat the transferred shape on calibration-area ground truth, so by the rule
                # fixed in advance Class 2 is merged into Class 3. Every key outside the Class 1
                # interval keeps the transferred shape built above ("z2").
    return dict(stations=common, net=net, gross=gross, pv=PVmat, src=src,
                R=R, cov=cov, lev=lev, f_src=f_src, covered=covered)
