<script setup lang="ts">
/**
 * 基础设置 - 资产交付物设置
 *
 * 两级结构：板块大类页签（具身智能/卫星服务/…）→ 大类内资产类型胶囊切换，
 * 每类独立配置标准交付包（交付物名称 / 分类 / 默认必选 / 适用说明）。
 * 资产详情页的「交付物」清单按类型模板初始化。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Box,
  Coin,
  Collection,
  Cpu,
  DataLine,
  InfoFilled,
  Monitor,
  Platform,
  Plus,
  Service,
} from '@element-plus/icons-vue'
import {
  BOARDS,
  DELIVERABLE_CATEGORIES,
  boardLabel,
  type Board,
  type DeliverableCategory,
  type DeliverableTemplateItem,
} from '@/types'
import { CATEGORY_UNITS, db } from '@/api'
import {
  addTemplateItem,
  deleteTemplateItem,
  getDeliverableTemplate,
  updateTemplateItem,
} from '@/api'
import { canWrite, READONLY_TIP } from '@/auth'

/** 资产类型 → 线性图标（仅作识别，不用插画） */
const TYPE_ICONS: Record<string, typeof Cpu> = {
  机器人: Service,
  数采设备: Collection,
  平台软件: Platform,
  卫星Token: Coin,
  卫星数据: DataLine,
  软件: Monitor,
  硬件集群: Box,
  算力服务器: Cpu,
}

/** 一级：板块大类 */
const activeBoard = ref<Board>(CATEGORY_UNITS[0].board)
/** 当前大类下的资产类型（二级） */
const boardTypes = computed(() =>
  CATEGORY_UNITS.filter((cu) => cu.board === activeBoard.value),
)
/** 二级：资产类型细类 */
const activeType = ref(CATEGORY_UNITS[0].type)
watch(activeBoard, () => {
  const first = boardTypes.value[0]
  if (first) activeType.value = first.type
})
const activeCu = computed(
  () => CATEGORY_UNITS.find((c) => c.type === activeType.value) ?? null,
)

// ============================================================
// 新增 / 编辑
// ============================================================
const dialog = reactive({
  visible: false,
  editing: null as DeliverableTemplateItem | null,
  type: '', // 资产类型
  submitting: false,
  form: {
    name: '',
    category: 'install' as DeliverableCategory,
    required: true,
    note: '',
  },
})

function openCreate(type?: string) {
  dialog.editing = null
  dialog.type = type || activeType.value
  dialog.form = { name: '', category: 'install', required: true, note: '' }
  dialog.visible = true
}

function openEdit(type: string, item: DeliverableTemplateItem) {
  dialog.editing = item
  dialog.type = type
  dialog.form = {
    name: item.name,
    category: item.category,
    required: item.required,
    note: item.note,
  }
  dialog.visible = true
}

async function handleSubmit() {
  if (!dialog.form.name.trim()) {
    ElMessage.warning('请输入交付物名称')
    return
  }
  dialog.submitting = true
  try {
    if (dialog.editing) {
      await updateTemplateItem(dialog.type, dialog.editing.id, { ...dialog.form })
      ElMessage.success('更新成功')
    } else {
      await addTemplateItem(dialog.type, { ...dialog.form })
      ElMessage.success('新增成功，新初始化的资产将包含该交付物')
    }
    dialog.visible = false
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    dialog.submitting = false
  }
}

async function handleDelete(type: string, item: DeliverableTemplateItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除【${type}】的交付物「${item.name}」吗？仅影响后续新初始化的资产。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteTemplateItem(type, item.id)
  ElMessage.success('删除成功')
}

function categoryLabel(c: DeliverableCategory) {
  return DELIVERABLE_CATEGORIES[c].label
}

// 保持对 db 的引用以避免 tree-shaking（响应式追踪）
void db
</script>

