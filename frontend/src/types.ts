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
  { key: 'software', label: '软件库存' },
  { key: 'hardware', label: '硬件库存' },
  { key: 'compute', label: '算力服务', wip: true },
]

export const boardLabel = (b: Board) => BOARDS.find((x) => x.key === b)?.label ?? b

/**
 * 资产类型 → 标签色板 class（列表类型列区分颜色，覆盖 light/plain 两种效果）
 * 同一板块内保证互异：具身智能 蓝/绿/灰，卫星 橙/紫，软件 蓝，硬件 绿，算力 橙
 */
export const TYPE_TAG_CLASS: Record<string, string> = {
  机器人: 'tag-blue',
  数采设备: 'tag-green',
  平台软件: 'tag-gray',
  卫星Token: 'tag-orange',
  卫星数据: 'tag-purple',
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
// 资产
// ============================================================
/** 资产状态：仅两种，由库存自动判定（锁定/在售关联在销售项目中体现，不占用状态） */
export type AssetStatus = 'in_stock' | 'all_sold'

export interface Asset {
  id: number
  code: string // 资产编号（自动生成，不可编辑）
  name: string
  board: Board
  type: string // 资产类型
  subject: string // 所在主体
  unit: string // 计量单位
  quantity: number // 资产总数
  lockedQty: number // 锁定数量（被进行中的销售项目占用）
  shippedQty: number // 售卖数量（已出库）
  repeatSale: boolean // 可重复售卖
  salePrice: number // 单价（万元/单位）
  soldAmount: number // 累计售卖金额（万元）
  soldCount: number // 授权/销售次数（可重复售卖）
  status: AssetStatus // 库存可售 / 全部出售
  inboundDate: string // 入库时间
  expiryDate: string // 到期时间（长期买断时为空）
  perpetual: boolean // 长期买断（无到期时间）
  spec: string // 规格/说明
  saleDetail?: IWorkbookData // 售卖内容明细（Excel 快照，入库时录入；结构自由、可含行列合并）
  contractFile?: string // 产品清单（uploads 目录文件名，抽屉内可在线预览）
  remark: string
  updatedAt: string
}

/** 购物车项（预留 userId 维度，为后续账号权限管控做准备；当前默认 admin） */
export interface CartItem {
  id: number
  userId: string
  assetId: number
  qty: number
  createdAt: string
  updatedAt: string
}

/** 可售数量：可重复售卖返回 null（表示"重复售卖，不扣减"） */
export function availableQty(a: Asset): number | null {
  if (a.repeatSale) return null
  return Math.max(0, a.quantity - a.lockedQty - a.shippedQty)
}

/** 可售金额 = 可售数量 × 单价 */
export function availableValue(a: Asset): number {
  const q = availableQty(a)
  return q === null ? 0 : q * a.salePrice
}

/** 资产库存状态（两态，列表/详情/算力板块共用）：库存可售（绿）/ 暂无库存（红）。可重复售卖归入"库存可售" */
export type AssetStockState = 'in_stock' | 'no_stock'

/** 两态判定：无可售库存（售罄 / 全锁定 / 无库存）→ 暂无库存；否则 → 库存可售（可重复售卖自然归入库存可售） */
export function assetStockState(a: Asset): AssetStockState {
  return noSellableStock(a) ? 'no_stock' : 'in_stock'
}

export const ASSET_STOCK_STATE: Record<AssetStockState, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  in_stock: { label: '库存可售', tag: 'success' },
  no_stock: { label: '暂无库存', tag: 'danger' },
}

/** 是否无可售库存（非可重复售卖且可售数量≤0）：用于禁止编辑 / 登记销售 */
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
export type ProjectStatus =
  | 'active'
  | 'delivered'
  | 'terminated'

export const PROJECT_STATUS: Record<ProjectStatus, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  active: { label: '进行中', tag: 'primary' },
  delivered: { label: '已完成', tag: 'success' },
  terminated: { label: '已终止', tag: 'danger' },
}

/** 状态流转路径（进行中 → 已完成；进行中 / 已完成均可终止；已终止为终点） */
export const PROJECT_FLOW: ProjectStatus[] = [
  'active',
  'delivered',
]

export type ItemStatus = 'pending_asset' | 'pending_amount' | 'locked' | 'confirmed' | 'shipped' | 'released'

export const ITEM_STATUS: Record<ItemStatus, { label: string; tag: 'success' | 'info' | 'warning' | 'danger' | 'primary' }> = {
  pending_asset: { label: '待关联资产', tag: 'info' },
  pending_amount: { label: '待确认金额', tag: 'warning' },
  locked: { label: '已锁定资源', tag: 'primary' },
  confirmed: { label: '已确认销售', tag: 'success' },
  shipped: { label: '已完成出库', tag: 'success' },
  released: { label: '已取消释放', tag: 'danger' },
}

export interface ProjectItem {
  id: number
  assetId: number | null
  qty: number
  unit: string
  price: number
  amount: number
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
  customer: string
  industry: string
  rep: string // 生态人员（原销售人员）
  subject: string
  status: ProjectStatus
  expectedAmount: number // 预计销售金额
  quoteAmount: number // 报价金额
  contractAmount: number // 合同金额
  paidAmount: number // 已回款金额
  expectedSignDate: string
  lastFollowDate: string
  remark: string
  items: ProjectItem[]
  createdAt: string
  updatedAt: string
}

// ============================================================
// 出库记录
// ============================================================
export type OutboundType = 'physical' | 'data_auth' | 'software_auth' | 'service'

export const OUTBOUND_TYPES: Record<OutboundType, string> = {
  physical: '实物发货',
  data_auth: '数据授权',
  software_auth: '软件授权',
  service: '服务开通',
}

/** 板块默认出库类型 */
export function defaultOutboundType(board: Board): OutboundType {
  if (board === 'satellite') return 'data_auth'
  if (board === 'software') return 'software_auth'
  if (board === 'compute') return 'service'
  return 'physical'
}

/** 出库性质：new=新出库（扣减当前库存）；history=历史补录（仅登记台账，不扣减库存） */
export type OutboundMode = 'new' | 'history'

export interface Outbound {
  id: number
  code: string // 出库单号 CK-XXXX
  projectId: number | null
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
  purchase_in: { label: '入库', tag: 'success' },
  project_lock: { label: '项目锁定', tag: 'primary' },
  sale_out: { label: '销售出库', tag: 'warning' },
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
}

export interface OpLog {
  id: number
  target: 'asset' | 'project' | 'outbound' | 'setting'
  targetName: string
  /** 目标为资产时的资产 ID（后端 logs[] 回传，用于按 ID 精确过滤、避免重名串台） */
  assetId?: number
  action: string // 新增/编辑/状态变更/删除/出库...
  detail: string
  operator: string
  time: string
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
// 交付物（按资产类型可配置的标准交付包）
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

/** 交付物模板项（基础设置中按资产类型配置） */
export interface DeliverableTemplateItem {
  id: number
  name: string
  category: DeliverableCategory
  required: boolean // 默认必选交付
  note: string // 适用说明
}

/** 交付物实例项（资产详情中，由模板初始化 + 可维护状态/版本） */
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

/** 标准金额展示：字段单位为万元，换算为元并以「¥ + 千分位 + 两位小数」展示 */
export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return '-'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(v * 10000)
}

/** 元单位金额的标准展示（千分位 + 两位小数，不含 ¥ 前缀），用于合同金额等以元为单位的输入展示 */
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
