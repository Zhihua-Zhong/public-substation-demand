#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper A P4+P6: 全国headroom両屏 + naive基線対比 + 図3枚 (v6.3凍結基線)。

両屏(旧稿と同定義·全国化):
  発電headroom = 昼間(09-15h)netの5百分位  (PV吸収余地·負=既飽和)
  負荷headroom = 運用容量 − net95百分位
P4 use-case: naive基線 = エリアnet総量を容量シェアで按分(データセット不在時の標準実務)。
  naiveの局別昼間5百分位 = share×エリア5百分位(単調scaling) → 局別飽和は構造的に検出不能。
図: fig_map_tier(=fig:map_accuracy·層別全国地図) / fig_gen / fig_load (matplotlib·PDF)。
"""
import io, os, subprocess, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.size": 11, "savefig.dpi": 600})
sys.stdout.reconfigure(encoding="utf-8")
import pathlib as _pl
WS   = str(_pl.Path(__file__).resolve().parents[2])
MAIN = f"{WS}/code/engine"
HERE = f"{WS}/results/micro"
FIG  = f"{WS}/manuscript/figs"          # 投稿する図(fig_maps3 のみ)
TMP  = f"{WS}/logs/figs_intermediate"   # 中間の単票図。論文は使わない(版管理外)
import os as _os2; _os2.makedirs(TMP, exist_ok=True)
sys.path.insert(0, f"{MAIN}/analysis/unified")
from stage2_engine import norm2
from est_source import db_source, untagged_suffix
EST_REL, EST_LIKE, TAG = db_source()   # PAPER_EST_REL, required (RERUN_PLAN_R1.md Step 3, items 4 and 6)
SFX = untagged_suffix(TAG)             # intermediate figures: v6.5 names kept, v6.6 adds _v66
import os as _os, sys as _sys
_DBC = _os.environ.get("DT_DB_CONTAINER") or _sys.exit(
    "[FATAL] 論文作業区では DT_DB_CONTAINER の明示が必須(例: iwafune_db_frozen)。生産DB誤接続の防止。")


def q(sql):
    p = subprocess.run(["docker","exec","-e","PGOPTIONS=-c max_parallel_workers_per_gather=0",
        "-i",_DBC,"psql","-U","postgres","-d","lab_database","-A","-F","|","-tc",sql], capture_output=True)
    if p.returncode: print("ERR:", p.stderr.decode("utf-8","replace")[:300]); sys.exit(1)
    return pd.read_csv(io.StringIO(p.stdout.decode("utf-8","replace")), sep="|", header=None)

# ── 1) 局別percentile(SQL·v6.3運転本表=凍結時点と同一git) ──
print("[1] 局別percentile...", flush=True)
st = q(f"""SELECT utility, station_id, src,
   percentile_cont(0.05) WITHIN GROUP (ORDER BY demand_net_mw)
     FILTER (WHERE extract(hour FROM ts) BETWEEN 9 AND 15),
   percentile_cont(0.95) WITHIN GROUP (ORDER BY demand_net_mw)
