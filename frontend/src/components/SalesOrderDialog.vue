<script setup lang="ts">
/**
 * 销售下单对话框（购物车下单 / 资产抽屉直接销售 共用）
 *
 * 表单字段：项目名称、客户名称、生态人员、商务负责人、预计签约日期、合同金额（¥ 元）、备注。
 * 所属主体由资产自动带出，只读展示；无客户行业字段。
 * allowQtyEdit=true（资产抽屉单资产）时可编辑数量。
 *
 * ADR-007 单合同语义：
 *  - 资产直接下单（/sales/order，默认模式）：payload 携带 customer + items + contractAmount，
 *    后端自动包装为单合同（SaleOrderInput 无 contracts 字段，已实测 200 且 contractCount=1）；
 *  - 购物车结算（/cart/checkout，cartMode=true）：客户已在购物车行级填写，对话框不再展示
 *    「客户名称」字段（payload 不带 customer，后端按行级客户分组拆合同）；合同金额改为
 *    只读汇总展示「合同合计（元）」= Σ各行小计（payload 不带 contractAmount，后端按分组小计派生）；
 *    项目名称默认「采购订单」可修改；previewGroups 传入时顶部展示「将生成 1 个项目 · N 份合同」分组预览。
 * 提交后由父组件调用对应下单接口，生成「进行中」销售项目并锁定库存（不自动出库）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import {
  availableQty,
  derivedUnitPrice,
  entityShort,
  formatMoney,
  formatTokens,
  formatYuan,
  isAmountMode,
  parseYuan,
  rsItemName,
  type Asset,
} from '@/types'
import { db, rsItemById, type OrderFields } from '@/api'

export interface OrderItem {
  asset: Asset
  qty: number
  /** ADR-008：包量定价行的合同金额（整数元）；购物车结算模式由购物车行带入 */
  amount?: number
  /** ADR-011：遥感数据明细行（挂 rs_items）——数量恒 1，单价 = 明细 price（后端权威重算） */
  itemId?: number
}

/** 结算预览分组（购物车场景）：按客户分组，每组 = 未来一份合同 */
export interface OrderPreviewGroup {
  customer: string
  qty: number
  amount: number
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    items: OrderItem[]
    allowQtyEdit?: boolean
    loading?: boolean
    previewGroups?: OrderPreviewGroup[]
    /** 购物车结算模式：客户已在行级填写 → 隐藏「客户名称」，合同金额只读汇总，项目名称默认「采购订单」 */
    cartMode?: boolean
  }>(),
  { title: '下单', allowQtyEdit: false, loading: false, previewGroups: () => [], cartMode: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: { fields: OrderFields; items: { assetId: number; qty: number; amount?: number; itemId?: number }[] }): void
}>()

/** 行计价单价（ADR-011）：遥感明细行取明细 price（后端权威重算，前端仅展示/传值）；其余取资产单价 */
function priceOf(i: OrderItem): number {
  if (i.itemId != null) return rsItemById(i.itemId)?.price ?? 0
  return i.asset.salePrice || 0
}

/** 单资产摘要行名称：遥感明细行显示「父资产名 · 明细名」 */
const singleName = computed(() => {
  const i = props.items[0]
  if (!i) return ''
  if (i.itemId != null) {
    const r = rsItemById(i.itemId)
    return r ? `${i.asset.name} · ${rsItemName(r)}` : i.asset.name
  }
  return i.asset.name
})

const reps = computed(() => Array.from(new Set(db.reps.map((r) => r.name))).filter(Boolean))

/** 主体：全部下单资产同主体时带出展示；跨主体混装（购物车场景）显示「多主体」 */
const subject = computed(() => {
  const subjects = Array.from(new Set(props.items.map((i) => i.asset.subject).filter(Boolean)))
  if (subjects.length <= 1) return subjects[0] ?? ''
  return '__multi__'
})
const totalQty = computed(() => props.items.reduce((s, i) => s + i.qty, 0))
/** 是否单资产可编辑数量（资产抽屉场景） */
const editableQty = computed(() => props.allowQtyEdit && props.items.length === 1)
const maxQty = computed(() => {
  const first = props.items[0]
  if (!first) return undefined
  // ADR-011：遥感明细行数量恒 1
  if (first.itemId != null) return 1
  const a = first.asset
  return a.repeatSale ? undefined : Math.max(availableQty(a) ?? 1, 1)
})

const form = reactive({
  projectName: '',
  customer: '',
  rep: '',
  businessOwner: '',
  expectedSignDate: '',
  remark: '',
})
const contractText = ref('') // 合同金额（元，展示用，千分位）
const qty = ref(1)

/** 是否含包量定价行（ADR-008）：金额以合同金额（整数元）为权威，单价不参与计价 */
const hasAmountItem = computed(() => props.items.some((i) => isAmountMode(i.asset)))

/** 预计/合同金额（元值）：unit 模式 = 单价×数量（遥感明细行取明细 price）；amount 模式 = 合同金额（购物车行带入 / 直接下单取金额输入框） */
const totalYuan = computed(() =>
  props.items.reduce((s, i) => {
    if (isAmountMode(i.asset)) {
      if (props.cartMode) return s + (i.amount ?? 0)
      // 直接下单：对话框「合同金额」输入框为权威输入
      return s + parseYuan(contractText.value)
    }
    return s + priceOf(i) * i.qty
  }, 0),
)

