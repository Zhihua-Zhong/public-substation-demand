# Index of `code/paper/`

**The clean-up of 2026-07-29 deleted everything other than v6.5.** Every executable left here
runs on workspace-relative paths (no hard-coded paths into the old working tree). The classification below rests on
**measurement** (path checks and runs on the frozen database), not on what the index used to say.

The previous index wrongly listed four scripts as "ported". In fact they still used the old paths and did not run:
`baselines_and_ci.py`, `check_saturation_and_hc.py`, `gen_headroom_v63.py` and `gen_evidence_v63.py`.
The first three have been ported. The last had already been superseded (by `gen_scoreboard_table_v65.py` and others),
so it was deleted.

## 1. Inside the reproduction gate (offline layer only, no database)

`reproduce_paper.sh` runs these five every time and checks them against `results/numbers/`.

| Script | Output |
|---|---|
| `calc_annual_monthly_v65.py` | `annual_monthly_v65.csv` |
| `calc_spatial_hourly_v65.py` | `spatial_hourly_v65.csv` |
| `calc_truth_coverage_v65.py` | `truth_coverage_v65.csv` |
| `gen_scoreboard_table_v65.py` | `scoreboard_v65.csv` / `scoreboard_v65_rows.tex` (Table 3) |
| `build_level_v66.py` | `station_levels_v66.csv` (5,950 substations) / `level_model_v66.json` |
| `check_method_numbers.py` | No output. A check that compares the numbers in method §3.4 against the JSON above |

### About `build_level_v66.py`

It is **the canonical generator for item ② of the methods handbook (手法書), the net-flow level**, and succeeds
`p0_phantom_lf.py` (v6.5, DB required). It differs in only three ways; everything else keeps the definitional scope exactly.

1. The level equation drops the operating probability: `L = C × λ_a`
2. The anchor's denominator becomes the full registered capacity: `λ = Σground truth / Σcapacity(full filtered substation list) = 0.3501`
3. The transfer regression gains PV density

Because the level no longer needs per-substation covariates, every substation with a capacity gets a level (5,950 keys = 5,968 substations).
The Okinawa anchor based on officially published load has been dropped.

**Asserts pin down that the v6.5 anchor is reproduced exactly**
(filtered list 1,415 / loaded 1,196 / Σcap 56,757 / phantom 219 / 9,023MW / Σground truth 23,031 / LF_real 0.4058).
These values came from running `p0_phantom_lf.py` on the frozen DB, and the offline layer alone yields the same numbers.
If the definitional scope drifts, the asserts fail.

