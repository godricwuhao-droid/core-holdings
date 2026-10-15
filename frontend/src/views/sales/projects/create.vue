<script setup lang="ts">
/**
 * 销售管理 - 新建 / 编辑销售项目（精简版）
 *
 * 聚焦核心信息：客户 + 销售明细（资产 / 数量 / 单价 / 金额）
 * 次要字段（销售人员 / 行业 / 主体 / 签约·跟进日期 / 预计销售·报价·合同·已回款金额 / 备注）
 *   折叠到「更多设置」，默认收起；数据层提交上述字段（不含 status，后端强制 active），
 *   不影响销售项目列表、状态流转、库存锁定与回款逻辑。
 * 项目状态不在表单内维护：新建恒为「进行中」，编辑模式通过底部「修改状态」流转。
 * 从资产详情「登记销售」跳转时，自动同步带入 资产 + 单价 + 可售数量。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  CircleCheck,
  Delete,
  Folder,
  Link,
  Plus,
  Setting,
} from '@element-plus/icons-vue'
import {
  ENTITIES,
  PROJECT_STATUS,
  availableQty,
  boardLabel,
  formatMoney,
  formatWan,
  type Asset,
  type Board,
  type ProjectStatus,
} from '@/types'
import {
  changeProjectStatus,
  createProject,
  getAsset,
  refresh,
  db,
  updateProject,
  type ProjectInput,
  type ProjectItemInput,
} from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

const route = useRoute()
const router = useRouter()

const isEdit = computed(() => route.path.endsWith('edit'))
const projectId = computed(() => Number(route.params.id))

const formRef = ref()
const submitting = ref(false)
/** 「更多设置」折叠：默认收起，需要补充时展开 */
const showMore = ref(false)

const form = reactive({
  name: '',
  customer: '',
  industry: '',
  rep: '',
  subject: '',
  status: 'active' as ProjectStatus,
  expectedAmount: 0,
  quoteAmount: 0,
  contractAmount: 0,
  paidAmount: 0,
  expectedSignDate: '',
  lastFollowDate: '',
  remark: '',
})

const items = reactive<ProjectItemInput[]>([])

const rules = {
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  customer: [{ required: true, message: '请输入客户名称', trigger: 'blur' }],
}

/** 可选资产：仅展示当前有可售库存的资产（可重复售卖，或可售数量 > 0；无库存的不再进入下拉） */
const sellableAssets = computed(() =>
  db.assets.filter(
    (a) => a.board !== 'compute' && (a.repeatSale || (availableQty(a) ?? 0) > 0),
  ),
)

