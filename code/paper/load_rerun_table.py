#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load one run of run_stage2_to_files.py into the separate table lab_data.ed_rerun_v66, and drop
it again when the regeneration chain is done.

RERUN_PLAN_R1.md, Section 5.3 and 5.5, Steps 8 and 11. Needs the frozen database for writing, but
only to this one table:

  load_rerun_table.py results/rerun_v66/run_a     # CREATE TABLE + COPY + checks (Step 8)
  load_rerun_table.py --drop                      # DROP TABLE + checks (Step 11)

Safety (CLAUDE.md rule 4):
  - DT_DB_CONTAINER must be iwafune_db_frozen.
  - Every write statement passes a guard that requires lab_data.ed_rerun_v66 and refuses any other
    relation, so lab_data.estimated_demand and lab_data.estimation_run cannot be written.
  - The Section 5.4 fingerprint of lab_data.estimated_demand is taken before and after; a
    difference stops the script with an error. --drop also compares it byte for byte with
    logs/rerun_v66/fingerprint_before.txt and writes logs/rerun_v66/fingerprint_after.txt.
  - The table must not exist before a load; a leftover table is never replaced silently.
  - The name avoids the relations that contract C8 forbids (check_contracts.py:94-100).

Table: the columns of the view lab_data.estimated_demand_fy2024 plus fiscal_year, with the same
types (timestamptz, real) and primary key (utility, station_id, ts). run_id is
'v66_rerun_fy2024_<utility>', which est_source.py maps to the tag v66.
It needs about 5 GB plus 2 GB of index: check `docker system df -v` first.
"""
import argparse, hashlib, json, os, pathlib, re, subprocess, sys, tempfile

if os.environ.get("DT_DB_CONTAINER") != "iwafune_db_frozen":
    sys.exit("[FATAL] set DT_DB_CONTAINER=iwafune_db_frozen explicitly (CLAUDE.md rule 4).")
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
DBC = os.environ["DT_DB_CONTAINER"]
TABLE = "lab_data.ed_rerun_v66"
REGIONS = ["TEPCO", "KANSAI", "CHUBU", "TOHOKU", "KYUSHU", "CHUGOKU", "HOKKAIDO", "HOKURIKU",
           "SHIKOKU", "OKINAWA"]
FP_BEFORE = W / "logs" / "rerun_v66" / "fingerprint_before.txt"
FP_AFTER = W / "logs" / "rerun_v66" / "fingerprint_after.txt"
TEPCO_ROWS = 12395400

ap = argparse.ArgumentParser()
ap.add_argument("run_dir", nargs="?", help="results/rerun_v66/<tag> to load")
ap.add_argument("--drop", action="store_true", help=f"DROP TABLE {TABLE} and confirm the baseline")
a = ap.parse_args()
if bool(a.run_dir) == bool(a.drop):
    sys.exit("usage: load_rerun_table.py RUN_DIR | --drop")


def psql_read(sql):
    p = subprocess.run(["docker", "exec", "-i", DBC, "psql", "-U", "postgres", "-d", "lab_database",
                        "-tAc", sql], capture_output=True)
    if p.returncode:
        sys.exit("SQL ERR: " + p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout

_FORBID = re.compile(r"estimated_demand|estimation_run|canonical\.|public_data\.|validation\.|"
                     r"proprietary\.", re.I)
def psql_write(sql, stdin=None):
    """The only path that writes. It must name the rerun table and nothing else."""
    if TABLE not in sql or _FORBID.search(sql.replace(TABLE, "")):
        raise RuntimeError(f"guard: a write may touch {TABLE} only: {sql[:160]}")
    p = subprocess.run(["docker", "exec", "-i", DBC, "psql", "-U", "postgres", "-d", "lab_database",
                        "-v", "ON_ERROR_STOP=1", "-c", sql], stdin=stdin, capture_output=True)
    if p.returncode:
        sys.exit("SQL ERR: " + p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout.decode("utf-8", "replace").strip()

def fingerprint():
    """The two read-only queries of plan Section 5.4, byte for byte as the shell runs them."""
    return (psql_read("SELECT utility, fiscal_year, run_id, count(*), count(DISTINCT station_id), "
                      "round(sum(demand_net_mw::float8)::numeric, 3) FROM lab_data.estimated_demand "
                      "GROUP BY 1,2,3 ORDER BY 1,2,3")
            + psql_read("SELECT run_id, git_commit, created_at, params->>'z1_stations' FROM "
                        "lab_data.estimation_run WHERE run_id LIKE 'stage2_pvaware_fy2024_%' ORDER BY 1"))

def tepco_rows():
    return int(psql_read("SELECT count(*) FROM lab_data.estimated_demand "
                         "WHERE utility='TEPCO' AND fiscal_year=2024").decode().strip())

def table_exists():
    return psql_read(f"SELECT to_regclass('{TABLE}') IS NOT NULL").decode().strip() == "t"

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


fp0 = fingerprint()
if FP_BEFORE.exists() and fp0 != FP_BEFORE.read_bytes():
    sys.exit(f"[FATAL] the fingerprint of lab_data.estimated_demand differs from {FP_BEFORE} "
             "before this script wrote anything. Stop and investigate.")

if a.drop:
    if not table_exists():
        print(f"{TABLE} does not exist; nothing to drop")
    else:
        psql_write(f"DROP TABLE {TABLE}")
    assert not table_exists(), f"{TABLE} still exists"
    fp1 = fingerprint()
    FP_AFTER.parent.mkdir(parents=True, exist_ok=True)
    FP_AFTER.write_bytes(fp1)
    t = tepco_rows()
    same = FP_BEFORE.exists() and fp1 == FP_BEFORE.read_bytes()
    print(f"to_regclass('{TABLE}') is null; TEPCO FY2024 rows {t:,}; fingerprint written to {FP_AFTER}")
    print(f"fingerprint identical to {FP_BEFORE.name}: {same}")
    if not same or t != TEPCO_ROWS:
        sys.exit("[FATAL] the baseline is not back: compare the fingerprints")
    print("Baseline confirmed. Run check_contracts.py for C8.")
    sys.exit(0)

RUN = pathlib.Path(a.run_dir).resolve()
man = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
if man.get("smoke") or man.get("areas_written") != REGIONS:
    sys.exit(f"[FATAL] {RUN} is not a complete national run")
if man.get("level_file") != "results/numbers/station_levels_v66.csv":
    sys.exit(f"[FATAL] {RUN} was run on {man.get('level_file')}; only a run on the canonical level file is "
             "loaded (criterion G sensitivities stay in files)")
for U in REGIONS:
    f = RUN / f"ed_{U}.parquet"
    if sha256(f) != man["areas"][U]["sha256"]:
        sys.exit(f"[FATAL] {f} does not match the sha256 in its manifest")
if table_exists():
    sys.exit(f"[FATAL] {TABLE} already exists. Drop it first with --drop; it is never replaced silently.")

psql_write(f"""CREATE TABLE {TABLE} (
    run_id text NOT NULL, utility text NOT NULL, fiscal_year integer NOT NULL,
    station_id text NOT NULL, ts timestamptz NOT NULL,
    demand_net_mw real, demand_gross_mw real, pv_mw real, src text,
    PRIMARY KEY (utility, station_id, ts))""")
psql_write(f"COMMENT ON TABLE {TABLE} IS 'v6.6 rerun ({RUN.name}, git {man['git_head'][:7]}); "
           f"temporary, drop after the regeneration chain (RERUN_PLAN_R1.md Step 11)'")
tmp = pathlib.Path(tempfile.gettempdir()) / "paper_rerun_v66_load"
tmp.mkdir(parents=True, exist_ok=True)
expected = 0
for U in REGIONS:
    d = pd.read_parquet(RUN / f"ed_{U}.parquet")
    d.insert(0, "fiscal_year", 2024); d.insert(0, "utility", U)
    d.insert(0, "run_id", f"v66_rerun_fy2024_{U.lower()}")
    d = d[["run_id", "utility", "fiscal_year", "station_id", "ts", "demand_net_mw",
           "demand_gross_mw", "pv_mw", "src"]]
    csv = tmp / f"ed_{U}.csv"
    d.to_csv(csv, index=False, header=False, encoding="utf-8")
    n = len(d); del d
    with open(csv, "rb") as fh:
        psql_write(f"COPY {TABLE}(run_id,utility,fiscal_year,station_id,ts,demand_net_mw,"
                   f"demand_gross_mw,pv_mw,src) FROM STDIN WITH CSV", stdin=fh)
    csv.unlink()
    got = int(psql_read(f"SELECT count(*) FROM {TABLE} WHERE utility='{U}'").decode().strip())
    print(f"  {U:9} {got:>10,} rows", flush=True)
    if got != n:
        sys.exit(f"[FATAL] {U}: {got} rows loaded, {n} expected")
    expected += n

# Checks of plan Step 8
tot = int(psql_read(f"SELECT count(*) FROM {TABLE}").decode().strip())
nst = int(psql_read(f"SELECT count(DISTINCT (utility, station_id)) FROM {TABLE}").decode().strip())
cls = psql_read(f"SELECT utility, src, count(DISTINCT station_id) FROM {TABLE} GROUP BY 1,2 ORDER BY 1,2"
                ).decode().split()
got_cls = {(u, s): int(c) for u, s, c in (x.split("|") for x in cls)}
at = pd.read_csv(RUN / "area_totals.csv")
want_cls = {(r.utility, s): int(getattr(r, s)) for r in at.itertuples() for s in ("z1", "z1s", "z2")
            if int(getattr(r, s)) > 0}
fp1 = fingerprint()
t = tepco_rows()
log = dict(run=str(RUN), table=TABLE, rows=tot, rows_expected=expected, stations=nst,
           stations_expected=int(at.stations.sum()), classes_match=got_cls == want_cls,
           fingerprint_unchanged=fp1 == fp0, tepco_fy2024_rows=t)
(RUN / "load_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
print(json.dumps(log, indent=1))
if not (tot == expected and nst == log["stations_expected"] and log["classes_match"]
        and log["fingerprint_unchanged"] and t == TEPCO_ROWS):
    sys.exit("[FATAL] a load check failed; see load_log.json")
print(f"[ok] {TABLE} loaded. Drop it after the regeneration chain: load_rerun_table.py --drop")
