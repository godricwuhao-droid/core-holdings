<script setup lang="ts">
/**
 * 销售管理 - 销售项目列表
 *
 * 列：编号/名称/关联合同（合同数，tooltip 列客户）/生态人员/状态/合同金额/关联产品数/预计签约日期/最近跟进日期
 * （项目级「主体」列已移除：多合同多主体，项目 subject 恒为空/无意义；合同卡内主体 tag 保留）
 * （金额列仅保留「合同金额」，元值 formatMoney 直显）
 * 快览抽屉：点击行打开（交互对齐产品列表），聚焦项目概览 + 合同清单（不展示合同编号）；
 * 抽屉底部提供状态变更快捷入口（商务/管理员：交付/终止，项目级批量；生态人员：仅终止自己项目），
 * 逐合同操作与「查看详情」仍走项目详情页。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, InfoFilled, Search, Tickets } from '@element-plus/icons-vue'
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
import { allUserOptions, changeProjectStatus, claimProject, db, deleteProject, getAsset, showError, userOptions, type UserOption } from '@/api'
import { canWrite, currentUser, isViewer, isAdmin, NO_PERM_TIP } from '@/auth'
import TransferDialog from '@/components/TransferDialog.vue'

const router = useRouter()

const searchText = ref('')
const statusFilter = ref<ProjectStatus | ''>('')
const repFilter = ref('')
// ADR-012 §5.1：商务负责人关联查询——businessOwner 与商务角色账号（username）关联，按账号筛选
const ownerFilter = ref('') // ''=全部 | '__none__'=未指派 | username
// 2026-10-20：显示映射（商务/生态 账号→姓名）用**全量**名册（/users/options/all）——
// 原 /users/options 只有商务，生态 rep 查不到导致列表「生态人员」列裸账号外露
const ownerOptions = ref<UserOption[]>([])
allUserOptions().then((u) => { ownerOptions.value = u }).catch(() => {})
// 商务负责人**筛选下拉**保持商务专属（businessOwner 只可能是商务账号）
const ownerFilterOptions = ref<UserOption[]>([])
userOptions().then((u) => { ownerFilterOptions.value = u }).catch(() => {})

/** username → 展示名（2026-10-20：只显示姓名，不带账号；对不上账号的存量自由文本原样显示） */
function ownerLabel(username?: string): string {
  if (!username) return ''
  const u = ownerOptions.value.find((x) => x.username === username)
  return u?.name || username
}
/** 生态人员展示（rep 存 username，存量可能存姓名 → 统一显示姓名） */
function repName(rep?: string): string {
  if (!rep) return ''
  const u = ownerOptions.value.find((x) => x.username === rep) || ownerOptions.value.find((x) => x.name === rep)
  return u?.name || rep
}
/** ADR-012 §5.1：「审核订单」入口仅对接手人（或 admin 越过）展示；未接手/他人接手 → 隐藏（操作由后端守卫兜底） */
function canReviewRow(row: { businessOwner?: string }): boolean {
  return canWrite.value && !!row.businessOwner
    && (isAdmin.value || row.businessOwner === currentUser.value?.username)
}
/** ADR-012 §5.1 纯移交制：无主→任意商务可见「接手」（viewer 灰显）；有主→仅负责人「转交」或 admin 越过；
 *  他人负责的单据对普通商务不显示按钮 */
function canClaimRow(row: { status: string; businessOwner?: string }): boolean {
  if (!canWrite.value) return false // 2026-10-19 排查修复：viewer 不渲染接手/转交按钮（claim 需 editor，原对 viewer 灰显/不显示口径不一）
  if (row.status !== 'pending' && row.status !== 'active') return false
  if (!row.businessOwner) return true
  if (row.businessOwner === currentUser.value?.username) return true
  return isAdmin.value
}

