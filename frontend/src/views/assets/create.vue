<script setup lang="ts">
/**
 * 资产管理 - 登记资产 / 编辑资产
 *
 * 路由：/assets/create（可带 ?board=xxx 预填板块）；/assets/:id/edit 编辑
 * 页面结构对齐《新建销售项目 UI 开发提示词》：返回入口 + 标题区 + 分区块白卡表单 + 底部操作区
 *
 * 资产属性（2026-10-13 重设计）：
 *  - 基本信息：板块 / 类型 / 名称 / 规格 / 所在主体 / 入库时间 / 长期买断 / 到期时间
 *  - 数量单价：计量单位 / 资产总数 / 单价 / 可重复售卖
 *  - 状态与备注：状态由库存自动判定（库存可售 / 全部出售），备注 + 产品清单上传/预览
 *  资产编号自动生成，供应商/交付地点/序列号/预计金额等字段已移除
 *  2026-10-15：功能清单附件上传已移除（后端字段保留，提交 payload 不再携带）；
 *  产品清单附件 2026-10-15 误删后已恢复（上传/回显/预览）
 *  2026-10-16（ADR-011）：遥感数据容器资产——提示条移至「资产类型」正下方，
 *  隐藏「数量单价」卡，提交时兜底 quantity:1 / salePrice:0 / unit:'份（可售明细）'
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Box,
  CircleCheck,
  Document,
  Goods,
  InfoFilled,
  Upload,
} from '@element-plus/icons-vue'
import {
  ASSET_STOCK_STATE,
  BOARDS,
  ENTITIES,
  formatTokens,
  today,
  type AssetStatus,
  type AssetStockState,
  type Board,
} from '@/types'
import { createAsset, fileDisplayName, getAsset, refresh, updateAsset, uploadFile, type AssetInput } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'
import FilePreview from '@/components/FilePreview.vue'

const route = useRoute()
const router = useRouter()

const isEdit = computed(() => route.path.endsWith('edit'))
const assetId = computed(() => Number(route.params.id))

const formRef = ref()
const submitting = ref(false)

const form = reactive({
  name: '',
  board: (route.query.board as Board) || 'embodied',
  type: '',
  subject: '',
  unit: '',
  quantity: 1,
  repeatSale: false,
  salePrice: 0,
  status: 'in_stock' as AssetStatus,
  inboundDate: today(),
  expiryDate: '',
  perpetual: false,
  spec: '',
  contractFile: '',
  remark: '',
})

/** ADR-011：是否遥感数据类型（容器资产，仅显示 info-bar 提示；三维字段组已移除） */
const isRemote = computed(() => form.type === '遥感数据')

/** ADR-008：是否包量定价——新建时卫星 Token 即 amount 模式（后端入库置 pricingMode='amount'）；编辑读存量值 */
const isAmount = computed(() => {
  if (isEdit.value) return getAsset(assetId.value)?.pricingMode === 'amount'
  return form.type === '卫星Token'
})

const rules = {
  name: [{ required: true, message: '请输入资产名称', trigger: 'blur' }],
  board: [{ required: true, message: '请选择所属板块', trigger: 'change' }],
  type: [{ required: true, message: '请选择资产类型', trigger: 'change' }],
  subject: [{ required: true, message: '请选择所在主体', trigger: 'change' }],
  unit: [{ required: true, message: '请输入计量单位', trigger: 'blur' }],
  quantity: [{ required: true, message: '请输入资产总数', trigger: 'change' }],
  inboundDate: [{ required: true, message: '请选择入库时间', trigger: 'change' }],
}

const typeOptions: Record<Board, string[]> = {
  embodied: ['机器人', '数采设备', '平台软件'],
  satellite: ['卫星Token', '卫星数据', '遥感数据'],
  software: ['软件'],
  hardware: ['硬件集群'],
  compute: ['算力服务器'],
}

/** 卫星数据默认可重复售卖 */
watch([() => form.board, () => form.type], ([b, t]) => {
  if (b === 'satellite' && t === '卫星数据') form.repeatSale = true
})

/** 勾选长期买断后无需到期时间 */
watch(
  () => form.perpetual,
  (v) => {
    if (v) form.expiryDate = ''
  },
)

