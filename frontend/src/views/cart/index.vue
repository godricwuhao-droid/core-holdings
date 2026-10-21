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
import { Delete, InfoFilled, ShoppingCart } from '@element-plus/icons-vue'
import { availableQty, entityShort, formatMoney, formatTokens, isAmountMode, priceRangeText, rsItemName, type Asset, type CartItem, type RsItem } from '@/types'
import { checkoutCart, clearCart, db, getAsset, patchCartItem, refresh, removeCartItem, rsItemById, setCartAmount, setCartQty, setCartService, showError, type OrderFields } from '@/api'
import SalesOrderDialog from '@/components/SalesOrderDialog.vue'
import type { OrderItem } from '@/components/SalesOrderDialog.vue'

const router = useRouter()

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
}

const cartRows = computed<CartRow[]>(() =>
  db.cart
    .map((c) => {
      const asset = getAsset(c.assetId)
      const rsItem = c.itemId != null ? rsItemById(c.itemId) : undefined
      const isAmount = !!asset && !rsItem && isAmountMode(asset)
      // ADR-018 §3（PRICING-20261020）：行内销售金额（整数元）优先——
      // amount 模式行 = 权威合同金额；unit/遥感明细行 = 折扣金额；
      // 未填 = 原价成交：遥感行 = 明细单价（qty 恒 1）、amount 行回退「挂牌价×数量」取整
      //（与后端 checkout 回退口径一致，ADR-012）、unit 行 = 单价×数量
      const amountFallback = Math.round((asset?.salePrice ?? 0) * c.qty)
      const subtotal = c.amount ?? (rsItem ? rsItem.price : isAmount ? amountFallback : (asset?.salePrice ?? 0) * c.qty)
      return { cart: c, asset, price: rsItem ? rsItem.price : asset?.salePrice ?? 0, subtotal, isAmount, rsItem }
    })
    .filter((r): r is CartRow => !!r.asset),
)

const totalQty = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))
const totalAmount = computed(() => cartRows.value.reduce((s, r) => s + r.subtotal, 0))

// ==================== 行级客户（ADR-007/ADR-016：结算时按（产品, 客户）双键分组拆合同） ====================
// 2026-10-24（ADR-022）：客户/金额/服务期限统一「必填」口径——缺项标红改为值驱动
//（字段为空即标红，与列头红星同口径），不再维护 error id 集合（原 customerErrors/amountErrors 删除）

/** CART-PERF2-20261021（2026-10-21）：客户输入本地草稿（与 amountDrafts 同模式，按行 id 存）——
 *  剩余卡顿根因：原 v-model 每敲一字直接写 row.cart.customer（db.cart 共享镜像）→ cartRows computed 重算
 *  → 新数组 + 新行对象 → el-table :data 身份变化 → 整表重渲染（fixed 列双份 + 全部 tooltip）。
 *  改敲字只写草稿（不碰镜像、cartRows 不重算），失焦/回车经 onCustomerChange 提交（提交时才 trim）；
 *  无草稿时显示由已提交值派生（刷新后仍一致）。
 *  约定：本页逐字输入只写草稿（客户/金额/折扣均草稿化），日期 picker 为 change 提交非逐字（见模板注释）。
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
/** CART-PERF-20261021（2026-10-21）：金额输入本地草稿（与 discountDrafts 同模式，按行 id 存）——
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

/** 金额输入：仅保留整数位（元口径，禁止小数）——CART-PERF-20261021：只写草稿，不再碰 row.cart.amount */
function onAmountInput(row: CartRow, v: string) {
  const digits = (v ?? '').replace(/[^\d]/g, '')
  amountDrafts[row.cart.id] = digits
  // DISCOUNT-20261021（ADR-023）一致性规则：手动编辑销售金额 → 清空该行折扣草稿（显示）
  // 并置 discountRate 为 null（失焦提交 null）——金额是权威值，防止「显示 9 折但金额已被手改」。
  // CART-PERF2-20261021（2026-10-21）：仅当 discountRate 非 null 时才置 null——
  // 已为 null 时不再触碰镜像（避免敲金额首字时多余的镜像写触发一次全表重渲染）
  // 清折扣草稿用 delete（而非置 ''）：rate 置 null 后显示回退本就为 ''，delete 语义更准（无草稿）
  delete discountDrafts[row.cart.id]
  if (row.cart.discountRate != null) row.cart.discountRate = null
}

