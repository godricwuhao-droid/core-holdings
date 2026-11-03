/**
 * 全局领域类型与状态定义
 */
import type { IWorkbookData } from '@univerjs/presets'
// ENTITIES-20261022 / ADR-035：主体清单由硬编码常量改为 bootstrap 镜像（db.entities）；
// 仅 entityShort 在调用时读取 db，模块求值期不触碰，与 api/index.ts 的循环导入安全
import { db } from '@/api'

// ============================================================
// 板块
// ============================================================
export type Board = 'embodied' | 'satellite' | 'software' | 'hardware' | 'compute'

export interface BoardMeta {
  key: Board
  label: string
  wip?: boolean
}

export const BOARDS: BoardMeta[] = [
  { key: 'embodied', label: '具身智能' },
  { key: 'satellite', label: '卫星服务' },
  { key: 'software', label: '软件产品' },
  { key: 'hardware', label: '硬件产品' },
  { key: 'compute', label: '算力服务', wip: true },
]

export const boardLabel = (b: Board) => BOARDS.find((x) => x.key === b)?.label ?? b

/**
 * 产品类型 → 标签色板 class（列表类型列区分颜色，覆盖 light/plain 两种效果）
 * 同一板块内保证互异：具身智能 蓝/绿/灰，卫星 橙/紫，软件 蓝，硬件 绿，算力 橙
 */
export const TYPE_TAG_CLASS: Record<string, string> = {
  机器人: 'tag-blue',
  数采设备: 'tag-green',
  平台软件: 'tag-gray',
  卫星Token: 'tag-orange',
  卫星数据: 'tag-purple',
  遥感数据: 'tag-blue',
  软件: 'tag-blue',
  硬件集群: 'tag-green',
  算力服务器: 'tag-orange',
}

// ============================================================
// 公司所属主体（均为我司主体）
// ============================================================
/** 公司主体（FORMS-20261022 / ADR-036 起由「资产主体」改名；ENTITIES-20261022 / ADR-035：entities 表，bootstrap 全量下发；原硬编码 ENTITIES 常量已删除） */
export interface Entity {
  id: number
  name: string // 公司全称（存储值，assets.subject 存此值）
  short: string // 展示简称
  createdAt: string
  updatedAt: string
}

/** 全称 → 简称（列表列展示用；读 db.entities，查不到回退原值——兼容未刷新快照/存量游离值） */
export function entityShort(name: string): string {
  return db.entities.find((e) => e.name === name)?.short ?? name
}

// ============================================================
// 产品
// ============================================================
/** 产品状态：仅两种，由数量自动判定（锁定/在售关联在销售项目中体现，不占用状态） */
export type AssetStatus = 'in_stock' | 'all_sold'

export interface Asset {
  id: number
  code: string // 产品编号（自动生成，不可编辑）
  name: string
  board: Board
  type: string // 产品类型
  subject: string // 所在主体
  unit: string // 计量单位
  quantity: number // 产品总数
  lockedQty: number // 锁定数量（被进行中的销售项目占用）
  shippedQty: number // 售卖数量（已交付）
  repeatSale: boolean // 可重复售卖
  pricingMode?: 'unit' | 'amount' // 计价模式（ADR-008）：unit=单价×数量（默认）；amount=包量金额权威（卫星 Token），salePrice 仅参考
  salePrice: number // 单价（元/单位）；amount 模式下为参考单价（元/份，ADR-017），不参与计价
  // 参考价格区间（ADR-018，PRICING-20261020）：元/{unit}，选填（可单边），下单折扣区间校验用
  priceMin?: number | null
  priceMax?: number | null
  // 可售明细数（UI-OPT-20261022，ADR-038 修订口径）：**仅容器（type='遥感数据'）有值**，后端派生
  // = 明细总数 − 被「非 terminated 销售记录」占用**且 repeatSale=false** 的明细数
  // （repeatSale=true 的明细售出后仍可售，不参与扣减；锁定/已交付都算占用）；
  // 语义与普通产品的 quantity−lockedQty−shippedQty 对齐，只是容器的「数量」是明细条数。
  // 非容器恒 null；旧后端/旧快照不返回该字段 → undefined（消费方回退旧口径）
  availableCount?: number | null
  soldAmount: number // 累计售卖金额（元）
  soldCount: number // 授权/销售次数（可重复售卖）
  status: AssetStatus // 可售 / 全部出售
  inboundDate: string // 登记时间
  expiryDate: string // 到期时间（产品有效期勾选时为空）
  perpetual: boolean // 产品有效期（FORMS-20261022 / ADR-036 起由「长期买断」改名；无到期时间）
  spec: string // 规格/说明
  saleDetail?: IWorkbookData // 售卖内容明细（Excel 快照，登记时录入；结构自由、可含行列合并）
  contractFile?: string // 产品清单（uploads 目录散列文件名，抽屉内可在线预览；展示原始名走 fileDisplayName）
  featureDoc?: string // 功能清单附件（uploads 目录散列文件名；"" = 未上传，与 contractFile 同模式）
  remark: string
  updatedAt: string
}

