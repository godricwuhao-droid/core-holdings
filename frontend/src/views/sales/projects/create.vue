<script setup lang="ts">
/**
 * 销售管理 - 新建 / 编辑销售项目（ADR-007 合同清单结构）
 *
 * 新建：项目级字段（项目名称 / 生态人员 / 商务负责人 / 日期 / 备注）
 *   + 「合同清单」区——每客户一份合同卡片（客户 + 合同金额 + 明细行），
 *   提交走 POST /projects 的 contracts 结构（项目 subject/customer/expectedAmount 由后端派生）。
 * 合同一经生成不可增删改明细（2026-10-20 ADR-013：「合同内同一产品主体」限制已移除，
 * 允许一份合同内混合不同主体的产品明细）。
 * 编辑：只改基本信息（合同结构不可改——终止对应合同后重新下单）。
 * 项目状态由合同状态派生，本页不提供状态变更入口。
 * 2026-10-20（ADR-020）：产品「登记销售」直接下单入口已移除，下单统一走购物车（本页 assetId 预填死代码同步删除）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  CircleCheck,
  Delete,
  Document,
  Folder,
  Link,
  Plus,
  Setting,
} from '@element-plus/icons-vue'
import {
  availableQty,
  boardLabel,
  derivedUnitPrice,
  entityShort,
  formatAssetQty,
  formatMoney,
  formatTokens,
  isAmountMode,
  PROJECT_STATUS,
  rsItemName,
  tagInfo,
  // formatWan 已由 formatAssetQty 覆盖（ADR-008 数量口径统一）
  type Asset,
  type Board,
} from '@/types'
import {
  changeProjectStatus,
  claimProject,
  createProject,
  getAsset,
  refresh,
  db,
  updateProject,
  allUserOptions,
  showError,
  type UserOption,
  type ContractInput,
  type ProjectInput,
} from '@/api'
import { canWrite, currentUser, isViewer, isAdmin, NO_PERM_TIP } from '@/auth'
import TransferDialog from '@/components/TransferDialog.vue'
import WithdrawProjectDialog from '@/components/WithdrawProjectDialog.vue'

const route = useRoute()
const router = useRouter()

const isEdit = computed(() => route.path.endsWith('edit'))
const projectId = computed(() => Number(route.params.id))
// 2026-10-21（ADR-027）：本页的「重新提交（原单明细预填）」模式已移除——
// 「重新提交」改为回填购物车后跳 /cart，本页仅保留「新建」（无 id）与「编辑」（:id/edit）两种形态。

const formRef = ref()
const submitting = ref(false)
/** 「更多设置」折叠：默认收起，需要补充时展开 */
const showMore = ref(false)

// ==================== 项目级字段（合同结构外的基本信息） ====================
const form = reactive({
  name: '',
  rep: '',
  businessOwner: '',
  expectedSignDate: '',
  lastFollowDate: '',
  remark: '',
})

const rules = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
}

// ==================== 合同清单（ADR-007：每客户一份合同） ====================
interface ContractDraftItem {
  assetId: number | null
  itemId?: number // ADR-011：遥感明细行（本页手工加行恒无 itemId，仅展示列兜底）
  qty: number
  price: number
  amount: number
  deliveryReq: string
  // 服务期限（ADR-020，PRICING-20261020）：YYYY-MM-DD，普通行填写；遥感行不展示（期数即服务时间）
  serviceStart: string
  serviceEnd: string
  // 原价快照（ADR-018 §2，PRICING-20261020）：仅重新提交预填时带出旧单值用于展示（只读，不提交）；
  // 手动新建时 orig 尚未落库（为空）
  origPrice?: number | null
  origAmount?: number | null
}

interface ContractDraft {
  customer: string
  // 元；= 明细金额合计（只读，2026-10-20 问题12d：删除手改逻辑——审核确认时后端按 Σ 明细重算，手改值会被静默丢弃）
  contractAmount: number
  remark: string
  items: ContractDraftItem[]
}

const contracts = reactive<ContractDraft[]>([])

function newItem(): ContractDraftItem {
  // ADR-020（PRICING-20261020）：服务期限默认空（选填，start ≤ end 由后端 400 兜底）
  return { assetId: null, qty: 0, price: 0, amount: 0, deliveryReq: '', serviceStart: '', serviceEnd: '' }
}

function addContract() {
  contracts.push({ customer: '', contractAmount: 0, remark: '', items: [newItem()] })
}

function removeContract(idx: number) {
  contracts.splice(idx, 1)
}

function addItem(c: ContractDraft) {
  c.items.push(newItem())
}

function removeItem(c: ContractDraft, idx: number) {
  c.items.splice(idx, 1)
  recalcContractAmount(c)
}

function itemAsset(it: ContractDraftItem) {
  return it.assetId ? getAsset(it.assetId) : undefined
}

/** ADR-011：明细列展示——itemId 非空显示 rsItemName（查 db.rsItems），空则 '-'（手工加行恒无 itemId） */
function itemRsName(it: ContractDraftItem): string {
  if (it.itemId == null) return '-'
  const r = db.rsItems.find((x) => x.id === it.itemId)
  return r ? rsItemName(r) : '-'
}

/** 明细数量上限：非可重复售卖按可售数量限制，可重复售卖不限制 */
function itemMax(it: ContractDraftItem): number | undefined {
  const a = itemAsset(it)
  if (!a || a.repeatSale) return undefined
  return availableQty(a) ?? 0
}

/**
 * 明细金额计算（ADR-008 双模式）：
 *  - unit 模式：销售金额 = 数量 × 单价（元值，保留 2 位小数），空/非法按 0
 *  - amount 模式（包量定价）：合同金额（整数元）为权威输入，单价派生 = 金额 ÷ 数量（元/份，6 位小数，ADR-017）
 */
function calcItemAmount(c: ContractDraft, it: ContractDraftItem) {
  const a = itemAsset(it)
  if (a && isAmountMode(a)) {
    it.price = it.qty && it.amount ? Math.round((it.amount / it.qty) * 1e6) / 1e6 : 0
  } else {
    it.amount = Math.round((it.qty || 0) * (it.price || 0) * 100) / 100
  }
  recalcContractAmount(c)
}

/** ADR-008：包量定价行合同金额输入——仅保留整数位（元口径） */
function onItemAmountInput(it: ContractDraftItem, v: string) {
  const digits = (v ?? '').replace(/[^\d]/g, '')
  it.amount = digits === '' ? 0 : Number(digits)
}

/** 合同金额 = 该合同明细金额合计（元），实时重算（2026-10-20 问题12d：只读展示，无手改；
 *  后端审核确认时同样按 Σ 明细重算，口径一致） */
