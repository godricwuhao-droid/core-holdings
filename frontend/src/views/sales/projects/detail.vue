<script setup lang="ts">
/**
 * 销售管理 - 销售项目详情（只读展示 + 状态变更）
 *
 * 从「销售项目列表」行点击 / 「资产详情-关联销售项目」进入。
 * 只读展示项目信息与销售明细；底部「修改状态」复用状态机与库存联动；
 * 「编辑」跳转编辑页。
 */
import { computed, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, EditPen, Folder, Link } from '@element-plus/icons-vue'
import {
  ITEM_STATUS,
  PROJECT_STATUS,
  entityShort,
  formatMoney,
  tagInfo,
  type ProjectStatus,
} from '@/types'
import { changeProjectStatus, db, getAsset, refresh } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const project = computed(() => db.projects.find((x) => x.id === projectId.value) ?? null)

onMounted(async () => {
  await refresh()
})

function goBack() {
  // 有历史栈时返回上一页；直达 URL（无历史）时回退到销售项目列表，避免退出应用
  if (window.history.state?.back) router.back()
  else router.push('/sales/projects')
}

function goEdit() {
  if (project.value) router.push(`/sales/projects/${project.value.id}/edit`)
}

/** 明细关联资产：名称（编号），可点击跳资产详情 */
function itemAssetName(assetId: number | null): string {
  const a = assetId ? getAsset(assetId) : undefined
  return a ? `${a.name}（${a.code}）` : '未关联资产'
}

function goAssetDetail(assetId: number | null) {
  if (assetId) router.push(`/assets/${assetId}/detail`)
}

// ============================================================
// 状态流转：复用销售项目状态机与库存联动
// ============================================================
const statusDialog = reactive({
  visible: false,
  status: '' as ProjectStatus | '',
  reason: '',
  submitting: false,
})