/** 2026-10-24（ADR-022）：金额缺项（空 / 0 / 非整数）→ 标红，与客户列同一「必填缺项」样式
 *  CART-PERF-20261021：改读「草稿或已提交值」合并口径（amountValue），标红跟随输入草稿实时变化 */
function amountInvalid(row: CartRow): boolean {
  const n = amountValue(row)
  return n === undefined || !Number.isInteger(n) || n <= 0
}

/** 2026-10-24（ADR-022）：服务期限缺项（对应日期为空，或 start > end）→ 标红；
 *  遥感明细行豁免（ADR-020，模板本就不渲染日期输入） */
function serviceMissing(row: CartRow, which: 'start' | 'end'): boolean {
  const s = row.cart.serviceStart
  const e = row.cart.serviceEnd
  const orderBad = !!s && !!e && s > e
  return which === 'start' ? !s || orderBad : !e || orderBad
}

// 2026-10-25：金额输入框 tooltip 文案 amountTip() 随输入框 hover 提示删除（用户反馈「太碍事」）——
// 必填/整数元口径见列头红星 + 顶部提示条，参考区间见金额下方提示行，无信息死角

/** 行参考区间文案（ADR-021，RSITEM-RANGE-20261020）：
 *  遥感明细行（rsItem 非空）读该明细自身区间（不再取父产品容器区间）；普通行读产品区间；未设返回空串不显示 */
function rowRangeText(row: CartRow): string {
  return row.rsItem ? priceRangeText(row.rsItem) : priceRangeText(row.asset)
}

/** 失焦/回车提交（ADR-018 §3，PRICING-20261020；2026-10-24 ADR-022 必填口径；
 *  CART-PERF-20261021 改读草稿）：
 *  - 所有行（unit/amount/遥感）：整数元 > 0 才提交；缺项（空/0/非整数）不提交，保留草稿，输入框值驱动标红
 *  - 合法草稿在 await 前的**同步段**即写入镜像并清草稿——点「结算下单」按钮会先触发本输入框 blur
 *    （浏览器行为：mousedown → blur/change 先于 click），openOrder 校验运行时镜像已是最新值，
 *    天然失焦链路成立，无需额外合并处理（amountInvalid 的草稿合并口径作双保险）
 *  - 超参考区间由后端 400（文案走 showError），400 时回滚到后端值并重置草稿 */
async function onAmountChange(row: CartRow) {
  const n = amountValue(row)
  if (n === undefined || !Number.isInteger(n) || n <= 0) return // 缺项不提交（标红由值驱动，草稿保留）
  row.cart.amount = n
  // CART-PERF2-20261021（2026-10-21）：清草稿用 delete（而非置 ''）——'' 是合法草稿值（用户清空未失焦），
  // delete 后显示回退已提交值（镜像已写入 n）
  delete amountDrafts[row.cart.id]
  try {
    // 回传该行当前 qty：后端 PUT 对 qty<=0 直接 400，且区间校验按新 qty 重算
    // DISCOUNT-20261021（ADR-023，2026-10-21）：amount + discountRate（0-1 小数）一次性提交；
    // 手改金额路径已在 onAmountInput 清空该行折扣率，此处提交 null（后端只存不算）
    await setCartAmount(row.cart.id, row.cart.qty, n, row.cart.discountRate ?? null)
  } catch (e) {
    showError(e, '销售金额更新失败')
    await refresh(true)
    delete amountDrafts[row.cart.id] // 回滚：删草稿 → 显示回退刷新后的镜像（后端值）
  }
}

// ==================== 行级折扣率（DISCOUNT-20261021 / ADR-023，2026-10-21：选填快捷入口，金额仍权威必填） ====================
/** 折扣输入本地草稿（「折」单位，0-10 一位小数，如 9 / 8.5）——
 *  不直接 v-model 到 row.cart.discountRate（0-1 小数）：输入中间态（"8."、"0"）
 *  若回写后端值会被 model 覆盖；草稿按行 id 存，无草稿时由后端值派生（刷新后仍一致）。
 *  CART-PERF2-20261021（2026-10-21）：ref → reactive（同 customerDrafts，见其注释） */
const discountDrafts = reactive<Record<number, string>>({})

