<script setup lang="ts">
/**
 * 产品及服务 - 详情页
 *
 * 按《产品详情页 UI 开发提示词》实现：
 * ← 返回 → 大标题 + 元信息行 + [编辑产品] [登记销售] [更多▾]（删除收入菜单）
 * → 五页签：基本信息(左基础资料 1 列 + 右数量与归属含可售数量) / 交付物
 *   / 销售关联(空状态) / 数量流水(时间线) / 操作记录
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  Box,
  CircleCheck,
  Delete,
  Edit,
  InfoFilled,
  Key,
  Link,
  Operation,
  Plus,
  Tickets,
  TopRight,
  Upload,
} from '@element-plus/icons-vue'
import {
  ASSET_STOCK_STATE,
  DELIVERABLE_CATEGORIES,
  FLOW_TYPES,
  PROJECT_STATUS,
  RS_ITEM_STATUS,
  amountInputFormatter,
  amountInputParser,
  assetStockState,
  availableQty,
  boardLabel,
  checkDeliverableUrl,
  displayUnitPrice,
  entityShort,
  expiryText,
  formatAssetQty,
  formatMoney,
  isAmountMode,
  isAmountPrecisionValid,
  noSellableStock,
  priceRangeText,
  tagInfo,
  rsItemName,
  type AssetDeliverable,
  type AssetFlow,
  type DeliverableCategory,
  type FlowType,
  type OpLog,
  type Project,
  type ProjectItem,
  type RsItem,
  type RsItemWithSold,
} from '@/types'
import {
  addAssetDeliverable,
  addRsItem,
  deleteAsset,
  deleteRsItem,
  deleteUploadFile,
  fileDisplayName,
  getAsset,
  getAssetDeliverables,
  allUserOptions,
  listAssetFlows,
  listAssetLogs,
  listAssetRsItems,
  projectItemsOfAsset,
  removeAssetDeliverable,
  showError,
  translateFileNames,
  updateAssetDeliverable,
  updateRsItem,
  uploadFile,
  db,
  type RsItemInput,
  type UserOption,
} from '@/api'
import { PROVINCES } from '@/constants'
import { canWrite, NO_PERM_TIP } from '@/auth'
import FilePreview from '@/components/FilePreview.vue'

const route = useRoute()
const router = useRouter()
const assetId = computed(() => Number(route.params.id))

const asset = computed(() => getAsset(assetId.value))

const salesLinks = computed(() =>
  asset.value ? projectItemsOfAsset(asset.value.id) : [],
)
// ============================================================
// 数量流水 / 操作记录（PAGE-20261021：服务端分页，tab 首次激活时加载）
// ============================================================
const flow = reactive({
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  items: [] as AssetFlow[],
  loaded: false,
})

async function loadFlows() {
  const a = asset.value
  if (!a) return
  flow.loading = true
  try {
    const res = await listAssetFlows(a.id, flow.page, flow.pageSize)
    flow.total = res.total
    flow.items = res.items
    flow.loaded = true
  } catch (e) {
    showError(e, '加载数量流水失败')
  } finally {
    flow.loading = false
  }
}

function onFlowPageChange(page: number) {
  flow.page = page
  loadFlows()
}

const opLog = reactive({
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  items: [] as OpLog[],
  loaded: false,
})

async function loadOpLogs() {
  const a = asset.value
  if (!a) return
  opLog.loading = true
  try {
    const res = await listAssetLogs(a.id, opLog.page, opLog.pageSize)
    opLog.total = res.total
    opLog.items = res.items
    opLog.loaded = true
  } catch (e) {
    showError(e, '加载操作记录失败')
  } finally {
    opLog.loading = false
  }
}

function onOpLogPageChange(page: number) {
  opLog.page = page
  loadOpLogs()
}

// 2026-10-20（问题12b）：「销售关联」生态人员走账号→姓名映射——
// 复用项目页既有口径（/users/options/all 全量名册 + repName 同构实现，原本页裸账号外露）
const repOptions = ref<UserOption[]>([])
allUserOptions().then((u) => { repOptions.value = u }).catch(() => {})
function repName(rep?: string): string {
  if (!rep) return '-'
  const u = repOptions.value.find((x) => x.username === rep) || repOptions.value.find((x) => x.name === rep)
  return u?.name || rep
}

/** 状态点胶囊：可售绿 / 已售罄红（可重复售卖归入可售） */
function statusPill(): { cls: 'ok' | 'off'; dot: string } {
  const s = assetStockState(asset.value!)
  return s === 'in_stock' ? { cls: 'ok', dot: '●' } : { cls: 'off', dot: '◌' }
}

function isWipBoard() {
  return asset.value?.board === 'compute'
}

// ============================================================
// 顶部动作
// ============================================================
// 2026-10-20（ADR-020，PRICING-20261020）：「登记销售」直接下单入口已移除，
// 下单统一走购物车（SalesOrderDialog 仅保留购物车结算确认模式）。

/** 编辑产品：无可用数量时提示（不阻止，允许补登记） */
function goEditAsset() {
  if (!asset.value) return
  if (noSellableStock(asset.value)) {
    ElMessage.warning('该产品当前无可用数量（可售数量为 0）。可继续编辑补登记或核对锁定 / 售出情况。')
  }
  router.push(`/assets/${asset.value.id}/edit`)
}

/**
 * 复制产品编号。
 * CLIPBOARD-20261022：`navigator.clipboard` 是 secure-context-only API——
 * http + 局域网 IP 访问时为 undefined（本项目实际部署形态），原先只能走 catch 弹编号。
 * 降级链：clipboard API → execCommand('copy')（不受安全上下文限制）→ 弹窗展示让用户手抄。
 * 注意：execCommand 需要 user gesture，必须在点击的同一 task 内同步调用（不要在它之前 await）。
 */
async function copyCode() {
  if (!asset.value) return
  const code = asset.value.code
  // 1 级：异步 Clipboard API（https / localhost 才有）
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(code)
      ElMessage.success('产品编号已复制')
      return
    } catch {
      // 权限被拒 / 非聚焦文档 → 继续降级
    }
  }
  // 2 级：execCommand（需 user gesture；此处仍在点击的同步调用链上）
  if (copyByExecCommand(code)) {
    ElMessage.success('产品编号已复制')
    return
  }
  // 3 级：兜底展示
  ElMessage.info(`产品编号：${code}`)
}

/**
 * textarea + execCommand 兜底复制；返回是否成功。同步实现，勿引入 await。
 * CLIPBOARD-20261022：textarea 的移除放在 finally——成功 / 返回 false / execCommand 抛错
 * 三条路径都会摘除节点，不留 DOM 残留（`document.body.children.length` 回到调用前）。
 */
function copyByExecCommand(text: string): boolean {
  const prevFocus = document.activeElement as HTMLElement | null
  const ta = document.createElement('textarea')
  try {
    ta.value = text
    // 防滚动/防闪烁：移出视口 + 只读 + 无边框
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length) // iOS Safari 需要
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    // 无论成功 / 返回 false / execCommand 抛错，只要挂上过就摘除 → 不留 DOM 残留
    ta.parentNode?.removeChild(ta)
    // 焦点归还给触发前的元素（select() 会把焦点吸到 textarea 上）；
    // 该元素可能已脱离文档，focus 自身也可能抛错 → 内层 try 吞掉，保证 finally 不外抛
    if (prevFocus && typeof prevFocus.focus === 'function') {
      try {
        prevFocus.focus()
      } catch {
        // 忽略：焦点归还失败不影响复制结果
      }
    }
  }
}

// ============================================================
// 删除
// ============================================================
async function handleDelete() {
  if (!asset.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除产品「${asset.value.name}」（${asset.value.code}）吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteAsset(asset.value.id)
    ElMessage.success('删除成功')
    router.push(`/assets/${asset.value.board}`)
  } catch (e) {
    showError(e, '删除失败')
  }
}

// ============================================================
// 页签
// ============================================================
const activeTab = ref('info')
onMounted(() => {
  const t = route.query.tab
  if (t === 'deliverables') activeTab.value = 'deliverables'
})

// ============================================================
// 数量流水：筛选 + 时间线
// ============================================================
type FlowGroup = 'all' | 'purchase_in' | 'project_lock' | 'sale_out' | 'adjust'
const flowFilter = ref<FlowGroup>('all')
/** PAGE-20261021：后端分页接口不支持 type 参数，类型过滤保持前端过滤、仅作用于当前页（UI 已注明口径）；
 * 接口本身按 id DESC 返回，无需再 reverse */
const filteredFlows = computed(() => {
  const list = [...flow.items]
  if (flowFilter.value === 'all') return list
  if (flowFilter.value === 'adjust') {
    return list.filter((f) => f.type === 'cancel_release' || f.type === 'manual_adjust')
  }
  return list.filter((f) => f.type === flowFilter.value)
})

/** 流水类型 → 时间线色点（蓝/绿/灰蓝/橙） */
const FLOW_CLS: Record<FlowType, string> = {
  purchase_in: 'blue',
  project_lock: 'blue',
  sale_out: 'green',
  cancel_release: 'gray',
  manual_adjust: 'orange',
}

