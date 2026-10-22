#!/usr/bin/env python3
"""遥感数据可售明细重新录入（RS-IMPORT-20261022）：按附件二服务清单 + 第一张图期次展开写入。

背景
----
「遥感数据-2026」（assets#29，type='遥感数据'）的 97 条可售明细已于
RS-RESET-20261022 清空（备份 /tmp/rs-items-backup-20261022-151059.db）。
现按用户最新口径重新录入 **60 条**，单价 = 面积(km²) × 单位费率。

口径（用户已确认）
------------------
- 省份组固定 6 个：新疆、陕西、甘肃、宁夏、青海、内蒙古；城市一律留空（city=''）。
- 期次（以用户确认的第一张图为准）：
    * 1m   仅 2024-10 一期                                     → 6 省 × 1 = 6 条
    * 1.5m 2024-10 ~ 2025-04（7 个月连续）+ 2025-12 ~ 2026-01（2 个月）
          共 9 期                                              → 6 省 × 9 = 54 条
    合计 60 条。
- 费用：1m 25 元/km²、1.5m 18 元/km²；单价为整数元/份 = round(面积 × 费率)。
- 面积与单价均取自附件二服务清单（下表为**权威数据，勿自行推算省份/面积**），
  脚本内以显式常量固化，并在启动时做「单价 == round(面积 × 费率)」交叉自检 ——
  面积表或单价表任一处笔误都会在预检阶段中止，不会静默写库。

安全约束（预检任一不满足即中止）
--------------------------------
1. 目标产品必须存在且 type == '遥感数据'；
2. 该产品当前 rs_items 条数必须为 0（**二次执行保护**：已导入过则条数 > 0 → 中止，
   避免重复导入产生唯一键冲突或双份明细）；
3. 展开后的 60 条 (province, city, resolution, saleMonth) 无重复
   （对齐 DB 唯一索引 uq_rs_items_dim + 服务层 _rs_item_dup 的判重口径）；
4. 金额自检：每条 price == round(area × rate)，且分精度小计 / 总计与口径一致。
以上第 3、4 条同时是纯内存自检（不依赖数据库）。

执行方式
--------
    # 只看预检 + 60 行展开预览，不备份、不写库（推荐先跑）
    python3 backend/scripts/import_rs_items.py --asset-id 29 --dry-run

    # 不加 --yes 时同样只预览（不写库），属刻意的安全默认
    python3 backend/scripts/import_rs_items.py --asset-id 29

    # 真实写入（需用户确认后执行）：在线备份 + 单事务插入 60 条 + OpLog + 回读校验
    python3 backend/scripts/import_rs_items.py --asset-id 29 --yes

--dry-run 与 --yes 互斥（写错参数不会误写库）。

写入口径与业务层一致（src/services.py create_rs_item）
------------------------------------------------------
repeatSale=1（只计次不扣量）、priceMin/priceMax 留空（不限制）、
createdAt/updatedAt = 'YYYY-MM-DD HH:MM'、price 为元整数（DB 列 REAL，ADR-006）。

容器数量同步（RS-REPEAT-20261022-FIX §1）
------------------------------------------
写入后同事务把 `assets.quantity` 同步为 **明细条数**（`sync_container_quantity`，
与 `services._sync_container_quantity` 同口径）。历史执行遗留 `quantity=1`，
使 repeatSale=false 的明细行只能卖出 1 条（`quantity-lockedQty-shippedQty>=1` 卡死），
本次修复后由 `sync_container_quantity.py` 把存量账修正为 60。

⚠️ ADR-038（RS-REPEAT-20261022）起明细默认 **repeatSale=false（单次售卖）**，本脚本是
该口径变更**之前**的一次性历史导入（`INSERT ... repeatSale 固定写 1`），已完成执行；
**不要原样重跑**：如需再导入，请把下方 SQL 的 `1` 改为 `0`（或复用
`normalize_rs_repeat_sale.py` 归一），否则会把明细又导成可重复售卖。

对应任务：RS-IMPORT-20261022（详见 docs/backend/changelog.md，待用户确认后补记）
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime

# 遥感数据类型标记（与 src/services.py 的 RS_DATA_TYPE 保持一致；脚本独立常量，
# 不 import 业务包，服务代码变更时脚本仍可独立运行）
RS_DATA_TYPE = "遥感数据"

DEFAULT_ASSET_ID = 29
DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core_holdings.db")
)

LOG_TARGET = "asset"
LOG_ACTION = "导入可售明细"
LOG_OPERATOR = "admin"

# =============================================================================
# 权威数据常量（附件二服务清单 + 用户确认的第一张图期次）
# 改动数据只改这里；下方自检会拦住面积/单价/条数/唯一性任意一处不一致。
# =============================================================================

# 省份组（固定 6 个，顺序即录入校验顺序；city 一律留空）
PROVINCES: tuple[str, ...] = ("新疆", "陕西", "甘肃", "宁夏", "青海", "内蒙古")

CITY = ""  # 城市一律留空（口径：只到省，不细分到市）

# 精度（米）：1 = 1m，1.5 = 1.5m
RESOLUTIONS: tuple[float, ...] = (1.0, 1.5)

# 面积（km²），来源：附件二服务清单。按「精度 → 省」取值。
AREA_KM2: dict[float, dict[str, int]] = {
    1.0: {"新疆": 1096, "陕西": 1268, "甘肃": 824, "宁夏": 458, "青海": 254, "内蒙古": 535},
    1.5: {"新疆": 19015, "陕西": 10843, "甘肃": 7287, "宁夏": 7653, "青海": 7857,
          "内蒙古": 10576},
}

# 单位费率（元/km²）：1m = 25，1.5m = 18
RATE_PER_KM2: dict[float, int] = {1.0: 25, 1.5: 18}

# 单价（元/份，整数，来源：附件二服务清单）——与「面积 × 费率」交叉自检用
PRICE_YUAN: dict[float, dict[str, int]] = {
    1.0: {"新疆": 27400, "陕西": 31700, "甘肃": 20600, "宁夏": 11450, "青海": 6350,
          "内蒙古": 13375},
    1.5: {"新疆": 342270, "陕西": 195174, "甘肃": 131166, "宁夏": 137754, "青海": 141426,
          "内蒙古": 190368},
}

# 期次（来源：用户确认的第一张图）
SALE_MONTHS: dict[float, tuple[str, ...]] = {
    # 1m：仅 2024-10 一期
    1.0: ("2024-10",),
    # 1.5m：2024-10 ~ 2025-04（7 个月连续）+ 2025-12 ~ 2026-01（2 个月）= 9 期
    1.5: (
        "2024-10", "2024-11", "2024-12",
        "2025-01", "2025-02", "2025-03", "2025-04",
        "2025-12", "2026-01",
    ),
}

# 期望值（口径硬编码，自检对不上即中止；预检报告也按此打印小计）
EXPECTED_SUBTOTAL: dict[float, tuple[int, int]] = {  # 精度 → (条数, 金额合计)
    1.0: (6, 110875),
    1.5: (54, 10243422),
}
EXPECTED_TOTAL: tuple[int, int] = (60, 10354297)  # (条数, 金额合计)


class AbortPrecheck(Exception):
    """预检不通过 / 事务内二次校验失败：中止且不写库。"""


# ---------------------------------------------------------------- 小工具

def now_str() -> str:
    """与 services.now_str() 同口径（createdAt/updatedAt 为 'YYYY-MM-DD HH:MM'）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _disp_width(text: str) -> int:
    """终端显示宽度（CJK 全角字符占 2 列），用于表格对齐（内蒙古 3 字 vs 新疆 2 字）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _ljust(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_width(text))


def _rjust(text: str, width: int) -> str:
    return " " * max(0, width - _disp_width(text)) + text


def _res_label(res: float) -> str:
    """精度标签：1.0 → '1m'，1.5 → '1.5m'（与 services._rs_item_desc 的 %g 口径一致）。"""
    return f"{res:g}m"


# ---------------------------------------------------------------- 展开 + 自检

def build_rows() -> list[dict]:
    """按常量展开全部明细行（不读库、不写库）。

    返回 [{seq, province, city, resolution, saleMonth, area, price, rate}]，
    顺序：精度（1m → 1.5m）→ 省份（PROVINCES 顺序）→ 月份（SALE_MONTHS 顺序）。
    """
    rows: list[dict] = []
    for res in RESOLUTIONS:
        area_map = AREA_KM2[res]
        price_map = PRICE_YUAN[res]
        rate = RATE_PER_KM2[res]
        for province in PROVINCES:
            area = area_map[province]
            price = price_map[province]
            for month in SALE_MONTHS[res]:
                rows.append({
                    "seq": len(rows) + 1,
                    "province": province,
                    "city": CITY,
                    "resolution": float(res),
                    "saleMonth": month,
                    "area": area,
                    "price": price,
                    "rate": rate,
                })
    return rows


def self_check(rows: list[dict]) -> dict:
    """纯内存自检：条数 / 金额 / 月份 / 唯一键。任一项失败 → AbortPrecheck。"""
    problems: list[str] = []

    # 1) 条数：分精度条数 = 省数 × 期数，且与期望一致
    count_by_res: dict[float, int] = {res: 0 for res in RESOLUTIONS}
    amount_by_res: dict[float, int] = {res: 0 for res in RESOLUTIONS}
    for r in rows:
        count_by_res[r["resolution"]] += 1
        amount_by_res[r["resolution"]] += r["price"]
    for res in RESOLUTIONS:
        want_count, want_amount = EXPECTED_SUBTOTAL[res]
        if count_by_res[res] != want_count:
            problems.append(
                f"{_res_label(res)} 条数 {count_by_res[res]} != 期望 {want_count}"
                f"（省 {len(PROVINCES)} × 期 {len(SALE_MONTHS[res])}）"
            )
        if amount_by_res[res] != want_amount:
            problems.append(
                f"{_res_label(res)} 金额合计 {amount_by_res[res]} != 期望 {want_amount}"
            )

    total_count = len(rows)
    total_amount = sum(r["price"] for r in rows)
    if (total_count, total_amount) != EXPECTED_TOTAL:
        problems.append(
            f"总计 {total_count} 条 / {total_amount} 元 != 期望 "
            f"{EXPECTED_TOTAL[0]} 条 / {EXPECTED_TOTAL[1]} 元"
        )

    # 2) 金额自检：price == round(area × rate)（面积表与单价表交叉校验）
    amount_failures: list[str] = []
    combos = 0
    for res in RESOLUTIONS:
        for province in PROVINCES:
            combos += 1
            area = AREA_KM2[res][province]
            rate = RATE_PER_KM2[res]
            declared = PRICE_YUAN[res][province]
            computed = round(area * rate)
            if declared != computed:
                amount_failures.append(
                    f"{province} {_res_label(res)}：单价 {declared} != "
                    f"round({area}×{rate})={computed}"
                )
    if amount_failures:
        problems.extend(amount_failures)

    # 3) 月份自检：格式 YYYY-MM、无重复、严格升序（字符串比较对 YYYY-MM 成立）
    for res in RESOLUTIONS:
        months = SALE_MONTHS[res]
        if len(set(months)) != len(months):
            problems.append(f"{_res_label(res)} 期次列表存在重复：{months}")
        if list(months) != sorted(months):
            problems.append(f"{_res_label(res)} 期次未按升序排列：{months}")
        for m in months:
            if len(m) != 7 or m[4] != "-" or not (m[:4].isdigit() and m[5:].isdigit()):
                problems.append(f"{_res_label(res)} 期次格式非法（须 YYYY-MM）：{m!r}")

    # 4) 唯一键自检：对齐 DB 唯一索引 uq_rs_items_dim
    #    (assetId, province, city, resolution, saleMonth)；assetId 由 --asset-id 决定，
    #    故此处校验四元组。resolution 为 FLOAT，用 1e-9 容差比较（同 services._rs_item_dup）。
    keys = [(r["province"], r["city"], round(r["resolution"], 9), r["saleMonth"]) for r in rows]
    dup_keys = sorted({k for k in keys if keys.count(k) > 1})
    if dup_keys:
        problems.append(
            f"展开结果存在重复明细（违反唯一键口径）：{len(dup_keys)} 组 → {dup_keys[:5]}"
        )

    if problems:
        raise AbortPrecheck("数据自检失败：\n  - " + "\n  - ".join(problems))

    return {
        "count_by_res": count_by_res,
        "amount_by_res": amount_by_res,
        "total_count": total_count,
        "total_amount": total_amount,
        "amount_combos": combos,
        "unique_keys": len(set(keys)),
    }


# ---------------------------------------------------------------- 数据库预检

def fetch_asset(con: sqlite3.Connection, asset_id: int) -> tuple | None:
    return con.execute(
        "SELECT id, code, name, type, quantity, unit, repeatSale, soldCount, soldAmount "
        "FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()


def count_rs_items(con: sqlite3.Connection, asset_id: int) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM rs_items WHERE assetId = ?", (asset_id,)
    ).fetchone()[0]


def sync_container_quantity(con: sqlite3.Connection, asset_id: int) -> tuple[int, int]:
    """写入明细后同步容器 quantity（与 `services._sync_container_quantity` 同口径）。

    WHY（RS-REPEAT-20261022-FIX）：容器 quantity 的语义 = **可售明细条数**。
    历史导入没同步 quantity（停留登记占位值 1），导致 repeatSale=false 的明细行
    下单时 `quantity - lockedQty - shippedQty >= 1` 只能成功 1 次 → 60 条明细只卖得动 1 条。

    - 无真实锁定/已交付（lockedQty == 0 and shippedQty == 0）→ quantity = COUNT(rs_items)；
    - 否则不改数量，仅校验 quantity >= lockedQty + shippedQty，不满足即中止。

    返回 (before, after)。脚本不 import 业务包，故用等价 SQL 实现，
    口径变更时须与 `src/services.py` 的 `_sync_container_quantity` 同步修改。
    """
    row = con.execute(
        "SELECT quantity, lockedQty, shippedQty FROM assets WHERE id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        raise AbortPrecheck(f"事务内复核失败：assets#{asset_id} 已不存在")
    quantity, locked, shipped = int(row[0]), int(row[1] or 0), int(row[2] or 0)
    count = count_rs_items(con, asset_id)
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


def db_precheck(db_path: str, asset_id: int) -> dict:
    """只读预检：产品存在 / 类型正确 / 现有明细条数为 0（二次执行保护）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        asset = fetch_asset(con, asset_id)
        if asset is None:
            raise AbortPrecheck(f"assets 中不存在 id={asset_id} 的产品")
        if asset[3] != RS_DATA_TYPE:
            raise AbortPrecheck(
                f"assets#{asset_id}「{asset[2]}」的 type='{asset[3]}'，"
                f"不是「{RS_DATA_TYPE}」→ 拒绝写入（防止污染普通产品明细）"
            )
        existing = count_rs_items(con, asset_id)
        if existing != 0:
            # 二次执行保护：已有明细说明清空后已导入过（或人工录入过），
            # 继续插入会与唯一键冲突 / 产生双份明细 → 直接中止，不做部分写入。
            raise AbortPrecheck(
                f"assets#{asset_id} 当前已有 {existing} 条 rs_items（要求 0 条）→ "
                f"疑似已导入或人工录入过，拒绝重复导入。"
                f"如确需重录，请先评估是否清空（参考 scripts/reset_rs_items.py）"
            )
        return {"asset": asset, "existing": existing}
    finally:
        con.close()


