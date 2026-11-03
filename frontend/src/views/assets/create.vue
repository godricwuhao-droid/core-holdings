<script setup lang="ts">
/**
 * 产品及服务 - 登记产品 / 编辑产品
 *
 * 路由：/assets/create（可带 ?board=xxx 预填板块）；/assets/:id/edit 编辑
 * 页面结构对齐《新建销售项目 UI 开发提示词》：返回入口 + 标题区 + 分区块白卡表单 + 底部操作区
 *
 * 产品属性（2026-10-13 重设计；FORMS-20261022 / ADR-036 §5 分块重构，不增不减字段）：
 *  - ① 基本信息：板块 / 类型 / 名称 / 规格 / 所在主体（遥感容器追加 info-bar + 可重复售卖禁用态开关）
 *  - ② 数量与价格（仅非容器）：计量单位 / 产品总数 / 销售单价（元）/ 参考价格区间（元）/ 可重复售卖
 *  - ③ 有效期与附件：产品有效期（原「长期买断」）/ 到期时间 / 登记时间（仅编辑，只读）/ 产品清单附件
 *  - ④ 备注：仅备注（UI-OPT-20261022：「产品状态」展示块已移除——状态本就由数量自动派生，无输入价值）
 *  产品编号自动生成，供应商/交付地点/序列号/预计金额等字段已移除
 *  2026-10-15：功能清单附件上传已移除（后端字段保留，提交 payload 不再携带）；
 *  产品清单附件 2026-10-15 误删后已恢复（上传/回显/预览）
 *  2026-10-16（ADR-011）：遥感数据容器产品——提示条位于「产品类型」正下方，
 *  隐藏「数量与价格」卡，提交时兜底 quantity:1 / salePrice:0 / unit:'份（可售明细）'
 *  FORMS-20261022（ADR-036）：
 *  - §1 登记时间：新建不再提供输入（提交传空，后端自动取当天）；编辑只读展示（文本行）
 *  - §2 术语「长期买断」→「产品有效期」（字段名 perpetual 不变）
 *  - §3 参考区间自动同步（仅新建、仅非容器）：salePrice>0 且区间未手改 →
 *    priceMin=salePrice、priceMax=salePrice×1.02（ADR-048：按 1e-6 规整）；手改置 touchedMin/touchedMax 后不再覆盖
 *  - §4 重复售卖：移除「卫星数据自动勾选」，默认一律 false；容器恒关（禁用态 + 说明）
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
  amountInputFormatter,
  amountInputParser,
  BOARDS,
  roundAmount,
  today,
  type AssetStatus,
  type Board,
} from '@/types'
import { createAsset, db, deleteUploadFile, fileDisplayName, getAsset, refresh, showError, updateAsset, uploadFile, type AssetInput } from '@/api'
import { canWrite, NO_PERM_TIP } from '@/auth'
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
  // 参考价格区间（ADR-018，PRICING-20261020）：选填，可单边；下单折扣区间校验用
  priceMin: undefined as number | undefined,
  priceMax: undefined as number | undefined,
  status: 'in_stock' as AssetStatus,
  inboundDate: today(),
  expiryDate: '',
  perpetual: false,
  spec: '',
  contractFile: '',
  remark: '',
})

/** ADR-011：是否遥感数据类型（容器产品，仅显示 info-bar 提示；三维字段组已移除） */
const isRemote = computed(() => form.type === '遥感数据')

/** ADR-008：是否包量定价——新建时卫星 Token 即 amount 模式（后端登记置 pricingMode='amount'）；编辑读存量值 */
const isAmount = computed(() => {
  if (isEdit.value) return getAsset(assetId.value)?.pricingMode === 'amount'
  return form.type === '卫星Token'
})

