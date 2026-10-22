<script setup lang="ts">
/**
 * 销售管理 - 销售项目详情（ADR-007 合同清单）
 *
 * 从「销售项目列表」行点击 / 「产品详情-关联销售项目」进入。
 * 只读展示项目信息 + 「合同清单」区块（每份合同一张卡片，明细并入卡片展示）；
 * 合同级操作：交付 / 终止（PATCH /contracts/{id}/status，数量联动最小单位）；
 * 项目状态由合同状态自动派生，本页不提供项目级状态变更入口。
 * 「编辑」跳转编辑页（仅基本信息）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, EditPen, Folder, InfoFilled, Tickets } from '@element-plus/icons-vue'
import {
  PROJECT_STATUS,
  derivedUnitPrice,
  formatDate,
  formatMoney,
  formatTokens,
  isAmountMode,
  rsItemName,
  tagInfo,
  type Contract,
} from '@/types'
import { allUserOptions, changeContractStatus, claimProject, db, getAsset, patchContractFields, refillProjectCart, refresh, showError, type UserOption } from '@/api'
import TransferDialog from '@/components/TransferDialog.vue'
import WithdrawProjectDialog from '@/components/WithdrawProjectDialog.vue'
import { canWrite, isViewer, isAdmin, currentUser, NO_PERM_TIP } from '@/auth'

// 生态人员（viewer）：数据已按「自己下单」在后端过滤，能进入本页即自己项目——
// ADR-028（2026-10-21）：订单提交后禁编辑（头部「编辑」不渲染 + goEdit 兜底拦截），
// 权限退化为「只读 + 撤销 / 终止 / 重新提交（回购物车）」；交付、编辑仍仅商务/管理员。
// 越权 URL 访问他人项目时 bootstrap 无该项目 → 上方 el-empty「未找到该销售项目」
const canOwn = computed(() => canWrite.value || isViewer.value)

/** 人员展示：账号/姓名 → 姓名（2026-10-20：只显示姓名不带账号；存量自由文本原样）
 *  显示映射用全量名册（含生态）——原商务专属列表查不到生态 rep → 裸账号外露 */
const ownerOptions = ref<UserOption[]>([])
allUserOptions().then((u) => { ownerOptions.value = u }).catch(() => {})
function userName(v?: string): string {
  if (!v) return ''
  const u = ownerOptions.value.find((x) => x.username === v) || ownerOptions.value.find((x) => x.name === v)
  return u?.name || v
}
/** ADR-012 §5.1：「审核订单」入口仅对接手人（或 admin 越过）展示；未接手/他人接手 → 隐藏（后端守卫兜底） */
const canReview = computed(() => canWrite.value && !!project.value?.businessOwner
  && (isAdmin.value || project.value!.businessOwner === currentUser.value?.username))

