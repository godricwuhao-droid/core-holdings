"""Pydantic 请求/响应模型（字段与前端 types.ts 对齐）"""
from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ============================================================
# 产品
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
    # 参考区间（ADR-018 §1，PRICING-20261020）：元/份，选填；null=未设置（不限制折扣）
    priceMin: float | None = None
    priceMax: float | None = None
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
    # 容器「可售数量」= 可售期数（加性可选字段，追加在末尾）。
    # 仅 type == '遥感数据' 的容器由 bootstrap 派生（RS-STATUS-20261022 口径：
    # `rs_items.status = 'in_stock'` 的明细条数，in_stock=可售 / all_sold=已售罄）；
    # 非容器恒 None —— 前端对非容器继续用 quantity-lockedQty-shippedQty，双口径不混。
    availableCount: int | None = None
    # 注：ADR-010 的 province/city/resolution/imageDate 出参已移除（ADR-011，列保留不删）；
    # 遥感数据售卖粒度见 bootstrap.rsItems（RsItemOutWithSold[]，FIX-20261022-FOLLOWUP 起含派生 soldCount）


class AssetInput(BaseModel):
    name: str
    board: str
    type: str
    subject: str
    unit: str = ""
    quantity: int = Field(ge=0)
    repeatSale: bool
    salePrice: float = Field(ge=0)  # 元（ADR-006）；卫星Token（amount 模式）仅作参考值
    # 参考区间（ADR-018 §1，PRICING-20261020）：元/份，选填（单边允许）；
    # 两者都有时 min ≤ max，否则 400「参考区间下限不能大于上限」
    priceMin: float | None = Field(default=None, ge=0)
    priceMax: float | None = Field(default=None, ge=0)
    status: str
    # ADR-036 §1（FORMS-20261022）：登记时间不再必填——不传/空 → 后端自动生成当天
    # YYYY-MM-DD；传值仍走 _validate_date_str 校验（编辑页只读展示是前端约束）
    inboundDate: str = ""
    expiryDate: str
    perpetual: bool
    spec: str
    saleDetail: dict | None = None  # 保留入参兼容（UI 不再展示），列与存量数据不删
    featureDoc: str = ""  # 功能清单附件 filename；空=未上传
    contractFile: str = ""
    remark: str = ""
    # 注意：不含 pricingMode——计价模式由后端按类型权威决定（卫星Token → 'amount'）。
    # ADR-010 的 province/city/resolution/imageDate 入参已移除（ADR-011）：
    # 遥感数据按普通父产品登记，售卖粒度走 POST /assets/{id}/rs-items 明细。
    # 前端若仍多传这 4 个字段，Pydantic 默认忽略未知字段，不报错。