const rules = {
  name: [{ required: true, message: '请输入产品名称', trigger: 'blur' }],
  board: [{ required: true, message: '请选择所属板块', trigger: 'change' }],
  type: [{ required: true, message: '请选择产品类型', trigger: 'change' }],
  subject: [{ required: true, message: '请选择所在主体', trigger: 'change' }],
  unit: [{ required: true, message: '请输入计量单位', trigger: 'blur' }],
  quantity: [{ required: true, message: '请输入产品总数', trigger: 'change' }],
  // ADR-036 §1：登记时间不再是入参必填（新建无输入项、编辑只读展示），inboundDate 校验规则移除
}

const typeOptions: Record<Board, string[]> = {
  embodied: ['机器人', '数采设备', '平台软件'],
  satellite: ['卫星Token', '卫星数据', '遥感数据'],
  software: ['软件'],
  hardware: ['硬件集群'],
  compute: ['算力服务器'],
}

// ADR-036 §4：移除「卫星数据自动勾选可重复售卖」逻辑——默认一律 false（存量产品不受影响，只改新建默认值）

/** 勾选产品有效期（原「长期买断」）后无需到期时间 */
watch(
  () => form.perpetual,
  (v) => {
    if (v) form.expiryDate = ''
  },
)

/** ADR-036 §3：参考区间自动同步（仅新建、仅非遥感容器）——
 *  salePrice > 0 且对应边界未被手动修改过 → priceMin = salePrice、priceMax = salePrice × 1.02（ADR-048：按 1e-6 规整）；
 *  手改区间输入（@change）置 touchedMin/touchedMax 后不再自动覆盖（以最后一次手改为准）；
 *  编辑模式不自动同步（loadAsset 回显存量值，watch 有 isEdit 守卫） */
const touchedMin = ref(false)
const touchedMax = ref(false)
watch(
  () => form.salePrice,
  (v) => {
    if (isEdit.value || isRemote.value || !(v > 0)) return
    if (!touchedMin.value) form.priceMin = v
    if (!touchedMax.value) form.priceMax = roundAmount(v * 1.02)
  },
)

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
    // ADR-018（PRICING-20261020）：参考区间回显（未设为 null → 输入框留空）
    priceMin: a.priceMin ?? undefined,
    priceMax: a.priceMax ?? undefined,
    status: a.status,
    inboundDate: a.inboundDate,
    expiryDate: a.expiryDate,
    perpetual: a.perpetual,
    spec: a.spec,
    contractFile: a.contractFile || '',
    remark: a.remark,
  })
  // ADR-036 §4：遥感容器强制 repeatSale=false（后端 create/update 传 true 会 400）——
  // 表单内为禁用态恒关开关，存量脏值（历史数据）在此归零，避免保存时被后端 400 卡住
  if (isRemote.value) form.repeatSale = false
}

// ===== 产品清单上传 =====
const contractInputRef = ref<HTMLInputElement>()
const uploading = ref(false)
const previewVisible = ref(false)

function pickContract() {
  contractInputRef.value?.click()
}
/**
 * 释放旧附件（FIX-20261022 / BUG-36）：替换/移除产品清单时顺带删除服务端散列文件。
 * 仍被产品清单/功能清单/交付物附件引用时后端返回 400（detail 为可读中文）——属正常边界（如
 * 存量产品仍指向该文件、或本次移除尚未保存），**忽略错误**并给一句轻提示，不阻断表单。
 */
async function releaseContractFile(stored: string) {
  if (!stored) return
  try {
    await deleteUploadFile(stored)
  } catch {
    ElMessage.info('原附件仍被引用，暂未删除服务端文件')
  }
}