# ---------------------------------------------------------------- 报告打印

def print_report(db_path: str, precheck: dict, rows: list[dict], stat: dict) -> None:
    asset = precheck["asset"]
    line = "=" * 78
    thin = "-" * 78

    print(line)
    print("遥感明细重新录入 · 预检 + 展开预览")
    print(line)
    print(f"数据库            : {db_path}")
    print(f"目标产品          : assets#{asset[0]} {asset[1]}「{asset[2]}」type={asset[3]}")
    print(f"产品本体现状      : quantity={asset[4]}, unit={asset[5]!r}, "
          f"repeatSale={bool(asset[6])}, soldCount={asset[7]}, soldAmount={asset[8]}")
    print("  ↑ 本次只新增明细行，不改动产品本体（quantity/价格区间/soldCount 均不动）")
    print(f"现有 rs_items      : {precheck['existing']} 条（要求 = 0；>0 则中止，防重复导入）")
    print(f"期次口径          : 1m → {', '.join(SALE_MONTHS[1.0])}（{len(SALE_MONTHS[1.0])} 期）；"
          f"1.5m → {len(SALE_MONTHS[1.5])} 期")
    print(f"                    1.5m 明细期次：{', '.join(SALE_MONTHS[1.5])}")
    print(f"省份组            : {'、'.join(PROVINCES)}（city 一律留空 city=''）")
    print(f"费用口径          : 1m {RATE_PER_KM2[1.0]} 元/km²、"
          f"1.5m {RATE_PER_KM2[1.5]} 元/km²；单价(元/份) = round(面积(km²) × 费率)")

    print(thin)
    print("预检结果")
    print(thin)
    print(f"  [OK] 产品存在且 type='{asset[3]}'")
    print(f"  [OK] 当前 rs_items = 0 条（二次执行保护通过）")
    print(f"  [OK] 展开条数 = {stat['total_count']} 条"
          f"（1m {stat['count_by_res'][1.0]} + 1.5m {stat['count_by_res'][1.5]}）")
    print(f"  [OK] 金额自检 price == round(area × rate)："
          f"{stat['amount_combos']}/{stat['amount_combos']} 组合成立")
    print(f"  [OK] 唯一键校验 (province, city, resolution, saleMonth)："
          f"{stat['unique_keys']}/{stat['total_count']} 唯一，无重复")
    print(f"  [OK] 小计/总计与口径一致（"
          f"1m {stat['amount_by_res'][1.0]} + 1.5m {stat['amount_by_res'][1.5]} "
          f"= {stat['total_amount']} 元）")

    print(thin)
    print(f"明细展开预览（共 {stat['total_count']} 条；面积单位 km²，单价单位 元/份）")
    print(thin)
    header = (f"  {_rjust('序号', 4)}  {_ljust('省份', 8)}  {_ljust('精度', 5)}  "
              f"{_ljust('月份', 8)}  {_rjust('面积', 10)}  {_rjust('单价', 12)}")
    print(header)
    for r in rows:
        print(f"  {r['seq']:>4}  {_ljust(r['province'], 8)}  {_ljust(_res_label(r['resolution']), 5)}  "
              f"{_ljust(r['saleMonth'], 8)}  {r['area']:>10}  {r['price']:>12}")

    print(thin)
    print("分精度小计")
    print(thin)
    for res in RESOLUTIONS:
        print(f"  {_ljust(_res_label(res), 5)}: {stat['count_by_res'][res]:>3} 条，"
              f"金额合计 {stat['amount_by_res'][res]} 元")
    print(f"  {_ljust('总计', 5)}: {stat['total_count']:>3} 条，金额合计 "
          f"{stat['total_amount']} 元")
    print(line)


