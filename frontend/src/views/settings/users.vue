<script setup lang="ts">
/**
 * 基础设置 - 账号与审计（仅 admin，路由守卫已拦截）
 *
 * 两个页签：
 *  - 账号管理：账号 CRUD（新增/编辑/删除；自己那行禁用改角色/启用与删除）
 *  - 审计日志：按操作类型/操作人筛选，分页（pageSize 20），时间倒序
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, Plus, Search, User, UserFilled, Document } from '@element-plus/icons-vue'
import {
  createUser,
  deleteUser,
  listAuditLogs,
  listUsers,
  updateUser,
  type AuditLogOut,
  type UserOut,
} from '@/api'
import { currentUser, type Role } from '@/auth'

// ============================================================
// 角色 / 操作类型 中文映射
// ============================================================
const ROLE_OPTIONS: { value: Role; label: string }[] = [
  { value: 'admin', label: '管理' },
  { value: 'editor', label: '可编辑' },
  { value: 'viewer', label: '只读' },
]

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((r) => r.value === role)?.label ?? role
}

const ACTION_TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'sale', label: '销售' },
  { value: 'outbound', label: '出库' },
  { value: 'asset_change', label: '资产变更' },
  { value: 'setting', label: '设置' },
  { value: 'user_mgmt', label: '账号管理' },
  { value: 'auth', label: '登录认证' },
  { value: 'other', label: '其他' },
]

function actionTypeLabel(t: string): string {
  return ACTION_TYPE_OPTIONS.find((o) => o.value === t)?.label ?? t
}

// ============================================================
// 账号管理
// ============================================================
const users = ref<UserOut[]>([])
const loadingUsers = ref(false)

async function loadUsers() {
  loadingUsers.value = true
  try {
    users.value = await listUsers()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载账号失败')
  } finally {
    loadingUsers.value = false
  }
}

const stats = computed(() => ({
  total: users.value.length,
  enabled: users.value.filter((u) => u.enabled).length,
  admins: users.value.filter((u) => u.role === 'admin').length,
}))

const myId = computed(() => currentUser.value?.id ?? -1)
function isSelf(row: UserOut): boolean {
  return row.id === myId.value
}

// ---------- 新增 / 编辑 弹窗 ----------
const dialog = reactive({
  visible: false,
  editing: null as UserOut | null,
  submitting: false,
  form: {
    username: '',
    name: '',
    role: 'viewer' as Role,
    enabled: true,
    password: '',
  },
})

function openCreate() {
  dialog.editing = null
  dialog.form = { username: '', name: '', role: 'viewer', enabled: true, password: '' }
  dialog.visible = true
}

function openEdit(row: UserOut) {
  dialog.editing = row
  dialog.form = {
    username: row.username,
    name: row.name,
    role: row.role as Role,
    enabled: row.enabled,
    password: '',
  }
  dialog.visible = true
}

async function handleSubmit() {
  if (dialog.editing) {
    if (!dialog.form.name.trim()) {
      ElMessage.warning('请输入姓名')
      return
    }
  } else {
    if (!dialog.form.username.trim()) {
      ElMessage.warning('请输入用户名')
      return
    }
    if (!dialog.form.name.trim()) {
      ElMessage.warning('请输入姓名')
      return
    }
    if (!dialog.form.password) {
      ElMessage.warning('请输入初始密码')
      return
    }
  }
  dialog.submitting = true
  try {
    if (dialog.editing) {
      const self = isSelf(dialog.editing)
      const patch: { name: string; role?: Role; enabled?: boolean; password?: string } = {
        name: dialog.form.name.trim(),
      }
      // 后端：编辑自己时 body 含 role/enabled 字段即 400（即使值未变），故自己只提交 name/密码
      if (!self) {
        patch.role = dialog.form.role
        patch.enabled = dialog.form.enabled
      }
      // 重置密码可空：留空不提交 password 字段（改自己密码是允许的改密通道）
      if (dialog.form.password) patch.password = dialog.form.password
      await updateUser(dialog.editing.id, patch)
      ElMessage.success('账号已更新')
    } else {
      await createUser({
        username: dialog.form.username.trim(),
        password: dialog.form.password,
        name: dialog.form.name.trim(),
        role: dialog.form.role,
      })
      ElMessage.success('账号已创建')
    }
    dialog.visible = false
    await loadUsers()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    dialog.submitting = false
  }
}

async function handleDelete(row: UserOut) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.username}」吗？删除后该账号立即无法登录，且不可恢复。`,
      '删除账号确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('账号已删除')
    await loadUsers()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  }
}

// ============================================================
// 审计日志
// ============================================================
const audit = reactive({
  loading: false,
  actionType: '',
  username: '',
  page: 1,
  pageSize: 20,
  total: 0,
  items: [] as AuditLogOut[],
})

async function loadAudit() {
  audit.loading = true
  try {
    const res = await listAuditLogs({
      actionType: audit.actionType || undefined,
      username: audit.username.trim() || undefined,
      page: audit.page,
      pageSize: audit.pageSize,
    })
    audit.total = res.total
    audit.items = res.items
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载审计日志失败')
  } finally {
    audit.loading = false
  }
}

function searchAudit() {
  audit.page = 1
  loadAudit()
}

function onAuditPageChange(page: number) {
  audit.page = page
  loadAudit()
}

const activeTab = ref('accounts')

onMounted(() => {
  loadUsers()
  loadAudit()
})
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">基础设置 / 账号与审计</div>
        <h1>账号与审计</h1>
        <div class="desc">管理平台账号（角色：管理 / 可编辑 / 只读），并查询全部业务写操作与登录认证审计记录。</div>
      </div>
      <div class="head-actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新增账号</el-button>
      </div>
    </div>

    <!-- 统计卡 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div>
          <div class="s-label">账号总数</div>
          <div class="s-value">{{ stats.total }}</div>
          <div class="s-sub">平台全部登录账号</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><User /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">启用中</div>
          <div class="s-value">{{ stats.enabled }}</div>
          <div class="s-sub">禁用账号立即无法登录</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><UserFilled /></el-icon>
      </div>
      <div class="stat-card">
        <div>
          <div class="s-label">管理员</div>
          <div class="s-value">{{ stats.admins }}</div>
          <div class="s-sub">仅管理员可访问本页</div>
        </div>
        <el-icon class="s-icon" aria-hidden="true"><Document /></el-icon>
      </div>
    </div>

    <!-- 权限说明 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>
        管理：全部权限（含账号与审计）；可编辑：业务写操作（资产 / 销售 / 出库 / 基础资料）；只读：仅查看，全部写入口禁用。
      </span>
    </div>

    <!-- 页签卡 -->
    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <!-- ============ 账号管理 ============ -->
        <el-tab-pane label="账号管理" name="accounts">
          <div class="table-head">
            <span class="t">账号列表</span>
            <span class="c">共 {{ users.length }} 条</span>
          </div>

          <el-table v-loading="loadingUsers" :data="users" border stripe>
            <el-table-column prop="username" label="用户名" width="160" align="left">
              <template #default="{ row }">
                <span style="font-weight: 500;">{{ row.username }}</span>
                <el-tag v-if="isSelf(row)" size="small" effect="plain" class="tag-gray" style="margin-left: 6px;">
                  当前登录
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="姓名" min-width="140" align="left">
              <template #default="{ row }">{{ row.name || '-' }}</template>
            </el-table-column>
            <el-table-column label="角色" width="110" align="center">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  effect="light"
                  :class="row.role === 'admin' ? 'tag-blue' : row.role === 'editor' ? 'tag-green' : 'tag-gray'"
                >
                  {{ roleLabel(row.role) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.enabled ? 'success' : 'info'" effect="light">
                  {{ row.enabled ? '启用' : '禁用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="150" align="left">
              <template #default="{ row }">{{ row.createdAt || '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right" align="center">
              <template #default="{ row }">
                <div class="op-actions">
                  <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
                  <el-button
                    link
                    type="danger"
                    size="small"
                    :disabled="isSelf(row)"
                    @click="handleDelete(row)"
                  >
                    删除
                  </el-button>
                </div>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无账号" :image-size="80" />
            </template>
          </el-table>
        </el-tab-pane>

        <!-- ============ 审计日志 ============ -->
        <el-tab-pane label="审计日志" name="audit">
          <div class="table-head">
            <span class="t">操作审计记录</span>
            <span class="c">共 {{ audit.total }} 条</span>
          </div>

          <div class="toolbar">
            <el-select v-model="audit.actionType" style="width: 150px;" @change="searchAudit">
              <el-option v-for="o in ACTION_TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <el-input
              v-model="audit.username"
              placeholder="搜索操作人用户名"
              clearable
              style="width: 220px;"
              :prefix-icon="Search"
              @keyup.enter="searchAudit"
              @clear="searchAudit"
            />
            <el-button type="primary" @click="searchAudit">查询</el-button>
          </div>

          <el-table v-loading="audit.loading" :data="audit.items" border stripe>
            <el-table-column prop="time" label="时间" width="150" align="left" />
            <el-table-column prop="username" label="操作人" width="130" align="left">
              <template #default="{ row }">{{ row.username || '-' }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" effect="light" class="tag-purple">{{ actionTypeLabel(row.actionType) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="action" label="操作" width="150" align="left" />
            <el-table-column label="对象" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ row.targetName || row.target || '-' }}</template>
            </el-table-column>
            <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ row.detail || '-' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无审计记录" :image-size="80" />
            </template>
          </el-table>

          <div class="pagination">
            <el-pagination
              v-model:current-page="audit.page"
              :page-size="audit.pageSize"
              :total="audit.total"
              layout="total, prev, pager, next"
              @current-change="onAuditPageChange"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 新增 / 编辑 账号弹窗 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.editing ? `编辑账号 · ${dialog.editing.username}` : '新增账号'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-width="90px">
        <el-form-item v-if="!dialog.editing" label="用户名" required>
          <el-input v-model="dialog.form.username" placeholder="登录用户名（唯一）" />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="dialog.form.name" placeholder="显示姓名" />
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select
            v-model="dialog.form.role"
            style="width: 100%;"
            :disabled="!!dialog.editing && isSelf(dialog.editing)"
          >
            <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch
            v-model="dialog.form.enabled"
            :disabled="!!dialog.editing && isSelf(dialog.editing)"
          />
        </el-form-item>
        <el-form-item :label="dialog.editing ? '重置密码' : '初始密码'" :required="!dialog.editing">
          <el-input
            v-model="dialog.form.password"
            type="password"
            show-password
            :placeholder="dialog.editing ? '留空则不修改密码' : '初始登录密码'"
          />
        </el-form-item>
        <el-alert
          v-if="dialog.editing && isSelf(dialog.editing)"
          title="不能修改自己的角色或启用状态（可通过「重置密码」修改自己的密码）。"
          type="info"
          :closable="false"
          show-icon
        />
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 操作列按钮组：与全站 .op-actions 结构一致 */
.op-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.op-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
