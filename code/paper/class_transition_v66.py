# -*- coding: utf-8 -*-
"""Old-to-new class transition matrix by area (RERUN_PLAN_R1.md Step 7; criterion E; review E7).

Three steps are reported for every area, so that the v6.5 -> v6.6 matrix is not misread (plan Section 9,
risk 2):
  v65_to_v66    the stored v6.5 class (offline layer) -> the v6.6 class (run classes.csv)
  kappa_only    the stored v6.5 class -> the class the v6.5 engine gives on the frozen level file
                (experiments/e5_confirm/e5_classes.csv, column class_frozen). In nine areas this removes
                kappa = 1.0383 only; in Okinawa it also removes the published-loading anchor.
  rest          class_frozen -> the v6.6 class: removal of the operating probability p, the v6.6 lambda_a,
                the E5 tie-breaks. (E3 changes no class: plan Section 3.)

Basis: the 5,968 listed names (station_key_map kind='master' x substation_master node_type='haihen' x
the estimate's keys), as every paper number. The 6,270 engine keys are reported too, to reconcile with
the run manifests. Reads files only; no database.

  python code/paper/class_transition_v66.py --run results/rerun_v66/run_a
  PAPER_EST_FILE=estimated_demand_fy2024_v66.parquet python code/paper/class_transition_v66.py --offline

Outputs (tag v66): results/numbers/class_transition_v66.csv (long: basis, step, utility, from, to, n)
                   results/numbers/class_transition_v66_summary.csv (per area and step: stations, moved,
                   class counts before and after)
"""
import argparse, pathlib, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group()
g.add_argument("--run", default=str(C.W / "results" / "rerun_v66" / "run_a"), help="v6.6 run directory")
g.add_argument("--offline", action="store_true", help="v6.6 classes from the offline file named by PAPER_EST_FILE")
ap.add_argument("--v65-file", default="estimated_demand_fy2024.parquet")
ap.add_argument("--e5", default=str(C.W / "experiments" / "e5_confirm" / "e5_classes.csv"))
ap.add_argument("--tag", default="v66")
ap.add_argument("--allow-smoke", action="store_true", help="test on a smoke run (one area)")
a = ap.parse_args()

old = C.per_key_offline(a.v65_file)[["utility", "key", "src"]]
if a.offline:
    import est_source
    f, t = est_source.offline_source()
    if t == "v65":
        sys.exit("[FATAL] --offline needs PAPER_EST_FILE=estimated_demand_fy2024_v66.parquet")
    new = C.per_key_offline(f)[["utility", "key", "src"]]
    src_label = f"offline:{f}"
else:
    run, man = C.check_run_dir(a.run, allow_smoke=a.allow_smoke)
    new = C.classes_run(run)[["utility", "key", "src"]]
    src_label = f"run:{run.name} (git {man['git_head'][:7]})"
areas = [u for u in C.ORDER if u in set(new.utility)]
old = old[old.utility.isin(areas)]

e5 = pd.read_csv(a.e5, encoding="utf-8-sig", dtype={"key": str})
e5 = e5[e5.utility.isin(areas)][["utility", "key", "stored_src", "class_frozen"]]

# The three class sources must cover the same engine keys, and e5's stored class must be the offline one
ko, kn, ke = (set(map(tuple, x[["utility", "key"]].values)) for x in (old, new, e5))
if not (ko == kn == ke):
    sys.exit(f"[FATAL] key sets differ: v6.5 {len(ko)}, v6.6 {len(kn)}, e5 {len(ke)}; "
             f"v6.5-only {sorted(ko - kn)[:5]}, v6.6-only {sorted(kn - ko)[:5]}")
chk = old.merge(e5, on=["utility", "key"])
bad = chk[chk.src != chk.stored_src]
if len(bad):
    sys.exit(f"[FATAL] e5_classes.csv stored_src differs from the offline v6.5 class for {len(bad)} keys")

K = (old.rename(columns={"src": "c65"})
        .merge(e5.rename(columns={"class_frozen": "cfz"})[["utility", "key", "cfz"]], on=["utility", "key"])
        .merge(new.rename(columns={"src": "c66"}), on=["utility", "key"]))
names = C.list_basis(new[["utility", "key"]])
N = names.merge(K, on=["utility", "key"], how="left")
assert N.c65.notna().all() and N.c66.notna().all()
print(f"[basis] {len(N)} listed names on {N[['utility','key']].drop_duplicates().shape[0]} keys; "
      f"{len(K)} engine keys; v6.6 source {src_label}")
if not a.allow_smoke:
    assert len(N) == 5968, f"list basis is {len(N)}, not 5,968"

STEPS = [("v65_to_v66", "c65", "c66"), ("kappa_only", "c65", "cfz"), ("rest", "cfz", "c66")]
long, summ = [], []
for basis, D in (("list_names_5968", N), ("engine_keys_6270", K)):
    for step, fc, tc in STEPS:
        for U in areas + ["TOTAL"]:
            x = D if U == "TOTAL" else D[D.utility == U]
            for f_ in C.CLASSES:
                for t_ in C.CLASSES:
                    long.append(dict(basis=basis, step=step, utility=U, area=C.JA.get(U, "Total"),
                                     from_class=f_, to_class=t_,
                                     n=int(((x[fc] == f_) & (x[tc] == t_)).sum())))
            rec = dict(basis=basis, step=step, utility=U, area=C.JA.get(U, "Total"), stations=len(x),
                       moved=int((x[fc] != x[tc]).sum()))
            for s in C.CLASSES:
                rec[f"before_{s}"] = int((x[fc] == s).sum()); rec[f"after_{s}"] = int((x[tc] == s).sum())
            rec["note"] = ("kappa and the Okinawa anchor removed" if (step == "kappa_only" and U == "OKINAWA")
                           else "kappa removed" if step == "kappa_only" else "")
            summ.append(rec)
L, S = pd.DataFrame(long), pd.DataFrame(summ)
p1 = C.out_path("results/numbers", f"class_transition_{a.tag}.csv", a.tag)
p2 = C.out_path("results/numbers", f"class_transition_{a.tag}_summary.csv", a.tag)
L.to_csv(p1, index=False, encoding="utf-8-sig", lineterminator="\n")
S.to_csv(p2, index=False, encoding="utf-8-sig", lineterminator="\n")
v = S[(S.basis == "list_names_5968")]
print(v[["step", "area", "stations", "moved", "before_z1", "before_z1s", "before_z2",
         "after_z1", "after_z1s", "after_z2"]].to_string(index=False))
print(f"[out] {p1}\n[out] {p2}")
