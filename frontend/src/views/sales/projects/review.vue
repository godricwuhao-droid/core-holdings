<script setup lang="ts">
/**
 * 销售管理 - 订单审核（独立页面，2026-10-19 从编辑页拆出）
 *
 * 审核是独立动作，不是编辑：本页仅两块内容——
 *   ① 订单审核（改价确认/驳回，原编辑页内嵌面板整体迁移）
 *   ② 备注（可编辑保存）
 * 权限（后端 require_editor + 接手人守卫兜底）：
 *   - 仅商务/管理员（viewer 路由守卫直接拦截）；
 *   - pending 项目；无主单 → 先「接手」；有主单 → 仅负责人/admin（其余看只读提示）。
 * 入口：编辑页/详情页/列表页「审核订单」→ /sales/projects/:id/review
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useBack } from '@/composables/useBack'
import { ArrowLeft, CircleCheck, InfoFilled, Money, UserFilled } from '@element-plus/icons-vue'
import {
  availableQty,
  entityShort,
  formatAmountValue,
  formatMoney,
  isAmountMode,
  isAmountPrecisionValid,
  roundAmount,
  rsItemName,
  type ReviewContractInput,
  type ReviewItemInput,
} from '@/types'
import {
  claimProject,
  db,
  getAsset,
  refresh,
  rejectContracts,
  reviewProject,
  updateProject,
  allUserOptions,
  showError,
  type UserOption,
} from '@/api'
import { canAssign, canWrite, currentUser, isAdmin, isSupervisor } from '@/auth'
import TransferDialog from '@/components/TransferDialog.vue'
import ClickEditNumber from '@/components/ClickEditNumber.vue'
import ClickEditText from '@/components/ClickEditText.vue'

const route = useRoute()
const router = useRouter()
// 顶部「返回」：回上一页；深链/刷新直达（无历史）时兜底销售项目列表
const { goBack } = useBack('/sales/projects')
const projectId = computed(() => Number(route.params.id))

const proj = computed(() => db.projects.find((x) => x.id === projectId.value))
const contracts = computed(() =>
  proj.value ? db.contracts.filter((c) => c.projectId === proj.value!.id) : [],
)
const isPending = computed(() => proj.value?.status === 'pending')

// ADR-057 §3：审核页只展示可审的 pending 合同——部分确认/驳回后已确认(active)/已驳回(terminated)
// 的合同自动移出，剩余 pending 可续审
const pendingContracts = computed(() => contracts.value.filter((c) => c.status === 'pending'))
/** 勾选的合同 id（幂等默认全选：pendingContracts 只随数据变化触发——挂载 + 写操作后 refresh，
 *  每次变化重置为当前全部 pending 合同（续审就绪）；用户勾选/取消走 toggleContract 改 checkedIds，
 *  不改 pendingContracts、不触发此 watch，确认前取消勾选不会被覆盖） */
const checkedIds = ref<number[]>([])
watch(pendingContracts, (list) => {
  checkedIds.value = list.map((c) => c.id)
}, { immediate: true })
const checkedContracts = computed(() => pendingContracts.value.filter((c) => checkedIds.value.includes(c.id)))
/** sticky 条合计 = 勾选合同的 contractTotal 之和（实时派生） */
const checkedTotal = computed(() =>
  roundAmount(checkedContracts.value.reduce((s, c) => s + contractTotal(c.id), 0)),
)
function toggleContract(id: number, v: boolean | string | number) {
  checkedIds.value = v === true ? [...checkedIds.value, id] : checkedIds.value.filter((x) => x !== id)
}
/** 某合同的审核明细行（el-table :data 用） */
function linesOf(contractId: number): ReviewLine[] {
  return reviewLines.value.filter((l) => l.contractId === contractId)
}
/** 某合同的审核级状态（模板取 customer/amount 用；reviewContracts 与 contracts 同序展开，find 兜底） */
function reviewContractOf(contractId: number): ReviewContract | undefined {
  return reviewContracts.value.find((x) => x.id === contractId)
}

function editItemName(it: { assetId?: number | null }): string {
  if (!it.assetId) return '未关联产品'
  return getAsset(it.assetId)?.name ?? '产品已删除'
}

// ==================== 订单审核（原编辑页面板迁移） ====================
interface ReviewLine {
  id: number // project_items.id（审核接口 items[].itemId）
  contractId: number
  customer: string
  name: string
  assetId: number | null // ADR-062：数量上限取 availableQty 用（asset 缺失 → 上限按 origQty 兜底）
  qty: number
  unit: string
  mode: 'unit' | 'amount' | 'rs' // rs=遥感明细行（2026-10-20：金额可改，仅本单生效不回写明细单价）
  // 原价快照（ADR-018 §2，PRICING-20261020）：下单时挂牌价快照，**只读不可改**；
  // 存量订单 orig 为空 → 按当前 price/amount 兜底展示（ADR-018 Consequences）
  origPrice: number
  origAmount: number
  price: number | null // unit 模式可编辑（实际单价）
  amount: number | null // amount 模式可编辑（实际合同金额，元，最多 6 位小数，ADR-048）
  // 服务期限（ADR-020，PRICING-20261020）：confirm 可改（start ≤ end 后端 400 兜底）
  serviceStart: string
  serviceEnd: string
  origServiceStart: string // 预填原值（变更检测用）
  origServiceEnd: string
  origQty: number // 预填原值（ADR-050：数量变更检测用）
}
const reviewLines = ref<ReviewLine[]>([])
const reviewBusy = ref(false)

