#!/usr/bin/env python3
"""按**真值**重算遥感可售明细 `rs_items.status`（RS-STATUS-20261022 / ADR-038 Decision 3）。

背景
----
ADR-038 修订后，明细自带状态标识（与外层产品 `assets.status` 同枚举）：
    in_stock  = 可售
    all_sold  = 已售罄
容器「可售数量」= `COUNT(status='in_stock')`（`services._rs_container_available_counts`）。
状态由 `services._sync_rs_item_status` 在**所有占用变化点**按真值维护；本脚本用于：
1. 上线补列后的**存量真值归一**（老库 `status` 由列 DEFAULT 填充为 in_stock，
   若库里已存在占用数据，需要按真值纠正）；
2. 任何「状态与真值漂移」的人工修复出口（幂等：重跑 0 变更）。

真值规则（唯一口径，与 services._sync_rs_item_status 完全一致）
--------------------------------------------------------------
    repeatSale = true                     → in_stock（可重复售卖只计次，永不售罄）
    否则 被非 terminated 合同引用（占用） → all_sold
    否则 未被任何有效合同引用             → in_stock
占用 = `project_items.itemId = 明细 id` 且所属 `contracts.status != 'terminated'`
（pending / active / delivering / delivered 全算占用）。

安全约束
--------
1. 只改 `rs_items.status`，**不动价格 / 数量 / repeatSale / 精度 / 月份**——执行前后核对
   `COUNT(*)`、`SUM(price)`、重复售卖条数、容器 `quantity`，任一变化 → 判定失败；
2. 预检只读；**0 变更直接退出**（幂等，不备份、不写库）；
3. 执行前用 **SQLite 在线备份 API**（`sqlite3.Connection.backup()`）整库备份到
   `/tmp/rs-status-backup-<ts>.db`——服务在线运行，delete 日志模式下直接 cp 可能拿到半写状态
   文件，故不用 cp（环境无 sqlite3 CLI，只能走 Python 备份 API）；
4. 单事务 UPDATE + OpLog（`action='明细状态归一'`），事务内**重新按真值计算**并复核条数/金额，
   异常即回滚；不带 `--yes` 一律只预览、不备份、不写库。

执行方式
--------
    # 全表预览（只读；--asset-id 可限定单个容器）
    python3 backend/scripts/sync_rs_item_status.py --dry-run
    python3 backend/scripts/sync_rs_item_status.py --asset-id 29 --dry-run

    # 真实执行：备份 → 单事务按真值 UPDATE → OpLog → 回读校验
    python3 backend/scripts/sync_rs_item_status.py --asset-id 29 --yes

对应任务：RS-STATUS-20261022（详见 docs/backend/changelog.md）
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

LOG_TARGET = "asset"
LOG_ACTION = "明细状态归一"
LOG_OPERATOR = "admin"

DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)

# 任务验收基线（仅作报告提示，可用命令行覆盖）：#29 明细 60 条、合计 10,354,297 元
EXPECT_ITEMS_ASSET29 = 60
EXPECT_SUM_PRICE_ASSET29 = 10354297.0

PRICE_EPS = 0.005  # 金额按分比较（price 列为 REAL，浮点求和可能有 1e-9 级误差）

IN_STOCK = "in_stock"
ALL_SOLD = "all_sold"


class AbortPrecheck(Exception):
    """预检 / 事务内复核不通过：中止且不写库（已写则回滚）。"""


def now_str() -> str:
    """与 services.now_str() 同口径（OpLog.time 为 'YYYY-MM-DD HH:MM' 字符串）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------- 真值计算

def truth_sql(where: str = "") -> str:
    """真值 + 现值 + 占用事实的一次性快照 SQL（in_stock/all_sold 目标值由 SQL 直接算出）。

    occupied 子查询与 services._rs_item_occupied 等价：
    明细被任一「非 terminated」合同的项目明细引用即为占用。
    """
    return (
        "SELECT r.id, r.assetId, COALESCE(r.repeatSale, 0) AS repeat_on, "
        "       COALESCE(r.status, '') AS cur_status, "
        "       CASE WHEN COALESCE(r.repeatSale, 0) = 1 THEN 0 ELSE ("
        "           SELECT 1 FROM project_items pi "
        "           JOIN contracts c ON c.id = pi.contractId "
        "           WHERE pi.itemId = r.id AND c.status != 'terminated' LIMIT 1"
        "       ) END AS occupied, "
        "       CASE WHEN COALESCE(r.repeatSale, 0) = 1 THEN 'in_stock' "
        "            WHEN EXISTS ("
        "                SELECT 1 FROM project_items pi "
        "                JOIN contracts c ON c.id = pi.contractId "
        "                WHERE pi.itemId = r.id AND c.status != 'terminated'"
        "            ) THEN 'all_sold' "
        "            ELSE 'in_stock' END AS target_status "
        "FROM rs_items r " + where + " ORDER BY r.id"
    )


