# -*- coding: utf-8 -*-
"""Shared read-only loaders for the round-1 evaluation analyses (E9, E10, E14 to E17, E19).

Evaluation only. The estimator (code/engine) never imports this module, and nothing here
writes anywhere the estimator reads. Ground truth and reference statistics are read only to
score estimates that already exist (CLAUDE.md rule 1).

Definitions are taken from the canonical scripts, not re-derived (CLAUDE.md rule 2):
  population     results/micro/{TAG}_micro_clean.csv from clean_truth_and_recompute.py
                 (1,249 series, 33 screened out, 1,216 evaluated in v6.5)
  station metric APE, r, CV-RMSE exactly as clean_truth_and_recompute.py lines 48 to 61
  list coverage  station_key_map (kind='master') x substation_master (node_type='haihen'),
                 as calc_annual_monthly_v65.py
  sales          high + low voltage, FY2024, MW = GWh x 1000 / hours of the month,
                 as recompute_all_clean.py part A
Hourly series come from the offline layer. check_population() proves that they reproduce the
canonical per-station numbers before any new statistic is computed.

Paths
  OUT_ROOT  the tree this file sits in; outputs go to OUT_ROOT/results/{micro,numbers} and
            OUT_ROOT/manuscript/figs. Installed in the workspace, that is the workspace.
  WS        the input workspace: PAPER_WS if set, else OUT_ROOT. A staged copy therefore
            reads the workspace and writes only into the staging tree.
Estimate      est_source.offline_source(): PAPER_EST_FILE, default the v6.5 file -> TAG.
"""
import os, sys, pathlib
import numpy as np, pandas as pd, pyarrow.parquet as pq

OUT_ROOT = pathlib.Path(__file__).resolve().parents[2]
WS = pathlib.Path(os.environ.get("PAPER_WS", str(OUT_ROOT))).resolve()
OFF = WS / "data" / "offline"
# Canonical products read as inputs. Installed, they are the workspace's own files. Before
# installation the v6.6 products can be produced by the unchanged canonical scripts in a scratch
# copy; PAPER_MICRO_IN, PAPER_NUM_IN and PAPER_ENG_OUT then point at that copy.
MICRO_IN = pathlib.Path(os.environ.get("PAPER_MICRO_IN", str(WS / "results" / "micro")))
NUM_IN = pathlib.Path(os.environ.get("PAPER_NUM_IN", str(WS / "results" / "numbers")))
ENG_OUT_IN = pathlib.Path(os.environ.get("PAPER_ENG_OUT", str(WS / "code" / "engine" / "analysis" / "unified" / "out")))
MICRO_OUT, NUM_OUT = OUT_ROOT / "results" / "micro", OUT_ROOT / "results" / "numbers"
FIG_OUT = OUT_ROOT / "manuscript" / "figs"
sys.path.insert(0, str(WS / "code" / "engine" / "analysis" / "unified"))
# norm2 and IDX come from the canonical engine module. Offline scripts never query the
# database; the import-time check of the frozen package only needs the variable to exist
# (the same device as build_level_v66.py). E10 sets the real container before importing.
os.environ.setdefault("DT_DB_CONTAINER", "offline-not-used")
from stage2_engine import IDX, norm2          # noqa: E402
from est_source import offline_source          # noqa: E402

EST_FILE, TAG = offline_source()
H = len(IDX)
MONTHS = list(pd.Series(IDX).dt.strftime("%Y-%m").unique())
MO = pd.Series(IDX).dt.strftime("%Y-%m").values
HOUR = IDX.hour.values
SEASON = np.select([np.isin(IDX.month, [3, 4, 5]), np.isin(IDX.month, [6, 7, 8]),
                    np.isin(IDX.month, [9, 10, 11])], ["MAM", "JJA", "SON"], "DJF")
