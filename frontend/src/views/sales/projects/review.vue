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
import { ArrowLeft, CircleCheck, Money, UserFilled } from '@element-plus/icons-vue'
import {
  entityShort,
  formatMoney,
  isAmountMode,
  rsItemName,
} from '@/types'
import {
  claimProject,
  db,
  getAsset,
  refresh,
  reviewProject,
  updateProject,
  allUserOptions,
  showError,
  type UserOption,
} from '@/api'
import { canWrite, currentUser, isAdmin } from '@/auth'
import TransferDialog from '@/components/TransferDialog.vue'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const proj = computed(() => db.projects.find((x) => x.id === projectId.value))
const contracts = computed(() =>
  proj.value ? db.contracts.filter((c) => c.projectId === proj.value!.id) : [],
)
const isPending = computed(() => proj.value?.status === 'pending')

function editItemName(it: { assetId?: number | null }): string {
  if (!it.assetId) return '未关联产品'
  return getAsset(it.assetId)?.name ?? '产品已删除'
}

/** DISCOUNT-20261021（ADR-023，2026-10-21）：折扣率小数 → 展示文案（0.9→"9折"、0.85→"8.5折"，一位小数去尾零） */
function discountRateText(rate: number): string {
  const t = (rate * 10).toFixed(1)
  return (t.endsWith('.0') ? t.slice(0, -2) : t) + '折'
}

// ==================== 订单审核（原编辑页面板迁移） ====================
interface ReviewLine {
  id: number // project_items.id（审核接口 items[].itemId）
  contractId: number
  customer: string
  name: string
  qty: number
  unit: string
  mode: 'unit' | 'amount' | 'rs' // rs=遥感明细行（2026-10-20：金额可改，仅本单生效不回写明细单价）
  // 原价快照（ADR-018 §2，PRICING-20261020）：下单时挂牌价快照，**只读不可改**；
  // 存量订单 orig 为空 → 按当前 price/amount 兜底展示（ADR-018 Consequences）
  origPrice: number
  origAmount: number
  price: number | null // unit 模式可编辑（实际单价）
  amount: number | null // amount 模式可编辑（实际合同金额，整数元）
  // 折扣率快照（DISCOUNT-20261021 / ADR-023，2026-10-21）：下单时生态人员填写的折扣率（0-1 小数），
  // 只读展示（快照不可改，review 接口不改该字段）；null 显示 -
  discountRate: number | null
  // 服务期限（ADR-020，PRICING-20261020）：confirm 可改（start ≤ end 后端 400 兜底）
  serviceStart: string
  serviceEnd: string
  origServiceStart: string // 预填原值（变更检测用）
  origServiceEnd: string
}
const reviewLines = ref<ReviewLine[]>([])
const reviewBusy = ref(false)

/** 展开审核行（watch 首次有合同时执行；db 刷新后不重建，避免覆盖编辑中值） */
watch(contracts, (cs) => {
  if (!isPending.value || reviewLines.value.length) return
  reviewLines.value = cs.flatMap((c) =>
    c.items.map((it) => {
      const a = it.assetId ? getAsset(it.assetId) : undefined
      const rs = it.itemId ? db.rsItems.find((x) => x.id === it.itemId) : undefined
      const mode: ReviewLine['mode'] = it.itemId ? 'rs' : a && isAmountMode(a) ? 'amount' : 'unit'
      return {
        id: it.id, contractId: c.id, customer: c.customer,
        name: editItemName(it) + (rs ? ` · ${rsItemName(rs)}` : ''),
        qty: it.qty, unit: a?.unit || '',
        mode,
        // ADR-018 §2（PRICING-20261020）：原价取下单时快照 origPrice/origAmount（只读）；
        // 存量订单快照为空 → 按当前 price/amount 兜底（展示口径与 ADR 一致）
        origPrice: it.origPrice ?? it.price, origAmount: it.origAmount ?? it.amount,
        price: it.price ?? null,
        amount: it.amount ?? null,
        // DISCOUNT-20261021（ADR-023，2026-10-21）：折扣率快照（只读；存量订单为空 → 显示 -）
        discountRate: it.discountRate ?? null,
        // ADR-020（PRICING-20261020）：服务期限预填（可改）
        serviceStart: it.serviceStart ?? '',
        serviceEnd: it.serviceEnd ?? '',
        origServiceStart: it.serviceStart ?? '',
        origServiceEnd: it.serviceEnd ?? '',
      }
    }),
  )
}, { immediate: true })

