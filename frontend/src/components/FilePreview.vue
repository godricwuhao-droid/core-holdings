<template>
  <div class="fp">
    <div class="fp-bar">
      <span class="fp-name">{{ title || filename }}</span>
      <span class="fp-ops">
        <a :href="url" target="_blank" rel="noopener" class="fp-op">新窗口打开</a>
        <a :href="url" download class="fp-op">下载</a>
      </span>
    </div>
    <div class="fp-body">
      <img v-if="kind === 'image'" :src="url" class="fp-img" alt="产品清单预览" />
      <iframe v-else-if="kind === 'pdf'" :src="url" class="fp-pdf" title="PDF 预览"></iframe>
      <div v-else-if="kind === 'docx'" class="fp-docx">
        <div v-if="loading" class="fp-tip">文档解析中…</div>
        <div v-else-if="error" class="fp-tip">解析失败：{{ error }}（可点「下载」查看原文件）</div>
        <div v-else class="docx-render" v-html="html"></div>
      </div>
      <div v-else class="fp-tip">暂不支持在线预览「.{{ ext || '?' }}」，请点「下载」后本地打开。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fileUrl } from '@/api'

const props = withDefaults(
  defineProps<{ filename: string; title?: string }>(),
  { title: '' },
)

const ext = computed(() => (props.filename.split('.').pop() || '').toLowerCase())
const kind = computed<'image' | 'pdf' | 'docx' | 'other'>(() => {
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext.value)) return 'image'
  if (ext.value === 'pdf') return 'pdf'
  if (ext.value === 'docx') return 'docx'
  return 'other'
})
const url = computed(() => fileUrl(props.filename))

const html = ref('')
const loading = ref(false)
const error = ref('')
let aborter: AbortController | null = null

async function loadDocx() {
  if (kind.value !== 'docx') return
  aborter?.abort()
  aborter = new AbortController()
  loading.value = true
  error.value = ''
  html.value = ''
  try {
    const mod = (await import('mammoth/mammoth.browser')) as any
    const mammoth = mod?.default ?? mod
    const res = await fetch(url.value, { signal: aborter.signal })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const buf = await res.arrayBuffer()
    const out = await mammoth.convertToHtml({ arrayBuffer: buf })
    html.value = out.value || '<p>（文档内容为空）</p>'
  } catch (e: any) {
    if (e?.name !== 'AbortError') error.value = e?.message || '未知错误'
  } finally {
    loading.value = false
  }
}

watch(() => props.filename, loadDocx, { immediate: true })
onBeforeUnmount(() => aborter?.abort())
</script>

<style scoped>
.fp {
  border: 1px solid #e1e8f1;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.fp-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid #eef2f7;
  background: #f8fafc;
}
.fp-name {
  font-size: 13px;
  font-weight: 600;
  color: #354a68;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fp-ops {
  flex-shrink: 0;
  display: flex;
  gap: 12px;
}
.fp-op {
  font-size: 12px;
  color: #3b82f6;
  text-decoration: none;
}
.fp-op:hover {
  text-decoration: underline;
}
.fp-body {
  min-height: 120px;
}
.fp-img {
  display: block;
  width: 100%;
  max-height: 70vh;
  object-fit: contain;
  background: #f4f6f9;
}
.fp-pdf {
  width: 100%;
  height: 70vh;
  border: 0;
  display: block;
}
.fp-docx {
  padding: 16px 20px;
  max-height: 70vh;
  overflow: auto;
}
.fp-tip {
  padding: 40px 20px;
  text-align: center;
  color: #70819a;
  font-size: 13px;
}
:deep(.docx-render) {
  font-size: 14px;
  line-height: 1.7;
  color: #333;
  word-break: break-word;
}
:deep(.docx-render) img {
  max-width: 100%;
}
:deep(.docx-render) table {
  border-collapse: collapse;
  max-width: 100%;
}
:deep(.docx-render) td,
:deep(.docx-render) th {
  border: 1px solid #ccc;
  padding: 4px 8px;
}
</style>
