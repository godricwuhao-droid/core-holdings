"""ORM 数据模型（SQLite 持久化）

字段名与前端 src/types.ts 完全对齐（camelCase），序列化后前端零转换直接可用。
日期类字段（inboundDate/expiryDate/updatedAt 等）统一用字符串存储（YYYY-MM-DD / YYYY-MM-DD HH:MM），
与前端类型保持一致，避免 datetime 序列化差异。
"""
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # 金额列单位=元（ADR-006，旧单位已迁移为元）。落库仍为 SQLite REAL（float）：
    # 业务计算一律用 decimal.Decimal（见 services.py），Decimal↔float 转换收敛在
    # ORM 边界（写入前 float()、读取后按需 Decimal(str(x))），模型层保持 Float 不动。
    salePrice: Mapped[float] = mapped_column(Float, default=0)  # 元
    # 参考区间（ADR-018 §1，PRICING-20261020）：元/份，商务/管理员在产品页维护（选填）。
    # 行折扣单价（amount÷qty）须落在 [priceMin, priceMax] 内；未设置 = 不限制，
    # 只填其一 = 单边边界。存量数据 NULL（即不限制）。
    priceMin: Mapped[float | None] = mapped_column(Float, nullable=True)
    priceMax: Mapped[float | None] = mapped_column(Float, nullable=True)
    soldAmount: Mapped[float] = mapped_column(Float, default=0)  # 元
    soldCount: Mapped[int] = mapped_column(Integer, default=0)
    # 计价模式（ADR-008）：'unit'（默认，单价×数量）| 'amount'（包量金额整数元权威）。
    # 卫星 Token 类型登记时置 'amount'（salePrice 仅作参考值，不参与金额计算）。
    pricingMode: Mapped[str] = mapped_column(String(16), default="unit")
    # 遥感数据三维字段（ADR-010，⚠️ 已废弃 ADR-011）：列保留不删（技术债），
    # 服务层不再读写、schema 不再暴露；遥感数据的售卖粒度改由 rs_items 明细表承载。
    province: Mapped[str] = mapped_column(String(64), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    resolution: Mapped[float | None] = mapped_column(Float, nullable=True)  # 精度，单位米（如 1.5）
    imageDate: Mapped[str] = mapped_column(String(10), default="")  # 影像日期 YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(32), default="in_stock", index=True)
    inboundDate: Mapped[str] = mapped_column(String(32), default="")
    expiryDate: Mapped[str] = mapped_column(String(32), default="")
    perpetual: Mapped[bool] = mapped_column(Boolean, default=False)
    spec: Mapped[str] = mapped_column(String(255), default="")
    # 电子表格销售明细：UI 载体已改为 featureDoc（功能清单附件），本列与存量数据保留不动，仅不再展示
    saleDetail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 功能清单附件（/upload 返回的 filename），替换原 saleDetail 电子表格的 UI 载体
    featureDoc: Mapped[str] = mapped_column(String(255), default="")
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
    # 下单账号（实际登录下单的 username；存量项目为空）。
    # 生态人员（viewer）可见性判定用：creator == 自己 即可见；
    # creator 为空的存量项目回退 rep == 自己姓名 判定（见 services.user_sees_project）。
    creator: Mapped[str] = mapped_column(String(64), default="", index=True)
    # 商务负责人（可选，默认空；存量项目为空，前端显示 "-"）
    businessOwner: Mapped[str] = mapped_column(String(64), default="")
    # 签约主体：后端权威推导（下单路径由产品带出；手动建项目输入为空时取首条明细产品主体）。
    # 存量项目 subject 为空不做批量回填，前端展示时用产品主体兜底。
    subject: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    # 金额列单位=元（ADR-006；Decimal↔float 转换在 ORM 边界处理，见 Asset 金额列注释）
    expectedAmount: Mapped[float] = mapped_column(Float, default=0)  # 元
    quoteAmount: Mapped[float] = mapped_column(Float, default=0)  # 元
    contractAmount: Mapped[float] = mapped_column(Float, default=0)  # 元
    paidAmount: Mapped[float] = mapped_column(Float, default=0)  # 元
    expectedSignDate: Mapped[str] = mapped_column(String(32), default="")
    lastFollowDate: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")

    items: Mapped[list["ProjectItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectItem.id"
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Contract.id"
    )

    @property
    def contractCount(self) -> int:
        """合同数量（ADR-007 派生字段，供 ProjectOut 出参；非 DB 列）"""
        return len(self.contracts)


class Contract(Base):
    """合同（ADR-007）：项目下按客户拆分的合同，数量联动的最小单位。

    - 合同内强制同一产品主体（subject 建合同时从合同内产品主体推导）；
    - 合同一经生成不可增删改明细（终止再重下）；
    - 项目 status/customer/subject/expectedAmount 均由合同派生（见 services._recompute_project）。
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # HT-{4位序号}
    # 注：SQLite 默认不启用外键约束（PRAGMA foreign_keys=off），ForeignKey 仅作 ORM 关系声明，
    # 与 project_items.project_id 既有做法一致；引用完整性由服务层保证（H7 策略）
    projectId: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    customer: Mapped[str] = mapped_column(String(128), default="")
    # 签约主体：建合同时从合同内产品主体推导（合同内强制同主体）
    subject: Mapped[str] = mapped_column(String(128), default="")
    contractAmount: Mapped[float] = mapped_column(Float, default=0)  # 元（ADR-006）
    # 合同状态（ADR-019 扩展，PRICING-20261020）：
    # pending（待审核）→ active（合同签订中）→ delivering（交付中，录 signedDate 自动进入）
    # → delivered（已交付）；terminated 各阶段可达
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)  # active/delivering/delivered/terminated
    # 合同签订时间（ADR-019，PRICING-20261020）：商务填（YYYY-MM-DD），录入即 active→delivering；
    # 录后可改、不可清空；存量 active 合同为 NULL（上线后由商务补录）
    signedDate: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 预计交付时间（ADR-019，PRICING-20261020）：仅 admin 填（YYYY-MM-DD），仅 delivering 可录/改/清空
    scheduledDeliveryDate: Mapped[str | None] = mapped_column(String(10), nullable=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")

    project: Mapped["Project"] = relationship(back_populates="contracts")
    items: Mapped[list["ProjectItem"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ProjectItem.id"
    )


class ProjectItem(Base):
    __tablename__ = "project_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    # 所属合同（ADR-007）：新数据必填；存量项为 NULL（清理脚本执行后消失）
    # SQLite 默认不启用外键约束，ForeignKey 仅作 ORM 关系声明（同 project_id 做法）
    contractId: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"), nullable=True, index=True)
    assetId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    price: Mapped[float] = mapped_column(Float, default=0)  # 元（ADR-006）；语义=最终价（折扣/终审后，ADR-018）
    amount: Mapped[float] = mapped_column(Float, default=0)  # 元（= price × qty，Decimal 重算）；语义=最终行金额
    # 原价快照（ADR-018 §2，PRICING-20261020）：下单时快照写入、**永不覆盖**——
    # unit/amount 行 = asset.salePrice / salePrice×qty；遥感行 = rs_items.price / 同值。
    # 存量订单为 NULL（展示端按 price/amount 兜底显示）。
    origPrice: Mapped[float | None] = mapped_column(Float, nullable=True)  # 元
    origAmount: Mapped[float | None] = mapped_column(Float, nullable=True)  # 元
    status: Mapped[str] = mapped_column(String(32), default="pending_asset", index=True)
    deliveryReq: Mapped[str] = mapped_column(Text, default="")
    # 下单时刻该产品是否真实加锁（= 非 repeatSale）。存量数据默认 False（未锁过，语义正确）。
    # WHY：repeatSale 产品下单只记 status='locked' 但实际不加锁，交付/终止需据此区分
    # 「真锁过要释放」与「从未锁过不可写 cancel_release 幽灵流水」。
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    lockedDate: Mapped[str] = mapped_column(String(32), default="")
    confirmedDate: Mapped[str] = mapped_column(String(32), default="")
    shippedDate: Mapped[str] = mapped_column(String(32), default="")
    # 遥感数据明细（ADR-011）：非空时本行售卖的是 rs_items 明细（qty 恒 1，金额=明细 price 权威）；
    # 存量/非遥感行恒 NULL
    itemId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，下单人填、商务审核可改；
    # 遥感行按期数 saleMonth 售卖不填期限；存量行 NULL
    serviceStart: Mapped[str | None] = mapped_column(String(10), nullable=True)
    serviceEnd: Mapped[str | None] = mapped_column(String(10), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="items")
    contract: Mapped["Contract | None"] = relationship(back_populates="items")


class Outbound(Base):
    __tablename__ = "outbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    projectId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 所属合同（ADR-007）：合同交付自动交付时精确关联；projectId 保留（项目级手动交付为 NULL）
    contractId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 所属项目明细（FIX-20261020-#7）：合同交付自动交付时指向 ProjectItem.id，
    # 撤销交付按此精确定位明细（同合同同产品多明细不再 limit(1) 猜行）；
    # 手动补录/存量记录为 NULL（撤销时回退 contractId+assetId limit(1) 兼容逻辑）
    projectItemId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    projectName: Mapped[str] = mapped_column(String(128), default="")
    customer: Mapped[str] = mapped_column(String(128), default="")
    assetId: Mapped[int] = mapped_column(Integer, index=True)
    assetName: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)  # 元（ADR-006）
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
    amount: Mapped[float] = mapped_column(Float, default=0)  # 元（ADR-006）
    date: Mapped[str] = mapped_column(String(32), default="")
    ref: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(String(255), default="")
    # 流水操作账号（登录 username；启动 seed 路径为 "system"）；存量流水为空，前端显示 "-"
    operator: Mapped[str] = mapped_column(String(64), default="")
    # 关联合同 id（ADR-007）：合同级交付/终止产生的流水记录；非合同场景为 NULL
    contractId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class OpLog(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(String(32))
    targetName: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(String(512), default="")
    operator: Mapped[str] = mapped_column(String(64), default="admin")
    time: Mapped[str] = mapped_column(String(32), default="")
    # 关联产品 id（target='asset' 时记录，便于按产品追溯操作日志）；存量数据为 NULL
    assetId: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 字段级变更描述（如「销售单价: 330,000 元 → 3,200,000 元；产品总数: 10 → 12 台」，金额单位=元）；
    # 仅 update_asset 有实际变更时写入，其余日志点为空
    changes: Mapped[str] = mapped_column(String(512), default="")
    # 关联合同 id（ADR-007）：合同级状态变更日志记录；非合同场景为 NULL
    contractId: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FileMeta(Base):
    """上传文件原名映射：散列落盘名 → 原始文件名。

    上传文件以散列名落盘 uploads/，产品/日志直接存散列名；本表记录散列名与
    原始文件名的对应关系，供前端展示与下载时还原原始名。上传不是产品操作，
    故 add_file_meta 只写本表、不写 OpLog。
    """

    __tablename__ = "file_meta"

    storedName: Mapped[str] = mapped_column(String(255), primary_key=True)  # 散列落盘名
    name: Mapped[str] = mapped_column(String(255), default="")  # 原始文件名
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploadedBy: Mapped[str] = mapped_column(String(64), default="")  # 上传账号 username
    createdAt: Mapped[str] = mapped_column(String(32), default="")  # ISO 字符串，风格同 OpLog.time


class BaseRecord(Base):
    """供应商 / 客户，通用表按 kind 区分（CLEANUP-20261020：reps 已下线）"""

    __tablename__ = "base_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # suppliers / customers（reps 已下线）
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
    """购物车项（ADR-009：按登录用户隔离，userId=登录用户 users.id 字符串）"""

    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    userId: Mapped[str] = mapped_column(String(64), default="admin", index=True)
    assetId: Mapped[int] = mapped_column(Integer, index=True)
    # 行级客户（ADR-007）：购物车支持跨主体加购，结算时按 customer 分组拆合同。
    # 唯一键语义：(userId, assetId, customer) 相同才合并（不同 customer 同产品 = 两行）。
    customer: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    # 包量计价合同金额（ADR-008，元，整数）：仅 pricingMode='amount' 产品行使用，
    # 结算时必填（缺失 400）；unit 模式行为不变（忽略本列，恒 NULL）。
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 遥感数据明细（ADR-011）：非空时本行售卖 rs_items 明细（qty 恒 1，结算金额=明细 price 权威）；
    # 判重键升级为 (userId, assetId, itemId, customer)；存量/非遥感行恒 NULL。
    # DB 兜底：唯一索引 uq_cart_items_key 在 main._ensure_unique_indexes 以
    # COALESCE(itemId, 0) 表达式幂等补建（SQLite 唯一索引不认 NULL 相等；0 为不可能的主键值）。
    itemId: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，下单人填，checkout 透传落 project_items；
    # 遥感行不填期限（期数即服务时间）；存量行 NULL
    serviceStart: Mapped[str | None] = mapped_column(String(10), nullable=True)
    serviceEnd: Mapped[str | None] = mapped_column(String(10), nullable=True)
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")


class RsItem(Base):
    """遥感数据可售明细（ADR-011）：父产品（assets 行，容器）下的真正售卖单位。

    维度 = 省（可含市）× 精度（米）× 月份（YYYY-MM），每份一个单价（整数元/份），
    默认可重复售卖（只计次不扣量）。唯一性 (assetId, province, city, resolution, saleMonth)
    双防线：服务层判重（Python 层，含浮点容差）+ DB 唯一索引（uq_rs_items_dim，
    main._ensure_unique_indexes 为存量表幂等补建，新库由 create_all 随约束生成）。
    """

    __tablename__ = "rs_items"
    __table_args__ = (
        UniqueConstraint("assetId", "province", "city", "resolution", "saleMonth",
                         name="uq_rs_items_dim"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assetId: Mapped[int] = mapped_column(Integer, index=True)  # 父产品（type='遥感数据'）
    province: Mapped[str] = mapped_column(String(64), default="")  # 省/自治区/直辖市，必填
    city: Mapped[str] = mapped_column(String(64), default="")  # 市，可空（默认 ''）
    resolution: Mapped[float] = mapped_column(Float, default=0)  # 精度，单位米（如 1.5）
    saleMonth: Mapped[str] = mapped_column(String(7), default="")  # 售卖月份 YYYY-MM
    price: Mapped[float] = mapped_column(Float, default=0)  # 单价，整数元/份（元口径，ADR-006）
    repeatSale: Mapped[bool] = mapped_column(Boolean, default=True)  # 可重复售卖（只计次不扣量）
    createdAt: Mapped[str] = mapped_column(String(32), default="")
    updatedAt: Mapped[str] = mapped_column(String(32), default="")
