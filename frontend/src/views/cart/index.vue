<script setup lang="ts">
/**
 * 购物车 - 汇总待售资产
 *
 * 展示已加入购物车的资产，支持调整数量 / 移除 / 清空；数量受可售库存约束。
 * 「下单」= 用购物车资产生成「进行中」销售项目并锁定库存（不自动出库），随后清空购物车；
 * 交付（扣库存 + 出库记录）需在销售项目页将状态置「已完成」后触发。
 * 数据预留 userId 维度（当前默认 admin），为后续账号权限管控做准备。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, InfoFilled, Sell, ShoppingCart } from '@element-plus/icons-vue'
import { availableQty, formatMoney, type Asset, type CartItem } from '@/types'
import { checkoutCart, clearCart, db, getAsset, refresh, removeCartItem, setCartQty, type OrderFields } from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'
import SalesOrderDialog from '@/components/SalesOrderDialog.vue'
import type { OrderItem } from '@/components/SalesOrderDialog.vue'

const router = useRouter()

interface CartRow {
  cart: CartItem
  asset: Asset
  price: number
  subtotal: number
}

const cartRows = computed<CartRow[]>(() =>
  db.cart
    .map((c) => {
      const asset = getAsset(c.assetId)
      return { cart: c, asset, price: asset?.salePrice ?? 0, subtotal: (asset?.salePrice ?? 0) * c.qty }
    })
    .filter((r): r is CartRow => !!r.asset),
)

const totalQty = computed(() => db.cart.reduce((s, c) => s + c.qty, 0))
const totalAmount = computed(() => cartRows.value.reduce((s, r) => s + r.subtotal, 0))
/** 当前购物车主体（购物车强制同主体，取第一条展示全称） */
const cartSubject = computed(() => cartRows.value[0]?.asset.subject ?? '')

onMounted(async () => {
  await refresh()
})

/** 可售库存上限：可重复售卖返回 null（无上限）；否则为可售数量 */
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
  const avail = availOf(row.asset)
  if (avail !== null && row.cart.qty > avail) {
    ElMessage.error(`「${row.asset.name}」可售库存仅 ${avail}${row.asset.unit}，已为你回退`)
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
    await ElMessageBox.confirm('确定清空购物车？将移除全部已添加资产。', '清空购物车', {
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

// ==================== 下单（生成进行中项目并锁定库存，复用 SalesOrderDialog） ====================
const orderVisible = ref(false)
const orderLoading = ref(false)

const orderItems = computed<OrderItem[]>(() =>
  cartRows.value.map((r) => ({ asset: r.asset, qty: r.cart.qty })),
)

function openOrder() {
  if (!db.cart.length) return
  orderVisible.value = true
}

async function onOrderSubmit(payload: { fields: OrderFields; items: { assetId: number; qty: number }[] }) {
  orderLoading.value = true
  try {
    const p = await checkoutCart(payload.fields)
    orderVisible.value = false
    ElMessage.success(`下单成功，已生成销售项目 ${p.code}（进行中）`)
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
        <div class="desc">汇总待售资产，可调整数量、移除或清空；下单后生成进行中销售项目并锁定库存，确认交付后在项目页置「已完成」即出库。</div>
      </div>
    </div>

    <!-- 空状态 -->
    <el-card v-if="!db.cart.length" shadow="never">
      <el-empty description="购物车为空">
        <el-button type="primary" :icon="ShoppingCart" @click="goAssets">去选择资产</el-button>
      </el-empty>
    </el-card>

    <template v-else>
      <!-- 提示条 -->
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>当前购物车主体：{{ cartSubject }}。购物车仅可添加「同一主体」的资产，且数量受资产「可售库存」约束：暂无可售库存的资产不可加入，超出可售库存的数量会被自动拦截；可重复售卖资产不受限。点击「下单」将生成进行中销售项目并锁定库存，确认交付后在项目页置「已完成」即出库。</span>
      </div>

      <!-- 表格卡 -->
      <el-card shadow="never">
        <div class="table-head">
          <span class="t">待售资产</span>
          <div class="th-right">
            <span class="c">共 {{ totalQty }} 件</span>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
              <span>
                <el-button type="danger" plain :icon="Delete" :disabled="!canWrite || !db.cart.length" @click="clearAll">
                  清空购物车
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </div>
        <el-table :data="cartRows" border stripe>
          <el-table-column label="资产名称" min-width="220" align="left">
            <template #default="{ row }">
              <a class="cart-asset-name" @click="goAssetDetail(row.asset.id)">{{ row.asset.name }}</a>
              <div class="muted cart-asset-sub">{{ row.asset.code }} · {{ row.asset.type }}</div>
            </template>
          </el-table-column>
          <el-table-column label="销售单价" width="130" align="right" header-align="right">
            <template #default="{ row }">{{ formatMoney(row.price) }}</template>
          </el-table-column>
          <el-table-column label="数量" width="160" align="center">
            <template #default="{ row }">
              <el-input-number
                v-model="row.cart.qty"
                :min="1"
                :max="qtyMax(row)"
                :precision="0"
                controls-position="right"
                style="width: 110px;"
                @change="onQtyChange(row)"
              />
              <div v-if="row.asset.repeatSale" class="muted cart-qty-hint">不限</div>
              <div v-else-if="row.cart.qty >= (availOf(row.asset) ?? 0)" class="cart-sellable-max">
                已达上限 {{ availOf(row.asset) }}
              </div>
              <div v-else class="muted cart-qty-hint">可售 {{ availOf(row.asset) }}</div>
            </template>
          </el-table-column>
          <el-table-column label="小计" width="130" align="right" header-align="right">
            <template #default="{ row }">
              <span class="cart-subtotal">{{ formatMoney(row.subtotal) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70" align="center">
            <template #default="{ row }">
              <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
                <span>
                  <el-button link type="danger" size="small" :disabled="!canWrite" @click="removeRow(row)">
                    移除
                  </el-button>
                </span>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>
        <!-- 底部结算条：唯一结算入口 -->
        <div class="cart-settle">
          <span class="muted cart-settle-qty">合计 {{ totalQty }} 件</span>
          <div class="cart-settle-right">
            <span class="cart-total-value">{{ formatMoney(totalAmount) }}</span>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span>
                <el-button type="primary" :icon="Sell" :disabled="!canWrite || !db.cart.length" @click="openOrder">
                  下单
                </el-button>
              </span>
            </el-tooltip>
          </div>
        </div>
      </el-card>
    </template>

    <!-- 下单对话框（共用组件：主体只读 / 无行业 / ¥ 金额） -->
    <SalesOrderDialog
      v-model="orderVisible"
      title="购物车下单"
      :items="orderItems"
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
