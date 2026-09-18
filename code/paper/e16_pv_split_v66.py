#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E16 (R1-M7): validation of the PV split on the canonical evaluation set (1,216 Tokyo).

(a) Reverse-flow share by month, estimated against measured, on the same substations. The
    definition is the canonical saturation audit (recompute_all_clean.py part D): a substation
    reverses when the 5th percentile of its daytime (09-15 h) net load is <= 0, over the hours
    where truth and estimate both exist. The annual row must reproduce the canonical 20.6 %
    against 28.1 % (asserted). Also the pooled share of station-hours with net load < 0.
(b) Net-load bias by hour and season: per substation (mean_est - mean_true) in the cell,
    divided by the annual true mean, then the median over substations; and the shape-only bias
    (mean_est / annual mean_est - mean_true / annual mean_true), which removes the level error
    and isolates the diurnal and seasonal pattern, where the PV term acts.
(c) Regression of measured net load on the allocated behind-the-meter PV v_i(t): within each
    substation, net load and v_i are demeaned inside month x hour cells over the hours with
    v_i > 0, and beta_i = sum(v~ y~) / sum(v~^2). The day-to-day variation of v_i within a cell
    is irradiance, so beta is the response of net load to PV output; a correctly scaled v_i gives
    beta close to -1. Weather-driven gross load (cooling on sunny days) biases beta towards 0.
    The same fit on the estimate's own net load is the reference for what the estimator implies.

