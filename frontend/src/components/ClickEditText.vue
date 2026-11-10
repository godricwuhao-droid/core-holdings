<script setup lang="ts">
/**
 * 点击即改文本（ADR-060）：交互与 ClickEditNumber（ADR-059）完全一致——
 * 常态显示文本（默认 slot 渲染，非输入框），点击就地变 el-input（预填当前值 + 自动聚焦）；
 * 失焦/回车提交写回 v-model（提交前 trim），Esc 恢复原值。
 * 同一时刻全局只允许一个文本格处于编辑态（模块级注册，另一格进入编辑时自动收拢本格）。
 * 纯展示层组件：提交值 = 用户编辑值（trim 后），直接写回父级响应式字段（如 c.customer）。
 */
import { onBeforeUnmount, ref } from 'vue'
import { ElInput } from 'element-plus'

const props = withDefaults(defineProps<{
  /** v-model：当前文本（空串 = 未填） */
  modelValue: string
  maxlength?: number
  /** 组件宽度（常态文本与编辑框共用） */
  width?: string
  placeholder?: string
}>(), {
  maxlength: 128,
  width: '100%',
  placeholder: '',
})
const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

// ==================== 全局单编辑态（模块级：跨表格/跨合同只允许一个文本格在编辑） ====================
interface EditorHandle { id: number; close: () => void }
let activeEditor: EditorHandle | null = null
let editorSeq = 0
const myId = ++editorSeq

const editing = ref(false)
const draft = ref(props.modelValue)
const inputRef = ref<InstanceType<typeof ElInput>>()

function open() {
  if (editing.value) return
  draft.value = props.modelValue
  editing.value = true
  // 另一格正在编辑 → 收拢（其 blur 已先行提交；此处兜底直接提交）
  if (activeEditor && activeEditor.id !== myId) activeEditor.close()
  activeEditor = { id: myId, close: () => closeEdit(true) }
  // 等输入框渲染后自动聚焦
  requestAnimationFrame(() => inputRef.value?.focus())
}
/** 收拢：commit=true 时把编辑值（trim 后）写回 v-model（值未变则不 emit，保持「只传变更」口径） */
function closeEdit(commit: boolean) {
  if (!editing.value) return
  editing.value = false
  const v = (draft.value ?? '').trim()
  if (commit && v !== props.modelValue) emit('update:modelValue', v)
  if (activeEditor?.id === myId) activeEditor = null
}
/** 回车提交；Esc → 恢复原值 */
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    e.preventDefault()
    closeEdit(true)
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    draft.value = props.modelValue
    closeEdit(true)
  }
}
onBeforeUnmount(() => {
  if (activeEditor?.id === myId) activeEditor = null
})
</script>

<template>
  <span class="cet" :style="{ width }" @keydown.capture="editing && onKeydown($event)">
    <!-- 常态：文本（默认 slot 渲染），hover 轻微可编辑提示 -->
    <span v-if="!editing" class="cet-view" role="button" tabindex="0" @click="open" @keydown.enter.prevent="open">
      <slot>{{ modelValue || '-' }}</slot>
    </span>
    <!-- 编辑态：就地 el-input（失焦提交，回车/Esc 由上方 keydown capture 处理） -->
    <el-input
      v-else
      ref="inputRef"
      :model-value="draft"
      @update:model-value="(v: string) => (draft = v)"
      :maxlength="maxlength"
      :placeholder="placeholder"
      class="cet-input"
      @blur="closeEdit(true)"
    />
  </span>
</template>

<style scoped>
.cet {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}
/* 常态文本：主蓝淡色 hover 提示可编辑（主蓝 #1769D4 + 浅蓝底 #EAF3FF，遵循 core-holdings-ui） */
.cet-view {
  display: inline-flex;
  align-items: center;
  width: 100%;
  min-height: 24px;
  padding: 2px 6px;
  border-radius: 4px;
  border-bottom: 1px dashed transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.cet-view:hover,
.cet-view:focus-visible {
  color: var(--primary-color);
  background: var(--primary-light);
  border-bottom-color: var(--primary-color);
  outline: none;
}
/* 编辑态输入框：占满组件宽度（文本左对齐，同原 el-input 口径） */
.cet-input {
  width: 100%;
  min-width: 0;
}
</style>
