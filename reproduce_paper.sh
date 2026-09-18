#!/usr/bin/env bash
# 論文数値の再現ゲート: 離線層から結論ファイルを再生成し、results/numbers と突き合わせる。
#
#   ./reproduce_paper.sh verify   # 再生成→バイト比較→PASS/FAIL(数分・DB不要)
#   ./reproduce_paper.sh twice    # 2回連続で再生成し、双方一致して初めてPASS(再現の最低条件)
#
# 設計: すべての計算は data/offline/*.parquet だけを読む(DBに接続しない)。
#   行順はファイルが権威なので、実行計画・統計情報の揺れは入り込まない。
#   正本由来の入力(examiner調和・p3空間相関)は「凍結された入力」であり再生成対象ではない。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PAPER_PY:-$HERE/.venv/Scripts/python.exe}"  # 作業区に同梱(code/engine/requirements_lock.txt から再構築可)
NUM="$HERE/results/numbers"
MS="$HERE/manuscript/sections/validation.tex"   # 中核表 tab:scoreboard を抱える節

# 再生成の対象(離線層のみから決定的に作れるもの)
export PAPER_EST_FILE="${PAPER_EST_FILE:-estimated_demand_fy2024_v66.parquet}"
TARGETS=(annual_monthly_v66.csv spatial_hourly_v66.csv scoreboard_v66.csv scoreboard_v66_rows.tex truth_coverage_v66.csv
         station_levels_v66.csv level_model_v66.json)
SCRIPTS=(calc_annual_monthly_v65.py calc_spatial_hourly_v65.py gen_scoreboard_table_v66.py calc_truth_coverage_v65.py
         build_level_v66.py)

log(){ printf '\n=== %s ===\n' "$*"; }
fail(){ printf '\n★FAIL: %s\n' "$*" >&2; exit 1; }

