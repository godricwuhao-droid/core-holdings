<script setup lang="ts">
/**
 * 产品统计（ADR-056 §3，纯前端聚合，无后端新端点）
 *
 * 数据源：bootstrap `db.assets` 全量，**按 `asset.subject`（产品所在主体）分组**
 * （空 subject 归「(未设主体)」，不隐藏）。
 * - 主体汇总表：主体 / 产品数 / 总数量(Σquantity) / 剩余量(ΣavailableQty) /
 *   剩余金额(Σ剩余量×salePrice) / 采购总价(Σquantity×salePrice)；
 * - 展开行：单资产明细（编号/名称/数量/剩余量/剩余金额/采购单价/采购总价/销售状态），
 *   供逐条对账 Excel。
 * 口径（采购口径）：单价 = `salePrice`；剩余量 = `availableQty(asset)`（types.ts，
 * 遥感容器用后端 `availableCount`）；空值兜底 0 / `-`；金额 `formatMoney`。
 * 可见性：admin/主管/商务/财务（菜单 `v-if="!isViewer"` + finance 守卫白名单），viewer 不可见。
 */
import { computed } from 'vue'
import { db } from '@/api'
import { availableQty, formatMoney, type Asset } from '@/types'

const NO_SUBJECT = '(未设主体)'

/** 销售状态展示（asset.status：in_stock=可售 / all_sold=已售罄；色板同 RS_ITEM_STATUS 口径，不新增色值） */
const SALE_STATUS: Record<string, { label: string; tag: 'success' | 'info' }> = {
  in_stock: { label: '可售', tag: 'success' },
  all_sold: { label: '已售罄', tag: 'info' },
}
function saleStatus(a: Asset): { label: string; tag: 'success' | 'info' } {
  return SALE_STATUS[a.status] ?? SALE_STATUS.in_stock
}
/** 剩余量（可重复售卖 availableQty 返回 null → 兜底 0） */
function availQty(a: Asset): number {
  return availableQty(a) ?? 0
}
/** 剩余金额 = 剩余量 × 采购单价（采购口径；空值兜底 0） */
function availValue(a: Asset): number {
  return availQty(a) * (a.salePrice ?? 0)
}
/** 采购总价 = 数量 × 采购单价（采购口径；空值兜底 0） */
function purchaseTotal(a: Asset): number {
  return (a.quantity ?? 0) * (a.salePrice ?? 0)
}

interface SubjectRow {
  subject: string
  assets: Asset[]
  count: number
  totalQty: number
  availableQty: number
  availableValue: number
  purchaseTotal: number
}

/** 按主体分组聚合（照抄 getDashboard().boardStats 模式，board → subject）；
 *  排序：主体名中文序，「(未设主体)」恒置末位 */
const rows = computed<SubjectRow[]>(() => {
  const map = new Map<string, Asset[]>()
  for (const a of db.assets) {
    const key = (a.subject || '').trim() || NO_SUBJECT
    const list = map.get(key)
    if (list) list.push(a)
    else map.set(key, [a])
  }
  const out: SubjectRow[] = []
  for (const [subject, list] of map) {
    out.push({
      subject,
      assets: list,
      count: list.length,
      totalQty: list.reduce((s, a) => s + (a.quantity ?? 0), 0),
      availableQty: list.reduce((s, a) => s + availQty(a), 0),
      availableValue: list.reduce((s, a) => s + availValue(a), 0),
      purchaseTotal: list.reduce((s, a) => s + purchaseTotal(a), 0),
    })
  }
  out.sort((x, y) => {
    if (x.subject === NO_SUBJECT) return 1
    if (y.subject === NO_SUBJECT) return -1
    return x.subject.localeCompare(y.subject, 'zh-CN')
  })
  return out
})

// 顶部概览（简洁：主体数 / 产品数 / 总数量 / 剩余量）
const totalAssets = computed(() => db.assets.length)
const totalQty = computed(() => db.assets.reduce((s, a) => s + (a.quantity ?? 0), 0))
const totalAvailable = computed(() => db.assets.reduce((s, a) => s + availQty(a), 0))
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">产品统计</div>
        <h1>产品统计</h1>
        <div class="desc">按产品所在主体汇总数量与金额，用于与 Excel 库存明细对账（采购口径：单价取采购单价）。</div>
      </div>
    </div>

    <!-- 概览信息条 -->
    <div class="info-bar">
      共 {{ rows.length }} 个主体 · {{ totalAssets }} 个产品 · 总数量 {{ totalQty }} · 剩余量 {{ totalAvailable }}
    </div>

    <!-- 主体汇总表（可展开到单资产明细，逐条对账） -->
    <el-card shadow="never">
      <div class="table-head">
        <span class="t">主体汇总</span>
        <span class="c">共 {{ rows.length }} 个主体</span>
      </div>

      <el-table :data="rows" border>
        <!-- 展开明细行：单资产（对齐 Excel 对账列） -->
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="sub-wrap">
              <el-table :data="row.assets" border size="small">
                <el-table-column prop="code" label="产品编号" width="150" align="left">
                  <template #default="{ row: a }"><span class="mono">{{ a.code }}</span></template>
                </el-table-column>
                <el-table-column prop="name" label="产品名称" min-width="200" align="left" show-overflow-tooltip />
                <el-table-column label="数量" width="100" align="center">
                  <template #default="{ row: a }">{{ a.quantity ?? 0 }}</template>
                </el-table-column>
                <el-table-column label="剩余量" width="100" align="center">
                  <template #default="{ row: a }">{{ availQty(a) }}</template>
                </el-table-column>
                <el-table-column label="剩余金额" width="140" align="right" header-align="right">
                  <template #default="{ row: a }">{{ formatMoney(availValue(a)) }}</template>
                </el-table-column>
                <el-table-column label="采购单价" width="130" align="right" header-align="right">
                  <template #default="{ row: a }">
                    <span :class="{ muted: a.salePrice == null }">{{ a.salePrice != null ? formatMoney(a.salePrice) : '-' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="采购总价" width="140" align="right" header-align="right">
                  <template #default="{ row: a }">{{ formatMoney(purchaseTotal(a)) }}</template>
                </el-table-column>
                <el-table-column label="销售状态" width="100" align="center">
                  <template #default="{ row: a }">
                    <el-tag :type="saleStatus(a).tag" size="small" effect="light">{{ saleStatus(a).label }}</el-tag>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="subject" label="主体" min-width="200" align="left" show-overflow-tooltip />
        <el-table-column label="产品数" width="100" align="center">
          <template #default="{ row }">{{ row.count }}</template>
        </el-table-column>
        <el-table-column label="总数量" width="110" align="center">
          <template #default="{ row }">{{ row.totalQty }}</template>
        </el-table-column>
        <el-table-column label="剩余量" width="110" align="center">
          <template #default="{ row }">{{ row.availableQty }}</template>
        </el-table-column>
        <el-table-column label="剩余金额" width="150" align="right" header-align="right">
          <template #default="{ row }">{{ formatMoney(row.availableValue) }}</template>
        </el-table-column>
        <el-table-column label="采购总价" width="160" align="right" header-align="right">
          <template #default="{ row }">{{ formatMoney(row.purchaseTotal) }}</template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无产品数据" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
/* 产品编号 mono 等宽（与项目列表 .proj-code 同字体栈） */
.mono {
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
}
/* 展开明细行内边距（避免贴边） */
.sub-wrap {
  padding: 12px 24px 14px;
}
</style>
