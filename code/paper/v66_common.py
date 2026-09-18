# -*- coding: utf-8 -*-
"""Shared plumbing for the v6.6 evaluation generators (RERUN_PLAN_R1.md, Steps 7 and 10a; review item E8).

This module defines no metric of its own. Every definition it applies is taken from a canonical script,
and the test named next to it shows that it reproduces that script's committed output on v6.5 data:

  list basis (5,968 names, 5,950 keys)   calc_annual_monthly_v65.py, gen_scoreboard_table_v65.py
  class of an estimate key               gen_scoreboard_table_v65.py (src of the key in the estimate)
  the canonical harness                  clean_truth_and_recompute.py and recompute_all_clean.py, executed
                                         verbatim with their queries answered from files (run_canonical)
  per-substation metrics                 clean_truth_and_recompute.py, lines 47-61
  loss-scaled band                       run_N_adopted_and_validate.py:98-116, run_O_loss_adjusted.py:32-34
  engine query guard                     run_stage2_to_files.py:90-105

Tests: tests/test_harness_v65.py (harness, metrics, truth) and tests/test_common_v65.py (list basis,
classes, band, annual ratio). Both run on v6.5 data and compare with committed files.

Paths. W is the workspace the inputs come from and OUT_ROOT the root the outputs go to. Both default to
the workspace that holds this file. PAPER_WS and PAPER_OUT_ROOT override them, so that a staged copy can
be tested against a live workspace without writing into it. Outputs tagged v65 may be written only
outside the workspace: v6.5 mode exists to test these scripts against numbers the paper already reports,
and a v6.5 file in the workspace is never replaced.
"""
import contextlib, hashlib, io, json, os, pathlib, re, subprocess, sys, tempfile
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

_HERE = pathlib.Path(__file__).resolve()
W = pathlib.Path(os.environ.get("PAPER_WS") or _HERE.parents[2]).resolve()
OUT_ROOT = pathlib.Path(os.environ.get("PAPER_OUT_ROOT") or W).resolve()
OFF = W / "data" / "offline"
ENG = W / "code" / "engine" / "analysis" / "unified"
ENG_OUT = ENG / "out"
if str(ENG) not in sys.path:
    sys.path.insert(0, str(ENG))

ORDER = ["HOKKAIDO", "TOHOKU", "TEPCO", "CHUBU", "HOKURIKU", "KANSAI", "CHUGOKU", "SHIKOKU",
         "KYUSHU", "OKINAWA"]
JA = {"HOKKAIDO": "Hokkaido", "TOHOKU": "Tohoku", "TEPCO": "Tokyo", "CHUBU": "Chubu",
      "HOKURIKU": "Hokuriku", "KANSAI": "Kansai", "CHUGOKU": "Chugoku", "SHIKOKU": "Shikoku",
      "KYUSHU": "Kyushu", "OKINAWA": "Okinawa"}
AREA_CODE = {u: i + 1 for i, u in enumerate(ORDER)}          # OCCTO area codes, north to south
CLASS_NAME = {"z1": "Class 1", "z1s": "Class 2", "z2": "Class 3"}
CLASSES = ["z1", "z1s", "z2"]


# ── Small utilities ───────────────────────────────────────────────────────────────────────────────
def half_up(x, nd=0):
    """Round half up, as gen_scoreboard_table_v65.py does (79.25 -> 79.3, not 79.2)."""
    q = Decimal(10) ** -nd
    v = Decimal(str(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    return int(v) if nd == 0 else float(v)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=W, capture_output=True,
                          text=True).stdout.strip()


def out_path(sub, name, tag):
    """OUT_ROOT/sub/name. Refuses a v6.5-tagged output inside the workspace."""
    if tag == "v65" and OUT_ROOT == W:
        sys.exit("[FATAL] v6.5 mode is a test mode: set PAPER_OUT_ROOT to a directory outside the "
                 "workspace. A v6.5 file in the workspace is never written by these scripts.")
    p = OUT_ROOT / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_json(p, obj):
    pathlib.Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
                               encoding="utf-8")


