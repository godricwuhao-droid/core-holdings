<script setup lang="ts">
/**
 * 销售管理 - 销售项目列表
 *
 * 列：编号/名称/关联合同（合同数，tooltip 列客户）/生态人员/状态/合同金额/关联资产数/预计签约日期/最近跟进日期
 * （项目级「主体」列已移除：多合同多主体，项目 subject 恒为空/无意义；合同卡内主体 tag 保留）
 * （金额列仅保留「合同金额」，元值 formatMoney 直显）
 * 快览抽屉：点击行打开（交互对齐资产列表），聚焦项目概览 + 合同清单（只读）；
 * 「查看详情」跳项目详情页（交付/终止等合同操作仍在详情页进行）。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, InfoFilled, Plus, Search, Tickets } from '@element-plus/icons-vue'
import {
  PROJECT_STATUS,
  entityShort,
  formatDate,
  formatMoney,
  tagInfo,
  type Contract,
  type ContractItem,
  type Project,
  type ProjectStatus,
} from '@/types'
import { db, deleteProject, getAsset } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

const router = useRouter()

const searchText = ref('')
const statusFilter = ref<ProjectStatus | ''>('')
const repFilter = ref('')

const reps = computed(() =>
  Array.from(new Set([...db.projects.map((p) => p.rep), ...db.reps.map((r) => r.name)]))
    .filter(Boolean)
    .map(String),
)

const list = computed(() =>
  db.projects.filter((p) => {
    const kw = searchText.value.trim()
    if (kw && !`${p.name}${p.code}${p.customer}`.includes(kw)) return false
    if (statusFilter.value && p.status !== statusFilter.value) return false
    if (repFilter.value && p.rep !== repFilter.value) return false
    return true
  }),
)

function goEdit(p: Project) {
  router.push(`/sales/projects/${p.id}/edit`)
}

/** 关联合同列 tooltip：客户信息承载位（客户列已并入本列）——多合同「N 位客户：A、B、C」；单合同直接客户名；无客户名 → 空串（不渲染 tooltip） */
function contractTip(p: Project): string {
  const names = db.contracts
    .filter((c) => c.projectId === p.id)
    .map((c) => c.customer)
    .filter(Boolean)
  if (!names.length) return ''
  return names.length > 1 ? `${names.length} 位客户：${names.join('、')}` : names[0]
}

/**
 * 编辑按钮可见性（对齐后端 PUT /projects 400 规则，ADR-007）：
 * - 有合同项目：名下**无 delivered 合同**且项目非 terminated → 可编辑
 *   （全 terminated 项目派生 status=terminated，一并禁用；混合 active+terminated 无 delivered → 可编辑）
 * - 存量无合同项目（contractCount=0/缺失）：沿用原 status==='active' 判定
 */
function canEditProject(p: Project): boolean {
  if (!p.contractCount) return p.status === 'active'
  const contracts = db.contracts.filter((c) => c.projectId === p.id)
  return contracts.every((c) => c.status !== 'delivered') && p.status !== 'terminated'
}

function goDetail(p: Project) {
  router.push(`/sales/projects/${p.id}/detail`)
}

// ---- 快览抽屉：点击行打开（交互对齐资产列表），「查看详情」才跳详情页 ----
const drawerVisible = ref(false)
const drawerProject = ref<Project | null>(null)

function openDrawer(row: Project) {
  drawerProject.value = row
  drawerVisible.value = true
}

/** 项目名下合同（bootstrap.contracts 按 projectId 过滤，按合同编号 code 升序） */
const dContracts = computed<Contract[]>(() => {
  const p = drawerProject.value
  if (!p) return []
  return db.contracts.filter((c) => c.projectId === p.id).sort((a, b) => a.code.localeCompare(b.code))
})

/** 合同明细单项资产名（第二层逐行展示用） */
function contractItemName(it: ContractItem): string {
  return it.assetId ? getAsset(it.assetId)?.name ?? '未关联资产' : '未关联资产'
}

/** 锁定/交付日期（取明细首个非空值，口径与详情页合同卡片一致） */
function contractDates(c: Contract): string {
  const locked = c.items.find((it) => it.lockedDate)?.lockedDate
  const shipped = c.items.find((it) => it.shippedDate)?.shippedDate
  const parts: string[] = []
  if (locked) parts.push(`锁定 ${formatDate(locked)}`)
  if (shipped) parts.push(`交付 ${formatDate(shipped)}`)
  return parts.join(' · ')
}

