/**
 * 「重新提交」（终止/驳回项目明细回填购物车）共用动线 — ADR-042 / REFILL-20261022
 *
 * 背景（ADR-042 Context）：原两处调用点（列表页 `views/sales/projects/index.vue`、
 * 详情页 `views/sales/projects/detail.vue`）各自内联一套「调接口 → 刷新 → 跳 /cart」，
 * 造成三个缺陷：失败静默往空车跳、购物车非空时静默累加、代操作归属错位（明细进下单人的车、
 * 操作者自己跳到空车）。本 composable 是**唯一**动线实现（两处调用点只保留 loading 与入口）。
 *
 * 流程顺序（ADR-042 §2~§5，严格按此顺序执行）：
 *  1. 购物车非空 **且** 回填对象是当前登录者 → 三选弹窗（合并 / 清空后回填 / 取消）；
 *     回填对象是他人时不问（问的是别人的车，没有意义）——归属按项目 `creator` 优先、
 *     回退 `rep` 预判（后端 `_withdraw_owner` 同口径），接口返回后再用 `res.owner` 复核一次。
 *  2. 调 `refillProjectCart(id, mode)`，`busy` 置位防连点。
 *  3. `alreadyRefilled`（merge 幂等短路）→ 提示「已在购物车」；回填目标非本人时说明「在谁的购物车」，
 *     且**不跳转**（跳过去只会看到自己的空车）。⚠ 幂等必须排在「全失败」之前：merge 短路时 restored 恒 0。
 *  4. `restored === 0`（全失败）→ 不跳转，弹窗逐行列出原因（可售不足 / 已被其他订单占用等，不截断）；
 *     回填目标非本人时副标题注明「（回填目标：X）」——**归属提示不得掩盖失败**
 *     （ADR-042 补遗6 / ADR-043 §3：原实现把归属放在最前，restored=0 也报"已回填至他人购物车"）。
 *  5. 成功（部分或全部）之后才轮到归属：目标非本人 → 提示并**停留原页**（不跳转）；
 *     本人 → `skipped > 0` 跳 /cart 并携带未回填清单（购物车页显示可关闭警告条），全成功直接跳 /cart。
 *      ⚠️ ADR-042 补遗5（REFILL-20261022-F2）：短路但**本人购物车为空**时先自愈——
 *      改走 `mode='replace'` 重填一次（仅一次），成功则用第二次响应走 3/4 分支；
 *      失败（旧后端 400 / 他人车 / 网络）回退首次响应的「已在购物车」分支，不向用户抛错。
 *
 * ⚠️ 降级（backend REFILL-20261022-B 未热载）：`owner` / `rows` / `mode` / `forced` / `cleared`
 * 可能为 undefined —— 全部可选链兜底：owner 缺失按本人处理，rows 缺失回退 `skippedReasons`，
 * mode 缺失按 merge 处理。**不做**「后端是否支持 mode」的探测请求。
 *
 * ⚠️ 降级（backend REFILL-20261022-B3 / 本批次 F3）：`rows[].code / assetId / need` 三个**加性**字段
 * 也可能缺失 —— 见 `buildFailRows`：code 缺失按 reason 关键字猜（仅降级路径），assetId 缺失 →
 * 不显示库存 meta（**不**显示「库存 -」空壳），need 缺失回退 `qty`。
 *
 * 展示层（REFILL-20261022-F3）：两个弹窗均为 `h()` 渲染的 `el-dialog`，样式统一落在
 * `styles/global.css` 的 `.rf-*` 命名空间（h() 内容无法被 SFC scoped 样式命中）。
 * **只改「怎么展示」，不改 decideRefillOutcome 的分支优先级。**
 */
