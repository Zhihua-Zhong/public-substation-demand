# -*- coding: utf-8 -*-
"""Criterion G: the screened-anchor variant of the v6.6 level input, and the anchor-evaluation population
reconciliation (ACCEPTANCE_CRITERIA_R1.md, criterion G; SUPERVISOR_DECISIONS_R1.md section 2, E2).

The canonical build_level_v66.py is executed verbatim, offline, in a scratch copy of the workspace layout
(its outputs must equal the committed station_levels_v66.csv and level_model_v66.json byte for byte, which
this script asserts). From its own namespace it then takes the purified Tokyo roster with ground truth
(`ros`), the area indices (`idx`) and the level table (`lv`), and applies ONE change: the plausibility
screen of line 124 (ground truth / capacity <= 1), which the canonical script applies to the regression
only, is applied to the anchor numerator as well. The denominator (total capacity of the purified roster)
is unchanged, as in the E2 computation. lambda_0 is rounded to 4 decimals, as lambda_tepco is, and every
area's lambda_a = lambda_0 x idx_a / idx_Tokyo, level = C x lambda_a: every level x 0.2651/0.3501.

Expected (SUPERVISOR_DECISIONS_R1.md section 2): 29 over-capacity substations, 5,590 MW (24.3 % of the
numerator), lambda_0 = 0.2651. Asserted.

The variant is a sensitivity input only. It is run through the engine with
PAPER_LEVEL_FILE=results/numbers/station_levels_v66_screened.csv (patches/criterion_g_level_file.patch)
into results/rerun_v66/sens_screened/ and is never loaded as the main result.

Outputs: results/numbers/station_levels_v66_screened.csv, level_model_v66_screened.json,
         anchor_population_reconciliation_v66.csv
Offline layer only; no database.
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--eval-tag", default="v66", help="tag of the admission-test outputs in results/micro "
                "(falls back to v65, whose population the rerun must reproduce)")
a = ap.parse_args()
E = C.engine_offline()                   # build_level_v66.py imports norm2 from stage2_engine
NUM = C.W / "results" / "numbers"
CANON = "code/paper/build_level_v66.py"

tmp = pathlib.Path(tempfile.mkdtemp(prefix="lv66scr_"))
junction = tmp / "data"
try:
    (tmp / "results" / "numbers").mkdir(parents=True)
    shutil.copyfile(NUM / "ledger_whitelist_v65.csv", tmp / "results" / "numbers" / "ledger_whitelist_v65.csv")
    (tmp / "code" / "engine" / "analysis" / "unified" / "out").mkdir(parents=True)
    shutil.copyfile(C.ENG_OUT / "national_verdict_v5.csv",
                    tmp / "code" / "engine" / "analysis" / "unified" / "out" / "national_verdict_v5.csv")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str((C.W / "data").resolve())],
                   check=True, capture_output=True)          # a link, not a copy: no data added
    fake = tmp / CANON
    fake.parent.mkdir(parents=True)
    ns = {"__name__": "__main__", "__file__": str(fake)}
    with open(tmp / "build_level_v66.log", "w", encoding="utf-8") as fh:
        import contextlib
        with contextlib.redirect_stdout(C._Log(fh)):
            exec(compile((C.W / CANON).read_text(encoding="utf-8"), str(fake), "exec"), ns)
    for f in ("station_levels_v66.csv", "level_model_v66.json"):
        same = (tmp / "results" / "numbers" / f).read_bytes() == (NUM / f).read_bytes()
        assert same, f"the canonical build_level_v66.py no longer reproduces the committed {f}"
    print("[canonical] build_level_v66.py reproduces station_levels_v66.csv and level_model_v66.json byte for byte")
finally:
    if junction.exists():
        os.rmdir(junction)                                     # removes the link only
    shutil.rmtree(tmp, ignore_errors=True)

ros, R0, idx, lv = ns["ros"], ns["R"], ns["idx"], ns["lv"].copy()
ld = ros[ros.load].copy()
ld["lf"] = ld.truth / ld.cap
over = ld[ld.lf > 1.0]                                       # the screen of build_level_v66.py:124
cap_total = float(ros.cap.sum())
num_all, num_scr = float(ld.truth.sum()), float(ld[ld.lf <= 1.0].truth.sum())
lam_c, lam_s = R0["lambda_tepco"], round(num_scr / cap_total, 4)
assert round(num_all) == R0["truth_sum_mw"] and round(cap_total) == R0["cap_total_mw"]
assert (len(over), round(num_all - num_scr), lam_s) == (29, 5590, 0.2651), \
    (len(over), round(num_all - num_scr), lam_s)
LAM = {u: lam_s * idx[u] / idx["TEPCO"] for u in C.ORDER}
lv["lambda"] = lv.utility.map(LAM)
lv["level"] = lv.cap * lv["lambda"]
pl = C.out_path("results/numbers", "station_levels_v66_screened.csv", "v66")
lv[["utility", "key", "cap", "lambda", "level"]].sort_values(["utility", "key"]).to_csv(
    pl, index=False, encoding="utf-8-sig")

# Reconciliation of the anchor population with the evaluation population (criterion G, last sentence)
mic = C.W / "results" / "micro"
et = a.eval_tag if (mic / f"{a.eval_tag}_micro_clean.csv").exists() else "v65"
ev = pd.read_csv(mic / f"{et}_micro_clean.csv", encoding="utf-8-sig")
dr = pd.read_csv(mic / f"{et}_truth_dropped.csv", encoding="utf-8-sig")
ov_keys, dr_keys, ev_keys = set(over.key), set(dr.key), set(ev.key)
rows = [
    ("anchor", "purified calibration-area roster", R0["roster_purified"], round(cap_total), "capacity MW"),
    ("anchor", "with ground truth above 0.5 MW (anchor numerator)", R0["n_loaded"], round(num_all), "ground truth MW"),
    ("anchor", "of which ground truth exceeds capacity", len(over), round(num_all - num_scr), "ground truth MW"),
    ("anchor", "screened anchor numerator", R0["n_loaded"] - len(over), round(num_scr), "ground truth MW"),
    ("evaluation", "series with ground truth and an estimate (>= 3,000 h, mean >= 0.5 MW)", len(ev) + len(dr), None, ""),
    ("evaluation", "screened out (ground truth exceeds capacity or no capacity)", len(dr), None, ""),
    ("evaluation", "evaluated", len(ev), None, ""),
    ("overlap", "anchor over-capacity keys among the evaluation's screened-out keys", len(ov_keys & dr_keys), None, ""),
    ("overlap", "anchor over-capacity keys among the evaluated keys", len(ov_keys & ev_keys), None, ""),
    ("overlap", "anchor over-capacity keys absent from the evaluation", len(ov_keys - dr_keys - ev_keys), None, ""),
]
rec = pd.DataFrame(rows, columns=["side", "item", "substations", "mw", "unit"])
pr = C.out_path("results/numbers", "anchor_population_reconciliation_v66.csv", "v66")
rec.to_csv(pr, index=False, encoding="utf-8-sig", lineterminator="\n")

pj = C.out_path("results/numbers", "level_model_v66_screened.json", "v66")
C.write_json(pj, dict(
    variant="screened anchor (criterion G sensitivity; never the main result)",
    lambda_tepco_canonical=lam_c, lambda_tepco_screened=lam_s, scale_vs_canonical=round(lam_s / lam_c, 4),
    anchor_n_loaded=R0["n_loaded"], anchor_n_over_capacity=len(over),
    anchor_mw_removed=round(num_all - num_scr), anchor_share_removed_pct=round(100 * (num_all - num_scr) / num_all, 1),
    cap_total_mw=round(cap_total), lambda_by_area={C.JA[u]: round(LAM[u], 4) for u in C.ORDER},
    n_keys=int(len(lv)), evaluation_population_tag=et,
    inputs_sha256={"station_levels_v66.csv": C.sha256(NUM / "station_levels_v66.csv"),
                   "level_model_v66.json": C.sha256(NUM / "level_model_v66.json"),
                   CANON: C.sha256(C.W / CANON)}))
print(f"lambda_0: canonical {lam_c}, screened {lam_s} (x{lam_s/lam_c:.4f}); removed {len(over)} substations, "
      f"{round(num_all-num_scr)} MW ({100*(num_all-num_scr)/num_all:.1f} %)")
print(rec.to_string(index=False))
print(f"[out] {pl}\n[out] {pj}\n[out] {pr}")
