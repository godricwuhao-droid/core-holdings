<script setup lang="ts">
/**
 * 购物车 - 汇总待售产品
 *
 * 展示已加入购物车的产品，支持调整数量 / 移除 / 清空；数量受可用数量约束。
 * ADR-007：允许跨主体混装；每行填写「客户」，结算时按（产品, 客户）双键分组（ADR-016，2026-10-20）——
 * 每个「产品 × 客户」组合生成一份合同（一资产一客户一记录），全部挂在同一个「进行中」销售项目下并锁定数量。
 * 交付（扣数量 + 交付记录）在项目详情页对合同执行「交付」后触发。
 * 数据预留 userId 维度（当前默认 admin），为后续账号权限管控做准备。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, InfoFilled, ShoppingCart, WarningFilled } from '@element-plus/icons-vue'
import { availableQty, displayUnitPrice, entityShort, formatMoney, formatTokens, isAmountMode, isAmountTextValid, priceRangeText, roundAmount, rsItemName, sanitizeAmountInput, type Asset, type CartItem, type RsItem } from '@/types'
import { checkoutCart, clearCart, db, genRequestId, getAsset, patchCartItem, refresh, removeCartItem, rsItemById, setCartAmount, setCartQty, setCartService, showError, type OrderFields } from '@/api'
import SalesOrderDialog from '@/components/SalesOrderDialog.vue'
import type { OrderItem } from '@/components/SalesOrderDialog.vue'

const router = useRouter()

// ==================== 「重新提交」未回填明细警告条（ADR-042 / REFILL-20261022） ====================
/**
 * 读取并**立即清除** history.state 里的未回填清单。
 * 来源：项目页「重新提交」部分失败时 `router.push({ path: '/cart', state: { refillSkips } })`
 * （history.state 是跨页传参的轻量通道，不污染 URL）。
 * 清除动机：state 挂在当前历史条目上，**不清就会被浏览器刷新 / 后退再前进重复消费**（警告条反复出现）；
 * 读完立刻 replaceState 置 null，并把 Vue Router 自己的 back/forward/position 等键原样保留。
 * 必须在 setup 首帧执行一次（早于渲染），故在模块作用域直接调用。
 */
function readAndClearRefillSkips(): string[] {
  const st = (window.history.state ?? {}) as Record<string, unknown>
  const raw = st.refillSkips
  if (raw == null) return []
  window.history.replaceState({ ...st, refillSkips: null }, '')
  return Array.isArray(raw) ? raw.map((x) => String(x)) : []
}
const skipLines = ref<string[]>(readAndClearRefillSkips())
/** 「知道了」仅隐藏本条（history 已在 setup 时清理，无需再动） */
const skipClosed = ref(false)
const skipNotice = computed(() => (skipClosed.value ? [] : skipLines.value))

interface CartRow {
  cart: CartItem
  asset: Asset
  price: number
  subtotal: number
  /** ADR-008：包量定价行（合同金额权威，单价仅参考） */
  isAmount: boolean
  /** ADR-011：遥感明细行（含 itemId，数量恒 1，单价 = 明细 price）
   *  显式 `RsItem | undefined`（而非可选属性）：computed map 恒返回该键，
   *  可选属性会使 filter 类型谓词 `r is CartRow` 不满足可赋值性（TS2677） */
  rsItem: RsItem | undefined
  /** 本行可用数量上限（FIX-20261022 / BUG-22）：可重复售卖 null（不限），否则为
   *  「可售数量 − 同产品其他行已占数量」 */
  avail: number | null
}

const cartRows = computed<CartRow[]>(() => {
  const rows = db.cart
    .map((c) => {
      const asset = getAsset(c.assetId)
      const rsItem = c.itemId != null ? rsItemById(c.itemId) : undefined
      const isAmount = !!asset && !rsItem && isAmountMode(asset)
      // ADR-018 §3 + 2026-10-29 语义修正：
      // unit 模式 cart_items.amount = **单价**（元/单位），行总价 = 单价 × 数量；
      // amount 模式（卫星 Token）amount = 合同总价（ADR-008）；
      // 遥感明细行（rsItem）amount = 单价 = 总价（qty 恒 1）。
      // 未填 = 原价成交：遥感行 = 明细单价、amount 行回退「挂牌价×数量」、unit 行 = 挂牌价×数量
      const amountFallback = roundAmount((asset?.salePrice ?? 0) * c.qty)
      const subtotal = c.amount != null
        ? (rsItem || isAmount ? c.amount : roundAmount(c.amount * c.qty))
        : (rsItem ? rsItem.price : isAmount ? amountFallback : (asset?.salePrice ?? 0) * c.qty)
      return {
        cart: c,
        asset,
        price: rsItem ? rsItem.price : asset?.salePrice ?? 0,
        subtotal,
        isAmount,
        rsItem,
        // 下面统一按「同产品其他行已占数量」回填（declared 为可空，避免字面量 null 收窄类型）
        avail: null as number | null,
      }
    })
    .filter((r): r is CartRow => !!r.asset)
  // FIX-20261022 / BUG-22：数量上限改「同产品合计」口径（后端 PUT /cart/{id} 与 checkout 均按
  // 该产品在购物车全部行合计校验）——本行上限 = 可售 − 同 assetId 其他行 qty 合计，避免越界只能靠后端 400 回滚
  const qtyByAsset = new Map<number, number>()
  for (const r of rows) qtyByAsset.set(r.cart.assetId, (qtyByAsset.get(r.cart.assetId) ?? 0) + r.cart.qty)
  for (const r of rows) {
    if (r.asset.repeatSale) continue // 可重复售卖不限数量
    const others = (qtyByAsset.get(r.cart.assetId) ?? 0) - r.cart.qty
    r.avail = Math.max(0, (availableQty(r.asset) ?? 0) - others)
  }
  return rows
})

const totalQty = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))
// ADR-048：多位小数累加按 1e-6 规整，避免 JS 浮点尾巴导致前端合计与后端 Decimal 求和不等
const totalAmount = computed(() => roundAmount(cartRows.value.reduce((s, r) => s + r.subtotal, 0)))

// ==================== 行级客户（ADR-007/ADR-016：结算时按（产品, 客户）双键分组拆合同） ====================
// 2026-10-24（ADR-022）：客户/金额必填口径——缺项标红改为值驱动；2026-10-26（ADR-047）服务期限改选填
//（字段为空即标红，与列头红星同口径），不再维护 error id 集合（原 customerErrors/amountErrors 删除）

/** CART-PERF2-20261021（2026-10-21）：客户输入本地草稿（与 amountDrafts 同模式，按行 id 存）——
 *  剩余卡顿根因：原 v-model 每敲一字直接写 row.cart.customer（db.cart 共享镜像）→ cartRows computed 重算
 *  → 新数组 + 新行对象 → el-table :data 身份变化 → 整表重渲染（fixed 列双份 + 全部 tooltip）。
 *  改敲字只写草稿（不碰镜像、cartRows 不重算），失焦/回车经 onCustomerChange 提交（提交时才 trim）；
 *  无草稿时显示由已提交值派生（刷新后仍一致）。
 *  约定：本页逐字输入只写草稿（客户/金额均草稿化），日期 picker 为 change 提交非逐字（见模板注释）。
 *  CART-PERF2-20261021 修复：草稿存储必须用 reactive(Record) 而非 ref(Record)——
 *  ref(plainObject) 的索引读写（drafts[id]）落在 RefImpl 实例自身（绕过响应式代理），
 *  草稿更新不触发任何重渲染（显示/标红不跟随草稿，CART-PERF 遗留缺陷）；
 *  reactive 对象按属性追踪，敲字仅失效本行单元格渲染，cartRows（:data）仍不重算 */
const customerDrafts = reactive<Record<number, string>>({})

/** 客户输入框当前显示值（草稿优先，无草稿读已提交值） */
function customerDraft(row: CartRow): string {
  return customerDrafts[row.cart.id] ?? (row.cart.customer ?? '')
}

/** 客户有效值（「草稿或已提交值」合并口径，trim 后）——标红校验与结算前置校验共用：
 *  用户敲了还没失焦的客户名也计入校验（草稿优先），与金额（amountValue）同口径 */
function customerValue(row: CartRow): string {
  return customerDraft(row).trim()
}

/** 客户输入：CART-PERF2-20261021：只写草稿，不再碰 row.cart.customer（敲字不 trim，提交时才 trim） */
function onCustomerInput(row: CartRow, v: string) {
  customerDrafts[row.cart.id] = v ?? ''
}

