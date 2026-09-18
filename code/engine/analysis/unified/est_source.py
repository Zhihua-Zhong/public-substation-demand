# -*- coding: utf-8 -*-
"""Which estimate a downstream script reads, and the tag of the files it writes.

RERUN_PLAN_R1.md, Step 3, items 4 to 6 (review item E7). After the v6.6 rerun two estimates
coexist: the v6.5 archive and the v6.6 rerun. A script that kept reading v6.5 without saying so
would put a v6.5 number into a v6.6 table, and a v6.6 run that wrote under a v6.5 name would
destroy a file the transition matrix and the response still need. Hence:

  - DB-bound readers take the relation from PAPER_EST_REL. It is required and has no default,
    so a forgotten switch stops the script instead of silently reading v6.5.
  - Offline readers take the parquet file name from PAPER_EST_FILE. Its default is the v6.5 file,
    which keeps the reproduction gate on its v6.5 targets until Step 12 switches them.
  - Both map to a tag, "v65" or "v66". Every output name carries it, so a v6.6 run never
    overwrites a v6.5 file.

Only the values listed below are accepted; anything else stops the script. The relation name is
interpolated into SQL, so the fixed list is also what keeps that interpolation safe.
"""
import os, sys

# relation -> (run_id LIKE pattern, tag)
DB_SOURCES = {
    "lab_data.estimated_demand_fy2024": ("stage2_pvaware_fy2024_%", "v65"),
    "lab_data.ed_rerun_v66":            ("v66_rerun_fy2024_%",      "v66"),
}
# parquet file in data/offline/ -> tag
OFFLINE_SOURCES = {
    "estimated_demand_fy2024.parquet":     "v65",
    "estimated_demand_fy2024_v66.parquet": "v66",
}


def db_source():
    """(relation, run_id LIKE pattern, tag) from PAPER_EST_REL; exits if unset or unknown."""
    rel = os.environ.get("PAPER_EST_REL", "")
    if rel not in DB_SOURCES:
        sys.exit("[FATAL] PAPER_EST_REL must name the estimate explicitly (there is no default). "
                 f"Allowed: {', '.join(DB_SOURCES)}. Got: {rel!r}")
    like, tag = DB_SOURCES[rel]
    print(f"[estimate] {rel} (run_id LIKE '{like}'); outputs tagged {tag}", flush=True)
    return rel, like, tag


def offline_source():
    """(file name, tag) from PAPER_EST_FILE, default the v6.5 file; exits if unknown."""
    f = os.environ.get("PAPER_EST_FILE", "estimated_demand_fy2024.parquet")
    if f not in OFFLINE_SOURCES:
        sys.exit(f"[FATAL] PAPER_EST_FILE must be one of {', '.join(OFFLINE_SOURCES)}. Got: {f!r}")
    return f, OFFLINE_SOURCES[f]


def untagged_suffix(tag):
    """For files whose v6.5 name carries no version (engine out/ files, figures): '' for v6.5,
    '_v66' for v6.6, so the v6.5 file keeps its name and the v6.6 file never replaces it."""
    return "" if tag == "v65" else f"_{tag}"