/** 遥感数据可售明细（ADR-011，Supersedes ADR-010）：父产品（type='遥感数据'）下的可售卖子项，维度 省（可含市）× 精度 × 月份 */
export interface RsItem {
  id: number
  assetId: number // 父产品 id
  province: string // 省/自治区/直辖市，必填
  city: string // 市，可空（默认 ""）
  resolution: number // 精度（米），如 1.5
  saleMonth: string // YYYY-MM
  price: number // 单价（元/份，最多 6 位小数，ADR-048）
  // 参考价格区间（ADR-021，RSITEM-RANGE-20261020）：元/份，选填（可单边）；下单折扣区间校验用
  priceMin?: number | null
  priceMax?: number | null
  // 可重复售卖（ADR-038 起默认 false = 单次售卖，售出即占用可售数；true = 只计次不扣量）
  repeatSale: boolean
  // 可售状态（RS-STATUS-20261022 / ADR-038 Decision 3）：`in_stock`=可售 / `all_sold`=已售罄，
  // **与 assets.status 同枚举**（AssetStatus），后端按真值维护（repeatSale=true 或未被非 terminated
  // 合同引用 → in_stock），前端只读、不提交（RsItemInput 不含该字段）。
  // 原派生字段 `occupied` 已由后端删除，「这条明细还能不能卖」只认本字段。
  status: AssetStatus
  createdAt: string
  updatedAt: string
  // 已售次数（FIX-20261022-FOLLOWUP）：后端派生值（该明细被 delivered 合同明细计数）。
  // 可选——bootstrap.rsItems 同批补齐该字段，旧后端/旧快照不返回时为 undefined（消费方需降级）
  soldCount?: number
}

/** 明细展示名：省 + 市 + 精度m + 月份（如「河北省石家庄市 1.5m 2026-09」） */
export function rsItemName(r: RsItem): string {
  return `${r.province}${r.city || ''} ${r.resolution}m ${r.saleMonth}`
}

/** 可售明细 + 已售次数（PAGE-20261021）：GET /assets/{id}/rs-items 分页接口的派生行类型，
 * soldCount 由后端按 delivered 合同明细 itemId 计数（替代前端遍历 contracts 派生）；
 * RS-STATUS-20261022：status 由 RsItem 继承（与 assets.status 同枚举），本接口无需重复声明 */
export interface RsItemWithSold extends RsItem {
  soldCount: number
}

/** 明细状态 → 展示文案 + tag 类型（RS-STATUS-20261022）：
 * 与 `ASSET_STOCK_STATE` 同口径（success=绿 / info=灰），**不新增色值**（§6 硬约束） */
export const RS_ITEM_STATUS: Record<AssetStatus, { label: string; tag: 'success' | 'info' }> = {
  in_stock: { label: '可售', tag: 'success' },
  all_sold: { label: '已售罄', tag: 'info' },
}

/**
 * 明细是否「已售罄且不可再选」（RS-STATUS-20261022）：
 * `status === 'all_sold' && !repeatSale` → 详情表展示灰「已售罄」、选择器置灰禁选。
 * `repeatSale === true` 的明细即使已售出也照常可选（后端放行，只计次不扣量）；
 * 缺失 status（旧后端/旧快照）按可售处理，不误伤。
 */
export function isRsItemSoldOut(r: Pick<RsItem, 'status' | 'repeatSale'>): boolean {
  return r.status === 'all_sold' && !r.repeatSale
}

/** 是否包量定价模式（ADR-008）：amount 模式下合同金额为权威输入，salePrice 仅参考 */
export function isAmountMode(a: Pick<Asset, 'pricingMode'>): boolean {
  return a.pricingMode === 'amount'
}

/** 文件元数据（bootstrap files 全量）：storedName=散列名（URL/产品字段用），name=原始文件名（展示用） */
export interface FileMeta {
  storedName: string
  name: string
  size: number
  uploadedBy: string
  createdAt: string
}

/** 购物车项（预留 userId 维度，为后续账号权限管控做准备；当前默认 admin） */
export interface CartItem {
  id: number
  userId: string
  assetId: number
  itemId?: number // 遥感数据明细 id（ADR-011，挂 rs_items；含 itemId 行数量恒 1）
  customer?: string // 行级客户（ADR-007）：结算时按 customer 分组拆合同；"" = 未填写
  qty: number
  // 合同金额（元，整数；ADR-008 包量定价行权威输入；ADR-018 §3 PRICING-20261020 起 unit/遥感行=行内成交金额，可空=原价成交）
  amount?: number
  // 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，购物车行填写、结算透传落 project_items；遥感行不填
  serviceStart?: string | null
  serviceEnd?: string | null
  // 折算率：已下线（ADR-039），仅历史数据存在——购物车已无录入入口，后端也不再读取/校验/写入该字段；
  // 保留字段仅为存量行（含历史快照）类型兼容，前端不展示、不提交
  discountRate?: number | null
  createdAt: string
  updatedAt: string
}