function recalcContractAmount(c: ContractDraft) {
  c.contractAmount = Math.round(c.items.reduce((s, it) => s + (it.amount || 0), 0) * 100) / 100
}

function contractItemsTotal(c: ContractDraft): number {
  return Math.round(c.items.reduce((s, it) => s + (it.amount || 0), 0) * 100) / 100
}

/**
 * 明细产品变更处理（2026-10-20 问题12c：删除「合同内同一产品主体」预校验——
 * 后端 ADR-013 已移除该限制，一份合同内允许混合不同主体的产品明细，原「后端 400 兜底」已失效）。
 */
function onItemAssetChange(c: ContractDraft, it: ContractDraftItem) {
  const a = it.assetId ? getAsset(it.assetId) : undefined
  // ADR-011：遥感数据父产品不可手工加行（明细只经购物车进入，ADR-020：登记销售入口已移除），toast 拦截并回退选择；
  // 2026-10-20 例外：重新提交预填的遥感明细行（it.itemId 非空）允许保留/改选同产品
  if (a?.type === '遥感数据' && it.itemId == null) {
    ElMessage.info('遥感数据请通过产品列表加购')
    it.assetId = null
    it.price = 0
    it.amount = 0
    return
  }
  // 2026-10-20：产品变更后清空旧遥感明细绑定（明细必须归属所选产品，后端同口径校验）
  if (it.itemId != null && !(a?.type === '遥感数据' && db.rsItems.some((r) => r.id === it.itemId && r.assetId === it.assetId))) {
    it.itemId = undefined
  }
  // FIX-20261022 / BUG-07：切换产品必须重置上一产品的单价/金额——原实现「仅 price 为空才预填」会让
  // 上一产品的 price/amount 原样带到新产品（后端 unit 行直接采信前端 price → 错误单价/金额落库）。
  // 重置即视为「未手改过」：旧产品下手改过的价格随产品切换一并丢弃（安全侧），再按新产品预填。
  const amountMode = !!a && isAmountMode(a)
  it.amount = 0 // amount 模式：合同金额必须人工重新录入；unit 模式：由 qty × price 重算
  it.price = amountMode ? 0 : (a?.salePrice ?? 0)
  calcItemAmount(c, it)
}

/** 项目名称是否被用户手动改过；未改过时跟随首份合同客户名（客户为空则留空） */
const nameTouched = ref(false)
watch(
  () => contracts[0]?.customer,
  (c) => {
    if (!isEdit.value && !nameTouched.value) form.name = c || ''
  },
)

// ==================== 可选产品（与明细行共用） ====================
/** 可选产品：仅展示当前有可用数量的产品（可重复售卖，或可售数量 > 0；无数量的不再进入下拉） */
const sellableAssets = computed(() =>
  db.assets.filter(
    (a) => a.board !== 'compute' && (a.repeatSale || (availableQty(a) ?? 0) > 0),
  ),
)

/** 产品树：按板块分组（卫星服务下分 Token / 数据两级），供 el-tree-select 树状筛选与搜索 */
const assetTreeData = computed(() => {
  const boards: Board[] = ['embodied', 'satellite', 'software', 'hardware']
  const leaf = (a: Asset) => ({ id: a.id, label: `${a.name}（${a.code}）` })
  return boards
    .map((board) => {
      const assets = sellableAssets.value.filter((a) => a.board === board)
      const children =
        board === 'satellite'
          ? (['卫星Token', '卫星数据', '遥感数据'] as const) // ADR-010：遥感数据
              .map((t) => ({
                id: `sat_${t}`,
                label: t,
                disabled: true,
                children: assets.filter((a) => a.type === t).map(leaf),
              }))
              .filter((n) => n.children.length)
          : assets.map(leaf)
      return { id: `board_${board}`, label: boardLabel(board), disabled: true, children }
    })
    .filter((n) => n.children.length)
})

// ==================== 编辑模式：已有数据预填 + 合同只读概览（2026-10-19 重构） ====================
/** 编辑目标项目（db 镜像；onMounted 已完成存在性/权限/可编辑性守卫） */
const editProject = computed(() =>
  isEdit.value ? db.projects.find((x) => x.id === projectId.value) : undefined,
)
/** 编辑项目名下合同（db.contracts 按 projectId 过滤，与项目列表抽屉同源） */
const editContracts = computed(() =>
  editProject.value ? db.contracts.filter((c) => c.projectId === editProject.value!.id) : [],
)
/** 只读合同清单的明细产品名 */
function editItemName(it: { assetId?: number | null }): string {
  if (!it.assetId) return '未关联产品'
  return getAsset(it.assetId)?.name ?? '产品已删除'
}

/** 编辑的是否为待审核项目（销售记录清单的 pending 提示用；审核操作已拆独立审核页 /review） */
const isPendingEdit = computed(() => isEdit.value && editProject.value?.status === 'pending')
/** 2026-10-19：订单审核（改价确认/驳回）整体迁至独立审核页 review.vue，本页不再承载 */

// ==================== 商务接手机制（ADR-012 §5.1：改价/确认/驳回仅限接手账号，admin 可越过） ====================
// 2026-10-20：显示映射（生态人员下拉/rep 归一/负责人展示）用**全量**名册——
// 原商务专属列表查不到生态账号，编辑页生态人员下拉选不到人、回显裸账号
const ownerOptions = ref<UserOption[]>([])
const ownerOptionsReady = allUserOptions().then((u) => { ownerOptions.value = u }).catch(() => {})

/** 当前用户是否可操作该订单：接手账号本人，或 admin 兜底（日志留痕实际操作人） */
const canReviewEdit = computed(() => {
  if (!canWrite.value || !editProject.value) return false
  const owner = editProject.value.businessOwner
  return isAdmin.value || owner === currentUser.value?.username
})
/** 基本信息表单可编辑性（与后端 PUT 守卫同口径）：
 *  - viewer：ADR-028（2026-10-21）已收回编辑权——后端 PUT 对 viewer 一律 403，
 *    本页对 viewer 的编辑访问在 onMounted 即被拦截（提示 + 回详情页），故下方 viewer 分支
 *    实际不可达（保留为页面级兜底，视图仍按 creator 判定只读）；
 *  - 商务/管理员：pending 项目仅负责人/admin 可编辑（审核走独立审核页）；active 均可编辑 */
const canEditForm = computed(() => {
  if (isViewer.value) {
    return !!editProject.value && editProject.value.creator === currentUser.value?.username
  }
  if (!canWrite.value) return false
  return !(isPendingEdit.value && !canReviewEdit.value)
})
/** ADR-012 §5.1：直连 URL 无权限拦截——pending + 非负责人的商务 → 只读提示页（不渲染表单，
 *  防绕过入口按钮进入；viewer 看自己单子的只读视图不受影响，admin 可越过不受影响） */
