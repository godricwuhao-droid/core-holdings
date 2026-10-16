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
    salePrice: float  # 元（ADR-006）；pricingMode='amount' 时仅作参考值，不参与金额计算
    soldAmount: float  # 元
    soldCount: int
    status: str
    inboundDate: str
    expiryDate: str
    perpetual: bool
    spec: str
    saleDetail: dict | None = None  # 保留出参（存量数据），UI 已改用 featureDoc 展示
    featureDoc: str = ""  # 功能清单附件 filename（/upload 返回值）；空=未上传
    contractFile: str = ""
    remark: str
    updatedAt: str
    # 计价模式（ADR-008）：'unit'（单价×数量）| 'amount'（包量金额整数元权威）。
    # 后端按类型权威决定（卫星Token → 'amount'），不接受前端入参。
    pricingMode: str = "unit"
    # 注：ADR-010 的 province/city/resolution/imageDate 出参已移除（ADR-011，列保留不删）；
    # 遥感数据售卖粒度见 bootstrap.rsItems（RsItemOut[]）


class AssetInput(BaseModel):
    name: str
    board: str
    type: str
    subject: str
    unit: str = ""
    quantity: int = Field(ge=0)
    repeatSale: bool
    salePrice: float = Field(ge=0)  # 元（ADR-006）；卫星Token（amount 模式）仅作参考值
    status: str
    inboundDate: str
    expiryDate: str
    perpetual: bool
    spec: str
    saleDetail: dict | None = None  # 保留入参兼容（UI 不再展示），列与存量数据不删
    featureDoc: str = ""  # 功能清单附件 filename；空=未上传
    contractFile: str = ""
    remark: str = ""
    # 注意：不含 pricingMode——计价模式由后端按类型权威决定（卫星Token → 'amount'）。
    # ADR-010 的 province/city/resolution/imageDate 入参已移除（ADR-011）：
    # 遥感数据按普通父资产登记，售卖粒度走 POST /assets/{id}/rs-items 明细。
    # 前端若仍多传这 4 个字段，Pydantic 默认忽略未知字段，不报错。


class AssetUpdate(BaseModel):
    """PUT /assets/{id} 入参（编辑为部分更新，全字段可选）。

    修复裸 dict 无校验问题：quantity 必须为非负整数、salePrice 非负，
    非法类型/负数 422（此前裸 dict + setattr，负数/字符串可落库破坏库存口径）。
    status 保留兼容（前端会传），服务层落库前由 auto_status 覆盖（两态自动判定）。
    """
    name: str | None = None
    board: str | None = None
    type: str | None = None
    subject: str | None = None
    unit: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    repeatSale: bool | None = None
    salePrice: float | None = Field(default=None, ge=0)  # 元（ADR-006）
    status: str | None = None
    inboundDate: str | None = None
    expiryDate: str | None = None
    perpetual: bool | None = None
    spec: str | None = None
    saleDetail: dict | None = None
    featureDoc: str | None = None
    contractFile: str | None = None
    remark: str | None = None


class StatusInput(BaseModel):
    status: str
    reason: str = ""


# ============================================================
# 遥感数据可售明细（ADR-011：父资产 + 明细两层模型）
# ============================================================
class RsItemInput(BaseModel):
    """POST /assets/{assetId}/rs-items 与 PUT /rs-items/{id} 入参。

    金额单位=元（ADR-006）：price 为整数元/份（服务层校验 >0 且整数，否则 400）。
    """
    province: str  # 省/自治区/直辖市，必填（服务层校验非空）
    city: str = ""  # 市，可空（默认 ''）
    resolution: float = Field(gt=0)  # 精度，单位米（如 1.5）
    saleMonth: str = Field(pattern=r"^\d{4}-\d{2}$")  # 售卖月份 YYYY-MM
    price: float = Field(gt=0)  # 单价，整数元/份
    repeatSale: bool = True  # 可重复售卖（默认 true，可关闭）


class RsItemOut(_ORM):
    id: int
    assetId: int
    province: str
    city: str
    resolution: float
    saleMonth: str
    price: float  # 元（整数元/份）
    repeatSale: bool
    createdAt: str
    updatedAt: str