async function onContractPicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const prev = form.contractFile
  uploading.value = true
  try {
    const { filename } = await uploadFile(file)
    form.contractFile = filename
    ElMessage.success(prev ? '产品清单已替换' : '产品清单已上传')
    // 替换场景：旧文件不再被本表单引用 → 尝试删除（引用占用 400 时忽略，见 releaseContractFile）
    if (prev && prev !== filename) await releaseContractFile(prev)
  } catch (err) {
    showError(err, '上传失败')
  } finally {
    uploading.value = false
  }
}
function previewContract() {
  if (form.contractFile) previewVisible.value = true
}
async function removeContract() {
  const stored = form.contractFile
  form.contractFile = ''
  await releaseContractFile(stored)
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
  // ADR-011：遥感容器产品兜底——数量=明细数派生、单价在明细上，后端 AssetIn 对 quantity 有 >0 校验，
  // 故传 quantity:1 / salePrice:0，单位与 constants.ts CATEGORY_UNITS 遥感条目一致；其余类型行为不变
  // ADR-018（PRICING-20261020）：参考区间 undefined → null（后端可空字段，区分「未设」）
  const priceRange = { priceMin: form.priceMin ?? null, priceMax: form.priceMax ?? null }
  // ADR-036 §1：新建不传登记时间（传空 → 后端自动取当天）；编辑回传存量值（前端只读展示，后端不锁）
  const payload: AssetInput = isRemote.value
    ? { ...form, ...priceRange, name: form.name, quantity: 1, salePrice: 0, unit: '份（可售明细）', inboundDate: isEdit.value ? form.inboundDate : '' }
    : { ...form, ...priceRange, name: form.name, inboundDate: isEdit.value ? form.inboundDate : '' }
  try {
    if (isEdit.value) {
      await updateAsset(assetId.value, payload)
      ElMessage.success('更新成功')
      router.push(`/assets/${assetId.value}/detail`)
    } else {
      const created = await createAsset(payload)
      ElMessage.success(`创建成功，产品编号 ${created.code}`)
      router.push(`/assets/${created.id}/detail`)
    }
  } catch (e) {
    // FIX-20261022 / BUG-09：后端 400/422（区间 min>max、必填校验等）此前完全静默
    showError(e, '保存失败')
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到产品台账，避免退出应用
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
            {{ isEdit ? '返回产品详情' : '返回产品台账' }}
          </a>
          <h1>{{ isEdit ? '编辑产品' : '登记产品' }}</h1>
          <div class="desc">登记产品名称、板块、数量与单价；产品编号自动生成，金额以元为单位。</div>
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
            <el-form-item label="产品类型" prop="type">
              <!-- 2026-10-20（问题8）：编辑模式禁用（与所属板块一致）——计价模式（pricingMode）由产品类型决定，
                   可改类型会造成计价模式与类型脱钩；后端 type 变更时自动重算 pricingMode（契约 FIX-20261020） -->
              <el-select v-model="form.type" :disabled="isEdit" placeholder="选择产品类型" style="width: 100%;">
                <el-option v-for="t in typeOptions[form.board] || []" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <!-- 1.5 遥感数据容器产品提示（ADR-011：紧跟产品类型下方，三维字段组已移除，按普通父产品登记） -->
            <div v-if="isRemote" class="info-bar">
              <el-icon aria-hidden="true"><InfoFilled /></el-icon>
              <span>遥感数据为容器产品，保存后请在产品详情「可售明细」页签维护 省/精度/月份 明细</span>
            </div>
            <!-- ADR-036 §4：遥感容器——禁用态「可重复售卖」开关（恒关）+ 说明（后端传 true 会 400） -->
            <el-form-item v-if="isRemote" label="可重复售卖">
              <el-switch :model-value="false" disabled />
              <span class="muted" style="font-size: 12px; margin-left: 8px;">容器按可售明细售卖，剩余数量 = 未售明细数</span>
            </el-form-item>
            <el-form-item label="产品名称" prop="name">
              <el-input v-model="form.name" placeholder="如：智元机器人-G1" />
            </el-form-item>
            <el-form-item label="规格说明" prop="spec">
              <el-input v-model="form.spec" placeholder="型号 / 配置 / 数据范围等" />
            </el-form-item>
            <el-form-item label="所在主体" prop="subject">
              <!-- ENTITIES-20261022 / ADR-035：选项来自 bootstrap 镜像 db.entities（label=简称或全称，value=全称，存储口径不变） -->
              <el-select v-model="form.subject" placeholder="选择所在主体" filterable style="width: 100%;">
                <el-option v-for="e in db.entities" :key="e.id" :label="e.short || e.name" :value="e.name" />
              </el-select>
            </el-form-item>
          </div>
        </div>

        <!-- 2. 数量与价格（ADR-011：遥感容器产品整卡隐藏——数量=明细数派生、单价在明细上，提交时兜底） -->
        <div v-if="!isRemote" class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Goods /></el-icon></span>
            <span class="bh-title">数量与价格</span>
            <span class="bh-hint">登记产品总数、计量单位与销售单价（元）</span>
          </div>
          <div class="form-grid">
            <el-form-item label="计量单位" prop="unit">
              <el-input v-model="form.unit" placeholder="套 / 台 / 轨 / 期 / 许可证 / 集群" />
            </el-form-item>
            <el-form-item label="产品总数" prop="quantity">
              <el-input-number v-model="form.quantity" :min="0" :precision="0" :step="1" style="width: 100%;" />
              <!-- ADR-017（2026-10-20）：Token 产品数量口径统一为「可售份数」（与普通产品一致）；
                   「每份内含多少 Token」只写进规格说明，不参与计算 -->
              <div v-if="isAmount" class="muted" style="font-size: 12px; margin-top: 4px;">
                {{ form.quantity }} 份（数量为可售份数；「每份含多少 Token」请写入规格说明）
              </div>
            </el-form-item>
            <!-- ADR-017（2026-10-20）：Token 产品单价口径与普通产品一致（元/份），删除「元/万Token」特判 -->
            <el-form-item label="销售单价（元）" prop="salePrice">
              <!-- FIX-20261022 / BUG-44（§6 硬约束）：金额输入一律 :controls="false"（无步进按钮），数量类保留
                   ADR-048：单价支持最多 6 位小数（formatter 失焦展示「最少两位」，parser 截断到 6 位） -->
              <el-input-number v-model="form.salePrice" :min="0" :controls="false" :formatter="amountInputFormatter" :parser="amountInputParser" style="width: 100%;" />
            </el-form-item>
            <!-- ADR-018（PRICING-20261020）：参考价格区间——元/{unit}，选填（可单边）；
                 ADR-049（2026-10-29）：下单时**只校验下限**（低于下限 400，高于上限不拦截），
                 商务审核改价不受区间约束
                 ADR-036 §3：新建时销售单价填写后自动同步（min=单价、max=单价×1.02）；
                 用户手改（@change）置 touchedMin/touchedMax 后不再自动覆盖（编辑模式不自动同步） -->
            <el-form-item label="参考价格区间（元）">
              <div class="price-range-row">
                <el-input-number v-model="form.priceMin" :min="0" :controls="false" :formatter="amountInputFormatter" :parser="amountInputParser" placeholder="下限（选填）" style="width: 100%;" @change="touchedMin = true" />
                <span class="muted price-range-sep">~</span>
                <el-input-number v-model="form.priceMax" :min="0" :controls="false" :formatter="amountInputFormatter" :parser="amountInputParser" placeholder="上限（选填）" style="width: 100%;" @change="touchedMax = true" />
              </div>
              <div class="muted" style="font-size: 12px; margin-top: 4px;">
                元/{{ form.unit || '单位' }}，选填（可只填一边）；下单时用于校验金额下限（上限不限制，可高于上限成交），未设置则不限制
              </div>
            </el-form-item>
            <!-- ADR-008：包量定价说明（浅蓝提示条） -->
            <div v-if="isAmount" class="info-bar soft">
              Token 产品按包量售卖，下单时以销售金额（元，最多 6 位小数）为准，参考单价不参与计价
            </div>
            <el-form-item label="可重复售卖">
              <el-switch v-model="form.repeatSale" />
              <span class="muted" style="font-size: 12px; margin-left: 8px;">数据类产品建议开启，销售不扣减数量</span>
            </el-form-item>
            <div class="repeat-sale-hint muted">开启后该产品不再受数量限制：售罄产品也可继续下单，销售只计次、不扣减数量</div>
          </div>
        </div>

        <!-- 3. 有效期与附件（FORMS-20261022 / ADR-036 §5：原「长期买断/到期时间」自基本信息移入，
             产品清单自「状态与备注」移入；登记时间仅编辑模式只读展示） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Document /></el-icon></span>
            <span class="bh-title">有效期与附件</span>
          </div>
          <div class="form-grid">
            <el-form-item label="产品有效期">
              <el-switch v-model="form.perpetual" />
              <span class="muted" style="font-size: 12px; margin-left: 8px;">勾选后产品长期有效，无需设置到期时间</span>
            </el-form-item>
            <el-form-item label="到期时间" prop="expiryDate">
              <el-date-picker
                v-model="form.expiryDate"
                type="date"
                value-format="YYYY-MM-DD"
                :disabled="form.perpetual"
                :placeholder="form.perpetual ? '长期有效，无需设置' : '选择到期时间'"
                style="width: 100%;"
              />
            </el-form-item>
            <!-- ADR-036 §1：登记时间——新建不展示（提交传空，后端自动生成当天）；
                 编辑只读展示（文本行；前端约束，后端不锁，API 仍可改） -->
            <el-form-item v-if="isEdit" label="登记时间">
              <span class="readonly-text">{{ form.inboundDate || '-' }}</span>
            </el-form-item>
            <el-form-item label="产品清单">
            <div class="contract-up">
              <input
                ref="contractInputRef"
                type="file"
                accept=".pdf,.docx,.png,.jpg,.jpeg,.gif,.webp,.xlsx"
                style="display: none"
                @change="onContractPicked"
              />
              <template v-if="!form.contractFile">
                <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
                  <span>
                    <el-button :icon="Upload" :loading="uploading" :disabled="!canWrite" @click="pickContract">
                      上传产品清单（PDF / Word / 图片）
                    </el-button>
                  </span>
                </el-tooltip>
                <!-- FIX-20261022-FOLLOWUP：提示文案与后端 /api/upload 白名单（pdf/docx/图片/xlsx，.doc 已移除）对齐 -->
                <span class="muted" style="font-size: 12px; margin-left: 8px;">支持 PDF、Word（.docx）、图片、Excel（.xlsx），≤20MB</span>
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
        </div>

        <!-- 4. 备注（UI-OPT-20261022：「产品状态」展示块已整体移除，卡片仅保留备注） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><CircleCheck /></el-icon></span>
            <span class="bh-title">备注</span>
          </div>
          <el-form-item label="备注" prop="remark">
            <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="填写特殊约定或注意事项" />
          </el-form-item>
        </div>

        <!-- 底部操作区：右对齐，不悬浮 -->
        <div class="bottom-actions">
          <el-button @click="handleCancel">返回</el-button>
          <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
            <span>
              <!-- FIX-20261022 / BUG-36：附件上传中禁用提交，避免「上传未完成就保存」丢附件 -->
              <el-button
                type="primary"
                :icon="CircleCheck"
                :loading="submitting"
                :disabled="!canWrite || uploading"
                @click="handleSubmit"
              >
                {{ isEdit ? '保存修改' : '创建产品' }}
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

/* 遥感提示条（ADR-011：位于基本信息 grid 内、产品类型正下方），下边距与表单行距一致 */
.form-grid .info-bar {
  margin-bottom: 18px;
}

/* ADR-018（PRICING-20261020）：参考价格区间双输入（下限 ~ 上限） */
.price-range-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.price-range-sep {
  flex-shrink: 0;
}

/* 可重复售卖警示行：紧跟开关下方，muted 12px */
.repeat-sale-hint {
  font-size: 12px;
  line-height: 18px;
  margin: -10px 0 18px;
}

/* ADR-036 §1：登记时间只读展示（编辑模式文本行）——行高 32px 与输入控件行盒对齐 */
.readonly-text {
  font-size: 13px;
  line-height: 32px;
  color: var(--text-primary);
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