/** 存量无合同项目的旧明细摘要（兜底展示一行，口径对齐详情页存量明细） */
const legacyItemSummary = computed(() => {
  const p = drawerProject.value
  if (!p) return ''
  return p.items
    .map((it) => `${it.assetId ? getAsset(it.assetId)?.name ?? '未关联资产' : '未关联资产'} ×${it.qty}`)
    .join(' · ')
})

// 项目状态由合同状态自动派生（ADR-007）：列表页不再提供手动状态变更入口，
// 交付 / 终止操作在「项目详情 → 合同清单」的合同卡片上进行。

async function handleDelete(p: Project) {
  try {
    await ElMessageBox.confirm(
      `确定删除项目「${p.name}」（${p.code}）吗？删除将释放其占用的库存锁定，并撤销该项目已生成的出库记录（回退已售数量与累计销售金额），且不可恢复。`,
      '删除项目确认',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    await deleteProject(p.id)
    ElMessage.success('项目已删除：库存锁定已释放，相关出库记录已撤销')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">销售管理 / 销售项目</div>
        <h1>销售项目</h1>
        <div class="desc">从线索登记到交付完成的全生命周期跟踪，销售项目关联资产明细并自动锁定库存。</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button
              type="primary"
              :icon="Plus"
              :disabled="!canWrite"
              @click="router.push('/sales/projects/create')"
            >
              新增销售项目
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 业务规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>项目状态由合同状态自动派生：「进行中」项目已锁定库存，在项目详情页对合同执行「交付」即扣减库存并生成出库记录；执行「终止」释放锁定（已交付合同终止将撤销出库并回退）。资产明细支持「重复售卖」类型不扣减额度。</span>
    </div>

    <!-- 表格卡 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">销售项目</span>
        <span class="c">共 {{ list.length }} 条</span>
      </div>

      <div class="toolbar">
        <el-input
          v-model="searchText"
          placeholder="搜索项目名称 / 编号 / 客户"
          clearable
          style="width: 260px;"
          :prefix-icon="Search"
        />
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px;">
          <el-option v-for="(s, k) in PROJECT_STATUS" :key="k" :label="s.label" :value="k" />
        </el-select>
        <el-select v-model="repFilter" placeholder="全部生态人员" clearable style="width: 150px;">
          <el-option v-for="r in reps" :key="r" :label="r" :value="r" />
        </el-select>
      </div>

      <el-table :data="list" border stripe @row-click="openDrawer" class="clickable">
        <el-table-column prop="code" label="项目编号" width="110" align="left" />
        <el-table-column label="项目名称" min-width="200" align="left" show-overflow-tooltip>
          <template #default="{ row }">
            <span style="font-weight: 500;">{{ row.name }}</span>
          </template>
        </el-table-column>
        <!-- 关联合同列（原「客户」列并入）：展示合同数；客户名由 tooltip 承载（多合同「N 位客户：A、B、C」/ 单合同客户名）；原独立「合同数」列已删除 -->
        <el-table-column label="关联合同" width="100" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.contractCount" :content="contractTip(row)" placement="top">
              <span class="ct-count">{{ row.contractCount }}</span>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="rep" label="生态人员" width="100" align="left" />
        <el-table-column label="项目状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="tagInfo(PROJECT_STATUS, row.status).tag" size="small" effect="light">
              {{ tagInfo(PROJECT_STATUS, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="合同金额" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.contractAmount">{{ formatMoney(row.contractAmount) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="关联资产" width="90" align="center">
          <template #default="{ row }">{{ row.items.length }} 项</template>
        </el-table-column>
        <el-table-column prop="expectedSignDate" label="预计签约" width="110" align="left">
          <template #default="{ row }">{{ row.expectedSignDate || '-' }}</template>
        </el-table-column>
        <el-table-column prop="lastFollowDate" label="最近跟进" width="110" align="left">
          <template #default="{ row }">{{ row.lastFollowDate || '-' }}</template>
        </el-table-column>
        <!-- 操作列：详情入口收敛到快览抽屉底部「查看详情」（点击行即开抽屉），此处保留编辑 / 删除 -->
        <el-table-column label="操作" width="160" fixed="right" align="center">
          <template #default="{ row }">
            <div class="op-actions">
              <el-tooltip
                :content="!canWrite ? READONLY_TIP : canEditProject(row) ? '' : '含已交付合同或已终止的项目不可编辑'"
                :disabled="canWrite && canEditProject(row)"
                placement="top"
              >
                <span class="op-tip" @click.stop>
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :disabled="!canWrite || !canEditProject(row)"
                    @click.stop="goEdit(row)"
                  >
                    编辑
                  </el-button>
                </span>
              </el-tooltip>
              <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                <span class="op-tip" @click.stop>
                  <el-button
                    link
                    type="danger"
                    size="small"
                    :disabled="!canWrite"
                    @click.stop="handleDelete(row)"
                  >
                    删除
                  </el-button>
                </span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无销售项目，点击右上角「新增销售项目」" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 项目快览抽屉：点击行打开，聚焦合同清单（只读）；「查看详情」才进入详情页 -->
    <el-drawer v-model="drawerVisible" size="640px" class="project-drawer">
      <template v-if="drawerProject" #header>
        <div class="dr-head">
          <span class="dr-icon" aria-hidden="true"><el-icon><Tickets /></el-icon></span>
          <div class="dr-head-main">
            <div class="dr-title">
              <span class="dr-name">{{ drawerProject.name }}</span>
              <el-tag :type="tagInfo(PROJECT_STATUS, drawerProject.status).tag" size="small" effect="light">
                {{ tagInfo(PROJECT_STATUS, drawerProject.status).label }}
              </el-tag>
            </div>
            <div class="dr-sub muted">
              <span class="dr-code">{{ drawerProject.code }}</span>
            </div>
          </div>
          <el-icon class="dr-close" aria-hidden="true" @click="drawerVisible = false"><Close /></el-icon>
        </div>
      </template>

      <template v-if="drawerProject">
        <!-- 概览 -->
        <div class="dr-section">
          <div class="sec-title">概览</div>
          <div class="info-grid info-grid-1">
            <div class="info-item">
              <span class="il">商务负责人</span>
              <span class="iv">{{ drawerProject.businessOwner || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">生态人员</span>
              <span class="iv">{{ drawerProject.rep || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">预计签约日期</span>
              <span class="iv">{{ drawerProject.expectedSignDate || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">合同合计</span>
              <span class="iv">{{ drawerProject.expectedAmount ? formatMoney(drawerProject.expectedAmount) : '-' }}</span>
            </div>
          </div>
        </div>

        <!-- 合同清单（只读快览：交付 / 终止仍在项目详情页操作） -->
        <div class="dr-section">
          <div class="sec-title">
            合同清单<span class="sec-count muted">（{{ dContracts.length }}）</span>
          </div>
          <div v-if="dContracts.length" class="dr-contracts">
            <div v-for="c in dContracts" :key="c.id" class="ct-row" :class="`ct-${c.status}`">
              <!-- 第一层：合同号 + 客户 + 主体/状态 tag（左）｜ 合同金额（右） -->
              <div class="ct-main">
                <div class="ct-left">
                  <span class="ct-code">{{ c.code }}</span>
                  <span class="ct-customer">{{ c.customer }}</span>
                  <el-tag v-if="c.subject" size="small" effect="plain">{{ entityShort(c.subject) }}</el-tag>
                  <el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light">
                    {{ tagInfo(PROJECT_STATUS, c.status).label }}
                  </el-tag>
                </div>
                <span class="ct-amount">{{ formatMoney(c.contractAmount) }}</span>
              </div>
              <!-- 第二层：明细资产逐行展示（资产名 13px 正文色 + 数量 12px muted） -->
              <div v-if="c.items.length" class="ct-items">
                <div v-for="it in c.items" :key="it.id" class="ct-item">
                  <el-tooltip :content="contractItemName(it)" placement="top">
                    <span class="ct-item-name">{{ contractItemName(it) }}</span>
                  </el-tooltip>
                  <span class="ct-item-qty muted">× {{ it.qty }}</span>
                </div>
              </div>
              <!-- 第三层：锁定/交付日期 -->
              <div v-if="contractDates(c)" class="ct-dates muted">{{ contractDates(c) }}</div>
            </div>
          </div>
          <div v-else-if="drawerProject.items.length" class="ct-fallback muted">
            该项目暂无合同（存量数据），明细摘要：{{ legacyItemSummary }}
          </div>
          <el-empty v-else description="该项目暂无合同（存量数据）" :image-size="56" />
        </div>
      </template>

      <template #footer>
        <div class="dr-footer">
          <el-button v-if="drawerProject" type="primary" @click="goDetail(drawerProject)">
            查看详情
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.s-unit {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
}
.clickable :deep(.el-table__row) {
  cursor: pointer;
}
/* 操作列按钮组：flex + 固定 gap，间距不依赖相邻按钮选择器与文案长度；
   禁用行与启用行 DOM 结构一致（编辑按钮恒渲染，仅 disabled 变灰） */
.op-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.op-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.op-tip {
  display: inline-flex;
}
/* 关联合同列：合同数（hover tooltip 列出客户） */
.ct-count {
  font-weight: 600;
  color: var(--text-body);
  cursor: help;
}
</style>

<!-- 抽屉样式（非 scoped：抽屉内容挂载到 body，scoped 选择器无法命中） -->
<style>
/* ============ 项目快览抽屉（结构对齐资产快览抽屉） ============ */
.project-drawer .el-drawer__header {
  margin-bottom: 0;
  padding: 16px 20px;
  border-bottom: 1px solid var(--divider-color);
}
.project-drawer .el-drawer__body {
  padding: 16px 20px 12px;
  overflow-y: auto;
}
.project-drawer .el-drawer__footer {
  padding: 12px 20px;
  border-top: 1px solid var(--divider-color);
}

/* 头部：图标 + 名称/编号 + 关闭 */
.project-drawer .dr-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
}
.project-drawer .dr-icon {
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
.project-drawer .dr-head-main {
  flex: 1;
  min-width: 0;
}
.project-drawer .dr-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.project-drawer .dr-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 24px;
}
.project-drawer .dr-sub {
  margin-top: 4px;
  font-size: 12px;
}
/* 项目编号：与详情页 .contract-code 同一 mono 字体栈 */
.project-drawer .dr-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-weight: 600;
  color: var(--text-primary);
}
.project-drawer .dr-close {
  flex-shrink: 0;
  font-size: 16px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
}
.project-drawer .dr-close:hover {
  background: var(--sidebar-hover);
  color: var(--text-primary);
}

/* 分区 */
.project-drawer .dr-section {
  margin-bottom: 18px;
}
.project-drawer .sec-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.project-drawer .sec-count {
  font-weight: 400;
  font-size: 12px;
  margin-left: 2px;
}

/* 合同卡片行：状态左侧色条（与详情页 .contract-card 同色系） */
.project-drawer .ct-row {
  border: 1px solid var(--border-color, #e5e9f0);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.project-drawer .ct-row:last-child {
  margin-bottom: 0;
}
.project-drawer .ct-row.ct-active {
  border-left-color: var(--primary-color);
}
.project-drawer .ct-row.ct-delivered {
  border-left-color: var(--success-color, #0c7b51);
}
.project-drawer .ct-row.ct-terminated {
  border-left-color: var(--danger-color);
  opacity: 0.85;
}
.project-drawer .ct-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.project-drawer .ct-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.project-drawer .ct-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.project-drawer .ct-customer {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.project-drawer .ct-amount {
  flex-shrink: 0;
  font-weight: 600;
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
/* 第二层：明细资产逐行（资产名 13px 正文色，数量 12px muted 紧跟） */
.project-drawer .ct-items {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
}
.project-drawer .ct-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.project-drawer .ct-item-name {
  min-width: 0;
  font-size: 13px;
  color: var(--text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-drawer .ct-item-qty {
  flex-shrink: 0;
  font-size: 12px;
}
/* 第三层：锁定/交付日期（左对齐，与资产行同起点，视觉整齐） */
.project-drawer .ct-dates {
  margin-top: 6px;
  font-size: 12px;
}

/* 存量无合同：旧明细摘要兜底行 */
.project-drawer .ct-fallback {
  font-size: 12px;
  line-height: 1.6;
  padding: 10px 12px;
  border: 1px dashed var(--divider-color);
  border-radius: 8px;
}

/* 底部操作 */
.project-drawer .dr-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