/**
 * 库存状态展示：与列表页口径统一，走派生函数（库存可售 / 暂无库存）。
 * 基于表单实时值派生，勾选/取消「可重复售卖」瞬间状态标签即时联动：
 *  - repeatSale → 库存可售（与 assetStockState 口径一致）
 *  - 否则按 form.quantity 实时值 + 已存锁定/售卖量（编辑模式取已存值，新建模式为 0）判定
 */
const stockState = computed<AssetStockState>(() => {
  if (form.repeatSale) return 'in_stock'
  const a = isEdit.value ? getAsset(assetId.value) : null
  // 与 noSellableStock/availableQty 同口径：quantity - lockedQty - shippedQty <= 0（repeatSale 已排除）
  const noStock = form.quantity - (a?.lockedQty ?? 0) - (a?.shippedQty ?? 0) <= 0
  return noStock ? 'no_stock' : 'in_stock'
})

function loadAsset() {
  if (!isEdit.value) return
  const a = getAsset(assetId.value)
  if (!a) return
  Object.assign(form, {
    name: a.name,
    board: a.board,
    type: a.type,
    subject: a.subject,
    unit: a.unit,
    quantity: a.quantity,
    repeatSale: a.repeatSale,
    salePrice: a.salePrice,
    status: a.status,
    inboundDate: a.inboundDate,
    expiryDate: a.expiryDate,
    perpetual: a.perpetual,
    spec: a.spec,
    contractFile: a.contractFile || '',
    remark: a.remark,
  })
}

// ===== 产品清单上传 =====
const contractInputRef = ref<HTMLInputElement>()
const uploading = ref(false)
const previewVisible = ref(false)

function pickContract() {
  contractInputRef.value?.click()
}
async function onContractPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploading.value = true
  try {
    const { filename } = await uploadFile(file)
    form.contractFile = filename
    ElMessage.success('产品清单已上传')
  } catch (err: any) {
    ElMessage.error(err?.message || '上传失败')
  } finally {
    uploading.value = false
  }
}
function previewContract() {
  if (form.contractFile) previewVisible.value = true
}
function removeContract() {
  form.contractFile = ''
}
function contractTypeLabel(fname: string): string {
  const e = fname.split('.').pop()?.toLowerCase() || ''
  if (e === 'pdf') return 'PDF'
  if (e === 'docx' || e === 'doc') return 'Word'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(e)) return '图片'
  return e ? e.toUpperCase() : '文件'
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  // ADR-011：遥感容器资产兜底——数量=明细数派生、单价在明细上，后端 AssetIn 对 quantity 有 >0 校验，
  // 故传 quantity:1 / salePrice:0，单位与 constants.ts CATEGORY_UNITS 遥感条目一致；其余类型行为不变
  const payload: AssetInput = isRemote.value
    ? { ...form, name: form.name, quantity: 1, salePrice: 0, unit: '份（可售明细）' }
    : { ...form, name: form.name }
  try {
    if (isEdit.value) {
      await updateAsset(assetId.value, payload)
      ElMessage.success('更新成功')
      router.push(`/assets/${assetId.value}/detail`)
    } else {
      const created = await createAsset(payload)
      ElMessage.success(`创建成功，资产编号 ${created.code}`)
      router.push(`/assets/${created.id}/detail`)
    }
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到资产台账，避免退出应用
  if (window.history.state?.back) router.back()
  else router.push(`/assets/${form.board}`)
}

// 编辑模式：先拉取后端数据填充镜像，再预填表单（新建模式直接渲染）
onMounted(async () => {
  await refresh()
  loadAsset()
})
</script>

