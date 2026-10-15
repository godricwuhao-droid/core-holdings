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

/** 角色中文标签（与后端固定三角色一致） */
export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理',
  editor: '可编辑',
  viewer: '只读',
}

/** 只读账号统一禁用提示文案 */
export const READONLY_TIP = '只读账号无操作权限'

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

/** 是否可执行业务写操作（admin / editor 可写，viewer 只读） */
export const canWrite = computed(() => state.user !== null && state.user.role !== 'viewer')

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
