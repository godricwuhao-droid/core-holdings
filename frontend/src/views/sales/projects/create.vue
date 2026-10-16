<script setup lang="ts">
/**
 * 销售管理 - 新建 / 编辑销售项目（ADR-007 合同清单结构）
 *
 * 新建：项目级字段（项目名称 / 生态人员 / 商务负责人 / 日期 / 报价 / 已回款 / 备注）
 *   + 「合同清单」区——每客户一份合同卡片（客户 + 合同金额 + 明细行），
 *   提交走 POST /projects 的 contracts 结构（项目 subject/customer/expectedAmount 由后端派生）。
 * 合同内强制同一资产主体（前端预校验 + 后端 400 兜底）；合同一经生成不可增删改明细。
 * 编辑：只改基本信息（合同结构不可改——终止对应合同后重新下单）。
 * 项目状态由合同状态派生，本页不提供状态变更入口。
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
  availableQty,
  boardLabel,
  derivedUnitPrice,
  formatAssetQty,
  formatMoney,
  formatTokens,
  isAmountMode,
  rsItemName,
  // formatWan 已由 formatAssetQty 覆盖（ADR-008 数量口径统一）
  type Asset,
  type Board,
} from '@/types'
import {
  createProject,
  getAsset,
  refresh,
  db,
  updateProject,
  type ContractInput,
  type ProjectInput,
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

// ==================== 项目级字段（合同结构外的基本信息） ====================
const form = reactive({
  name: '',
  rep: '',
  businessOwner: '',
  expectedSignDate: '',
  lastFollowDate: '',
  quoteAmount: 0,
  paidAmount: 0,
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
}

interface ContractDraft {
  customer: string
  contractAmount: number // 元；未手改时随明细合计自动重算
  contractTouched: boolean
  remark: string
  items: ContractDraftItem[]
}

const contracts = reactive<ContractDraft[]>([])

function newItem(): ContractDraftItem {
  return { assetId: null, qty: 0, price: 0, amount: 0, deliveryReq: '' }
}

function addContract() {
  contracts.push({ customer: '', contractAmount: 0, contractTouched: false, remark: '', items: [newItem()] })
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
 *  - amount 模式（包量定价）：合同金额（整数元）为权威输入，单价派生 = 金额 ÷ 数量（元/Token，6 位小数）
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

/** 合同金额默认 = 该合同明细金额合计（元）；用户手改后不再自动覆盖 */
function recalcContractAmount(c: ContractDraft) {
  if (c.contractTouched) return
  c.contractAmount = Math.round(c.items.reduce((s, it) => s + (it.amount || 0), 0) * 100) / 100
}

function contractItemsTotal(c: ContractDraft): number {
  return Math.round(c.items.reduce((s, it) => s + (it.amount || 0), 0) * 100) / 100
}

/**
 * 合同内主体预校验（ADR-007）：选资产时若与本合同内已选资产主体不同 → 提示并回退选择。
 * 后端仍有 400「客户「X」的资产主体不一致，请拆分」兜底。
 */