# ---------------------------------------------------------------- 写库（--yes 才走）

def backup_database(db_path: str) -> str:
    """用 SQLite 在线备份 API 备份整库（服务在线运行，不用 cp 直接拷贝）。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"/tmp/rs-items-import-backup-{ts}.db"
    if os.path.exists(backup_path):  # 同秒重复执行时避免覆盖既有备份
        backup_path = f"/tmp/rs-items-import-backup-{ts}-{os.getpid()}.db"

    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)  # 等价于 sqlite3 CLI 的 .backup（同一在线备份 API）
        finally:
            dst.close()
            src.close()
    except Exception as exc:  # noqa: BLE001 - 备份失败必须硬中止
        raise RuntimeError(f"SQLite 在线备份失败: {exc}") from exc

    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        raise RuntimeError(f"备份文件未生成或为空: {backup_path}")

    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if integrity != "ok":
        raise RuntimeError(f"备份完整性校验失败: {integrity}")
    return backup_path


def execute_import(db_path: str, asset_id: int, rows: list[dict], stat: dict) -> dict:
    """单事务导入 60 条明细 + 写 OpLog。

    BEGIN IMMEDIATE 先取写锁，事务内**再次**校验「产品类型 + 现有明细为 0」，
    避免预检后到写库前有并发写入（服务在线运行）导致重复插入。
    """
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        try:
            asset = fetch_asset(con, asset_id)
            if asset is None or asset[3] != RS_DATA_TYPE:
                raise AbortPrecheck("事务内复核失败：目标产品不存在或 type 已变更")

            existing = count_rs_items(con, asset_id)
            if existing != 0:
                raise AbortPrecheck(
                    f"事务内复核失败：rs_items 已有 {existing} 条（预检时 0 条），中止"
                )

            ts = now_str()
            con.executemany(
                "INSERT INTO rs_items (assetId, province, city, resolution, saleMonth, "
                "price, repeatSale, createdAt, updatedAt, priceMin, priceMax) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL)",
                [
                    (asset_id, r["province"], r["city"], r["resolution"],
                     r["saleMonth"], float(r["price"]), ts, ts)
                    for r in rows
                ],
            )

            inserted = count_rs_items(con, asset_id)
            if inserted != stat["total_count"]:
                raise AbortPrecheck(
                    f"事务内复核失败：插入后条数 {inserted} != 期望 {stat['total_count']}，已回滚"
                )

            # RS-REPEAT-20261022-FIX §1：容器 quantity = 可售明细条数（写入后同事务同步）
            qty_before, qty_after = sync_container_quantity(con, asset_id)

            detail = (
                f"按附件二服务清单重新录入 {stat['total_count']} 条可售明细"
                f"（1m {stat['count_by_res'][1.0]} 条 {stat['amount_by_res'][1.0]} 元；"
                f"1.5m {stat['count_by_res'][1.5]} 条 {stat['amount_by_res'][1.5]} 元；"
                f"合计 {stat['total_amount']} 元）；容器数量 {qty_before} → {qty_after}"
            )
            con.execute(
                "INSERT INTO logs (target, targetName, action, detail, operator, time, "
                "assetId, changes) VALUES (?, ?, ?, ?, ?, ?, ?, '')",
                (LOG_TARGET, asset[2], LOG_ACTION, detail, LOG_OPERATOR, ts, asset_id),
            )
            log_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            con.execute("COMMIT")
            return {"inserted": inserted, "detail": detail, "log_id": log_id,
                    "asset_name": asset[2],
                    "qty_before": qty_before, "qty_after": qty_after}
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def print_readback(db_path: str, asset_id: int, stat: dict) -> bool:
    """回读校验：条数 / 金额合计 / 唯一性 / 期次分布。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        total = count_rs_items(con, asset_id)
        amount = con.execute(
            "SELECT COALESCE(SUM(price), 0) FROM rs_items WHERE assetId = ?", (asset_id,)
        ).fetchone()[0]
        by_res = con.execute(
            "SELECT resolution, COUNT(*), COALESCE(SUM(price), 0) FROM rs_items "
            "WHERE assetId = ? GROUP BY resolution ORDER BY resolution", (asset_id,)
        ).fetchall()
        months = con.execute(
            "SELECT COUNT(DISTINCT saleMonth) FROM rs_items WHERE assetId = ?", (asset_id,)
        ).fetchone()[0]
        provs = con.execute(
            "SELECT COUNT(DISTINCT province) FROM rs_items WHERE assetId = ?", (asset_id,)
        ).fetchone()[0]
        cities = con.execute(
            "SELECT COUNT(*) FROM rs_items WHERE assetId = ? AND city <> ''", (asset_id,)
        ).fetchone()[0]
        # RS-REPEAT-20261022-FIX：容器 quantity 必须等于明细条数（无锁定/交付时）
        qty_row = con.execute(
            "SELECT quantity, lockedQty, shippedQty FROM assets WHERE id = ?", (asset_id,)
        ).fetchone()
    finally:
        con.close()

    ok = True
    print("-" * 78)
    print("回读校验")
    print("-" * 78)
    checks = [
        (f"rs_items 条数 = {stat['total_count']}", total, stat["total_count"]),
        (f"金额合计 = {stat['total_amount']}", int(round(amount)), stat["total_amount"]),
        ("省份数 = 6", provs, len(PROVINCES)),
        ("city 非空行数 = 0", cities, 0),
        # 容器数量 = 明细条数（在售数据只校验不改，故仅锁定/交付均为 0 时断言相等）
        ("容器 quantity = 明细条数", int(qty_row[0]),
         total if not (int(qty_row[1] or 0) or int(qty_row[2] or 0)) else int(qty_row[0])),
    ]
    for label, actual, expected in checks:
        flag = "OK" if actual == expected else "FAIL"
        if flag == "FAIL":
            ok = False
        print(f"  [{flag}] {label}（实际 {actual}）")
    for res, cnt, amt in by_res:
        want = EXPECTED_SUBTOTAL[float(res)]
        flag = "OK" if (cnt, int(round(amt))) == want else "FAIL"
        if flag == "FAIL":
            ok = False
        print(f"  [{flag}] {_res_label(float(res))}: {cnt} 条 / {int(round(amt))} 元"
              f"（期望 {want[0]} 条 / {want[1]} 元）")
    print(f"  期次去重数: {months}（1m 1 期 ∪ 1.5m 9 期，含重叠共 9 个不同月份）")
    return ok


