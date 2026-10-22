"""Core Holdings 产品及服务平台 - 后端入口（FastAPI + SQLAlchemy + SQLite）

启动：cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import models, security, seed_data
from src.database import Base, engine, SessionLocal
from src.models import Asset, AssetFlow, BaseRecord, CategoryUnit, OpLog, User
from src.routers.api import router as api_router

# 建表（models 已随 import 链全部注册到 Base.metadata）
# 新表（schema_migrations / idempotency）由 create_all 直接建出，无需 ALTER。
Base.metadata.create_all(bind=engine)


# ============================================================
# 迁移治理（BUG-01 / ADR-031）：schema_migrations 标记表
# - 启动期**只允许结构迁移**（CREATE TABLE/INDEX、ALTER TABLE ADD COLUMN、幂等 DROP 废弃表）；
# - 所有**数据类**一次性动作（UPDATE/DELETE 业务表）必须先查标记、执行后写标记，
#   绝不允许「靠业务表为空」当幂等条件（业务数据永远会有新行）；
# - 确需数据修复时改为 `backend/scripts/` 下的人工脚本 + changelog 记录。
# ============================================================
def _applied(name: str) -> bool:
    """该一次性动作是否已执行过（schema_migrations 命中即跳过）。"""
    from sqlalchemy import text
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :n"), {"n": name}
        ).first()
    return row is not None


def _mark_applied(name: str, note: str = "") -> None:
    """写入/更新一次性动作标记（幂等：已存在则不改）。"""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (name, appliedAt, note) "
                 "VALUES (:n, :t, :note)"),
            {"n": name, "t": datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note[:255]},
        )


def _run_once(name: str, fn, note: str = "") -> None:
    """执行一次性数据迁移（幂等）：已标记 → 跳过；否则执行 + 写标记。"""
    if _applied(name):
        return
    fn()
    _mark_applied(name, note)
    print(f"[migration] 一次性动作 {name} 已执行并登记标记")


def _ensure_migration() -> None:
    """轻量迁移：为存量表补充新增列（create_all 不会修改已存在的表）。

    结构迁移（补列/补索引）逐条幂等；数据类动作一律经 `_run_once` 标记化（ADR-031）。
    """
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("assets")]
    if "contractFile" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE assets ADD COLUMN contractFile VARCHAR(255) DEFAULT ''"))
        print("[migration] assets.contractFile 列已补充")
    # 操作日志关联产品 id（target='asset' 时记录，便于按产品追溯）；幂等补列
    log_cols = [c["name"] for c in insp.get_columns("logs")]
    if "assetId" not in log_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE logs ADD COLUMN assetId INTEGER"))
        print("[migration] logs.assetId 列已补充")
    # 产品功能清单附件（替换 saleDetail 电子表格的 UI 载体；saleDetail 列保留不删）；幂等补列
    if "featureDoc" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE assets ADD COLUMN featureDoc VARCHAR(255) DEFAULT ''"))
        print("[migration] assets.featureDoc 列已补充")
    # 项目签约主体（后端权威推导）；幂等补列（现有库已有该列时为 no-op）
    proj_cols = [c["name"] for c in insp.get_columns("projects")]
    if "subject" not in proj_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN subject VARCHAR(128) DEFAULT ''"))
        print("[migration] projects.subject 列已补充")
    # 项目商务负责人（可选，默认空，前端显示 "-"）；幂等补列
    if "businessOwner" not in proj_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN businessOwner VARCHAR(64) DEFAULT ''"))
        print("[migration] projects.businessOwner 列已补充")
    # 项目下单账号（实际登录下单的 username；存量为空）。生态人员（viewer）按
    # 「自己下单」口径过滤销售项目可见性（2026-10-16）；幂等补列 + 索引
    if "creator" not in proj_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN creator VARCHAR(64) DEFAULT ''"))
            conn.execute(text("CREATE INDEX ix_projects_creator ON projects (creator)"))
        print("[migration] projects.creator 列已补充")
    # 流水操作账号（存量流水保持空，前端显示 "-"）；幂等补列
    flow_cols = [c["name"] for c in insp.get_columns("flows")]
    if "operator" not in flow_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE flows ADD COLUMN operator VARCHAR(64) DEFAULT ''"))
        print("[migration] flows.operator 列已补充")
    # 操作日志字段级变更描述（仅 update_asset 有实际变更时写入）；幂等补列
    if "changes" not in log_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE logs ADD COLUMN changes VARCHAR(512) DEFAULT ''"))
        print("[migration] logs.changes 列已补充")
    # BUG-13 / ADR-030 §4（FIX-20261022）：logs.projectId——项目级日志的结构化归属外键。
    # viewer 日志可见性只认外键（projectId/contractId），不再用 detail 文本里的 SP- 正则。
    # 幂等补列；存量 project 日志保持 NULL（对 viewer 一律过滤，宁可保守不漏放）。
    if "projectId" not in log_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE logs ADD COLUMN projectId INTEGER"))
        print("[migration] logs.projectId 列已补充（ADR-030 日志可见性结构化判定）")
    # BUG-11 / ADR-034 §2（FIX-20261022）：users.tokenVersion——凭据版本，JWT 携带并每请求比对。
    # 改密/禁用/改角色时 +1 → 旧 token 立即失效。存量账号补列置 0
    #（旧 token 无 ver 字段按 0 处理，仍然有效直至自然过期）。
    user_cols = [c["name"] for c in insp.get_columns("users")]
    if "tokenVersion" not in user_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN tokenVersion INTEGER DEFAULT 0"))
        print("[migration] users.tokenVersion 列已补充（ADR-034 凭据吊销）")
    # 项目明细「下单时刻是否真实加锁」标记（repeatSale 产品下单不加锁）；存量数据视为 False
    item_cols = [c["name"] for c in insp.get_columns("project_items")]
    if "locked" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN locked BOOLEAN DEFAULT 0"))
        print("[migration] project_items.locked 列已补充")
    # ADR-007 合同层级（幂等补列 + 补索引）：
    # 1) project_items.contractId：明细挂合同（新数据必填；存量项为 NULL，清理脚本执行后消失）
    if "contractId" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN contractId INTEGER"))
            conn.execute(text("CREATE INDEX ix_project_items_contractId ON project_items (contractId)"))
        print("[migration] project_items.contractId 列已补充")
    # 2) outbounds.contractId：交付记录精确关联合同（projectId 保留）
    ob_cols = [c["name"] for c in insp.get_columns("outbounds")]
    if "contractId" not in ob_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE outbounds ADD COLUMN contractId INTEGER"))
            conn.execute(text("CREATE INDEX ix_outbounds_contractId ON outbounds (contractId)"))
        print("[migration] outbounds.contractId 列已补充")
    # FIX-20261020-#7：outbounds.projectItemId 交付记录精确关联项目明细（撤销交付按 id 定位，
    # 同合同同产品多明细不再 limit(1) 猜行）；手动补录/存量记录为 NULL；幂等补列 + 索引
    if "projectItemId" not in ob_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE outbounds ADD COLUMN projectItemId INTEGER"))
            conn.execute(text("CREATE INDEX ix_outbounds_projectItemId ON outbounds (projectItemId)"))
        print("[migration] outbounds.projectItemId 列已补充")
    # 3) flows.contractId：合同级交付/终止产生的流水关联合同
    if "contractId" not in flow_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE flows ADD COLUMN contractId INTEGER"))
            conn.execute(text("CREATE INDEX ix_flows_contractId ON flows (contractId)"))
        print("[migration] flows.contractId 列已补充")
    # 4) logs.contractId：合同级状态变更日志关联合同
    if "contractId" not in log_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE logs ADD COLUMN contractId INTEGER"))
        print("[migration] logs.contractId 列已补充")
    # 5) cart_items.customer：购物车行级客户（跨主体加购 + 按客户分组结算）
    cart_cols = [c["name"] for c in insp.get_columns("cart_items")]
    if "customer" not in cart_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN customer VARCHAR(128) DEFAULT ''"))
        print("[migration] cart_items.customer 列已补充")
    # 6) ADR-008 包量定价：assets.pricingMode（'unit' 默认 / 'amount' 包量金额权威）；幂等补列
    if "pricingMode" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE assets ADD COLUMN pricingMode VARCHAR(16) NOT NULL DEFAULT 'unit'"))
        print("[migration] assets.pricingMode 列已补充")
    # 7) ADR-008：cart_items.amount 包量计价合同金额（元，整数；unit 模式恒 NULL）；幂等补列
    if "amount" not in cart_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN amount FLOAT"))
        print("[migration] cart_items.amount 列已补充")
    # 8) ADR-010 遥感数据：assets 省/市/精度/影像日期 4 个可空维度列；幂等补列
    #（⚠️ ADR-011 起已废弃：列保留不删，服务层不再读写；遥感售卖粒度改由 rs_items 承载）
    if "province" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE assets ADD COLUMN province VARCHAR(64) DEFAULT ''"))
            conn.execute(text("ALTER TABLE assets ADD COLUMN city VARCHAR(64) DEFAULT ''"))
            conn.execute(text("ALTER TABLE assets ADD COLUMN resolution FLOAT"))
            conn.execute(text("ALTER TABLE assets ADD COLUMN imageDate VARCHAR(10) DEFAULT ''"))
        print("[migration] assets 遥感数据 4 列（province/city/resolution/imageDate）已补充")
    # 11) ADR-011 遥感数据两层模型：cart_items.itemId / project_items.itemId（挂 rs_items 明细）；幂等补列
    if "itemId" not in cart_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN itemId INTEGER"))
            conn.execute(text("CREATE INDEX ix_cart_items_itemId ON cart_items (itemId)"))
        print("[migration] cart_items.itemId 列已补充")
    if "itemId" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN itemId INTEGER"))
            conn.execute(text("CREATE INDEX ix_project_items_itemId ON project_items (itemId)"))
        print("[migration] project_items.itemId 列已补充")
    # 13) PRICING-20261020（ADR-018/019/020）：价格体系 + 时间节点 + 服务期限，4 表 9 列，
    # 全部可空、存量数据不迁移（旧数据 NULL 即兼容：未设区间=不限制、无原价快照、无期限/签订时间）
    if "priceMin" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE assets ADD COLUMN priceMin FLOAT"))
            conn.execute(text("ALTER TABLE assets ADD COLUMN priceMax FLOAT"))
        print("[migration] assets.priceMin/priceMax 列已补充（ADR-018 参考区间）")
    # RSITEM-RANGE-20261020（ADR-021）：遥感售卖明细参考价区间，可空、存量 96 条明细 NULL=不限制
    rs_cols = [c["name"] for c in insp.get_columns("rs_items")]
    if "priceMin" not in rs_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE rs_items ADD COLUMN priceMin FLOAT"))
            conn.execute(text("ALTER TABLE rs_items ADD COLUMN priceMax FLOAT"))
        print("[migration] rs_items.priceMin/priceMax 列已补充（ADR-021 参考区间）")
    if "serviceStart" not in cart_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN serviceStart VARCHAR(10)"))
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN serviceEnd VARCHAR(10)"))
        print("[migration] cart_items.serviceStart/serviceEnd 列已补充（ADR-020 服务期限）")
    if "origPrice" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN origPrice FLOAT"))
            conn.execute(text("ALTER TABLE project_items ADD COLUMN origAmount FLOAT"))
            conn.execute(text("ALTER TABLE project_items ADD COLUMN serviceStart VARCHAR(10)"))
            conn.execute(text("ALTER TABLE project_items ADD COLUMN serviceEnd VARCHAR(10)"))
        print("[migration] project_items.origPrice/origAmount/serviceStart/serviceEnd 列已补充（ADR-018/020）")
    contract_cols = [c["name"] for c in insp.get_columns("contracts")]
    if "signedDate" not in contract_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE contracts ADD COLUMN signedDate VARCHAR(10)"))
            conn.execute(text("ALTER TABLE contracts ADD COLUMN scheduledDeliveryDate VARCHAR(10)"))
        print("[migration] contracts.signedDate/scheduledDeliveryDate 列已补充（ADR-019 时间节点）")
    # 14) DISCOUNT-20261021（ADR-023）：折扣率——cart_items.discountRate（购物车行，选填）+
    # project_items.discountRate（下单快照，只写不改，与 origPrice 同级口径）；
    # 全部可空、存量数据不迁移（NULL=无折扣/无快照，展示端不显示）
    if "discountRate" not in cart_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE cart_items ADD COLUMN discountRate FLOAT"))
        print("[migration] cart_items.discountRate 列已补充（ADR-023 折扣率）")
    if "discountRate" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN discountRate FLOAT"))
        print("[migration] project_items.discountRate 列已补充（ADR-023 折扣率快照）")
    # 18) ADR-027 明细回填购物车幂等标记：projects.cartRefilled（BOOLEAN 默认 0）；幂等补列。
    # 一次性数据迁移（幂等）：历史**已撤销**过的终止项目置 1——判据 = 其名下任一合同 remark 含
    # 「撤销」（与 ADR-026 withdraw 写入格式「撤销：{reason}」一致）；被驳回的项目 remark 为
    # 「驳回：{reason}」，不含「撤销」故保持 0（首次点「重新提交」才回填购物车）。
    # 幂等保证：只更新 cartRefilled=0 的行，已是 1 的直接跳过（第二次启动命中 0 条）。
    if "cartRefilled" not in proj_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN cartRefilled BOOLEAN DEFAULT 0"))
        print("[migration] projects.cartRefilled 列已补充（ADR-027）")
    def _backfill_cartrefilled() -> None:
        with engine.begin() as conn:
            r = conn.execute(text(
                "UPDATE projects SET cartRefilled = 1 "
                "WHERE COALESCE(cartRefilled, 0) = 0 AND status = 'terminated' AND EXISTS ("
                "  SELECT 1 FROM contracts WHERE contracts.projectId = projects.id "
                "  AND contracts.remark LIKE '%撤销%')"
            ))
            print(f"[migration] 历史已撤销项目 cartRefilled 置 1：{r.rowcount} 条（ADR-027）")

    _run_once("ADR027_cartrefilled_backfill", _backfill_cartrefilled,
              "ADR-027 历史已撤销项目回填 cartRefilled=1（一次性数据迁移）")
    # 19) ADR-035 资产主体可维护（ENTITIES-20261022）：entities 表由 create_all 建出
    # （name UNIQUE 随约束生成）；存量回填 = 从 assets.subject 去重取非空值
    # （short 默认取 name，由管理员在设置页修正）。数据类动作，标记化只执行一次（ADR-031）。
    def _backfill_entities() -> None:
        with engine.begin() as conn:
            r = conn.execute(text(
                "INSERT OR IGNORE INTO entities (name, short, createdAt, updatedAt) "
                "SELECT DISTINCT subject, subject, :now, :now "
                "FROM assets WHERE subject <> ''"
            ), {"now": datetime.now().strftime("%Y-%m-%d %H:%M")})
            print(f"[migration] entities 存量回填 {r.rowcount} 条（ADR-035）")

    _run_once("ADR035_entities_backfill", _backfill_entities,
              "ADR-035 存量 assets.subject 去重回填 entities（一次性数据迁移）")
    # 15) ADR-024 交付物模板下线：旧库物理表幂等清理（create_all 已不再建该表，模型已删除）
    table_names = set(insp.get_table_names())
    if "deliverable_templates" in table_names:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS deliverable_templates"))
        print("[migration] deliverable_templates 表已删除（ADR-024 模板体系下线）")
    # 16) ADR-024 交付物单文件附件：asset_deliverables.file（散列名，空/NULL=无附件）；幂等补列
    deliv_cols = [c["name"] for c in insp.get_columns("asset_deliverables")]
    if "file" not in deliv_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE asset_deliverables ADD COLUMN file VARCHAR(255)"))
        print("[migration] asset_deliverables.file 列已补充（ADR-024 交付物附件）")
    # 17) ADR-024 存量交付物实例一次性清空 —— ⚠️ BUG-01 已移除「每次启动 DELETE 全表」。
    # 旧实现把「上线时一次性清空」写成了「表非空就清空」，导致每次进程重启（含 --reload）
    # 都静默删除全部手工维护的交付物（审计日志有 13 条历史交付物操作、表已 0 行，不可恢复）。
    # 现改为**只写标记**：表示「历史清理已完成/不再执行」，启动期不再触碰该业务表（ADR-031）。
    # 后续确需清理数据 → backend/scripts/ 下的人工脚本 + changelog 记录，禁止放回启动期。
    _mark_applied("ADR024_cleanup_done",
                  "ADR-024 存量交付物清理标记：历史清理已完成，启动期禁止再 DELETE 该表（BUG-01/ADR-031）")

    def _cleanup_demo_rs_assets() -> None:
        """ADR-011 一次性清理 ADR-010 演示遥感数据产品（数据类动作，标记化执行）。

        ⚠️ BUG-01/ADR-031：本函数只删除「被判定为 ADR-010 演示数据的单个产品」及其从属行，
        不触碰其他产品的交付物；且已用 `_run_once` 标记，整套动作在库上只执行一次。
        交付物从属行用 Core Delete（按 asset_id 精确限定）而非全表 DELETE。
        """
        from src import models as _models
        with engine.begin() as conn:
            demo = conn.execute(text(
                "SELECT id, name FROM assets WHERE type='遥感数据' "
                "AND (province <> '' OR city <> '' OR imageDate <> '' OR resolution IS NOT NULL)"
            )).fetchall()
            for aid, aname in demo:
                refs = conn.execute(text(
                    "SELECT COUNT(*) FROM project_items WHERE assetId=:aid OR itemId IN "
                    "(SELECT id FROM rs_items WHERE assetId=:aid)"
                ), {"aid": aid}).scalar() + conn.execute(
                    text("SELECT COUNT(*) FROM cart_items WHERE assetId=:aid"), {"aid": aid}
                ).scalar()
                assert refs == 0, f"ADR-011 迁移：演示产品 {aname}(id={aid}) 存在 {refs} 条销售/购物车引用，禁止自动删除"
                conn.execute(text("DELETE FROM rs_items WHERE assetId=:aid"), {"aid": aid})
                # 交付物从属行：Core Delete 按 asset_id 精确限定（不使用全表 DELETE 字面量）
                conn.execute(_models.AssetDeliverable.__table__.delete().where(
                    _models.AssetDeliverable.asset_id == aid))
                conn.execute(text("DELETE FROM flows WHERE assetId=:aid"), {"aid": aid})
                conn.execute(text("DELETE FROM assets WHERE id=:aid"), {"aid": aid})
                print(f"[migration] ADR-011 已删除演示遥感数据产品 {aname} (id={aid})")

    _run_once("ADR011_demo_asset_cleanup", _cleanup_demo_rs_assets,
              "ADR-011 删除 ADR-010 演示遥感数据产品（一次性数据迁移）")

    # 9) ADR-008 存量回填：卫星 Token 产品 pricingMode → 'amount'（salePrice 原值保留为参考值）
    def _backfill_pricing_mode() -> None:
        with engine.begin() as conn:
            r = conn.execute(text(
                "UPDATE assets SET pricingMode='amount' WHERE type='卫星Token' AND pricingMode='unit'"
            ))
            print(f"[migration] 卫星Token 产品 pricingMode 回填 {r.rowcount} 条 → amount")

    _run_once("ADR008_pricingmode_backfill", _backfill_pricing_mode,
              "ADR-008 卫星Token 存量回填 pricingMode=amount（一次性数据迁移）")

    # 10) ADR-009 购物车按登录用户隔离：存量 userId='admin' 行回填为 admin 账号的 users.id
    def _backfill_cart_user() -> None:
        with engine.begin() as conn:
            admin_id = conn.execute(
                text("SELECT id FROM users WHERE username='admin' LIMIT 1")).scalar()
            if admin_id is not None:
                r = conn.execute(
                    text("UPDATE cart_items SET userId=:uid WHERE userId='admin'"),
                    {"uid": str(admin_id)},
                )
                print(f"[migration] 购物车存量行 userId='admin' 回填 {r.rowcount} 条 → {admin_id}")

    _run_once("ADR009_cart_userid_backfill", _backfill_cart_user,
              "ADR-009 购物车存量 userId='admin' 回填为 users.id（一次性数据迁移）")

    # 销售项目状态：存量旧 8 态 → 3 态（进行中 active / 已完成 delivered / 已终止 terminated）
    def _migrate_project_status() -> None:
        with engine.begin() as conn:
            r = conn.execute(text(
                "UPDATE projects SET status='active' WHERE status IN "
                "('lead_reg','quoting','negotiating','locked','contracted','pending_info')"
            ))
            print(f"[migration] 销售项目状态迁移 {r.rowcount} 条 → active")

    _run_once("LEGACY_project_status_3state", _migrate_project_status,
              "旧 8 态项目状态归一为 3 态（一次性数据迁移）")

    # 存量数据自洽：按新规则回填 assets.status。
    # WHY：auto_status 规则（(qty-locked-shipped)<=0 且非 repeatSale → all_sold）上线后，
    # 历史行 status 可能仍是旧口径。此处**复用 services.auto_status**（避免规则二次实现产生分歧），
    # 逐条比对、仅当计算值与现值不同才 UPDATE；不得改动 lockedQty/shippedQty/quantity。
    # BUG-01/ADR-031：这是数据类动作，改为标记化「只跑一次」——不再每次启动扫描全表。
    def _backfill_asset_status() -> None:
        from src import services as _services
        db = SessionLocal()
        try:
            changed = 0
            for a in db.query(Asset).all():
                expected = _services.auto_status(a)
                if a.status != expected:
                    a.status = expected
                    changed += 1
            if changed:
                db.commit()
            print(f"[migration] assets.status 规则回填 {changed} 条")
        finally:
            db.close()

    _run_once("assets_status_backfill", _backfill_asset_status,
              "按 auto_status 规则一次性回填 assets.status（数据类动作，不再每次启动扫描）")


def _ensure_unique_indexes() -> None:
    """轻量迁移：为存量表补唯一约束（create_all 不会修改已存在的表）。

    - rs_items：(assetId, province, city, resolution, saleMonth) 维度唯一（ADR-011 判重 DB 兜底）；
    - cart_items：(userId, assetId, COALESCE(itemId, 0), customer) 判重键唯一
      （SQLite 唯一索引不认 NULL 相等，itemId 用 COALESCE 归一——0 为不可能的主键值，与 NULL 互不冲突）；
    - contracts：(projectId, customer) 唯一（BUG-19 / ADR-016「一资产一客户一记录」DB 兜底）；
    - project_items：(contractId, assetId, COALESCE(itemId, 0)) 唯一（BUG-19 防重复销售明细）。
    幂等 / 不阻断启动（BUG-19）：**建索引前先查重**——存在重复行则**跳过建索引并打印告警**
    （不启动失败、不删数据）；服务层 Python 判重仍为主防线。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    # (名称, 建索引 DDL, 查重 SQL, 说明)
    indexes = [
        ("uq_rs_items_dim",
         "CREATE UNIQUE INDEX IF NOT EXISTS uq_rs_items_dim "
         "ON rs_items (assetId, province, city, resolution, saleMonth)",
         None, "遥感明细维度判重"),
        ("uq_cart_items_key",
         "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_items_key "
         "ON cart_items (userId, assetId, COALESCE(itemId, 0), customer)",
         None, "购物车判重键"),
        ("uq_project_items_key",
         "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_items_key "
         "ON project_items (contractId, assetId, COALESCE(itemId, 0))",
         "SELECT contractId, assetId, COALESCE(itemId, 0) AS k, COUNT(*) AS c FROM project_items "
         "WHERE contractId IS NOT NULL AND assetId IS NOT NULL "
         "GROUP BY contractId, assetId, COALESCE(itemId, 0) HAVING COUNT(*) > 1",
         "销售明细 (合同, 产品, 明细) 唯一"),
    ]
    for name, ddl, dup_sql, label in indexes:
        if dup_sql:
            with engine.begin() as conn:
                dups = conn.execute(text(dup_sql)).fetchall()
            if dups:
                sample = "；".join(str(tuple(d)) for d in dups[:5])
                print(f"[migration] ⚠️ 跳过唯一索引 {name}（{label}）：存量数据存在 "
                      f"{len(dups)} 组重复行，需人工清理后再建。示例：{sample}")
                continue
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
            print(f"[migration] 唯一索引 {name} 就绪（{label}）")
        except IntegrityError:
            print(f"[migration] 跳过唯一索引 {name}：存量数据存在重复行（服务层判重仍生效）")

    # BUG-19：contracts 的 `UNIQUE(projectId, customer)` —— **不建**（技术冲突，见 database.md）。
    # WHY：ADR-016 起销售记录粒度 = 「一产品（×客户）一条」，同一项目同一客户**必然**有多条
    #      （多产品同客户结算，现有库 projectId=2 就有 3 条 customer='云从'）。建该唯一索引会
    #      直接阻断购物车「多产品同客户」结算（IntegrityError → 500），属不可安全实施。
    # 替代方案（已落地）：① 迁移前查重并打印告警（本函数下方）；
    #      ② 服务层禁止同项目下「客户 + 明细集合」完全重复（services._create_project_core）；
    #      ③ project_items (contractId, assetId, COALESCE(itemId,0)) 唯一索引已建立，
    #         阻断同一销售记录内重复产品/明细行。
    with engine.begin() as conn:
        dups = conn.execute(text(
            "SELECT projectId, customer, COUNT(*) AS c FROM contracts "
            "WHERE projectId IS NOT NULL GROUP BY projectId, customer HAVING COUNT(*) > 1"
        )).fetchall()
    if dups:
        sample = "；".join(str(tuple(d)) for d in dups[:5])
        print(f"[migration] ⚠️ contracts 存在 {len(dups)} 组 (projectId, customer) 重复行——"
              f"按 ADR-016 属合法多产品记录，故不建 UNIQUE(projectId, customer)；示例：{sample}")