/** 合同级可编辑项（ADR-050：合同总价 + 客户公司名称；orig 为预填原值，变更检测用） */
interface ReviewContract {
  id: number
  customer: string
  amount: number | null // 合同总价（元，>0 且 ≤6 位小数；null = 未填，按 Σ 明细派生）
  origCustomer: string
  origAmount: number
}
const reviewContracts = ref<ReviewContract[]>([])

/** 展开审核行 + 合同级状态（watch 首次有合同时执行；db 刷新后不重建，避免覆盖编辑中值） */
watch(contracts, (cs) => {
  if (!isPending.value || reviewLines.value.length) return
  reviewContracts.value = cs.map((c) => ({
    id: c.id,
    customer: c.customer || '',
    amount: null,
    origCustomer: c.customer || '',
    origAmount: roundAmount(c.items.reduce((s, it) => s + (it.amount ?? 0), 0)),
  }))
  reviewLines.value = cs.flatMap((c) =>
    c.items.map((it) => {
      const a = it.assetId ? getAsset(it.assetId) : undefined
      const rs = it.itemId ? db.rsItems.find((x) => x.id === it.itemId) : undefined
      const mode: ReviewLine['mode'] = it.itemId ? 'rs' : a && isAmountMode(a) ? 'amount' : 'unit'
      return {
        id: it.id, contractId: c.id, customer: c.customer,
        name: editItemName(it) + (rs ? ` · ${rsItemName(rs)}` : ''),
        assetId: it.assetId ?? null, // ADR-062：展开时已有 it.assetId，补存（qtyMax 用）
        qty: it.qty, unit: a?.unit || '',
        mode,
        // ADR-018 §2（PRICING-20261020）：原价取下单时快照 origPrice/origAmount（只读）；
        // 存量订单快照为空 → 按当前 price/amount 兜底（展示口径与 ADR 一致）
        origPrice: it.origPrice ?? it.price, origAmount: it.origAmount ?? it.amount,
        price: it.price ?? null,
        amount: it.amount ?? null,
        // ADR-020（PRICING-20261020）：服务期限预填（可改）
        serviceStart: it.serviceStart ?? '',
        serviceEnd: it.serviceEnd ?? '',
        origServiceStart: it.serviceStart ?? '',
        origServiceEnd: it.serviceEnd ?? '',
        origQty: it.qty,
      }
    }),
  )
}, { immediate: true })

/** ADR-062：数量输入上限（对齐购物车截断口径）——审核行已锁定库存，
 *  该行 max = origQty + 该资产剩余可售 availableQty（与后端确认 400 口径 delta ≤ availableQty 一致）；
 *  repeatSale 行不限（null）；rs 明细行恒 1 不可改（不走本函数）；asset 缺失 → availableQty 取 0（max=origQty） */
function qtyMax(l: ReviewLine): number | null {
  if (l.mode === 'rs') return null
  const a = l.assetId ? getAsset(l.assetId) : undefined
  if (a?.repeatSale) return null
  return Math.max(l.origQty + (a ? availableQty(a) ?? 0 : 0), 1)
}
/** 超上限截断警告文案（ADR-062，与购物车统一；max 不限时不用） */
function qtyMaxMsg(l: ReviewLine): string {
  const max = qtyMax(l)
  return max == null ? '' : `「${l.name}」可用数量仅 ${max}${l.unit}，已按上限填写`
}
/** 行当前金额（unit=单价×数量 派生；amount/rs=行金额）——ADR-048：按 1e-6 规整 */
function lineAmount(l: ReviewLine): number {
  if (l.mode === 'unit') return roundAmount((l.price ?? 0) * l.qty)
  return l.amount ?? 0
}
/** 合同 Σ 明细行金额（实时派生） */
function contractLineSum(contractId: number): number {
  return roundAmount(reviewLines.value
    .filter((l) => l.contractId === contractId)
    .reduce((s, l) => s + lineAmount(l), 0))
}
/** 合同生效总额（ADR-050：填了合同总价 → 以总价为准（总额权威）；未填 → Σ 明细派生） */
function contractTotal(contractId: number): number {
  const c = reviewContracts.value.find((x) => x.id === contractId)
  return c?.amount ? c.amount : contractLineSum(contractId)
}
// ADR-057：变更检测/校验范围 = 勾选合同（未勾选的异常项不阻断勾选的确认）
/** 是否有行级变更（单价/金额/数量/服务期限；确认弹窗文案用） */
const hasLineChange = computed(() =>
  reviewLines.value.some((l) =>
    checkedIds.value.includes(l.contractId)
    && ((l.mode === 'unit' ? (l.price ?? l.origPrice) !== l.origPrice : (l.amount ?? l.origAmount) !== l.origAmount)
      || (l.mode !== 'rs' && l.qty !== l.origQty)),
  ),
)
/** 是否有合同级变更（ADR-050：合同总价 / 客户名称） */
const hasContractChange = computed(() =>
  reviewContracts.value.some((c) =>
    checkedIds.value.includes(c.id)
    && ((c.amount != null && c.amount !== c.origAmount) || c.customer.trim() !== c.origCustomer),
  ),
)
/** 合同级输入是否非法（客户名空/超 128 字、总价 ≤0 或超 6 位小数）——非法时禁用「确认下单」 */
function contractInvalid(c: ReviewContract): string {
  const name = c.customer.trim()
  if (!name) return '客户公司名称不能为空'
  if (name.length > 128) return '客户公司名称超过 128 字'
  if (c.amount != null && (!c.amount || c.amount <= 0 || !isAmountPrecisionValid(c.amount))) {
    return '合同总价须大于 0，且最多 6 位小数'
  }
  return ''
}
// ADR-057：校验范围 = 勾选合同（未勾选的异常项不阻断勾选的确认）
const contractInvalidMsg = computed(() =>
  reviewContracts.value
    .filter((c) => checkedIds.value.includes(c.id))
    .map(contractInvalid).find(Boolean) || '',
)
/** 合同级字段写入（模板 v-model 用：可选链表达式不可作赋值目标，经 setter 落值） */
function setContractField(contractId: number, field: 'customer' | 'amount', value: string | number | null) {
  const c = reviewContracts.value.find((x) => x.id === contractId)
  if (!c) return
  if (field === 'customer') c.customer = value as string
  else c.amount = value as number | null
}