/** 派生参考单价（仅 amount 模式直接下单展示）：合同金额 ÷ 数量 ÷ 1e4，保留 4 位 + 「约」 */
const derivedPriceText = computed(() => {
  if (!editableQty.value || !props.items.length || !isAmountMode(props.items[0].asset)) return ''
  return derivedUnitPrice(parseYuan(contractText.value), qty.value)
})

/** 用户是否手动改写过合同金额；未改写时随数量/明细自动重算 */
const contractTouched = ref(false)

/** 项目名称是否被用户手动改过；未改过时默认跟随客户名称（客户为空则留空） */
const projectNameTouched = ref(false)
watch(
  () => form.customer,
  (c) => {
    if (!projectNameTouched.value) form.projectName = c || ''
  },
)

function reset() {
  // 购物车模式：客户已行级填写，项目名称默认「采购订单」（可修改）；直接下单仍默认跟随客户名称
  form.projectName = props.cartMode ? '采购订单' : ''
  form.customer = ''
  form.rep = ''
  form.businessOwner = ''
  form.expectedSignDate = ''
  form.remark = ''
  qty.value = props.items[0]?.qty ?? 1
  contractTouched.value = false
  projectNameTouched.value = false
  // amount 模式：合同金额为权威输入，初始 0.00 待用户填写（购物车模式只读展示行内金额合计）
  contractText.value = hasAmountItem.value ? '0.00' : formatYuan(Math.round(totalYuan.value))
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) reset()
  },
)

/** 数量 / 明细变化且用户未手改时，合同金额自动重算（amount 模式跳过：合同金额为权威输入） */
watch(totalYuan, (v) => {
  if (contractTouched.value) return
  if (hasAmountItem.value) return
  contractText.value = formatYuan(Math.round(v))
})

function onContractBlur() {
  contractText.value = formatYuan(parseYuan(contractText.value))
}

function validate(): boolean {
  if (!form.projectName.trim()) {
    ElMessage.warning('请填写项目名称')
    return false
  }
  // 购物车模式客户已在行级填写（父组件已拦截空客户行），对话框不再校验
  if (!props.cartMode && !form.customer.trim()) {
    ElMessage.warning('请填写客户名称')
    return false
  }
  if (editableQty.value && qty.value < 1) {
    ElMessage.warning('数量不能小于 1')
    return false
  }
  // ADR-008：包量定价直接下单——合同金额必须为正整数元
  if (editableQty.value && isAmountMode(props.items[0].asset)) {
    const amt = parseYuan(contractText.value)
    if (!Number.isInteger(amt) || amt <= 0) {
      ElMessage.warning('合同金额须为整数元')
      return false
    }
  }
  return true
}