def _backfill_file_meta() -> None:
    """存量 uploads 文件回填 file_meta（幂等：file_meta 为空才执行）。

    纯数据库操作，**不移动/重命名/删除 uploads 里任何文件**。
    对每个无 file_meta 记录的文件：散列名文件若存在内容相同的非散列文件，
    以其为原始名；否则 name=文件名本身。
    """
    import hashlib
    import os

    from sqlalchemy import text
    from src.routers.api import UPLOAD_DIR

    db = SessionLocal()
    try:
        cnt = db.execute(text("SELECT COUNT(*) FROM file_meta")).scalar()
        if cnt:
            return  # 已有记录则跳过（幂等）
        if not os.path.isdir(UPLOAD_DIR):
            return

        def _is_hashed(fn: str) -> bool:
            """散列名判定：主名（去扩展名）为纯小写十六进制（uuid4().hex 为 32 位，放宽到 ≥4 以兼容短散列）。"""
            stem = fn.rsplit(".", 1)[0]
            return len(stem) >= 4 and all(c in "0123456789abcdef" for c in stem)

        # 预扫描：文件名 → (内容 md5, 大小)
        entries = []
        for fn in sorted(os.listdir(UPLOAD_DIR)):
            fp = os.path.join(UPLOAD_DIR, fn)
            if not os.path.isfile(fp):
                continue
            with open(fp, "rb") as fh:
                digest = hashlib.md5(fh.read()).hexdigest()
            entries.append((fn, digest, os.path.getsize(fp)))

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        added = 0
        for fn, digest, size in entries:
            name = fn
            # 找内容相同的非散列（可读原始名）文件作为原始名；无则用自身名
            for other, other_digest, _ in entries:
                if other != fn and other_digest == digest and not _is_hashed(other):
                    name = other
                    break
            db.execute(
                text("INSERT OR IGNORE INTO file_meta (storedName, name, size, uploadedBy, createdAt) "
                     "VALUES (:s, :n, :sz, :u, :c)"),
                {"s": fn, "n": name, "sz": size, "u": "", "c": now},
            )
            added += 1
        db.commit()
        print(f"[migration] file_meta 存量回填 {added} 条")
    finally:
        db.close()


