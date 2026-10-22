/**
 * API 统一出口（生产环境：后端 FastAPI + SQLite）
 *
 * 视图层通过本文件读写数据：
 *  - 同步读取（getAsset/assetFlows/getDashboard/…）：从响应式镜像 `db` 计算，
 *    `db` 由 `refresh()` 从后端 `/api/bootstrap` 拉取填充；
 *  - 写操作（createAsset/updateProject/…）：调用后端 REST，成功后 `refresh()` 同步镜像。
 *
 * 列表/看板页依赖响应式 `db`，App 挂载时 `refresh()` 一次即可全量渲染；
 * 表单/详情页需同步预填的，在 `onMounted` 内 `await refresh()` 后再读取。
 */
import { reactive } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import type { IWorkbookData } from '@univerjs/presets'
import {
  BOARDS,
  availableQty,
  availableValue,
  expiringSoon,
  noSellableStock,
  type Asset,
  type AssetStatus,
  type AssetFlow,
  type BaseRecord,
  type FileMeta,
  type CartItem,
  type AssetDeliverable,
  type FeatureModule,
  type OpLog,
  type Outbound,
  type OutboundMode,
  type OutboundType,
  type Project,
  type ProjectItem,
  type Contract,
  type Board,
  type Entity,
  type RsItem,
  type RsItemWithSold,
} from '@/types'
import { CATEGORY_UNITS, FEATURE_CATALOGS } from '@/constants'
import {
  clearSession,
  getToken,
  setUser,
  type CurrentUser,
  type Role,
} from '@/auth'

const http = axios.create({ baseURL: '/api', timeout: 20000 })

// 请求拦截器：已登录时统一携带 Bearer token。
// 2026-10-20（ADR-014）：移除前端 viewer 写请求白名单预拦截——权限判定统一由后端守卫
// （require_order / require_editor）兜底，避免前后端两套权限清单再次漂移；
// viewer 越权时后端返回 403（detail 为可读中文提示），由下方响应拦截器统一 toast。
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** Pydantic 422 校验项形态（detail 数组元素） */
interface PydanticIssue {
  loc?: unknown[]
  msg?: string
}

/**
 * 统一解析后端错误体 detail：
 *  - 业务错误：字符串（如「可用数量不足：…」）
 *  - 校验错误：Pydantic 数组（拼成「字段: 说明」可读中文，避免退化成 status 422）
 *  - 兜底：对象（取 msg）或 JSON 串
 */
function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail || null
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === 'object') {
          const issue = item as PydanticIssue
          const loc = Array.isArray(issue.loc)
            ? issue.loc.filter((x) => typeof x === 'string' && x !== 'body').join('.')
            : ''
          const msg = typeof issue.msg === 'string' ? issue.msg : ''
          return loc && msg ? `${loc}: ${msg}` : msg || loc
        }
        return String(item)
      })
      .filter(Boolean)
    return parts.length ? parts.join('；') : null
  }
  if (detail && typeof detail === 'object') {
    const msg = (detail as PydanticIssue).msg
    return typeof msg === 'string' ? msg : JSON.stringify(detail)
  }
  return null
}

/** 403 权限错误（ADR-014，2026-10-20）：响应拦截器已统一 toast 后端 detail，调用方经 showError 跳过重复提示 */
export class PermissionError extends Error {}

