#!/usr/bin/env python3
"""金额单位迁移：万元 → 元（ADR-006）。⚠️ 只执行一次！

流程：
1. 幂等保护：检查特征（assets 表金额数量级），若疑似已迁移则**中止**；
2. 备份库到 <db>.bak.YYYYMMDD；
3. 事务内逐表逐列 UPDATE（×10000），失败整体回滚；
4. 抽样校验：每表随机 5 行，输出 迁移前值 / 迁移后值 / 比值（应=10000）；
5. 打印完成摘要。

用法：
    python3 migrate_amount_to_yuan.py [db_path]
    # db_path 缺省为脚本同目录 core_holdings.db（隔离测试可传 /tmp 副本）

幂等保护说明（特征选择）：
    旧单位（万元）口径下，全库金额上限量级为：
    - assets.salePrice 最大 ~3256（3256 万 = 3256 万元级单价）
    - assets.soldAmount 最大 ~47200（4.7 亿）
    迁移为元后：salePrice 最大 ~32,560,000、soldAmount 最大 ~472,000,000。
    故判定：MAX(salePrice) > 100000 或 MAX(soldAmount) > 1000000 → 疑似已迁移，中止。
    （任务书示例阈值 1000 在真实库上会误伤——旧单位下 salePrice 已有 3256，故上调。）
"""
import os
import random
import shutil
import sqlite3
import sys
from datetime import date

# 全量金额列清单（表, 列）——全仓搜索确认仅这 5 张表含金额语义字段
TABLES = [
    ("assets", ["salePrice", "soldAmount"]),
    ("projects", ["expectedAmount", "quoteAmount", "contractAmount", "paidAmount"]),
    ("project_items", ["price", "amount"]),
    ("outbounds", ["amount"]),
    ("flows", ["amount"]),
]

FACTOR = 10000


def _db_path() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "core_holdings.db")


def _guard(conn: sqlite3.Connection) -> None:
    """幂等保护：疑似已迁移则中止（不备份、不写库）"""
    max_price = conn.execute("SELECT MAX(salePrice) FROM assets").fetchone()[0] or 0
    max_sold = conn.execute("SELECT MAX(soldAmount) FROM assets").fetchone()[0] or 0
    if max_price > 100000 or max_sold > 1000000:
        print(f"[ABORT] 疑似已迁移为元：MAX(salePrice)={max_price}, MAX(soldAmount)={max_sold}")
        print("       本脚本只执行一次，请勿重复运行。如需回滚请用 migrate_amount_to_wan.py")
        sys.exit(1)
    print(f"[guard] 数量级检查通过（MAX(salePrice)={max_price}, MAX(soldAmount)={max_sold}，符合旧单位特征）")


def _sample_before(conn: sqlite3.Connection) -> dict:
    """每表随机抽 5 行，记录 (id, 列, 迁移前值)"""
    samples = {}
    for table, cols in TABLES:
        rows = conn.execute(f"SELECT id FROM {table} ORDER BY RANDOM() LIMIT 5").fetchall()
        samples[table] = []
        for (rid,) in rows:
            for c in cols:
                v = conn.execute(f"SELECT {c} FROM {table} WHERE id=?", (rid,)).fetchone()[0]
                samples[table].append((rid, c, v))
    return samples


def main() -> None:
    db = _db_path()
    if not os.path.isfile(db):
        print(f"[ERROR] 库文件不存在：{db}")
        sys.exit(1)

    conn = sqlite3.connect(db)
    conn.isolation_level = None  # autocommit 模式，事务由下方显式 BEGIN/COMMIT 控制
    try:
        _guard(conn)

        # 1. 备份
        bak = f"{db}.bak.{date.today().strftime('%Y%m%d')}"
        shutil.copy2(db, bak)
        print(f"[backup] 已备份 → {bak}")

        # 2. 抽样（迁移前值）
        samples = _sample_before(conn)

        # 3. 事务内逐表逐列 UPDATE
        conn.execute("BEGIN IMMEDIATE")
        updates = []
        for table, cols in TABLES:
            for c in cols:
                sql = f"UPDATE {table} SET {c} = {c} * {FACTOR} WHERE {c} IS NOT NULL"
                updates.append(sql)
                conn.execute(sql)
                print(f"[update] {sql}  → {conn.total_changes} (累计)")
        conn.commit()
        print(f"[update] 事务已提交，共 {len(updates)} 条 UPDATE")

        # 4. 抽样校验（迁移后值 + 比值）
        print("\n=== 抽样校验（每表随机 5 行 × 各金额列）===")
        bad = 0
        for table, cols in TABLES:
            print(f"\n--- {table} ---")
            for rid, c, before in samples[table]:
                after = conn.execute(f"SELECT {c} FROM {table} WHERE id=?", (rid,)).fetchone()[0]
                if before in (0, None):
                    ratio = "-"
                    ok = after in (0, None)
                else:
                    ratio = round(after / before, 6)
                    ok = abs(after - before * FACTOR) < 1e-6
                if not ok:
                    bad += 1
                print(f"  id={rid} {c}: 迁移前={before} → 迁移后={after}  比值={ratio}  {'OK' if ok else 'MISMATCH!'}")

        # 5. 摘要
        print("\n=== 完成摘要 ===")
        for table, cols in TABLES:
            for c in cols:
                mx = conn.execute(f"SELECT MAX({c}) FROM {table}").fetchone()[0]
                print(f"  {table}.{c}: MAX = {mx}")
        if bad:
            print(f"[FAIL] {bad} 条抽样校验不一致，请检查！")
            sys.exit(2)
        print(f"[DONE] 金额单位迁移完成（万元→元，×{FACTOR}），抽样校验全部通过。备份：{bak}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
