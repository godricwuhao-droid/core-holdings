#!/usr/bin/env python3
"""一次性数据脚本：批量填入产品参考价区间（TASK-BE-025）。

口径（用户已拍板）：
1. 基准 = 产品当前挂牌单价 assets.salePrice；
2. 写入 priceMin = salePrice（原值不动，保持精度）；
   priceMax = salePrice × 1.02，Decimal ROUND_HALF_UP 四舍五入到整数元（先算后转 int，禁止 float）；
3. 范围仅 assets 表，rs_items 明细级区间一律不动（脚本执行前后做 diff 校验）；
4. 跳过：pricingMode='amount'（卫星 Token 派生价）、salePrice 为 NULL 或 0 的产品；
5. 覆盖：目标产品已有 priceMin/priceMax 一律覆盖为新值（不做空值判断）。

幂等：目标值与库内现值一致的产品归入"已符合目标值"，不重复写；重复执行结果一致、不报错。
审计：纯数据脚本，不写 OpLog。

用法：
    python3 fill_asset_price_range.py [db_path]
    # db_path 缺省为脚本同目录 core_holdings.db（隔离测试可传 /tmp 副本）
"""
import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

FACTOR = Decimal("1.02")


def _db_path() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "core_holdings.db")


def _target_values(sale_price_raw) -> tuple[Decimal, int]:
    """由 salePrice 计算目标 (priceMin, priceMax)。

    salePrice 落库为 REAL（float），sqlite3 返回 float；经 str() 转 Decimal
    保持与库内显示值一致的精度（与 services.py Decimal(str(x)) 边界约定一致）。
    priceMax 先算后转 int（ROUND_HALF_UP），全程 Decimal，禁止 float。
    """
    price_min = Decimal(str(sale_price_raw))
    price_max = int((price_min * FACTOR).to_integral_value(rounding=ROUND_HALF_UP))
    return price_min, price_max


def _rs_items_fingerprint(conn: sqlite3.Connection) -> tuple[int, str]:
    """rs_items 指纹：行数 + 全部 (id, priceMin, priceMax) 的 SHA256，用于前后 diff"""
    rows = conn.execute("SELECT id, priceMin, priceMax FROM rs_items ORDER BY id").fetchall()
    digest = hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
    return len(rows), digest


