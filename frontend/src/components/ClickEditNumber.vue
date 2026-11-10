<script setup lang="ts">
/**
 * 点击即改数字（ADR-059）：常态显示数值文本（默认 slot 渲染，非输入框），
 * 点击就地变 el-input-number（预填当前值 + 自动聚焦）；
 * 失焦/回车提交写回 v-model，Esc 恢复原值。
 * 同一时刻全局只允许一个单元格处于编辑态（模块级注册，另一格进入编辑时自动收拢本格）。
 * 纯展示层组件：提交值 = 用户编辑值，直接写回父级响应式字段（l.price / l.qty / l.amount）。
 */
import { onBeforeUnmount, ref } from 'vue'
import { ElInputNumber, ElMessage } from 'element-plus'
import { amountInputFormatter, amountInputParser } from '@/types'

const props = withDefaults(defineProps<{
  /** v-model：当前值（null = 未填） */
  modelValue: number | null
  min?: number
  /** 上限（ADR-062）：null/undefined = 不限；commit 时超上限截断到 max 并弹 maxMessage 警告（只弹一次） */
  max?: number | null
  /** 超上限截断时的警告文案（ADR-062；max 生效时才用） */
  maxMessage?: string
  /** 禁用（ADR-062）：常态文本不可点进编辑（如本行请求在飞） */
  disabled?: boolean
  precision?: number
  step?: number
  /** 组件宽度（常态文本与编辑框共用），默认占满列宽 */
  width?: string
  placeholder?: string
}>(), {
  min: 0,
  max: null,
  maxMessage: '',
  disabled: false,
  step: 1,
  width: '100%',
  placeholder: '',
})
const emit = defineEmits<{ (e: 'update:modelValue', v: number | null): void }>()

// ==================== 全局单编辑态（模块级：跨表格/跨合同只允许一个单元格在编辑） ====================
interface EditorHandle { id: number; close: () => void }
let activeEditor: EditorHandle | null = null
let editorSeq = 0
const myId = ++editorSeq

const editing = ref(false)
const draft = ref<number | null>(props.modelValue)
const inputRef = ref<InstanceType<typeof ElInputNumber>>()

function open() {
  if (editing.value) return
  if (props.disabled) return // ADR-062：禁用态不可点进编辑
  draft.value = props.modelValue
  editing.value = true
  // 另一格正在编辑 → 收拢（其 blur 已先行提交；此处兜底直接提交）
  if (activeEditor && activeEditor.id !== myId) activeEditor.close()
  activeEditor = { id: myId, close: () => closeEdit(true) }
  // 等输入框渲染后自动聚焦
  requestAnimationFrame(() => inputRef.value?.focus())
}
/** 收拢：commit=true 时把编辑值写回 v-model（值未变则不 emit，保持「只传变更」口径）
 *  ADR-062：commit 且超上限 → 先截断到 max + 弹一次 maxMessage 警告，再 emit 截断后的值；
 *  Esc 分支（onKeydown 已把 draft 还原为 modelValue）→ 不超 max、draft===modelValue → 不截断/不弹/不 emit */
function closeEdit(commit: boolean) {
  if (!editing.value) return
  editing.value = false
  if (commit && props.max != null && draft.value != null && draft.value > props.max) {
    draft.value = props.max
    if (props.maxMessage) ElMessage.warning(props.maxMessage)
  }
  if (commit && draft.value !== props.modelValue) emit('update:modelValue', draft.value)
  if (activeEditor?.id === myId) activeEditor = null
}
/** 回车提交（EP 2.14 el-input-number 不内置 Enter 处理，此处兜底）；Esc → 恢复原值 */
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
  <span class="cen" :style="{ width: width }" @keydown.capture="editing && onKeydown($event)">
    <!-- 常态：数值文本（默认 slot 渲染），hover 轻微可编辑提示；ADR-062：disabled 时不可点（cursor 非 pointer） -->
    <span
      v-if="!editing"
      class="cen-view"
      :class="{ 'cen-view-disabled': disabled }"
      :role="disabled ? undefined : 'button'"
      :tabindex="disabled ? -1 : 0"
      @click="open"
      @keydown.enter.prevent="open"
    >
      <slot>{{ modelValue ?? '-' }}</slot>
    </span>
    <!-- 编辑态：就地 el-input-number（复用既有金额 formatter/parser；失焦提交，回车/Esc 由上方 keydown capture 处理）
         ADR-062：max 截断统一在 closeEdit 处理（不透传 :max 给 el-input-number——
         EP 原生 max 会在 blur 时先行钳值，导致 draft 已 ≤ max、closeEdit 的截断分支不触发，警告被吞） -->
    <el-input-number
      v-else
      ref="inputRef"
      :model-value="draft"
      @update:model-value="(v: number | null | undefined) => (draft = v ?? null)"
      :min="min"
      :precision="precision"
      :step="step"
      :controls="false"
      :formatter="amountInputFormatter"
      :parser="amountInputParser"
      :placeholder="placeholder"
      class="cen-input"
      @blur="closeEdit(true)"
    />
  </span>
</template>

<style scoped>
.cen {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}
/* 常态文本：主蓝淡色 hover 提示可编辑（主蓝 #1769D4 + 浅蓝底 #EAF3FF，遵循 core-holdings-ui） */
.cen-view {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 24px;
  padding: 2px 6px;
  border-radius: 4px;
  border-bottom: 1px dashed transparent;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.cen-view:hover,
.cen-view:focus-visible {
  color: var(--primary-color);
  background: var(--primary-light);
  border-bottom-color: var(--primary-color);
  outline: none;
}
/* ADR-062：禁用态（如本行请求在飞）——不可点、无 hover 提示 */
.cen-view-disabled {
  cursor: default;
}
.cen-view-disabled:hover,
.cen-view-disabled:focus-visible {
  color: var(--text-primary);
  background: transparent;
  border-bottom-color: transparent;
}
/* 编辑态输入框：占满组件宽度、值居中、等宽数字（同既有 .rv-amount-input 口径） */
.cen-input {
  width: 100%;
  min-width: 0;
}
.cen-input :deep(.el-input__inner) {
  text-align: center;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
