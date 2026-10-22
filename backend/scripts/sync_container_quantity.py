#!/usr/bin/env python3
"""遥感数据容器 `assets.quantity` 与可售明细条数同步（RS-REPEAT-20261022-FIX）。

背景 / 修的是什么缺陷
----------------------
ADR-038（RS-REPEAT-20261022）把 `rs_items.repeatSale` 默认改为 false（单次售卖）后，
明细行下单走 `apply_item_lock(db, assetId=<父容器>, qty=1)`，其原子条件更新为：

    UPDATE assets SET lockedQty = lockedQty + 1
     WHERE id = :id AND quantity - lockedQty - shippedQty >= 1

而「遥感数据-2026」（assets#29）的 `quantity` 一直是登记时的占位值 **1**（明细有 60 条）。
后果：第一条明细锁得上（locked=1），第二条起 rowcount=0 → 400「可用数量不足」；
同一单两条明细时 `_validate_item_stock(asset, 2)` 也 2 > 1 → 400；
交付侧 `shippedQty + qty > quantity` → `_invariant_violation`（500）。
即「60 条明细实际只能卖出 1 条」。

修复口径（本脚本落存量，服务层 `services._sync_container_quantity` 落增量）
--------------------------------------------------------------------------
容器的「数量」= **可售明细条数**（一期明细 = 一期可售）。同步后
`quantity - lockedQty - shippedQty` 与 `availableCount`（明细总数 − 被非 terminated
合同占用且 repeatSale=false 的明细数）天然一致。

    - 无任何真实锁定/已交付（lockedQty == 0 and shippedQty == 0）→ quantity = COUNT(rs_items)
    - 否则（在售数据）→ **不改数量**（避免冲掉进行中的锁定/交付统计），
      仅校验 quantity >= lockedQty + shippedQty，不满足 → 中止并要求人工核对。

安全约束
--------
1. 只处理 `type == '遥感数据'` 的产品（`--asset-id` 指定时校验类型，不匹配即中止）；
2. 执行前用 SQLite **在线备份 API** 备份整库到 /tmp（服务在线运行，不用 cp）；
3. 写入为单事务（BEGIN IMMEDIATE 先取写锁 + 事务内二次复核），逐产品 UPDATE + OpLog；
4. 幂等：无差异时不写库、不写 OpLog（重跑 0 变更）。

执行方式
--------
    # 只看同步计划，不备份、不写库（推荐先跑）
    python3 backend/scripts/sync_container_quantity.py --dry-run

    # 只处理某个容器
    python3 backend/scripts/sync_container_quantity.py --asset-id 29 --dry-run

    # 真实执行：必须显式 --yes（在线备份 + 单事务写入 + 回读校验）
    python3 backend/scripts/sync_container_quantity.py --asset-id 29 --yes

对应任务：RS-REPEAT-20261022-FIX（详见 docs/backend/changelog.md / database.md）
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

# 遥感数据类型标记（与 src/services.py 的 RS_DATA_TYPE 保持一致；脚本独立常量，
# 不 import 业务包，服务代码变更时脚本仍可独立运行）
RS_DATA_TYPE = "遥感数据"

LOG_TARGET = "asset"
LOG_ACTION = "同步容器数量"
LOG_OPERATOR = "admin"

DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)


class AbortPrecheck(Exception):
    """预检不通过 / 执行期二次校验失败：中止且不写库。"""


def now_str() -> str:
    """与 services.now_str() 同口径（OpLog.time 为 'YYYY-MM-DD HH:MM' 字符串）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today() -> str:
    """与 services.today() 同口径（assets.updatedAt 为 'YYYY-MM-DD'）。"""
    return datetime.now().strftime("%Y-%m-%d")


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