// CART-PERF-20261021（2026-10-21）性能自查（修复清单第 4 项）：模板单元格内调用的方法
// （discountDraft/discountInvalid/discountSummary/discountPreviewRate/amountDraft/
// amountInvalid/amountPlaceholder/serviceMissing/rowRangeText 等）均只读
// per-row 状态（row.cart.* 属性 + 草稿 Record 的单个 id 键），不遍历 cartRows/db.cart——
// 敲字只失效本行依赖，cartRows computed（:data）不重算，el-table 无整表重建（无固定列双渲染重建）。
// 遍历 cartRows 的 previewGroups/orderItems 仅用于结算栏/弹窗，不在表格单元格渲染路径上。

/** 折扣率小数 → 输入框文案（0.9→"9"、0.85→"8.5"，一位小数去尾零） */
function rateToText(rate: number): string {
  const t = (rate * 10).toFixed(1)
  return t.endsWith('.0') ? t.slice(0, -2) : t
}

/** 折扣输入框当前显示值（草稿优先，无草稿由后端 discountRate 派生） */
function discountDraft(row: CartRow): string {
  return discountDrafts[row.cart.id] ?? (row.cart.discountRate != null ? rateToText(row.cart.discountRate) : '')
}

/** 折扣输入合法性（值驱动标红）：0 < r ≤ 10，一位小数；空 = 未填不标红 */
function discountInvalid(row: CartRow): boolean {
  const t = discountDraft(row)
  if (t === '') return false
  const n = Number(t)
  return !/^\d+(\.\d)?$/.test(t) || !(n > 0 && n <= 10)
}

// 2026-10-25：折扣输入框 tooltip 文案 discountTip() 随输入框 hover 提示删除（用户反馈「太碍事」）——
// 折扣回填/一致性规则见顶部提示条 + 折扣摘要提示行

/** CART-PERF-20261021（2026-10-21）：折扣有效率（0-1 小数，草稿或已提交值合并口径）——
 *  草稿合法（0<r≤10，本地校验同 onDiscountChange 正则）取草稿；无草稿读已提交值；
 *  草稿非法（0/超10/非数字）返回 null（不显示预览，标红提示用户）。
 *  供摘要实时显示与金额 placeholder 预览共用——敲折扣数字过程中即可见摘要，不等失焦 */
function discountPreviewRate(row: CartRow): number | null {
  const t = discountDraft(row)
  if (t !== '') {
    const n = Number(t)
    if (!/^\d+(\.\d)?$/.test(t) || !(n > 0 && n <= 10)) return null
    return Math.round(n * 10) / 10 / 10 // 归一到一位小数后转 0-1 小数（如 "9" → 0.9）
  }
  return row.cart.discountRate ?? null
}

/** 提示行折扣摘要（DISCOUNT-20261021 / ADR-023：填了折扣后四个数字全可见——
 *  原价单价=单价列、原价总额与折后单价=本摘要、折扣总价=金额输入框值+小计列）
 *  CART-PERF-20261021（2026-10-21）：实时预览（按当前草稿率计算，已提交无草稿用提交值）+
 *  文案压缩（契约 §3：`原价 ¥{单价×qty} · 折后 ¥{折后单价}`，折后单价保留 2 位——
 *  比旧「原价总额 ¥X · 折后单价 ¥Z」短，200px 列宽下截断概率更低） */
function discountSummary(row: CartRow): string {
  const rate = discountPreviewRate(row) ?? 0
  return `原价 ${formatMoney(row.price * row.cart.qty)} · 折后 ¥${(row.price * rate).toFixed(2)}`
}

/** CART-PERF-20261021（2026-10-21）：金额输入 placeholder——实时回填金额预览：
 *  折扣合法（草稿或已提交）且金额为空（无草稿、无已提交值）时显示预计金额（灰色 placeholder 态）。
 *  选 placeholder 方案（而非草稿预填）：placeholder 纯展示、不进 model 值、不触发提交，
 *  失焦链路零重复提交风险（onAmountChange 读草稿，草稿为空即不提交）；
 *  折扣失焦后金额回填为真实值，placeholder 自然让位 */
function amountPlaceholder(row: CartRow): string {
  const rate = discountPreviewRate(row)
  if (rate != null && amountValue(row) === undefined) {
    return `预计 ${Math.round(row.price * row.cart.qty * rate)}`
  }
  return '必填，整数元'
}

