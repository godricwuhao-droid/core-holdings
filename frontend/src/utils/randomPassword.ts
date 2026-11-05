/**
 * 随机密码生成器（ADR-054：账号管理建号随机密码）
 *
 * - 12 位；字符集去易混（大写去 O/I、小写去 l、数字去 0/1）
 * - 保证至少含 1 个大写、1 个小写、1 个数字，其余随机填充后洗牌
 * - 使用 crypto.getRandomValues（Web Crypto，非 Math.random）
 */
const UPPER = 'ABCDEFGHJKLMNPQRSTUVWXYZ' // 去 O / I
const LOWER = 'abcdefghijkmnopqrstuvwxyz' // 去 l
const DIGITS = '23456789' // 去 0 / 1
const ALL = UPPER + LOWER + DIGITS

function randInt(max: number): number {
  const buf = new Uint32Array(1)
  crypto.getRandomValues(buf)
  return buf[0] % max
}

/** 生成指定长度（默认 12）随机密码：三类字符各至少 1 个，洗牌后返回 */
export function generateRandomPassword(length = 12): string {
  const chars: string[] = [
    UPPER[randInt(UPPER.length)],
    LOWER[randInt(LOWER.length)],
    DIGITS[randInt(DIGITS.length)],
  ]
  while (chars.length < length) {
    chars.push(ALL[randInt(ALL.length)])
  }
  // Fisher–Yates 洗牌（避免前三位固定为大小写/数字）
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randInt(i + 1)
    ;[chars[i], chars[j]] = [chars[j], chars[i]]
  }
  return chars.join('')
}
