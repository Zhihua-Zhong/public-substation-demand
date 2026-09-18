# -*- coding: utf-8 -*-
"""論文作業区の離線データ層を作る(Parquet + 台帳)。

設計の要点(過去に踏んだ罠への対処):
  1. 潮流・推計は必ず**ビュー経由**で出す。物理表を直に出すと、九州1〜3月の年度標識を
     付け替えているビューの論理が落ち、誤りごと固定してしまう。
  2. すべての照会に決定的な ORDER BY を置く。ファイル自体が行順の権威になり、
     実行計画・統計情報の揺れが再現性に入り込む経路を断つ(構造的保証)。
  3. 各ファイルに 行数・sha256・生成SQL を台帳として添える。添えなければ
     「誰も検証していないファイルが増えただけ」になる。

使い方:
  DT_DB_CONTAINER=iwafune_db_frozen python export_offline.py [対象名 ...]
"""
import subprocess, sys, os, pathlib, hashlib, json, io, datetime
sys.stdout.reconfigure(encoding="utf-8")

CONTAINER = os.environ.get("DT_DB_CONTAINER")
if not CONTAINER:
    sys.exit("[FATAL] DT_DB_CONTAINER を明示すること(例: iwafune_db_frozen)。既定値は持たない。")
OUT = pathlib.Path(__file__).resolve().parents[2] / "data" / "offline"
OUT.mkdir(parents=True, exist_ok=True)

# (出力名, 照会) — 大表は必ずビュー経由・全件に決定的な整列
JOBS = [
 ("estimated_demand_fy2024",
  "SELECT * FROM lab_data.estimated_demand_fy2024 ORDER BY utility, station_id, ts"),
 # v6.6 rerun (RERUN_PLAN_R1.md Step 9): the separate table loaded by load_rerun_table.py, with the
 # columns, order and text timestamps of the v6.5 export above. Run it by name only:
 #   DT_DB_CONTAINER=iwafune_db_frozen python export_offline.py estimated_demand_fy2024_v66
 # The v6.5 file is kept; the v6.6 table is dropped after the regeneration chain (Step 11).
 ("estimated_demand_fy2024_v66",
  "SELECT run_id, utility, station_id, ts, demand_net_mw, demand_gross_mw, pv_mw, src "
  "FROM lab_data.ed_rerun_v66 ORDER BY utility, station_id, ts"),
 ("flow_input_fy2024",
  "SELECT * FROM public_data.flow_estimation_input WHERE fiscal_year=2024 "
  "ORDER BY utility, equipment_type, equipment_id, ts"),
 ("truth_tepco_bank_fy2024",
  "SELECT * FROM validation.tepco_bank_fy2024_full ORDER BY station_norm, ts"),
 ("canonical_demand",        "SELECT * FROM canonical.demand ORDER BY node_id, ts"),
 ("haihen_roster",           "SELECT * FROM canonical.haihen_roster ORDER BY utility, official_code"),
 ("substation_master",       "SELECT * FROM lab_data.substation_master ORDER BY utility, station_id"),
 ("station_features",        "SELECT * FROM canonical.station_features ORDER BY product, node_id"),
 ("hosting_capacity",        "SELECT * FROM canonical.hosting_capacity ORDER BY node_id"),
 ("mesh_substation_alloc",   "SELECT * FROM canonical.mesh_substation_allocation ORDER BY mesh_code, utility, station_id"),
 ("substation_pv",           "SELECT * FROM canonical.substation_pv ORDER BY utility, station_id"),
 ("station_key_map",         "SELECT * FROM validation.station_key_map ORDER BY utility, kind, key, src_name"),
 ("tepco_lt_scalar",         "SELECT * FROM validation.tepco_lt_scalar ORDER BY utility, station_id"),
 ("estimation_run",          "SELECT * FROM lab_data.estimation_run ORDER BY run_id"),
 ("uncertainty_band",        "SELECT * FROM lab_data.uncertainty_band ORDER BY utility, tier"),
 ("pv_regional_gen",         "SELECT * FROM lab_data.pv_regional_gen ORDER BY utility, ts"),
 ("pv_curtailment_fy2024",   "SELECT * FROM public_data.pv_curtailment_fy2024 ORDER BY utility, ts"),
 ("area_demand_by_voltage",  "SELECT * FROM public_data.area_demand_by_voltage ORDER BY 1,2,3"),
 ("census_mesh_1km",         "SELECT * FROM public_data.census_mesh_1km ORDER BY mesh_1km"),
 ("econ_census_mesh_1km",    "SELECT * FROM public_data.econ_census_mesh_1km ORDER BY mesh_1km"),
 ("meti_demand_stats",      "SELECT * FROM public_data.meti_demand_stats ORDER BY 1,2,3"),
 ("occto_supply_demand",    "SELECT * FROM public_data.occto_supply_demand ORDER BY 1,2"),
 ("occto_area_demand_raw",  "SELECT * FROM raw_data.occto_area_demand ORDER BY 1"),
 ("mesh_city_map",          "SELECT * FROM canonical.mesh_city_map ORDER BY mesh_1km"),
 ("station_municipality",
  "SELECT sm.utility, sm.station_id, "
  "(SELECT ab.city_name FROM public_data.admin_boundaries ab WHERE ST_Contains(ab.geom, sm.geom) LIMIT 1) AS city_name, "
  "(SELECT ab.pref_name FROM public_data.admin_boundaries ab WHERE ST_Contains(ab.geom, sm.geom) LIMIT 1) AS pref_name "
  "FROM lab_data.substation_master sm WHERE sm.node_type='haihen' ORDER BY sm.utility, sm.station_id"),
]

