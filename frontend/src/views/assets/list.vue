<script setup lang="ts">
/**
 * 产品及服务 - 板块列表页（具身智能 / 卫星服务 / 软件产品 / 硬件产品）
 *
 * 卫星服务板块顶部增加二级切换：卫星 Token / 卫星数据
 * 筛选：名称搜索 / 状态 / 主体 / 登记日期
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Box, Close, Document, InfoFilled, Plus, Search, ShoppingCart } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  ASSET_STOCK_STATE,
  DELIVERABLE_CATEGORIES,
  DELIVERABLE_STATUS,
  FLOW_TYPES,
  assetStockState,
  availableQty,
  boardLabel,
  entityShort,
  expiryText,
  formatAssetQty,
  formatMoney,
  noSellableStock,
  priceRangeText,
  rsItemName,
  TYPE_TAG_CLASS,
  type Asset,
  type AssetStockState,
  type Board,
} from '@/types'
import {
  addCartBatch,
  addToCart,
  db,
  fileDisplayName,
  fileUrl,
  getAssetDeliverables,
  listAssetFlows,
  listAssetLogs,
  listAssetRsItems,
  projectItemsOfAsset,
  refresh,
  showError,
} from '@/api'
import FilePreview from '@/components/FilePreview.vue'
import RsItemPicker from '@/components/RsItemPicker.vue'
import { canWrite, NO_PERM_TIP } from '@/auth'
import type { RsItem, RsItemWithSold } from '@/types'

const route = useRoute()
const router = useRouter()

const board = computed<Board>(() => (route.params.board as Board) || 'embodied')

const boardName = computed(() => boardLabel(board.value))

// 卫星二级切换（ADR-010：新增「遥感数据」页签）
const satelliteTab = ref<'all' | 'token' | 'data' | 'remote'>('all')

// 筛选（状态默认「可售」：只展示可售产品；清空 = 全部）
const searchText = ref('')
const statusFilter = ref<AssetStockState | ''>('in_stock')
const subjectFilter = ref('')
const inboundMonth = ref('')

// 切换板块时重置二级切换与筛选条件（状态回到默认「可售」），避免残留上一板块的筛选值
watch(board, () => {
  satelliteTab.value = 'all'
  statusFilter.value = 'in_stock'
  subjectFilter.value = ''
  inboundMonth.value = ''
  searchText.value = ''
})

const subjects = computed(() =>
  Array.from(new Set(db.assets.filter((a) => a.board === board.value).map((a) => a.subject))).filter(Boolean),
)

const list = computed(() => {
  return db.assets.filter((a) => {
    if (a.board !== board.value) return false
    if (board.value === 'satellite' && satelliteTab.value === 'token' && a.type !== '卫星Token') return false
    if (board.value === 'satellite' && satelliteTab.value === 'data' && a.type !== '卫星数据') return false
    if (board.value === 'satellite' && satelliteTab.value === 'remote' && a.type !== '遥感数据') return false
    const kw = searchText.value.trim()
    if (kw && !`${a.name}${a.code}${a.spec}${a.type}`.includes(kw)) return false
    if (statusFilter.value && assetStockState(a) !== statusFilter.value) return false
    if (subjectFilter.value && a.subject !== subjectFilter.value) return false
    if (inboundMonth.value && !(a.inboundDate || '').startsWith(inboundMonth.value)) return false
    return true
  })
})

function goDetail(a: Asset) {
  router.push(`/assets/${a.id}/detail`)
}

/** ADR-011：遥感数据行次级行摘要（覆盖省份 · 明细数，替换 ADR-010 三维摘要） */
function remoteSummary(a: Asset): string {
  const items = db.rsItems.filter((r) => r.assetId === a.id)
  const provinces = Array.from(new Set(items.map((r) => r.province))).filter(Boolean)
  const pText = provinces.length ? provinces.join('/') : '-'
  return `覆盖 ${pText} · ${items.length} 份明细`
}

/** ADR-011：遥感数据父产品的明细数（「产品总数」列显示「N 期」——遥感明细按期售卖） */
function rsCount(a: Asset): number {
  return db.rsItems.filter((r) => r.assetId === a.id).length
}

function goEdit(a: Asset) {
  if (noSellableStock(a)) {
    ElMessage.warning('该产品当前无可用数量（可售数量为 0）。可继续编辑补登记或核对锁定 / 售出情况。')
  }
  router.push(`/assets/${a.id}/edit`)
}

// ---- ADR-011：遥感数据明细选择弹窗（加购用途；ADR-020 PRICING-20261020：
//      「登记销售」直接下单入口已移除，购物车为唯一下单链路）----
const rsPickerVisible = ref(false)
const rsPickerAsset = ref<Asset | null>(null)

function openRsPicker(a: Asset) {
  rsPickerAsset.value = a
  rsPickerVisible.value = true
}