// ============================================================
// 交付物
// ============================================================
const deliverables = computed(() =>
  asset.value ? getAssetDeliverables(asset.value.id) : [],
)
const catFilter = ref<DeliverableCategory | ''>('')
const filteredDels = computed(() =>
  deliverables.value.filter((d) => !catFilter.value || d.category === catFilter.value),
)
const delStats = computed(() => {
  const list = deliverables.value
  const ready = list.filter((d) => d.status === 'ready').length
  const latest = [...list].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]
  return { total: list.length, ready, latest: latest?.updatedAt ?? '-' }
})

/** 分类 → 图标与底色（浅蓝/浅绿/浅紫蓝/中性） */
const CAT_ICON: Record<DeliverableCategory, { icon: typeof Box; cls: string }> = {
  install: { icon: Box, cls: 'blue' },
  license: { icon: Key, cls: 'green' },
  feature: { icon: Tickets, cls: 'purple' },
  accept: { icon: CircleCheck, cls: 'neutral' },
}

/** 默认交付范围（右侧说明栏） */
const defaultScope = computed(() =>
  (Object.keys(DELIVERABLE_CATEGORIES) as DeliverableCategory[])
    .map((c) => ({
      label: DELIVERABLE_CATEGORIES[c].label,
      names: deliverables.value.filter((d) => d.category === c).map((d) => d.name),
    }))
    .filter((x) => x.names.length > 0),
)

/** 交付三步（右侧说明栏时间线） */
const DELIVERY_STEPS = [
  { t: '项目关联', d: '生态人员在销售项目中选择产品及数量。' },
  { t: '选择交付包', d: '交付人员确认本次需使用的交付物版本。' },
  { t: '完成交付', d: '记录序列号、客户、日期和经办人，生成交付凭证。' },
]

// ---- 交付物操作 ----
const delCreate = reactive({
  visible: false,
  form: {
    name: '',
    category: 'install' as DeliverableCategory,
    required: true,
    note: '',
    url: '', // ADR-044：外部链接（选填）
  },
})

function openDelCreate() {
  delCreate.form = { name: '', category: 'install', required: true, note: '', url: '' }
  delCreate.visible = true
}

async function confirmDel() {
  if (!asset.value) return
  if (!delCreate.form.name.trim()) {
    ElMessage.warning('请输入交付物名称')
    return
  }
  // ADR-044：外链与后端 `_normalize_deliverable_url` 同规则（http/https + ≤512），不合法中断提交
  const url = delCreate.form.url.trim()
  const urlErr = checkDeliverableUrl(url)
  if (urlErr) {
    ElMessage.warning(urlErr)
    return
  }
  // FIX-20261022 / BUG-09：写操作补 catch（后端 400/422 此前完全静默）
  try {
    await addAssetDeliverable(asset.value.id, {
      name: delCreate.form.name,
      category: delCreate.form.category,
      required: delCreate.form.required,
      note: delCreate.form.note,
      url, // 空串也照传（后端归一为 ''，便于「只上传附件」语义）
    })
    ElMessage.success('新增成功')
    delCreate.visible = false
  } catch (e) {
    showError(e, '新增失败')
  }
}

/**
 * 交付物详情弹窗：只持有 id，数据按 id 从**刷新后的镜像**取值（FIX-20261022 / BUG-36）。
 * 原实现持有打开瞬间的对象引用 → 标记就绪/上传附件等写操作刷新 bootstrap 后，
 * 弹窗仍显示旧状态（与列表不一致）；改为 computed 后弹窗内容随 `db.assetDeliverables` 自动同步。
 */
const viewingId = ref<number | null>(null)
const viewDialog = ref(false)
const viewing = computed<AssetDeliverable | null>(() =>
  viewingId.value == null ? null : deliverables.value.find((d) => d.id === viewingId.value) ?? null,
)

/** ADR-044：弹窗内「外部链接」编辑草稿（清空后保存 → 传 url: ''，即清除链接） */
const delUrlDraft = ref('')
const delUrlSaving = ref(false)

function openView(id: number) {
  viewingId.value = id
  // ADR-044：链接编辑草稿按打开瞬间的值播种（之后由用户编辑，不随镜像刷新重播，避免打字被打断）
  delUrlDraft.value = deliverables.value.find((d) => d.id === id)?.url ?? ''
  viewDialog.value = true
}

async function setDelStatus(status: 'ready' | 'todo') {
  const d = viewing.value
  if (!asset.value || !d) return
  // FIX-20261022 / BUG-09：补 catch（含与列表同步：失败不提示成功）
  try {
    await updateAssetDeliverable(asset.value.id, d.id, { status })
    ElMessage.success(status === 'ready' ? '已置为「已就绪」' : '已置为「待完善」')
  } catch (e) {
    showError(e, '状态更新失败')
  }
}

/**
 * ADR-044：保存外部链接。
 * - 校验失败：提示并**不发请求**；
 * - 输入框清空后保存 → `url: ''`（显式清空，而非不传字段，否则后端保留旧值）。
 */
async function saveDelUrl() {
  const a = asset.value
  const d = viewing.value
  if (!a || !d) return
  const id = d.id // 先取 id：成功刷新镜像后 computed 可能已换对象
  const url = delUrlDraft.value.trim()
  const err = checkDeliverableUrl(url)
  if (err) {
    ElMessage.warning(err)
    return
  }
  delUrlSaving.value = true
  try {
    await updateAssetDeliverable(a.id, id, { url })
    delUrlDraft.value = url
    ElMessage.success('链接已保存')
  } catch (e) {
    showError(e, '链接保存失败')
  } finally {
    delUrlSaving.value = false
  }
}

/**
 * ADR-044：删除交付物（ADR-044 §4：入口只在详情弹窗底部左侧，二次确认）。
 * 删除前先把 id / 名称取到本地 —— 成功后镜像刷新，`viewing` 已找不到该对象（再读即 undefined）。
 * 成功后置 `viewingId = null` 并关闭弹窗，避免弹窗指向已删对象。
 */
async function removeDeliverable() {
  const a = asset.value
  const d = viewing.value
  if (!a || !d) return
  const id = d.id
  const name = d.name
  const assetIdNow = a.id
  try {
    await ElMessageBox.confirm(
      `确定删除交付物「${name}」？删除后该交付物的附件文件不再被引用（文件本身保留在文件库，可由管理员清理），此操作不可撤销。`,
      '删除交付物',
      {
        type: 'warning',
        confirmButtonText: '删除',
        confirmButtonClass: 'el-button--danger',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return // 取消 / 关闭 → 无操作
  }
  try {
    await removeAssetDeliverable(assetIdNow, id) // 内部 afterWrite() → 镜像自动刷新
    viewingId.value = null
    viewDialog.value = false
    ElMessage.success('交付物已删除')
  } catch (e) {
    showError(e, '删除失败')
  }
}

// ============================================================
// 交付物附件（ADR-024：每项单文件；交互对齐 create.vue「产品清单」(contractFile)）
// 上传/替换/删除仅 canWrite（editor/admin）；预览所有角色（含 viewer）可用
// ============================================================
const DEL_FILE_EXTS = ['pdf', 'docx', 'png', 'jpg', 'jpeg', 'gif', 'webp']
const delFileInputRef = ref<HTMLInputElement>()
const delFileTarget = ref<AssetDeliverable | null>(null)
const delUploading = ref(false)

function pickDelFile(d: AssetDeliverable) {
  delFileTarget.value = d
  const input = delFileInputRef.value
  if (!input) return
  input.value = ''
  input.click()
}

function onDelFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const d = delFileTarget.value
  const a = asset.value
  if (!file || !d || !a) return
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!DEL_FILE_EXTS.includes(ext)) {
    ElMessage.warning('文件格式不支持：仅允许 PDF、Word（.docx）、图片（不支持 .doc / .xlsx）')
    return
  }
  delUploading.value = true
  uploadFile(file)
    .then(async (res) => {
      await updateAssetDeliverable(a.id, d.id, { file: res.filename })
      ElMessage.success('附件上传成功')
    })
    .catch((err) => showError(err, '附件上传失败'))
    .finally(() => {
      delUploading.value = false
    })
}

async function removeDelFile(d: AssetDeliverable) {
  const a = asset.value
  if (!a) return
  try {
    await ElMessageBox.confirm('移除附件后文件将被一并删除，不可恢复。', '移除附件', { type: 'warning' })
  } catch {
    return
  }
  const stored = d.file
  delUploading.value = true
  try {
    await updateAssetDeliverable(a.id, d.id, { file: '' })
  } catch (err) {
    showError(err, '移除附件失败')
  } finally {
    delUploading.value = false
  }
  if (stored) {
    try {
      await deleteUploadFile(stored)
      ElMessage.success('附件已移除')
    } catch (err) {
      // 后端 400：文件仍被其他记录引用（如产品清单）——字段已清空，物理文件保留
      ElMessage.warning(err instanceof Error ? err.message : '该文件仍被其他记录引用，已清空附件字段，文件未删除')
    }
  }
}