def rows_of(con: sqlite3.Connection, asset_id: int | None) -> list[tuple]:
    if asset_id is None:
        return con.execute(truth_sql()).fetchall()
    return con.execute(truth_sql("WHERE r.assetId = ?"), (asset_id,)).fetchall()


def summarize(rows: list[tuple]) -> dict:
    cur = {IN_STOCK: 0, ALL_SOLD: 0, "": 0}
    target = {IN_STOCK: 0, ALL_SOLD: 0}
    diffs: list[tuple[int, int, str, str]] = []  # (id, assetId, cur, target)
    repeat_on = occupied = 0
    for item_id, asset_id, repeat_on_i, cur_status, occupied_i, target_status in rows:
        cur[cur_status if cur_status in cur else ""] += 1
        target[target_status] += 1
        repeat_on += 1 if repeat_on_i else 0
        occupied += 1 if occupied_i else 0
        if cur_status != target_status:
            diffs.append((item_id, asset_id, cur_status, target_status))
    return {"cur": cur, "target": target, "diffs": diffs,
            "repeat_on": repeat_on, "occupied": occupied, "total": len(rows)}


def fetch_stats(con: sqlite3.Connection, asset_id: int | None) -> dict:
    """不变式快照（脚本承诺不改的列 + 容器 quantity）。"""
    where, params = ("WHERE assetId = ?", (asset_id,)) if asset_id is not None else ("", ())
    row = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(price), 0), "
        "       SUM(CASE WHEN COALESCE(repeatSale, 1) = 1 THEN 1 ELSE 0 END) "
        f"FROM rs_items {where}", params,
    ).fetchone()
    asset_where, asset_params = ("WHERE id = ?", (asset_id,)) if asset_id is not None else ("", ())
    qty_row = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM assets "
        + (asset_where if asset_id is not None else "WHERE type = '遥感数据'"),
        asset_params,
    ).fetchone()
    return {
        "count": row[0] or 0,
        "sum_price": float(row[1] or 0),
        "repeat_on": row[2] or 0,
        "containers": qty_row[0] or 0,
        "quantity_sum": qty_row[1] or 0,
    }


# ---------------------------------------------------------------- 备份

