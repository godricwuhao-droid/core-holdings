<script setup lang="ts">
/**
 * 基础设置 - 通用 CRUD 页（供应商 / 客户 / 生态人员）
 * 通过路由名区分数据类型
 */
import { computed, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { addBase, db, deleteBase, showError, updateBase, type BaseKind } from '@/api'
import { canWrite, NO_PERM_TIP } from '@/auth'

const route = useRoute()

const kind = computed<BaseKind>(() => {
  if (route.path.includes('suppliers')) return 'suppliers'
  if (route.path.includes('customers')) return 'customers'
  return 'reps'
})

const kindLabel = computed(() =>
  kind.value === 'suppliers' ? '供应商' : kind.value === 'customers' ? '客户' : '生态人员',
)

const kindDesc = computed(() =>
  kind.value === 'suppliers'
    ? '维护供应商主数据，供产品登记时选择供应商。'
    : kind.value === 'customers'
      ? '维护客户主数据，供销售项目建档时选择客户。'
      : '维护公司生态人员名单，供销售项目指派负责人。',
)

const list = computed(() => db[kind.value])

const searchText = ref('')
const filtered = computed(() =>
  list.value.filter((r) => !searchText.value.trim() || r.name.includes(searchText.value.trim())),
)

const dialog = reactive({
  visible: false,
  editing: null as { id: number } | null,
  submitting: false,
  form: { name: '', contact: '', phone: '', remark: '' },
})

function openCreate() {
  dialog.editing = null
  dialog.form = { name: '', contact: '', phone: '', remark: '' }
  dialog.visible = true
}

function openEdit(row: { id: number; name: string; contact: string; phone: string; remark: string }) {
  dialog.editing = row
  dialog.form = { name: row.name, contact: row.contact, phone: row.phone, remark: row.remark }
  dialog.visible = true
}

async function handleSubmit() {
  if (!dialog.form.name.trim()) {
    ElMessage.warning(`请输入${kindLabel.value}名称`)
    return
  }
  dialog.submitting = true
  try {
    if (dialog.editing) {
      await updateBase(kind.value, dialog.editing.id, dialog.form)
      ElMessage.success('更新成功')
    } else {
      await addBase(kind.value, dialog.form)
      ElMessage.success('新增成功')
    }
    dialog.visible = false
  } catch (e) {
    showError(e, '保存失败')
  } finally {
    dialog.submitting = false
  }
}

async function handleDelete(row: { id: number; name: string }) {
  try {
    await ElMessageBox.confirm(`确定删除${kindLabel.value}「${row.name}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteBase(kind.value, row.id)
  ElMessage.success('删除成功')
}
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">基础设置 / {{ kindLabel }}管理</div>
        <h1>{{ kindLabel }}管理</h1>
        <div class="desc">{{ kindDesc }}</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button type="primary" :icon="Plus" :disabled="!canWrite" @click="openCreate">
              新增{{ kindLabel }}
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 表格卡 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">{{ kindLabel }}列表</span>
        <span class="c">共 {{ filtered.length }} 条</span>
      </div>

      <div class="toolbar">
        <el-input
          v-model="searchText"
          :placeholder="`搜索${kindLabel}名称`"
          clearable
          style="width: 240px;"
          :prefix-icon="Search"
        />
      </div>

      <el-table :data="filtered" border stripe>
        <el-table-column prop="name" label="名称" min-width="200" />
        <el-table-column prop="contact" label="联系人" width="140" align="left">
          <template #default="{ row }">{{ row.contact || '-' }}</template>
        </el-table-column>
        <el-table-column prop="phone" label="联系电话" width="160" align="left">
          <template #default="{ row }">{{ row.phone || '-' }}</template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right" align="center">
          <template #default="{ row }">
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip">
                <el-button link type="primary" size="small" :disabled="!canWrite" @click="openEdit(row)">编辑</el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="NO_PERM_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip">
                <el-button link type="danger" size="small" :disabled="!canWrite" @click="handleDelete(row)">删除</el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无数据，点击右上角新增" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialog.visible"
      :title="(dialog.editing ? '编辑' : '新增') + kindLabel"
      class="dlg-form"
      :close-on-click-modal="false"
    >
      <el-form label-width="96px">
        <el-form-item label="名称" required>
          <el-input v-model="dialog.form.name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="dialog.form.contact" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="dialog.form.phone" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 操作列按钮包在 tooltip span 内，间距由 inline-flex 保证（不依赖相邻按钮选择器） */
.op-tip {
  display: inline-flex;
  margin-left: 8px;
}
.op-tip:first-child {
  margin-left: 0;
}
</style>
