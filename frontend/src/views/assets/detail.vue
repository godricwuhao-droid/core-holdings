<script setup lang="ts">
/**
 * 资产管理 - 详情页
 *
 * 按《资产详情页 UI 开发提示词》实现：
 * ← 返回 → 大标题 + 元信息行 + [编辑资产] [登记销售] [更多▾]（删除收入菜单）
 * → 五页签：基本信息(左基础资料 1 列 + 右库存与归属含可售数量) / 交付物
 *   / 销售关联(空状态) / 出入库流水(时间线) / 操作记录
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  Box,
  CircleCheck,
  Delete,
  Edit,
  InfoFilled,
  Key,
  Link,
  Operation,
  Plus,
  Tickets,
} from '@element-plus/icons-vue'
import {
  ASSET_STOCK_STATE,
  DELIVERABLE_CATEGORIES,
  FLOW_TYPES,
  PROJECT_STATUS,
  assetStockState,
  availableQty,
  boardLabel,
  entityShort,
  expiryText,
  formatAssetQty,
  formatMoney,
  isAmountMode,
  noSellableStock,
  tagInfo,
  rsItemName,
  type AssetFlow,
  type DeliverableCategory,
  type FlowType,
  type Project,
  type ProjectItem,
  type RsItem,
} from '@/types'
import {
  addAssetDeliverable,
  addRsItem,
  assetFlows,
  createSaleOrder,
  deleteAsset,
  deleteRsItem,
  getAsset,
  getAssetDeliverables,
  projectItemsOfAsset,
  refresh,
  rsItemsOfAsset,
  translateFileNames,
  updateAssetDeliverable,
  updateRsItem,
  db,
  type OrderFields,
  type RsItemInput,
} from '@/api'
import SalesOrderDialog from '@/components/SalesOrderDialog.vue'
import RsItemPicker from '@/components/RsItemPicker.vue'
import type { OrderItem } from '@/components/SalesOrderDialog.vue'
import { PROVINCES } from '@/constants'
import { canWrite, isViewer, READONLY_TIP } from '@/auth'

const route = useRoute()
const router = useRouter()
const assetId = computed(() => Number(route.params.id))

const asset = computed(() => getAsset(assetId.value))

const salesLinks = computed(() =>
  asset.value ? projectItemsOfAsset(asset.value.id) : [],
)
const flows = computed(() => (asset.value ? assetFlows(asset.value.id) : []))
const opLogs = computed(() =>
  asset.value
    ? db.logs.filter((l) => l.target === 'asset' && l.assetId === asset.value!.id)
    : [],
)

/** 状态点胶囊：库存可售绿 / 暂无库存红（可重复售卖归入库存可售） */
function statusPill(): { cls: 'ok' | 'off'; dot: string } {
  const s = assetStockState(asset.value!)
  return s === 'in_stock' ? { cls: 'ok', dot: '●' } : { cls: 'off', dot: '◌' }
}

function isWipBoard() {
  return asset.value?.board === 'compute'
}

// ============================================================
// 顶部动作
// ============================================================
// ---- 登记销售：admin/editor 走销售模块创建页（原行为）；viewer（生态人员）无销售模块入口，
//      直接打开下单对话框（与资产列表抽屉「销售」同一表单，单资产 + 数量） ----
const saleItem = ref<OrderItem | null>(null)
const saleVisible = ref(false)
const saleLoading = ref(false)
/** ADR-011：遥感数据「登记销售」勾选的明细行（订单级客户 + N 行明细，行带 itemId、qty=1） */
const rsSaleItems = ref<OrderItem[]>([])
const saleItems = computed<OrderItem[]>(() =>
  rsSaleItems.value.length ? rsSaleItems.value : saleItem.value ? [saleItem.value] : [],
)

// ---- ADR-011：遥感数据明细选择弹窗（登记销售入口；加购统一走资产列表）----
const rsPickerVisible = ref(false)

function onRsPickerConfirm(items: RsItem[]) {
  const a = asset.value
  if (!a) return
  rsSaleItems.value = items.map((it) => ({ asset: a, qty: 1, amount: it.price, itemId: it.id }))
  saleItem.value = null
  saleVisible.value = true
}

function goRegisterSale() {
  if (!asset.value) return
  // ADR-011：遥感数据父资产 → 明细选择弹窗（父资产本身不可直接下单，库存校验不适用）
  if (asset.value.type === '遥感数据') {
    rsPickerVisible.value = true
    return
  }
  if (noSellableStock(asset.value)) {
    ElMessage.warning('该资产当前无可售库存（可售数量为 0），无法登记销售。请待库存释放（取消锁定或补充入库）后再操作。')
    return
  }
  if (isViewer.value) {
    rsSaleItems.value = []
    saleItem.value = { asset: asset.value, qty: 1 }
    saleVisible.value = true
    return
  }
  router.push({ path: '/sales/projects/create', query: { assetId: String(asset.value.id) } })
}

async function onSaleSubmit(payload: { fields: OrderFields; items: { assetId: number; qty: number; amount?: number }[] }) {
  saleLoading.value = true
  try {
    const p = await createSaleOrder({ ...payload.fields, items: payload.items })
    saleVisible.value = false
    ElMessage.success(`下单成功，已生成销售项目 ${p.code}（进行中）`)
    await refresh(true)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下单失败')
    await refresh(true)
  } finally {
    saleLoading.value = false
  }
}