/** 是否遥感数据容器（父产品 + 可售明细两层，ADR-011） */
export function isRemoteContainer(a: Pick<Asset, 'type'>): boolean {
  return a.type === '遥感数据'
}

/**
 * 可售数量：可重复售卖返回 null（表示"重复售卖，不扣减"）。
 *
 * UI-OPT-20261022：容器（type='遥感数据'）的「数量」是**可售明细条数**，父产品 quantity 恒 1，
 * 故优先读后端派生 `availableCount`（明细总数 − 被非 terminated 销售记录占用的明细数）。
 *  - 有值（number）→ 直接用（后端权威，viewer 视角同样正确，不再前端本地汇总）；
 *  - undefined / null（旧后端、旧快照、非容器）→ 回退旧口径 quantity−lockedQty−shippedQty（兼容）。
 * repeatSale / 非容器逻辑与改造前完全一致。列表「可售数量」列、抽屉「可售 N 份」、
 * assetStockState / noSellableStock 状态派生均依赖本函数，不得各自另算。
 */
export function availableQty(a: Asset): number | null {
  if (a.repeatSale) return null
  if (isRemoteContainer(a) && typeof a.availableCount === 'number') {
    return Math.max(0, a.availableCount)
  }
  return Math.max(0, a.quantity - a.lockedQty - a.shippedQty)
}

/** 可售金额 = 可售数量 × 单价。
 * 包量定价（amount 模式，卫星Token）返回 0：其 salePrice 为参考值（元/份，不参与计价，
 * ADR-008/ADR-017），以合同金额（元，最多 6 位小数）为权威口径，两者相乘不是真实金额
 * （曾导致看板/板块「可售金额」虚高）。已体现在项目/合同的 contractAmount 统计中。 */
export function availableValue(a: Asset): number {
  if (isAmountMode(a)) return 0
  const q = availableQty(a)
  return q === null ? 0 : q * a.salePrice
}

/** 产品数量状态（两态，列表/详情/算力板块共用）：可售（绿）/ 已售罄（红）。可重复售卖归入"可售" */
export type AssetStockState = 'in_stock' | 'no_stock'

/** 两态判定：无可用数量（售罄 / 全锁定 / 无数量）→ 已售罄；否则 → 可售（可重复售卖自然归入可售） */
export function assetStockState(a: Asset): AssetStockState {
  return noSellableStock(a) ? 'no_stock' : 'in_stock'
}

export const ASSET_STOCK_STATE: Record<AssetStockState, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  in_stock: { label: '可售', tag: 'success' },
  no_stock: { label: '已售罄', tag: 'danger' },
}

/**
 * 参考价格区间展示文本（ADR-018，PRICING-20261020）：
 * 双边 → 「{min}~{max}」；单边 → 仅展示已设边界；未设 → ''（展示端据此决定是否追加区间后缀）
 */
export function priceRangeText(a: Pick<Asset, 'priceMin' | 'priceMax'>): string {
  const min = a.priceMin
  const max = a.priceMax
  if (min == null && max == null) return ''
  if (min != null && max != null) return `${min}~${max}`
  return min != null ? `≥${min}` : `≤${max}`
}

/** 是否无可用数量（非可重复售卖且可售数量≤0）：用于禁止编辑 / 登记销售 */
export function noSellableStock(a: Asset): boolean {
  return !a.repeatSale && (availableQty(a) ?? 0) <= 0
}

/** 到期时间展示：产品有效期（原「长期买断」）→ 长期；有到期时间 → 日期；否则 长期 */
export function expiryText(a: Asset): string {
  if (a.perpetual || !a.expiryDate) return '长期'
  return a.expiryDate
}

/** 是否在 days 天内到期（非产品有效期（原「长期买断」）且已设到期时间且未过期） */
export function expiringSoon(a: Asset, days: number, now = Date.now()): boolean {
  if (a.perpetual || !a.expiryDate) return false
  const d = new Date(a.expiryDate).getTime()
  if (Number.isNaN(d) || d < now) return false
  return d <= now + days * 86400000
}

// ============================================================
// 销售项目
// ============================================================
// ADR-019（PRICING-20261020）：新增 delivering（交付中）——合同录入签订时间后 active→delivering，
// 交付动作（扣量/流水/交付记录）在 delivering→delivered 时发生
export type ProjectStatus =
  | 'pending'
  | 'active'
  | 'delivering'
  | 'delivered'
  | 'terminated'

export const PROJECT_STATUS: Record<ProjectStatus, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  pending: { label: '待审核', tag: 'warning' },
  active: { label: '进行中', tag: 'primary' },
  delivering: { label: '交付中', tag: 'warning' }, // 橙（#A86514，与全局 --warning-color 同色板）
  delivered: { label: '已完成', tag: 'success' },
  terminated: { label: '已终止', tag: 'danger' },
}

/** 状态流转路径（进行中 → 交付中 → 已完成；各阶段均可终止；已终止为终点，ADR-019） */
export const PROJECT_FLOW: ProjectStatus[] = [
  'active',
  'delivering',
  'delivered',
]

