<script setup lang="ts">
/**
 * 购物车结算确认对话框（ADR-020，PRICING-20261020：下单入口统一收口购物车）
 *
 * 2026-10-20 起本组件仅保留购物车结算确认模式——「登记销售」直接下单（/sales/order）
 * 入口及其非购物车分支（客户名称/预计签约/备注/合同金额输入等直接下单专用字段）已整体删除，
 * 购物车成为唯一下单链路（后端 POST /sales/order 保留并标记 deprecated，前端不再调用）。
 *
 * 表单字段：仅项目名称（默认「采购订单」可修改）；客户已在购物车行级填写（按（产品, 客户）
 * 双键分组拆合同，ADR-016），销售金额合计只读展示（行级金额已由 PUT /cart/{id} 持久化，
 * 结算 payload 不携带金额，后端按 cart_items 落库值派生）。
 * previewGroups 传入时顶部展示「将生成 1 个项目 · N 份销售记录」分组预览（含服务期限，ADR-020）。
 * 提交后由父组件调用 checkoutCart，生成「待审核」销售项目并锁定数量（不自动交付）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import {
  entityShort,
  formatMoney,
  formatYuan,
  rsItemName,
  type Asset,
} from '@/types'
import { rsItemById, type OrderFields } from '@/api'
import { currentUser } from '@/auth'

export interface OrderItem {
  asset: Asset
  qty: number
  /** 行内销售金额（整数元）：包量定价权威值 / unit 与遥感行折扣金额（ADR-018 §3）；未填不带 */
  amount?: number
  /** ADR-011：遥感数据明细行（挂 rs_items）——数量恒 1，单价 = 明细 price（后端权威重算） */
  itemId?: number
}

/** 结算预览分组（购物车场景）：按（产品, 客户）双键分组（ADR-016），每组 = 未来一份销售记录 */
export interface OrderPreviewGroup {
  customer: string
  /** 产品名（仅展示：同一客户跨多个产品会拆成多组，需产品名区分） */
  assetName?: string
  qty: number
  amount: number
  /** 服务期限（ADR-020）：组内行期限一致时展示「start ~ end」，否则不带 */
  service?: string
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    items: OrderItem[]
    loading?: boolean
    previewGroups?: OrderPreviewGroup[]
  }>(),
  { title: '购物车下单', loading: false, previewGroups: () => [] },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: { fields: OrderFields; items: { assetId: number; qty: number; amount?: number; itemId?: number }[] }): void
}>()

/** 行计价单价（ADR-011）：遥感明细行取明细 price（后端权威重算，前端仅展示/传值）；其余取产品单价 */
function priceOf(i: OrderItem): number {
  if (i.itemId != null) return rsItemById(i.itemId)?.price ?? 0
  return i.asset.salePrice || 0
}

/** 主体：全部下单产品同主体时带出展示；跨主体混装（购物车场景）显示「多主体」 */
const subject = computed(() => {
  const subjects = Array.from(new Set(props.items.map((i) => i.asset.subject).filter(Boolean)))
  if (subjects.length <= 1) return subjects[0] ?? ''
  return '__multi__'
})
const totalQty = computed(() => props.items.reduce((s, i) => s + i.qty, 0))
/** 是否含已填销售金额的行（ADR-018 §3：包量定价权威值 / 折扣金额） */
const hasAmountItem = computed(() => props.items.some((i) => i.amount != null))
/** 销售金额合计（元值）：已填金额行取行内值，未填行按 单价×数量 占位（结算以后端 cart_items 持久化值为准） */
const totalYuan = computed(() =>
  props.items.reduce((s, i) => s + (i.amount ?? priceOf(i) * i.qty), 0),
)

const form = reactive({
  projectName: '',
  rep: '',
  businessOwner: '',
})

function reset() {
  // 购物车模式：客户已行级填写，项目名称默认「采购订单」（可修改）
  form.projectName = '采购订单'
  // 2026-10-19 UI 优化：rep 静默取当前登录账号（保证「自己下单」的 rep 归属口径，仅供展示与可见性兜底）
  // 2026-10-20（问题10）：rep 统一存 username（原存姓名，与建单页口径不一致导致账号/姓名混存）
  form.rep = currentUser.value?.username ?? ''
  // 商务负责人：下单入口不再指定（纯移交制，接手时绑定），恒空提交
  form.businessOwner = ''
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) reset()
  },
)

/** 项目名称是否被用户手动改过（默认「采购订单」，可修改） */
function validate(): boolean {
  if (!form.projectName.trim()) {
    ElMessage.warning('请填写项目名称')
    return false
  }
  // 购物车模式客户已在行级填写（父组件已拦截空客户行），对话框不再校验
  return true
}