import { defineComponent, h, ref, render } from 'vue'
import type { VNode } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElDialog, ElIcon, ElMessage, ElTag } from 'element-plus'
import { InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import { db, refillProjectCart, refresh, showError } from '@/api'
import { currentUser } from '@/auth'
import type { Asset, RefillMode, RefillResult, RefillRowCode, RefillRowResult } from '@/types'

/** 重新提交入参：`{id, code, name}` 为必需；`creator/rep` 仅用于**弹窗前的归属预判**（可选，缺失按本人处理） */
export interface ResubmitTarget {
  id: number
  code: string
  name: string
  creator?: string
  rep?: string
}

/** 结果分支决策（纯函数，无 IO / 无组件依赖 —— 可直接在 node 脚本中断言） */
export type RefillOutcome =
  | { kind: 'notify-owner'; ownerName: string; message: string }
  /** `ownerName` 非空 = 明细在**他人**购物车：只提示不跳转（ADR-042 补遗6） */
  | { kind: 'push-already'; ownerName?: string }
  /** `ownerName` 非空 = 全失败的那辆车属于谁（弹窗副标题注明，ADR-043 §3） */
  | { kind: 'alert-all-failed'; title: string; lines: string[]; ownerName?: string }
  | { kind: 'push-with-warning'; skips: string[] }
  | { kind: 'push-plain' }

/**
 * 回填对象是否当前登录者（ADR-042 §5，后端 `_withdraw_owner` 同口径：creator 优先，回退 rep）。
 * 无归属信息（存量单）/ 未登录 → true（后端按当前登录者兜底，按本人处理最安全）。
 * 账号与姓名都参与比对：`rep` 在存量数据里可能存的是姓名。
 */
export function isOwnCartTarget(
  p: { creator?: string; rep?: string },
  me: { username: string; name?: string } | null,
): boolean {
  if (!me?.username) return true
  const key = ((p.creator ?? '').trim() || (p.rep ?? '').trim()).trim()
  if (!key) return true
  return key === me.username || (!!me.name && key === me.name)
}

/** 是否需要弹「购物车非空」三选框：车里有东西 **且** 回填的是自己的车（ADR-042 §2） */
export function shouldAskRefillMode(opts: { cartCount: number; ownerLikelySelf: boolean }): boolean {
  return opts.cartCount > 0 && opts.ownerLikelySelf
}

/**
 * ADR-042 补遗5（REFILL-20261022-F2）：幂等短路但本人购物车为空 → 自动改走 replace 重填一次。
 * 否则「明细已在购物车」的提示与空购物车矛盾（真实数据可复现：lshangkun 的积云项目）。
 *
 * 三个条件同时成立才自愈：
 *  1. `res.alreadyRefilled === true`（merge 幂等短路；`mode=replace` 时后端根本不短路）；
 *  2. 购物车为空（`cartCount === 0`）——车里有货时 replace 会清空用户的东西，必须由用户显式选择；
 *  3. 回填对象是本人（`res.owner` 缺失按本人处理，与 `isOwnCartTarget` / 后端降级口径一致；
 *     `me` 缺失即 `currentUser` 未就绪，同样按本人处理）。
 *
 * 为什么这条自愈是安全的：`mode=replace` 在服务端有两道守卫——
 *  ① 「仅限本人购物车」（ADR-042 补遗2）：目标不是当前登录者 → 400，一行未删；
 *  ② 「可行行 0 时不清空」（ADR-042 补遗1）：全部行不可售 → `cleared=0`，用户原购物车不丢。
 * 因此最坏结果只是 400 或 `cleared=0`，不会破坏数据；加之本函数已把「非本人 / 车非空」排除，
 * 实际能走到 replace 的只有「本人 + 空车」——清空本身是无副作用的空操作。
 */
export function shouldSelfHealRefill(res: RefillResult, cartCount: number, me?: string): boolean {
  if (!res.alreadyRefilled) return false
  if (Math.max(0, cartCount) > 0) return false // 车里有货：清空必须由用户显式选择
  const owner = res.owner
  if (owner?.username && me && owner.username !== me) return false // 他人车：服务端会 400，不试
  return true
}

/**
 * 单行失败展示文案（`assetName：reason`）。
 * 后端 ADR-042 的 `reason` 已自带产品名（如「「融合视讯云平台」可售数量不足（库存 1，已锁定 1…）」），
 * 故 reason 已含产品名时**原样展示**，避免出现「产品名：「产品名」可售数量不足」的双重前缀；
 * 未含产品名的 reason（区间不符以外的兜底文案）才补前缀。原因全文不截断。
 *
 * 注：`push-with-warning`（跳购物车 + 警告条）仍用这段纯文本；只有「全失败」弹窗改用 F3 的结构化行。
 */
function rowLine(r: { assetName?: string; reason?: string }): string {
  const reason = (r.reason ?? '').trim() || '未能回填'
  const name = (r.assetName ?? '').trim()
  if (!name || reason.includes(name)) return reason
  return `${name}：${reason}`
}

/**
 * 结果分支决策（纯函数）：
 * 优先级 **幂等短路 → 全失败 → 部分/全成功后再判归属**（ADR-042 补遗6 / ADR-043 §3，顺序固定不得调整）。
 *
 * 为什么不能把归属放最前：只要 `owner.username !== 当前账号` 就直接返回「已回填至 X 的购物车」，
 * 哪怕 `restored === 0`（一行都没回填）——实测商务点被占用产品（`restored=0, skipped=2`）收到
 * 「明细已回填至下单人 刘尚坤（lshangkun）的购物车…」，把彻底失败包装成了成功。
 * 归属现在只做「结果修饰」：失败优先报失败，成功后才决定动线（本人跳 /cart，他人只提示）。
 *
 * 为什么幂等仍最前：merge 命中幂等短路时 `restored` 恒为 0，否则会把「明细已在购物车」误报成失败。
 */
export function decideRefillOutcome(res: RefillResult, currentUsername: string): RefillOutcome {
  const owner = res.owner
  const isOthers = !!owner?.username && owner.username !== currentUsername
  const ownerName = owner ? (owner.name ? `${owner.name}（${owner.username}）` : owner.username) : ''

  // ① 幂等短路最优先（merge 命中时 restored 恒 0，不能误判成失败）
  if (res.alreadyRefilled) return { kind: 'push-already', ownerName: isOthers ? ownerName : '' }

  const failed = (res.rows ?? []).filter((r) => !r.ok)
  // rows 缺失（后端未热载）→ 回退 skippedReasons（旧字段，只有原因类别没有行名）
  const lines = failed.length
    ? failed.map((r) => rowLine(r))
    : (res.skippedReasons ?? []).map((s) => String(s))

  // ② 全失败 → 无论回填目标是谁，都必须报失败（ADR-042 补遗6）
  if (!(res.restored > 0)) {
    return { kind: 'alert-all-failed', title: '无法回填到购物车', lines, ownerName: isOthers ? ownerName : '' }
  }
  // ③ 成功（部分或全部）后，才轮到归属决定动线
  if (isOthers) {
    const skipNote = (res.skipped ?? 0) > 0 ? `（另有 ${res.skipped} 行未能回填）` : ''
    return {
      kind: 'notify-owner',
      ownerName,
      message: `明细已回填至下单人 ${ownerName} 的购物车${skipNote}，请通知该账号前往购物车改单`,
    }
  }
  if ((res.skipped ?? 0) > 0) {
    return {
      kind: 'push-with-warning',
      skips: lines.length ? lines : [`${res.skipped} 行明细未能回填，请核对明细`],
    }
  }
  return { kind: 'push-plain' }
}

// ============================================================
// REFILL-20261022-F3：「无法回填到购物车」弹窗的**数据组装**（纯函数，渲染层只消费它）
// ============================================================

/** 单行失败展示模型（`buildFailRows` 的产出，与 Vue 无关，可在 node 里直接断言） */
export interface RefillFailRow {
  /** 产品名（`skippedReasons` 降级路径下即原因原文） */
  name: string
  /** 行数量；缺失（skippedReasons 降级路径）→ 不渲染「× N」 */
  qty?: number
  /** 本次需要数量 = `need ?? qty`；两者都缺 → undefined */
  need?: number
  /** 状态胶囊代码 */
  code: RefillRowCode
  /** 「库存 N · 已锁定 N · 已出库 N · 本次需 N」；空串 = 该行不渲染 meta（不显示「库存 -」空壳） */
  meta: string
  /** 补充说明：仅当胶囊文案 + meta 无法承载 reason 信息时非空（如价格区间不符、产品 #id 不存在） */
  detail: string
}

const TAG_TEXT: Record<RefillRowCode, string> = {
  ok: '已回填',
  insufficient: '可售不足',
  no_asset: '产品缺失',
  other: '无法回填',
}
/** 胶囊配色：不足=红（真实缺货）、产品缺失=灰（无从处理）、其它=橙（需人工看原因） */
const TAG_TYPE: Record<RefillRowCode, 'danger' | 'info' | 'warning'> = {
  ok: 'info',
  insufficient: 'danger',
  no_asset: 'info',
  other: 'warning',
}

function numOrUndefined(v: unknown): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}

