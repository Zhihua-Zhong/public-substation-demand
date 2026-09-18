#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Determinism verdict between two runs of run_stage2_to_files.py.

RERUN_PLAN_R1.md, Step 6; ACCEPTANCE_CRITERIA_R1.md, criterion D. Reads files only.

Criterion D passes when
  - the two manifests carry identical input sha256 and the same database dump,
  - every class assignment is identical (classes.csv), and
  - the per-area totals are byte-identical (area_totals.csv).
The series are compared as well, by the sha256 of each ed_<UTILITY>.parquet and, where they differ,
by the maximum absolute difference per area and column. That comparison is reported; criterion D
does not make it a pass condition.

  compare_runs.py results/rerun_v66/run_a results/rerun_v66/run_b [--report PATH]

Writes results/rerun_v66/determinism_report.csv (or PATH). Exit 0 if D passes, 1 if it fails.
"""
import argparse, hashlib, json, pathlib, sys
import numpy as np, pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("run_a"); ap.add_argument("run_b")
ap.add_argument("--report", help="default: <parent of run_a>/determinism_report.csv")
a = ap.parse_args()
A, B = pathlib.Path(a.run_a).resolve(), pathlib.Path(a.run_b).resolve()
REPORT = pathlib.Path(a.report) if a.report else A.parent / "determinism_report.csv"

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""): h.update(blk)
    return h.hexdigest()

ma = json.loads((A / "manifest.json").read_text(encoding="utf-8"))
mb = json.loads((B / "manifest.json").read_text(encoding="utf-8"))
for m, p in ((ma, A), (mb, B)):
    if m.get("smoke"):
        sys.exit(f"[FATAL] {p} is a smoke run; criterion D needs two complete national runs")
    if len(m.get("areas_written", [])) != 10:
        sys.exit(f"[FATAL] {p} does not hold all ten areas")

rows = []
def rec(item, area, va, vb, equal, gate, detail=""):
    rows.append(dict(item=item, area=area, run_a=va, run_b=vb, equal=bool(equal),
                     part_of_criterion_D=gate, detail=detail))

# Inputs
keys = sorted(set(ma["inputs_sha256"]) | set(mb["inputs_sha256"]))
for k in keys:
    va, vb = ma["inputs_sha256"].get(k), mb["inputs_sha256"].get(k)
    rec("input_sha256", k, va, vb, va == vb, True)
rec("db_dump", "", ma.get("db_dump_sha256sums"), mb.get("db_dump_sha256sums"),
    ma.get("db_dump_sha256sums") == mb.get("db_dump_sha256sums"), True)
rec("git_head", "", ma["git_head"], mb["git_head"], ma["git_head"] == mb["git_head"], False,
    "reported; the input hashes decide")
rec("env", "", json.dumps(ma["env"]), json.dumps(mb["env"]), ma["env"] == mb["env"], False)
rec("versions", "", json.dumps(ma["versions"]), json.dumps(mb["versions"]),
    ma["versions"] == mb["versions"], False)

# Classes
ca, cb = sha256(A / "classes.csv"), sha256(B / "classes.csv")
xa = pd.read_csv(A / "classes.csv", dtype=str, keep_default_na=False)
xb = pd.read_csv(B / "classes.csv", dtype=str, keep_default_na=False)
j = xa.merge(xb, on=["utility", "key"], how="outer", suffixes=("_a", "_b"), indicator=True)
n_only = int((j._merge != "both").sum())
jb = j[j._merge == "both"]
n_cls = int((jb.src_a != jb.src_b).sum())
rec("classes_all", "ALL", ca, cb, n_only == 0 and n_cls == 0, True,
    f"stations only in one run: {n_only}; class differences: {n_cls}; file bytes equal: {ca == cb}")
for U, g in jb.groupby("utility"):
    d = int((g.src_a != g.src_b).sum())
    rec("classes", U, len(g), len(g), d == 0, True, f"class differences: {d}")
for col in ("cap", "level", "rbar", "q"):
    fa = pd.to_numeric(jb[f"{col}_a"], errors="coerce").values
    fb = pd.to_numeric(jb[f"{col}_b"], errors="coerce").values
    dif = np.nanmax(np.abs(fa - fb)) if np.isfinite(fa).any() else 0.0
    rec(f"classes_{col}_max_abs_diff", "ALL", "", "", float(dif) == 0.0, False, repr(float(dif)))

# Area totals
ta, tb = sha256(A / "area_totals.csv"), sha256(B / "area_totals.csv")
rec("area_totals_bytes", "ALL", ta, tb, ta == tb, True)

# Series
for U in ma["areas_written"]:
    fa, fb = A / f"ed_{U}.parquet", B / f"ed_{U}.parquet"
    ha, hb = sha256(fa), sha256(fb)
    if ha == hb:
        rec("series_sha256", U, ha, hb, True, False)
        continue
    pa_ = pd.read_parquet(fa); pb_ = pd.read_parquet(fb)
    same_idx = len(pa_) == len(pb_) and (pa_.station_id.values == pb_.station_id.values).all() \
        and (pa_.ts.values == pb_.ts.values).all()
    det = [f"rows {len(pa_)} vs {len(pb_)}", f"same station/ts order: {same_idx}"]
    if same_idx:
        for c in ("demand_net_mw", "demand_gross_mw", "pv_mw"):
            det.append(f"{c} max|diff| {float(np.max(np.abs(pa_[c].values - pb_[c].values))):.6g}")
        det.append(f"src differences {int((pa_.src.values != pb_.src.values).sum())}")
    rec("series_sha256", U, ha, hb, False, False, "; ".join(det))

rep = pd.DataFrame(rows)
REPORT.parent.mkdir(parents=True, exist_ok=True)
rep.to_csv(REPORT, index=False, encoding="utf-8")
gate = rep[rep.part_of_criterion_D]
ok = bool(gate.equal.all())
print(rep[["item", "area", "equal", "part_of_criterion_D", "detail"]].to_string(index=False))
print(f"\n[report] {REPORT}")
print(f"Criterion D: {'PASS' if ok else 'FAIL'} (classes identical, area totals byte-identical, same inputs)")
sys.exit(0 if ok else 1)