// ==================== 接手机制（ADR-012 §5.1：改价/确认/驳回仅限接手账号，admin 可越过） ====================
const ownerOptions = ref<UserOption[]>([])
// 2026-10-20：显示映射用全量名册（含生态，负责人提示/rep 展示同口径）
allUserOptions().then((u) => { ownerOptions.value = u }).catch(() => {})

/** 当前用户是否可操作该订单：接手账号本人，或 admin/supervisor 兜底（ADR-051 Q3：主管为审核兜底处理人，
 *  与后端 review 守卫同口径）；未分配（businessOwner 空）→ 不可审核（后端 400「请先由商务主管分配」） */
const canReview = computed(() => {
  if (!canWrite.value || !proj.value) return false
  const owner = (proj.value.businessOwner || '').trim()
  if (!owner) return false
  return isAdmin.value || isSupervisor.value || owner === currentUser.value?.username
})
/** 转交/分配对话框（ADR-051：未分配单对主管/管理员展示「分配」，下拉仅商务 editor） */
const transferVisible = ref(false)
const transferTarget = ref<{ id: number; name: string; businessOwner?: string } | null>(null)
const transferMode = ref<'transfer' | 'assign'>('transfer')
function openTransferPanel() {
  const p = proj.value
  if (!p) return
  transferTarget.value = p
  // ADR-051：主管/管理员走「分配/改派」（下拉仅商务 editor）；商务走原「转交」语义
  transferMode.value = canAssign.value ? 'assign' : 'transfer'
  transferVisible.value = true
}
/** 负责人/管理员展示的负责人标签（2026-10-20：只显示姓名，不带账号；存量自由文本原样） */
function ownerLabel(username?: string): string {
  if (!username) return ''
  const u = ownerOptions.value.find((x) => x.username === username)
  return u?.name || username
}

async function handleClaim() {
  const p = proj.value
  if (!p) return
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
  } catch (e) {
    showError(e, '操作失败')
  } finally {
    reviewBusy.value = false
  }
}

/** 确认下单（ADR-057：只确认勾选的合同）：校验（范围=勾选）→ 二次确认 → 提交（仅传改过的行）
 *  ADR-018 §4：改价/期限只写本单，不回写平台挂牌价；
 *  部分确认后剩余 pending 合同留在本页可续审，全部确认后项目派生离 pending → 跳详情 */