/**
 * 失败代码：优先用后端 `code`（B3 加性字段）；**仅当 code 缺失**（旧后端未热载）才按 reason 猜。
 * 猜测不写进正常路径——后端一旦返回 code，本函数第一条即短路。
 */
function inferCode(r: RefillRowResult): RefillRowCode {
  if (r.code) return r.code
  const reason = (r.reason ?? '').trim()
  if (reason.includes('可售数量不足')) return 'insufficient'
  if (reason.includes('已不存在')) return 'no_asset'
  return 'other'
}

/**
 * meta 文本：`assets`（即 `db.assets`）里按 `assetId` 查库存。
 * 查不到 asset、或任一数值字段缺失 → 返回空串，由渲染层**整行不渲染**（不显示「库存 -」空壳）。
 */
function rowMeta(asset: Asset | undefined, need: number | undefined): string {
  if (!asset) return ''
  const quantity = numOrUndefined(asset.quantity)
  const locked = numOrUndefined(asset.lockedQty)
  const shipped = numOrUndefined(asset.shippedQty)
  if (quantity === undefined || locked === undefined || shipped === undefined) return ''
  const base = `库存 ${quantity} · 已锁定 ${locked} · 已出库 ${shipped}`
  return need === undefined ? base : `${base} · 本次需 ${need}`
}

