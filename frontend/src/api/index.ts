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
  type CartItem,
  type AssetDeliverable,
  type DeliverableTemplateItem,
  type FeatureModule,
  type OpLog,
  type Outbound,
  type OutboundMode,
  type OutboundType,
  type Project,
  type ProjectItem,
  type ProjectStatus,
  type Board,
} from '@/types'
import { CATEGORY_UNITS, FEATURE_CATALOGS } from '@/constants'
import {
  clearSession,
  currentUser,
  getToken,
  READONLY_TIP,
  setUser,
  type CurrentUser,
  type Role,
} from '@/auth'

const http = axios.create({ baseURL: '/api', timeout: 20000 })

// 请求拦截器：已登录时统一携带 Bearer token；
// 全局写操作兜底：viewer（只读）的任何非 GET 请求在发出前直接拒绝（避免 UI 漏网点）
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (config.method && config.method !== 'get' && currentUser.value?.role === 'viewer') {
    return Promise.reject(new Error(READONLY_TIP))
  }
  return config
})

/** Pydantic 422 校验项形态（detail 数组元素） */
interface PydanticIssue {
  loc?: unknown[]
  msg?: string
}

/**
 * 统一解析后端错误体 detail：
 *  - 业务错误：字符串（如「库存不足：…」）
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

// 统一错误：把后端 detail 转成 Error，便于调用方 catch 后展示
//  - 401（token 缺失/过期/账号禁用）：清本地态并整页跳 /login（登录接口自身 401 不跳转，留在登录页提示）
//  - 403（角色不足）：走既有 detail 解析，提示「无权限执行此操作」
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
    return Promise.reject(new Error(msg))
  },
)

// ============================================================
// 响应式数据镜像（由 refresh() 填充，视图直接响应式读取）
// ============================================================
export const db = reactive({
  assets: [] as Asset[],
  projects: [] as Project[],
  outbounds: [] as Outbound[],
  cart: [] as CartItem[],
  suppliers: [] as BaseRecord[],
  customers: [] as BaseRecord[],
  reps: [] as BaseRecord[],
  flows: [] as AssetFlow[],
  logs: [] as OpLog[],
  deliverableTemplates: {} as Record<string, DeliverableTemplateItem[]>,
  assetDeliverables: {} as Record<number, AssetDeliverable[]>,
})

let refreshing: Promise<void> | null = null

/** 拉取后端全量，填充 db（幂等、防并发） */
export function refresh(force = false): Promise<void> {
  if (!force && refreshing) return refreshing
  refreshing = (async () => {
    try {
      const { data } = await http.get('/bootstrap')
      db.assets = data.assets
      db.projects = data.projects
      db.outbounds = data.outbounds
      db.cart = data.cart
      db.suppliers = data.suppliers
      db.customers = data.customers
      db.reps = data.reps
      db.flows = data.flows
      db.logs = data.logs
      db.deliverableTemplates = data.deliverableTemplates
      db.assetDeliverables = data.assetDeliverables
    } finally {
      refreshing = null
    }
  })()
  return refreshing
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
  status: AssetStatus
  inboundDate: string
  expiryDate: string
  perpetual: boolean
  spec: string
  saleDetail?: IWorkbookData
  contractFile?: string
  remark: string
}

export interface ProjectItemInput {
  assetId: number | null
  qty: number
  price: number
  amount: number
  deliveryReq: string
}

export interface ProjectInput {
  name: string
  customer: string
  industry: string
  rep: string
  subject: string
  expectedAmount: number
  quoteAmount: number
  contractAmount: number
  paidAmount: number
  expectedSignDate: string
  lastFollowDate: string
  remark: string
  items: ProjectItemInput[]
}

export interface OutboundInput {
  projectId: number | null
  customer: string
  assetId: number
  qty: number
  amount: number
  type: OutboundType
  mode: OutboundMode
  date: string
  operator: string
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

export type BaseKind = 'suppliers' | 'customers' | 'reps'

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

export function getDeliverableTemplate(type: string): DeliverableTemplateItem[] {
  return db.deliverableTemplates[type] ?? []
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
export function fileUrl(filename: string): string {
  return `/api/files/${encodeURIComponent(filename)}`
}

export async function uploadFile(
  file: File,
): Promise<{ filename: string; name: string; size: number }> {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await http.post('/upload', fd)
  return data
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

export async function updateProject(id: number, input: ProjectInput): Promise<void> {
  await http.put(`/projects/${id}`, input)
  await afterWrite()
}

export async function changeProjectStatus(id: number, status: ProjectStatus, reason: string): Promise<void> {
  await http.patch(`/projects/${id}/status`, { status, reason })
  await afterWrite()
}

/** 删除项目：后端先回滚（释放锁定 / 撤销该项目出库）再硬删 */
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

export async function addTemplateItem(
  type: string,
  item: Omit<DeliverableTemplateItem, 'id'>,
): Promise<void> {
  await http.post('/deliverable-templates', item, { params: { type } })
  await afterWrite()
}

export async function updateTemplateItem(
  type: string,
  id: number,
  item: Omit<DeliverableTemplateItem, 'id'>,
): Promise<void> {
  await http.put(`/deliverable-templates/${id}`, item, { params: { type } })
  await afterWrite()
}

export async function deleteTemplateItem(type: string, id: number): Promise<void> {
  await http.delete(`/deliverable-templates/${id}`, { params: { type } })
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
// 购物车（预留账号权限；当前 user_id 固定 admin）
// ============================================================
export async function addToCart(assetId: number, qty = 1): Promise<void> {
  await http.post('/cart', { assetId, qty })
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

export async function addCartBatch(items: { assetId: number; qty: number }[]): Promise<CartBatchResult> {
  const { data } = await http.post<CartBatchResult>('/cart/batch', { items })
  await afterWrite()
  return data
}

export async function setCartQty(id: number, qty: number): Promise<void> {
  await http.put(`/cart/${id}`, { qty })
  await afterWrite()
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
  customer: string
  rep?: string
  contractAmount?: number // 单位：万元（与后端 Project.contractAmount 一致）
  expectedSignDate?: string
  remark?: string
  deliveryReq?: string
}

export interface CheckoutInput extends OrderFields {}

export interface SaleOrderInput extends OrderFields {
  items: { assetId: number; qty: number }[]
}

export interface ProjectOut {
  id: number
  code: string
  name: string
  status: string
}

/** 购物车下单：生成「进行中」销售项目并锁定库存（不自动出库），随后清空购物车 */
export async function checkoutCart(data: CheckoutInput): Promise<ProjectOut> {
  const { data: d } = await http.post<ProjectOut>('/cart/checkout', data)
  await afterWrite()
  return d
}

/** 资产直接下单：单/多资产生成「进行中」销售项目并锁定库存（与购物车下单同一流程） */
export async function createSaleOrder(data: SaleOrderInput): Promise<ProjectOut> {
  const { data: d } = await http.post<ProjectOut>('/sales/order', data)
  await afterWrite()
  return d
}

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