class AssetUpdate(BaseModel):
    """PUT /assets/{id} 入参（编辑为部分更新，全字段可选）。

    修复裸 dict 无校验问题：quantity 必须为非负整数、salePrice 非负，
    非法类型/负数 422（此前裸 dict + setattr，负数/字符串可落库破坏数量口径）。
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
    # 参考区间（ADR-018 §1，PRICING-20261020）：选填；传 null 清空（恢复不限制）
    priceMin: float | None = Field(default=None, ge=0)
    priceMax: float | None = Field(default=None, ge=0)
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
# 订单审核（ADR-012：生态人员下单 → 待审核 → 商务改价确认/驳回）
# ============================================================
class ReviewItemInput(BaseModel):
    """行级改价入参：itemId = project_items.id。
    unit 模式传 price（实际单价）；amount 模式传 amount（实际合同金额，整数元）；
    遥感明细行（含 itemId 的销售明细）不接受改价 → 400。"""
    itemId: int
    price: float | None = None
    amount: float | None = None
    # 服务期限（ADR-020，PRICING-20261020）：confirm 可改（YYYY-MM-DD，start ≤ end 否则 400）；
    # 不传 = 保持原值
    serviceStart: str | None = None
    serviceEnd: str | None = None


class ReviewInput(BaseModel):
    """POST /projects/{id}/review：action=confirm 确认下单（可带 items 改价）/ reject 驳回（reason 必填）"""
    action: str  # confirm | reject
    reason: str = ""
    items: list[ReviewItemInput] = []


class ClaimInput(BaseModel):
    """POST /projects/{id}/claim（ADR-012 §5.1 纯移交制）：newOwner 空=接手给自己；
    非空=转交给该账号（仅当前负责人或 admin 可传，目标须为启用的商务/管理员账号）。"""
    newOwner: str = ""


class WithdrawInput(BaseModel):
    """POST /projects/{id}/withdraw（ADR-026）：生态人员撤销自己提交的待审核订单。

    reason：必填，1–200 字（服务层 strip 后校验，空白 → 400「请填写撤销原因」，
    超长 → 400「撤销原因不能超过 200 字」）。缺省空串（而非 422）便于统一 400 文案。
    """
    reason: str = ""


# ============================================================
# 遥感数据可售明细（ADR-011：父产品 + 明细两层模型）
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
    # 参考区间（ADR-021，RSITEM-RANGE-20261020）：元/份，选填（单边允许）；
    # 两者都有时 min ≤ max，否则 400「参考区间下限不能大于上限」（与产品区间同口径）
    priceMin: float | None = Field(default=None, ge=0)
    priceMax: float | None = Field(default=None, ge=0)
    # 可重复售卖（ADR-038，RS-REPEAT-20261022）：缺省 **false** = 单次售卖——
    # 该明细一旦被非 terminated 合同占用即从容器 availableCount 中扣除（一期通常只卖一次）。
    # true = 只计次不扣量（售出后仍计入可售）。与 models.RsItem.repeatSale 默认值保持一致。
    repeatSale: bool = False


class RsItemOut(_ORM):
    id: int
    assetId: int
    province: str
    city: str
    resolution: float
    saleMonth: str
    price: float  # 元（整数元/份）
    # 参考区间（ADR-021，RSITEM-RANGE-20261020）：元/份，null=不限制
    priceMin: float | None
    priceMax: float | None
    repeatSale: bool
    # 明细状态（RS-STATUS-20261022，ADR-038 Decision 3 修订）：'in_stock'（可售）/
    # 'all_sold'（已售罄）。由 services._sync_rs_item_status 按真值维护；
    # 前端选择器的置灰判断与「已售罄」文案统一用本字段（原 `occupied` 派生字段已删除，
    # 避免 occupied / status 两套语义并存）。
    status: str
    createdAt: str
    updatedAt: str


class RsItemOutWithSold(RsItemOut):
    """PAGE-20261021：GET /assets/{id}/rs-items 出参 = RsItemOut 全部字段 + 派生 soldCount。

    soldCount 口径：该明细被 delivered 状态合同的项目明细计数
    （project_items.itemId == rs_item.id 且所属合同 status='delivered'），
    由路由层聚合查询后回填（ORM 对象无此属性，故不设默认值依赖 from_attributes）。

    RS-STATUS-20261022：`occupied`（被非 terminated 合同引用）派生字段**已删除**——
    「该明细还能不能卖」只认 `status`（in_stock/all_sold），不再保留第二套语义。
    """

    soldCount: int


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
    # - 产品 pricingMode='amount'：amount 为**权威输入**（整数元，>0，否则 400），
    #   后端跳过 price×qty 重算，price = round(amount/qty, 6) 仅作派生展示值；
    # - pricingMode='unit'：后端权威重算 amount = (Decimal(price) * qty).quantize(0.01)，不采信传入值。
    amount: float = Field(ge=0)
    deliveryReq: str = ""
    # 遥感数据明细（ADR-011，可选）：非空时本行售卖 rs_items 明细——
    # qty 强制 1（≠1 → 400），amount 后端权威 = 明细 price × 1（忽略前端传值），
    # 明细 repeatSale=true → 不锁数量；false → 按父产品 lockedQty 逻辑（qty=1）
    itemId: int | None = None
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，start ≤ end 否则 400；
    # 遥感行不填期限（期数即服务时间）
    serviceStart: str | None = None
    serviceEnd: str | None = None
    # 折扣率：**已下线（ADR-039），后端忽略**——字段定义仅为兼容旧客户端（传了不 422、不 400），
    # 后端不读取、不校验、不落库（新明细 discountRate 恒 null；原 DISCOUNT-20261021/ADR-023）
    discountRate: float | None = None


class ProjectItemOut(_ORM):
    id: int
    assetId: int | None = None
    contractId: int | None = None  # 所属合同（ADR-007）；存量项为 null
    itemId: int | None = None  # 遥感数据明细（ADR-011）；存量/非遥感行为 null
    qty: int
    unit: str
    price: float  # 最终价（折扣/终审后，ADR-018）
    amount: float  # 最终行金额
    # 原价快照（ADR-018 §2，PRICING-20261020）：下单时快照、永不覆盖；存量订单为 null
    origPrice: float | None = None
    origAmount: float | None = None
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD；存量/遥感行为 null
    serviceStart: str | None = None
    serviceEnd: str | None = None
    # 折扣率快照：**已下线（ADR-039），后端不再写入**——新单恒 null；
    # 存量单/历史项目的历史值原样返回（只读追溯用，前端不再展示）
    discountRate: float | None = None
    status: str
    deliveryReq: str
    locked: bool  # 下单时刻是否真实加锁（非 repeatSale）；前端展示/判断用
    lockedDate: str
    confirmedDate: str
    shippedDate: str


class ContractInput(BaseModel):
    """合同入参（ADR-007）：POST /projects 的 contracts[] 元素。

    合同内强制同一产品主体（后端校验，不一致 400）；contractAmount 可选，
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
    status: str  # active / delivering / delivered / terminated（ADR-019 新增 delivering「交付中」）
    # 时间节点（ADR-019，PRICING-20261020）：YYYY-MM-DD；存量合同为 null
    signedDate: str | None = None  # 合同签订时间（商务填，录入即 active→delivering，不可清空）
    scheduledDeliveryDate: str | None = None  # 预计交付时间（仅 admin 填，仅 delivering 可录/改/清空）
    remark: str
    items: list[ProjectItemOut]
    createdAt: str
    updatedAt: str