/** 折扣输入：仅保留数字与一个小数点（一位小数），中间态由值驱动标红 */
function onDiscountInput(row: CartRow, v: string) {
  let t = (v ?? '').replace(/[^\d.]/g, '')
  const dot = t.indexOf('.')
  if (dot !== -1) {
    // 第二个及以后的小数点丢弃；小数部分截断到一位（如 "8.55"→"8.5"、"10.5" 保留由校验标红）
    t = t.slice(0, dot + 1) + t.slice(dot + 1).replace(/\./g, '').slice(0, 1)
  }
  discountDrafts[row.cart.id] = t
}

/** 折扣失焦/回车：合法（0<r≤10）→ 回填 amount = round(原价单价 × 数量 × r/10)（整数元，
 *  遥感行原价单价 = 明细价，与 row.price 口径一致）并走现有 onAmountChange 提交链路
 *  （一次性提交 amount + discountRate 小数，后端只存）；
 *  非法（0/超10/非数字）→ 输入框标红（值驱动）不回填，金额不受影响；
 *  清空折扣输入 → 折扣率提交 null（金额保持当前值） */
async function onDiscountChange(row: CartRow) {
  const t = discountDraft(row)
  const n = Number(t)
  if (t !== '' && (!/^\d+(\.\d)?$/.test(t) || !(n > 0 && n <= 10))) return
  if (t === '') {
    if (row.cart.discountRate == null) return
    row.cart.discountRate = null
  } else {
    const rate = Math.round(n * 10) / 10 // 归一到一位小数（如 9 → 9.0）
    row.cart.discountRate = rate / 10
    row.cart.amount = Math.round(row.price * row.cart.qty * rate) // 回填金额输入框（整数元）
    // CART-PERF-20261021（2026-10-21）：回填覆盖金额 → 清金额草稿，
    // 防止 onAmountChange 读到用户先前未失焦的旧金额草稿（草稿优先口径）
    // CART-PERF2-20261021（2026-10-21）：清草稿用 delete（显示回退已回填的镜像金额）
    delete amountDrafts[row.cart.id]
  }
  await onAmountChange(row)
}

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
    groups[i].amount += r.subtotal
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

/** 可用数量上限：可重复售卖返回 null（无上限）；否则为可售数量 */
function availOf(a: Asset): number | null {
  return a.repeatSale ? null : (availableQty(a) ?? 0)
}

/** 数量输入上限：可重复不限；否则取可售数量（至少 1，避免 min/max 冲突） */
function qtyMax(row: CartRow): number | undefined {
  return row.asset.repeatSale ? undefined : Math.max(availOf(row.asset) ?? 0, 1)
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

/** 数量变更提交；返回是否成功（DISCOUNT-20261021：stepQty 需据此决定是否按折扣重算金额） */
async function onQtyChange(row: CartRow): Promise<boolean> {
  // ADR-011：遥感明细行数量恒 1（输入禁用，双保险拦截）
  if (row.rsItem) return false
  const avail = availOf(row.asset)
  if (avail !== null && row.cart.qty > avail) {
    ElMessage.error(`「${row.asset.name}」可用数量仅 ${avail}${row.asset.unit}，已为你回退`)
    row.cart.qty = avail
    return false
  }
  try {
    await setCartQty(row.cart.id, row.cart.qty)
    return true
  } catch (e) {
    showError(e, '数量更新失败')
    row.cart.qty = avail ?? row.cart.qty
    await refresh(true)
    return false
  }
}

/** 步进器 ±1（2026-10-22 视觉优化：替代 el-input-number）：
 *  改数量后复用现有 onQtyChange 的 PUT 提交链路（含上限拦截 / 400 回滚），业务逻辑零变更 */
async function stepQty(row: CartRow, delta: number) {
  if (row.rsItem) return // ADR-011：遥感明细行数量恒 1
  const next = row.cart.qty + delta
  if (next < 1) return
  const max = qtyMax(row)
  if (max != null && next > max) return // 已达可用上限，+ 号本就禁用（双保险）
  row.cart.qty = next
  const ok = await onQtyChange(row)
  // DISCOUNT-20261021（ADR-023，2026-10-21）：数量变更后若该行有折扣率 →
  // 按新数量重新回填 amount = round(原价单价 × 新数量 × rate) 并提交（保持折扣语义跟随数量）
  if (ok && row.cart.discountRate != null) {
    const amount = Math.round(row.price * row.cart.qty * row.cart.discountRate)
    row.cart.amount = amount
    delete amountDrafts[row.cart.id] // CART-PERF2-20261021（2026-10-21）：重算覆盖金额 → 删金额草稿（显示回退镜像，delete 而非置 ''）
    try {
      await setCartAmount(row.cart.id, row.cart.qty, amount, row.cart.discountRate)
    } catch (e) {
      showError(e, '销售金额更新失败')
      await refresh(true)
    }
  }
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
    // ADR-018 §3（PRICING-20261020）：已填销售金额的行（包量定价权威值 / unit 与遥感行折扣金额）携带 amount；
    // 未填行不带（对话框按 单价×数量 占位展示，结算以后端 cart_items 持久化值为准）
    ...(r.cart.amount != null ? { amount: r.cart.amount } : {}),
    // ADR-011：遥感明细行携带 itemId（数量恒 1，单价 = 明细 price）
    ...(r.rsItem ? { itemId: r.rsItem.id } : {}),
  })),
)