def engine_offline():
    """Import stage2_engine for its constants and norm2 only, without a database (as build_level_v66.py
    does): the frozen-package check needs DT_DB_CONTAINER to be set, and no query is issued."""
    os.environ.setdefault("DT_DB_CONTAINER", "offline-not-used")
    import stage2_engine as E
    return E


def require_frozen_db():
    if os.environ.get("DT_DB_CONTAINER") != "iwafune_db_frozen":
        sys.exit("[FATAL] set DT_DB_CONTAINER=iwafune_db_frozen explicitly (CLAUDE.md rule 4).")


# ── Engine query guard (verbatim from run_stage2_to_files.py:90-105) ─────────────────────────────
DENY_PATTERN = (r"validation\.|area_demand_by_voltage|meti_demand|occto|okinawa_syscapa|"
                r"estimated_demand|ed_rerun|canonical\.demand\b|proprietary\.|"
                r"truth|tepco_bank")
WRITE_PATTERN = r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|COPY|GRANT|REVOKE)\b"


def guard_engine(E):
    """Replace E.qdf with the guard of the production wrapper: SELECT only, and no ground truth,
    reference statistics or earlier estimate can reach the estimator (CLAUDE.md rule 1)."""
    deny, write = re.compile(DENY_PATTERN, re.I), re.compile(WRITE_PATTERN, re.I)
    orig, log = E.qdf, []

    def guarded(sql, names, num=()):
        s = sql.lstrip().upper()
        if not (s.startswith("SELECT") or s.startswith("WITH")) or write.search(sql):
            raise RuntimeError(f"guard: only SELECT is allowed: {sql[:100]}")
        if deny.search(sql):
            raise RuntimeError(f"guard: relation on the deny-list: {sql[:160]}")
        log.append(" ".join(sql.split()))
        return orig(sql, names, num)
    E.qdf = guarded
    return log


# ── The list basis: 5,968 listed names on 5,950 estimate keys ─────────────────────────────────────
def list_basis(est_keys):
    """(utility, key, src_name) for every listed distribution substation that the estimate covers:
    station_key_map (kind='master') x substation_master (node_type='haihen') x the estimate's keys,
    as calc_annual_monthly_v65.py and gen_scoreboard_table_v65.py build it. One row per listed name.
    On both v6.5 and v6.6 this is 5,968 names on 5,950 keys (asserted by the callers' tests)."""
    km = pd.read_parquet(OFF / "station_key_map.parquet")
    km = km[km.kind == "master"][["utility", "key", "src_name"]].drop_duplicates()
    sm = pd.read_parquet(OFF / "substation_master.parquet", columns=["utility", "station_id", "node_type"])
    sm = sm[sm.node_type == "haihen"][["utility", "station_id"]].rename(columns={"station_id": "src_name"})
    names = km.merge(sm.drop_duplicates(), on=["utility", "src_name"])
    names = names.merge(est_keys[["utility", "key"]].drop_duplicates(), on=["utility", "key"])
    dup = names.duplicated(["utility", "src_name"], keep=False)
    if dup.any():                     # a name on two keys would make the name basis order-dependent
        sys.exit(f"[FATAL] {int(dup.sum())} listed names map to more than one key: "
                 f"{names[dup].head().to_dict('records')}")
    return names.sort_values(["utility", "src_name"], kind="mergesort").reset_index(drop=True)


def list_keys(est_keys):
    return list_basis(est_keys)[["utility", "key"]].drop_duplicates().reset_index(drop=True)