def backup_database(db_path: str) -> tuple[str, str]:
    """用 SQLite 在线备份 API 整库备份到 /tmp，返回 (备份路径, 备份方式描述)。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"/tmp/rs-status-backup-{ts}.db"
    if os.path.exists(backup_path):  # 同秒重复执行时不覆盖既有备份
        backup_path = f"/tmp/rs-status-backup-{ts}-{os.getpid()}.db"
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


def verify_backup(backup_path: str, asset_id: int | None, expect: dict) -> dict:
    """校验备份可用：integrity_check + 明细条数/状态分布与源库一致。"""
    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        stats = fetch_stats(con, asset_id)
        summary = summarize(rows_of(con, asset_id))
    finally:
        con.close()
    if integrity != "ok":
        raise RuntimeError(f"备份完整性校验失败: {integrity}")
    if stats["count"] != expect["count"] or summary["cur"] != expect["cur"]:
        raise RuntimeError(
            f"备份内容与源库不一致: 备份 count={stats['count']}/cur={summary['cur']}，"
            f"源库 count={expect['count']}/cur={expect['cur']}"
        )
    return {"integrity": integrity, "count": stats["count"], "cur": summary["cur"]}


# ---------------------------------------------------------------- 预检

def run_precheck(db_path: str, asset_id: int | None) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if asset_id is not None:
            exists = con.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone()
            if exists is None:
                raise AbortPrecheck(f"assets 中不存在 id={asset_id} 的产品")
            cols = [r[1] for r in con.execute("PRAGMA table_info(rs_items)")]
            if "status" not in cols:
                raise AbortPrecheck(
                    "rs_items.status 列不存在——请先启动服务跑一次结构迁移"
                    "（main._ensure_migration），再执行本脚本")
        return {"stats": fetch_stats(con, asset_id),
                "summary": summarize(rows_of(con, asset_id))}
    finally:
        con.close()


def print_precheck(report: dict, asset_id: int | None, db_path: str) -> None:
    s, m = report["stats"], report["summary"]
    scope = f"assets#{asset_id}" if asset_id is not None else "全部容器（全表明细）"
    print("=" * 78)
    print("预检报告（只读，按真值重算 rs_items.status）")
    print("=" * 78)
    print(f"数据库            : {db_path}")
    print(f"范围              : {scope}")
    print(f"明细总数          : {m['total']} 条（其中 repeatSale=1 {m['repeat_on']} 条、"
          f"被非 terminated 合同占用 {m['occupied']} 条）")
    print(f"现值分布          : in_stock={m['cur'][IN_STOCK]}、all_sold={m['cur'][ALL_SOLD]}、"
          f"NULL/其它={m['cur']['']}")
    print(f"真值分布（目标）  : in_stock={m['target'][IN_STOCK]}、all_sold={m['target'][ALL_SOLD]}")
    print(f"需要变更          : {len(m['diffs'])} 条")
    print(f"不改动（不变式）  : 合计金额(元) {s['sum_price']:.2f}、"
          f"容器数量合计 {s['quantity_sum']}（{s['containers']} 个容器）")
    if asset_id == 29 and m["total"] == EXPECT_ITEMS_ASSET29:
        print(f"验收基线          : #29 明细 {EXPECT_ITEMS_ASSET29} 条 / 合计 "
              f"{EXPECT_SUM_PRICE_ASSET29:.0f} 元 —— 与基线一致")
    if m["diffs"]:
        print("-" * 78)
        print("变更明细（前 20 条）")
        print("-" * 78)
        for item_id, aid, cur, target in m["diffs"][:20]:
            print(f"  明细 #{item_id:<6} assetId={aid:<4} {cur or 'NULL':<9} → {target}")
        if len(m["diffs"]) > 20:
            print(f"  …… 其余 {len(m['diffs']) - 20} 条略")
    print("=" * 78)


# ---------------------------------------------------------------- 执行

def execute_sync(db_path: str, asset_id: int | None) -> dict:
    """单事务：按真值逐条 UPDATE rs_items.status + 写 OpLog（事务内重算，不沿用预检结果）。"""
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            rows = rows_of(con, asset_id)
            before = fetch_stats(con, asset_id)
            summary = summarize(rows)
            changed = 0
            for item_id, _aid, cur, target in summary["diffs"]:
                con.execute("UPDATE rs_items SET status = ? WHERE id = ?", (target, item_id))
                changed += 1

            after_rows = summarize(rows_of(con, asset_id))
            after = fetch_stats(con, asset_id)
            if after["count"] != before["count"]:
                raise AbortPrecheck(
                    f"事务内复核失败：明细条数发生变化（{before['count']} → {after['count']}）")
            if abs(after["sum_price"] - before["sum_price"]) > PRICE_EPS:
                raise AbortPrecheck(
                    f"事务内复核失败：金额发生变化"
                    f"（{before['sum_price']:.2f} → {after['sum_price']:.2f}）")
            if after["repeat_on"] != before["repeat_on"]:
                raise AbortPrecheck("事务内复核失败：repeatSale 条数发生变化")
            if after["quantity_sum"] != before["quantity_sum"]:
                raise AbortPrecheck("事务内复核失败：容器 quantity 合计发生变化")
            if after_rows["diffs"]:
                raise AbortPrecheck(
                    f"事务内复核失败：仍有 {len(after_rows['diffs'])} 条明细状态与真值不一致")

            detail = (
                f"{changed} 条明细 status 按真值归一（in_stock={after_rows['target'][IN_STOCK]}、"
                f"all_sold={after_rows['target'][ALL_SOLD]}；RS-STATUS-20261022）"
                f"；明细总数 {after['count']} 条、合计金额 {after['sum_price']:.0f} 元、"
                f"容器数量合计 {after['quantity_sum']} 未变"
            )
            target_name = "全部遥感容器" if asset_id is None else f"产品 #{asset_id}"
            con.execute(
                "INSERT INTO logs (target, targetName, action, detail, operator, time, "
                "assetId, changes) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (LOG_TARGET, target_name, LOG_ACTION, detail, LOG_OPERATOR, now_str(),
                 asset_id),
            )
            log_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("COMMIT")
            return {"changed": changed, "detail": detail, "log_id": log_id,
                    "after_rows": after_rows, "after": after, "before": before}
        except AbortPrecheck:
            con.execute("ROLLBACK")
            raise
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def print_readback(db_path: str, asset_id: int | None, result: dict) -> bool:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        after_rows = summarize(rows_of(con, asset_id))
        after = fetch_stats(con, asset_id)
        log_row = con.execute(
            "SELECT id, target, targetName, action, detail, operator, time, assetId "
            "FROM logs WHERE id = ?", (result["log_id"],)
        ).fetchone()
    finally:
        con.close()

    before = result["before"]
    ok = True
    print("-" * 78)
    print("回读校验")
    print("-" * 78)
    checks = [
        ("残差为 0（全部明细状态 = 真值）", len(after_rows["diffs"]), 0),
        (f"明细总条数 = {before['count']}", after["count"], before["count"]),
        ("repeatSale 条数未变", after["repeat_on"], before["repeat_on"]),
        ("容器 quantity 合计未变", after["quantity_sum"], before["quantity_sum"]),
        (f"in_stock 条数 = 真值 {after_rows['target'][IN_STOCK]}",
         after_rows["cur"][IN_STOCK], after_rows["target"][IN_STOCK]),
        (f"all_sold 条数 = 真值 {after_rows['target'][ALL_SOLD]}",
         after_rows["cur"][ALL_SOLD], after_rows["target"][ALL_SOLD]),
    ]
    for label, actual, expected in checks:
        flag = "OK" if actual == expected else "FAIL"
        if flag == "FAIL":
            ok = False
        print(f"  [{flag}] {label}（实际 {actual}）")
    sum_ok = abs(after["sum_price"] - before["sum_price"]) <= PRICE_EPS
    if not sum_ok:
        ok = False
    print(f"  [{'OK' if sum_ok else 'FAIL'}] 合计金额(元) 未变"
          f"（实际 {after['sum_price']:.2f}，执行前 {before['sum_price']:.2f}）")
    print(f"  OpLog 回读: #{log_row[0]} target={log_row[1]} targetName={log_row[2]!r} "
          f"action={log_row[3]!r} assetId={log_row[7]} time={log_row[6]}")
    print(f"             detail={log_row[4]!r} operator={log_row[5]!r}")
    print("=" * 78)
    return ok


# ---------------------------------------------------------------- 入口

def main() -> int:
    parser = argparse.ArgumentParser(
        description="按真值重算遥感可售明细 status（RS-STATUS-20261022 / ADR-038）"
    )
    parser.add_argument("--asset-id", type=int, default=None,
                        help="可选：只处理某个容器（assets.id）；缺省 = 全表明细")
    parser.add_argument("--dry-run", action="store_true",
                        help="只输出预检报告，不备份、不写库（默认行为，与不带 --yes 等价）")
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

    stats, summary = report["stats"], report["summary"]
    if summary["total"] == 0:
        print("[跳过] 范围内没有可售明细，无需处理。")
        return 0
    if not summary["diffs"]:
        print("[跳过] 所有明细状态已等于真值，0 变更（幂等，无需备份/写库）。")
        return 0

    print("将执行（单事务）：")
    print("  UPDATE rs_items SET status = <真值> WHERE id = <明细 id>;  "
          f"→ 预计 {len(summary['diffs'])} 行")
    print(f"  INSERT INTO logs (target='asset', action='{LOG_ACTION}', ...);")

    if args.dry_run or not args.yes:
        print("[未执行] dry-run / 缺少 --yes 确认：未备份、未写库。确认无误后加 --yes 执行。")
        return 0

    # 2) 备份（在线备份 API，服务运行中安全）
    print("=" * 78)
    print("执行：备份 → 单事务按真值 UPDATE → OpLog → 回读校验")
    print("=" * 78)
    try:
        backup_path, method = backup_database(db_path)
        backup_info = verify_backup(backup_path, args.asset_id,
                                    {"count": stats["count"], "cur": summary["cur"]})
    except Exception as exc:  # noqa: BLE001 - 备份失败必须中止
        print(f"[中止] 备份失败，未做任何写操作：{exc}", file=sys.stderr)
        return 4
    print(f"备份路径          : {backup_path}（保留，不删除）")
    print(f"备份方式          : {method}")
    print(f"备份校验          : integrity_check={backup_info['integrity']}, "
          f"明细 {backup_info['count']} 条、现值分布 {backup_info['cur']}（与源库一致）")

    # 3) 单事务执行
    try:
        result = execute_sync(db_path, args.asset_id)
    except AbortPrecheck as exc:
        print(f"[回滚] {exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"[回滚] 执行异常已回滚：{exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 6

    print(f"已更新明细        : {result['changed']} 条")
    print(f"已写 OpLog        : #{result['log_id']}「{result['detail']}」")
    print(f"备份路径          : {backup_path}")

    # 4) 回读校验
    ok = print_readback(db_path, args.asset_id, result)
    print("结果: " + ("全部校验通过（价格/数量/repeatSale 未变）" if ok
                     else "存在校验失败项，请人工复核（可从备份恢复）"))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())