/**
 * 把 `RefillResult` 组装成弹窗逐行数据（纯函数，REFILL-20261022-F3）。
 *
 * 降级矩阵：
 *  1. 有 `code/assetId/need` + 能查到 asset → meta = `库存 1 · 已锁定 1 · 已出库 0 · 本次需 1`；
 *  2. 有 `code` 但查不到 asset → meta = ''（不渲染 meta 行）；
 *  3. 无 `code`（旧后端）+ reason 含「可售数量不足」→ 归 `insufficient`；
 *  4. 无 `code` + reason 为「产品 #9 已不存在」→ 归 `no_asset`；
 *  5. 无 `rows`（旧后端）→ 用 `skippedReasons` 生成列表：meta 空、tag 用 `other`。
 *
 * @param res 后端响应（`rows` 可能缺失）
 * @param assets 库存镜像（调用方传 `db.assets`；显式传参是为了本函数保持纯函数、可在 node 里跑）
 */
export function buildFailRows(res: RefillResult, assets: Asset[]): RefillFailRow[] {
  const pool = Array.isArray(assets) ? assets : []
  const failed = (res.rows ?? []).filter((r) => !r.ok)

  // 降级 5：旧后端无逐行明细 → skippedReasons（只有原因类别，没有产品名/数量/库存）
  if (!failed.length) {
    return (res.skippedReasons ?? []).map((s) => ({
      name: String(s),
      code: 'other' as RefillRowCode,
      meta: '',
      detail: '',
    }))
  }

  return failed.map((r) => {
    const code = inferCode(r)
    const qty = numOrUndefined(r.qty)
    const need = numOrUndefined(r.need) ?? qty
    const asset = r.assetId == null ? undefined : pool.find((a) => a.id === r.assetId)
    const meta = rowMeta(asset, need)
    const reason = (r.reason ?? '').trim()
    // 「可售不足 + 已有库存数值」时 reason 是冗余的（数值已结构化展示）；
    // 其余情况保留原文，避免丢掉价格区间不符 / 产品 #id 等 meta 表达不了的细节。
    const detail = reason && !(code === 'insufficient' && meta) ? reason : ''
    return {
      name: (r.assetName ?? '').trim() || '未命名产品',
      qty,
      need,
      code,
      meta,
      detail,
    }
  })
}

// ============================================================
// 弹窗（h() 渲染 el-dialog，样式见 styles/global.css 的 .rf-*）
// ============================================================

/** 底部橙色提示条：仅「存在可售不足行」时展示（全是产品缺失/其它原因时文案不对题，不显示） */
const TIP_INSUFFICIENT =
  '可售数量不足时，需等待其他订单释放占用或补货后再试；本次不会跳转购物车，购物车内容不受影响。'

/**
 * 弹窗头部（两个弹窗共用同一套结构，保证视觉同源）：
 * `⚠/ⓘ 图标 + 标题(17px/600/#1A2E4E) + 副标题(13px/#71829A)`。
 * 默认标题（EP 的黑字 + 下边框）由 `#header` 插槽整体替换。
 */