# ============================================================
# 销售项目
# ============================================================
class ProjectItemInput(BaseModel):
    """金额字段单位=元（ADR-006）。

    类型选择说明：入参保持 `float` 接收（Pydantic 兼容 Decimal 比较，`ge=0` 422 语义不变）；
    后端业务计算在 services 层统一转 decimal.Decimal，改动最小。
    """
    assetId: int | None = None
    qty: int = Field(ge=0)
    price: float = Field(ge=0)  # 元
    # 计价分支（ADR-008）：
    # - 资产 pricingMode='amount'：amount 为**权威输入**（整数元，>0，否则 400），
    #   后端跳过 price×qty 重算，price = round(amount/qty, 6) 仅作派生展示值；
    # - pricingMode='unit'：后端权威重算 amount = (Decimal(price) * qty).quantize(0.01)，不采信传入值。
    amount: float = Field(ge=0)
    deliveryReq: str = ""
    # 遥感数据明细（ADR-011，可选）：非空时本行售卖 rs_items 明细——
    # qty 强制 1（≠1 → 400），amount 后端权威 = 明细 price × 1（忽略前端传值），
    # 明细 repeatSale=true → 不锁库存；false → 按父资产 lockedQty 逻辑（qty=1）
    itemId: int | None = None


class ProjectItemOut(_ORM):
    id: int
    assetId: int | None = None
    contractId: int | None = None  # 所属合同（ADR-007）；存量项为 null
    itemId: int | None = None  # 遥感数据明细（ADR-011）；存量/非遥感行为 null
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


class ContractInput(BaseModel):
    """合同入参（ADR-007）：POST /projects 的 contracts[] 元素。

    合同内强制同一资产主体（后端校验，不一致 400）；contractAmount 可选，
    缺省由后端按明细 amount 合计重算（Decimal，元口径）。
    """
    customer: str  # 必填：合同客户
    items: list[ProjectItemInput]
    contractAmount: float | None = Field(default=None, ge=0)  # 元；None=按明细合计
    remark: str = ""


class ContractOut(_ORM):
    """合同出参（bootstrap.contracts / 项目关联展示）"""
    id: int
    code: str  # HT-{4位序号}
    projectId: int
    customer: str
    subject: str
    contractAmount: float  # 元（ADR-006）
    status: str  # active / delivered / terminated
    remark: str
    items: list[ProjectItemOut]
    createdAt: str
    updatedAt: str


class ProjectInput(BaseModel):
    """销售项目输入。

    注意：不含 status —— 项目状态由后端状态机权威决定（create 强制 active，编辑不采信 status）。
    前端若仍传 status，Pydantic 默认忽略未知字段，不报错。
    """
    name: str
    customer: str
    industry: str
    rep: str
    businessOwner: str = ""  # 商务负责人（可选，默认空；前端显示 "-"）
    subject: str
    # 金额字段单位=元（ADR-006）；保持 float 接收，422 语义不变（ge=0）
    expectedAmount: float = Field(ge=0)
    quoteAmount: float = Field(ge=0)
    contractAmount: float = Field(ge=0)
    paidAmount: float = Field(ge=0)
    expectedSignDate: str
    lastFollowDate: str
    remark: str
    items: list[ProjectItemInput] = Field(default_factory=list)  # ADR-007：可空（传 contracts 时不传 items）
    # ADR-007：合同结构入参（可选）。两种入参都支持：
    # - 传 contracts：按合同建项目（每客户一个合同，合同内强制同主体）；
    # - 不传（仅 items）：向后兼容，按单合同自动包装，customer 取项目 customer 字段。
    # 注意：update_project 不再接受 items/contracts 变更（收到即忽略）。
    contracts: list[ContractInput] | None = None


class ProjectOut(_ORM):
    id: int
    code: str
    name: str
    customer: str
    industry: str
    rep: str
    businessOwner: str  # 商务负责人（存量项目为空，前端显示 "-"）
    subject: str
    status: str
    expectedAmount: float  # 元（ADR-006）
    quoteAmount: float  # 元
    contractAmount: float  # 元
    paidAmount: float  # 元
    expectedSignDate: str
    lastFollowDate: str
    remark: str
    items: list[ProjectItemOut]
    contractCount: int = 0  # 合同数量（ADR-007 派生，Project.contractCount 属性）
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
    amount: float = Field(ge=0)  # 元（ADR-006）
    type: str
    mode: str
    date: str
    operator: str = ""
    remark: str = ""