// ADR-024：附件预览（全屏复用 FilePreview，弹窗内自带下载入口；viewer 亦可）
const delPreviewVisible = ref(false)
const delPreviewFile = ref('')
function openDelPreview(filename: string) {
  delPreviewFile.value = filename
  delPreviewVisible.value = true
}

// ============================================================
// 可售明细（ADR-011：仅 type='遥感数据' 显示页签；CRUD 走 rs-items 接口，require_editor）
// PAGE-20261021：列表改服务端分页（tab 首次激活时加载，asset 切换重置）；
// 「已售次数」列改读后端 soldCount，删除前端遍历 contracts 派生
// ============================================================
const rs = reactive({
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  items: [] as RsItemWithSold[],
  loaded: false,
})

/** ADR-038：行级 in-flight 互斥（同购物车 qtyBusy）——请求在飞期间该行开关禁用 */
const rsBusy = reactive<Record<number, boolean>>({})
/** ADR-038：开关显示值的局部副本（按明细 id），不直接改行对象 → 失败可回滚 */
const rsDraft = reactive<Record<number, boolean>>({})
/**
 * RS-STATUS-20261022：行「状态」的局部副本（按明细 id），与 `rsDraft` 同模式、同生命周期。
 * 开关保存成功后由 `PUT /rs-items/{id}` 响应体（已含后端重算后的 status）回写，
 * 缺省回退行快照 `row.status` → 行内状态随开关切换即时更新，不必等分页重拉。
 */
const rsStatusDraft = reactive<Record<number, RsItem['status']>>({})

async function loadRsItems() {
  const a = asset.value
  if (!a) return
  rs.loading = true
  try {
    const res = await listAssetRsItems(a.id, rs.page, rs.pageSize)
    rs.total = res.total
    rs.items = res.items
    // ADR-038：每次加载按服务端值重播种开关副本，消除「弹窗编辑后副本残留旧值」的漂移
    for (const it of res.items) {
      rsDraft[it.id] = it.repeatSale
      // RS-STATUS-20261022：状态副本同批按服务端值重播种（分页接口已返回 status）
      rsStatusDraft[it.id] = it.status
    }
    rs.loaded = true
  } catch (e) {
    showError(e, '加载可售明细失败')
  } finally {
    rs.loading = false
  }
}

function onRsPageChange(page: number) {
  rs.page = page
  loadRsItems()
}

// PAGE-20261021：tab 首次激活时加载对应分页数据（loaded 标记只拉一次，重复进入不重拉）
function ensureTabLoaded() {
  const a = asset.value
  if (!a) return
  if (activeTab.value === 'rsItems' && a.type === '遥感数据' && !rs.loaded) {
    rs.page = 1
    loadRsItems()
  } else if (activeTab.value === 'flows' && !flow.loaded) {
    flow.page = 1
    loadFlows()
  } else if (activeTab.value === 'logs' && !opLog.loaded) {
    opLog.page = 1
    loadOpLogs()
  }
}
watch(activeTab, ensureTabLoaded)
// bootstrap 晚于 tab 切换就绪时补拉（db 刷新后 asset computed 重新求值触发）
watch(asset, ensureTabLoaded)
// PAGE-20261021：切换产品（路由参数变化复用组件）时重置三处分页状态
watch(assetId, () => {
  rs.page = 1
  rs.loaded = false
  rs.items = []
  rs.total = 0
  flow.page = 1
  flow.loaded = false
  flow.items = []
  flow.total = 0
  opLog.page = 1
  opLog.loaded = false
  opLog.items = []
  opLog.total = 0
})

/**
 * FIX-20261022 / BUG-40：页签分页数据「写后失效」修复。
 * PAGE-20261021 把 `loaded` 做成一次性标记（首次进入才拉取，避免重复请求）——但本页的写操作
 * （交付物新增/状态/附件、可售明细 CRUD）都会走 afterWrite 刷新 bootstrap，`db.logs` / `db.flows`
 * 长度随之变化，而页签数据仍是旧快照且 `loaded` 已为 true → 再进页签也不重拉。
 * 现按镜像长度变化重置 loaded：当前正停在该页签则立刻重载，否则下次进入时由 ensureTabLoaded 重拉。
 */
function invalidatePager(state: { loaded: boolean }, load: () => void, tab: string) {
  state.loaded = false
  if (activeTab.value === tab) load()
}
watch(() => db.logs.length, () => invalidatePager(opLog, loadOpLogs, 'logs'))
watch(() => db.flows.length, () => invalidatePager(flow, loadFlows, 'flows'))
// 可售明细同理（本页 CRUD 后已有显式 loadRsItems 重载）：这里只重置 loaded，
// 不立即重拉，避免与 saveRsItem/removeRsItem 的重载叠加成两次请求
watch(() => db.rsItems.length, () => { rs.loaded = false })

/** 精度选项（米） */
const RS_RESOLUTIONS = [0.5, 1, 1.5, 2]

const rsForm = reactive({
  visible: false,
  editing: null as RsItem | null,
  province: '',
  city: '',
  resolution: undefined as number | undefined,
  saleMonth: '',
  price: undefined as number | undefined,
  // 参考价格区间（ADR-021，RSITEM-RANGE-20261020）：选填（可单边），与产品区间同口径
  priceMin: undefined as number | undefined,
  priceMax: undefined as number | undefined,
  // 可重复售卖（ADR-038，RS-REPEAT-20261022）：默认 false = 单次售卖（售出即占用）
  repeatSale: false,
})

function openRsCreate() {
  rsForm.editing = null
  rsForm.province = ''
  rsForm.city = ''
  rsForm.resolution = undefined
  rsForm.saleMonth = ''
  rsForm.price = undefined
  rsForm.priceMin = undefined
  rsForm.priceMax = undefined
  rsForm.repeatSale = false // ADR-038：新增默认关闭（单次售卖）
  rsForm.visible = true
}

function openRsEdit(it: RsItem) {
  rsForm.editing = it
  rsForm.province = it.province
  rsForm.city = it.city
  rsForm.resolution = it.resolution
  rsForm.saleMonth = it.saleMonth
  rsForm.price = it.price
  // ADR-021（RSITEM-RANGE-20261020）：参考区间回显（未设为 null → 输入框留空）
  rsForm.priceMin = it.priceMin ?? undefined
  rsForm.priceMax = it.priceMax ?? undefined
  // ADR-038：回显该明细现有开关值（编辑不改默认，改不改都由用户决定）
  rsForm.repeatSale = it.repeatSale
  rsForm.visible = true
}

async function saveRsItem() {
  if (!asset.value) return
  if (!rsForm.province) {
    ElMessage.warning('请选择省份')
    return
  }
  if (!rsForm.resolution) {
    ElMessage.warning('请选择精度')
    return
  }
  if (!rsForm.saleMonth) {
    ElMessage.warning('请选择月份')
    return
  }
  // ADR-048：明细单价精度由「整数元/份」放宽为「> 0 且最多 6 位小数」
  if (!rsForm.price || rsForm.price <= 0 || !isAmountPrecisionValid(rsForm.price)) {
    ElMessage.warning('单价须大于 0，且最多 6 位小数')
    return
  }
  const data: RsItemInput = {
    province: rsForm.province,
    city: rsForm.city,
    resolution: rsForm.resolution,
    saleMonth: rsForm.saleMonth,
    price: rsForm.price,
    // ADR-021（RSITEM-RANGE-20261020）：参考区间 undefined → null（区分「未设」，含清空场景）
    priceMin: rsForm.priceMin ?? null,
    priceMax: rsForm.priceMax ?? null,
    // ADR-038（RS-REPEAT-20261022）：明细级「可重复售卖」随整行提交；默认 false = 单次售卖
    repeatSale: rsForm.repeatSale,
  }
  try {
    const wasEdit = !!rsForm.editing
    if (wasEdit) {
      await updateRsItem(rsForm.editing!.id, data)
      ElMessage.success('明细已更新')
    } else {
      await addRsItem(asset.value.id, data)
      ElMessage.success('明细已新增')
    }
    rsForm.visible = false
    // PAGE-20261021：CRUD 后重载分页数据（明细按 id ASC 追加，新增后跳末页展示新行）
    if (!wasEdit) rs.page = Math.ceil((rs.total + 1) / rs.pageSize)
    loadRsItems()
  } catch (e) {
    showError(e, '保存失败')
  }
}

/** 开关显示值：优先局部副本（`rsDraft`），缺省 = 行镜像值 */
function rsRepeatValue(row: RsItemWithSold): boolean {
  return rsDraft[row.id] ?? row.repeatSale
}

/** RS-STATUS-20261022：状态显示值：优先局部副本（`rsStatusDraft`）→ 行快照值（只读，不参与写入）；
 * 旧后端/旧快照缺 `status` 时按「可售」降级（与 `isRsItemSoldOut` 的缺省口径一致） */
function rsStatusValue(row: RsItemWithSold): RsItem['status'] {
  return rsStatusDraft[row.id] ?? row.status ?? 'in_stock'
}

