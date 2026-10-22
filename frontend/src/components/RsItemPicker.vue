<script setup lang="ts">
/**
 * 遥感数据明细选择弹窗（ADR-011）
 *
 * el-tree 三级：省 → 精度（1.5m）→ 月份（2026-09 · ¥330,000.00），叶子 = 可售明细，
 * checkbox 多选（勾选父级 = 全选其下明细），叶子 label 带单价。
 * 用于：产品列表遥感数据行「加入购物车」（勾选 N 份 = N 行购物车）。
 * 2026-10-20（ADR-020）：原「产品详情登记销售」用途已移除（下单统一走购物车）。
 * 树数据从 db.rsItems 按 parentAsset.id 过滤分组；无明细时 el-empty 空态 + confirm 禁用。
 *
 * RS-STATUS-20261022：已售罄且**不可重复售卖**的明细（`status === 'all_sold' && !repeatSale`）
 * 节点保留展示但**禁选/置灰**（行尾灰字「已售罄」，hover 提示「该期已售出，不可再选」）；
 * `repeatSale === true` 的明细即使已售出也照常可选（后端放行，只计次不扣量）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { RS_ITEM_STATUS, formatMoney, isRsItemSoldOut, priceRangeText, type Asset, type RsItem } from '@/types'
import { db } from '@/api'

interface TreeNode {
  id: string | number
  label: string
  leaf?: boolean
  /** RS-STATUS-20261022：已售罄且单次售卖 → 置灰禁选（el-tree 读该字段禁用节点） */
  disabled?: boolean
  /** 同上（展示用标记，与 disabled 同值；省/精度节点恒 undefined） */
  soldOut?: boolean
  children?: TreeNode[]
}

const props = defineProps<{
  modelValue: boolean
  parentAsset: Asset
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', items: RsItem[]): void
}>()

const treeRef = ref()

/**
 * RS-STATUS-20261022：`props.disabled` 绑定节点的 `disabled` 字段。el-tree 对 disabled 叶子
 * ① 禁用自身勾选框、② 父级全选不连带勾选（内部对 disabled 子节点保留原勾选态）、
 * ③ 点击行文本也不会切换（`!node.disabled` 守卫）——故置灰明细天然不进入选中集合。
 */
const treeProps = { label: 'label', children: 'children', disabled: 'disabled' }

/**
 * 已选明细 id（叶子）——**选中集合的事实来源**。
 * el-tree 在 `data` 引用变化时会重建全部节点（勾选态被清空），故不能只依赖树的内部状态：
 * 这里自行维护集合，数据刷新后按剩余 id 回填勾选（RS-STATUS-20261022 的「剔除已售罄」也基于它）。
 */
const pickedIds = ref<number[]>([])
const checkedCount = computed(() => pickedIds.value.length)

/** 明细树：省 → 精度（1.5m）→ 月份（叶子，带单价） */
const treeData = computed<TreeNode[]>(() => {
  const items = db.rsItems.filter((r) => r.assetId === props.parentAsset.id)
  const byProvince = new Map<string, Map<string, RsItem[]>>()
  for (const it of items) {
    let resMap = byProvince.get(it.province)
    if (!resMap) {
      resMap = new Map()
      byProvince.set(it.province, resMap)
    }
    const key = String(it.resolution)
    const list = resMap.get(key) ?? []
    list.push(it)
    resMap.set(key, list)
  }
  return [...byProvince.entries()].map(([province, resMap]) => ({
    id: `p_${province}`,
    label: province,
    children: [...resMap.entries()].map(([res, list]) => ({
      id: `p_${province}_r_${res}`,
      label: `${res}m`,
      children: list
        .sort((a, b) => a.saleMonth.localeCompare(b.saleMonth))
        .map((it) => {
          // ADR-021（RSITEM-RANGE-20261020）：叶子带单价，有参考区间时顺带展示（无则维持原样）
          const range = priceRangeText(it)
          // RS-STATUS-20261022：已售罄且单次售卖 → 置灰禁选（repeatSale=true 不受影响）
          const soldOut = isRsItemSoldOut(it)
          return {
            id: it.id,
            label: `${it.saleMonth} · ${formatMoney(it.price)}${range ? `（参考区间 ${range}）` : ''}`,
            leaf: true,
            soldOut,
            disabled: soldOut,
          }
        }),
    })),
  }))
})

