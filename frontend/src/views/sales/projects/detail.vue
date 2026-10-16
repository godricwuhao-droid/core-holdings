<script setup lang="ts">
/**
 * 销售管理 - 销售项目详情（ADR-007 合同清单）
 *
 * 从「销售项目列表」行点击 / 「资产详情-关联销售项目」进入。
 * 只读展示项目信息 + 「合同清单」区块（每份合同一张卡片，明细并入卡片展示）；
 * 合同级操作：交付 / 终止（PATCH /contracts/{id}/status，库存联动最小单位）；
 * 项目状态由合同状态自动派生，本页不提供项目级状态变更入口。
 * 「编辑」跳转编辑页（仅基本信息）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, EditPen, Folder, Tickets } from '@element-plus/icons-vue'
import {
  PROJECT_STATUS,
  derivedUnitPrice,
  entityShort,
  formatDate,
  formatMoney,
  formatTokens,
  isAmountMode,
  rsItemName,
  tagInfo,
  type Contract,
} from '@/types'
import { changeContractStatus, db, getAsset, refresh } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.id))

const project = computed(() => db.projects.find((x) => x.id === projectId.value) ?? null)

/** 项目名下合同（bootstrap.contracts 按 projectId 过滤，id 升序 = 生成顺序） */
const contracts = computed<Contract[]>(() =>
  db.contracts.filter((c) => c.projectId === projectId.value).sort((a, b) => a.id - b.id),
)

/** 客户展示：多合同（customer 派生为空）显示「N 位客户」；单合同/存量显示客户名 */
const customerText = computed(() => {
  const p = project.value
  if (!p) return '-'
  if (p.customer) return p.customer
  const n = contracts.value.length
  return n ? `${n} 位客户` : '-'
})

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

/** ADR-008：明细行资产是否包量定价（单价列改派生参考展示，带「约」） */
function isAmountItem(assetId: number | null): boolean {
  const a = assetId ? getAsset(assetId) : undefined
  return !!a && isAmountMode(a)
}

/** ADR-008：明细数量展示——包量定价（Token）资产用 formatTokens，其余原数 */
function itemQtyText(assetId: number | null, qty: number): string {
  return isAmountItem(assetId) ? formatTokens(qty) : String(qty)
}

/** ADR-011：明细列展示——itemId 非空显示 rsItemName（查 db.rsItems），空则 '-' */
function itemRsName(itemId: number | null | undefined): string {
  if (itemId == null) return '-'
  const r = db.rsItems.find((x) => x.id === itemId)
  return r ? rsItemName(r) : '-'
}

// ============================================================
// 合同状态操作（ADR-007：交付 / 终止，库存联动最小单位）
// ============================================================
const actingContractId = ref<number | null>(null)