/** 资产树：按板块分组（卫星服务下分 Token / 数据两级），供 el-tree-select 树状筛选与搜索 */
const assetTreeData = computed(() => {
  const boards: Board[] = ['embodied', 'satellite', 'software', 'hardware']
  const leaf = (a: Asset) => ({ id: a.id, label: `${a.name}（${a.code}）` })
  return boards
    .map((board) => {
      const assets = sellableAssets.value.filter((a) => a.board === board)
      const children =
        board === 'satellite'
          ? (['卫星Token', '卫星数据'] as const)
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

function onItemAssetChange(it: ProjectItemInput) {
  const a = it.assetId ? getAsset(it.assetId) : undefined
  if (a && !it.price && a.salePrice) it.price = a.salePrice
  calcItemAmount(it)
}

/** 销售金额 = 数量 × 单价（万元，保留 4 位小数 = 元级精度），空/非法按 0 */
function calcItemAmount(it: ProjectItemInput) {
  it.amount = Math.round((it.qty || 0) * (it.price || 0) * 10000) / 10000
}

function addItem() {
  items.push({ assetId: null, qty: 0, price: 0, amount: 0, deliveryReq: '' })
}

function removeItem(idx: number) {
  items.splice(idx, 1)
}

function itemAsset(it: ProjectItemInput) {
  return it.assetId ? getAsset(it.assetId) : undefined
}

/** 明细数量上限：非可重复售卖按可售数量限制，可重复售卖不限制 */
function itemMax(it: ProjectItemInput): number | undefined {
  const a = itemAsset(it)
  if (!a || a.repeatSale) return undefined
  return availableQty(a) ?? 0
}

/** 用户是否手改过「预计销售金额」；未手改时自动跟随明细合计 */
const expectedTouched = ref(false)

function buildPayload(): ProjectInput {
  return {
    name: form.name,
    customer: form.customer,
    industry: form.industry,
    rep: form.rep,
    subject: form.subject,
    expectedAmount: form.expectedAmount,
    quoteAmount: form.quoteAmount,
    contractAmount: form.contractAmount,
    paidAmount: form.paidAmount,
    expectedSignDate: form.expectedSignDate,
    lastFollowDate: form.lastFollowDate,
    remark: form.remark,
    items: validItems(),
  }
}

/** 明细数量校验：> 0 且不超过可售上限（可重复售卖不限制） */
function validateItems(): boolean {
  for (const it of validItems()) {
    if (!it.assetId) continue
    if (!it.qty || it.qty <= 0) {
      ElMessage.warning('销售明细数量必须大于 0')
      return false
    }
    const max = itemMax(it)
    if (max !== undefined && it.qty > max) {
      ElMessage.warning(`「${itemAsset(it)?.name ?? '资产'}」本单数量超出可售上限（可售 ${max}）`)
      return false
    }
  }
  return true
}

/** 预填：编辑模式带出项目；从资产「登记销售」跳转时带 assetId（同步资产+单价+可售数量） */
onMounted(async () => {
  await refresh()
  if (isEdit.value) {
    const p = db.projects.find((x) => x.id === projectId.value)
    if (p) {
      // 直达 URL 守卫：仅「进行中」项目可编辑（列表/详情已禁用编辑入口，此处兜底防止绕过）。
      // 已完成/已终止项目直接拦截并跳转详情页，不进入表单（避免填完保存才被后端拦截）。
      if (p.status !== 'active') {
        ElMessage.warning('已完成/已终止项目不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      Object.assign(form, {
        name: p.name,
        customer: p.customer,
        industry: p.industry,
        rep: p.rep,
        subject: p.subject,
        status: p.status,
        expectedAmount: p.expectedAmount,
        quoteAmount: p.quoteAmount,
        contractAmount: p.contractAmount,
        paidAmount: p.paidAmount,
        expectedSignDate: p.expectedSignDate,
        lastFollowDate: p.lastFollowDate,
        remark: p.remark,
      })
      p.items.forEach((it) =>
        items.push({
          assetId: it.assetId,
          qty: it.qty,
          price: it.price,
          amount: it.amount,
          deliveryReq: it.deliveryReq,
        }),
      )
      if (items.length === 0) addItem()
      // 编辑已有项目：保留原「预计销售金额」，不被明细合计覆盖
      expectedTouched.value = true
      return
    }
  }
  const assetId = Number(route.query.assetId)
  if (assetId) {
    const a = getAsset(assetId)
    items.push({
      assetId,
      // 可重复售卖 availableQty 为 null，预填默认 1
      qty: a ? (availableQty(a) ?? 1) : 1,
      price: a?.salePrice || 0,
      amount: 0,
      deliveryReq: '',
    })
    calcItemAmount(items[0])
  } else {
    addItem()
  }
})

function validItems() {
  return items.filter((it) => it.assetId || it.deliveryReq)
}

/** 保存草稿：仅要求项目名称，后端强制状态为「进行中」 */
async function saveDraft() {
  if (!form.name.trim()) {
    ElMessage.warning('请先填写项目名称再保存草稿')
    return
  }
  submitting.value = true
  const payload: ProjectInput = buildPayload()
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, payload)
    } else {
      await createProject(payload)
    }
    ElMessage.success('已保存草稿，项目状态为「进行中」')
    router.push('/sales/projects')
  } finally {
    submitting.value = false
  }
}

async function handleSubmit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  if (!validateItems()) return
  submitting.value = true
  const payload: ProjectInput = buildPayload()
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, payload)
      ElMessage.success('更新成功，锁定数量已重新计算')
    } else {
      const created = await createProject(payload)
      ElMessage.success(`创建成功，项目编号 ${created.code}`)
    }
    router.push('/sales/projects')
  } finally {
    submitting.value = false
  }
}