/** 整行入参（PUT 整行覆盖：明细字段一个不漏，priceMin/priceMax 未设 → null） */
function rsRowInput(row: RsItem, repeatSale: boolean): RsItemInput {
  return {
    province: row.province,
    city: row.city,
    resolution: row.resolution,
    saleMonth: row.saleMonth,
    price: row.price,
    priceMin: row.priceMin ?? null,
    priceMax: row.priceMax ?? null,
    repeatSale,
  }
}

/**
 * ADR-038（RS-REPEAT-20261022）：列表「可重复售卖」由只读胶囊改为**行内开关**，切换即提交。
 *
 * 一致性三保障（与购物车 `qtyBusy` 同思路，BUG-25）：
 *  1. 局部副本 `rsDraft`：开关显示值读副本（缺省回退行值），**从不直接改 `row.repeatSale`**——
 *     行对象保持首次 GET 的快照不写回，回滚目标取「点击前的显示值」（= 上一次成功落库值）；
 *  2. 行级互斥 `rsBusy`：请求在飞期间该行开关 disabled + loading，防连点与响应乱序
 *     （连续切两次时第二次直接被忽略，最终状态 = 第一次请求的结果）；
 *  3. 成功后按 `db.rsItems`（`updateRsItem` → `afterWrite()` 已刷新镜像）回写副本值，
 *     服务端权威优先，避免本地乐观值覆盖后端实际落库值。
 * 契约 §1：`PUT /rs-items/{id}` 为**整行覆盖**，故开关也走 `rsRowInput(row, next)` 全量提交。
 */
async function toggleRsRepeat(row: RsItemWithSold, val: unknown) {
  const next = val === true
  if (rsBusy[row.id]) return // 本行上一次请求未回：忽略（开关同时 disabled）
  // 提交前的显示值 = 「上一次成功落库值」：在飞期间被 rsBusy 拦住、失败即回滚，
  // 故它既是「无变化」的判据（防重复提交），也是失败时的回滚目标（不能拿 row.repeatSale 当判据，
  // 行对象是首次 GET 的快照、永不回写，否则第二次反向切换会被误判为「无变化」）
  const committed = rsRepeatValue(row)
  if (next === committed) return
  // RS-STATUS-20261022：状态的回滚目标同样取「点击前的显示值」
  const committedStatus = rsStatusValue(row)
  rsBusy[row.id] = true
  rsDraft[row.id] = next // 乐观显示新状态（row 不动，可回滚）
  try {
    const updated = await updateRsItem(row.id, rsRowInput(row, next))
    const mirror = db.rsItems.find((r) => r.id === row.id)
    rsDraft[row.id] = mirror ? mirror.repeatSale : next
    // RS-STATUS-20261022：PUT 响应已含后端重算后的最新 status（切 true → in_stock），
    // 优先用它回写本行状态；镜像（afterWrite 刷新）与旧值依次兜底，避免多等一次分页重拉
    rsStatusDraft[row.id] = updated.status ?? mirror?.status ?? committedStatus
  } catch (e) {
    rsDraft[row.id] = committed // 回滚到上一次成功落库值
    rsStatusDraft[row.id] = committedStatus // 状态同步回滚
    showError(e, '保存失败')
  } finally {
    delete rsBusy[row.id] // 只清自己的行锁（行 id 唯一）
  }
}

async function removeRsItem(it: RsItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除明细「${rsItemName(it)}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteRsItem(it.id)
    ElMessage.success('明细已删除')
    // PAGE-20261021：删除后当前页变空且非第 1 页时回退一页，再重载
    if (rs.items.length <= 1 && rs.page > 1) rs.page -= 1
    loadRsItems()
  } catch (e) {
    // 后端 400「该明细存在销售关联，无法删除」原样 toast
    showError(e, '删除失败')
  }
}

/**
 * 签约主体（ADR-007，三级兜底）：
 * 1. 项目自身 subject（派生：单合同=该合同值，多合同=空）；
 * 2. 为空时取**本行明细所属合同**的 subject（合同内强制同一产品主体，最贴近本行）；
 * 3. 仍无（存量明细 contractId=null）→ 兜底明细产品自身主体；仍无 → '-'。
 */
function projectSubject(p: Project, item: ProjectItem): string {
  if (p.subject) return p.subject
  if (item.contractId) {
    const c = db.contracts.find((c) => c.id === item.contractId)
    if (c?.subject) return c.subject
  }
  const it = item.assetId != null ? item : p.items.find((i) => i.assetId != null)
  const assetId = it?.assetId
  return (assetId != null ? getAsset(assetId)?.subject : '') || '-'
}

/** 合同数（ADR-007）：contractCount 缺失/0 的存量项目按单合同口径显示「1 份合同」 */
function contractCountText(p: Project): string {
  return p.contractCount ? `${p.contractCount} 份销售记录` : '1 份销售记录'
}

/** 流水操作人：空 → -；system → 系统 */
function operatorText(f: AssetFlow): string {
  if (!f.operator) return '-'
  return f.operator === 'system' ? '系统' : f.operator
}
</script>

