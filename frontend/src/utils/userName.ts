/**
 * ADR-058：username → name 展示层解析（username 继续作存储标识，只在展示层解析成姓名）
 *
 * - 映射数据源：`GET /users/options/all` 的全量启用账号（含各角色，见 api.allUserOptions）；
 * - 空 name / 未知 username 一律回退显示 username（不显空、不报错）。
 */
import type { UserOption } from '@/api'

/** 取 username 对应的展示姓名；查不到 / name 为空 → 回退 username；入参为空 → 空串 */
export function nameOf(username: string | null | undefined, options: UserOption[]): string {
  if (!username) return ''
  const u = options.find((x) => x.username === username)
  return (u?.name || '').trim() || username
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 把自由文本（流转日志 detail）中出现的 username 替换为对应姓名。
 *
 * 要点（ADR-058）：
 * ① 用全量启用账号建 username→name 表（name 为空 / 与 username 相同的条目不入表）；
 * ② 按 username 长度**从长到短**替换（避免 `biz01` 误替换进 `biz011`）；
 * ③ 词边界：username 为拉丁（字母/数字/下划线），匹配位置前后不得是字母/数字/下划线
 *    （姓名为中文，天然不命中，避免误伤）；
 * ④ 未知 username / 空 name 保持原样；
 * ⑤ 幂等：对已解析文本再跑不变（姓名不含未解析的 username 时）。
 */
export function resolveUserNames(text: string, options: UserOption[]): string {
  if (!text) return text
  const map = new Map<string, string>()
  for (const o of options) {
    const name = (o.name || '').trim()
    if (o.username && name && name !== o.username) map.set(o.username, name)
  }
  if (!map.size) return text
  const usernames = Array.from(map.keys()).sort((a, b) => b.length - a.length)
  let out = text
  for (const u of usernames) {
    const re = new RegExp(`(?<![A-Za-z0-9_])${escapeRegExp(u)}(?![A-Za-z0-9_])`, 'g')
    out = out.replace(re, map.get(u)!)
  }
  return out
}