// ============================================================
// ADR-041 / FLOW-20261022：终止态细分（纯展示层）
// ============================================================
/** ADR-041：终止态三种成因——仅展示层概念，后端 status 一律 'terminated'，切勿当成状态机状态 */
export type ProjectOutcome = 'revoked' | 'rejected' | 'terminated'

export const PROJECT_OUTCOME: Record<ProjectOutcome, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  revoked: { label: '已撤销', tag: 'info' },
  rejected: { label: '已驳回', tag: 'danger' },
  terminated: { label: '已终止', tag: 'danger' },
}

/**
 * 终止成因判定（ADR-041 §1）：先看日志 action（精确），无日志的存量单回退合同 remark 前缀。
 * ⚠️ 只用于展示；筛选/按钮可用性一律继续用真实 status。
 * 降级（FLOW-20261022 后端 projectId 并行期）：`l.projectId` 全为 undefined 时此处过滤结果为空，
 * 自动走 remark 兜底分支，仍能区分撤销/驳回（故不得使用 `l.projectId!` 断言）。
 */
export function projectOutcome(
  p: { id: number; status: ProjectStatus },
  logs: OpLog[],
  contracts: { projectId: number; remark?: string }[],
): { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' } {
  if (p.status !== 'terminated') return PROJECT_STATUS[p.status]
  const mine = logs.filter((l) => l.projectId === p.id)
  if (mine.some((l) => l.action === '撤销订单')) return PROJECT_OUTCOME.revoked
  if (mine.some((l) => l.action === '驳回订单')) return PROJECT_OUTCOME.rejected
  const remarks = contracts.filter((c) => c.projectId === p.id).map((c) => c.remark || '')
  if (remarks.some((r) => r.includes('撤销：'))) return PROJECT_OUTCOME.revoked
  if (remarks.some((r) => r.includes('驳回：'))) return PROJECT_OUTCOME.rejected
  return PROJECT_OUTCOME.terminated
}

/**
 * 从日志 detail 或合同 remark 提取撤销/驳回原因（ADR-041 §2），提不到返回 ''。
 * ⚠️ 取数范围收紧到「成因事件」日志（action = 撤销订单 / 驳回订单）：ADR-041 §2 明确原因来源是
 * 「撤销事件 / 驳回事件」。实测（2026-10-22 库内 project 1）撤销时各合同先落「销售记录状态变更」
 * 日志，detail 为「…终止：释放锁定…，原因：撤销：撤销测试」——若对项目全部日志 join 后匹配，
 * 会先命中这条，展示成「撤销：撤销测试」（前缀重复）；只取成因日志后得到「撤销测试」。
 */
export function outcomeReason(
  p: { id: number; status: ProjectStatus },
  logs: OpLog[],
  contracts: { projectId: number; remark?: string }[],
): string {
  const mine = logs
    .filter((l) => l.projectId === p.id)
    .filter((l) => l.action === '撤销订单' || l.action === '驳回订单')
  const logText = mine.map((l) => l.detail || '').join('\n')
  // 撤销：「…原因：撤销测试；原商务负责人…」；驳回：「…订单已驳回：的（锁定已释放）」
  const mRevoke = logText.match(/原因：([^；\n]+)/)
  if (mRevoke) return mRevoke[1].trim()
  const mReject = logText.match(/订单已驳回：([^（\n]+)/)
  if (mReject) return mReject[1].trim()
  // 兜底：合同 remark 前缀（存量单无日志时）
  for (const c of contracts.filter((x) => x.projectId === p.id)) {
    const r = (c.remark || '')
    const m = r.match(/(?:撤销|驳回)：(.+)$/)
    if (m) return m[1].trim()
  }
  return ''
}

export type ItemStatus = 'pending_asset' | 'pending_amount' | 'locked' | 'confirmed' | 'shipped' | 'released'

export const ITEM_STATUS: Record<ItemStatus, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  pending_asset: { label: '待关联产品', tag: 'info' },
  pending_amount: { label: '待确认金额', tag: 'warning' },
  locked: { label: '已锁定资源', tag: 'primary' },
  confirmed: { label: '已确认销售', tag: 'success' },
  shipped: { label: '已完成交付', tag: 'success' },
  released: { label: '已取消释放', tag: 'danger' },
}

export interface ProjectItem {
  id: number
  assetId: number | null
  contractId?: number | null // 所属合同（ADR-007）；存量明细为 null
  itemId?: number // 遥感数据明细 id（ADR-011，挂 rs_items；空 = 非明细行）
  qty: number
  unit: string
  price: number // 最终单价（折扣/终审后；ADR-018）
  amount: number // 最终金额（折扣/终审后；合同总额 = Σ 最终行金额）
  // 原价快照（ADR-018 §2，PRICING-20261020）：下单时挂牌价快照，永不覆盖；存量订单为空（展示端按 price/amount 兜底）
  origPrice?: number | null
  origAmount?: number | null
  // 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，下单人填、商务审核可改
  serviceStart?: string | null
  serviceEnd?: string | null
  // 折算率快照：已下线（ADR-039），仅历史数据存在——本批次起下单不再写入（新单恒为 null），
  // 审核页也不再展示该列；保留字段仅为存量订单类型兼容，前端不读不写
  discountRate?: number | null
  status: ItemStatus
  locked?: boolean // 明细下单时刻是否真实加锁（存量数据 false）
  deliveryReq: string // 交付要求
  lockedDate: string
  confirmedDate: string
  shippedDate: string
}