// ==================== 行级销售金额（ADR-008 包量定价行权威输入；ADR-022 起所有行必填） ====================
/** CART-PERF-20261021（2026-10-21）：金额输入本地草稿（与 customerDrafts 同模式，按行 id 存）——
 *  卡顿次因：原每敲一字直接写 row.cart.amount（db.cart 共享镜像）→ cartRows computed 重算 →
 *  el-table 整表重渲染（含固定列双渲染 + 全部 tooltip）。改敲字只写草稿（不碰镜像、cartRows 不重算），
 *  失焦/回车经 onAmountChange 提交；无草稿时显示由已提交值派生（刷新后仍一致）。
 *  CART-PERF2-20261021（2026-10-21）：ref → reactive（同 customerDrafts，见其注释——
 *  ref(plainObject) 索引读写绕过响应式代理，草稿更新不触发重渲染） */
const amountDrafts = reactive<Record<number, string>>({})

/** 金额输入框当前显示值（草稿优先，无草稿读已提交值） */
function amountDraft(row: CartRow): string {
  return amountDrafts[row.cart.id] ?? (row.cart.amount != null ? String(row.cart.amount) : '')
}

/** 金额有效值（「草稿或已提交值」合并口径）——标红校验与结算前置校验共用：
 *  用户敲了还没失焦的金额也计入校验（草稿优先），避免「敲了 1000 没失焦就点结算被拦」的坑 */
function amountValue(row: CartRow): number | undefined {
  const t = amountDraft(row)
  return t === '' ? undefined : Number(t)
}

/** 金额输入：允许最多 6 位小数（元口径，ADR-048）——只写草稿，不再碰 row.cart.amount。
 *  过滤复用 `sanitizeAmountInput`（非数字/小数点丢弃、多余小数点丢弃、小数位截断到 6 位）。
 *  ADR-039（NO-DISCOUNT-20261022）：折扣快捷入口下线后，金额是唯一输入路径，
 *  原「手改金额 → 折扣镜像作废」的 amountManualDrafts 标记 / 清折扣草稿分支一并删除 */
function onAmountInput(row: CartRow, v: string) {
  amountDrafts[row.cart.id] = sanitizeAmountInput(v)
}

/** 金额缺项（空 / 0 / 格式非法 / 超 6 位小数）→ 标红，与客户列同一「必填缺项」样式
 *  CART-PERF-20261021：改读「草稿或已提交值」合并口径（amountValue），标红跟随输入草稿实时变化 */
function amountInvalid(row: CartRow): boolean {
  const t = amountDraft(row).trim()
  const n = amountValue(row)
  return t === '' || !isAmountTextValid(t) || n === undefined || !Number.isFinite(n) || n <= 0
}

/** 2026-10-26（ADR-047，OPTIONAL-SERVICEPERIOD-20261026）：服务期限改为**选填**，标红口径同步：
 *  - 两端都空 → 合法，不标红（原 ADR-022「任一为空即标红」口径作废）；
 *  - 只填一端 → 成对缺失，两端都标红；
 *  - 两端都填但 start > end → 两端都标红。
 *  遥感明细行豁免（ADR-020，模板本就不渲染日期输入） */
function serviceMissing(row: CartRow): boolean {
  const s = row.cart.serviceStart || ''
  const e = row.cart.serviceEnd || ''
  if (!s && !e) return false // 选填：都不填 → 放行
  if (!s || !e) return true // 成对校验：只填一端 → 缺项
  return s > e // 顺序校验：开始晚于结束 → 非法
}

// 2026-10-25：金额输入框 tooltip 文案 amountTip() 随输入框 hover 提示删除（用户反馈「太碍事」）——
// 必填/两位小数口径见列头红星 + 顶部提示条，参考区间见金额下方提示行，无信息死角

/** 行参考区间文案（ADR-021，RSITEM-RANGE-20261020）：
 *  遥感明细行（rsItem 非空）读该明细自身区间（不再取父产品容器区间）；普通行读产品区间；未设返回空串不显示 */
function rowRangeText(row: CartRow): string {
  return row.rsItem ? priceRangeText(row.rsItem) : priceRangeText(row.asset)
}

/** 失焦/回车提交（ADR-018 §3，PRICING-20261020；2026-10-24 ADR-022 必填口径；
 *  CART-PERF-20261021 改读草稿）：
 *  - 所有行（unit/amount/遥感）：最多 6 位小数的元值 > 0 才提交（ADR-048，原仅整数元）；
 *    缺项（空/0/超 6 位小数）不提交，保留草稿，输入框值驱动标红
 *  - 合法草稿在 await 前的**同步段**即写入镜像并清草稿——点「结算下单」按钮会先触发本输入框 blur
 *    （浏览器行为：mousedown → blur/change 先于 click），openOrder 校验运行时镜像已是最新值，
 *    天然失焦链路成立，无需额外合并处理（amountInvalid 的草稿合并口径作双保险）
 *  - 低于参考区间下限由后端 400（文案走 showError），400 时回滚到后端值并重置草稿；
 *    ADR-049：高于区间上限不拦截（金额可超上限成交）
 *  ADR-039（NO-DISCOUNT-20261022）：折扣快捷入口下线——原「手改金额 → 折扣镜像作废 / 无手改则回传 rate」
 *  两分支整体删除，payload 只剩 qty + amount（金额是唯一权威，后端也不再读取折扣字段） */
async function onAmountChange(row: CartRow) {
  if (amountInvalid(row)) return // 缺项/非法不提交（标红由值驱动，草稿保留）
  const n = roundAmount(amountValue(row) ?? 0) // 按 1e-6 规整：规避 JS 浮点尾巴（如 0.1+0.2）
  if (n <= 0) return
  row.cart.amount = n
  // CART-PERF2-20261021（2026-10-21）：清草稿用 delete（而非置 ''）——'' 是合法草稿值（用户清空未失焦），
  // delete 后显示回退已提交值（镜像已写入 n）
  delete amountDrafts[row.cart.id]
  try {
    // 回传该行当前 qty：后端 PUT 对 qty<=0 直接 400，且区间校验按新 qty 重算
    await setCartAmount(row.cart.id, row.cart.qty, n)
  } catch (e) {
    showError(e, '销售金额更新失败')
    await refresh(true)
    delete amountDrafts[row.cart.id] // 回滚：删草稿 → 显示回退刷新后的镜像（后端值）
  }
}

// CART-PERF-20261021（2026-10-21）性能自查（修复清单第 4 项）：模板单元格内调用的方法
// （amountDraft/amountInvalid/serviceMissing/rowRangeText 等）均只读
// per-row 状态（row.cart.* 属性 + 草稿 Record 的单个 id 键），不遍历 cartRows/db.cart——
// 敲字只失效本行依赖，cartRows computed（:data）不重算，el-table 无整表重建（无固定列双渲染重建）。
// 遍历 cartRows 的 previewGroups/orderItems 仅用于结算栏/弹窗，不在表格单元格渲染路径上。
// ADR-039（NO-DISCOUNT-20261022）：本页原「行级快捷换算率」整段（草稿/校验/摘要/placeholder 预览/
// 失焦回填）已全部删除，金额输入是唯一路径，placeholder 固定「必填，最多 6 位小数」。

// ==================== 行级服务期限（ADR-020，PRICING-20261020：普通产品行填写，遥感行不展示） ====================
/** 服务期限变更：PUT /cart/{id} 提交（回传 qty）；start > end 前端先拦，其余校验（格式/顺序）由后端 400 兜底 */
async function onServiceChange(row: CartRow) {
  const s = row.cart.serviceStart || null
  const e = row.cart.serviceEnd || null
  if (s && e && s > e) {
    ElMessage.warning('服务开始日期不能晚于结束日期')
    await refresh(true) // 回滚到后端值
    return
  }
  try {
    await setCartService(row.cart.id, row.cart.qty, s, e)
  } catch (err) {
    showError(err, '服务期限更新失败')
    await refresh(true)
  }
}

/** 结算预览：按（产品, 客户）双键分组（保持行序），每组 = 未来一份合同
 *  2026-10-20（ADR-016）：原按客户单键分组，与后端 checkout 的 (assetId, customer) 分组口径不一致
 *  （同产品多客户被静默合并为一条记录）；改为双键后「将生成 N 份销售记录」提示与落库一致 */
