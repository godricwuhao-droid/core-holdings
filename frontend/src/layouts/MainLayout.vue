<template>
  <el-container direction="vertical" style="height: 100vh">
    <!-- 顶栏：平台名称 + 系统状态 -->
    <div class="top-header">
      <div class="header-left">
        <span class="header-logo">
          <el-icon :size="24"><Coin /></el-icon>
        </span>
        <span class="header-title">蜂云产品及服务平台</span>
        <el-button
          @click="isCollapse = !isCollapse"
          :icon="isCollapse ? Expand : Fold"
          text
          class="collapse-btn"
          style="font-size: 18px; margin-left: 8px;"
        />
      </div>
      <div class="header-right">
        <el-tag type="success" size="small" effect="light">
          <el-icon style="vertical-align: -2px;"><CircleCheckFilled /></el-icon>
          <span style="margin-left: 4px;">系统运行中</span>
        </el-tag>
        <span class="user-chip">
          <span class="user-name">{{ currentUser?.name || currentUser?.username || '-' }}</span>
          <el-tag
            size="small"
            effect="light"
            :class="'tag-' + roleTagClass"
            style="margin-left: 6px;"
          >
            {{ ROLE_LABELS[currentUser?.role ?? 'viewer'] }}
          </el-tag>
        </span>
        <el-button text class="logout-btn" @click="handleLogout">退出</el-button>
      </div>
    </div>

    <el-container style="min-height: 0;">
      <!-- 侧边栏（浅色） -->
      <el-aside
        :width="isCollapse ? '64px' : '220px'"
        style="background: #ffffff; border-right: 1px solid var(--border-color); transition: width 0.2s; overflow: hidden;"
      >
        <el-menu
          :default-active="activeMenu"
          router
          :collapse="isCollapse"
          background-color="#ffffff"
          text-color="#3d4a5c"
          active-text-color="var(--primary-color)"
          class="side-menu"
          style="border-right: none; padding-top: 8px;"
        >
          <el-menu-item v-if="!isViewer" index="/dashboard">
            <el-icon><Odometer /></el-icon>
            <template #title><span>首页概览</span></template>
          </el-menu-item>

          <el-sub-menu index="assets">
            <template #title>
              <el-icon><Box /></el-icon>
              <span>产品及服务</span>
            </template>
            <el-menu-item index="/assets/embodied">具身智能</el-menu-item>
            <el-menu-item index="/assets/satellite">卫星服务</el-menu-item>
            <el-menu-item index="/assets/software">软件产品</el-menu-item>
            <el-menu-item index="/assets/hardware">硬件产品</el-menu-item>
            <el-menu-item index="/assets/compute">
              <span style="display: inline-flex; align-items: center; gap: 6px;">
                算力服务
                <el-tag size="small" type="warning" effect="plain" style="padding: 0 6px; font-size: 11px;">建设中</el-tag>
              </span>
            </el-menu-item>
          </el-sub-menu>

          <!-- viewer（生态人员）：销售管理整组不可见，仅「销售项目」（后端已按自己下单过滤）与购物车独立保留 -->
          <el-menu-item v-if="isViewer" index="/sales/projects">
            <el-icon><TrendCharts /></el-icon>
            <template #title><span>销售项目</span></template>
          </el-menu-item>
          <el-menu-item v-if="isViewer" index="/cart">
            <el-icon><ShoppingCart /></el-icon>
            <template #title>
              <span style="display: inline-flex; align-items: center; gap: 6px;">
                购物车
                <el-badge v-if="cartCount > 0" :value="cartCount" :max="99" style="transform: translateY(1px);" />
              </span>
            </template>
          </el-menu-item>

          <el-sub-menu v-if="!isViewer" index="sales">
            <template #title>
              <el-icon><TrendCharts /></el-icon>
              <span>销售管理</span>
            </template>
            <el-menu-item index="/sales/projects">销售项目</el-menu-item>
            <el-menu-item index="/sales/outbound">交付记录</el-menu-item>
            <el-menu-item index="/cart" :disabled="!canWrite">
              <span style="display: inline-flex; align-items: center; gap: 6px;">
                购物车
                <el-badge v-if="cartCount > 0" :value="cartCount" :max="99" style="transform: translateY(1px);" />
              </span>
            </el-menu-item>
          </el-sub-menu>

          <el-sub-menu v-if="isAdmin" index="settings">
            <template #title>
              <el-icon><Setting /></el-icon>
              <span>基础设置</span>
            </template>
            <el-menu-item index="/settings/deliverables">交付物设置</el-menu-item>
            <el-menu-item index="/settings/users">账号与审计</el-menu-item>
          </el-sub-menu>
        </el-menu>
      </el-aside>

      <!-- 内容区 -->
      <el-main style="background: var(--bg-color); padding: 0; overflow-y: auto;">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  Odometer,
  Box,
  TrendCharts,
  Setting,
  Coin,
  CircleCheckFilled,
  Fold,
  Expand,
  ShoppingCart,
} from '@element-plus/icons-vue'
import { db } from '@/api'
import { canWrite, clearSession, currentUser, isAdmin, isViewer, ROLE_LABELS } from '@/auth'

const route = useRoute()
const isCollapse = ref(false)

const activeMenu = computed(() => route.path)

/** 购物车角标：当前购物车条目总数量（预留账号权限后按登录用户统计） */
const cartCount = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))

/** 角色标签配色（对齐 global.css 产品类型色板，不用 Element 默认色） */
const roleTagClass = computed(() => {
  const role = currentUser.value?.role
  if (role === 'admin') return 'blue'
  if (role === 'editor') return 'green'
  return 'gray'
})

/** 退出：确认弹窗 → 清本地态 → 跳登录页 */
async function handleLogout() {
  try {
    await ElMessageBox.confirm('确定退出当前账号吗？', '退出确认', {
      type: 'warning',
      confirmButtonText: '退出',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  clearSession()
  window.location.href = '/login'
}
</script>

<style scoped>
.top-header {
  height: 56px;
  background: #ffffff;
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px 0 12px;
  flex-shrink: 0;
  z-index: 10;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}
.header-logo {
  display: inline-flex;
  align-items: center;
  color: var(--primary-color);
}
.header-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary-color);
  letter-spacing: 1px;
  margin-left: 4px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-chip {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
  color: var(--text-body);
}
.user-name {
  font-weight: 500;
}
.logout-btn {
  font-size: 13px;
  color: var(--text-secondary);
}
.logout-btn:hover {
  color: var(--danger-color);
}

/* 侧边菜单：可纵向滚动，滚动条隐藏（跨浏览器） */
.side-menu {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* 旧版 Edge/IE */
}
.side-menu::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none; /* Chrome/Safari */
}
</style>
