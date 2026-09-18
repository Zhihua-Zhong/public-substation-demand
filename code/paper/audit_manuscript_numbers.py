# -*- coding: utf-8 -*-
"""原稿に現れる数値を洗い出し、出所を突き止めるための台帳を作る。

目的: v6.3 で書かれた原稿を v6.5 へ移行するにあたり、「どの数字を直す必要があるか」を
  推測でなく網羅で把握する。原稿の各節から数値を抽出し、v6.5 の産出物に同じ値が
  あるかを照合して、一致/不一致/未確認 に分類する。

出力: results/MANIFEST_numbers.csv (節・行・文脈・数値・照合結果)
"""
import re, sys, pathlib, csv, io, json
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
MS = W/"manuscript"/"sections"
OUT = W/"results"

# 本文が使う節(cas双欄=投稿対象が読む v63 系)
SECTIONS = sorted(MS.glob("*_v63.tex")) or sorted(MS.glob("*.tex"))

# 数値の抽出: 小数・百分率・千区切り・範囲。LaTeXコマンドや参照は除く
NUM = re.compile(r"(?<![\\A-Za-z0-9_])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+)\s*(\\,?%|\\%|%)?")
SKIP_CTX = re.compile(r"\\(label|ref|cite|eqref|includegraphics|input|section|subsection|begin|end)\b")

rows = []
for f in SECTIONS:
    for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("%"): continue
        if SKIP_CTX.search(s): continue
        for m in NUM.finditer(s):
            val, pct = m.group(1), bool(m.group(2))
            # 明らかな非データ(年・式番号・1桁の列挙)は落とす
            if not pct and re.fullmatch(r"\d{1,2}", val): continue
            if re.fullmatch(r"(19|20)\d{2}", val): continue
            ctx = s[max(0, m.start()-60):m.end()+60]
            rows.append(dict(section=f.name, line=i, value=val + ("%" if pct else ""),
                             context=re.sub(r"\s+", " ", ctx)))

# v6.5 の産出物に同じ値があるか(素朴だが網羅的な照合)
v65_text = ""
for p in list((W/"results"/"numbers").glob("*")) + [W/"data"/"offline"/"MANIFEST.json"]:
    if p.is_file():
        try: v65_text += p.read_text(encoding="utf-8", errors="replace")
        except Exception: pass
for r in rows:
    bare = r["value"].rstrip("%").replace(",", "")
    r["found_in_v65_results"] = "yes" if (v65_text and bare in v65_text) else "no"

OUT.mkdir(parents=True, exist_ok=True)
dest = OUT/"MANIFEST_numbers.csv"
with io.open(dest, "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["section","line","value","found_in_v65_results","context"])
    w.writeheader(); w.writerows(rows)

from collections import Counter
c = Counter(r["section"] for r in rows)
print(f"抽出した数値: {len(rows)} 件 / 節 {len(SECTIONS)} 本")
for k, v in sorted(c.items(), key=lambda x: -x[1]): print(f"  {v:4d}  {k}")
print(f"\n台帳: {dest}")
print("※ この台帳は「原稿に数字がどこにいくつあるか」の網羅であり、")
print("   各値の正誤ではない。v6.5 の産出物が揃った段階で照合列が意味を持つ。")