DAY = (HOUR >= 9) & (HOUR <= 15)               # daytime window of the saturation audit
# v6.5 has three classes. v6.6 has two: criterion F merged the measured-shape class (z1s) into the
# transferred one, which the manuscript then numbers Class 2.
if TAG == "v65":
    CLASSES = ["z1", "z1s", "z2"]
    CLASS_NAME = {"z1": "Class 1", "z1s": "Class 2", "z2": "Class 3", "all": "All"}
else:
    CLASSES = ["z1", "z2"]
    CLASS_NAME = {"z1": "Class 1", "z2": "Class 2", "all": "All"}
_HPOS = {s: i for i, s in enumerate(IDX.strftime("%Y-%m-%d %H"))}


def out(kind, name):
    """Output path; every name must carry the estimate tag so v6.5 and v6.6 never collide."""
    assert TAG in name, f"output name must carry the tag {TAG}: {name}"
    d = {"micro": MICRO_OUT, "numbers": NUM_OUT, "figs": FIG_OUT}[kind]
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def banner(title):
    print(f"[{title}] estimate {EST_FILE} (tag {TAG}); inputs {WS}; outputs {OUT_ROOT}", flush=True)


# ── long table -> (hour x key) matrix, without pandas pivots ──
def _positions(col, table):
    codes, uniq = pd.factorize(col, sort=False)
    pos_u = np.array([table(u) for u in uniq], dtype=np.int64) if len(uniq) else np.zeros(0, np.int64)
    return pos_u[codes]


def to_wide(keycol, tscol, val, keys, keyfun=None, unique=False):
    """Sum of val per (hour, key); NaN where the key has no row in that hour (pivot_table
    semantics). keyfun maps the raw name to the key (norm2 for truth names)."""
    kidx = {k: i for i, k in enumerate(keys)}
    kf = (lambda u: kidx.get(keyfun(u), -1)) if keyfun else (lambda u: kidx.get(u, -1))
    kp = _positions(keycol, kf)
    tp = _positions(tscol, lambda u: _HPOS.get(str(u)[:13], -1))
    ok = (kp >= 0) & (tp >= 0)
    flat = tp[ok] * len(keys) + kp[ok]
    v = np.asarray(val, float)[ok]
    fin = np.isfinite(v)
    n = H * len(keys)
    cnt = np.bincount(flat, minlength=n).reshape(H, len(keys))
    if unique:
        assert cnt.max() <= 1, "duplicate (key, hour) rows in the estimate"
    W = np.bincount(flat[fin], weights=v[fin], minlength=n).reshape(H, len(keys))
    W[cnt == 0] = np.nan
    return W


# ── inputs ──
def population():
    """The canonical evaluation set (1,216 in v6.5), sorted by key."""
    d = pd.read_csv(MICRO_IN / f"{TAG}_micro_clean.csv", encoding="utf-8-sig")
    return d.sort_values("key", kind="mergesort").reset_index(drop=True)


def screened_out():
    """Series removed by the admission test (33 in v6.5), sorted by key."""
    d = pd.read_csv(MICRO_IN / f"{TAG}_truth_dropped.csv", encoding="utf-8-sig")
    return d.sort_values("key", kind="mergesort").reset_index(drop=True)


def list_coverage():
    """(utility, key) pairs on the list-coverage basis (5,950 keys = 5,968 list names)."""
    km = pd.read_parquet(OFF / "station_key_map.parquet")
    km = km[km.kind == "master"][["utility", "key", "src_name"]].drop_duplicates()
    sm = pd.read_parquet(OFF / "substation_master.parquet", columns=["utility", "station_id", "node_type"])
    sm = sm[sm.node_type == "haihen"][["utility", "station_id"]].rename(columns={"station_id": "src_name"})
    return (km.merge(sm, on=["utility", "src_name"])[["utility", "key"]]
              .drop_duplicates().sort_values(["utility", "key"], kind="mergesort").reset_index(drop=True))


