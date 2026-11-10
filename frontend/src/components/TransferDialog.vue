<script setup lang="ts">
/**
 * 销售订单转交/分配对话框（ADR-012 §5.1 纯移交制；ADR-051 叠加主管分配模式）：
 * - transfer（默认）：负责人 → 下拉选新负责人（商务/管理员启用账号）→ claimProject(id, newOwner)；
 *   admin → 额外可选「接手给我」（newOwner 空）。
 * - assign（ADR-051）：商务主管/管理员对任意可见项目「分配/改派」——下拉只列
 *   启用中的商务（role==='editor'，前端过滤，契约见 ADR-051 §6），必选目标商务。
 * 打开时现取 GET /users/options（账号列表可能变化，不做全局缓存）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { claimProject, showError, userOptions, type UserOption } from '@/api'
import { currentUser, isAdmin } from '@/auth'
// ADR-058：username→name 展示解析（value 仍提交 username，仅显示层换姓名）
import { nameOf } from '@/utils/userName'

const SELF_KEY = '__self__'

const props = defineProps<{
  modelValue: boolean
  project: { id: number; name: string; businessOwner?: string } | null
  /** ADR-051：'assign' = 主管/管理员分配/改派（下拉仅商务 editor）；'transfer' = 原转交语义 */
  mode?: 'transfer' | 'assign'
}>()
const isAssign = computed(() => props.mode === 'assign')
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

/** 转交目标 = 启用商务账号（排除当前负责人本人）；
 *  ADR-051 分配模式 = 仅启用中的商务（role==='editor'，不含 admin） */
const targets = computed(() =>
  options.value
    .filter((o) => (isAssign.value ? o.role === 'editor' : true))
    .filter((o) => o.username !== props.project?.businessOwner),
)
// ADR-058：选项只显示姓名（原「姓名（账号）」）；空 name 回退 username；value 仍提交 username（不动）
const label = (o: UserOption) => (o.name || '').trim() || o.username
const submitLabel = computed(() => {
  if (isAssign.value) return props.project?.businessOwner ? '确认改派' : '确认分配'
  return selected.value === SELF_KEY ? '确认接手' : '确认转交'
})

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
    if (isAssign.value) {
      ElMessage.success(props.project?.businessOwner ? '改派成功，商务负责人已变更' : '分配成功，商务负责人已指定')
    } else {
      ElMessage.success(toSelf ? '接手成功，该订单现在归你负责' : '转交成功，商务负责人已变更')
    }
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
  <el-dialog v-model="visible" :title="isAssign ? (project?.businessOwner ? '改派销售订单' : '分配销售订单') : '转交销售订单'" width="440" append-to-body>
    <div v-if="project" class="tf-body">
      <p class="tf-line">
        销售订单：<b>{{ project.name }}</b>
        <template v-if="project.businessOwner">
          <!-- ADR-058：当前负责人显示姓名（businessOwner 是 username，经 nameOf 解析；选项来自 /users/options，查不到回退原值） -->
          （当前负责人：<b>{{ nameOf(project.businessOwner, options) }}</b>）
        </template>
      </p>
      <p class="tf-tip muted">
        {{ isAssign
          ? '分配/改派后由目标商务负责该订单的定价审核（确认下单/驳回）。'
          : '转交后由新负责人负责该订单的定价审核（确认下单/驳回）。' }}
      </p>
      <el-select v-model="selected" placeholder="请选择目标商务账号" style="width: 100%">
        <!-- 2026-10-19 排查修复：无主单 admin 也提供「接手给我」（原条件要求有主，admin 在编辑页无法接手）；
             ADR-051 分配模式不含该选项（下拉只列商务 editor） -->
        <!-- ADR-058：显示当前用户姓名（name 为空回退 username） -->
        <el-option
          v-if="isAdmin && !isAssign"
          :value="SELF_KEY"
          :label="`接手给我（admin · ${(currentUser?.name || '').trim() || currentUser?.username}）`"
        />
        <el-option v-for="o in targets" :key="o.username" :value="o.username" :label="label(o)" />
      </el-select>
      <p v-if="!targets.length" class="tf-empty muted">暂无可用的商务账号</p>
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
