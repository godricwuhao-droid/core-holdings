<script setup lang="ts">
/**
 * 销售管理 - 销售出库记录
 *
 * 来源：销售项目交付完成自动生成 + 手工补录
 * 撤销出库必须填写原因，并反向生成调整流水（设计稿 8）
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, InfoFilled, Money, Plus, Search, Van } from '@element-plus/icons-vue'
import {
  OUTBOUND_TYPES,
  availableQty,
  defaultOutboundType,
  formatMoney,
  formatWan,
  noSellableStock,
  today,
  type Outbound,
  type OutboundMode,
  type OutboundType,
} from '@/types'
import { createOutbound, db, getAsset, revertOutbound } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

const router = useRouter()
const searchText = ref('')
const typeFilter = ref<OutboundType | ''>('')

/** 关联项目跳转项目详情（与项目列表 goDetail 同路由）；无项目不跳转 */
function goProjectDetail(row: Outbound) {
  if (row.projectId) router.push(`/sales/projects/${row.projectId}/detail`)
}

/**
 * 关联合同（ADR-007）：contractId 非空（合同交付自动出库）→ 合同号；
 * 合同无独立详情页，故整词纯文本 mono 展示**不跳转**（避免死链），hover tooltip 显示合同客户名；
 * 存量 / 手工补录 contractId 为 null（或合同已随项目删除）→ '-'。
 */
function contractOf(row: Outbound) {
  return row.contractId ? db.contracts.find((c) => c.id === row.contractId) : undefined
}

const list = computed(() =>
  db.outbounds.filter((o) => {
    const kw = searchText.value.trim()
    if (kw && !`${o.code}${o.assetName}${o.projectName}${o.customer}`.includes(kw)) return false
    if (typeFilter.value && o.type !== typeFilter.value) return false
    return true
  }),
)

// ============================================================
// 补录出库
// ============================================================
const createDialog = reactive({
  visible: false,
  submitting: false,
  form: {
    projectId: null as number | null,
    customer: '',
    assetId: null as number | null,
    qty: 0,
    amount: 0,
    type: 'physical' as OutboundType,
    mode: 'new' as OutboundMode,
    date: today(),
    operator: 'admin',
    remark: '',
  },
})

function typeLabel(t: string): string {
  return OUTBOUND_TYPES[t as OutboundType] || t
}

/** 页面统计（仅统计未撤销记录） */
const summary = computed(() => {
  const done = db.outbounds.filter((o) => o.status === 'done')
  return {
    count: done.length,
    amount: done.reduce((s, o) => s + o.amount, 0),
    projects: new Set(done.map((o) => o.projectName).filter(Boolean)).size,
  }
})

const activeProjects = computed(() =>
  db.projects.filter((p) => p.status !== 'terminated'),
)

/** 可选资产：新出库排除无可售库存资产；历史补录放开（仅登记台账） */
const selectableAssets = computed(() =>
  db.assets.filter((a) => (createDialog.form.mode === 'history' ? true : !noSellableStock(a))),
)

function openCreate() {
  createDialog.form = {
    projectId: null,
    customer: '',
    assetId: null,
    qty: 0,
    amount: 0,
    type: 'physical',
    mode: 'new',
    date: today(),
    operator: 'admin',
    remark: '',
  }
  createDialog.visible = true
}

function onProjectChange() {
  const p = createDialog.form.projectId
    ? db.projects.find((x) => x.id === createDialog.form.projectId)
    : undefined
  if (p) createDialog.form.customer = p.customer
}

function onAssetChange() {
  const a = createDialog.form.assetId ? getAsset(createDialog.form.assetId) : undefined
  if (a) createDialog.form.type = defaultOutboundType(a.board)
}

async function confirmCreate() {
  const f = createDialog.form
  if (!f.assetId) {
    ElMessage.warning('请选择资产')
    return
  }
  if (!f.qty || f.qty <= 0) {
    ElMessage.warning('请输入数量 / 额度')
    return
  }
  // 新出库：校验不超过可售数量（可重复售卖不限制）；历史补录不校验
  if (f.mode === 'new') {
    const a = getAsset(f.assetId)
    if (a && !a.repeatSale) {
      const avail = availableQty(a) ?? 0
      if (f.qty > avail) {
        ElMessage.warning(`「${a.name}」可售 ${formatWan(avail)}${a.unit}，本次出库 ${f.qty} 超出可售数量，请调整数量或改选“历史补录”`)
        return
      }
    }
  }
  // 防重复出库：新出库且关联项目时，检查该项目下该资产的明细是否已全部出库
  if (f.mode === 'new' && f.projectId) {
    const p = db.projects.find((x) => x.id === f.projectId)
    const a = getAsset(f.assetId)
    if (p && a) {
      const items = p.items.filter((it) => it.assetId === a.id)
      if (items.length > 0 && items.every((it) => it.status === 'shipped' || it.status === 'released')) {
        ElMessage.warning(`「${a.name}」在项目 ${p.code} 下的明细已全部出库，请勿重复登记；历史记录请改选「历史补录」`)
        return
      }
    }
  }
  createDialog.submitting = true
  try {
    await createOutbound({ ...f, assetId: f.assetId })
    ElMessage.success(f.mode === 'history' ? '历史补录登记成功，仅记录台账，未调整当前库存' : '出库登记成功，资产库存已更新')
    createDialog.visible = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '登记失败')
  } finally {
    createDialog.submitting = false
  }
}