class OutboundOut(_ORM):
    id: int
    code: str
    projectId: int | None = None
    contractId: int | None = None  # 所属合同（ADR-007）；合同交付自动出库时非空
    projectName: str
    customer: str
    assetId: int
    assetName: str
    qty: int
    unit: str
    amount: float  # 元（ADR-006）
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
    amount: float  # 元（ADR-006）
    date: str
    ref: str
    note: str
    operator: str = ""  # 流水操作账号；存量流水为空（前端显示 "-"），启动 seed 为 "system"
    contractId: int | None = None  # 关联合同（ADR-007）；非合同场景为 null


class FileMetaOut(_ORM):
    """上传文件原名映射（bootstrap.files 全量返回）"""
    storedName: str
    name: str
    size: int
    uploadedBy: str
    createdAt: str


class LogOut(_ORM):
    id: int
    target: str
    targetName: str
    action: str
    detail: str
    operator: str
    time: str
    assetId: int | None = None  # 仅 target='asset' 有值；前端 types.ts 未声明，属可选附加字段
    changes: str = ""  # 字段级变更描述（仅 update_asset 有实际变更时非空），如「销售单价: 330,000 元 → 3,200,000 元」
    contractId: int | None = None  # 关联合同（ADR-007）；合同级状态变更日志非空


# ============================================================
# 购物车（ADR-009：按登录用户隔离）
# ============================================================
class CartItemOut(_ORM):
    id: int
    userId: str
    assetId: int
    customer: str = ""  # 行级客户（ADR-007）；结算时按 customer 分组拆合同
    qty: int
    # 包量计价合同金额（ADR-008，元，整数）：仅 amount 模式资产行非空；unit 模式恒 null
    amount: float | None = None
    itemId: int | None = None  # 遥感数据明细（ADR-011）；含 itemId 行 qty 恒 1；存量/非遥感行为 null
    createdAt: str
    updatedAt: str


class CartItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)
    customer: str = ""  # 行级客户（ADR-007）；(userId, assetId, customer) 相同才合并
    # 包量计价合同金额（ADR-008，可选，元，整数）：amount 模式资产行结算前必填（缺失 400）；
    # unit 模式忽略（不采信、不落库）
    amount: float | None = None
    # 遥感数据明细（ADR-011，可选）：非空时校验明细存在且归属 assetId；qty 恒 1（≠1 → 400）；
    # 判重键升级为 (userId, assetId, itemId, customer)（无 itemId 行口径不变）
    itemId: int | None = None


class CartPatchInput(BaseModel):
    """PATCH /cart/{id}：修改购物车行级客户（ADR-007）；可选携带 amount（ADR-008）"""
    customer: str
    amount: float | None = None  # amount 模式行可改合同金额（整数元）；unit 模式忽略


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
    """购物车下单（ADR-007）：按购物车行级 customer 分组，每客户一个合同。

    customer 字段保留兼容（可选，不再参与分组）——行级 customer 为空直接 400。
    """
    projectName: str = ""
    customer: str = ""  # 兼容保留，不参与分组（行级 customer 为准）
    rep: str = ""
    businessOwner: str = ""  # 商务负责人（可选，默认空；前端显示 "-"）
    contractAmount: float = Field(default=0, ge=0)  # 元（ADR-006）
    expectedSignDate: str = ""
    remark: str = ""
    deliveryReq: str = ""


class SaleOrderItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)
    # 包量计价合同金额（ADR-008，元，整数）：amount 模式资产必填（缺失/非整数 400）；unit 模式忽略
    amount: float | None = None
    # 遥感数据明细（ADR-011，可选）：非空时 qty 强制 1（≠1 → 400），
    # amount 后端权威 = 明细 price × 1（忽略前端传值）
    itemId: int | None = None


class SaleOrderInput(BaseModel):
    """资产直接下单（单/多资产）：主体由资产带出，生成进行中销售项目（锁定库存）；交付由人工置"已完成"触发"""
    projectName: str
    customer: str
    rep: str = ""
    businessOwner: str = ""  # 商务负责人（可选，默认空；前端显示 "-"）
    contractAmount: float = 0  # 元（ADR-006）
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
