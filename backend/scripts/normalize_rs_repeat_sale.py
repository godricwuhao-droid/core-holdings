#!/usr/bin/env python3
"""存量归一：把指定遥感数据产品的可售明细 `rs_items.repeatSale` 一次性置为 0（ADR-038）。

背景
----
ADR-011 时期明细默认「可重复售卖」（只计次不扣量），`models.RsItem.repeatSale`
默认 `True`。ADR-038 起业务口径改为 **默认单次售卖**（一期通常只卖一次，售出即占用），
需要重复售卖的月份再逐条打开。ORM 默认值变更只影响新写入的行，**存量明细仍是 1**，
故需本脚本一次性归一（ADR-031：走 backend/scripts/ 显式脚本，dry-run + 备份 + OpLog，
不放启动迁移，也不手动改库）。

当前存量：`assets#29`「遥感数据-2026」60 条明细全部 repeatSale=1，合计 10,354,297 元。

口径与安全约束
--------------
1. 只改 `repeatSale`，**不动价格 / 数量 / 精度 / 月份**：执行前后核对
   `COUNT(*)`、`SUM(price)`、`SUM(CASE WHEN repeatSale=1 ...)`，任一不符 → 判定失败；
2. 预检：目标产品必须存在且 `type == '遥感数据'`（防误改普通产品）；
3. 执行前用 **SQLite 在线备份 API**（`sqlite3.Connection.backup()`）整库备份到
   `/tmp/rs-repeat-backup-<ts>.db`——服务在线运行，delete 日志模式下直接 cp 可能拿到
   半写状态文件，故不用 cp（环境无 sqlite3 CLI，只能走 Python 备份 API）；
4. 单事务 UPDATE + OpLog（`action='明细重复售卖归一'`），事务内二次复核条数，
   异常即回滚；不带 `--yes` 一律只预览、不备份、不写库。

执行方式
--------
    # 只预览（预检报告 + 分布 + 将执行的 SQL），不备份、不写库
    python3 backend/scripts/normalize_rs_repeat_sale.py --asset-id 29 --dry-run
    python3 backend/scripts/normalize_rs_repeat_sale.py --asset-id 29      # 等价（缺省不写库）

    # 真实执行：备份 → 单事务 UPDATE → OpLog → 回读校验
    python3 backend/scripts/normalize_rs_repeat_sale.py --asset-id 29 --yes

对应任务：RS-REPEAT-20261022（详见 docs/backend/changelog.md）
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

# 遥感数据类型标记（与 src/services.py 的 RS_DATA_TYPE 保持一致；脚本独立常量，
# 避免 import 业务包，服务代码变更时脚本仍可独立运行）
RS_DATA_TYPE = "遥感数据"

LOG_TARGET = "asset"
LOG_ACTION = "明细重复售卖归一"
LOG_OPERATOR = "admin"

DEFAULT_ASSET_ID = 29
DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)

# 任务验收基线（可用命令行覆盖）：#29 明细 60 条、合计 10,354,297 元
EXPECT_ITEMS = 60
EXPECT_SUM_PRICE = 10354297.0
# 预检期望「repeatSale=1」的条数（ADR-038 存量口径）；仅作报告提示，实际以库里条数为准
EXPECT_REPEAT_ON = 60

PRICE_EPS = 0.005  # 金额按分比较（price 列为 REAL，浮点求和可能有 1e-9 级误差）


class AbortPrecheck(Exception):
    """预检 / 事务内复核不通过：中止且不写库（已写则回滚）。"""


def now_str() -> str:
    """与 services.now_str() 同口径（OpLog.time 为 'YYYY-MM-DD HH:MM' 字符串）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 只读查询工具

