"""Pydantic 请求/响应模型（字段与前端 types.ts 对齐）"""
from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 资产
# ============================================================
class AssetOut(_ORM):
    id: int
    code: str
    name: str
    board: str
    type: str
    subject: str
    unit: str
    quantity: int
    lockedQty: int
    shippedQty: int
    repeatSale: bool
    salePrice: float
    soldAmount: float
    soldCount: int
    status: str
    inboundDate: str
    expiryDate: str
    perpetual: bool
    spec: str
    saleDetail: dict | None = None
    contractFile: str = ""
    remark: str
    updatedAt: str


class AssetInput(BaseModel):
    name: str
    board: str
    type: str
    subject: str
    unit: str
    quantity: int = Field(ge=0)
    repeatSale: bool
    salePrice: float = Field(ge=0)
    status: str
    inboundDate: str
    expiryDate: str
    perpetual: bool
    spec: str
    saleDetail: dict | None = None
    contractFile: str = ""
    remark: str = ""


class StatusInput(BaseModel):
    status: str
    reason: str = ""


# ============================================================
# 销售项目
# ============================================================
class ProjectItemInput(BaseModel):
    assetId: int | None = None
    qty: int = Field(ge=0)
    price: float = Field(ge=0)
    amount: float = Field(ge=0)  # 仅作前端回显；后端权威重算 amount = round(price*qty, 4)，不采信传入值
    deliveryReq: str = ""


class ProjectItemOut(_ORM):
    id: int
    assetId: int | None = None
    qty: int
    unit: str
    price: float
    amount: float
    status: str
    deliveryReq: str
    locked: bool  # 下单时刻是否真实加锁（非 repeatSale）；前端展示/判断用
    lockedDate: str
    confirmedDate: str
    shippedDate: str


class ProjectInput(BaseModel):
    """销售项目输入。

    注意：不含 status —— 项目状态由后端状态机权威决定（create 强制 active，编辑不采信 status）。
    前端若仍传 status，Pydantic 默认忽略未知字段，不报错。
    """
    name: str
    customer: str
    industry: str
    rep: str
    subject: str
    expectedAmount: float = Field(ge=0)
    quoteAmount: float = Field(ge=0)
    contractAmount: float = Field(ge=0)
    paidAmount: float = Field(ge=0)
    expectedSignDate: str
    lastFollowDate: str
    remark: str
    items: list[ProjectItemInput]


class ProjectOut(_ORM):
    id: int
    code: str
    name: str
    customer: str
    industry: str
    rep: str
    subject: str
    status: str
    expectedAmount: float
    quoteAmount: float
    contractAmount: float
    paidAmount: float
    expectedSignDate: str
    lastFollowDate: str
    remark: str
    items: list[ProjectItemOut]
    createdAt: str
    updatedAt: str


# ============================================================
# 出库
# ============================================================
class OutboundInput(BaseModel):
    projectId: int | None = None
    customer: str = ""
    assetId: int
    qty: int = Field(ge=0)
    amount: float = Field(ge=0)
    type: str
    mode: str
    date: str
    operator: str = ""
    remark: str = ""


class OutboundOut(_ORM):
    id: int
    code: str
    projectId: int | None = None
    projectName: str
    customer: str
    assetId: int
    assetName: str
    qty: int
    unit: str
    amount: float
    type: str
    mode: str
    date: str
    operator: str
    status: str
    remark: str


# ============================================================
# 基础资料
# ============================================================
class BaseRecordInput(BaseModel):
    name: str
    contact: str = ""
    phone: str = ""
    remark: str = ""


class BaseRecordOut(_ORM):
    id: int
    name: str
    contact: str
    phone: str
    remark: str


# ============================================================
# 交付物
# ============================================================
class DeliverableTemplateInput(BaseModel):
    name: str
    category: str
    required: bool
    note: str = ""


class DeliverableTemplateOut(_ORM):
    id: int
    name: str
    category: str
    required: bool
    note: str


class AssetDeliverableInput(BaseModel):
    name: str
    category: str
    required: bool
    note: str = ""


class AssetDeliverableOut(_ORM):
    id: int
    name: str
    category: str
    required: bool
    note: str
    version: str
    meta: str
    status: str
    updatedAt: str


# ============================================================
# 分类单位
# ============================================================
class CategoryUnitOut(_ORM):
    id: int
    board: str
    type: str
    unit: str
    note: str


# ============================================================
# 流水 / 日志
# ============================================================
class FlowOut(_ORM):
    id: int
    assetId: int
    type: str
    qty: int
    unit: str
    amount: float
    date: str
    ref: str
    note: str


class LogOut(_ORM):
    id: int
    target: str
    targetName: str
    action: str
    detail: str
    operator: str
    time: str
    assetId: int | None = None  # 仅 target='asset' 有值；前端 types.ts 未声明，属可选附加字段


# ============================================================
# 购物车（预留 userId 维度）
# ============================================================
class CartItemOut(_ORM):
    id: int
    userId: str
    assetId: int
    qty: int
    createdAt: str
    updatedAt: str


class CartItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)


class CartBatchInput(BaseModel):
    items: list[CartItemInput]


class CartSkippedItem(BaseModel):
    assetId: int
    name: str
    available: int
    reason: str


class CartBatchResult(BaseModel):
    addedCount: int
    skipped: list[CartSkippedItem]
    cart: list[CartItemOut]


class CheckoutInput(BaseModel):
    """购物车下单：主体/行业由资产自动带出，无需前端传入"""
    projectName: str
    customer: str
    rep: str = ""
    contractAmount: float = Field(default=0, ge=0)
    expectedSignDate: str = ""
    remark: str = ""
    deliveryReq: str = ""


class SaleOrderItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)


class SaleOrderInput(BaseModel):
    """资产直接下单（单/多资产）：主体由资产带出，生成进行中销售项目（锁定库存）；交付由人工置"已完成"触发"""
    projectName: str
    customer: str
    rep: str = ""
    contractAmount: float = 0
    expectedSignDate: str = ""
    remark: str = ""
    deliveryReq: str = ""
    items: list[SaleOrderItemInput]


# ============================================================
# 认证 / 用户管理 / 审计日志
# ============================================================
class LoginInput(BaseModel):
    username: str
    password: str


class UserOut(_ORM):
    """用户输出（不含 passwordHash）"""
    id: int
    username: str
    name: str
    role: str
    enabled: bool


class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    role: str  # admin / editor / viewer


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    enabled: bool | None = None
    password: str | None = None


class AuditLogOut(_ORM):
    id: int
    userId: int | None = None
    username: str
    actionType: str
    action: str
    target: str
    targetName: str
    detail: str | None = None
    time: str
