# -*- coding: utf-8 -*-
"""原稿 §3.4(水準模型)が引用する数値が、正本産生器の出力と一致するかを確かめる。

なぜ要るか。中核表は `check_manuscript_table` が守っているが、方法章の散文に埋めた数値は
これまで誰も見ていなかった。実際、手で書き写した「全国中央 19MW」は沖縄の中央値の
取り違えで、産生器を書いて初めて露見した。

守る対象は少ない。§3.4 は論文の節であって物料表ではないので、本文に残す数値は
主張を担うものだけに絞ってある(2026-08-03 の整理で 17個 → 4個)。門もそれに合わせる。
比較の相手は `results/numbers/level_model_v66.json`(`build_level_v66.py` の産物)。
"""
import json, pathlib, re, sys
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
J = W/"results"/"numbers"/"level_model_v66.json"
TEX = W/"manuscript"/"sections"/"method.tex"

if not J.exists():
    sys.exit(f"[FATAL] {J} が無い。先に build_level_v66.py を走らせること。")
R = json.loads(J.read_text(encoding="utf-8"))
src = re.sub(r"\s+", " ", TEX.read_text(encoding="utf-8"))
share = R["roster_purified"] / R["n_phantom"]          # 真値を公表しない局は何局に一つか
WORD = {2:"two",3:"three",4:"four",5:"five",6:"six",7:"seven",8:"eight",9:"nine",10:"ten"}

CHECKS = [
    ("標定区の負荷率",   f"give {R['lambda_tepco']:.2f}."),
    ("区域負荷率の幅",   f"between {R['lambda_min']:.2f} and {R['lambda_max']:.2f}"),
    ("台帳名の総数",     f"all {R['n_ledger_names']:,} of them"),
    ("真値を公表しない局", f"one substation in {WORD[round(share)]} that publishes no flow"),
]

print(f"=== 方法章の門: §3.4 の {len(CHECKS)} 個の数値を正本の出力と突き合わせる ===")
ng = []
for label, want in CHECKS:
    if want in src:
        print(f"  一致  {label:<20} {want}")
    else:
        print(f"  ★不一致 {label:<20} 本文に見当たらない: {want}")
        ng.append(want)
if ng:
    print(f"\n★FAIL: {len(ng)} 個が本文と食い違う。")
    print("  産生器の出力が正で、本文を直す。逆をやってはならない。")
    sys.exit(1)
print(f"\n★PASS: 方法章 §3.4 の数値はすべて {J.name} の産物である")
