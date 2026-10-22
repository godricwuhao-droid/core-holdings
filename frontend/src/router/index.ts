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

      // ---------- 产品及服务 ----------
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
      // 2026-10-19：订单审核独立页（仅订单审核 + 备注；商务/管理员，viewer 路由守卫拦截）
      {
        path: 'sales/projects/:id/review',
        name: 'ProjectReview',
        component: () => import('@/views/sales/projects/review.vue'),
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
        path: 'settings/users',
        name: 'SettingsUsers',
        component: () => import('@/views/settings/users.vue'),
      },
      // ENTITIES-20261022 / ADR-035；FORMS-20261022（ADR-036）：文案「资产主体」→「公司主体」（路径不变，仅 admin/editor；viewer 直达被守卫拦回）
      {
        path: 'settings/entities',
        name: 'SettingsEntities',
        component: () => import('@/views/settings/entities.vue'),
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

/** viewer（生态人员）可访问路由：/assets/**（排除创建/编辑等写页面）+ /sales/projects（仅自己下单，后端过滤）+ /cart；默认落地 /assets/embodied */
const VIEWER_HOME = '/assets/embodied'
/** ADR-028：viewer 禁入的销售项目编辑页（`/sales/projects/:id/edit`）——守卫拦截后提示并回详情页 */
const VIEWER_BLOCKED_PROJECT_EDIT = /^\/sales\/projects\/(\d+)\/edit\/?$/
function viewerAllowedPath(path: string): boolean {
  if (path === '/cart') return true
  // 销售项目：列表 + 详情（仅限自己下单的项目；新建/审核/编辑/交付记录不放行）
  if (path === '/sales/projects') return true
  // ADR-028（2026-10-21）：生态人员订单提交后禁编辑——edit 页不再对 viewer 放行，仅放行 detail
  // （改单唯一路径 =「撤销」→ 明细回购物车 → 重新下单，见 ADR-026/027）
  if (/^\/sales\/projects\/\d+\/detail$/.test(path)) return true
  // 2026-10-21（ADR-027）：原「按 query 参数放行新建页」的重新提交通道已移除——
  // 重新提交改为列表/详情页调 refill-cart 后跳 /cart；生态新建页维持整体拦截。
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
//  - viewer（生态人员）：仅 /assets/**（排除创建/编辑页）、/sales/projects(+/:id/detail) 与 /cart，
//    其余路由（看板/销售/交付/基础设置/产品创建编辑）→ 静默重定向 /assets/embodied
//  - ADR-028：viewer 禁入销售项目编辑页 → 提示「订单已提交，不可编辑…」并回该单详情页
//  - /settings/users 仅 admin，非 admin 直接访问 → 提示并回 /
//  - /settings/entities（ENTITIES-20261022）仅 admin/editor，viewer 直接访问 → 提示并回产品首页
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
  // ENTITIES-20261022 / ADR-035；FORMS-20261022（ADR-036）：公司主体（原「资产主体」）仅 admin/editor——viewer 直达提示后回产品首页
  // （须置于下方 viewer 静默收窄之前，否则会被无提示重定向抢先拦截）
  if (to.path === '/settings/entities' && currentUser.value?.role === 'viewer') {
    ElMessage.warning('仅商务人员/管理员可访问「公司主体」')
    return VIEWER_HOME
  }
  // viewer（生态人员）：菜单/路由收窄——仅产品浏览 + 购物车，其余静默回产品首页
  if (currentUser.value?.role === 'viewer') {
    // ADR-028（2026-10-21）：订单提交后禁编辑——直达 /sales/projects/:id/edit 时提示并回该单详情页
    // （create 页 onMounted 的同名兜底不会执行到，故提示放在守卫；detail 在白名单内，无重定向死循环）
    const blockedEdit = VIEWER_BLOCKED_PROJECT_EDIT.exec(to.path)
    if (blockedEdit) {
      ElMessage.warning('订单已提交，不可编辑，如需修改请「撤销」后重新下单')
      return `/sales/projects/${blockedEdit[1]}/detail`
    }
    if (!viewerAllowedPath(to.path)) return VIEWER_HOME
  }
  if (to.path === '/settings/users' && currentUser.value?.role !== 'admin') {
    ElMessage.warning('仅管理员可访问「账号与审计」')
    return '/'
  }
  return true
})

export default router
