#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WLS 実験2: 片側更新 (docs/WLS_PREREGISTRATION.md §5)。自由パラメータ追加なし。

min_x || min(z - A x, 0) ||_W^2 + || x - x0 ||_P^-1^2
  = 未建模通過潮流 u>=0 を消去した形。活性集合(負残差)反復で解く。
出力: lab_data.estimated_demand_fy2024_wls (run_id=wls3_*) ·sd は活性測定のみの事後共分散。
"""
import os, pathlib, subprocess, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
# 移植(PaperA_workspace): エンジンは workspace 内の凍結コピー、DBは環境変数で明示
WS   = str(pathlib.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/wls"
sys.path.insert(0, f"{MAIN}/analysis/unified")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from stage2_engine import compute_region, IDX, norm2, ROOT, REGIONS as _ALL
from wls_v2 import build_A, SIG_REL_FLOOR, KAPPA, PRIOR_CV, SCRATCH, DB_CONTAINER   # 定数は実験1と同一

REGS = [a.upper() for a in sys.argv[1:]] or ["TEPCO","KANSAI"]
NITER = 8

def psql(sql):
    p = subprocess.run(["docker","exec","-i",DB_CONTAINER,"psql","-U","postgres","-d","lab_database","-tAc",sql],
                       capture_output=True)
    if p.returncode: print("SQL ERR:", p.stderr.decode("utf-8","replace")[:400]); sys.exit(1)
    return p.stdout.decode("utf-8","replace").strip()

for U in REGS:
    print(f"\n=== {U} (片側WLS) ===", flush=True)
    r = compute_region(U, blend=True)
    stations, lev, x0, PV = r["stations"], r["lev"], r["net"], r["pv"]
    N = len(stations); idx_of = {k: i for i, k in enumerate(stations)}
    R = r["R"]
    if R is None or R.shape[1] == 0: print("  測定なし→skip"); continue
    Rcols = list(R.columns); Z = R[Rcols].values.T
    edges = pd.read_csv(f"{ROOT}/analysis/unified/out/tepco_edges_raw.csv") if U == "TEPCO" else None
    A, n_down = build_A(stations, Rcols, edges, idx_of)
    keep = A.sum(axis=1) > 0
    A, Z = A[keep], Z[keep]
    M = A.shape[0]
    lv = np.array([float(lev.get(k, np.nan)) for k in stations])
    lv = np.where(np.isfinite(lv) & (lv > 0.05), lv, np.nanmedian(lv[np.isfinite(lv)]))
    P = (PRIOR_CV * lv) ** 2
    Ax0 = A @ x0
    unexp = np.abs(Z.mean(axis=1) - Ax0.mean(axis=1))
    zbar = np.abs(Z).mean(axis=1)
    sig = np.maximum(SIG_REL_FLOOR * np.maximum(zbar, 1e-3), KAPPA * unexp)
    Rm = sig ** 2
    print(f"  N={N} M={M} 下流結合={n_down}", flush=True)

    # ── 活性集合反復(時刻ごと·ただし活性集合はブロックで共有し高速化) ──
    T = x0.shape[1]
    xh = x0.copy()
    act_count = np.zeros(M)
    for it in range(NITER):
        resid = Z - A @ xh                        # (M, T)
        act = resid < 0                           # 負残差=情報を持つ測定
        act_count = act.mean(axis=1)
        # 時刻ごとの活性集合が異なるため、活性率で測定を分類し、共通活性集合ごとに一括解法
        # 実装簡略化: 活性率>=0.5 の測定を常時活性、それ以外は不活性とみなす(片側の期待値近似)
        sel = act_count >= 0.5
        if sel.sum() == 0: break
        As, Rs = A[sel], Rm[sel]
        PAt = As.T * P[:, None]
        S = As @ PAt + np.diag(Rs)
        K = np.linalg.solve(S.T, PAt.T).T
        xh_new = x0 + K @ (Z[sel] - As @ x0)
        xh_new = np.maximum(xh_new, 0.0)
        d = np.max(np.abs(xh_new - xh))
        xh = xh_new
        print(f"   iter{it}: 活性測定 {int(sel.sum())}/{M}  Δmax={d:.3f}", flush=True)
        if d < 1e-3: break
    Ppost = P - np.einsum("nm,mn->n", K, As * P[None, :])
    sd = np.sqrt(np.clip(Ppost, 1e-6, None))
    gross = xh + PV
    print(f"  Σnet {x0.mean(axis=1).sum():.0f} → {xh.mean(axis=1).sum():.0f} MW"
          f" / sd/level 中央 {np.median(sd/np.maximum(lv,1e-6)):.3f}", flush=True)

    RID = f"wls3_fy2024_{U.lower()}"
    psql(f"DELETE FROM lab_data.estimated_demand_fy2024_wls WHERE utility='{U}' AND run_id LIKE 'wls3_%'")
    path = f"{SCRATCH}/wls3_{U}.csv"
    if os.path.exists(path): os.remove(path)
    for i0 in range(0, N, 150):
        i1 = min(i0+150, N); k = i1 - i0
        pd.DataFrame({
            "run_id": RID, "utility": U,
            "station_id": np.repeat(stations[i0:i1], len(IDX)),
            "ts": np.tile(IDX.strftime("%Y-%m-%d %H:%M:%S").values, k),
            "demand_net_mw": np.round(xh[i0:i1].ravel(), 3),
            "demand_gross_mw": np.round(gross[i0:i1].ravel(), 3),
            "pv_mw": np.round(PV[i0:i1].ravel(), 3),
            "sd_mw": np.round(np.repeat(sd[i0:i1], len(IDX)), 4),
            "src": np.repeat(r["src"][i0:i1], len(IDX))}).to_csv(path, mode="a", header=False, index=False)
    with open(path, "rb") as fh:
        p = subprocess.run(["docker","exec","-i",DB_CONTAINER,"psql","-U","postgres","-d","lab_database",
            "-c","COPY lab_data.estimated_demand_fy2024_wls FROM STDIN WITH CSV"], stdin=fh, capture_output=True)
    if p.returncode: print("  COPY ERR:", p.stderr.decode("utf-8","replace")[:300]); sys.exit(1)
    os.remove(path)
    np.save(f"{HERE}/wls3_sd_{U}.npy", sd)
    pd.Series(stations).to_csv(f"{HERE}/wls3_keys_{U}.csv", index=False, header=False, encoding="utf-8-sig")
print("\n[出力] run_id=wls3_* / wls3_sd_*.npy")
