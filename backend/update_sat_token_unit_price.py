# -*- coding: utf-8 -*-
"""TASK-BE-026 返工：卫星 Token 产品 salePrice / unit 修正（ADR-025）。

上一轮误将 salePrice 写成 33333.33（元/百万Token 口径），ADR-025 要求
salePrice 单位为 元/个（1 个 = 1 Token），必须写 0.03333333（8 位小数），
前端展示层做 ×1e6 换算显示 ¥33,333.33/百万Token。

修正内容：
1. CH-SAT-001/002/003：salePrice = 0.03333333（字符串直写，禁止 float 运算）、
   unit = 个（Token 数量）；
2. category_units 卫星Token 行残留单位文案 颗（Token 额度）→ 个（Token 数量）
   （与 seed_data.py CATEGORY_UNITS 同步，前端排查发现的后端残留）。

幂等：值已符合则 0 写入。执行前已备份 core_holdings.db.bak.20261021-token-unit-fix。
"""
import sqlite3
from decimal import Decimal
from pathlib import Path

DB = Path(__file__).parent / "core_holdings.db"
TARGETS = ["CH-SAT-001", "CH-SAT-002", "CH-SAT-003"]
NEW_PRICE_STR = "0.03333333"          # 字符串直写，全程不做 float 运算
NEW_PRICE = Decimal(NEW_PRICE_STR)    # 仅用于十进制比较
NEW_UNIT = "个（Token 数量）"
OLD_UNIT_RESIDUE = "颗（Token 额度）"


def main() -> None:
    conn = sqlite3.connect(DB)
    try:
        written = 0
        for code in TARGETS:
            row = conn.execute(
                'SELECT id, salePrice, unit FROM assets WHERE code = ?', (code,)
            ).fetchone()
            if row is None:
                raise SystemExit(f"产品 {code} 不存在，终止")
            aid, price, unit = row
            price_dec = Decimal(str(price))  # 经 str 中转，避免 float 二进制误差
            ok = price_dec == NEW_PRICE and unit == NEW_UNIT
            if ok:
                print(f"[skip] {code}: 已符合（salePrice={price_dec}, unit={unit}）")
                continue
            # 字符串参数直写：sqlite 按最近 double 落库，repr 还原为 0.03333333
            conn.execute(
                'UPDATE assets SET "salePrice" = ?, unit = ? WHERE id = ?',
                (NEW_PRICE_STR, NEW_UNIT, aid),
            )
            written += 1
            print(f"[write] {code}: salePrice {price_dec} -> {NEW_PRICE_STR}, "
                  f"unit {unit!r} -> {NEW_UNIT!r}")

        # 顺带：category_units 卫星Token 行残留单位文案
        cu = conn.execute(
            "SELECT id, unit FROM category_units "
            "WHERE board = 'satellite' AND type = '卫星Token'"
        ).fetchall()
        for cid, cu_unit in cu:
            if cu_unit == NEW_UNIT:
                print(f"[skip] category_units#{cid}: 已符合（{cu_unit}）")
                continue
            conn.execute(
                "UPDATE category_units SET unit = ? WHERE id = ?", (NEW_UNIT, cid)
            )
            written += 1
            print(f"[write] category_units#{cid}: unit {cu_unit!r} -> {NEW_UNIT!r}")

        conn.commit()
        if written == 0:
            print("已符合，无写入")
        else:
            print(f"完成：共写入 {written} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