// ============================================================
// 撤销出库
// ============================================================
async function handleRevert(o: Outbound) {
  let reason = ''
  try {
    const { value } = await ElMessageBox.prompt(
      `撤销出库 ${o.code}（${o.assetName} ${formatWan(o.qty)}${o.unit}）将反向更新资产库存，请填写撤销原因。`,
      '撤销出库',
      {
        inputPattern: /\S+/,
        inputErrorMessage: '撤销原因不能为空',
        confirmButtonText: '确认撤销',
        cancelButtonText: '取消',
      },
    )
    reason = value
  } catch {
    return
  }
  await revertOutbound(o.id, reason)
  ElMessage.success('已撤销并生成调整流水')
}
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">销售管理 / 出库记录</div>
        <h1>销售出库记录</h1>
        <div class="desc">出库记录由销售项目「交付完成」后自动生成，也支持手工补录；撤销须填写原因并保留审计流水。</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button type="primary" :icon="Plus" :disabled="!canWrite" @click="openCreate">
              补录出库记录
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div>
          <div class="s-label">出库记录</div>
          <div class="s-value">{{ summary.count }}</div>
          <div class="s-sub">未撤销记录</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Van /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">累计出库金额</div>
          <div class="s-value">{{ formatMoney(summary.amount) }}</div>
          <div class="s-sub">按出库单金额汇总</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Money /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">关联项目</div>
          <div class="s-value">{{ summary.projects }}</div>
          <div class="s-sub">有出库记录的销售项目</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Document /></el-icon>
      </div>
    </div>

    <!-- 业务规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>撤销出库必须填写原因，系统将反向生成调整流水；审计记录不可删除，仅可追溯。</span>
    </div>

    <!-- 表格卡 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">出库记录</span>
        <span class="c">共 {{ list.length }} 条</span>
      </div>

      <div class="toolbar">
        <el-input
          v-model="searchText"
          placeholder="搜索单号 / 资产 / 项目 / 客户"
          clearable
          style="width: 280px;"
          :prefix-icon="Search"
        />
        <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 140px;">
          <el-option v-for="(label, k) in OUTBOUND_TYPES" :key="k" :label="label" :value="k" />
        </el-select>
      </div>

      <el-table :data="list" border stripe>
        <el-table-column prop="code" label="出库单号" width="120" align="left" />
        <el-table-column label="关联项目" min-width="200">
          <template #default="{ row }">
            <span v-if="row.projectName" style="display: inline-flex; align-items: center; gap: 6px;">
              <a
                v-if="row.projectId"
                class="link"
                style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                @click="goProjectDetail(row)"
              >{{ row.projectName }}</a>
              <span v-else style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ row.projectName }}</span>
              <el-tag
                v-if="row.mode === 'history'"
                size="small"
                type="warning"
                effect="plain"
              >
                历史补录
              </el-tag>
            </span>
            <el-tag v-else size="small" type="info" effect="plain">补录</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联合同" width="110" align="left">
          <template #default="{ row }">
            <el-tooltip
              v-if="contractOf(row)"
              :content="`合同客户：${contractOf(row)!.customer || '-'}`"
              placement="top"
            >
              <span class="contract-code">{{ contractOf(row)!.code }}</span>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="customer" label="客户" width="140" show-overflow-tooltip />
        <el-table-column prop="assetName" label="资产" min-width="180" show-overflow-tooltip />
        <el-table-column label="数量/额度" width="110" align="right">
          <template #default="{ row }">{{ formatWan(row.qty) }} {{ row.unit }}</template>
        </el-table-column>
        <el-table-column label="销售金额" width="120" align="right">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="出库类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="date" label="出库日期" width="110" align="left" />
        <el-table-column prop="operator" label="经办人" width="100" align="left" />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'done'" type="success" size="small" effect="light">已完成</el-tag>
            <el-tag v-else type="danger" size="small" effect="light">已撤销</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.status === 'done'" :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button
                  link
                  type="danger"
                  size="small"
                  :disabled="!canWrite"
                  @click="handleRevert(row)"
                >
                  撤销
                </el-button>
              </span>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无出库记录。销售项目标记「交付完成」后自动生成，或点击「补录入库出库」" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 补录对话框（对齐创建页表单视觉：顶标签 + 分区块） -->
    <el-dialog v-model="createDialog.visible" title="补录销售出库" class="dlg-form" :close-on-click-modal="false">
      <div class="info-bar" style="margin-bottom: 14px;">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>
          <template v-if="createDialog.form.mode === 'new'">
            选择资产后出库类型按板块自动带出；确认登记后自动扣减库存、累计销售金额并生成流水。
          </template>
          <template v-else>
            历史补录仅将已发生的出库补登入账，不扣减当前库存、不计入当前累计销售金额；撤销时同样不回拨。
          </template>
        </span>
      </div>

      <el-form label-position="top">
        <!-- 出库性质 -->
        <div class="dlg-sec">
          <div class="dlg-sec-title">出库性质</div>
          <el-radio-group v-model="createDialog.form.mode">
            <el-radio value="new">新出库（扣减当前库存）</el-radio>
            <el-radio value="history">历史补录（仅登记台账，不扣减库存）</el-radio>
          </el-radio-group>
        </div>
        <!-- 交付来源 -->
        <div class="dlg-sec">
          <div class="dlg-sec-title">交付来源</div>
          <div class="form-grid-2">
            <el-form-item label="关联项目">
              <el-select
                v-model="createDialog.form.projectId"
                clearable
                filterable
                placeholder="可不选（视为纯补录）"
                style="width: 100%;"
                @change="onProjectChange"
              >
                <el-option
                  v-for="p in activeProjects"
                  :key="p.id"
                  :label="`${p.name}（${p.code}）`"
                  :value="p.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="客户">
              <el-input v-model="createDialog.form.customer" placeholder="关联项目后自动带出，补录时手填" />
            </el-form-item>
            <el-form-item label="出库日期">
              <el-date-picker
                v-model="createDialog.form.date"
                type="date"
                value-format="YYYY-MM-DD"
                style="width: 100%;"
              />
            </el-form-item>
            <el-form-item label="经办人">
              <el-input v-model="createDialog.form.operator" placeholder="登记操作的经办人" />
            </el-form-item>
          </div>
        </div>

        <!-- 出库明细 -->
        <div class="dlg-sec">
          <div class="dlg-sec-title">出库明细</div>
          <el-form-item label="资产" required>
            <el-select
              v-model="createDialog.form.assetId"
              filterable
              placeholder="选择要出库的资产"
              style="width: 100%;"
              @change="onAssetChange"
            >
              <el-option
                v-for="a in selectableAssets"
                :key="a.id"
                :label="`${a.name}（${a.code}）`"
                :value="a.id"
              />
            </el-select>
          </el-form-item>
          <div class="form-grid">
            <el-form-item label="出库类型">
              <el-select v-model="createDialog.form.type" style="width: 100%;">
                <el-option v-for="(label, k) in OUTBOUND_TYPES" :key="k" :label="label" :value="k" />
              </el-select>
            </el-form-item>
            <el-form-item label="数量 / 额度">
              <el-input-number v-model="createDialog.form.qty" :min="0" :precision="0" :step="1" controls-position="right" style="width: 100%;" />
            </el-form-item>
            <el-form-item label="销售金额（元）">
              <el-input-number v-model="createDialog.form.amount" :min="0" :precision="2" :controls="false" style="width: 100%;" />
            </el-form-item>
          </div>
          <el-form-item label="备注">
            <el-input
              v-model="createDialog.form.remark"
              type="textarea"
              :rows="2"
              placeholder="补录原因 / 出库单号 / 特殊说明"
            />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <div class="bottom-actions">
          <el-button @click="createDialog.visible = false">取消</el-button>
          <el-button type="primary" :loading="createDialog.submitting" @click="confirmCreate">
            确认登记
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 文字链接：与资产详情页 .link 同规格（复用平台 token，不引入新色值） */
.link {
  color: var(--primary-color);
  font-weight: 500;
  cursor: pointer;
}
.link:hover {
  color: var(--primary-hover);
  text-decoration: underline;
}

/* 合同号：纯文本 mono（与项目详情页 .contract-code 同规格；无独立详情页，不跳转） */
.contract-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  cursor: default;
}

/* 补录弹窗内部分区块（与创建页 block-head 同语言，更紧凑） */
.dlg-sec {
  padding: 14px 16px;
  background: #fafbfd;
  border: 1px solid var(--divider-color);
  border-radius: 8px;
}
.dlg-sec + .dlg-sec {
  margin-top: 12px;
}
.dlg-sec-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.dlg-sec-title::before {
  content: '';
  width: 3px;
  height: 13px;
  border-radius: 2px;
  background: var(--primary-color);
}
.dlg-sec :deep(.el-form-item) {
  margin-bottom: 14px;
}
.dlg-sec :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}
.dlg-sec .form-grid,
.dlg-sec .form-grid-2 {
  gap: 14px;
}
</style>
