/**
 * ADR-058：全量启用账号（`GET /users/options/all`）的**模块级缓存** composable——
 * 多页（销售项目列表抽屉流转过程 / 详情页等）复用同一 Promise，不重复发请求；
 * 供 username→name 展示解析（utils/userName.ts）使用。
 */
import { ref, type Ref } from 'vue'
import { allUserOptions, type UserOption } from '@/api'

let cached: Promise<UserOption[]> | null = null

function loadAll(): Promise<UserOption[]> {
  if (!cached) {
    cached = allUserOptions().catch((e) => {
      cached = null // 失败不缓存，下次进页可重试
      throw e
    })
  }
  return cached
}

/** 返回响应式的全量启用账号列表（失败保持空数组，展示层自动回退 username） */
export function useUserNameOptions(): Ref<UserOption[]> {
  const options = ref<UserOption[]>([])
  loadAll().then((u) => {
    options.value = u
  }).catch(() => {})
  return options
}