/** 交付（active → delivered）：扣减库存并生成出库记录 */
async function deliverContract(c: Contract) {
  try {
    await ElMessageBox.confirm(
      `确认交付合同 ${c.code}？将扣减库存并生成出库记录。`,
      '交付合同确认',
      { type: 'warning', confirmButtonText: '确认交付', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await changeContract(c, 'delivered')
}

/** 终止（active → terminated 释放锁定；delivered → terminated 撤销出库并回退） */
async function terminateContract(c: Contract) {
  const msg =
    c.status === 'delivered'
      ? '已交付合同终止将撤销出库并回退售出数量与金额，确认终止？'
      : '确认终止？将释放该合同锁定库存。'
  try {
    await ElMessageBox.confirm(msg, '终止合同确认', {
      type: 'warning',
      confirmButtonText: '确认终止',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await changeContract(c, 'terminated')
}

async function changeContract(c: Contract, status: 'delivered' | 'terminated') {
  actingContractId.value = c.id
  try {
    await changeContractStatus(c.id, status)
    ElMessage.success(
      status === 'delivered'
        ? `合同 ${c.code} 已交付，资产库存与出库记录已自动更新`
        : `合同 ${c.code} 已终止`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '合同状态变更失败')
  } finally {
    actingContractId.value = null
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
            编号 {{ project.code }} · 客户 {{ customerText }}
            <template v-if="contracts.length"> · {{ contracts.length }} 份合同</template>
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
              <span class="iv">{{ customerText }}</span>
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
              <span class="il">商务负责人</span>
              <span class="iv">{{ project.businessOwner || '-' }}</span>
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

        <!-- ② 合同清单（ADR-007：库存联动最小单位；项目状态由合同状态自动派生） -->
        <div class="form-card">
          <div class="block-head">
            <span class="bh-icon" aria-hidden="true"><el-icon><Tickets /></el-icon></span>
            <div>
              <div class="bh-title">合同清单</div>
              <div class="bh-sub">
                共 {{ contracts.length }} 份合同；项目状态由合同状态自动派生（有进行中→进行中；全部完成→已完成；全部终止→已终止）。
              </div>
            </div>
          </div>

          <template v-if="contracts.length">
            <div v-for="c in contracts" :key="c.id" class="contract-card" :class="`contract-${c.status}`">
              <div class="contract-head">
                <div class="ch-left">
                  <span class="contract-code">{{ c.code }}</span>
                  <span class="contract-customer">{{ c.customer }}</span>
                  <el-tag v-if="c.subject" size="small" effect="plain" class="contract-subject">
                    {{ entityShort(c.subject) }}
                  </el-tag>
                  <el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light">
                    {{ tagInfo(PROJECT_STATUS, c.status).label }}
                  </el-tag>
                </div>
                <div class="op-actions">
                  <template v-if="c.status === 'active'">
                    <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button
                          type="primary"
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canWrite"
                          @click="deliverContract(c)"
                        >
                          交付
                        </el-button>
                      </span>
                    </el-tooltip>
                    <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                      <span>
                        <el-button
                          type="danger"
                          plain
                          size="small"
                          :loading="actingContractId === c.id"
                          :disabled="!canWrite"
                          @click="terminateContract(c)"
                        >
                          终止
                        </el-button>
                      </span>
                    </el-tooltip>
                  </template>
                  <el-tooltip v-else-if="c.status === 'delivered'" :content="READONLY_TIP" :disabled="canWrite" placement="top">
                    <span>
                      <el-button
                        type="danger"
                        plain
                        size="small"
                        :loading="actingContractId === c.id"
                        :disabled="!canWrite"
                        @click="terminateContract(c)"
                      >
                        终止
                      </el-button>
                    </span>
                  </el-tooltip>
                  <span v-else class="muted contract-ended">已终止</span>
                </div>
              </div>

              <div class="contract-info">
                <span class="ci-item">
                  <span class="muted">合同金额</span>
                  <b class="ci-amount">{{ formatMoney(c.contractAmount) }}</b>
                </span>
                <span class="ci-item" v-if="c.items.some((it) => it.lockedDate)">
                  <span class="muted">签约/锁定</span>
                  <span>{{ formatDate(c.items.find((it) => it.lockedDate)?.lockedDate) }}</span>
                </span>
                <span class="ci-item" v-if="c.items.some((it) => it.shippedDate)">
                  <span class="muted">交付</span>
                  <span>{{ formatDate(c.items.find((it) => it.shippedDate)?.shippedDate) }}</span>
                </span>
                <span class="ci-item" v-if="c.remark">
                  <span class="muted">备注</span>
                  <span>{{ c.remark }}</span>
                </span>
              </div>

              <el-table v-if="c.items.length" :data="c.items" border size="small" class="contract-items">
                <el-table-column label="资产" min-width="220">
                  <template #default="{ row }">
                    <a class="link" @click="goAssetDetail(row.assetId)">{{ itemAssetName(row.assetId) }}</a>
                  </template>
                </el-table-column>
                <!-- ADR-011：明细列（遥感明细行显示明细名，其余 '-'） -->
                <el-table-column label="明细" width="200" align="left" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span :class="{ muted: itemRsName(row.itemId) === '-' }">{{ itemRsName(row.itemId) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="数量" width="120" align="right">
                  <template #default="{ row }">{{ itemQtyText(row.assetId, row.qty) }} {{ row.unit }}</template>
                </el-table-column>
                <el-table-column label="单价" width="170" align="right">
                  <!-- ADR-008：包量定价行单价为派生参考展示（带「约」），金额以合同金额为准 -->
                  <template #default="{ row }">
                    <span v-if="isAmountItem(row.assetId)" class="muted">{{ derivedUnitPrice(row.amount, row.qty) }}</span>
                    <span v-else>{{ formatMoney(row.price) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="金额" width="140" align="right">
                  <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
                </el-table-column>
                <el-table-column label="交付要求" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.deliveryReq || '-' }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>

          <!-- 存量无合同项目：保留原销售明细展示（明细 contractId 为 null） -->
          <template v-else>
            <el-table v-if="project.items.length" :data="project.items" border>
              <el-table-column label="关联资产" min-width="240">
                <template #default="{ row }">
                  <a class="link" @click="goAssetDetail(row.assetId)">{{ itemAssetName(row.assetId) }}</a>
                </template>
              </el-table-column>
              <!-- ADR-011：明细列（遥感明细行显示明细名，其余 '-'） -->
              <el-table-column label="明细" width="200" align="left" show-overflow-tooltip>
                <template #default="{ row }">
                  <span :class="{ muted: itemRsName(row.itemId) === '-' }">{{ itemRsName(row.itemId) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="数量" width="120" align="right">
                <template #default="{ row }">{{ itemQtyText(row.assetId, row.qty) }} {{ row.unit }}</template>
              </el-table-column>
              <el-table-column label="单价" width="170" align="right">
                <!-- ADR-008：包量定价行单价为派生参考展示（带「约」） -->
                <template #default="{ row }">
                  <span v-if="isAmountItem(row.assetId)" class="muted">{{ derivedUnitPrice(row.amount, row.qty) }}</span>
                  <span v-else>{{ formatMoney(row.price) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="金额" width="150" align="right">
                <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
              </el-table-column>
              <el-table-column label="交付要求" min-width="180" show-overflow-tooltip>
                <template #default="{ row }">{{ row.deliveryReq || '-' }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无销售明细" :image-size="80" />
          </template>
        </div>
      </template>
    </div>
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

/* 合同卡片：状态左侧色条区分（复用既有 token 色） */
.contract-card {
  border: 1px solid var(--border-color, #e5e9f0);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.contract-card:last-child {
  margin-bottom: 0;
}
.contract-card.contract-active {
  border-left-color: var(--primary-color);
}
.contract-card.contract-delivered {
  border-left-color: var(--success-color, #0c7b51);
}
.contract-card.contract-terminated {
  border-left-color: var(--danger-color);
  opacity: 0.85;
}
.contract-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.ch-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.contract-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.contract-customer {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.contract-subject {
  font-weight: 400;
}
.op-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.op-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.contract-ended {
  font-size: 13px;
}
.contract-info {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--text-body);
}
.ci-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ci-amount {
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
}
.contract-items {
  margin-top: 4px;
}
</style>
