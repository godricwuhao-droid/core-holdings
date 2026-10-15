"""Core Holdings 资产管理平台 - 后端入口（FastAPI + SQLAlchemy + SQLite）

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
    # 操作日志关联资产 id（target='asset' 时记录，便于按资产追溯）；幂等补列
    log_cols = [c["name"] for c in insp.get_columns("logs")]
    if "assetId" not in log_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE logs ADD COLUMN assetId INTEGER"))
        print("[migration] logs.assetId 列已补充")
    # 项目明细「下单时刻是否真实加锁」标记（repeatSale 资产下单不加锁）；存量数据视为 False
    item_cols = [c["name"] for c in insp.get_columns("project_items")]
    if "locked" not in item_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE project_items ADD COLUMN locked BOOLEAN DEFAULT 0"))
        print("[migration] project_items.locked 列已补充")
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


_ensure_migration()

app = FastAPI(title="Core Holdings API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


def seed_if_empty() -> None:
    """首次启动写入种子数据（资产/供应商/分类单位/交付物模板）"""
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
        db.flush()  # 生成资产 id，用于关联初始流水
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for asset, raw in assets:
            db.add(AssetFlow(
                assetId=asset.id, type="purchase_in", qty=raw["quantity"],
                unit=raw["unit"], amount=0, date=raw["inboundDate"],
                ref="-", note="历史入库（初始化）",
            ))
            db.add(OpLog(
                target="asset", targetName=raw["name"], action="入库",
                detail=f"入库 {raw['quantity']}{raw['unit']}", operator="admin", time=now,
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
