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
  type DeliverableTemplateItem,
  type FeatureModule,
  type OpLog,
  type Outbound,
  type OutboundMode,
  type OutboundType,
  type Project,
  type ProjectItem,
  type Contract,
  type Board,
  type RsItem,
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

/**
 * viewer（生态人员）放行的写端点白名单（与后端 `require_order` 对齐，ADR-009）：
 * 下单链路（加购 / 批量加购 / 改数量 / 改行级客户 / 删行 / 清空 / 购物车结算 / 产品直接下单）
 * 后端已全部改为 require_order（认证即放行），前端白名单同步覆盖全部购物车端点。
 */
const VIEWER_ALLOWED_REQUESTS: { method: string; pattern: RegExp }[] = [
  { method: 'post', pattern: /^\/cart\/?$/ },
  { method: 'post', pattern: /^\/cart\/batch$/ },
  { method: 'post', pattern: /^\/cart\/checkout$/ },
  { method: 'put', pattern: /^\/cart\/\d+$/ },
  { method: 'patch', pattern: /^\/cart\/\d+$/ },
  { method: 'delete', pattern: /^\/cart\/\d+$/ },
  { method: 'delete', pattern: /^\/cart$/ },
  { method: 'post', pattern: /^\/sales\/order$/ },
]

// 请求拦截器：已登录时统一携带 Bearer token；
// 全局写操作兜底：viewer（生态人员）的非 GET 请求仅放行下单链路白名单，其余在发出前直接拒绝（避免 UI 漏网点）
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (config.method && config.method !== 'get' && currentUser.value?.role === 'viewer') {
    const url = config.url || ''
    const allowed = VIEWER_ALLOWED_REQUESTS.some(
      (r) => r.method === config.method && r.pattern.test(url),
    )
    if (!allowed) return Promise.reject(new Error(READONLY_TIP))
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
  contracts: [] as Contract[],
  outbounds: [] as Outbound[],
  cart: [] as CartItem[],
  suppliers: [] as BaseRecord[],
  customers: [] as BaseRecord[],
  reps: [] as BaseRecord[],
  flows: [] as AssetFlow[],
  logs: [] as OpLog[],
  deliverableTemplates: {} as Record<string, DeliverableTemplateItem[]>,
  assetDeliverables: {} as Record<number, AssetDeliverable[]>,
  files: [] as FileMeta[],
  rsItems: [] as RsItem[], // 遥感数据可售明细（ADR-011，bootstrap 顶层字段）
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
      db.contracts = data.contracts ?? []
      db.outbounds = data.outbounds
      db.cart = data.cart
      db.suppliers = data.suppliers
      db.customers = data.customers
      db.reps = data.reps
      db.flows = data.flows
      db.logs = data.logs
      db.deliverableTemplates = data.deliverableTemplates
      db.assetDeliverables = data.assetDeliverables
      db.files = data.files ?? []
      db.rsItems = data.rsItems ?? []
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
  repeatSale?: boolean // 默认 true
}

export interface ProjectItemInput {
  assetId: number | null
  qty: number
  price: number
  amount: number
  deliveryReq: string
  itemId?: number // ADR-011：遥感明细行（重新提交预填时携带；qty 恒 1）
}

/** 合同入参（ADR-007）：POST /projects 的 contracts[] 元素；合同内强制同一产品主体（后端校验） */
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

/** 重新提交（2026-10-20）：已终止项目按（可修改的）明细新建 pending 订单，旧项目保留终止历史 */
export async function resubmitProject(id: number, input: ProjectInput): Promise<Project> {
  const { data } = await http.post<Project>(`/projects/${id}/resubmit`, input)
  await afterWrite()
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
 * - confirm = 确认下单（items 可带行级改价：unit 行传 price 实际单价、amount 行传 amount 实际合同金额，
 *   整数元；遥感明细行不接受改价；确认后实际价同步写回平台挂牌价）；
 * - reject = 驳回（reason 必填，释放锁定、项目终止并留痕）。
 */
export async function reviewProject(
  id: number,
  payload: {
    action: 'confirm' | 'reject'
    reason?: string
    items?: { itemId: number; price?: number; amount?: number }[]
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
// 遥感数据可售明细（ADR-011：require_editor，admin/editor 可维护；viewer 不在白名单，403 兜底）
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

export async function setCartQty(id: number, qty: number): Promise<void> {
  await http.put(`/cart/${id}`, { qty })
  await afterWrite()
}

/**
 * 修改购物车行合同金额（ADR-008，仅包量定价产品行）：整数元，后端校验 int > 0。
 * ⚠️ 后端 PUT /cart/{id} 对 qty<=0 执行删行，必须同时回传该行当前 qty（缺省=0 会误删行）。
 */
export async function setCartAmount(id: number, qty: number, amount: number): Promise<void> {
  await http.put(`/cart/${id}`, { qty, amount })
  await afterWrite()
}

/** 修改购物车行级客户（ADR-007）：400「购物车中该产品在客户「X」下已有行，无法修改客户（请先删除原行）」 */
export async function patchCartItem(id: number, customer: string): Promise<void> {
  await http.patch(`/cart/${id}`, { customer })
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
  /** 直接下单必填；购物车结算不带（后端按行级客户分组，CheckoutInput.customer 可选且不参与分组） */
  customer?: string
  rep?: string
  businessOwner?: string // 商务负责人（可选，默认空）
  contractAmount?: number // 单位：元（与后端 Project.contractAmount 一致，ADR-006）
  expectedSignDate?: string
  remark?: string
  deliveryReq?: string
}

/**
 * 购物车结算入参（ADR-008）：后端 `CheckoutInput` 无 items 字段——
 * 包量定价行的合同金额权威值已由 PUT/PATCH /cart/{id} 持久化到 cart_items.amount，结算不再携带。
 */
export type CheckoutInput = OrderFields

export interface SaleOrderInput extends OrderFields {
  // amount：包量定价行的合同金额（整数元，ADR-008）；itemId：遥感明细行（ADR-011，qty 恒 1，金额后端按 rs_items.price 权威重算）
  items: { assetId: number; qty: number; amount?: number; itemId?: number }[]
}

export interface ProjectOut {
  id: number
  code: string
  name: string
  status: string
  contractCount?: number // ADR-007：合同数量（=客户组数）
}

/** 购物车下单：生成「进行中」销售项目并锁定数量（不自动交付），随后清空购物车 */
export async function checkoutCart(data: CheckoutInput): Promise<ProjectOut> {
  const { data: d } = await http.post<ProjectOut>('/cart/checkout', data)
  await afterWrite()
  return d
}

/** 产品直接下单：单/多产品生成「进行中」销售项目并锁定数量（与购物车下单同一流程） */
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