# ── Classes and annual means per estimate key ─────────────────────────────────────────────────────
def _per_key_from_table(tb):
    """Annual means and the class per (utility, station_id); asserts one class and 8,760 hours per key."""
    import pyarrow as pa
    g = tb.group_by(["utility", "station_id"]).aggregate(
        [("demand_net_mw", "mean"), ("demand_gross_mw", "mean"), ("pv_mw", "mean"),
         ("demand_net_mw", "count"), ("src", "min"), ("src", "max")]).to_pandas()
    g.columns = ["utility", "key", "net", "gross", "pv", "n_hours", "src_min", "src_max"]
    assert (g.src_min == g.src_max).all(), "a key changes class within the year"
    assert (g.n_hours == 8760).all(), "a key does not have 8,760 hours"
    g = g.rename(columns={"src_max": "src"}).drop(columns=["src_min", "n_hours"])
    return g.sort_values(["utility", "key"], kind="mergesort").reset_index(drop=True)


def per_key_offline(fname):
    """From an offline-layer estimate (estimated_demand_fy2024[_v66].parquet)."""
    import pyarrow.parquet as pq
    tb = pq.read_table(OFF / fname, columns=["utility", "station_id", "demand_net_mw",
                                              "demand_gross_mw", "pv_mw", "src"])
    return _per_key_from_table(tb)


def check_run_dir(run_dir, allow_smoke=False, need_all_areas=True):
    run_dir = pathlib.Path(run_dir).resolve()
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if man.get("smoke") and not allow_smoke:
        sys.exit(f"[FATAL] {run_dir} is a smoke run; pass a complete national run")
    if need_all_areas and not man.get("smoke") and len(man.get("areas_written", [])) != 10:
        sys.exit(f"[FATAL] {run_dir} does not hold all ten areas")
    return run_dir, man


def per_key_run(run_dir, areas=None):
    """From a run directory of run_stage2_to_files.py (ed_<UTILITY>.parquet)."""
    import pyarrow as pa, pyarrow.parquet as pq
    run_dir = pathlib.Path(run_dir)
    out = []
    for U in (areas or ORDER):
        f = run_dir / f"ed_{U}.parquet"
        if not f.exists():
            continue
        tb = pq.read_table(f, columns=["station_id", "demand_net_mw", "demand_gross_mw", "pv_mw", "src"])
        tb = tb.append_column("utility", pa.array([U] * tb.num_rows, type=pa.string()))
        out.append(_per_key_from_table(tb))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
        columns=["utility", "key", "net", "gross", "pv", "src"])


def classes_run(run_dir):
    """classes.csv of a run (utility, key, cap, level, in_level_file, rbar, q, src)."""
    c = pd.read_csv(pathlib.Path(run_dir) / "classes.csv", dtype={"utility": str, "key": str, "src": str},
                    keep_default_na=False, na_values=[""])
    return c.sort_values(["utility", "key"], kind="mergesort").reset_index(drop=True)


# ── Loss-scaled band of criterion B ───────────────────────────────────────────────────────────────
def sales_and_record():
    """FY2024 sales by voltage (GWh) and the mean area supply-demand record (MW), from the offline
    layer, exactly as run_N_adopted_and_validate.py:98-107 forms them."""
    egc = pd.read_parquet(OFF / "area_demand_by_voltage.parquet")
    egc["ym"] = pd.to_datetime(egc.year_month).dt.to_period("M")
    egc = egc[egc.ym.isin(pd.period_range("2024-04", "2025-03", freq="M"))]
    E = egc.pivot_table(index="utility", columns="voltage_class", values="demand_gwh", aggfunc="sum")
    occ = pd.read_parquet(OFF / "occto_supply_demand.parquet")
    occ = occ[(occ.ts >= "2024-04-01") & (occ.ts < "2025-04-01")]
    O = occ.groupby("area_code")["demand_mw"].mean()
    return E, O