_ensure_migration()
_ensure_unique_indexes()
# file_meta 回填也是数据类动作（INSERT 业务表）——同样标记化，只执行一次（ADR-031）。
_run_once("file_meta_backfill_done", _backfill_file_meta,
          "存量 uploads 文件一次性回填 file_meta（数据类动作）")

app = FastAPI(title="Core Holdings API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


def seed_if_empty() -> None:
    """首次启动写入种子数据（产品/供应商/分类单位；ADR-024 起交付物模板不再种子化）"""
    db = SessionLocal()
    try:
        if db.query(Asset).count() > 0:
            return
        assets = [(Asset(**a), a) for a in seed_data.ASSETS]
        for asset, _ in assets:
            db.add(asset)
        for s in seed_data.SUPPLIERS:
            db.add(BaseRecord(kind="suppliers", **s))
        for c in seed_data.CATEGORY_UNITS:
            db.add(CategoryUnit(**c))
        db.flush()  # 生成产品 id，用于关联初始流水
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for asset, raw in assets:
            db.add(AssetFlow(
                assetId=asset.id, type="purchase_in", qty=raw["quantity"],
                unit=raw["unit"], amount=0, date=raw["inboundDate"],
                ref="-", note="历史登记（初始化）", operator="system",
            ))
            db.add(OpLog(
                target="asset", targetName=raw["name"], action="登记",
                detail=f"登记 {raw['quantity']}{raw['unit']}", operator="admin", time=now,
                assetId=asset.id,
            ))
        db.commit()
    finally:
        db.close()


seed_if_empty()


def seed_admin_user() -> None:
    """首次启动创建默认管理员（幂等：users 非空则不创建）。

    初始密码 123456 仅供本地开发；生产环境应通过环境变量 JWT_SECRET 更换密钥，
    并在登录后立即修改默认密码。
    """
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        db.add(User(
            username="admin",
            passwordHash=security.hash_password("123456"),
            name="系统管理员",
            role="admin",
            enabled=True,
            createdAt=security.now_str(),
        ))
        db.commit()
        print("[seed] 已创建默认管理员账号 admin（初始密码 123456，请尽快修改）")
    finally:
        db.close()


seed_admin_user()
