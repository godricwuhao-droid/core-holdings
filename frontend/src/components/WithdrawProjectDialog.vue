<script setup lang="ts">
/**
 * 撤销待审核订单对话框（ADR-026 / TASK-FE-029）：
 * - 语义：撤销 = 终止原单（释放锁定、留痕）+ 全部明细自动回填下单人购物车，改单后重新提交；
 * - 必填原因（1–200 字）→ POST /projects/{id}/withdraw；
 * - 成功后 toast + 关闭并 emit('done')：镜像刷新与跳转由调用方决定
 *   （列表入口停留刷新；详情/编辑入口 await refresh() 后 router.push('/cart')），
 *   以保证 refresh 先于跳转、购物车页读到回填行；
 * - 失败统一走 showError（403/400 文案由后端 detail 给出）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { showError, withdrawProject } from '@/api'

const props = defineProps<{
  modelValue: boolean
  project: { id: number; name: string } | null
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; done: [] }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})
const reason = ref('')
const submitting = ref(false)

// 每次打开重置原因与 loading（关闭后残留上次输入）
watch(visible, (v) => {
  if (!v) return
  reason.value = ''
  submitting.value = false
})

async function onConfirm() {
  const p = props.project
  if (!p || submitting.value) return
  if (!reason.value.trim()) {
    ElMessage.warning('请填写撤销原因')
    return
  }
  submitting.value = true
  try {
    const res = await withdrawProject(p.id, reason.value.trim())
    ElMessage.success('已撤销，明细已回填到购物车')
    // 回填容错（ADR-026 Decision 4）：有跳过行时补一条提示，避免用户以为明细全在购物车
    if (res.skipped > 0) {
      const why = res.skippedReasons?.length ? `：${res.skippedReasons.join('；')}` : ''
      ElMessage.warning(`${res.skipped} 行明细未能回填购物车${why}`)
    }
    visible.value = false
    emit('done')
  } catch (e) {
    showError(e, '撤销失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="撤销订单" class="dlg-form" :close-on-click-modal="false">
    <div v-if="project" class="wd-body">
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>撤销后原单终止、锁定释放，明细将回填到你的购物车，可在购物车修改后重新提交。</span>
      </div>
      <p class="wd-line">销售订单：<b>{{ project.name }}</b></p>
      <div class="wd-field">
        <label class="wd-label" for="withdraw-reason">撤销原因 <span class="wd-req" aria-hidden="true">*</span></label>
        <el-input
          id="withdraw-reason"
          v-model="reason"
          type="textarea"
          :rows="3"
          maxlength="200"
          show-word-limit
          placeholder="请填写撤销原因（1–200 字）"
        />
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="danger" :loading="submitting" @click="onConfirm">确认撤销</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.wd-line {
  margin: 16px 0 12px;
  font-size: 13px;
  color: var(--text-body);
}
.wd-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wd-label {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 20px;
}
.wd-req {
  color: var(--danger-color);
}
</style>
