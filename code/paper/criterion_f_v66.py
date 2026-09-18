# -*- coding: utf-8 -*-
"""Criterion F: Class 2 and the ceiling (ACCEPTANCE_CRITERIA_R1.md, criterion F; review E11/E12).

The rule, verbatim from the criteria file:
  "On the calibration-area substations that have a nodal balance and ground truth, compare, substation by
   substation, the measured-shape treatment with the transferred-shape treatment (Wilcoxon signed-rank test
   on hourly CV-RMSE), at ceilings of 3, 4, 6 and inf. If Class 2 does not beat Class 3 at p < 0.05,
   Class 2 is merged into Class 3. Otherwise the ceiling is the best-performing one, and it stays at 4 if
   the ceilings do not differ significantly. If this rule changes the classes, the estimator is run once
   more with the new rule, and that run must also pass D."

Treatments, all from the canonical engine (stage2_engine.py, imported, every query through the production
guard: SELECT only, no ground truth, no reference statistics, no earlier estimate):
  transferred shape (Class 3)   compute_region("TEPCO", blend=False)["net"]: every key built as Class 3
  measured shape   (Class 2)    L x R(t) / R-bar, the engine's Class 2 line, with R and L of the same call
  balance          (Class 1)    R(t), reported only
Population: the 1,216 screened substations of <tag>_micro_clean.csv with a usable balance (R-bar > 0.5 MW,
L > 0, the engine's condition), q = R-bar / L > 1.4 (the Class 2 range starts there). Metric: hourly
CV-RMSE of clean_truth_and_recompute.py (v66_common.station_metrics). Ground truth is read from the offline
layer only after the estimator has returned: evaluation, not estimation (CLAUDE.md rule 1).

Operational reading of the rule, fixed in this code before any v6.6 result was computed (MANIFEST.md
asks the supervisor to confirm it):
  R1  At ceiling c the Class 2 set is 1.4 < q <= c. "Class 2 beats Class 3" at c: two-sided Wilcoxon
      signed-rank p < 0.05 on the paired differences (measured - transferred) AND their median < 0.
      The one-sided p (alternative: measured < transferred) is reported beside it.
  R2  Class 2 is merged into Class 3 if it beats Class 3 at none of the four ceilings.
  R3  Otherwise every ceiling is scored on one common population (all q > 1.4): the rule of ceiling c
      assigns the measured shape to q <= c and the transferred shape above. Best-performing = the lowest
      median CV-RMSE among the ceilings at which Class 2 beats Class 3 (ties: 4, then the lower ceiling).
  R4  The ceiling stays at 4 unless the best rule differs from the ceiling-4 rule by a two-sided paired
      Wilcoxon test at p < 0.05 on the common population.
  Alternatives are reported for transparency: the merge decided at ceiling 4 alone, and the one-sided test.
Self-donor note: for q in [0.5, 2] a substation can be one of its own kNN donors, which favours the
transferred shape; the q > 2 subset is reported as well.

  DT_DB_CONTAINER=iwafune_db_frozen OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    python code/paper/criterion_f_v66.py [--check-run results/rerun_v66/run_a]

Outputs (tag v66): results/micro/v66_criterion_f_stations.csv, v66_criterion_f.json. Writes no table.
"""
import argparse, json, math, pathlib, sys
import numpy as np, pandas as pd
from scipy import stats as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
C.require_frozen_db()
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="v66")
ap.add_argument("--check-run", default=str(C.W / "results" / "rerun_v66" / "run_a"),
                help="run whose Class 3 series must equal the blend=False series (engine identity check)")
