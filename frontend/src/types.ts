/**
 * 全局领域类型与状态定义
 */
import type { IWorkbookData } from '@univerjs/presets'

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
export interface Entity {
  name: string // 公司全称（存储值）
  short: string // 列表页展示简称
}

export const ENTITIES: Entity[] = [
  { name: '蜂云时代科技有限公司', short: '蜂云时代' },
  { name: '四川蜂云星座人工智能科技有限公司', short: '蜂云星座' },
  { name: '蜂云纪元科技(贺州)有限公司', short: '蜂云纪元(贺州)' },
  { name: '安徽天枢智算人工智能科技有限公司', short: '安徽天枢' },
]

/** 全称 → 简称（列表列展示用，未收录的按原值显示） */
export function entityShort(name: string): string {
  return ENTITIES.find((e) => e.name === name)?.short ?? name
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
  soldAmount: number // 累计售卖金额（元）
  soldCount: number // 授权/销售次数（可重复售卖）
  status: AssetStatus // 可售 / 全部出售
  inboundDate: string // 登记时间
  expiryDate: string // 到期时间（长期买断时为空）
  perpetual: boolean // 长期买断（无到期时间）
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
  price: number // 单价（整数元/份）
  // 参考价格区间（ADR-021，RSITEM-RANGE-20261020）：元/份，选填（可单边）；下单折扣区间校验用
  priceMin?: number | null
  priceMax?: number | null
  repeatSale: boolean // 可重复售卖（默认 true，只计次不扣量）
  createdAt: string
  updatedAt: string
}

/** 明细展示名：省 + 市 + 精度m + 月份（如「河北省石家庄市 1.5m 2026-09」） */
export function rsItemName(r: RsItem): string {
  return `${r.province}${r.city || ''} ${r.resolution}m ${r.saleMonth}`
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
  // 合同金额（元，整数；ADR-008 包量定价行权威输入；ADR-018 §3 PRICING-20261020 起 unit/遥感行=折扣金额，可空=原价成交）
  amount?: number
  // 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，购物车行填写、结算透传落 project_items；遥感行不填
  serviceStart?: string | null
  serviceEnd?: string | null
  createdAt: string
  updatedAt: string
}

/** 可售数量：可重复售卖返回 null（表示"重复售卖，不扣减"） */
export function availableQty(a: Asset): number | null {
  if (a.repeatSale) return null
  return Math.max(0, a.quantity - a.lockedQty - a.shippedQty)
}

/** 可售金额 = 可售数量 × 单价。
 * 包量定价（amount 模式，卫星Token）返回 0：其 salePrice 为参考值（元/份，不参与计价，
 * ADR-008/ADR-017），以合同金额（整数元）为权威口径，两者相乘不是真实金额
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

/** 到期时间展示：长期买断 → 长期；有到期时间 → 日期；否则 长期 */
export function expiryText(a: Asset): string {
  if (a.perpetual || !a.expiryDate) return '长期'
  return a.expiryDate
}

/** 是否在 days 天内到期（非长期买断且已设到期时间且未过期） */
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
  createdAt: string
  updatedAt: string
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

/** 交付物模板项（基础设置中按产品类型配置） */
export interface DeliverableTemplateItem {
  id: number
  name: string
  category: DeliverableCategory
  required: boolean // 默认必选交付
  note: string // 适用说明
}

/** 交付物实例项（产品详情中，由模板初始化 + 可维护状态/版本） */
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
 * 派生参考单价（ADR-017，仅包量定价模式展示用）：合同金额 ÷ 数量（元/份），
 * 与后端 `_derived_price` 同口径，无 1e4 换算（2026-10-20：删除「元/万Token」口径）；
 * 不参与任何金额计算。
 * @param unit 产品计量单位，用于「元/{unit}」展示；缺省显示「元/份」
 */
export function derivedUnitPrice(amount: number, qty: number, unit?: string): string {
  if (!amount || !qty) return '-'
  return `${(amount / qty).toFixed(2)} 元/${unit || '份'}`
}

/** 标准金额展示：字段单位即元（ADR-006），直显「¥ + 千分位 + 两位小数」，0/空显示 '-' */
export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v)
}

/** 元单位金额的输入框展示（千分位 + 两位小数，不含 ¥ 前缀，空/非法回退 0.00），与 formatMoney 同为元口径 */
export function formatYuan(v: number | null | undefined): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '0.00'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
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