FROM {EST_REL} WHERE run_id LIKE '{EST_LIKE}'
GROUP BY 1,2,3""")
st.columns = ["u","key","src","p05day","p95"]
for c in ("p05day","p95"): st[c] = pd.to_numeric(st[c], errors="coerce")
print(f"  {len(st)}局 (口径前)")
# 台帳被覆の白名単へ絞る(build_ledger_whitelist_v65.py が離線層から作る)。
# 5,950は推計キーの数。台帳名で数えると5,968(差18=norm2キーの衝突)。
_wl = pd.read_csv(f"{WS}/results/numbers/ledger_whitelist_{TAG}.csv")
_wlset = set(zip(_wl.u, _wl.sid))
st = st[[(u,k) in _wlset for u,k in zip(st.u, st.key)]].copy()
print(f"  {len(st)}局 (台帳被覆の白名単後)")

# 容量(roster) + 座標(master)
ros = q("SELECT utility, name, coalesce(equip_mw,0), coalesce(opcap_mw,0) FROM canonical.haihen_roster")
ros.columns = ["u","nm","emw","omw"]
for c in ("emw","omw"): ros[c] = pd.to_numeric(ros[c], errors="coerce")
ros["cap"] = ros.emw.where(ros.emw>0, ros.omw)
ros["key"] = ros.nm.map(norm2)
capmap = ros.drop_duplicates(["u","key"]).set_index(["u","key"])["cap"]
ms = q("SELECT utility, coalesce(station_name,station_id), lat, lon FROM lab_data.substation_master")
ms.columns = ["u","nm","lat","lon"]
for c in ("lat","lon"): ms[c] = pd.to_numeric(ms[c], errors="coerce")
ms["key"] = ms.nm.map(norm2)
crd = ms.dropna(subset=["lat"]).drop_duplicates(["u","key"]).set_index(["u","key"])[["lat","lon"]]

st = st.set_index(["u","key"])
st["cap"] = capmap
st = st.join(crd)
st["hr_gen"] = st.p05day
st["hr_load"] = st.cap - st.p95
val = st.dropna(subset=["cap"])
sat = val[val.hr_gen <= 0]
print(f"  発電headroom中央 {val.hr_gen.median():.1f}MW IQR[{val.hr_gen.quantile(.25):.1f},{val.hr_gen.quantile(.75):.1f}]")
print(f"  飽和(≤0) {len(sat)}局 ({100*len(sat)/len(val):.1f}%)  正値Σ={val.hr_gen.clip(lower=0).sum()/1000:.1f}GW")
print(f"  負荷headroom中央 {val.hr_load.median():.1f}MW  余裕≥20MW {100*(val.hr_load>=20).mean():.0f}%  Σ={val.hr_load.clip(lower=0).sum()/1000:.1f}GW")
print("  飽和局の区域分布:", sat.reset_index().u.value_counts().to_dict())

# ── 2) P4 naive基線(容量シェア按分) ──
print("[2] naive基線...", flush=True)
area = q(f"""SELECT utility,
   percentile_cont(0.05) WITHIN GROUP (ORDER BY tot) FILTER (WHERE hr BETWEEN 9 AND 15),
   percentile_cont(0.95) WITHIN GROUP (ORDER BY tot)