function handleCancel() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到销售项目列表，避免退出应用
  if (window.history.state?.back) router.back()
  else router.push('/sales/projects')
}

// ============================================================
// 状态流转（编辑模式）：复用销售项目列表的状态机与库存联动
// ============================================================
const currentProject = computed(() =>
  isEdit.value ? db.projects.find((x) => x.id === projectId.value) ?? null : null,
)

const statusDialog = reactive({
  visible: false,
  status: '' as ProjectStatus | '',
  reason: '',
  submitting: false,
})

function openStatusDialog() {
  const p = currentProject.value
  if (!p) return
  statusDialog.status = p.status
  statusDialog.reason = ''
  statusDialog.visible = true
}

/** 状态机：进行中→已完成 / 已终止；已完成→已终止；已终止为终点不可再变 */
function canGo(from: ProjectStatus, to: ProjectStatus): boolean {
  if (from === to) return true
  if (from === 'terminated') return false
  if (from === 'active') return to === 'delivered' || to === 'terminated'
  if (from === 'delivered') return to === 'terminated'
  return false
}

async function confirmStatus() {
  const p = currentProject.value
  if (!p || !statusDialog.status || statusDialog.status === p.status) {
    statusDialog.visible = false
    return
  }
  statusDialog.submitting = true
  try {
    await changeProjectStatus(projectId.value, statusDialog.status, statusDialog.reason)
    form.status = statusDialog.status
    ElMessage.success(
      statusDialog.status === 'delivered'
        ? '已标记已完成，资产库存与出库记录已自动更新'
        : '状态已更新',
    )
    statusDialog.visible = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '状态变更失败')
  } finally {
    statusDialog.submitting = false
  }
}

const itemsTotal = computed(() => items.reduce((s, it) => s + (it.amount || 0), 0))

