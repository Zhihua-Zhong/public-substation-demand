#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E10 (R1-M3b, R2-M1.4): substation-level shape accuracy in the nine transfer areas.

Evaluation only. The partial ground truth of the nine areas (validation.flow_lt_truth, the
view that puts Kyushu's January to March rows in FY2024) is read here to score estimates that
already exist; it is on the deny-list of the estimator's query guard and never reaches it.

Partial truth covers some of a substation's banks, so it carries shape but not level. Each
series is therefore divided by its own mean over the hours where truth and estimate both
exist, and the table reports per area x class
  r         hourly Pearson correlation (scale-free),
  shape CV  100 x RMSE(e / mean e - t / mean t), the CV-RMSE of the normalised shapes,
with n, the number whose truth is flagged complete (validation.truth_completeness), and the
same statistics without the series flagged by partial_truth_flag.py rule dm (>= 20 % negative
hours: generation or reverse flow dominates the recorded series). A Tokyo reference row uses the
same shape metric on the canonical 1,216.

Truth side, as gen_val_daily_fy2024.py builds it: bank flows summed by norm2(equipment_name),
physically impossible spikes masked by its mask_outliers rule; plus the CLAUDE.md purification
(names containing 中間 or 開閉 belong to the upstream system and are dropped). Kyushu is
partial by construction (22 kV slice). Stations: estimate keys on the list-coverage basis;
selection as the canonical filter (>= 3,000 common hours, mean truth >= 0.5 MW).

Database: read-only SELECT through a guard, DT_DB_CONTAINER=iwafune_db_frozen required.
Outputs: results/micro/e10_transfer_shape_{TAG}.csv, e10_transfer_shape_station_{TAG}.csv,
results/numbers/e10_transfer_shape_{TAG}_rows.tex.
"""
import io as _io, os, re, subprocess, sys
if os.environ.get("DT_DB_CONTAINER") != "iwafune_db_frozen":
    sys.exit("[FATAL] set DT_DB_CONTAINER=iwafune_db_frozen explicitly (CLAUDE.md rule 4).")
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
import eval_io_v66 as io

_WRITE = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|COPY|GRANT|REVOKE)\b", re.I)
def qdf(sql, names, num=()):
    """Read-only query on the frozen container (SELECT only; the COPY wrapper is added here)."""
    if not sql.lstrip().upper().startswith("SELECT") or _WRITE.search(sql):
        raise RuntimeError(f"guard: only SELECT is allowed: {sql[:80]}")
    p = subprocess.run(["docker", "exec", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
                        "-i", "iwafune_db_frozen", "psql", "-U", "postgres", "-d", "lab_database", "-tAc",
                        f"COPY ({sql}) TO STDOUT WITH CSV"], capture_output=True)
    if p.returncode:
        sys.exit("SQL ERR: " + p.stderr.decode("utf-8", "replace")[:400])
    df = pd.read_csv(_io.StringIO(p.stdout.decode("utf-8", "replace")), names=names, dtype=str)
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def mask_outliers(t):
    """gen_val_daily_fy2024.py: NaN where |t| > 150 MW and > 15 x the median positive value."""
    tf = t[np.isfinite(t)]
    if tf.size < 100: return t
    pos = tf[tf > 0]
    med = float(np.median(pos)) if pos.size else 0.0
    if med <= 0: return t
    return np.where(np.isfinite(t) & (np.abs(t) > 150.0) & (np.abs(t) > 15.0 * med), np.nan, t)

def shape_metric(e, t):
    m = np.isfinite(t) & np.isfinite(e)
    if m.sum() < 3000 or np.mean(t[m]) < 0.5: return None
    e, t = e[m], t[m]
    me, mt = float(e.mean()), float(t.mean())
    r = float(np.corrcoef(e, t)[0, 1]) if np.std(e) > 1e-9 and np.std(t) > 1e-9 else np.nan
    scv = 100 * float(np.sqrt(np.mean((e / me - t / mt) ** 2))) if abs(me) > 1e-9 else np.nan
    return dict(hours=int(m.sum()), mt=mt, me=me, r=r, shape_cv=scv, neg_share=float((t < 0).mean()))

OCCTO_AREA = {"HOKKAIDO": 1, "TOHOKU": 2, "TEPCO": 3, "CHUBU": 4, "HOKURIKU": 5,
              "KANSAI": 6, "CHUGOKU": 7, "SHIKOKU": 8, "KYUSHU": 9, "OKINAWA": 10}
_OCC = None
def area_shape(U):
    """Hourly published area demand (R1-M6 baseline): the same shape for every substation of
    the area, so it needs no substation estimate. Aligned to the canonical hour index."""
    global _OCC
    if _OCC is None:
        _OCC = pd.read_parquet(io.OFF / "occto_supply_demand.parquet",
                               columns=["area_code", "ts", "demand_mw"])
    d = _OCC[_OCC.area_code == OCCTO_AREA[U]]
    W = io.to_wide(np.full(len(d), "A", dtype=object), d.ts.values, d.demand_mw.values, ["A"])
    return W[:, 0]

io.banner("E10 transfer-area shape")
AREAS = ["KANSAI", "CHUBU", "TOHOKU", "KYUSHU", "CHUGOKU", "HOKKAIDO", "HOKURIKU", "SHIKOKU", "OKINAWA"]
lc = io.list_coverage()
cap = io.engine_capacity().set_index(["utility", "key"])["cap"]
comp = qdf("SELECT utility, key, complete FROM validation.truth_completeness ORDER BY 1, 2", ["u", "key", "c"])
compmap = {(r.u, r.key): str(r.c) in ("t", "true", "True") for r in comp.itertuples()}
st = []
for U in AREAS:
    tru = qdf(f"""SELECT equipment_name, to_char(ts,'YYYY-MM-DD HH24:00'), sum(flow_mw)
                  FROM validation.flow_lt_truth WHERE utility='{U}' AND fiscal_year=2024
                  GROUP BY 1, 2 ORDER BY 1, 2""", ["nm", "ts", "mw"], ["mw"])
    if tru.empty:
        print(f"  {U:9} no ground truth"); continue
    pur = tru.nm.str.contains("中間|開閉", regex=True)
    n_pur = int(tru[pur].nm.nunique()); tru = tru[~pur]
    tkeys = sorted(set(tru.nm.map(io.norm2)) - {""})
    e = io.est_long(U, ("demand_net_mw",))
    lk = set(lc[lc.utility == U].key)
    keys = [k for k in tkeys if k in lk and k in set(e.station_id.unique())]
    if not keys:
        print(f"  {U:9} {len(tkeys)} truth keys, none on list coverage"); continue
    T = io.to_wide(tru.nm.values, tru.ts.values, tru.mw.values, keys, keyfun=io.norm2)
    E = io.est_wide(e, keys, "demand_net_mw")
    cls = io.est_classes(e[e.station_id.isin(keys)])
    nz = np.abs(T[np.isfinite(T)]); nz = nz[nz > 0.3]
    q_int = bool(len(nz)) and float(np.mean(np.abs(nz - np.round(nz)) < 1e-9)) >= 0.9
    n_ok = 0
    A = area_shape(U)
    for j, k in enumerate(keys):
        tj = mask_outliers(T[:, j])
        s = shape_metric(E[:, j], tj)
        if s is None: continue
        b = shape_metric(A, tj) or {}
        n_ok += 1
        c = float(cap.get((U, k), np.nan))
        st.append(dict(utility=U, key=k, src=cls[k], **s,
                       r_base=b.get("r", np.nan), shape_cv_base=b.get("shape_cv", np.nan),
                       complete=(False if U == "KYUSHU" else bool(compmap.get((U, k), False))),
                       flag_lf=bool(np.isfinite(c) and c > 0 and abs(s["mt"]) / c < 0.05),
                       flag_qt=bool(q_int and abs(s["mt"]) < 2.0), flag_dm=bool(s["neg_share"] >= 0.20)))
    print(f"  {U:9} truth keys {len(tkeys)} (purified names {n_pur}), on list coverage with an estimate "
          f"{len(keys)}, evaluated {n_ok}", flush=True)
st = pd.DataFrame(st)

# Tokyo reference: the canonical 1,216 with the same shape metric
pop = io.population()
Tt = io.tokyo_truth(pop.key); et = io.est_long("TEPCO", ("demand_net_mw",)); Et = io.est_wide(et, pop.key, "demand_net_mw")
io.check_population(pop, Tt, Et)
tk = []
At = area_shape("TEPCO")
for j, r in enumerate(pop.itertuples()):
    s = shape_metric(Et[:, j], Tt[:, j])
    b = shape_metric(At, Tt[:, j]) or {}
    if s: tk.append(dict(utility="TEPCO", key=r.key, src=r.src, **s,
                         r_base=b.get("r", np.nan), shape_cv_base=b.get("shape_cv", np.nan), complete=True,
                         flag_lf=False, flag_qt=False, flag_dm=bool(s["neg_share"] >= 0.20)))
st = pd.concat([st, pd.DataFrame(tk)], ignore_index=True)
st.to_csv(io.out("micro", f"e10_transfer_shape_station_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

def agg(g):
    h = g[~g.flag_dm]
    return dict(n=len(g), n_complete=int(g.complete.sum()), n_dm=int(g.flag_dm.sum()),
                r_med=float(g.r.median()), r_q25=float(g.r.quantile(.25)), r_q75=float(g.r.quantile(.75)),
                r_med_base=float(g.r_base.median()), shape_cv_med_base=float(g.shape_cv_base.median()),
                shape_cv_med=float(g.shape_cv.median()), shape_cv_q25=float(g.shape_cv.quantile(.25)),
                shape_cv_q75=float(g.shape_cv.quantile(.75)),
                n_nodm=len(h), r_med_nodm=float(h.r.median()) if len(h) else np.nan,
                shape_cv_med_nodm=float(h.shape_cv.median()) if len(h) else np.nan,
                r_med_complete=float(g[g.complete].r.median()) if g.complete.any() else np.nan)
rows = []
for U in ["TEPCO"] + AREAS:
    gu = st[st.utility == U]
    for c in ["all"] + io.CLASSES:
        g = gu if c == "all" else gu[gu.src == c]
        if len(g): rows.append(dict(utility=U, cls=c, **agg(g)))
nine = st[st.utility != "TEPCO"]
for c in ["all"] + io.CLASSES:
    g = nine if c == "all" else nine[nine.src == c]
    if len(g): rows.append(dict(utility="NINE_AREAS", cls=c, **agg(g)))
tab = pd.DataFrame(rows)
tab.to_csv(io.out("micro", f"e10_transfer_shape_{io.TAG}.csv"), index=False, encoding="utf-8-sig")

JA = {"TEPCO": "Tokyo (reference)", "KANSAI": "Kansai", "CHUBU": "Chubu", "TOHOKU": "Tohoku", "KYUSHU": "Kyushu",
      "CHUGOKU": "Chugoku", "HOKKAIDO": "Hokkaido", "HOKURIKU": "Hokuriku", "SHIKOKU": "Shikoku",
      "OKINAWA": "Okinawa", "NINE_AREAS": "Eight areas"}   # 公表系列があるのは9区域のうち8つ(北海道は無し)
tex = [f"{JA[r.utility]} & {io.CLASS_NAME[r.cls]} & {r.n} & {r.r_med:.2f} & {r.r_med_base:.2f} & {r.shape_cv_med:.0f} & {r.shape_cv_med_base:.0f}\\\\"
       for r in tab.itertuples()]
io.out("numbers", f"e10_transfer_shape_{io.TAG}_rows.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
pd.set_option("display.width", 220)
print(tab.round(3).to_string(index=False))
print(f"[output] e10_transfer_shape_{io.TAG}.csv, e10_transfer_shape_station_{io.TAG}.csv, "
      f"e10_transfer_shape_{io.TAG}_rows.tex")