export interface Project {
  id: number
  code: string // 项目编号 SP-XXXX
  name: string
  customer: string // 多合同时为空字符串（前端显示「N 位客户」）
  industry: string
  rep: string // 生态人员（原销售人员）
  creator?: string // 实际下单账号（2026-10-16 起；生态可见性口径 creator==自己，存量为空回退 rep）
  businessOwner?: string // 商务负责人（存量项目为空，展示 '-'）
  subject: string
  status: ProjectStatus // 派生字段：由名下合同状态推导（ADR-007），前端不可手动变更
  expectedAmount: number // 预计销售金额（=Σ合同金额，派生）
  quoteAmount?: number // 报价金额（2026-10-19 废弃，仅存量数据）
  contractAmount: number // 合同金额（=Σ合同金额，派生兼容口径）
  paidAmount?: number // 已回款金额（2026-10-19 废弃，仅存量数据）
  expectedSignDate: string
  lastFollowDate: string
  remark: string
  items: ProjectItem[]
  contractCount?: number // 合同数量（ADR-007，派生；存量项目可能缺失）
  // ADR-028 §5（2026-10-21）：明细是否已回填/已产生撤销留痕（后端 projects.cartRefilled，bootstrap 同步）。
  // `status === 'terminated' && cartRefilled` = 撤销导致的终止 → 详情页展示「已撤销，历史记录已保留」提示条，
  // 同时后端 DELETE /projects 对该组合 403（留痕不可删）。被驳回未回填的终态项目为 false
  cartRefilled?: boolean
  createdAt: string
  updatedAt: string
}

// ============================================================
// ADR-042 / REFILL-20261022：「重新提交」回填购物车响应
// ============================================================
/**
 * 回填方式（ADR-042 §2）：
 * - `merge`（默认）：保留购物车现有商品，同产品同客户的行用本次明细**覆盖**（替换，不累加）；
 * - `replace`：先清空下单人购物车再回填（不可撤销）。
 */
export type RefillMode = 'merge' | 'replace'

/**
 * 逐行失败代码（REFILL-20261022-F3 / 后端 B3 新增 `code`）。
 * 前端用它选「状态胶囊文案 + 颜色」并决定是否展示「库存/锁定/出库」数值，
 * 不再靠解析中文 `reason`（解析仅在 `code` 缺失时作为降级）。
 * - `insufficient`：可售数量不足（库存 − 锁定 − 出库 < 本次需）
 * - `no_asset`：产品不存在（assetId 在库存里查不到）
 * - `other`：其它原因（价格区间不符、数据异常等）
 */
export type RefillRowCode = 'ok' | 'insufficient' | 'no_asset' | 'other'

/** 逐行回填结果（ADR-042 §3/§4）：reason 为「可售不足/区间不符」等可读中文原因（含库存数值） */
export interface RefillRowResult {
  assetName: string
  qty: number
  ok: boolean
  reason: string
  // ---- REFILL-20261022-F3：以下 3 字段由后端 B3 加性提供，旧后端缺失时必须降级（不得非空断言）----
  /** 产品 id —— 前端据此从 `db.assets` 直读库存，避免解析中文 reason */
  assetId?: number | null
  /** 失败代码（展示用）；缺失 → 按 reason 关键字猜（仅降级路径） */
  code?: RefillRowCode
  /** 本次需要的数量；缺失 → 回退 `qty` */
  need?: number
}

/** 回填目标账号 = 下单人（ADR-042 §5 归属提示用） */
export interface RefillOwner {
  id: number
  username: string
  name: string
}

/**
 * 重新提交回填购物车响应（ADR-027 旧字段全保留 + ADR-042 加性字段）。
 *
 * ⚠️ 降级约定（REFILL-20261022 / 后端并行未热载）：`owner` / `rows` / `mode` / `forced` / `cleared`
 * 一律 **optional**——旧后端不返回时必须按「本人 + 无逐行明细」处理，不得非空断言。
 */
export interface RefillResult {
  ok: boolean
  alreadyRefilled: boolean
  restored: number
  amountFallback: number
  skipped: number
  skippedReasons: string[]
  /** 本次实际生效的回填方式（旧后端缺失 → 视为 merge） */
  mode?: RefillMode
  /** replace 跳过幂等短路时为 true（旧后端缺失） */
  forced?: boolean
  /** replace 清掉的购物车行数（旧后端缺失） */
  cleared?: number
  /** 回填目标（下单人）；缺失 → 跳过归属判断，按本人处理 */
  owner?: RefillOwner
  /** 逐行结果；缺失 → 回退 `skippedReasons` 展示 */
  rows?: RefillRowResult[]
}