/** ADR-012 §5.1 纯移交制：详情页无主单「接手」（转交走 TransferDialog 下拉选人） */
async function handleClaim() {
  const p = project.value
  if (!p || p.businessOwner) return
  try {
    await ElMessageBox.confirm(
      `确认接手「${p.name}」？接手后你将负责该订单的定价审核（确认下单/驳回）。`,
      '接手订单',
      { type: 'warning', confirmButtonText: '确认接手', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await claimProject(p.id)
    await refresh()
    ElMessage.success('接手成功，现在可以审核该订单了')
  } catch (e) {
    showError(e, '操作失败')
  }
}

const transferVisible = ref(false)
const transferTarget = ref<{ id: number; name: string; businessOwner?: string } | null>(null)
function openTransfer() {
  const p = project.value
  if (!p) return
  transferTarget.value = p
  transferVisible.value = true
}

/**
 * 撤销待审核订单（ADR-026 / TASK-FE-029）：仅 `pending` 且「本人下单（creator==当前登录）或 admin」可见。
 * 商务（editor）不显示——商务走「驳回」；viewer 他人单不可见（后端 creator 归属守卫兜底）。
 * 注：`ProjectOut` 自 2026-10-21 起已输出 `creator`（bootstrap 同步），按账号精确比对；
 * 存量项目 creator 为空时按「可见即本人单」兜底（后端归属守卫兜底）。
 */
const canWithdraw = computed(() => {
  const p = project.value
  if (!p || p.status !== 'pending') return false
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

/**
 * 重新提交（ADR-027 / TASK-FE-031）：已终止项目不再跳 create 页 copy 模式——
 * 调 POST /projects/{id}/refill-cart 确保明细在下单人购物车（幂等）→ `refresh()` → 跳 /cart 改单重提。
 * 失败 showError 并停留本页，不跳转。
 */
const refilling = ref(false)
async function handleResubmit() {
  const p = project.value
  if (!p || refilling.value) return
  refilling.value = true
  try {
    const res = await refillProjectCart(p.id)
    await refresh()
    const base = res.alreadyRefilled ? '明细已在购物车，可直接修改后提交' : '明细已回填购物车，可修改后提交'
    ElMessage.success(res.skipped > 0 ? `${base}（${res.skipped} 行未能回填，请核对明细）` : base)
    router.push('/cart')
  } catch (e) {
    showError(e, '重新提交失败')
  } finally {
    refilling.value = false
  }
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const project = computed(() => db.projects.find((x) => x.id === projectId.value) ?? null)

/** 项目名下合同（bootstrap.contracts 按 projectId 过滤，id 升序 = 生成顺序） */
const contracts = computed<Contract[]>(() =>
  db.contracts.filter((c) => c.projectId === projectId.value).sort((a, b) => a.id - b.id),
)

/** 客户展示：项目 customer 非空直接显示；为空时从合同客户去重提取（2026-10-20 问题12a）——
 *  去重后 1 个 → 直接显示该客户名；多个 → 「N 位客户」（N 为去重客户数）；0 个 → '-'
 *  （修复原按合同数回退：空客户合同/空草稿会误显示「1 位客户」） */
const customerText = computed(() => {
  const p = project.value
  if (!p) return '-'
  if (p.customer) return p.customer
  const names = Array.from(new Set(contracts.value.map((c) => (c.customer || '').trim()).filter(Boolean)))
  if (names.length === 1) return names[0]
  return names.length ? `${names.length} 位客户` : '-'
})

onMounted(async () => {
  await refresh()
})

function goBack() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到销售项目列表，避免退出应用
  if (window.history.state?.back) router.back()
  else router.push('/sales/projects')
}

function goEdit() {
  // ADR-028（2026-10-21）：生态人员订单提交后禁编辑——兜底拦截（按钮已不渲染、路由也不放行 edit，
  // 此判断仅防程序化调用/未来入口遗漏；后端 PUT 对 viewer 一律 403，双保险）
  if (isViewer.value) {
    ElMessage.warning('订单已提交，不可编辑，如需修改请「撤销」后重新下单')
    return
  }
  const p = project.value
  if (!p) return
  // 2026-10-19：订单审核独立页——商务/管理员的 pending 单 → /review（仅订单审核+备注）；其余状态 → /edit
  const toReview = p.status === 'pending'
  router.push(`/sales/projects/${p.id}/${toReview ? 'review' : 'edit'}`)
}

/** 明细关联产品：名称（编号），可点击跳产品详情 */
function itemAssetName(assetId: number | null): string {
  const a = assetId ? getAsset(assetId) : undefined
  return a ? `${a.name}（${a.code}）` : '未关联产品'
}

function goAssetDetail(assetId: number | null) {
  if (assetId) router.push(`/assets/${assetId}/detail`)
}

/** ADR-008/ADR-017：明细行产品是否包量定价（单价列改派生参考展示，元/{unit}） */
function isAmountItem(assetId: number | null): boolean {
  const a = assetId ? getAsset(assetId) : undefined
  return !!a && isAmountMode(a)
}

/** ADR-008：明细数量展示——包量定价（Token）产品用 formatTokens，其余原数 */
function itemQtyText(assetId: number | null, qty: number): string {
  return isAmountItem(assetId) ? formatTokens(qty) : String(qty)
}

/** ADR-011：明细列展示——itemId 非空显示 rsItemName（查 db.rsItems），空则 '-' */
function itemRsName(itemId: number | null | undefined): string {
  if (itemId == null) return '-'
  const r = db.rsItems.find((x) => x.id === itemId)
  return r ? rsItemName(r) : '-'
}

// ============================================================
// 合同状态操作（ADR-007：交付 / 终止，数量联动最小单位）
// ============================================================
const actingContractId = ref<number | null>(null)

/** 交付（active → delivered）：扣减数量并生成交付记录 */
async function deliverContract(c: Contract) {
  try {
    await ElMessageBox.confirm(
      `确认交付 ${c.code}？将扣减数量并生成交付记录。`,
      '交付确认',
      { type: 'warning', confirmButtonText: '确认交付', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await changeContract(c, 'delivered')
}

/** 终止（active → terminated 释放锁定；delivered → terminated 撤销交付并回退） */
async function terminateContract(c: Contract) {
  const msg =
    c.status === 'delivered'
      ? '已交付终止将撤销交付并回退售出数量与金额，确认终止？'
      : '确认终止？将释放该销售记录锁定数量。'
  try {
    await ElMessageBox.confirm(msg, '终止销售记录确认', {
      type: 'warning',
      confirmButtonText: '确认终止',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await changeContract(c, 'terminated')
}

async function changeContract(c: Contract, status: 'delivered' | 'terminated') {
  if (actingContractId.value != null) return // BUG-10：已有合同状态变更在飞，忽略连点（按钮同时 loading+禁用）
  actingContractId.value = c.id
  try {
    await changeContractStatus(c.id, status)
    ElMessage.success(
      status === 'delivered'
        ? `销售记录 ${c.code} 已交付，产品数量与交付记录已自动更新`
        : `销售记录 ${c.code} 已终止`,
    )
  } catch (e) {
    showError(e, '销售记录状态变更失败')
  } finally {
    actingContractId.value = null
  }
}

// ============================================================
// 合同时间节点录入（ADR-019，PRICING-20261020）：PATCH /contracts/{id}
// - signedDate（合同签订时间）：商务/管理员；录入即 active→delivering；录后不可清空（后端 400 兜底）
// - scheduledDeliveryDate（预计交付时间）：仅 admin；仅 delivering 可录/改/清空（null 允许）
// 403/400 文案由后端 detail 给出，经 showError 统一提示
// ============================================================
const dateDialog = reactive({
  visible: false,
  contractId: 0,
  field: 'signedDate' as 'signedDate' | 'scheduledDeliveryDate',
  value: '',
})
const dateSaving = ref(false)
function openDateDialog(c: Contract, field: 'signedDate' | 'scheduledDeliveryDate') {
  dateDialog.contractId = c.id
  dateDialog.field = field
  dateDialog.value = (field === 'signedDate' ? c.signedDate : c.scheduledDeliveryDate) ?? ''
  dateDialog.visible = true
}
async function submitDateDialog() {
  if (!dateDialog.value) {
    // 签订时间不可清空（ADR-019）；预计交付时间允许清空（payload 传 null）
    if (dateDialog.field === 'signedDate') {
      ElMessage.warning('请选择签订时间（已录入后不可清空）')
      return
    }
    dateSaving.value = true
    try {
      await patchContractFields(dateDialog.contractId, { scheduledDeliveryDate: null })
      ElMessage.success('预计交付时间已清空')
      dateDialog.visible = false
    } catch (e) {
      showError(e, '更新预计交付时间失败')
    } finally {
      dateSaving.value = false
    }
    return
  }
  dateSaving.value = true
  try {
    if (dateDialog.field === 'signedDate') {
      await patchContractFields(dateDialog.contractId, { signedDate: dateDialog.value })
      ElMessage.success('签订时间已录入，销售记录转为「交付中」')
    } else {
      await patchContractFields(dateDialog.contractId, { scheduledDeliveryDate: dateDialog.value })
      ElMessage.success('预计交付时间已更新')
    }
    dateDialog.visible = false
  } catch (e) {
    showError(e, '时间更新失败')
  } finally {
    dateSaving.value = false
  }
}
</script>

<template>
  <div class="page-container">
    <div class="detail-wrap">
      <!-- 页面标题区 -->
      <div class="page-head">
        <div>
          <a class="back-link" @click="goBack">
            <el-icon><ArrowLeft /></el-icon>
            返回销售项目
          </a>
          <div class="title-row">
            <h1>{{ project?.name ?? '销售项目详情' }}</h1>
            <el-tag
              v-if="project"
              :type="tagInfo(PROJECT_STATUS, project.status).tag"
              size="large"
              effect="light"
            >
              {{ tagInfo(PROJECT_STATUS, project.status).label }}
            </el-tag>
          </div>
        </div>
        <!-- FIX-20261022 / BUG-39：原 tooltip 包裹了整块动作按钮（hover 撤销/重新提交也会弹「已完成/已终止不可编辑」），
             现收窄到「编辑 / 审核订单」按钮本身 -->
        <div class="head-actions" v-if="project">
          <span>
            <!-- ADR-012 §5.1 纯移交制：无主→「接手」；有主→仅负责人「转交」（下拉选人）或 admin 越过；
                 他人负责的单据对普通商务不显示（审核订单按钮仅接手人可见） -->
            <el-button
              v-if="canWrite && (project.status === 'pending' || project.status === 'active')
                   && (!project.businessOwner
                       || project.businessOwner === currentUser?.username
                       || isAdmin)"
              :type="project.businessOwner ? 'info' : 'success'"
              @click="project.businessOwner ? openTransfer() : handleClaim()"
            >
              {{ project.businessOwner ? '转交' : '接手' }}
            </el-button>
            <!-- ADR-012 §5.1：pending 项目仅负责人/admin 可审核（走独立审核页 /review）；active 可编辑基本信息。
                 ADR-028（2026-10-21）：生态人员订单提交后禁编辑 → 头部「编辑」入口整块不渲染
                 （连禁用态也不给；viewer 唯一改单路径 =「撤销」→ 购物车重下，后端 PUT 对 viewer 一律 403）
                 FIX-20261022 / BUG-21：「交付中」纳入可编辑（与列表页 canEditProject / 后端 PUT 一致，
                 原实现把 delivering 归到「不可编辑」分支，与列表页口径相反） -->
            <el-tooltip
              v-if="!isViewer && (project.status === 'active' || project.status === 'delivering'
                   || (project.status === 'pending' && canReview))"
              :content="canOwn ? '' : NO_PERM_TIP"
              :disabled="canOwn"
              placement="top"
            >
              <span>
                <el-button
                  :icon="EditPen"
                  :type="project.status === 'pending' ? 'warning' : 'primary'"
                  :disabled="!canOwn"
                  @click="goEdit"
                >
                  {{ project.status === 'pending' ? '审核订单' : '编辑' }}
                </el-button>
              </span>
            </el-tooltip>
            <!-- ADR-026：待审核订单撤销（本人下单 / admin 可见）——终止原单 + 明细回填购物车 -->
            <el-button
              v-if="canWithdraw"
              type="danger"
              plain
              @click="withdrawVisible = true"
            >
              撤销
            </el-button>
            <!-- ADR-028：viewer 不渲染任何「编辑」入口（含禁用态），故该只读提示按钮同样对 viewer 隐藏。
                 FIX-20261022 / BUG-21：delivering 已可编辑，禁用态只保留「已完成」 -->
            <el-tooltip v-if="!isViewer && project.status === 'delivered'" content="已完成项目不可编辑" placement="top">
              <el-button :icon="EditPen" disabled>编辑</el-button>
            </el-tooltip>
            <!-- ADR-027（2026-10-21）：重新提交——已终止（驳回/终止）项目由下单账号（或商务/管理员）
                 回填购物车（幂等）后跳 /cart 改单重提，旧单保留终止历史（驳回原因可查） -->
            <el-button
              v-if="project.status === 'terminated' && (canWrite || isViewer)"
              type="warning"
              plain
              :loading="refilling"
              :disabled="refilling"
              @click="handleResubmit"
            >
              重新提交
            </el-button>
            <!-- 2026-10-19 排查修复：viewer 不能接手（claim 需 editor），换用不误导的文案
                 FIX-20261021：改为独立 v-if——原 v-else 挂到了「重新提交」的 v-if 上，
                 待审核项目会同时渲染「审核订单」与禁用态「审核订单」两个按钮 -->
            <el-tooltip v-if="project.status === 'pending' && !canReview && !isViewer" :content="'待审核项目仅商务负责人（或管理员）可进入，请先接手'" placement="top">
              <el-button :icon="EditPen" type="warning" disabled>审核订单</el-button>
            </el-tooltip>
          </span>
        </div>
      </div>

      <!-- ADR-028 Decision 5（2026-10-21）：撤销留痕可见性——撤销导致的终止单（terminated && cartRefilled）
           在头部下方给一行浅色提示（复用全局 .info-bar 浅蓝底信息条，不新造配色/不加新布局块）；
           撤销原因由合同 remark（「撤销：{原因}」）在下方销售记录卡片内展示，
           「重新提交」入口复用头部既有按钮 -->
      <div v-if="project && project.status === 'terminated' && project.cartRefilled" class="info-bar revoked-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>该订单已撤销，历史记录已保留；撤销原因见下方销售记录备注</span>
      </div>

      <el-empty v-if="!project" description="未找到该销售项目" :image-size="80" />

      <template v-else>
        <!-- ① 基本信息（只读） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Folder /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">更新于 {{ project.updatedAt }}</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="il">项目名称</span>
              <span class="iv">{{ project.name }}</span>
            </div>
            <div class="info-item">
              <span class="il">项目编号</span>
              <span class="iv">{{ project.code }}</span>
            </div>
            <div class="info-item">
              <span class="il">客户名称</span>
              <span class="iv">{{ customerText }}</span>
            </div>
            <div class="info-item">
              <span class="il">生态人员</span>
              <span class="iv">{{ userName(project.rep) || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">商务负责人</span>
              <span class="iv">{{ userName(project.businessOwner) || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">预计销售</span>
              <span class="iv">{{ project.expectedAmount ? formatMoney(project.expectedAmount) : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">销售金额</span>
              <span class="iv">{{ project.contractAmount ? formatMoney(project.contractAmount) : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">预计签约</span>
              <span class="iv">{{ project.expectedSignDate || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">最近跟进</span>
              <span class="iv">{{ project.lastFollowDate || '-' }}</span>
            </div>
            <div class="info-item span-3" v-if="project.remark">
              <span class="il">备注</span>
              <span class="iv">{{ project.remark }}</span>
            </div>
          </div>
        </div>

        <!-- ② 销售记录清单（ADR-007：数量联动最小单位；项目状态由销售记录状态自动派生） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Tickets /></el-icon></span>
            <div>
              <div class="bh-title">销售记录清单</div>
            </div>
          </div>

          <template v-if="contracts.length">
            <div v-for="c in contracts" :key="c.id" class="contract-card" :class="`contract-${c.status}`">
              <div class="contract-head">
                <div class="ch-left">
                  <!-- 2026-10-21：卡头改为「甲方：客户名称；乙方：签约主体全称」文本式——
                       甲方 = 生态人员下单时输入的客户名称；乙方 = 该项目签约主体全称（不再用简称徽标）。
                       状态标签保留在右侧。 -->
                  <span class="contract-party">
                    <span class="cp-label">甲方：</span>{{ c.customer || '-' }}
                  </span>
                  <span v-if="c.subject" class="contract-party">
                    <span class="cp-label">乙方：</span>{{ c.subject }}
                  </span>
                  <el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light">
                    {{ tagInfo(PROJECT_STATUS, c.status).label }}
                  </el-tag>
                </div>
                <div class="op-actions">
                  <!-- ADR-012：待审核销售记录无 交付/终止 快捷（后端对 pending 一律 400），唯一出口是编辑页审核面板 -->
                  <template v-if="c.status === 'pending'">
                    <!-- ADR-012 §5.1：仅接手人（或 admin）可见；未接手/他人接手 → 提示等待 -->
                    <el-button
                      v-if="canReview"
                      type="warning"
                      size="small"
                      @click="goEdit"
                    >
                      审核订单
                    </el-button>
                    <span v-else class="muted contract-ended">待审核（等商务确认）</span>
                  </template>
                  <template v-else-if="c.status === 'active'">
                    <!-- 交付仅商务/管理员（后端同样拦截 viewer） -->
                    <el-tooltip :content="!canWrite ? '交付需商务人员/管理员操作' : ''" :disabled="canWrite" placement="top">
                      <span>
                        <el-button
                          type="primary"
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canWrite || actingContractId === c.id"
                          @click="deliverContract(c)"
                        >
                          交付
                        </el-button>
                      </span>
                    </el-tooltip>
                    <!-- 终止：自己项目可操作（含生态人员，后端校验归属） -->
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canOwn" placement="top">
                      <span>
                        <el-button
                          type="danger"
                          plain
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canOwn || actingContractId === c.id"
                          @click="terminateContract(c)"
                        >
                          终止
                        </el-button>
                      </span>
                    </el-tooltip>
                    <!-- ADR-019（PRICING-20261020）：录入签订时间（商务/管理员）——录入即 active→delivering；
                         已录过签订时间的合同已转 delivering，active 分支下该按钮恒为「未录入」态 -->
                    <el-tooltip :content="!canWrite ? '录入签订时间需商务人员/管理员操作' : ''" :disabled="canWrite" placement="top">
                      <span>
                        <el-button
                          type="primary"
                          plain
                          size="small"
                          :disabled="!canWrite"
                          @click="openDateDialog(c, 'signedDate')"
                        >
                          录入签订时间
                        </el-button>
                      </span>
                    </el-tooltip>
                  </template>
                  <!-- ADR-019（PRICING-20261020）：交付中（已录签订时间未交付）——
                       交付/终止沿用 active 分支既有调用；「预计交付时间」仅 admin 可录/改/清空 -->
                  <template v-else-if="c.status === 'delivering'">
                    <el-tooltip :content="!canWrite ? '交付需商务人员/管理员操作' : ''" :disabled="canWrite" placement="top">
                      <span>
                        <el-button
                          type="primary"
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canWrite || actingContractId === c.id"
                          @click="deliverContract(c)"
                        >
                          交付
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip :content="NO_PERM_TIP" :disabled="canOwn" placement="top">
                      <span>
                        <el-button
                          type="danger"
                          plain
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canOwn || actingContractId === c.id"
                          @click="terminateContract(c)"
                        >
                          终止
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip :content="!isAdmin ? '预计交付时间仅管理员可录入' : ''" :disabled="isAdmin" placement="top">
                      <span>
                        <el-button
                          size="small"
                          :disabled="!isAdmin"
                          @click="openDateDialog(c, 'scheduledDeliveryDate')"
                        >
                          预计交付时间
                        </el-button>
                      </span>
                    </el-tooltip>
                  </template>
                  <el-tooltip v-else-if="c.status === 'delivered'" :content="NO_PERM_TIP" :disabled="canOwn" placement="top">
                    <span>
                      <el-button
                        type="danger"
                        plain
                        size="small"
                        :loading="actingContractId === c.id"
                        :disabled="!canOwn"
                        @click="terminateContract(c)"
                      >
                        终止
                      </el-button>
                    </span>
                  </el-tooltip>
                  <span v-else class="muted contract-ended">已终止</span>
                </div>
              </div>

              <div class="contract-info">
                <span class="ci-item">
                  <span class="muted">销售金额</span>
                  <b class="ci-amount">{{ formatMoney(c.contractAmount) }}</b>
                </span>
                <span class="ci-item" v-if="c.items.some((it) => it.lockedDate)">
                  <!-- 2026-10-20（ADR-019）：原「签约/锁定」改名「下单时间」（锁定即下单时刻；签订时间另列） -->
                  <span class="muted">下单时间</span>
                  <span>{{ formatDate(c.items.find((it) => it.lockedDate)?.lockedDate) }}</span>
                </span>
                <!-- ADR-019（PRICING-20261020）：合同签订时间 / 预计交付时间（存量合同为 null，显示占位文案） -->
                <span class="ci-item">
                  <span class="muted">合同签订</span>
                  <span :class="{ muted: !c.signedDate }">{{ c.signedDate || '未签订' }}</span>
                </span>
                <span class="ci-item">
                  <span class="muted">预计交付</span>
                  <span :class="{ muted: !c.scheduledDeliveryDate }">{{ c.scheduledDeliveryDate || '未录入' }}</span>
                </span>
                <span class="ci-item" v-if="c.items.some((it) => it.shippedDate)">
                  <span class="muted">交付</span>
                  <span>{{ formatDate(c.items.find((it) => it.shippedDate)?.shippedDate) }}</span>
                </span>
                <span class="ci-item" v-if="c.remark">
                  <span class="muted">备注</span>
                  <span>{{ c.remark }}</span>
                </span>
              </div>

              <el-table v-if="c.items.length" :data="c.items" border size="small" class="contract-items">
                <!-- TASK-FE-030：行高固定 36px 后产品列单行显示，超长名称（含编号）用 tooltip 兜底不丢信息 -->
                <el-table-column label="产品" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">
                    <a class="link" @click="goAssetDetail(row.assetId)">{{ itemAssetName(row.assetId) }}</a>
                  </template>
                </el-table-column>
                <!-- ADR-011：明细列（遥感明细行显示明细名，其余 '-'） -->
                <el-table-column label="明细" width="200" align="left" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span :class="{ muted: itemRsName(row.itemId) === '-' }">{{ itemRsName(row.itemId) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="数量" width="120" align="right">
                  <template #default="{ row }">{{ itemQtyText(row.assetId, row.qty) }} {{ row.unit }}</template>
                </el-table-column>
                <el-table-column label="单价" width="170" align="right">
                  <!-- ADR-008：包量定价行单价为派生参考展示（带「约」），金额以销售金额为准 -->
                  <template #default="{ row }">
                    <span v-if="isAmountItem(row.assetId)" class="muted">{{ derivedUnitPrice(row.amount, row.qty, row.unit) }}</span>
                    <span v-else>{{ formatMoney(row.price) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="金额" width="140" align="right">
                  <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
                </el-table-column>
                <!-- ADR-020（PRICING-20261020）：服务期限（start ~ end，空显 -；遥感明细行按期数售卖，展示为空即可） -->
                <el-table-column label="服务期限" width="200" align="center">
                  <template #default="{ row }">
                    <span :class="{ muted: !(row.serviceStart || row.serviceEnd) }">
                      {{ row.serviceStart || row.serviceEnd ? `${row.serviceStart || '-'} ~ ${row.serviceEnd || '-'}` : '-' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="交付要求" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.deliveryReq || '-' }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>

          <!-- 存量无销售记录项目：保留原销售明细展示（明细 contractId 为 null） -->
          <template v-else>
            <el-table v-if="project.items.length" :data="project.items" border>
              <el-table-column label="关联产品" min-width="240">
                <template #default="{ row }">
                  <a class="link" @click="goAssetDetail(row.assetId)">{{ itemAssetName(row.assetId) }}</a>
                </template>
              </el-table-column>
              <!-- ADR-011：明细列（遥感明细行显示明细名，其余 '-'） -->
              <el-table-column label="明细" width="200" align="left" show-overflow-tooltip>
                <template #default="{ row }">
                  <span :class="{ muted: itemRsName(row.itemId) === '-' }">{{ itemRsName(row.itemId) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="数量" width="120" align="right">
                <template #default="{ row }">{{ itemQtyText(row.assetId, row.qty) }} {{ row.unit }}</template>
              </el-table-column>
              <el-table-column label="单价" width="170" align="right">
                <!-- ADR-008：包量定价行单价为派生参考展示（带「约」） -->
                <template #default="{ row }">
                  <span v-if="isAmountItem(row.assetId)" class="muted">{{ derivedUnitPrice(row.amount, row.qty, row.unit) }}</span>
                  <span v-else>{{ formatMoney(row.price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="金额" width="150" align="right">
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column label="交付要求" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.deliveryReq || '-' }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无销售明细" :image-size="80" />
          </template>
        </div>
      </template>

      <!-- ADR-019（PRICING-20261020）：合同时间节点录入（签订时间 / 预计交付时间） -->
      <el-dialog
        v-model="dateDialog.visible"
        :title="dateDialog.field === 'signedDate' ? '录入签订时间' : '预计交付时间'"
        class="dlg-form"
        :close-on-click-modal="false"
      >
        <el-form label-position="top">
          <el-form-item :label="dateDialog.field === 'signedDate' ? '合同签订时间' : '预计交付时间'">
            <el-date-picker
              v-model="dateDialog.value"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              style="width: 100%;"
            />
          </el-form-item>
          <p class="muted" style="font-size: 12px; margin: 0;">
            <template v-if="dateDialog.field === 'signedDate'">
              录入后销售记录转为「交付中」，可执行交付；签订时间录入后不可清空。
            </template>
            <template v-else>
              仅管理员可录入/修改；已有值时可不选日期直接保存以清空。
            </template>
          </p>
        </el-form>
        <template #footer>
          <el-button @click="dateDialog.visible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="dateSaving"
            :plain="dateDialog.field === 'scheduledDeliveryDate' && !dateDialog.value"
            @click="submitDateDialog"
          >
            {{ dateDialog.field === 'scheduledDeliveryDate' && !dateDialog.value ? '清空预计交付时间' : '保存' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- ADR-012 §5.1 纯移交制：转交对话框（负责人/admin，下拉选新负责人） -->
      <TransferDialog v-model="transferVisible" :project="transferTarget" />

      <!-- ADR-026：撤销待审核订单（统一对话框；成功后刷新镜像并跳 /cart 改单重提） -->
      <WithdrawProjectDialog v-model="withdrawVisible" :project="project" @done="onWithdrawn" />
    </div>
  </div>
</template>

<style scoped>
/* 内容区最大 1080px，居中 */
.detail-wrap {
  max-width: 1080px;
  margin: 0 auto;
  width: 100%;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
/* ADR-028：撤销提示条——只补间距，配色/边框/字号全部沿用全局 .info-bar（浅底 #f0f6ff / 边框 #e0ecff） */
.revoked-bar {
  margin-bottom: 16px;
}
.link {
  color: var(--primary-color);
  cursor: pointer;
}
.link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}

/* 合同卡片：状态左侧色条区分（复用既有 token 色） */
.contract-card {
  border: 1px solid var(--border-color, #e5e9f0);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.contract-card:last-child {
  margin-bottom: 0;
}
.contract-card.contract-active {
  border-left-color: var(--primary-color);
}
/* ADR-019（PRICING-20261020）：交付中（已录签订时间未交付）——与状态 tag 同色板（橙） */
.contract-card.contract-delivering {
  border-left-color: var(--warning-color, #A86514);
}
.contract-card.contract-delivered {
  border-left-color: var(--success-color, #0c7b51);
}
.contract-card.contract-terminated {
  border-left-color: var(--danger-color);
  opacity: 0.85;
}
.contract-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.ch-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
/* 2026-10-21：卡头「甲方：客户 / 乙方：主体全称」文本式（甲方值加粗，标签次要色） */
.contract-party {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cp-label {
  color: var(--text-secondary);
}
/* 甲乙方之间的「；」分隔（用伪元素，不额外增加 DOM 文案） */
.contract-party + .contract-party::before {
  content: '；';
  color: var(--text-secondary);
  margin-right: 2px;
}
.op-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.op-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.contract-ended {
  font-size: 13px;
}
.contract-info {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--text-body);
}
.ci-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ci-amount {
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
}
.contract-items {
  margin-top: 4px;
}
/* TASK-FE-030：明细表「表头行 / 数据行」行高统一 36px（多张卡片一致）。
   只作用于本页 .contract-items，不改全局 .el-table；外框/分隔线/hover 沿用全局规范。
   加高来源：size="small" 的 .el-table__cell padding:4px 0 与 .cell line-height:23px 叠加，
   导致含换行/不同内容的数据行高于表头 —— 这里统一 padding:0 + 固定行高。 */
.contract-items :deep(.el-table__header th.el-table__cell),
.contract-items :deep(.el-table__body td.el-table__cell) {
  height: 36px;
  padding: 0;
}
/* 单元格文字：字号维持现有 13px（th 继承全局 13px），行高固定、单行省略 —— 不受继承行高差异影响，
   22px 行高居中于 36px 单元格内，不裁切文字 */
.contract-items :deep(.el-table__cell .cell) {
  line-height: 22px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
