#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WLS本装 v2 (Paper A・paper分支専用)。docs/WLS_PREREGISTRATION.md の定式化を実装。

隔離: stage2_engine.py は import するのみ(不変更)。出力は独立表
      lab_data.estimated_demand_fy2024_wls（v5/v5R/release.v63 に触れない）。
解: Kalman形 K = P A'(A P A' + Rm)^-1 を区域ごとに一度だけ計算し、8760時刻へ適用。
    diag(P_post) が原則的な局別不確実性（論文の主眼）。
使い方: python wls_v2.py TEPCO [KANSAI ...]        (引数なし=全10区域)
"""
import io, json, os, pathlib, subprocess, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
# 移植(PaperA_workspace): エンジンは workspace 内の凍結コピー、DBは環境変数で明示(既定値なし=fail-closed)
WS   = str(pathlib.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/wls"
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import compute_region, IDX, norm2, ROOT, REGIONS as _ALL
DB_CONTAINER = os.environ.get("DT_DB_CONTAINER") or sys.exit("[FATAL] DT_DB_CONTAINER 必須(例: iwafune_db_frozen)")

REGS = [a.upper() for a in sys.argv[1:]] or _ALL
SIG_REL_FLOOR = 0.10       # σ_min = 0.10 * mean|z|      (預登録·掃引しない)
KAPPA         = 1.0        # σ = κ * |unexplained mean|   (預登録)
PRIOR_CV      = 0.20       # 事前の局別水準離散(TEPCO実測)
SCRATCH = f"{WS}/scratch"
os.makedirs(SCRATCH, exist_ok=True); os.makedirs(HERE, exist_ok=True)

def psql(sql):
    p = subprocess.run(["docker","exec","-i",DB_CONTAINER,"psql","-U","postgres","-d","lab_database","-tAc",sql],
                       capture_output=True)
    if p.returncode: print("SQL ERR:", p.stderr.decode("utf-8","replace")[:400]); sys.exit(1)
    return p.stdout.decode("utf-8","replace").strip()

def build_A(stations, Rcols, edges, idx_of):
    """A[m, j]: 測定 m が局 j の需要を含むか。自局=1、遠端解決済の下流=1。"""
    M, N = len(Rcols), len(stations)
    A = np.zeros((M, N))
    down = {}
    if edges is not None:
        el = edges[edges.is_line.astype(str) == "True"]
        for _, r in el.iterrows():
            mk = norm2(str(r.meas)) if pd.notna(r.meas) else ""
            fk = str(r.far) if (str(r.far_hit) == "True" and isinstance(r.far, str)) else ""
            if mk and fk and mk != fk:
                down.setdefault(mk, set()).add(fk)
    n_down = 0
    for m, k in enumerate(Rcols):
        if k in idx_of: A[m, idx_of[k]] = 1.0
        for j in down.get(k, ()):
            if j in idx_of and j != k:
                A[m, idx_of[j]] = 1.0; n_down += 1
    return A, n_down

print(f"[WLS v2] regions={REGS}", flush=True)
summary = []
for U in REGS:
    print(f"\n=== {U} ===", flush=True)
    r = compute_region(U, blend=True)                    # v6.3の水準×形状=事前分布
    stations, lev = r["stations"], r["lev"]
    x0 = r["net"]                                        # (N, 8760) 事前平均
    N = len(stations); idx_of = {k: i for i, k in enumerate(stations)}
    R = r["R"]
    if R is None or R.shape[1] == 0:
        print("  測定なし→skip"); continue
    Rcols = [c for c in R.columns]
    Z = R[Rcols].values.T                                # (M, 8760)
    try:
        edges = pd.read_csv(f"{ROOT}/analysis/unified/out/tepco_edges_raw.csv") if U == "TEPCO" else None
    except FileNotFoundError:
        edges = None
    A, n_down = build_A(stations, Rcols, edges, idx_of)
    keep = A.sum(axis=1) > 0                             # 局空間に写像できた測定のみ
    A, Z, Rcols = A[keep], Z[keep], [c for c, k in zip(Rcols, keep) if k]
    M = A.shape[0]
    print(f"  局 N={N}  測定 M={M} (下流結合 {n_down})", flush=True)

    lv = np.array([float(lev.get(k, np.nan)) for k in stations])
    lv = np.where(np.isfinite(lv) & (lv > 0.05), lv, np.nanmedian(lv[np.isfinite(lv)]))
    P = (PRIOR_CV * lv) ** 2                             # 事前分散(対角)
    Ax0 = A @ x0                                         # (M, 8760)
    unexp = np.abs(Z.mean(axis=1) - Ax0.mean(axis=1))    # 事前で説明できない平均残差
    zbar = np.abs(Z).mean(axis=1)
    sig = np.maximum(SIG_REL_FLOOR * np.maximum(zbar, 1e-3), KAPPA * unexp)
    Rm = sig ** 2

    # K = P A' (A P A' + Rm)^-1     … (M×M) 一回の解法
    PAt = A.T * P[:, None]                               # (N, M) = P A'
    S = A @ PAt + np.diag(Rm)                            # (M, M)
    K = np.linalg.solve(S.T, PAt.T).T                    # (N, M)
    innov = Z - Ax0                                      # (M, 8760)
    xh = x0 + K @ innov
    Ppost = P - np.einsum("nm,mn->n", K, A * P[None, :])  # diag(P - K A P)
    Ppost = np.clip(Ppost, 1e-6, None)
    sd = np.sqrt(Ppost)

    # 非負制約(需要は非負·PVはgrossで別管理) と gross再構成
    xh = np.maximum(xh, 0.0)
    PV = r["pv"]; gross = xh + PV
    print(f"  Σnet {x0.mean(axis=1).sum():.0f} → {xh.mean(axis=1).sum():.0f} MW"
          f" / 不確実性: sd/level 中央 {np.median(sd/np.maximum(lv,1e-6)):.3f}"
          f" (事前 {PRIOR_CV})", flush=True)

    # ── 独立表へ書込(v5/v5Rに触れない) ──
    psql("""CREATE TABLE IF NOT EXISTS lab_data.estimated_demand_fy2024_wls(
        run_id text, utility text, station_id text, ts timestamp,
        demand_net_mw double precision, demand_gross_mw double precision,
        pv_mw double precision, sd_mw double precision, src text)""")
    RID = f"wls_fy2024_{U.lower()}"
    psql(f"DELETE FROM lab_data.estimated_demand_fy2024_wls WHERE utility='{U}'")
    path = f"{SCRATCH}/wls_{U}.csv"
    if os.path.exists(path): os.remove(path)
    CH = 150
    for i0 in range(0, N, CH):
        i1 = min(i0 + CH, N); k = i1 - i0
        df = pd.DataFrame({
            "run_id": RID, "utility": U,
            "station_id": np.repeat(stations[i0:i1], len(IDX)),
            "ts": np.tile(IDX.strftime("%Y-%m-%d %H:%M:%S").values, k),
            "demand_net_mw": np.round(xh[i0:i1].ravel(), 3),
            "demand_gross_mw": np.round(gross[i0:i1].ravel(), 3),
            "pv_mw": np.round(PV[i0:i1].ravel(), 3),
            "sd_mw": np.round(np.repeat(sd[i0:i1], len(IDX)), 4),
            "src": np.repeat(r["src"][i0:i1], len(IDX))})
        df.to_csv(path, mode="a", header=False, index=False)
    with open(path, "rb") as fh:
        p = subprocess.run(["docker","exec","-i",DB_CONTAINER,"psql","-U","postgres","-d","lab_database",
            "-c","COPY lab_data.estimated_demand_fy2024_wls FROM STDIN WITH CSV"], stdin=fh, capture_output=True)
    if p.returncode: print("  COPY ERR:", p.stderr.decode("utf-8","replace")[:300]); sys.exit(1)
    os.remove(path)
    summary.append(dict(utility=U, n=N, m=M, net_prior=round(float(x0.mean(axis=1).sum())),
                        net_wls=round(float(xh.mean(axis=1).sum())),
                        sd_rel_med=round(float(np.median(sd/np.maximum(lv,1e-6))), 4)))
    np.save(f"{HERE}/wls_sd_{U}.npy", sd)
    pd.Series(stations).to_csv(f"{HERE}/wls_keys_{U}.csv", index=False, header=False, encoding="utf-8-sig")

pd.DataFrame(summary).to_csv(f"{HERE}/wls_summary.csv", index=False, encoding="utf-8-sig")
print("\n[出力] lab_data.estimated_demand_fy2024_wls / wls_summary.csv / wls_sd_*.npy")