ap.add_argument("--from-stations", help="skip the engine: apply the rule to an existing stations CSV")
a = ap.parse_args()
CEILS = [3.0, 4.0, 6.0, math.inf]
RULE = ("On the calibration-area substations that have a nodal balance and ground truth, compare, substation "
        "by substation, the measured-shape treatment with the transferred-shape treatment (Wilcoxon signed-rank "
        "test on hourly CV-RMSE), at ceilings of 3, 4, 6 and ∞. If Class 2 does not beat Class 3 at p < 0.05, "
        "Class 2 is merged into Class 3. Otherwise the ceiling is the best-performing one, and it stays at 4 if "
        "the ceilings do not differ significantly. If this rule changes the classes, the estimator is run once "
        "more with the new rule, and that run must also pass D.")

mic = C.W / "results" / "micro"
pop_tag = a.tag if (mic / f"{a.tag}_micro_clean.csv").exists() else "v65"
POP = set(pd.read_csv(mic / f"{pop_tag}_micro_clean.csv", encoding="utf-8-sig").key)

if a.from_stations:
    S = pd.read_csv(a.from_stations, encoding="utf-8-sig"); engine_info = dict(source=a.from_stations)
else:
    import stage2_engine as E
    queries = C.guard_engine(E)
    r = E.compute_region("TEPCO", blend=False)          # every key as Class 3; no class decision applied
    keys, lev, R, Z2 = list(r["stations"]), r["lev"], r["R"], r["net"]
    assert set(r["src"]) == {"z2"}
    engine_info = dict(n_keys=len(keys), n_queries=len(queries), level_file=str(E.LEVEL_FILE.name),
                       level_sha256=E.level_input()[1])
    # Identity check: run A's Class 3 series are exactly these (rounded to 3 decimals in the run file)
    if a.check_run:
        tok = C.TokyoSeries.from_run(a.check_run, E.IDX)
        pos = {k: i for i, k in enumerate(keys)}
        z2 = [i for i, s in enumerate(tok.src) if s == "z2"]
        dmax = max(float(np.max(np.abs(tok.net[i] - np.round(Z2[pos[tok.keys[i]]], 3)))) for i in z2)
        engine_info["check_run_class3_max_abs_diff_mw"] = dmax
        print(f"[identity] run {pathlib.Path(a.check_run).name}: {len(z2)} Class 3 series, max |diff| {dmax:.2e} MW")
        assert dmax < 1e-6, "blend=False does not reproduce the run's Class 3 series"
    tw = C.truth_wide(E.IDX, E.norm2)                   # ground truth only now, after the estimator
    rows = []
    for i, k in enumerate(keys):
        if k not in POP or k not in R.columns or k not in tw.columns:
            continue
        l, rm = float(lev.loc[k]), float(R[k].mean())
        if l <= 0 or rm <= 0.5:
            continue
        t = tw[k].values.astype(float)
        mm = C.station_metrics(l * (R[k].values / rm), t)
        mt_ = C.station_metrics(Z2[i].astype(float), t)
        mb = C.station_metrics(R[k].values.astype(float), t)
        if mm is None or mt_ is None:
            continue
        rows.append(dict(key=k, q=rm / l, level=l, rbar=rm, cv_measured=mm["cv"], cv_transferred=mt_["cv"],
                         cv_balance=mb["cv"] if mb else np.nan, corr_measured=mm["corr"],
                         corr_transferred=mt_["corr"], ape_measured=mm["ape"], ape_transferred=mt_["ape"],
                         self_donor_possible=bool(0.5 <= rm / l <= 2.0)))
    S = pd.DataFrame(rows).sort_values("key", kind="mergesort").reset_index(drop=True)


def wil(d, alternative="two-sided"):
    d = np.asarray(d, float)
    if (d != 0).sum() < 1:
        return float("nan")
    return float(st.wilcoxon(d, zero_method="wilcox", alternative=alternative).pvalue)


