<script setup lang="ts">
/**
 * 其他功能（预留）
 */
import { MoreFilled } from '@element-plus/icons-vue'
</script>

<template>
  <div class="page-container">
    <div class="page-title">
      <el-icon :size="22" style="color: var(--primary-color); vertical-align: -3px;"><MoreFilled /></el-icon>
      <span style="margin-left: 8px;">其他功能（预留）</span>
    </div>

    <el-card shadow="never">
      <el-empty description="功能规划中：报表中心 / 审批流 / 价格版本 / 权限细分 / 批量导入 等，敬请期待">
        <el-tag type="info" effect="plain">预留</el-tag>
      </el-empty>
    </el-card>
  </div>
</template>