class ContractFieldPatch(BaseModel):
    """PATCH /contracts/{id} 入参（ADR-019，PRICING-20261020）：两字段均可选，按字段分别校验。

    - signedDate：editor/admin（接手人守卫，与审核同口径）；仅合同 active 可录入，
      录入后自动 active→delivering；录后可改、传 null 清空 → 400；
    - scheduledDeliveryDate：仅 admin；仅合同 delivering 可录/改/清空（null 允许）。
    路由层用 model_dump(exclude_unset=True) 区分「未传」与「传 null」。
    """
    signedDate: str | None = None
    scheduledDeliveryDate: str | None = None


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
    quoteAmount: float = Field(default=0, ge=0)  # 2026-10-19 废弃（不再填写/不写入），可选兼容存量调用
    contractAmount: float = Field(ge=0)
    paidAmount: float = Field(default=0, ge=0)  # 2026-10-19 废弃（不再填写/不写入），可选兼容存量调用
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
    # 下单账号（username；存量项目为空串）。ADR-026：生态人员「撤销」按 creator 判定归属，
    # 前端也需要该字段做「本人单」按钮显隐（此前 ProjectOut 漏输出，导致前端只能靠可见性兜底）
    creator: str = ""
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
    # 明细是否已回填购物车（ADR-027 幂等标记）：前端「重新提交」据此提示「明细已在购物车」
    cartRefilled: bool = False
    createdAt: str
    updatedAt: str


