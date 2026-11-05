/**
 * 全站「返回」统一动线：优先回到上一页（`router.back()`），无历史（深链 / 刷新直达）时兜底到该域首页。
 *
 * 背景：此前各页返回按钮各自内联 `if (history.state?.back) router.back() else router.push(固定路由)`，
 * 且审核页等写死跳固定路由（如审核页写死跳项目详情）——对「从列表进来」的 viewer 会跳错到详情。
 * 本 composable 是唯一实现，各页只传兜底路由，消除重复并保证同一行为。
 *
 * 判据：Vue Router 4 的 `history.state.back` 存在 = 有可回退历史（与浏览器前进/后退栈一致）。
 * 注意：购物车页 `readAndClearRefillSkips` 用 replaceState 清 `refillSkips` 时**保留** back/forward/position
 * 键，故本判据在 /cart 上依然成立。
 *
 * @param fallbackRoute 兜底路由 path 字符串；或返回该字符串的函数（兜底路由依赖运行时数据时用，
 *                      如产品详情按 `asset.board` 回对应板块列表）。
 */
import { useRouter } from 'vue-router'

export function useBack(fallbackRoute: string | (() => string)) {
  const router = useRouter()

  function goBack() {
    if (window.history.state?.back) {
      router.back()
    } else {
      router.push(typeof fallbackRoute === 'function' ? fallbackRoute() : fallbackRoute)
    }
  }

  return { goBack }
}