/** 明细勾选确认：加购（逐条 addToCart，勾选 N 份明细 = N 行购物车，含 itemId、qty=1、客户行内填） */
async function onRsPickerConfirm(items: RsItem[]) {
  const a = rsPickerAsset.value
  if (!a) return
  let ok = 0
  const failed: string[] = []
  for (const it of items) {
    try {
      await addToCart(a.id, 1, it.id)
      ok++
    } catch (e) {
      failed.push(`${rsItemName(it)}（${e instanceof Error ? e.message : '加入购物车失败'}）`)
    }
  }
  if (ok) ElMessage.success(`已将 ${ok} 份明细加入购物车`)
  if (failed.length) ElMessage.error(`以下明细加入购物车失败：${failed.join('、')}`)
}

function goCreate() {
  router.push({ path: '/assets/create', query: { board: board.value } })
}

// ---- 快览抽屉：点击行其它单元格打开，「查看详情」才跳详情页 ----
const drawerVisible = ref(false)
const drawerAsset = ref<Asset | null>(null)

function openDrawer(row: Asset) {
  drawerAsset.value = row
  drawerVisible.value = true
}

/** row-click 入口：selection 列（行复选框 / 该列留白）的点击只做勾选动作，不打开抽屉。
 * 注：EP 2.14 中 selection 单元格 class 为 el-table-column--selection（旧版为 el-table-selection-column），两者都排除 */
function onRowClick(row: Asset, _column: unknown, event: MouseEvent) {
  const target = event.target as HTMLElement | null
  if (target?.closest?.('.el-table-column--selection, .el-table-selection-column')) return
  openDrawer(row)
}

// ---- 购物车：勾选批量加购 + 单行加购 ----
const tableRef = ref()
const selectedAssets = ref<Asset[]>([])

function onSelectionChange(rows: Asset[]) {
  selectedAssets.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
}

/** 点击「产品名称」列（除名称文字外的次级行 / 空白处）= 切换该行勾选，不打开抽屉、不跳详情 */
function toggleRow(row: Asset) {
  tableRef.value?.toggleRowSelection(row)
}

async function singleAddToCart(a: Asset) {
  // ADR-011：遥感数据父产品 → 打开明细选择弹窗（勾选 N 份 = N 行购物车）
  if (a.type === '遥感数据') {
    openRsPicker(a)
    return
  }
  if (noSellableStock(a)) {
    ElMessage.warning(`「${a.name}」暂无可用数量，无法加入购物车`)
    return
  }
  try {
    await addToCart(a.id, 1)
    ElMessage.success(`「${a.name}」已加入购物车`)
  } catch (e) {
    showError(e, '加入购物车失败')
  }
}

/** ADR-009：批量加购对三角色统一走 POST /cart/batch（后端已改 require_order，认证即放行）
 * ADR-011：遥感数据父产品不可直接加购（后端不拦，前端拦死）——勾选中遥感行分流：
 * 不加入、不发 batch 请求、勾选状态保留（clearSelection 后按 id 重新 toggle 回来），info 提示逐份选明细 */
async function batchAddToCart() {
  const rsRows = selectedAssets.value.filter((a) => a.type === '遥感数据')
  const normalRows = selectedAssets.value.filter((a) => a.type !== '遥感数据')
  if (rsRows.length) {
    ElMessage.info('遥感数据需逐份选择明细，请单独点击对应行的"加入购物车"')
  }
  // 勾选中只有遥感行：不发 batch 请求，仅提示（勾选状态本就保留）
  if (!normalRows.length) return
  const items = normalRows.map((a) => ({ assetId: a.id, qty: 1 }))
  try {
    const res = await addCartBatch(items)
    if (res.skipped.length) {
      const names = res.skipped.map((s) => `${s.name}（${s.reason}）`).join('、')
      ElMessage.warning(`已加入 ${res.addedCount} 项，${res.skipped.length} 项因可用数量不足未加入：${names}`)
    } else {
      ElMessage.success(`已将 ${res.addedCount} 项产品加入购物车`)
    }
    // 清勾选后把遥感行重新勾回（afterWrite 已刷新，行对象被替换，需按 id 从新 list 取行）
    const rsIds = new Set(rsRows.map((a) => a.id))
    clearSelection()
    list.value.filter((a) => rsIds.has(a.id)).forEach((a) => tableRef.value?.toggleRowSelection(a))
  } catch (e) {
    showError(e, '加入购物车失败')
  }
}

// 产品清单预览弹层
const previewVisible = ref(false)
function openPreview() {
  if (drawerAsset.value?.contractFile) previewVisible.value = true
}
function contractKindLabel(a: Asset): string {
  if (!a.contractFile) return ''
  const e = a.contractFile.split('.').pop()?.toLowerCase() || ''
  if (e === 'pdf') return 'PDF'
  if (e === 'docx' || e === 'doc') return 'Word'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(e)) return '图片'
  return e ? e.toUpperCase() : '文件'
}

const dDeliverables = computed(() =>
  drawerAsset.value ? getAssetDeliverables(drawerAsset.value.id) : [],
)
const dProjects = computed(() =>
  drawerAsset.value ? projectItemsOfAsset(drawerAsset.value.id) : [],
)