Q = S[S.q > 1.4].copy()
per_c, wins, wins_1s = [], {}, {}
for c in CEILS:
    P = Q[Q.q <= c]
    d = (P.cv_measured - P.cv_transferred).to_numpy()
    p2, p1 = wil(d), wil(d, "less")
    med = float(np.median(d)) if len(d) else float("nan")
    wins[c] = bool(len(d) and p2 < 0.05 and med < 0)
    wins_1s[c] = bool(len(d) and p1 < 0.05)
    Pq2 = P[P.q > 2.0]; d2 = (Pq2.cv_measured - Pq2.cv_transferred).to_numpy()
    per_c.append(dict(ceiling=("inf" if math.isinf(c) else c), n=int(len(P)), median_cv_measured=float(P.cv_measured.median()),
                      median_cv_transferred=float(P.cv_transferred.median()), median_difference=med,
                      p_two_sided=p2, p_one_sided_less=p1, class2_beats_class3=wins[c],
                      class2_beats_class3_one_sided=wins_1s[c],
                      n_q_above_2=int(len(Pq2)), p_two_sided_q_above_2=wil(d2),
                      median_difference_q_above_2=float(np.median(d2)) if len(d2) else float("nan")))
rule_cv = {c: np.where(Q.q <= c, Q.cv_measured, Q.cv_transferred) for c in CEILS}
score = {c: float(np.median(rule_cv[c])) for c in CEILS}


def decide(wins_map):
    if not any(wins_map.values()):
        return dict(verdict="Class 2 is merged into Class 3.", merge=True, ceiling=None)
    cand = [c for c in CEILS if wins_map[c]]
    best = sorted(cand, key=lambda c: (score[c], c != 4.0, c))[0]
    if best == 4.0:
        return dict(verdict="The ceiling stays at 4.", merge=False, ceiling=4, best=4, p_best_vs_4=None)
    p = wil(rule_cv[best] - rule_cv[4.0])
    if not (p < 0.05):
        return dict(verdict="The ceiling stays at 4 (the ceilings do not differ significantly).", merge=False,
                    ceiling=4, best=("inf" if math.isinf(best) else best), p_best_vs_4=p)
    b = "∞" if math.isinf(best) else f"{best:g}"
    return dict(verdict=f"The ceiling is the best-performing one: {b}.", merge=False,
                ceiling=("inf" if math.isinf(best) else best), best=("inf" if math.isinf(best) else best), p_best_vs_4=p)


primary = decide(wins)
alt_one_sided = decide(wins_1s)
alt_merge_at_4 = "Class 2 is merged into Class 3." if not wins[4.0] else "Class 2 is kept (beats Class 3 at 4)."
changes_classes = primary["merge"] or primary["ceiling"] != 4
out = dict(criterion="F", rule_verbatim=RULE, operational_reading=["R1", "R2", "R3", "R4"],
           population=dict(screened_set=pop_tag, n_with_balance=int(len(S)), n_q_above_1_4=int(len(Q))),
           engine=engine_info, per_ceiling=per_c,
           common_population_median_cv={("inf" if math.isinf(c) else c): score[c] for c in CEILS},
           decision=primary, verdict=primary["verdict"],
           rule_changes_the_classes=bool(changes_classes),
           consequence=("the estimator is run once more with the new rule, and that run must also pass D"
                        if changes_classes else "no further run"),
           alternatives=dict(one_sided=alt_one_sided["verdict"], merge_decided_at_ceiling_4=alt_merge_at_4),
           readings_agree=bool(alt_one_sided["verdict"] == primary["verdict"] and
                               ((not wins[4.0]) == primary["merge"] or not primary["merge"])))
p1 = C.out_path("results/micro", f"{a.tag}_criterion_f_stations.csv", a.tag)
p2 = C.out_path("results/micro", f"{a.tag}_criterion_f.json", a.tag)
if not a.from_stations:
    S.to_csv(p1, index=False, encoding="utf-8-sig", lineterminator="\n")
C.write_json(p2, out)
print(pd.DataFrame(per_c).to_string(index=False))
print("common-population median CV-RMSE:", out["common_population_median_cv"])
print(f"VERDICT (primary reading): {primary['verdict']}   alternatives: {out['alternatives']}")
print(f"[out] {p1}\n[out] {p2}")