Inputs: offline estimate (net, PV) and Tokyo truth; results/micro/{TAG}_micro_clean.csv and
{TAG}_clean_all.json (for the assertion).
Outputs: results/micro/e16_reverse_monthly_{TAG}.csv, e16_bias_hour_season_{TAG}.csv,
e16_pv_beta_{TAG}.csv (per class), e16_pv_beta_station_{TAG}.csv.
"""
import sys, json
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E16 PV split")
pop = io.population()
keys = list(pop.key)
T = io.tokyo_truth(keys)
e = io.est_long("TEPCO", ("demand_net_mw", "pv_mw"))
E = io.est_wide(e, keys, "demand_net_mw")
PV = io.est_wide(e, keys, "pv_mw")
io.check_population(pop, T, E)
V = np.isfinite(T) & np.isfinite(E)
src = pop.src.values
n = len(keys)

# ── (a) reverse-flow share ──
def p5(X, sel):
    out = np.full(n, np.nan)
    for j in range(n):
        s = sel & V[:, j]
        if s.sum() >= 100:
            out[j] = np.percentile(X[s, j], 5)
    return out
rows = []
ann_t, ann_e = p5(T, io.DAY), p5(E, io.DAY)
ref = json.loads((io.MICRO_IN / f"{io.TAG}_clean_all.json").read_text(encoding="utf-8"))["saturation"]
assert round(100 * np.nanmean(ann_t <= 0), 1) == ref["truth_pct"] and round(100 * np.nanmean(ann_e <= 0), 1) == ref["est_pct"], \
    "annual reverse-flow shares do not reproduce the canonical saturation audit"
for m in ["annual"] + io.MONTHS:
    if m == "annual":
        t5, e5, sel = ann_t, ann_e, io.DAY
    else:
        sel = io.DAY & (io.MO == m)
        t5, e5 = p5(T, sel), p5(E, sel)
    for c in ["all"] + io.CLASSES:
        k = np.isfinite(t5) & np.isfinite(e5) & ((src == c) if c != "all" else True)
        Vs = V & sel[:, None] & (((src == c) if c != "all" else np.ones(n, bool))[None, :])
        rows.append(dict(month=m, cls=c, n=int(k.sum()),
                         share_true=100 * float(np.mean(t5[k] <= 0)), share_est=100 * float(np.mean(e5[k] <= 0)),
                         both=int(((t5[k] <= 0) & (e5[k] <= 0)).sum()),
                         hours_neg_true=100 * float((T[Vs] < 0).mean()), hours_neg_est=100 * float((E[Vs] < 0).mean())))
rev = pd.DataFrame(rows)
rev.to_csv(io.out("micro", f"e16_reverse_monthly_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# ── (b) bias by hour and season ──
Tz, Ez = np.where(V, T, 0.0), np.where(V, E, 0.0)
mt_a = Tz.sum(0) / V.sum(0); me_a = Ez.sum(0) / V.sum(0)
brow = []
for s in ["MAM", "JJA", "SON", "DJF"]:
    for h in range(24):
        sel = (io.SEASON == s) & (io.HOUR == h)
        cnt = V[sel].sum(0)
        mt = np.where(cnt > 0, Tz[sel].sum(0) / np.maximum(cnt, 1), np.nan)
        me = np.where(cnt > 0, Ez[sel].sum(0) / np.maximum(cnt, 1), np.nan)
        b = 100 * (me - mt) / mt_a
        sh = 100 * (me / me_a - mt / mt_a)
        for c in ["all"] + io.CLASSES:
            k = np.isfinite(b) & ((src == c) if c != "all" else True)
            brow.append(dict(season=s, hour=h, cls=c, n=int(k.sum()),
                             bias_med=float(np.median(b[k])), bias_q25=float(np.percentile(b[k], 25)),
                             bias_q75=float(np.percentile(b[k], 75)),
                             shape_bias_med=float(np.median(sh[k])), shape_q25=float(np.percentile(sh[k], 25)),
                             shape_q75=float(np.percentile(sh[k], 75))))
bias = pd.DataFrame(brow)
bias.to_csv(io.out("micro", f"e16_bias_hour_season_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# ── (c) beta of net load on v_i ──
cellid = (pd.Series(io.MO).map({m: i for i, m in enumerate(io.MONTHS)}).values * 24 + io.HOUR).astype(int)
def beta(y, v, sel):
    c = cellid[sel]; y = y[sel]; v = v[sel]
    cnt = np.bincount(c, minlength=288)
    ym = np.bincount(c, y, 288) / np.maximum(cnt, 1); vm = np.bincount(c, v, 288) / np.maximum(cnt, 1)
    yt, vt = y - ym[c], v - vm[c]
    sv = float((vt ** 2).sum())
    return (float((vt * yt).sum()) / sv if sv > 1e-9 else np.nan), float((vt * yt).sum()), sv
st = []
for j, k in enumerate(keys):
    sel = V[:, j] & (PV[:, j] > 0)
    if sel.sum() < 500 or np.nanmax(PV[:, j]) < 0.05:
        st.append(dict(key=k, src=src[j], n_hours=int(sel.sum()), pv_mean=float(np.nanmean(PV[:, j])),
                       beta_true=np.nan, beta_est=np.nan, sxy_t=0.0, sxy_e=0.0, sxx=0.0)); continue
    bt, sxy_t, sxx = beta(T[:, j], PV[:, j], sel)
    be, sxy_e, _ = beta(E[:, j], PV[:, j], sel)
    st.append(dict(key=k, src=src[j], n_hours=int(sel.sum()), pv_mean=float(np.nanmean(PV[:, j])),
                   beta_true=bt, beta_est=be, sxy_t=sxy_t, sxy_e=sxy_e, sxx=sxx))
st = pd.DataFrame(st)
st.to_csv(io.out("micro", f"e16_pv_beta_station_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
brs = []
for c in ["all"] + io.CLASSES:
    g = st[st.beta_true.notna() & ((st.src == c) if c != "all" else True)]
    brs.append(dict(cls=c, n=len(g),
                    beta_true_med=float(g.beta_true.median()), beta_true_q25=float(g.beta_true.quantile(.25)),
                    beta_true_q75=float(g.beta_true.quantile(.75)), beta_true_pooled=float(g.sxy_t.sum() / g.sxx.sum()),
                    share_true_in_m15_m05=100 * float(g.beta_true.between(-1.5, -0.5).mean()),
                    beta_est_med=float(g.beta_est.median()), beta_est_pooled=float(g.sxy_e.sum() / g.sxx.sum())))
br = pd.DataFrame(brs)
br.to_csv(io.out("micro", f"e16_pv_beta_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

pd.set_option("display.width", 220)
print(rev[rev.cls == "all"].round(1).to_string(index=False))
piv = bias[bias.cls == "all"].pivot(index="hour", columns="season", values="bias_med").round(1)
print("median net-load bias, % of annual true mean (all classes)\n", piv.to_string())
print(bias[bias.cls == "all"].pivot(index="hour", columns="season", values="shape_bias_med").round(1).to_string())
print(br.round(3).to_string(index=False))
print(f"[output] e16_reverse_monthly_{io.TAG}.csv, e16_bias_hour_season_{io.TAG}.csv, e16_pv_beta_{io.TAG}.csv, "
      f"e16_pv_beta_station_{io.TAG}.csv")