def engine_capacity():
    """Capacity the engine allocates by (purified roster, results/numbers/station_levels_v66.csv)."""
    lv = pd.read_csv(NUM_IN / "station_levels_v66.csv", encoding="utf-8-sig")
    return lv[["utility", "key", "cap", "lambda", "level"]]


def level_model():
    import json
    return json.loads((NUM_IN / "level_model_v66.json").read_text(encoding="utf-8"))


def anchor_constant():
    """The area anchor of the estimate being scored: v6.5 LF_real 0.4058, v6.6 lambda 0.3501."""
    lm = level_model()
    return float(lm["lf_real_v65"] if TAG == "v65" else lm["lambda_tepco"])


def tokyo_covariates():
    """Public covariates per Tokyo key, built exactly as build_level_v66.py section 2
    (lines 91 to 111): households, manufacturing and tertiary employment through the mesh
    allocation, registered PV. Returns key, hh, manu, tert, pv_mw."""
    al = pd.read_parquet(OFF / "mesh_substation_alloc.parquet", columns=["mesh_code", "utility", "station_id", "weight"])
    ce = pd.read_parquet(OFF / "census_mesh_1km.parquet", columns=["mesh_1km", "households"])
    ec = pd.read_parquet(OFF / "econ_census_mesh_1km.parquet", columns=["mesh_1km", "emp_total", "emp_manu"])
    sm = pd.read_parquet(OFF / "substation_master.parquet", columns=["utility", "station_id", "station_name", "node_type"])
    sm = sm[sm.node_type == "haihen"].copy()
    sm["key"] = sm.station_name.fillna(sm.station_id).astype(str).map(norm2)
    a = (al.merge(ce, left_on="mesh_code", right_on="mesh_1km", how="left")
           .merge(ec, left_on="mesh_code", right_on="mesh_1km", how="left"))
    for c in ("households", "emp_total", "emp_manu"):
        a[c] = pd.to_numeric(a[c], errors="coerce").fillna(0.0)
    a["hh"] = a.weight * a.households
    a["manu"] = a.weight * a.emp_manu
    a["tert"] = a.weight * (a.emp_total - a.emp_manu)
    cov = (a.groupby(["utility", "station_id"], as_index=False)[["hh", "manu", "tert"]].sum()
             .merge(sm[["utility", "station_id", "key"]], on=["utility", "station_id"], how="inner")
             .groupby(["utility", "key"], as_index=False)[["hh", "manu", "tert"]].sum())
    pv = pd.read_parquet(OFF / "substation_pv.parquet")
    pvk = (pv.merge(sm[["utility", "station_id", "key"]], on=["utility", "station_id"], how="inner")
             .groupby(["utility", "key"], as_index=False)["pv_total_kw"].sum())
    pvk["pv_mw"] = pvk.pv_total_kw / 1000.0
    c = cov[cov.utility == "TEPCO"].merge(pvk[pvk.utility == "TEPCO"][["key", "pv_mw"]], on="key", how="left")
    c["pv_mw"] = c.pv_mw.fillna(0.0)
    return c[["key", "hh", "manu", "tert", "pv_mw"]].sort_values("key", kind="mergesort").reset_index(drop=True)


def tokyo_truth(keys):
    """Hourly Tokyo ground truth for keys (hours x keys), summed over banks by norm2 key,
    as clean_truth_and_recompute.py builds it from validation.tepco_bank_fy2024_full."""
    t = pq.read_table(OFF / "truth_tepco_bank_fy2024.parquet").to_pandas()
    return to_wide(t.station_norm.values, t.ts.values, t.flow_mw.values, list(keys), keyfun=norm2)


def est_long(utility, cols=("demand_net_mw",)):
    tb = pq.read_table(OFF / EST_FILE, columns=["utility", "station_id", "ts", "src", *cols],
                       filters=[("utility", "==", utility)])
    return tb.to_pandas()


def est_wide(e, keys, col):
    return to_wide(e.station_id.values, e.ts.values, e[col].values, list(keys), unique=True)