run_once(){
  local dest="$1"
  mkdir -p "$dest"
  # 現行の results/numbers を退避し、再生成後に比較して戻す
  local bak; bak="$(mktemp -d)"
  cp "$NUM"/*.csv "$NUM"/*.tex "$NUM"/*.json "$bak"/ 2>/dev/null || true
  for s in "${SCRIPTS[@]}"; do
    (cd "$HERE" && PYTHONUTF8=1 "$PY" "code/paper/$s" >/dev/null) || { cp "$bak"/* "$NUM"/; fail "$s が異常終了"; }
  done
  for t in "${TARGETS[@]}"; do cp "$NUM/$t" "$dest/$t"; done
  cp "$bak"/* "$NUM"/ 2>/dev/null || true     # 基準を元に戻す(ゲートは読み取り専用)
}

# 原稿の中核表は、投稿包を自己完結させるため正本の行を写してある。
# 写した以上は写し崩れが起こりうるので、ゲートで毎回突き合わせる(原稿は書き換えない)。
check_manuscript_table(){
  log "原稿の中核表(tab:scoreboard)と正本の突き合わせ"
  [ -f "$MS" ] || fail "原稿の節が見つからない: $MS"
  local ms; ms="$(mktemp)"
  # 節には区域名で始まる行を持つ表が複数ある(tab:shape-transfer など)。
  # 区域名だけで拾うと他表の行まで混ざるので、tab:scoreboard の tabular の中だけを見る。
  awk '/\\label{tab:scoreboard}/{inlab=1} inlab&&/\\begin{tabular}/{intab=1;next}
       intab&&/\\end{tabular}/{exit} intab' "$MS" \
    | grep -E '^(Hokkaido|Tohoku|Tokyo|Chubu|Hokuriku|Kansai|Chugoku|Shikoku|Kyushu|Okinawa) & ' \
    | sed 's/[[:space:]]*$//' > "$ms" || true
  local n; n="$(wc -l < "$ms" | tr -d ' ')"
  [ "$n" = 10 ] || fail "原稿から表の行を10行取り出せない(取得 ${n} 行)。表の書式が変わった疑いがある"
  if diff -q <(sed 's/[[:space:]]*$//' "$NUM/scoreboard_v66_rows.tex") "$ms" >/dev/null; then
    echo "  一致: manuscript/sections/validation.tex の tab:scoreboard(10行)"
  else
    diff <(sed 's/[[:space:]]*$//' "$NUM/scoreboard_v66_rows.tex") "$ms" || true
    fail "原稿の中核表が正本 scoreboard_v66_rows.tex と食い違う"
  fi
}

# 方法章 §3.4 の散文に埋めた数値も、正本の産物であることを毎回確かめる。
# 中核表だけを守っていたので、手で書き写した「全国中央 19MW」の誤りが長く残った。
check_method_numbers(){
  log "方法章 §3.4 の数値と正本産生器の突き合わせ"
  (cd "$HERE" && PYTHONUTF8=1 "$PY" code/paper/check_method_numbers.py)     || fail "方法章の数値が正本の出力と食い違う"
}

# 用語の門。TERMS.md が置かれていれば、原稿の散文に禁止語が無いことも確かめる。
# 数値と同じ扱いにする理由は manuscript/check_terms.sh の冒頭に書いた。
check_terms(){
  if [ ! -f "$HERE/manuscript/TERMS.md" ]; then
    echo "  用語の門: TERMS.md が無いので飛ばした(語彙は未管理の状態)"
    return 0
  fi
  log "用語の門(TERMS.md の禁止語)"
  (cd "$HERE/manuscript" && ./check_terms.sh) || fail "原稿に禁止語がある"
}

# 補足資料への参照の門。本文の「Supplementary Table S<n>」は手書きの文字列で、
# xr の連携は補足→本文の一方向しか張っていない。補足の表を並べ替えれば本文の番号が
# 黙ってずれる。ここでは補足の表ラベルの順序を固定し、本文が引く最大の S 番号が
# 表の数を超えないことを確かめる。
check_supplementary_pointers(){
  local supp="$HERE/manuscript/supplementary/parameters_repro.tex"
  [ -f "$supp" ] || { echo "  補足資料が無いので飛ばした"; return 0; }
  log "補足資料の表順序と本文の S 番号"
  local expected="tab:glossary tab:app-pop tab:app-reg tab:app-level tab:app-pv tab:app-quantiles tab:app-skill tab:app-transition"
  local actual
  actual="$(grep -oE 'label\{tab:[A-Za-z0-9:_-]+\}' "$supp" | sed -E 's/label\{(.*)\}/\1/' | tr '\n' ' ' | sed 's/ *$//')"
  if [ "$actual" != "$expected" ]; then
    echo "  期待: $expected" >&2
    echo "  実際: $actual" >&2
    fail "補足資料の表の順序が変わった。本文の Supplementary Table S<n> を見直すこと"
  fi
  local ntab maxref
  ntab="$(printf '%s' "$expected" | wc -w | tr -d ' ')"
  maxref="$(grep -ohE 'Supplementary Table S[0-9]+' "$HERE/manuscript/main_cas.tex" "$HERE"/manuscript/sections/*.tex | grep -oE '[0-9]+$' | sort -n | tail -1)"
  maxref="${maxref:-0}"
  [ "$maxref" -le "$ntab" ] || fail "本文が Supplementary Table S${maxref} を引くが、補足には表が ${ntab} 個しかない"
  echo "  一致: 補足の表 ${ntab} 個、本文が引く最大 S 番号 ${maxref}"
}

cmd_verify(){
  log "離線層から再生成(1回目)"
  local w="$HERE/logs/repro_$(date +%Y%m%d_%H%M%S)"
  run_once "$w"
  log "基準(results/numbers)との照合"
  local ng=0
  for t in "${TARGETS[@]}"; do
    if diff -q "$NUM/$t" "$w/$t" >/dev/null 2>&1; then echo "  一致: $t"
    else echo "  ★不一致: $t (diff: $w/diff_$t)"; diff "$NUM/$t" "$w/$t" > "$w/diff_$t" || true; ng=1; fi
  done
  [ "$ng" = 0 ] || fail "再現しない。$w を確認"
  check_manuscript_table
  check_method_numbers
  check_supplementary_pointers
  check_terms
  printf '\n★PASS: 論文数値は離線層から再現し、原稿の中核表とも一致する\n'
}

cmd_twice(){
  log "2回連続の再生成(1回の合格を再現とみなさない)"
  local w1="$HERE/logs/repro_a_$$" w2="$HERE/logs/repro_b_$$"
  run_once "$w1"; run_once "$w2"
  local ng=0
  for t in "${TARGETS[@]}"; do
    diff -q "$w1/$t" "$w2/$t" >/dev/null || { echo "  ★2回の実行が不一致: $t"; ng=1; }
    diff -q "$NUM/$t" "$w1/$t" >/dev/null || { echo "  ★基準と不一致: $t"; ng=1; }
  done
  [ "$ng" = 0 ] || fail "再現しない"
  check_manuscript_table
  check_method_numbers
  check_supplementary_pointers
  check_terms
  printf '\n★PASS: 2回連続で同一・基準とも一致・原稿の中核表とも一致\n'
}

warn_pending(){
  [ -f "$HERE/manuscript/PENDING_RERUN.md" ] || return 0
  cat >&2 <<'EOS'

  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃  警告: 原稿は方法章と数値が食い違った状態にある。                     ┃
  ┃  このゲートが見ているのは「数値が離線層から再現するか」だけで、       ┃
  ┃  「方法章がその数値を生んだ式を説明しているか」は見ていない。         ┃
  ┃  したがってゲートの PASS は投稿可を意味しない。                      ┃
  ┃  manuscript/PENDING_RERUN.md を読むこと。archive_pdf.sh は拒む。     ┃
  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
EOS
}

case "${1:-verify}" in
  verify) cmd_verify; warn_pending ;;
  twice)  cmd_twice;  warn_pending ;;
  *) echo "usage: $0 {verify|twice}"; exit 2 ;;
esac