function dialogHeader(icon: VNode, title: string, subtitle: string, tone: 'warn' | 'info') {
  return h('div', { class: 'rf-head' }, [
    h(ElIcon, { class: tone === 'warn' ? 'rf-head-icon is-warn' : 'rf-head-icon is-info', 'aria-hidden': 'true' }, () => icon),
    h('div', { class: 'rf-head-text' }, [
      h('div', { class: 'rf-head-title' }, title),
      h('div', { class: 'rf-head-sub' }, subtitle),
    ]),
  ])
}

/**
 * 购物车非空 → 三选弹窗（合并 / 清空后回填 / 取消）。
 *
 * 实现说明（ADR-042 / REFILL-20261022）：旧的 `MessageBox` 只有 confirm/cancel 两个按钮，无法三选；
 * 本批次文件范围限定（不新增 SFC），故用 `h()` 直接渲染 `el-dialog`（等价于组件内 el-dialog）
 * 挂到 body，选择后卸载。返回 `null` = 取消（含右上角关闭 / ESC）——调用方**不得**发起任何请求。
 *
 * REFILL-20261022-F3：标题字号 / 副标题色 / 底部提示条与「无法回填」弹窗统一为 `.rf-*`（视觉同源），
 * 选项排版一并收进 `.rf-opt*`，功能与文案一字未改。
 */
function askRefillMode(cartCount: number): Promise<RefillMode | null> {
  return new Promise<RefillMode | null>((resolve) => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const visible = ref(true)
    let settled = false
    const finish = (mode: RefillMode | null) => {
      if (settled) return
      settled = true
      resolve(mode) // 先返回决策，弹层随后走关闭动画 + onClosed 卸载
      visible.value = false
    }
    const cleanup = () => {
      render(null, host)
      host.remove()
    }
    const option = (title: string, desc: string) =>
      h('div', { class: 'rf-opt' }, [
        h('div', { class: 'rf-opt-title' }, title),
        h('div', { class: 'rf-opt-desc' }, desc),
      ])

    const DialogHost = defineComponent({
      name: 'ResubmitRefillModeDialog',
      setup() {
        return () =>
          h(
            ElDialog,
            {
              modelValue: visible.value,
              width: '480px',
              alignCenter: true,
              // 点遮罩不关闭：三选必须显式表态，避免误关后静默按 merge 回填
              closeOnClickModal: false,
              appendToBody: true,
              class: 'rf-dialog',
              'onUpdate:modelValue': (v: boolean) => {
                visible.value = v
              },
              onClosed: () => {
                cleanup()
                if (!settled) {
                  settled = true
                  resolve(null) // 关闭（X / ESC）= 取消
                }
              },
            },
            {
              header: () =>
                dialogHeader(
                  h(InfoFilled),
                  '购物车中已有商品',
                  `购物车中已有 ${cartCount} 项商品，请选择本次明细的回填方式`,
                  'info',
                ),
              default: () => [
                option(
                  '合并到现有购物车',
                  '保留购物车现有商品；同一产品同一客户的行，用本次明细的数量与金额覆盖（替换，不累加）。',
                ),
                option('清空后回填', '先清空购物车，再按本次明细重建（适合购物车里的内容已作废的情况）。'),
                h('div', { class: 'rf-tip' }, `⚠ 将清空你购物车中现有的 ${cartCount} 项商品，且不可撤销。`),
              ],
              footer: () =>
                h('div', { class: 'rf-foot' }, [
                  h(ElButton, { onClick: () => finish(null) }, () => '取消'),
                  h(ElButton, { type: 'primary', onClick: () => finish('merge') }, () => '合并'),
                  // 破坏性操作：danger 实心 + 文案直接写明不可撤销（ADR-042 Consequences）
                  h(ElButton, { type: 'danger', onClick: () => finish('replace') }, () => '清空后回填（不可撤销）'),
                ]),
            },
          )
      },
    })

    render(h(DialogHost), host)
  })
}

/**
 * 「无法回填到购物车」弹窗（REFILL-20261022-F3 重做，替换原 `MessageBox.alert` 文本列表）。
 *
 * 旧版：标题黑字 → 一行说明 → 两个圆点 + 两条超长中文句子 → 一行橙色小字 —— 产品名、数量、
 * 失败原因、库存数值全糊在一句话里，扫读困难，且与站内「卡片 / 胶囊 / 浅色提示条」语言脱节。
 * 新版：`el-dialog`（560px，居中）自定义头部（⚠ + 标题 + 副标题）→ 逐行
 * 「产品名 × 数量 + 状态胶囊 + 库存/锁定/出库/需求」→（仅可售不足时）橙色提示条 → 「知道了」。
 *
 * 语义与旧版一致：**仅关闭，不发起任何请求、不跳转**；列表不截断（行多时内部滚动，头尾固定）。
 *
 * ADR-043 §3：回填目标是他人时，副标题追加「（回填目标：X）」——让操作者明白"失败的是谁的车"，
 * 也避免再被误读成"已经回填到某人购物车了"。`buildFailRows` 结构不变，归属只出现在副标题。
 */