<template>
  <div class="page-container">
    <!-- 页面头部 -->
    <div class="page-head">
      <div>
        <div class="crumb">基础设置 / 资产交付物设置</div>
        <h1>资产交付物设置</h1>
        <div class="desc">按资产类型独立配置标准交付包；资产按类型模板初始化交付物清单，销售交付时按清单选择版本。</div>
      </div>
      <div class="head-actions">
        <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
          <span>
            <el-button type="primary" :icon="Plus" :disabled="!canWrite" @click="openCreate()">
              新增交付物
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 规则提示条 -->
    <div class="info-bar">
      <el-icon aria-hidden="true"><InfoFilled /></el-icon>
      <span>
        模板修改即时生效，仅影响之后新初始化的资产；已在资产详情中生成清单的交付物需在资产内单独维护。验收类交付物默认「待完善」，完善后可编辑版本并置为「已就绪」。
      </span>
    </div>

    <!-- 一级：板块大类页签 -->
    <el-tabs v-model="activeBoard" class="board-tabs">
      <el-tab-pane
        v-for="b in BOARDS"
        :key="b.key"
        :label="b.label + (b.wip ? '（建设中）' : '')"
        :name="b.key"
      />
    </el-tabs>

    <!-- 二级：大类内资产类型胶囊切换 -->
    <div class="type-chips">
      <button
        v-for="cu in boardTypes"
        :key="cu.type"
        type="button"
        class="type-chip"
        :class="{ active: cu.type === activeType }"
        @click="activeType = cu.type"
      >
        {{ cu.type }}
      </button>
    </div>

    <!-- 当前细类交付物模板 -->
    <div v-if="activeCu" class="detail-card">
      <div class="card-head">
        <div class="th">
          <span class="type-icon" aria-hidden="true">
            <el-icon><component :is="TYPE_ICONS[activeCu.type] ?? Monitor" /></el-icon>
          </span>
          <div>
            <div class="card-title">{{ activeCu.type }} 交付物模板</div>
            <div class="card-desc">{{ boardLabel(activeCu.board) }} · 计量单位：{{ activeCu.unit }}</div>
          </div>
        </div>
        <div class="th-actions">
          <span class="muted" style="font-size: 12px;">
            共 {{ getDeliverableTemplate(activeCu.type).length }} 项
          </span>
          <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="bottom">
            <span>
              <el-button plain size="small" :icon="Plus" :disabled="!canWrite" @click="openCreate(activeCu.type)">
                新增交付物
              </el-button>
            </span>
          </el-tooltip>
        </div>
      </div>

      <el-table :data="getDeliverableTemplate(activeCu.type)">
        <el-table-column prop="name" label="交付物名称" min-width="220">
          <template #default="{ row }">
            <span style="font-weight: 500; color: var(--text-primary);">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认交付" width="110" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.required" size="small" type="primary" effect="plain">必选</el-tag>
            <el-tag v-else size="small" type="info" effect="plain">可选</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="适用说明" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="muted">{{ row.note }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip">
                <el-button link type="primary" size="small" :disabled="!canWrite" @click="openEdit(activeCu.type, row)">
                  编辑
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="READONLY_TIP" :disabled="canWrite" placement="top">
              <span class="op-tip">
                <el-button link type="danger" size="small" :disabled="!canWrite" @click="handleDelete(activeCu.type, row)">
                  删除
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="该类型暂未配置交付物，点击右上「新增交付物」" :image-size="60" />
        </template>
      </el-table>
    </div>

    <!-- 新增 / 编辑对话框 -->
    <el-dialog
      v-model="dialog.visible"
      :title="(dialog.editing ? '编辑' : '新增') + '交付物 · ' + dialog.type"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form label-width="100px">
        <el-form-item v-if="!dialog.editing" label="资产类型">
          <el-input :model-value="dialog.type" disabled />
          <div class="muted dl-tip">针对当前选中的类型新增；其他类型请先在上方切换页签 / 胶囊</div>
        </el-form-item>
        <el-form-item label="交付物名称" required>
          <el-input v-model="dialog.form.name" placeholder="如：软件安装包（离线部署版）" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="dialog.form.category" style="width: 100%;">
            <el-option
              v-for="(c, k) in DELIVERABLE_CATEGORIES"
              :key="k"
              :label="c.label"
              :value="k"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="默认必选">
          <el-switch v-model="dialog.form.required" />
          <span class="muted" style="font-size: 12px; margin-left: 8px;">
            必选项随项目交付默认勾选，不可移除
          </span>
        </el-form-item>
        <el-form-item label="适用说明">
          <el-input
            v-model="dialog.form.note"
            type="textarea"
            :rows="2"
            placeholder="版本 / 格式 / 授权范围等适用说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* 操作列按钮包在 tooltip span 内，间距由 inline-flex 保证（不依赖相邻按钮选择器） */
.op-tip {
  display: inline-flex;
  margin-left: 8px;
}
.op-tip:first-child {
  margin-left: 0;
}

/* 板块大类页签：13px / 40px 高，与详情页一致 */
:deep(.el-tabs__header) {
  margin-bottom: 10px;
}
:deep(.el-tabs__item) {
  font-size: 13px;
  height: 40px;
}
:deep(.board-tabs .el-tabs__item) {
  font-size: 14px;
  font-weight: 500;
}

/* 二级：资产类型胶囊 */
.type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.type-chip {
  padding: 5px 16px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  background: #fff;
  font-size: 13px;
  color: var(--text-body);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.type-chip:hover {
  border-color: var(--el-color-primary-light-5);
  color: var(--primary-color);
}
.type-chip.active {
  background: var(--primary-light);
  border-color: var(--el-color-primary-light-7);
  color: var(--primary-color);
  font-weight: 500;
}

/* 当前细类白卡（与详情页 .detail-card 同规格） */
.detail-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 18px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}
.th {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.type-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--primary-light);
  color: var(--primary-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  flex-shrink: 0;
  margin-top: 2px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.card-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 2px;
}
.th-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.dl-tip {
  font-size: 12px;
  line-height: 18px;
  margin-top: 6px;
}
</style>