const hasItems = computed(() => treeData.value.length > 0)

/** 勾选变化：把树上的叶子勾选同步进 `pickedIds`（禁选节点不在其中） */
function onCheck() {
  const nodes: TreeNode[] = treeRef.value?.getCheckedNodes() ?? []
  pickedIds.value = nodes
    .filter((n) => n.leaf && typeof n.id === 'number')
    .map((n) => n.id as number)
}

/**
 * RS-STATUS-20261022：数据刷新后（afterWrite / bootstrap 重建 `db.rsItems` → `treeData` 重新求值）
 * ① 树节点被重建、勾选态清空 → 按 `pickedIds` 回填，保证「只剔除已售罄，其余选中不丢」；
 * ② 已选中但已被标记为已售罄的明细 → 从集合中剔除，并 toast 提示一次。
 */
function syncAfterRefresh() {
  const tree = treeRef.value
  if (!tree) return
  const soldOutIds = new Set(
    db.rsItems.filter((r) => r.assetId === props.parentAsset.id && isRsItemSoldOut(r)).map((r) => r.id),
  )
  const kept = pickedIds.value.filter((id) => !soldOutIds.has(id))
  const removed = pickedIds.value.length - kept.length
  pickedIds.value = kept
  tree.setCheckedKeys(kept)
  if (removed > 0) ElMessage.warning(`${removed} 份已选明细已售罄，已自动取消勾选`)
}

// 等 el-tree 内部按其 data watcher 重建节点后再回填/剔除（本组件 watcher 先于子组件注册，故必须延到 nextTick）
watch(treeData, () => {
  void nextTick(syncAfterRefresh)
})

// 每次打开清空勾选
watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      pickedIds.value = []
      treeRef.value?.setCheckedKeys([])
    }
  },
)

function onConfirm() {
  const ids = pickedIds.value
  const items = db.rsItems.filter((r) => r.assetId === props.parentAsset.id && ids.includes(r.id))
  if (!items.length) return
  emit('confirm', items)
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="`选择可售明细 · ${parentAsset.name}`"
    class="dlg-wide"
    :close-on-click-modal="false"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <!-- 空态：该父产品暂无明细 -->
    <template v-if="!hasItems">
      <el-empty description="该产品暂无可售明细" :image-size="80" />
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>请先在产品详情「可售明细」页签维护 省/精度/月份 明细后再加入购物车。</span>
      </div>
    </template>

    <template v-else>
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>按 省 → 精度 → 月份 勾选可售明细，每份明细独立计价（整数元/份）；<b>已售罄的单次售卖明细已置灰，不可再选</b>（可重复售卖的明细不置灰）。</span>
      </div>
      <el-tree
        ref="treeRef"
        :data="treeData"
        :props="treeProps"
        node-key="id"
        show-checkbox
        default-expand-all
        class="rs-tree"
        @check="onCheck"
      >
        <!-- RS-STATUS-20261022：叶子行尾灰字「已售罄」；置灰节点 hover 提示不可再选（其余节点不挂 tooltip） -->
        <template #default="{ data }">
          <el-tooltip :disabled="!data.soldOut" content="该期已售出，不可再选" placement="right">
            <span class="rs-node" :class="{ 'is-sold-out': data.soldOut }">
              <span class="rs-node-label">{{ data.label }}</span>
              <span v-if="data.soldOut" class="rs-node-soldout">{{ RS_ITEM_STATUS.all_sold.label }}</span>
            </span>
          </el-tooltip>
        </template>
      </el-tree>
    </template>

    <template #footer>
      <span v-if="hasItems" class="picked-count muted">已选 {{ checkedCount }} 份</span>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!hasItems || checkedCount === 0"
        @click="onConfirm"
      >
        确定加入
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.picked-count {
  font-size: 13px;
  margin-right: 12px;
}
.rs-tree {
  min-height: 320px;
  max-height: 55vh;
  overflow-y: auto;
  border: 1px solid var(--divider-color);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 12px;
}
/* RS-STATUS-20261022：叶子节点 = 文案 + 行尾「已售罄」小字（flex 占满剩余宽度，不影响既有树结构与缩进） */
.rs-node {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.rs-node-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 置灰：沿用既有次要文字 token，不新增色值 */
.rs-node.is-sold-out .rs-node-label {
  color: var(--text-secondary);
}
.rs-node-soldout {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--text-secondary);
}
</style>