async function handleClaim(p: Project) {
  // 纯移交制（ADR-012 §5.1）：此处仅处理无主单接手；转交走 TransferDialog 下拉选人
  try {
    await ElMessageBox.confirm(
      `确认接手「${p.name}」？接手后你将负责该订单的定价审核（确认下单/驳回）。`,
      '接手订单',
      { type: 'warning', confirmButtonText: '确认接手', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await claimProject(p.id)
    ElMessage.success('已接手，该订单现在归你负责')
  } catch (e) {
    showError(e, '操作失败')
  }
}

const transferVisible = ref(false)
const transferTarget = ref<{ id: number; name: string; businessOwner?: string } | null>(null)
function openTransfer(p: Project) {
  transferTarget.value = p
  transferVisible.value = true
}

/** 生态人员筛选选项（2026-10-20 问题10：rep 统一存 username——选项值收集 p.rep（username），
 *  显示名走 repName（/users/options/all 账号→姓名映射）；不再混入 db.reps 基础资料姓名，
 *  避免同一人出现「账号 + 姓名」两个不同值的选项导致筛选/统计拆分） */
const reps = computed(() =>
  Array.from(new Set(db.projects.map((p) => p.rep)))
    .filter(Boolean)
    .map(String),
)

const list = computed(() =>
  db.projects.filter((p) => {
    const kw = searchText.value.trim()
    if (kw && !`${p.name}${p.code}${p.customer}`.includes(kw)) return false
    if (statusFilter.value && p.status !== statusFilter.value) return false
    if (repFilter.value && p.rep !== repFilter.value) return false
    // ADR-012 §5.1：按商务负责人账号筛选（'__none__' = 未指派/历史自由文本）
    if (ownerFilter.value === '__none__' && p.businessOwner) return false
    if (ownerFilter.value && ownerFilter.value !== '__none__' && p.businessOwner !== ownerFilter.value) return false
    return true
  }),
)

function goEdit(p: Project) {
  // 2026-10-19：订单审核独立页——商务/管理员的 pending 单 → /review（仅订单审核+备注）；
  // viewer 自己单始终 → /edit（可改基本信息 + 取消订单）；其余状态 → /edit
  const toReview = !isViewer.value && p.status === 'pending'
  router.push(`/sales/projects/${p.id}/${toReview ? 'review' : 'edit'}`)
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
  // ADR-012 §5.1：pending（待审核）项目仅商务负责人（或 admin 越过）可审核；
  // 2026-10-19：viewer 自己下单的 pending 单可进入编辑页（改基本信息 + 取消订单）
  if (p.status === 'pending') {
    if (isViewer.value) return (p.creator || '').trim() === currentUser.value?.username
    return isAdmin.value || (p.businessOwner || '').trim() === currentUser.value?.username
  }
  if (!p.contractCount) return p.status === 'active'
  const contracts = db.contracts.filter((c) => c.projectId === p.id)
  return contracts.every((c) => c.status !== 'delivered') && p.status !== 'terminated'
}

function goDetail(p: Project) {
  router.push(`/sales/projects/${p.id}/detail`)
}

// ---- 快览抽屉：点击行打开（交互对齐产品列表），「查看详情」才跳详情页 ----
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

/** 合同明细单项产品名（第二层逐行展示用） */
function contractItemName(it: ContractItem): string {
  return it.assetId ? getAsset(it.assetId)?.name ?? '未关联产品' : '未关联产品'
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
    .map((it) => `${it.assetId ? getAsset(it.assetId)?.name ?? '未关联产品' : '未关联产品'} ×${it.qty}`)
    .join(' · ')
})

// 项目状态由合同状态自动派生（ADR-007）：列表页不再提供手动状态变更入口，
// 交付 / 终止操作在「项目详情 → 合同清单」的合同卡片上进行。

// 生态人员（viewer）：列表数据已按「自己下单」在后端过滤，可见行均为自己项目——
// 允许编辑基本信息（后端同样校验归属），删除/新建仍仅商务/管理员
const canEditRow = computed(() => canWrite.value || isViewer.value)

// ==================== 抽屉状态变更（2026-10-19：商务/管理员可交付/终止；生态人员仅终止自己项目） ====================
const drawerActing = ref(false)
/** 抽屉项目名下进行中的合同数（批量接口仅作用于 active 合同） */
const dActiveCount = computed(() => dContracts.value.filter((c) => c.status === 'active').length)
const canDrawerDeliver = computed(
  () => canWrite.value && dActiveCount.value > 0 && drawerProject.value?.status !== 'terminated',
)
const canDrawerTerminate = computed(
  () => (canWrite.value || isViewer.value) && dActiveCount.value > 0 && drawerProject.value?.status !== 'terminated',
)

/** 抽屉批量状态变更：走项目级 PATCH /projects/{id}/status（对全部 active 合同批量执行） */
async function drawerChangeStatus(status: 'delivered' | 'terminated') {
  const p = drawerProject.value
  if (!p) return
  const msg =
    status === 'delivered'
      ? `确认交付项目「${p.name}」下 ${dActiveCount.value} 份进行中销售记录？将扣减数量并生成交付记录。`
      : `确认终止项目「${p.name}」下 ${dActiveCount.value} 份进行中销售记录？将释放锁定数量（已交付不受影响，如需撤销交付请前往项目详情）。`
  try {
    await ElMessageBox.confirm(msg, status === 'delivered' ? '交付项目确认' : '终止项目确认', {
      type: 'warning',
      confirmButtonText: status === 'delivered' ? '确认交付' : '确认终止',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  drawerActing.value = true
  try {
    await changeProjectStatus(p.id, status)
    ElMessage.success(status === 'delivered' ? '项目已交付：产品数量与交付记录已自动更新' : '项目已终止：数量锁定已释放')
    drawerVisible.value = false
  } catch (e) {
    showError(e, '项目状态变更失败')
  } finally {
    drawerActing.value = false
  }
}

async function handleDelete(p: Project) {
  try {
    await ElMessageBox.confirm(
      `确定删除项目「${p.name}」（${p.code}）吗？删除将释放其占用的数量锁定，并撤销该项目已生成的交付记录（回退已售数量与累计销售金额），且不可恢复。`,
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
    ElMessage.success('项目已删除：数量锁定已释放，相关交付记录已撤销')
  } catch (e) {
    showError(e, '删除失败')
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
        <div class="desc">从线索登记到交付完成的全生命周期跟踪，销售项目关联产品明细并自动锁定数量。</div>
      </div>
      <!-- 2026-10-19：移除「新增销售项目」入口——下单统一走产品下单（购物车/直接下单）；
           手动建单页保留路由（直连 URL 可进，供代录/数据修复等特殊场景，API 保留） -->
    </div>

    <!-- 业务规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>下单（购物车，下单入口已统一收口）统一进入「待审核」（数量已锁定），由商务人员接手后确认下单（可修改单价/销售金额/服务期限）或驳回。项目状态由销售记录状态自动派生：「进行中」项目已锁定数量，商务录入签订时间后销售记录转「交付中」，在项目详情页对销售记录执行「交付」即扣减数量并生成交付记录；执行「终止」释放锁定（已交付终止将撤销交付并回退「交付中」）。产品明细支持「重复售卖」类型不扣减额度。</span>
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
          <!-- 2026-10-20：label 显示姓名（value 保持原值用于匹配行数据） -->
          <el-option v-for="r in reps" :key="r" :label="repName(r)" :value="r" />
        </el-select>
        <!-- ADR-012 §5.1：商务负责人（账号关联）筛选 -->
        <el-select v-model="ownerFilter" placeholder="全部商务负责人" clearable style="width: 170px;">
          <el-option value="__none__" label="未指派 / 历史数据" />
          <!-- 2026-10-20：筛选下拉用商务专属列表（ownerOptions 已是全量名册，仅显示映射用） -->
          <el-option v-for="u in ownerFilterOptions" :key="u.username" :label="ownerLabel(u.username)" :value="u.username" />
        </el-select>
      </div>

      <el-table :data="list" border stripe @row-click="openDrawer" class="clickable">
        <!-- 2026-10-19 UI 优化：编号列加宽 + mono 等宽 + 不换行（原 110px 导致 SP-xxxx 折 3 行）；
             项目名称列收窄（min-width 200 → 150），超长省略 + tooltip 已有 -->
        <el-table-column prop="code" label="项目编号" width="185" align="left" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="proj-code">{{ row.code }}</span>
          </template>
        </el-table-column>
        <el-table-column label="项目名称" min-width="150" align="left" show-overflow-tooltip>
          <template #default="{ row }">
            <span style="font-weight: 500;">{{ row.name }}</span>
          </template>
        </el-table-column>
        <!-- 销售记录列（原「客户」列并入）：展示销售记录数；客户名由 tooltip 承载（多销售记录「N 位客户：A、B、C」/ 单销售记录客户名）；原独立「销售记录数」列已删除 -->
        <el-table-column label="销售记录" width="100" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.contractCount" :content="contractTip(row)" placement="top">
              <span class="ct-count">{{ row.contractCount }}</span>
            </el-tooltip>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="rep" label="生态人员" width="100" align="left">
          <!-- 2026-10-20：只显示姓名（原显示裸账号） -->
          <template #default="{ row }">{{ repName(row.rep) }}</template>
        </el-table-column>
        <!-- ADR-012 §5.1：商务负责人（接手/转交后绑定商务账号，支持账号关联查询） -->
        <el-table-column label="商务负责人" width="130" align="left" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.businessOwner">{{ ownerLabel(row.businessOwner) }}</span>
            <span v-else class="muted">未指派</span>
          </template>
        </el-table-column>
        <el-table-column label="项目状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="tagInfo(PROJECT_STATUS, row.status).tag" size="small" effect="light">
              {{ tagInfo(PROJECT_STATUS, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="销售金额" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.contractAmount">{{ formatMoney(row.contractAmount) }}</span>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="关联产品" width="90" align="center">
          <template #default="{ row }">{{ row.items.length }} 项</template>
        </el-table-column>
        <el-table-column prop="expectedSignDate" label="预计签约" width="110" align="left">
          <template #default="{ row }">{{ row.expectedSignDate || '-' }}</template>
        </el-table-column>
        <el-table-column prop="lastFollowDate" label="最近跟进" width="110" align="left">
          <template #default="{ row }">{{ row.lastFollowDate || '-' }}</template>
        </el-table-column>
        <!-- 操作列：详情入口收敛到快览抽屉底部「查看详情」（点击行即开抽屉），此处保留编辑 / 删除 -->
        <el-table-column label="操作" width="190" fixed="right" align="center">
          <template #default="{ row }">
            <div class="op-actions">
              <!-- ADR-012 §5.1：接手（pending 未指派）/ 转交（他人已负责，pending 或 active 均可）；
                   已接手的自己不再显示按钮；delivered/terminated 终态不可接手/转交 -->
              <!-- ADR-012 §5.1 纯移交制：无主→「接手」（任意商务）；有主→仅负责人「转交」（下拉选人）或 admin 越过；
                   他人负责的单据对普通商务不显示按钮；delivered/terminated 终态不可接手/转交 -->
              <el-tooltip
                v-if="canClaimRow(row)"
                :content="!canWrite
                  ? NO_PERM_TIP
                  : !row.businessOwner ? '接手后由你负责定价审核（确认下单/驳回）'
                  : row.businessOwner === currentUser?.username ? `转交给其他商务账号（当前负责人 ${ownerLabel(row.businessOwner)}）`
                  : '转交给其他商务账号，或 admin 接手给自己'"
                :disabled="canWrite"
                placement="top"
              >
                <span class="op-tip" @click.stop>
                  <el-button
                    link
                    :type="row.businessOwner ? 'info' : 'success'"
                    size="small"
                    :disabled="!canWrite"
                    @click.stop="row.businessOwner ? openTransfer(row) : handleClaim(row)"
                  >
                    {{ row.businessOwner ? '转交' : '接手' }}
                  </el-button>
                </span>
              </el-tooltip>
              <!-- ADR-012 §5.1：pending 项目入口按钮文案「审核订单」，仅负责人/admin 可点，其余禁用（禁止态） -->
              <el-tooltip
                :content="!canEditRow
                  ? NO_PERM_TIP
                  : canEditProject(row) ? ''
                  : row.status === 'pending' ? (isViewer ? '待审核项目由商务人员接手确认后生效' : '待审核项目仅商务负责人（或管理员）可进入，请先接手')
                  : '含已交付或已终止的项目不可编辑'"
                :disabled="canEditRow && canEditProject(row)"
                placement="top"
              >
                <span class="op-tip" @click.stop>
                  <el-button
                    link
                    :type="row.status === 'pending' && !isViewer ? 'warning' : 'primary'"
                    size="small"
                    :disabled="!canEditRow || !canEditProject(row)"
                    @click.stop="goEdit(row)"
                  >
                    {{ row.status === 'pending' && !isViewer ? '审核订单' : '编辑' }}
                  </el-button>
                </span>
              </el-tooltip>
              <!-- 2026-10-20：重新提交——已终止（驳回/取消/终止）项目由下单账号（或商务/管理员）
                   预填原单明细（可改）重新下单；旧项目保留终止历史 -->
              <el-button
                v-if="row.status === 'terminated' && (canWrite || isViewer)"
                link
                type="warning"
                size="small"
                @click.stop="router.push(`/sales/projects/create?copy=${row.id}`)"
              >
                重新提交
              </el-button>
              <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
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
          <!-- 2026-10-19：新建入口已移除，空态文案同步 -->
        <el-empty description="暂无销售项目，请从产品页「直接下单 / 加入购物车」下单" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 项目快览抽屉：点击行打开，聚焦销售记录清单（只读）；「查看详情」才进入详情页 -->
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
              <span class="iv">{{ drawerProject.businessOwner ? ownerLabel(drawerProject.businessOwner) : '未指派' }}</span>
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
              <span class="il">销售金额合计</span>
              <span class="iv">{{ drawerProject.expectedAmount ? formatMoney(drawerProject.expectedAmount) : '-' }}</span>
            </div>
          </div>
        </div>

        <!-- 销售记录清单（只读快览：交付 / 终止仍在项目详情页操作） -->
        <div class="dr-section">
          <div class="sec-title">
            销售记录清单<span class="sec-count muted">（{{ dContracts.length }}）</span>
          </div>
          <div v-if="dContracts.length" class="dr-contracts">
            <div v-for="c in dContracts" :key="c.id" class="ct-row" :class="`ct-${c.status}`">
              <!-- 第一层：客户 + 主体/状态 tag（左）｜ 销售金额（右）；销售记录编号不对外展示（2026-10-19） -->
              <div class="ct-main">
                <div class="ct-left">
                  <span class="ct-customer">{{ c.customer }}</span>
                  <el-tag v-if="c.subject" size="small" effect="plain">{{ entityShort(c.subject) }}</el-tag>
                  <el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light">
                    {{ tagInfo(PROJECT_STATUS, c.status).label }}
                  </el-tag>
                </div>
                <span class="ct-amount">{{ formatMoney(c.contractAmount) }}</span>
              </div>
              <!-- 第二层：明细产品逐行展示（产品名 13px 正文色 + 数量 12px muted） -->
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
            该项目暂无销售记录（存量数据），明细摘要：{{ legacyItemSummary }}
          </div>
          <el-empty v-else description="该项目暂无销售记录（存量数据）" :image-size="56" />
        </div>
      </template>

      <template #footer>
        <div class="dr-footer">
          <template v-if="drawerProject">
            <!-- ADR-012 §5.1：待审核订单 → 仅接手人（或 admin）可见「审核订单」；未接手/他人接手时隐藏（后端守卫兜底） -->
            <el-button
              v-if="drawerProject.status === 'pending' && canReviewRow(drawerProject)"
              type="warning"
              @click="goEdit(drawerProject)"
            >
              审核订单
            </el-button>
            <!-- 状态变更：商务/管理员可交付+终止（项目级批量快捷）；生态人员仅终止（后端校验归属） -->
            <el-button
              v-if="canDrawerDeliver"
              type="primary"
              :loading="drawerActing"
              @click="drawerChangeStatus('delivered')"
            >
              交付
            </el-button>
            <el-button
              v-if="canDrawerTerminate"
              type="danger"
              plain
              :loading="drawerActing"
              @click="drawerChangeStatus('terminated')"
            >
              终止
            </el-button>
            <el-button type="primary" plain @click="goDetail(drawerProject)">
              查看详情
            </el-button>
          </template>
        </div>
      </template>
    </el-drawer>

    <!-- ADR-012 §5.1 纯移交制：转交对话框（负责人/admin，下拉选新负责人） -->
    <TransferDialog v-model="transferVisible" :project="transferTarget" />
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
/* ============ 项目快览抽屉（结构对齐产品快览抽屉） ============ */
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
.proj-code {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
  white-space: nowrap;
}
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
/* 第二层：明细产品逐行（产品名 13px 正文色，数量 12px muted 紧跟） */
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
/* 第三层：锁定/交付日期（左对齐，与产品行同起点，视觉整齐） */
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
