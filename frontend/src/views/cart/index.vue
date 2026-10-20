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
import { isViewer } from '@/auth'

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
/** 客户校验失败（标红）的购物车行 id 集合 */
const customerErrors = reactive(new Set<number>())

// ==================== 行级合同金额（ADR-008：仅包量定价行，整数元权威输入） ====================
/** 合同金额未填/非法（标红置灰）的购物车行 id 集合 */
const amountErrors = reactive(new Set<number>())

/** 金额输入：仅保留整数位（元口径，禁止小数） */
function onAmountInput(row: CartRow, v: string) {
  const digits = (v ?? '').replace(/[^\d]/g, '')
  row.cart.amount = digits === '' ? undefined : Number(digits)
  if (row.cart.amount) amountErrors.delete(row.cart.id)
}

/** 金额 tooltip 文案：amount 行 = 权威输入（必填/生态可空）；unit/遥感行 = 折扣金额（选填，超区间后端 400） */
function amountTip(row: CartRow): string {
  if (row.isAmount) {
    return row.cart.amount
      ? '包量定价：销售金额（整数元）为权威输入'
      : isViewer.value
        ? '留空按 挂牌价×数量 计价（整数元取整），商务确认订单时可再调整'
        : '请填写销售金额（整数元）后方可结算'
  }
  return '选填：留空按原价成交（挂牌价×数量）；填写即折扣金额（整数元，须落在产品参考区间内）'
}

/** 行参考区间文案（ADR-021，RSITEM-RANGE-20261020）：
 *  遥感明细行（rsItem 非空）读该明细自身区间（不再取父产品容器区间）；普通行读产品区间；未设返回空串不显示 */
function rowRangeText(row: CartRow): string {
  return row.rsItem ? priceRangeText(row.rsItem) : priceRangeText(row.asset)
}

/** 金额输入占位：amount 行沿用原口径；unit/遥感行标注「选填」 */
function amountPlaceholder(row: CartRow): string {
  if (row.isAmount) return isViewer.value ? '整数元（可留空）' : '整数元'
  return '整数元（选填）'
}

/** 金额留空兜底口径提示（2026-10-22 修复⑤：金额下方 11px 小字，一行以内，复用 .muted 辅助色，不新增样式体系）：
 *  - 遥感行留空 = 按明细价结算（qty 恒 1）
 *  - amount 行留空 = 挂牌价×数量（viewer 可留空；商务必填，提示「必填」）
 *  - unit 行留空 = 挂牌价×数量 */
function amountFallbackHint(row: CartRow): string {
  if (row.rsItem) return '留空按明细价结算'
  if (row.isAmount) return isViewer.value ? '留空按 挂牌价×数量 结算' : '必填，整数元'
  return '留空按挂牌价结算'
}

/** 失焦提交（ADR-018 §3，PRICING-20261020）：
 *  - unit/遥感行：选填——留空 = 原价成交（不提交）；填写须为整数元（≥0），超参考区间由后端 400（文案走 showError）
 *  - amount 行：整数元 > 0（商务必填；生态留空走挂牌价回退）
 *  400 时回滚到后端值 */