// 统一错误：把后端 detail 转成 Error，便于调用方 catch 后展示
//  - 401（token 缺失/过期/账号禁用）：清本地态并整页跳 /login（登录接口自身 401 不跳转，留在登录页提示）
//  - 403（角色/归属不足）：文案统一由后端给出（detail），拦截器统一 toast 并抛 PermissionError
//    （ADR-014：不再出现前端本地「只读账号…」文案；调用方经 showError 跳过重复提示）
http.interceptors.response.use(
  (r) => r,
  (err) => {
    const status = err?.response?.status
    const url: string = err?.config?.url || ''
    if (status === 401 && !url.startsWith('/auth/login')) {
      clearSession()
      if (window.location.pathname !== '/login') {
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirect}`
      }
      return Promise.reject(new Error('未登录或登录已过期'))
    }
    const msg = detailMessage(err?.response?.data?.detail) ?? err?.message ?? '请求失败'
    if (status === 403) {
      ElMessage.error(msg)
      return Promise.reject(new PermissionError(msg))
    }
    return Promise.reject(new Error(msg))
  },
)

/**
 * 统一错误提示（ADR-014，2026-10-20）：
 * 403 权限错误（PermissionError）已由响应拦截器统一 toast（文案 = 后端 detail），此处跳过避免重复弹框；
 * 其余错误展示后端 detail 文案（拦截器已解析进 Error.message），无则回退 fallback。
 */
export function showError(e: unknown, fallback: string): void {
  if (e instanceof PermissionError) return
  ElMessage.error(e instanceof Error ? e.message : fallback)
}

// ============================================================
// 响应式数据镜像（由 refresh() 填充，视图直接响应式读取）
// ============================================================
export const db = reactive({
  assets: [] as Asset[],
  projects: [] as Project[],
  contracts: [] as Contract[],
  outbounds: [] as Outbound[],
  cart: [] as CartItem[],
  suppliers: [] as BaseRecord[],
  customers: [] as BaseRecord[],
  flows: [] as AssetFlow[],
  logs: [] as OpLog[],
  assetDeliverables: {} as Record<number, AssetDeliverable[]>,
  files: [] as FileMeta[],
  rsItems: [] as RsItem[], // 遥感数据可售明细（ADR-011，bootstrap 顶层字段）
  entities: [] as Entity[], // 公司主体（FORMS-20261022 / ADR-036 起由「资产主体」改名；ENTITIES-20261022 / ADR-035，bootstrap 全量下发，无角色过滤）
})

let refreshing: Promise<void> | null = null
/** 请求序号（FIX-20261022 / BUG-24）：仅接受「最新一次」请求的响应，避免旧快照覆盖新快照 */
let refreshSeq = 0
/** ENTITIES-20261022：bootstrap 缺 entities 字段（旧后端并行期）仅提示一次，避免每次刷新都弹 */
let entityListWarned = false

/**
 * 拉取后端全量，填充 db（幂等、防并发）。
 *
 * FIX-20261022 / BUG-24（并发语义修复）：
 *  - **请求序号**：每次请求递增 `refreshSeq`，响应回来时若已不是最新序号则直接丢弃
 *    （原实现下 `refresh(true)` 与在飞请求并发时，先发后到的旧快照会把新快照覆盖回旧值）；
 *  - **`finally` 只清自己持有的 promise**：原实现在任何一次请求结束时无条件 `refreshing = null`，
 *    会把并发中「更新一次请求」的锁提前释放掉（防重入失效）；
 *  - **`force` 不再无条件绕过**：`force` 仍会发起新请求（写操作后必须拿最新快照），
 *    但不再牺牲序号校验，旧响应一律作废。
 */
async function fetchBootstrap(): Promise<void> {
  const seq = ++refreshSeq
  const { data } = await http.get('/bootstrap')
  if (seq !== refreshSeq) return // 已有更新请求在飞/已完成：本响应已过期，丢弃（不写镜像）
  db.assets = data.assets
  db.projects = data.projects
  db.contracts = data.contracts ?? []
  db.outbounds = data.outbounds
  db.cart = data.cart
  db.suppliers = data.suppliers
  db.customers = data.customers
  db.flows = data.flows
  db.logs = data.logs
  db.assetDeliverables = data.assetDeliverables
  db.files = data.files ?? []
  db.rsItems = data.rsItems ?? []
  // ENTITIES-20261022 / ADR-035：旧后端快照缺 entities 字段时回退空数组（下拉/设置页优雅降级），仅提示一次
  db.entities = data.entities ?? []
  if (data.entities === undefined && !entityListWarned) {
    entityListWarned = true
    ElMessage.warning('主体清单未加载，请刷新页面')
  }
}

export function refresh(force = false): Promise<void> {
  if (!force && refreshing) return refreshing
  const p = fetchBootstrap()
  refreshing = p
  return p.finally(() => {
    // 只清自己持有的锁：并发下旧请求结束不得清掉新请求登记的 promise
    if (refreshing === p) refreshing = null
  })
}

/**
 * 写操作后刷新镜像，保持与后端一致。
 *
 * 时序说明：写请求若失败会在调用 `afterWrite()` 之前抛出，由调用方 catch 正常提示「操作失败」；
 * 而刷新阶段失败并不代表写入失败（数据已落库），故此处吞掉刷新异常并给出温和提示，
 * 避免「接口已写成功却弹出操作失败」的误导。仅吞掉刷新失败，写请求本身的失败仍照常上抛。
 */
async function afterWrite() {
  try {
    await refresh(true)
  } catch {
    ElMessage.warning('操作已生效，但数据刷新失败，请手动刷新页面')
  }
}

/**
 * CART-PERF-20261021（2026-10-21）：购物车行级写本地打补丁（契约「CART-PERF-20261021 批次」§1/§2）。
 * PUT/PATCH /cart/{id} 响应由 `{"ok":true}` 改为返回更新后的完整 CartItemOut：
 * 成功后用响应体按 id 替换 db.cart 对应行（按下标替换，**数组引用保持稳定**，仅该行对象变更，
 * 不再重拉 bootstrap——原每次行级 PUT 后全量刷新（97 条 rsItems + 122 条 logs）是输入卡顿主因）。
 * 兼容回退：响应不是含 id 的对象（后端并行未就绪 / 旧格式 `{"ok":true}`）→ 回退 afterWrite()
 * （即 refresh(true) 全量刷新 + 刷新失败温和提示，保旧行为不崩）。
 * 注意：`afterWrite()` 全量刷新仅保留给结构性操作（加购/批量加购/删行/清空/结算，见下方各函数）。
 */
async function patchCartRow(id: number, data: unknown): Promise<void> {
  const row = (data ?? null) as { id?: unknown } | null
  if (row && typeof row === 'object' && typeof row.id === 'number') {
    const idx = db.cart.findIndex((c) => c.id === id)
    if (idx !== -1) {
      db.cart[idx] = row as CartItem
      return
    }
    // 本地镜像中未找到该行（理论边界：镜像未加载/已漂移）→ 全量刷新保证一致
  }
  await afterWrite()
}

// ============================================================
// 输入类型（对齐后端 schema）
// ============================================================
export interface AssetInput {
  name: string
  board: Board
  type: string
  subject: string
  unit: string
  quantity: number
  repeatSale: boolean
  salePrice: number
  // 参考价格区间（ADR-018，PRICING-20261020）：元/份，选填（可单边）；两者都有时后端校验 min ≤ max
  priceMin?: number | null
  priceMax?: number | null
  status: AssetStatus
  inboundDate: string
  expiryDate: string
  perpetual: boolean
  spec: string
  saleDetail?: IWorkbookData
  contractFile?: string
  featureDoc?: string
  remark: string
}

/** 遥感数据可售明细入参（ADR-011，RsItemInput：POST /assets/{id}/rs-items 与 PUT /rs-items/{id} 同构） */
export interface RsItemInput {
  province: string
  city?: string // 选填，默认 ""
  resolution: number // 米
  saleMonth: string // YYYY-MM
  price: number // 整数元/份
  // 参考价格区间（ADR-021，RSITEM-RANGE-20261020）：元/份，选填（可单边）；未设为 null
  priceMin?: number | null
  priceMax?: number | null
  repeatSale?: boolean // 默认 true
}

export interface ProjectItemInput {
  assetId: number | null
  qty: number
  price: number
  amount: number
  deliveryReq: string
  itemId?: number // ADR-011：遥感明细行（重新提交预填时携带；qty 恒 1）
  // 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，start ≤ end 否则 400；遥感行不填
  serviceStart?: string | null
  serviceEnd?: string | null
}

/** 合同入参（ADR-007）：POST /projects 的 contracts[] 元素（2026-10-20 ADR-013：「合同内同一产品主体」限制已移除，允许混合主体明细） */
export interface ContractInput {
  customer: string // 必填：合同客户
  items: ProjectItemInput[]
  contractAmount?: number | null // 元；缺省由后端按明细 price×qty 合计重算
  remark?: string
}

export interface ProjectInput {
  name: string
  customer: string // 派生字段（后端不采信）：多合同传 ""，单合同可传该客户
  industry: string
  rep: string
  businessOwner?: string // 商务负责人（可选，默认空）
  subject: string
  expectedAmount: number
  quoteAmount?: number // 2026-10-19：字段已废弃（不再填写），可选兼容
  contractAmount: number
  paidAmount?: number // 2026-10-19：字段已废弃（不再填写），可选兼容
  expectedSignDate: string
  lastFollowDate: string
  remark: string
  items: ProjectItemInput[] // 兼容路径：不传 contracts 时按单合同自动包装
  contracts?: ContractInput[] // ADR-007：合同结构入参（每客户一个合同）
}

/** 补录交付入参（ADR-015，2026-10-20：移除 operator 字段——后端一直不采信，经办人统一取触发请求的登录账号） */
export interface OutboundInput {
  projectId: number | null
  customer: string
  assetId: number
  qty: number
  amount: number
  type: OutboundType
  mode: OutboundMode
  date: string
  remark: string
}

export interface DashboardData {
  assetCount: number
  boardCount: number
  availableValue: number
  soldAmount: number
  inQty: number
  lockedQty: number
  shippedQty: number
  availableQty: number
  boardStats: {
    board: Board
    label: string
    count: number
    inQty: number
    lockedQty: number
    shippedQty: number
    availableValue: number
    sold: number
  }[]
  sales: {
    projectCount: number
    followingAmount: number
    contractAmount: number
    confirmedAmount: number
    pendingAmount: number
  }
  todos: {
    expiring: Asset[]
    staleProjects: Project[]
  }
  recentLogs: OpLog[]
}

export type BaseKind = 'suppliers' | 'customers'

// ============================================================
// 同步读取（从 db 镜像计算，视图无需改）
// ============================================================
export function getAsset(id: number): Asset | undefined {
  return db.assets.find((a) => a.id === id)
}

export function assetFlows(assetId: number): AssetFlow[] {
  return db.flows.filter((f) => f.assetId === assetId)
}

export function projectItemsOfAsset(assetId: number) {
  return db.projects.flatMap((p) =>
    p.items.filter((it) => it.assetId === assetId).map((it) => ({ project: p, item: it as ProjectItem })),
  )
}

export function getAssetDeliverables(assetId: number): AssetDeliverable[] {
  return db.assetDeliverables[assetId] ?? []
}

export function getFeatureCatalog(type: string): FeatureModule[] {
  return FEATURE_CATALOGS[type] ?? []
}

export function getDashboard(): DashboardData {
  const assets = db.assets
  const availableValueTotal = assets.reduce((s, a) => s + availableValue(a), 0)
  const soldAmount = assets.reduce((s, a) => s + a.soldAmount, 0)
  const physical = assets.filter((a) => !a.repeatSale)
  const inQty = physical.reduce((s, a) => s + a.quantity, 0)
  const lockedQty = physical.reduce((s, a) => s + a.lockedQty, 0)
  const shippedQty = physical.reduce((s, a) => s + a.shippedQty, 0)
  const availableQtyTotal = physical.reduce((s, a) => s + (availableQty(a) ?? 0), 0)
  const boardCount = BOARDS.filter((b) => assets.some((a) => a.board === b.key)).length

  const boardStats = BOARDS.map((b) => {
    const list = assets.filter((a) => a.board === b.key)
    const phys = list.filter((a) => !a.repeatSale)
    return {
      board: b.key,
      label: b.label,
      count: list.length,
      inQty: phys.reduce((s, a) => s + a.quantity, 0),
      lockedQty: phys.reduce((s, a) => s + a.lockedQty, 0),
      shippedQty: phys.reduce((s, a) => s + a.shippedQty, 0),
      availableValue: list.reduce((s, a) => s + availableValue(a), 0),
      sold: list.reduce((s, a) => s + a.soldAmount, 0),
    }
  })

  const ps = db.projects
  const sales = {
    projectCount: ps.length,
    followingAmount: ps
      .filter((p) => p.status === 'active')
      .reduce((s, p) => s + (p.contractAmount || p.expectedAmount || 0), 0),
    contractAmount: ps
      .filter((p) => p.status !== 'terminated')
      .reduce((s, p) => s + (p.contractAmount || 0), 0),
    confirmedAmount: ps
      .filter((p) => p.status === 'delivered')
      .reduce((s, p) => s + (p.contractAmount || 0), 0),
    pendingAmount: 0,
  }

  const staleDays = 30
  const cutoff = Date.now() - staleDays * 86400000
  const todos = {
    expiring: assets.filter((a) => !noSellableStock(a) && expiringSoon(a, 90)),
    staleProjects: ps.filter((p) => {
      if (p.status !== 'active') return false
      const d = p.lastFollowDate ? new Date(p.lastFollowDate).getTime() : 0
      return d < cutoff
    }),
  }

  return {
    assetCount: assets.length,
    boardCount,
    availableValue: availableValueTotal,
    soldAmount,
    inQty,
    lockedQty,
    shippedQty,
    availableQty: availableQtyTotal,
    boardStats,
    sales,
    todos,
    recentLogs: [...db.logs].reverse().slice(0, 10),
  }
}

// ============================================================
// 文件（产品清单等）上传 / 预览
// ============================================================
/**
 * 文件访问 URL（端点已挂双通道鉴权：Bearer 头或 ?token= 查询参数）。
 * 此处统一走查询参数通道（iframe/img/a[download]/fetch 均无法带请求头），
 * token 读取与 axios 拦截器同源（auth.getToken）。
 * @param inline true → `&inline=true`（Content-Disposition: inline，内联预览）；缺省为下载语义
 */
export function fileUrl(filename: string, inline = false): string {
  const params = new URLSearchParams()
  const token = getToken()
  if (token) params.set('token', token)
  if (inline) params.set('inline', 'true')
  const qs = params.toString()
  return `/api/files/${encodeURIComponent(filename)}${qs ? `?${qs}` : ''}`
}

/** 散列名 → 原始文件名（展示用）；无映射记录（存量文件）返回散列名本身兜底 */
export function fileDisplayName(storedName: string): string {
  return db.files.find((f) => f.storedName === storedName)?.name ?? storedName
}

/**
 * 将整段文本中的散列 storedName 翻译为原始文件名（纯展示层，不修改数据）。
 * - 仅取 db.files 中 name !== storedName 的条目参与替换；
 * - 按 storedName 长度降序替换，避免短名是长名子串时误替换；
 * - 无映射的散列保持原样（回退）。
 */
export function translateFileNames(text: string): string {
  if (!text) return text
  const pairs = db.files
    .filter((f) => f.name && f.name !== f.storedName)
    .map((f) => [f.storedName, f.name] as const)
    .sort((a, b) => b[0].length - a[0].length)
  let out = text
  for (const [stored, name] of pairs) {
    if (out.includes(stored)) out = out.split(stored).join(name)
  }
  return out
}

export async function uploadFile(
  file: File,
): Promise<{ filename: string; name: string; size: number }> {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await http.post('/upload', fd)
  return data
}

/** 删除上传文件（DELETE /upload/{filename}，require_editor）：
 * 仍被产品清单/功能清单/交付物附件引用时 400（detail 为可读中文），由调用方 catch 后提示并仅清空字段 */
export async function deleteUploadFile(filename: string): Promise<void> {
  await http.delete(`/upload/${encodeURIComponent(filename)}`)
}

// ============================================================
// 写操作（调用后端 REST + refresh 同步镜像）
// ============================================================
export async function createAsset(input: AssetInput): Promise<Asset> {
  const { data } = await http.post<Asset>('/assets', input)
  await afterWrite()
  return data
}

export async function updateAsset(id: number, input: Partial<AssetInput>): Promise<void> {
  await http.put(`/assets/${id}`, input)
  await afterWrite()
}

export async function deleteAsset(id: number): Promise<void> {
  await http.delete(`/assets/${id}`)
  await afterWrite()
}

export async function createProject(input: ProjectInput): Promise<Project> {
  const { data } = await http.post<Project>('/projects', input)
  await afterWrite()
  return data
}

/** 重新提交回填购物车响应（ADR-027）：alreadyRefilled=此前已回填过（幂等，本次不重复回填）；
 *  restored=回填行数；amountFallback=金额降级为原价成交的行数；
 *  skipped/skippedReasons=回填失败被跳过的行数及原因类别（回填本身不中断） */
export interface RefillCartResult {
  ok: boolean
  alreadyRefilled: boolean
  restored: number
  amountFallback: number
  skipped: number
  skippedReasons: string[]
}

/**
 * 重新提交（ADR-027 / TASK-FE-031）：POST /projects/{id}/refill-cart（无 body）
 * 语义 = 确保**已终止**项目明细在**下单人**购物车（`cartRefilled` 幂等标记：已回填过则不重复回填），
 * 前端随后跳 /cart 改单重提（与撤销同动线）。权限与 resubmit 同口径（下单人本人 / admin / editor）。
 * 错误文案由后端 detail 给出（403 非本人下单 / 400 仅已终止项目可重新提交、下单账号不存在 / 404），
 * 经响应拦截器解析进 Error.message 后由调用方 showError 展示。
 *
 * 不做 afterWrite 全量刷新：由调用方 `await refresh()` 后再跳 /cart（保证购物车镜像先就位）。
 * 注：后端 POST /projects/{id}/resubmit 保留（已 deprecated，无前端入口），前端封装已随之删除。
 */
export async function refillProjectCart(id: number): Promise<RefillCartResult> {
  const { data } = await http.post<RefillCartResult>(`/projects/${id}/refill-cart`)
  return data
}

export async function updateProject(id: number, input: ProjectInput): Promise<void> {
  await http.put(`/projects/${id}`, input)
  await afterWrite()
}

/**
 * 合同状态流转（ADR-007，数量联动最小单位）：
 *  - delivered：逐明细交付（释放锁定/扣 shippedQty/生成交付记录）
 *  - terminated：active 合同释放锁定；delivered 合同撤销交付并回退售出数量与金额
 * 项目 status/expectedAmount/customer/subject 由后端按合同派生重算。
 */
export async function changeContractStatus(
  id: number,
  status: 'delivered' | 'terminated',
  reason = '',
): Promise<void> {
  await http.patch(`/contracts/${id}/status`, { status, reason })
  await afterWrite()
}

/**
 * 合同时间节点录入（ADR-019，PRICING-20261020）：PATCH /contracts/{id}
 * - signedDate（合同签订时间）：editor/admin（接手人守卫，与审核同口径）；仅 active/delivering 可录/改；
 *   录入即 active→delivering；录后**不可清空**（传 null/空 → 400）；
 * - scheduledDeliveryDate（预计交付时间）：仅 admin；仅 delivering 可录/改/清空（null 允许）。
 * 403/400 文案由后端 detail 给出，经拦截器统一 toast。
 */
export async function patchContractFields(
  id: number,
  payload: { signedDate?: string; scheduledDeliveryDate?: string | null },
): Promise<void> {
  await http.patch(`/contracts/${id}`, payload)
  await afterWrite()
}

/**
 * 项目级状态批量快捷（PATCH /projects/{id}/status）：
 * 对名下全部 **active** 合同批量执行该状态动作（delivered=全部交付 / terminated=全部终止），
 * 主入口仍是合同级 changeContractStatus；项目列表抽屉的「交付 / 终止」用本函数。
 * viewer（生态人员）仅可终止自己下单的项目（后端同样校验归属与动作）。
 */
export async function changeProjectStatus(
  id: number,
  status: 'delivered' | 'terminated',
  reason = '',
): Promise<void> {
  await http.patch(`/projects/${id}/status`, { status, reason })
  await afterWrite()
}

/**
 * 订单审核（ADR-012，仅商务/管理员；生态人员 403）：
 * - confirm = 确认下单（items 可带行级改价：unit 行传 price 实际单价、amount/遥感行传 amount 实际合同金额，
 *   整数元；ADR-018 §4：改价只写 ProjectItem，**不再回写平台挂牌价**；
 *   ADR-020 PRICING-20261020：行级可改服务期限 serviceStart/serviceEnd，不传 = 保持原值）；
 * - reject = 驳回（reason 必填，释放锁定、项目终止并留痕）。
 */
export async function reviewProject(
  id: number,
  payload: {
    action: 'confirm' | 'reject'
    reason?: string
    items?: {
      itemId: number
      price?: number
      amount?: number
      serviceStart?: string | null
      serviceEnd?: string | null
    }[]
  },
): Promise<void> {
  await http.post(`/projects/${id}/review`, payload)
  await afterWrite()
}

/** 商务账号选项（ADR-012 §5.1）：editor/admin 有效账号，供商务负责人筛选与 username→姓名 展示映射 */
export interface UserOption {
  id: number
  username: string
  name: string
  role: string
}
export async function userOptions(): Promise<UserOption[]> {
  const { data } = await http.get<UserOption[]>('/users/options')
  return data
}

/** 全部启用账号（2026-10-20：含生态 viewer）——项目页「账号 → 姓名」显示映射用；
 *  商务接手/转交下拉仍用 userOptions（商务专属，不得转给生态） */
export async function allUserOptions(): Promise<UserOption[]> {
  const { data } = await http.get<UserOption[]>('/users/options/all')
  return data
}

/** 商务接手/转交（ADR-012 §5.1 纯移交制）：无负责人=接手（绑当前账号）；
 * 已有负责人=仅负责人可转交（newOwner=目标商务账号）或 admin 越过（newOwner 空=接手给自己）；
 * 非负责人普通商务 400；delivered/terminated 400 */
export async function claimProject(id: number, newOwner = ''): Promise<void> {
  await http.post(`/projects/${id}/claim`, { newOwner })
  await afterWrite()
}

/** 撤销待审核订单响应（ADR-026）：restored=已回填行数；amountFallback=降级为原价成交行数；
 *  skipped/skippedReasons=回填失败被跳过的行数及原因类别（撤销本身不中断） */
export interface WithdrawResult {
  ok: boolean
  restored: number
  amountFallback: number
  skipped: number
  skippedReasons: string[]
}

/**
 * 撤销待审核订单（ADR-026 / TASK-FE-029）：POST /projects/{id}/withdraw
 * 语义 = 终止原单（释放锁定、留痕）+ 全部明细回填下单人购物车；仅 pending 可撤销，
 * 权限 creator==登录账号 或 admin（商务走驳回）。错误文案由后端 detail 给出（403/400/404），
 * 经响应拦截器解析进 Error.message 后由调用方 showError 展示。
 *
 * 不做 afterWrite 全量刷新：撤销同时改项目/合同/明细/购物车多表且失败会有部分降级，
 * 由调用方在成功后 `await refresh()`（保证 refresh 先于跳 /cart）。
 */
export async function withdrawProject(id: number, reason: string): Promise<WithdrawResult> {
  const { data } = await http.post<WithdrawResult>(`/projects/${id}/withdraw`, { reason })
  return data
}

/** 删除项目：后端先回滚（释放锁定 / 撤销该项目交付）再硬删 */
export async function deleteProject(id: number): Promise<void> {
  await http.delete(`/projects/${id}`)
  await afterWrite()
}

export async function createOutbound(input: OutboundInput): Promise<void> {
  await http.post('/outbounds', input)
  await afterWrite()
}

export async function revertOutbound(id: number, reason: string): Promise<void> {
  await http.post(`/outbounds/${id}/revert`, { reason })
  await afterWrite()
}

export async function addBase(kind: BaseKind, rec: Omit<BaseRecord, 'id'>): Promise<void> {
  await http.post(`/bases/${kind}`, rec)
  await afterWrite()
}

export async function updateBase(kind: BaseKind, id: number, rec: Omit<BaseRecord, 'id'>): Promise<void> {
  await http.put(`/bases/${kind}/${id}`, rec)
  await afterWrite()
}

export async function deleteBase(kind: BaseKind, id: number): Promise<void> {
  await http.delete(`/bases/${kind}/${id}`)
  await afterWrite()
}

export async function addAssetDeliverable(
  assetId: number,
  item: { name: string; category: AssetDeliverable['category']; required: boolean; note: string },
): Promise<void> {
  await http.post(`/assets/${assetId}/deliverables`, item)
  await afterWrite()
}

export async function updateAssetDeliverable(
  assetId: number,
  id: number,
  patch: Partial<AssetDeliverable>,
): Promise<void> {
  await http.put(`/assets/${assetId}/deliverables/${id}`, patch)
  await afterWrite()
}

export async function removeAssetDeliverable(assetId: number, id: number): Promise<void> {
  await http.delete(`/assets/${assetId}/deliverables/${id}`)
  await afterWrite()
}

// ============================================================
// 遥感数据可售明细（ADR-011：require_editor，admin/editor 可维护；viewer 由后端守卫 403 拒绝）
// ============================================================
export function rsItemsOfAsset(assetId: number): RsItem[] {
  return db.rsItems.filter((r) => r.assetId === assetId)
}

export function rsItemById(id: number | null | undefined): RsItem | undefined {
  if (id == null) return undefined
  return db.rsItems.find((r) => r.id === id)
}

/** 新增明细：后端返回新建的 RsItemOut（response_model=schemas.RsItemOut） */
export async function addRsItem(assetId: number, data: RsItemInput): Promise<RsItem> {
  const { data: d } = await http.post<RsItem>(`/assets/${assetId}/rs-items`, data)
  await afterWrite()
  return d
}

export async function updateRsItem(id: number, data: RsItemInput): Promise<void> {
  await http.put(`/rs-items/${id}`, data)
  await afterWrite()
}

/** 删除明细：后端 400「该明细存在销售关联，无法删除」（任一 project_items.itemId 引用，含已完成合同） */
export async function deleteRsItem(id: number): Promise<void> {
  await http.delete(`/rs-items/${id}`)
  await afterWrite()
}

// ============================================================
// 公司主体（FORMS-20261022 / ADR-036 起由「资产主体」改名；ENTITIES-20261022 / ADR-035：entities 表 + 设置页维护；
// 读走 bootstrap 镜像 db.entities（全量、无角色过滤），写走 REST + afterWrite 同步镜像）
// ============================================================
/** 主体清单（登录即可；按 createdAt 正序）——设置页/需要最新清单时调用，常规展示读 db.entities */
export async function listEntities(): Promise<Entity[]> {
  const { data } = await http.get<Entity[]>('/entities')
  return data
}

/** 新增主体（require_editor）：name 2–64 字、short 1–32 字；name 重复 → 400「主体已存在」 */
export async function createEntity(name: string, short: string): Promise<void> {
  await http.post('/entities', { name, short })
  await afterWrite()
}

/** 编辑主体（require_editor）：name 与其他主体重复 → 400「主体已存在」；
 * 改 name（全称）不回写 assets.subject（存量产品仍挂旧名称，前端改名前二次确认） */
export async function updateEntity(id: number, name: string, short: string): Promise<void> {
  await http.put(`/entities/${id}`, { name, short })
  await afterWrite()
}

/** 删除主体（require_editor）：被产品引用 → 400「该主体下存在 N 个产品，不可删除」；不存在 → 404 */
export async function deleteEntity(id: number): Promise<void> {
  await http.delete(`/entities/${id}`)
  await afterWrite()
}

// ============================================================
// 产品列表服务端分页（PAGE-20261021，契约 docs/api-contracts.md）：
// 参数 page/pageSize（默认 10，上限 100），返回 { total, items }；
// bootstrap 镜像字段（rsItems/flows/logs）保留不动，RsItemPicker / 项目页名称查找仍用全量
// ============================================================
/** 可售明细分页（GET /assets/{assetId}/rs-items）：items = RsItem + 后端派生 soldCount，id ASC */
export async function listAssetRsItems(
  assetId: number,
  page = 1,
  pageSize = 10,
): Promise<{ total: number; items: RsItemWithSold[] }> {
  const { data } = await http.get<{ total: number; items: RsItemWithSold[] }>(
    `/assets/${assetId}/rs-items`,
    { params: { page, pageSize } },
  )
  return data
}

/** 数量流水分页（GET /assets/{assetId}/flows）：仅该 assetId 的产品级流水，id DESC */
export async function listAssetFlows(
  assetId: number,
  page = 1,
  pageSize = 10,
): Promise<{ total: number; items: AssetFlow[] }> {
  const { data } = await http.get<{ total: number; items: AssetFlow[] }>(
    `/assets/${assetId}/flows`,
    { params: { page, pageSize } },
  )
  return data
}

/** 操作日志分页（GET /assets/{assetId}/logs）：target='asset' && assetId 的操作日志，id DESC */
export async function listAssetLogs(
  assetId: number,
  page = 1,
  pageSize = 10,
): Promise<{ total: number; items: OpLog[] }> {
  const { data } = await http.get<{ total: number; items: OpLog[] }>(
    `/assets/${assetId}/logs`,
    { params: { page, pageSize } },
  )
  return data
}

// ============================================================
// 购物车（ADR-009：按登录用户隔离，后端以当前登录用户为准；bootstrap.cart 仅含当前用户行）
// ============================================================
/** 加购：含 itemId（遥感明细，ADR-011）时数量恒 1（后端校验 qty≠1 → 400），行级客户由购物车页行内填写 */
export async function addToCart(assetId: number, qty = 1, itemId?: number): Promise<void> {
  await http.post('/cart', { assetId, qty, ...(itemId != null ? { itemId } : {}) })
  await afterWrite()
}

export interface CartSkippedItem {
  assetId: number
  name: string
  available: number
  reason: string
}

export interface CartBatchResult {
  addedCount: number
  skipped: CartSkippedItem[]
  cart: CartItem[]
}

/** 批量加购：行可含 itemId（遥感明细，ADR-011），含 itemId 行数量恒 1 */
export async function addCartBatch(
  items: { assetId: number; qty: number; itemId?: number }[],
): Promise<CartBatchResult> {
  const { data } = await http.post<CartBatchResult>('/cart/batch', { items })
  await afterWrite()
  return data
}

/** CART-PERF-20261021（2026-10-21）：行级写改本地打补丁——成功后用响应 CartItemOut 替换本地行，不再全量刷新 */
export async function setCartQty(id: number, qty: number): Promise<void> {
  const { data } = await http.put(`/cart/${id}`, { qty })
  await patchCartRow(id, data)
}

/**
 * 修改购物车行销售金额（ADR-008/ADR-018 §3，PRICING-20261020）：整数元。
 * - amount 模式行：权威输入，后端校验 int > 0；
 * - unit/遥感明细行：折扣金额，过产品参考区间校验（超区间 400，文案由后端给出）。
 * ⚠️ 必须同时回传该行当前 qty（后端 PUT 对 qty<=0 直接 400，且区间校验按新 qty 重算）。
 * DISCOUNT-20261021（ADR-023，2026-10-21）：新增 discountRate 入参（0-1 小数，如 9 折传 0.9；
 * null = 清空；undefined = 不传该字段）。一致性规则由前端执行（折扣回填 amount 后一次性提交；
 * 手改 amount 时传 null），后端只存不算。
 */
export async function setCartAmount(
  id: number,
  qty: number,
  amount: number,
  discountRate?: number | null,
): Promise<void> {
  const body: { qty: number; amount: number; discountRate?: number | null } = { qty, amount }
  if (discountRate !== undefined) body.discountRate = discountRate
  // CART-PERF-20261021（2026-10-21）：行级写改本地打补丁（响应 CartItemOut 替换本地行，旧格式回退全量刷新）
  const { data } = await http.put(`/cart/${id}`, body)
  await patchCartRow(id, data)
}

/**
 * 修改购物车行服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，start ≤ end 否则 400。
 * 同 setCartAmount：必须回传该行当前 qty。
 */
export async function setCartService(
  id: number,
  qty: number,
  serviceStart: string | null,
  serviceEnd: string | null,
): Promise<void> {
  // CART-PERF-20261021（2026-10-21）：行级写改本地打补丁（响应 CartItemOut 替换本地行，旧格式回退全量刷新）
  const { data } = await http.put(`/cart/${id}`, { qty, serviceStart, serviceEnd })
  await patchCartRow(id, data)
}

/** 修改购物车行级客户（ADR-007）：400「购物车中该产品在客户「X」下已有行，无法修改客户（请先删除原行）」
 *  CART-PERF-20261021（2026-10-21）：行级写改本地打补丁（PATCH 响应同为 CartItemOut，旧格式回退全量刷新） */
export async function patchCartItem(id: number, customer: string): Promise<void> {
  const { data } = await http.patch(`/cart/${id}`, { customer })
  await patchCartRow(id, data)
}

export async function removeCartItem(id: number): Promise<void> {
  await http.delete(`/cart/${id}`)
  await afterWrite()
}

export async function clearCart(): Promise<void> {
  await http.delete('/cart')
  await afterWrite()
}

export interface OrderFields {
  projectName: string
  /** 购物车结算不带（后端按行级客户分组，CheckoutInput.customer 可选且不参与分组） */
  customer?: string
  rep?: string
  businessOwner?: string // 商务负责人（可选，默认空）
  contractAmount?: number // 单位：元（与后端 Project.contractAmount 一致，ADR-006）
  expectedSignDate?: string
  remark?: string
  deliveryReq?: string
}

/**
 * 购物车结算入参（ADR-008/ADR-018 §3）：后端 `CheckoutInput` 无 items 字段——
 * 行级销售金额（包量定价权威值 / unit 与遥感行折扣金额）与服务期限均已由
 * PUT/PATCH /cart/{id} 持久化到 cart_items，结算不再携带（行级值随 cart_items 透传落库）。
 *
 * FIX-20261022 / BUG-10（ADR-033 幂等）：新增可选 `requestId`——同一次提交（含失败重试）沿用同一 id，
 * 后端按 (userId, requestId) 24h 内幂等返回首次生成的项目，避免双击/重试重复建单与重复锁量。
 * 成功后由调用方丢弃（下次结算重新生成）。
 */
export interface CheckoutInput extends OrderFields {
  requestId?: string
}

export interface ProjectOut {
  id: number
  code: string
  name: string
  status: string
  contractCount?: number // ADR-007：合同数量（=客户组数）
  /** ADR-033：true = 命中幂等键，返回的是首次创建的项目（本次未重复建单/锁量/清购物车） */
  idempotent?: boolean
}

/** 购物车下单（ADR-020，PRICING-20261020：购物车为唯一下单链路）：
 * 生成「待审核」销售项目并锁定数量（不自动交付），随后清空购物车。
 * FIX-20261022 / BUG-10：payload 可带 `requestId`（幂等键，ADR-033）。 */
export async function checkoutCart(data: CheckoutInput): Promise<ProjectOut> {
  const { data: d } = await http.post<ProjectOut>('/cart/checkout', data)
  await afterWrite()
  return d
}

// 2026-10-20（ADR-020）：产品「登记销售」直接下单入口已移除，前端不再调用
// POST /sales/order（后端端点保留并标记 deprecated，兼容潜在直调方），createSaleOrder 一并删除。

// ============================================================
// 认证 / 账号管理 / 审计日志（2026-10-15 权限体系）
// ============================================================
export interface LoginResult {
  token: string
  user: CurrentUser
}

/** 登录（匿名接口）：401 时 detail 为「用户名或密码错误 / 账号已被禁用」 */
export async function login(username: string, password: string): Promise<LoginResult> {
  const { data } = await http.post<LoginResult>('/auth/login', { username, password })
  return data
}

/** 当前登录用户（路由守卫在 token 存在但本地用户缺失时校验用） */
export async function fetchMe(): Promise<CurrentUser> {
  const { data } = await http.get<CurrentUser>('/auth/me')
  setUser(data)
  return data
}

/** 用户输出（不含密码；后端 UserOut 未含 createdAt，前端按可选字段兜底展示） */
export interface UserOut {
  id: number
  username: string
  name: string
  role: Role
  enabled: boolean
  createdAt?: string
}

export interface UserCreateInput {
  username: string
  password: string
  name: string
  role: Role
}

export interface UserUpdateInput {
  name?: string
  role?: Role
  enabled?: boolean
  password?: string
}

/** 账号列表（仅 admin） */
export async function listUsers(): Promise<UserOut[]> {
  const { data } = await http.get<UserOut[]>('/users')
  return data
}

/** 新增账号（仅 admin）：400「用户名已存在」 */
export async function createUser(input: UserCreateInput): Promise<UserOut> {
  const { data } = await http.post<UserOut>('/users', input)
  return data
}

/** 编辑账号（仅 admin）：400「不能修改自己的角色或启用状态」；改自己密码允许 */
export async function updateUser(id: number, patch: UserUpdateInput): Promise<UserOut> {
  const { data } = await http.put<UserOut>(`/users/${id}`, patch)
  return data
}

/** 删除账号（仅 admin）：400「不能删除自己的账号」 */
export async function deleteUser(id: number): Promise<void> {
  await http.delete(`/users/${id}`)
}

export interface AuditLogOut {
  id: number
  userId: number | null
  username: string
  actionType: string
  action: string
  target: string
  targetName: string
  detail: string | null
  time: string
}

export interface AuditLogQuery {
  actionType?: string
  username?: string
  page?: number
  pageSize?: number
}

/** 审计日志查询（仅 admin，时间倒序） */
export async function listAuditLogs(
  query: AuditLogQuery,
): Promise<{ total: number; items: AuditLogOut[] }> {
  const { data } = await http.get<{ total: number; items: AuditLogOut[] }>('/audit-logs', {
    params: {
      actionType: query.actionType || undefined,
      username: query.username || undefined,
      page: query.page ?? 1,
      pageSize: query.pageSize ?? 20,
    },
  })
  return data
}

export { CATEGORY_UNITS }
