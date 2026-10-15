<script setup lang="ts">
/**
 * 销售下单对话框（购物车下单 / 资产抽屉直接销售 共用）
 *
 * 表单字段：项目名称、客户名称、生态人员、预计签约日期、合同金额（¥ 元）、备注。
 * 所属主体由资产自动带出（下单资产已约束为同一主体），只读展示；无客户行业字段。
 * allowQtyEdit=true（资产抽屉单资产）时可编辑数量。
 * 提交后由父组件调用对应下单接口（checkoutCart / createSaleOrder），生成「进行中」销售项目并锁定库存（不自动出库）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { availableQty, entityShort, formatMoney, formatYuan, parseYuan, type Asset } from '@/types'
import { db, type OrderFields } from '@/api'

export interface OrderItem {
  asset: Asset
  qty: number
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    items: OrderItem[]
    allowQtyEdit?: boolean
    loading?: boolean
  }>(),
  { title: '下单', allowQtyEdit: false, loading: false },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'submit', payload: { fields: OrderFields; items: { assetId: number; qty: number }[] }): void
}>()

const reps = computed(() => Array.from(new Set(db.reps.map((r) => r.name))).filter(Boolean))

/** 主体：由首个资产带出（下单资产已约束为同一主体） */
const subject = computed(() => props.items[0]?.asset.subject ?? '')
const totalQty = computed(() => props.items.reduce((s, i) => s + i.qty, 0))
/** 是否单资产可编辑数量（资产抽屉场景） */
const editableQty = computed(() => props.allowQtyEdit && props.items.length === 1)
const maxQty = computed(() => {
  const a = props.items[0]?.asset
  if (!a) return undefined
  return a.repeatSale ? undefined : Math.max(availableQty(a) ?? 1, 1)
})

const form = reactive({
  projectName: '',
  customer: '',
  rep: '',
  expectedSignDate: '',
  remark: '',
})
const contractText = ref('') // 合同金额（元，展示用，千分位）
const qty = ref(1)

/** 预计金额（元）：可编辑数量时随 qty 变化 */
const totalYuan = computed(() => {
  const base = props.items.reduce((s, i) => s + (i.asset.salePrice || 0) * i.qty, 0)
  return base * 10000
})

/** 用户是否手动改写过合同金额；未改写时随数量/明细自动重算 */
const contractTouched = ref(false)

function reset() {
  form.projectName = ''
  form.customer = ''
  form.rep = ''
  form.expectedSignDate = ''
  form.remark = ''
  qty.value = props.items[0]?.qty ?? 1
  contractTouched.value = false
  contractText.value = formatYuan(Math.round(totalYuan.value))
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) reset()
  },
)

/** 数量 / 明细变化且用户未手改时，合同金额自动重算 */
watch(totalYuan, (v) => {
  if (!contractTouched.value) contractText.value = formatYuan(Math.round(v))
})

function onContractBlur() {
  contractText.value = formatYuan(parseYuan(contractText.value))
}

function validate(): boolean {
  if (!form.projectName.trim()) {
    ElMessage.warning('请填写项目名称')
    return false
  }
  if (!form.customer.trim()) {
    ElMessage.warning('请填写客户名称')
    return false
  }
  if (editableQty.value && qty.value < 1) {
    ElMessage.warning('数量不能小于 1')
    return false
  }
  return true
}

function onSubmit() {
  if (!validate()) return
  const fields: OrderFields = {
    projectName: form.projectName.trim(),
    customer: form.customer.trim(),
    rep: form.rep,
    contractAmount: parseYuan(contractText.value) / 10000, // 元 → 万元
    expectedSignDate: form.expectedSignDate,
    remark: form.remark,
    deliveryReq: '',
  }
  const items = editableQty.value
    ? [{ assetId: props.items[0].asset.id, qty: qty.value }]
    : props.items.map((i) => ({ assetId: i.asset.id, qty: i.qty }))
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
    width="560px"
    :close-on-click-modal="false"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <!-- 摘要 / 数量 -->
    <div class="sod-summary">
      <template v-if="editableQty && items.length === 1">
        <div class="sod-line">
          <span class="sod-asset-name">{{ items[0].asset.name }}</span>
          <el-input-number v-model="qty" :min="1" :max="maxQty" :precision="0" controls-position="right" size="small" style="width: 110px;" />
          <span class="muted">{{ items[0].asset.unit }}</span>
        </div>
        <div class="sod-total muted">
          小计 <b class="sod-amount">{{ formatMoney((items[0].asset.salePrice || 0) * qty) }}</b>
        </div>
      </template>
      <template v-else>
        <div class="sod-total">
          待下单 <b>{{ totalQty }}</b> 件 · 预计金额 <b class="sod-amount">{{ formatMoney(totalYuan / 10000) }}</b>
        </div>
      </template>
    </div>

    <!-- 所属主体（只读，由资产带出） -->
    <div v-if="subject" class="sod-subject">
      <el-icon><InfoFilled /></el-icon>
      <span>所属主体：<b>{{ entityShort(subject) }}</b></span>
      <span class="muted">（由资产自动带出）</span>
    </div>

    <el-form label-position="top" class="sod-form">
      <el-form-item label="项目名称" required>
        <el-input v-model="form.projectName" placeholder="如：XX 公司数据采购" />
      </el-form-item>
      <el-form-item label="客户名称" required>
        <el-input v-model="form.customer" placeholder="客户 / 单位名称" />
      </el-form-item>
      <div class="sod-row">
        <el-form-item label="生态人员">
          <el-select v-model="form.rep" placeholder="选择" clearable style="width: 100%;">
            <el-option v-for="r in reps" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="预计签约日期">
          <el-date-picker v-model="form.expectedSignDate" type="date" value-format="YYYY-MM-DD" placeholder="选填" style="width: 100%;" />
        </el-form-item>
      </div>
      <el-form-item label="合同金额（元）">
        <el-input v-model="contractText" placeholder="0.00" @input="contractTouched = true" @blur="onContractBlur">
          <template #prefix>¥</template>
        </el-input>
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
</style>
