#!/usr/bin/env python3
"""存量调价：产品「销售单价」与「参考区间最低价」统一上调 1%（PRICE-UP-20261027）。

背景
----
2026-10-27 业务要求：除遥感数据销售明细（`rs_items.price`）外，其余价格的
**销售单价**（`assets.salePrice`）与**参考区间最低价**（`assets.priceMin`）上调 1%。

口径与安全约束
--------------
1. 只改 `assets.salePrice` 与 `assets.priceMin` 两列，`priceMax` **不动**（业务仅要求最低价上调）；
2. **排除** `id in (6, 7, 8)`（宏大卫星 26年10月发射 / 46号卫星 / 38号卫星 —— Token 服务，业务明确不调）；
3. **排除** `salePrice == 0 且 priceMin is None` 的产品（算力服务器 18/19/20、遥感容器 29，×1.01 仍为 0，无实际变化）；
4. **不动** `rs_items.price`（遥感明细价格）、`project_items.origPrice/origAmount`（历史订单快照）、`contracts` 成交额；
5. 精度：`round(x * 1.01, 2)`（整数仍为整数，2 位小数保留 2 位；现有产品无 amount 模式 8 位小数场景，因为 6/7/8 已排除）；
6. 购物车在途行：`cart_items` 中 `amount` 非空且所属资产在本次调整集合内的行，`amount` 同比例 ×1.01
   —— 否则该行结算时会低于新区间下限被 400 拦截；
7. 单事务 UPDATE + 每个产品一条 OpLog（`logs`，`action='调整价格'`），事务内二次复核行数，异常即回滚；
8. 备份用 **SQLite 在线备份 API**（服务在线运行，delete 日志模式下直接 cp 可能拿到半写状态文件）；
9. **不带 `--yes` 一律只预览、不备份、不写库**。

执行方式
--------
    python3 backend/scripts/adjust_price_up_1pct.py            # 只预览
    python3 backend/scripts/adjust_price_up_1pct.py --yes      # 备份 → 单事务 → OpLog → 回读校验

对应任务：PRICE-UP-20261027（详见 docs/backend/changelog.md）
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

# 业务明确排除的资产（Token 服务，不参与本次调价）
EXCLUDE_IDS = (6, 7, 8)
LOG_OPERATOR = "admin"
LOG_ACTION = "调整价格"
RATE = Decimal("1.01")

DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)


def _dec(v) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _up(v: Decimal | None) -> Decimal | None:
    if v is None:
        return None
    return (v * RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def collect(conn: sqlite3.Connection) -> list[dict]:
    """收集本次要调整的行（口径见文件头 1~3 条）。"""
    rows = conn.execute(
        "select id, name, salePrice, priceMin, priceMax from assets order by id"
    ).fetchall()
    plan: list[dict] = []
    for aid, name, sp, mn, mx in rows:
        if aid in EXCLUDE_IDS:
            continue
        sp_d, mn_d, mx_d = _dec(sp), _dec(mn), _dec(mx)
        if (sp_d is None or sp_d == 0) and mn_d is None:
            continue  # 无实际价格，跳过
        new_sp, new_mn = _up(sp_d), _up(mn_d)
        if new_mn is not None and mx_d is not None and new_mn > mx_d:
            raise SystemExit(
                f"[ABORT] 资产 #{aid}「{name}」上调后最低价 {new_mn} > 区间最高价 {mx_d}，请先人工确认区间"
            )
        plan.append(
            {"id": aid, "name": name, "old_sp": sp_d, "new_sp": new_sp,
             "old_min": mn_d, "new_min": new_mn, "max": mx_d}
        )
    return plan


def collect_cart(conn: sqlite3.Connection, asset_ids: set[int]) -> list[dict]:
    """购物车在途行：amount 非空且所属资产在调整集合内 → 同比例上调。"""
    out: list[dict] = []
    for cid, aid, amount in conn.execute(
        "select id, assetId, amount from cart_items where amount is not null order by id"
    ):
        if aid not in asset_ids:
            continue
        new = (Decimal(str(amount)) * RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out.append({"id": cid, "assetId": aid, "old": _dec(amount), "new": new})
    return out


def backup(db_path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = f"{db_path}.bak.{ts}-price-up-1pct"
    src = sqlite3.connect(db_path)
    try:
        with sqlite3.connect(dst) as out:
            src.backup(out)
    finally:
        src.close()
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="销售单价与区间最低价统一上调 1%（PRICE-UP-20261027）")
    ap.add_argument("--db", default=DEFAULT_DB_PATH, help="数据库路径")
    ap.add_argument("--yes", action="store_true", help="真实执行（备份 + 写库）；缺省仅预览")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        plan = collect(conn)
        asset_ids = {p["id"] for p in plan}
        carts = collect_cart(conn, asset_ids)

        print(f"数据库: {args.db}")
        print(f"排除资产: {EXCLUDE_IDS}（Token 服务，业务不调）")
        print(f"\n将调整 {len(plan)} 个产品（salePrice / priceMin × 1.01，priceMax 不动）：")
        print(f"{'id':>4}  {'产品':<28}{'单价':>26}{'区间最低价':>28}  区间最高价(不变)")
        for p in plan:
            sp = f"{p['old_sp']} → {p['new_sp']}" if p["old_sp"] is not None else "-"
            mn = f"{p['old_min']} → {p['new_min']}" if p["old_min"] is not None else "-（无区间）"
            print(f"{p['id']:>4}  {(p['name'] or '')[:26]:<28}{sp:>26}{mn:>28}  {p['max']}")

        print(f"\n购物车在途行同步（amount × 1.01，否则结算会低于新区间下限）：")
        if not carts:
            print("  （无）")
        for c in carts:
            print(f"  cart #{c['id']} (asset #{c['assetId']}): {c['old']} → {c['new']}")

        if not args.yes:
            print("\n[DRY-RUN] 未写库。确认无误后加 --yes 执行。")
            return 0

        dst = backup(args.db)
        print(f"\n[备份] {dst}")

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        with conn:  # 单事务：异常自动回滚
            cur = conn.executemany(
                "update assets set salePrice=?, priceMin=? where id=?",
                [(float(p["new_sp"]) if p["new_sp"] is not None else None,
                  float(p["new_min"]) if p["new_min"] is not None else None,
                  p["id"]) for p in plan],
            )
            if cur.rowcount not in (len(plan), -1):
                raise SystemExit(f"[ABORT] assets 更新行数异常：{cur.rowcount} != {len(plan)}")

            for c in carts:
                conn.execute("update cart_items set amount=? where id=?", (float(c["new"]), c["id"]))

            for p in plan:
                parts = []
                if p["old_sp"] is not None and p["new_sp"] is not None:
                    parts.append(f"销售单价 {p['old_sp']} → {p['new_sp']}")
                if p["old_min"] is not None and p["new_min"] is not None:
                    parts.append(f"区间最低价 {p['old_min']} → {p['new_min']}")
                detail = "；".join(parts) + "（统一上调 1%）"
                conn.execute(
                    "insert into logs (target, targetName, action, detail, operator, time,"
                    " assetId, changes, contractId, projectId)"
                    " values ('asset', ?, ?, ?, ?, ?, ?, ?, null, null)",
                    (p["name"], LOG_ACTION, detail, LOG_OPERATOR, now, p["id"], detail),
                )

            # 事务内二次复核：调价后每行必须与预览值一致
            bad = []
            for p in plan:
                row = conn.execute(
                    "select salePrice, priceMin from assets where id=?", (p["id"],)
                ).fetchone()
                got_sp, got_mn = _dec(row[0]), _dec(row[1])
                if got_sp != p["new_sp"] or got_mn != p["new_min"]:
                    bad.append((p["id"], got_sp, got_mn))
            if bad:
                raise SystemExit(f"[ABORT] 回读校验失败，已回滚：{bad}")

        print(f"[完成] 已更新 {len(plan)} 个产品、{len(carts)} 条购物车行，写入 {len(plan)} 条操作记录。")
        print("[校验] 事务内回读一致。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
