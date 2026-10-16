/**
 * 路由配置
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import MainLayout from '@/layouts/MainLayout.vue'
import { currentUser, getToken } from '@/auth'
import { fetchMe } from '@/api'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
  },
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
      },

      // ---------- 资产管理 ----------
      {
        path: 'assets/:board(embodied|satellite|software|hardware)',
        name: 'AssetList',
        component: () => import('@/views/assets/list.vue'),
      },
      {
        path: 'assets/compute',
        name: 'AssetCompute',
        component: () => import('@/views/assets/compute.vue'),
      },
      {
        path: 'assets/create',
        name: 'AssetCreate',
        component: () => import('@/views/assets/create.vue'),
      },
      {
        path: 'assets/:id/detail',
        name: 'AssetDetail',
        component: () => import('@/views/assets/detail.vue'),
      },
      {
        path: 'assets/:id/edit',
        name: 'AssetEdit',
        component: () => import('@/views/assets/create.vue'),
      },

      // ---------- 销售管理 ----------
      {
        path: 'sales/projects',
        name: 'ProjectList',
        component: () => import('@/views/sales/projects/index.vue'),
      },
      {
        path: 'sales/projects/create',
        name: 'ProjectCreate',
        component: () => import('@/views/sales/projects/create.vue'),
      },
      {
        path: 'sales/projects/:id/detail',
        name: 'ProjectDetail',
        component: () => import('@/views/sales/projects/detail.vue'),
      },
      {
        path: 'sales/projects/:id/edit',
        name: 'ProjectEdit',
        component: () => import('@/views/sales/projects/create.vue'),
      },
      {
        path: 'sales/outbound',
        name: 'OutboundList',
        component: () => import('@/views/sales/outbound/index.vue'),
      },
      {
        path: 'cart',
        name: 'Cart',
        component: () => import('@/views/cart/index.vue'),
      },

      // ---------- 基础设置 ----------
      {
        path: 'settings/deliverables',
        name: 'SettingsDeliverables',
        component: () => import('@/views/settings/deliverables.vue'),
      },
      {
        path: 'settings/reps',
        name: 'SettingsReps',
        component: () => import('@/views/settings/base.vue'),
      },
      {
        path: 'settings/users',
        name: 'SettingsUsers',
        component: () => import('@/views/settings/users.vue'),
      },

      // ---------- 预留 ----------
      {
        path: 'reserved',
        name: 'Reserved',
        component: () => import('@/views/reserved/index.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** viewer（生态人员）可访问路由：/assets/**（排除创建/编辑等写页面）+ /cart；默认落地 /assets/embodied */
const VIEWER_HOME = '/assets/embodied'
function viewerAllowedPath(path: string): boolean {
  if (path === '/cart') return true
  if (!path.startsWith('/assets/')) return false
  if (path === '/assets/create') return false
  if (/^\/assets\/\d+\/edit$/.test(path)) return false
  return true
}

// ============================================================
// 全局守卫：登录态 + 角色
//  - 无 token：非 /login 一律重定向 /login（带 redirect 参数）
//  - 有 token 访问 /login：回 /
//  - token 在但 currentUser 缺失（新标签页刷新）：fetchMe 校验，
//    401 由响应拦截器清态跳登录
//  - viewer（生态人员）：仅 /assets/**（排除创建/编辑页）与 /cart，
//    其余路由（看板/销售/出库/基础设置/资产创建编辑）→ 静默重定向 /assets/embodied
//  - /settings/*（users/deliverables/reps）仅 admin，非 admin 直接访问 → 提示并回 /
// ============================================================
router.beforeEach(async (to) => {
  if (to.path === '/login') {
    return getToken() ? '/' : true
  }
  if (!getToken()) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!currentUser.value) {
    try {
      await fetchMe()
    } catch {
      // 401 已被响应拦截器处理（清态 + 整页跳登录）；其余错误阻断导航
      return false
    }
  }
  // viewer（生态人员）：菜单/路由收窄——仅资产浏览 + 购物车，其余静默回资产首页
  if (currentUser.value?.role === 'viewer' && !viewerAllowedPath(to.path)) {
    return VIEWER_HOME
  }
  if (to.path === '/settings/users' && currentUser.value?.role !== 'admin') {
    ElMessage.warning('仅管理员可访问「账号与审计」')
    return '/'
  }
  if (
    (to.path === '/settings/deliverables' || to.path === '/settings/reps') &&
    currentUser.value?.role !== 'admin'
  ) {
    ElMessage.warning('仅管理员可访问「基础设置」')
    return '/'
  }
  return true
})

export default router
