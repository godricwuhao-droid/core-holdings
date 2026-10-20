"""Core Holdings 产品及服务平台 - 后端入口（FastAPI + SQLAlchemy + SQLite）

启动：cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src import models, security, seed_data
from src.database import Base, engine, SessionLocal
from src.models import Asset, AssetFlow, BaseRecord, CategoryUnit, DeliverableTemplate, OpLog, User
from src.routers.api import router as api_router

# 建表（models 已随 import 链全部注册到 Base.metadata）
Base.metadata.create_all(bind=engine)


def _ensure_migration() -> None:
    """轻量迁移：为存量表补充新增列（create_all 不会修改已存在的表）"""
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
    # 12) ADR-011 数据清理（幂等一次性）：删除 ADR-010 演示遥感数据产品
    #（type='遥感数据' 且带三维字段值的存量行；ADR-011 新建的父产品容器 4 列恒空，不会被误删）。
    # 删前 assert 无合同/购物车/项目明细引用（当前库应无；有引用则启动失败暴露问题，
    # 与 delete_asset 的 400 逻辑等价，迁移场景直接 assert）。
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
            conn.execute(text("DELETE FROM asset_deliverables WHERE asset_id=:aid"), {"aid": aid})
            conn.execute(text("DELETE FROM flows WHERE assetId=:aid"), {"aid": aid})
            conn.execute(text("DELETE FROM assets WHERE id=:aid"), {"aid": aid})
            print(f"[migration] ADR-011 已删除演示遥感数据产品 {aname} (id={aid})")
    # 9) ADR-008 存量回填：卫星 Token 产品 pricingMode → 'amount'（幂等，salePrice 原值保留为参考值）
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE assets SET pricingMode='amount' WHERE type='卫星Token' AND pricingMode='unit'"
        ))
        if r.rowcount:
            print(f"[migration] 卫星Token 产品 pricingMode 回填 {r.rowcount} 条 → amount")
    # 10) ADR-009 购物车按登录用户隔离：存量 userId='admin' 行回填为 admin 账号的 users.id
    #（隔离后 admin 仍可见自己的存量行；幂等——第二次启动无 userId='admin' 行，命中 0 条）
    with engine.begin() as conn:
        admin_id = conn.execute(text("SELECT id FROM users WHERE username='admin' LIMIT 1")).scalar()
        if admin_id is not None:
            r = conn.execute(
                text("UPDATE cart_items SET userId=:uid WHERE userId='admin'"),
                {"uid": str(admin_id)},
            )
            if r.rowcount:
                print(f"[migration] 购物车存量行 userId='admin' 回填 {r.rowcount} 条 → {admin_id}")
    # 销售项目状态：存量旧 8 态 → 3 态（进行中 active / 已完成 delivered / 已终止 terminated）
    with engine.begin() as conn:
        r = conn.execute(text(
            "UPDATE projects SET status='active' WHERE status IN "
            "('lead_reg','quoting','negotiating','locked','contracted','pending_info')"
        ))
        if r.rowcount:
            print(f"[migration] 销售项目状态迁移 {r.rowcount} 条 → active")
    # 存量数据自洽：按新规则回填 assets.status（幂等）。
    # WHY：新增 auto_status 规则（(qty-locked-shipped)<=0 且非 repeatSale → all_sold）后，
    # 历史行 status 可能仍是旧口径（如 id=5/25 的 in_stock）。此处**复用 services.auto_status**，
    # 避免规则二次实现产生分歧；逐条比对，仅当计算值与现值不同才 UPDATE，
    # 第二次启动命中 0 条且不产生任何写入。不得改动 lockedQty/shippedQty/quantity 等数量字段。
    # import 说明：services 仅依赖 models/schemas（不反向依赖 main），且 main 已通过
    # `from src.routers.api import router` 间接加载 services，故此处导入无循环依赖风险。
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


def _ensure_unique_indexes() -> None:
    """轻量迁移：为存量表补唯一约束（create_all 不会修改已存在的表）。

    - rs_items：(assetId, province, city, resolution, saleMonth) 维度唯一（ADR-011 判重 DB 兜底）；
    - cart_items：(userId, assetId, COALESCE(itemId, 0), customer) 判重键唯一
      （SQLite 唯一索引不认 NULL 相等，itemId 用 COALESCE 归一——0 为不可能的主键值，与 NULL 互不冲突）。
    幂等：CREATE UNIQUE INDEX IF NOT EXISTS；若存量数据已含重复行则建索引失败，
    打印告警并跳过（服务层 Python 判重仍为主防线，不阻断启动）。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    indexes = [
        ("uq_rs_items_dim",
         "CREATE UNIQUE INDEX IF NOT EXISTS uq_rs_items_dim "
         "ON rs_items (assetId, province, city, resolution, saleMonth)"),
        ("uq_cart_items_key",
         "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_items_key "
         "ON cart_items (userId, assetId, COALESCE(itemId, 0), customer)"),
    ]
    for name, ddl in indexes:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
        except IntegrityError:
            print(f"[migration] 跳过唯一索引 {name}：存量数据存在重复行（服务层判重仍生效）")


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
_backfill_file_meta()

app = FastAPI(title="Core Holdings API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


def seed_if_empty() -> None:
    """首次启动写入种子数据（产品/供应商/分类单位/交付物模板）"""
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
        for tname, items in seed_data.DELIVERABLE_TEMPLATES.items():
            for it in items:
                db.add(DeliverableTemplate(type=tname, **it))
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
