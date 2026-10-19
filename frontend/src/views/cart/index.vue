<script setup lang="ts">
/**
 * 购物车 - 汇总待售产品
 *
 * 展示已加入购物车的产品，支持调整数量 / 移除 / 清空；数量受可用数量约束。
 * ADR-007：允许跨主体混装；每行填写「客户」，结算时按客户分组——
 * 每客户生成一份合同（合同内强制同一主体），全部挂在同一个「进行中」销售项目下并锁定数量。
 * 交付（扣数量 + 交付记录）在项目详情页对合同执行「交付」后触发。
 * 数据预留 userId 维度（当前默认 admin），为后续账号权限管控做准备。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, InfoFilled, Sell, ShoppingCart } from '@element-plus/icons-vue'
import { availableQty, entityShort, formatMoney, formatTokens, isAmountMode, rsItemName, type Asset, type CartItem, type RsItem } from '@/types'
import { checkoutCart, clearCart, db, getAsset, patchCartItem, refresh, removeCartItem, rsItemById, setCartAmount, setCartQty, type OrderFields } from '@/api'
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
      // 遥感明细行合计 = 明细单价（qty 恒 1）；amount 模式行 = 行内合同金额；unit 模式 = 单价×数量
      // ADR-012：生态人员免填金额时，amount 行回退「挂牌价×数量」取整展示（与后端 checkout 回退口径一致）
      const amountFallback = Math.round((asset?.salePrice ?? 0) * c.qty)
      const subtotal = rsItem ? rsItem.price : isAmount ? (c.amount ?? amountFallback) : (asset?.salePrice ?? 0) * c.qty
      return { cart: c, asset, price: rsItem ? rsItem.price : asset?.salePrice ?? 0, subtotal, isAmount, rsItem }
    })
    .filter((r): r is CartRow => !!r.asset),
)

const totalQty = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))
const totalAmount = computed(() => cartRows.value.reduce((s, r) => s + r.subtotal, 0))

// ==================== 行级客户（ADR-007：结算时按客户分组拆合同） ====================
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

/** 失焦提交：正整数校验通过后同步后端（400 时回滚到后端值） */
async function onAmountChange(row: CartRow) {
  const n = row.cart.amount
  if (!n || !Number.isInteger(n) || n <= 0) {
    amountErrors.add(row.cart.id)
    return
  }
  amountErrors.delete(row.cart.id)
  try {
    // 回传该行当前 qty：后端 PUT 对 qty<=0 会删行，金额提交绝不能触发删除
    await setCartAmount(row.cart.id, row.cart.qty, n)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '销售金额更新失败')
    await refresh(true)
  }
}