function onSubmit() {
  if (!validate()) return
  const fields: OrderFields = {
    projectName: form.projectName.trim(),
    rep: form.rep,
    businessOwner: form.businessOwner,
    deliveryReq: '',
  }
  // 购物车结算（后端 CheckoutInput 已确认）：customer 可选且不参与分组（按行级客户分组）、
  // contractAmount 不被消费（合同金额按分组小计派生）→ payload 均不带；
  // 行级销售金额/服务期限已持久化在 cart_items，结算不再携带
  const items = props.items.map((i) => ({
    assetId: i.asset.id,
    qty: i.qty,
    ...(i.itemId != null ? { itemId: i.itemId, amount: i.amount ?? priceOf(i) } : {}),
    ...(i.itemId == null && i.amount != null ? { amount: i.amount } : {}),
  }))
  emit('submit', { fields, items })
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    class="dlg-wide"
    :close-on-click-modal="false"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <!-- 结算预览（购物车场景）：按（产品, 客户）双键分组展示将生成的销售记录（ADR-016） -->
    <div v-if="previewGroups.length" class="sod-preview">
      <div class="sod-preview-title">
        将生成 1 个项目 · <b>{{ previewGroups.length }}</b> 份销售记录
      </div>
      <!-- 2026-10-19 UI 优化：三列固定对齐（客户名弹性+超长省略 / 数量右对齐 / 金额右对齐等宽数字）
           2026-10-20（ADR-016）：同一客户跨多个产品会拆成多组，客户名后追加产品名区分
           ADR-020（PRICING-20261020）：组内服务期限一致时行内简短展示 -->
      <div v-for="(g, gi) in previewGroups" :key="gi" class="sod-preview-row">
        <span class="sod-preview-customer" :title="g.assetName ? `${g.customer} · ${g.assetName}` : g.customer">
          {{ g.customer }}<span v-if="g.assetName" class="muted"> · {{ g.assetName }}</span>
          <span v-if="g.service" class="muted">（服务期限 {{ g.service }}）</span>
        </span>
        <span class="muted sod-preview-qty">{{ g.qty }} 件</span>
        <span class="sod-amount sod-preview-amount">{{ formatMoney(g.amount) }}</span>
      </div>
    </div>

    <!-- 摘要：件数 + 销售金额合计（只读，行级金额已由 PUT /cart/{id} 持久化） -->
    <div class="sod-summary">
      <div class="sod-total">
        待下单 <b>{{ totalQty }}</b> 件 ·
        <template v-if="hasAmountItem">销售金额合计 <b class="sod-amount">{{ formatMoney(totalYuan) }}</b></template>
        <template v-else>预计金额 <b class="sod-amount">{{ formatMoney(totalYuan) }}</b></template>
      </div>
    </div>

    <!-- 所属主体（只读，由产品带出；跨主体混装时提示按客户分组） -->
    <div v-if="subject" class="sod-subject">
      <el-icon><InfoFilled /></el-icon>
      <template v-if="subject === '__multi__'">
        <span>所属主体：<b>多主体</b></span>
        <span class="muted">（购物车允许跨主体混装，结算时每个产品按客户各生成一条销售记录）</span>
      </template>
      <template v-else>
        <span>所属主体：<b>{{ entityShort(subject) }}</b></span>
        <span class="muted">（由产品自动带出）</span>
      </template>
    </div>

    <el-form label-position="top" class="sod-form">
      <el-form-item label="项目名称" required>
        <el-input v-model="form.projectName" placeholder="默认采购订单，可修改" />
      </el-form-item>
      <!-- 购物车模式：多销售记录下单，单值金额语义模糊 → 只读汇总展示（Σ各行小计），金额由后端按分组小计派生 -->
      <el-form-item label="销售金额合计（元）">
        <div class="sod-readonly-amount">¥ {{ formatYuan(Math.round(totalYuan)) }}</div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="loading" @click="onSubmit">确认下单</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 结算预览（按客户分组）：浅蓝底，与 .sod-summary 同款 */
.sod-preview {
  padding: 10px 14px;
  margin-bottom: 12px;
  background: #f0f6ff;
  border: 1px solid #e0ecff;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-body);
}
.sod-preview-title {
  margin-bottom: 6px;
  font-weight: 500;
}
.sod-preview-row {
  /* 2026-10-19 UI 优化：三列固定对齐（原 flex gap 流式排列，客户名长短不一导致列错位） */
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px 150px;
  align-items: center;
  column-gap: 12px;
  padding: 2px 0;
}
.sod-preview-customer {
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sod-preview-qty {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.sod-preview-amount {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.sod-summary {
  padding: 10px 14px;
  margin-bottom: 12px;
  background: #f0f6ff;
  border: 1px solid #e0ecff;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-body);
}
.sod-total {
  font-size: 13px;
}
.sod-amount {
  color: var(--primary-color);
}
.sod-subject {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  margin-bottom: 14px;
  background: #f6f8fa;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-body);
}
/* 购物车模式：合同合计只读展示 */
.sod-readonly-amount {
  font-size: 14px;
  font-weight: 600;
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
  line-height: 32px;
}
</style>