// ============================================================
// 合同（ADR-007：项目下按客户拆分的合同，数量联动最小单位）
// ============================================================
export interface ContractItem {
  id: number
  assetId: number | null
  contractId: number | null // 所属合同；存量明细为 null
  itemId?: number // 遥感数据明细 id（ADR-011，挂 rs_items；空 = 非明细行）
  qty: number
  unit: string
  price: number
  amount: number
  // 原价快照 / 服务期限（ADR-018/ADR-020，PRICING-20261020，与 ProjectItem 同构）
  origPrice?: number | null
  origAmount?: number | null
  serviceStart?: string | null
  serviceEnd?: string | null
  status: ItemStatus
  locked?: boolean // 下单时刻是否真实加锁
  deliveryReq: string
  lockedDate: string
  confirmedDate: string
  shippedDate: string
}

export interface Contract {
  id: number
  code: string // 合同编号 HT-XXXX
  projectId: number
  customer: string // 合同客户（2026-10-20 ADR-013：「合同内同一产品主体」限制已移除）
  subject: string // 产品主体（由明细带出）
  contractAmount: number // 合同金额（元）
  // pending / active / delivering / delivered / terminated（与项目状态同构；ADR-012 pending=待审核；
  // ADR-019 PRICING-20261020 新增 delivering=交付中）
  status: ProjectStatus
  // 时间节点（ADR-019，PRICING-20261020）：YYYY-MM-DD；存量合同为 null
  signedDate?: string | null // 合同签订时间（商务填，录入即 active→delivering，不可清空）
  scheduledDeliveryDate?: string | null // 预计交付时间（仅 admin 填，仅 delivering 可录/改/清空）
  remark: string
  items: ContractItem[]
  createdAt: string
  updatedAt: string
}

// ============================================================
// 交付记录
// ============================================================
export type OutboundType = 'physical' | 'data_auth' | 'software_auth' | 'service'

export const OUTBOUND_TYPES: Record<OutboundType, string> = {
  physical: '实物发货',
  data_auth: '数据授权',
  software_auth: '软件授权',
  service: '服务开通',
}

/** 板块默认交付类型 */
export function defaultOutboundType(board: Board): OutboundType {
  if (board === 'satellite') return 'data_auth'
  if (board === 'software') return 'software_auth'
  if (board === 'compute') return 'service'
  return 'physical'
}

/** 交付性质：new=新交付（扣减当前数量）；history=历史补录（仅登记台账，不扣减数量） */
export type OutboundMode = 'new' | 'history'

export interface Outbound {
  id: number
  code: string // 交付单号 CK-XXXX
  projectId: number | null
  contractId?: number | null // 关联合同（ADR-007）：合同交付自动交付时非空；存量/手工补录为 null
  projectItemId?: number | null // 关联合同明细（2026-10-20 问题7）：合同交付指向 ProjectItem.id；手动补录为 null（界面不展示，仅类型同步）
  projectName: string
  customer: string
  assetId: number
  assetName: string
  qty: number
  unit: string
  amount: number
  type: OutboundType
  mode: OutboundMode
  date: string
  operator: string
  status: 'done' | 'reverted'
  remark: string
}

// ============================================================
// 流水 / 操作日志
// ============================================================
export type FlowType = 'purchase_in' | 'project_lock' | 'sale_out' | 'cancel_release' | 'manual_adjust'

export const FLOW_TYPES: Record<FlowType, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  purchase_in: { label: '登记', tag: 'success' },
  project_lock: { label: '项目锁定', tag: 'primary' },
  sale_out: { label: '销售交付', tag: 'warning' },
  cancel_release: { label: '取消释放', tag: 'info' },
  manual_adjust: { label: '手工调整', tag: 'danger' },
}

export interface AssetFlow {
  id: number
  assetId: number
  type: FlowType
  qty: number
  unit: string
  amount: number
  date: string
  ref: string // 关联单号/项目
  note: string
  operator?: string // 操作账号（存量流水为空显示 -；"system" = 初始化登记，显示「系统」）
}

export interface OpLog {
  id: number
  target: 'asset' | 'project' | 'outbound' | 'setting'
  targetName: string
  /** 目标为产品时的产品 ID（后端 logs[] 回传，用于按 ID 精确过滤、避免重名串台） */
  assetId?: number
  /** ADR-041（FLOW-20261022）：项目/交付单日志的结构化外键，按 id 精确过滤（对齐 assetId 做法） */
  projectId?: number | null
  action: string // 新增/编辑/状态变更/删除/交付...
  detail: string
  operator: string
  time: string
  changes?: string // 字段级变更明细（仅产品「编辑」日志有；"" = 无变更不展示）
}

// ============================================================
// 基础资料
// ============================================================
export interface BaseRecord {
  id: number
  name: string
  contact: string
  phone: string
  remark: string
}

export interface CategoryUnit {
  board: Board
  type: string
  unit: string
  note: string
}

// ============================================================
// 交付物（按产品类型可配置的标准交付包）
// ============================================================
export type DeliverableCategory = 'install' | 'license' | 'feature' | 'accept'