FROM (SELECT utility, ts, extract(hour FROM ts) hr, sum(demand_net_mw) tot
      FROM {EST_REL} WHERE run_id LIKE '{EST_LIKE}'
      GROUP BY utility, ts) x GROUP BY 1""")
area.columns = ["u","a05day","a95"]
for c in ("a05day","a95"): area[c] = pd.to_numeric(area[c], errors="coerce")
area = area.set_index("u")
v2 = val.reset_index().merge(area, on="u")
csum = v2.groupby("u")["cap"].transform("sum")
v2["naive_gen"] = v2.cap/csum * v2.a05day
v2["naive_load"] = v2.cap - v2.cap/csum * v2.a95
n_sat_naive = int((v2.naive_gen <= 0).sum())
flip_gen = int(((v2.hr_gen <= 0) != (v2.naive_gen <= 0)).sum())
TH = 10.0     # 負荷側の実務閾値: 新規大口(例:10MW級DC/EV hub)受入可否
flip_load = int(((v2.hr_load < TH) != (v2.naive_load < TH)).sum())
print(f"  naive飽和局={n_sat_naive} (構造的に0)  発電判定flip={flip_gen}局({100*flip_gen/len(v2):.1f}%)")
print(f"  負荷判定(<{TH}MW)flip={flip_load}局({100*flip_load/len(v2):.1f}%)  ours<{TH}MW={int((v2.hr_load<TH).sum())} naive<{TH}MW={int((v2.naive_load<TH).sum())}")
v2.to_csv(f"{HERE}/{TAG}_headroom.csv", index=False, encoding="utf-8-sig")

# ── 3) 図3枚 ──
print("[3] 図...", flush=True)
g = v2.dropna(subset=["lat","lon"])
g = g[(g.lon>122)&(g.lon<147)&(g.lat>24)&(g.lat<46)]
def basemap(ax):
    ax.set_xlim(127, 146.5); ax.set_ylim(26, 45.8)
    ax.set_aspect(1.2); ax.axis("off")
# F1: tier map
fig, ax = plt.subplots(figsize=(6.0, 5.6))
cols = {"z1":"#0b6b3a", "z1s":"#2e9bd6", "z2":"#c9c9c9"}
lab  = {"z1":"tier 1 (nodal balance)", "z1s":"tier 2 (measured shape)", "z2":"tier 3 (transfer)"}
for s in ("z2","z1s","z1"):
    gg = g[g.src==s]
    ax.scatter(gg.lon, gg.lat, s=7.0 if s!="z2" else 4.5, c=cols[s], label=lab[s],
               alpha=0.85 if s!="z2" else 0.45, linewidths=0)
basemap(ax)
ax.legend(loc="upper left", fontsize=12, frameon=False, markerscale=2.6,
          handletextpad=0.4, borderpad=0.2)
fig.tight_layout()
fig.savefig(f"{TMP}/fig_map_tier{SFX}.pdf", bbox_inches="tight")   # 中間物
plt.close(fig)
# F2/F3: headroom maps
from matplotlib.colors import TwoSlopeNorm
# 発散配色: 0(飽和境界)を白に固定し、各図の分布に合わせて範囲を設定する。
#   gen は中央2.7MW·IQR[-0.2,8.1] と分布が狭いので、load と同じ範囲では全面が単色になり
#   「31%が飽和」という主要な所見が視覚的に消える(300dpi検品で検出·2026-07-22)。
for nmfig, colv, title, fname, lo, hi in [
    ("gen", "hr_gen", "generation headroom (5th pct daytime net, MW)", f"fig_gen{SFX}.pdf", -6.0, 14.0),
    ("load", "hr_load", "load headroom (capacity minus 95th pct net, MW)", f"fig_load{SFX}.pdf", -10.0, 40.0)]:
    fig, ax = plt.subplots(figsize=(6.0, 5.6))
    vv = g[colv].clip(lo, hi)
    nrm = TwoSlopeNorm(vmin=lo, vcenter=0.0, vmax=hi)
    sc = ax.scatter(g.lon, g.lat, s=6, c=vv, cmap="BrBG", norm=nrm, alpha=0.85, linewidths=0)
    basemap(ax)
    cb = fig.colorbar(sc, ax=ax, shrink=0.62, pad=0.01)
    cb.set_label(title, fontsize=11)
    cb.ax.tick_params(labelsize=10)
    fig.tight_layout()
    fig.savefig(f"{TMP}/{fname}", bbox_inches="tight")            # 中間物
    plt.close(fig)
print(f"[出力] {TAG}_headroom.csv / 中間図(logs/figs_intermediate): fig_map_tier{SFX}.pdf fig_gen{SFX}.pdf fig_load{SFX}.pdf")

# ── 4) 三聯圖(跨欄): tier / generation / load を横並び ──
#   単独配置だと地図3枚で約2.5頁を占め、上下に大きな空白が出る(300dpi検品で検出·2026-07-22)。
#   figure* で跨欄1枚に統合し、3つの空間パターンを直接比較できるようにする。
from matplotlib.colors import TwoSlopeNorm as _TSN
fig, axs = plt.subplots(1, 3, figsize=(7.4, 2.9))
for ax in axs: basemap(ax)
cols = {"z1":"#0b6b3a", "z1s":"#2e9bd6", "z2":"#c9c9c9"}
lab  = {"z1":"tier 1 (nodal balance)", "z1s":"tier 2 (measured shape)", "z2":"tier 3 (transfer)"}
for s in ("z2","z1s","z1"):
    gg = g[g.src==s]
    axs[0].scatter(gg.lon, gg.lat, s=2.6 if s!="z2" else 1.8, c=cols[s], label=lab[s],
                   alpha=0.85 if s!="z2" else 0.45, linewidths=0)
axs[0].legend(loc="upper left", fontsize=7.0, frameon=False, markerscale=3.2,
              handletextpad=0.3, borderpad=0.1, labelspacing=0.25)
axs[0].set_title("(a) observability tier", fontsize=9, pad=2)
for ax, colv, ttl, lo, hi in [
    (axs[1], "hr_gen",  "(b) generation headroom (MW)", -6.0, 14.0),
    (axs[2], "hr_load", "(c) load headroom (MW)",      -10.0, 40.0)]:
    sc = ax.scatter(g.lon, g.lat, s=2.2, c=g[colv].clip(lo,hi),
                    cmap="BrBG", norm=_TSN(vmin=lo, vcenter=0.0, vmax=hi), alpha=0.85, linewidths=0)
    ax.set_title(ttl, fontsize=9, pad=2)
    cb = fig.colorbar(sc, ax=ax, shrink=0.78, pad=0.02, aspect=18)
    cb.ax.tick_params(labelsize=7.5)
fig.tight_layout(w_pad=0.4)
# Round-1 revision (E28): the paper's Fig. 5 is drawn by gen_fig_maps_v65.py from v65_headroom.csv.
# This legacy triptych goes to the intermediate folder only, so rerunning this script can no longer
# overwrite manuscript/figs/fig_maps3.pdf with the old presentation.
fig.savefig(f"{TMP}/fig_maps3_legacy{SFX}.pdf", bbox_inches="tight")
plt.close(fig)
print(f"[output] logs/figs_intermediate/fig_maps3_legacy{SFX}.pdf; run gen_fig_maps_v65.py for the paper's Fig. 5")
