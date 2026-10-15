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
  formatMoney,
  formatWan,
  noSellableStock,
  tagInfo,
  type DeliverableCategory,
  type FlowType,
} from '@/types'
import {
  addAssetDeliverable,
  assetFlows,
  deleteAsset,
  getAsset,
  getAssetDeliverables,
  getFeatureCatalog,
  projectItemsOfAsset,
  updateAssetDeliverable,
  db,
} from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

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
function goRegisterSale() {
  if (!asset.value) return
  if (noSellableStock(asset.value)) {
    ElMessage.warning('该资产当前无可售库存（可售数量为 0），无法登记销售。请待库存释放（取消锁定或补充入库）后再操作。')
    return
  }
  router.push({ path: '/sales/projects/create', query: { assetId: String(asset.value.id) } })
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
  { t: '项目关联', d: '销售人员在销售项目中选择资产及数量。' },
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

// ---- 功能清单（结构化模块树）----
const featureDialog = ref(false)
const featureCatalog = computed(() => getFeatureCatalog(asset.value?.type ?? ''))
const activeModule = ref(0)
const activeSub = ref(0)

function openFeature(delName: string) {
  if (featureCatalog.value.length === 0) {
    ElMessage.info('该资产类型暂未配置结构化功能清单')
    return
  }
  void delName
  activeModule.value = 0
  activeSub.value = 0
  featureDialog.value = true
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
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
              <span>
                <el-button plain :icon="Link" :disabled="!canWrite" @click="goRegisterSale">登记销售</el-button>
              </span>
            </el-tooltip>
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
                    <span class="iv">{{ formatWan(asset.quantity) }} {{ asset.unit }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">可售数量</span>
                    <span class="iv">{{ asset.repeatSale ? '不限' : `${formatWan(availableQty(asset))} ${asset.unit}` }}</span>
                  </div>
                  <div class="info-item">
                    <span class="il">销售单价</span>
                    <span class="iv">{{ asset.salePrice ? formatMoney(asset.salePrice) : '-' }}<template v-if="asset.repeatSale"> / {{ asset.unit }}</template></span>
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
                      <a
                        v-if="d.category === 'feature'"
                        class="dl-link"
                        @click.stop="openFeature(d.name)"
                      >
                        查看功能清单
                      </a>
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
                    <div class="muted" style="font-size: 12px;">{{ row.project.code }}</div>
                  </template>
                </el-table-column>
                <el-table-column prop="project.customer" label="客户名称" width="150" show-overflow-tooltip />
                <el-table-column label="销售人员" width="110" align="left">
                  <template #default="{ row }">{{ row.project.rep || '-' }}</template>
                </el-table-column>
                <el-table-column label="关联数量" width="110" align="right">
                  <template #default="{ row }">{{ formatWan(row.item.qty) }} {{ row.item.unit }}</template>
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
                <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                  <span>
                    <el-button v-if="!isWipBoard()" type="primary" size="small" :disabled="!canWrite" @click="goRegisterSale">
                      登记销售
                    </el-button>
                  </span>
                </el-tooltip>
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
                    </div>
                    <div class="fl-desc">
                      {{ asset.name }} · {{ FLOW_TYPES[f.type].label }} {{ formatWan(f.qty) }} {{ f.unit }}
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
        width="560px"
        :close-on-click-modal="false"
      >
        <el-form label-width="90px">
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
          <el-button v-if="viewing?.category === 'feature'" @click="openFeature(viewing.name)">
            查看功能清单
          </el-button>
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

      <!-- 功能清单：左侧模块树 + 右侧能力详情 -->
      <el-dialog
        v-model="featureDialog"
        :title="`产品功能清单 · ${asset.name}`"
        width="880px"
        :close-on-click-modal="false"
      >
        <div class="feature-layout">
          <div class="feature-tree">
            <div v-for="(m, mi) in featureCatalog" :key="m.name" class="ft-group">
              <div class="ft-l1">{{ m.name }}</div>
              <div
                v-for="(s, si) in m.subs"
                :key="s.name"
                class="ft-l2"
                :class="{ active: mi === activeModule && si === activeSub }"
                @click="activeModule = mi; activeSub = si"
              >
                {{ s.name }}（{{ s.capabilities.length }}）
              </div>
            </div>
          </div>
          <div
            v-if="featureCatalog[activeModule]?.subs[activeSub]"
            class="feature-detail"
          >
            <div class="fd-head">
              <div class="card-title">{{ featureCatalog[activeModule].subs[activeSub].name }}</div>
              <div class="card-desc">共 {{ featureCatalog[activeModule].subs[activeSub].capabilities.length }} 项能力</div>
            </div>
            <div
              v-for="cap in featureCatalog[activeModule].subs[activeSub].capabilities"
              :key="cap.name"
              class="cap-card"
            >
              <div class="cap-name">{{ cap.name }}</div>
              <div class="cap-block">
                <div class="cap-label muted">功能说明</div>
                <div class="cap-text">{{ cap.desc }}</div>
              </div>
              <div class="cap-block value">
                <div class="cap-label">核心价值</div>
                <div class="cap-text">{{ cap.value }}</div>
              </div>
            </div>
          </div>
        </div>
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

/* ============ 功能清单 ============ */
.feature-layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 16px;
  min-height: 420px;
}
@media (max-width: 860px) {
  .feature-layout {
    grid-template-columns: 1fr;
  }
}
.feature-tree {
  border-right: 1px solid var(--divider-color);
  padding-right: 12px;
}
@media (max-width: 860px) {
  .feature-tree {
    border-right: none;
    border-bottom: 1px solid var(--divider-color);
    padding-right: 0;
    padding-bottom: 12px;
  }
}
.ft-group {
  margin-bottom: 12px;
}
.ft-l1 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}
.ft-l2 {
  font-size: 13px;
  color: var(--text-body);
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-left: 4px;
}
.ft-l2:hover {
  background: var(--row-hover);
}
.ft-l2.active {
  background: var(--primary-light);
  color: var(--primary-color);
  font-weight: 500;
}
.feature-detail {
  min-width: 0;
}
.fd-head {
  margin-bottom: 12px;
}
.cap-card {
  border: 1px solid var(--divider-color);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.cap-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
}
.cap-block {
  margin-bottom: 10px;
}
.cap-block:last-child {
  margin-bottom: 0;
}
.cap-label {
  font-size: 12px;
  margin-bottom: 3px;
}
.cap-block.value .cap-label {
  color: var(--primary-color);
}
.cap-block.value {
  background: #f5f9ff;
  border-left: 3px solid #cfe0f5;
  border-radius: 4px;
  padding: 8px 10px;
}
.cap-text {
  font-size: 13px;
  color: var(--text-body);
  line-height: 1.6;
}
</style>
