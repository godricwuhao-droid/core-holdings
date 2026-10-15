<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { refresh } from '@/api'
import { hasToken } from '@/auth'

// 应用挂载时从后端拉取全量数据填充响应式镜像 db，各页面随即响应式渲染
// 未登录不拉取（bootstrap 需认证；登录页成功后会自行 refresh）
onMounted(() => {
  if (!hasToken()) return
  refresh().catch(() => {
    ElMessage.error('数据加载失败，请检查后端服务')
  })
})
</script>
