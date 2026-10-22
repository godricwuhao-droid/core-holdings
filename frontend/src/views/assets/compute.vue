<script setup lang="ts">
/**
 * 算力服务 - 建设中
 *
 * 展示 3 项算力服务器产品（只读），不可操作；后续启用时按完整产品页实现。
 */
import { computed } from 'vue'
import { ASSET_STOCK_STATE, assetStockState, expiryText, formatMoney, type Asset } from '@/types'
import { db } from '@/api'

const list = computed<Asset[]>(() => db.assets.filter((a) => a.board === 'compute'))
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">产品及服务 / 算力服务</div>
        <h1>
          算力服务
          <el-tag type="warning" size="small" effect="plain">建设中</el-tag>
        </h1>
        <div class="desc">算力服务器产品台账，按服务期管理可售额度，支持资源池与交付开通记录。</div>
      </div>
    </div>

    <!-- ADR-041/UI-CLEANUP-20261022：移除页面说明条（用户要求，纯展示删除） -->
    <!-- 表格卡 -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">算力服务器产品</span>
        <span class="c">共 {{ list.length }} 条</span>
      </div>

      <el-table :data="list" border stripe>
        <el-table-column prop="code" label="产品编号" min-width="120" align="left" />
        <el-table-column label="产品名称" min-width="220">
          <template #default="{ row }">
            <div class="asset-name">{{ row.name }}</div>
            <div class="asset-spec muted">{{ row.spec }}</div>
          </template>
        </el-table-column>
        <el-table-column label="服务到期" width="120" align="left">
          <template #default="{ row }">{{ expiryText(row) }}</template>
        </el-table-column>
        <el-table-column label="台数" width="90" align="right">
          <template #default="{ row }">{{ row.quantity }} 台</template>
        </el-table-column>
        <el-table-column label="累计已售服务" width="130" align="right">
          <template #default="{ row }">
            <span style="color: var(--info-purple);">{{ formatMoney(row.soldAmount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="ASSET_STOCK_STATE[assetStockState(row)].tag" size="small" effect="light">
              {{ ASSET_STOCK_STATE[assetStockState(row)].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">{{ row.remark }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.asset-name {
  font-weight: 500;
  font-size: 13px;
}
.asset-spec {
  font-size: 12px;
  margin-top: 2px;
}
</style>
