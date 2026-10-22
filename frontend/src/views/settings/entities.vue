<script setup lang="ts">
/**
 * 基础设置 - 公司主体（ENTITIES-20261022 / ADR-035；FORMS-20261022 / ADR-036 起由「资产主体」改名，
 * 仅 admin/editor，路由守卫已拦截 viewer）
 *
 * 主体清单 = 我司签约主体（assets.subject 存公司全称）。数据源为 bootstrap 镜像 db.entities
 * （全量、无角色过滤；写操作经 afterWrite 自动同步镜像，本页无需手动 reload）。
 * 交互：
 *  - 新增/编辑：弹窗 .dlg-form（公司全称 2–64 字必填、简称 1–32 字必填），失败走 showError（400「主体已存在」等后端文案）
 *  - 删除：ElMessageBox.confirm；被产品引用 → 400「该主体下存在 N 个产品，不可删除」由 showError 展示
 *  - 改名（全称变化）：二次确认（存量产品仍挂旧名称，需到产品页逐个改选；ADR-035 Decision 5）
 */
import { reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, Plus } from '@element-plus/icons-vue'
import { createEntity, db, deleteEntity, showError, updateEntity } from '@/api'
import { formatDate, type Entity } from '@/types'

// ---------- 新增 / 编辑 弹窗 ----------
const dialog = reactive({
  visible: false,
  editing: null as Entity | null,
  submitting: false,
  form: {
    name: '',
    short: '',
  },
})

function openCreate() {
  dialog.editing = null
  dialog.form = { name: '', short: '' }
  dialog.visible = true
}

function openEdit(row: Entity) {
  dialog.editing = row
  dialog.form = { name: row.name, short: row.short }
  dialog.visible = true
}

/** 前端预校验（长度口径与后端一致：name 2–64 字、short 1–32 字） */
function validateForm(): boolean {
  const name = dialog.form.name.trim()
  const short = dialog.form.short.trim()
  if (!name) {
    ElMessage.warning('请输入公司全称')
    return false
  }
  if (name.length < 2 || name.length > 64) {
    ElMessage.warning('公司全称需为 2–64 字')
    return false
  }
  if (!short) {
    ElMessage.warning('请输入简称')
    return false
  }
  if (short.length < 1 || short.length > 32) {
    ElMessage.warning('简称需为 1–32 字')
    return false
  }
  return true
}

async function handleSubmit() {
  if (!validateForm()) return
  const name = dialog.form.name.trim()
  const short = dialog.form.short.trim()
  dialog.submitting = true
  try {
    if (dialog.editing) {
      // ADR-035 Decision 5：仅「全称变化」需二次确认（存量产品仍挂旧名称）；只改简称不弹
      if (name !== dialog.editing.name) {
        await ElMessageBox.confirm(
          '修改主体全称后，存量产品仍挂旧名称，需到产品页逐个改选。确定修改？',
          '修改主体全称确认',
          { type: 'warning', confirmButtonText: '确定修改', cancelButtonText: '取消' },
        )
      }
      await updateEntity(dialog.editing.id, name, short)
      ElMessage.success('主体已更新')
    } else {
      await createEntity(name, short)
      ElMessage.success('主体已创建')
    }
    dialog.visible = false
  } catch (e) {
    // 取消二次确认（ElMessageBox reject）不提示；接口错误（400「主体已存在」等）走 showError
    if (e instanceof Error) showError(e, '保存失败')
  } finally {
    dialog.submitting = false
  }
}

async function handleDelete(row: Entity) {
  try {
    await ElMessageBox.confirm(
      `确定删除主体「${row.name}」吗？被产品引用的主体不可删除。`,
      '删除主体确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteEntity(row.id)
    ElMessage.success('主体已删除')
  } catch (e) {
    // 400「该主体下存在 N 个产品，不可删除」由 showError 展示后端文案
    showError(e, '删除失败')
  }
}
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">基础设置 / 公司主体</div>
        <h1>公司主体</h1>
        <div class="desc">维护我司签约主体清单（产品「所在主体」下拉与主体筛选的数据来源）。产品存储口径为公司全称，简称仅用于展示。</div>
      </div>
      <div class="head-actions">
        <el-button type="primary" :icon="Plus" @click="openCreate">新增主体</el-button>
      </div>
    </div>

    <!-- 权限/行为说明 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>
        修改主体全称不会回写存量产品（产品仍挂旧名称，需到产品页逐个改选）；被产品引用的主体不可删除。
      </span>
    </div>

    <!-- 主体列表 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">主体列表</span>
        <span class="c">共 {{ db.entities.length }} 条</span>
      </div>

      <el-table :data="db.entities" border stripe>
        <el-table-column prop="name" label="主体全称" min-width="260" align="left">
          <template #default="{ row }">
            <span style="font-weight: 500;">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="short" label="简称" min-width="160" align="left">
          <template #default="{ row }">{{ row.short || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="150" align="left">
          <template #default="{ row }">{{ formatDate(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right" align="center">
          <template #default="{ row }">
            <div class="op-actions">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无主体，请添加" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑 主体弹窗 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.editing ? `编辑主体 · ${dialog.editing.name}` : '新增主体'"
      class="dlg-form"
      :close-on-click-modal="false"
    >
      <el-form label-width="96px">
        <el-form-item label="公司全称" required>
          <el-input v-model="dialog.form.name" maxlength="64" show-word-limit placeholder="如：蜂云时代科技有限公司" />
        </el-form-item>
        <el-form-item label="简称" required>
          <el-input v-model="dialog.form.short" maxlength="32" show-word-limit placeholder="如：蜂云时代（列表展示用）" />
        </el-form-item>
        <el-alert
          v-if="dialog.editing && dialog.form.name.trim() !== dialog.editing.name"
          title="修改全称后，存量产品仍挂旧名称，需到产品页逐个改选。"
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
/* 操作列按钮组：与全站 .op-actions 结构一致（同 settings/users.vue） */
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
