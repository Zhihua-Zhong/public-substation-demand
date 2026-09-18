# -*- coding: utf-8 -*-
"""Figure: the national screening maps (observability class / reverse-flow margin / load margin), Fig. 5.

The canonical generator (it replaced the unported v6.3 generator). It computes nothing: it reads
results/micro/v65_headroom.csv (a product of the baseline run) and draws it.

  (a) observability class (src: z1 -> Class 1, z1s -> Class 2, z2 -> Class 3)
  (b) reverse-flow margin = fifth percentile of daytime net load (p05day)
  (c) load margin = operating capacity minus the 95th-percentile net load (hr_load)

Round-1 revision (E28; R3-m10, m13; R1 minor 10), presentation only:
- panel titles and class names follow TERMS.md;
- colour-blind-safe class palette (Okabe and Ito: blue, orange, grey), Class 2 drawn on top;
- (b) diverging map centred at 0 MW (symmetric limits); (c) sequential map; values beyond the colour limits
  take the end colours and the colour bars carry extension arrows (the data themselves are not clipped);
- each panel has insets for Greater Tokyo and Greater Osaka, and an inset for the Okinawa and Amami islands,
  so that the main map can be enlarged; scale bars on the main map and the metropolitan insets;
- drawn at print width (6.84 in) so that no text falls below 7 pt.
No area boundaries are drawn: the workspace holds no offline boundary file, and none is downloaded.

Output: manuscript/figs/fig_maps3.pdf (the path is unchanged, so the tex is unchanged)
"""
import sys, pathlib
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
import sys as _sys_tag
_sys_tag.path.insert(0, str(W / "code" / "engine" / "analysis" / "unified"))
from est_source import offline_source, untagged_suffix
_, TAG = offline_source()   # PAPER_EST_FILE picks the v65 (default) or v66 inputs and output names
FIG = W / "manuscript" / "figs"
TEXT_W = 6.84                              # cas-dc \textwidth = 494.5 pt
plt.rcParams.update({"font.size": 7.5, "axes.titlesize": 7.8, "xtick.labelsize": 7.2,
                     "legend.fontsize": 7.5, "savefig.dpi": 600})

h = pd.read_csv(W / "results" / "micro" / f"{TAG}_headroom.csv")
h.columns = [c.lstrip("﻿") for c in h.columns]
h = h[h.lat.notna() & h.lon.notna()].copy()
print(f"substations with coordinates {len(h)}")

# Map frames (degrees). The main frame leaves out the Okinawa and Amami islands, which get their own inset
# in the empty upper-left corner of the main frame (the Sea of Japan north of 40.3 N and west of 135.6 E).
MAIN = dict(lon=(128.6, 146.0), lat=(30.8, 45.75))
ISL = dict(lon=(123.4, 131.4), lat=(24.1, 30.8))
TKY = dict(lon=(139.0, 140.5), lat=(35.1, 36.3), name="Greater Tokyo")
OSA = dict(lon=(134.95, 136.05), lat=(34.25, 35.15), name="Greater Osaka")
inside = lambda f: h.lon.between(*f["lon"]) & h.lat.between(*f["lat"])
assert (inside(MAIN) | inside(ISL)).all(), "a substation falls outside both map frames"
assert not (h.lon.lt(135.6) & h.lat.gt(40.3)).any(), "a substation would be hidden under the island inset"

# Colour-blind-safe class palette (Okabe and Ito), shared with Fig. 2; drawing order puts Class 2 on top
# Criterion F merged the measured-shape class into the transferred one in v6.6: with no z1s rows the map
# shows two classes, and the transferred class is Class 2 in the manuscript's numbering.
TWO = not (h.src == "z1s").any()
CLASSES = [("z2", "#8c8c8c", f"Class {2 if TWO else 3} (transferred shape)", 1),
           ("z1", "#0072B2", "Class 1 (nodal balance)", 2),
           ("z1s", "#E69F00", "Class 2 (measured shape)", 3)]
if TWO:
    CLASSES = [c for c in CLASSES if c[0] != "z1s"]
LEGEND_ORDER = [s for s in ["z1", "z1s", "z2"] if s in {c[0] for c in CLASSES}]
CM_B = plt.get_cmap("BrBG")                                  # diverging; brown = reverse flow
NORM_B = Normalize(vmin=-15, vmax=15)                        # symmetric, so the neutral colour sits at 0 MW
CM_C = ListedColormap(plt.get_cmap("viridis")(np.linspace(0.0, 0.9, 256)))   # sequential, no pale end
NORM_C = Normalize(vmin=0, vmax=30)
SEA = "#eef1f4"
LABEL_BOX = dict(boxstyle="square,pad=0.12", fc="white", ec="none", alpha=0.85)


def frame(ax, f, aspect_lat):
    ax.set_xlim(*f["lon"]); ax.set_ylim(*f["lat"])
    ax.set_aspect(1.0 / np.cos(np.radians(aspect_lat)))
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_facecolor(SEA)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6); sp.set_color("0.45")