/** 列表「销售单价」列（口径与抽屉「销售单价」一致）：
 *  遥感容器按明细定价显示「-」；包量定价（amount 模式）单价与普通产品一致（元/份，ADR-017，2026-10-20）；
 *  金额直显（repeatSale 带 /unit）。定宽 120 + 居中 + 溢出省略 hover 显示全文。
 *  ADR-018（PRICING-20261020）：有参考区间时追加「（参考区间 {min}~{max}）」，无区间维持原展示 */
function salePriceText(a: Asset): string {
  if (a.type === '遥感数据' || !a.salePrice) return '-'
  const base = a.repeatSale ? `${formatMoney(a.salePrice)}/${a.unit || '份'}` : formatMoney(a.salePrice)
  const range = priceRangeText(a)
  return range ? `${base}（参考区间 ${range}）` : base
}

// ---- ADR-011：遥感数据（容器产品）抽屉五段式结构 ----
const isRemote = computed(() => drawerAsset.value?.type === '遥感数据')

/** 可售明细（PAGE-20261021）：服务端分页（抽屉打开时加载第 1 页）；
 * 「已售次数」列改读后端 soldCount，不再前端遍历 contracts 派生 */
const dRs = reactive({
  loading: false,
  page: 1,
  pageSize: 10,
  total: 0,
  items: [] as RsItemWithSold[],
})

async function loadDrawerRs() {
  const a = drawerAsset.value
  if (!a || a.type !== '遥感数据') return
  dRs.loading = true
  try {
    const res = await listAssetRsItems(a.id, dRs.page, dRs.pageSize)
    dRs.total = res.total
    dRs.items = res.items
  } catch (e) {
    showError(e, '加载可售明细失败')
  } finally {
    dRs.loading = false
  }
}

function onDrawerRsPageChange(page: number) {
  dRs.page = page
  loadDrawerRs()
}

/** 遥感容器「已售次数」总数（PAGE-20261021）：后端仅按行返回 soldCount（当前页），
 * 抽屉头部总数仍由 bootstrap 镜像派生（db.rsItems 取该产品的明细 id + db.contracts 按 itemId 计数，口径与原先一致） */
const dRsSoldTotal = computed(() => {
  const a = drawerAsset.value
  if (!a) return 0
  const ids = new Set(db.rsItems.filter((r) => r.assetId === a.id).map((r) => r.id))
  let n = 0
  for (const c of db.contracts) {
    if (c.status !== 'delivered') continue
    for (const it of c.items) {
      if (it.itemId != null && ids.has(it.itemId)) n++
    }
  }
  return n
})

/** 最近动态（PAGE-20261021，契约 §4.3）：并行取 flows 第 1 页(10) + logs 第 1 页(10)，
 * 前端合并倒序取前 10 条（保持「最近 10 条」语义；不新增合并端点，动态条数多时可能有 1-2 条口径误差，契约已接受） */
interface DrawerActivity {
  key: string
  time: string
  title: string
  operator?: string
  kind: 'flow' | 'log'
}
const dActivities = ref<DrawerActivity[]>([])

async function loadDrawerActivities() {
  const a = drawerAsset.value
  if (!a) return
  try {
    const [flowsRes, logsRes] = await Promise.all([
      listAssetFlows(a.id, 1, 10),
      listAssetLogs(a.id, 1, 10),
    ])
    const flows: DrawerActivity[] = flowsRes.items.map((f) => ({
      key: `flow-${f.id}`,
      time: f.date.slice(0, 10),
      title: [FLOW_TYPES[f.type].label, f.ref, f.note].filter(Boolean).join(' · '),
      operator: f.operator ? (f.operator === 'system' ? '系统' : f.operator) : undefined,
      kind: 'flow' as const,
    }))
    const logs: DrawerActivity[] = logsRes.items.map((l) => ({
      key: `log-${l.id}`,
      time: l.time.slice(0, 16),
      title: [l.action, l.detail].filter(Boolean).join(' · '),
      operator: l.operator || undefined,
      kind: 'log' as const,
    }))
    dActivities.value = [...flows, ...logs].sort((x, y) => y.time.localeCompare(x.time)).slice(0, 10)
  } catch (e) {
    dActivities.value = []
    showError(e, '加载最近动态失败')
  }
}

// PAGE-20261021：抽屉打开时重置并加载可售明细（仅遥感）与最近动态
watch(drawerVisible, (v) => {
  if (!v || !drawerAsset.value) return
  dRs.page = 1
  dActivities.value = []
  loadDrawerRs()
  loadDrawerActivities()
})