async function handleConfirm() {
  if (!checkedIds.value.length) {
    ElMessage.warning('请至少勾选一个合同')
    return
  }
  const checkedSet = new Set(checkedIds.value)
  // ADR-057：校验范围 = 勾选合同（未勾选的异常项不阻断勾选的确认）
  const targetLines = reviewLines.value.filter((l) => checkedSet.has(l.contractId))
  for (const l of targetLines) {
    if (l.mode === 'unit' && !(l.price && l.price > 0)) {
      ElMessage.warning(`「${l.name}」请填写实际单价`)
      return
    }
    // amount/rs 行统一校验（2026-10-20：遥感明细行金额放开可改，仅本单生效）
    // ADR-048：金额精度由「整数元」放宽为「> 0 且最多 6 位小数」
    if (l.mode !== 'unit' && (!l.amount || l.amount <= 0 || !isAmountPrecisionValid(l.amount))) {
      ElMessage.warning(`「${l.name}」销售金额须大于 0，且最多 6 位小数`)
      return
    }
    if (lineAmount(l) <= 0) {
      ElMessage.warning(`「${l.name}」金额须大于 0`)
      return
    }
  }
  // ADR-050：合同级输入校验（客户名非空 ≤128 字；合同总价 >0 且 ≤6 位小数）
  for (const c of reviewContracts.value.filter((x) => checkedSet.has(x.id))) {
    const msg = contractInvalid(c)
    if (msg) {
      ElMessage.warning(`合同「${c.customer.trim() || '未填客户名'}」：${msg}`)
      return
    }
  }
  const partial = checkedIds.value.length < pendingContracts.value.length
  try {
    await ElMessageBox.confirm(
      (partial
        ? `确认勾选的 ${checkedIds.value.length}/${pendingContracts.value.length} 个合同？`
        : `确认项目「${proj.value?.name}」的订单？`)
      + ((hasLineChange.value || hasContractChange.value)
        ? '含合同总价/客户名称/单价/销售金额/数量/服务期限调整，确认后销售记录生效（合同总价按各明细行金额比例分摊；终审价格仅作用于本订单，不回写平台产品单价）。'
        : '确认后销售记录正式生效（数量锁定保持不变）。')
      + (partial ? '未勾选合同保持待审核，可继续审核。' : ''),
      '确认下单',
      { type: 'warning', confirmButtonText: '确认下单', cancelButtonText: '再检查一下' },
    )
  } catch {
    return
  }
  reviewBusy.value = true
  try {
    // 只提交有变更项（既有原则），且仅限勾选合同：
    // - 行级（2026-10-20 rs 行改价 / ADR-020 服务期限 / ADR-050 数量）：
    //   unit 行传 price（+qty 变更时附 qty，金额按 price×qty 后端重算）；
    //   amount 行传 amount（仅改数量时只传 qty，金额按数量比例缩放后端重算）；
    //   遥感行 qty 恒 1 不提交；
    // - 合同级（ADR-050）：仅含确实改了 customer 或 amount 的勾选合同（带 contractId）；
    // - ADR-057：contractIds = 勾选 id（OBS-ADR057-01：勾全选时省略 → 后端走整单确认路径，
    //   日志格式与改前一致；仅部分勾选才传，走部分确认路径）。
    const items: ReviewItemInput[] = targetLines
      .filter((l) =>
        (l.mode === 'unit' ? l.price !== l.origPrice : l.amount !== l.origAmount)
        || (l.mode !== 'rs' && l.qty !== l.origQty)
        || l.serviceStart !== l.origServiceStart
        || l.serviceEnd !== l.origServiceEnd,
      )
      .map((l) => {
        const base: ReviewItemInput = { itemId: l.id }
        if (l.mode === 'unit') {
          base.price = l.price ?? undefined
          if (l.qty !== l.origQty) base.qty = l.qty
        } else {
          if (l.amount !== l.origAmount) base.amount = l.amount ?? undefined
          else if (l.mode !== 'rs' && l.qty !== l.origQty) base.qty = l.qty
        }
        base.serviceStart = l.serviceStart || null
        base.serviceEnd = l.serviceEnd || null
        return base
      })
    const contractsPayload: ReviewContractInput[] = reviewContracts.value
      .filter((c) => checkedSet.has(c.id)
        && ((c.amount != null && c.amount !== c.origAmount) || c.customer.trim() !== c.origCustomer))
      .map((c) => {
        const base: ReviewContractInput = { contractId: c.id }
        if (c.amount != null && c.amount !== c.origAmount) base.amount = c.amount
        if (c.customer.trim() !== c.origCustomer) base.customer = c.customer.trim()
        return base
      })
    const confirmedCount = checkedIds.value.length
    // OBS-ADR057-01：勾全选 = 整单确认（contractIds 省略，日志无「（N 份）」）；部分勾选才传 contractIds
    const isFull = checkedIds.value.length === pendingContracts.value.length
    await reviewProject(projectId.value, {
      action: 'confirm',
      items,
      contracts: contractsPayload,
      contractIds: isFull ? undefined : checkedIds.value,
    })
    await refresh()
    // ADR-057：部分确认 → 剩余 pending 合同留在本页续审；全部确认 → 项目派生离 pending，跳详情
    if (proj.value?.status === 'pending') {
      ElMessage.success(`已确认 ${confirmedCount} 个合同，剩余待审核合同可继续审核`)
    } else {
      // ADR-018 §4（PRICING-20261020）：终审改价只写本单，不再回写平台挂牌价
      ElMessage.success('订单已确认：项目转为进行中' + (items.length || contractsPayload.length ? '，调整仅作用于本订单' : ''))
      router.push(`/sales/projects/${projectId.value}/detail`)
    }
  } catch (e) {
    showError(e, '确认下单失败')
  } finally {
    reviewBusy.value = false
  }
}

/** 驳回勾选合同（ADR-057：复用 ADR-056 reject-contracts 部分驳回）：
 *  原因必填（留痕，生态人员可见）→ 勾选合同 terminated、释放锁定；
 *  剩余 pending 合同留在本页可续审，全部驳回 → 项目 terminated → 跳详情 */
async function handleReject() {
  if (!checkedIds.value.length) return
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt(
      `将驳回勾选的 ${checkedIds.value.length} 个合同（将记录在项目上，生态人员可见；数量锁定自动释放）`,
      '驳回订单',
      { inputPattern: /\S+/, inputErrorMessage: '驳回原因不能为空', confirmButtonText: '确认驳回', cancelButtonText: '取消' },
    )
    reason = value
  } catch {
    return
  }
  reviewBusy.value = true
  try {
    const rejectedCount = checkedIds.value.length
    await rejectContracts(projectId.value, { contractIds: checkedIds.value, reason })
    await refresh()
    if (proj.value?.status === 'pending') {
      ElMessage.success(`已驳回 ${rejectedCount} 个合同，剩余待审核合同可继续审核`)
    } else {
      ElMessage.success('订单已驳回：数量锁定已释放，项目已终止')
      router.push(`/sales/projects/${projectId.value}/detail`)
    }
  } catch (e) {
    showError(e, '驳回失败')
  } finally {
    reviewBusy.value = false
  }
}

// ==================== 备注（可编辑保存） ====================
const remark = ref('')
const savingRemark = ref(false)
async function saveRemark() {
  const p = proj.value
  if (!p) return
  savingRemark.value = true
  try {
    // PUT 白名单仅基本信息字段；派生字段（customer/subject/金额）传原值，后端不采信
    await updateProject(p.id, {
      name: p.name,
      customer: p.customer,
      industry: p.industry,
      rep: p.rep,
      businessOwner: p.businessOwner ?? '',
      subject: p.subject,
      expectedAmount: 0,
      contractAmount: 0,
      expectedSignDate: p.expectedSignDate,
      lastFollowDate: p.lastFollowDate,
      remark: remark.value,
      items: [],
    })
    ElMessage.success('备注已保存')
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    savingRemark.value = false
  }
}

function goDetail() {
  router.push(`/sales/projects/${projectId.value}/detail`)
}