/** 未手改「预计销售金额」时，自动取销售明细金额合计（万元）作为默认值 */
watch(itemsTotal, (v) => {
  if (!expectedTouched.value) form.expectedAmount = Math.round(v * 10000) / 10000
})
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
          <div class="desc">填写客户与待售资产，销售金额按 数量 × 单价 自动计算。</div>
        </div>
        <div class="head-actions" v-if="!isEdit">
          <span class="draft-tag">◌ 草稿未保存</span>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="create-form">
        <!-- ① 基本信息 -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Folder /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">带 * 为必填</span>
          </div>
          <div class="form-grid-2">
            <el-form-item label="客户名称" prop="customer">
              <el-input v-model="form.customer" placeholder="填写客户名称" />
            </el-form-item>
            <el-form-item label="项目名称" prop="name">
              <el-input v-model="form.name" placeholder="如：智元机器人示范项目" />
            </el-form-item>
          </div>
        </div>

        <!-- ② 销售明细（核心，视觉重点） -->
        <div class="form-card asset-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Link /></el-icon></span>
            <div>
              <div class="bh-title">销售明细</div>
              <div class="bh-sub">选择待售资产，销售金额 = 数量 × 单价，自动计算。</div>
            </div>
            <span class="bh-hint">
              <el-button plain size="small" :icon="Plus" @click="addItem">添加资产</el-button>
            </span>
          </div>

          <div class="items-wrap">
            <el-table :data="items" border>
              <el-table-column label="资产" min-width="280">
                <template #default="{ row }">
                  <el-tree-select
                    v-model="row.assetId"
                    :data="assetTreeData"
                    :props="{ label: 'label', children: 'children' }"
                    node-key="id"
                    check-strictly
                    filterable
                    :render-after-expand="false"
                    placeholder="选择待售资产"
                    style="width: 100%;"
                    @change="onItemAssetChange(row)"
                  />
                  <div v-if="itemAsset(row)" class="asset-meta">
                    <span class="muted" style="font-size: 12px;">
                      {{ itemAsset(row)!.code }} · {{ itemAsset(row)!.type }}
                    </span>
                    <span class="stock-pill" :class="itemAsset(row)!.repeatSale ? 'repeat' : 'ok'">
                      <span class="dot" aria-hidden="true">{{ itemAsset(row)!.repeatSale ? '↻' : '●' }}</span>
                      {{ itemAsset(row)!.repeatSale ? '可重复售卖' : `库存可售 ${formatWan(availableQty(itemAsset(row)!))} ${itemAsset(row)!.unit}` }}
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
              <el-table-column label="数量" width="130" align="center">
                <template #default="{ row }">
                  <el-input-number
                    v-model="row.qty"
                    :min="0"
                    :max="itemMax(row)"
                    :precision="0"
                    :step="1"
                    controls-position="right"
                    style="width: 100%;"
                    @change="calcItemAmount(row)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="单价（元）" width="170" align="center">
                <template #default="{ row }">
                  <el-input-number
                    :model-value="(row.price || 0) * 10000"
                    :min="0"
                    :precision="0"
                    controls-position="right"
                    style="width: 100%;"
                    @update:model-value="(v) => { row.price = (v || 0) / 10000; calcItemAmount(row) }"
                  />
                </template>
              </el-table-column>
              <el-table-column label="金额" width="180" align="right">
                <template #default="{ row }">
                  <span class="item-amount">{{ formatMoney(row.amount) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="" width="60" align="center">
                <template #default="{ $index }">
                  <el-button link type="danger" :icon="Delete" @click="removeItem($index)" />
                </template>
              </el-table-column>
            </el-table>
          </div>

          <div class="items-total">
            <span class="muted" style="font-size: 13px;">销售金额合计</span>
            <span class="total-value">{{ formatMoney(itemsTotal) }}</span>
          </div>
        </div>

        <!-- ③ 更多设置（默认收起，展开补填次要字段） -->
        <div class="form-card more-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Setting /></el-icon></span>
            <div>
              <div class="bh-title">更多设置</div>
              <div class="bh-sub">销售人员、行业、主体、日期、各金额口径与备注等可选补充；项目状态由系统统一维护（新建即为「进行中」）。</div>
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
              <el-form-item label="销售人员">
                <el-select
                  v-model="form.rep"
                  filterable
                  allow-create
                  placeholder="选择销售人员"
                  style="width: 100%;"
                >
                  <el-option v-for="r in db.reps" :key="r.id" :label="r.name" :value="r.name" />
                </el-select>
              </el-form-item>
              <el-form-item label="行业">
                <el-input v-model="form.industry" placeholder="如：智能制造" />
              </el-form-item>
              <el-form-item label="所属主体">
                <el-select v-model="form.subject" filterable placeholder="选择公司所属主体" style="width: 100%;">
                  <el-option v-for="e in ENTITIES" :key="e.name" :label="e.name" :value="e.name" />
                </el-select>
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

            <div class="amount-grid">
              <div class="amount-panel">
                <div class="ap-label">预计销售金额</div>
                <el-input-number
                  :model-value="(form.expectedAmount || 0) * 10000"
                  :min="0"
                  :precision="0"
                  :controls="false"
                  placeholder="按明细自动带出"
                  @update:model-value="(v) => { expectedTouched = true; form.expectedAmount = (v || 0) / 10000 }"
                />
                <div class="ap-foot">元</div>
              </div>
              <div class="amount-panel">
                <div class="ap-label">报价金额</div>
                <el-input-number
                  :model-value="(form.quoteAmount || 0) * 10000"
                  :min="0"
                  :precision="0"
                  :controls="false"
                  placeholder="未报价"
                  @update:model-value="(v) => { form.quoteAmount = (v || 0) / 10000 }"
                />
                <div class="ap-foot">元</div>
              </div>
              <div class="amount-panel">
                <div class="ap-label">合同金额</div>
                <el-input-number
                  :model-value="(form.contractAmount || 0) * 10000"
                  :min="0"
                  :precision="0"
                  :controls="false"
                  placeholder="未签约"
                  @update:model-value="(v) => { form.contractAmount = (v || 0) / 10000 }"
                />
                <div class="ap-foot">元</div>
              </div>
              <div class="amount-panel">
                <div class="ap-label">已回款金额</div>
                <el-input-number
                  :model-value="(form.paidAmount || 0) * 10000"
                  :min="0"
                  :precision="0"
                  :controls="false"
                  placeholder="未回款"
                  @update:model-value="(v) => { form.paidAmount = (v || 0) / 10000 }"
                />
                <div class="ap-foot">元</div>
              </div>
            </div>
            <div class="muted" style="font-size: 12px; margin-top: 8px;">
              预计销售金额默认取「销售明细金额合计」，手动修改后不再自动覆盖。
            </div>

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
            行业、主体、签约 / 跟进日期、预计销售 / 报价 / 合同 / 已回款金额、备注等（非必填，默认收起）
          </div>
        </div>

        <!-- 底部操作区：右对齐，不悬浮 -->
        <div class="bottom-actions">
          <template v-if="!isEdit">
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button plain :loading="submitting" :disabled="!canWrite" @click="saveDraft">保存草稿</el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                  创建项目
                </el-button>
              </span>
            </el-tooltip>
          </template>
          <template v-else>
            <el-button @click="handleCancel">返回</el-button>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="warning" plain :disabled="!canWrite" @click="openStatusDialog">修改状态</el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                  保存修改
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </div>
      </el-form>

      <!-- 状态流转对话框（编辑模式） -->
      <el-dialog v-model="statusDialog.visible" title="项目状态流转" width="560px" :close-on-click-modal="false">
        <p class="flow-hint">
          当前项目：<b>{{ currentProject?.name }}</b>（{{ currentProject?.code }}）
        </p>
        <p class="flow-path muted">
          常规流转（仅可前进，不可回退）：进行中 → 已完成 → 已终止
        </p>
        <el-radio-group v-model="statusDialog.status" class="status-radios">
          <el-radio
            v-for="(s, k) in PROJECT_STATUS"
            :key="k"
            :value="k"
            :disabled="currentProject ? !canGo(currentProject.status, k as ProjectStatus) : false"
          >
            <el-tag :type="s.tag" size="small" effect="light">{{ s.label }}</el-tag>
          </el-radio>
        </el-radio-group>
        <p v-if="currentProject?.status === 'terminated'" class="muted" style="font-size: 12px; margin-top: 8px;">
          项目已终止，状态不可再变更（审计要求）。
        </p>
        <el-input
          v-model="statusDialog.reason"
          type="textarea"
          :rows="2"
          placeholder="备注/原因（选填）"
          style="margin-top: 14px;"
        />
        <el-alert
          v-if="statusDialog.status === 'delivered'"
          class="flow-tip"
          title="已完成将自动：扣减锁定数量、增加已售数量/累计销售金额，并生成出库记录。"
          type="success"
          :closable="false"
        />
        <el-alert
          v-if="statusDialog.status === 'terminated'"
          class="flow-tip"
          title="已终止将自动释放锁定资产，并撤销已出库记录（回退数量与累计销售金额）。"
          type="warning"
          :closable="false"
        />
        <template #footer>
          <el-button @click="statusDialog.visible = false">取消</el-button>
          <el-button type="primary" :loading="statusDialog.submitting" @click="confirmStatus">确定</el-button>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<style scoped>
/* 状态流转对话框（编辑模式） */
.status-radios {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  margin-top: 10px;
}
.flow-hint {
  font-size: 13px;
  color: var(--text-secondary);
}
.flow-path {
  font-size: 12px;
  margin-top: 4px;
}
.flow-tip {
  margin-top: 12px;
}
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

/* 资产关联区块：细边框强调（不用深色背景） */
.asset-card {
  border-color: #cfe0f5;
}

/* 关联资产首列：名称下方 code·分类 + 库存状态胶囊 */
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

/* 销售金额：只读自动计算 */
.item-amount {
  font-weight: 600;
  color: var(--text-primary);
}

/* 合计：弱化标签、强调金额 */
.items-total {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  align-items: baseline;
  gap: 8px;
}
.items-total .total-value {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 资产表格可横向滚动，最小宽度 720px */
.items-wrap {
  overflow-x: auto;
}
.items-wrap :deep(.el-table) {
  min-width: 720px;
}
/* 单元格顶部对齐：资产列下方 meta 撑高行时，右侧数量/单价/金额输入框仍与首列顶部对齐
   （vertical-align 只对 table-cell 生效，须加在 td 上而非块级 .cell） */
.items-wrap :deep(.el-table__body td.el-table__cell) {
  vertical-align: top;
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
