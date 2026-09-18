# -*- coding: utf-8 -*-
"""Criterion A: calibration-area substation-level accuracy of v6.6 against v6.5
(ACCEPTANCE_CRITERIA_R1.md, criterion A; RERUN_PLAN_R1.md Step 10a).

Population: the 1,216 substations of v65_micro_clean.csv (the same set as in v6.5). Metrics: median APE of
the annual mean, median hourly Pearson r, median hourly CV-RMSE, for all 1,216 and by v6.6 class. Pass per
metric: APE worsens by at most 2 percentage points, r falls by at most 0.02, CV-RMSE worsens by at most
5 percentage points. The per-substation metrics are those of the canonical clean_truth_and_recompute.py;
this script only takes medians (rounded as recompute_all_clean.py rounds them) and compares.

Sources of the v6.6 per-substation metrics (one of):
  default    results/micro/v66_micro_clean.csv, written by the canonical Step 10 chain
             (PAPER_EST_REL=lab_data.ed_rerun_v66 clean_truth_and_recompute.py)
  --run DIR  the canonical scripts executed verbatim on the run's Tokyo series through the file harness
             (v66_common.canonical_micro); needs only the frozen database for the roster statement
  --offline  the same on the offline file named by PAPER_EST_FILE (v6.5 file: a self-test, all changes 0)
The class-wise comparison is accompanied by the Tokyo transition matrix of the 1,216 (criterion A, last
sentence). Evaluation only: ground truth is read after the estimate exists and enters no estimator.

Outputs (tag v66): results/numbers/criterion_a_v66.csv, criterion_a_v66.json,
                   criterion_a_transition_v66.csv
"""
import argparse, json, pathlib, sys, tempfile
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group()
g.add_argument("--micro", help="per-substation metrics CSV (default results/micro/<tag>_micro_clean.csv)")
g.add_argument("--run", help="run directory: compute the metrics through the file harness")
g.add_argument("--offline", action="store_true", help="offline file of PAPER_EST_FILE, through the harness")
ap.add_argument("--tag", default=None)
ap.add_argument("--keep-harness", help="directory to keep the harness outputs in")
a = ap.parse_args()

ref, pop = C.reference_v65()
if a.run or a.offline:
    E = C.engine_offline()
    if a.run:
        C.check_run_dir(a.run)
        tok, tag = C.TokyoSeries.from_run(a.run, E.IDX), a.tag or "v66"
    else:
        import est_source
        f, t = est_source.offline_source()
        tok, tag = C.TokyoSeries.from_offline(f, E.IDX), a.tag or t
    root = pathlib.Path(a.keep_harness) if a.keep_harness else pathlib.Path(tempfile.mkdtemp(prefix="crit_a_"))
    paths = C.canonical_micro(tok, tag, root, root / "harness.log")
    micro_p, all_p, source = paths["micro_clean.csv"], paths["clean_all.json"], f"harness:{tok.label}"
else:
    tag = a.tag or "v66"
    micro_p = pathlib.Path(a.micro) if a.micro else C.W / "results" / "micro" / f"{tag}_micro_clean.csv"
    all_p = micro_p.with_name(micro_p.name.replace("_micro_clean.csv", "_clean_all.json"))
    source = f"file:{micro_p.name}"

micro = pd.read_csv(micro_p, encoding="utf-8-sig")
got = set(micro.key)
pop_note = "identical to v6.5" if got == pop else (f"differs from v6.5: {len(got - pop)} added "
                                                    f"{sorted(got - pop)[:5]}, {len(pop - got)} missing {sorted(pop - got)[:5]}")
print(f"[population] v6.6 screened set {len(got)}, v6.5 {len(pop)}: {pop_note}")
new = C.medians(micro, keys=pop)                       # the criterion's population: the v6.5 set

# When the v6.6 set equals v6.5, the medians must equal the canonical JSON of the same run
if got == pop and all_p.exists():
    ca = json.loads(all_p.read_text(encoding="utf-8"))
    assert (new["all"]["ape"], new["all"]["corr"]) == (ca["overall"]["ape"], ca["overall"]["corr"])
    for s in C.CLASSES:
        if s in ca["tiers"]:
            t = ca["tiers"][s]
            assert (new[s]["n"], new[s]["ape"], new[s]["corr"], new[s]["cvrmse"]) == \
                   (t["n"], t["ape"], t["corr"], t["cvrmse"]), f"{s}: medians differ from {all_p.name}"
    print(f"[check] medians equal the canonical {all_p.name}")

rows = C.criterion_a_rows(new, ref)
old = pd.read_csv(C.W / "results" / "micro" / "v65_micro_clean.csv", encoding="utf-8-sig")[["key", "src"]]
tr = old.merge(micro[["key", "src"]], on="key", how="inner", suffixes=("_v65", "_v66"))
T = pd.crosstab(tr.src_v65, tr.src_v66).reindex(index=C.CLASSES, columns=C.CLASSES, fill_value=0)
stable = {s: C.medians(micro[micro.key.isin(tr[(tr.src_v65 == s) & (tr.src_v66 == s)].key)])["all"]
          for s in C.CLASSES}

p1 = C.out_path("results/numbers", f"criterion_a_{tag}.csv", tag)
p2 = C.out_path("results/numbers", f"criterion_a_{tag}.json", tag)
p3 = C.out_path("results/numbers", f"criterion_a_transition_{tag}.csv", tag)
rows.to_csv(p1, index=False, encoding="utf-8-sig", lineterminator="\n")
T.rename_axis(index="v65_class", columns="v66_class").to_csv(p3, encoding="utf-8-sig", lineterminator="\n")
fails = rows[~rows.passed]
C.write_json(p2, dict(
    criterion="A", source=source, population=dict(n_v65=len(pop), n_v66_screened=len(got), note=pop_note),
    tolerances=C.TOL, reference_v65=ref, v66=new,
    passed=bool(len(fails) == 0),
    failures=fails[["population", "metric", "v65", "v66", "worsening", "tolerance"]].to_dict("records"),
    transition_1216={f"{r} -> {c}": int(T.at[r, c]) for r in C.CLASSES for c in C.CLASSES},
    stable_class_medians=stable,
    note=("Class-wise rows use the v6.6 class of each substation. The criteria file quotes no CV-RMSE for "
          "all 1,216; its v6.5 value is the median of v65_micro_clean.csv. Changes are computed on medians "
          "rounded as recompute_all_clean.py rounds them.")))
print(rows.to_string(index=False))
print(f"\nCriterion A: {'PASS' if len(fails) == 0 else 'FAIL on ' + str(len(fails)) + ' metric(s)'}")
print(T.to_string())
print(f"[out] {p1}\n[out] {p2}\n[out] {p3}")