onMounted(async () => {
  await refresh()
  const p = db.projects.find((x) => x.id === projectId.value)
  if (!p) {
    ElMessage.warning('项目不存在或无查看权限')
    router.replace('/sales/projects')
    return
  }
  remark.value = p.remark || ''
  if (p.status !== 'pending') {
    // 审核仅针对待审核订单（确认后 active / 驳回或终止 terminated → 均无审核意义）
    ElMessage.warning('该订单不是待审核状态，无需审核')
    router.replace(`/sales/projects/${p.id}/detail`)
  }
})

/** 页面渲染所需的最小数据（避免模板空引用） */
const pageReady = computed(() => proj.value != null)
</script>

<template>
  <div class="page-container">
    <div v-if="pageReady" v-show="proj" class="review-page">
      <!-- 页头：返回 + 标题 + 项目信息 -->
      <div class="page-head">
        <div class="ph-left">
          <a class="back-link" @click="goBack"><el-icon><ArrowLeft /></el-icon>返回</a>
          <h1>订单审核 <span class="rh-name">{{ proj?.name }}</span></h1>
          <div class="ph-meta">
            <span class="mono">{{ proj?.code }}</span>
            <el-tag type="warning" effect="light" size="small" class="st-tag">待审核</el-tag>
            <el-tag type="info" effect="light" size="small" class="st-tag">数量已锁定</el-tag>
          </div>
        </div>
        <div class="head-actions" v-if="!canReview">
          <!-- ADR-051：未分配单——主管/管理员展示「分配」（下拉仅商务 editor，分配后才能审核） -->
          <el-button v-if="!proj?.businessOwner && canAssign" type="primary" :icon="UserFilled" @click="openTransferPanel">
            分配
          </el-button>
          <!-- 商务（editor）：无主单接手给自己（ADR-012） -->
          <el-button v-else-if="!proj?.businessOwner" type="primary" :icon="UserFilled" :loading="reviewBusy" @click="handleClaim">
            接手此单
          </el-button>
        </div>
      </div>

      <!-- 无审核权限提示（有主单 + 非负责人商务/admin/supervisor 外） -->
      <el-card v-if="canReview === false && proj?.businessOwner" shadow="never">
        <div class="no-access">
          <p>该订单由商务负责人 <b>{{ ownerLabel(proj?.businessOwner) }}</b> 负责审核，仅其本人（或管理员/商务主管）可操作。</p>
          <p class="muted">如负责人无法处理，请联系管理员/商务主管介入，或由负责人在编辑页「转交」后重新审核。</p>
        </div>
      </el-card>

      <!-- ADR-051：未分配（businessOwner 空）——后端 400「请先由商务主管分配」，前端提示先分配 -->
      <el-card v-else-if="!proj?.businessOwner" shadow="never">
        <div class="no-access">
          <p>该订单尚未分配商务负责人，请先由商务主管「分配」后再审核。</p>
        </div>
      </el-card>

      <template v-else-if="canReview">
        <!-- ① 订单审核 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Money /></el-icon></span>
            <div>
              <div class="bh-title">订单审核<span class="muted" style="font-weight: 400;">（待审核 → 确认生效）</span></div>
            </div>
          </div>
          <!-- ADR-059：顶部 4 行说明条已删（细节由合同头/列头 tooltip 覆盖） -->
          <!-- ADR-057 方案 A：每合同一张表——容器块（圆角 + 边框）= 合同头（勾选 + 客户名 + 主体 + 合同总价 + 小计）
               + 明细 el-table（表头一次声明列语义、行高统一、金额/数字列 center）；
               只展示 pending 合同（部分确认后已确认/已驳回自动移出，剩余可续审） -->
          <div class="rv-contracts">
            <div v-for="c in pendingContracts" :key="c.id" class="rv-ct">
              <!-- 合同头（仿购物车 .table-head 范式，单行）：左 = 客户名（点击即改，ADR-060）+ 主体 tag；
                   右 = 合同总价（点击总价数字直接编辑，ADR-060；默认 = Σ 明细派生）
                   2026-11-10 UI：勾选框自合同头移至明细表首列（语义不变：按合同一个，见下方首列） -->
              <div class="rv-ct-head">
                <!-- ADR-050：客户公司名称可改（trim 后非空、≤128 字，前端校验 + 后端兜底）；
                     ADR-060：改点击即改（ClickEditText：常态文本，点击出 el-input，失焦/回车提交 trim、Esc 还原）；
                     空客户名 → 弱警示提示（会拦「确认下单」） -->
                <ClickEditText
                  class="rv-ct-customer"
                  width="260px"
                  :maxlength="128"
                  placeholder="客户公司名称"
                  :model-value="reviewContractOf(c.id)?.customer ?? ''"
                  @update:model-value="(v: string) => setContractField(c.id, 'customer', v)"
                >
                  <span v-if="(reviewContractOf(c.id)?.customer ?? '').trim()" class="rv-ct-customer-val">
                    {{ reviewContractOf(c.id)?.customer }}
                  </span>
                  <span v-else class="rv-ct-customer-empty">未填写客户名称</span>
                </ClickEditText>
                <el-tag v-if="c.subject" size="small" effect="plain" class="rv-ct-subject">{{ entityShort(c.subject) }}</el-tag>
                <div class="rv-ct-right">
                  <!-- ADR-050：合同总价（总额权威）——默认 = Σ 明细派生；点击总价数字直接编辑（ADR-060），
                       填写后按各明细行金额比例分摊；清空 → amount=null 回退 Σ 明细派生 -->
                  <span class="rv-lbl">合同总价（元）</span>
                  <el-tooltip content="默认 = 明细合计；点击可直接改为自定义总价（总额权威，按各明细行金额比例分摊）" placement="top">
                    <span class="rv-lbl-tip"><el-icon><InfoFilled /></el-icon></span>
                  </el-tooltip>
                  <!-- 常态始终显有效总价（amount=null 时 = Σ 明细派生）；点击编辑初始值 = 当前有效总价，
                       提交写 amount（数字 → 覆盖；清空 → null 回退派生） -->
                  <ClickEditNumber
                    class="rv-ct-amount"
                    width="150px"
                    :min="0"
                    :model-value="contractTotal(c.id)"
                    @update:model-value="(v: number | null) => setContractField(c.id, 'amount', v)"
                  >
                    {{ formatMoney(contractTotal(c.id)) }}
                  </ClickEditNumber>
                </div>
              </div>
              <!-- 明细表：无竖线 + stripe；列宽由 column 声明（删 Grid 硬编码）；
                   行结构 = 主区 40px + 副区 18px（仿购物车 .cart-cell，行高统一、跨列输入框对齐） -->
              <el-table :data="linesOf(c.id)" stripe size="small" class="rv-table">
                <!-- 2026-11-10 UI：勾选框自合同头移至明细表首列（纯挪位）——每行渲染同一个 el-checkbox，
                     与合同头原实现完全同源（checkedIds.includes(c.id) / toggleContract(c.id, v)）：
                     整表所有行勾选框状态一致、控制同一张合同；confirm 逻辑一字未动 -->
                <el-table-column width="48" align="center" header-align="center">
                  <template #default>
                    <el-checkbox
                      :model-value="checkedIds.includes(c.id)"
                      @change="(v: boolean | string | number) => toggleContract(c.id, v)"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="产品" min-width="180" align="left" header-align="left">
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main">
                        <el-tooltip :content="l.name" placement="top">
                          <span class="rv-line-name">{{ l.name }}</span>
                        </el-tooltip>
                      </div>
                      <div class="cell-hint" aria-hidden="true"></div>
                    </div>
                  </template>
                </el-table-column>
                <!-- ADR-050：数量可编辑（非遥感行，整数 ≥1，放大时后端校验可用库存）；
                     ADR-059：点击即改（常态整数文本，点击出框）；遥感行恒 1 静态不可点；
                     ADR-062：超上限（origQty+availableQty）截断 + 一次黄警告（repeatSale 不限） -->
                <el-table-column label="数量" width="100" align="center" header-align="center">
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-center">
                        <ClickEditNumber
                          v-if="l.mode !== 'rs'"
                          v-model="l.qty"
                          :min="1"
                          :precision="0"
                          :step="1"
                          :max="qtyMax(l)"
                          :max-message="qtyMaxMsg(l)"
                          width="64px"
                          placeholder="数量"
                        >
                          {{ l.qty }}
                        </ClickEditNumber>
                        <span v-else class="muted rv-dash">1</span>
                        <span class="muted rv-unit">{{ l.unit }}</span>
                      </div>
                      <div class="cell-hint cell-hint-center">
                        <span v-if="l.mode !== 'rs' && qtyMax(l) != null" class="muted">最大 {{ qtyMax(l) }}</span>
                        <span v-else-if="l.mode === 'rs'" class="muted">1</span>
                      </div>
                    </div>
                  </template>
                </el-table-column>
                <!-- ADR-018 §2（PRICING-20261020）：原价列只读——展示下单时挂牌价快照（unit=原单价、amount/rs=原金额）；
                     存量订单 orig 为空时数据层已按当前 price/amount 兜底（见 reviewLines 展开逻辑），恒展示 -->
                <el-table-column label="原单价/金额（元）" width="120" align="right" header-align="right">
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-right">
                        <span class="muted">{{ formatMoney(l.mode === 'unit' ? l.origPrice : l.origAmount) }}</span>
                      </div>
                      <div class="cell-hint" aria-hidden="true"></div>
                    </div>
                  </template>
                </el-table-column>
                <!-- 实际单价：unit 行可编辑（ADR-048：最多 6 位小数）；
                     ADR-059：点击即改（常态 ¥ 千分位文本，点击出框）；amount/rs 行不适用（静态 -） -->
                <el-table-column label="实际单价（元）" width="140" align="right" header-align="right">
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-right">
                        <ClickEditNumber
                          v-if="l.mode === 'unit'"
                          v-model="l.price"
                          :min="0"
                          placeholder="实际单价"
                        >
                          {{ formatMoney(l.price) }}
                        </ClickEditNumber>
                        <span v-else class="muted rv-dash">-</span>
                      </div>
                      <div class="cell-hint" aria-hidden="true"></div>
                    </div>
                  </template>
                </el-table-column>
                <!-- 销售金额：amount/rs 行可编辑（ADR-048：最多 6 位小数；rs 行仅本单生效不回写明细单价）；
                     ADR-059：点击即改（常态 ¥ 千分位文本，点击出框）；
                     unit 行 = 派生只读（单价×数量，静态不可点）+ 副区「参考单价 ≈ …」 -->
                <el-table-column label="销售金额（元）" width="160" align="right" header-align="right">
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-right">
                        <ClickEditNumber
                          v-if="l.mode !== 'unit'"
                          v-model="l.amount"
                          :min="0"
                          placeholder="销售金额"
                        >
                          {{ formatMoney(l.amount) }}
                        </ClickEditNumber>
                        <span v-else class="rv-line-amt">{{ formatMoney(lineAmount(l)) }}</span>
                      </div>
                      <div class="cell-hint">
                        <span v-if="l.mode !== 'unit' && l.qty > 0" class="rv-derived">
                          参考单价 ≈ {{ formatAmountValue(lineAmount(l) / l.qty, false) }} 元/{{ l.mode === 'rs' ? '份' : (l.unit || '个') }}
                        </span>
                      </div>
                    </div>
                  </template>
                </el-table-column>
                <!-- ADR-020（PRICING-20261020）：服务期限可改（选填）；
                     ADR-059：单列拆「开始时间 / 结束时间」两个表头列（各自 el-date-picker，
                     分别绑 l.serviceStart / l.serviceEnd，数据模型不变）；遥感明细行按期数售卖两列均 - -->
                <el-table-column label="开始时间" width="150" align="center" header-align="center">
                  <template #header>
                    <el-tooltip content="选填（开始/结束日期需成对填写；遥感明细行按期数售卖，不填期限）" placement="top">
                      <span>开始时间</span>
                    </el-tooltip>
                  </template>
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-center">
                        <el-date-picker
                          v-if="l.mode !== 'rs'"
                          v-model="l.serviceStart"
                          type="date"
                          value-format="YYYY-MM-DD"
                          size="small"
                          placeholder="开始"
                          class="rv-date"
                        />
                        <span v-else class="muted rv-dash">-</span>
                      </div>
                      <div class="cell-hint" aria-hidden="true"></div>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="结束时间" width="150" align="center" header-align="center">
                  <template #header>
                    <el-tooltip content="选填（开始/结束日期需成对填写；遥感明细行按期数售卖，不填期限）" placement="top">
                      <span>结束时间</span>
                    </el-tooltip>
                  </template>
                  <template #default="{ row: l }">
                    <div class="rv-cell">
                      <div class="cell-main cell-main-center">
                        <el-date-picker
                          v-if="l.mode !== 'rs'"
                          v-model="l.serviceEnd"
                          type="date"
                          value-format="YYYY-MM-DD"
                          size="small"
                          placeholder="结束"
                          class="rv-date"
                        />
                        <span v-else class="muted rv-dash">-</span>
                      </div>
                      <div class="cell-hint" aria-hidden="true"></div>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>

        <!-- ② 备注 -->
        <div class="form-card">
          <div class="block-head">
            <div>
              <div class="bh-title">备注</div>
              <div class="bh-sub">审核备注（如改价说明、跟进约定），保存后对项目可见</div>
            </div>
          </div>
          <el-input
            v-model="remark"
            type="textarea"
            :rows="3"
            placeholder="填写审核备注（选填）"
          />
          <div style="margin-top: 10px; text-align: right;">
            <el-button size="small" :loading="savingRemark" @click="saveRemark">保存备注</el-button>
          </div>
        </div>

        <!-- ADR-057 §2：sticky 底部工具条（合并原 .rv-foot 项目总额 + .bottom-actions 操作）——
             照购物车 .cart-checkout 范式（sticky 白卡 + 描边 + 轻投影）。
             显式豁免全局非悬浮 .bottom-actions 规范（购物车 checkout 本就是既有特例）。
             勾选数 = 0 → 确认/驳回禁用；返回详情/改派转交入口并入此条保留 -->
        <div class="rv-checkout">
          <div class="co-left">
            <span class="co-selected">已选 <b>{{ checkedIds.length }}</b> / {{ pendingContracts.length }} 个合同</span>
            <span class="co-divider" aria-hidden="true"></span>
            <div class="co-total">
              <small>合计</small>{{ formatMoney(checkedTotal) }}
            </div>
          </div>
          <div class="co-actions">
            <el-button @click="goDetail">返回详情</el-button>
            <!-- ADR-051：主管/管理员「改派」（assign 模式，下拉仅商务 editor）；商务「转交」（原语义） -->
            <el-button plain :loading="reviewBusy" @click="openTransferPanel">
              {{ canAssign ? '改派' : '转交' }}
            </el-button>
            <el-button type="danger" plain :loading="reviewBusy" :disabled="!checkedIds.length" @click="handleReject">
              驳回
            </el-button>
            <el-tooltip :content="contractInvalidMsg || ''" :disabled="!contractInvalidMsg" placement="top">
              <el-button
                type="primary"
                :icon="CircleCheck"
                :loading="reviewBusy"
                :disabled="!checkedIds.length || !!contractInvalidMsg"
                @click="handleConfirm"
              >
                确认下单
              </el-button>
            </el-tooltip>
          </div>
        </div>
      </template>
    </div>

    <TransferDialog v-model="transferVisible" :project="transferTarget" :mode="transferMode" />
  </div>