/** 结算前置校验（2026-10-24 ADR-022：三必填项逐行校验，与后端 checkout 400 同口径）：
 *  客户非空 / 金额整数元 > 0（所有行类型，含遥感行）/ 普通行服务期限两日期齐全且 start ≤ end
 *  （遥感明细行期限豁免，ADR-020）；有缺项不弹结算窗——提示点明缺项类别，
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
  const missingService = cartRows.value.filter(
    (r) => !r.rsItem && (!r.cart.serviceStart || !r.cart.serviceEnd || r.cart.serviceStart > r.cart.serviceEnd),
  )
  const missingCount = missingCustomer.length + missingAmount.length + missingService.length
  if (missingCount) {
    const parts: string[] = []
    if (missingCustomer.length) parts.push('客户')
    if (missingAmount.length) parts.push('销售金额（整数元）')
    if (missingService.length) parts.push('服务期限（遥感明细行豁免）')
    ElMessage.warning(`${missingCount} 行信息未填齐：请填写${parts.join('、')}`)
    return
  }
  orderVisible.value = true
}

async function onOrderSubmit(payload: { fields: OrderFields; items: { assetId: number; qty: number; amount?: number }[] }) {
  orderLoading.value = true
  try {
    // ADR-008：包量定价行合同金额已由行内失焦 PUT /cart/{id} 持久化，结算只传订单字段（后端 CheckoutInput 无 items）
    const p = await checkoutCart({ ...payload.fields })
    orderVisible.value = false
    const cc = p.contractCount ?? previewGroups.value.length
    // ADR-012 修订（2026-10-19）：所有角色下单统一进「待审核」（数量已锁定），商务接手审核（可改价）后生效
    ElMessage.success(
      `下单成功，销售项目 ${p.code} 待审核（数量已锁定 · ${cc} 份销售记录），商务接手确认后生效`,
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
  <!-- 2026-10-22 修复④：加 cart-page 类——底部留白需让开 sticky 深色结算栏（见 scoped 样式） -->
  <div class="page-container cart-page">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">销售管理 / 购物车</div>
        <h1>购物车</h1>
        <div class="desc">汇总待售产品，可调整数量、移除或清空；为每件产品填写客户后下单，按「产品 + 客户」分组生成销售记录并锁定数量，交付在项目详情页对销售记录执行「交付」即生成交付记录。</div>
      </div>
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
          <!-- 2026-10-24（ADR-022）：必填口径——客户/销售金额/服务期限三必填（遥感明细行期限豁免），
               原「生态可留空回退 / 其余选填」表述废弃 -->
          <span>每件产品必填客户、销售金额（整数元 &gt; 0）与服务期限（开始/结束日期，遥感明细行豁免期限）；设参考区间时金额须落在区间内；数量受产品可用数量约束（可重复售卖不受限）。下单后按「产品 + 客户」分组各生成一条销售记录，销售项目进入「待审核」并锁定数量，商务确认（可改价）后生效，再执行「交付」生成交付记录。</span>
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
             操作列仍 fixed="right"——列宽合计约 1360px，1440 屏宽（内容区约 1150px）下会溢出横滚 -->
        <el-table :data="cartRows" stripe>
          <el-table-column label="产品名称" min-width="240" align="left">
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
          <el-table-column label="客户" width="180" align="left">
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
          <el-table-column label="销售单价" width="150" align="right" header-align="right">
            <template #default="{ row }">
              <!-- 2026-10-22 视觉优化：价格 14px 加粗 + 11px 副文案（单位 + 库存/上限），
                   原数量列「已达上限」红色小字整合进此副文案（警示色沿用 --danger-color） -->
              <!-- 2026-10-23 修复①：统一单元格结构——价格进主内容区，单位 + 可售/上限副文案进 18px 副提示区一行内 -->
              <div class="cart-cell">
                <div class="cell-main cart-price">
                  <!-- ADR-017（2026-10-20）：包量定价行单价与普通产品一致（元/份，参考口径），删除「元/万Token」特判
                       2026-10-23 修复②：去掉模板里多余的「¥ 」前缀——formatMoney 返回值已含 ¥，原写法渲染成「¥ ¥5,100,000.00」 -->
                  <span class="cart-price-value" :class="{ muted: row.isAmount }">{{ formatMoney(row.price) }}</span>
                </div>
                <div class="cell-hint cart-price-sub">
                  <span>{{ row.rsItem ? '元/份' : `元/${row.asset.unit || '单位'}` }}</span>
                  <span
                    v-if="!row.rsItem && !row.asset.repeatSale"
                    :class="row.cart.qty >= (availOf(row.asset) ?? 0) ? 'cart-sellable-max' : ''"
                  >
                    {{ row.cart.qty >= (availOf(row.asset) ?? 0) ? `已达上限 ${availOf(row.asset)}` : `可售 ${availOf(row.asset)}` }}
                  </span>
                </div>
              </div>
            </template>
          </el-table-column>
          <!-- 2026-10-22 视觉优化：数量列改自定义步进器 [−] 数值 [+]（借鉴 cart-ui-demo.html stepper，
               替代上一批 96px el-input-number 写法）；± 点击走现有 onQtyChange PUT 提交链路，
               上限（min=1 / max=可用上限）与「已达上限」语义保留（上限时 + 号禁用置灰） -->
          <el-table-column label="数量" width="120" align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——步进器进主内容区，hint 进 18px 副提示区（无 hint 也渲染空占位） -->
              <div class="cart-cell">
                <div class="cell-main cell-main-center">
                  <div class="cart-stepper">
                    <button
                      type="button"
                      class="step-btn"
                      :disabled="!!row.rsItem || row.cart.qty <= 1"
                      :aria-label="`减少${row.asset.name}数量`"
                      @click="stepQty(row, -1)"
                    >
                      −
                    </button>
                    <span class="step-value">{{ row.cart.qty }}</span>
                    <button
                      type="button"
                      class="step-btn"
                      :disabled="!!row.rsItem || (qtyMax(row) != null && row.cart.qty >= qtyMax(row)!)"
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
          <!-- ADR-018 §3（PRICING-20261020）：所有行（unit/amount/遥感）均可输销售金额（整数元）；
               2026-10-24（ADR-022）：所有行必填（整数元 > 0）——amount 行 = 权威输入，
               unit/遥感行 = 折扣金额（超参考区间后端 400）；原「选填 / 留空回退」口径废弃 -->
          <!-- 2026-10-20 修复：列宽 190→200，保证下方参考区间小字（如「参考区间 5100000~5100000 元/套」）不挤压换行 -->
          <el-table-column label="销售金额（元）" width="200" align="center">
            <!-- 2026-10-24（ADR-022）：列头必填红星（警示红，轻量） -->
            <template #header><span>销售金额（元）<i class="req-star">*</i></span></template>
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——输入框进主内容区，参考区间小字进 18px 副提示区
                   2026-10-24（ADR-022）：placeholder 统一「必填，整数元」；缺项（空/0/非整数）值驱动标红
                   （复用 .cart-customer-error 同一「必填缺项」样式）；原留空兜底口径小字整体移除 -->
              <div class="cart-cell">
                <!-- DISCOUNT-20261021（ADR-023，2026-10-21）：折扣输入放主内容区内（与金额输入并排：
                     金额 flex:1 + 折扣固定 68px、同高 size=small、间距 6px），40px 主区 + 18px 提示区
                     统一行结构不变（不加新行、不改行高） -->
                <div class="cell-main">
                  <div class="cart-amount-row">
                    <!-- CART-PERF-20261021（2026-10-21）：金额输入改本地草稿——
                         :model-value 草稿优先（无草稿读已提交值），敲字只写草稿不碰 db.cart 镜像；
                         placeholder 实时回填折扣预计金额（纯展示，无重复提交风险，见 amountPlaceholder 注释） -->
                    <!-- 2026-10-25：用户反馈输入框 hover 提示「太碍事」，删除金额输入框 tooltip
                         （必填/整数元口径见列头红星 + 顶部提示条，参考区间见下方提示行） -->
                    <el-input
                      :model-value="amountDraft(row)"
                      :placeholder="amountPlaceholder(row)"
                      size="small"
                      class="cart-amount-input"
                      :class="{ 'cart-customer-error': amountInvalid(row) }"
                      @input="onAmountInput(row, $event)"
                      @change="onAmountChange(row)"
                    />
                    <!-- 折扣输入（选填，0-10 一位小数）：合法→回填金额走 onAmountChange 提交链路；
                         非法（0/超10/非数字）→ 值驱动标红不回填；手改金额自动清空（onAmountInput）
                         2026-10-25：删除折扣输入框 tooltip（回填规则见顶部提示条 + 折扣摘要提示行） -->
                    <el-input
                      :model-value="discountDraft(row)"
                      placeholder="折扣"
                      size="small"
                      class="cart-discount-input"
                      :class="{ 'cart-customer-error': discountInvalid(row) }"
                      @input="onDiscountInput(row, $event)"
                      @change="onDiscountChange(row)"
                    />
                  </div>
                </div>
                <div class="cell-hint">
                  <!-- DISCOUNT-20261021（ADR-023，2026-10-21）：填了折扣 → 提示行优先显示折扣摘要
                       （原价总额 · 折后单价，11px 辅助色 #71829A，超长省略 + tooltip 全文）；
                       未填折扣 → 维持现状（参考区间或空）
                       2026-10-25：金额输入框 hover tooltip 删除后，填了折扣的行参考区间不再于提示行展示
                       （超区间由后端 400 文案兜底，无信息死角，按用户要求不补新展示） -->
                  <!-- CART-PERF-20261021（2026-10-21）：渲染条件改「草稿合法或已提交值非空」（discountPreviewRate）——
                       折扣输入过程中摘要实时出现，不等失焦落值；截断时 el-tooltip 全文可触发（见 .cart-amount-range 样式） -->
                  <el-tooltip v-if="discountPreviewRate(row) != null" :content="discountSummary(row)" placement="top">
                    <span class="cart-amount-range">{{ discountSummary(row) }}</span>
                  </el-tooltip>
                  <!-- ADR-018：产品设了参考区间时展示区间提示（超区间提交由后端 400，文案走 showError）
                       ADR-021（RSITEM-RANGE-20261020）：遥感明细行改读该明细自身区间，普通行仍读产品区间
                       2026-10-20 修复：提示可见性——显式辅助色 #71829A（原 .muted #9aa9bf 过淡）、11px；
                       遥感行单位按 ADR-021 口径展示「份」（父产品 unit 为「份（可售明细）」容器口径，不宜直接展示） -->
                  <span v-else-if="rowRangeText(row)" class="cart-amount-range">
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
          <el-table-column label="服务期限" width="300" align="center">
            <!-- 2026-10-24（ADR-022）：列头必填红星 + tooltip 说明遥感明细行豁免 -->
            <template #header>
              <el-tooltip content="必填（遥感明细行按期数售卖，豁免期限）" placement="top">
                <span>服务期限<i class="req-star">*</i></span>
              </el-tooltip>
            </template>
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——双日期（136px 不变）进主内容区，本列无副提示（空占位）
                   2026-10-24（ADR-022）：placeholder 改「开始日期/结束日期」（修正语义）；
                   任一日期为空（或 start > end）对应输入框标红（与输入框标红同色系）；遥感行仍豁免 -->
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
                        placeholder="开始日期"
                        style="width: 136px;"
                        :class="{ 'cart-service-error': serviceMissing(row, 'start') }"
                        @change="onServiceChange(row)"
                      />
                      <el-date-picker
                        v-model="row.cart.serviceEnd"
                        type="date"
                        value-format="YYYY-MM-DD"
                        size="small"
                        placeholder="结束日期"
                        style="width: 136px;"
                        :class="{ 'cart-service-error': serviceMissing(row, 'end') }"
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
          <el-table-column label="小计" width="110" align="right" header-align="right">
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
               文字已自明，移除 tooltip；fixed="right" 保留（列宽合计约 1360px，常见屏宽下溢出横滚，见表格注释） -->
          <el-table-column label="操作" width="76" align="center" fixed="right">
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

      <!-- 底部深色结算栏（2026-10-22 视觉优化：借鉴 cart-ui-demo.html checkout 栏——
           sticky 固定内容区底部、深蓝底白字、主蓝按钮；「将生成 N 份销售记录」结算预览保留在结算弹窗内） -->
      <div class="cart-checkout">
        <div class="co-left">
          <span class="co-selected">已选 {{ totalQty }} 件产品</span>
          <div class="co-total">
            <!-- 2026-10-23 修复②：去掉多余「¥ 」前缀——formatMoney 返回值已含 ¥（同单价列） -->
            <small>应付合计</small>{{ formatMoney(totalAmount) }}
          </div>
        </div>
        <!-- 结算下单对三角色均可用（含生态人员）；前置校验（2026-10-24 ADR-022：客户/金额/服务期限三必填）仍走 openOrder -->
        <el-button class="co-btn" type="primary" :disabled="!db.cart.length" @click="openOrder">
          结算下单 →
        </el-button>
      </div>
    </template>

    <!-- 下单对话框（ADR-020 PRICING-20261020：仅购物车结算确认模式——客户已在行级填写，
         销售金额只读汇总，项目名称默认「采购订单」，带按（产品, 客户）分组的结算预览） -->
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

/* 数量步进器 [−] 数值 [+]：圆角 8px 边框容器、按钮 28px 灰底、数值居中只读 */
.cart-stepper {
  display: inline-flex;
  align-items: center;
  width: 96px;
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

/* 2026-10-22 修复④：页面底部留白——结算栏 sticky 悬浮（bottom:16px，实际高度约 72px），
   原 .page-container 底部仅 24px，滚动到底时末行金额/小计被结算栏压住；
   130px = 结算栏高度 + bottom 偏移 16px + 约 40px 间距，保证任意滚动位置末行不被遮挡 */
.cart-page {
  padding-bottom: 130px;
}

/* 底部深色结算栏：sticky 固定内容区底部（滚动容器为 el-main），深蓝底白字 + 主蓝按钮 */
.cart-checkout {
  position: sticky;
  bottom: 16px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: #112d54;
  color: #fff;
  border-radius: 14px;
  padding: 15px 20px;
  box-shadow: 0 14px 35px rgba(16, 35, 63, 0.24);
}
.co-left {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
}
.co-selected {
  color: rgba(255, 255, 255, 0.72);
  font-size: 13px;
}
.co-total {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  font-variant-numeric: tabular-nums;
}
.co-total small {
  font-size: 12px;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.72);
}
.co-btn {
  background: var(--primary-color);
  border-color: var(--primary-color);
  padding: 11px 22px;
  font-weight: 600;
  box-shadow: 0 5px 13px rgba(23, 105, 212, 0.35);
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
}
/* ADR-018（PRICING-20261020）：参考区间提示（金额输入框下方副提示区）
   2026-10-20 修复：显式辅助色 #71829A + 11px（原 .muted #9aa9bf 过淡，用户反馈看不到提示）
   2026-10-23 修复①：并入 18px 副提示区（去 margin-top，字号/行高由 .cell-hint 统一控制）
   DISCOUNT-20261021（ADR-023，2026-10-21）：折扣摘要（原价总额·折后单价）复用本样式同规格 */
.cart-amount-range {
  color: #71829a;
  /* CART-PERF-20261021（2026-10-21）：11px（继承 .cell-hint）单行省略——
     折扣摘要压缩文案在 200px 列宽下仍可能超长，ellipsis 截断时外层 el-tooltip hover 显示全文 */
  display: block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* DISCOUNT-20261021（ADR-023，2026-10-21）：金额 + 折扣并排（主内容区内，40px 行结构不变）——
   金额输入 flex:1（列宽 200 内约 126px，整数元与 placeholder 均不截断），折扣输入固定 68px，间距 6px */
.cart-amount-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}
.cart-amount-input {
  flex: 1;
  min-width: 0;
}
.cart-discount-input {
  width: 68px;
  flex-shrink: 0;
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
/* 必填缺项标红（2026-10-24 ADR-022：客户/金额/服务期限统一同一「必填缺项」样式——
   EP 2.14 独立 el-input / el-date-picker 无 validate 态，按 wrapper box-shadow 描边，警示红同色系；
   原 .cart-amount-empty 置灰样式随「viewer 免填」口径一并废弃） */
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
/* 2026-10-22 视觉优化：原浅蓝 .cart-settle 结算条已由 .cart-checkout 深色结算栏取代，旧样式删除 */
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