/** 编辑资产：无可售库存时提示（不阻止，允许补入库） */
function goEditAsset() {
  if (!asset.value) return
  if (noSellableStock(asset.value)) {
    ElMessage.warning('该资产当前无可售库存（可售数量为 0）。可继续编辑补入库或核对锁定 / 售出情况。')
  }
  router.push(`/assets/${asset.value.id}/edit`)
}

async function copyCode() {
  if (!asset.value) return
  try {
    await navigator.clipboard.writeText(asset.value.code)
    ElMessage.success('资产编号已复制')
  } catch {
    ElMessage.info(`资产编号：${asset.value.code}`)
  }
}

// ============================================================
// 删除
// ============================================================
async function handleDelete() {
  if (!asset.value) return
  try {
    await ElMessageBox.confirm(
      `确定删除资产「${asset.value.name}」（${asset.value.code}）吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteAsset(asset.value.id)
    ElMessage.success('删除成功')
    router.push(`/assets/${asset.value.board}`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ============================================================
// 页签
// ============================================================
const activeTab = ref('info')
onMounted(() => {
  const t = route.query.tab
  if (t === 'deliverables') activeTab.value = 'deliverables'
})

// ============================================================
// 出入库流水：筛选 + 时间线
// ============================================================
type FlowGroup = 'all' | 'purchase_in' | 'project_lock' | 'sale_out' | 'adjust'
const flowFilter = ref<FlowGroup>('all')
const filteredFlows = computed(() => {
  const list = [...flows.value].reverse()
  if (flowFilter.value === 'all') return list
  if (flowFilter.value === 'adjust') {
    return list.filter((f) => f.type === 'cancel_release' || f.type === 'manual_adjust')
  }
  return list.filter((f) => f.type === flowFilter.value)
})

/** 流水类型 → 时间线色点（蓝/绿/灰蓝/橙） */
const FLOW_CLS: Record<FlowType, string> = {
  purchase_in: 'blue',
  project_lock: 'blue',
  sale_out: 'green',
  cancel_release: 'gray',
  manual_adjust: 'orange',
}

// ============================================================
// 交付物
// ============================================================
const deliverables = computed(() =>
  asset.value ? getAssetDeliverables(asset.value.id) : [],
)
const catFilter = ref<DeliverableCategory | ''>('')
const filteredDels = computed(() =>
  deliverables.value.filter((d) => !catFilter.value || d.category === catFilter.value),
)
const delStats = computed(() => {
  const list = deliverables.value
  const ready = list.filter((d) => d.status === 'ready').length
  const latest = [...list].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))[0]
  return { total: list.length, ready, latest: latest?.updatedAt ?? '-' }
})

/** 分类 → 图标与底色（浅蓝/浅绿/浅紫蓝/中性） */
const CAT_ICON: Record<DeliverableCategory, { icon: typeof Box; cls: string }> = {
  install: { icon: Box, cls: 'blue' },
  license: { icon: Key, cls: 'green' },
  feature: { icon: Tickets, cls: 'purple' },
  accept: { icon: CircleCheck, cls: 'neutral' },
}

/** 默认交付范围（右侧说明栏） */
const defaultScope = computed(() =>
  (Object.keys(DELIVERABLE_CATEGORIES) as DeliverableCategory[])
    .map((c) => ({
      label: DELIVERABLE_CATEGORIES[c].label,
      names: deliverables.value.filter((d) => d.category === c).map((d) => d.name),
    }))
    .filter((x) => x.names.length > 0),
)

/** 交付三步（右侧说明栏时间线） */
const DELIVERY_STEPS = [
  { t: '项目关联', d: '生态人员在销售项目中选择资产及数量。' },
  { t: '选择交付包', d: '交付人员确认本次需使用的交付物版本。' },
  { t: '完成交付', d: '记录序列号、客户、日期和经办人，生成交付凭证。' },
]

// ---- 交付物操作 ----
const delCreate = reactive({
  visible: false,
  form: {
    name: '',
    category: 'install' as DeliverableCategory,
    required: true,
    note: '',
  },
})

function openDelCreate() {
  delCreate.form = { name: '', category: 'install', required: true, note: '' }
  delCreate.visible = true
}

async function confirmDel() {
  if (!asset.value) return
  if (!delCreate.form.name.trim()) {
    ElMessage.warning('请输入交付物名称')
    return
  }
  await addAssetDeliverable(asset.value.id, { ...delCreate.form })
  ElMessage.success('新增成功')
  delCreate.visible = false
}

/** 查看（行点击），引用保持响应式 */
const viewing = ref<import('@/types').AssetDeliverable | null>(null)
const viewDialog = ref(false)

function openView(id: number) {
  viewing.value = deliverables.value.find((d) => d.id === id) ?? null
  viewDialog.value = true
}

async function setDelStatus(status: 'ready' | 'todo') {
  if (!asset.value || !viewing.value) return
  await updateAssetDeliverable(asset.value.id, viewing.value.id, { status })
  ElMessage.success(status === 'ready' ? '已置为「已就绪」' : '已置为「待完善」')
}

// ============================================================
// 可售明细（ADR-011：仅 type='遥感数据' 显示页签；CRUD 走 rs-items 接口，require_editor）
// ============================================================
const rsItems = computed<RsItem[]>(() => (asset.value ? rsItemsOfAsset(asset.value.id) : []))

/** 精度选项（米） */
const RS_RESOLUTIONS = [0.5, 1, 1.5, 2]

/** 已售次数（派生）：db 中该 itemId 已完成（delivered）合同明细计次；统计不到显示 0 */
function rsSoldCount(itemId: number): number {
  return db.contracts
    .filter((c) => c.status === 'delivered')
    .reduce((s, c) => s + c.items.filter((it) => it.itemId === itemId).length, 0)
}

const rsForm = reactive({
  visible: false,
  editing: null as RsItem | null,
  province: '',
  city: '',
  resolution: undefined as number | undefined,
  saleMonth: '',
  price: undefined as number | undefined,
})

function openRsCreate() {
  rsForm.editing = null
  rsForm.province = ''
  rsForm.city = ''
  rsForm.resolution = undefined
  rsForm.saleMonth = ''
  rsForm.price = undefined
  rsForm.visible = true
}

function openRsEdit(it: RsItem) {
  rsForm.editing = it
  rsForm.province = it.province
  rsForm.city = it.city
  rsForm.resolution = it.resolution
  rsForm.saleMonth = it.saleMonth
  rsForm.price = it.price
  rsForm.visible = true
}

async function saveRsItem() {
  if (!asset.value) return
  if (!rsForm.province) {
    ElMessage.warning('请选择省份')
    return
  }
  if (!rsForm.resolution) {
    ElMessage.warning('请选择精度')
    return
  }
  if (!rsForm.saleMonth) {
    ElMessage.warning('请选择月份')
    return
  }
  if (!rsForm.price || !Number.isInteger(rsForm.price) || rsForm.price <= 0) {
    ElMessage.warning('单价须为整数元（大于 0）')
    return
  }
  const data: RsItemInput = {
    province: rsForm.province,
    city: rsForm.city,
    resolution: rsForm.resolution,
    saleMonth: rsForm.saleMonth,
    price: rsForm.price,
    // 编辑沿用既有可重复售卖设置；新增默认 true（只计次不扣量）
    repeatSale: rsForm.editing ? rsForm.editing.repeatSale : true,
  }
  try {
    if (rsForm.editing) {
      await updateRsItem(rsForm.editing.id, data)
      ElMessage.success('明细已更新')
    } else {
      await addRsItem(asset.value.id, data)
      ElMessage.success('明细已新增')
    }
    rsForm.visible = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  }
}

async function removeRsItem(it: RsItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除明细「${rsItemName(it)}」吗？`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteRsItem(it.id)
    ElMessage.success('明细已删除')
  } catch (e) {
    // 后端 400「该明细存在销售关联，无法删除」原样 toast
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

/**
 * 签约主体（ADR-007，三级兜底）：
 * 1. 项目自身 subject（派生：单合同=该合同值，多合同=空）；
 * 2. 为空时取**本行明细所属合同**的 subject（合同内强制同一资产主体，最贴近本行）；
 * 3. 仍无（存量明细 contractId=null）→ 兜底明细资产自身主体；仍无 → '-'。
 */
function projectSubject(p: Project, item: ProjectItem): string {
  if (p.subject) return p.subject
  if (item.contractId) {
    const c = db.contracts.find((c) => c.id === item.contractId)
    if (c?.subject) return c.subject
  }
  const it = item.assetId != null ? item : p.items.find((i) => i.assetId != null)
  const assetId = it?.assetId
  return (assetId != null ? getAsset(assetId)?.subject : '') || '-'
}

/** 合同数（ADR-007）：contractCount 缺失/0 的存量项目按单合同口径显示「1 份合同」 */
function contractCountText(p: Project): string {
  return p.contractCount ? `${p.contractCount} 份合同` : '1 份合同'
}

/** 流水操作人：空 → -；system → 系统 */
function operatorText(f: AssetFlow): string {
  if (!f.operator) return '-'
  return f.operator === 'system' ? '系统' : f.operator
}
</script>

<template>
  <div class="page-container">
    <template v-if="asset">
      <div class="detail-page">
        <!-- 返回入口 -->
        <a class="back-link" @click="router.push(`/assets/${asset.board}`)">
          <el-icon><ArrowLeft /></el-icon>
          返回{{ boardLabel(asset.board) }}
        </a>

        <!-- 标题 + 元信息 + 动作 -->
        <div class="detail-head">
          <div class="head-left">
            <h1 class="head-title">{{ asset.name }}</h1>
            <div class="head-sub">
              <span>{{ asset.code }}</span>
              <span class="sep">·</span>
              <span>{{ boardLabel(asset.board) }} / {{ asset.type }}</span>
              <template v-if="asset.subject">
                <span class="sep">·</span>
                <span>{{ entityShort(asset.subject) }}</span>
              </template>
              <span class="status-pill" :class="statusPill().cls">
                <span class="dot" aria-hidden="true">{{ statusPill().dot }}</span>
                {{ ASSET_STOCK_STATE[assetStockState(asset)].label }}
              </span>
            </div>
          </div>
          <div class="head-actions" v-if="!isWipBoard()">
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
              <span>
                <el-button type="primary" :icon="Edit" :disabled="!canWrite" @click="goEditAsset">
                  编辑资产
                </el-button>
              </span>
            </el-tooltip>
            <!-- 登记销售对三角色均可用（含生态人员；viewer 打开直接下单对话框） -->
            <el-button plain :icon="Link" @click="goRegisterSale">登记销售</el-button>
            <el-dropdown trigger="click">
              <span class="more-btn">
                更多
                <el-icon><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="copyCode">复制资产编号</el-dropdown-item>
                  <el-dropdown-item @click="activeTab = 'logs'">查看操作记录</el-dropdown-item>
                  <el-dropdown-item divided :disabled="!canWrite" @click="handleDelete" class="danger-item">
                    <el-icon><Delete /></el-icon>
                    删除资产
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <div v-if="isWipBoard()" class="info-bar">
          <el-icon aria-hidden="true"><InfoFilled /></el-icon>
          <span>算力服务板块建设中，本页仅支持查看。后续启用时将支持资源池管理、可售算力、服务期额度与交付开通记录。</span>
        </div>

        <!-- 六页签 -->
        <el-tabs v-model="activeTab" class="asset-tabs">
          <!-- 1 基本信息：左 2/3 基础资料(1列) + 右 1/3 库存与归属(含可售数量) -->
          <el-tab-pane label="基本信息" name="info">
            <div class="basic-layout">
              <div class="detail-card">
                <div class="card-head">
                  <div class="card-title">基础资料</div>
                </div>
                <div class="info-grid info-grid-1">
                  <div class="info-item">
                    <span class="il">资产名称</span>
                    <span class="iv">{{ asset.name }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">资产编号</span>
                    <span class="iv">{{ asset.code }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">所属板块</span>
                    <span class="iv">{{ boardLabel(asset.board) }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">资产类型</span>
                    <span class="iv">{{ asset.type }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">规格型号</span>
                    <span class="iv">{{ asset.spec || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">计量单位</span>
                    <span class="iv">{{ asset.unit || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">备注</span>
                    <span class="iv">{{ asset.remark || '-' }}</span>
                  </div>
                </div>
              </div>

              <div class="detail-card">
                <div class="card-head">
                  <div class="card-title">库存与归属</div>
                </div>
                <div class="info-grid info-grid-1">
                  <div class="info-item">
                    <span class="il">资产总数</span>
                    <span class="iv">{{ formatAssetQty(asset, asset.quantity) }} {{ asset.unit }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">可售数量</span>
                    <span class="iv">{{ asset.repeatSale ? '不限' : `${formatAssetQty(asset, availableQty(asset))} ${asset.unit}` }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">销售单价</span>
                    <!-- ADR-008：包量定价资产单价为参考口径（元/万Token），不参与计价 -->
                    <span v-if="isAmountMode(asset)" class="iv">
                      {{ asset.salePrice ? `约 ¥${asset.salePrice}/万Token（参考）` : '-' }}
                    </span>
                    <span v-else class="iv">{{ asset.salePrice ? formatMoney(asset.salePrice) : '-' }}<template v-if="asset.repeatSale"> / {{ asset.unit }}</template></span>
                  </div>
                  <div class="info-item">
                    <span class="il">入库时间</span>
                    <span class="iv">{{ asset.inboundDate || '-' }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">到期时间</span>
                    <span class="iv">{{ expiryText(asset) }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">归属主体</span>
                    <span class="iv">{{ asset.subject || '-' }}</span>
                  </div>
                </div>
                <div class="info-bar soft" style="margin-top: 12px;">
                  <el-icon aria-hidden="true"><InfoFilled /></el-icon>
                  <span>资产基础信息登记入库后生成；修改关键字段将记录操作日志。</span>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 1.5 可售明细（ADR-011：仅遥感数据父资产显示；CRUD 明细） -->
          <el-tab-pane v-if="asset.type === '遥感数据'" :label="`可售明细（${rsItems.length}）`" name="rsItems">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">可售明细</div>
                  <div class="card-desc">按 省/精度/月份 维护可售卖明细，每份明细独立计价（整数元/份），默认可重复售卖（只计次不扣量）。</div>
                </div>
                <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
                  <span>
                    <el-button type="primary" size="small" :icon="Plus" :disabled="!canWrite" @click="openRsCreate">
                      新增明细
                    </el-button>
                  </span>
                </el-tooltip>
              </div>
              <el-table v-if="rsItems.length" :data="rsItems" border stripe>
                <el-table-column label="省 / 市" min-width="180" align="left">
                  <template #default="{ row }">{{ row.city ? `${row.province} / ${row.city}` : row.province }}</template>
                </el-table-column>
                <el-table-column label="精度" width="90" align="center">
                  <template #default="{ row }">{{ row.resolution }}m</template>
                </el-table-column>
                <el-table-column label="月份" width="110" align="center" prop="saleMonth" />
                <el-table-column label="单价" width="110" align="center">
                  <template #default="{ row }">{{ formatMoney(row.price) }}</template>
                </el-table-column>
                <el-table-column label="可重复售卖" width="110" align="center">
                  <template #default="{ row }">
                    <!-- 胶囊标签：重复售卖 = 紫蓝、单次 = 灰（平台 token 色，参照 stock-pill） -->
                    <span class="rs-pill" :class="row.repeatSale ? 'repeat' : 'once'">
                      {{ row.repeatSale ? '重复售卖' : '单次' }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="已售次数" width="100" align="center">
                  <template #default="{ row }">{{ rsSoldCount(row.id) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="120" align="center">
                  <template #default="{ row }">
                    <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button link type="primary" size="small" :disabled="!canWrite" @click="openRsEdit(row)">
                          编辑
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button link type="danger" size="small" :disabled="!canWrite" @click="removeRsItem(row)">
                          删除
                        </el-button>
                      </span>
                    </el-tooltip>
                  </template>
                </el-table-column>
              </el-table>
              <el-empty v-else description="暂无可售明细" :image-size="70">
                <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                  <span>
                    <el-button type="primary" size="small" :icon="Plus" :disabled="!canWrite" @click="openRsCreate">
                      新增明细
                    </el-button>
                  </span>
                </el-tooltip>
              </el-empty>
            </div>
          </el-tab-pane>

          <!-- 2 交付物 -->
          <el-tab-pane :label="`交付物（${deliverables.length}）`" name="deliverables">
            <div class="stat-cards del-stats">
              <div class="stat-card">
                <div>
                  <div class="s-label">标准交付物</div>
                  <div class="s-value">{{ delStats.total }}</div>
                  <div class="s-sub">面向每套资产默认交付</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><Tickets /></el-icon>
              </div>
              <div class="stat-card">
                <div>
                  <div class="s-label">已就绪</div>
                  <div class="s-value">{{ delStats.ready }}</div>
                  <div class="s-sub">可随项目交付</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><CircleCheck /></el-icon>
              </div>
              <div class="stat-card">
                <div>
                  <div class="s-label">最近更新</div>
                  <div class="s-value s-value-sm">{{ delStats.latest }}</div>
                  <div class="s-sub">交付物最近更新日期</div>
                </div>
                <el-icon class="s-icon" aria-hidden="true"><Operation /></el-icon>
              </div>
            </div>

            <div class="deliver-layout">
              <div class="detail-card">
                <div class="card-head">
                  <div>
                    <div class="card-title">交付物清单</div>
                    <div class="card-desc">交付包是资产的标准材料集合；项目交付时选择版本并生成交付记录。</div>
                  </div>
                  <div class="dl-head-actions">
                    <el-select v-model="catFilter" placeholder="全部类型" clearable style="width: 130px;">
                      <el-option
                        v-for="(c, k) in DELIVERABLE_CATEGORIES"
                        :key="k"
                        :label="c.label"
                        :value="k"
                      />
                    </el-select>
                    <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
                      <span>
                        <el-button
                          v-if="!isWipBoard()"
                          plain
                          size="small"
                          :icon="Plus"
                          :disabled="!canWrite"
                          @click="openDelCreate"
                        >
                          新增
                        </el-button>
                      </span>
                    </el-tooltip>
                  </div>
                </div>

                <div class="dl-list">
                  <div
                    v-for="d in filteredDels"
                    :key="d.id"
                    class="dl-row"
                    @click="openView(d.id)"
                  >
                    <span class="cat-icon" :class="CAT_ICON[d.category].cls" aria-hidden="true">
                      <el-icon><component :is="CAT_ICON[d.category].icon" /></el-icon>
                    </span>
                    <div class="dl-main">
                      <div class="dl-name">
                        {{ d.name }}
                        <el-tag v-if="d.required" size="small" type="primary" effect="plain" class="req-tag">必选</el-tag>
                      </div>
                      <div class="dl-meta muted">
                        {{ DELIVERABLE_CATEGORIES[d.category].label }} · {{ d.version }} · {{ d.meta }} · 更新于 {{ d.updatedAt }}
                      </div>
                    </div>
                    <div class="dl-right">
                      <span class="dl-pill" :class="d.status === 'ready' ? 'ok' : 'wip'">
                        {{ d.status === 'ready' ? '已就绪' : '待完善' }}
                      </span>
                    </div>
                  </div>
                  <el-empty v-if="!filteredDels.length" description="暂无匹配的交付物" :image-size="60" />
                </div>
              </div>

              <!-- 右侧交付说明窄栏 -->
              <div class="detail-card side-card">
                <div class="card-title">交付说明</div>
                <div class="card-desc" style="margin-bottom: 12px;">销售项目确认后选择实际交付范围</div>
                <div class="step-timeline">
                  <div class="step" v-for="(s, i) in DELIVERY_STEPS" :key="s.t">
                    <span class="step-dot" :class="{ last: i === DELIVERY_STEPS.length - 1 }" aria-hidden="true"></span>
                    <div class="step-title">{{ s.t }}</div>
                    <div class="step-desc muted">{{ s.d }}</div>
                  </div>
                </div>
                <div class="scope-title" v-if="defaultScope.length">默认交付范围</div>
                <div v-if="defaultScope.length" class="scope-list">
                  <div v-for="s in defaultScope" :key="s.label" class="scope-row">
                    <span class="scope-label muted">{{ s.label }}</span>
                    <span class="scope-names">{{ s.names.join('、') }}</span>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <!-- 3 销售关联 -->
          <el-tab-pane :label="`销售关联（${salesLinks.length}）`" name="sales">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">关联销售项目</div>
                  <div class="card-desc">登记销售时按明细锁定库存或记录售卖；项目「交付完成」后自动扣减并生成出库记录。</div>
                </div>
                <span class="muted" style="font-size: 12px;">共 {{ salesLinks.length }} 条</span>
              </div>
              <el-table v-if="salesLinks.length" :data="salesLinks">
                <el-table-column label="项目名称" min-width="200">
                  <template #default="{ row }">
                    <a class="link" @click="router.push(`/sales/projects/${row.project.id}/detail`)">{{ row.project.name }}</a>
                    <div class="muted" style="font-size: 12px;">{{ row.project.code }} · {{ contractCountText(row.project) }}</div>
                  </template>
                </el-table-column>
                <el-table-column prop="project.customer" label="客户名称" width="150" show-overflow-tooltip />
                <el-table-column label="生态人员" width="110" align="left">
                  <template #default="{ row }">{{ row.project.rep || '-' }}</template>
                </el-table-column>
                <el-table-column label="签约主体" width="130" align="left">
                  <template #default="{ row }">{{ entityShort(projectSubject(row.project, row.item)) }}</template>
                </el-table-column>
                <el-table-column label="关联数量" width="120" align="right">
                  <template #default="{ row }">{{ formatAssetQty(asset, row.item.qty) }} {{ row.item.unit }}</template>
                </el-table-column>
                <el-table-column label="销售金额" width="120" align="right">
                  <template #default="{ row }">{{ formatMoney(row.item.amount) }}</template>
                </el-table-column>
                <el-table-column label="当前状态" width="110" align="center">
                  <template #default="{ row }">
                    <el-tag :type="tagInfo(PROJECT_STATUS, row.project.status).tag" size="small" effect="plain">
                      {{ tagInfo(PROJECT_STATUS, row.project.status).label }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="关联日期" width="120" align="left">
                  <template #default="{ row }">{{ row.item.lockedDate || '-' }}</template>
                </el-table-column>
              </el-table>
              <div v-else class="empty-compact">
                <el-icon class="empty-icon" aria-hidden="true"><Link /></el-icon>
                <div class="empty-title">暂无销售关联</div>
                <div class="empty-desc muted">登记销售项目后，关联资产会在这里显示，并自动更新锁定数量和销售金额。</div>
                <el-button v-if="!isWipBoard()" type="primary" size="small" @click="goRegisterSale">
                  登记销售
                </el-button>
              </div>
            </div>
          </el-tab-pane>

          <!-- 4 出入库流水 -->
          <el-tab-pane :label="`出入库流水（${flows.length}）`" name="flows">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">出入库流水</div>
                  <div class="card-desc">入库、锁定、出库、调整与撤销均留痕，审计记录不可删除。</div>
                </div>
                <el-radio-group v-model="flowFilter" size="small">
                  <el-radio-button value="all">全部流水</el-radio-button>
                  <el-radio-button value="purchase_in">入库</el-radio-button>
                  <el-radio-button value="project_lock">项目锁定</el-radio-button>
                  <el-radio-button value="sale_out">销售出库</el-radio-button>
                  <el-radio-button value="adjust">调整记录</el-radio-button>
                </el-radio-group>
              </div>

              <div v-if="filteredFlows.length" class="flow-list">
                <div v-for="f in filteredFlows" :key="f.id" class="flow-item">
                  <div class="fl-date muted">{{ f.date }}</div>
                  <div class="fl-main">
                    <div class="fl-title">
                      <span class="fl-dot" :class="FLOW_CLS[f.type]" aria-hidden="true"></span>
                      {{ FLOW_TYPES[f.type].label }}
                      <span class="fl-operator muted">操作人：{{ operatorText(f) }}</span>
                    </div>
                    <div class="fl-desc">
                      {{ asset.name }} · {{ FLOW_TYPES[f.type].label }} {{ formatAssetQty(asset, f.qty) }} {{ f.unit }}
                      <template v-if="f.amount"> · 金额 {{ formatMoney(f.amount) }}</template>
                    </div>
                    <div class="fl-meta muted">
                      <template v-if="f.ref">关联单号：{{ f.ref }}</template>
                      <template v-if="f.ref && f.note"> · </template>
                      <template v-if="f.note">{{ f.note }}</template>
                    </div>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无流水" :image-size="70" />
            </div>
          </el-tab-pane>

          <!-- 5 操作记录 -->
          <el-tab-pane :label="`操作记录（${opLogs.length}）`" name="logs">
            <div class="detail-card">
              <div class="card-head">
                <div>
                  <div class="card-title">操作记录</div>
                  <div class="card-desc">资产创建、状态变更、编辑与删除的审计留痕，不提供编辑或删除。</div>
                </div>
                <span class="muted" style="font-size: 12px;">共 {{ opLogs.length }} 条</span>
              </div>
              <el-timeline v-if="opLogs.length">
                <el-timeline-item
                  v-for="log in [...opLogs].reverse()"
                  :key="log.id"
                  :timestamp="`${log.time} · ${log.operator}`"
                  placement="top"
                >
                  <div class="log-action">{{ log.action }}</div>
                  <div v-if="log.changes" class="log-changes muted">{{ translateFileNames(log.changes) }}</div>
                  <div class="log-detail muted">{{ log.detail }}</div>
                </el-timeline-item>
              </el-timeline>
              <el-empty v-else description="暂无操作记录" :image-size="70" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>

      <!-- 新增交付物对话框 -->
      <el-dialog
        v-model="delCreate.visible"
        :title="`新增交付物 · ${asset.name}`"
        class="dlg-form"
        :close-on-click-modal="false"
      >
        <el-form label-width="96px">
          <el-form-item label="交付物名称" required>
            <el-input v-model="delCreate.form.name" placeholder="如：部署与运维手册" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="delCreate.form.category" style="width: 100%;">
              <el-option
                v-for="(c, k) in DELIVERABLE_CATEGORIES"
                :key="k"
                :label="c.label"
                :value="k"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="默认必选">
            <el-switch v-model="delCreate.form.required" />
            <span class="muted" style="font-size: 12px; margin-left: 8px;">必选项随项目交付默认勾选</span>
          </el-form-item>
          <el-form-item label="适用说明">
            <el-input v-model="delCreate.form.note" type="textarea" :rows="2" placeholder="版本 / 格式 / 适用范围" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="delCreate.visible = false">取消</el-button>
          <el-button type="primary" @click="confirmDel">确定</el-button>
        </template>
      </el-dialog>

      <!-- 交付物详情 -->
      <el-dialog v-model="viewDialog" title="交付物详情" width="560px" :close-on-click-modal="false">
        <template v-if="viewing">
          <div class="dl-detail-head">
            <span class="cat-icon" :class="CAT_ICON[viewing.category].cls" aria-hidden="true">
              <el-icon><component :is="CAT_ICON[viewing.category].icon" /></el-icon>
            </span>
            <div style="flex: 1; min-width: 0;">
              <div class="dl-name">{{ viewing.name }}</div>
              <div class="dl-meta muted">
                {{ DELIVERABLE_CATEGORIES[viewing.category].label }} · {{ viewing.version }}
              </div>
            </div>
            <span class="dl-pill" :class="viewing.status === 'ready' ? 'ok' : 'wip'">
              {{ viewing.status === 'ready' ? '已就绪' : '待完善' }}
            </span>
          </div>
          <div class="info-grid info-grid-1" style="margin-top: 14px;">
            <div class="info-item span-3">
              <span class="il">适用说明</span>
              <span class="iv">{{ viewing.meta }}</span>
            </div>
            <div class="info-item span-3">
              <span class="il">默认交付</span>
              <span class="iv">{{ viewing.required ? '必选（默认勾选，不可移除）' : '可选' }}</span>
            </div>
            <div class="info-item span-3">
              <span class="il">最近更新</span>
              <span class="iv">{{ viewing.updatedAt }}</span>
            </div>
          </div>
          <div class="info-bar" style="margin-top: 12px;">
            <el-icon aria-hidden="true"><InfoFilled /></el-icon>
            <span>已被项目引用的版本不可直接覆盖，应新增新版本。</span>
          </div>
        </template>
        <template #footer>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <el-button
              v-if="viewing && viewing.status !== 'ready'"
              type="primary"
              :disabled="!canWrite"
              @click="setDelStatus('ready')"
            >
              标记就绪
            </el-button>
          </el-tooltip>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <el-button
              v-if="viewing && viewing.status === 'ready'"
              :disabled="!canWrite"
              @click="setDelStatus('todo')"
            >
              退回待完善
            </el-button>
          </el-tooltip>
          <el-button @click="viewDialog = false">关闭</el-button>
        </template>
      </el-dialog>

      <!-- 登记销售（生态人员直接下单；遥感数据 = 订单级客户 + N 行明细） -->
      <SalesOrderDialog
        v-model="saleVisible"
        title="销售下单"
        :items="saleItems"
        :allow-qty-edit="true"
        :loading="saleLoading"
        @submit="onSaleSubmit"
      />

      <!-- ADR-011：遥感数据明细选择弹窗（登记销售入口） -->
      <RsItemPicker
        v-if="asset.type === '遥感数据'"
        v-model="rsPickerVisible"
        :parent-asset="asset"
        @confirm="onRsPickerConfirm"
      />

      <!-- ADR-011：新增 / 编辑可售明细 -->
      <el-dialog
        v-model="rsForm.visible"
        :title="rsForm.editing ? `编辑明细 · ${asset.name}` : `新增明细 · ${asset.name}`"
        class="dlg-form"
        :close-on-click-modal="false"
      >
        <el-form label-width="96px">
          <el-form-item label="省份" required>
            <el-select v-model="rsForm.province" placeholder="选择省 / 自治区 / 直辖市" style="width: 100%;">
              <el-option v-for="p in PROVINCES" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
          <el-form-item label="城市">
            <el-input v-model="rsForm.city" placeholder="选填，如：石家庄市" />
          </el-form-item>
          <el-form-item label="精度" required>
            <el-select v-model="rsForm.resolution" placeholder="选择精度" style="width: 100%;">
              <el-option v-for="r in RS_RESOLUTIONS" :key="r" :label="`${r}m`" :value="r" />
            </el-select>
          </el-form-item>
          <el-form-item label="月份" required>
            <el-date-picker
              v-model="rsForm.saleMonth"
              type="month"
              value-format="YYYY-MM"
              placeholder="选择售卖月份"
              style="width: 100%;"
            />
          </el-form-item>
          <el-form-item label="单价（元）" required>
            <el-input-number
              v-model="rsForm.price"
              :min="1"
              :precision="0"
              :step="1"
              :controls="false"
              placeholder="整数元/份"
              style="width: 100%;"
            />
            <div class="dlg-hint">整数元/份，须大于 0</div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="rsForm.visible = false">取消</el-button>
          <el-button type="primary" @click="saveRsItem">确定</el-button>
        </template>
      </el-dialog>
    </template>

    <!-- 未找到资产：空态 + 返回列表（避免直达无效 URL 时白屏） -->
    <el-empty v-else description="未找到该资产" :image-size="80">
      <el-button type="primary" @click="router.push('/assets/embodied')">返回资产台账</el-button>
    </el-empty>
  </div>
</template>

<style scoped>
/* 主体限宽 1180px 居中 */
.detail-page {
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ============ 头部 ============ */
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}
.head-left {
  min-width: 0;
}
.head-title {
  margin: 2px 0 8px;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
}
.head-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--text-secondary);
  font-size: 13px;
}
.head-sub .sep {
  color: #c3d2e6;
}
.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
/* 「更多」文字按钮（非描边按钮） */
.more-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  border-radius: 6px;
}
.more-btn:hover {
  color: var(--primary-color);
  background: var(--primary-light);
}
:deep(.el-dropdown-menu .danger-item) {
  color: #d9534f;
}

/* 状态点胶囊 */
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.status-pill .dot {
  font-size: 10px;
}
.status-pill.ok {
  color: #0c7b51;
  background: #eaf8f1;
}
.status-pill.off {
  color: #c62828;
  background: #fdecea;
}

/* 可售明细「可重复售卖」胶囊标签：重复售卖 = 紫蓝、单次 = 灰（平台 token 色，与 stock-pill 同款） */
.rs-pill {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.rs-pill.repeat {
  color: #4e63a8;
  background: #eef0ff;
}
.rs-pill.once {
  color: #71829a;
  background: #eef2f8;
}

/* ============ 页签 ============ */
.asset-tabs {
  background: transparent;
}
:deep(.el-tabs__header) {
  margin-bottom: 18px;
}
:deep(.el-tabs__item) {
  font-size: 13px;
  height: 40px;
}
:deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
:deep(.el-tab-pane) > .stat-cards {
  margin-bottom: 0;
}

/* 页签内白卡 */
.detail-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.card-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}

/* ============ 基本信息：2/3 + 1/3 双栏 ============ */
.basic-layout {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 14px;
  align-items: stretch;
}
@media (max-width: 999px) {
  .basic-layout {
    grid-template-columns: 1fr;
  }
}
.ig-2 {
  grid-template-columns: repeat(2, 1fr);
}
@media (max-width: 680px) {
  .ig-2 {
    grid-template-columns: 1fr;
  }
  .ig-2 .info-item.span-2 {
    grid-column: span 1;
  }
}
.info-bar.soft {
  background: #f7fafd;
  border: 1px solid #e7edf5;
}

/* 序列号空态 */
.serial-empty {
  font-size: 13px;
  padding: 14px 4px;
  text-align: center;
}

/* ============ 交付物 ============ */
.del-stats {
  grid-template-columns: repeat(3, 1fr);
}
@media (max-width: 680px) {
  .del-stats {
    grid-template-columns: 1fr;
  }
}
.s-value-sm {
  font-size: 18px;
}

.deliver-layout {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 12px;
  align-items: start;
}
@media (max-width: 999px) {
  .deliver-layout {
    grid-template-columns: 1fr;
  }
}
.side-card {
  position: sticky;
  top: 8px;
}

.dl-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 清单项：横向信息行 */
.dl-list {
  display: flex;
  flex-direction: column;
}
.dl-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 8px;
  border-bottom: 1px solid var(--divider-color);
  cursor: pointer;
  border-radius: 6px;
}
.dl-row:hover {
  background: var(--row-hover);
}
.dl-row:last-child {
  border-bottom: none;
}
.dl-main {
  flex: 1;
  min-width: 0;
}
.dl-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dl-meta {
  font-size: 12px;
  margin-top: 3px;
}
.dl-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.dl-link {
  font-size: 13px;
  color: var(--primary-color);
  cursor: pointer;
  white-space: nowrap;
}
.dl-link:hover {
  color: var(--primary-hover);
}
.dl-pill {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  line-height: 18px;
  padding: 2px 10px;
  border-radius: 999px;
  white-space: nowrap;
}
.dl-pill.ok {
  color: #0c7b51;
  background: #eaf8f1;
}
.dl-pill.wip {
  color: #a86514;
  background: #fff5e7;
}

/* 分类图标 */
.cat-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.cat-icon.blue {
  background: #eaf3ff;
  color: #1769d4;
}
.cat-icon.green {
  background: #eaf8f1;
  color: #0c7b51;
}
.cat-icon.purple {
  background: #eef0ff;
  color: #4e63a8;
}
.cat-icon.neutral {
  background: #eef2f8;
  color: #71829a;
}

/* 右侧说明栏时间线 */
.step-timeline {
  position: relative;
  padding-left: 14px;
  margin-bottom: 16px;
}
.step {
  position: relative;
  padding-bottom: 14px;
}
.step:last-child {
  padding-bottom: 0;
}
.step::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 6px;
  bottom: 0;
  width: 1px;
  background: var(--border-color);
}
.step:last-child::before {
  display: none;
}
.step-dot {
  position: absolute;
  left: -17px;
  top: 3px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary-color);
}
.step-dot.last {
  background: #c3d2e6;
}
.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.step-desc {
  font-size: 12px;
  margin-top: 3px;
  line-height: 1.5;
}

.scope-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.scope-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.scope-row {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.scope-names {
  color: var(--text-body);
}

.dl-detail-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* ============ 销售关联空状态 ============ */
.empty-compact {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 16px;
  text-align: center;
}
.empty-icon {
  font-size: 34px;
  color: #c9d6e8;
}
.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.empty-desc {
  font-size: 13px;
  max-width: 420px;
  line-height: 1.6;
}
.empty-compact .el-button {
  margin-top: 6px;
}
.link {
  color: var(--primary-color);
  font-weight: 500;
  cursor: pointer;
}
.link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}

/* ============ 出入库流水时间线 ============ */
.flow-list {
  display: flex;
  flex-direction: column;
}
.flow-item {
  display: flex;
  gap: 16px;
  padding: 14px 4px;
  border-bottom: 1px solid var(--divider-color);
}
.flow-item:last-child {
  border-bottom: none;
}
.fl-date {
  flex-shrink: 0;
  width: 86px;
  font-size: 13px;
  padding-top: 1px;
}
.fl-main {
  flex: 1;
  min-width: 0;
}
.fl-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.fl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.fl-dot.blue {
  background: #1769d4;
}
.fl-dot.green {
  background: #0c7b51;
}
.fl-dot.gray {
  background: #71829a;
}
.fl-dot.orange {
  background: #a86514;
}
.fl-operator {
  margin-left: 4px;
  font-size: 12px;
  font-weight: 400;
}
.fl-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-body);
}
.fl-meta {
  margin-top: 3px;
  font-size: 12px;
}
@media (max-width: 680px) {
  .flow-item {
    flex-wrap: wrap;
  }
  .fl-date {
    width: 100%;
  }
}

/* ============ 操作记录 ============ */
.log-action {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.log-changes {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.6;
}
.log-detail {
  margin-top: 3px;
  font-size: 13px;
  line-height: 1.6;
}

.status-radios {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}

</style>