/** 行当前金额（unit=单价×数量 派生；amount/rs=行金额） */
function lineAmount(l: ReviewLine): number {
  if (l.mode === 'unit') return Math.round(((l.price ?? 0) * l.qty) * 100) / 100
  return l.amount ?? 0
}
/** 合同合计（实时） */
function contractTotal(contractId: number): number {
  return Math.round(reviewLines.value
    .filter((l) => l.contractId === contractId)
    .reduce((s, l) => s + lineAmount(l), 0) * 100) / 100
}
/** 项目总金额（实时 = Σ 行） */
const projectTotal = computed(() =>
  Math.round(reviewLines.value.reduce((s, l) => s + lineAmount(l), 0) * 100) / 100,
)
/** 是否有改价行（确认弹窗文案用；2026-10-20：rs 行金额也可改，一并计入） */
const hasPriceChange = computed(() =>
  reviewLines.value.some((l) =>
    l.mode === 'unit' ? (l.price ?? l.origPrice) !== l.origPrice : (l.amount ?? l.origAmount) !== l.origAmount,
  ),
)

// ==================== 接手机制（ADR-012 §5.1：改价/确认/驳回仅限接手账号，admin 可越过） ====================
const ownerOptions = ref<UserOption[]>([])
// 2026-10-20：显示映射用全量名册（含生态，负责人提示/rep 展示同口径）
allUserOptions().then((u) => { ownerOptions.value = u }).catch(() => {})

