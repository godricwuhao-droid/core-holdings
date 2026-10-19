/**
 * 认证态管理（登录 token / 当前用户 / 角色权限）
 *
 *  - localStorage 持久化 `token` 与 `currentUser`（刷新/新标签页可恢复）；
 *  - `currentUser` 为响应式状态，布局/视图直接读取做角色化 UI；
 *  - axios 拦截器（api/index.ts）负责：请求带 Bearer token、401 清态跳登录、
 *    viewer 写请求统一拦截。本模块不依赖 axios，避免循环导入。
 */
import { computed, reactive } from 'vue'

export type Role = 'admin' | 'editor' | 'viewer'

export interface CurrentUser {
  id: number
  username: string
  name: string
  role: Role
  enabled: boolean
}

const TOKEN_KEY = 'token'
const USER_KEY = 'currentUser'

/** 角色中文展示名（内部标识仍为 admin/editor/viewer，仅展示名调整） */
export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理员',
  editor: '商务人员',
  viewer: '生态人员',
}

/** 生态人员（viewer）写入口统一禁用提示文案 */
export const READONLY_TIP = '生态人员无此操作权限'

function loadUser(): CurrentUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as CurrentUser) : null
  } catch {
    return null
  }
}

const state = reactive<{ user: CurrentUser | null }>({ user: loadUser() })

/** 当前登录用户（响应式；未登录为 null） */
export const currentUser = computed<CurrentUser | null>(() => state.user)

/** 是否管理员（账号与审计等 admin 专用能力） */
export const isAdmin = computed(() => state.user?.role === 'admin')

/** 是否可执行业务写操作（admin / editor 可写；viewer 仅下单链路，产品编辑类禁用） */
export const canWrite = computed(() => state.user !== null && state.user.role !== 'viewer')

/** 是否生态人员（viewer）：菜单/路由收窄 + 下单链路放权 */
export const isViewer = computed(() => state.user?.role === 'viewer')

/**
 * 是否已登录（ADR-009）：下单链路（购物车加购/改量/删行/清空/结算、直接下单）
 * 后端已全部改为 require_order（认证即放行），前端对应入口以本判据解禁，
 * 不再受 canWrite（admin/editor）限制；产品编辑类入口仍用 canWrite。
 */
export const isLoggedIn = computed(() => state.user !== null)

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function hasToken(): boolean {
  return !!getToken()
}

/** 登录成功后写入会话 */
export function setSession(token: string, user: CurrentUser): void {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  state.user = user
}

/** 本地清态（退出登录 / 401 失效时调用；无后端登出接口） */
export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  state.user = null
}

/** fetchMe 成功后同步最新用户信息（如改名后） */
export function setUser(user: CurrentUser): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
  state.user = user
}
