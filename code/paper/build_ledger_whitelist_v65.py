# -*- coding: utf-8 -*-
"""台帳被覆の白名単を離線層から作る。図4の生成器が局を絞るのに使う。

**5,968 と 5,950 はどちらも台帳被覆である。数える側が違う。**

  台帳名(src_name)を数えると **5,968**  ← 論文の見出しの数。表3の Stations 列
  推計キー(station_id)を数えると **5,950**  ← 実在する系列の数。このファイル

差の 18 は、二つの台帳名が同じ推計キーへ落ちる組である(台帳名36件→キー18件)。
内訳は関西15・中部1・中国1・東北1で、関西に集中するのは norm2 キーの衝突による。
`gen_scoreboard_table_v65.py` は `drop_duplicates(["utility","src_name"])` で
台帳名の側を数えるので 5,968 になる。**どちらも正しく、取り違えると18局ずれる。**

図は一つの点が一つの推計系列に対応するので、描けるのは 5,950 である。

導出(`calc_annual_monthly_v65.py` と同じ橋渡し):
  station_key_map(kind='master') で推計IDを台帳名へ橋渡しし、
  substation_master の node_type='haihen' に載るものだけを残し、
  さらに推計を実際に持つ局と交わらせる。
橋渡しだけなら 6,121。台帳に載っていても推計が無い局がある。

このファイルは v6.4 期に凍結入力として置かれていたものと**内容が完全に一致する**。
つまり当時の白名単は正しく、いま離線層から作り直せることが確かめられた。

データベースには接続しない。出力の列は下流に合わせて u / sid とする。
"""
import sys, pathlib
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
W = pathlib.Path(__file__).resolve().parents[2]
OFF, OUT = W/"data"/"offline", W/"results"/"numbers"
sys.path.insert(0, str(W/"code"/"engine"/"analysis"/"unified"))
from est_source import offline_source
EST_FILE, TAG = offline_source()   # v6.5 file unless PAPER_EST_FILE names the v6.6 one (E7)
OUT.mkdir(parents=True, exist_ok=True)

ORDER = ["HOKKAIDO","TOHOKU","TEPCO","CHUBU","HOKURIKU",
         "KANSAI","CHUGOKU","SHIKOKU","KYUSHU","OKINAWA"]

km = pd.read_parquet(OFF/"station_key_map.parquet")
km = km[km.kind == "master"][["utility","key","src_name"]].drop_duplicates()
sm = pd.read_parquet(OFF/"substation_master.parquet",
                     columns=["utility","station_id","node_type"])
sm = sm[sm.node_type == "haihen"][["utility","station_id"]].rename(
        columns={"station_id":"src_name"})
ledger = (km.merge(sm, on=["utility","src_name"])[["utility","key"]]
            .drop_duplicates().rename(columns={"key":"station_id"}))
est = pd.read_parquet(OFF/EST_FILE,
                      columns=["utility","station_id"]).drop_duplicates()
wl = (est.merge(ledger, on=["utility","station_id"])
         .drop_duplicates()
         .rename(columns={"utility":"u", "station_id":"sid"}))

# 行順をファイルの権威にする(実行計画の揺れを入れない)
wl["_o"] = wl.u.map({u:i for i,u in enumerate(ORDER)})
wl = wl.sort_values(["_o","sid"], kind="mergesort").drop(columns="_o").reset_index(drop=True)

print(f"台帳被覆: {len(wl):,}局")
for u in ORDER:
    print(f"  {u:<9} {int((wl.u==u).sum()):>5}")
assert len(wl) == 5950, f"推計キーが 5,950 でない: {len(wl)}"

wl.to_csv(OUT/f"ledger_whitelist_{TAG}.csv", index=False, encoding="utf-8-sig")
print(f"[出力] {OUT/f'ledger_whitelist_{TAG}.csv'}")