function onItemAssetChange(c: ContractDraft, it: ContractDraftItem) {
  const a = it.assetId ? getAsset(it.assetId) : undefined
  // ADR-011：遥感数据父资产不可手工加行（明细只经购物车/登记销售进入），toast 拦截并回退选择
  if (a?.type === '遥感数据') {
    ElMessage.info('遥感数据请通过资产列表加购或详情页登记销售')
    it.assetId = null
    it.price = 0
    it.amount = 0
    return
  }
  if (a?.subject) {
    const conflict = c.items.find(
      (o) => o !== it && o.assetId && getAsset(o.assetId)?.subject && getAsset(o.assetId)!.subject !== a.subject,
    )
    if (conflict) {
      ElMessage.warning('该资产主体与本合同内其它资产不一致，请新建一份合同')
      it.assetId = null
      it.price = 0
      it.amount = 0
      return
    }
  }
  // ADR-008：包量定价资产单价为参考值，不作为明细单价预填（单价由合同金额派生）
  if (a && !isAmountMode(a) && !it.price && a.salePrice) it.price = a.salePrice
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

// ==================== 可选资产（与明细行共用） ====================
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

// ==================== 校验与提交 ====================
/** 有效合同：至少含一条已选资产的明细 */
function validContracts(): ContractDraft[] {
  return contracts.filter((c) => c.items.some((it) => it.assetId))
}

/** 创建校验：≥1 份有效合同；每份客户必填；明细数量 > 0 且不超可售上限（可重复售卖不限制） */
function validateContracts(): boolean {
  const valid = validContracts()
  if (!valid.length) {
    ElMessage.warning('请至少添加一份合同并选择资产')
    return false
  }
  for (const c of valid) {
    if (!c.customer.trim()) {
      ElMessage.warning('请为每份合同填写客户')
      return false
    }
    for (const it of c.items) {
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
      // ADR-008：包量定价行合同金额必须为正整数元
      const a = itemAsset(it)
      if (a && isAmountMode(a) && (!it.amount || !Number.isInteger(it.amount) || it.amount <= 0)) {
        ElMessage.warning('合同金额须为整数元')
        return false
      }
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
    quoteAmount: form.quoteAmount,
    contractAmount: 0,
    paidAmount: form.paidAmount,
    expectedSignDate: form.expectedSignDate,
    lastFollowDate: form.lastFollowDate,
    remark: form.remark,
    items: [],
  }
  if (withContracts) base.contracts = buildContractsPayload()
  return base
}

/** 预填：编辑模式带出项目基本信息；从资产「登记销售」跳转时带 assetId（同步资产+单价+可售数量） */
onMounted(async () => {
  await refresh()
  if (isEdit.value) {
    const p = db.projects.find((x) => x.id === projectId.value)
    if (p) {
      // 直达 URL 守卫：存在 delivered 合同 → 不可编辑（后端 400 同文案）；
      // 存量无合同项目沿用旧规则（status != active 不可编辑）。
      const pc = db.contracts.filter((c) => c.projectId === p.id)
      if (pc.some((c) => c.status === 'delivered')) {
        ElMessage.warning('已交付完成的项目不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      if (!pc.length && p.status !== 'active') {
        ElMessage.warning('已完成/已终止项目不可编辑')
        router.replace(`/sales/projects/${p.id}/detail`)
        return
      }
      Object.assign(form, {
        name: p.name,
        rep: p.rep,
        businessOwner: p.businessOwner ?? '',
        expectedSignDate: p.expectedSignDate,
        lastFollowDate: p.lastFollowDate,
        quoteAmount: p.quoteAmount,
        paidAmount: p.paidAmount,
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
  const assetId = Number(route.query.assetId)
  if (assetId) {
    const a = getAsset(assetId)
    const it: ContractDraftItem = {
      assetId,
      // 可重复售卖 availableQty 为 null，预填默认 1
      qty: a ? (availableQty(a) ?? 1) : 1,
      // ADR-008：包量定价资产单价为参考值不预填，合同金额待填（整数元）
      price: a && isAmountMode(a) ? 0 : a?.salePrice || 0,
      amount: 0,
      deliveryReq: '',
    }
    contracts[0].items[0] = it
    calcItemAmount(contracts[0], it)
  }
})

/** 保存草稿：仅要求项目名称，后端强制状态为「进行中」 */
async function saveDraft() {
  if (!form.name.trim()) {
    ElMessage.warning('请先填写项目名称再保存草稿')
    return
  }
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, buildPayload(false))
    } else {
      await createProject(buildPayload(true))
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
  if (!isEdit.value && !validateContracts()) return
  submitting.value = true
  try {
    if (isEdit.value) {
      await updateProject(projectId.value, buildPayload(false))
      ElMessage.success('更新成功')
    } else {
      const created = await createProject(buildPayload(true))
      ElMessage.success(`创建成功，项目编号 ${created.code}（${created.contractCount ?? validContracts().length} 份合同）`)
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
                ? '仅可修改项目基本信息；合同与明细在创建后不可修改。'
                : '每客户一份合同，合同内选择待售资产，销售金额按 数量 × 单价 自动计算；包量定价（Token）资产以合同金额（整数元）为准。'
            }}
          </div>
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
            <el-form-item label="项目名称" prop="name">
              <el-input v-model="form.name" placeholder="默认跟随首份合同客户名，可修改" @input="nameTouched = true" />
            </el-form-item>
          </div>
        </div>

        <!-- ② 合同清单（仅新建模式；编辑模式合同结构不可改） -->
        <div v-if="!isEdit" class="form-card asset-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Link /></el-icon></span>
            <div>
              <div class="bh-title">合同清单</div>
              <div class="bh-sub">每客户一份合同（合同内资产须同一主体）；合同金额默认 = 明细合计，可手改。跨主体的资产请新建一份合同。</div>
            </div>
            <span class="bh-hint">
              <el-button plain size="small" :icon="Plus" @click="addContract">添加合同</el-button>
            </span>
          </div>

          <div v-for="(c, ci) in contracts" :key="ci" class="contract-card">
            <div class="contract-head">
              <span class="contract-title">
                合同 {{ ci + 1 }}
                <template v-if="c.customer"> · {{ c.customer }}</template>
                <template v-else class="muted"> · 客户未填写</template>
              </span>
              <el-button link type="danger" size="small" :icon="Delete" @click="removeContract(ci)">删除合同</el-button>
            </div>

            <div class="contract-fields">
              <div class="cf-item">
                <span class="cf-label">客户 <i class="req">*</i></span>
                <el-input v-model="c.customer" placeholder="填写本合同客户名称" style="width: 220px;" />
              </div>
              <div class="cf-item">
                <span class="cf-label">合同金额（元）</span>
                <el-input-number
                  v-model="c.contractAmount"
                  :min="0"
                  :precision="2"
                  :controls="false"
                  placeholder="默认=明细合计"
                  style="width: 180px;"
                  @update:model-value="() => { c.contractTouched = true }"
                />
              </div>
            </div>

            <div class="items-wrap">
              <el-table :data="c.items" border>
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
                      @change="onItemAssetChange(c, row)"
                    />
                    <div v-if="itemAsset(row)" class="asset-meta">
                      <span class="muted" style="font-size: 12px;">
                        {{ itemAsset(row)!.code }} · {{ itemAsset(row)!.type }}
                      </span>
                      <span class="stock-pill" :class="itemAsset(row)!.repeatSale ? 'repeat' : 'ok'">
                        <span class="dot" aria-hidden="true">{{ itemAsset(row)!.repeatSale ? '↻' : '●' }}</span>
                        {{ itemAsset(row)!.repeatSale ? '可重复售卖' : `库存可售 ${formatAssetQty(itemAsset(row)!, availableQty(itemAsset(row)!))} ${itemAsset(row)!.unit}` }}
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
                    <!-- ADR-008：Token 资产数量按 formatTokens 展示（原数提交） -->
                    <div v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)" class="muted item-qty-hint">
                      {{ formatTokens(row.qty) }} Token
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="单价（元）" width="180" align="center">
                  <template #default="{ row }">
                    <!-- ADR-008：包量定价行单价为派生参考展示（金额÷数量÷1e4，保留 4 位 + 「约」） -->
                    <span v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)" class="muted">
                      {{ derivedUnitPrice(row.amount, row.qty) }}
                    </span>
                    <el-input-number
                      v-else
                      v-model="row.price"
                      :min="0"
                      :precision="2"
                      controls-position="right"
                      style="width: 100%;"
                      @change="calcItemAmount(c, row)"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="金额" width="190" align="right">
                  <template #default="{ row }">
                    <!-- ADR-008：包量定价行合同金额（整数元）为权威输入；unit 模式保持只读自动计算 -->
                    <el-input
                      v-if="itemAsset(row) && isAmountMode(itemAsset(row)!)"
                      :model-value="row.amount || ''"
                      placeholder="整数元"
                      size="small"
                      @input="onItemAmountInput(row, $event)"
                      @change="calcItemAmount(c, row)"
                    />
                    <span v-else class="item-amount">{{ formatMoney(row.amount) }}</span>
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

          <el-empty v-if="!contracts.length" description="暂无合同，点击右上角「添加合同」" :image-size="60" />
        </div>

        <!-- 编辑模式：合同结构不可改的说明 -->
        <el-alert
          v-else
          class="edit-contract-tip"
          title="合同与明细在创建后不可修改，如需调整请终止对应合同后重新下单"
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
              <div class="bh-sub">生态人员、商务负责人、日期、报价 / 已回款金额与备注等可选补充；项目状态由合同状态自动派生。</div>
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
                <el-select
                  v-model="form.rep"
                  filterable
                  allow-create
                  placeholder="选择生态人员"
                  style="width: 100%;"
                >
                  <el-option v-for="r in db.reps" :key="r.id" :label="r.name" :value="r.name" />
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

            <div class="amount-grid">
              <div class="amount-panel">
                <div class="ap-label">报价金额</div>
                <el-input-number
                  v-model="form.quoteAmount"
                  :min="0"
                  :precision="2"
                  :controls="false"
                  placeholder="未报价"
                />
                <div class="ap-foot">元</div>
              </div>
              <div class="amount-panel">
                <div class="ap-label">已回款金额</div>
                <el-input-number
                  v-model="form.paidAmount"
                  :min="0"
                  :precision="2"
                  :controls="false"
                  placeholder="未回款"
                />
                <div class="ap-foot">元</div>
              </div>
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
            生态人员、商务负责人、签约 / 跟进日期、报价 / 已回款金额、备注等（非必填，默认收起）
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
                <el-button type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canWrite" @click="handleSubmit">
                  保存修改
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </div>
      </el-form>
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

/* 合同清单区块：细边框强调（与资产关联区块同款） */
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

.total-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
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