def main() -> None:
    db = _db_path()
    if not os.path.isfile(db):
        print(f"[ERROR] 库文件不存在：{db}")
        sys.exit(1)

    conn = sqlite3.connect(db)
    conn.isolation_level = None  # autocommit 模式，事务由下方显式 BEGIN/COMMIT 控制
    try:
        # 0. rs_items 执行前指纹
        rs_before = _rs_items_fingerprint(conn)

        # 1. 备份（仅当本次确有写入时）
        rows = conn.execute(
            "SELECT id, code, name, type, pricingMode, salePrice, priceMin, priceMax "
            "FROM assets ORDER BY id"
        ).fetchall()
        total = len(rows)

        to_write, already_ok = [], []
        skipped_amount, skipped_noprice = [], []
        for rid, code, name, atype, mode, sale_price, pmin, pmax in rows:
            if mode == "amount":
                skipped_amount.append((rid, code))
                continue
            if sale_price is None or Decimal(str(sale_price)) == 0:
                skipped_noprice.append((rid, code))
                continue
            tmin, tmax = _target_values(sale_price)
            if (pmin is not None and pmax is not None
                    and Decimal(str(pmin)) == tmin and Decimal(str(pmax)) == Decimal(tmax)):
                already_ok.append((rid, code, name, atype, pmin, pmax))
            else:
                to_write.append((rid, code, name, atype, sale_price, pmin, pmax, tmin, tmax))

        # 2. 事务内写入（幂等：已符合目标值的行不 UPDATE）
        bak = None
        if to_write:
            bak = f"{db}.bak.{date.today().strftime('%Y%m%d')}-price-range"
            if not os.path.exists(bak):
                shutil.copy2(db, bak)
                print(f"[backup] 已备份 → {bak}")
            conn.execute("BEGIN IMMEDIATE")
            for rid, code, name, atype, sale_price, pmin, pmax, tmin, tmax in to_write:
                conn.execute(
                    "UPDATE assets SET priceMin=?, priceMax=? WHERE id=?",
                    (float(tmin), float(tmax), rid),
                )
            conn.commit()
            print(f"[update] 事务已提交，共 {len(to_write)} 条 UPDATE\n")
        else:
            print("[idempotent] 全部目标产品已符合目标值，无写入\n")

        # 3. 执行报告
        print("=" * 72)
        print(f"执行报告：共扫描 {total} 个产品，写入 {len(to_write)} 个，"
              f"跳过 {len(skipped_amount) + len(skipped_noprice)} 个"
              f"（另有 {len(already_ok)} 个已符合目标值未重复写）")
        print("=" * 72)

        print(f"\n--- 写入 {len(to_write)} 个（编号/名称/类型/旧区间→新区间）---")
        for rid, code, name, atype, sale_price, pmin, pmax, tmin, tmax in to_write:
            old = f"[{pmin}, {pmax}]"
            new = f"[{tmin}, {tmax}]"
            print(f"  #{rid} {code} {name}（{atype}）: {old} → {new}  (salePrice={sale_price})")

        if already_ok:
            print(f"\n--- 已符合目标值 {len(already_ok)} 个（幂等跳过）---")
            for rid, code, name, atype, pmin, pmax in already_ok:
                print(f"  #{rid} {code} {name}（{atype}）: [{pmin}, {pmax}]")

        print(f"\n--- 跳过（amount 模式）{len(skipped_amount)} 个 ---")
        for rid, code in skipped_amount:
            print(f"  #{rid} {code}")
        print(f"\n--- 跳过（salePrice 为 NULL/0）{len(skipped_noprice)} 个 ---")
        for rid, code in skipped_noprice:
            print(f"  #{rid} {code}")

        # 4. 验收自查
        print("\n=== 验收自查 ===")
        bad = 0

        # 4.1 抽查 3 个被写产品（取写入清单前 3 个）
        print("--- 抽查被写产品（priceMin==salePrice、priceMax==int(salePrice*1.02 四舍五入)）---")
        for rid, code, name, atype, sale_price, pmin, pmax, tmin, tmax in to_write[:3]:
            cur = conn.execute(
                "SELECT salePrice, priceMin, priceMax FROM assets WHERE id=?", (rid,)
            ).fetchone()
            sp, cmin, cmax = cur
            exp_min, exp_max = _target_values(sp)
            ok = (Decimal(str(cmin)) == exp_min and Decimal(str(cmax)) == Decimal(exp_max)
                  and Decimal(str(cmin)) == Decimal(str(sp)))
            if not ok:
                bad += 1
            print(f"  #{rid} {code}: salePrice={sp} priceMin={cmin} priceMax={cmax} "
                  f"期望[{exp_min}, {exp_max}]  {'OK' if ok else 'MISMATCH!'}")

        # 4.2 抽查 1 个 amount 模式 + 1 个 salePrice=0 产品：区间未被触碰（仍为 NULL）
        print("--- 抽查跳过产品（区间应保持 NULL 未触碰）---")
        for rid, code in (skipped_amount[:1] + skipped_noprice[:1]):
            cur = conn.execute(
                "SELECT priceMin, priceMax FROM assets WHERE id=?", (rid,)
            ).fetchone()
            ok = cur == (None, None)
            if not ok:
                bad += 1
            print(f"  #{rid} {code}: priceMin={cur[0]} priceMax={cur[1]}  {'OK' if ok else 'MISMATCH!'}")

        # 4.3 rs_items 0 变化
        rs_after = _rs_items_fingerprint(conn)
        rs_ok = rs_before == rs_after
        if not rs_ok:
            bad += 1
        print(f"--- rs_items diff ---")
        print(f"  执行前: 行数={rs_before[0]} sha256={rs_before[1][:16]}…")
        print(f"  执行后: 行数={rs_after[0]} sha256={rs_after[1][:16]}…")
        print(f"  {'OK（0 变化）' if rs_ok else 'MISMATCH!'}")

        if bad:
            print(f"\n[FAIL] {bad} 项验收自查不一致，请检查！")
            sys.exit(2)
        print(f"\n[DONE] 参考价区间批量写入完成（写入 {len(to_write)} / 跳过 "
              f"{len(skipped_amount) + len(skipped_noprice)} / 已符合 {len(already_ok)}），"
              f"验收自查全部通过。{'备份：' + bak if bak else '无写入，未备份。'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