def container_rows(con: sqlite3.Connection, asset_id: int | None) -> list[sqlite3.Row]:
    """取出待处理的遥感容器（含明细条数），按 id 升序。"""
    sql = (
        "SELECT a.id, a.code, a.name, a.quantity, a.lockedQty, a.shippedQty, a.status, "
        "       (SELECT COUNT(*) FROM rs_items r WHERE r.assetId = a.id) AS itemCount "
        "FROM assets a WHERE a.type = ? "
    )
    params: list[object] = [RS_DATA_TYPE]
    if asset_id is not None:
        sql += "AND a.id = ? "
        params.append(asset_id)
    sql += "ORDER BY a.id"
    return con.execute(sql, params).fetchall()


def plan_row(row: sqlite3.Row) -> dict:
    """按同步口径算目标数量；在售数据（有锁定/交付）只做一致性校验，不改数量。"""
    asset_id, code, name, quantity, locked, shipped, status, items = row
    locked, shipped = int(locked or 0), int(shipped or 0)
    plan = {
        "assetId": asset_id, "code": code, "name": name,
        "quantity": int(quantity), "lockedQty": locked, "shippedQty": shipped,
        "itemCount": int(items), "status": status,
        "target": int(quantity), "change": False, "violation": "",
    }
    if locked == 0 and shipped == 0:
        plan["target"] = int(items)
        plan["change"] = int(quantity) != int(items)
    elif int(quantity) < locked + shipped:
        plan["violation"] = (
            f"quantity={quantity} < lockedQty={locked} + shippedQty={shipped}"
            f"（明细 {items} 条；在售数据不自动改数量，请人工核对）"
        )
    return plan


# ---------------------------------------------------------------- 备份

def backup_database(db_path: str) -> tuple[str, str]:
    """用 SQLite 在线备份 API 备份整库，返回 (备份路径, 使用方式描述)。

    优先调用 sqlite3 CLI 的 `.backup`；CLI 不可用时退回 Python 的
    `Connection.backup()`（两者是同一个在线备份 API，服务运行中调用安全）。
    绝不用 cp：delete 日志模式下边写边拷贝可能得到损坏/半写文件。
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = f"/tmp/container-quantity-backup-{ts}.db"
    if os.path.exists(backup_path):  # 同秒重复执行时避免覆盖既有备份
        backup_path = f"/tmp/container-quantity-backup-{ts}-{os.getpid()}.db"

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


def verify_backup(backup_path: str, expect_counts: dict[str, int]) -> dict:
    """校验备份可用：integrity_check + 关键表行数与源库一致。"""
    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        counts = table_counts(con)
    finally:
        con.close()
    if integrity != "ok":
        raise RuntimeError(f"备份完整性校验失败: {integrity}")
    for name in ("assets", "rs_items", "logs"):
        if counts.get(name) != expect_counts.get(name):
            raise RuntimeError(
                f"备份行数不符: {name} 备份={counts.get(name)}, 源库={expect_counts.get(name)}"
            )
    return {"integrity": integrity, "tables": len(counts)}


# ---------------------------------------------------------------- 预检

def run_precheck(db_path: str, asset_id: int | None) -> dict:
    """只读预检：容器清单 + 同步计划 + 全库行数快照。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if asset_id is not None:
            row = con.execute("SELECT id, name, type FROM assets WHERE id = ?",
                              (asset_id,)).fetchone()
            if row is None:
                raise AbortPrecheck(f"assets 中不存在 id={asset_id} 的产品")
            if row[2] != RS_DATA_TYPE:
                raise AbortPrecheck(
                    f"assets#{asset_id}「{row[1]}」的 type='{row[2]}'，"
                    f"不是「{RS_DATA_TYPE}」→ 拒绝操作"
                )
        rows = container_rows(con, asset_id)
        plans = [plan_row(r) for r in rows]
        violations = [p for p in plans if p["violation"]]
        if violations:
            detail = "; ".join(
                f"assets#{p['assetId']} {p['code']}：{p['violation']}" for p in violations
            )
            raise AbortPrecheck(f"存在数量不变量不满足的容器 → 中止：{detail}")
        return {"plans": plans, "counts": table_counts(con)}
    finally:
        con.close()


