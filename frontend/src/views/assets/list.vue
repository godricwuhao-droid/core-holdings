<script setup lang="ts">
/**
 * 资产管理 - 板块列表页（具身智能 / 卫星服务 / 软件库存 / 硬件库存）
 *
 * 卫星服务板块顶部增加二级切换：卫星 Token / 卫星数据
 * 筛选：名称搜索 / 状态 / 主体 / 入库日期
 */
import { computed, ref, watch } from 'vue'
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
  formatMoney,
  formatWan,
  noSellableStock,
  TYPE_TAG_CLASS,
  type Asset,
  type AssetStockState,
  type Board,
} from '@/types'
import {
  addCartBatch,
  addToCart,
  assetFlows,
  createSaleOrder,
  db,
  fileUrl,
  getAssetDeliverables,
  projectItemsOfAsset,
  refresh,
  type OrderFields,
} from '@/api'
import FilePreview from '@/components/FilePreview.vue'
import SalesOrderDialog from '@/components/SalesOrderDialog.vue'
import { canWrite, READONLY_TIP } from '@/auth'
import type { OrderItem } from '@/components/SalesOrderDialog.vue'

const route = useRoute()
const router = useRouter()

const board = computed<Board>(() => (route.params.board as Board) || 'embodied')

const boardName = computed(() => boardLabel(board.value))

// 卫星二级切换
const satelliteTab = ref<'all' | 'token' | 'data'>('all')

// 筛选
const searchText = ref('')
const statusFilter = ref<AssetStockState | ''>('')
const subjectFilter = ref('')
const inboundMonth = ref('')