def run_copy(sql, dest_csv):
    """COPY ... TO STDOUT で取り出す。巨大表でもメモリに載せない。"""
    cmd = ["docker","exec","-e","PGOPTIONS=-c max_parallel_workers_per_gather=0",
           "-i",CONTAINER,"psql","-U","postgres","-d","lab_database",
           "-c", f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)"]
    with open(dest_csv, "wb") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8","replace")[:400])

def sha256(path, buf=1<<20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while (b := f.read(buf)): h.update(b)
    return h.hexdigest()

targets = sys.argv[1:] or [n for n,_ in JOBS]
ledger = []
for name, sql in JOBS:
    if name not in targets: continue
    csv_path = OUT / f"{name}.csv"
    pq_path  = OUT / f"{name}.parquet"
    print(f"[出力] {name} ...", flush=True)
    run_copy(sql, csv_path)
    # CSV → Parquet(型と浮動小数の往復を保つ。CSVは小表のみ残す)
    import pandas as pd
    df = pd.read_csv(csv_path, low_memory=False)
    df.to_parquet(pq_path, index=False, compression="zstd")
    rows = len(df)
    small = rows <= 200_000                      # 小表は人が開けるようCSVも残す
    if not small: csv_path.unlink()
    ledger.append(dict(name=name, rows=rows,
                       parquet=pq_path.name, parquet_bytes=pq_path.stat().st_size,
                       parquet_sha256=sha256(pq_path),
                       csv=(csv_path.name if small else None),
                       sql=sql))
    print(f"   {rows:,}行 / {pq_path.stat().st_size/1e6:.1f}MB" + ("  (CSVも保持)" if small else ""))

# 台帳(監査F3の教訓: 検証されないファイルを増やさない)
led = OUT / "MANIFEST.json"
prev = json.loads(led.read_text(encoding="utf-8")) if led.exists() else {"exports": []}
byname = {e["name"]: e for e in prev.get("exports", [])}
for e in ledger: byname[e["name"]] = e
out = {"generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
       "source_container": CONTAINER,
       "note": "潮流・推計はビュー経由(九州1〜3月の年度修正を保持)。全照会に決定的ORDER BY。",
       "exports": [byname[k] for k in sorted(byname)]}
led.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n台帳: {led}  ({len(out['exports'])}件)")