const previewGroups = computed(() => {
  const groups: { assetName: string; customer: string; qty: number; amount: number; service?: string }[] = []
  const idx = new Map<string, number>()
  const svcSets = new Map<number, Set<string>>()
  for (const r of cartRows.value) {
    // CART-PERF2-20261021（2026-10-21）：保持读已提交值（r.cart.customer），不用草稿合并口径——
    // 点「结算下单」会先触发客户输入框失焦（change 先于 click，onCustomerChange 已提交并更新镜像），
    // 预览仅在结算弹窗打开后展示，草稿窗口期不存在，读镜像即最新值
    const customer = (r.cart.customer ?? '').trim()
    if (!customer) continue
    const key = `${r.cart.assetId}::${customer}`
    let i = idx.get(key)
    if (i === undefined) {
      i = groups.length
      idx.set(key, i)
      groups.push({ assetName: r.asset.name, customer, qty: 0, amount: 0 })
      svcSets.set(i, new Set())
    }
    groups[i].qty += r.cart.qty
    // ADR-048：分组小计按 1e-6 规整累加（与后端 checkout 的 Decimal 求和同口径）
    groups[i].amount = roundAmount(groups[i].amount + r.subtotal)
    // ADR-020（PRICING-20261020）：组内行服务期限一致时在预览行简短展示（不影响分组逻辑）
    if (r.cart.serviceStart || r.cart.serviceEnd) {
      svcSets.get(i)!.add(`${r.cart.serviceStart || '-'} ~ ${r.cart.serviceEnd || '-'}`)
    }
  }
  for (const [gi, set] of svcSets) {
    if (set.size === 1) groups[gi].service = [...set][0]
  }
  return groups
})

/** 行内编辑客户：失焦 / 回车提交；400（同产品同客户已有行）弹后端文案并回滚
 *  CART-PERF2-20261021（2026-10-21）：提交值改读草稿优先的合并值（customerValue，trim 后）——
 *  镜像不再逐字更新，草稿是输入权威；成功后 patchCartItem（patchCartRow）已把镜像替换为后端值，
 *  清草稿即可（显示由镜像派生）；400 回滚（refresh(true)）后同样清草稿——
 *  草稿重置为后端值口径（与金额草稿回滚同写法，显示改由刷新后的镜像派生） */
async function onCustomerChange(row: CartRow) {
  const id = row.cart.id
  const next = customerValue(row)
  // 2026-10-24（ADR-022）：缺项标红为值驱动（空即红），无需维护 error 集合
  try {
    await patchCartItem(id, next)
    // CART-PERF2-20261021：清草稿用 delete（而非置 ''）——'' 是合法草稿值（用户清空未失焦），
    // delete 后显示回退已提交值（镜像已由 patchCartRow 更新为后端值）
    delete customerDrafts[id]
  } catch (e) {
    showError(e, '客户修改失败')
    await refresh(true) // 回滚到后端值
    delete customerDrafts[id] // 回滚：删草稿 → 显示回退刷新后的镜像（后端值），与金额草稿回滚同口径
  }
}

onMounted(async () => {
  await refresh()
})

/** 本行可用数量上限（FIX-20261022 / BUG-22）：可重复售卖 null（不限）；
 *  否则 = 可售数量 − 同产品其他行已占数量（口径见 cartRows 内注释） */
function availOf(row: CartRow): number | null {
  return row.avail
}

/** 数量输入上限：可重复不限；否则取本行可用上限（至少 1，避免 min/max 冲突） */
function qtyMax(row: CartRow): number | undefined {
  return row.asset.repeatSale ? undefined : Math.max(availOf(row) ?? 0, 1)
}

function goAssetDetail(assetId: number) {
  router.push(`/assets/${assetId}/detail`)
}

/** 产品类型 → 图标块字符（2026-10-22 视觉优化：借鉴 cart-ui-demo.html 产品图标，按现有类型集合映射） */
function typeIcon(type: string): string {
  switch (type) {
    case '软件':
      return '◈'
    case '平台软件':
      return '◫'
    case '数采设备':
    case '硬件集群':
      return '▣'
    case '算力服务器':
      return '⚡'
    case '卫星Token':
      return '◉'
    case '卫星数据':
      return '✦'
    case '遥感数据':
      return '▦'
    default:
      return '◆'
  }
}

/** 数量变更提交；返回是否成功（stepQty 需据此决定是否提示重填销售金额） */
async function onQtyChange(row: CartRow): Promise<boolean> {
  // ADR-011：遥感明细行数量恒 1（输入禁用，双保险拦截）
  if (row.rsItem) return false
  const avail = availOf(row)
  if (avail !== null && row.cart.qty > avail) {
    ElMessage.error(`「${row.asset.name}」可用数量仅 ${avail}${row.asset.unit}，已为你回退`)
    row.cart.qty = avail
    return false
  }
  try {
    // 2026-10-29：携带当前金额（后端有 amount 时保留不清空），解决「先填金额再改数量 → 金额丢失」
    await setCartQty(row.cart.id, row.cart.qty, row.cart.amount)
    return true
  } catch (e) {
    showError(e, '数量更新失败')
    row.cart.qty = avail ?? row.cart.qty
    await refresh(true)
    return false
  }
}

/** 步进器行级 in-flight 互斥（FIX-20261022 / BUG-25）：同行请求在飞期间禁用 ± 按钮/输入框，
 *  避免连点产生并发 PUT、响应乱序把镜像写回旧数量/旧金额 */
const qtyBusy = reactive<Record<number, boolean>>({})

/** 数量输入本地草稿（2026-10-27 DIRECT-QTY-INPUT）：数量改为可直接键入——
 *  敲字只写草稿、不碰共享镜像，失焦/回车才提交（与 amountDrafts 同模式，按行 id 存） */
const qtyDrafts = reactive<Record<number, string>>({})

/** 输入框显示值：草稿优先，未编辑时回落到镜像值 */
function qtyText(row: CartRow): string {
  return qtyDrafts[row.cart.id] ?? String(row.cart.qty)
}

/** 键入过滤：只留数字（去掉负号/小数点/字母），最多 6 位（数量级远小于此） */
function onQtyInput(row: CartRow, e: Event) {
  const el = e.target as HTMLInputElement
  const filtered = el.value.replace(/\D/g, '').slice(0, 6)
  if (el.value !== filtered) el.value = filtered // 非法字符立即清掉，光标位置由浏览器保持
  qtyDrafts[row.cart.id] = filtered
}

/** 数量提交（失焦 / 回车）：空、0、非整数 → 静默回退显示镜像值；未变更 → 直接收起草稿；
 *  变更 → 走 applyQty 的 PUT 提交链路（上限截断 / 400 回滚 / 金额被清空提示与 ± 同口径） */
async function onQtyCommit(row: CartRow, e?: Event) {
  const el = e?.target as HTMLInputElement | undefined
  const raw = qtyDrafts[row.cart.id]
  if (raw === undefined) return // change 与 blur 双触发：第二次已无草稿
  delete qtyDrafts[row.cart.id]
  if (row.rsItem || qtyBusy[row.cart.id]) {
    if (el) el.value = String(row.cart.qty)
    return
  }
  const n = Number(raw)
  if (!raw.trim() || !Number.isInteger(n) || n < 1) {
    if (el) el.value = String(row.cart.qty) // 非法输入静默回退，不弹提示（避免误触打扰）
    return
  }
  if (n === row.cart.qty) {
    if (el) el.value = String(n)
    return
  }
  await applyQty(row, n, true)
  // 提交后回写 DOM：可能被上限截断、400 回退或被 refresh 替换镜像（用最新镜像值兜底）
  const fresh = db.cart.find((c) => c.id === row.cart.id)
  if (el) el.value = String(fresh ? fresh.qty : row.cart.qty)
}

/** 数量落库（± 按钮与手工输入共用）：
 *  clampMax=true → 超可用上限时截断到上限并提示（手工输入 999 比「静默不生效」更易理解）；
 *  false → 直接忽略（± 按钮本就在上限处禁用，双保险） */
async function applyQty(row: CartRow, next: number, clampMax = false) {
  if (row.rsItem) return // ADR-011：遥感明细行数量恒 1
  if (qtyBusy[row.cart.id]) return // 本行上一次请求未回：忽略连点（按钮同时置灰）
  if (next < 1) return
  let target = next
  const max = qtyMax(row)
  if (max != null && target > max) {
    if (!clampMax) return
    target = max
    ElMessage.warning(`「${row.asset.name}」可用数量仅 ${max}${row.asset.unit}，已按上限填写`)
  }
  const prevAmount = row.cart.amount
  qtyBusy[row.cart.id] = true
  try {
    row.cart.qty = target
    const ok = await onQtyChange(row)
    if (!ok) return
    // FIX-20261022 / BUG-27：后端改数量时会静默清空已填金额（旧总额对新数量已失真）。
    // 前端必须显式提示重填；该行标红由 amountInvalid 值驱动（镜像 amount 已为 null → 输入框立即标红）
    // ADR-039（NO-DISCOUNT-20261022）：原「按旧换算率重算金额并回写」分支已删除——
    // 改数量后金额不自动重算（金额是权威，保持用户填的值；被后端清空则提示重填，绝不回填推算值）
    // 2026-10-29 修复：草稿态（amountDrafts 有值但 row.cart.amount 仍 null）也需清草稿并提示，
    // 否则页面金额框残留旧草稿但后端已无值，合计/结算不一致
    const fresh = db.cart.find((c) => c.id === row.cart.id)
    const hadValue = prevAmount != null || amountDrafts[row.cart.id] != null
    if (hadValue && fresh && fresh.amount == null) {
      delete amountDrafts[row.cart.id]
      ElMessage.warning(`「${row.asset.name}」数量已变更，请重新填写销售金额`)
    }
  } finally {
    delete qtyBusy[row.cart.id] // 只清自己的行锁（行 id 唯一，天然不误清新行）
  }
}

