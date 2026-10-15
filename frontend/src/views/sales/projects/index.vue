<script setup lang="ts">
/**
 * 销售管理 - 销售项目列表
 *
 * 字段按设计稿 7.1：编号/名称/客户/生态人员/主体/状态/预计销售金额/合同金额/
 * 已确认销售金额/关联资产数/预计签约日期/最近跟进日期
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, Document, InfoFilled, Money, Plus, Search } from '@element-plus/icons-vue'
import {
  PROJECT_STATUS,
  entityShort,
  formatMoney,
  tagInfo,
  type Project,
  type ProjectStatus,
} from '@/types'
import { changeProjectStatus, db, deleteProject } from '@/api'
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

/** 已确认销售金额：交付完成项目按合同额计 */
function confirmedAmount(p: Project): number {
  return p.status === 'delivered' ? p.contractAmount : 0
}

function goEdit(p: Project) {
  router.push(`/sales/projects/${p.id}/edit`)
}

function goDetail(p: Project) {
  router.push(`/sales/projects/${p.id}/detail`)
}

/** 页面统计 */
const summary = computed(() => ({
  count: db.projects.length,
  active: db.projects.filter((p) => p.status !== 'delivered' && p.status !== 'terminated').length,
  expected: db.projects.reduce((s, p) => s + (p.expectedAmount || 0), 0),
  confirmed: db.projects.reduce((s, p) => s + confirmedAmount(p), 0),
}))

// ============================================================
// 状态流转
// ============================================================
const statusDialog = reactive({
  visible: false,
  project: null as Project | null,
  status: '' as ProjectStatus | '',
  reason: '',
  submitting: false,
})

function openStatusDialog(p: Project) {
  statusDialog.project = p
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
  const p = statusDialog.project
  if (!p || !statusDialog.status || statusDialog.status === p.status) {
    statusDialog.visible = false
    return
  }
  statusDialog.submitting = true
  try {
    await changeProjectStatus(p.id, statusDialog.status, statusDialog.reason)
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

    <!-- 统计卡 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div>
          <div class="s-label">项目总数</div>
          <div class="s-value">{{ summary.count }}</div>
          <div class="s-sub">进行中 {{ summary.active }} 个</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Document /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">预计销售金额</div>
          <div class="s-value">{{ formatMoney(summary.expected) }}</div>
          <div class="s-sub">全部项目预计口径</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Money /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">已确认销售</div>
          <div class="s-value">{{ formatMoney(summary.confirmed) }}</div>
          <div class="s-sub">交付完成项目按合同额计</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><CircleCheck /></el-icon>
      </div>
    </div>

    <!-- 业务规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>项目标记「交付完成」后自动扣减关联资产库存并生成出库记录；「进行中」项目已锁定库存，确认交付后请置为「已完成」以扣减库存并生成出库。资产明细支持「重复售卖」类型不扣减额度。</span>
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

      <el-table :data="list" border stripe @row-click="goDetail" class="clickable">
        <el-table-column prop="code" label="项目编号" width="110" align="left" />
        <el-table-column label="项目名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span style="font-weight: 500;">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="customer" label="客户" width="140" show-overflow-tooltip />
        <el-table-column prop="rep" label="生态人员" width="100" align="left" />
        <el-table-column label="主体" width="110" align="left" show-overflow-tooltip>
          <template #default="{ row }">{{ entityShort(row.subject) }}</template>
        </el-table-column>
        <el-table-column label="项目状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="tagInfo(PROJECT_STATUS, row.status).tag" size="small" effect="light">
              {{ tagInfo(PROJECT_STATUS, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预计销售" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.expectedAmount">{{ formatMoney(row.expectedAmount) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="合同金额" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.contractAmount">{{ formatMoney(row.contractAmount) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="已确认销售" width="120" align="right">
          <template #default="{ row }">
            <span :style="{ color: confirmedAmount(row) > 0 ? 'var(--success-color)' : undefined }">
              {{ confirmedAmount(row) ? formatMoney(confirmedAmount(row)) : '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="关联资产" width="90" align="right">
          <template #default="{ row }">{{ row.items.length }} 项</template>
        </el-table-column>
        <el-table-column prop="expectedSignDate" label="预计签约" width="110" align="left">
          <template #default="{ row }">{{ row.expectedSignDate || '-' }}</template>
        </el-table-column>
        <el-table-column prop="lastFollowDate" label="最近跟进" width="110" align="left">
          <template #default="{ row }">{{ row.lastFollowDate || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right" align="center">
          <template #default="{ row }">
            <div class="op-actions">
              <el-button link type="primary" size="small" @click.stop="goDetail(row)">详情</el-button>
              <el-tooltip
                :content="!canWrite ? READONLY_TIP : row.status === 'active' ? '' : '已完成 / 已终止项目不可编辑'"
                :disabled="canWrite && row.status === 'active'"
                placement="top"
              >
                <span class="op-tip" @click.stop>
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :disabled="!canWrite || row.status !== 'active'"
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
                    type="warning"
                    size="small"
                    :disabled="!canWrite"
                    @click.stop="openStatusDialog(row)"
                  >
                    状态
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

    <!-- 状态流转对话框 -->
    <el-dialog v-model="statusDialog.visible" title="项目状态流转" width="560px" :close-on-click-modal="false">
      <p class="flow-hint">
        当前项目：<b>{{ statusDialog.project?.name }}</b>（{{ statusDialog.project?.code }}）
      </p>
      <p class="flow-path muted">
        常规流转（仅可前进，不可回退）：进行中 → 已完成 → 已终止
      </p>
      <el-radio-group v-model="statusDialog.status" class="status-radios">
        <el-radio
          v-for="(s, k) in PROJECT_STATUS"
          :key="k"
          :value="k"
          :disabled="statusDialog.project ? !canGo(statusDialog.project.status, k as ProjectStatus) : false"
        >
          <el-tag :type="s.tag" size="small" effect="light">{{ s.label }}</el-tag>
        </el-radio>
      </el-radio-group>
      <p v-if="statusDialog.project?.status === 'terminated'" class="muted" style="font-size: 12px; margin-top: 8px;">
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
        show-icon
      />
      <el-alert
        v-if="statusDialog.status === 'terminated'"
        class="flow-tip"
        title="已终止将自动释放锁定资产，并撤销已出库记录（回退数量与累计销售金额）。"
        type="warning"
        :closable="false"
        show-icon
      />
      <template #footer>
        <el-button @click="statusDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="statusDialog.submitting" @click="confirmStatus">确定</el-button>
      </template>
    </el-dialog>
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
</style>
