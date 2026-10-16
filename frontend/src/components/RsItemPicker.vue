<script setup lang="ts">
/**
 * 遥感数据明细选择弹窗（ADR-011）
 *
 * el-tree 三级：省 → 精度（1.5m）→ 月份（2026-09 · ¥330,000.00），叶子 = 可售明细，
 * checkbox 多选（勾选父级 = 全选其下明细），叶子 label 带单价。
 * 用于：① 资产列表遥感数据行「加入购物车」（勾选 N 份 = N 行购物车）
 *      ② 资产详情「登记销售」（勾选后进 SalesOrderDialog，订单级客户 + N 行明细）
 * 树数据从 db.rsItems 按 parentAsset.id 过滤分组；无明细时 el-empty 空态 + confirm 禁用。
 */
import { computed, ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { formatMoney, type Asset, type RsItem } from '@/types'
import { db } from '@/api'

interface TreeNode {
  id: string | number
  label: string
  leaf?: boolean
  item?: RsItem
  children?: TreeNode[]
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    parentAsset: Asset
    /** 确认按钮文案（默认「确定加入」；登记销售等用途可传入其它文案） */
    confirmText?: string
  }>(),
  { confirmText: '确定加入' },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'confirm', items: RsItem[]): void
}>()

const treeRef = ref()
const checkedCount = ref(0)

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
        .map((it) => ({
          id: it.id,
          label: `${it.saleMonth} · ${formatMoney(it.price)}`,
          leaf: true,
          item: it,
        })),
    })),
  }))
})

const hasItems = computed(() => treeData.value.length > 0)

/** 勾选变化：统计叶子（明细）勾选数 */
function onCheck() {
  const nodes: TreeNode[] = treeRef.value?.getCheckedNodes() ?? []
  checkedCount.value = nodes.filter((n) => n.leaf).length
}

// 每次打开清空勾选
watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      checkedCount.value = 0
      treeRef.value?.setCheckedKeys([])
    }
  },
)

function onConfirm() {
  const nodes: TreeNode[] = treeRef.value?.getCheckedNodes() ?? []
  const items = nodes.filter((n) => n.leaf && n.item).map((n) => n.item as RsItem)
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
    <!-- 空态：该父资产暂无明细 -->
    <template v-if="!hasItems">
      <el-empty description="该资产暂无可售明细" :image-size="80" />
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>请先在资产详情「可售明细」页签维护 省/精度/月份 明细后再加购或登记销售。</span>
      </div>
    </template>

    <template v-else>
      <div class="info-bar">
        <el-icon aria-hidden="true"><InfoFilled /></el-icon>
        <span>按 省 → 精度 → 月份 勾选可售明细，每份明细独立计价（整数元/份），可重复售卖、只计次不扣量。</span>
      </div>
      <el-tree
        ref="treeRef"
        :data="treeData"
        :props="{ label: 'label', children: 'children' }"
        node-key="id"
        show-checkbox
        default-expand-all
        class="rs-tree"
        @check="onCheck"
      />
    </template>

    <template #footer>
      <span v-if="hasItems" class="picked-count muted">已选 {{ checkedCount }} 份</span>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!hasItems || checkedCount === 0"
        @click="onConfirm"
      >
        {{ confirmText }}
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
</style>

