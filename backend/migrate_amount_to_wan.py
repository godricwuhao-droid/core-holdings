#!/usr/bin/env python3
"""金额单位回滚：元 → 万元（÷10000）。⚠️ 仅回滚用！只执行一次！

与 migrate_amount_to_yuan.py 对称：
1. 幂等保护：检查特征，若疑似**尚未迁移**（仍是旧单位）则**中止**；
2. 备份库到 <db>.bak.YYYYMMDD；
3. 事务内逐表逐列 UPDATE（÷10000），失败整体回滚；
4. 抽样校验：每表随机 5 行，输出 回滚前值 / 回滚后值 / 比值（应=0.0001）；
5. 打印完成摘要。

用法：
    python3 migrate_amount_to_wan.py [db_path]

幂等保护说明（特征选择，与正向脚本对称）：
    元口径下 assets.salePrice 最大 ~32,560,000、soldAmount 最大 ~472,000,000；
    旧单位（万元）下分别为 ~3256 / ~47200。
    故判定：MAX(salePrice) < 100000 且 MAX(soldAmount) < 1000000 → 疑似未迁移（已是旧单位），中止。
"""
import os
import shutil
import sqlite3
import sys
from datetime import date

# 全量金额列清单（表, 列）——与正向脚本完全一致
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
    """幂等保护：疑似未迁移（已是旧单位）则中止（不备份、不写库）"""
    max_price = conn.execute("SELECT MAX(salePrice) FROM assets").fetchone()[0] or 0
    max_sold = conn.execute("SELECT MAX(soldAmount) FROM assets").fetchone()[0] or 0
    if max_price < 100000 and max_sold < 1000000:
        print(f"[ABORT] 疑似尚未迁移（已是旧单位）：MAX(salePrice)={max_price}, MAX(soldAmount)={max_sold}")
        print("       本脚本仅回滚用，只执行一次。如需正向迁移请用 migrate_amount_to_yuan.py")
        sys.exit(1)
    print(f"[guard] 数量级检查通过（MAX(salePrice)={max_price}, MAX(soldAmount)={max_sold}，符合元口径特征）")


def _sample_before(conn: sqlite3.Connection) -> list:
    """每表随机抽 5 行，记录 (table, id, 列, 回滚前值)"""
    samples = []
    for table, cols in TABLES:
        rows = conn.execute(f"SELECT id FROM {table} ORDER BY RANDOM() LIMIT 5").fetchall()
        for (rid,) in rows:
            for c in cols:
                v = conn.execute(f"SELECT {c} FROM {table} WHERE id=?", (rid,)).fetchone()[0]
                samples.append((table, c, rid, v))
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

        # 2. 抽样（回滚前值）
        samples = _sample_before(conn)

        # 3. 事务内逐表逐列 UPDATE
        conn.execute("BEGIN IMMEDIATE")
        updates = []
        for table, cols in TABLES:
            for c in cols:
                sql = f"UPDATE {table} SET {c} = {c} / {FACTOR} WHERE {c} IS NOT NULL"
                updates.append(sql)
                conn.execute(sql)
        conn.commit()
        print(f"[update] 事务已提交，共 {len(updates)} 条 UPDATE（÷{FACTOR}）")

        # 4. 抽样校验（回滚后值 + 比值）
        print("\n=== 抽样校验（每表随机 5 行 × 各金额列）===")
        bad = 0
        for table, c, rid, before in samples:
            after = conn.execute(f"SELECT {c} FROM {table} WHERE id=?", (rid,)).fetchone()[0]
            if before in (0, None):
                ratio = "-"
                ok = after in (0, None)
            else:
                ratio = round(after / before, 8)
                ok = abs(after - before / FACTOR) < 1e-9
            if not ok:
                bad += 1
            print(f"  {table} id={rid} {c}: 回滚前={before} → 回滚后={after}  比值={ratio}  {'OK' if ok else 'MISMATCH!'}")

        # 5. 摘要
        print("\n=== 完成摘要 ===")
        for table, cols in TABLES:
            for c in cols:
                mx = conn.execute(f"SELECT MAX({c}) FROM {table}").fetchone()[0]
                print(f"  {table}.{c}: MAX = {mx}")
        if bad:
            print(f"[FAIL] {bad} 条抽样校验不一致，请检查！")
            sys.exit(2)
        print(f金额单位回滚完成（元→旧单位，÷{FACTOR}），抽样校验全部通过。备份：{bak}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