function showRefillFailed(
  outcome: Extract<RefillOutcome, { kind: 'alert-all-failed' }>,
  res: RefillResult,
  code: string,
): Promise<void> {
  const rows = buildFailRows(res, db.assets)
  // 全部失败分支（restored === 0），但 rows 里可能混有 ok 行，故分别算总行数 / 失败行数
  const total = res.rows?.length || res.skipped || rows.length
  const failedCount = rows.length
  const order = code ? `订单 ${code} ` : ''
  const ownerNote = outcome.ownerName ? `（回填目标：${outcome.ownerName}）` : ''
  const subtitle =
    (failedCount >= total
      ? `${order}共 ${total} 行明细，均未能回填`
      : `${order}共 ${total} 行，${failedCount} 行未能回填`) + ownerNote
  const hasInsufficient = rows.some((r) => r.code === 'insufficient')
  // replace 已清空原购物车属于破坏性结果，必须显式告知（旧版那句 clearNote 不能丢）
  const cleared = res.cleared ?? 0
  const clearedNote =
    res.mode === 'replace' && cleared > 0
      ? `已按你的选择清空原购物车 ${cleared} 项商品，本次无任何明细回填成功。`
      : ''
  const rowViews: RefillFailRow[] = rows.length
    ? rows
    : [{ name: '后端未返回逐行原因，请稍后重试或联系管理员', code: 'other', meta: '', detail: '' }]

  return new Promise<void>((resolve) => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const visible = ref(true)
    const cleanup = () => {
      render(null, host)
      host.remove()
    }
    const close = () => {
      visible.value = false
    }

    const rowNodes: VNode[] = rowViews.map((r, i) => {
      const nameNode =
        r.qty === undefined
          ? h('div', { class: 'rf-name' }, r.name)
          : h('div', { class: 'rf-name' }, [r.name, h('span', { class: 'rf-qty' }, `× ${r.qty}`)])
      const kids: VNode[] = [
        h('div', { class: 'rf-row-main' }, [
          nameNode,
          // el-tag 的 type 在 h() 里就是普通 prop：`type: 'danger'`（取值见 TAG_TYPE）
          h(ElTag, { size: 'small', type: TAG_TYPE[r.code], effect: 'light' }, () => TAG_TEXT[r.code]),
        ]),
      ]
      if (r.meta) kids.push(h('div', { class: 'rf-meta' }, r.meta))
      if (r.detail) kids.push(h('div', { class: 'rf-detail' }, r.detail))
      return h('li', { class: 'rf-row', key: i }, kids)
    })

    const bodyKids: VNode[] = [h('ul', { class: 'rf-list' }, rowNodes)]
    if (hasInsufficient) bodyKids.push(h('div', { class: 'rf-tip' }, TIP_INSUFFICIENT))
    if (clearedNote) bodyKids.push(h('div', { class: 'rf-tip is-danger' }, clearedNote))

    const FailedDialog = defineComponent({
      name: 'ResubmitRefillFailedDialog',
      setup() {
        return () =>
          h(
            ElDialog,
            {
              modelValue: visible.value,
              width: '560px',
              appendToBody: true,
              alignCenter: true,
              closeOnClickModal: true,
              class: 'rf-dialog',
              'onUpdate:modelValue': (v: boolean) => {
                visible.value = v
              },
              onClosed: () => {
                cleanup()
                resolve()
              },
            },
            {
              header: () => dialogHeader(h(WarningFilled), outcome.title, subtitle, 'warn'),
              default: () => h('div', { class: 'rf-body' }, bodyKids),
              footer: () =>
                h('div', { class: 'rf-foot' }, [h(ElButton, { type: 'primary', onClick: close }, () => '知道了')]),
            },
          )
      },
    })

    render(h(FailedDialog), host)
  })
}

/**
 * 重新提交动线（两处调用点共用）。
 * `busy` 为动线级防连点（页面可另有行级 loading 用于按钮态）。
 */