# ============================================================
# 交付
# ============================================================
class OutboundInput(BaseModel):
    projectId: int | None = None
    customer: str = ""
    assetId: int
    qty: int = Field(ge=0)  # 服务层拒绝 0（FIX-20261020-#13a：交付数量必须大于 0）
    amount: float = Field(ge=0)  # 元（ADR-006）
    type: str
    mode: str
    date: str
    # 注：operator 字段已移除（FIX-20261020/ADR-015 契约：后端一直不采信前端入参，
    # 操作人取路由层真实登录账号；前端旧版本多传该字段时 Pydantic 默认忽略未知字段）
    remark: str = ""


class OutboundOut(_ORM):
    id: int
    code: str
    projectId: int | None = None
    contractId: int | None = None  # 所属合同（ADR-007）；合同交付自动交付时非空
    projectItemId: int | None = None  # 所属项目明细（FIX-20261020-#7）；合同交付时非空，手动补录/存量为 null
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
# 资产主体（ADR-035，ENTITIES-20261022）
# ============================================================
class EntityInput(BaseModel):
    # 长度校验在服务层 trim 后进行（name 2–64 字、short 1–32 字，400）
    name: str
    short: str


class EntityOut(_ORM):
    id: int
    name: str
    short: str
    createdAt: str
    updatedAt: str


# ============================================================
# 交付物（ADR-024：模板体系下线，实例完全手动维护；每项可挂单文件附件 file）
# ============================================================
class AssetDeliverableInput(BaseModel):
    name: str
    category: str
    required: bool
    note: str = ""
    url: str = ""  # ADR-044：外部链接（仅 http/https，服务层校验；""=无链接）


class AssetDeliverableUpdate(BaseModel):
    """PUT /assets/{id}/deliverables/{did} 入参（BUG-20 / FIX-20261022：裸 dict → Pydantic）。

    全部字段可选，语义为**部分更新**：未传 = 保持原值（路由层按 `model_fields_set` 取 patch）。
    非法类型 422（此前裸 dict + setattr 可写脏值）。`file`：散列文件名；`""`/null = 清空附件。
    `url`：外部链接，`""`/null = 清空（ADR-044，仅 http/https，服务层校验）。
    """
    name: str | None = None
    category: str | None = None
    required: bool | None = None
    note: str | None = None
    version: str | None = None
    meta: str | None = None
    status: str | None = None
    file: str | None = None
    url: str | None = None


class AssetDeliverableOut(_ORM):
    id: int
    name: str
    category: str
    required: bool
    note: str
    version: str
    meta: str
    status: str
    file: str | None = None  # ADR-024：单文件附件散列名（空/NULL=无附件）
    url: str = ""  # ADR-044：外部链接（空串=无链接；仅 http/https）
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
    # ADR-041（FLOW-20261022）：target='project'/'outbound' 的结构化外键，
    # 前端「流转过程」按 id 精确过滤（对齐 assetId 既有做法）；非项目级日志显式 null。
    # 注：Visibility.log_visible 早已按该字段过滤，本字段纯属出参补齐，无行为变更。
    projectId: int | None = None


# ============================================================
# 购物车（ADR-009：按登录用户隔离）
# ============================================================
class CartItemOut(_ORM):
    id: int
    userId: str
    assetId: int
    customer: str = ""  # 行级客户（ADR-007）；结算时按 customer 分组拆合同
    qty: int
    # 合同金额（元，整数）：amount 模式行=权威金额；unit/遥感明细行=折扣金额
    # （ADR-018 §3，PRICING-20261020 起 unit 行放开）；null=原价成交
    amount: float | None = None
    itemId: int | None = None  # 遥感数据明细（ADR-011）；含 itemId 行 qty 恒 1；存量/非遥感行为 null
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD；遥感行不填；存量行为 null
    serviceStart: str | None = None
    serviceEnd: str | None = None
    # 折扣率：**已下线（ADR-039）**——出参保留该字段（历史行原值可追溯），新行恒 null
    discountRate: float | None = None
    createdAt: str
    updatedAt: str


class CartItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)
    customer: str = ""  # 行级客户（ADR-007）；(userId, assetId, customer) 相同才合并
    # 合同金额（可选，元，整数）：amount 模式产品行结算前必填（缺失 400）；
    # unit/遥感明细行=折扣金额（ADR-018 §3，PRICING-20261020 起放开，过参考区间校验）；
    # 不传 = 原价成交
    amount: float | None = None
    # 遥感数据明细（ADR-011，可选）：非空时校验明细存在且归属 assetId；qty 恒 1（≠1 → 400）；
    # 判重键升级为 (userId, assetId, itemId, customer)（无 itemId 行口径不变）
    itemId: int | None = None
    # 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，start ≤ end 否则 400；遥感行不填
    serviceStart: str | None = None
    serviceEnd: str | None = None
    # 折扣率：**已下线（ADR-039），后端忽略**——字段保留以兼容旧客户端（不 422、不 400）；
    # 后端不读取、不校验、不落库
    discountRate: float | None = None


class CartPatchInput(BaseModel):
    """PATCH /cart/{id}：修改购物车行级客户（ADR-007）；可选携带 amount（ADR-008）
    与服务期限（ADR-020，PRICING-20261020）。

    amount 语义（ADR-018 §3）：unit/遥感明细行=销售金额（传入即采信并过参考区间校验，
    不传保持原值）；amount 模式行=权威合同金额（整数元，不传保持原值）。
    discountRate：**已下线（ADR-039），后端忽略**——容忍旧客户端传值，不校验、不落库。
    """
    customer: str
    amount: float | None = None
    serviceStart: str | None = None  # YYYY-MM-DD；start ≤ end 否则 400
    serviceEnd: str | None = None
    discountRate: float | None = None  # 已下线（ADR-039），后端忽略


class CartQtyUpdate(BaseModel):
    """PUT /cart/{id} 入参（BUG-20 / FIX-20261022：裸 dict → Pydantic）。

    语义与 CART-PATCH-20261021 一致：`qty` 必传；其余字段**未传 = 保持原值，显式 null = 清空**
    （路由层用 `model_fields_set` 判断）。非法类型（如 `{"qty":"abc"}`）由 Pydantic 422 拦截，
    不再 500 或写脏值。
    """
    qty: int
    amount: float | None = None
    serviceStart: str | None = None
    serviceEnd: str | None = None
    discountRate: float | None = None  # 已下线（ADR-039），后端忽略（容忍旧客户端传值）


class OutboundRevertInput(BaseModel):
    """POST /outbounds/{id}/revert 入参（BUG-20：裸 dict → Pydantic）。reason 选填。"""
    reason: str = ""


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
    requestId（BUG-10 / ADR-033 §1，可选）：前端 `crypto.randomUUID()`，同一次提交重试沿用；
    后端以 `(userId, requestId)` 唯一记录 24h，重复请求返回首次项目（`idempotent: true`）。
    不传 = 退化旧行为（无幂等保护，不做任何校验变更）。
    """
    projectName: str = ""
    customer: str = ""  # 兼容保留，不参与分组（行级 customer 为准）
    rep: str = ""
    businessOwner: str = ""  # 商务负责人（可选，默认空；前端显示 "-"）
    contractAmount: float = Field(default=0, ge=0)  # 元（ADR-006）
    expectedSignDate: str = ""
    remark: str = ""
    deliveryReq: str = ""
    requestId: str | None = None  # 幂等键（可选，建议 UUID；≤64 字符）


class SaleOrderItemInput(BaseModel):
    assetId: int
    qty: int = Field(default=1, ge=0)
    # 包量计价合同金额（ADR-008，元，整数）：amount 模式产品必填（缺失/非整数 400）；unit 模式忽略
    amount: float | None = None
    # 遥感数据明细（ADR-011，可选）：非空时 qty 强制 1（≠1 → 400），
    # amount 后端权威 = 明细 price × 1（忽略前端传值）
    itemId: int | None = None


class SaleOrderInput(BaseModel):
    """产品直接下单（单/多产品）：主体由产品带出，生成进行中销售项目（锁定数量）；交付由人工置"已完成"触发"""
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
