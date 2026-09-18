#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E9 (R2-M1, R1-M10): substation-level validity of the level, against capacity alone.

On the canonical evaluation set (1,216 Tokyo substations in v6.5) the annual level error is
the log ratio ln(estimate / ground truth) of the annual means, taken from the canonical
{TAG}_micro_clean.csv (me, mt over the hours where both exist). For each class x capacity
tercile the table gives
  bias  = median log ratio,  rSD = 1.4826 x MAD of the log ratio,  within20 = share |ratio-1| <= 0.2
for the estimate and for the capacity x constant baseline L0_i = C_i x c, where C_i is the
capacity the engine allocates by (station_levels_v66.csv) and c is the anchor of the estimate
being scored (v6.5: 0.4058, v6.6: 0.3501). rSD does not depend on c; bias does. Paired
bootstrap intervals (stations resampled, seed fixed) are given for rSD(model) - rSD(baseline).

Also the correlations R2 reported (log level 0.68, load factor 0.12, class 3 0.10):
  r(ln me, ln mt) and r(ln me/C, ln mt/C) with C the canonical capacity of micro_clean,
plus the Pearson r of the linear load factors, Spearman, and the SD of the estimated load
factor (in v6.6 it is constant by construction for classes 2 and 3, which makes r undefined
or meaningless there: the SD column shows it).