<template>
  <div class="page-container">
    <div class="create-wrap">
      <!-- 页面标题区：文字式返回入口 + 标题 + 说明 -->
      <div class="page-head">
        <div>
          <a class="back-link" @click="handleCancel">
            <el-icon><ArrowLeft /></el-icon>
            {{ isEdit ? '返回资产详情' : '返回资产台账' }}
          </a>
          <h1>{{ isEdit ? '编辑资产' : '登记资产' }}</h1>
          <div class="desc">登记资产名称、板块、数量与单价；资产编号自动生成，金额以元为单位。</div>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="asset-form">
        <!-- 1. 基本信息 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Box /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">带 * 的字段为必填项</span>
          </div>
          <div class="form-grid">
            <el-form-item label="所属板块" prop="board">
              <el-select v-model="form.board" :disabled="isEdit" placeholder="选择所属板块" style="width: 100%;">
                <el-option
                  v-for="b in BOARDS"
                  :key="b.key"
                  :label="b.label + (b.wip ? '（建设中）' : '')"
                  :value="b.key"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="资产类型" prop="type">
              <el-select v-model="form.type" placeholder="选择资产类型" style="width: 100%;">
                <el-option v-for="t in typeOptions[form.board] || []" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <!-- 1.5 遥感数据容器资产提示（ADR-011：紧跟资产类型下方，三维字段组已移除，按普通父资产登记） -->
            <div v-if="isRemote" class="info-bar">
              <el-icon aria-hidden="true"><InfoFilled /></el-icon>
              <span>遥感数据为容器资产，保存后请在资产详情「可售明细」页签维护 省/精度/月份 明细</span>
            </div>
            <el-form-item label="资产名称" prop="name">
              <el-input v-model="form.name" placeholder="如：智元机器人-G1" />
            </el-form-item>
            <el-form-item label="规格说明" prop="spec">
              <el-input v-model="form.spec" placeholder="型号 / 配置 / 数据范围等" />
            </el-form-item>
            <el-form-item label="所在主体" prop="subject">
              <el-select v-model="form.subject" placeholder="选择所在主体" filterable style="width: 100%;">
                <el-option v-for="e in ENTITIES" :key="e.name" :label="e.name" :value="e.name" />
              </el-select>
            </el-form-item>
            <el-form-item label="入库时间" prop="inboundDate">
              <el-date-picker
                v-model="form.inboundDate"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择入库时间"
                style="width: 100%;"
              />
            </el-form-item>
            <el-form-item label="长期买断">
              <el-switch v-model="form.perpetual" />
              <span class="muted" style="font-size: 12px; margin-left: 8px;">勾选后资产长期有效，无需设置到期时间</span>
            </el-form-item>
            <el-form-item label="到期时间" prop="expiryDate">
              <el-date-picker
                v-model="form.expiryDate"
                type="date"
                value-format="YYYY-MM-DD"
                :disabled="form.perpetual"
                :placeholder="form.perpetual ? '长期买断，无需设置' : '选择到期时间'"
                style="width: 100%;"
              />
            </el-form-item>
          </div>
        </div>

        <!-- 2. 数量单价（ADR-011：遥感容器资产隐藏——数量=明细数派生、单价在明细上，提交时兜底） -->
        <div v-if="!isRemote" class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Goods /></el-icon></span>
            <span class="bh-title">数量单价</span>
            <span class="bh-hint">登记资产总数、计量单位与销售单价（元）</span>
          </div>
          <div class="form-grid">
            <el-form-item label="计量单位" prop="unit">
              <el-input v-model="form.unit" placeholder="套 / 台 / 轨 / 期 / 许可证 / 集群" />
            </el-form-item>
            <el-form-item label="资产总数" prop="quantity">
              <el-input-number v-model="form.quantity" :min="0" :precision="0" :step="1" style="width: 100%;" />
              <!-- ADR-008：Token 资产数量按 formatTokens 展示（库内仍存原始个数） -->
              <div v-if="isAmount" class="muted" style="font-size: 12px; margin-top: 4px;">
                {{ formatTokens(form.quantity) }} Token（按原始个数入库）
              </div>
            </el-form-item>
            <el-form-item :label="isAmount ? '参考单价（元/万Token）' : '销售单价（元）'" prop="salePrice">
              <el-input-number v-model="form.salePrice" :min="0" :precision="2" style="width: 100%;" />
            </el-form-item>
            <!-- ADR-008：包量定价说明（浅蓝提示条） -->
            <div v-if="isAmount" class="info-bar soft">
              Token 资产按包量售卖，下单时以合同金额（整数元）为准，参考单价不参与计价
            </div>
            <el-form-item label="可重复售卖">
              <el-switch v-model="form.repeatSale" />
              <span class="muted" style="font-size: 12px; margin-left: 8px;">数据类资产建议开启，销售不扣减库存</span>
            </el-form-item>
            <div class="repeat-sale-hint muted">开启后该资产不再受库存限制：售罄资产也可继续下单，销售只计次、不扣减库存数量</div>
          </div>
        </div>

        <!-- 4. 状态与备注 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><CircleCheck /></el-icon></span>
            <span class="bh-title">状态与备注</span>
          </div>
          <el-form-item label="资产状态">
            <div class="status-line">
              <el-tag :type="ASSET_STOCK_STATE[stockState].tag" size="large" round>
                {{ ASSET_STOCK_STATE[stockState].label }}
              </el-tag>
              <span class="status-tip muted">状态由库存自动判定，无需手动修改</span>
            </div>
          </el-form-item>
          <el-form-item label="备注" prop="remark">
            <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="填写特殊约定或注意事项" />
          </el-form-item>
          <el-form-item label="产品清单">
            <div class="contract-up">
              <input
                ref="contractInputRef"
                type="file"
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.xlsx"
                style="display: none"
                @change="onContractPicked"
              />
              <template v-if="!form.contractFile">
                <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                  <span>
                    <el-button :icon="Upload" :loading="uploading" :disabled="!canWrite" @click="pickContract">
                      上传产品清单（PDF / Word / 图片）
                    </el-button>
                  </span>
                </el-tooltip>
                <span class="muted" style="font-size: 12px; margin-left: 8px;">支持 PDF、Word（.doc/.docx）、图片，≤20MB</span>
              </template>
              <template v-else>
                <el-icon class="cu-ic"><Document /></el-icon>
                <span class="cu-name">{{ fileDisplayName(form.contractFile) }}</span>
                <span class="cu-sub">产品清单 · {{ contractTypeLabel(form.contractFile) }}</span>
                <el-button link type="primary" size="small" @click="previewContract">预览</el-button>
                <el-button link type="primary" size="small" :loading="uploading" :disabled="!canWrite" @click="pickContract">替换</el-button>
                <el-button link type="danger" size="small" :disabled="!canWrite" @click="removeContract">移除</el-button>
              </template>
            </div>
          </el-form-item>
        </div>

        <!-- 底部操作区：右对齐，不悬浮 -->
        <div class="bottom-actions">
          <el-button @click="handleCancel">返回</el-button>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <span>
              <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                {{ isEdit ? '保存修改' : '创建资产' }}
              </el-button>
            </span>
          </el-tooltip>
        </div>
      </el-form>

      <!-- 产品清单预览 -->
      <el-dialog v-model="previewVisible" title="产品清单预览" fullscreen append-to-body destroy-on-close>
        <FilePreview
          v-if="previewVisible && form.contractFile"
          :filename="form.contractFile"
        />
      </el-dialog>

    </div>
  </div>