/** 数量进度分段（不可重复售卖时展示） */
const dProgress = computed(() => {
  const a = drawerAsset.value
  if (!a || a.repeatSale || a.quantity <= 0) return null
  const avail = availableQty(a) ?? 0
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / a.quantity) * 100))}%`
  return {
    shippedPct: pct(a.shippedQty),
    lockedPct: pct(a.lockedQty),
    availPct: pct(avail),
  }
})

/** 各板块的说明文案与业务规则提示 */
const boardMeta = computed(() => {
  switch (board.value) {
    case 'embodied':
      return {
        desc: '机器人、数采设备与平台软件产品的登记、数量与销售追踪统一台账。',
        rule: '机器人产品默认整机交付，可选序列号交付管理；数采设备按套登记与销售。',
      }
    case 'satellite':
      return {
        desc: '卫星 Token、卫星数据与遥感数据产品的销售台账，按额度、批次与区域精度追踪销售进度。',
        rule: '卫星数据默认支持重复售卖，不随销售交付扣减原始数据量；卫星 Token 按包量售卖（销售金额整数元为准）；遥感数据为容器产品，按 省/精度/月份 维护可售明细售卖（可重复售卖，只计次不扣量）。',
      }
    case 'software':
      return {
        desc: '软件产品台账，支持永久、年限或账号等许可方式追踪。',
        rule: '软件按套销售，许可方式可选永久、年限或账号；可重复售卖类产品支持多次出售。',
      }
    case 'hardware':
      return {
        desc: '硬件集群产品台账，核入后登记，支持整机柜或单台交付。',
        rule: '硬件集群支持整机柜或单台交付，整机序列号交付管理。',
      }
    default:
      return { desc: '', rule: '' }
  }
})

</script>

<template>
  <div class="page-container">
    <!-- 页面头部：面包屑 + 标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <div class="crumb">产品及服务 / {{ boardName }}</div>
        <h1>{{ boardName }} · 产品台账</h1>
        <div class="desc">{{ boardMeta.desc }}</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button type="primary" :icon="Plus" :disabled="!canWrite" @click="goCreate">
              登记产品
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 业务规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>{{ boardMeta.rule }}</span>
    </div>

    <!-- 表格卡 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">产品台账</span>
        <span class="c">共 {{ list.length }} 条</span>
      </div>

      <!-- 卫星二级切换 -->
      <el-tabs v-if="board === 'satellite'" v-model="satelliteTab" class="sat-tabs">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="卫星 Token" name="token" />
        <el-tab-pane label="卫星数据" name="data" />
        <el-tab-pane label="遥感数据" name="remote" />
      </el-tabs>

      <!-- 筛选栏 -->
      <div class="toolbar">
        <!-- 加购对三角色均可用（含生态人员）；仅未勾选时禁用 -->
        <el-button
          type="success"
          :icon="ShoppingCart"
          :disabled="selectedAssets.length === 0"
          @click="batchAddToCart"
        >
          加入购物车{{ selectedAssets.length ? `（${selectedAssets.length}）` : '' }}
        </el-button>
        <el-input
          v-model="searchText"
          placeholder="搜索名称 / 编号 / 规格 / 类型"
          clearable
          style="width: 260px;"
          :prefix-icon="Search"
        />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px;">
          <el-option v-for="(s, k) in ASSET_STOCK_STATE" :key="k" :label="s.label" :value="k" />
        </el-select>
        <el-select v-model="subjectFilter" placeholder="全部主体" clearable style="width: 150px;">
          <el-option v-for="s in subjects" :key="s" :label="entityShort(s)" :value="s" />
        </el-select>
        <el-date-picker
          v-model="inboundMonth"
          type="month"
          value-format="YYYY-MM"
          placeholder="登记月份"
          style="width: 150px;"
        />
      </div>

      <!-- 表格 -->
      <el-table ref="tableRef" :data="list" border stripe @row-click="onRowClick" @selection-change="onSelectionChange" class="clickable">
        <el-table-column type="selection" width="44" align="center" />
        <el-table-column label="产品名称" min-width="220" align="left" class-name="asset-name-col">
          <template #default="{ row }">
            <!-- 整列分工：名称文字 = 跳详情页；列内其余区域（次级行/空白）= 切换该行勾选；全部 stop 阻断 row-click，本列绝不打开抽屉 -->
            <div class="asset-cell" @click.stop="toggleRow(row)">
              <span class="asset-name" @click.stop="goDetail(row)">{{ row.name }}</span>
              <!-- ADR-011：遥感数据行次级行显示 覆盖省份 · 明细数 摘要 -->
              <div class="asset-spec muted">
                <template v-if="row.type === '遥感数据'">{{ remoteSummary(row) }}</template>
                <template v-else>{{ row.spec || row.type }}</template>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :class="TYPE_TAG_CLASS[row.type] ?? 'tag-gray'">
              {{ row.type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所在主体" width="110" align="left" show-overflow-tooltip>
          <template #default="{ row }">{{ entityShort(row.subject) }}</template>
        </el-table-column>
        <el-table-column label="产品总数" width="110" align="center">
          <template #default="{ row }">
            <!-- ADR-011：遥感数据父产品显示明细数（quantity 对容器无意义；明细按期售卖 → 「N 期」） -->
            <template v-if="row.type === '遥感数据'">{{ rsCount(row) }} 期</template>
            <template v-else>{{ formatAssetQty(row, row.quantity) }} <span class="muted">{{ row.unit }}</span></template>
          </template>
        </el-table-column>
        <el-table-column label="锁定数量" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.lockedQty > 0" style="color: var(--primary-color); font-weight: 600;">{{ row.lockedQty }}</span>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="售卖数量" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.shippedQty > 0" style="color: var(--warning-color); font-weight: 600;">{{ row.shippedQty }}</span>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="销售单价" width="120" align="center" show-overflow-tooltip>
          <template #default="{ row }">{{ salePriceText(row) }}</template>
        </el-table-column>
        <el-table-column label="可用数量" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.repeatSale" size="small" type="success" effect="plain">重复售卖</el-tag>
            <span v-else style="font-weight: 600; color: var(--success-color);">{{ formatAssetQty(row, availableQty(row)) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="ASSET_STOCK_STATE[assetStockState(row)].tag" size="small" effect="light">
              {{ ASSET_STOCK_STATE[assetStockState(row)].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right" align="center">
          <template #default="{ row }">
            <!-- 单行加购对三角色均可用（含生态人员） -->
            <span class="op-tip" @click.stop>
              <el-button link type="success" size="small" @click.stop="singleAddToCart(row)">
                加入购物车
              </el-button>
            </span>
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip" @click.stop>
                <el-button link type="primary" size="small" :disabled="!canWrite" @click.stop="goEdit(row)">
                  编辑
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无产品，点击右上角「登记产品」" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 产品快览抽屉：行内核心参数，查看详情才进入详情页 -->
    <el-drawer v-model="drawerVisible" size="640px" class="asset-drawer">
      <template v-if="drawerAsset" #header>
        <div class="dr-head">
          <span class="dr-icon" aria-hidden="true"><el-icon><Box /></el-icon></span>
          <div class="dr-head-main">
            <div class="dr-title">
              <span class="dr-name">{{ drawerAsset.name }}</span>
              <el-tag :type="ASSET_STOCK_STATE[assetStockState(drawerAsset)].tag" size="small" effect="light">
                {{ ASSET_STOCK_STATE[assetStockState(drawerAsset)].label }}
              </el-tag>
              <el-tag size="small" effect="plain" :class="TYPE_TAG_CLASS[drawerAsset.type] ?? 'tag-gray'">
                {{ drawerAsset.type }}
              </el-tag>
            </div>
            <div class="dr-sub muted">
              {{ drawerAsset.code }} · {{ boardLabel(drawerAsset.board) }} · 主体 {{ entityShort(drawerAsset.subject) }}
            </div>
          </div>
          <el-icon class="dr-close" aria-hidden="true" @click="drawerVisible = false"><Close /></el-icon>
        </div>
      </template>

      <template v-if="drawerAsset">
        <!-- 数量进度（ADR-011：容器产品不展示；数字保留在图例，指标卡已移除） -->
        <div v-if="dProgress && !isRemote" class="dr-section">
          <div class="sec-title">数量进度</div>
          <div class="sec-desc muted">按数量扣减口径</div>
          <div class="dr-bar">
            <span class="seg seg-shipped" :style="{ width: dProgress.shippedPct }" />
            <span class="seg seg-locked" :style="{ width: dProgress.lockedPct }" />
            <span class="seg seg-avail" :style="{ width: dProgress.availPct }" />
          </div>
          <div class="dr-bar-legend muted">
            <span><i class="dot dot-shipped" />已交付 {{ drawerAsset.shippedQty }}</span>
            <span><i class="dot dot-locked" />锁定 {{ drawerAsset.lockedQty }}</span>
            <span><i class="dot dot-avail" />可售 {{ formatAssetQty(drawerAsset, availableQty(drawerAsset)) }}</span>
            <span class="bar-total">总数量 {{ formatAssetQty(drawerAsset, drawerAsset.quantity) }} {{ drawerAsset.unit }}</span>
          </div>
        </div>

        <!-- 可重复售卖说明（仅可重复产品；ADR-011：容器产品不展示） -->
        <div v-if="drawerAsset.repeatSale && !isRemote" class="dr-notice">
          <el-icon><InfoFilled /></el-icon>
          <span>可重复售卖：重复售卖不扣减原始数据量，按售卖次数与金额累计。</span>
        </div>

        <!-- 产品清单（全类型统一 15px 标题 + 弱说明） -->
        <div class="dr-section">
          <div class="sec-title">产品清单</div>
          <div class="sec-desc muted">销售记录产品清单文件，支持在线预览</div>
          <div v-if="drawerAsset.contractFile" class="contract-row">
            <el-icon class="contract-ic"><Document /></el-icon>
            <span class="contract-name">{{ fileDisplayName(drawerAsset.contractFile) }}</span>
            <span class="contract-sub">产品清单 · {{ contractKindLabel(drawerAsset) }}</span>
            <span class="contract-ops">
              <el-button size="small" type="primary" @click="openPreview">预览</el-button>
              <a :href="fileUrl(drawerAsset.contractFile)" download class="contract-dl">下载</a>
            </span>
          </div>
          <div v-else class="contract-empty muted">
            未上传产品清单
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <el-link
                type="primary"
                underline="never"
                :disabled="!canWrite"
                @click="goEdit(drawerAsset)"
              >
                去上传
              </el-link>
            </el-tooltip>
          </div>
        </div>

        <!-- 关键信息（全类型统一字段；repeatSale 产品与容器追加销售口径行，指标卡数字在此补偿） -->
        <div class="dr-section">
          <div class="sec-title">关键信息</div>
          <div class="sec-desc muted">产品基础信息与销售口径</div>
          <div class="info-grid info-grid-1">
            <div class="info-item">
              <span class="il">销售单价</span>
              <!-- 遥感容器：按明细定价（明细单价为权威口径） -->
              <span v-if="isRemote" class="iv iv-weak">按明细定价</span>
              <!-- ADR-017（2026-10-20）：包量定价产品单价与普通产品一致（元/份），删除「元/万Token」特判 -->
              <!-- ADR-018（PRICING-20261020）：有参考区间时追加区间提示（与列表列同口径） -->
              <span v-else class="iv">
                {{ drawerAsset.salePrice ? formatMoney(drawerAsset.salePrice) : '-' }}<template v-if="drawerAsset.repeatSale"> / {{ drawerAsset.unit }}</template>
                <template v-if="priceRangeText(drawerAsset)">（参考区间 {{ priceRangeText(drawerAsset) }}）</template>
              </span>
            </div>
            <div class="info-item">
              <span class="il">产品说明</span>
              <span class="iv">{{ drawerAsset.spec || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">登记时间</span>
              <span class="iv">{{ drawerAsset.inboundDate || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">有效期</span>
              <span class="iv">{{ expiryText(drawerAsset) }}</span>
            </div>
            <div v-if="drawerAsset.remark" class="info-item">
              <span class="il">备注</span>
              <span class="iv">{{ drawerAsset.remark }}</span>
            </div>
            <!-- repeatSale 普通产品：销售口径 2 行（对外页面不展示累计售卖金额，ADR-011） -->
            <template v-if="drawerAsset.repeatSale && !isRemote">
              <div class="info-item">
                <span class="il">数据规模</span>
                <span class="iv">{{ formatAssetQty(drawerAsset, drawerAsset.quantity) }} {{ drawerAsset.unit }}</span>
              </div>
              <div class="info-item">
                <span class="il">售卖次数</span>
                <span class="iv">{{ drawerAsset.soldCount }} 次</span>
              </div>
            </template>
            <!-- 遥感容器：明细销售口径 2 行（对外页面不展示累计售卖金额，ADR-011） -->
            <template v-if="isRemote">
              <div class="info-item">
                <span class="il">明细份数</span>
                <!-- PAGE-20261021：份数改用分页接口 total（dRsItems 已改分页，仅当前页） -->
                <span class="iv">{{ dRs.total }} 份</span>
              </div>
              <div class="info-item">
                <span class="il">已售次数</span>
                <span class="iv">{{ dRsSoldTotal }} 次</span>
              </div>
            </template>
          </div>
          <div v-if="boardMeta.rule" class="dr-rule muted">
            <el-icon><InfoFilled /></el-icon>
            <span>{{ boardMeta.rule }}</span>
          </div>
        </div>

        <!-- ADR-011：容器产品五段式第 3 段——可售明细 -->
        <div v-if="isRemote" class="dr-section">
          <div class="sec-title">可售明细</div>
          <div class="sec-desc muted">按 省 / 精度 / 月份 维护的可售子项（只计次不扣量）</div>
          <!-- PAGE-20261021：可售明细改服务端分页（el-pagination 照 settings/users.vue 先例）；「已售次数」改读后端 soldCount -->
          <el-table v-if="dRs.loading || dRs.items.length" v-loading="dRs.loading" :data="dRs.items" class="rs-table" size="small">
            <el-table-column label="省 / 市" min-width="150" align="left">
              <template #default="{ row }">{{ row.city ? `${row.province} / ${row.city}` : row.province }}</template>
            </el-table-column>
            <el-table-column label="精度" width="70" align="center">
              <template #default="{ row }">{{ row.resolution }}m</template>
            </el-table-column>
            <el-table-column label="月份" width="90" align="center" prop="saleMonth" />
            <el-table-column label="单价" width="110" align="center">
              <template #default="{ row }">{{ formatMoney(row.price) }}</template>
            </el-table-column>
            <el-table-column label="已售次数" width="80" align="center">
              <template #default="{ row }">{{ row.soldCount }}</template>
            </el-table-column>
          </el-table>
          <div v-if="dRs.total > 0" class="pagination">
            <el-pagination
              v-model:current-page="dRs.page"
              :page-size="dRs.pageSize"
              :total="dRs.total"
              layout="total, prev, pager, next"
              @current-change="onDrawerRsPageChange"
            />
          </div>
          <el-empty v-if="!dRs.loading && !dRs.items.length" description="暂无可售明细，请在产品详情维护" :image-size="56" />
        </div>

        <!-- 交付物（全类型统一 15px 标题 + 弱说明） -->
        <div class="dr-section">
          <div class="sec-title">
            交付物<span class="sec-count muted">（{{ dDeliverables.length }}）</span>
          </div>
          <div class="sec-desc muted">该类型标准交付包</div>
          <div class="dr-dels">
            <div v-for="d in dDeliverables" :key="d.id" class="del-row">
              <div class="del-main">
                <span class="del-name">{{ d.name }}</span>
                <el-tag :type="DELIVERABLE_STATUS[d.status].tag" size="small" effect="light">
                  {{ DELIVERABLE_STATUS[d.status].label }}
                </el-tag>
              </div>
              <div class="del-sub muted">
                {{ DELIVERABLE_CATEGORIES[d.category].label }}
                <template v-if="d.required"> · 必选</template>
                <template v-if="d.version"> · {{ d.version }}</template>
                <template v-if="d.updatedAt"> · 更新于 {{ d.updatedAt.slice(0, 10) }}</template>
              </div>
            </div>
            <el-empty v-if="!dDeliverables.length" description="该类型暂无交付物配置" :image-size="56" />
          </div>
        </div>

        <!-- 最近动态（全类型统一：操作日志 + 数量流水合并，细线时间线） -->
        <div class="dr-section">
          <div class="sec-title">最近动态</div>
          <div class="sec-desc muted">操作日志与数量流水合并，倒序前 10 条 · 关联销售 {{ dProjects.length }} 项</div>
          <div v-if="dActivities.length" class="rs-tl">
            <div v-for="act in dActivities" :key="act.key" class="rs-tl-item">
              <span class="rs-tl-dot" :class="act.kind" aria-hidden="true"></span>
              <div class="rs-tl-title">
                <span class="rs-tl-time muted">{{ act.time }}</span>
                <span class="rs-tl-text">{{ act.title }}</span>
              </div>
              <div v-if="act.operator" class="rs-tl-op muted">操作人：{{ act.operator }}</div>
            </div>
          </div>
          <div v-else class="muted" style="font-size: 13px;">暂无动态记录</div>
        </div>
      </template>

      <template #footer>
        <div class="dr-footer">
          <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
            <el-button v-if="drawerAsset" :disabled="!canWrite" @click="goEdit(drawerAsset)">编辑</el-button>
          </el-tooltip>
          <!-- ADR-020（PRICING-20261020）：「登记销售」直接下单入口已移除，下单统一走购物车 -->
          <el-button v-if="drawerAsset" type="primary" @click="goDetail(drawerAsset)">
            查看详情
          </el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="previewVisible" title="产品清单预览" fullscreen append-to-body destroy-on-close>
      <FilePreview
        v-if="previewVisible && drawerAsset?.contractFile"
        :filename="drawerAsset.contractFile"
      />
    </el-dialog>

    <!-- ADR-011：遥感数据明细选择弹窗（加购用途；ADR-020：登记销售入口已移除） -->
    <RsItemPicker
      v-if="rsPickerAsset"
      v-model="rsPickerVisible"
      :parent-asset="rsPickerAsset"
      @confirm="onRsPickerConfirm"
    />
  </div>
</template>

<style scoped>
.s-unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
}
.sat-tabs {
  margin: -4px 0 8px;
}
/* 名称列单元格：作为定位上下文，::before 铺满整格（含上下 padding 与垂直居中留白），空白处点击也命中根容器（= 切换勾选） */
.clickable :deep(td.asset-name-col) {
  position: relative;
}
.asset-cell::before {
  content: '';
  position: absolute;
  inset: 0;
  cursor: pointer;
}
.asset-cell {
  display: block;
  cursor: pointer;
}
/* 名称文字 = 真链接：跳详情页，hover 下划线；relative 使其绘制在 ::before 之上，点击命中名称本身 */
.asset-name {
  position: relative;
  font-weight: 500;
  font-size: 13px;
  color: var(--primary-color);
  cursor: pointer;
}
.asset-name:hover {
  text-decoration: underline;
}
/* 次级行点击 = 切换勾选（走根容器事件） */
.asset-spec {
  font-size: 12px;
  margin-top: 2px;
  cursor: pointer;
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
/* 操作列按钮包在 tooltip span 内，间距由 inline-flex 保证（不依赖相邻按钮选择器） */
.op-tip {
  display: inline-flex;
  margin-left: 8px;
}
.op-tip:first-child {
  margin-left: 0;
}
</style>

<!-- 抽屉样式（非 scoped：抽屉内容挂载到 body，scoped 选择器无法命中） -->
<style>
/* ============ 产品快览抽屉 ============ */
.asset-drawer .el-drawer__header {
  margin-bottom: 0;
  padding: 16px 20px;
  border-bottom: 1px solid var(--divider-color);
}
.asset-drawer .el-drawer__body {
  padding: 16px 20px 12px;
  overflow-y: auto;
}
.asset-drawer .el-drawer__footer {
  padding: 12px 20px;
  border-top: 1px solid var(--divider-color);
}

/* 头部：图标 + 名称/编号 + 关闭 */
.asset-drawer .dr-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
}
.asset-drawer .dr-icon {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  margin-top: 2px;
  border-radius: 7px;
  background: var(--primary-light);
  color: var(--primary-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.asset-drawer .dr-head-main {
  flex: 1;
  min-width: 0;
}
.asset-drawer .dr-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.asset-drawer .dr-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 24px;
}
.asset-drawer .dr-sub {
  margin-top: 4px;
  font-size: 12px;
}
.asset-drawer .dr-close {
  flex-shrink: 0;
  font-size: 16px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
}
.asset-drawer .dr-close:hover {
  background: var(--sidebar-hover);
  color: var(--text-primary);
}

/* 分区（全类型统一 15px 标题 + 弱说明） */
.asset-drawer .dr-section {
  margin-bottom: 18px;
}
.asset-drawer .sec-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.asset-drawer .sec-count {
  font-weight: 400;
  font-size: 12px;
  margin-left: 2px;
}

/* 数量进度条 */
.asset-drawer .dr-bar {
  display: flex;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--divider-color);
}
.asset-drawer .seg {
  height: 100%;
}
.asset-drawer .seg-shipped {
  background: var(--warning-color);
}
.asset-drawer .seg-locked {
  background: var(--primary-color);
}
.asset-drawer .seg-avail {
  background: var(--success-color);
}
.asset-drawer .dr-bar-legend {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 8px;
  font-size: 12px;
}
.asset-drawer .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
.asset-drawer .dot-shipped {
  background: var(--warning-color);
}
.asset-drawer .dot-locked {
  background: var(--primary-color);
}
.asset-drawer .dot-avail {
  background: var(--success-color);
}
.asset-drawer .bar-total {
  margin-left: auto;
}

/* 可重复售卖说明条 */
.asset-drawer .dr-notice {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  background: #eef4ff;
  border: 1px solid rgba(23, 105, 212, 0.15);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 18px;
}
.asset-drawer .dr-notice .el-icon {
  color: var(--primary-color);
  margin-top: 1px;
  flex-shrink: 0;
}
/* 产品清单 */
.asset-drawer .contract-row {
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid var(--divider-color);
  border-radius: 8px;
  padding: 10px 12px;
}
.asset-drawer .contract-ic {
  color: var(--primary-color);
  font-size: 18px;
  flex-shrink: 0;
}
.asset-drawer .contract-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-drawer .contract-sub {
  flex-shrink: 0;
  font-size: 12px;
  color: #9aa9bf;
}
.asset-drawer .contract-ops {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}
.asset-drawer .contract-dl {
  font-size: 12px;
  color: var(--primary-color);
  text-decoration: none;
}
.asset-drawer .contract-dl:hover {
  text-decoration: underline;
}
.asset-drawer .contract-empty {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 该类产品业务规则提示 */
.asset-drawer .dr-rule {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.6;
  border-top: 1px dashed var(--divider-color);
}
.asset-drawer .dr-rule .el-icon {
  color: var(--primary-color);
  margin-top: 1px;
  flex-shrink: 0;
}

/* 交付物列表 */
.asset-drawer .dr-dels {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--divider-color);
  border-radius: 8px;
}
.asset-drawer .del-row {
  padding: 8px 12px;
  border-bottom: 1px solid var(--divider-color);
}
.asset-drawer .del-row:last-child {
  border-bottom: none;
}
.asset-drawer .del-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.asset-drawer .del-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-drawer .del-sub {
  margin-top: 3px;
  font-size: 12px;
}

/* 底部操作 */
.asset-drawer .dr-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

/* ============ 抽屉分区弱说明（全类型统一） ============ */
.asset-drawer .sec-desc {
  font-size: 12px;
  font-weight: 400;
  margin: -4px 0 10px;
}
/* 关键信息弱值（如遥感容器「按明细定价」） */
.asset-drawer .iv-weak {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 可售明细表格：无竖线（默认即无 border），行 hover 平台浅蓝 */
.asset-drawer .rs-table .el-table__cell {
  padding: 8px 0;
}
.asset-drawer .rs-table .el-table__body tr:hover > td.el-table__cell {
  background: #f8fbff;
}

/* 最近动态细线时间线（参考平台细线风格，勿用 EP 默认时间线配色） */
.asset-drawer .rs-tl {
  padding-left: 14px;
}
.asset-drawer .rs-tl-item {
  position: relative;
  padding-bottom: 12px;
}
.asset-drawer .rs-tl-item:last-child {
  padding-bottom: 0;
}
.asset-drawer .rs-tl-item::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 6px;
  bottom: 0;
  width: 1px;
  background: var(--divider-color);
}
.asset-drawer .rs-tl-item:last-child::before {
  display: none;
}
.asset-drawer .rs-tl-dot {
  position: absolute;
  left: -17px;
  top: 4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #9aa9bf;
}
.asset-drawer .rs-tl-dot.flow {
  background: var(--primary-color);
}
.asset-drawer .rs-tl-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}
.asset-drawer .rs-tl-time {
  flex-shrink: 0;
  font-size: 12px;
  width: 84px;
}
.asset-drawer .rs-tl-text {
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.asset-drawer .rs-tl-op {
  margin-top: 2px;
  font-size: 12px;
}
</style>