export function useResubmitProject() {
  const router = useRouter()
  const busy = ref(false)

  /** 跳 /cart 前的镜像刷新：回填已写库，刷新失败不阻断跳转（购物车页 onMounted 会再刷一次） */
  async function gotoCart(skips?: string[]): Promise<void> {
    try {
      await refresh()
    } catch {
      /* 忽略：见上 */
    }
    if (skips && skips.length) {
      router.push({ path: '/cart', state: { refillSkips: skips } })
    } else {
      router.push('/cart')
    }
  }

  /**
   * 执行重新提交。
   * @param p 项目 `{id, code, name}`（可附 creator/rep 供归属预判）
   * @param opts.cartCount 当前购物车行数（页面传 `db.cart.length`）；>0 且是本人车才弹三选框
   * @returns 无返回值；「已成功跳转」或「已给出结果（提示/弹窗）」两条路径均正常 resolve
   */
  async function resubmit(p: ResubmitTarget, opts: { cartCount?: number } = {}): Promise<void> {
    if (busy.value) return
    busy.value = true
    try {
      const me = currentUser.value
      const cartCount = Math.max(0, opts.cartCount ?? 0)
      let mode: RefillMode = 'merge'
      if (shouldAskRefillMode({ cartCount, ownerLikelySelf: isOwnCartTarget(p, me) })) {
        const chosen = await askRefillMode(cartCount)
        if (!chosen) return // 取消：什么都不做（不调接口、不跳转）
        mode = chosen
      }

      const first = await refillProjectCart(p.id, mode)
      let res = first
      // ADR-042 补遗5（REFILL-20261022-F2）：幂等短路 + 本人空车 → 自愈重填一次。
      // 插入点在「幂等分支」之前，不改动 decideRefillOutcome 的分支优先顺序
      // （ADR-042 补遗6 / ADR-043 §3：幂等 → 全失败 → 部分/成功后再判归属）。
      // 只在首次响应 alreadyRefilled 且 cartCount===0 时触发；原本就是空车，故不会再弹三选框
      // （用户已明确点过「重新提交」，空车没有任何选择必要）。**仅重试一次，无循环。**
      if (shouldSelfHealRefill(first, cartCount, me?.username)) {
        try {
          res = await refillProjectCart(p.id, 'replace')
        } catch (e) {
          // 回退旧行为：旧后端（不认 mode）/ 归属被判为他人（服务端 400）等，都不该抛给用户。
          // 说明：此处**不走 showError**——首次响应本来就不是失败，静默降级为「已在购物车」，
          // 仅留一条带任务号的 warn 便于排查（同类问题再出现时可从控制台定位）。
          console.warn(
            '[REFILL-20261022-F2] 幂等短路自愈（mode=replace）失败，回退「明细已在购物车」分支：',
            e,
          )
          ElMessage.success('明细已在购物车，可直接修改后提交')
          await gotoCart()
          return
        }
      }
      const outcome = decideRefillOutcome(res, me?.username ?? '')

      switch (outcome.kind) {
        case 'notify-owner':
          // 明细进了别人的车：只提示并停留原页（ADR-042 §5）。**仅 reached when restored > 0**——
          // 全失败在上一个分支已拦下，所以这里不会再把失败包装成成功（ADR-043 §3）
          ElMessage.success(outcome.message)
          return
        case 'push-already':
          // 目标非本人（ADR-042 补遗6 / ADR-043 §3）：明细在**别人**的车里，跳 /cart 只会看到自己的空车
          if (outcome.ownerName) {
            ElMessage.success(`明细已在 下单人 ${outcome.ownerName} 的购物车，请通知该账号前往改单`)
            return
          }
          ElMessage.success('明细已在购物车，可直接修改后提交')
          await gotoCart()
          return
        case 'alert-all-failed':
          // 全部失败：不跳空车，逐行说明原因（ADR-042 §3；REFILL-20261022-F3 改为结构化弹窗）
          await showRefillFailed(outcome, res, p.code)
          return
        case 'push-with-warning':
          ElMessage.warning('部分明细未能回填，已到购物车页查看详情')
          await gotoCart(outcome.skips)
          return
        case 'push-plain':
        default:
          ElMessage.success('明细已回填购物车，可修改后提交')
          await gotoCart()
      }
    } catch (e) {
      showError(e, '重新提交失败')
    } finally {
      busy.value = false
    }
  }

  return { busy, resubmit }
}