def print_precheck(report: dict, db_path: str) -> None:
    plans = report["plans"]
    print("=" * 88)
    print("同步计划（容器 quantity ← 可售明细条数）")
    print("=" * 88)
    print(f"数据库            : {db_path}")
    print(f"遥感容器          : {len(plans)} 个")
    print(f"  {'id':>4}  {'编号':<14}{'名称':<16}{'明细':>4}{'当前数量':>8}{'目标数量':>8}"
          f"{'锁定':>6}{'已交付':>6}  判定")
    changed = 0
    for p in plans:
        verdict = f"需同步 {p['quantity']} → {p['target']}" if p["change"] else "无需变更"
        if p["change"]:
            changed += 1
        if p["lockedQty"] or p["shippedQty"]:
            verdict += "（在售：仅校验，不改数量）"
        print(f"  {p['assetId']:>4}  {p['code']:<14}{p['name']:<16}{p['itemCount']:>4}"
              f"{p['quantity']:>8}{p['target']:>8}{p['lockedQty']:>6}{p['shippedQty']:>6}  {verdict}")
    print(f"待同步容器        : {changed} 个（其余 {len(plans) - changed} 个已一致）")
    print("=" * 88)


# ---------------------------------------------------------------- 执行

def execute_sync(db_path: str, plans: list[dict]) -> dict:
    """单事务同步：逐容器 UPDATE quantity + 更新 updatedAt + 写 OpLog。

    事务内二次复核（BEGIN IMMEDIATE 先取写锁）：数量/锁定/交付/明细条数与预检一致，
    否则中止回滚——避免预检后到写库前有并发下单（服务在线运行）被本次同步冲掉。
    """
    changed_plans = [p for p in plans if p["change"]]
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            applied: list[dict] = []
            ts, day = now_str(), today()
            for p in changed_plans:
                row = con.execute(
                    "SELECT a.quantity, a.lockedQty, a.shippedQty, a.type, a.name, "
                    "       (SELECT COUNT(*) FROM rs_items r WHERE r.assetId = a.id) "
                    "FROM assets a WHERE a.id = ?", (p["assetId"],)
                ).fetchone()
                if row is None:
                    raise AbortPrecheck(f"事务内复核失败：assets#{p['assetId']} 已不存在")
                quantity, locked, shipped, atype, name, items = row
                if atype != RS_DATA_TYPE:
                    raise AbortPrecheck(
                        f"事务内复核失败：assets#{p['assetId']} type 已变为 {atype!r}")
                if int(locked or 0) or int(shipped or 0):
                    raise AbortPrecheck(
                        f"事务内复核失败：assets#{p['assetId']} 出现锁定/交付"
                        f"（locked={locked}, shipped={shipped}），请重跑预检")
                if int(quantity) != p["quantity"] or int(items) != p["itemCount"]:
                    raise AbortPrecheck(
                        f"事务内复核失败：assets#{p['assetId']} 数量/明细条数已变化"
                        f"（quantity {p['quantity']}→{quantity}, 明细 {p['itemCount']}→{items}），"
                        f"请重跑预检")

                con.execute(
                    "UPDATE assets SET quantity = ?, updatedAt = ? WHERE id = ?",
                    (p["target"], day, p["assetId"]),
                )
                detail = (
                    f"容器数量按可售明细条数同步：{p['quantity']} → {p['target']}"
                    f"（明细 {p['itemCount']} 条）"
                )
                con.execute(
                    "INSERT INTO logs (target, targetName, action, detail, operator, time, "
                    "assetId, changes) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                    (LOG_TARGET, name, LOG_ACTION, detail, LOG_OPERATOR, ts, p["assetId"]),
                )
                applied.append({
                    "assetId": p["assetId"], "code": p["code"],
                    "old": p["quantity"], "new": p["target"], "itemCount": p["itemCount"],
                    "log_id": con.execute("SELECT last_insert_rowid()").fetchone()[0],
                })

            con.execute("COMMIT")
            return {"applied": applied}
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def print_readback(db_path: str, asset_id: int | None, before: dict[str, int],
                   applied: list[dict]) -> bool:
    """回读校验：目标容器数量 = 明细条数；全库行数只允许 logs 增加。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = container_rows(con, asset_id)
        after = table_counts(con)
    finally:
        con.close()

    ok = True
    print("-" * 88)
    print("回读校验")
    print("-" * 88)
    for r in rows:
        asset_id_, code, name, quantity, locked, shipped, _status, items = r
        if int(locked or 0) == 0 and int(shipped or 0) == 0:
            flag = "OK" if int(quantity) == int(items) else "FAIL"
            if flag == "FAIL":
                ok = False
            print(f"  [{flag}] assets#{asset_id_} {code}「{name}」quantity={quantity} "
                  f"= 明细 {items} 条")
        else:
            print(f"  [SKIP] assets#{asset_id_} {code}「{name}」在售"
                  f"（locked={locked}, shipped={shipped}）→ 未改数量，当前 quantity={quantity}")
    for a in applied:
        print(f"  OpLog #{a['log_id']}：assets#{a['assetId']} {a['code']} "
              f"{a['old']} → {a['new']}（明细 {a['itemCount']} 条）")

    print("-" * 88)
    print("全库行数对比（before → after）")
    print("-" * 88)
    print(f"  {'表名':<22}{'before':>8}{'after':>8}{'delta':>8}  备注")
    for name in sorted(before):
        b = before[name]
        a = after.get(name, -1)
        delta = a - b
        if delta == 0:
            note = ""
        elif name in ("logs",):
            note = "预期内变更（OpLog）"
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
        description="同步遥感数据容器 quantity 与可售明细条数（RS-REPEAT-20261022-FIX）"
    )
    parser.add_argument("--asset-id", type=int, default=None,
                        help="只处理指定产品 assets.id（须 type='遥感数据'）；缺省=全部遥感容器")
    # --dry-run / --yes 互斥（写错参数不会误写库，默认只预览）
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="只输出同步计划，不备份、不写库")
    mode.add_argument("--yes", action="store_true",
                      help="确认写入（缺省时同样只预览，不写库）")
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

    print_precheck(report, db_path)
    changed = [p for p in report["plans"] if p["change"]]
    if not changed:
        print("[跳过] 全部容器数量已与明细条数一致（幂等：重跑 0 变更），未写库。")
        return 0

    if args.dry_run:
        print("[dry-run] 未备份、未写库。确认无误后加 --yes 执行。")
        return 0
    if not args.yes:
        print("[未执行] 预检通过但缺少 --yes 确认；本脚本不做任何写操作。")
        return 0

    # 2) 备份（在线备份 API，服务运行中安全）
    print("=" * 88)
    print("执行：在线备份 → 单事务同步 → 回读校验")
    print("=" * 88)
    try:
        backup_path, method = backup_database(db_path)
        info = verify_backup(backup_path, report["counts"])
    except Exception as exc:  # noqa: BLE001 - 备份失败必须中止
        print(f"[中止] 备份失败，未做任何写操作：{exc}", file=sys.stderr)
        return 4
    print(f"备份路径          : {backup_path}（保留，不删除）")
    print(f"备份方式          : {method}")
    print(f"备份校验          : integrity_check={info['integrity']}, 表数={info['tables']}")

    # 3) 单事务执行
    try:
        result = execute_sync(db_path, report["plans"])
    except AbortPrecheck as exc:
        print(f"[回滚] {exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"[回滚] 执行异常已回滚：{exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 6

    for a in result["applied"]:
        print(f"已同步            : assets#{a['assetId']} {a['code']} "
              f"quantity {a['old']} → {a['new']}（明细 {a['itemCount']} 条）")
    print(f"OpLog 条数        : {len(result['applied'])}")
    print(f"备份路径          : {backup_path}")

    # 4) 回读校验
    ok = print_readback(db_path, args.asset_id, report["counts"], result["applied"])
    print("=" * 88)
    print("结果: " + ("全部校验通过" if ok else "存在校验失败项，请人工复核（可从备份恢复）"))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())