</template>

<style scoped>
/* 2026-11-10 UI：项目名放大 + 改深色（原 18px 灰不显眼）——与 h1 标题（22px/600）同规格，醒目 */
.rh-name {
  font-size: 22px;
  color: var(--text-primary);
  font-weight: 600;
  margin-left: 4px;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  margin-bottom: 8px;
}
.back-link:hover {
  color: var(--primary-color);
}
.mono {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
  color: var(--text-secondary);
}
.no-access {
  padding: 40px 24px;
  text-align: center;
  color: var(--text-primary);
  font-size: 14px;
  line-height: 2;
}
.no-access .muted {
  font-size: 13px;
}

/* 页头关键信息：代码（等宽）+ 状态标签（待审核 / 数量已锁定），去冗余 */
.ph-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.st-tag {
  flex-shrink: 0;
}
/* ==================== ADR-057 方案 A：每合同一张表 ====================
   合同 = 容器块（10px 圆角 + --border-color 边框，合同间 16px 间距清晰分隔）：
   合同头（勾选 + 客户名 small + 主体 tag | 合同总价输入 + 小计）+ 明细 el-table
   （表头一次声明列语义、行高统一、金额/数字列 center、输入框占满列宽） */
.rv-contracts {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.rv-ct {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  overflow: hidden;
}
/* 合同头（仿购物车 .table-head 范式，单行）：表头底 #F8FAFC（UI 规范） */
.rv-ct-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: #f8fafc;
  border-bottom: 1px solid var(--border-color);
}
/* 2026-11-10 UI：合同总价常态文字改深蓝（品牌主色 #1769D4 的深色变体，比原正文色更醒目）；
   hover/编辑态沿用 ClickEditNumber 既有浅蓝可编辑提示，不冲突。
   选择器带 .rv-ct-right 前缀提升特异性，稳定压过组件内 .cen-view 常态色 */
