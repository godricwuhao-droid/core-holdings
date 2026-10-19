<script setup lang="ts">
/**
 * 销售订单转交对话框（ADR-012 §5.1 纯移交制）：
 * - 负责人 → 下拉选新负责人（商务/管理员启用账号）→ claimProject(id, newOwner)；
 * - admin → 额外可选「接手给我」（newOwner 空）。
 * 打开时现取 GET /users/options（账号列表可能变化，不做全局缓存）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { claimProject, showError, userOptions, type UserOption } from '@/api'
import { currentUser, isAdmin } from '@/auth'

const SELF_KEY = '__self__'

const props = defineProps<{
  modelValue: boolean
  project: { id: number; name: string; businessOwner?: string } | null
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; done: [] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})
const options = ref<UserOption[]>([])
const submitting = ref(false)
const selected = ref('')

watch(visible, async (v) => {
  if (!v) return
  selected.value = ''
  options.value = []
  try {
    options.value = await userOptions()
  } catch {
    options.value = []
  }
})

/** 转交目标 = 启用商务账号（排除当前负责人本人） */
const targets = computed(() =>
  options.value.filter((o) => o.username !== props.project?.businessOwner),
)
const label = (o: UserOption) => (o.name ? `${o.name}（${o.username}）` : o.username)
const submitLabel = computed(() => (selected.value === SELF_KEY ? '确认接手' : '确认转交'))

async function onConfirm() {
  const p = props.project
  if (!p) return
  if (!selected.value) {
    ElMessage.warning('请选择目标商务账号')
    return
  }
  submitting.value = true
  try {
    const toSelf = selected.value === SELF_KEY
    await claimProject(p.id, toSelf ? '' : selected.value)
    ElMessage.success(toSelf ? '接手成功，该订单现在归你负责' : '转交成功，商务负责人已变更')
    emit('done')
    visible.value = false
  } catch (e) {
    showError(e, '操作失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="转交销售订单" width="440" append-to-body>
    <div v-if="project" class="tf-body">
      <p class="tf-line">
        销售订单：<b>{{ project.name }}</b>
        <template v-if="project.businessOwner">
          （当前负责人：<b>{{ project.businessOwner }}</b>）
        </template>
      </p>
      <p class="tf-tip muted">转交后由新负责人负责该订单的定价审核（确认下单/驳回）。</p>
      <el-select v-model="selected" placeholder="请选择目标商务账号" style="width: 100%">
        <!-- 2026-10-19 排查修复：无主单 admin 也提供「接手给我」（原条件要求有主，admin 在编辑页无法接手） -->
        <el-option
          v-if="isAdmin"
          :value="SELF_KEY"
          :label="`接手给我（admin · ${currentUser?.username}）`"
        />
        <el-option v-for="o in targets" :key="o.username" :value="o.username" :label="label(o)" />
      </el-select>
      <p v-if="!options.length" class="tf-empty muted">暂无可用的商务账号</p>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="onConfirm">
        {{ submitLabel }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tf-body .tf-line { margin: 0 0 6px; }
.tf-tip { margin: 0 0 12px; font-size: 12px; }
.tf-empty { margin: 8px 0 0; font-size: 12px; }
.muted { color: var(--el-text-color-secondary, #909399); }
</style>