export const DELIVERABLE_CATEGORIES: Record<
  DeliverableCategory,
  { label: string; icon: 'blue' | 'green' | 'purple' | 'neutral' }
> = {
  install: { label: '安装部署', icon: 'blue' },
  license: { label: '授权凭证', icon: 'green' },
  feature: { label: '功能资料', icon: 'purple' },
  accept: { label: '验收材料', icon: 'neutral' },
}

/** 交付物实例项（产品详情中手动维护；ADR-024：模板已下线，每项可挂单文件附件） */
export interface AssetDeliverable {
  id: number
  name: string
  category: DeliverableCategory
  required: boolean
  note: string
  version: string
  meta: string // 次要信息：格式/大小/授权范围等
  status: 'ready' | 'todo' // 已就绪 / 待完善
  updatedAt: string
  file?: string | null // 附件（upload 返回的散列文件名；空/NULL = 无附件，ADR-024）
  /** 外部链接（ADR-044；仅 http/https，'' = 未填）。可选：旧后端未热载该字段时为 undefined → 前端降级不渲染 */
  url?: string
}

/** ADR-044：交付物外链校验——仅 http/https（渲染为可点击 <a>，伪协议 = XSS 入口）。
 *  返回 '' 表示合法，否则返回错误文案。与后端 `_normalize_deliverable_url` 同规则。 */
export function checkDeliverableUrl(raw: string): string {
  const u = (raw ?? '').trim()
  if (!u) return '' // 空 = 不填，合法
  if (!/^https?:\/\//i.test(u)) return '链接地址必须以 http:// 或 https:// 开头'
  if (u.length > 512) return '链接地址过长（最多 512 字符）'
  return ''
}

export const DELIVERABLE_STATUS: Record<
  AssetDeliverable['status'],
  { label: string; tag: 'success' | 'warning' }
> = {
  ready: { label: '已就绪', tag: 'success' },
  todo: { label: '待完善', tag: 'warning' },
}

/** 功能清单（结构化模块树，交付物详情页展示） */
export interface FeatureCapability {
  name: string // 能力名称
  desc: string // 功能说明
  value: string // 核心价值 / 技术体现
}

export interface FeatureSubModule {
  name: string // 二级模块
  capabilities: FeatureCapability[]
}

export interface FeatureModule {
  name: string // 一级模块
  subs: FeatureSubModule[]
}

// ============================================================
// 状态标签安全索引（表格 slot 中 row 为 any 类型）
// ============================================================
export type TagInfo = { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }

export function tagInfo<T extends string>(map: Record<T, TagInfo>, key: string): TagInfo {
  return (map as Record<string, TagInfo>)[key] ?? { label: key, tag: 'info' }
}

// ============================================================
// 格式化
// ============================================================
export function formatWan(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

/**
 * Token 数量展示（ADR-008）：库内仍存原始 Token 数，仅展示层换算——
 * 300000000 → "3 亿"，137000000 → "13700 万"，< 1e4 → 原数 + "个"
 */
export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '-'
  if (n >= 1e8) {
    const v = n / 1e8
    return `${Number.isInteger(v) ? v : v.toFixed(2).replace(/\.?0+$/, '')} 亿`
  }
  if (n >= 1e4) {
    const v = n / 1e4
    return `${Number.isInteger(v) ? v : v.toFixed(2).replace(/\.?0+$/, '')} 万`
  }
  return `${n} 个`
}

/** 数量展示口径（ADR-008）：包量定价（Token）产品用 formatTokens，其余用 formatWan */
export function formatAssetQty(a: Pick<Asset, 'pricingMode'>, n: number | null | undefined): string {
  return isAmountMode(a) ? formatTokens(n) : formatWan(n)
}

/**
 * 金额精度（ADR-048，2026-10-29）：最多 6 位小数（1e-6 元，微元级）。
 * 取代 ADR-008/ADR-022 的「整数元」口径；展示规则为「最少 2 位、最多 6 位、尾随 0 截到 2 位」。
 */
export const AMOUNT_MAX_FRAC = 6

/** 金额按 1e-6 规整（消除 JS 浮点尾巴，如 0.1+0.2；仅用于前端合计，不改变用户输入值） */
export function roundAmount(v: number): number {
  const f = 10 ** AMOUNT_MAX_FRAC
  return Math.round(v * f) / f
}

/**
 * 金额格式化核心（ADR-048）：千分位整数 + 小数「最少 2 位、最多 6 位，尾随 0 截到 2 位」。
 * 例：12.5 → 12.50；12.3400 → 12.34；12.345678 → 12.345678；1000 → 1,000.00。
 * 不做四舍五入隐藏（原 Intl `maximumFractionDigits: 2` 会把 12.3456 显示成 12.35，与落库值不符）。
 * @param withSymbol 是否带 ¥ 前缀（formatMoney 带、输入框/纯数值场景不带）
 */
export function formatAmountValue(v: number, withSymbol = true): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '-'
  const sign = n < 0 ? '-' : ''
  const fixed = Math.abs(n).toFixed(AMOUNT_MAX_FRAC)
  const dot = fixed.indexOf('.')
  const intPart = dot < 0 ? fixed : fixed.slice(0, dot)
  const fracRaw = dot < 0 ? '' : fixed.slice(dot + 1)
  const frac = fracRaw.replace(/0+$/, '').padEnd(2, '0')
  return `${sign}${withSymbol ? '¥' : ''}${intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${frac}`
}

