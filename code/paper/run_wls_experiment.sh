#!/usr/bin/env bash
# WLS実験の再走(§method-joint の数字の裏付け)。凍結DB(iwafune_db_frozen)に対し実行。
#   独立表 lab_data.estimated_demand_fy2024_wls を作る → 裁決 → 表をDROP → 指紋確認は呼び出し側。
set -euo pipefail
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PAPER_PY:-python}"   # 実行環境の python を PAPER_PY で指定する
export DT_DB_CONTAINER=iwafune_db_frozen
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
cd "$WS/code/paper"

echo "=== [1/4] WLS v2 (両側) TEPCO KANSAI ==="
"$PY" wls_v2.py TEPCO KANSAI
echo "=== [2/4] 裁決 v2 (G1-G4) ==="
"$PY" wls_adjudicate.py
echo "=== [3/4] WLS v3 (片側) TEPCO KANSAI ==="
"$PY" wls_v3_onesided.py TEPCO KANSAI
echo "=== [4/4] 裁決 v3 (G1-G4) ==="
"$PY" wls3_adjudicate.py
echo "★DONE_WLS_ALL"