.rv-ct-right .rv-ct-amount :deep(.cen-view) {
  color: #0f4c9e;
}
/* ADR-060：客户名称点击即改（ClickEditText）——常态文本 14px/600（合同头最醒目之一）；
   空客户名弱警示（会拦「确认下单」，复用「建设中」橙 token，不新增色值） */
.rv-ct-customer {
  max-width: 100%;
}
.rv-ct-customer :deep(.cet-view) {
  font-size: 14px;
  font-weight: 600;
}
.rv-ct-customer-empty {
  color: var(--warning-color);
  font-weight: 500;
}
.rv-ct-subject {
  flex-shrink: 0;
}
/* 合同头右侧：合同总价（标签 + 提示图标 + 可点击总价数字，默认 = Σ 明细派生） */
.rv-ct-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.rv-lbl {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: 13px; /* ADR-060：合同头标签 12px → 13px */
  color: var(--text-secondary);
}
/* 合同总价说明图标（tooltip 触发点） */
.rv-lbl-tip {
  display: inline-flex;
  align-items: center;
  color: var(--text-secondary);
  cursor: help;
  flex-shrink: 0;
}
.rv-lbl-tip .el-icon {
  font-size: 14px;
}
/* ADR-060：合同总价点击即改（ClickEditNumber）——常态始终显有效总价数字（组件自带 13px/600） */
/* 明细表：表头 12px 灰字加粗 + 行舒展（仿购物车 el-table 口径，无竖线 + stripe 由组件属性提供） */
.rv-table :deep(th.el-table__cell) {
  padding: 10px 0;
}
.rv-table :deep(th .cell) {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}
.rv-table :deep(td.el-table__cell) {
  padding: 12px 0;
}
/* 统一单元格结构（仿购物车 .cart-cell）：主区 40px 垂直居中 + 副区 18px（允许空占位），
   保证每行每列总高度一致、跨列输入框水平对齐 */