def scalebar(ax, f, km, pos=(0.60, 0.07)):
    """A bar of `km` kilometres placed at axes fraction `pos` (left end), at the latitude where it sits."""
    x0 = f["lon"][0] + pos[0] * (f["lon"][1] - f["lon"][0])
    y0 = f["lat"][0] + pos[1] * (f["lat"][1] - f["lat"][0])
    dlon = km / (111.32 * np.cos(np.radians(y0)))
    ax.plot([x0, x0 + dlon], [y0, y0], color="k", lw=1.6, solid_capstyle="butt", zorder=8)
    ax.text(x0 + dlon / 2, y0 + 0.022 * (f["lat"][1] - f["lat"][0]), f"{km:g} km",
            ha="center", va="bottom", fontsize=7.0, zorder=8, bbox=LABEL_BOX)


def draw(ax, kind, size):
    if kind == "class":
        for src, col, lb, z in CLASSES:
            s = h[h.src == src]
            ax.scatter(s.lon, s.lat, s=size * (1.35 if src == "z1s" else 1.0), color=col, zorder=z, lw=0)
        return None
    col, cmap, norm = {"b": ("p05day", CM_B, NORM_B), "c": ("hr_load", CM_C, NORM_C)}[kind]
    o = h.sort_values(col, ascending=(kind == "b")).iloc[::-1]  # extreme low values drawn last (on top)
    return ax.scatter(o.lon, o.lat, s=size, c=o[col], cmap=cmap, norm=norm, lw=0, zorder=2)


fig = plt.figure(figsize=(TEXT_W, 4.5))
outer = fig.add_gridspec(3, 3, height_ratios=[2.2, 1.08, 0.46], hspace=0.10, wspace=0.07,
                         left=0.005, right=0.995, top=0.955, bottom=0.01)
titles = {"class": "(a) observability class", "b": "(b) reverse-flow margin (MW)",
          "c": "(c) load margin (MW)"}
for c, kind in enumerate(["class", "b", "c"]):
    ax = fig.add_subplot(outer[0, c])
    frame(ax, MAIN, 38.0)
    sc = draw(ax, kind, 1.3)
    ax.set_title(titles[kind], pad=3)
    scalebar(ax, MAIN, 200, pos=(0.66, 0.06))
    for f, tag, dx in [(TKY, "Tokyo", 0.25), (OSA, "Osaka", -2.75)]:
        ax.add_patch(Rectangle((f["lon"][0], f["lat"][0]), f["lon"][1] - f["lon"][0], f["lat"][1] - f["lat"][0],
                               fill=False, lw=0.8, ec="k", zorder=5))
    ax.text(TKY["lon"][1] + 0.25, TKY["lat"][0] - 0.25, "Tokyo", fontsize=7.0, va="top", zorder=8,
            bbox=LABEL_BOX)
    ax.text(OSA["lon"][0] - 0.2, OSA["lat"][0] - 0.3, "Osaka", fontsize=7.0, ha="right", va="top", zorder=8,
            bbox=LABEL_BOX)
    # Okinawa and Amami islands, at the same scale as the main map
    wfrac = (ISL["lon"][1] - ISL["lon"][0]) / (MAIN["lon"][1] - MAIN["lon"][0])
    hfrac = (ISL["lat"][1] - ISL["lat"][0]) / (MAIN["lat"][1] - MAIN["lat"][0])
    axi = ax.inset_axes([0.0, 1.0 - hfrac, wfrac, hfrac])
    frame(axi, ISL, 38.0)
    draw(axi, kind, 1.3)
    axi.text(0.04, 0.95, "Okinawa and\nAmami islands", transform=axi.transAxes, fontsize=7.0,
             va="top", linespacing=0.95)
    # metropolitan insets
    sub = outer[1, c].subgridspec(1, 2, wspace=0.05)
    for j, f in enumerate([TKY, OSA]):
        axm = fig.add_subplot(sub[0, j])
        frame(axm, f, np.mean(f["lat"]))
        draw(axm, kind, 5.0)
        axm.text(0.03, 0.97, f["name"], transform=axm.transAxes, fontsize=7.0, va="top", ha="left",
                 bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85), zorder=7)
        scalebar(axm, f, 20, pos=(0.62, 0.07))
    # legend or colour bar
    cell = outer[2, c].subgridspec(2, 3, width_ratios=[0.08, 0.84, 0.08], height_ratios=[0.3, 0.7])
    if kind == "class":
        axl = fig.add_subplot(outer[2, c]); axl.axis("off")
        hd = {src: Line2D([], [], ls="", marker="o", ms=4.5, color=col, label=lb) for src, col, lb, _ in CLASSES}
        axl.legend(handles=[hd[s] for s in LEGEND_ORDER], loc="center", ncol=1, frameon=False,
                   handletextpad=0.3, labelspacing=0.15, borderpad=0.0)
    else:
        cax = fig.add_subplot(cell[0, 1])
        cb = fig.colorbar(sc, cax=cax, orientation="horizontal", extend="both")
        cb.ax.tick_params(labelsize=7.2, length=2, pad=1.5)
        cb.outline.set_linewidth(0.5)
        if kind == "b":
            cb.set_ticks([-15, -10, -5, 0, 5, 10, 15])
            cb.set_label("MW; below 0: reverse flow", fontsize=7.2, labelpad=1)
        else:
            cb.set_ticks([0, 5, 10, 15, 20, 25, 30])
            cb.set_label("MW; below 0: peak net load above capacity", fontsize=7.2, labelpad=1)

fig.savefig(FIG / f"fig_maps3{untagged_suffix(TAG)}.pdf", bbox_inches="tight", pad_inches=0.02)
print(f"[output] {FIG / f'fig_maps3{untagged_suffix(TAG)}.pdf'}")