function openStatusDialog() {
  const p = project.value
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
  const p = project.value
  if (!p || !statusDialog.status || statusDialog.status === p.status) {
    statusDialog.visible = false
    return
  }
  statusDialog.submitting = true
  try {
    await changeProjectStatus(projectId.value, statusDialog.status, statusDialog.reason)
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
</script>

<template>
  <div class="page-container">
    <div class="detail-wrap">
      <!-- 页面标题区 -->
      <div class="page-head">
        <div>
          <a class="back-link" @click="goBack">
            <el-icon><ArrowLeft /></el-icon>
            返回销售项目
          </a>
          <div class="title-row">
            <h1>{{ project?.name ?? '销售项目详情' }}</h1>
            <el-tag
              v-if="project"
              :type="tagInfo(PROJECT_STATUS, project.status).tag"
              size="large"
              effect="light"
            >
              {{ tagInfo(PROJECT_STATUS, project.status).label }}
            </el-tag>
          </div>
          <div class="desc" v-if="project">
            编号 {{ project.code }} · 客户 {{ project.customer }}
          </div>
        </div>
        <div class="head-actions" v-if="project">
          <el-tooltip
            :content="!canWrite ? READONLY_TIP : project.status === 'active' ? '' : '已完成 / 已终止项目不可编辑'"
            :disabled="canWrite && project.status === 'active'"
            placement="top"
          >
            <span>
              <el-button
                v-if="project.status === 'active'"
                :icon="EditPen"
                :disabled="!canWrite"
                @click="goEdit"
              >
                编辑
              </el-button>
              <el-button v-else :icon="EditPen" disabled>编辑</el-button>
            </span>
          </el-tooltip>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
            <span>
              <el-button type="warning" plain :disabled="!canWrite" @click="openStatusDialog">修改状态</el-button>
            </span>
          </el-tooltip>
        </div>
      </div>

      <el-empty v-if="!project" description="未找到该销售项目" :image-size="80" />

      <template v-else>
        <!-- ① 基本信息（只读） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Folder /></el-icon></span>
            <span class="bh-title">基本信息</span>
            <span class="bh-hint">更新于 {{ project.updatedAt }}</span>
          </div>
          <div class="info-grid">
            <div class="info-item">
              <span class="il">项目名称</span>
              <span class="iv">{{ project.name }}</span>
            </div>
            <div class="info-item">
              <span class="il">项目编号</span>
              <span class="iv">{{ project.code }}</span>
            </div>
            <div class="info-item">
              <span class="il">客户名称</span>
              <span class="iv">{{ project.customer || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">行业</span>
              <span class="iv">{{ project.industry || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">生态人员</span>
              <span class="iv">{{ project.rep || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">所属主体</span>
              <span class="iv">{{ entityShort(project.subject) }}</span>
            </div>
            <div class="info-item">
              <span class="il">预计销售</span>
              <span class="iv">{{ project.expectedAmount ? formatMoney(project.expectedAmount) : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">合同金额</span>
              <span class="iv">{{ project.contractAmount ? formatMoney(project.contractAmount) : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">已回款</span>
              <span class="iv">{{ project.paidAmount ? formatMoney(project.paidAmount) : '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">预计签约</span>
              <span class="iv">{{ project.expectedSignDate || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="il">最近跟进</span>
              <span class="iv">{{ project.lastFollowDate || '-' }}</span>
            </div>
            <div class="info-item span-3" v-if="project.remark">
              <span class="il">备注</span>
              <span class="iv">{{ project.remark }}</span>
            </div>
          </div>
        </div>

        <!-- ② 销售明细（只读） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Link /></el-icon></span>
            <div>
              <div class="bh-title">销售明细</div>
              <div class="bh-sub">共 {{ project.items.length }} 项，交付完成时按明细自动扣减库存并生成出库记录。</div>
            </div>
          </div>
          <el-table v-if="project.items.length" :data="project.items" border>
            <el-table-column label="关联资产" min-width="240">
              <template #default="{ row }">
                <a class="link" @click="goAssetDetail(row.assetId)">{{ itemAssetName(row.assetId) }}</a>
              </template>
            </el-table-column>
            <el-table-column label="数量" width="110" align="right">
              <template #default="{ row }">{{ row.qty }} {{ row.unit }}</template>
            </el-table-column>
            <el-table-column label="单价" width="150" align="right">
              <template #default="{ row }">{{ formatMoney(row.price) }}</template>
            </el-table-column>
            <el-table-column label="金额" width="150" align="right">
              <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
            </el-table-column>
            <el-table-column label="明细状态" width="130" align="center">
              <template #default="{ row }">
                <el-tag :type="tagInfo(ITEM_STATUS, row.status).tag" size="small" effect="light">
                  {{ tagInfo(ITEM_STATUS, row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="交付要求" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.deliveryReq || '-' }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无销售明细" :image-size="80" />
        </div>
      </template>
    </div>

    <!-- 状态流转对话框 -->
    <el-dialog v-model="statusDialog.visible" title="项目状态流转" width="560px" :close-on-click-modal="false">
      <p class="flow-hint">
        当前项目：<b>{{ project?.name }}</b>（{{ project?.code }}）
      </p>
      <p class="flow-path muted">
        常规流转（仅可前进，不可回退）：进行中 → 已完成 → 已终止
      </p>
      <el-radio-group v-model="statusDialog.status" class="status-radios">
        <el-radio
          v-for="(s, k) in PROJECT_STATUS"
          :key="k"
          :value="k"
          :disabled="project ? !canGo(project.status, k as ProjectStatus) : false"
        >
          <el-tag :type="s.tag" size="small" effect="light">{{ s.label }}</el-tag>
        </el-radio>
      </el-radio-group>
      <p v-if="project?.status === 'terminated'" class="muted" style="font-size: 12px; margin-top: 8px;">
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
</template>

<style scoped>
/* 内容区最大 1080px，居中 */
.detail-wrap {
  max-width: 1080px;
  margin: 0 auto;
  width: 100%;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.link {
  color: var(--primary-color);
  cursor: pointer;
}
.link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}
/* 状态流转对话框 */
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