/** 步进器 ±1（2026-10-22 视觉优化：替代 el-input-number）：
 *  改数量后复用 applyQty 的 PUT 提交链路（含上限拦截 / 400 回滚），业务逻辑零变更 */
async function stepQty(row: CartRow, delta: number) {
  await applyQty(row, row.cart.qty + delta)
}

async function removeRow(row: CartRow) {
  try {
    await removeCartItem(row.cart.id)
    ElMessage.success('已移除')
  } catch (e) {
    showError(e, '移除失败')
  }
}

async function clearAll() {
  if (!db.cart.length) return
  try {
    await ElMessageBox.confirm('确定清空购物车？将移除全部已添加产品。', '清空购物车', {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await clearCart()
    ElMessage.success('购物车已清空')
  } catch (e) {
    showError(e, '清空失败')
  }
}

function goAssets() {
  router.push('/assets/embodied')
}

// ==================== 下单（生成进行中项目并锁定数量，复用 SalesOrderDialog） ====================
const orderVisible = ref(false)
const orderLoading = ref(false)

const orderItems = computed<OrderItem[]>(() =>
  cartRows.value.map((r) => ({
    asset: r.asset,
    qty: r.cart.qty,
    // ADR-018 §3（PRICING-20261020）：已填销售金额的行（包量定价权威值 / unit 与遥感行成交金额）携带 amount；
    // 未填行不带（对话框按 单价×数量 占位展示，结算以后端 cart_items 持久化值为准）
    ...(r.cart.amount != null ? { amount: r.cart.amount } : {}),
    // ADR-011：遥感明细行携带 itemId（数量恒 1，单价 = 明细 price）
    ...(r.rsItem ? { itemId: r.rsItem.id } : {}),
  })),
)

/** 结算前置校验（2026-10-24 ADR-022 / 2026-10-26 ADR-047，与后端 checkout 400 同口径）：
 *  客户非空 / 金额最多 6 位小数且 > 0（所有行类型，含遥感行）为必填；普通行服务期限为**选填**
 *  ——两端都空放行，只填一端或 start > end 才拦（成对校验）；遥感明细行期限豁免（ADR-020）。
 *  有缺项不弹结算窗——提示点明缺项类别，
 *  缺项输入框本身已值驱动标红（amountInvalid / serviceMissing / 客户空值），用户可直接定位
 *  CART-PERF-20261021（2026-10-21）：金额校验读「草稿或已提交值」合并口径（amountInvalid → amountValue）——
 *  点结算按钮本身会先触发金额输入框 blur（change 先于 click，onAmountChange 同步段已把合法草稿写入镜像），
 *  天然失焦链路 + 草稿合并口径双保险：敲了还没失焦的合法金额不会被误拦，非法草稿（0/空）仍拦截
 *  CART-PERF2-20261021（2026-10-21）：客户校验改读合并口径（customerValue，草稿优先 trim 后）——
 *  点结算按钮同样先触发客户输入框 blur（onCustomerChange 已提交），天然失焦链路 + 草稿合并口径
 *  双保险：敲了还没失焦的客户名不会被误拦（与金额同口径） */
function openOrder() {
  if (!db.cart.length) return
  const missingCustomer = cartRows.value.filter((r) => customerValue(r) === '')
  const missingAmount = cartRows.value.filter((r) => amountInvalid(r))
  const missingService = cartRows.value.filter((r) => !r.rsItem && serviceMissing(r))
  const missingCount = missingCustomer.length + missingAmount.length + missingService.length
  if (missingCount) {
    const parts: string[] = []
    if (missingCustomer.length) parts.push('客户')
    if (missingAmount.length) parts.push('销售金额（元，最多 6 位小数）')
    if (missingService.length) parts.push('服务期限（开始/结束日期需成对填写，或都留空）')
    ElMessage.warning(`${missingCount} 行信息未填齐：请填写${parts.join('、')}`)
    return
  }
  orderVisible.value = true
}

/**
 * 结算幂等键（FIX-20261022 / BUG-10，ADR-033）：点击开始时生成，**同一次提交的重试沿用**，
 * 成功后清空（下次结算重新生成）。后端按 (userId, requestId) 24h 内幂等返回首次创建的项目，
 * 双击/失败重试不会重复建单与重复锁量。
 */
const checkoutRequestId = ref('')

async function onOrderSubmit(payload: { fields: OrderFields; items: { assetId: number; qty: number; amount?: number }[] }) {
  if (orderLoading.value) return // 请求在飞：忽略重复提交（按钮同时 loading 禁用）
  orderLoading.value = true
  // BUG-LAN-20261022：改用 genRequestId()——crypto.randomUUID 在局域网 http 下不存在，会导致下单 TypeError
  if (!checkoutRequestId.value) checkoutRequestId.value = genRequestId()
  try {
    // ADR-008：包量定价行合同金额已由行内失焦 PUT /cart/{id} 持久化，结算只传订单字段（后端 CheckoutInput 无 items）
    const p = await checkoutCart({ ...payload.fields, requestId: checkoutRequestId.value })
    checkoutRequestId.value = '' // 成功后丢弃幂等键
    orderVisible.value = false
    const cc = p.contractCount ?? previewGroups.value.length
    // ADR-012 修订（2026-10-19）：所有角色下单统一进「待审核」（数量已锁定），商务接手审核（可改价）后生效
    ElMessage.success(
      p.idempotent
        ? `该次结算已提交过，销售项目 ${p.code} 已存在（本次未重复建单）`
        : `下单成功，销售项目 ${p.code} 待审核（数量已锁定 · ${cc} 份销售记录），商务接手确认后生效`,
    )
    await refresh(true)
    router.push(`/sales/projects/${p.id}/detail`)
  } catch (e) {
    showError(e, '下单失败')
    await refresh(true)
  } finally {
    orderLoading.value = false
  }
}
</script>

<template>
  <!-- 2026-10-22 修复④：加 cart-page 类——底部留白需让开 sticky 吸附结算条（见 scoped 样式） -->
  <div class="page-container cart-page">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">销售管理 / 购物车</div>
        <h1>购物车</h1>
        <div class="desc">汇总待售产品，可调整数量、移除或清空；为每件产品填写客户后下单，按「产品 + 客户」分组生成销售记录并锁定数量，交付在项目详情页对销售记录执行「交付」即生成交付记录。</div>
      </div>
    </div>

    <!-- ADR-042 / REFILL-20261022：「重新提交」部分明细未能回填时的可关闭警告条。
         复用全局 .info-bar 骨架 + 警示橙（--warning-bg / #a86514，与「建设中」同配色，**不新增 token**）；
         无内容整条不渲染（不默认渲染空条）；内容为「以下明细未能回填：」+ 每条原因一行 + 「知道了」 -->
    <div v-if="skipNotice.length" class="info-bar refill-skip-bar" role="status">
      <el-icon aria-hidden="true"><WarningFilled /></el-icon>
      <div class="refill-skip-body">
        <div class="refill-skip-title">以下明细未能回填：</div>
        <ul class="refill-skip-list">
          <li v-for="(line, i) in skipNotice" :key="i">{{ line }}</li>
        </ul>
      </div>
      <button type="button" class="refill-skip-close" @click="skipClosed = true">知道了</button>
    </div>

    <!-- 空状态 -->
    <el-card v-if="!db.cart.length" shadow="never">
      <el-empty description="购物车为空">
        <el-button type="primary" :icon="ShoppingCart" @click="goAssets">去选择产品</el-button>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- 规则提示条（2026-10-22 视觉优化：借鉴 cart-ui-demo.html notice 条，压缩为「标题 + 要点」，关键规则语义全保留） -->
      <div class="cart-notice">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <div>
          <b>下单前请完善关键信息</b>
          <!-- 2026-10-24（ADR-022）：必填口径——客户/销售金额必填；2026-10-26（ADR-047）服务期限改选填 -->
          <!-- ADR-049（2026-10-29）：参考区间只约束下限——金额可高于上限成交（任何角色一致） -->
          <span>每件产品必填客户、销售金额（元，最多 6 位小数且 &gt; 0），服务期限为选填（填则开始/结束日期须成对且开始不晚于结束；遥感明细行按期数售卖，不填期限）；设参考区间时金额不得低于区间下限（<b>上限不限制，可高于上限成交</b>）；数量受产品可用数量约束（可重复售卖不受限）。下单后按「产品 + 客户」分组各生成一条销售记录，销售项目进入「待审核」并锁定数量，商务确认（可改价）后生效，再执行「交付」生成交付记录。</span>
        </div>
      </div>

      <!-- 表格卡 -->
      <el-card shadow="never">
        <div class="table-head">
          <span class="t">待售产品</span>
          <div class="th-right">
            <span class="c">共 {{ totalQty }} 件</span>
            <!-- ADR-009：清空购物车对三角色均可用（后端 require_order，已登录即可）；仅空车禁用 -->
            <el-button type="danger" plain :icon="Delete" :disabled="!db.cart.length" @click="clearAll">
              清空购物车
            </el-button>
          </div>
        </div>
        <!-- 2026-10-22 视觉优化：去 border（表格无竖线，UI 规范），保留 stripe 与行 hover；
             操作列仍 fixed="right"——列宽合计约 1416px（原 1376px），1440 屏宽（内容区约 1150px）下会溢出横滚 -->
        <!-- FT-20261022-F：全列表头统一居中（8 列显式 headerAlign=center），数据单元格 align 不变 -->
        <el-table :data="cartRows" stripe>
          <!-- FT-20261022-F：表头统一居中（全列显式 headerAlign=center） -->
          <el-table-column label="产品名称" min-width="240" align="left" header-align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构（主内容区 40px 垂直居中 + 副提示区 18px 占位），
                   保证所有行等高、各列输入框水平对齐 -->
              <div class="cart-cell">
                <div class="cell-main">
                  <!-- 2026-10-22 视觉优化：借鉴 demo 产品图标——名称左侧 42px 渐变圆角图标块（按类型区分字符） -->
                  <div class="cart-product">
                    <div class="cart-product-icon" aria-hidden="true">{{ typeIcon(row.asset.type) }}</div>
                    <div class="cart-product-info">
                      <!-- ADR-011：遥感明细行两行展示——主行父产品名，次级行明细名（省/市 精度 月份） -->
                      <!-- 2026-10-24 修复：长产品名换行后超出 40px 主区、首行被行分隔线盖住——
                           名称/meta 均改单行省略（CSS ellipsis），el-tooltip hover 显示全文
                           （与本页客户/金额列 tooltip 同款做法），行高保持 ~90px 不变 -->
                      <el-tooltip :content="row.asset.name" placement="top">
                        <a class="cart-asset-name" @click="goAssetDetail(row.asset.id)">{{ row.asset.name }}</a>
                      </el-tooltip>
                      <el-tooltip v-if="row.rsItem" :content="rsItemName(row.rsItem)" placement="top">
                        <div class="muted cart-asset-sub">{{ rsItemName(row.rsItem) }}</div>
                      </el-tooltip>
                      <el-tooltip v-else :content="`${row.asset.code} · ${row.asset.type} · ${entityShort(row.asset.subject)}`" placement="top">
                        <div class="muted cart-asset-sub">{{ row.asset.code }} · {{ row.asset.type }} · {{ entityShort(row.asset.subject) }}</div>
                      </el-tooltip>
                    </div>
                  </div>
                </div>
                <div class="cell-hint" aria-hidden="true"></div>
              </div>
            </template>
          </el-table-column>
          <!-- FT-20261022-F：自定义 #header 插槽为内联 span，th.is-center 的 text-align 可直接居中，无需兜底样式 -->
          <el-table-column label="客户" width="180" align="left" header-align="center">
            <!-- 2026-10-24（ADR-022）：列头必填红星（警示红，轻量） -->
            <template #header><span>客户<i class="req-star">*</i></span></template>
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——客户列无副提示，渲染空占位区保证行高一致 -->
              <div class="cart-cell">
                <div class="cell-main">
                  <!-- 行级客户对三角色均可编辑（含生态人员）；
                       2026-10-24（ADR-022）：空值即标红（值驱动，与列头红星同口径）
                       CART-PERF2-20261021（2026-10-21）：客户输入改本地草稿——
                       :model-value 草稿优先（无草稿读已提交值），敲字只写草稿不碰 db.cart 镜像
                       （cartRows 不重算、无整表重建）；标红/placeholder 改读合并口径 customerValue
                       （草稿优先 trim 后），标红跟随输入草稿实时变化 -->
                  <!-- 2026-10-25：用户反馈输入框 hover 提示「太碍事」，删除客户输入框 tooltip（分组规则见顶部提示条） -->
                  <el-input
                    :model-value="customerDraft(row)"
                    size="small"
                    :placeholder="customerValue(row) ? '填写客户' : '必填'"
                    :class="{ 'cart-customer-error': customerValue(row) === '' }"
                    @input="onCustomerInput(row, $event)"
                    @change="onCustomerChange(row)"
                  />
                </div>
                <div class="cell-hint" aria-hidden="true"></div>
              </div>
            </template>
          </el-table-column>
          <!-- FT-20261022-F：表头改居中（原表头右对齐已删），价格数据单元格仍 align="right" -->
          <el-table-column label="销售单价" width="150" align="right" header-align="center">
            <template #default="{ row }">
              <!-- 2026-10-22 视觉优化：价格 14px 加粗 + 11px 副文案（单位 + 库存/上限），
                   原数量列「已达上限」红色小字整合进此副文案（警示色沿用 --danger-color） -->
              <!-- 2026-10-23 修复①：统一单元格结构——价格进主内容区，单位 + 可售/上限副文案进 18px 副提示区一行内 -->
              <div class="cart-cell">
                <div class="cell-main cart-price">
                  <!-- ADR-025（2026-10-21）：包量定价（amount 模式）行单价统一走百万Token 口径（displayUnitPrice，仅展示，
                       权威口径仍为行内销售金额）；unit/遥感行维持 formatMoney 原展示
                       2026-10-23 修复②：去掉模板里多余的「¥ 」前缀——formatMoney 返回值已含 ¥，原写法渲染成「¥ ¥5,100,000.00」 -->
                  <span class="cart-price-value" :class="{ muted: row.isAmount }">{{ row.isAmount ? displayUnitPrice(row.asset) : formatMoney(row.price) }}</span>
                </div>
                <div class="cell-hint cart-price-sub">
                  <!-- ADR-025：amount 行单价已含「/百万Token」后缀，不再重复展示「元/{unit}」副文案 -->
                  <span v-if="!row.isAmount">{{ row.rsItem ? '元/份' : `元/${row.asset.unit || '单位'}` }}</span>
                  <!-- FIX-20261022 / BUG-22：上限口径改「本行可加到的上限」= 可售 − 同产品其他行 qty 合计 -->
                  <span
                    v-if="!row.rsItem && !row.asset.repeatSale"
                    :class="row.cart.qty >= (availOf(row) ?? 0) ? 'cart-sellable-max' : ''"
                  >
                    {{ row.cart.qty >= (availOf(row) ?? 0) ? `已达上限 ${availOf(row)}` : `可售 ${availOf(row)}` }}
                  </span>
                </div>
              </div>
            </template>
          </el-table-column>
          <!-- 2026-10-22 视觉优化：数量列改自定义步进器 [−] 数值 [+]（借鉴 cart-ui-demo.html stepper，
               替代上一批 96px el-input-number 写法）；± 点击走现有 onQtyChange PUT 提交链路，
               上限（min=1 / max=可用上限）与「已达上限」语义保留（上限时 + 号禁用置灰） -->
          <!-- FT-20261022-F：表头显式居中（原缺省靠 align=center 继承，改为显式，避免日后改 align 波及表头） -->
          <el-table-column label="数量" width="120" align="center" header-align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——步进器进主内容区，hint 进 18px 副提示区（无 hint 也渲染空占位） -->
              <div class="cart-cell">
                <div class="cell-main cell-main-center">
                  <div class="cart-stepper">
                    <!-- FIX-20261022 / BUG-25：本行请求在飞期间（qtyBusy）两个按钮一并禁用，
                         避免连点造成并发 PUT / 响应乱序 -->
                    <button
                      type="button"
                      class="step-btn"
                      :disabled="!!row.rsItem || row.cart.qty <= 1 || !!qtyBusy[row.cart.id]"
                      :aria-label="`减少${row.asset.name}数量`"
                      @click="stepQty(row, -1)"
                    >
                      −
                    </button>
                    <!-- 2026-10-27（DIRECT-QTY-INPUT）：数量支持直接键入（原为只读 span，只能点 ±）——
                         原生 input + 本地草稿：敲字不写镜像，失焦/回车提交，非法值静默回退、超上限截断提示；
                         遥感明细行数量恒 1，保留只读展示 -->
                    <input
                      v-if="!row.rsItem"
                      class="step-input"
                      type="text"
                      inputmode="numeric"
                      autocomplete="off"
                      :value="qtyText(row)"
                      :disabled="!!qtyBusy[row.cart.id]"
                      :aria-label="`${row.asset.name}数量，可直接输入`"
                      @input="onQtyInput(row, $event)"
                      @change="onQtyCommit(row, $event)"
                      @keyup.enter="onQtyCommit(row, $event)"
                      @blur="onQtyCommit(row, $event)"
                    />
                    <span v-else class="step-value">{{ row.cart.qty }}</span>
                    <button
                      type="button"
                      class="step-btn"
                      :disabled="!!row.rsItem || !!qtyBusy[row.cart.id] || (qtyMax(row) != null && row.cart.qty >= qtyMax(row)!)"
                      :aria-label="`增加${row.asset.name}数量`"
                      @click="stepQty(row, 1)"
                    >
                      ＋
                    </button>
                  </div>
                </div>
                <!-- ADR-011：遥感明细行数量恒 1（双按钮禁用 + 提示）；「已达上限/可售」信息已移至单价列副文案 -->
                <div class="cell-hint">
                  <span v-if="row.rsItem" class="muted">遥感明细数量固定 1</span>
                  <span v-else-if="row.isAmount" class="muted">{{ formatTokens(row.cart.qty) }} Token</span>
                  <span v-else-if="row.asset.repeatSale" class="muted">不限</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <!-- ADR-018 §3（PRICING-20261020）：所有行（unit/amount/遥感）均可输销售金额（元）；
               2026-10-24（ADR-022）：所有行必填（> 0）——amount 行 = 权威输入，
               unit/遥感行 = 行内成交金额（超参考区间后端 400）；原「选填 / 留空回退」口径废弃
               2026-10-29（ADR-048）精度放宽：支持最多 6 位小数（原仅整数元），后端同步放开
               ADR-039（NO-DISCOUNT-20261022）：本列原并排的快捷换算输入删除，金额输入独占主内容区 -->
          <!-- 2026-10-20 修复：列宽 190→200，保证下方参考区间小字（如「参考区间 5100000~5100000 元/套」）不挤压换行 -->
          <el-table-column label="销售金额（元）" width="200" align="center" header-align="center">
            <!-- 2026-10-24（ADR-022）：列头必填红星（警示红，轻量） -->
            <template #header><span>销售金额（元）<i class="req-star">*</i></span></template>
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——输入框进主内容区，参考区间小字进 18px 副提示区
                   2026-10-24（ADR-022）：缺项（空/0/非法）值驱动标红
                   （复用 .cart-customer-error 同一「必填缺项」样式）；原留空兜底口径小字整体移除 -->
              <div class="cart-cell">
                <!-- ADR-039（NO-DISCOUNT-20261022）：主内容区只剩金额输入——原并排的 68px 窄输入已删除，
                     输入框在本列内自适应占满；40px 主区 + 18px 提示区的行结构/行高不变 -->
                <div class="cell-main">
                  <!-- CART-PERF-20261021（2026-10-21）：金额输入改本地草稿——
                       :model-value 草稿优先（无草稿读已提交值），敲字只写草稿不碰 db.cart 镜像 -->
                  <!-- 2026-10-25：用户反馈输入框 hover 提示「太碍事」，删除金额输入框 tooltip
                       （必填口径见列头红星 + 顶部提示条，参考区间见下方提示行）
                       2026-10-29（ADR-048）：placeholder 改「必填，最多 6 位小数」（原「必填，整数元」） -->
                  <el-input
                    :model-value="amountDraft(row)"
                    placeholder="必填，最多 6 位小数"
                    size="small"
                    class="cart-amount-input"
                    :class="{ 'cart-customer-error': amountInvalid(row) }"
                    @input="onAmountInput(row, $event)"
                    @change="onAmountChange(row)"
                  />
                </div>
                <div class="cell-hint">
                  <!-- ADR-018：产品设了参考区间时展示区间提示（低于下限由后端 400，文案走 showError）
                       ADR-049（2026-10-29）：高于区间上限不拦截（金额可超上限成交）
                       ADR-021（RSITEM-RANGE-20261020）：遥感明细行改读该明细自身区间，普通行仍读产品区间
                       2026-10-20 修复：提示可见性——显式辅助色 #71829A（原 .muted #9aa9bf 过淡）、11px；
                       遥感行单位按 ADR-021 口径展示「份」（父产品 unit 为「份（可售明细）」容器口径，不宜直接展示）
                       ADR-039（NO-DISCOUNT-20261022）：提示行原「快捷换算摘要优先」分支删除，恒走参考区间 -->
                  <span v-if="rowRangeText(row)" class="cart-amount-range">
                    参考区间 {{ rowRangeText(row) }} 元/{{ row.rsItem ? '份' : (row.asset.unit || '单位') }}
                  </span>
                </div>
              </div>
            </template>
          </el-table-column>
          <!-- ADR-020（PRICING-20261020）：服务期限——普通产品行填写（变更即 PUT 提交）；
               遥感明细行按期数售卖（期数即服务时间），不展示期限输入 -->
          <!-- 2026-10-20 修复：列宽 215→300（原列宽下每个日期输入仅约 94px，YYYY-MM-DD 被截断成「2026-10-2…」）；
               两个日期输入各设明确宽度 136px（可完整显示 YYYY-MM-DD + 日历图标），中间留 8px 间距 -->
          <!-- FT-20261022-F：表头显式居中（自定义 #header 内为 el-tooltip 包裹的内联 span，text-align 即可居中） -->
          <el-table-column label="服务期限" width="300" align="center" header-align="center">
            <!-- 2026-10-26（ADR-047）：列头去必填红星（选填），tooltip 说明成对填写口径 + 遥感明细行豁免 -->
            <template #header>
              <el-tooltip content="选填（开始/结束日期需成对填写；遥感明细行按期数售卖，不填期限）" placement="top">
                <span>服务期限</span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——双日期（136px 不变）进主内容区，本列无副提示（空占位）
                   2026-10-24（ADR-022）：placeholder 改「开始日期/结束日期」（修正语义）；
                   2026-10-26（ADR-047）：服务期限改选填——两端都空不标红，只填一端或 start > end 才标红；遥感行仍豁免 -->
              <div class="cart-cell">
                <div class="cell-main cell-main-center">
                  <template v-if="!row.rsItem">
                    <!-- CART-PERF2-20261021（2026-10-21）全页输入链路终审：日期 picker 保留 v-model——
                         日期选择是 change 提交（选中即落值）而非逐字输入，不构成逐字写镜像路径 -->
                    <div class="cart-service-row">
                      <el-date-picker
                        v-model="row.cart.serviceStart"
                        type="date"
                        value-format="YYYY-MM-DD"
                        size="small"
                        placeholder="开始日期（选填）"
                        style="width: 136px;"
                        :class="{ 'cart-service-error': serviceMissing(row) }"
                        @change="onServiceChange(row)"
                      />
                      <el-date-picker
                        v-model="row.cart.serviceEnd"
                        type="date"
                        value-format="YYYY-MM-DD"
                        size="small"
                        placeholder="结束日期（选填）"
                        style="width: 136px;"
                        :class="{ 'cart-service-error': serviceMissing(row) }"
                        @change="onServiceChange(row)"
                      />
                    </div>
                  </template>
                  <!-- 2026-10-22 修复⑤：遥感行「-」在整列宽度内居中（原裸 span 随单元格左对齐出现半列偏移） -->
                  <span v-else class="muted cart-service-dash">-</span>
                </div>
                <div class="cell-hint" aria-hidden="true"></div>
              </div>
            </template>
          </el-table-column>
          <!-- 2026-10-22 微调：小计列宽 130→110（次要列收窄，缓解横向滚动压力，信息完整保留） -->
          <!-- FT-20261022-F：小计列宽 110→150——formatMoney 常规输出 17 字符（¥1,000,000,000.00），
               13px tabular-nums 下内容宽 ≈119px，加 EP .cell 左右 padding 12×2 后需 ≈143px；
               原 110px 可用仅 ≈86px，右对齐时左侧被 .el-table .cell 的 overflow:hidden 裁切（用户截图红框）。
               表头同步改居中（原表头右对齐已删），金额单元格仍 align="right"。
               ADR-048：金额支持最多 6 位小数，极少数超长值（如 ¥1,000.00 后带 6 位小数）可能被裁切，
               常规（≤2 位有效小数）宽度不变，不为此整体加宽表格 -->
          <el-table-column label="小计" width="150" align="right" header-align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——小计进主内容区（formatMoney 已含 ¥，模板不再叠加前缀），副提示区空占位 -->
              <div class="cart-cell">
                <div class="cell-main cell-main-end">
                  <span class="cart-subtotal">{{ formatMoney(row.subtotal) }}</span>
                </div>
                <div class="cell-hint" aria-hidden="true"></div>
              </div>
            </template>
          </el-table-column>
          <!-- 2026-10-23 修复③：× 图标不明显，改回文字按钮「删除」（默认辅助色 #71829A，hover 警示红 + 浅红底，13px）；
               文字已自明，移除 tooltip；fixed="right" 保留（列宽合计约 1416px，常见屏宽下溢出横滚，见表格注释） -->
          <!-- FT-20261022-F：表头显式居中（原缺省靠 align=center 继承） -->
          <el-table-column label="操作" width="76" align="center" header-align="center" fixed="right">
            <template #default="{ row }">
              <!-- 删行对三角色均可用（含生态人员）；2026-10-23 修复①：统一单元格结构，副提示区空占位 -->
              <div class="cart-cell">
                <div class="cell-main cell-main-center">
                  <button type="button" class="cart-remove" @click="removeRow(row)">删除</button>
                </div>
                <div class="cell-hint" aria-hidden="true"></div>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 底部白卡吸附工具条（2026-10-21 视觉对齐平台：白卡 + 描边 + 轻投影，主蓝只用于合计金额与结算按钮；
           sticky 固定内容区底部；「将生成 N 份销售记录」结算预览保留在结算弹窗内）
           2026-10-21（TASK-FE-036）：左侧重排为「一条信息」——件数 → 竖细线分隔 → 应付合计 → 金额，
           两个灰字统一 13px，金额与标签 flex 中线对齐（原 baseline 让小字「掉底」）；分隔线纯装饰 aria-hidden -->
      <div class="cart-checkout">
        <div class="co-left">
          <span class="co-selected">已选 <b>{{ totalQty }}</b> 件产品</span>
          <span class="co-divider" aria-hidden="true"></span>
          <div class="co-total">
            <!-- 2026-10-23 修复②：去掉多余「¥ 」前缀——formatMoney 返回值已含 ¥（同单价列） -->
            <small>应付合计</small>{{ formatMoney(totalAmount) }}
          </div>
        </div>
        <!-- 结算下单对三角色均可用（含生态人员）；前置校验（2026-10-24 ADR-022 / 2026-10-26 ADR-047：客户/金额必填，服务期限选填）仍走 openOrder
             FIX-20261022 / BUG-10：请求期间 loading + 禁用（防重复提交，配合结算弹窗的 requestId 幂等） -->
        <el-button
          class="co-btn"
          type="primary"
          :loading="orderLoading"
          :disabled="!db.cart.length || orderLoading"
          @click="openOrder"
        >
          结算下单 →
        </el-button>
      </div>
    </template>

    <!-- 下单对话框（ADR-020 PRICING-20261020：仅购物车结算确认模式——客户已在行级填写，
         销售金额只读汇总，项目名称由下单人填写（必填），带按（产品, 客户）分组的结算预览） -->
    <SalesOrderDialog
      v-model="orderVisible"
      title="购物车下单"
      :items="orderItems"
      :preview-groups="previewGroups"
      :loading="orderLoading"
      @submit="onOrderSubmit"
    />
  </div>
</template>

<style scoped>
/* ============ 2026-10-22 视觉优化（借鉴 cart-ui-demo.html，不重构布局，色值走系统体系） ============ */

/* 表头 12px 灰字加粗 + 行舒展（min-height ~96px 感，输入组件垂直居中沿用 EP 默认 middle） */
:deep(.el-table th.el-table__cell) {
  padding: 12px 0;
}
:deep(.el-table th .cell) {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
}
/* 2026-10-23 修复①：行高由「单元格 padding 26px + 不定高内容」改为「padding 16px + 统一单元格结构
   （主内容区 40px + 副提示区 18px = 58px）」，行总高 ≈ 90px，任意行任意列输入框水平对齐 */
:deep(.el-table td.el-table__cell) {
  padding: 16px 0;
}

/* 2026-10-23 修复①：统一单元格结构——主内容区固定 40px 垂直居中 + 副提示区固定 18px（允许为空占位），
   保证每行每列总高度一致、跨行同列输入框上下对齐 */
.cart-cell {
  display: flex;
  flex-direction: column;
}
.cell-main {
  height: 40px;
  display: flex;
  align-items: center;
  min-width: 0;
}
.cell-main-center {
  justify-content: center;
}
.cell-main-end {
  justify-content: flex-end;
}
.cell-hint {
  height: 18px;
  font-size: 11px;
  line-height: 18px;
  overflow: hidden;
  white-space: nowrap;
}

/* 操作列固定右侧——强化左侧分隔阴影，横向滚动时与「小计」列内容清晰分隔、避免视觉粘连 */
:deep(.el-table .el-table-fixed-column--right) {
  box-shadow: -8px 0 8px -8px rgba(0, 0, 0, 0.12) inset;
}

/* ADR-042 / REFILL-20261022：未回填明细警告条——复用 .info-bar 骨架，仅换警示橙配色
   （--warning-bg/#fff5e7 + #a86514/--warning-color，与「建设中」同色板，不新增 token） */
.refill-skip-bar {
  background: var(--warning-bg);
  border-color: #f3e0c2;
  color: #a86514;
}
/* 覆盖全局 .info-bar .el-icon 的主蓝图标色（scoped 属性选择器特异性更高） */
.refill-skip-bar .el-icon {
  color: var(--warning-color);
}
.refill-skip-body {
  flex: 1;
  min-width: 0;
}
.refill-skip-title {
  font-weight: 600;
  color: #a86514;
}
.refill-skip-list {
  margin: 4px 0 0;
  padding-left: 18px;
}
/* 逐行完整展示（含「可售不足」的库存数值），长原因换行不省略 */
.refill-skip-list li {
  word-break: break-all;
}
.refill-skip-close {
  flex-shrink: 0;
  border: 1px solid #f3e0c2;
  background: #fff;
  color: #a86514;
  font-size: 12px;
  line-height: 1.6;
  padding: 3px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.refill-skip-close:hover {
  background: var(--warning-bg);
  border-color: var(--warning-color);
}

/* 规则提示条：浅蓝底 + 蓝边框 + 圆角 12px + ⓘ 图标，「加粗标题 + 正文要点」 */
.cart-notice {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: #f0f6ff;
  border: 1px solid #e0ecff;
  border-radius: 12px;
  padding: 13px 16px;
  font-size: 13px;
  color: var(--text-body);
  line-height: 1.7;
}
.cart-notice .el-icon {
  color: var(--primary-color);
  font-size: 16px;
  margin-top: 3px;
  flex-shrink: 0;
}
.cart-notice b {
  display: block;
  color: var(--text-primary);
  margin-bottom: 2px;
}

/* 产品信息列：42px 渐变圆角图标块（浅蓝→浅紫，系统色 --primary-light → --info-purple-bg） */
.cart-product {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.cart-product-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--primary-light), var(--info-purple-bg));
  color: var(--primary-color);
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
}
.cart-product-info {
  min-width: 0;
}
.cart-asset-name {
  /* 2026-10-24 修复：长名称（如「青牛企业大数据分析平台V1.0」）原换行 2 行 + meta 1 行共 3 行，
     超出 40px 主区导致首行被行分隔线盖住——改单行省略，全文由 el-tooltip hover 展示，行高不变 */
  display: block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--primary-color);
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  /* 2026-10-24 修复：显式行高 20px（名称 20 + margin 4 + meta 16 = 40px），
     保证「名称 + meta」两行恰好落在 40px 主区内，不撑高行、不压副提示区 */
  line-height: 20px;
}
.cart-asset-name:hover {
  text-decoration: underline;
}
.cart-asset-sub {
  /* 2026-10-24 修复：meta 行（编号·类型·主体 / 遥感明细名）同样可能过长——
     统一单行省略（与名称行同规格），全文由 el-tooltip hover 展示，保证行高统一 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  line-height: 16px; /* 2026-10-24 修复：与名称行高配合，两行合计 40px 不超出主区 */
  margin-top: 4px;
}