def fetch_asset(con: sqlite3.Connection, asset_id: int) -> tuple | None:
    return con.execute(
        "SELECT id, code, name, type, quantity, unit, repeatSale, soldCount, soldAmount "
        "FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()


def fetch_rs_stats(con: sqlite3.Connection, asset_id: int) -> dict:
    row = con.execute(
        "SELECT COUNT(*), "
        "       SUM(CASE WHEN COALESCE(repeatSale, 1) = 1 THEN 1 ELSE 0 END), "
        "       COALESCE(SUM(price), 0), "
        "       MIN(saleMonth), MAX(saleMonth) "
        "FROM rs_items WHERE assetId = ?",
        (asset_id,),
    ).fetchone()
    return {
        "count": row[0] or 0,
        "repeat_on": row[1] or 0,
        "sum_price": float(row[2] or 0),
        "month_min": row[3] or "",
        "month_max": row[4] or "",
    }


def fetch_distribution(con: sqlite3.Connection, asset_id: int) -> dict:
    """分布统计：按精度 / 按月份（各含总条数与 repeatSale=1 条数）。"""
    by_res = con.execute(
        "SELECT resolution, COUNT(*), SUM(CASE WHEN COALESCE(repeatSale, 1) = 1 THEN 1 ELSE 0 END) "
        "FROM rs_items WHERE assetId = ? GROUP BY resolution ORDER BY resolution",
        (asset_id,),
    ).fetchall()
    by_month = con.execute(
        "SELECT saleMonth, COUNT(*), SUM(CASE WHEN COALESCE(repeatSale, 1) = 1 THEN 1 ELSE 0 END) "
        "FROM rs_items WHERE assetId = ? GROUP BY saleMonth ORDER BY saleMonth",
        (asset_id,),
    ).fetchall()
    return {"by_resolution": by_res, "by_month": by_month}


def fetch_occupied_count(con: sqlite3.Connection, asset_id: int) -> int:
    """被非 terminated 合同占用的明细数（ADR-038 可售口径的扣减基数，仅供报告）。"""
    return con.execute(
        "SELECT COUNT(DISTINCT r.id) FROM rs_items r "
        "JOIN project_items pi ON pi.itemId = r.id "
        "JOIN contracts c ON c.id = pi.contractId "
        "WHERE r.assetId = ? AND c.status != 'terminated'",
        (asset_id,),
    ).fetchone()[0]


# ---------------------------------------------------------------- 备份

def backup_database(db_path: str) -> tuple[str, str]:
    """用 SQLite 在线备份 API 整库备份到 /tmp，返回 (备份路径, 备份方式描述)。

    环境无 sqlite3 CLI，统一走 Python `Connection.backup()`（与服务端在线写并发安全）。
    源连接以只读 URI 打开，避免脚本误写源库。
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"/tmp/rs-repeat-backup-{ts}.db"
    if os.path.exists(backup_path):  # 同秒重复执行时不覆盖既有备份
        backup_path = f"/tmp/rs-repeat-backup-{ts}-{os.getpid()}.db"

    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    except Exception as exc:  # noqa: BLE001 - 备份失败必须硬中止
        raise RuntimeError(f"Python sqlite3 Connection.backup() 失败: {exc}") from exc

    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        raise RuntimeError(f"备份文件未生成或为空: {backup_path}")
    return backup_path, "Python sqlite3 Connection.backup()（在线备份 API，非 cp 拷贝）"


def verify_backup(backup_path: str, asset_id: int, expect_total: int,
                  expect_repeat_on: int) -> dict:
    """校验备份可用：integrity_check + 该产品明细条数与 repeatSale=1 条数与源库一致。"""
    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        stats = fetch_rs_stats(con, asset_id)
    finally:
        con.close()
    if integrity != "ok":
        raise RuntimeError(f"备份完整性校验失败: {integrity}")
    if stats["count"] != expect_total or stats["repeat_on"] != expect_repeat_on:
        raise RuntimeError(
            f"备份内容与源库不一致: 备份 count={stats['count']}/repeat_on={stats['repeat_on']}，"
            f"源库 count={expect_total}/repeat_on={expect_repeat_on}"
        )
    return {"integrity": integrity, "count": stats["count"],
            "repeat_on": stats["repeat_on"], "sum_price": stats["sum_price"]}


# ---------------------------------------------------------------- 预检

def run_precheck(db_path: str, asset_id: int) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        asset = fetch_asset(con, asset_id)
        if asset is None:
            raise AbortPrecheck(f"assets 中不存在 id={asset_id} 的产品")
        if asset[3] != RS_DATA_TYPE:
            raise AbortPrecheck(
                f"assets#{asset_id}「{asset[2]}」的 type='{asset[3]}'，"
                f"不是「{RS_DATA_TYPE}」→ 拒绝操作（防止误改普通产品）"
            )
        return {
            "asset": asset,
            "stats": fetch_rs_stats(con, asset_id),
            "dist": fetch_distribution(con, asset_id),
            "occupied": fetch_occupied_count(con, asset_id),
        }
    finally:
        con.close()


def print_precheck(report: dict, asset_id: int, db_path: str,
                   expect_items: int, expect_sum: float) -> None:
    asset, s, dist = report["asset"], report["stats"], report["dist"]
    print("=" * 78)
    print("预检报告（只读）")
    print("=" * 78)
    print(f"数据库              : {db_path}")
    print(f"目标产品            : assets#{asset[0]} {asset[1]}「{asset[2]}」type={asset[3]}")
    print(f"产品本体（不改动）  : quantity={asset[4]}, unit={asset[5]!r}, "
          f"repeatSale={bool(asset[6])}, soldCount={asset[7]}, soldAmount={asset[8]}")
    print(f"明细总数            : {s['count']} 条（预期 {expect_items}）"
          f"{'' if s['count'] == expect_items else '  ← 与验收基线不一致'}")
    print(f"  repeatSale = 1    : {s['repeat_on']} 条（预期 {EXPECT_REPEAT_ON}，需置 0 的就是这些）")
    print(f"  repeatSale = 0    : {s['count'] - s['repeat_on']} 条（已归一，无需改动）")
    print(f"  合计金额(元)      : {s['sum_price']:.2f}（预期 {expect_sum:.0f}，脚本不改价）")
    print(f"  月份跨度          : {s['month_min']} ~ {s['month_max']}")
    print(f"被占用明细（非 terminated 合同）: {report['occupied']} 条"
          f"（可售数每占用 1 条且 repeatSale=false 才扣 1）")

    print("-" * 78)
    print("分布：按精度（总条数 / repeatSale=1）")
    print("-" * 78)
    for res, total, on in dist["by_resolution"]:
        print(f"  {res:g}m{'':<6}{total:>6} 条 / 其中=1 {on:>6} 条")
    print("-" * 78)
    print("分布：按月份（总条数 / repeatSale=1）")
    print("-" * 78)
    for month, total, on in dist["by_month"]:
        print(f"  {month}   {total:>6} 条 / 其中=1 {on:>6} 条")
    print("=" * 78)


# ---------------------------------------------------------------- 执行

def execute_normalize(db_path: str, asset_id: int, expect_total: int) -> dict:
    """单事务：UPDATE rs_items SET repeatSale=0 + 写 OpLog。

    BEGIN IMMEDIATE 先取写锁并二次复核明细条数（服务在线运行，预检→写库之间存在
    并发写入窗口），条数变化即中止，避免误改范围。
    """
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            asset = fetch_asset(con, asset_id)
            if asset is None or asset[3] != RS_DATA_TYPE:
                raise AbortPrecheck("事务内复核失败：目标产品不存在或 type 已变更")

            stats = fetch_rs_stats(con, asset_id)
            if stats["count"] != expect_total:
                raise AbortPrecheck(
                    f"事务内复核失败：明细条数发生变化（预检 {expect_total} → 现在 {stats['count']}），"
                    "请重跑预检"
                )
            before_sum = stats["sum_price"]

            updated = con.execute(
                "UPDATE rs_items SET repeatSale = 0 "
                "WHERE assetId = ? AND COALESCE(repeatSale, 0) != 0",
                (asset_id,),
            ).rowcount

            after = fetch_rs_stats(con, asset_id)
            if abs(after["sum_price"] - before_sum) > PRICE_EPS:
                raise AbortPrecheck(
                    f"事务内复核失败：金额发生变化（{before_sum:.2f} → {after['sum_price']:.2f}）"
                )
            if after["count"] != expect_total:
                raise AbortPrecheck(
                    f"事务内复核失败：明细条数发生变化（{expect_total} → {after['count']}）"
                )

            detail = (
                f"{updated} 条明细 repeatSale 置为 false（ADR-038）"
                f"；明细总数 {after['count']} 条、合计金额 {after['sum_price']:.0f} 元不变"
            )
            con.execute(
                "INSERT INTO logs (target, targetName, action, detail, operator, time, "
                "assetId, changes) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (LOG_TARGET, asset[2], LOG_ACTION, detail, LOG_OPERATOR, now_str(), asset_id),
            )
            log_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            con.execute("COMMIT")
            return {
                "updated": updated,
                "detail": detail,
                "log_id": log_id,
                "asset_name": asset[2],
                "after": after,
            }
        except AbortPrecheck:
            con.execute("ROLLBACK")
            raise
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def print_readback(db_path: str, asset_id: int, before: dict, result: dict,
                   expect_total: int, expect_sum: float) -> bool:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        after = fetch_rs_stats(con, asset_id)
        asset = fetch_asset(con, asset_id)
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
        ("repeatSale = 1 条数 = 0", after["repeat_on"], 0),
        (f"明细总条数 = {expect_total}（执行前 {before['count']}）", after["count"], expect_total),
    ]
    for label, actual, expected in checks:
        flag = "OK" if actual == expected else "FAIL"
        if flag == "FAIL":
            ok = False
        print(f"  [{flag}] {label}（实际 {actual}）")

    sum_ok = abs(after["sum_price"] - expect_sum) <= PRICE_EPS
    if not sum_ok:
        ok = False
    print(f"  [{'OK' if sum_ok else 'FAIL'}] 合计金额(元) = {expect_sum:.0f}"
          f"（实际 {after['sum_price']:.2f}，执行前 {before['sum_price']:.2f}）")
    print(f"  [OK] 产品本体未改动: quantity={asset[4]}, unit={asset[5]!r}, "
          f"repeatSale={bool(asset[6])}, soldCount={asset[7]}, soldAmount={asset[8]}")

    print(f"  OpLog 回读: #{log_row[0]} target={log_row[1]} targetName={log_row[2]!r} "
          f"action={log_row[3]!r} assetId={log_row[7]} time={log_row[6]}")
    print(f"             detail={log_row[4]!r} operator={log_row[5]!r}")
    print("=" * 78)
    return ok


# ---------------------------------------------------------------- 入口

def main() -> int:
    parser = argparse.ArgumentParser(
        description="存量归一：遥感可售明细 repeatSale 置 0（ADR-038 / RS-REPEAT-20261022）"
    )
    parser.add_argument("--asset-id", type=int, default=DEFAULT_ASSET_ID,
                        help=f"目标产品 assets.id（默认 {DEFAULT_ASSET_ID}，须为 type='遥感数据'）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只输出预检报告，不备份、不写库（默认行为，与不带 --yes 等价）")
    parser.add_argument("--yes", action="store_true",
                        help="确认执行（缺省时仅预检后退出，不写库）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help=f"数据库路径（默认 {DEFAULT_DB_PATH}）")
    parser.add_argument("--expect-total", type=int, default=EXPECT_ITEMS,
                        help=f"验收基线：该产品明细总条数（默认 {EXPECT_ITEMS}）")
    parser.add_argument("--expect-sum", type=float, default=EXPECT_SUM_PRICE,
                        help=f"验收基线：该产品明细合计金额（元，默认 {EXPECT_SUM_PRICE:.0f}）")
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

    print_precheck(report, args.asset_id, db_path, args.expect_total, args.expect_sum)

    stats = report["stats"]
    if stats["count"] == 0:
        print("[跳过] 该产品没有可售明细，无需归一。")
        return 0
    if stats["repeat_on"] == 0:
        print("[跳过] 该产品明细已全部为 repeatSale=false，无需执行（幂等）。")
        return 0

    print("将执行（单事务）：")
    print(f"  UPDATE rs_items SET repeatSale = 0 "
          f"WHERE assetId = {args.asset_id} AND COALESCE(repeatSale, 0) != 0;  "
          f"→ 预计 {stats['repeat_on']} 行")
    print(f"  INSERT INTO logs (target='asset', action='{LOG_ACTION}', ...);")

    if args.dry_run or not args.yes:
        print("[未执行] dry-run / 缺少 --yes 确认：未备份、未写库。确认无误后加 --yes 执行。")
        return 0

    # 2) 备份（在线备份 API，服务运行中安全）
    print("=" * 78)
    print("执行：备份 → 单事务 UPDATE → OpLog → 回读校验")
    print("=" * 78)
    try:
        backup_path, method = backup_database(db_path)
        backup_info = verify_backup(backup_path, args.asset_id,
                                   stats["count"], stats["repeat_on"])
    except Exception as exc:  # noqa: BLE001 - 备份失败必须中止
        print(f"[中止] 备份失败，未做任何写操作：{exc}", file=sys.stderr)
        return 4
    print(f"备份路径          : {backup_path}（保留，不删除）")
    print(f"备份方式          : {method}")
    print(f"备份校验          : integrity_check={backup_info['integrity']}, "
          f"明细 {backup_info['count']} 条（其中 repeatSale=1 {backup_info['repeat_on']} 条）、"
          f"合计 {backup_info['sum_price']:.0f} 元（与源库一致）")

    # 3) 单事务执行
    try:
        result = execute_normalize(db_path, args.asset_id, expect_total=stats["count"])
    except AbortPrecheck as exc:
        print(f"[回滚] {exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"[回滚] 执行异常已回滚：{exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 6

    print(f"已更新明细        : {result['updated']} 条（assetId={args.asset_id}，repeatSale → 0）")
    print(f"已写 OpLog        : #{result['log_id']}「{result['detail']}」")
    print(f"备份路径          : {backup_path}")

    # 4) 回读校验
    ok = print_readback(db_path, args.asset_id, stats, result,
                        args.expect_total, args.expect_sum)
    print("结果: " + ("全部校验通过（价格/数量未变）" if ok
                     else "存在校验失败项，请人工复核（可从备份恢复）"))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())
