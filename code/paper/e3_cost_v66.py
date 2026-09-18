# -*- coding: utf-8 -*-
"""Cost of E3, for reporting only (ACCEPTANCE_CRITERIA_R1.md, "Cost of E3, declared in advance").

The v6.5 calibration-area residual corrections (12 monthly factors, 24 x 4 hour-by-season factors) are
applied offline to the v6.6 Tokyo output, exactly as the deleted engine block applied them: Class 3
series only, multiplied by the factor, then rescaled to each series' own annual mean
(v66_common.retired_correction / apply_retired; tests/test_e3_equivalence.py runs the deleted block
from git history and compares). The corrected series are rounded to 3 decimals, as the run files are.
The corrections never re-enter the estimator: this script reads the run's files and writes a report.

Both arms, v6.6 as run ("without") and v6.6 with the retired factors ("with"), go through the same
canonical scripts, executed verbatim by the file harness (clean_truth_and_recompute.py,
recompute_all_clean.py). Reported: the criterion A medians and pass/fail of each arm, the floor test
(CV of the monthly ratios with the canonical i.i.d. intervals), and which criterion A shortfalls the
comparison attributes to the removal (fails without, passes with): the cost of uniformity.

  python code/paper/e3_cost_v66.py --run results/rerun_v66/run_a

Outputs (tag v66): results/micro/v66_e3_cost.json, v66_e3_cost_by_class.csv,
                   v66_e3cost_floor_monthly_without.csv, v66_e3cost_floor_monthly_with.csv
                   (the last two feed floor_bootstrap_v66.py)
"""
import argparse, json, pathlib, shutil, sys, tempfile
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--run", default=str(C.W / "results" / "rerun_v66" / "run_a"))
ap.add_argument("--tag", default="v66")
ap.add_argument("--keep-harness", help="directory to keep the harness outputs in")
a = ap.parse_args()

E = C.engine_offline()
run, man = C.check_run_dir(a.run)
MF_P, HS_P = C.ENG_OUT / "monthly_factor_tepco.json", C.ENG_OUT / "hourshape_factor_tepco.json"
MF = json.loads(MF_P.read_text(encoding="utf-8"))
HS = json.loads(HS_P.read_text(encoding="utf-8"))
assert len(MF) == 12 and all(len(HS[s]) == 24 for s in ("spring", "summer", "autumn", "winter"))

tok = C.TokyoSeries.from_run(run, E.IDX)
corr = C.retired_correction(E.IDX, MF, HS)
net_e3 = np.round(C.apply_retired(tok.net, tok.src, corr), 3)
tok_e3 = C.TokyoSeries(tok.keys, tok.src, net_e3, tok.label + "+retired_E3_factors")
z2 = tok.src == "z2"
dev_mean = float(np.max(np.abs(net_e3[z2].mean(axis=1) - tok.net[z2].mean(axis=1))))
untouched = bool((net_e3[~z2] == tok.net[~z2]).all())
print(f"[factors] Class 3 series corrected: {int(z2.sum())}; other classes untouched: {untouched}; "
      f"max |annual mean change| {dev_mean:.2e} MW (rounding only)")
assert untouched and dev_mean < 1e-3

root = pathlib.Path(a.keep_harness) if a.keep_harness else pathlib.Path(tempfile.mkdtemp(prefix="e3cost_"))
arms = {}
for arm, t in (("without", tok), ("with", tok_e3)):
    p = C.canonical_micro(t, a.tag, root / arm, root / "harness.log")
    micro = pd.read_csv(p["micro_clean.csv"], encoding="utf-8-sig")
    ca = json.loads(p["clean_all.json"].read_text(encoding="utf-8"))
    arms[arm] = dict(micro=micro, clean_all=ca, floor_csv=p["floor_monthly.csv"])

ref, pop = C.reference_v65()
res, long = {}, []
for arm, d in arms.items():
    med = C.medians(d["micro"], keys=pop)
    rows = C.criterion_a_rows(med, ref)
    res[arm] = dict(n_screened=int(len(d["micro"])), medians=med, criterion_a=rows.to_dict("records"),
                    criterion_a_passed=bool(rows.passed.all()), floor=d["clean_all"]["floor"])
    res[arm]["_rows"] = rows
    # Only the classes the run has: after criterion F there is no measured-shape class (z1s).
    for grp in ["all"] + [c for c in C.CLASSES if c in med]:
        for k in ("ape", "corr", "cvrmse"):
            long.append(dict(population=grp if grp == "all" else C.CLASS_NAME[grp], src=grp, metric=k,
                             arm=arm, value=med[grp][k]))
L = pd.DataFrame(long).pivot_table(index=["population", "src", "metric"], columns="arm",
                                   values="value", aggfunc="first").reset_index()
L["with_minus_without"] = (L["with"] - L["without"]).round(3)
fl = []
for k in ("cv_truth_egc", "cv_est_egc", "cv_est_truth", "mean_est_truth"):
    fl.append(dict(population="floor test", src="", metric=k, without=res["without"]["floor"][k],
                   with_=res["with"]["floor"][k]))
F = pd.DataFrame(fl).rename(columns={"with_": "with"})
F["with_minus_without"] = (F["with"] - F["without"]).round(4)
out_tab = pd.concat([L[["population", "src", "metric", "without", "with", "with_minus_without"]], F],
                    ignore_index=True)

rw, re_ = res["without"].pop("_rows"), res["with"].pop("_rows")
j = rw.merge(re_, on=["population", "metric"], suffixes=("_without", "_with"))
attributed = j[(~j.passed_without) & (j.passed_with)][["population", "metric", "v66_without", "v66_with",
                                                        "tolerance_without"]]
other = j[(~j.passed_without) & (~j.passed_with)][["population", "metric", "v66_without", "v66_with"]]

p1 = C.out_path("results/micro", f"{a.tag}_e3_cost.json", a.tag)
p2 = C.out_path("results/micro", f"{a.tag}_e3_cost_by_class.csv", a.tag)
for arm in ("without", "with"):
    shutil.copyfile(arms[arm]["floor_csv"],
                    C.out_path("results/micro", f"{a.tag}_e3cost_floor_monthly_{arm}.csv", a.tag))
out_tab.to_csv(p2, index=False, encoding="utf-8-sig", lineterminator="\n")
C.write_json(p1, dict(
    purpose="cost of E3, reporting only; the corrections never re-enter the estimator",
    run=str(run.name), run_git_head=man["git_head"],
    factors={"monthly_factor_tepco.json": C.sha256(MF_P), "hourshape_factor_tepco.json": C.sha256(HS_P)},
    n_class3_corrected=int(z2.sum()), max_abs_annual_mean_change_mw=dev_mean,
    arms=res,
    shortfalls_attributed_to_E3=attributed.to_dict("records"),
    shortfalls_not_attributed=other.to_dict("records"),
    note="Class-wise rows use the v6.6 class. The floor intervals are the canonical i.i.d. ones; "
         "floor_bootstrap_v66.py adds the block bootstrap for both arms."))
print(out_tab.to_string(index=False))
print(f"\ncriterion A without: {'PASS' if res['without']['criterion_a_passed'] else 'FAIL'}; "
      f"with retired factors: {'PASS' if res['with']['criterion_a_passed'] else 'FAIL'}")
print("shortfalls attributed to E3:", attributed.to_dict("records"))
print(f"[out] {p1}\n[out] {p2}")