.rv-cell {
  display: flex;
  flex-direction: column;
}
.cell-main {
  height: 40px;
  display: flex;
  align-items: center;
  min-width: 0;
}
.cell-main-center {
  justify-content: center;
}
/* 金额列（原单价/实际单价/销售金额）：数据右对齐（表头仍居中）；
   ClickEditNumber 常态文本/编辑框贴右（组件默认居中，此处覆盖） */
.cell-main-right {
  justify-content: flex-end;
}
.cell-main-right :deep(.cen-view) {
  justify-content: flex-end;
}
.cell-main-right :deep(.cen-input) {
  width: 150px;
  margin-left: auto;
}
.cell-hint {
  height: 18px;
  font-size: 11px;
  line-height: 18px;
  overflow: hidden;
  white-space: nowrap;
}
.cell-hint-center {
  text-align: center;
}
/* 产品名列：单行省略（全文由 el-tooltip hover 展示） */
.rv-line-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-primary);
}
/* 数量单位（ADR-059：数量值由 ClickEditNumber 渲染，此处仅留单位） */
.rv-unit {
  margin-left: 4px;
  font-size: 12px;
  white-space: nowrap;
}
/* unit 行销售金额（派生只读：单价×数量；ADR-059：单价/金额可编辑格由 ClickEditNumber 渲染） */
.rv-line-amt {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* 派生提示（参考单价 ≈ …）：副区单行省略（显式辅助色，同购物车口径；销售金额列右对齐） */
.rv-derived {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: right;
  color: #71829a;
}
/* 服务期限日期输入（ADR-059：拆「开始时间/结束时间」两列，各 136px） */
.rv-date {
  width: 136px;
  flex-shrink: 0;
}
/* 不适用占位「-」（amount/rs 行实际单价列、rs 行数量/开始/结束时间列）：整列宽内居中 */
.rv-dash {
  display: block;
  text-align: center;
}

/* ==================== ADR-057 §2：sticky 底部工具条（照购物车 .cart-checkout 范式） ====================
   页面底部留 ~130px 让位（条高 ~62px + bottom 16px + 间距） */
.review-page {
  padding-bottom: 130px;
}
.rv-checkout {
  position: sticky;
  bottom: 16px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 20px;
  box-shadow: 0 6px 20px rgba(26, 46, 78, 0.08);
}
.co-left {
  display: flex;
  align-items: center;
  gap: 13px;
  flex-wrap: wrap;
}
.co-selected {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.2;
}
.co-selected b {
  font-weight: 600;
  color: var(--text-primary);
}
.co-divider {
  width: 1px;
  height: 16px;
  background: var(--divider-color);
  flex: 0 0 auto;
  align-self: center;
}
.co-total {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
}
.co-total small {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.2;
}
.co-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-wrap: wrap;
}
</style>