const noEditAccess = computed(() => isEdit.value && isPendingEdit.value && canWrite.value && !canReviewEdit.value)
/** 转交对话框（面板内入口） */
const transferVisible = ref(false)
const transferTarget = ref<{ id: number; name: string; businessOwner?: string } | null>(null)
function openTransferPanel() {
  const p = editProject.value
  if (!p) return
  transferTarget.value = p
  transferVisible.value = true
}
/** 接手提示中展示的当前负责人（2026-10-20：只显示姓名，不带账号；存量自由文本原样） */
function ownerLabel(username?: string): string {
  if (!username) return ''
  const u = ownerOptions.value.find((x) => x.username === username)
  return u?.name || username
}
/** 生态人员选项（2026-10-19：展示 姓名(账号) 而非裸账号；value=username 与下单口径一致） */
const repUserOptions = computed(() => ownerOptions.value)
/** 存量 rep 归一：存的是姓名时按姓名查账号 → username；已是账号或查不到则原样 */
function normalizeRep(rep: string): string {
  if (!rep) return ''
  if (ownerOptions.value.some((u) => u.username === rep)) return rep
  const byName = ownerOptions.value.find((u) => u.name === rep)
  return byName ? byName.username : rep
}

async function handleClaimInPanel() {
  const p = editProject.value
  if (!p) return
  // 纯移交制：有主单（admin 路径）→ 转交下拉选人；无主单 → 接手给自己
  if (p.businessOwner) {
    openTransferPanel()
    return
  }
  try {
    await ElMessageBox.confirm(
      '确认接手该订单？接手后由你负责定价审核（确认下单/驳回）。',
      '接手此单',
      { type: 'warning', confirmButtonText: '确认接手', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  reviewBusy.value = true
  try {
    await claimProject(p.id)
    ElMessage.success('已接手，现在可以改价并确认下单')
    // claimProject 内 afterWrite 已刷新 db 镜像 → canReviewEdit 自动翻转
  } catch (e) {
    showError(e, '操作失败')
  } finally {
    reviewBusy.value = false
  }
}

/** 2026-10-19：确认下单/驳回已迁至独立审核页 review.vue（reviewBusy 保留供本页接手按钮 loading） */
const reviewBusy = ref(false)

/**
 * 撤销待审核订单（ADR-026 / TASK-FE-029）：仅 `pending` 且「本人下单（creator==当前登录）或 admin」可见。
 * 商务（editor）不显示——商务走「驳回」；viewer 他人单不可见（后端 creator 归属守卫兜底）。
 * 待审核单的「取消订单（终止）」由本动作取代（撤销 = 终止 + 明细回填购物车）。
 * 注：`ProjectOut` 自 2026-10-21 起已输出 `creator`（bootstrap 同步），按账号精确比对；
 * 存量项目 creator 为空时按「可见即本人单」兜底（后端归属守卫兜底）。
 */
const canWithdraw = computed(() => {
  const p = editProject.value
  if (!p || !isPendingEdit.value) return false
  if (isAdmin.value) return true
  if (canWrite.value) return false // 商务（editor）不显示，走驳回
  const creator = (p.creator || '').trim()
  return !creator || creator === currentUser.value?.username
})
const withdrawVisible = ref(false)
/** 撤销成功后：刷新镜像（项目转 terminated + 购物车回填）后跳 /cart 改单重提 */
async function onWithdrawn() {
  await refresh()
  router.push('/cart')
}

/** 终止项目（2026-10-19 生态放开）：项目级批量终止——非删除，记录留存、状态 terminated 后不可再编辑；
 *  active 单 = 批量终止进行中销售记录（pending 单的「取消订单」已由撤销取代，ADR-026）。
 *  后端 change_project_status 守卫：viewer 仅自己下单的项目；商务/admin 对 pending 仅走审核接口 */
const terminating = ref(false)
async function handleTerminateProject() {
  const p = editProject.value
  if (!p || terminating.value) return // BUG-10：请求期间按钮 loading+禁用，此处再兜一次
  // FIX-20261022 / BUG-21：终止批量口径纳入「交付中」（与后端 change_project_status 的
  // targets = active + delivering 一致，原只数 active 会把交付中记录漏掉，文案计数偏小）
  const n = isPendingEdit.value
    ? editContracts.value.length
    : editContracts.value.filter((c) => c.status === 'active' || c.status === 'delivering').length
  const msg = isPendingEdit.value
    ? `取消该订单后项目将终止：数量锁定释放，记录留存、不可再编辑。确定取消？`
    : `终止项目「${p.name}」将终止名下 ${n} 份进行中销售记录（释放锁定数量，已交付不受影响）。记录留存、不可再编辑。确定终止？`
  try {
    await ElMessageBox.confirm(msg, isPendingEdit.value ? '取消订单确认' : '终止项目确认',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
  } catch {
    return
  }
  terminating.value = true
  try {
    await changeProjectStatus(p.id, 'terminated')
    ElMessage.success('项目已终止（记录留存，不可再编辑）')
    router.push('/sales/projects')
  } catch (e) {
    showError(e, '操作失败')
  } finally {
    terminating.value = false
  }
}

// ==================== 校验与提交 ====================
/** 有效合同：至少含一条已选产品的明细 */
function validContracts(): ContractDraft[] {
  return contracts.filter((c) => c.items.some((it) => it.assetId))
}

/**
 * 创建校验：≥1 份有效合同；每份客户必填；明细数量 > 0；
 * 数量上限按「同产品合计」口径（可重复售卖不限制）。
 *
 * FIX-20261022 / BUG-22：原逐行与可售数量比较，而后端 `_create_project_core` 是「先按 assetId 聚合
 * demand 再与可售比较」——同一产品拆到多行/多份销售记录时，逐行校验会放过越界组合（只能靠后端 400 回滚）。
 * 现改为先按 assetId 汇总，再逐产品与可售比较；遥感明细行数量仍恒 1。
 */
function validateContracts(): boolean {
  const valid = validContracts()
  if (!valid.length) {
    ElMessage.warning('请至少添加一份销售记录并选择产品')
    return false
  }
  const demand = new Map<number, number>()
  for (const c of valid) {
    if (!c.customer.trim()) {
      ElMessage.warning('请为每份销售记录填写客户')
      return false
    }
    for (const it of c.items) {
      if (!it.assetId) continue
      if (!it.qty || it.qty <= 0) {
        ElMessage.warning('销售明细数量必须大于 0')
        return false
      }
      // ADR-011 / 2026-10-20：遥感明细行数量固定 1（重新提交预填行同口径）
      if (it.itemId != null && it.qty !== 1) {
        ElMessage.warning('遥感数据明细行数量固定为 1')
        return false
      }
      // ADR-008：包量定价行合同金额必须为正整数元
      const a = itemAsset(it)
      if (a && isAmountMode(a) && (!it.amount || !Number.isInteger(it.amount) || it.amount <= 0)) {
        ElMessage.warning('销售金额须为整数元')
        return false
      }
      // ADR-020（PRICING-20261020）：服务期限 start ≤ end（后端同口径 400，前端先拦）
      if (it.serviceStart && it.serviceEnd && it.serviceStart > it.serviceEnd) {
        ElMessage.warning('服务开始日期不能晚于结束日期')
        return false
      }
      demand.set(it.assetId, (demand.get(it.assetId) ?? 0) + it.qty)
    }
  }
  // 「同产品合计 ≤ 可售」——与后端聚合口径一致（可重复售卖跳过）
  for (const [assetId, qty] of demand) {
    const a = getAsset(assetId)
    if (!a || a.repeatSale) continue
    const avail = availableQty(a) ?? 0
    if (qty > avail) {
      ElMessage.warning(`「${a.name}」本单数量合计 ${qty} 超出可售上限（可售 ${avail}）`)
      return false
    }
  }
  return true
}

function buildContractsPayload(): ContractInput[] {
  return validContracts().map((c) => ({
    customer: c.customer.trim(),
    contractAmount: c.contractAmount,
    remark: c.remark,
    items: c.items
      .filter((it) => it.assetId)
      .map((it) => ({
        assetId: it.assetId,
        qty: it.qty,
        price: it.price,
        amount: it.amount,
        deliveryReq: it.deliveryReq,
        ...(it.itemId != null ? { itemId: it.itemId } : {}), // 2026-10-20：重新提交预填的遥感明细行
        // ADR-020（PRICING-20261020）：服务期限随明细提交（空 → null；start ≤ end 后端校验）
        serviceStart: it.serviceStart || null,
        serviceEnd: it.serviceEnd || null,
      })),
  }))
}

/**
 * 项目级 payload：
 *  - 新建：contracts 结构（customer/subject/expectedAmount/contractAmount 为派生字段，后端不采信）
 *  - 编辑：仅基本信息（PUT 不再接受 items/contracts，合同结构不可改）
 */
function buildPayload(withContracts: boolean): ProjectInput {
  const base: ProjectInput = {
    name: form.name,
    customer: withContracts ? (contracts[0]?.customer.trim() ?? '') : '',
    industry: '',
    rep: form.rep,
    businessOwner: form.businessOwner,
    subject: '',
    expectedAmount: 0,
    contractAmount: 0,
    expectedSignDate: form.expectedSignDate,
    lastFollowDate: form.lastFollowDate,
    remark: form.remark,
    items: [],
  }
  if (withContracts) base.contracts = buildContractsPayload()
  return base
}

/** 预填：编辑模式带出项目基本信息；新建模式初始化 1 份空合同卡片 */
onMounted(async () => {
  await refresh()
  // 生态人员（viewer）：新建一律禁止（下单走产品下单入口，「重新提交」已改为回填购物车跳 /cart，
  // 见 ADR-027）；编辑亦已禁止（ADR-028，见下方拦截）
  if (isViewer.value && !isEdit.value) {
    ElMessage.warning('生态人员新建项目请通过产品下单入口；已终止的自己的订单可「重新提交」')
    router.replace('/sales/projects')
    return
  }
  // ADR-028（2026-10-21）：生态人员订单提交后禁编辑——编辑模式对 viewer 一律请回详情页
  // （路由守卫已不放行 /:id/edit，此处为页面级兜底；置于项目查找之前，避免无谓加载）。
  // viewer 唯一改单路径 =「撤销」（明细回购物车）→ 重新下单
  if (isEdit.value && isViewer.value) {
    ElMessage.warning('订单已提交，不可编辑，如需修改请「撤销」后重新下单')
    router.replace(`/sales/projects/${projectId.value}/detail`)
    return
  }
  if (isEdit.value) {
    const p = db.projects.find((x) => x.id === projectId.value)
    if (!p) {
      // 项目不存在，或生态人员经 URL 访问他人项目（后端已按「自己下单」过滤，镜像中无此项目）
      ElMessage.warning('项目不存在或无查看权限')
      router.replace('/sales/projects')
      return
    }
    if (p) {
      // 直达 URL 守卫：存在 delivered 合同 → 不可编辑（后端 400 同文案）；
      // 存量无合同项目沿用旧规则（status != active 不可编辑）。
      const pc = db.contracts.filter((c) => c.projectId === p.id)
      if (pc.some((c) => c.status === 'delivered')) {
        ElMessage.warning('已交付完成的项目不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      // 2026-10-19 排查修复：有合同且派生 status=terminated（全终止/混合 terminated）同样不可编辑
      //（原守卫只拦 delivered，此类项目可绕过进入表单、提交才被后端 400；与列表 canEditProject 同口径）
      if (p.status === 'terminated') {
        ElMessage.warning('项目已终止，不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      if (!pc.length && p.status !== 'active') {
        ElMessage.warning('已完成/已终止项目不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      // 2026-10-19：等用户列表加载完（rep 姓名→账号归一需要）
      await ownerOptionsReady
      Object.assign(form, {
        name: p.name,
        rep: normalizeRep(p.rep),
        businessOwner: p.businessOwner ?? '',
        expectedSignDate: p.expectedSignDate,
        lastFollowDate: p.lastFollowDate,
        remark: p.remark,
      })
      return
    }
  }
  // 新建模式：默认 1 份合同卡片
  addContract()
  // 从「登记销售」等入口带客户预填时：首份合同客户 = 预填客户，项目名同步跟随
  const preCustomer = typeof route.query.customer === 'string' ? route.query.customer : ''
  if (preCustomer) {
    contracts[0].customer = preCustomer
    form.name = preCustomer
  }
  // 2026-10-20（ADR-020）：原「登记销售」入口的 ?assetId 预填死代码已删除
  //（产品详情/列表下单入口统一收口购物车，router 已无该 query 入口，无其他调用路径）
})

/**
 * 保存草稿：项目名称必填 + **复用同一套合同校验**（FIX-20261022 / BUG-26）。
 * 后端建单即「待审核」（ADR-012：所有角色统一 pending，无草稿态），若跳过合同校验会产出
 * 0 明细 0 元的 pending 空单（审核必 400 且 pending 不可编辑 → 单据无出口）。
 * FIX-20261022 / BUG-09：写操作补 catch（400/422 不再静默）。
 */
async function saveDraft() {
  if (submitting.value) return // 双按钮共用 submitting：请求在飞期间忽略重复点击
  if (!form.name.trim()) {
    ElMessage.warning('请先填写项目名称再保存草稿')
    return
  }
  if (!isEdit.value && !validateContracts()) return
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, buildPayload(false))
    } else {
      await createProject(buildPayload(true))
    }
    ElMessage.success('已保存草稿，项目状态为「待审核」（商务接手确认后生效）')
    router.push('/sales/projects')
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    submitting.value = false
  }
}

async function handleSubmit() {
  if (submitting.value) return // 双按钮共用 submitting：请求在飞期间忽略重复点击
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  if (!isEdit.value && !validateContracts()) return
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, buildPayload(false))
      ElMessage.success('更新成功')
    } else {
      const created = await createProject(buildPayload(true))
      ElMessage.success(`创建成功，项目编号 ${created.code}（${created.contractCount ?? validContracts().length} 份销售记录）`)
    }
    router.push('/sales/projects')
  } catch (e) {
    // FIX-20261022 / BUG-09：后端 400/422（库存不足、区间越界、服务期限非法…）此前完全静默
    showError(e, '提交失败')
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到销售项目列表，避免退出应用
  if (window.history.state?.back) router.back()
  else router.push('/sales/projects')
}
</script>

<template>
  <div class="page-container">
    <div class="create-wrap">
      <!-- 页面标题区：文字式返回入口 + 标题 + 说明 + 草稿标签 -->
      <div class="page-head">
        <div>
          <a class="back-link" @click="handleCancel">
            <el-icon><ArrowLeft /></el-icon>
            返回销售项目
          </a>
          <h1>{{ isEdit ? '编辑销售项目' : '新建销售项目' }}</h1>
          <div class="desc">
            {{
              isEdit
                ? '仅可修改项目基本信息；销售记录与明细在创建后不可修改。'
                : '每客户一份销售记录，销售记录内选择待售产品，销售金额按 数量 × 单价 自动计算；包量定价（Token）产品以销售金额（整数元）为准。'
            }}
          </div>
        </div>
        <div class="head-actions" v-if="!isEdit">
          <span class="draft-tag">◌ 草稿未保存</span>
        </div>
      </div>

      <!-- ==================== 编辑模式（2026-10-19 重构）：进入即预填已有数据；金额区 2 可编辑 + 2 派生只读 ==================== -->
      <!-- ADR-012 §5.1：pending 项目无权限（非负责人商务直连 URL）→ 只读提示页，禁止编辑/审核操作 -->
      <div v-if="isEdit && noEditAccess" class="create-form">
        <div class="form-card" style="text-align: center; padding: 48px 24px;">
          <el-alert
            :title="editProject?.businessOwner
              ? `该订单由商务 ${ownerLabel(editProject.businessOwner)} 负责，你暂无编辑/审核权限`
              : '该订单尚未被商务接手，你暂无编辑/审核权限'"
            type="warning"
            :closable="false"
            show-icon
            style="max-width: 520px; margin: 0 auto 16px; text-align: left;"
          />
          <p class="muted" style="margin: 0 0 20px;">待审核项目仅接手的商务负责人（或管理员）可进入编辑与审核。可在列表页先「接手」，或联系负责人处理。</p>
          <!-- 2026-10-19 排查修复：无主单商务 / 有主单 admin 可直接在此接手（接手成功后 canReviewEdit 翻转，
               noEditAccess 自动失效，表单原地渲染，无需手动刷新） -->
          <el-button
            v-if="!editProject?.businessOwner || isAdmin"
            type="primary"
            :loading="reviewBusy"
            @click="handleClaimInPanel"
          >
            {{ editProject?.businessOwner ? '接手给我（管理员）' : '接手此单' }}
          </el-button>
          <el-button type="primary" @click="handleCancel">返回项目列表</el-button>
        </div>
      </div>
      <el-form v-if="isEdit && !noEditAccess" ref="formRef" :model="form" :rules="rules" label-position="top" class="create-form">
        <!-- ① 基本信息（onMounted 已从 db 镜像预填） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Folder /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">带 * 为必填</span>
          </div>
          <div class="form-grid-2">
            <el-form-item label="项目名称" prop="name">
              <el-input v-model="form.name" placeholder="项目名称" :disabled="!canEditForm" />
            </el-form-item>
            <el-form-item label="生态人员">
              <!-- viewer 编辑自己项目时 rep 只读（后端同样忽略 viewer 的 rep 变更，防转移项目）
                   2026-10-19：展示 姓名(账号)（原裸账号/姓名混杂），value=username -->
              <el-select
                v-model="form.rep"
                :disabled="isViewer || !canEditForm"
                filterable
                placeholder="选择生态人员"
                style="width: 100%;"
              >
                <el-option v-for="u in repUserOptions" :key="u.username" :label="ownerLabel(u.username)" :value="u.username" />
              </el-select>
            </el-form-item>
            <el-form-item label="商务负责人">
              <!-- ADR-012 §5.1：负责人只读——唯一变更入口是「接手/转交」接口，后端 PUT 忽略该字段 -->
              <el-input :model-value="ownerLabel(editProject?.businessOwner)" placeholder="未指派（接手/转交后自动关联账号）" disabled />
            </el-form-item>
            <el-form-item label="预计签约日期">
              <el-date-picker
                v-model="form.expectedSignDate"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                :disabled="!canEditForm"
                style="width: 100%;"
              />
            </el-form-item>
            <el-form-item label="最近跟进日期">
              <el-date-picker
                v-model="form.lastFollowDate"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                :disabled="!canEditForm"
                style="width: 100%;"
              />
            </el-form-item>
          </div>
        </div>

        <!-- ② 销售记录清单（只读概览：销售记录结构创建后不可改，PUT 亦不受理）
             2026-10-19：金额信息卡（销售金额合计）删除；订单审核面板整体迁独立审核页 /review -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Link /></el-icon></span>
            <div>
              <div class="bh-title">销售记录清单（只读）<span class="muted" style="font-weight: 400;">（{{ editContracts.length }}）</span></div>
              <div class="bh-sub">销售记录与明细在创建后不可修改，如需调整请终止对应销售记录后重新下单；交付 / 终止状态变更在项目详情页操作。</div>
            </div>
          </div>
          <el-alert
            v-if="isPendingEdit"
            type="warning"
            :closable="false"
            show-icon
            title="该订单已提交商务确认（数量已锁定），最终价格以商务「确认下单」为准"
            class="rv-pending-alert"
          />
          <div v-if="editContracts.length" class="ro-contracts">
            <div v-for="c in editContracts" :key="c.id" class="ro-ct">
              <div class="ro-ct-head">
                <span class="ro-ct-customer">{{ c.customer || '-' }}</span>
                <el-tag v-if="c.subject" size="small" effect="plain">{{ entityShort(c.subject) }}</el-tag>
                <el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light">
                  {{ tagInfo(PROJECT_STATUS, c.status).label }}
                </el-tag>
                <span class="ro-ct-amount">{{ formatMoney(c.contractAmount) }}</span>
              </div>
              <div class="ro-ct-items">
                <div v-for="it in c.items" :key="it.id" class="ro-ct-item">
                  <el-tooltip :content="editItemName(it)" placement="top">
                    <span class="ro-ct-name">{{ editItemName(it) }}</span>
                  </el-tooltip>
                  <span class="ro-ct-qty muted">× {{ it.qty }}</span>
                  <span class="ro-ct-amt">{{ formatMoney(it.amount) }}</span>
                  <!-- ADR-018 §2（PRICING-20261020）：原价快照（下单时挂牌价，只读；存量订单为空不展示） -->
                  <span v-if="it.origAmount != null" class="muted ro-ct-orig">原价 {{ formatMoney(it.origAmount) }}</span>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="该项目暂无销售记录（存量数据）" :image-size="56" />
        </div>

        <!-- ③ 备注（2026-10-19：置底——位于销售记录清单之后） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
            <span class="bh-title">备注</span>
          </div>
          <el-input
            v-model="form.remark"
            type="textarea"
            :rows="3"
            :disabled="!canEditForm"
            placeholder="填写项目背景、重点跟进事项或特殊约定"
          />
        </div>

        <!-- 底部操作区：右对齐，不悬浮
             2026-10-19：确认下单/驳回/转交迁至独立审核页 /review；
             新增「审核订单」跳转入口（商务/管理员 + 待审核）与「撤销订单 / 终止项目」（生态自己单）；
             ADR-026：待审核单的「取消订单（终止）」由「撤销订单」取代（终止 + 明细回填购物车），
             非待审核的「终止项目」口径不变 -->
        <div class="bottom-actions">
          <el-button @click="handleCancel">返回</el-button>
          <el-button
            v-if="canWithdraw"
            type="danger"
            plain
            @click="withdrawVisible = true"
          >
            撤销订单
          </el-button>
          <el-button
            v-if="isViewer && editProject?.creator === currentUser?.username && !isPendingEdit"
            type="danger"
            plain
            :loading="terminating"
            :disabled="terminating"
            @click="handleTerminateProject"
          >
            终止项目
          </el-button>
          <el-button v-if="canWrite && isPendingEdit" type="primary" plain @click="router.push(`/sales/projects/${projectId}/review`)">
            审核订单
          </el-button>
          <el-tooltip :content="canEditForm ? '' : NO_PERM_TIP" :disabled="canEditForm" placement="top">
            <span>
              <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canEditForm" @click="handleSubmit">
                保存修改
              </el-button>
            </span>
          </el-tooltip>
        </div>
      </el-form>

      <!-- ==================== 新建模式（原销售记录清单表单） ==================== -->
      <el-form v-else ref="formRef" :model="form" :rules="rules" label-position="top" class="create-form">
        <!-- ① 基本信息 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Folder /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">带 * 为必填</span>
          </div>
          <div class="form-grid-2">
            <el-form-item label="项目名称" prop="name">
              <el-input v-model="form.name" placeholder="默认跟随首份销售记录客户名，可修改" @input="nameTouched = true" />
            </el-form-item>
          </div>
        </div>

        <!-- ② 销售记录清单（仅新建模式；编辑模式销售记录结构不可改） -->
        <div v-if="!isEdit" class="form-card asset-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Link /></el-icon></span>
            <div>
              <div class="bh-title">销售记录清单</div>
              <div class="bh-sub">每客户一份销售记录（可含不同主体的产品明细）；销售金额 = 明细合计（自动计算，只读）。</div>
            </div>
            <span class="bh-hint">
              <el-button plain size="small" :icon="Plus" @click="addContract">添加销售记录</el-button>
            </span>
          </div>

          <div v-for="(c, ci) in contracts" :key="ci" class="contract-card">
            <div class="contract-head">
              <span class="contract-title">
                销售记录 {{ ci + 1 }}
                <template v-if="c.customer"> · {{ c.customer }}</template>
                <template v-else class="muted"> · 客户未填写</template>
              </span>
              <el-button link type="danger" size="small" :icon="Delete" @click="removeContract(ci)">删除销售记录</el-button>
            </div>

            <div class="contract-fields">
              <div class="cf-item">
                <span class="cf-label">客户 <i class="req">*</i></span>
                <el-input v-model="c.customer" placeholder="填写本销售记录客户名称" style="width: 220px;" />
              </div>
              <div class="cf-item">
                <span class="cf-label">销售金额（元）</span>
                <!-- 2026-10-20（问题12d）：合同金额只读 = Σ 明细金额实时值——
                     原手改值在审核确认时会被后端按 Σ 明细重算静默丢弃，删除手改入口 -->
                <el-input-number
                  :model-value="c.contractAmount"
                  :min="0"
                  :precision="2"
                  :controls="false"
                  disabled
                  style="width: 180px;"
                />
              </div>
            </div>

            <div class="items-wrap">
              <el-table :data="c.items" border>
                <el-table-column label="产品" min-width="280">
                  <template #default="{ row }">
                    <el-tree-select
                      v-model="row.assetId"
                      :data="assetTreeData"
                      :props="{ label: 'label', children: 'children' }"
                      node-key="id"
                      check-strictly
                      filterable
                      :render-after-expand="false"
                      placeholder="选择待售产品"
                      style="width: 100%;"
                      @change="onItemAssetChange(c, row)"
                    />
                    <div v-if="itemAsset(row)" class="asset-meta">
                      <span class="muted" style="font-size: 12px;">
                        {{ itemAsset(row)!.code }} · {{ itemAsset(row)!.type }}
                      </span>
                      <span class="stock-pill" :class="itemAsset(row)!.repeatSale ? 'repeat' : 'ok'">
                        <span class="dot" aria-hidden="true">{{ itemAsset(row)!.repeatSale ? '↻' : '●' }}</span>
                        {{ itemAsset(row)!.repeatSale ? '可重复售卖' : `可售 ${formatAssetQty(itemAsset(row)!, availableQty(itemAsset(row)!))} ${itemAsset(row)!.unit}` }}
                      </span>
                      <a
                        class="pkg-link"
                        @click.stop="router.push(`/assets/${row.assetId}/detail?tab=deliverables`)"
                      >
                        查看交付包
                      </a>
                    </div>
                  </template>
                </el-table-column>
                <!-- ADR-011：明细列（遥感明细行显示明细名；本页手工加行恒为 '-'） -->
                <el-table-column label="明细" width="200" align="left" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span :class="{ muted: itemRsName(row) === '-' }">{{ itemRsName(row) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="数量" width="150" align="center">
                  <template #default="{ row }">
                    <el-input-number
                      v-model="row.qty"
                      :min="0"
                      :max="itemMax(row)"
                      :precision="0"
                      :step="1"
                      controls-position="right"
                      style="width: 100%;"
                      @change="calcItemAmount(c, row)"
                    />
                    <!-- ADR-008：Token 产品数量按 formatTokens 展示（原数提交） -->
                    <div v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)" class="muted item-qty-hint">
                      {{ formatTokens(row.qty) }} Token
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="单价（元）" width="180" align="center">
                  <template #default="{ row }">
                    <!-- ADR-017：包量定价行单价为派生参考展示（金额÷数量，元/{unit}，无 1e4 换算） -->
                    <span v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)" class="muted">
                      {{ derivedUnitPrice(row.amount, row.qty, itemAsset(row)?.unit) }}
                    </span>
                    <!-- FIX-20261022 / BUG-44（§6 硬约束）：金额类 el-input-number 一律 :controls="false"（无步进按钮） -->
                    <el-input-number
                      v-else
                      v-model="row.price"
                      :min="0"
                      :precision="2"
                      :controls="false"
                      style="width: 100%;"
                      @change="calcItemAmount(c, row)"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="金额" width="190" align="right">
                  <template #default="{ row }">
                    <!-- ADR-008：包量定价行销售金额（整数元）为权威输入；unit 模式保持只读自动计算 -->
                    <el-input
                      v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)"
                      :model-value="row.amount || ''"
                      placeholder="整数元"
                      size="small"
                      @input="onItemAmountInput(row, $event)"
                      @change="calcItemAmount(c, row)"
                    />
                    <span v-else class="item-amount">{{ formatMoney(row.amount) }}</span>
                    <!-- ADR-018 §2（PRICING-20261020）：原价快照——仅重新提交预填（旧单有 orig）时展示；
                         手动新建时 orig 尚未落库（为空），不展示 -->
                    <div v-if="row.origAmount != null" class="muted item-orig">原价 {{ formatMoney(row.origAmount) }}</div>
                  </template>
                </el-table-column>
                <!-- ADR-020（PRICING-20261020）：服务期限——普通行填写（选填）；
                     遥感明细行按期数售卖（期数即服务时间），不展示期限输入 -->
                <el-table-column label="服务期限" width="220" align="center">
                  <template #default="{ row }">
                    <template v-if="row.itemId == null">
                      <div class="svc-row">
                        <el-date-picker
                          v-model="row.serviceStart"
                          type="date"
                          value-format="YYYY-MM-DD"
                          size="small"
                          placeholder="开始（选填）"
                          style="width: 100%;"
                        />
                        <el-date-picker
                          v-model="row.serviceEnd"
                          type="date"
                          value-format="YYYY-MM-DD"
                          size="small"
                          placeholder="结束（选填）"
                          style="width: 100%;"
                        />
                      </div>
                    </template>
                    <span v-else class="muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="" width="60" align="center">
                  <template #default="{ $index }">
                    <el-button link type="danger" :icon="Delete" @click="removeItem(c, $index)" />
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div class="contract-foot">
              <el-button link type="primary" size="small" :icon="Plus" @click="addItem(c)">添加明细行</el-button>
              <span class="muted" style="font-size: 13px;">明细合计</span>
              <span class="total-value">{{ formatMoney(contractItemsTotal(c)) }}</span>
            </div>
          </div>

          <el-empty v-if="!contracts.length" description="暂无销售记录，点击右上角「添加销售记录」" :image-size="60" />
        </div>

        <!-- 编辑模式：销售记录结构不可改的说明 -->
        <el-alert
          v-else
          class="edit-contract-tip"
          title="销售记录与明细在创建后不可修改，如需调整请终止对应销售记录后重新下单"
          type="info"
          :closable="false"
          show-icon
        />

        <!-- ③ 更多设置（默认收起，展开补填次要字段） -->
        <div class="form-card more-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Setting /></el-icon></span>
            <div>
              <div class="bh-title">更多设置</div>
              <div class="bh-sub">生态人员、商务负责人、日期、报价 / 已回款金额与备注等可选补充；项目状态由销售记录状态自动派生。</div>
            </div>
            <span class="bh-hint">
              <el-button link type="primary" size="small" @click="showMore = !showMore">
                {{ showMore ? '收起' : '展开补充' }}
                <el-icon
                  :style="{ marginLeft: '2px', transition: 'transform .2s', transform: showMore ? 'rotate(180deg)' : '' }"
                >
                  <ArrowDown />
                </el-icon>
              </el-button>
            </span>
          </div>

          <template v-if="showMore">
            <div class="form-grid">
              <el-form-item label="生态人员">
                <!-- 生态人员（viewer）编辑自己的项目时 rep 只读（后端同样忽略 viewer 的 rep 变更，防转移项目）
                     2026-10-20（问题10）：rep 统一存 username——选项源由 db.reps 基础资料（value=姓名）
                     切换为全量账号名册（与编辑面板同源，value=username，label 显示姓名）；
                     去掉 allow-create：手输会写入姓名，导致 rep 账号/姓名混存回潮 -->
                <el-select
                  v-model="form.rep"
                  :disabled="isViewer"
                  filterable
                  placeholder="选择生态人员"
                  style="width: 100%;"
                >
                  <el-option v-for="u in repUserOptions" :key="u.username" :label="ownerLabel(u.username)" :value="u.username" />
                </el-select>
              </el-form-item>
              <el-form-item label="商务负责人">
                <el-input v-model="form.businessOwner" placeholder="商务负责人姓名" />
              </el-form-item>
              <el-form-item label="预计签约日期">
                <el-date-picker
                  v-model="form.expectedSignDate"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="选择日期"
                  style="width: 100%;"
                />
              </el-form-item>
              <el-form-item label="最近跟进日期">
                <el-date-picker
                  v-model="form.lastFollowDate"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="选择日期"
                  style="width: 100%;"
                />
              </el-form-item>
            </div>

            <!-- 2026-10-19：报价/已回款输入已删除（字段废弃，无业务用途） -->

            <el-form-item label="备注" class="remark-item">
              <el-input
                v-model="form.remark"
                type="textarea"
                :rows="3"
                placeholder="填写项目背景、重点跟进事项或特殊约定"
              />
            </el-form-item>
          </template>
          <div v-else class="more-collapsed-hint muted">
            生态人员、商务负责人、签约 / 跟进日期、报价 / 已回款金额、备注等（非必填，默认收起）
          </div>
        </div>

        <!-- 底部操作区：右对齐，不悬浮 -->
        <div class="bottom-actions">
          <template v-if="!isEdit">
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button plain :loading="submitting" :disabled="!canWrite" @click="saveDraft">保存草稿</el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                  创建项目
                </el-button>
              </span>
            </el-tooltip>
          </template>
          <template v-else>
            <el-button @click="handleCancel">返回</el-button>
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                  保存修改
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </div>
      </el-form>

      <!-- ADR-012 §5.1 纯移交制：转交对话框（负责人/admin，下拉选新负责人） -->
      <TransferDialog v-model="transferVisible" :project="transferTarget" />

      <!-- ADR-026：撤销待审核订单（统一对话框；成功后刷新镜像并跳 /cart 改单重提） -->
      <WithdrawProjectDialog v-model="withdrawVisible" :project="editProject ?? null" @done="onWithdrawn" />
    </div>
  </div>
</template>

<style scoped>
/* 内容区最大 1080px，居中 */
.create-wrap {
  max-width: 1080px;
  margin: 0 auto;
  width: 100%;
}

.create-form :deep(.el-form-item__label) {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 20px;
  padding-bottom: 6px;
}
.create-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
.create-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

/* 合同清单区块：细边框强调（与产品关联区块同款） */
.asset-card {
  border-color: #cfe0f5;
}

/* 单份合同卡片：浅底 + 圆角，卡片头 = 合同 N · 客户名 + 删除 */
.contract-card {
  border: 1px solid #e0ecff;
  background: #fafcff;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.contract-card:last-of-type {
  margin-bottom: 0;
}
.contract-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.contract-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.contract-fields {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.cf-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cf-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.cf-label .req {
  color: var(--danger-color);
  font-style: normal;
}
.contract-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

/* 编辑模式合同不可改提示 */
.edit-contract-tip {
  margin-bottom: 16px;
}

/* 关联产品首列：名称下方 code·分类 + 数量状态胶囊 */
.asset-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.stock-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
}
.stock-pill .dot {
  font-size: 10px;
}
.stock-pill.ok {
  color: #0c7b51;
  background: #eaf8f1;
}
.stock-pill.repeat {
  color: #4e63a8;
  background: #eef0ff;
}

/* 查看交付包入口 */
.pkg-link {
  font-size: 12px;
  color: var(--primary-color);
  cursor: pointer;
  white-space: nowrap;
}
.pkg-link:hover {
  color: var(--primary-hover);
}

/* ADR-008：Token 数量展示提示 */
.item-qty-hint {
  font-size: 12px;
  margin-top: 4px;
}

/* 销售金额：只读自动计算 */
.item-amount {
  font-weight: 600;
  color: var(--text-primary);
}
/* ADR-018 §2（PRICING-20261020）：原价快照小字（金额列下方，仅重新提交预填展示） */
.item-orig {
  font-size: 12px;
  margin-top: 4px;
}
/* ADR-020（PRICING-20261020）：服务期限双日期输入（开始/结束） */
.svc-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.total-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

/* 产品表格可横向滚动，最小宽度 720px */
.items-wrap {
  overflow-x: auto;
}
.items-wrap :deep(.el-table) {
  min-width: 720px;
}
/* 单元格顶部对齐：产品列下方 meta 撑高行时，右侧数量/单价/金额输入框仍与首列顶部对齐
   （vertical-align 只对 table-cell 生效，须加在 td 上而非块级 .cell） */
.items-wrap :deep(.el-table__body td.el-table__cell) {
  vertical-align: top;
}

/* ============ 编辑模式（2026-10-19 重构）：金额 4 卡 + 只读合同清单 ============ */
.amount-grid-4 {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 900px) {
  .amount-grid-4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
/* 金额卡：统一边框/圆角/浅底，label 12px 弱 + 值/输入 14-16px 主色 */
.create-form .amount-panel {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #f8fafc;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.create-form .amount-panel.ro {
  background: #fff;
}
.create-form .amount-panel .ap-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.create-form .amount-panel .ap-input {
  width: 100%;
}
.create-form .amount-panel .ap-input :deep(.el-input__inner) {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.create-form .amount-panel .ap-value {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}
.create-form .amount-panel .ap-foot {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 只读合同清单：客户 + 主体/状态 tag（左）+ 合同金额（右），明细逐行 名称 ×数量 金额 */
.ro-contracts {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ro-ct {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
}
.ro-ct-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.ro-ct-customer {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.ro-ct-amount {
  margin-left: auto;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.ro-ct-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ro-ct-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.ro-ct-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.ro-ct-qty {
  flex-shrink: 0;
}
.ro-ct-amt {
  margin-left: auto;
  flex-shrink: 0;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
/* ADR-018 §2（PRICING-20261020）：原价快照小字（只读概览行内） */
.ro-ct-orig {
  font-size: 12px;
  flex-shrink: 0;
}

/* ============ 订单审核面板（ADR-012，待审核项目） ============ */
.review-card {
  border-color: var(--el-color-warning-light-5, #f5d488);
}
.rv-pending-alert {
  margin-bottom: 12px;
}
.rv-contracts {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rv-ct {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 14px;
}
.rv-ct-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.rv-ct-customer {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.rv-ct-total {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-primary, var(--primary-color));
  font-variant-numeric: tabular-nums;
}
.rv-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px dashed var(--border-color);
  flex-wrap: wrap;
}
.rv-line-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1 1 240px;
}
.rv-line-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
  font-size: 13px;
  color: var(--text-primary);
}
.rv-line-qty {
  flex-shrink: 0;
  font-size: 12px;
}
.rv-lbl {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.rv-input {
  width: 160px;
  flex-shrink: 0;
}
.rv-input :deep(.el-input__inner) {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.rv-amt {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.rv-derived {
  font-size: 12px;
}
.rv-rs-tip {
  font-size: 12px;
}
.rv-foot {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid var(--border-color);
  font-size: 13px;
  color: var(--text-secondary);
}
.rv-foot b {
  color: var(--text-primary);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

/* 更多设置：金额面板与表单网格之间的间距 */
.more-card .amount-grid {
  margin-top: 4px;
}
.more-card .remark-item {
  margin-top: 16px;
}
.more-collapsed-hint {
  font-size: 12px;
  padding: 4px 0;
}
</style>