function onSubmit() {
  if (!validate()) return
  const fields: OrderFields = {
    projectName: form.projectName.trim(),
    rep: form.rep,
    businessOwner: form.businessOwner,
    expectedSignDate: form.expectedSignDate,
    remark: form.remark,
    deliveryReq: '',
  }
  if (props.cartMode) {
    // 购物车结算（后端 CheckoutInput 已确认）：customer 可选且不参与分组（按行级客户分组）、
    // contractAmount 不被消费（合同金额按分组小计派生）→ payload 均不带
  } else {
    fields.customer = form.customer.trim()
    fields.contractAmount = parseYuan(contractText.value) // 元值直提
  }
  // ADR-008：amount 模式行携带合同金额（整数元，权威输入）；unit 模式行不带
  // ADR-011：遥感明细行携带 itemId（qty 恒 1）+ amount=明细 price（后端按 rs_items.price 权威重算，前端传值无妨）
  const source: OrderItem[] = editableQty.value
    ? [{ asset: props.items[0].asset, qty: qty.value, itemId: props.items[0].itemId }]
    : props.items
  const items = source.map((i) => ({
    assetId: i.asset.id,
    qty: i.qty,
    ...(i.itemId != null ? { itemId: i.itemId, amount: i.amount ?? priceOf(i) } : {}),
    ...(i.itemId == null && isAmountMode(i.asset)
      ? { amount: props.cartMode ? (i.amount ?? 0) : parseYuan(contractText.value) }
      : {}),
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
    <!-- 结算预览（购物车场景）：按客户分组展示将生成的合同 -->
    <div v-if="previewGroups.length" class="sod-preview">
      <div class="sod-preview-title">
        将生成 1 个项目 · <b>{{ previewGroups.length }}</b> 份合同
      </div>
      <div v-for="g in previewGroups" :key="g.customer" class="sod-preview-row">
        <span class="sod-preview-customer">{{ g.customer }}</span>
        <span class="muted">{{ g.qty }} 件</span>
        <span class="sod-amount">{{ formatMoney(g.amount) }}</span>
      </div>
    </div>

    <!-- 摘要 / 数量 -->
    <div class="sod-summary">
      <template v-if="editableQty && items.length === 1">
        <div class="sod-line">
          <span class="sod-asset-name">{{ singleName }}</span>
          <!-- ADR-011：遥感明细行数量恒 1（禁用） -->
          <el-input-number v-model="qty" :min="1" :max="maxQty" :precision="0" controls-position="right" size="small" style="width: 140px;" :disabled="items[0].itemId != null" />
          <span class="muted">
            <template v-if="isAmountMode(items[0].asset)">Token（{{ formatTokens(qty) }}）</template>
            <template v-else>{{ items[0].asset.unit }}</template>
          </span>
        </div>
        <!-- ADR-008：包量定价——合同金额（整数元）为权威输入，单价为派生参考 -->
        <div v-if="isAmountMode(items[0].asset)" class="sod-total muted">
          派生单价 <b class="sod-amount">{{ derivedPriceText || '-' }}</b>
          <span>（合同金额在下方「合同金额」字段填写，须为整数元）</span>
        </div>
        <div v-else class="sod-total muted">
          小计 <b class="sod-amount">{{ formatMoney(priceOf(items[0]) * qty) }}</b>
        </div>
      </template>
      <template v-else>
        <div class="sod-total">
          待下单 <b>{{ totalQty }}</b> 件 ·
          <template v-if="hasAmountItem">合同合计 <b class="sod-amount">{{ formatMoney(totalYuan) }}</b></template>
          <template v-else>预计金额 <b class="sod-amount">{{ formatMoney(totalYuan) }}</b></template>
        </div>
      </template>
    </div>

    <!-- 所属主体（只读，由资产带出；跨主体混装时提示按客户分组） -->
    <div v-if="subject" class="sod-subject">
      <el-icon><InfoFilled /></el-icon>
      <template v-if="subject === '__multi__'">
        <span>所属主体：<b>多主体</b></span>
        <span class="muted">（购物车允许跨主体混装，结算时按客户分组生成合同）</span>
      </template>
      <template v-else>
        <span>所属主体：<b>{{ entityShort(subject) }}</b></span>
        <span class="muted">（由资产自动带出）</span>
      </template>
    </div>

    <el-form label-position="top" class="sod-form">
      <el-form-item label="项目名称" required>
        <el-input
          v-model="form.projectName"
          :placeholder="cartMode ? '默认采购订单，可修改' : '默认跟随客户名称，可修改'"
          @input="projectNameTouched = true"
        />
      </el-form-item>
      <!-- 客户名称：仅直接下单模式；购物车模式客户已在行级填写（按行级分组生成合同） -->
      <el-form-item v-if="!cartMode" label="客户名称" required>
        <el-input v-model="form.customer" placeholder="客户 / 单位名称" />
      </el-form-item>
      <div class="sod-row">
        <el-form-item label="生态人员">
          <el-select v-model="form.rep" placeholder="选择" clearable style="width: 100%;">
            <el-option v-for="r in reps" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="商务负责人">
          <el-input v-model="form.businessOwner" placeholder="商务负责人姓名" />
        </el-form-item>
      </div>
      <div class="sod-row">
        <el-form-item label="预计签约日期">
          <el-date-picker v-model="form.expectedSignDate" type="date" value-format="YYYY-MM-DD" placeholder="选填" style="width: 100%;" />
        </el-form-item>
      </div>
      <!-- 购物车模式：多合同下单，单值金额语义模糊 → 只读汇总展示（Σ各行小计），金额由后端按分组小计派生 -->
      <el-form-item v-if="cartMode" label="合同合计（元）">
        <div class="sod-readonly-amount">¥ {{ formatYuan(Math.round(totalYuan)) }}</div>
      </el-form-item>
      <el-form-item v-else :label="hasAmountItem ? '合同金额（整数元）' : '合同金额（元）'">
        <!-- 修复：unit 模式合同金额由后端按 单价×数量 权威重算（入参不采信），
             可编辑时用户改写的值会被静默丢弃且无提示——改为只读展示派生值，所见即所得 -->
        <el-input v-model="contractText" :readonly="!hasAmountItem" :placeholder="hasAmountItem ? '整数元，如 8000000' : '按 单价×数量 自动计算'" @input="contractTouched = true" @blur="onContractBlur">
          <template #prefix>¥</template>
        </el-input>
        <!-- ADR-008 包量定价说明（浅蓝提示） -->
        <div v-if="hasAmountItem" class="sod-amount-hint">
          Token 资产按包量售卖，下单以合同金额（整数元）为准，参考单价不参与计价
        </div>
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
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
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 0;
}
.sod-preview-customer {
  font-weight: 500;
  color: var(--text-primary);
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
.sod-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.sod-asset-name {
  font-weight: 500;
  color: var(--text-primary);
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
.sod-row {
  display: flex;
  gap: 12px;
}
.sod-row .el-form-item {
  flex: 1;
}
/* ADR-008 包量定价说明：浅蓝提示条（与 .sod-summary 同款） */
.sod-amount-hint {
  margin-top: 6px;
  padding: 8px 12px;
  background: #f0f6ff;
  border: 1px solid #e0ecff;
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-body);
  line-height: 18px;
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