</template>

<style scoped>
/* 内容区最大 720px，居中（单列表单下 1080px 过宽，长文本输入框拉得过散，720px 更整齐） */
.create-wrap {
  max-width: 720px;
  margin: 0 auto;
  width: 100%;
}

.asset-form :deep(.el-form-item__label) {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 20px;
  padding-bottom: 6px;
}
.asset-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.asset-form :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
/* 单列表单：覆盖全局 .form-grid 的 3/2 列（scoped 仅作用于本页），行距沿用组件既有 18px */
.form-grid {
  grid-template-columns: 1fr;
  gap: 0;
}

/* 遥感提示条（ADR-011：位于基本信息 grid 内、资产类型正下方），下边距与表单行距一致 */
.form-grid .info-bar {
  margin-bottom: 18px;
}

/* 可重复售卖警示行：紧跟开关下方，muted 12px */
.repeat-sale-hint {
  font-size: 12px;
  line-height: 18px;
  margin: -10px 0 18px;
}

/* ===== 资产状态行：tag 在上，muted 12px 提示置于其正下方，左缘与 tag 对齐 ===== */
.status-line {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}
.status-line .status-tip {
  font-size: 12px;
  line-height: 18px;
}

/* ===== 产品清单 ===== */
.contract-up {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.contract-up .cu-ic {
  color: var(--primary-color);
  font-size: 18px;
}
.contract-up .cu-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.contract-up .cu-sub {
  font-size: 12px;
  color: #9aa9bf;
  flex-shrink: 0;
}
</style>
