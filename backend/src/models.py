"""ORM 数据模型（SQLite 持久化）

字段名与前端 src/types.ts 完全对齐（camelCase），序列化后前端零转换直接可用。
日期类字段（inboundDate/expiryDate/updatedAt 等）统一用字符串存储（YYYY-MM-DD / YYYY-MM-DD HH:MM），
与前端类型保持一致，避免 datetime 序列化差异。
"""
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    board: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(64), default="")
    subject: Mapped[str] = mapped_column(String(128), default="")
    unit: Mapped[str] = mapped_column(String(32), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    lockedQty: Mapped[int] = mapped_column(Integer, default=0)
    shippedQty: Mapped[int] = mapped_column(Integer, default=0)
    repeatSale: Mapped[bool] = mapped_column(Boolean, default=False)
    salePrice: Mapped[float] = mapped_column(Float, default=0)
    soldAmount: Mapped[float] = mapped_column(Float, default=0)
    soldCount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="in_stock", index=True)
    inboundDate: Mapped[str] = mapped_column(String(32), default="")
    expiryDate: Mapped[str] = mapped_column(String(32), default="")
    perpetual: Mapped[bool] = mapped_column(Boolean, default=False)
    spec: Mapped[str] = mapped_column(String(255), default="")
    saleDetail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    contractFile: Mapped[str] = mapped_column(String(255), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")

    deliverables: Mapped[list["AssetDeliverable"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    customer: Mapped[str] = mapped_column(String(128), default="")
    industry: Mapped[str] = mapped_column(String(128), default="")
    rep: Mapped[str] = mapped_column(String(64), default="")
    subject: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    expectedAmount: Mapped[float] = mapped_column(Float, default=0)
    quoteAmount: Mapped[float] = mapped_column(Float, default=0)
    contractAmount: Mapped[float] = mapped_column(Float, default=0)
    paidAmount: Mapped[float] = mapped_column(Float, default=0)
    expectedSignDate: Mapped[str] = mapped_column(String(32), default="")
    lastFollowDate: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")

    items: Mapped[list["ProjectItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectItem.id"
    )


class ProjectItem(Base):
    __tablename__ = "project_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    assetId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    price: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending_asset", index=True)
    deliveryReq: Mapped[str] = mapped_column(Text, default="")
    # 下单时刻该资产是否真实加锁（= 非 repeatSale）。存量数据默认 False（未锁过，语义正确）。
    # WHY：repeatSale 资产下单只记 status='locked' 但实际不加锁，交付/终止需据此区分
    # 「真锁过要释放」与「从未锁过不可写 cancel_release 幽灵流水」。
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lockedDate: Mapped[str] = mapped_column(String(32), default="")
    confirmedDate: Mapped[str] = mapped_column(String(32), default="")
    shippedDate: Mapped[str] = mapped_column(String(32), default="")

    project: Mapped["Project"] = relationship(back_populates="items")


class Outbound(Base):
    __tablename__ = "outbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    projectId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    projectName: Mapped[str] = mapped_column(String(128), default="")
    customer: Mapped[str] = mapped_column(String(128), default="")
    assetId: Mapped[int] = mapped_column(Integer, index=True)
    assetName: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    type: Mapped[str] = mapped_column(String(32), default="physical")
    mode: Mapped[str] = mapped_column(String(16), default="new")
    date: Mapped[str] = mapped_column(String(32), default="")
    operator: Mapped[str] = mapped_column(String(64), default="admin")
    status: Mapped[str] = mapped_column(String(16), default="done")
    remark: Mapped[str] = mapped_column(Text, default="")


class AssetFlow(Base):
    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assetId: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(32))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    date: Mapped[str] = mapped_column(String(32), default="")
    ref: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")


class OpLog(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(String(32))
    targetName: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(512), default="")
    operator: Mapped[str] = mapped_column(String(64), default="admin")
    time: Mapped[str] = mapped_column(String(32), default="")
    # 关联资产 id（target='asset' 时记录，便于按资产追溯操作日志）；存量数据为 NULL
    assetId: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BaseRecord(Base):
    """供应商 / 客户 / 生态人员，通用表按 kind 区分"""

    __tablename__ = "base_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # suppliers / customers / reps
    name: Mapped[str] = mapped_column(String(128), default="")
    contact: Mapped[str] = mapped_column(String(64), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(String(255), default="")


class DeliverableTemplate(Base):
    __tablename__ = "deliverable_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32), default="install")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(255), default="")


class AssetDeliverable(Base):
    __tablename__ = "asset_deliverables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    category: Mapped[str] = mapped_column(String(32), default="install")
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(32), default="V1.0")
    meta: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")

    asset: Mapped["Asset"] = relationship(back_populates="deliverables")


class CategoryUnit(Base):
    __tablename__ = "category_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    unit: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")


class User(Base):
    """平台账号（固定三角色：admin / editor / viewer）"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # 格式：pbkdf2$<salt_hex>$<hash_hex>（PBKDF2-SHA256, 100_000 轮）
    passwordHash: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(50), default="")
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin / editor / viewer
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[str] = mapped_column(String(32), default="")


class AuditLog(Base):
    """操作审计日志（谁在什么时间做了什么）。

    与既有 OpLog（表 logs，实体级流水）分表：OpLog 行为完全不动，
    本表仅记录带操作者身份的业务写操作与认证事件。
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    userId: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(50), default="")  # 操作者快照（账号被删后仍可追溯）
    actionType: Mapped[str] = mapped_column(String(20), index=True)  # sale/outbound/asset_change/setting/user_mgmt/auth/other
    action: Mapped[str] = mapped_column(String(50), default="")  # 如「新建销售项目」
    target: Mapped[str] = mapped_column(String(50), default="")  # 如 project / asset / outbound
    targetName: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    time: Mapped[str] = mapped_column(String(32), default="")


class CartItem(Base):
    """购物车项（预留 userId 维度，为后续账号权限管控做准备；当前默认 admin）"""

    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    userId: Mapped[str] = mapped_column(String(64), default="admin", index=True)
    assetId: Mapped[int] = mapped_column(Integer, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")
