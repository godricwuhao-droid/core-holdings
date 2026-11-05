<template>
  <el-container direction="vertical" style="height: 100vh">
    <!-- 顶栏：平台名称 + 系统状态 -->
    <div class="top-header">
      <div class="header-left">
        <span class="header-logo">
          <img src="/brand/logo-icon.png" alt="蜂云时代" style="height: 26px; display: block;" />
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
        <!-- ADR-054：user-chip 改 el-dropdown（修改密码 / 退出登录），所有角色可见 -->
        <el-dropdown trigger="click" @command="onUserCommand">
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
            <el-icon class="user-chip-caret" aria-hidden="true"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
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
          <!-- ADR-051：首页概览仅业务档（admin/supervisor/editor）；viewer 与 finance 均不显示 -->
          <el-menu-item v-if="!isViewer && !isFinance" index="/dashboard">
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

          <!-- ADR-056 §3：产品统计（按主体聚合对账）——admin/主管/商务/财务可见，viewer（生态人员）不可见
               （finance 可见性由守卫 financeAllowedPath 白名单同步放开） -->
          <el-menu-item v-if="!isViewer" index="/statistics">
            <el-icon><DataAnalysis /></el-icon>
            <template #title><span>产品统计</span></template>
          </el-menu-item>

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

          <!-- ADR-051：销售管理整组仅业务档（admin/supervisor/editor）；finance 仅「产品及服务」 -->
          <el-sub-menu v-if="!isViewer && !isFinance" index="sales">
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

          <el-menu-item v-if="isAdmin" index="/settings/users">
            <el-icon><Setting /></el-icon>
            <template #title>账号与审计</template>
          </el-menu-item>
          <!-- ENTITIES-20261022 / ADR-035；FORMS-20261022（ADR-036）：菜单改名「资产主体」→「公司主体」（路由路径不变）——
               v-if 与「账号与审计」同口径（isAdmin）；editor 可直达路由访问 -->
          <el-menu-item v-if="isAdmin" index="/settings/entities">
            <el-icon><OfficeBuilding /></el-icon>
            <template #title>公司主体</template>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <!-- 内容区 -->
      <el-main style="background: var(--bg-color); padding: 0; overflow-y: auto;">
        <router-view />
      </el-main>
    </el-container>

    <!-- ADR-054：自助改密弹窗（所有角色） -->
    <el-dialog
      v-model="pwdDialog.visible"
      title="修改密码"
      width="420px"
      :close-on-click-modal="false"
    >
      <el-form label-width="96px">
        <el-form-item label="旧密码" required>
          <el-input v-model="pwdDialog.oldPassword" type="password" show-password placeholder="当前登录密码" />
        </el-form-item>
        <el-form-item label="新密码" required>
          <el-input v-model="pwdDialog.newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码" required>
          <el-input v-model="pwdDialog.confirmPassword" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="pwdDialog.submitting" @click="handleChangePassword">
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Odometer,
  Box,
  TrendCharts,
  Setting,
  OfficeBuilding,
  CircleCheckFilled,
  Fold,
  Expand,
  ShoppingCart,
  ArrowDown,
  DataAnalysis, // ADR-056 §3：「产品统计」菜单图标（既有依赖内图标）
} from '@element-plus/icons-vue'
import { changeMyPassword, db } from '@/api'
import { canWrite, clearSession, currentUser, isAdmin, isFinance, isViewer, ROLE_LABELS, setSession } from '@/auth'

const route = useRoute()
const isCollapse = ref(false)

const activeMenu = computed(() => route.path)

/** 购物车角标：当前购物车条目总数量（预留账号权限后按登录用户统计） */
const cartCount = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))

/** 角色标签配色（对齐 global.css 产品类型色板，不用 Element 默认色；
 *  ADR-051 五角色：admin 蓝 / supervisor 紫 / editor 绿 / finance 橙 / viewer 灰） */
const roleTagClass = computed(() => {
  const role = currentUser.value?.role
  if (role === 'admin') return 'blue'
  if (role === 'supervisor') return 'purple'
  if (role === 'editor') return 'green'
  if (role === 'finance') return 'orange'
  return 'gray'
})

// ============================================================
// ADR-054：自助改密（所有角色）
// ============================================================
const pwdDialog = reactive({
  visible: false,
  submitting: false,
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})

function openPasswordDialog() {
  pwdDialog.oldPassword = ''
  pwdDialog.newPassword = ''
  pwdDialog.confirmPassword = ''
  pwdDialog.visible = true
}

async function handleChangePassword() {
  if (!pwdDialog.oldPassword) {
    ElMessage.warning('请输入旧密码')
    return
  }
  if (!pwdDialog.newPassword || pwdDialog.newPassword.length < 6) {
    ElMessage.warning('新密码不能为空且至少 6 位')
    return
  }
  if (pwdDialog.newPassword !== pwdDialog.confirmPassword) {
    ElMessage.warning('新密码与确认新密码不一致')
    return
  }
  pwdDialog.submitting = true
  try {
    const res = await changeMyPassword(pwdDialog.oldPassword, pwdDialog.newPassword)
    // 关键：改密后 tokenVersion+1，必须用返回的新 token 换掉本地 token，
    // 否则下次请求用旧 token 会 401 掉线
    setSession(res.token, res.user)
    ElMessage.success('密码已修改')
    pwdDialog.visible = false
  } catch (e) {
    // 400「旧密码不正确」等：detail 已由拦截器解析进 Error.message
    ElMessage.error(e instanceof Error ? e.message : '修改密码失败')
  } finally {
    pwdDialog.submitting = false
  }
}

function onUserCommand(cmd: string) {
  if (cmd === 'password') openPasswordDialog()
  else if (cmd === 'logout') void handleLogout()
}

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
/* ADR-054：user-chip 改下拉后的可点击态与下拉箭头 */
.user-chip {
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
}
.user-chip:hover {
  background: var(--bg-color);
}
.user-chip-caret {
  margin-left: 6px;
  font-size: 12px;
  color: var(--text-secondary);
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