/**
 * 派生参考单价（ADR-017 / ADR-048，仅包量定价模式展示用）：合同金额 ÷ 数量（元/份），
 * 与后端 `_derived_price` 同口径（6 位小数），无 1e4 换算；不参与任何金额计算。
 * @param unit 产品计量单位，用于「元/{unit}」展示；缺省显示「元/份」
 */
export function derivedUnitPrice(amount: number, qty: number, unit?: string): string {
  if (!amount || !qty) return '-'
  return `${formatAmountValue(amount / qty, false)} 元/${unit || '份'}`
}

/**
 * 标准金额展示：字段单位即元（ADR-006），直显「¥ + 千分位 + 最少两位小数」（ADR-048 支持多位），
 * 空/非法显示 '-'。全站金额统一走本函数。
 */
export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return formatAmountValue(Number(v), true)
}

/** el-input-number 金额显示格式（ADR-048）：聚焦时显示用户原文，失焦后走「最少两位/最多六位」 */
export function amountInputFormatter(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === '') return ''
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  return formatAmountValue(n, false)
}

/**
 * el-input-number 金额解析（ADR-048）：剔除千分位等非法字符，多余小数点丢弃，
 * 小数位超过 6 位直接截断（不四舍五入，与后端 6 位校验同口径）。
 */
export function amountInputParser(v: string | number): string {
  const raw = String(v ?? '').replace(/[^\d.-]/g, '')
  const dot = raw.indexOf('.')
  if (dot < 0) return raw
  return raw.slice(0, dot + 1) + raw.slice(dot + 1).replace(/\./g, '').slice(0, AMOUNT_MAX_FRAC)
}

/**
 * 金额文本输入过滤（ADR-048，el-input 场景）：保留数字与单个小数点、剔除千分位等字符，
 * 小数位超过 6 位截断；保留「12.」这类中间态，避免用户输小数点时被吞。
 */
export function sanitizeAmountInput(v: string | number | null | undefined): string {
  const raw = String(v ?? '').replace(/[^\d.]/g, '')
  const dot = raw.indexOf('.')
  if (dot < 0) return raw
  return raw.slice(0, dot + 1) + raw.slice(dot + 1).replace(/\./g, '').slice(0, AMOUNT_MAX_FRAC)
}

/** 金额文本格式校验（ADR-048）：数字 + 最多 6 位小数（允许「12.」「.5」中间态） */
export const AMOUNT_INPUT_RE = new RegExp(`^\\d*(\\.\\d{0,${AMOUNT_MAX_FRAC}})?$`)

/** 金额文本是否合法（ADR-048）：空串 / 超 6 位小数 / 含非法字符 → false */
export function isAmountTextValid(t: string): boolean {
  return AMOUNT_INPUT_RE.test((t ?? '').trim())
}

/** 金额是否满足 6 位小数精度（ADR-048，数值场景）：用于提交前校验，避免浮点尾巴误判 */
export function isAmountPrecisionValid(v: number): boolean {
  if (!Number.isFinite(v)) return false
  return roundAmount(v) === v
}

/**
 * 销售单价展示口径（ADR-025，2026-10-21，仅展示层，不影响任何输入/校验/提交）：
 * amount 模式（卫星 Token）统一换算到百万Token 口径——salePrice（元/个）× 1e6，
 * formatMoney 两位小数 + 千分位，如 `¥33,333.33/百万Token`；
 * unit 模式维持 formatMoney 原展示（调用方原有的 salePrice 判空/`/unit` 后缀逻辑不变）。
 */
export function displayUnitPrice(a: Pick<Asset, 'pricingMode' | 'salePrice'>): string {
  if (isAmountMode(a)) return `${formatMoney(a.salePrice * 1_000_000)}/百万Token`
  return formatMoney(a.salePrice)
}

/** 元单位金额的输入框展示（千分位，不含 ¥ 前缀，空/非法回退 0.00），精度规则同 formatMoney（ADR-048） */
export function formatYuan(v: number | null | undefined): string {
  const n = Number(v)
  if (v === null || v === undefined || !Number.isFinite(n)) return '0.00'
  return formatAmountValue(n, false)
}

/** 将用户输入（含千分位）解析为元单位的数值；非法输入返回 0 */
export function parseYuan(text: string): number {
  const cleaned = (text || '').replace(/[^\d.]/g, '')
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : 0
}

export function formatDate(v: string | null | undefined): string {
  if (!v) return '-'
  return v.length > 10 ? v.slice(0, 10) : v
}

export function formatDateTime(v: string | null | undefined): string {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 16)
}

export function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function nowStr(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 16)
}