/* 销售单价列：价格 14px 加粗 + 11px 副文案（单位 + 库存/上限）
   2026-10-23 修复①：价格进 40px 主内容区（右对齐），副文案进 18px 副提示区一行内（去掉 margin-top） */
.cart-price {
  justify-content: flex-end;
}
.cart-price-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.cart-price-sub {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  color: var(--text-secondary);
}
.cart-sellable-max {
  color: var(--danger-color);
  font-weight: 600;
}

/* 数量步进器 [−] 数值 [+]：圆角 8px 边框容器、按钮 28px 灰底、数值居中可键入
   2026-10-27（DIRECT-QTY-INPUT）：中区改 input 后由 96px 加宽到 104px（中区 48px），
   保证 6 位数字（如 472）完整显示不被裁切；数量列宽 120px 内仍居中 */
.cart-stepper {
  display: inline-flex;
  align-items: center;
  width: 104px;
  border: 1px solid var(--input-border);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.step-btn {
  width: 28px;
  height: 30px;
  border: 0;
  padding: 0;
  background: #f7f9fc;
  color: var(--text-body);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.step-btn:hover:not(:disabled) {
  color: var(--primary-color);
  background: var(--primary-light);
}
.step-btn:disabled {
  color: #c3cddb;
  cursor: not-allowed;
}
.step-value {
  flex: 1;
  min-width: 40px;
  text-align: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  border-left: 1px solid var(--divider-color);
  border-right: 1px solid var(--divider-color);
  line-height: 30px;
}
/* 2026-10-27（DIRECT-QTY-INPUT）：中间数值区改可键入 input——外观与只读态完全一致
   （无边框/透明底/等宽数字），聚焦时浅蓝底提示「可编辑」，禁用态（请求在飞）灰字 */
.step-input {
  flex: 1;
  min-width: 0;
  width: 40px;
  height: 30px;
  border: 0;
  padding: 0 2px;
  background: transparent;
  text-align: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  border-left: 1px solid var(--divider-color);
  border-right: 1px solid var(--divider-color);
  outline: none;
  transition: background-color 0.15s;
}
.step-input:focus {
  background: var(--primary-light);
  color: var(--primary-color);
}
.step-input:disabled {
  color: #c3cddb;
  background: #f7f9fc;
  cursor: not-allowed;
}
/* 2026-10-23 修复③：× 图标不明显，改回文字按钮「删除」；
   2026-10-24（ADR-022 批次）：默认即系统警示红 + 浅红底（danger-light-9，沿用系统色板），
   hover 加深（danger-dark-2 + danger-light-8）——破坏性操作一眼可见 */
.cart-remove {
  border: 0;
  padding: 4px 10px;
  background: var(--el-color-danger-light-9);
  color: var(--danger-color);
  font-size: 13px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
}
.cart-remove:hover {
  color: var(--el-color-danger-dark-2);
  background: var(--el-color-danger-light-8);
}

/* 2026-10-22 修复④：页面底部留白——结算条 sticky 悬浮（bottom:16px）。
   2026-10-21 复测（白卡工具条）：实测条高 62px（padding 14×2 + 按钮 32 + 1px 描边×2），
   130px = 62 + bottom 偏移 16 + 约 50px 间距；1440/1280/1024 三档视口滚到底
   末行（金额/小计/删除）距条顶仍余 35px，未被遮挡，故维持 130px 不再下调
   TASK-FE-036（2026-10-21）复测：文字排版调整未改变条高（仍 62px，22px 数字行盒 = 按钮 32px 未撑高），
   1440×900 / 1280×800 / 1024×768 滚到底末行距条顶仍均为 35px → padding-bottom 维持 130px */
.cart-page {
  padding-bottom: 130px;
}

/* 白卡吸附工具条（2026-10-21 视觉对齐平台：白卡 + 描边 + 轻投影，主蓝只用于合计金额与结算按钮）
   sticky 固定内容区底部（滚动容器为 el-main），与上方「待售产品」el-card 同一套白卡语言 */
.cart-checkout {
  position: sticky;
  bottom: 16px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 14px 20px;
  box-shadow: 0 6px 20px rgba(26, 46, 78, 0.08);
}
.co-left {
  display: flex;
  align-items: center;
  /* 2026-10-21（TASK-FE-036）：22px → 13px，分隔线两侧间距由 gap 统一控制，两段信息连成一体 */
  gap: 13px;
  flex-wrap: wrap;
}
.co-selected {
  color: var(--text-secondary);
  font-size: 13px;
  /* 2026-10-21（TASK-FE-036）：与 .co-total small 同为 13px / line-height 1.2——
     两者行盒等高，align-items:center 后墨迹重心才对得齐（行高不同会差 2px） */
  line-height: 1.2;
}
/* 2026-10-21（TASK-FE-036）：件数数字轻微跳出灰字（600 主文字色），避免整句糊成一片 */
.co-selected b {
  font-weight: 600;
  color: var(--text-primary);
}
/* 2026-10-21（TASK-FE-036）：件数 / 应付合计之间的竖细线（纯装饰，不参与语义朗读） */
.co-divider {
  width: 1px;
  height: 16px;
  background: var(--divider-color);
  flex: 0 0 auto;
  align-self: center;
}
.co-total {
  display: flex;
  /* 2026-10-21（TASK-FE-036）：baseline → center——原小字被对齐到 22px 数字基线（视觉掉底、重心左低右高） */
  align-items: center;
  /* 2026-10-21（TASK-FE-036）：8px → 6px，标签与金额贴合为一段 */
  gap: 6px;
  font-size: 22px;
  font-weight: 700;
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
}
.co-total small {
  /* 2026-10-21（TASK-FE-036）：字号 12 → 13，与 .co-selected 统一（同行同级信息不再发虚） */
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.2;
}
/* 结算按钮：沿用 type="primary" 实心主蓝（底色/圆角/极轻投影均由 global.css 主按钮统一规则提供，此处不重复声明投影） */
.co-btn {
  /* 2026-10-21（TASK-FE-036）：显式靠右（原靠父级 space-between），与左侧信息区保留 .cart-checkout 的 16px 最小间距 */
  margin-left: auto;
  padding: 10px 22px;
  font-weight: 600;
}
.co-btn:hover,
.co-btn:focus {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}

.cart-subtotal {
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  /* FT-20261022-F：禁止折行——EP .el-table .cell 默认 white-space:normal/overflow-wrap:break-word，
     亿级金额（¥1,000,000,000.00）在窄列下会被断成两行；字号/金额格式均未改 */
  white-space: nowrap;
}
/* ADR-018（PRICING-20261020）：参考区间提示（金额输入框下方副提示区）
   2026-10-20 修复：显式辅助色 #71829A + 11px（原 .muted #9aa9bf 过淡，用户反馈看不到提示）
   2026-10-23 修复①：并入 18px 副提示区（去 margin-top，字号/行高由 .cell-hint 统一控制）
   ADR-039（NO-DISCOUNT-20261022）：本样式现只服务参考区间提示（原同规格的换算摘要已下线） */
.cart-amount-range {
  color: #71829a;
  /* 11px（继承 .cell-hint）单行省略——参考区间文案在 200px 列宽下可能超长，超长即省略不换行 */
  display: block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* ADR-039（NO-DISCOUNT-20261022）：金额输入独占本列主内容区（原「金额 flex:1 + 窄输入 68px」并排已删除）——
   .cell-main 为 flex 容器，输入框 flex:1 自适应占满列宽（200px 列宽扣除单元格内边距后的全部宽度），
   不再需要中间层 flex 行容器，也不留空洞；40px 主区高度不变 */
.cart-amount-input {
  flex: 1;
  min-width: 0;
}
/* 2026-10-24（ADR-022）：原 .cart-amount-fallback（金额留空兜底口径小字）随留空成交口径下线而删除 */
/* 2026-10-22 修复⑤：遥感行服务期限「-」整列宽度内居中（block + text-align，覆盖单元格默认左对齐） */
.cart-service-dash {
  display: block;
  text-align: center;
}
/* ADR-020（PRICING-20261020）：服务期限双日期输入（开始/结束）
   2026-10-20 修复：间距 6→8px，两输入各 136px 明确宽度（配合列宽 300），避免日期截断 */
.cart-service-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 缺项标红（2026-10-24 ADR-022：客户/金额/服务期限统一同一「缺项」样式——
  EP 2.14 独立 el-input / el-date-picker 无 validate 态，按 wrapper box-shadow 描边，警示红同色系；
  原 .cart-amount-empty 置灰样式随「viewer 免填」口径一并废弃）
  2026-10-26（ADR-047）：服务期限改选填后本样式仅用于「只填一端 / start > end」，
  不再用于「空值即缺项」（客户 / 销售金额仍是空值即标红） */
.cart-customer-error :deep(.el-input__wrapper),
.cart-service-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--danger-color) inset;
}
/* 2026-10-24（ADR-022）：列头必填红星（警示红，轻量——仅颜色 + 2px 间距，继承表头 12px 加粗） */
.req-star {
  color: var(--danger-color);
  font-style: normal;
  margin-left: 2px;
}
.th-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
/* 2026-10-22 视觉优化：原浅蓝 .cart-settle 结算条已由 .cart-checkout 白卡吸附工具条取代，旧样式删除 */
.cart-order-summary {
  padding: 10px 14px;
  margin-bottom: 16px;
  background: #f0f6ff;
  border: 1px solid #e0ecff;
  border-radius: 8px;
  font-size: 13px;
  color: var(--text-body);
}
.cart-order-amount {
  color: var(--primary-color);
}
.cart-order-row {
  display: flex;
  gap: 12px;
}
.cart-order-row .el-form-item {
  flex: 1;
}
</style>
