#!/usr/bin/env python3
"""一次性数据操作：清空指定遥感数据产品的可售明细（rs_items），用户重新录入。

背景
----
「遥感数据-2026」（assets#29，type='遥感数据'）的 97 条可售明细（省/市 × 精度 ×
月份，月份跨 2024-10 ~ 2026-09）为用户早期录入的演示数据，需整体清空后重新录入。
父产品本身（unit / repeatSale / 价格区间等）保持不变，只清空明细行。

⚠️ RS-REPEAT-20261022-FIX 起：容器 `quantity` = **可售明细条数**（`sync_container_quantity`），
故清空明细后 `quantity` 同事务同步为 **0**（此前保持旧值，会让「数量」与明细条数脱钩，
进而使明细行下单被 `quantity - lockedQty - shippedQty >= 1` 卡死在 1 条）。

为什么必须同时清购物车
----------------------
`cart_items.itemId` 指向 `rs_items.id`（ADR-011，无 DB 外键）。若只删 rs_items，
用户购物车里会留下悬空 itemId（前端显示坏行、结算时 400「明细不存在」）。
这些行都是购物车草稿（未生成订单），删掉后用户重新选明细即可，故一并清理。

安全约束（预检任一不满足即中止，不强删）
--------------------------------------
1. 目标产品必须存在且 `type == '遥感数据'`（防误删普通产品）；
2. `project_items.itemId` 若引用待删明细 → **中止**（已产生销售关联，不允许清空，
   否则销量/合同明细会指向不存在的明细）；
3. 执行前用 SQLite 在线备份 API 备份整库到 /tmp（服务在线运行，不用 cp 直接拷贝，
   delete 日志模式下直接 cp 可能拿到半写状态的文件）。

执行方式
--------
    # 只看预检报告，不写库（推荐先跑）
    python3 backend/scripts/reset_rs_items.py --asset-id 29 --dry-run

    # 真实执行：必须显式 --yes（备份 + 单事务删除 + 回读校验）
    python3 backend/scripts/reset_rs_items.py --asset-id 29 --yes

对应任务：RS-RESET-20261022（详见 docs/backend/changelog.md）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

# 遥感数据类型标记（与 src/services.py 的 RS_DATA_TYPE 保持一致；此处独立常量
# 以避免脚本 import 业务包，脚本可在服务代码变更时独立运行）
RS_DATA_TYPE = "遥感数据"

LOG_TARGET = "asset"
LOG_ACTION = "清空可售明细"
LOG_OPERATOR = "admin"

DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)

# 允许变化的表（其余表行数必须前后一致）——仅用于报告标注，不做白名单校验
EXPECTED_CHANGED_TABLES = {"rs_items", "cart_items", "logs"}


class AbortPrecheck(Exception):
    """预检不通过 / 执行期二次校验失败：中止且不写库。"""


def now_str() -> str:
    """与 services.now_str() 同口径（OpLog.time 为 'YYYY-MM-DD HH:MM' 字符串）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 只读查询工具