def loss_band(check_against_O=True):
    """Per area: loss ratio = supply-demand record / total sales across all voltage levels; band =
    [1.02, 1.08] x loss ratio / median(loss ratio). ACCEPTANCE_CRITERIA_R1.md, criterion B. The criteria
    name experiments/level_validation/O_loss_adjusted.csv; the band is rebuilt here from the offline layer
    (so that the reproduction gate can regenerate it) and must equal that file."""
    E, O = sales_and_record()
    b = pd.DataFrame(index=ORDER)
    b["occto_mw"] = [float(O[AREA_CODE[u]]) for u in ORDER]
    b["hl_sales_mw"] = [(E.at[u, "high"] + E.at[u, "low"]) * 1000.0 / 8760.0 for u in ORDER]
    b["xh_sales_mw"] = [E.at[u, "extra_high"] * 1000.0 / 8760.0 for u in ORDER]
    b["all_sales_mw"] = b.hl_sales_mw + b.xh_sales_mw
    b["loss_ratio"] = b.occto_mw / b.all_sales_mw
    med = float(b.loss_ratio.median())
    b["band_lo"] = 1.02 * b.loss_ratio / med
    b["band_hi"] = 1.08 * b.loss_ratio / med
    if check_against_O:
        Of = pd.read_csv(W / "experiments" / "level_validation" / "O_loss_adjusted.csv",
                         encoding="utf-8-sig").set_index("utility").reindex(ORDER)
        dev = max(float((b.loss_ratio - Of.loss_implied).abs().max()),
                  float((b.band_lo - Of.band_lo).abs().max()), float((b.band_hi - Of.band_hi).abs().max()))
        if dev > 1e-12:
            sys.exit(f"[FATAL] the band rebuilt from the offline layer differs from O_loss_adjusted.csv "
                     f"by {dev:.3g}; criterion B names that file")
    return b


def signed_gap_pp(annual_pct, band_lo, band_hi):
    """Signed gap in percentage points between the estimate-to-sales ratio (per cent) and the band:
    0 inside, negative below, positive above (ACCEPTANCE_CRITERIA_R1.md, criterion B)."""
    lo, hi = 100.0 * band_lo, 100.0 * band_hi
    if annual_pct < lo:
        return annual_pct - lo
    if annual_pct > hi:
        return annual_pct - hi
    return 0.0


def annual_pct_from_means(per_key, keys=None):
    """Annual (%) = sum of the estimate over the fiscal year / high + low voltage sales, on the list
    basis. The definition of calc_annual_monthly_v65.py, written from annual means (every key carries
    8,760 hours). Only a pre-check before the offline v6.6 file exists; the canonical route is that
    script's output annual_monthly_<tag>.csv. tests/test_common_v65.py shows the two agree on v6.5."""
    keys = list_keys(per_key) if keys is None else keys
    x = per_key.merge(keys, on=["utility", "key"], how="inner")
    E, _ = sales_and_record()
    out = {}
    for u in ORDER:
        s = x[x.utility == u]
        if s.empty:
            continue
        est_gwh = float(s.net.sum()) * 8760.0 / 1000.0
        out[u] = 100.0 * est_gwh / float(E.at[u, "high"] + E.at[u, "low"])
    return pd.Series(out, name="annual_pct")


# ── Ground truth of the calibration area (evaluation only; never an estimator input) ──────────────
_TRUTH = None


def truth_frame():
    """Tokyo ground truth as clean_truth_and_recompute.py receives it from its query
    (station_norm, 'YYYY-MM-DD HH:00', flow_mw), read from data/offline/truth_tepco_bank_fy2024.parquet,
    the export of validation.tepco_bank_fy2024_full. tests/test_harness_v65.py shows that the canonical
    scripts reproduce their committed v6.5 outputs from it."""
    global _TRUTH
    if _TRUTH is None:
        t = pd.read_parquet(OFF / "truth_tepco_bank_fy2024.parquet")
        t = pd.DataFrame({"nm": t.station_norm.astype(str), "ts": t.ts.str.slice(0, 13) + ":00",
                          "mw": t.flow_mw.astype(float)})
        _TRUTH = t
    return _TRUTH


