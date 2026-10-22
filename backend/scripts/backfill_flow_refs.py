#!/usr/bin/env python3
"""一次性数据修复脚本：按 contractId 权威外键回填 flows.ref。

用途
----
历史清理脚本改过合同编号（contracts.code）但未同步流水（flows.ref），
导致部分流水的 ref 指向已不存在的旧合同编号。可见性判定按 contractId
权威外键放行，无越权问题，仅展示层编号对不上。本脚本将
`contractId` 非空且 ref 与现编号不一致的流水 ref 回填为对应合同现编号。

对应 QA 观察项
--------------
OBS-FIX20261022-01（docs/qa/bug-tracker.md）：QA 回归时标记了 5 条
存量流水（flows id 78/136/160/164/212）ref 为旧编号。按验收口径
（contractId 非空且 ref != contracts.code 的回读查询应为 0）实际
待修复行不止这 5 条——脚本执行时以实时查询为准，全部回填。

幂等 / 可重复执行
-----------------
UPDATE 条件为 `contractId IS NOT NULL AND ref != contracts.code`，
修过之后再跑影响 0 行，可安全重复执行。

预期影响行数
------------
任务单口径为 5 行（QA 标记数）；2026-10-22 实际执行时为 64 行
（含 QA 标记的 5 行，其余为同因未标记的历史流水）。已修过后为 0。

执行方式
--------
    python3 backend/scripts/backfill_flow_refs.py            # 预览 + 执行（默认）
    python3 backend/scripts/backfill_flow_refs.py --dry-run  # 仅预览不写库

按 ADR-031 口径：数据类修复放 backend/scripts/ 下显式脚本，不放启动期。
执行前请备份数据库（cp core_holdings.db /tmp/flows-backup-<ts>.db）。
"""

import argparse
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")

# 待修复行查询：contractId 非空、指向现存合同、且 ref 与现编号不一致
MISMATCH_SELECT = """
    SELECT f.id, f.contractId, f.ref, c.code
    FROM flows f
    JOIN contracts c ON f.contractId = c.id
    WHERE f.contractId IS NOT NULL
      AND f.ref != c.code
    ORDER BY f.id
"""

MISMATCH_COUNT = """
    SELECT COUNT(*) FROM flows f
    JOIN contracts c ON f.contractId = c.id
    WHERE f.contractId IS NOT NULL AND f.ref != c.code
"""

UPDATE_SQL = """
    UPDATE flows
    SET ref = (SELECT c.code FROM contracts c WHERE c.id = flows.contractId)
    WHERE contractId IS NOT NULL
      AND ref != (SELECT c.code FROM contracts c WHERE c.id = flows.contractId)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="按 contractId 回填 flows.ref（OBS-FIX20261022-01）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览将被修改的行，不写库")
    args = parser.parse_args()

    db = os.path.normpath(DB_PATH)
    if not os.path.exists(db):
        print(f"数据库不存在: {db}", file=sys.stderr)
        return 1

    # 1) 只读连接：预览将被修改的行数与前后对照
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(MISMATCH_SELECT).fetchall()
    finally:
        con.close()

    print(f"数据库: {db}")
    print(f"待修改行数: {len(rows)}")
    if rows:
        print("前后对照（flows.id | contractId | ref 旧值 -> 新值）:")
        for fid, cid, old_ref, new_code in rows:
            print(f"  {fid} | contractId={cid} | {old_ref} -> {new_code}")
    else:
        print("无待修改行（已修复或无数据），无需写库。")

    if args.dry_run:
        print("--dry-run：未写库。")
        return 0
    if not rows:
        return 0

    # 2) 写连接：执行回填
    con = sqlite3.connect(db)
    try:
        cur = con.execute(UPDATE_SQL)
        affected = cur.rowcount
        con.commit()
        # 3) 回读核对（同连接，事务已提交）
        remaining = con.execute(MISMATCH_COUNT).fetchone()[0]
    finally:
        con.close()

    print(f"已执行 UPDATE，影响行数: {affected}")
    print(f"回读核对：剩余待修改行数: {remaining}（应为 0）")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
