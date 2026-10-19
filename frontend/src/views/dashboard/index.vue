<script setup lang="ts">
/**
 * 首页仪表盘（经营看板）
 *
 * 区域：板块数量总览 / 待办提醒
 */
import { computed } from 'vue'
import {
  Box,
  Odometer,
  Bell,
} from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { getDashboard } from '@/api'
import { formatMoney, formatWan } from '@/types'

const router = useRouter()

const data = computed(() => getDashboard())

/** 无任何待办（临期产品与长期未跟进项目均为空） */
const noTodos = computed(
  () =>
    data.value.todos.expiring.length +
    data.value.todos.staleProjects.length ===
    0,
)

const wipBoards = new Set(['compute'])

function goBoard(board: string) {
  router.push(`/assets/${board}`)
}

function handleBoardRow(row: { board: string }) {
  goBoard(row.board)
}
</script>

<template>
  <div class="page-container">
    <div class="page-title">
      <el-icon :size="22" style="color: var(--primary-color); vertical-align: -3px;"><Odometer /></el-icon>
      <span style="margin-left: 8px;">经营看板</span>
    </div>

    <el-row :gutter="16">
      <!-- 板块数量 -->
      <el-col :xs="24">
        <el-card shadow="never" style="height: 100%;">
          <template #header>
            <div class="card-header">
              <div class="title">
                <el-icon><Box /></el-icon>
                <span>板块数量总览</span>
              </div>
              <span class="muted" style="font-size: 12px;">点击行进入对应板块</span>
            </div>
          </template>
          <el-table :data="data.boardStats" class="board-table" @row-click="handleBoardRow">
            <el-table-column label="板块" min-width="130">
              <template #default="{ row }">
                <span class="board-name">
                  {{ row.label }}
                  <el-tag
                    v-if="wipBoards.has(row.board)"
                    size="small"
                    type="warning"
                    effect="plain"
                    style="margin-left: 6px;"
                  >
                    建设中
                  </el-tag>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="产品项数" width="90" align="right">
              <template #default="{ row }">{{ row.count }} 项</template>
            </el-table-column>
            <el-table-column label="总数量" min-width="100" align="right">
              <template #default="{ row }">{{ formatWan(row.inQty) }}</template>
            </el-table-column>
            <el-table-column label="已锁定" min-width="90" align="right">
              <template #default="{ row }">
                <span :style="{ color: row.lockedQty > 0 ? 'var(--primary-color)' : undefined, fontWeight: row.lockedQty > 0 ? 600 : 400 }">{{ formatWan(row.lockedQty) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="已交付" min-width="90" align="right">
              <template #default="{ row }">
                <span :style="{ color: row.shippedQty > 0 ? 'var(--warning-color)' : undefined, fontWeight: row.shippedQty > 0 ? 600 : 400 }">{{ formatWan(row.shippedQty) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="当前可售" min-width="110" align="right">
              <template #default="{ row }">
                <span style="color: var(--success-color); font-weight: 600;">{{ formatMoney(row.availableValue) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="累计已售" min-width="110" align="right">
              <template #default="{ row }">
                <span :style="{ color: row.sold > 0 ? 'var(--info-purple)' : undefined }">{{ formatMoney(row.sold) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

    </el-row>

    <el-row :gutter="16">
      <!-- 待办提醒 -->
      <el-col :xs="24">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <div class="title">
                <el-icon style="color: var(--warning-color);"><Bell /></el-icon>
                <span>待办提醒</span>
              </div>
            </div>
          </template>
          <el-empty v-if="noTodos" description="暂无待办事项" :image-size="70" />
          <div v-else class="todo-groups">
            <div class="todo-group" v-if="data.todos.expiring.length">
              <div class="todo-group-title">
                <el-tag size="small" type="warning" effect="light">临期产品</el-tag>
                <span class="muted" style="font-size: 12px;">90 天内到期 · 共 {{ data.todos.expiring.length }} 项</span>
              </div>
              <div
                v-for="a in data.todos.expiring.slice(0, 4)"
                :key="a.id"
                class="todo-item"
                @click="$router.push(`/assets/${a.id}/detail`)"
              >
                <span class="todo-name">{{ a.name }}</span>
                <span class="muted">{{ a.code }} · 到期 {{ a.expiryDate }}</span>
              </div>
            </div>
            <div class="todo-group" v-if="data.todos.staleProjects.length">
              <div class="todo-group-title">
                <el-tag size="small" type="info" effect="light">长期未更新项目</el-tag>
                <span class="muted" style="font-size: 12px;">30 天以上未跟进</span>
              </div>
              <div
                v-for="p in data.todos.staleProjects"
                :key="p.id"
                class="todo-item"
                @click="$router.push(`/sales/projects/${p.id}/edit`)"
              >
                <span class="todo-name">{{ p.name }}</span>
                <span class="muted">{{ p.code }} · 最近跟进 {{ p.lastFollowDate || '无' }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

    </el-row>
  </div>
</template>

<style scoped>
/* 板块表格 */
.board-table :deep(.el-table__row) {
  cursor: pointer;
}
.board-name {
  font-weight: 500;
}
.board-hint {
  margin-top: 8px;
  font-size: 12px;
}

/* 待办 */
.todo-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.todo-group-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.todo-item:hover {
  border-color: #cfe0f5;
  background: var(--row-hover);
}
.todo-name {
  font-size: 14px;
  font-weight: 500;
}
</style>