def truth_wide(IDX, norm2):
    """The canonical pivot of clean_truth_and_recompute.py:29-31: key = norm2(station_norm), summed."""
    tru = truth_frame().copy()
    tru["key"] = tru.nm.map(norm2)
    tw = tru.pivot_table(index="ts", columns="key", values="mw", aggfunc="sum")
    tw.index = pd.to_datetime(tw.index)
    return tw.reindex(IDX)


def station_metrics(e, t):
    """clean_truth_and_recompute.py:49-61 for one substation, without the capacity screen:
    None if fewer than 3,000 joint hours or a mean ground truth below 0.5 MW."""
    m = np.isfinite(t) & np.isfinite(e)
    if m.sum() < 3000 or np.nanmean(t[m]) < 0.5:
        return None
    mt = float(np.nanmean(t[m])); me = float(np.nanmean(e[m]))
    r = float(np.corrcoef(e[m], t[m])[0, 1]) if np.std(e[m]) > 1e-9 else np.nan
    return dict(mt=mt, me=me, ape=100 * abs(me - mt) / mt, corr=r,
                cv=100 * float(np.sqrt(np.mean((e[m] - t[m]) ** 2)) / mt))


# ── Tokyo estimate series, for the canonical harness ──────────────────────────────────────────────
class TokyoSeries:
    """Net series of the Tokyo estimate: keys (sorted), src per key, net (n x 8,760) in IDX order."""

    def __init__(self, keys, src, net, label):
        self.keys, self.src, self.net, self.label = list(keys), np.asarray(src, dtype=object), net, label

    @classmethod
    def _from_frame(cls, d, label, IDX):
        d = d.sort_values(["station_id", "ts"], kind="mergesort")
        keys = d.station_id.drop_duplicates().tolist()
        n, H = len(keys), len(IDX)
        if len(d) != n * H:
            sys.exit(f"[FATAL] {label}: {len(d)} rows for {n} keys x {H} hours")
        ts13 = d.ts.str.slice(0, 13).to_numpy().reshape(n, H)
        want = np.array(IDX.strftime("%Y-%m-%d %H"), dtype=object)
        if not (ts13 == want[None, :]).all():
            sys.exit(f"[FATAL] {label}: hours are not the fiscal-year index in order")
        src = d.src.to_numpy().reshape(n, H)
        assert (src == src[:, :1]).all(), f"{label}: a key changes class within the year"
        return cls(keys, src[:, 0], d.demand_net_mw.to_numpy(dtype=float).reshape(n, H), label)

    @classmethod
    def from_run(cls, run_dir, IDX):
        f = pathlib.Path(run_dir) / "ed_TEPCO.parquet"
        d = pd.read_parquet(f, columns=["station_id", "ts", "demand_net_mw", "src"])
        return cls._from_frame(d, f"run:{pathlib.Path(run_dir).name}", IDX)

    @classmethod
    def from_offline(cls, fname, IDX):
        d = pd.read_parquet(OFF / fname, columns=["utility", "station_id", "ts", "demand_net_mw", "src"],
                            filters=[("utility", "=", "TEPCO")])
        return cls._from_frame(d.drop(columns="utility"), f"offline:{fname}", IDX)

    def query_frame(self, IDX):
        n, H = self.net.shape
        ts13 = np.array(IDX.strftime("%Y-%m-%d %H:00"), dtype=object)
        return pd.DataFrame({"station_id": np.repeat(np.array(self.keys, dtype=object), H),
                             "src": np.repeat(self.src, H), "ts": np.tile(ts13, n),
                             "demand_net_mw": self.net.ravel()})


