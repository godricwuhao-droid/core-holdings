"""存量销售/出库数据清理脚本（ADR-007 合同层级迁移窗口专用）

⚠️ 本脚本**只由架构师审核后在停服窗口手动执行**，应用启动流程不会调用它。
严禁在 8000 端口服务运行时执行（先停服）。

用法（backend 目录下）：
    python3 cleanup_sales_data.py                 # 默认清理 ./core_holdings.db
    python3 cleanup_sales_data.py --db /path/x.db # 指定库文件
    python3 cleanup_sales_data.py --dry-run       # 只打印清理前后计数，不写库

行为（先备份 → 单事务按序清理 → 抽样输出计数）：
    0. 备份：复制库文件为 <db>.bak.cleanup-<时间戳>
    1. 删 project_items（项目明细，连带）
    2. 删 outbounds（全部出库记录）
    3. 删 flows（仅销售相关类型：project_lock / sale_out / cancel_release / manual_adjust；
       purchase_in 等入库流水**保留**）
    4. 删 cart_items（购物车全部）
    5. 删 contracts（合同全部）
    6. 删 projects（项目全部）
    7. 资产字段清零：lockedQty=0, shippedQty=0, soldCount=0, soldAmount=0
    8. 资产 status 重刷：按 (quantity - lockedQty - shippedQty) 判定
       （非 repeatSale 且可售 <=0 → all_sold，否则 in_stock；与 services.auto_status 同规则）
    9. 抽样输出清理前后各表计数

幂等保护：projects 与 contracts 均已为空时跳过并提示（不重复备份/写入）。
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

from sqlalchemy import create_engine, text

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core_holdings.db")

# 销售相关流水类型（purchase_in 等入库类保留）
SALES_FLOW_TYPES = ("project_lock", "sale_out", "cancel_release", "manual_adjust")
# 命名参数占位（:t0,:t1...）与参数字典（兼容 SQLAlchemy 2.x 的 text() 参数规则）
_FLOW_PLACEHOLDERS = ",".join(f":t{i}" for i in range(len(SALES_FLOW_TYPES)))
_FLOW_PARAMS = {f"t{i}": t for i, t in enumerate(SALES_FLOW_TYPES)}


def _counts(conn) -> dict:
    """各表计数（清理前/后抽样输出用）"""
    tables = ["projects", "contracts", "project_items", "outbounds", "flows",
              "cart_items", "assets"]
    out = {}
    for t in tables:
        out[t] = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    # 销售相关流水单独计数（保留的 purchase_in 等不在此列）
    out["flows(sales)"] = conn.execute(
        text(f"SELECT COUNT(*) FROM flows WHERE type IN ({_FLOW_PLACEHOLDERS})"),
        _FLOW_PARAMS,
    ).scalar()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="存量销售/出库数据清理（ADR-007 迁移窗口）")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite 库文件路径（默认 backend/core_holdings.db）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计数，不备份不写库")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    if not os.path.isfile(db_path):
        print(f"[error] 库文件不存在：{db_path}")
        return 1

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    with engine.begin() as conn:
        before = _counts(conn)
        print("=== 清理前计数 ===")
        for k, v in before.items():
            print(f"  {k:16s} {v}")

        # 幂等保护：projects 与 contracts 均已为空 → 无需清理
        if before["projects"] == 0 and before["contracts"] == 0:
            print("\n[skip] projects 与 contracts 均已为空，无需清理（幂等保护）。")
            return 0

    if args.dry_run:
        print("\n[dry-run] 未写库。将执行：删 project_items/outbounds/销售类 flows/cart_items/contracts/projects，"
              "资产 lockedQty/shippedQty/soldCount/soldAmount 清零并刷新 status。")
        return 0

    # 备份（先备份后写库；备份失败直接中止）
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{db_path}.bak.cleanup-{ts}"
    shutil.copy2(db_path, backup_path)
    print(f"\n[backup] 已备份 → {backup_path}")

    with engine.begin() as conn:  # 单事务：任一步失败整体回滚
        r = conn.execute(text("DELETE FROM project_items"))
        print(f"[1/8] 删 project_items：{r.rowcount} 行")
        r = conn.execute(text("DELETE FROM outbounds"))
        print(f"[2/8] 删 outbounds：{r.rowcount} 行")
        r = conn.execute(
            text(f"DELETE FROM flows WHERE type IN ({_FLOW_PLACEHOLDERS})"),
            _FLOW_PARAMS,
        )
        print(f"[3/8] 删销售类 flows（{'/'.join(SALES_FLOW_TYPES)}）：{r.rowcount} 行（purchase_in 保留）")
        r = conn.execute(text("DELETE FROM cart_items"))
        print(f"[4/8] 删 cart_items：{r.rowcount} 行")
        r = conn.execute(text("DELETE FROM contracts"))
        print(f"[5/8] 删 contracts：{r.rowcount} 行")
        r = conn.execute(text("DELETE FROM projects"))
        print(f"[6/8] 删 projects：{r.rowcount} 行")
        r = conn.execute(text(
            "UPDATE assets SET lockedQty=0, shippedQty=0, soldCount=0, soldAmount=0"
        ))
        print(f"[7/8] 资产清零 lockedQty/shippedQty/soldCount/soldAmount：{r.rowcount} 行")
        # status 重刷（与 services.auto_status 同规则：非 repeatSale 且可售<=0 → all_sold）
        r = conn.execute(text(
            "UPDATE assets SET status='all_sold' WHERE repeatSale=0 AND quantity - lockedQty - shippedQty <= 0"
        ))
        r2 = conn.execute(text(
            "UPDATE assets SET status='in_stock' WHERE repeatSale=1 OR quantity - lockedQty - shippedQty > 0"
        ))
        print(f"[8/8] 资产 status 重刷：all_sold {r.rowcount} 行 / in_stock {r2.rowcount} 行")
        after = _counts(conn)

    print("\n=== 清理后计数 ===")
    for k, v in after.items():
        print(f"  {k:16s} {v}")
    print("\n[done] 清理完成（备份保留在 " + backup_path + "）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