Needs no hourly data. Inputs: results/micro/{TAG}_micro_clean.csv,
results/numbers/station_levels_v66.csv, results/numbers/level_model_v66.json.
Outputs: results/micro/e9_level_skill_{TAG}.csv, e9_level_corr_{TAG}.csv,
e9_station_{TAG}.csv (for the figure), results/numbers/e9_level_skill_{TAG}_rows.tex.
"""
import sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

io.banner("E9")
rng = np.random.default_rng(20260915)
pop = io.population()
cap = io.engine_capacity()
cap = cap[cap.utility == "TEPCO"].set_index("key")["cap"]
c0 = io.anchor_constant()
d = pop.copy()
d["cap_eng"] = d.key.map(cap)
n_nocap = int(d.cap_eng.isna().sum())
d["cap_eng"] = d.cap_eng.fillna(d.cap)            # stations outside the level file keep the canonical capacity
d["lr_model"] = np.log(d.me / d.mt)
d["lr_base"] = np.log(c0 * d.cap_eng / d.mt)
d["lf_true"] = d.mt / d.cap
d["lf_est"] = d.me / d.cap
edges = np.quantile(d.cap, [0, 1/3, 2/3, 1])
d["tercile"] = pd.cut(d.cap, edges, labels=["T1", "T2", "T3"], include_lowest=True).astype(str)
print(f"  {len(d)} stations; anchor c = {c0}; capacity tercile edges {np.round(edges, 1).tolist()} MW; "
      f"{n_nocap} without an engine capacity")

def cell(g):
    lm, lb = g.lr_model.values, g.lr_base.values
    n = len(g)
    ci = io.boot_ci(lambda i: io.rsd(lm[i]) - io.rsd(lb[i]), n, rng, n=1000) if n >= 10 else [np.nan, np.nan]
    return dict(n=n,
                bias_model=float(np.median(lm)), rsd_model=io.rsd(lm),
                within20_model=100 * float(np.mean(np.abs(np.exp(lm) - 1) <= 0.2)),
                bias_base=float(np.median(lb)), rsd_base=io.rsd(lb),
                within20_base=100 * float(np.mean(np.abs(np.exp(lb) - 1) <= 0.2)),
                d_rsd=io.rsd(lm) - io.rsd(lb), d_rsd_lo=ci[0], d_rsd_hi=ci[1])

rows = []
for cls in io.CLASSES + ["all"]:
    gc = d if cls == "all" else d[d.src == cls]
    for ter in ["T1", "T2", "T3", "all"]:
        g = gc if ter == "all" else gc[gc.tercile == ter]
        if len(g):
            rows.append(dict(cls=cls, tercile=ter, **cell(g)))
tab = pd.DataFrame(rows)
tab.insert(2, "cap_lo", tab.tercile.map({"T1": edges[0], "T2": edges[1], "T3": edges[2], "all": edges[0]}))
tab.insert(3, "cap_hi", tab.tercile.map({"T1": edges[1], "T2": edges[2], "T3": edges[3], "all": edges[3]}))
tab.to_csv(io.out("micro", f"e9_level_skill_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# E18 (minimum version, editor's ruling of round 2): the distribution of the level error by class
# and capacity band, in the calibration area only. Reported as the ratio estimate / ground truth,
# so a reader can see the spread rather than a single median. These quantiles describe the
# calibration area; the paper states that they do not transfer.
QS = [10, 25, 50, 75, 90]
qrows = []
for cls in io.CLASSES + ["all"]:
    gc = d if cls == "all" else d[d.src == cls]
    for ter in ["T1", "T2", "T3", "all"]:
        g = gc if ter == "all" else gc[gc.tercile == ter]
        if len(g) >= 10:
            v = np.percentile(g.lr_model.values, QS)
            qrows.append(dict(cls=cls, tercile=ter, n=len(g),
                              **{f"ratio_p{q}": float(np.exp(x)) for q, x in zip(QS, v)}))
qt = pd.DataFrame(qrows)
qt.to_csv(io.out("micro", f"e9_level_quantiles_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
qtex = []
for r in qt.itertuples():
    rng_txt = "all" if r.tercile == "all" else (
        f"{tab[(tab.cls == r.cls) & (tab.tercile == r.tercile)].cap_lo.iloc[0]:.0f}--"
        f"{tab[(tab.cls == r.cls) & (tab.tercile == r.tercile)].cap_hi.iloc[0]:.0f}")
    qtex.append(f"{io.CLASS_NAME[r.cls]} & {rng_txt} & {r.n} & {r.ratio_p10:.2f} & {r.ratio_p25:.2f} & "
                f"{r.ratio_p50:.2f} & {r.ratio_p75:.2f} & {r.ratio_p90:.2f}" + chr(92)*2)
io.out("numbers", f"e9_level_quantiles_{io.TAG}_rows.tex").write_text(chr(10).join(qtex) + chr(10), encoding="utf-8")
print(f"[out] e9_level_quantiles_{io.TAG}.csv")

def corr(g):
    from scipy.stats import spearmanr
    ok = (g.me > 0) & (g.mt > 0)
    g = g[ok]
    sd = float(g.lf_est.std(ddof=1))
    # In v6.6 the class 2 and 3 load factor is lambda by construction; what varies is only the
    # masking of hours without truth (SD about 1e-4). A correlation on that is noise: NaN below 1e-3.
    live = sd > 1e-3
    r_lf = float(np.corrcoef(g.lf_est, g.lf_true)[0, 1]) if live else np.nan
    return dict(n=len(g), n_nonpos=int((~ok).sum()),
                r_log_level=float(np.corrcoef(np.log(g.me), np.log(g.mt))[0, 1]),
                r_log_lf=float(np.corrcoef(np.log(g.lf_est), np.log(g.lf_true))[0, 1]) if live else np.nan,
                r_lf=r_lf, rho_lf=float(spearmanr(g.lf_est, g.lf_true)[0]) if live else np.nan,
                sd_lf_est=sd, sd_lf_true=float(g.lf_true.std(ddof=1)),
                r_log_level_base=float(np.corrcoef(np.log(c0 * g.cap_eng), np.log(g.mt))[0, 1]))
cr = pd.DataFrame([dict(cls=c, **corr(d if c == "all" else d[d.src == c])) for c in ["all"] + io.CLASSES])
cr.to_csv(io.out("micro", f"e9_level_corr_{io.TAG}.csv"), index=False, encoding="utf-8-sig")
d[["key", "src", "cap", "cap_eng", "mt", "me", "lf_true", "lf_est", "lr_model", "lr_base", "tercile"]].to_csv(
    io.out("micro", f"e9_station_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

# LaTeX rows: class x tercile, estimate against capacity x constant (appendix or main table)
tex = []
for r in tab.itertuples():
    rng_txt = "all" if r.tercile == "all" else f"{r.cap_lo:.0f}--{r.cap_hi:.0f}"
    tex.append(f"{io.CLASS_NAME[r.cls]} & {rng_txt} & {r.n} & {r.bias_model:+.2f} & {r.rsd_model:.2f} & "
               f"{r.within20_model:.0f} & {r.bias_base:+.2f} & {r.rsd_base:.2f} & {r.within20_base:.0f} & "
               f"{r.d_rsd:+.2f} [{r.d_rsd_lo:+.2f}, {r.d_rsd_hi:+.2f}]\\\\")
io.out("numbers", f"e9_level_skill_{io.TAG}_rows.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")

pd.set_option("display.width", 200)
print(tab.round(3).to_string(index=False))
print(cr.round(3).to_string(index=False))
print(f"[output] e9_level_skill_{io.TAG}.csv, e9_level_corr_{io.TAG}.csv, e9_station_{io.TAG}.csv, "
      f"e9_level_skill_{io.TAG}_rows.tex")