/** 结算预览：按客户分组（保持行序），每组 = 未来一份合同 */
const previewGroups = computed(() => {
  const groups: { customer: string; qty: number; amount: number }[] = []
  const idx = new Map<string, number>()
  for (const r of cartRows.value) {
    const customer = (r.cart.customer ?? '').trim()
    if (!customer) continue
    const i = idx.get(customer)
    if (i === undefined) {
      idx.set(customer, groups.length)
      groups.push({ customer, qty: r.cart.qty, amount: r.subtotal })
    } else {
      groups[i].qty += r.cart.qty
      groups[i].amount += r.subtotal
    }
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
    ElMessage.error(e instanceof Error ? e.message : '客户修改失败')
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
    ElMessage.error(e instanceof Error ? e.message : '数量更新失败')
    row.cart.qty = avail ?? row.cart.qty
    await refresh(true)
  }
}

async function removeRow(row: CartRow) {
  try {
    await removeCartItem(row.cart.id)
    ElMessage.success('已移除')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '移除失败')
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
    ElMessage.error(e instanceof Error ? e.message : '清空失败')
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
    // ADR-008：包量定价行携带行内合同金额（整数元）；ADR-012：生态人员留空时按挂牌价×数量占位展示
    ...(r.isAmount ? { amount: r.cart.amount ?? Math.round((r.asset?.salePrice ?? 0) * r.cart.qty) } : {}),
    // ADR-011：遥感明细行携带 itemId（数量恒 1，单价 = 明细 price）
    ...(r.rsItem ? { itemId: r.rsItem.id, amount: r.rsItem.price } : {}),
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
    ElMessage.error(e instanceof Error ? e.message : '下单失败')
    await refresh(true)
  } finally {
    orderLoading.value = false
  }
}
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">销售管理 / 购物车</div>
        <h1>购物车</h1>
        <div class="desc">汇总待售产品，可调整数量、移除或清空；为每件产品填写客户后下单，按客户分组生成销售记录并锁定数量，交付在项目详情页对销售记录执行「交付」即生成交付记录。</div>
      </div>
    </div>

    <!-- 空状态 -->
    <el-card v-if="!db.cart.length" shadow="never">
      <el-empty description="购物车为空">
        <el-button type="primary" :icon="ShoppingCart" @click="goAssets">去选择产品</el-button>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- 提示条 -->
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>购物车可混装不同主体的产品，数量受产品「可用数量」约束：暂无可用数量的产品不可加入，超出可用数量的数量会被自动拦截；可重复售卖产品不受限。包量定价（Token）产品按包售卖，需为该行填写销售金额（整数元），结算以销售金额为准。点击「下单」前请为每件产品填写客户：下单后每个产品生成一条销售记录（不同主体的产品可同单混装），销售项目进入「待审核」并锁定数量，商务接手确认（可改价）后生效，再在项目详情页对销售记录执行「交付」即生成交付记录。</span>
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
        <el-table :data="cartRows" border stripe>
          <el-table-column label="产品名称" min-width="220" align="left">
            <template #default="{ row }">
              <!-- ADR-011：遥感明细行两行展示——主行父产品名，次级行明细名（省/市 精度 月份） -->
              <a class="cart-asset-name" @click="goAssetDetail(row.asset.id)">{{ row.asset.name }}</a>
              <div v-if="row.rsItem" class="muted cart-asset-sub">{{ rsItemName(row.rsItem) }}</div>
              <div v-else class="muted cart-asset-sub">{{ row.asset.code }} · {{ row.asset.type }} · {{ entityShort(row.asset.subject) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="客户" width="180" align="left">
            <template #default="{ row }">
              <!-- 行级客户对三角色均可编辑（含生态人员） -->
              <el-tooltip content="结算时按客户分组生成销售记录" placement="top">
                <el-input
                  v-model="row.cart.customer"
                  size="small"
                  :placeholder="customerErrors.has(row.cart.id) ? '必填' : '填写客户'"
                  :class="{ 'cart-customer-error': customerErrors.has(row.cart.id) }"
                  @change="onCustomerChange(row)"
                />
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="销售单价" width="140" align="right" header-align="right">
            <template #default="{ row }">
              <!-- ADR-008：包量定价行单价为参考口径（元/万Token），不参与计价 -->
              <span v-if="row.isAmount" class="muted">¥{{ row.price }}/万Token</span>
              <span v-else>{{ formatMoney(row.price) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="160" align="center">
            <template #default="{ row }">
              <!-- ADR-011：遥感明细行数量恒 1（禁用输入 + tooltip 提示） -->
              <el-tooltip :content="row.rsItem ? '遥感明细数量固定 1' : ''" :disabled="!row.rsItem" placement="top">
                <el-input-number
                  v-model="row.cart.qty"
                  :min="1"
                  :max="row.rsItem ? 1 : qtyMax(row)"
                  :precision="0"
                  controls-position="right"
                  style="width: 110px;"
                  :disabled="!!row.rsItem"
                  @change="onQtyChange(row)"
                />
              </el-tooltip>
              <div v-if="row.rsItem" class="muted cart-qty-hint">遥感明细数量固定 1</div>
              <div v-else-if="row.isAmount" class="muted cart-qty-hint">{{ formatTokens(row.cart.qty) }} Token</div>
              <div v-else-if="row.asset.repeatSale" class="muted cart-qty-hint">不限</div>
              <div v-else-if="row.cart.qty >= (availOf(row.asset) ?? 0)" class="cart-sellable-max">
                已达上限 {{ availOf(row.asset) }}
              </div>
              <div v-else class="muted cart-qty-hint">可售 {{ availOf(row.asset) }}</div>
            </template>
          </el-table-column>
          <!-- ADR-008：包量定价行销售金额（整数元，权威输入）；未填时该行结算禁用 -->
          <el-table-column label="销售金额（元）" width="180" align="center">
            <template #default="{ row }">
              <template v-if="row.isAmount">
                <el-tooltip
                  :content="row.cart.amount
                    ? '包量定价：销售金额（整数元）为权威输入'
                    : isViewer
                      ? '留空按 挂牌价×数量 计价（整数元取整），商务确认订单时可再调整'
                      : '请填写销售金额（整数元）后方可结算'"
                  placement="top"
                >
                  <el-input
                    :model-value="row.cart.amount ?? ''"
                    :placeholder="isViewer ? '整数元（可留空）' : '整数元'"
                    size="small"
                    :class="{
                      'cart-amount-empty': !isViewer && !row.cart.amount,
                      'cart-customer-error': amountErrors.has(row.cart.id),
                    }"
                    @input="onAmountInput(row, $event)"
                    @change="onAmountChange(row)"
                  />
                </el-tooltip>
              </template>
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="小计" width="130" align="right" header-align="right">
            <template #default="{ row }">
              <span class="cart-subtotal">{{ formatMoney(row.subtotal) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ row }">
              <!-- 删行对三角色均可用（含生态人员） -->
              <el-button link type="danger" size="small" @click="removeRow(row)">
                移除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <!-- 底部结算条：唯一结算入口 -->
        <div class="cart-settle">
          <span class="muted cart-settle-qty">合计 {{ totalQty }} 件</span>
          <div class="cart-settle-right">
            <span class="cart-total-value">{{ formatMoney(totalAmount) }}</span>
            <!-- 结算下单对三角色均可用（含生态人员） -->
            <el-button type="primary" :icon="Sell" :disabled="!db.cart.length" @click="openOrder">
              下单
            </el-button>
          </div>
        </div>
      </el-card>
    </template>

    <!-- 下单对话框（共用组件：主体只读 / 无行业 / ¥ 金额；购物车场景带按客户分组的结算预览）
         cartMode：客户已在行级填写 → 对话框无「客户名称」字段，销售金额只读汇总，项目名称默认「采购订单」 -->
    <SalesOrderDialog
      v-model="orderVisible"
      title="购物车下单"
      :items="orderItems"
      :preview-groups="previewGroups"
      :cart-mode="true"
      :loading="orderLoading"
      @submit="onOrderSubmit"
    />
  </div>
</template>

<style scoped>
.cart-asset-name {
  color: var(--primary-color);
  cursor: pointer;
  font-weight: 500;
  font-size: 13px;
}
.cart-asset-name:hover {
  text-decoration: underline;
}
.cart-asset-sub {
  font-size: 12px;
  margin-top: 2px;
}
.cart-subtotal {
  font-weight: 600;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.cart-sellable-max {
  color: var(--danger-color);
  font-weight: 600;
  font-size: 12px;
  margin-top: 4px;
}
.cart-qty-hint {
  font-size: 12px;
  margin-top: 4px;
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
/* 底部结算条：浅蓝底（与 info-bar 同款）+ 两端对齐 */
.cart-settle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  padding: 14px 16px;
  background: #f0f6ff;
  border-radius: 8px;
  flex-wrap: wrap;
}
.cart-settle-qty {
  font-size: 13px;
}
.cart-settle-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cart-total-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--primary-color);
  font-variant-numeric: tabular-nums;
}
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