async function onAmountChange(row: CartRow) {
  const n = row.cart.amount
  if (n === undefined) {
    if (row.isAmount && !isViewer.value) amountErrors.add(row.cart.id)
    else amountErrors.delete(row.cart.id)
    return
  }
  if (!Number.isInteger(n) || (row.isAmount ? n <= 0 : n < 0)) {
    amountErrors.add(row.cart.id)
    return
  }
  amountErrors.delete(row.cart.id)
  try {
    // 回传该行当前 qty：后端 PUT 对 qty<=0 直接 400，且区间校验按新 qty 重算
    await setCartAmount(row.cart.id, row.cart.qty, n)
  } catch (e) {
    showError(e, '销售金额更新失败')
    await refresh(true)
  }
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

/** 行内编辑客户：失焦 / 回车提交；400（同产品同客户已有行）弹后端文案并回滚 */
async function onCustomerChange(row: CartRow) {
  const id = row.cart.id
  const next = (row.cart.customer ?? '').trim()
  if (next) customerErrors.delete(id)
  try {
    await patchCartItem(id, next)
  } catch (e) {
    showError(e, '客户修改失败')
    await refresh(true) // 回滚到后端值
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

async function onQtyChange(row: CartRow) {
  // ADR-011：遥感明细行数量恒 1（输入禁用，双保险拦截）
  if (row.rsItem) return
  const avail = availOf(row.asset)
  if (avail !== null && row.cart.qty > avail) {
    ElMessage.error(`「${row.asset.name}」可用数量仅 ${avail}${row.asset.unit}，已为你回退`)
    row.cart.qty = avail
    return
  }
  try {
    await setCartQty(row.cart.id, row.cart.qty)
  } catch (e) {
    showError(e, '数量更新失败')
    row.cart.qty = avail ?? row.cart.qty
    await refresh(true)
  }
}

/** 步进器 ±1（2026-10-22 视觉优化：替代 el-input-number）：
 *  改数量后复用现有 onQtyChange 的 PUT 提交链路（含上限拦截 / 400 回滚），业务逻辑零变更 */
function stepQty(row: CartRow, delta: number) {
  if (row.rsItem) return // ADR-011：遥感明细行数量恒 1
  const next = row.cart.qty + delta
  if (next < 1) return
  const max = qtyMax(row)
  if (max != null && next > max) return // 已达可用上限，+ 号本就禁用（双保险）
  row.cart.qty = next
  void onQtyChange(row)
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

function openOrder() {
  if (!db.cart.length) return
  // 结算前置校验：任一行为空客户 → 不发请求，标红输入框（validate=error）
  const missing = cartRows.value.filter((r) => !(r.cart.customer ?? '').trim())
  if (missing.length) {
    missing.forEach((r) => customerErrors.add(r.cart.id))
    ElMessage.warning('请为每件产品填写客户')
    return
  }
  // ADR-008：包量定价行未填合同金额（整数元）→ 该行结算禁用，标红提示
  // ADR-012：生态人员免填金额——留空时后端回退「挂牌价×数量」取整，商务审核订单时可再调整；商务保持必填
  const missingAmount = isViewer.value
    ? []
    : cartRows.value.filter(
        (r) => r.isAmount && !(r.cart.amount && Number.isInteger(r.cart.amount) && r.cart.amount > 0),
      )
  if (missingAmount.length) {
    missingAmount.forEach((r) => amountErrors.add(r.cart.id))
    ElMessage.warning('请为包量定价产品填写销售金额（整数元）')
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
          <span>每件产品必填客户；销售金额按整数元填写——包量定价产品必填（生态可留空按挂牌价×数量回退），其余选填、填写即折扣金额（设参考区间时须落在区间内）；数量受产品可用数量约束（可重复售卖不受限），普通产品行可填服务期限。下单后按「产品 + 客户」分组各生成一条销售记录，销售项目进入「待审核」并锁定数量，商务确认（可改价）后生效，再执行「交付」生成交付记录。</span>
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
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——客户列无副提示，渲染空占位区保证行高一致 -->
              <div class="cart-cell">
                <div class="cell-main">
                  <!-- 行级客户对三角色均可编辑（含生态人员） -->
                  <el-tooltip content="结算时按「产品 + 客户」分组生成销售记录" placement="top">
                    <el-input
                      v-model="row.cart.customer"
                      size="small"
                      :placeholder="customerErrors.has(row.cart.id) ? '必填' : '填写客户'"
                      :class="{ 'cart-customer-error': customerErrors.has(row.cart.id) }"
                      @change="onCustomerChange(row)"
                    />
                  </el-tooltip>
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
          <!-- ADR-018 §3（PRICING-20261020）：所有行（unit/amount/遥感）均可输销售金额（整数元）——
               amount 行 = 权威输入（商务必填）；unit/遥感行 = 折扣金额（选填，超参考区间后端 400） -->
          <!-- 2026-10-20 修复：列宽 190→200，保证下方参考区间小字（如「参考区间 5100000~5100000 元/套」）不挤压换行 -->
          <el-table-column label="销售金额（元）" width="200" align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——输入框进主内容区，两行小字合并为 18px 副提示区一行：
                   金额为空时优先显示参考区间，无区间则显示兜底口径提示；已填金额时显示区间（无区间则留空占位） -->
              <div class="cart-cell">
                <div class="cell-main">
                  <el-tooltip :content="amountTip(row)" placement="top">
                    <el-input
                      :model-value="row.cart.amount ?? ''"
                      :placeholder="amountPlaceholder(row)"
                      size="small"
                      :class="{
                        'cart-amount-empty': row.isAmount && !isViewer && !row.cart.amount,
                        'cart-customer-error': amountErrors.has(row.cart.id),
                      }"
                      @input="onAmountInput(row, $event)"
                      @change="onAmountChange(row)"
                    />
                  </el-tooltip>
                </div>
                <div class="cell-hint">
                  <!-- ADR-018：产品设了参考区间时展示区间提示（超区间提交由后端 400，文案走 showError）
                       ADR-021（RSITEM-RANGE-20261020）：遥感明细行改读该明细自身区间，普通行仍读产品区间
                       2026-10-20 修复：提示可见性——显式辅助色 #71829A（原 .muted #9aa9bf 过淡）、11px；
                       遥感行单位按 ADR-021 口径展示「份」（父产品 unit 为「份（可售明细）」容器口径，不宜直接展示）
                       2026-10-22 修复⑤ 兜底口径小字并入此行：仅金额留空且无区间时出现 -->
                  <span v-if="rowRangeText(row)" class="cart-amount-range">
                    参考区间 {{ rowRangeText(row) }} 元/{{ row.rsItem ? '份' : (row.asset.unit || '单位') }}
                  </span>
                  <span v-else-if="!row.cart.amount" class="cart-amount-fallback">{{ amountFallbackHint(row) }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <!-- ADR-020（PRICING-20261020）：服务期限——普通产品行填写（变更即 PUT 提交）；
               遥感明细行按期数售卖（期数即服务时间），不展示期限输入 -->
          <!-- 2026-10-20 修复：列宽 215→300（原列宽下每个日期输入仅约 94px，YYYY-MM-DD 被截断成「2026-10-2…」）；
               两个日期输入各设明确宽度 136px（可完整显示 YYYY-MM-DD + 日历图标），中间留 8px 间距 -->
          <el-table-column label="服务期限" width="300" align="center">
            <template #default="{ row }">
              <!-- 2026-10-23 修复①：统一单元格结构——双日期（136px 不变）进主内容区，本列无副提示（空占位） -->
              <div class="cart-cell">
                <div class="cell-main cell-main-center">
                  <template v-if="!row.rsItem">
                    <div class="cart-service-row">
                      <el-date-picker
                        v-model="row.cart.serviceStart"
                        type="date"
                        value-format="YYYY-MM-DD"
                        size="small"
                        placeholder="开始"
                        style="width: 136px;"
                        @change="onServiceChange(row)"
                      />
                      <el-date-picker
                        v-model="row.cart.serviceEnd"
                        type="date"
                        value-format="YYYY-MM-DD"
                        size="small"
                        placeholder="结束"
                        style="width: 136px;"
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
        <!-- 结算下单对三角色均可用（含生态人员）；前置校验（客户/金额必填）仍走 openOrder -->
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
/* 2026-10-23 修复③：× 图标不明显，改回文字按钮「删除」——默认辅助色 #71829A、13px，
   hover 系统警示红 + 浅红底（沿用系统色板）；原 .cart-qty-hint 样式随数量列 hint 并入 .cell-hint 而删除 */
.cart-remove {
  border: 0;
  padding: 4px 10px;
  background: transparent;
  color: #71829a;
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
}
.cart-remove:hover {
  color: var(--danger-color);
  background: var(--el-color-danger-light-9);
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
   2026-10-23 修复①：并入 18px 副提示区（去 margin-top，字号/行高由 .cell-hint 统一控制） */
.cart-amount-range {
  color: #71829a;
}
/* 2026-10-22 修复⑤：金额留空兜底口径小字——与参考区间提示同款规格（11px + 辅助色 #71829A），不引入新样式体系 */
.cart-amount-fallback {
  color: #71829a;
}
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
/* 空客户校验标红（EP 2.14 独立 el-input 无 validate 态，按 wrapper box-shadow 描边） */
.cart-customer-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--danger-color) inset;
}
/* ADR-008：合同金额未填时置灰（该行结算禁用，tooltip 提示） */
.cart-amount-empty :deep(.el-input__wrapper) {
  opacity: 0.45;
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
