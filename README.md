# Substation demand from public data

Code for "How much of distribution-substation demand can public data determine? Evidence from 5,968 substations in Japan" (submitted to *Sustainable Energy, Grids and Networks*).

The paper estimates hourly net load, gross demand and behind-the-meter photovoltaics for 5,968 distribution substations across Japan's ten service areas over fiscal year 2024, using published data only, and then audits what those estimates support. This repository holds the estimator, the validation and the figure scripts.

## What is here

| Path | What it is |
|---|---|
| `code/engine/analysis/unified/stage2_engine.py` | The estimator. One implementation of the level model, the observability classes, the shape transfer and the photovoltaic separation, which every downstream script imports so that the definition cannot drift. |
| `code/engine/analysis/unified/est_source.py` | Which estimate a script reads and under which tag it writes, so that a run of one version cannot overwrite the outputs of another. |
| `code/paper/` | Everything the paper reports: the validation against the three official statistics, the baselines, the acceptance-criterion tests, the sensitivity variants, the rejected alternatives (the weighted least squares experiment) and the figures. `code/paper/README.md` is the register of the scripts. |
| `reproduce_paper.sh` | The reproduction check. It regenerates from an archived snapshot the results that do not need the estimator to run again, requires two consecutive passes to agree, and compares the manuscript's core table with the canonical rows. |

## What is not here, and why

- **The estimates themselves.** The derived substation-level series cannot be released: the authors' institution permits publication of methods but not of derived infrastructure datasets. Section 4 of the paper reports the accuracy of those estimates against ground truth and against official statistics, and the Supplementary Material gives every fitted parameter value.
- **The database snapshot and the scripts that build it** from the published files. The estimator reads that snapshot, so this release specifies the method rather than providing a turnkey rebuild. Table 1 of the paper cites every input with its source, and all of them are public.
- **Ground truth and the reference statistics.** Outside the calibration area they enter no estimation formula, by design; the code keeps that separation in its structure rather than in a comment.

Running the scripts therefore requires the reader to build the inputs of Table 1 for themselves. The purpose of the release is to let a reader read the method exactly as it was executed, and to check any claim in the paper against the code that produced it.

## Notes for a reader

- The comments are in Japanese, the language the work was carried out in. The paper is the English description of the same method: Section 3 and Algorithm 1 state the estimator, and the Supplementary Material gives the parameter values and the software environment.
- `stage2_engine.py` reaches its database through a container name that must be supplied explicitly (`DT_DB_CONTAINER`); it refuses to start with a default, which is what keeps a frozen snapshot from being confused with a live database.
- The observability classes appear in the code as `z1` (nodal balance) and `z2` (transferred shape), and in the paper as Class 1 and Class 2.
- Scripts carry a version tag, `v65` or `v66`. The paper reports the v6.6 run.

## Citation

Zhong, Z., Kawai, T., Iwafune, Y. How much of distribution-substation demand can public data determine? Evidence from 5,968 substations in Japan. Submitted, 2026.

## Licence

MIT. See `LICENSE`.
