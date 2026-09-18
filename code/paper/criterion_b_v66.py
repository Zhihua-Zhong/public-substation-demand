# -*- coding: utf-8 -*-
"""Criterion B (and C): annual coverage against each area's loss-scaled band
(ACCEPTANCE_CRITERIA_R1.md, criteria B and C; RERUN_PLAN_R1.md Step 10a).

Band of area a: [1.02, 1.08] x loss ratio_a / median(loss ratio), loss ratio = area supply-demand record /
total sales across all voltage levels, from public statistics only. It is rebuilt from the offline layer
and must equal experiments/level_validation/O_loss_adjusted.csv, the file the criteria name
(v66_common.loss_band). Signed gap = estimate-to-sales ratio minus the band, in percentage points:
0 inside, negative below, positive above. Okinawa is judged against its own band like every other area
(criterion C). No coefficient is adjusted whatever the result.

The ratio is the canonical Annual (%) of calc_annual_monthly_v65.py (one decimal), the number that
Table 5 and Fig. 4 carry; an area within 0.05 percentage points of a band edge is flagged, because
rounding could then decide inside or outside.

Sources of the ratio (one of):
  default    results/numbers/annual_monthly_<tag>.csv (canonical; PAPER_EST_FILE names the estimate)
  --run DIR  computed from a run directory by the same definition (a pre-check before the offline file
             exists; tests/test_common_v65.py shows it equals the canonical file on v6.5)
Also used for the criterion G sensitivity: --run results/rerun_v66/sens_screened --tag v66_sens_screened.

Outputs: results/numbers/band_gap_<tag>.csv, band_gap_<tag>.json
"""
import argparse, pathlib, sys
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group()
g.add_argument("--annual", help="annual_monthly CSV (default results/numbers/annual_monthly_<tag>.csv)")
g.add_argument("--run", help="run directory (pre-check route)")
ap.add_argument("--tag", default="v66")
a = ap.parse_args()

b = C.loss_band()
if a.run:
    run, man = C.check_run_dir(a.run)
    ann = C.annual_pct_from_means(C.per_key_run(run)).map(lambda v: round(v, 1))
    source = f"run:{run.name} (git {man['git_head'][:7]}; level file {man.get('level_file')})"
else:
    p = pathlib.Path(a.annual) if a.annual else C.W / "results" / "numbers" / f"annual_monthly_{a.tag}.csv"
    ann = pd.read_csv(p, encoding="utf-8-sig").set_index("utility")["Annual_pct"]
    source = f"file:{p.name}"

rows = []
for u in C.ORDER:
    x = float(ann[u]); lo, hi = float(b.at[u, "band_lo"]), float(b.at[u, "band_hi"])
    gap = C.signed_gap_pp(x, lo, hi)
    edge = min(abs(x - 100 * lo), abs(x - 100 * hi))
    rows.append(dict(Area=C.JA[u], utility=u, loss_ratio=round(float(b.at[u, "loss_ratio"]), 4),
                     band_lo_pct=round(100 * lo, 2), band_hi_pct=round(100 * hi, 2), annual_pct=x,
                     gap_pp=C.half_up(gap, 1), inside=bool(gap == 0.0),
                     edge_distance_pp=round(edge, 2), edge_flag=bool(edge < 0.05),
                     inside_uniform_102_108=bool(102.0 <= x <= 108.0)))
R = pd.DataFrame(rows)
p1 = C.out_path("results/numbers", f"band_gap_{a.tag}.csv", a.tag)
p2 = C.out_path("results/numbers", f"band_gap_{a.tag}.json", a.tag)
R.to_csv(p1, index=False, encoding="utf-8-sig", lineterminator="\n")
oki = R[R.utility == "OKINAWA"].iloc[0]
C.write_json(p2, dict(
    criterion="B (and C for Okinawa)", source=source,
    n_inside=int(R.inside.sum()), areas_inside=R[R.inside].Area.tolist(),
    n_inside_uniform_band=int(R.inside_uniform_102_108.sum()),
    edge_flags=R[R.edge_flag].Area.tolist(),
    okinawa=dict(band_pct=[float(oki.band_lo_pct), float(oki.band_hi_pct)], annual_pct=float(oki.annual_pct),
                 gap_pp=float(oki.gap_pp), inside=bool(oki.inside)),
    rule="no coefficient is adjusted if an area falls outside its band"))
print(R.to_string(index=False))
print(f"\nareas inside their band: {int(R.inside.sum())} of 10  ({', '.join(R[R.inside].Area)})")
print(f"[out] {p1}\n[out] {p2}")
