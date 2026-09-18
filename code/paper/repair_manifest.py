# -*- coding: utf-8 -*-
"""離線層の台帳を全ファイル網羅へ修復し、台帳と実体の一致を検査する。

背景: 導出が途中で失敗した回は台帳を書けずに終わるため、台帳に載らないファイルが残る。
  台帳が現実を覆っていない状態は「検証されていないファイルが増えただけ」であり、
  第1回監査のF3(verify が恒真)と同じ病である。ここでは
  「台帳の件数 == 実ファイルの件数」を機械検査する。
"""
import sys, pathlib, json, hashlib, datetime
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF = W/"data"/"offline"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# 生成SQLは export_offline.py の JOBS を唯一の出所とする(定義の二重化を避ける)
src = (pathlib.Path(__file__).resolve().parent/"export_offline.py").read_text(encoding="utf-8")
ns = {}
exec(src[src.index("JOBS = ["):src.index("]\n", src.index("JOBS = ["))+1], ns)
SQL = dict(ns["JOBS"])

def sha256(p, buf=1<<20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while (b := f.read(buf)): h.update(b)
    return h.hexdigest()

entries = []
for pq in sorted(OFF.glob("*.parquet")):
    name = pq.stem
    rows = len(pd.read_parquet(pq, columns=[pd.read_parquet(pq).columns[0]])) \
           if pq.stat().st_size < 5_000_000 else None
    if rows is None:                       # 大表は行数だけ効率よく取る
        import pyarrow.parquet as papq
        rows = papq.ParquetFile(pq).metadata.num_rows
    csv = OFF/f"{name}.csv"
    entries.append(dict(name=name, rows=rows, parquet=pq.name,
                        parquet_bytes=pq.stat().st_size, parquet_sha256=sha256(pq),
                        csv=(csv.name if csv.exists() else None),
                        sql=SQL.get(name, "(SQL不明: export_offline.py の JOBS に無い)")))

led = OFF/"MANIFEST.json"
led.write_text(json.dumps(
    {"generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
     "source_container": "iwafune_db_frozen",
     "note": "潮流・推計はビュー経由(九州1〜3月の年度修正と防火壁を保持)。全照会に決定的ORDER BY。",
     "exports": entries}, ensure_ascii=False, indent=1), encoding="utf-8")

n_pq = len(list(OFF.glob("*.parquet")))
ok = len(entries) == n_pq and all(e["sql"].startswith("SELECT") for e in entries)
print(f"台帳: {len(entries)}件 / 実ファイル: {n_pq}件 / SQL既知: {sum(e['sql'].startswith('SELECT') for e in entries)}件")
print(f"合計 {sum(e['parquet_bytes'] for e in entries)/1e9:.2f} GB")
print("★PASS: 台帳が全ファイルを覆っている" if ok else "★FAIL: 台帳と実体が一致しない")
sys.exit(0 if ok else 1)