// 切换板块时重置二级切换与筛选条件，避免残留上一板块的筛选值
watch(board, () => {
  satelliteTab.value = 'all'
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

function goEdit(a: Asset) {
  if (noSellableStock(a)) {
    ElMessage.warning('该资产当前无可售库存（可售数量为 0）。可继续编辑补入库或核对锁定 / 售出情况。')
  }
  router.push(`/assets/${a.id}/edit`)
}

/** 从资产快览打开下单对话框（与购物车下单同一表单，单资产 + 数量） */
const saleItem = ref<OrderItem | null>(null)
const saleVisible = ref(false)
const saleLoading = ref(false)
const saleItems = computed(() => (saleItem.value ? [saleItem.value] : []))

function goRegisterSale(a: Asset) {
  if (noSellableStock(a)) {
    ElMessage.warning('该资产当前无可售库存（可售数量为 0），无法登记销售。请待库存释放（取消锁定或补充入库）后再操作。')
    return
  }
  saleItem.value = { asset: a, qty: 1 }
  saleVisible.value = true
}

async function onSaleSubmit(payload: { fields: OrderFields; items: { assetId: number; qty: number }[] }) {
  saleLoading.value = true
  try {
    const p = await createSaleOrder({ ...payload.fields, items: payload.items })
    saleVisible.value = false
    drawerVisible.value = false
    ElMessage.success(`下单成功，已生成销售项目 ${p.code}（进行中）`)
    await refresh(true)
    router.push(`/sales/projects/${p.id}/detail`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '下单失败')
    await refresh(true)
  } finally {
    saleLoading.value = false
  }
}

function goCreate() {
  router.push({ path: '/assets/create', query: { board: board.value } })
}

// ---- 快览抽屉：点击行打开，「查看详情」才跳详情页 ----
const drawerVisible = ref(false)
const drawerAsset = ref<Asset | null>(null)

function openDrawer(row: Asset) {
  drawerAsset.value = row
  drawerVisible.value = true
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

async function singleAddToCart(a: Asset) {
  if (noSellableStock(a)) {
    ElMessage.warning(`「${a.name}」暂无可售库存，无法加入购物车`)
    return
  }
  try {
    await addToCart(a.id, 1)
    ElMessage.success(`「${a.name}」已加入购物车`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加入购物车失败')
  }
}

async function batchAddToCart() {
  const items = selectedAssets.value.map((a) => ({ assetId: a.id, qty: 1 }))
  if (!items.length) return
  try {
    const res = await addCartBatch(items)
    if (res.skipped.length) {
      const names = res.skipped.map((s) => `${s.name}（${s.reason}）`).join('、')
      ElMessage.warning(`已加入 ${res.addedCount} 项，${res.skipped.length} 项因库存不足未加入：${names}`)
    } else {
      ElMessage.success(`已将 ${res.addedCount} 项资产加入购物车`)
    }
    clearSelection()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加入购物车失败')
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
const dFlows = computed(() => {
  if (!drawerAsset.value) return []
  return assetFlows(drawerAsset.value.id)
    .slice()
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 4)
})
const dProjects = computed(() =>
  drawerAsset.value ? projectItemsOfAsset(drawerAsset.value.id) : [],
)

/** 库存进度分段（不可重复售卖时展示） */
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
        desc: '机器人、数采设备与平台软件资产的入库登记、库存与销售追踪统一台账。',
        rule: '机器人资产默认整机交付，可选序列号出库管理；数采设备按套入库与销售。',
      }
    case 'satellite':
      return {
        desc: '卫星 Token 与卫星数据资产的销售台账，按额度与批次追踪销售进度。',
        rule: '卫星数据默认支持重复售卖，不随销售出库扣减原始数据量；卫星 Token 按额度与有效期管理。',
      }
    case 'software':
      return {
        desc: '软件资产台账，支持永久、年限或账号等许可方式追踪。',
        rule: '软件按套销售，许可方式可选永久、年限或账号；可重复售卖类资产支持多次出售。',
      }
    case 'hardware':
      return {
        desc: '硬件集群资产台账，核入入库后登记，支持整机柜或单台交付。',
        rule: '硬件集群支持整机柜或单台交付，整机序列号出库管理。',
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
        <div class="crumb">资产管理 / {{ boardName }}</div>
        <h1>{{ boardName }} · 资产台账</h1>
        <div class="desc">{{ boardMeta.desc }}</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button type="primary" :icon="Plus" :disabled="!canWrite" @click="goCreate">
              登记资产
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
        <span class="t">资产台账</span>
        <span class="c">共 {{ list.length }} 条</span>
      </div>

      <!-- 卫星二级切换 -->
      <el-tabs v-if="board === 'satellite'" v-model="satelliteTab" class="sat-tabs">
        <el-tab-pane label="全部" name="all" />
        <el-tab-pane label="卫星 Token" name="token" />
        <el-tab-pane label="卫星数据" name="data" />
      </el-tabs>

      <!-- 筛选栏 -->
      <div class="toolbar">
        <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button
              type="success"
              :icon="ShoppingCart"
              :disabled="!canWrite || selectedAssets.length === 0"
              @click="batchAddToCart"
            >
              加入购物车{{ selectedAssets.length ? `（${selectedAssets.length}）` : '' }}
            </el-button>
          </span>
        </el-tooltip>
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
          placeholder="入库月份"
          style="width: 150px;"
        />
      </div>

      <!-- 表格 -->
      <el-table ref="tableRef" :data="list" border stripe @row-click="openDrawer" @selection-change="onSelectionChange" class="clickable">
        <el-table-column type="selection" width="44" align="center" />
        <el-table-column label="资产名称" min-width="220" align="left">
          <template #default="{ row }">
            <el-tooltip content="点击名称进入资产详情" placement="top">
              <span class="asset-name" @click.stop="goDetail(row)">{{ row.name }}</span>
            </el-tooltip>
            <div class="asset-spec muted">{{ row.spec || row.type }}</div>
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
        <el-table-column label="资产总数" width="100" align="center">
          <template #default="{ row }">
            {{ formatWan(row.quantity) }} <span class="muted">{{ row.unit }}</span>
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
        <el-table-column label="库存数量" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.repeatSale" size="small" type="success" effect="plain">重复售卖</el-tag>
            <span v-else style="font-weight: 600; color: var(--success-color);">{{ formatWan(availableQty(row)) }}</span>
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
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip" @click.stop>
                <el-button link type="success" size="small" :disabled="!canWrite" @click.stop="singleAddToCart(row)">
                  加入购物车
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip" @click.stop>
                <el-button link type="primary" size="small" :disabled="!canWrite" @click.stop="goEdit(row)">
                  编辑
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无资产，点击右上角「登记资产」" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 资产快览抽屉：行内核心参数，查看详情才进入详情页 -->
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
        <!-- 核心指标（按资产类型差异化） -->
        <div class="dr-metrics" :class="{ 'dr-metrics-3': drawerAsset.repeatSale }">
          <template v-if="!drawerAsset.repeatSale">
            <div class="m-cell">
              <div class="m-label">入库</div>
              <div class="m-value">{{ formatWan(drawerAsset.quantity) }}<span class="m-unit">{{ drawerAsset.unit }}</span></div>
            </div>
            <div class="m-cell">
              <div class="m-label">锁定</div>
              <div class="m-value">{{ formatWan(drawerAsset.lockedQty) }}<span class="m-unit">{{ drawerAsset.unit }}</span></div>
            </div>
            <div class="m-cell">
              <div class="m-label">已售</div>
              <div class="m-value">{{ formatWan(drawerAsset.shippedQty) }}<span class="m-unit">{{ drawerAsset.unit }}</span></div>
            </div>
            <div class="m-cell m-hl">
              <div class="m-label">可售</div>
              <div class="m-value">{{ formatWan(availableQty(drawerAsset)) }}<span class="m-unit">{{ drawerAsset.unit }}</span></div>
            </div>
          </template>
          <template v-else>
            <div class="m-cell">
              <div class="m-label">数据规模</div>
              <div class="m-value">{{ formatWan(drawerAsset.quantity) }}<span class="m-unit">{{ drawerAsset.unit }}</span></div>
            </div>
            <div class="m-cell">
              <div class="m-label">售卖次数</div>
              <div class="m-value">{{ drawerAsset.soldCount }}<span class="m-unit">次</span></div>
            </div>
            <div class="m-cell m-hl">
              <div class="m-label">累计售卖金额</div>
              <div class="m-value">{{ formatMoney(drawerAsset.soldAmount) }}</div>
            </div>
          </template>
        </div>

        <!-- 库存进度 -->
        <div v-if="dProgress" class="dr-section">
          <div class="sec-title">库存进度</div>
          <div class="dr-bar">
            <span class="seg seg-shipped" :style="{ width: dProgress.shippedPct }" />
            <span class="seg seg-locked" :style="{ width: dProgress.lockedPct }" />
            <span class="seg seg-avail" :style="{ width: dProgress.availPct }" />
          </div>
          <div class="dr-bar-legend muted">
            <span><i class="dot dot-shipped" />已出库 {{ drawerAsset.shippedQty }}</span>
            <span><i class="dot dot-locked" />锁定 {{ drawerAsset.lockedQty }}</span>
            <span><i class="dot dot-avail" />可售 {{ formatWan(availableQty(drawerAsset)) }}</span>
            <span class="bar-total">入库合计 {{ formatWan(drawerAsset.quantity) }} {{ drawerAsset.unit }}</span>
          </div>
        </div>

        <!-- 可重复售卖说明（仅可重复资产） -->
        <div v-if="drawerAsset.repeatSale" class="dr-notice">
          <el-icon><InfoFilled /></el-icon>
          <span>可重复售卖：重复售卖不扣减原始数据量，按售卖次数与金额累计。</span>
        </div>

        <!-- 产品清单 -->
        <div class="dr-section">
          <div class="sec-title">产品清单</div>
          <div v-if="drawerAsset.contractFile" class="contract-row">
            <el-icon class="contract-ic"><Document /></el-icon>
            <span class="contract-name">产品清单（{{ contractKindLabel(drawerAsset) }}）</span>
            <span class="contract-ops">
              <el-button size="small" type="primary" @click="openPreview">预览</el-button>
              <a :href="fileUrl(drawerAsset.contractFile)" download class="contract-dl">下载</a>
            </span>
          </div>
          <div v-else class="contract-empty muted">
            未上传产品清单
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
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

        <!-- 关键信息 -->
        <div class="dr-section">
          <div class="sec-title">关键信息</div>
          <div class="info-grid info-grid-1">
            <div class="info-item">
              <span class="il">销售单价</span>
              <span class="iv">{{ drawerAsset.salePrice ? formatMoney(drawerAsset.salePrice) : '-' }}<template v-if="drawerAsset.repeatSale"> / {{ drawerAsset.unit }}</template></span>
            </div>
            <div class="info-item">
              <span class="il">产品说明</span>
              <span class="iv">{{ drawerAsset.spec || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">入库时间</span>
              <span class="iv">{{ drawerAsset.inboundDate || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">有效期</span>
              <span class="iv">{{ expiryText(drawerAsset) }}</span>
            </div>
          </div>
          <div v-if="boardMeta.rule" class="dr-rule muted">
            <el-icon><InfoFilled /></el-icon>
            <span>{{ boardMeta.rule }}</span>
          </div>
        </div>

        <!-- 交付物 -->
        <div class="dr-section">
          <div class="sec-title">
            交付物<span class="sec-count muted">（{{ dDeliverables.length }}）</span>
          </div>
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

        <!-- 最近动态 -->
        <div class="dr-section">
          <div class="sec-title">
            最近动态<span class="sec-count muted">（关联销售 {{ dProjects.length }} 项）</span>
          </div>
          <div class="dr-flows">
            <div v-for="f in dFlows" :key="f.id" class="flow-row">
              <span class="flow-date muted">{{ f.date.slice(0, 10) }}</span>
              <el-tag :type="FLOW_TYPES[f.type].tag" size="small" effect="plain">
                {{ FLOW_TYPES[f.type].label }}
              </el-tag>
              <span class="flow-note muted">{{ f.ref || f.note || '-' }}</span>
            </div>
            <div v-if="!dFlows.length" class="muted" style="font-size: 13px;">暂无流水记录</div>
          </div>
        </div>
      </template>

      <template #footer>
        <div class="dr-footer">
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <el-button v-if="drawerAsset" :disabled="!canWrite" @click="goEdit(drawerAsset)">编辑</el-button>
          </el-tooltip>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <el-button v-if="drawerAsset" type="success" :disabled="!canWrite" @click="goRegisterSale(drawerAsset)">
              销售
            </el-button>
          </el-tooltip>
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
        :title="`产品清单（${contractKindLabel(drawerAsset)}）`"
      />
    </el-dialog>

    <!-- 资产直接下单（与购物车下单同一表单，单资产 + 数量） -->
    <SalesOrderDialog
      v-model="saleVisible"
      title="销售下单"
      :items="saleItems"
      :allow-qty-edit="true"
      :loading="saleLoading"
      @submit="onSaleSubmit"
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
.asset-name {
  font-weight: 500;
  font-size: 13px;
  color: var(--primary-color);
  cursor: pointer;
}
.asset-name:hover {
  text-decoration: underline;
}
.asset-spec {
  font-size: 12px;
  margin-top: 2px;
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
/* ============ 资产快览抽屉 ============ */
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

/* 关键数字 */
.asset-drawer .dr-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 18px;
}
.asset-drawer .m-cell {
  background: #f8fafc;
  border: 1px solid var(--divider-color);
  border-radius: 8px;
  padding: 10px 12px;
}
.asset-drawer .m-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.asset-drawer .m-value {
  margin-top: 4px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.asset-drawer .m-unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 2px;
}
.asset-drawer .m-purple {
  color: var(--info-purple);
}
.asset-drawer .m-hl {
  background: #eaf8f1;
  border-color: rgba(12, 123, 81, 0.25);
}
.asset-drawer .m-hl .m-value {
  color: #0c7b51;
}
.asset-drawer .dr-metrics-3 {
  grid-template-columns: repeat(3, 1fr);
}

/* 分区 */
.asset-drawer .dr-section {
  margin-bottom: 18px;
}
.asset-drawer .sec-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.asset-drawer .sec-count {
  font-weight: 400;
  font-size: 12px;
  margin-left: 2px;
}

/* 库存进度条 */
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
/* 该类资产业务规则提示 */
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

/* 最近动态 */
.asset-drawer .flow-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--divider-color);
  font-size: 13px;
}
.asset-drawer .flow-row:last-child {
  border-bottom: none;
}
.asset-drawer .flow-date {
  flex-shrink: 0;
  font-size: 12px;
}
.asset-drawer .flow-note {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 底部操作 */
.asset-drawer .dr-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