/** 当前用户是否可操作该订单：接手账号本人，或 admin 兜底 */
const canReview = computed(() => {
  if (!canWrite.value || !proj.value) return false
  const owner = proj.value.businessOwner
  return isAdmin.value || owner === currentUser.value?.username
})
/** 转交对话框 */
const transferVisible = ref(false)
const transferTarget = ref<{ id: number; name: string; businessOwner?: string } | null>(null)
function openTransferPanel() {
  const p = proj.value
  if (!p) return
  transferTarget.value = p
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

/** 确认下单：校验 → 二次确认 → 提交（仅传改过的行；ADR-018 §4：改价/期限只写本单，不回写平台挂牌价） */
async function handleConfirm() {
  for (const l of reviewLines.value) {
    if (l.mode === 'unit' && !(l.price && l.price > 0)) {
      ElMessage.warning(`「${l.name}」请填写实际单价`)
      return
    }
    // amount/rs 行统一校验（2026-10-20：遥感明细行金额放开可改，仅本单生效）
    if (l.mode !== 'unit' && (!l.amount || l.amount <= 0 || !Number.isInteger(l.amount))) {
      ElMessage.warning(`「${l.name}」销售金额须为正整数（元）`)
      return
    }
    if (lineAmount(l) <= 0) {
      ElMessage.warning(`「${l.name}」金额须大于 0`)
      return
    }
  }
  try {
    await ElMessageBox.confirm(
      `确认项目「${proj.value?.name}」的订单？`
      + (hasPriceChange.value
        ? '含单价/销售金额/服务期限修改，确认后销售记录生效（终审价格仅作用于本订单，不回写平台产品单价）。'
        : '确认后销售记录正式生效（数量锁定保持不变）。'),
      '确认下单',
      { type: 'warning', confirmButtonText: '确认下单', cancelButtonText: '再检查一下' },
    )
  } catch {
    return
  }
  reviewBusy.value = true
  try {
    // 2026-10-20：rs 行（遥感明细）改价一并提交——后端只改本行金额，不回写明细单价；
    // ADR-020（PRICING-20261020）：服务期限变更的行一并提交 serviceStart/serviceEnd（不传 = 保持原值）
    const items: { itemId: number; price?: number; amount?: number; serviceStart?: string | null; serviceEnd?: string | null }[] = reviewLines.value
      .filter((l) =>
        (l.mode === 'unit' ? l.price !== l.origPrice : l.amount !== l.origAmount)
        || l.serviceStart !== l.origServiceStart
        || l.serviceEnd !== l.origServiceEnd,
      )
      .map((l) => {
        const base: { itemId: number; price?: number; amount?: number; serviceStart?: string | null; serviceEnd?: string | null } = { itemId: l.id }
        if (l.mode === 'unit') base.price = l.price ?? undefined
        else base.amount = l.amount ?? undefined
        base.serviceStart = l.serviceStart || null
        base.serviceEnd = l.serviceEnd || null
        return base
      })
    await reviewProject(projectId.value, { action: 'confirm', items })
    // ADR-018 §4（PRICING-20261020）：终审改价只写本单，不再回写平台挂牌价
    ElMessage.success('订单已确认：项目转为进行中' + (items.length ? '，改价/期限仅作用于本订单' : ''))
    router.push(`/sales/projects/${projectId.value}/detail`)
  } catch (e) {
    showError(e, '确认下单失败')
  } finally {
    reviewBusy.value = false
  }
}

/** 驳回订单：原因必填（留痕，生态人员可见）→ 释放锁定、项目终止 */
async function handleReject() {
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt(
      '请填写驳回原因（将记录在项目上，生态人员可见；数量锁定自动释放）',
      '驳回订单',
      { inputPattern: /\S+/, inputErrorMessage: '驳回原因不能为空', confirmButtonText: '确认驳回', cancelButtonText: '取消' },
    )
    reason = value
  } catch {
    return
  }
  reviewBusy.value = true
  try {
    await reviewProject(projectId.value, { action: 'reject', reason })
    ElMessage.success('订单已驳回：数量锁定已释放，项目已终止')
    router.push(`/sales/projects/${projectId.value}/detail`)
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
        <div>
          <a class="back-link" @click="goDetail"><el-icon><ArrowLeft /></el-icon>返回项目详情</a>
          <h1>订单审核 <span class="rh-name">{{ proj?.name }}</span></h1>
          <div class="desc">
            <span class="mono">{{ proj?.code }}</span>
            · 待审核（数量已锁定）· 修改实际单价/销售金额/服务期限后「确认下单」生效（终审价格仅作用于本订单，不回写平台产品单价）；数量不可修改（需改数量请驳回重下）
          </div>
        </div>
        <div class="head-actions" v-if="!canReview">
          <el-button v-if="!proj?.businessOwner" type="primary" :icon="UserFilled" :loading="reviewBusy" @click="handleClaim">
            接手此单
          </el-button>
        </div>
      </div>

      <!-- 无审核权限提示（有主单 + 非负责人商务/admin 外） -->
      <el-card v-if="canReview === false && proj?.businessOwner" shadow="never">
        <div class="no-access">
          <p>该订单由商务负责人 <b>{{ ownerLabel(proj?.businessOwner) }}</b> 负责审核，仅其本人（或管理员）可操作。</p>
          <p class="muted">如负责人无法处理，请联系管理员介入，或由负责人在编辑页「转交」后重新审核。</p>
        </div>
      </el-card>

      <template v-else-if="canReview">
        <!-- ① 订单审核 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Money /></el-icon></span>
            <div>
              <div class="bh-title">订单审核<span class="muted" style="font-weight: 400;">（待审核 → 确认生效）</span></div>
              <div class="bh-sub">
                修改实际单价 / 销售金额 / 服务期限后「确认下单」（终审价格仅作用于本订单，不回写平台产品单价）；
                数量不可修改（需改数量请驳回重下）；遥感明细行可改销售金额（仅本单生效，不回写产品「可售明细」单价）。
              </div>
            </div>
          </div>
          <div class="rv-contracts">
            <div v-for="c in contracts" :key="c.id" class="rv-ct">
              <div class="rv-ct-head">
                <span class="rv-ct-customer">{{ c.customer || '-' }}</span>
                <el-tag v-if="c.subject" size="small" effect="plain">{{ entityShort(c.subject) }}</el-tag>
                <span class="rv-ct-total">销售金额合计（实时）：{{ formatMoney(contractTotal(c.id)) }}</span>
              </div>
              <div v-for="l in reviewLines.filter((x) => x.contractId === c.id)" :key="l.id" class="rv-line">
                <!-- 第 1 层：产品名 + 数量 + 折扣 + 原价 + 可编辑价 + 金额（固定列网格，单行不换行，仅产品名可省略） -->
                <div class="rv-line-main-row">
                  <div class="rv-c-name">
                    <el-tooltip :content="l.name" placement="top">
                      <span class="rv-line-name">{{ l.name }}</span>
                    </el-tooltip>
                  </div>
                  <span class="rv-c-qty muted">× {{ l.qty }}{{ l.unit }}</span>
                  <!-- DISCOUNT-20261021（ADR-023，2026-10-21）：折扣率只读展示（下单时生态人员填写的快照，不可改；
                       null 显示 -）；与已有原单价/原金额 + 可编辑终审价并列，商务可见「原价、折扣率、折扣价」三要素 -->
                  <div class="rv-c-disc">
                    <span class="rv-lbl rv-discount-lbl">
                      <el-tooltip content="下单时生态人员填写的折扣率（快照，不可改）" placement="top">
                        <span>折扣</span>
                      </el-tooltip>
                    </span>
                    <span class="rv-orig">{{ l.discountRate != null ? discountRateText(l.discountRate) : '-' }}</span>
                  </div>
                  <!-- ADR-018 §2（PRICING-20261020）：原价列只读——展示下单时挂牌价快照；
                       存量订单 orig 为空时数据层已按当前 price/amount 兜底（见 reviewLines 展开逻辑），
                       故此处恒展示，无需再判空 -->
                  <template v-if="l.mode === 'unit'">
                    <div class="rv-c-orig">
                      <span class="rv-lbl">原单价（元）</span>
                      <span class="rv-orig muted">{{ formatMoney(l.origPrice) }}</span>
                    </div>
                    <div class="rv-c-edit">
                      <span class="rv-lbl">实际单价（元）</span>
                      <el-input-number v-model="l.price" :min="0" :precision="2" :controls="false" class="rv-input" />
                    </div>
                    <span class="rv-c-amt">金额 {{ formatMoney(lineAmount(l)) }}</span>
                  </template>
                  <template v-else-if="l.mode === 'amount'">
                    <div class="rv-c-orig">
                      <span class="rv-lbl">原金额（元）</span>
                      <span class="rv-orig muted">{{ formatMoney(l.origAmount) }}</span>
                    </div>
                    <div class="rv-c-edit">
                      <span class="rv-lbl">销售金额（整数元）</span>
                      <el-input-number v-model="l.amount" :min="0" :precision="0" :step="1000" :controls="false" class="rv-input" />
                    </div>
                    <span v-if="l.qty > 0" class="rv-c-amt rv-derived muted">参考单价 ≈ {{ (lineAmount(l) / l.qty).toFixed(2) }} 元/{{ l.unit || '个' }}</span>
                  </template>
                  <template v-else>
                    <!-- 2026-10-20：遥感明细行金额放开可改（仅本单生效，不回写产品明细单价） -->
                    <div class="rv-c-orig">
                      <span class="rv-lbl">原金额（元）</span>
                      <span class="rv-orig muted">{{ formatMoney(l.origAmount) }}</span>
                    </div>
                    <div class="rv-c-edit">
                      <span class="rv-lbl">销售金额（整数元）</span>
                      <el-input-number v-model="l.amount" :min="0" :precision="0" :step="1000" :controls="false" class="rv-input" />
                    </div>
                    <span v-if="l.qty > 0" class="rv-c-amt rv-derived muted">参考单价 ≈ {{ (lineAmount(l) / l.qty).toFixed(2) }} 元/{{ l.unit || '份' }}（明细单价不回写）</span>
                  </template>
                </div>
                <!-- 第 2 层：服务期限（同一行不换行）——ADR-020（PRICING-20261020）：普通行可改；遥感明细行按期数售卖不展示 -->
                <div v-if="l.mode !== 'rs'" class="rv-line-svc-row">
                  <span class="rv-lbl rv-svc-lbl">服务期限</span>
                  <el-date-picker v-model="l.serviceStart" type="date" value-format="YYYY-MM-DD" placeholder="开始" class="rv-date" />
                  <span class="rv-svc-sep muted">~</span>
                  <el-date-picker v-model="l.serviceEnd" type="date" value-format="YYYY-MM-DD" placeholder="结束" class="rv-date" />
                </div>
              </div>
            </div>
          </div>
          <div class="rv-foot">
            <span>项目总金额（实时）：</span>
            <b>{{ formatMoney(projectTotal) }}</b>
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

        <!-- 底部操作区 -->
        <div class="bottom-actions">
          <el-button @click="goDetail">返回详情</el-button>
          <el-button type="danger" plain :loading="reviewBusy" @click="handleReject">驳回</el-button>
          <el-button plain :loading="reviewBusy" @click="openTransferPanel">
            {{ proj?.businessOwner ? '转交' : '接手' }}
          </el-button>
          <el-button type="primary" :icon="CircleCheck" :loading="reviewBusy" @click="handleConfirm">
            确认下单
          </el-button>
        </div>
      </template>
    </div>

    <TransferDialog v-model="transferVisible" :project="transferTarget" />
  </div>
</template>

<style scoped>
.rh-name {
  font-size: 18px;
  color: var(--text-secondary);
  font-weight: 500;
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

/* E. 页头说明：限制行长，避免超长单行（文案不变） */
.page-head .desc {
  max-width: 920px;
  line-height: 1.7;
}

/* ==================== 订单审核行（自编辑页迁移，scoped 样式随迁） ====================
   TASK-FE-027（2026-10-21）：纯布局优化——卡片头单行、明细行两层结构、金额右对齐、总金额条对齐 */
/* C. 卡片与卡片容器：间距 14px，内边距 14px 16px，细边框 + 8px 圆角 */
.rv-contracts {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.rv-ct {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 14px 16px;
}
/* A. 卡片头：单行不换行（客户名 → 主体标签 → 合计金额右对齐），22px 基线 + 底部 12px */
.rv-ct-head {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  line-height: 22px;
  margin-bottom: 12px;
}
.rv-ct-customer {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
/* 主体标签紧随客户名，不参与压缩 */
.rv-ct-head .el-tag {
  flex-shrink: 0;
}
.rv-ct-total {
  margin-left: auto;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-primary, var(--primary-color));
  font-variant-numeric: tabular-nums;
}
/* B. 明细行：行与行之间单条 1px 细线（去掉 dashed，避免双线） */
.rv-line {
  min-width: 0;
}
.rv-line + .rv-line {
  border-top: 1px solid var(--divider-color);
}
/* B-1 层：产品名 + 数量 + 折扣 + 原价 + 可编辑价 + 金额
   TASK-FE-028（2026-10-21）：flex → 固定列 CSS Grid。「标签+值」成对包成分组，
   每个标签/输入框落在固定列上，三种明细行（unit/amount/rs）的输入框左边缘吸附同一列，
   标签不再被 overflow 裁切（只剩产品名省略）。 */
.rv-line-main-row {
  display: grid;
  /* 产品名 | 数量 | 折扣 | 原价 | 可编辑价 | 金额 */
  grid-template-columns: minmax(150px, 1fr) 78px 92px 176px 280px minmax(132px, auto);
  align-items: center;
  column-gap: 10px;
  padding: 9px 0;
  min-width: 0;
  /* 极端窄屏裁剪而不是换行（单行底线） */
  overflow: hidden;
}
/* 第 1 列：产品名（唯一允许省略的列） */
.rv-c-name {
  min-width: 0;
}
.rv-line-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-primary);
}
/* 第 2 列：× 数量单位 */
.rv-c-qty {
  white-space: nowrap;
  font-size: 12px;
}
/* 行内标签统一 12px 次要色 */
.rv-lbl {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-secondary);
}
/* DISCOUNT-20261021（ADR-023，2026-10-21）：折扣只读列（窄列，标签带 tooltip 说明快照口径） */
.rv-discount-lbl {
  cursor: help;
}
/* TASK-FE-028（2026-10-21）：成对分组容器——标签 + 值/输入框同组，组内 label 定宽 → 列内对齐 */
.rv-c-disc,   /* 第 3 列：折扣（标签 + 折扣率） */
.rv-c-orig,   /* 第 4 列：原单价/原金额（标签 + 值，标签文案随分支原样） */
.rv-c-edit {  /* 第 5 列：实际单价/销售金额（定宽标签 + 输入框） */
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
/* 第 4 列的值不换行、数字等宽 */
.rv-c-orig .rv-orig {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
/* 可编辑列标签定宽（容纳最长的「销售金额（整数元）」，不截断）→ 三种分支的输入框左边缘完全一致 */
.rv-c-edit .rv-lbl {
  width: 112px;
  flex: 0 0 auto;
  text-align: right;
  white-space: nowrap;
}
/* 单价/金额输入框宽度统一（158px） */
.rv-input {
  width: 158px;
  flex-shrink: 0;
}
.rv-input :deep(.el-input__inner) {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
/* 第 6 列：金额 / 参考单价（末列右边缘 = 行右边缘 → 各行右对齐） */
.rv-c-amt {
  justify-self: end;
  text-align: right;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
/* ADR-018 §2（PRICING-20261020）：原价只读列（弱于可编辑列，.muted 保持灰色） */
.rv-orig {
  flex-shrink: 0;
  white-space: nowrap;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.rv-orig:not(.muted) {
  color: var(--text-primary);
}
/* 派生提示（参考单价 ≈ …）：与金额列同一右基准，字号/灰度沿用原样式 */
.rv-derived {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}
/* ADR-020（PRICING-20261020）：服务期限日期输入（TASK-FE-028：默认尺寸 + 170px）
   el-date-picker 根节点不带 scope 属性 → 用父层 :deep 命中，并压过 EP 默认 --el-date-editor-width(220px) */
.rv-line-svc-row :deep(.rv-date) {
  width: 170px;
  flex-shrink: 0;
}
.rv-line-svc-row :deep(.rv-date .el-input__inner) {
  font-size: 13px;
}
.rv-rs-tip {
  font-size: 12px;
}
/* B-2 层：服务期限（标签 + 开始 ~ 结束，同一行不换行，与左侧标签对齐；层间单条细线） */
.rv-line-svc-row {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 10px;
  padding: 10px 0 10px 2px;
  border-top: 1px solid var(--divider-color);
  min-width: 0;
}
/* 第 2 层标签略大（13px），颜色沿用 .rv-lbl 次要色 */
.rv-svc-lbl {
  font-size: 13px;
}
/* `~` 分隔符前后各留 2px */
.rv-svc-sep {
  margin: 0 2px;
}
/* D. 项目总金额条：与卡片同内边距，左标签右数值 */
.rv-foot {
  margin-top: 14px;
  padding: 10px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid var(--border-color);
  font-size: 13px;
  color: var(--text-secondary);
}
.rv-foot b {
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
/* F. 响应式底线（TASK-FE-028）：视口 ≤1360px 时列宽整体收缩——先压产品名列（省略号），
   标签定宽保持 112px（不换行、不截断），输入框 150px；第 1 层仍为单行网格，不换行 */
@media (max-width: 1360px) {
  .rv-line-main-row {
    grid-template-columns: minmax(0, 1fr) 72px 88px 170px 268px minmax(132px, auto);
    column-gap: 8px;
  }
  .rv-input {
    width: 150px;
  }
}
</style>