def area_total(e, keys, col):
    """Hourly sum of col over keys (the area total on the chosen key basis)."""
    W = est_wide(e, keys, col)
    return np.nansum(W, axis=1), W


def est_classes(e):
    s = e.groupby("station_id", sort=True)["src"].agg(lambda x: sorted(set(x))[0] if len(set(x)) == 1 else "mixed")
    assert (s != "mixed").all(), "a station changes class within the year"
    return s


def monthly_sales_mw(utility):
    s = pd.read_parquet(OFF / "area_demand_by_voltage.parquet")
    s = s[(s.utility == utility) & s.voltage_class.isin(["high", "low"])].copy()
    s["ym"] = pd.to_datetime(s.year_month).dt.strftime("%Y-%m")
    s = s[s.ym.isin(MONTHS)].groupby("ym")["demand_gwh"].sum()
    hrs = pd.Series(MO).value_counts()
    return (s * 1000.0 / hrs.reindex(s.index)).reindex(MONTHS).values.astype(float)


# ── canonical station metric (clean_truth_and_recompute.py) ──
def station_metric(e, t, min_hours=3000):
    m = np.isfinite(t) & np.isfinite(e)
    if m.sum() < min_hours:
        return None
    mt, me = float(np.mean(t[m])), float(np.mean(e[m]))
    r = float(np.corrcoef(e[m], t[m])[0, 1]) if np.std(e[m]) > 1e-9 else np.nan
    return dict(mt=mt, me=me, ape=100 * abs(me - mt) / mt, corr=r,
                cv=100 * float(np.sqrt(np.mean((e[m] - t[m]) ** 2)) / mt))


def check_population(pop, T, E, tol=1e-6):
    """Recompute me, mt, APE, r and CV-RMSE and require agreement with the canonical file."""
    bad = []
    for j, r in enumerate(pop.itertuples()):
        s = station_metric(E[:, j], T[:, j])
        if s is None:
            bad.append((r.key, "too few hours")); continue
        for c in ("mt", "me", "ape", "corr", "cv"):
            a, b = s[c], getattr(r, c)
            if not (np.isclose(a, b, rtol=tol, atol=tol) or (np.isnan(a) and np.isnan(b))):
                bad.append((r.key, c, a, b)); break
    if bad:
        raise SystemExit(f"[FATAL] offline hourly data do not reproduce {TAG}_micro_clean.csv "
                         f"for {len(bad)} stations, e.g. {bad[:3]}")
    print(f"  check: offline hourly data reproduce the canonical metrics of all {len(pop)} stations")


# ── statistics ──
def rsd(x):
    """Robust SD: 1.4826 x median absolute deviation."""
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else np.nan


def auc(risk, label):
    """Area under the ROC curve of risk for binary label (Mann-Whitney form, ties averaged)."""
    from scipy.stats import rankdata
    risk, label = np.asarray(risk, float), np.asarray(label, bool)
    ok = np.isfinite(risk); risk, label = risk[ok], label[ok]
    n1, n0 = int(label.sum()), int((~label).sum())
    if n1 == 0 or n0 == 0:
        return np.nan
    rk = rankdata(risk)
    return float((rk[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def boot_ci(fn, n_items, rng, n=2000, lo=2.5, hi=97.5):
    """Percentile interval of fn(index array) over i.i.d. resamples of n_items items."""
    s = np.array([fn(rng.integers(0, n_items, n_items)) for _ in range(n)], float)
    s = s[np.isfinite(s)]
    return [float(np.percentile(s, lo)), float(np.percentile(s, hi))] if len(s) else [np.nan, np.nan]


def block_boot_idx(rng, n_items=12, block=3):
    """One circular block bootstrap resample of positions 0..n_items-1 (supervisor ruling of
    2026-09-15: block length 3 over the 12 months)."""
    starts = rng.integers(0, n_items, int(np.ceil(n_items / block)))
    return np.concatenate([(s + np.arange(block)) % n_items for s in starts])[:n_items]
