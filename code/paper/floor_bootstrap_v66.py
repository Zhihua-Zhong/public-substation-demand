# -*- coding: utf-8 -*-
"""Floor-test intervals: circular block bootstrap next to the canonical i.i.d. bootstrap
(SUPERVISOR_DECISIONS_R1.md, "Technical decisions for the rerun", item 4; R2 minor 3; review E8).

Input: the 12 monthly ratios written by the canonical recompute_all_clean.py (<tag>_floor_monthly.csv:
truth / sales, estimate / sales, estimate / truth). Statistic: CV = std (ddof 0) / mean, as there.
  i.i.d.   the canonical intervals, reproduced exactly: 2,000 resamples of the 12 months with replacement,
           seed 20260722, in the canonical call order (three draws for the printout, then the three that
           are stored). They are checked against <tag>_clean_all.json when it is given.
  block    circular block bootstrap: blocks of 3 consecutive months with wrap-around (March joins April),
           4 blocks per resample, 2,000 resamples, seed 20260915. The reported interval.
Percentile intervals, 2.5 and 97.5.

  python code/paper/floor_bootstrap_v66.py                                   # results/micro/v66_floor_monthly.csv
  python code/paper/floor_bootstrap_v66.py --floor A.csv B.csv --label without with --tag v66_e3cost

Output: results/micro/<tag>_floor_bootstrap.json
"""
import argparse, json, pathlib, sys
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import v66_common as C
sys.stdout.reconfigure(encoding="utf-8")

SEED_IID, SEED_BLOCK, N_RES, BLOCK = 20260722, 20260915, 2000, 3
SERIES = [("truth_egc", "cv_truth_egc", "ci_truth_egc"), ("est_egc", "cv_est_egc", "ci_est_egc"),
          ("est_truth", "cv_est_truth", "ci_est_truth")]

ap = argparse.ArgumentParser()
ap.add_argument("--floor", nargs="+")
ap.add_argument("--label", nargs="+")
ap.add_argument("--clean-all", nargs="*", help="canonical clean_all JSON per floor file, for the i.i.d. check")
ap.add_argument("--tag", default="v66")
a = ap.parse_args()
floors = [pathlib.Path(p) for p in (a.floor or [C.W / "results" / "micro" / f"{a.tag}_floor_monthly.csv"])]
labels = a.label or [p.stem for p in floors]
if a.clean_all is None:
    cands = [p.with_name(p.name.replace("_floor_monthly.csv", "_clean_all.json")) for p in floors]
    checks = [c if c.exists() and c != p else None for c, p in zip(cands, floors)]
else:
    checks = [pathlib.Path(c) if c else None for c in a.clean_all]

cv = lambda v: float(np.std(v, ddof=0) / np.mean(v))


def pct(s):
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def iid(rng, v, n=N_RES):                    # recompute_all_clean.py:59-61
    return pct([cv(rng.choice(v, len(v), replace=True)) for _ in range(n)])


def block(rng, v, L=BLOCK, n=N_RES):
    m = len(v); nb = -(-m // L)
    s = []
    for _ in range(n):
        starts = rng.integers(0, m, size=nb)
        idx = ((starts[:, None] + np.arange(L)[None, :]) % m).ravel()[:m]
        s.append(cv(v[idx]))
    return pct(s)


out = dict(design=dict(statistic="CV = std(ddof=0)/mean of the 12 monthly ratios", n_resamples=N_RES,
                       iid=dict(seed=SEED_IID, note="canonical recompute_all_clean.py, reproduced"),
                       block=dict(kind="circular", block_length_months=BLOCK, blocks_per_resample=4,
                                  seed=SEED_BLOCK)),
           results={})
for p, lab, chk in zip(floors, labels, checks):
    f = pd.read_csv(p, encoding="utf-8-sig")
    assert len(f) == 12, f"{p}: {len(f)} months"
    rng = np.random.default_rng(SEED_IID)
    for col, _, _ in SERIES:                 # the three draws the canonical script prints and discards
        iid(rng, f[col].to_numpy())
    r = {}
    for col, kcv, kci in SERIES:
        r[col] = dict(cv=round(cv(f[col].to_numpy()), 4), ci_iid=iid(rng, f[col].to_numpy()))
    rb = np.random.default_rng(SEED_BLOCK)
    for col, _, _ in SERIES:
        r[col]["ci_block"] = block(rb, f[col].to_numpy())
    r["mean_est_truth"] = round(float(f.est_truth.mean()), 4)
    if chk is not None:
        fl = json.loads(pathlib.Path(chk).read_text(encoding="utf-8"))["floor"]
        for col, kcv, kci in SERIES:
            assert r[col]["cv"] == fl[kcv] and r[col]["ci_iid"] == fl[kci], \
                f"{lab} {col}: i.i.d. {r[col]} does not reproduce {chk.name} {fl[kcv]} {fl[kci]}"
        r["iid_check"] = f"equal to {chk.name}"
    out["results"][lab] = dict(source=p.name, **r)
    print(f"{lab}: " + "  ".join(f"{c} {r[c]['cv']} iid {r[c]['ci_iid']} block {r[c]['ci_block']}"
                                   for c, _, _ in SERIES) + f"  {r.get('iid_check', '')}")
po = C.out_path("results/micro", f"{a.tag}_floor_bootstrap.json", a.tag)
C.write_json(po, out)
print(f"[out] {po}")