# ── The canonical harness ─────────────────────────────────────────────────────────────────────────
def _split_top(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


class OfflineShim:
    """Answers the queries of clean_truth_and_recompute.py and recompute_all_clean.py from files.
    It never reaches a database: an unrecognised query stops the run. Each answer carries the column
    types qdf would give (text, with the numeric columns converted by qdf's own rule)."""

    EST_MARK = "file:"

    def __init__(self, tokyo, IDX, roster="db"):
        self.tokyo, self.IDX, self.log, self.roster = tokyo, IDX, [], roster
        self._db_qdf = engine_offline().qdf          # captured before run_canonical patches it

    def _roster(self, sql, names, num):
        # clean_truth_and_recompute.py:40-44 reads the roster WITHOUT an ORDER BY and keeps the first
        # row per key, so the capacity of a colliding key, and hence whether its series passes the
        # plausibility screen, depends on the database's row order. The offline file (sorted by
        # official_code) moves two Tokyo keys across the screen (1,218 instead of 1,216;
        # tests/test_harness_v65.py). Default: this one statement, unchanged, goes to the frozen
        # database (SELECT only), exactly as the canonical run issued it. roster="file" uses the file.
        if self.roster == "db":
            require_frozen_db()
            if not re.fullmatch(r"\s*SELECT name, coalesce\(equip_mw,0\), coalesce\(opcap_mw,0\) FROM "
                                r"canonical\.haihen_roster\s+WHERE utility='TEPCO'\s*", sql):
                raise RuntimeError("harness: only the canonical roster statement may reach the database")
            return self._db_qdf(sql, names, num)
        r = pd.read_parquet(OFF / "haihen_roster.parquet")
        r = r[r.utility == "TEPCO"]
        return pd.DataFrame({"a": r["name"].astype(str),
                             "b": pd.to_numeric(r.equip_mw, errors="coerce").fillna(0.0),
                             "c": pd.to_numeric(r.opcap_mw, errors="coerce").fillna(0.0)})

    def _sales(self):
        e = pd.read_parquet(OFF / "area_demand_by_voltage.parquet")
        e = e[(e.utility == "TEPCO") & e.voltage_class.isin(["high", "low"]) &
              (e.year_month >= "2024-04-01") & (e.year_month < "2025-04-01")].copy()
        return e

    def __call__(self, sql, names, num=()):
        s = " ".join(sql.split())
        self.log.append(s[:160])
        if "validation.tepco_bank_fy2024_full" in s:
            df = truth_frame().copy()
        elif "canonical.haihen_roster" in s and "utility='TEPCO'" in s:
            df = self._roster(sql, names, num)
            if self.roster == "db":
                return df
        elif "public_data.area_demand_by_voltage" in s and "to_char(year_month" in s:
            e = self._sales()
            e["ym"] = e.year_month.str.slice(0, 7)
            hours = {ym: (pd.Period(ym, "M").days_in_month * 24.0) for ym in e.ym.unique()}
            g = e.groupby("ym", sort=True)["demand_gwh"].sum()
            df = pd.DataFrame({"ym": g.index, "mw": [v * 1000.0 / hours[k] for k, v in g.items()]})
        elif "public_data.area_demand_by_voltage" in s and "/8760" in s.replace(" ", ""):
            df = pd.DataFrame({"v": [float(self._sales().demand_gwh.sum()) * 1000.0 / 8760.0]})
        elif self.EST_MARK in s and "utility='TEPCO'" in s:
            sel = re.search(r"SELECT (.*?) FROM", s).group(1)
            q = self.tokyo.query_frame(self.IDX)
            cols = []
            for ex in _split_top(sel):
                if ex == "station_id": cols.append("station_id")
                elif ex == "src": cols.append("src")
                elif ex.startswith("to_char(ts"): cols.append("ts")
                elif ex == "demand_net_mw": cols.append("demand_net_mw")
                else: raise RuntimeError(f"harness: unknown estimate column {ex!r}")
            df = q[cols]
        else:
            raise RuntimeError(f"harness: query not recognised, refusing (no database path): {s[:160]}")
        df = df.copy()
        df.columns = names
        for c in names:
            if c not in num:
                df[c] = df[c].astype(str)
        for c in num:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.reset_index(drop=True)


class _Log(io.TextIOBase):
    def __init__(self, f):
        self.f = f

    def write(self, s):
        self.f.write(s); return len(s)

    def flush(self):
        self.f.flush()

    def reconfigure(self, **kw):          # the canonical scripts call sys.stdout.reconfigure
        pass


def run_canonical(script_rel, root, shim, tag, log_path):
    """Execute a canonical script's source, unmodified, with
         - stage2_engine.qdf replaced by `shim` (files, never the database),
         - est_source.db_source() returning the file-backed estimate and `tag`,
         - __file__ placed under `root`, so that its outputs land in root/results/micro/.
    With shim=None the script keeps its own database path (SELECT only, PAPER_EST_REL, frozen container)
    and only its outputs are relocated: the check that the file route equals the Step 10 route.
    Returns the script's global namespace. The text executed is the committed file (sha256 logged)."""
    E = engine_offline()
    import est_source as S
    saved = (E.qdf, S.db_source)
    if shim is not None:
        E.qdf = shim
        S.db_source = lambda: (f"{OfflineShim.EST_MARK}{shim.tokyo.label}", "%", tag)
        label = shim.tokyo.label
    else:
        require_frozen_db()
        label = "db:" + os.environ.get("PAPER_EST_REL", "")
    src_path = W / script_rel
    fake = pathlib.Path(root) / script_rel
    fake.parent.mkdir(parents=True, exist_ok=True)
    g = {"__name__": "__main__", "__file__": str(fake)}
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n### {script_rel} sha256={sha256(src_path)} estimate={label} tag={tag}\n")
            with contextlib.redirect_stdout(_Log(fh)):
                exec(compile(src_path.read_text(encoding="utf-8"), str(fake), "exec"), g)
    finally:
        E.qdf, S.db_source = saved
    return g


def canonical_micro(tokyo, tag, root, log_path):
    """clean_truth_and_recompute.py then recompute_all_clean.py on `tokyo` (None: the database route,
    tag from PAPER_EST_REL); returns the output paths."""
    E = engine_offline()
    shim = OfflineShim(tokyo, E.IDX) if tokyo is not None else None
    if shim is None:
        import est_source as S
        tag = S.DB_SOURCES[os.environ.get("PAPER_EST_REL", "")][1]
    run_canonical("code/paper/clean_truth_and_recompute.py", root, shim, tag, log_path)
    run_canonical("code/paper/recompute_all_clean.py", root, shim, tag, log_path)
    m = pathlib.Path(root) / "results" / "micro"
    return {k: m / f"{tag}_{k}" for k in ("micro_clean.csv", "truth_dropped.csv", "tier_clean.csv",
                                          "closure_clean.json", "clean_all.json", "floor_monthly.csv")}


# ── The retired Tokyo residual corrections (E3), for the offline cost-of-E3 comparison only ───────
def retired_correction(IDX, MF, HS_raw):
    """The hourly factor _fm * _HS of stage2_engine.py before commit 849afbc
    (git show 849afbc^:code/engine/analysis/unified/stage2_engine.py, lines 363-387 and 404-409):
    12 monthly factors times 24 x 4 hour-by-season factors. tests/test_e3_equivalence.py executes the
    deleted block itself from git history and compares."""
    fm = np.asarray(MF, dtype=float)[IDX.month.values - 1]
    s4 = {3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer",
          9: "autumn", 10: "autumn", 11: "autumn", 12: "winter", 1: "winter", 2: "winter"}
    sea = [s4[m] for m in IDX.month.values]
    hs = np.array([HS_raw[s][h] for s, h in zip(sea, IDX.hour.values)])
    corr = np.ones(len(IDX))
    corr = corr * fm
    corr = corr * hs
    return corr


def apply_retired(net, src, corr):
    """The deleted block's application (old lines 404-413): Class 3 series only, multiplied by the
    factor, then rescaled to the series' own annual mean. Returns a new array."""
    net = np.array(net, dtype=float, copy=True)
    for i in range(len(net)):
        if src[i] != "z2":
            continue
        mu0 = net[i].mean()
        net[i] = net[i] * corr
        if net[i].mean() > 1e-9:
            net[i] *= mu0 / net[i].mean()
    return net


# ── Criterion A: medians and the comparison with v6.5 ─────────────────────────────────────────────
TOL = dict(ape=2.0, corr=0.02, cvrmse=5.0)       # ACCEPTANCE_CRITERIA_R1.md, criterion A
REF_QUOTED = {"all": dict(ape=21.5, corr=0.739),  # the values the criteria file quotes
              "z1": dict(ape=18.4, corr=0.73, cvrmse=85.0),
              "z1s": dict(ape=18.3, corr=0.78, cvrmse=45.3),
              "z2": dict(ape=22.5, corr=0.73, cvrmse=50.0)}


def medians(micro, keys=None):
    """Medians rounded as recompute_all_clean.py rounds them (APE and CV-RMSE 1 dp, r 3 dp)."""
    d = micro if keys is None else micro[micro.key.isin(keys)]
    def one(x):
        return dict(n=int(len(x)), ape=round(float(x.ape.median()), 1),
                    corr=round(float(x["corr"].median()), 3), cvrmse=round(float(x.cv.median()), 1),
                    ape_raw=float(x.ape.median()), corr_raw=float(x["corr"].median()),
                    cvrmse_raw=float(x.cv.median()))
    out = {"all": one(d)}
    for s in CLASSES:
        x = d[d.src == s]
        if len(x):
            out[s] = one(x)
    return out


def reference_v65():
    """v6.5 reference medians from the committed canonical files, checked against the values the
    criteria file quotes. The file quotes no CV-RMSE for all 1,216; it is taken from v65_micro_clean.csv."""
    ca = json.loads((W / "results" / "micro" / "v65_clean_all.json").read_text(encoding="utf-8"))
    mc = pd.read_csv(W / "results" / "micro" / "v65_micro_clean.csv", encoding="utf-8-sig")
    ref = {"all": dict(n=ca["overall"]["n"], ape=ca["overall"]["ape"], corr=ca["overall"]["corr"],
                       cvrmse=round(float(mc.cv.median()), 1))}
    for s in CLASSES:
        t = ca["tiers"][s]
        ref[s] = dict(n=t["n"], ape=t["ape"], corr=t["corr"], cvrmse=t["cvrmse"])
    for grp, q in REF_QUOTED.items():
        for k, v in q.items():
            nd = 3 if (k == "corr" and grp == "all") else (2 if k == "corr" else 1)
            assert round(ref[grp][k], nd) == v, f"v6.5 file {grp}.{k}={ref[grp][k]} does not round to {v}"
    return ref, set(mc.key)


def criterion_a_rows(new, ref):
    """One row per population and metric: v6.5 reference, v6.6, change, tolerance, pass (<= tolerance)."""
    rows = []
    for grp in ["all"] + CLASSES:
        if grp not in new:
            continue
        for k in ("ape", "corr", "cvrmse"):
            v5, v6 = ref[grp][k], new[grp][k]
            worse = (v5 - v6) if k == "corr" else (v6 - v5)   # positive = worse
            rows.append(dict(population=grp if grp == "all" else CLASS_NAME[grp], src=grp,
                             n_v65=ref[grp]["n"], n_v66=new[grp]["n"], metric=k, v65=v5, v66=v6,
                             worsening=round(worse, 3), tolerance=TOL[k],
                             passed=bool(worse <= TOL[k] + 1e-9)))
    return pd.DataFrame(rows)