def table_counts(con: sqlite3.Connection) -> dict[str, int]:
    """返回全库每张表的行数（按表名排序）。"""
    names = [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def fetch_asset(con: sqlite3.Connection, asset_id: int) -> tuple | None:
    return con.execute(
        "SELECT id, code, name, type, quantity, unit, repeatSale, soldCount, soldAmount "
        "FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()


def fetch_rs_item_ids(con: sqlite3.Connection, asset_id: int) -> list[int]:
    return [r[0] for r in con.execute(
        "SELECT id FROM rs_items WHERE assetId = ? ORDER BY id", (asset_id,)
    )]


def fetch_rs_summary(con: sqlite3.Connection, asset_id: int) -> dict:
    row = con.execute(
        "SELECT COUNT(*), MIN(saleMonth), MAX(saleMonth), MIN(price), MAX(price) "
        "FROM rs_items WHERE assetId = ?",
        (asset_id,),
    ).fetchone()
    return {
        "count": row[0],
        "month_min": row[1] or "",
        "month_max": row[2] or "",
        "price_min": row[3],
        "price_max": row[4],
    }


def fetch_cart_rows(con: sqlite3.Connection, item_ids: list[int]) -> list[tuple]:
    if not item_ids:
        return []
    marks = ",".join("?" * len(item_ids))
    return con.execute(
        f"SELECT id, userId, assetId, itemId, customer, qty FROM cart_items "
        f"WHERE itemId IN ({marks}) ORDER BY id",
        item_ids,
    ).fetchall()


def fetch_sales_refs(con: sqlite3.Connection, item_ids: list[int]) -> list[tuple]:
    """project_items 中引用待删明细的行（有销售 → 不允许删除）。"""
    if not item_ids:
        return []
    marks = ",".join("?" * len(item_ids))
    return con.execute(
        f"SELECT id, project_id, assetId, itemId, qty, status FROM project_items "
        f"WHERE itemId IN ({marks}) ORDER BY id",
        item_ids,
    ).fetchall()


def sync_container_quantity(con: sqlite3.Connection, asset_id: int) -> tuple[int, int]:
    """删明细后同步容器 quantity（与 `services._sync_container_quantity` 同口径）。

    - 无真实锁定/已交付（lockedQty == 0 and shippedQty == 0）→ quantity = COUNT(rs_items)
      （清空场景即 0）；
    - 否则不改数量，仅校验 quantity >= lockedQty + shippedQty，不满足即中止。

    返回 (before, after)。脚本不 import 业务包，故此处用等价 SQL 实现，
    口径变更时须与 `src/services.py` 的 `_sync_container_quantity` 同步修改。
    """
    row = con.execute(
        "SELECT quantity, lockedQty, shippedQty FROM assets WHERE id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        raise AbortPrecheck(f"事务内复核失败：assets#{asset_id} 已不存在")
    quantity, locked, shipped = int(row[0]), int(row[1] or 0), int(row[2] or 0)
    count = con.execute(
        "SELECT COUNT(*) FROM rs_items WHERE assetId = ?", (asset_id,)
    ).fetchone()[0]
    if locked == 0 and shipped == 0:
        if quantity != count:
            con.execute(
                "UPDATE assets SET quantity = ?, updatedAt = ? WHERE id = ?",
                (count, now_str()[:10], asset_id),
            )
        return quantity, count
    if quantity < locked + shipped:
        raise AbortPrecheck(
            f"数量不变量不满足：assets#{asset_id} quantity={quantity} < "
            f"lockedQty={locked} + shippedQty={shipped}（在售数据不自动改数量）"
        )
    return quantity, quantity


def fetch_dangling_cart_count(con: sqlite3.Connection) -> int:
    """全库购物车中 itemId 指向不存在 rs_items 的悬空行数。"""
    return con.execute(
        "SELECT COUNT(*) FROM cart_items c WHERE c.itemId IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM rs_items r WHERE r.id = c.itemId)"
    ).fetchone()[0]


# ---------------------------------------------------------------- 备份

def backup_database(db_path: str) -> tuple[str, str]:
    """用 SQLite 在线备份 API 备份整库，返回 (备份路径, 使用方式描述)。

    优先调用 sqlite3 CLI 的 `.backup`；CLI 不可用时退回 Python 的
    `Connection.backup()`（两者是同一个在线备份 API，服务运行中调用安全）。
    绝不用 cp：delete 日志模式下边写边拷贝可能得到损坏/半写文件。
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"/tmp/rs-items-backup-{ts}.db"
    if os.path.exists(backup_path):  # 同秒重复执行时避免覆盖既有备份
        backup_path = f"/tmp/rs-items-backup-{ts}-{os.getpid()}.db"

    cli = shutil.which("sqlite3")
    if cli:
        proc = subprocess.run(
            [cli, db_path, f".backup {backup_path}"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sqlite3 .backup 失败: {proc.stderr.strip()}")
        method = "sqlite3 CLI .backup（在线备份 API）"
    else:
        try:
            src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            dst = sqlite3.connect(backup_path)
            try:
                src.backup(dst)  # Python 等价于 .backup
            finally:
                dst.close()
                src.close()
        except Exception as exc:  # noqa: BLE001 - 备份失败必须硬中止
            raise RuntimeError(f"Python sqlite3 backup 失败: {exc}") from exc
        method = "Python sqlite3 Connection.backup()（sqlite3 CLI 不可用，走同一在线备份 API）"

    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        raise RuntimeError(f"备份文件未生成或为空: {backup_path}")
    return backup_path, method


def verify_backup(backup_path: str, expect_rs_count: int) -> dict:
    """校验备份可用：integrity_check + rs_items 行数与源库一致。"""
    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        rs_count = con.execute("SELECT COUNT(*) FROM rs_items").fetchone()[0]
        tables = len(table_counts(con))
    finally:
        con.close()
    if integrity != "ok":
        raise RuntimeError(f"备份完整性校验失败: {integrity}")
    if rs_count != expect_rs_count:
        raise RuntimeError(
            f"备份行数不符: 备份 rs_items={rs_count}, 源库={expect_rs_count}"
        )
    return {"integrity": integrity, "rs_items": rs_count, "tables": tables}


# ---------------------------------------------------------------- 预检

def run_precheck(db_path: str, asset_id: int) -> dict:
    """只读预检：类型/条数/月份跨度/价格区间/购物车引用/销售引用。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        asset = fetch_asset(con, asset_id)
        if asset is None:
            raise AbortPrecheck(f"assets 中不存在 id={asset_id} 的产品")
        if asset[3] != RS_DATA_TYPE:
            raise AbortPrecheck(
                f"assets#{asset_id}「{asset[2]}」的 type='{asset[3]}'，"
                f"不是「{RS_DATA_TYPE}」→ 拒绝操作（防止误删普通产品明细）"
            )

        item_ids = fetch_rs_item_ids(con, asset_id)
        summary = fetch_rs_summary(con, asset_id)
        cart_rows = fetch_cart_rows(con, item_ids)
        sales_refs = fetch_sales_refs(con, item_ids)
        counts = table_counts(con)
        dangling_before = fetch_dangling_cart_count(con)

        if sales_refs:
            detail = "; ".join(
                f"project_items#{r[0]}(project_id={r[1]}, itemId={r[3]}, qty={r[4]}, status={r[5]})"
                for r in sales_refs
            )
            raise AbortPrecheck(
                f"存在 {len(sales_refs)} 条销售明细引用待删 rs_items → 中止（有销售关联不允许清空）：{detail}"
            )

        return {
            "asset": asset,
            "item_ids": item_ids,
            "summary": summary,
            "cart_rows": cart_rows,
            "sales_refs": sales_refs,
            "counts": counts,
            "dangling_cart_before": dangling_before,
        }
    finally:
        con.close()


def print_precheck(report: dict, asset_id: int, db_path: str) -> None:
    asset = report["asset"]
    s = report["summary"]
    print("=" * 78)
    print("预检报告")
    print("=" * 78)
    print(f"数据库            : {db_path}")
    print(f"目标产品          : assets#{asset[0]} {asset[1]}「{asset[2]}」type={asset[3]}")
    print(f"产品本体现状      : quantity={asset[4]}, unit={asset[5]!r}, "
          f"repeatSale={bool(asset[6])}, soldCount={asset[7]}, soldAmount={asset[8]}")
    print("  ↑ 本次只清明细行；quantity 将同步为 0（容器数量 = 可售明细条数，RS-REPEAT-20261022-FIX）")
    print(f"待删 rs_items     : {s['count']} 条")
    if s["count"]:
        print(f"  月份跨度        : {s['month_min']} ~ {s['month_max']}")
        print(f"  价格区间(元/份) : {s['price_min']:.2f} ~ {s['price_max']:.2f}")
        ids = report["item_ids"]
        print(f"  明细 id 范围    : {ids[0]} ~ {ids[-1]}（共 {len(ids)} 个）")
    print(f"待清 cart_items   : {len(report['cart_rows'])} 行")
    for r in report["cart_rows"]:
        print(f"  cart_items#{r[0]} | userId={r[1]} | assetId={r[2]} | itemId={r[3]} "
              f"| customer={r[4]!r} | qty={r[5]}")
    print(f"销售引用          : project_items.itemId 命中 {len(report['sales_refs'])} 行（须为 0 才允许执行）")
    print(f"当前悬空购物车行  : {report['dangling_cart_before']} 行（应为 0）")
    print("=" * 78)


# ---------------------------------------------------------------- 执行

def execute_reset(db_path: str, asset_id: int, expect_items: int, expect_cart: int) -> dict:
    """单事务执行：清理购物车引用 + 删除明细 + 写 OpLog。

    事务内做第二次校验（BEGIN IMMEDIATE 先取写锁），避免预检后到写库前
    有并发写入（服务在线运行）造成误删。
    """
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            asset = fetch_asset(con, asset_id)
            if asset is None or asset[3] != RS_DATA_TYPE:
                raise AbortPrecheck("事务内复核失败：目标产品不存在或 type 已变更")

            item_ids = fetch_rs_item_ids(con, asset_id)
            if len(item_ids) != expect_items:
                raise AbortPrecheck(
                    f"事务内复核失败：明细条数发生变化（预检 {expect_items} → 现在 {len(item_ids)}），请重跑预检"
                )
            sales_refs = fetch_sales_refs(con, item_ids)
            if sales_refs:
                raise AbortPrecheck(
                    f"事务内复核失败：出现 {len(sales_refs)} 条 project_items 销售引用，中止"
                )

            summary = fetch_rs_summary(con, asset_id)
            marks = ",".join("?" * len(item_ids)) if item_ids else "NULL"

            cart_deleted = 0
            if item_ids:
                cart_deleted = con.execute(
                    f"DELETE FROM cart_items WHERE itemId IN ({marks})", item_ids
                ).rowcount
            if cart_deleted != expect_cart:
                # 购物车行是草稿，多删/少删不应静默：以事务内实际值为准，但要求与预检一致
                raise AbortPrecheck(
                    f"事务内复核失败：购物车引用行数变化（预检 {expect_cart} → 现在 {cart_deleted}），请重跑预检"
                )

            items_deleted = con.execute(
                "DELETE FROM rs_items WHERE assetId = ?", (asset_id,)
            ).rowcount
            if items_deleted != expect_items:
                raise AbortPrecheck(
                    f"事务内复核失败：删除明细行数 {items_deleted} != 预检 {expect_items}，已回滚"
                )

            # RS-REPEAT-20261022-FIX §1：容器 quantity = 可售明细条数（删除后同事务同步）
            qty_before, qty_after = sync_container_quantity(con, asset_id)

            detail = (
                f"清空 {items_deleted} 条明细（月份 {summary['month_min']} ~ {summary['month_max']}）"
                f"；同时清理 {cart_deleted} 行购物车引用；容器数量 {qty_before} → {qty_after}"
            )
            con.execute(
                "INSERT INTO logs (target, targetName, action, detail, operator, time, "
                "assetId, changes) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (LOG_TARGET, asset[2], LOG_ACTION, detail, LOG_OPERATOR, now_str(), asset_id),
            )
            log_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            con.execute("COMMIT")
            return {
                "cart_deleted": cart_deleted,
                "items_deleted": items_deleted,
                "detail": detail,
                "log_id": log_id,
                "asset_name": asset[2],
                "qty_before": qty_before,
                "qty_after": qty_after,
            }
        except AbortPrecheck:
            con.execute("ROLLBACK")
            raise
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def print_readback(db_path: str, asset_id: int, before: dict[str, int],
                   result: dict) -> bool:
    """回读校验 + 全库行数前后对比，返回是否全部符合预期。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rs_left = con.execute(
            "SELECT COUNT(*) FROM rs_items WHERE assetId = ?", (asset_id,)
        ).fetchone()[0]
        dangling_after = fetch_dangling_cart_count(con)
        asset = fetch_asset(con, asset_id)
        after = table_counts(con)
        log_row = con.execute(
            "SELECT id, target, targetName, action, detail, operator, time, assetId "
            "FROM logs WHERE id = ?", (result["log_id"],)
        ).fetchone()
    finally:
        con.close()

    ok = True
    print("-" * 78)
    print("回读校验")
    print("-" * 78)
    checks = [
        (f"assets#{asset_id} rs_items 行数 = 0", rs_left, 0),
        ("cart_items 中悬空 itemId = 0", dangling_after, 0),
        # RS-REPEAT-20261022-FIX：容器数量 = 明细条数（清空后应为 0；在售数据只校验不改）
        (f"assets#{asset_id} quantity = 同步目标", asset[4], result["qty_after"]),
    ]
    for label, actual, expected in checks:
        flag = "OK" if actual == expected else "FAIL"
        if flag == "FAIL":
            ok = False
        print(f"  [{flag}] {label}（实际 {actual}）")

    print(f"  OpLog 回读: #{log_row[0]} target={log_row[1]} targetName={log_row[2]!r} "
          f"action={log_row[3]!r} assetId={log_row[7]} time={log_row[6]}")
    print(f"             detail={log_row[4]!r} operator={log_row[5]!r}")
    print(f"  产品本体      : quantity={asset[4]}（{result['qty_before']} → {result['qty_after']}，"
          f"= 明细条数）, unit={asset[5]!r}, repeatSale={bool(asset[6])}, "
          f"soldCount={asset[7]}, soldAmount={asset[8]}")

    print("-" * 78)
    print("全库行数对比（before → after）")
    print("-" * 78)
    print(f"  {'表名':<22}{'before':>8}{'after':>8}{'delta':>8}  备注")
    for name in sorted(before):
        b = before[name]
        a = after.get(name, -1)
        delta = a - b
        if delta == 0:
            note = ""
        elif name in EXPECTED_CHANGED_TABLES:
            note = "预期内变更"
        else:
            note = "!! 非预期变更"
            ok = False
        print(f"  {name:<22}{b:>8}{a:>8}{delta:>+8}  {note}")
    extra = set(after) - set(before)
    if extra:
        ok = False
        print(f"  !! 新增表：{sorted(extra)}")
    return ok


# ---------------------------------------------------------------- 入口

def main() -> int:
    parser = argparse.ArgumentParser(
        description="清空指定遥感数据产品的可售明细 rs_items（含清理购物车引用），RS-RESET-20261022"
    )
    parser.add_argument("--asset-id", type=int, required=True,
                        help="目标产品 assets.id（必须存在且 type='遥感数据'）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只输出预检报告，不备份、不写库")
    parser.add_argument("--yes", action="store_true",
                        help="确认执行（缺省时仅预检后退出，不写库）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help=f"数据库路径（默认 {DEFAULT_DB_PATH}）")
    args = parser.parse_args()

    db_path = os.path.normpath(args.db)
    if not os.path.exists(db_path):
        print(f"[中止] 数据库不存在: {db_path}", file=sys.stderr)
        return 2

    # 1) 预检（只读）
    try:
        report = run_precheck(db_path, args.asset_id)
    except AbortPrecheck as exc:
        print(f"[中止] 预检失败：{exc}", file=sys.stderr)
        return 3

    print_precheck(report, args.asset_id, db_path)

    summary = report["summary"]
    if summary["count"] == 0:
        print("[跳过] 该产品没有可售明细（可能已清空），无需执行。")
        return 0

    if args.dry_run:
        print("[dry-run] 未备份、未写库。确认无误后加 --yes 执行。")
        return 0
    if not args.yes:
        print("[未执行] 预检通过但缺少 --yes 确认；本脚本不做任何写操作。")
        return 0

    # 2) 备份（在线备份 API，服务运行中安全）
    print("=" * 78)
    print("执行：备份 → 单事务删除 → 回读校验")
    print("=" * 78)
    try:
        backup_path, method = backup_database(db_path)
        backup_info = verify_backup(backup_path, summary["count"])
    except Exception as exc:  # noqa: BLE001 - 备份失败必须中止
        print(f"[中止] 备份失败，未做任何写操作：{exc}", file=sys.stderr)
        return 4
    print(f"备份路径          : {backup_path}（保留，不删除）")
    print(f"备份方式          : {method}")
    print(f"备份校验          : integrity_check={backup_info['integrity']}, "
          f"表数={backup_info['tables']}, rs_items={backup_info['rs_items']}（与源库一致）")

    before_counts = report["counts"]

    # 3) 单事务执行
    try:
        result = execute_reset(db_path, args.asset_id,
                               expect_items=summary["count"],
                               expect_cart=len(report["cart_rows"]))
    except AbortPrecheck as exc:
        print(f"[回滚] {exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"[回滚] 执行异常已回滚：{exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 6

    print(f"已删除 rs_items   : {result['items_deleted']} 条（assetId={args.asset_id}）")
    print(f"已清理 cart_items : {result['cart_deleted']} 行（itemId 引用该产品明细）")
    print(f"已写 OpLog        : #{result['log_id']}「{result['detail']}」")
    print(f"备份路径          : {backup_path}")

    # 4) 回读校验
    ok = print_readback(db_path, args.asset_id, before_counts, result)
    print("=" * 78)
    print("结果: " + ("全部校验通过" if ok else "存在校验失败项，请人工复核（可从备份恢复）"))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())