<template>
  <div class="page-container">
    <template v-if="asset">
      <div class="detail-page">
        <!-- 返回入口 -->
        <a class="back-link" @click="router.push(`/assets/${asset.board}`)">
          <el-icon><ArrowLeft /></el-icon>
          返回{{ boardLabel(asset.board) }}
        </a>

        <!-- 标题 + 元信息 + 动作 -->
        <div class="detail-head">
          <div class="head-left">
            <h1 class="head-title">{{ asset.name }}</h1>
            <div class="head-sub">
              <span>{{ asset.code }}</span>
              <span class="sep">·</span>
              <span>{{ boardLabel(asset.board) }} / {{ asset.type }}</span>
              <template v-if="asset.subject">
                <span class="sep">·</span>
                <span>{{ entityShort(asset.subject) }}</span>
              </template>
              <span class="status-pill" :class="statusPill().cls">
                <span class="dot" aria-hidden="true">{{ statusPill().dot }}</span>
                {{ ASSET_STOCK_STATE[assetStockState(asset)].label }}
              </span>
            </div>
          </div>
          <div class="head-actions" v-if="!isWipBoard()">
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="bottom">
              <span>
                <el-button type="primary" :icon="Edit" :disabled="!canWrite" @click="goEditAsset">
                  编辑产品
                </el-button>
              </span>
            </el-tooltip>
            <!-- ADR-020（PRICING-20261020）：「登记销售」入口已移除，下单统一走购物车 -->
            <el-dropdown trigger="click">
              <span class="more-btn">
                更多
                <el-icon><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="copyCode">复制产品编号</el-dropdown-item>
                  <el-dropdown-item @click="activeTab = 'logs'">查看操作记录</el-dropdown-item>
                  <el-dropdown-item divided :disabled="!canWrite" @click="handleDelete" class="danger-item">
                    <el-icon><Delete /></el-icon>
                    删除产品
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <!-- ADR-041/UI-CLEANUP-20261022：移除页面说明条（用户要求，纯展示删除） -->
        <!-- 六页签 -->
        <el-tabs v-model="activeTab" class="asset-tabs">
          <!-- 1 基本信息：左 2/3 基础资料(1列) + 右 1/3 数量与归属(含可售数量) -->
          <el-tab-pane label="基本信息" name="info">
            <div class="basic-layout">
              <div class="detail-card">
                <div class="card-head">
                  <div class="card-title">基础资料</div>
                </div>
                <div class="info-grid info-grid-1">
                  <div class="info-item">
                    <span class="il">产品名称</span>
                    <span class="iv">{{ asset.name }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">产品编号</span>
                    <span class="iv">{{ asset.code }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">所属板块</span>
                    <span class="iv">{{ boardLabel(asset.board) }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">产品类型</span>
                    <span class="iv">{{ asset.type }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">规格型号</span>
                    <span class="iv">{{ asset.spec || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">计量单位</span>
                    <span class="iv">{{ asset.unit || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">备注</span>
                    <span class="iv">{{ asset.remark || '-' }}</span>
                  </div>
                </div>
              </div>

              <div class="detail-card">
                <div class="card-head">
                  <div class="card-title">数量与归属</div>
                </div>
                <div class="info-grid info-grid-1">
                  <div class="info-item">
                    <span class="il">产品总数</span>
                    <span class="iv">{{ formatAssetQty(asset, asset.quantity) }} {{ asset.unit }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">可售数量</span>
                    <span class="iv">{{ asset.repeatSale ? '不限' : `${formatAssetQty(asset, availableQty(asset))} ${asset.unit}` }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">销售单价</span>
                    <!-- ADR-025（2026-10-21）：包量定价（amount 模式）统一走百万Token 口径（与列表列同口径） -->
                    <!-- ADR-018（PRICING-20261020）：有参考区间时追加区间提示（与列表列同口径） -->
                    <span class="iv">
                      <template v-if="isAmountMode(asset)">{{ asset.salePrice ? displayUnitPrice(asset) : '-' }}</template>
                      <template v-else>{{ asset.salePrice ? formatMoney(asset.salePrice) : '-' }}<template v-if="asset.repeatSale"> / {{ asset.unit }}</template></template>
                      <template v-if="priceRangeText(asset)">（参考区间 {{ priceRangeText(asset) }}）</template>
                    </span>
                  </div>
                  <div class="info-item">
                    <span class="il">登记时间</span>
                    <span class="iv">{{ asset.inboundDate || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">到期时间</span>
                    <span class="iv">{{ expiryText(asset) }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">归属主体</span>
                    <span class="iv">{{ asset.subject || '-' }}</span>
                  </div>
                </div>
                <!-- ADR-041/UI-CLEANUP-20261022：移除基础信息说明条（用户要求，纯展示删除） -->
              </div>
            </div>
          </el-tab-pane>

          <!-- 1.5 可售明细（ADR-011：仅遥感数据父产品显示；CRUD 明细；PAGE-20261021：服务端分页） -->
          <el-tab-pane v-if="asset.type === '遥感数据'" :label="`可售明细（${rs.total}）`" name="rsItems">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">可售明细</div>
                  <!-- ADR-038（RS-REPEAT-20261022）：默认单次售卖；开启后只计次不扣量；
                       RS-STATUS-20261022：补「可售数量」口径说明（= 状态为可售的明细条数） -->
                  <div class="card-desc">按 省/精度/月份 维护可售卖明细，每份明细独立计价（元/份，最多 6 位小数）；<b>默认为单次售卖</b>（售出即占用），开启「可重复售卖」后只计次不扣量；<b>可售数量 = 状态为「可售」的明细条数</b>。</div>
                </div>
                <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="bottom">
                  <span>
                    <el-button type="primary" size="small" :icon="Plus" :disabled="!canWrite" @click="openRsCreate">
                      新增明细
                    </el-button>
                  </span>
                </el-tooltip>
              </div>
              <el-table v-if="rs.loading || rs.items.length" v-loading="rs.loading" :data="rs.items" border stripe>
                <!-- RS-STATUS-20261022：新增「状态」列后本表列宽重新配平（省/市 180→170、单价 150→140，
                     合计 950px），1280 视口（侧栏 220 + 页边距 24×2 + 卡片内距 18×2）下不出横向滚动条 -->
                <el-table-column label="省 / 市" min-width="170" align="left">
                  <template #default="{ row }">{{ row.city ? `${row.province} / ${row.city}` : row.province }}</template>
                </el-table-column>
                <el-table-column label="精度" width="90" align="center">
                  <template #default="{ row }">{{ row.resolution }}m</template>
                </el-table-column>
                <el-table-column label="月份" width="110" align="center" prop="saleMonth" />
                <el-table-column label="单价" width="140" align="center" show-overflow-tooltip>
                  <!-- ADR-021（RSITEM-RANGE-20261020）：有参考区间时追加「（参考区间 {min}~{max}）」；无区间维持原展示（与产品价同口径） -->
                  <template #default="{ row }">
                    {{ formatMoney(row.price) }}<template v-if="priceRangeText(row)">（参考区间 {{ priceRangeText(row) }}）</template>
                  </template>
                </el-table-column>
                <!-- RS-STATUS-20261022：明细状态**只读展示**（后端按 repeatSale + 有效合同引用维护），
                     不承载操作——切换仍是右侧「可重复售卖」开关；颜色走既有 tag 类型（success/info），不新增色值 -->
                <el-table-column label="状态" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag :type="tagInfo(RS_ITEM_STATUS, rsStatusValue(row)).tag" size="small" effect="light">
                      {{ tagInfo(RS_ITEM_STATUS, rsStatusValue(row)).label }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="可重复售卖" width="130" align="center">
                  <template #default="{ row }">
                    <!-- ADR-038（RS-REPEAT-20261022）：只读胶囊 → 行内开关，切换即 PUT 整行；
                         请求在飞期间该行开关禁用（rsBusy，防连点/响应乱序），失败回滚 + 提示 -->
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                      <span class="rs-toggle-cell">
                        <el-switch
                          :model-value="rsRepeatValue(row)"
                          size="small"
                          :loading="!!rsBusy[row.id]"
                          :disabled="!canWrite || !!rsBusy[row.id]"
                          @change="toggleRsRepeat(row, $event)"
                        />
                        <span class="rs-toggle-text">{{ rsRepeatValue(row) ? '重复售卖' : '单次' }}</span>
                      </span>
                    </el-tooltip>
                  </template>
                </el-table-column>
                <el-table-column label="已售次数" width="100" align="center">
                  <!-- PAGE-20261021：改读后端 soldCount（原前端遍历 contracts 派生已删除） -->
                  <template #default="{ row }">{{ row.soldCount }}</template>
                </el-table-column>
                <el-table-column label="操作" width="120" align="center">
                  <template #default="{ row }">
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button link type="primary" size="small" :disabled="!canWrite" @click="openRsEdit(row)">
                          编辑
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button link type="danger" size="small" :disabled="!canWrite" @click="removeRsItem(row)">
                          删除
                        </el-button>
                      </span>
                    </el-tooltip>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-if="!rs.loading && !rs.items.length" description="暂无可售明细" :image-size="70">
                <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                  <span>
                    <el-button type="primary" size="small" :icon="Plus" :disabled="!canWrite" @click="openRsCreate">
                      新增明细
                    </el-button>
                  </span>
                </el-tooltip>
              </el-empty>
              <!-- PAGE-20261021：服务端分页（el-pagination 照 settings/users.vue 先例） -->
              <div v-if="rs.total > 0" class="pagination">
                <el-pagination
                  v-model:current-page="rs.page"
                  :page-size="rs.pageSize"
                  :total="rs.total"
                  layout="total, prev, pager, next"
                  @current-change="onRsPageChange"
                />
              </div>
            </div>
          </el-tab-pane>

          <!-- 2 交付物 -->
          <el-tab-pane :label="`交付物（${deliverables.length}）`" name="deliverables">
            <!-- ADR-024：交付物附件上传（隐藏 input，accept 仅 .pdf/.docx/图片，禁 .doc/.xlsx；行上操作，新增对话框不带附件） -->
            <input
              ref="delFileInputRef"
              type="file"
              accept=".pdf,.docx,.png,.jpg,.jpeg,.gif,.webp"
              style="display: none"
              @change="onDelFilePicked"
            />
            <div class="stat-cards del-stats">
              <div class="stat-card">
                <div>
                  <div class="s-label">标准交付物</div>
                  <div class="s-value">{{ delStats.total }}</div>
                  <div class="s-sub">面向每套产品默认交付</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><Tickets /></el-icon>
              </div>
              <div class="stat-card">
                <div>
                  <div class="s-label">已就绪</div>
                  <div class="s-value">{{ delStats.ready }}</div>
                  <div class="s-sub">可随项目交付</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><CircleCheck /></el-icon>
              </div>
              <div class="stat-card">
                <div>
                  <div class="s-label">最近更新</div>
                  <div class="s-value s-value-sm">{{ delStats.latest }}</div>
                  <div class="s-sub">交付物最近更新日期</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><Operation /></el-icon>
              </div>
            </div>

            <div class="deliver-layout">
              <div class="detail-card">
                <div class="card-head">
                  <div>
                    <div class="card-title">交付物清单</div>
                    <div class="card-desc">交付包是产品的标准材料集合；项目交付时选择版本并生成交付记录。</div>
                  </div>
                  <div class="dl-head-actions">
                    <el-select v-model="catFilter" placeholder="全部类型" clearable style="width: 130px;">
                      <el-option
                        v-for="(c, k) in DELIVERABLE_CATEGORIES"
                        :key="k"
                        :label="c.label"
                        :value="k"
                      />
                    </el-select>
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="bottom">
                      <span>
                        <el-button
                          v-if="!isWipBoard()"
                          plain
                          size="small"
                          :icon="Plus"
                          :disabled="!canWrite"
                          @click="openDelCreate"
                        >
                          新增
                        </el-button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>

                <div class="dl-list">
                  <div
                    v-for="d in filteredDels"
                    :key="d.id"
                    class="dl-row"
                    @click="openView(d.id)"
                  >
                    <span class="cat-icon" :class="CAT_ICON[d.category].cls" aria-hidden="true">
                      <el-icon><component :is="CAT_ICON[d.category].icon" /></el-icon>
                    </span>
                    <div class="dl-main">
                      <div class="dl-name">
                        {{ d.name }}
                        <el-tag v-if="d.required" size="small" type="primary" effect="plain" class="req-tag">必选</el-tag>
                      </div>
                      <div class="dl-meta muted">
                        {{ DELIVERABLE_CATEGORIES[d.category].label }} · {{ d.version }} · {{ d.meta }} · 更新于 {{ d.updatedAt }}
                      </div>
                      <!-- ADR-044：外部链接（仅 url 非空时渲染；rel 防 window.opener 劫持；@click.stop 不触发行点击） -->
                      <div v-if="d.url" class="dl-extlink" @click.stop>
                        <el-icon class="dl-extlink-ic" aria-hidden="true"><TopRight /></el-icon>
                        <a
                          class="dl-extlink-a"
                          :href="d.url"
                          :title="d.url"
                          target="_blank"
                          rel="noopener noreferrer"
                        >{{ d.url }}</a>
                      </div>
                    </div>
                    <div class="dl-right">
                      <template v-if="!d.file">
                        <!-- ADR-024：单文件附件——无附件显示「上传」（仅 canWrite）；有附件显示原名 + 预览 + 删除（canWrite） -->
                        <template v-if="canWrite">
                          <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                            <el-button
                              link
                              type="primary"
                              size="small"
                              :icon="Upload"
                              :loading="delUploading"
                              @click.stop="pickDelFile(d)"
                            >
                              上传
                            </el-button>
                          </el-tooltip>
                        </template>
                        <span v-else class="dl-file-none muted">无附件</span>
                      </template>
                      <template v-else>
                        <a class="dl-file-name" :title="fileDisplayName(d.file)" @click.stop="openDelPreview(d.file as string)">
                          {{ fileDisplayName(d.file) }}
                        </a>
                        <el-button link type="primary" size="small" @click.stop="openDelPreview(d.file as string)">
                          预览
                        </el-button>
                        <el-button
                          v-if="canWrite"
                          link
                          type="danger"
                          size="small"
                          :loading="delUploading"
                          @click.stop="removeDelFile(d)"
                        >
                          删除
                        </el-button>
                      </template>
                      <span class="dl-pill" :class="d.status === 'ready' ? 'ok' : 'wip'">
                        {{ d.status === 'ready' ? '已就绪' : '待完善' }}
                      </span>
                    </div>
                  </div>
                  <el-empty v-if="!filteredDels.length" description="暂无匹配的交付物" :image-size="60" />
                </div>
              </div>

              <!-- 右侧交付说明窄栏 -->
              <div class="detail-card side-card">
                <div class="card-title">交付说明</div>
                <div class="card-desc" style="margin-bottom: 12px;">销售项目确认后选择实际交付范围</div>
                <div class="step-timeline">
                  <div class="step" v-for="(s, i) in DELIVERY_STEPS" :key="s.t">
                    <span class="step-dot" :class="{ last: i === DELIVERY_STEPS.length - 1 }" aria-hidden="true"></span>
                    <div class="step-title">{{ s.t }}</div>
                    <div class="step-desc muted">{{ s.d }}</div>
                  </div>
                </div>
                <div class="scope-title" v-if="defaultScope.length">默认交付范围</div>
                <div v-if="defaultScope.length" class="scope-list">
                  <div v-for="s in defaultScope" :key="s.label" class="scope-row">
                    <span class="scope-label muted">{{ s.label }}</span>
                    <span class="scope-names">{{ s.names.join('、') }}</span>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 3 销售关联 -->
          <el-tab-pane :label="`销售关联（${salesLinks.length}）`" name="sales">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">关联销售项目</div>
                  <!-- ADR-020（PRICING-20261020）：下单入口统一购物车，文案同步 -->
                  <div class="card-desc">购物车下单时按明细锁定数量或记录售卖；项目「交付完成」后自动扣减并生成交付记录。</div>
                </div>
                <span class="muted" style="font-size: 12px;">共 {{ salesLinks.length }} 条</span>
              </div>
              <el-table v-if="salesLinks.length" :data="salesLinks">
                <el-table-column label="项目名称" min-width="200">
                  <template #default="{ row }">
                    <a class="link" @click="router.push(`/sales/projects/${row.project.id}/detail`)">{{ row.project.name }}</a>
                    <div class="muted" style="font-size: 12px;">{{ row.project.code }} · {{ contractCountText(row.project) }}</div>
                  </template>
                </el-table-column>
                <el-table-column prop="project.customer" label="客户名称" width="150" show-overflow-tooltip />
                <el-table-column label="生态人员" width="110" align="left">
                  <!-- 2026-10-20（问题12b）：rep 存 username，走姓名映射显示（与项目页 repName 同口径） -->
                  <template #default="{ row }">{{ repName(row.project.rep) }}</template>
                </el-table-column>
                <el-table-column label="签约主体" width="130" align="left">
                  <template #default="{ row }">{{ entityShort(projectSubject(row.project, row.item)) }}</template>
                </el-table-column>
                <el-table-column label="关联数量" width="120" align="right">
                  <template #default="{ row }">{{ formatAssetQty(asset, row.item.qty) }} {{ row.item.unit }}</template>
                </el-table-column>
                <el-table-column label="销售金额" width="120" align="right">
                  <template #default="{ row }">{{ formatMoney(row.item.amount) }}</template>
                </el-table-column>
                <el-table-column label="当前状态" width="110" align="center">
                  <template #default="{ row }">
                    <el-tag :type="tagInfo(PROJECT_STATUS, row.project.status).tag" size="small" effect="plain">
                      {{ tagInfo(PROJECT_STATUS, row.project.status).label }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="关联日期" width="120" align="left">
                  <template #default="{ row }">{{ row.item.lockedDate || '-' }}</template>
                </el-table-column>
              </el-table>
              <div v-else class="empty-compact">
                <el-icon class="empty-icon" aria-hidden="true"><Link /></el-icon>
                <div class="empty-title">暂无销售关联</div>
                <!-- ADR-020（PRICING-20261020）：下单入口统一购物车，空状态仅文字提示 -->
                <div class="empty-desc muted">暂无关联，请通过购物车下单。下单后关联产品会在这里显示，并自动更新锁定数量和销售金额。</div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 4 数量流水（PAGE-20261021：服务端分页） -->
          <el-tab-pane :label="`数量流水（${flow.total}）`" name="flows">
            <div class="detail-card" v-loading="flow.loading">
              <div class="card-head">
                <div>
                  <div class="card-title">数量流水</div>
                  <!-- PAGE-20261021：后端分页接口不支持 type 参数，类型过滤仅作用于当前页 -->
                  <div class="card-desc">登记、锁定、交付、调整与撤销均留痕，审计记录不可删除。按类型过滤仅作用于当前页。</div>
                </div>
                <el-radio-group v-model="flowFilter" size="small">
                  <el-radio-button value="all">全部流水</el-radio-button>
                  <el-radio-button value="purchase_in">登记</el-radio-button>
                  <el-radio-button value="project_lock">项目锁定</el-radio-button>
                  <el-radio-button value="sale_out">销售交付</el-radio-button>
                  <el-radio-button value="adjust">调整记录</el-radio-button>
                </el-radio-group>
              </div>

              <div v-if="filteredFlows.length" class="flow-list">
                <div v-for="f in filteredFlows" :key="f.id" class="flow-item">
                  <div class="fl-date muted">{{ f.date }}</div>
                  <div class="fl-main">
                    <div class="fl-title">
                      <span class="fl-dot" :class="FLOW_CLS[f.type]" aria-hidden="true"></span>
                      {{ FLOW_TYPES[f.type].label }}
                      <span class="fl-operator muted">操作人：{{ operatorText(f) }}</span>
                    </div>
                    <div class="fl-desc">
                      {{ asset.name }} · {{ FLOW_TYPES[f.type].label }} {{ formatAssetQty(asset, f.qty) }} {{ f.unit }}
                      <template v-if="f.amount"> · 金额 {{ formatMoney(f.amount) }}</template>
                    </div>
                    <div class="fl-meta muted">
                      <template v-if="f.ref">关联单号：{{ f.ref }}</template>
                      <template v-if="f.ref && f.note"> · </template>
                      <template v-if="f.note">{{ f.note }}</template>
                    </div>
                  </div>
                </div>
              </div>
              <el-empty v-if="!flow.loading && !filteredFlows.length" description="暂无流水" :image-size="70" />
              <!-- PAGE-20261021：服务端分页（el-pagination 照 settings/users.vue 先例）
                   FIX-20261022 / BUG-40：类型筛选仅作用于当前页 → 筛选态隐藏全量 total
                   （避免「筛选 0 条却显示共 37 条」；口径说明见卡头 desc） -->
              <div v-if="flow.total > 0" class="pagination">
                <el-pagination
                  v-model:current-page="flow.page"
                  :page-size="flow.pageSize"
                  :total="flow.total"
                  :layout="flowFilter === 'all' ? 'total, prev, pager, next' : 'prev, pager, next'"
                  @current-change="onFlowPageChange"
                />
              </div>
            </div>
          </el-tab-pane>

          <!-- 5 操作记录（PAGE-20261021：服务端分页） -->
          <el-tab-pane :label="`操作记录（${opLog.total}）`" name="logs">
            <div class="detail-card" v-loading="opLog.loading">
              <div class="card-head">
                <div>
                  <div class="card-title">操作记录</div>
                  <div class="card-desc">产品创建、状态变更、编辑与删除的审计留痕，不提供编辑或删除。</div>
                </div>
                <!-- PAGE-20261021：总数改用分页接口 total -->
                <span class="muted" style="font-size: 12px;">共 {{ opLog.total }} 条</span>
              </div>
              <!-- 接口按 id DESC 返回，无需再 reverse -->
              <el-timeline v-if="opLog.items.length">
                <el-timeline-item
                  v-for="log in opLog.items"
                  :key="log.id"
                  :timestamp="`${log.time} · ${log.operator}`"
                  placement="top"
                >
                  <div class="log-action">{{ log.action }}</div>
                  <div v-if="log.changes" class="log-changes muted">{{ translateFileNames(log.changes) }}</div>
                  <div class="log-detail muted">{{ log.detail }}</div>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-if="!opLog.loading && !opLog.items.length" description="暂无操作记录" :image-size="70" />
              <!-- PAGE-20261021：服务端分页（el-pagination 照 settings/users.vue 先例） -->
              <div v-if="opLog.total > 0" class="pagination">
                <el-pagination
                  v-model:current-page="opLog.page"
                  :page-size="opLog.pageSize"
                  :total="opLog.total"
                  layout="total, prev, pager, next"
                  @current-change="onOpLogPageChange"
                />
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 新增交付物对话框 -->
      <el-dialog
        v-model="delCreate.visible"
        :title="`新增交付物 · ${asset.name}`"
        class="dlg-form"
        :close-on-click-modal="false"
      >
        <el-form label-width="96px">
          <el-form-item label="交付物名称" required>
            <el-input v-model="delCreate.form.name" placeholder="如：部署与运维手册" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="delCreate.form.category" style="width: 100%;">
              <el-option
                v-for="(c, k) in DELIVERABLE_CATEGORIES"
                :key="k"
                :label="c.label"
                :value="k"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="默认必选">
            <el-switch v-model="delCreate.form.required" />
            <span class="muted" style="font-size: 12px; margin-left: 8px;">必选项随项目交付默认勾选</span>
          </el-form-item>
          <el-form-item label="适用说明">
            <el-input v-model="delCreate.form.note" type="textarea" :rows="2" placeholder="版本 / 格式 / 适用范围" />
          </el-form-item>
          <!-- ADR-044：外部链接（选填，仅 http/https；与附件可并存） -->
          <el-form-item label="外部链接">
            <div style="width: 100%;">
              <el-input v-model="delCreate.form.url" placeholder="https://…" clearable />
              <div class="muted" style="font-size: 12px; line-height: 18px; margin-top: 4px;">
                可填写交付物的外部地址（在线文档/网盘/下载页）；也可只上传附件，两者可并存。
              </div>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="delCreate.visible = false">取消</el-button>
          <el-button type="primary" @click="confirmDel">确定</el-button>
        </template>
      </el-dialog>

      <!-- 交付物详情 -->
      <el-dialog v-model="viewDialog" title="交付物详情" width="560px" :close-on-click-modal="false">
        <template v-if="viewing">
          <div class="dl-detail-head">
            <span class="cat-icon" :class="CAT_ICON[viewing.category].cls" aria-hidden="true">
              <el-icon><component :is="CAT_ICON[viewing.category].icon" /></el-icon>
            </span>
            <div style="flex: 1; min-width: 0;">
              <div class="dl-name">{{ viewing.name }}</div>
              <div class="dl-meta muted">
                {{ DELIVERABLE_CATEGORIES[viewing.category].label }} · {{ viewing.version }}
              </div>
            </div>
            <span class="dl-pill" :class="viewing.status === 'ready' ? 'ok' : 'wip'">
              {{ viewing.status === 'ready' ? '已就绪' : '待完善' }}
            </span>
          </div>
          <div class="info-grid info-grid-1" style="margin-top: 14px;">
            <div class="info-item span-3">
              <span class="il">适用说明</span>
              <span class="iv">{{ viewing.meta }}</span>
            </div>
            <div class="info-item span-3">
              <span class="il">默认交付</span>
              <span class="iv">{{ viewing.required ? '必选（默认勾选，不可移除）' : '可选' }}</span>
            </div>
            <div class="info-item span-3">
              <span class="il">最近更新</span>
              <span class="iv">{{ viewing.updatedAt }}</span>
            </div>
          </div>
          <div class="info-bar" style="margin-top: 12px;">
            <el-icon aria-hidden="true"><InfoFilled /></el-icon>
            <span>已被项目引用的版本不可直接覆盖，应新增新版本。</span>
          </div>
          <!-- ADR-044：外部链接（仅 url 非空时渲染链接；canWrite 可编辑，清空后保存 = 清除） -->
          <div class="dl-url-block">
            <div class="dl-url-row">
              <span class="dl-url-label muted">外部链接</span>
              <a
                v-if="viewing.url"
                class="dl-extlink-a"
                :href="viewing.url"
                :title="viewing.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                <el-icon class="dl-extlink-ic" aria-hidden="true"><TopRight /></el-icon>
                <span class="dl-extlink-txt">{{ viewing.url }}</span>
              </a>
              <span v-else class="dl-url-none muted">未填写</span>
            </div>
            <div v-if="canWrite" class="dl-url-edit">
              <el-input
                v-model="delUrlDraft"
                placeholder="https://…"
                clearable
                @keyup.enter="saveDelUrl"
              />
              <el-button type="primary" plain :loading="delUrlSaving" @click="saveDelUrl">保存</el-button>
            </div>
          </div>
        </template>
        <template #footer>
          <div class="dl-detail-footer">
            <el-button v-if="viewing && canWrite" type="danger" plain @click="removeDeliverable">
              删除交付物
            </el-button>
            <div class="dl-detail-footer-right">
              <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                <el-button
                  v-if="viewing && viewing.status !== 'ready'"
                  type="primary"
                  :disabled="!canWrite"
                  @click="setDelStatus('ready')"
                >
                  标记就绪
                </el-button>
              </el-tooltip>
              <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                <el-button
                  v-if="viewing && viewing.status === 'ready'"
                  :disabled="!canWrite"
                  @click="setDelStatus('todo')"
                >
                  退回待完善
                </el-button>
              </el-tooltip>
              <el-button @click="viewDialog = false">关闭</el-button>
            </div>
          </div>
        </template>
      </el-dialog>

      <!-- ADR-024：交付物附件预览（全屏复用 FilePreview，弹窗内自带下载入口） -->
      <el-dialog v-model="delPreviewVisible" title="交付物附件预览" fullscreen append-to-body destroy-on-close>
        <FilePreview v-if="delPreviewVisible && delPreviewFile" :filename="delPreviewFile" />
      </el-dialog>

      <!-- ADR-011：新增 / 编辑可售明细 -->
      <el-dialog
        v-model="rsForm.visible"
        :title="rsForm.editing ? `编辑明细 · ${asset.name}` : `新增明细 · ${asset.name}`"
        class="dlg-form"
        :close-on-click-modal="false"
      >
        <el-form label-width="96px">
          <el-form-item label="省份" required>
            <el-select v-model="rsForm.province" placeholder="选择省 / 自治区 / 直辖市" style="width: 100%;">
              <el-option v-for="p in PROVINCES" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
          <el-form-item label="城市">
            <el-input v-model="rsForm.city" placeholder="选填，如：石家庄市" />
          </el-form-item>
          <el-form-item label="精度" required>
            <el-select v-model="rsForm.resolution" placeholder="选择精度" style="width: 100%;">
              <el-option v-for="r in RS_RESOLUTIONS" :key="r" :label="`${r}m`" :value="r" />
            </el-select>
          </el-form-item>
          <el-form-item label="月份" required>
            <el-date-picker
              v-model="rsForm.saleMonth"
              type="month"
              value-format="YYYY-MM"
              placeholder="选择售卖月份"
              style="width: 100%;"
            />
          </el-form-item>
          <el-form-item label="单价（元）" required>
            <!-- ADR-048：明细单价支持最多 6 位小数（原整数元/份） -->
            <el-input-number
              v-model="rsForm.price"
              :min="0"
              :controls="false"
              :formatter="amountInputFormatter"
              :parser="amountInputParser"
              placeholder="元/份，最多 6 位小数"
              style="width: 100%;"
            />
            <div class="dlg-hint">元/份，须大于 0，最多 6 位小数</div>
          </el-form-item>
          <!-- ADR-021（RSITEM-RANGE-20261020）：参考价格区间——元/份，选填（可单边）；
               ADR-049（2026-10-29）：下单时**只校验下限**（低于下限 400，高于上限不拦截），
               商务审核改价不受区间约束；交互/样式与产品区间一致 -->
          <el-form-item label="参考价格区间（元）">
            <div class="price-range-row">
              <el-input-number v-model="rsForm.priceMin" :min="0" :controls="false" :formatter="amountInputFormatter" :parser="amountInputParser" placeholder="下限（选填）" style="width: 100%;" />
              <span class="muted price-range-sep">~</span>
              <el-input-number v-model="rsForm.priceMax" :min="0" :controls="false" :formatter="amountInputFormatter" :parser="amountInputParser" placeholder="上限（选填）" style="width: 100%;" />
            </div>
            <div class="muted" style="font-size: 12px; margin-top: 4px;">
              元/份，选填（可只填一边）；下单时用于校验单价下限（上限不限制），未设置则不限制
            </div>
          </el-form-item>
          <!-- ADR-038（RS-REPEAT-20261022）：明细级「可重复售卖」，默认关闭 = 单次售卖；
               RS-STATUS-20261022：弹窗内不手工选状态（状态由系统维护），仅补一行状态口径说明 -->
          <el-form-item label="可重复售卖">
            <el-switch v-model="rsForm.repeatSale" />
            <div class="dlg-hint" style="width: 100%;">
              开启后该明细不会被标为「已售罄」（只计次）；关闭时售出/锁定即置为「已售罄」
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="rsForm.visible = false">取消</el-button>
          <el-button type="primary" @click="saveRsItem">确定</el-button>
        </template>
      </el-dialog>
    </template>

    <!-- 未找到产品：空态 + 返回列表（避免直达无效 URL 时白屏） -->
    <el-empty v-else description="未找到该产品" :image-size="80">
      <el-button type="primary" @click="router.push('/assets/embodied')">返回产品台账</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
/* 主体限宽 1180px 居中 */
.detail-page {
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ============ 头部 ============ */
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}
.head-left {
  min-width: 0;
}
.head-title {
  margin: 2px 0 8px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}
.head-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--text-secondary);
  font-size: 13px;
}
.head-sub .sep {
  color: #c3d2e6;
}
.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
/* 「更多」文字按钮（非描边按钮） */
.more-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  border-radius: 6px;
}
.more-btn:hover {
  color: var(--primary-color);
  background: var(--primary-light);
}
/* ADR-040（2026-10-22）：此处原有 scoped `:deep(.el-dropdown-menu .danger-item)`（编译为
   [data-v-x] .el-dropdown-menu .danger-item）无法命中 teleport 到 body 的 dropdown popper，
   属"看起来有样式其实没有"的死规则，已移至 styles/global.css 全局定义
   （.el-dropdown-menu__item.danger-item），本组件模板内仍保留 item 的 class="danger-item"。 */

/* 状态点胶囊 */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.status-pill .dot {
  font-size: 10px;
}
.status-pill.ok {
  color: #0c7b51;
  background: #eaf8f1;
}
.status-pill.off {
  color: #c62828;
  background: #fdecea;
}

/* 可售明细「可重复售卖」行内开关（ADR-038）：开关 + 状态文字，行高与既有单元格一致（18px 行高，不加内边距） */
.rs-toggle-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  /* 与原胶囊（18px 行高 + 2px 上下内边距 = 22px）等高，保证表格行高不变 */
  min-height: 22px;
}
.rs-toggle-text {
  font-size: 12px;
  line-height: 18px;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* ============ 页签 ============ */
.asset-tabs {
  background: transparent;
}
:deep(.el-tabs__header) {
  margin-bottom: 18px;
}
:deep(.el-tabs__item) {
  font-size: 13px;
  height: 40px;
}
:deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
:deep(.el-tab-pane) > .stat-cards {
  margin-bottom: 0;
}

/* 页签内白卡 */
.detail-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.card-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* ============ 基本信息：2/3 + 1/3 双栏 ============ */
.basic-layout {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 14px;
  align-items: stretch;
}
@media (max-width: 999px) {
  .basic-layout {
    grid-template-columns: 1fr;
  }
}
.ig-2 {
  grid-template-columns: repeat(2, 1fr);
}
@media (max-width: 680px) {
  .ig-2 {
    grid-template-columns: 1fr;
  }
  .ig-2 .info-item.span-2 {
    grid-column: span 1;
  }
}
/* ADR-041/UI-CLEANUP-20261022：基础信息说明条专用浅底变体（soft）唯一使用点已删 → 死样式同步移除 */

/* 序列号空态 */
.serial-empty {
  font-size: 13px;
  padding: 14px 4px;
  text-align: center;
}

/* ============ 交付物 ============ */
.del-stats {
  grid-template-columns: repeat(3, 1fr);
}
@media (max-width: 680px) {
  .del-stats {
    grid-template-columns: 1fr;
  }
}
.s-value-sm {
  font-size: 18px;
}

.deliver-layout {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 12px;
  align-items: start;
}
@media (max-width: 999px) {
  .deliver-layout {
    grid-template-columns: 1fr;
  }
}
.side-card {
  position: sticky;
  top: 8px;
}

.dl-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 清单项：横向信息行 */
.dl-list {
  display: flex;
  flex-direction: column;
}
.dl-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 8px;
  border-bottom: 1px solid var(--divider-color);
  cursor: pointer;
  border-radius: 6px;
}
.dl-row:hover {
  background: var(--row-hover);
}
.dl-row:last-child {
  border-bottom: none;
}
.dl-main {
  flex: 1;
  min-width: 0;
}
.dl-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dl-meta {
  font-size: 12px;
  margin-top: 3px;
}
.dl-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.dl-link {
  font-size: 13px;
  color: var(--primary-color);
  cursor: pointer;
  white-space: nowrap;
}
.dl-link:hover {
  color: var(--primary-hover);
}
.dl-pill {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.dl-pill.ok {
  color: #0c7b51;
  background: #eaf8f1;
}
.dl-pill.wip {
  color: #a86514;
  background: #fff5e7;
}
/* ADR-024：交付物附件（文字链接/文字按钮，复用平台 token，无新颜色与圆角） */
.dl-file-name {
  font-size: 13px;
  color: var(--primary-color);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dl-file-name:hover {
  text-decoration: underline;
}
.dl-file-none {
  font-size: 12px;
}

/* ADR-044：外部链接（复用 --primary-color，无新色值/圆角；超长省略，title 显示完整 URL） */
.dl-extlink {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  font-size: 12px;
  min-width: 0;
}
.dl-extlink-ic {
  color: var(--primary-color);
  flex-shrink: 0;
}
.dl-extlink-a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--primary-color);
  font-size: 12px;
  min-width: 0;
  text-decoration: none;
}
.dl-extlink-a:hover {
  text-decoration: underline;
}
.dl-extlink-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}
/* 详情弹窗：链接展示 + 编辑行 */
.dl-url-block {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--divider-color);
}
.dl-url-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.dl-url-label {
  font-size: 12px;
  flex-shrink: 0;
}
.dl-url-none {
  font-size: 12px;
}
.dl-url-edit {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
/* 弹窗底部：左侧删除、右侧既有动作 */
.dl-detail-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.dl-detail-footer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* 分类图标 */
.cat-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.cat-icon.blue {
  background: #eaf3ff;
  color: #1769d4;
}
.cat-icon.green {
  background: #eaf8f1;
  color: #0c7b51;
}
.cat-icon.purple {
  background: #eef0ff;
  color: #4e63a8;
}
.cat-icon.neutral {
  background: #eef2f8;
  color: #71829a;
}

/* 右侧说明栏时间线 */
.step-timeline {
  position: relative;
  padding-left: 14px;
  margin-bottom: 16px;
}
.step {
  position: relative;
  padding-bottom: 14px;
}
.step:last-child {
  padding-bottom: 0;
}
.step::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 6px;
  bottom: 0;
  width: 1px;
  background: var(--border-color);
}
.step:last-child::before {
  display: none;
}
.step-dot {
  position: absolute;
  left: -17px;
  top: 3px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary-color);
}
.step-dot.last {
  background: #c3d2e6;
}
.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.step-desc {
  font-size: 12px;
  margin-top: 3px;
  line-height: 1.5;
}

.scope-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.scope-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.scope-row {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.scope-names {
  color: var(--text-body);
}

.dl-detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ============ 销售关联空状态 ============ */
.empty-compact {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 16px;
  text-align: center;
}
.empty-icon {
  font-size: 34px;
  color: #c9d6e8;
}
.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.empty-desc {
  font-size: 13px;
  max-width: 420px;
  line-height: 1.6;
}
.empty-compact .el-button {
  margin-top: 6px;
}
.link {
  color: var(--primary-color);
  font-weight: 500;
  cursor: pointer;
}
.link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}

/* ============ 数量流水时间线 ============ */
.flow-list {
  display: flex;
  flex-direction: column;
}
.flow-item {
  display: flex;
  gap: 16px;
  padding: 14px 4px;
  border-bottom: 1px solid var(--divider-color);
}
.flow-item:last-child {
  border-bottom: none;
}
.fl-date {
  flex-shrink: 0;
  width: 86px;
  font-size: 13px;
  padding-top: 1px;
}
.fl-main {
  flex: 1;
  min-width: 0;
}
.fl-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.fl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.fl-dot.blue {
  background: #1769d4;
}
.fl-dot.green {
  background: #0c7b51;
}
.fl-dot.gray {
  background: #71829a;
}
.fl-dot.orange {
  background: #a86514;
}
.fl-operator {
  margin-left: 4px;
  font-size: 12px;
  font-weight: 400;
}
.fl-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-body);
}
.fl-meta {
  margin-top: 3px;
  font-size: 12px;
}
@media (max-width: 680px) {
  .flow-item {
    flex-wrap: wrap;
  }
  .fl-date {
    width: 100%;
  }
}

/* ============ 操作记录 ============ */
.log-action {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.log-changes {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.6;
}
.log-detail {
  margin-top: 3px;
  font-size: 13px;
  line-height: 1.6;
}

.status-radios {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

/* ADR-021（RSITEM-RANGE-20261020）：参考价格区间双输入（下限 ~ 上限），与产品表单同款 */
.price-range-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.price-range-sep {
  flex-shrink: 0;
}

</style>