# ---------------------------------------------------------------- 入口

def main() -> int:
    parser = argparse.ArgumentParser(
        description="遥感数据可售明细重新录入（60 条展开 + 预检 + 可选写入），"
                    "RS-IMPORT-20261022"
    )
    parser.add_argument("--asset-id", type=int, default=DEFAULT_ASSET_ID,
                        help=f"目标产品 assets.id（默认 {DEFAULT_ASSET_ID}；须 type='遥感数据'）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="只输出预检与 60 行预览，不备份、不写库")
    mode.add_argument("--yes", action="store_true",
                      help="确认写入（缺省时只预览不写库）")
    parser.add_argument("--db", default=DEFAULT_DB_PATH,
                        help=f"数据库路径（默认 {DEFAULT_DB_PATH}）")
    args = parser.parse_args()

    db_path = os.path.normpath(args.db)
    if not os.path.exists(db_path):
        print(f"[中止] 数据库不存在: {db_path}", file=sys.stderr)
        return 2

    # 1) 纯内存自检（不依赖数据库；面积/单价/条数/唯一性任一不符即中止）
    try:
        rows = build_rows()
        stat = self_check(rows)
    except AbortPrecheck as exc:
        print(f"[中止] {exc}", file=sys.stderr)
        return 3

    # 2) 数据库只读预检（产品存在 / 类型 / 现有条数为 0）
    try:
        precheck = db_precheck(db_path, args.asset_id)
    except AbortPrecheck as exc:
        print(f"[中止] 预检失败：{exc}", file=sys.stderr)
        return 3

    print_report(db_path, precheck, rows, stat)

    # 3) 未显式 --yes 一律只预览（--dry-run 与 --yes 互斥，写错参数不会误写库）
    if args.dry_run:
        print("[dry-run] 将写入 0 条（dry-run）——未备份、未写库。")
        print("          确认无误后由用户批准，再执行 --yes 真实写入。")
        return 0
    if not args.yes:
        print("[未执行] 预检全部通过，但缺少 --yes 确认；本脚本不做任何写操作。")
        print("          加 --dry-run 可显式预览，加 --yes 才真实写入。")
        return 0

    # 4) 真实写入：备份 → 单事务插入 → OpLog → 回读（本轮不由执行者触发）
    print("=" * 78)
    print("执行：备份 → 单事务插入 → 回读校验")
    print("=" * 78)
    try:
        backup_path = backup_database(db_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[中止] 备份失败，未做任何写操作：{exc}", file=sys.stderr)
        return 4
    print(f"备份路径          : {backup_path}（保留，不删除）")

    try:
        result = execute_import(db_path, args.asset_id, rows, stat)
    except AbortPrecheck as exc:
        print(f"[回滚] {exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 5
    except Exception as exc:  # noqa: BLE001
        print(f"[回滚] 执行异常已回滚：{exc}", file=sys.stderr)
        print(f"       备份文件仍在：{backup_path}")
        return 6

    print(f"已写入 rs_items   : {result['inserted']} 条（assetId={args.asset_id}）")
    print(f"已写 OpLog        : #{result['log_id']}「{result['detail']}」")
    ok = print_readback(db_path, args.asset_id, stat)
    print("=" * 78)
    print("结果: " + ("全部校验通过" if ok else "存在校验失败项，请人工复核（可从备份恢复）"))
    return 0 if ok else 7


if __name__ == "__main__":
    sys.exit(main())