`check_method_numbers.py` checks the 18 numbers embedded in the prose of §3.4 against the JSON.
While only the core tables were guarded, a hand-copied "national median 19MW" (actually Okinawa's median) stayed wrong
for a long time. **The generator's output is correct and the text gets fixed. Never the other way round.**

## 2. Offline layer only, outside the gate

| Script | Purpose |
|---|---|
| `build_scoreboard_v65.py` | Partial recomputation of the national validation summary (cross-check of substation counts and measured classes) |
| `calc_monthly_harm_v65.py` | A **reimplementation** of meter-reading-date harmonization. Not canonical (see the caution below) |
| `calc_spatial_r_v65.py` | Prefecture-level approximation of the spatial correlation. Not canonical |
| `calc_spatial_r_muni_v65.py` / `calc_spatial_r_muni2_v65.py` | Municipality-level prototypes |
| `gen_fig_validation_v65.py` | `manuscript/figs/fig_validation.pdf` (Fig. 4: three dot plots of the ten-area validation metrics; only reads scoreboard_v65.csv) |
| `gen_fig_maps_v65.py` | `manuscript/figs/fig_maps3.pdf` (Fig. 5: class map, reverse-flow margin and load margin, with metropolitan and island insets; only reads v65_headroom.csv; replaces the unported v6.3 generator) |
| `audit_manuscript_numbers.py` | Audit tool that mechanically picks up the manuscript's numbers and checks them against the offline layer |
| `export_offline.py` | Generator of the offline layer itself (from the frozen DB) |
| `repair_manifest.py` | Repairs `MANIFEST.json` |

**Caution.** Monthly CV (raw/harm) and Spatial r in Table 3 come not from the reimplementations above but from
**the canonical results of record**: `results/frozen_inputs/examiner_harmonized_fy2024.csv` and
`code/engine/analysis/unified/out/p3_meti_spatial.csv`, frozen inputs that are not regenerated.
The reimplemented values do not match the canonical ones (weights of 0.10 to 0.61 against 0.30 to 0.75).
**Never judge the text against the reimplemented values.**

## 3. Needs the frozen database (`DT_DB_CONTAINER=iwafune_db_frozen` required)

| Script | Output | Notes |
|---|---|---|
| `clean_truth_and_recompute.py` | `results/micro/v65_micro_clean.csv` and others | Applies the admission test. 1,249 → 1,216 |
| `recompute_all_clean.py` | `results/micro/v65_clean_all.json` | **Canonical output for Table 1, Table 2 and the benchmark-noise floor**. 1,216 substations after cleaning |
| `baselines_and_ci.py` | `results/micro/v65_*_pretest.csv` | Diagnostics on the 1,249 substations **before the admission test**. Not cited in the text |
| `check_saturation_and_hc.py` | `v65_saturation_check.csv` / `v65_hc_join_diag.csv` | Saturation rate and match against available connection capacity (3,443 substations, 21 substations) |
| `gate_sensitivity.py` | `v65_gate_sensitivity.csv` | Sensitivity of the §4.1 acceptance thresholds (89→110→62 / 187→149→214) |
| `build_ledger_whitelist_v65.py` | `results/numbers/ledger_whitelist_v65.csv` | Whitelist for substation-list coverage (offline layer only, no DB) |
| `gen_headroom_v65.py` | `v65_headroom.csv` (reverse-flow and load margins); its legacy map goes to `logs/figs_intermediate/fig_maps3_legacy.pdf` and no longer overwrites Fig. 5 | Needs the whitelist |
| `regen_fig_examiner2.py` | `fig_examiner2.pdf` (Fig. 3, the single floor-test panel) | Does not rewrite the tex |
| `regen_fig_series4.py` | `fig_series4.pdf` (Fig. 2) | Same. Run `baselines_and_ci.py` first |

**The same-name collision trap (resolved 2026-07-29).** `baselines_and_ci.py` (before the admission test, 1,249 substations) and
`recompute_all_clean.py` (after the test, 1,216 substations) used to write to the same file name, `floor_monthly.csv`.
Running them in the wrong order silently corrupted the canonical output, and it did happen once.
The former's outputs now carry `_pretest`, which removes the collision. **Do not break this rule.**

**5,968 versus 5,950 (confuse them and you are off by 18 substations).** Both are substation-list coverage, counted from different sides.
Counting substation-list names gives 5,968 (the paper's headline figure and the Stations column of Table 3); counting estimate keys gives 5,950
(the number of series that actually exist). The difference of 18 is pairs of list names that fall onto the same estimate key: Kansai 15, Chubu 1,
Chugoku 1, Tohoku 1. They concentrate in Kansai because of norm2 key collisions. A figure plots one point per series, so it can only show
5,950. `build_ledger_whitelist_v65.py` can rebuild the whitelist from the offline layer.

## 3a. The v6.6 rerun (RERUN_PLAN_R1.md)

| Script | Purpose | Database |
|---|---|---|
| `code/engine/analysis/unified/run_stage2_to_files.py` | Runs the estimator for all ten areas and writes `results/rerun_v66/<tag>/` (series, classes, area totals, manifest). Replaces `persist_stage2_fy2024.py`, which now refuses to run in this workspace | SELECT only, through a deny-list guard |
| `compare_runs.py` | Determinism verdict between two runs (criterion D) → `results/rerun_v66/determinism_report.csv` | none |
| `load_rerun_table.py` | Loads one run into the separate table `lab_data.ed_rerun_v66`; `--drop` removes it and confirms the fingerprint of `lab_data.estimated_demand` | **writes that one table only** |

**Choosing the estimate.** Every script that reads the estimate goes through `code/engine/analysis/unified/est_source.py`. DB-bound readers need `PAPER_EST_REL` (`lab_data.estimated_demand_fy2024` for v6.5, `lab_data.ed_rerun_v66` for v6.6); it has no default, so a forgotten switch stops the script. Offline readers take `PAPER_EST_FILE` (default: the v6.5 parquet). Outputs carry the tag: `v65_*` or `*_v65` files are never overwritten by a v6.6 run. `baselines_and_ci.py` accepts only the v6.6 relation, because its part B runs the live engine, which is v6.6.

## 3b. v6.6 evaluation generators (acceptance criteria, E8, review round 1)

All read the estimate named by `PAPER_EST_REL` / `PAPER_EST_FILE` and write tagged outputs; ground truth is read only after the estimate exists. They run after the canonical chain of RERUN_PLAN_R1.md Step 10, in the order of the table; the logs of the run C chain are `logs/rerun_v66/c_*.log`.

| Script | Purpose | Database |
|---|---|---|
| `v66_common.py` | Shared plumbing: list basis, classes, loss-scaled band, canonical harness, engine query guard | as the caller |
| `class_transition_v66.py` | Old-to-new class transition matrix by area (criterion E) | none |
| `criterion_a_v66.py` | Calibration-area accuracy against v6.5 (criterion A) | none by default |
| `criterion_b_v66.py` | Signed gap of the annual ratio to each area's band (criteria B, C; `--run` for criterion G) | none |
| `criterion_f_v66.py` | Class 2 against Class 3 at four ceilings (criterion F) | SELECT only, guarded |
| `e3_cost_v66.py` | Cost of removing the Tokyo corrections, reapplied offline for reporting only | none |
| `floor_bootstrap_v66.py` | Floor-test intervals, circular block bootstrap next to the canonical i.i.d. one | none |
| `e8_numbers_v66.py` | Generators for the numbers that had none (E8) | none |
| `gate_sensitivity_v66.py` | Class-limit sensitivity, ported from `gate_sensitivity.py` | SELECT only, guarded |
| `gen_scoreboard_table_v66.py` | Table 5 in the v6.6 format (signed gap, CV in per cent) | none |
| `build_level_v66_screened.py` | Level file for criterion G (screened anchor) and the anchor population reconciliation | none |
| `eval_io_v66.py` | Shared loaders of the review analyses; checks the 1,216 canonical metrics before any analysis | none |
| `e9_level_skill_v66.py` | Level skill against capacity × anchor (E9) | none |
| `e10_transfer_shape_v66.py` | Substation shape in the nine transfer areas (E10) | SELECT only (ground truth view) |
| `e15_station_baselines_v66.py` | Baselines, skill and the floor negative control (E15) | none |
| `e15_single_lambda_v66.py` | One national load factor as a null for Table 5 (E15) | none |
| `e15_spatial_baseline_v66.py` | Allocation-weight baseline for the municipal spatial r (E15) | none |
| `e16_pv_split_v66.py` | Seasonal and hourly structure of the reverse-flow error (E16) | none |
| `e17_screen_audit_v66.py` | Reverse-flow and load-margin screens against cheap baselines (E17) | none |
| `e19_selection_v66.py` | Selection of the evaluated set (E19) | none |
| `gen_fig_lf_scatter_v66.py`, `gen_fig_pv_split_v66.py` | Figures of E9 and E16 | none |

`e14_record_limit_v66.py` is not installed: its part (b) cross-validates on calibration-area ground truth and awaits the supervisor's ruling under rule 1 of `CLAUDE.md`.

## 4. Joint estimation (rejected interventions)

| Script | Purpose |
|---|---|
| `wls_v2.py` | Two-sided WLS |
| `wls_v3_onesided.py` | One-sided WLS |
| `wls_adjudicate.py` / `wls3_adjudicate.py` | Verdict against the pre-specified acceptance criterion |
| `run_wls_experiment.sh` | Runs the set above in order |

**This writes to the database.** It creates the separate table `estimated_demand_fy2024_wls`. When done, DROP it and
confirm that TEPCO FY2024 in `lab_data.estimated_demand` is back to **12,395,400 rows**.

## Figure dependency chains

```
Fig. 2  clean_truth_and_recompute.py → v65_micro_clean.csv (1,216 substations) → regen_fig_series4.py
Fig. 3  clean_truth_and_recompute.py → recompute_all_clean.py → v65_floor_monthly.csv, v65_clean_all.json → regen_fig_examiner2.py
Fig. 4  scoreboard_v65.csv → gen_fig_validation_v65.py
Fig. 5  build_ledger_whitelist_v65.py → ledger_whitelist_v65.csv → gen_headroom_v65.py → v65_headroom.csv → gen_fig_maps_v65.py
Fig. 1  TikZ inside the text. No script
```

**Fig. 2 was brought in line with v6.5 on 2026-07-29.** The published version had been drawn from v6.3-era per-substation metrics.
When it was rebuilt, the evaluation set also moved to the 1,216 substations **after** the admission test (it had been the 1,249 before the test,
so the caption "over all evaluated stations" disagreed with the evaluation set in the text). The three boxes in panel (d)
correspond to the 75 / 169 / 972 substations of Table 1.
**The choice of representative substations was fixed too.** It used to pick the substation closest to its class's median correlation and ignored APE.
The APE shown in the panels therefore drifted from the medians in Table 1 (18.4/18.3/22.5), and at one point (b) showed 28%.
It now adds the condition "APE also within ±5pt of the class median", and the panels show 15 / 19 / 18%, consistent with Table 1.
If a class has no substation that qualifies, it falls back automatically to the old rule (exclude the top 10%).
