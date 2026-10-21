# 前端变更日志

> 记录 core-holdings 前端（Vue3 + TS + Element Plus + Vite）的页面/组件/接口封装变更。

## 2026-10-21 ｜ 新增：购物车折扣率输入（选填快捷入口）+ 审核页折扣只读列（DISCOUNT-20261021 / ADR-023）

**关联任务**：DISCOUNT-20261021（契约见 docs/api-contracts.md「DISCOUNT-20261021 批次」，决策 docs/adr/ADR-023.md）。销售金额仍是权威必填值（ADR-022 不变），折扣率只是快捷工具。后端并行实现（bootstrap 带出 cartItems/projectItems 的 `discountRate: number|null`，购物车写接口接受该字段，0<rate≤1 否则 400），前端按契约先行。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | ① 类型与 API：`CartItem` / `ProjectItem` 加 `discountRate?: number \| null`（0-1 小数，0.9=九折）；`setCartAmount` 加第 4 参 `discountRate?`（undefined=不传字段、null=清空、小数=提交），PUT /cart/{id} body 携带 | types.ts、api/index.ts | DISCOUNT-20261021（ADR-023） | 契约 §1/§2 |
| 2026-10-21 | 新增 | ② 购物车金额列内联「折扣」输入（cart/index.vue）：布局红线（ADR-023）保持 `.cart-cell > .cell-main(40px) + .cell-hint(18px)` 统一结构——折扣输入放**主内容区内**与金额输入并排（新增 `.cart-amount-row` flex：金额 flex:1 + 折扣固定 68px、同高 size=small、间距 6px，列宽 200 不变、全表总宽零增加），不加新行不改行高；placeholder「折扣」，输入仅保留数字与一位小数（`onDiscountInput` 清洗） | views/cart/index.vue | DISCOUNT-20261021（ADR-023） | 普通/遥感/包量行均可用，原价单价来源 = row.price（明细价/挂牌价/挂牌价，与现有口径一致） |
| 2026-10-21 | 新增 | ③ 折扣交互三规则（cart/index.vue）：a) 合法（0<r≤10）→ `amount = Math.round(row.price × qty × r/10)`（整数元）回填金额输入框，走现有 `onAmountChange` 提交链路（一次性提交 amount + discountRate 小数，后端只存不算）；b) 非法（0/超10/非数字）→ 输入框值驱动标红（复用 `.cart-customer-error` 描边样式）不回填、金额不受影响；c) **手动编辑销售金额 → 该行 discountRate 清空（提交 null）并清空折扣输入框显示**（`onAmountInput` 内执行，ADR-023 一致性规则——金额权威，防止「显示 9 折但金额已被手改」）；另：数量变更（`stepQty`）后若该行有 discountRate → 按新数量重算 amount 并提交（折扣语义跟随数量，`onQtyChange` 改返回成功标记）；清空折扣输入 → discountRate 提交 null（金额保持当前值） | views/cart/index.vue | DISCOUNT-20261021（ADR-023） | 折扣输入用本地草稿 `discountDrafts`（按行 id 存「折」文案）而非直接 v-model 后端小数——避免输入中间态（"8."、"0"）被 model 覆盖；无草稿时由后端值派生（`rateToText` 一位小数去尾零） |
| 2026-10-21 | 新增 | ④ 填了折扣后的展示（四个数字全可见且不重复占位）：原价单价=单价列（不动）；金额列 `.cell-hint` 显示折扣摘要 `原价总额 ¥{price×qty} · 折后单价 ¥{price×r/10 保留2位}`（11px 辅助色 #71829A，复用 `.cart-amount-range`，超长省略 + el-tooltip 全文）；折扣总价=金额输入框值+小计列（不动）；**展示优先级：折扣与参考区间同时存在时提示行优先显示折扣摘要，区间移到金额输入框 hover tooltip 合并展示**（`amountTip` 追加区间文案，注释说明）；未填折扣 → 提示行维持现状（参考区间或空）、折扣输入框留空 | views/cart/index.vue | DISCOUNT-20261021（ADR-023） | 折扣回填金额仍走现有全部校验（整数元>0、参考区间后端 400 文案 showError + 回滚） |
| 2026-10-21 | 新增 | ⑤ 审核页折扣只读列（review.vue）：`ReviewLine` 加 `discountRate`（展开映射 `it.discountRate ?? null`）；明细行在已有「原单价/原金额（只读）+ 可编辑终审价」基础上新增「折扣」只读项——有值显示 `{r×10}折`（`discountRateText`：0.9→"9折"、0.85→"8.5折"，一位小数去尾零），null 显示 `-`；标签带 tooltip「下单时生态人员填写的折扣率（快照，不可改）」（窄列，`.rv-discount-lbl` cursor:help） | views/sales/projects/review.vue | DISCOUNT-20261021（ADR-023） | 契约 §5：review 接口不改——discountRate 只读快照，终审改价仍只写 price/amount，提交 items 不含该字段 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 场景自查：普通行（如 9 折 × ¥5,100,000 × 1 → 回填 ¥4,590,000 并一次性提交 amount+0.9）、遥感行（原价单价=明细价 row.price 口径）、包量行（挂牌价口径）、达上限行（+ 号禁用不触发重算）四类行型折扣输入均可用；手改金额 → 折扣率清 null + 折扣框清空；数量 ±1 后折扣行金额按新数量重算；未填折扣时提示行维持参考区间现状；`.cart-cell/.cell-main(40px)/.cell-hint(18px)` 样式 grep 确认未动（行高不变）。
- 后端接口并行未就绪：discountRate 提交 400/忽略均按契约容错（showError + 回滚），代码按契约写对即可。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-21 ｜ 修改：项目详情「销售记录清单」卡头去掉合同编号（HT-xxx）展示

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修改 | 销售记录清单每个合同卡头部去掉合同编号（HT-xxx）展示（删除 `.contract-code` span 及对应样式），保留客户名、主体徽标与状态标签（如「[蜂云星座] 待审核」+ 右侧「待审核（等商务确认）」）；**基本信息区「项目编号 SP-xxx」与页头「编号 SP-xxx」保留**（用户只要求清单不展示编号）；列表页等其他页面合同编号展示不动；交付/终止确认弹窗与成功提示中的 c.code 文案为操作确认语境，非清单卡头展示，保留 | views/sales/projects/detail.vue | 用户反馈 | grep 确认 detail.vue 内 HT 编号渲染点仅卡头一处，其余区域编号展示自查未受影响 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 自查：销售记录清单卡头无 HT 编号、主体徽标/状态/右侧操作区不变；基本信息区「项目编号 SP-xxx」正常展示。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-21 ｜ 修改：产品抽屉/详情页列表服务端分页（4 处 UI）+ 已售次数改后端 soldCount（PAGE-20261021）

**关联任务**：PAGE-20261021（契约见 docs/api-contracts.md「PAGE-20261021 批次」）。抽屉/详情页的可售明细、数量流水、操作记录此前随 bootstrap 全量下发前端渲染（遥感明细 97 条、日志随时间累积），改服务端分页（单页 10 条，`layout="total, prev, pager, next"` 照 settings/users.vue 先例）。**bootstrap 快照字段（db.rsItems/db.flows/db.logs）保留不动**——RsItemPicker 树、项目页名称查找（create/detail/review）、列表页「N 期」摘要等消费方仍用全量镜像，本次仅改 4 处渲染的数据源。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | ① API 封装 3 个分页函数（参数 page/pageSize 默认 10，返回 `{total, items}`，对齐契约）：`listAssetRsItems`（GET /assets/{id}/rs-items，items = RsItem + 后端派生 `soldCount`）、`listAssetFlows`（GET /assets/{id}/flows，id DESC）、`listAssetLogs`（GET /assets/{id}/logs，id DESC）；types.ts 新增派生类型 `RsItemWithSold extends RsItem { soldCount: number }` | api/index.ts、types.ts | PAGE-20261021 | 读接口，无 afterWrite |
| 2026-10-21 | 修改 | ② 抽屉·可售明细（list.vue）：`dRsItems` computed（db.rsItems 全量过滤）→ `dRs` 分页状态（reactive page/pageSize/total/items/loading）+ `loadDrawerRs()`，watch drawerVisible 打开时重置第 1 页并加载（仅遥感产品发请求）；表格下加 el-pagination；「已售次数」列改读后端 `row.soldCount`；「明细份数」关键信息行改读 `dRs.total`（原 `dRsItems.length` 分页后仅当前页）；加载中 el-table v-loading | views/assets/list.vue | PAGE-20261021 | 空态/loading 分支：`!loading && !items.length` 才显示 el-empty |
| 2026-10-21 | 修改 | ③ 抽屉·最近动态（list.vue）：`dActivities` computed（db 全量合并 slice(0,8)）→ ref + `loadDrawerActivities()`，按契约 §4.3 并行取 flows 第 1 页(10) + logs 第 1 页(10) 后前端合并倒序取前 **10** 条（保持「最近 10 条」语义；不新增合并端点，动态条数多时 1-2 条口径误差为契约已接受 trade-off）；抽屉打开时加载 | views/assets/list.vue | PAGE-20261021 | 展示映射（时间/标题/操作人）与原口径一致 |
| 2026-10-21 | 修改 | ④ 详情·可售明细 tab（detail.vue）：`rsItems` computed（rsItemsOfAsset 全量）→ `rs` 分页状态 + `loadRsItems()`，tab 首次激活时加载（`ensureTabLoaded`，loaded 标记只拉一次）；tab label「（N 条）」与表格数据源改用分页接口 total/items；「已售次数」列改读后端 `row.soldCount`；表格下加 el-pagination；CRUD 后重载（新增跳末页展示新行、删除末页空页回退一页）；watch assetId 切换产品重置分页状态 | views/assets/detail.vue | PAGE-20261021 | 接口 id ASC 稳定排序 |
| 2026-10-21 | 修改 | ⑤ 详情·数量流水 tab（detail.vue）：`flows` computed（assetFlows 全量）→ `flow` 分页状态 + `loadFlows()`，tab 首次激活加载；tab label 与时间线数据源改用分页接口；**类型 radio 过滤保持前端过滤、仅作用于当前页**（后端接口不支持 type 参数，选改动最小口径，card-desc 已注明「按类型过滤仅作用于当前页」）；接口本身 id DESC，删除原 `.reverse()`；时间线下加 el-pagination | views/assets/detail.vue | PAGE-20261021 | — |
| 2026-10-21 | 修改 | ⑥ 详情·操作记录 tab（detail.vue）：`opLogs` computed（db.logs 全量过滤）→ `opLog` 分页状态 + `loadOpLogs()`，tab 首次激活加载；「共 N 条」与 tab label 改用分页接口 total；时间线数据源改用分页 items（id DESC，删除原 `.reverse()`）；时间线下加 el-pagination | views/assets/detail.vue | PAGE-20261021 | — |
| 2026-10-21 | 删除 | ⑦ 前端 soldCount 派生逻辑删除：list.vue `dSoldMap`（遍历 db.contracts 按 itemId 计次）、detail.vue `rsSoldCount()` 函数均删除（grep 确认无残留调用）；抽屉头部「已售次数」总数 `dRsSoldTotal` 因后端仅按行返回 soldCount（当前页）、无聚合值，改为在自身 computed 内由 bootstrap 镜像派生（db.rsItems 取该产品明细 id + db.contracts 按 itemId 计数，口径与原先一致）；detail.vue 移除 `assetFlows`/`rsItemsOfAsset` 导入，list.vue 移除 `assetFlows` 导入（api 层两个导出函数保留，未删公共 API） | views/assets/list.vue、views/assets/detail.vue | PAGE-20261021 | db.rsItems 其他消费方（RsItemPicker、项目页 create/detail/review 名称查找、列表页摘要）零改动 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- curl 契约验证（后端已就绪）：rs-items total=97、id ASC、含 `soldCount` 字段；flows total=12、id DESC；logs total=122、id DESC；asset 不存在 404。
- agent-browser 页面冒烟（127.0.0.1:5173，admin）：卫星板块行点击开抽屉 → 可售明细表 10 行 + 分页「共 97 条」翻页正常、最近动态 10 条（新接口）；详情页「可售明细（97）」tab 首次激活加载 + 分页、「数量流水（12）」含「按类型过滤仅作用于当前页」小字、「操作记录（122）」时间线 + 分页均正常。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-24 ｜ 修改：购物车结算必填口径（客户/金额/服务期限）+ 删除按钮默认红色（ADR-022）

**关联任务**：REQUIRED-20261024（契约见 docs/api-contracts.md「REQUIRED-20261024 批次」，决策 ADR-022）。后端并行实现 checkout 必填 400，前端按契约先行。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-24 | 修改 | ① 必填口径（ADR-022：客户/销售金额/服务期限全部必填，遥感明细行期限豁免）：金额 placeholder 统一「必填，整数元」（viewer/商务旧口径文案废弃）；`amountFallbackHint` 兜底提示（留空按挂牌价/明细价结算）与 `.cart-amount-fallback` 样式整体移除；缺项标红改为**值驱动**——客户空值、金额空/0/非整数（新增 `amountInvalid`）、普通行任一日期为空或 start>end（新增 `serviceMissing`）即红边框，三者统一同一「必填缺项」样式（`.cart-customer-error` / `.cart-service-error` 共用 `--danger-color` inset 描边），原 `customerErrors`/`amountErrors` 集合与 `.cart-amount-empty` 置灰样式删除；`onAmountChange` 改所有行整数元 >0 才提交（viewer 免填/选填分支废弃，`isViewer` 导入随之移除）；`openOrder` 结算前置校验改三必填项逐行校验（客户/金额/普通行两日期齐全且 start≤end，遥感行期限豁免），缺项不弹结算窗并提示「N 行信息未填齐：请填写客户、销售金额（整数元）、服务期限（遥感明细行豁免）」（按实际缺项类别拼接） | views/cart/index.vue | REQUIRED-20261024（ADR-022） | 提交链路（PUT /cart/{id} 回滚口径）、结算预览 previewGroups、下单 onOrderSubmit 函数体零改动 |
| 2026-10-24 | 修改 | ② 服务期限 placeholder 语义修正：「开始/结束」→「开始日期/结束日期」；遥感行维持「-」占位豁免不标红 | views/cart/index.vue | REQUIRED-20261024（ADR-022） | — |
| 2026-10-24 | 修改 | ③ 列头必填红星 + 文案口径：客户/销售金额（元）/服务期限三列头加警示红 `*`（新增 `.req-star`，轻量——仅颜色 + 2px 间距），服务期限红星带 tooltip「必填（遥感明细行按期数售卖，豁免期限）」；notice 条与金额 tooltip（`amountTip`）「选填/留空回退」表述同步改为必填口径 | views/cart/index.vue | REQUIRED-20261024（ADR-022） | grep「选填」「留空按」代码零残留（仅注释说明保留） |
| 2026-10-24 | 修改 | ④ 删除按钮默认红色：`.cart-remove` 由默认灰 #71829A（hover 才红）改为默认系统警示红 `--danger-color` + 浅红底 `--el-color-danger-light-9`，hover 加深（`--el-color-danger-dark-2` + `--el-color-danger-light-8`），破坏性操作一眼可见 | views/cart/index.vue | REQUIRED-20261024（ADR-022） | 色值全部走系统色板变量；删行仍走 removeRow，三角色可用口径不变 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 场景自查：普通产品行（客户/金额/两日期空值即标红，填齐解除）、遥感明细行（金额必填标红、服务期限「-」豁免不校验不标红、数量恒 1）、包量行（金额必填权威口径）、缺项结算拦截（提示点明缺项类别 + 缺项输入框保持标红可定位、不弹结算窗）、空购物车（el-empty 分支，结算按钮禁用）均正常。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-24 ｜ 修复：购物车产品列长名称换行被遮挡（单行省略 + tooltip，行高不变）

**关联任务**：用户截图反馈——2026-10-23 行等高改造后，产品名较长（如「青牛企业大数据分析平台V1.0」）换行成 2 行 + meta 行 1 行共 3 行，超出 40px 主区，名称首行被行分隔线/单元格边界盖住（截图中仅「V1.0」与 meta 行可见）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-24 | 修复 | 产品列名称/meta 单行省略 + tooltip：`.cart-asset-name` 改 `display:block + nowrap + ellipsis`（列宽内单行，超出显示 …），`.cart-asset-sub`（编号·类型·主体 / 遥感明细名）同样式同规格；两者各包 `el-tooltip`（hover 显示全文，与本页客户/金额列 tooltip 同款做法）；名称 `line-height:20px` + meta `line-height:16px` + margin 4px = 40px，两行恰好落在主区内，图标块 + 名称 + meta 整体仍由 `.cell-main` 垂直居中，所有行 ~90px 等高不变；自查其余 7 列（客户/金额/服务期限为固定高输入框、单价/小计单行文本、步进器 30px、删除按钮）均无超 40px 主区被裁切隐患，无需改动 | views/cart/index.vue | 用户截图反馈 UI 修复 | 仅模板结构与样式改动，goAssetDetail 跳转/结算分组/校验/提交链路零改动；未动 backend/ |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 场景自查：长名称产品行（名称单行 + …、hover 显示全名）、普通短名称行、遥感明细行（父产品名 + 明细名两行均单行省略）行高与其他行一致，无文字被行分隔线遮挡。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-23 ｜ 修复：购物车页 3 项 UI 问题（行内错位/¥ 重复/删除按钮）

**关联任务**：用户反馈购物车页 3 个 UI 问题（①各列副提示文案高度不一导致行内输入框错位、②单价渲染成「¥ ¥5,100,000.00」、③操作列 × 图标不明显）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-23 | 修复 | ① 行内错位：为表格定义统一单元格结构 `.cart-cell > .cell-main（40px 固定高，flex 垂直居中）+ .cell-hint（18px 固定高，允许为空）`，全部 8 列（产品/客户/单价/数量/金额/服务期限/小计/操作）模板统一套此结构——无 hint 的列也渲染空副提示区占位；金额列两行小字合并为一行（区间优先，兜底口径提示仅在金额留空且无区间时出现，已填金额时显示区间或留空）；单价副文案（单位 + 可售/上限）、数量 hint（遥感固定 1/Token/不限）均收进 18px 副提示区一行内；单元格 padding 26px→16px，行总高 ≈ 90px | views/cart/index.vue | 用户反馈 UI 修复 | 任意行任意列输入框同一水平线、所有行等高；仅模板结构与样式改动，提交链路/校验/预览函数体零改动 |
| 2026-10-23 | 修复 | ② ¥ 符号重复：`formatMoney` 返回值已含 ¥（Intl.NumberFormat CNY），去掉模板中叠加的「¥ 」前缀——单价列 `cart-price-value`、结算栏「应付合计」两处（全页 formatMoney 调用点已逐一排查，小计列本无叠加前缀） | views/cart/index.vue | 用户反馈 UI 修复 | 全页无「¥ ¥」重复 |
| 2026-10-23 | 修复 | ③ 操作列 × 图标改回文字按钮「删除」：默认辅助色 #71829A、13px，hover 系统警示红 + 浅红底（--el-color-danger-light-9，沿用系统色板）；移除 tooltip（文字自明）；`fixed="right"` 保留，列宽 70→76px；`Close` 图标导入与旧图标按钮样式同步清理 | views/cart/index.vue | 用户反馈 UI 修复 | 删行仍走 removeRow，三角色可用口径不变 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 场景自查：普通产品行（单价副文案「元/套 + 可售 N」、金额兜底「留空按挂牌价结算」）、遥感明细行（「元/份」+「遥感明细数量固定 1」+ 服务期限「-」+ 金额兜底「留空按明细价结算」）、包量行（「N Token」+ 金额必填口径）、达上限行（单价副文案红色「已达上限 N」+ 步进器 + 号禁用）、空购物车（el-empty 分支）五类行高一致、各列输入框水平对齐，无「¥ ¥」重复。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-22 ｜ 修复：购物车页 4 项 UI 问题（提示归属/单位/末行遮挡/辅助提示）

**关联任务**：用户截图反馈购物车页 4 个 UI 问题（①提示串味+浮层遮挡、②遥感行单价单位「元/套」、④结算栏遮挡末行、⑤服务期限「-」偏移 + 金额兜底无暗示）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修复 | ① 提示串味+浮层遮挡：排查结论——当前代码（HEAD 56ac027）中金额 tooltip 为单一 `amountTip(row)` 字符串（hover 触发，内容仅金额规则），「数量固定 1」在数量列行内小字，「将生成 N 份销售记录」结算预览仅存在于 SalesOrderDialog 内，全仓检索确认不存在三段文案拼接/行内预览渲染（截图应来自旧构建），无代码改动 | views/cart/index.vue | 用户反馈 UI 修复 | 各提示已各归其位，互不混拼；tooltip 默认不遮挡行内容 |
| 2026-10-22 | 修复 | ② 遥感行单价单位：排查结论——单价列副文案当前已为 `row.rsItem ? '元/份' : 元/${产品unit}`（2026-10-22 视觉优化批次已修，见下方第 ④ 条），遥感行固定「元/份」、普通行维持产品 unit，无代码改动 | views/cart/index.vue | 用户反馈 UI 修复 | 与 RSITEM-RANGE 批次 rowRangeText 遥感行「份」口径一致 |
| 2026-10-22 | 修复 | ④ 结算栏遮挡末行：购物车页根节点加 `cart-page` 类，scoped 样式 `padding-bottom: 130px`（结算栏实际高度约 72px + sticky bottom 16px + 约 40px 间距；原 .page-container 底部仅 24px，滚动到底时末行金额/小计被深色结算栏压住） | views/cart/index.vue | 用户反馈 UI 修复 | 空购物车分支无结算栏，额外留白无副作用 |
| 2026-10-22 | 修复 | ⑤ 两项次要：a) 遥感行服务期限「-」由裸 span 加 `cart-service-dash`（display:block + text-align:center）整列宽度内居中，消除半列偏移；b) 金额输入框下方新增兜底口径小字（新增 `amountFallbackHint`：遥感行「留空按明细价结算」/ unit 行「留空按挂牌价结算」/ amount 行 viewer「留空按 挂牌价×数量 结算」、商务「必填，整数元」），11px + 辅助色 #71829A，与参考区间提示同款规格，不引入新样式体系 | views/cart/index.vue | 用户反馈 UI 修复 | 仅展示层新增，结算分组/校验/预览/提交链路函数体零改动 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 场景自查：普通产品行（金额小字「留空按挂牌价结算」+ 单位「元/套」+ 可售/上限副文案）、遥感行（「元/份」+「留空按明细价结算」+ 数量固定 1 + 服务期限「-」居中）、达上限行（+ 号禁用 + 红色「已达上限」）、空购物车（el-empty 分支，notice/结算栏不渲染）四类均正常，行内 tooltip 无混拼、默认不遮挡。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-22 ｜ 修改：购物车页视觉优化（借鉴 cart-ui-demo.html，不重构布局）

**关联任务**：用户对购物车页视觉不满意，提供参考 demo（`cart-ui-demo.html`）；**仅借鉴其视觉/交互优点，不照抄**——保留现有 el-table 布局与全部业务逻辑（结算分组/预览、金额校验提交、服务期限提交、viewer 免填兜底、参考区间提示、清空购物车均未改动），色值全部走系统体系（禁用 demo 的 #2a81ff/#db4d58 等非系统色）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | ① 数量列改自定义步进器 `[−] 数值 [+]`（96px 圆角 8px 边框容器、28px 灰底 #F7F9FC 按钮、数值居中只读），替代上一批 96px el-input-number 写法；± 点击经新增 `stepQty`（±1 边界拦截）复用现有 `onQtyChange` PUT 提交链路（上限拦截/400 回滚口径不变）；min=1 / max=可用上限保留，达上限时 + 号禁用置灰；遥感行双按钮禁用 + 「数量固定 1」提示保留 | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 业务逻辑零变更 |
| 2026-10-22 | 修改 | ② 底部结算区替换为深色结算栏：`position: sticky; bottom: 16px` 固定内容区底部（滚动容器 el-main），深蓝底 #112d54、圆角 14px、白字、内边距 15/20px；左侧「已选 N 件产品 + 应付合计 ¥xxx（22px 加粗）」，右侧主蓝 #1769D4 按钮「结算下单 →」（蓝色投影）；原浅蓝 .cart-settle 样式删除 | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 「将生成 N 份销售记录」结算预览完整保留在 SalesOrderDialog 内；前置校验仍走 openOrder |
| 2026-10-22 | 修改 | ③ 产品信息列：名称左侧加 42px 渐变圆角图标块（linear-gradient 135deg，系统色 --primary-light→--info-purple-bg，图标字符 var(--primary-color)），按现有类型集合映射字符（软件◈/平台软件◫/数采设备·硬件集群▣/算力服务器⚡/卫星Token◉/卫星数据✦/遥感数据▦/默认◆，新增 `typeIcon`）；meta 行「编号 · 类型 · 主体」维持不变 | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 名称字号 13→14px、字重 600 |
| 2026-10-22 | 修改 | ④ 单价列层级：¥价格 14px 加粗 + 下方 11px 辅助色（#71829A）副文案（单位 + 库存/上限）；原数量列「已达上限 N」红色小字整合进此副文案（警示色沿用 --danger-color），「可售 N」同移；遥感行副文案仅「元/份」，可重复售卖行仅单位 | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 列宽 140→150 |
| 2026-10-22 | 修改 | ⑤ 顶部大段说明文字压缩重做为 notice 条（浅蓝底 #F0F6FF、边框 #E0ECFF、圆角 12px、左侧 ⓘ 图标）：「加粗标题 + 正文 2 行要点」，关键规则语义全保留（客户必填、金额整数元/区间折扣、数量上限、服务期限、按产品+客户分组生成销售记录、待审核流程） | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 原 .info-bar 全局样式未动（其他页面仍用） |
| 2026-10-22 | 修改 | ⑥ 移除操作：红色「移除」文字改 × 图标按钮（Close 图标，默认 #A3AFBF 辅助色，hover 系统警示红 + danger-light-9 底，带 tooltip「移除」）；操作列 `fixed="right"` **保留**——列宽合计约 1360px，1440 屏宽（内容区约 1150px）下溢出横滚，按任务口径「溢出则保留 fixed」 | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 删行仍走 removeRow，三角色可用口径不变 |
| 2026-10-22 | 修改 | ⑦ 行距/表头：表格去 `border`（无竖线，UI 规范），保留 stripe 与行 hover；表头 12px 灰字（#71829A）加粗，行单元格上下 padding 26px（行高 ~96px 舒展感，输入组件垂直居中沿用 EP 默认） | views/cart/index.vue | 购物车视觉优化（借鉴 demo） | 固定列分隔阴影样式保留 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 业务逻辑自查：`onQtyChange/onAmountInput/onAmountChange/onServiceChange/onCustomerChange/previewGroups/openOrder/onOrderSubmit/removeRow/clearAll/rowRangeText` 函数体零改动；仅新增 `typeIcon`、`stepQty`（复用 onQtyChange）。
- 场景自查：上限场景 + 号禁用置灰（`qtyMax` 判定）；空购物车走 el-empty 分支（notice/结算栏不渲染）；viewer 场景无新增只读逻辑（viewer 免填金额口径不变）。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-22 ｜ 修改：购物车操作列固定右侧 + 数量输入框收窄

**关联任务**：用户截图反馈购物车页 2 处 UI 微调（操作列被挤到边缘需横滚、数量输入框过大）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | 购物车「操作」列加 `fixed="right"`，横向滚动时「移除」按钮始终固定右侧可见；并加 scoped 样式 `:deep(.el-table .el-table-fixed-column--right)` 强化左侧分隔阴影，避免与「小计」列内容视觉粘连 | views/cart/index.vue | 用户反馈 UI 微调 | 无横向滚动时 fixed 无副作用；表头/行高对齐正常 |
| 2026-10-22 | 修改 | 购物车「数量」列宽 160→120、el-input-number 宽度 110→96px（保留 `controls-position="right"` 单侧步进按钮），与「销售金额」输入框视觉重量协调；「小计」次要列宽 130→110 缓解横向滚动压力（信息完整保留，未删列） | views/cart/index.vue | 用户反馈 UI 微调 | 遥感行数量恒 1 禁用口径不变 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-20 ｜ 修复：购物车日期列遮挡 + 参考区间提示可见性

**关联任务**：用户截图反馈购物车页 2 个 UI 问题（服务期限日期截断、参考区间看不到）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修复 | 购物车「服务期限」列：列宽 215→300，两个 el-date-picker 由 `width:100%` 改为各 136px 明确宽度，间距 6→8px——原列宽下每个输入仅约 94px，已填日期被截断成「2026-10-2…」；现可完整显示 YYYY-MM-DD + 日历图标 | views/cart/index.vue | 用户反馈 UI 修复 | 遥感行仍不展示期限输入（ADR-020 口径不变） |
| 2026-10-20 | 修复 | 购物车「销售金额（元）」列参考区间提示可见性：提示行显式辅助色 #71829A + 11px（原 `.muted` 色 #9aa9bf 过淡）；列宽 190→200 防长区间文案挤压；遥感行单位按 ADR-021 口径展示「份」（原直接取父产品 unit「份（可售明细）」容器口径）。渲染位置/条件排查结论：提示本就渲染在金额输入下方、覆盖全部行类型（unit/amount/遥感）且不在 tooltip 内，用户看不到的主因是**当前所有产品/rsItem 的 priceMin/priceMax 均为 null**（curl GET /api/bootstrap 实测确认）→ 按「无区间则不显示」口径正确地未展示；设区间后即显示 | views/cart/index.vue | 用户反馈 UI 修复 | 已用真实数据（临时设区间 + 加购）浏览器验证「参考区间 4000000~5100000 元/套」可见，验证数据已还原 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）。
- 浏览器实测（dev server 5173 + 后端 8000）：服务期限填 2026-10-20 / 2026-12-31 完整显示不截断；设参考区间的行金额输入下方可见「参考区间 4000000~5100000 元/套」小字。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-20 ｜ 新增：遥感售卖明细参考区间（RSITEM-RANGE-20261020）

**关联任务**：RSITEM-RANGE-20261020；契约见 `docs/api-contracts.md`「RSITEM-RANGE-20261020 批次」；决策依据 ADR-021（rs_items 参考区间，取代 ADR-018 §5「遥感行不限制」口径）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 新增 | 类型层：`RsItem` 新增 `priceMin/priceMax`（参考区间，元/份，可单边，可空）；API 层 `RsItemInput` 同步加 `priceMin/priceMax`（未设 → null） | types.ts, api/index.ts | RSITEM-RANGE-20261020 | ADR-021；bootstrap rsItems 每行已带两字段 |
| 2026-10-20 | 新增 | 遥感明细新增/编辑弹窗「单价（元）」下方加「参考价格区间」双输入（下限 ~ 上限，选填可单边，回显未设留空），交互/样式复用产品表单口径（el-input-number :controls=false min=0 precision=2）；提交 payload 带 `priceMin/priceMax`（空 → null，含清空场景） | views/assets/detail.vue | RSITEM-RANGE-20261020 | ADR-021；min ≤ max 后端 400「参考区间下限不能大于上限」走 showError |
| 2026-10-20 | 修改 | 遥感明细列表「单价」列：有参考区间时展示 `¥{price}（参考区间 {min}~{max}）`，无区间维持原展示（与产品价展示同口径，复用 `priceRangeText`） | views/assets/detail.vue | RSITEM-RANGE-20261020 | ADR-021 §4 |
| 2026-10-20 | 修改 | 购物车遥感行（rsItem 非空）参考区间提示改读该行售卖明细自身区间（`rowRangeText` 区分行类型），普通行仍读产品区间；未设不显示（现状行为） | views/cart/index.vue | RSITEM-RANGE-20261020 | ADR-021 §2；取代 ADR-018 §5 遥感行不限制口径 |
| 2026-10-20 | 修改 | 加购选择器（RsItemPicker）叶子 label 顺带展示参考区间（有则显示，无则维持原样，不强制） | components/RsItemPicker.vue | RSITEM-RANGE-20261020 | ADR-021 §4 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict）；IDE 诊断 0。
- 提交 payload 自查：`saveRsItem` 的 `RsItemInput` 恒带 `priceMin/priceMax`，`undefined → null`（`?? null`），覆盖「未设」与「编辑清空」两种场景。
- 未修改 backend/ 下任何文件；未执行构建/部署；未 commit。

## 2026-10-20 ｜ 新增：价格体系（区间/折扣）+ 合同时间节点 + 交付中状态机 + 服务期限（PRICING-20261020）

**关联任务**：PRICING-20261020；契约见 `docs/api-contracts.md`「PRICING-20261020 批次」；决策依据 ADR-018（价格区间/原价快照/终审不回写）、ADR-019（合同签订/预计交付时间 + delivering 状态机）、ADR-020（服务期限 + 下单入口收口购物车）。本章节覆盖上一轮已完成项 + 中断后补做项（11 小项）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 新增 | 类型层：`Asset.priceMin/priceMax`（参考区间，元/份，可单边）+ `priceRangeText` 展示文本；`CartItem/ProjectItem` 新增 `serviceStart/serviceEnd`（YYYY-MM-DD）；`ProjectItem` 新增 `origPrice/origAmount` 原价快照（下单时挂牌价，永不覆盖，存量空）；`Contract` 新增 `signedDate/scheduledDeliveryDate`；`ProjectStatus` 新增 `delivering`（「交付中」，橙 tag）并更新 `PROJECT_STATUS/PROJECT_FLOW` | types.ts | PRICING-20261020 | ADR-018/019/020；bootstrap 新字段均为可空 |
| 2026-10-20 | 新增 | API 层：`AssetInput` 加 `priceMin/priceMax`（未设 → null 区分）；`ProjectItemInput` 加 `serviceStart/serviceEnd`；新增 `patchContractFields`（PATCH /contracts/{id}：signedDate 商务录后 active→delivering 不可清空；scheduledDeliveryDate 仅 admin、可 null 清空）；`reviewProject` confirm 行级支持 `serviceStart/serviceEnd`；新增 `setCartService`（PUT /cart/{id} 服务期限） | api/index.ts | PRICING-20261020 | 403/400 文案由后端 detail 给出，走 showError 统一提示 |
| 2026-10-20 | 新增 | 产品创建/编辑页「参考价格区间」双输入（下限 ~ 上限，选填可单边，回显未设留空） | views/assets/create.vue | PRICING-20261020 | ADR-018；min ≤ max 后端 400 兜底 |
| 2026-10-20 | 修改 | 产品列表/详情单价展示：有参考区间时追加「（参考区间 {min}~{max}）」，无区间维持原展示（列表列与详情同口径） | views/assets/{list,detail}.vue | PRICING-20261020 | ADR-018 |
| 2026-10-20 | 删除 | 「登记销售」直接下单入口移除：产品详情/列表的登记销售按钮及 SalesOrderDialog 非购物车分支整体删除，`createSaleOrder`（POST /sales/order）前端调用一并删除；下单统一收口购物车 | views/assets/{list,detail}.vue, components/SalesOrderDialog.vue, api/index.ts | PRICING-20261020 | ADR-020；后端端点保留并标记 deprecated |
| 2026-10-20 | 新增 | 购物车：所有行（unit/amount/遥感）可输销售金额（整数元，失焦提交，空 = 原价成交），金额输入下追加参考区间提示；普通产品行新增服务期限双日期输入（变更即 PUT 提交，遥感行不展示）；结算预览行展示组内一致的服务期限 | views/cart/index.vue, components/SalesOrderDialog.vue | PRICING-20261020 | ADR-018 §3 / ADR-020；区间校验（amount/qty ∈ [min,max]）后端 400 兜底 |
| 2026-10-20 | 新增 | 建单页：明细表新增「服务期限」列（普通行双日期选填，遥感行不展示）；校验 start ≤ end；payload 随明细提交（空 → null）；重新提交（?copy=）预填带出旧单期限与原价快照（只读展示，不提交）；编辑模式只读概览行展示原价 | views/sales/projects/create.vue | PRICING-20261020 | ADR-018 §2 / ADR-020 |
| 2026-10-20 | 新增 | 审核页数据层：`ReviewLine` 扩展 `origPrice/origAmount`（下单快照只读，存量空 → 按当前 price/amount 兜底）与 `serviceStart/serviceEnd`（预填可改 + orig 变更检测） | views/sales/projects/review.vue | PRICING-20261020 | 上一轮完成；UI 展示为本次补做 |
| 2026-10-20 | 新增 | 【补做】审核页四列改价 UI：unit 行加「原单价（只读）」列 + 保留「实际单价（可编辑）」；amount/遥感行加「原金额（只读）」+ 保留「销售金额（可编辑）」；存量订单 orig 为空时数据层已按现值兜底，故恒展示（注释说明） | views/sales/projects/review.vue | PRICING-20261020 | ADR-018 §2 |
| 2026-10-20 | 新增 | 【补做】审核页服务期限编辑：普通行加开始/结束双日期输入（el-date-picker value-format YYYY-MM-DD），遥感行（itemId 非空）不展示；confirm payload 行级追加 `serviceStart/serviceEnd`（期限变更的行一并提交，不传 = 保持原值） | views/sales/projects/review.vue | PRICING-20261020 | ADR-020；start ≤ end 后端 400 兜底 |
| 2026-10-20 | 修改 | 【补做】审核页过期文案清理：页头说明/面板说明/确认弹窗/成功 toast 中「实际价格将同步到平台产品单价」「实际价格已同步到平台」全部删除，改为「终审价格仅作用于本订单（不回写平台产品单价）」 | views/sales/projects/review.vue | PRICING-20261020 | ADR-018 §4：终审改价回写 assets.salePrice 的逻辑后端已删除 |
| 2026-10-20 | 修改 | 【补做】项目详情合同卡时间：「签约/锁定」改名「下单时间」；新增「合同签订」（signedDate，空显「未签订」）与「预计交付」（scheduledDeliveryDate，空显「未录入」）两个展示项（布局沿用 contract-info） | views/sales/projects/detail.vue | PRICING-20261020 | ADR-019 |
| 2026-10-20 | 新增 | 【补做】项目详情合同卡按钮：active 分支加「录入签订时间」（商务 canWrite 可见，日期小弹窗 .dlg-form → `patchContractFields(id, { signedDate })`，录入即转交付中、不可清空）；新增 `delivering` 分支（置于 v-else 兜底之前，修复原落入「已终止」文案）——「交付」+「终止」沿用既有调用与确认流程，另加 **admin 专属**「预计交付时间」按钮（日期弹窗 → `patchContractFields(id, { scheduledDeliveryDate })`，已有值可不选日期保存以清空，payload 传 null） | views/sales/projects/detail.vue | PRICING-20261020 | ADR-019；delivering 卡片左侧色条补橙（与状态 tag 同色板） |
| 2026-10-20 | 新增 | 【补做】项目详情合同明细表加「服务期限」列（`serviceStart ~ serviceEnd`，空显 `-`，遥感行展示为空） | views/sales/projects/detail.vue | PRICING-20261020 | ADR-020 |
| 2026-10-20 | 修改 | 【补做】状态文案同步：详情页销售记录清单派生说明、列表页 info-bar 补「交付中」环节（录入签订时间后转交付中、已交付终止回退交付中）；交付记录页撤销交付回退文案「进行中」→「交付中」（2 处） | views/sales/projects/{detail,index}.vue, views/sales/outbound/index.vue | PRICING-20261020 | ADR-019：撤销后合同回 delivering（signedDate 仍在） |
| 2026-10-20 | 删除 | 【补做】建单页残留清理：toast「遥感数据请通过产品列表加购或详情页登记销售」删「或详情页登记销售」；`?assetId` 预填死代码（onMounted 块 + 头部注释）删除（已确认 router 无该 query 入口，仅 `?copy=` 保留） | views/sales/projects/create.vue | PRICING-20261020 | ADR-020 |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict + noUnusedLocals）；IDE 诊断 0。
- `patchContractFields` 前端调用 2 处：signedDate（active 分支「录入签订时间」）+ scheduledDeliveryDate（delivering 分支 admin「预计交付时间」，含 null 清空路径）。
- 全局 grep：「登记销售」仅剩删除说明性注释（assets/cart/components/api 中标注入口已移除），无可用入口残留；「同步到平台产品单价」/「已同步到平台」文案无残留；`route.query.assetId` 无残留。
- 未修改 backend/ 下任何文件；未 commit。

## 2026-10-20 ｜ 修复：viewer「重新提交」被创建按钮禁用拦截（FIX-RESUBMIT）

**关联任务**：FIX-RESUBMIT（FIX-20261020 回归修复）；后端 `POST /projects/{id}/resubmit` 权限口径见 `docs/backend/api.md`（require_order + creator 归属校验）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修复 | 建单页新增 `canSubmit` 可提交判定（`canWrite \|\| (copy 模式 && 预填守卫通过)`）：viewer 对自己下单的 terminated 项目走 `?copy=` 重新提交时主按钮放开（对齐后端 resubmit 实际权限，修复 FIX-20261020 回归）；copy 模式主按钮文案改「重新提交」、隐藏「保存草稿」（saveDraft 走 createProject 会丢旧单关联与双向留痕，copy 模式只允许正式重新提交）；普通新建（无 copy）viewer 禁用 + NO_PERM_TIP、路由守卫、编辑模式按钮区均保持不动 | views/sales/projects/create.vue | FIX-RESUBMIT | `copyPrefillOk` 仅在 onMounted copy 守卫（viewer 归属 + terminated）全部通过并预填完成后置 true，校验失败跳回路径不置位；handleSubmit copy 分支已走 `resubmitProject` 无需改动 |

### 验证

- `npx vue-tsc --noEmit` 0 error；IDE 诊断 0。
- 验收：viewer + `?copy=<terminated 且 creator=自己>` → 主按钮可用、文案「重新提交」、无保存草稿；viewer 无 copy → 主按钮仍禁用 + NO_PERM_TIP；editor/admin 全场景行为不变。
- 未修改 backend/ 下任何文件；未 commit。

## 2026-10-20 ｜ 删除：移除「生态人员基础资料」页面及 db.reps 镜像（CLEANUP-20261020）

**关联任务**：CLEANUP-20261020；契约见 `docs/api-contracts.md`「CLEANUP-20261020 批次」章节。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 删除 | 移除 settings/reps「生态人员基础资料」页面（base.vue）及其路由、路由守卫分支、侧边栏「生态人员」菜单项；删除 api 层 `db.reps` 镜像字段、bootstrap 全量同步中的 `db.reps = data.reps`、`BaseKind` 联合类型中的 `'reps'`。原因：生态人员已由 users 表 + viewer 角色（账号角色体系）承载，base_records（kind='reps'）名册无任何业务消费点（建单下拉/筛选/展示均走 /users/options/all） | views/settings/base.vue（删除）, router/index.ts, layouts/MainLayout.vue, api/index.ts | CLEANUP-20261020 | addBase/updateBase/deleteBase 函数与 suppliers/customers 镜像保留不动（暂保留，前端暂无消费点）；「基础设置」子菜单保留（仍有交付物设置/账号与审计）；后端 bootstrap 的 reps 字段由后端并行移除 |

### 验证

- `npx vue-tsc --noEmit` 0 error。
- 全局搜索 `db.reps` / `SettingsReps` / `settings/reps` / `/bases/reps`：仅剩 sales/projects 两处历史说明性注释（解释选项源已由 db.reps 迁移至 /users/options/all），语义仍准确，予以保留。
- 未修改 backend/ 下任何文件；未 commit。

## 2026-10-20 ｜ 修复：业务逻辑 bug 10 项（FIX-20261020）

**关联任务**：FIX-20261020（问题清单 `docs/business-logic-bugs-20261020.md`）；接口契约以 `docs/api-contracts.md`「FIX-20261020 批次」为准；决策依据 ADR-014 / ADR-016 / ADR-017。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修复 | 删除前端 viewer 写请求白名单（`VIEWER_ALLOWED_REQUESTS`）与 axios 请求预拦截；响应拦截器对 403 统一 toast 后端 `detail` 并抛 `PermissionError`；新增 `showError` 统一提示函数，全部 catch 调用点（13 个文件 33 处）改用它避免 403 重复弹框；原 `READONLY_TIP` 更名为 `NO_PERM_TIP`（仅保留禁用按钮 UX 提示用途，403 错误文案统一由后端给出） | api/index.ts, auth.ts, views/{cart,login,assets/*,sales/*,settings/*}, components/TransferDialog.vue | FIX-20261020-#1 | ADR-014：权限判定统一由后端守卫（require_order/require_editor）兜底，viewer 编辑/取消/终止/交付/重新提交恢复可用 |
| 2026-10-20 | 修复 | 购物车结算预览 `previewGroups` 分组键由 customer 改为 `(assetId, customer)` 双键（同产品不同客户 = 两份销售记录），与后端 checkout 分组一致；预览行追加产品名区分同客户多产品分组；页面/tooltip「按客户分组」文案同步 | views/cart/index.vue, components/SalesOrderDialog.vue | FIX-20261020-#3 | ADR-016；「将生成 N 份销售记录」文案保持 |
| 2026-10-20 | 修复 | Token 计价展示统一：`derivedUnitPrice` 去掉 `/1e4`，改为 `amount/qty`（`元/{unit}`，2 位小数，新增可选 unit 参数，调用方传产品 unit）；产品列表/详情/创建/购物车「¥{salePrice}/万Token」特判分支全部删除，改为与普通产品一致的 `formatMoney(salePrice)` 展示；创建页数量提示改「份数」口径、单价标签统一「销售单价（元）」 | types.ts, views/assets/{list,detail,create}.vue, views/cart/index.vue, views/sales/projects/{create,detail}.vue, components/SalesOrderDialog.vue | FIX-20261020-#4 | ADR-017：前后端派生价同口径（元/份）；存量 Token 数据不自动迁移，由业务页面手工修正 |
| 2026-10-20 | 修复 | 产品编辑模式「产品类型」下拉加 `:disabled="isEdit"`（与所属板块一致），避免改类型造成计价模式脱钩 | views/assets/create.vue | FIX-20261020-#8 | 后端 type 变更时亦自动重算 pricingMode（契约 §7） |
| 2026-10-20 | 修复 | 补录交付弹窗删除「经办人」输入框与 `form.operator` 字段（提交不再携带 operator，`OutboundInput` 同步移除）；项目下拉 `activeProjects` 过滤改为排除 `terminated` 与 `pending` | views/sales/outbound/index.vue, api/index.ts | FIX-20261020-#5 / #9 | ADR-015：经办人统一取触发请求的登录账号；表格「经办人」列保留（展示后端返回值） |
| 2026-10-20 | 修复 | rep 统一存 username：下单弹窗静默取 `currentUser.username`（原 name）；建单页新建表单生态人员下拉由 db.reps 基础资料（value=姓名）切换为全量账号名册（value=username、label 显示姓名），去掉 allow-create（防手输姓名回潮）；列表筛选选项仅收集 `p.rep`（username），显示名走 `repName`（/users/options/all 映射） | components/SalesOrderDialog.vue, views/sales/projects/{create,index}.vue | FIX-20261020-#10 | 后端对姓名入参亦归一为 username（契约 §7）；编辑面板原已 username 不动 |
| 2026-10-20 | 修复 | 项目详情 `customerText`：p.customer 为空时从合同客户去重提取——1 个 → 直接显示客户名；多个 → 「N 位客户」（N 为去重客户数）；0 个 → '-'（修复空客户合同误显示「1 位客户」） | views/sales/projects/detail.vue | FIX-20261020-#12a | 原按合同数回退 |
| 2026-10-20 | 修复 | 资产详情「销售关联」tab 生态人员列由裸 `row.project.rep` 改为账号→姓名映射显示（复用项目页既有口径：/users/options/all 名册 + repName 同构实现） | views/assets/detail.vue | FIX-20261020-#12b | 2026-10-20 前只修了 4 个项目页，本页遗漏 |
| 2026-10-20 | 修复 | 建单页 `onItemAssetChange` 删除「同合同内产品主体必须一致」预校验及「后端 400 兜底」过时注释（后端 ADR-013 已移除该限制）；`ContractInput`/`Contract` 等相关注释同步 | views/sales/projects/create.vue, api/index.ts, types.ts | FIX-20261020-#12c | 手工混合主体合同不再被前端拦截 |
| 2026-10-20 | 修复 | 建单页 `contractAmount` 改只读展示（disabled，仍显示 Σ 明细金额实时值），删除 `contractTouched` 手改逻辑与相关注释；重新提交预填后按明细重算合同金额 | views/sales/projects/create.vue | FIX-20261020-#12d | 后端 review 仍按 Σ 明细重算，口径一致；提交值 = 明细合计（非手改值） |

### 验证

- `npx vue-tsc --noEmit` 0 error（strict + noUnusedLocals）；IDE 诊断 0。
- 全局搜索：`READONLY_TIP` / `VIEWER_ALLOWED_REQUESTS` 无残留引用；「万Token」展示特判无残留（仅删除说明性注释）；outbound 表单 `operator` 无残留（表格列保留，展示后端值）；`contractTouched` 仅剩 SalesOrderDialog 直接下单对话框的同名局部逻辑（非本次范围）。
- 未修改 backend/ 下任何文件；未 commit。

## 2026-10-20 ｜ 修复：列表「生态人员」列裸账号外露（显示名册缺生态账号）

**根因**：账号→姓名映射用的 `/users/options` 只返回商务（editor/admin）账号（商务负责人下拉专用），生态 viewer 账号不在其中 → `repName` 查不到回退原值；且 10-19 起 rep 归一为 username，保存过的项目列值变账号后直接外露（老单存姓名所以看着"又变回账号了"）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 4 个项目页显示映射（列表/编辑/审核/详情）数据源切到新接口 `allUserOptions`（全量启用账号，含生态）；连带修复**编辑页生态人员下拉选不到生态账号**（同源） | projects/index.vue, create.vue, review.vue, detail.vue, api/index.ts |
| 2 | 修改 | 列表页「商务负责人筛选」下拉拆出 `ownerFilterOptions`（仍用商务专属接口，businessOwner 只可能是商务）；「生态人员筛选」下拉 label 改 `repName` 显示姓名（value 保持原值匹配） | projects/index.vue |
| 3 | 保留 | TransferDialog（商务接手/转交选人）维持商务专属接口——订单不得转给生态 | components/TransferDialog.vue（未改） |

### 验证

- 接口实测：`/users/options/all` 含 3 个 viewer ✓；`/users/options` 仍仅商务 ✓；build 0 error、lint 0。

## 2026-10-20 ｜ 新增：已终止项目「重新提交」（预填原单明细可改 → 新建 pending 订单）

**关联任务**：用户要求被驳回的订单下单账号能再次编辑提交；审核中的订单可先撤销再编辑（撤销=已有的「取消订单」，本条打通撤销/驳回后的重提闭环）。拍板口径：**预填重新下单**（旧项目保留 terminated 历史，驳回原因可查）+ **明细可改**（产品/数量/客户）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | 入口：列表操作列 / 详情页头部对 terminated 项目显示「重新提交」（商务/管理员/下单生态本人）→ `create?copy=<id>` | projects/index.vue, detail.vue |
| 2 | 新增 | 建单页「重新提交」模式（`?copy=`）：标题区分；预填原单全部合同（客户/产品/数量/金额/遥感明细行 itemId），均可修改；rep 生态静默本人、商务沿用原单；守卫（非 terminated/非本人单 → 拦截回详情） | projects/create.vue |
| 3 | 修改 | 提交分支：copy 模式走 `resubmitProject`（新 API），成功提示新编号（待审核） | projects/create.vue, api/index.ts |
| 4 | 修改 | 遥感明细行支持：payload/`ProjectItemInput` 携带 `itemId`；`onItemAssetChange` 对预填遥感行豁免「遥感不可手工加行」拦截 + 换产品时清空旧明细绑定；校验补「遥感行数量固定 1」 | projects/create.vue, api/index.ts |
| 5 | 修改 | 路由守卫：viewer 仅 `create?copy=<id>` 放行（直连裸新建页仍拦截，新建入口移除策略不变）；页面内再校验归属/状态 | router/index.ts |
| 6 | 修改 | 列表空态文案修正（原仍写「点击右上角新增销售项目」） | projects/index.vue |

### 验证

- `npm run build` 0 error；lint 0。
- 冒烟（真实 API，已清理）：下单→驳回→生态重新提交（数量 2→3）→ 200 新单 pending、creator=下单人、双向备注留痕（新单「重新提交自 旧编号」、旧单「已重新提交为 新编号」）；生态重提他人单 403；pending 项目重提 400 ✓。

## 2026-10-20 ｜ 修改：审核页遥感明细行放开金额编辑（仅本单生效）

**关联任务**：用户要求资产容器（遥感明细）产品在审核时也可改金额。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 审核页 rs 行由只读 → 销售金额（整数元）可编辑，显示派生参考单价 + 「明细单价不回写」提示 | projects/review.vue |
| 2 | 修改 | 确认下单校验/提交体纳入 rs 行（金额正整数元；改过的行一并提交 amount） | projects/review.vue |
| 3 | 修改 | 面板/页头文案：「遥感明细行按明细单价计价不可改」→ 可改、仅本单生效 | projects/review.vue |

后端配套：`review_project` confirm 对遥感明细行由 400 → 接受 `amount`（只改本行金额、price 派生反算，**不回写 rs_items 明细单价，不写平台挂牌价**）；changelog 见后端文档。

### 验证

- build 0 error；lint 0；py_compile 0。
- 冒烟（真实 API，已清理）：遥感明细行审核改 330000→350000 → 200，本行生效、`rs_items.price` 不变、`assets.salePrice` 不变 ✓。

## 2026-10-20 ｜ 修改：人员展示统一「只显示姓名」（用户更正：不要带账号）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 三处 `ownerLabel`（列表/编辑/审核页）由「姓名(账号)」改为**只显示姓名**（查不到/无姓名回退原值） | projects/index.vue, create.vue, review.vue |
| 2 | 修改 | 列表「生态人员」列原显示裸账号 → 新增 `repName`（username→姓名，存量姓名格式兼容） | projects/index.vue |
| 3 | 修改 | 详情页「生态人员/商务负责人」原显示裸账号 → 补 `userName` 映射显示姓名 | projects/detail.vue |
| 4 | 保留 | 转交/接手**选人下拉**保留「姓名(账号)」——选择场景需区分同名，非展示字段 | components/TransferDialog.vue（未改） |

### 验证

- `npm run build` 0 error；lint 0。

---

## 2026-10-19 ｜ 修改：生态编辑/终止权限放开 + 订单审核独立页 + 编辑页布局优化（用户三项需求）

**关联任务**：① 生态人员需可编辑自己项目 + 终止项目（非删除，记录留存，终止后不可编辑）；② 审核是独立页面（仅订单审核+备注两块），不是编辑页；③ 编辑页优化：生态人员显示姓名不显示账号、删金额信息卡、备注置底。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 生态（viewer）放开编辑自己下单的项目（pending/active 均可改基本信息；rep 锁本人、负责人只读）：`canEditForm` 按 creator 判定 | projects/create.vue |
| 2 | 新增 | 编辑页底部「取消订单（终止）」/「终止项目」按钮（仅 viewer 自己单）→ `PATCH /projects/{id}/status terminated`（项目级批量终止，记录留存、不可再编辑） | projects/create.vue |
| 3 | 新增 | **独立审核页** `/sales/projects/:id/review`（仅商务/管理员，viewer 路由守卫拦截）：仅「订单审核」（改价确认/驳回，自编辑页整体迁移）+「备注」（可编辑保存）两块；含无主单「接手此单」、非负责人只读提示、转交入口 | projects/review.vue（新文件）, router/index.ts |
| 4 | 修改 | 编辑页删除内嵌订单审核面板与 确认下单/驳回/转交 按钮；删「金额信息（销售金额合计）」卡；备注卡移至销售记录清单之后（置底）；新增「审核订单」跳转按钮（商务/管理员+pending） | projects/create.vue |
| 5 | 修改 | 生态人员下拉改为展示 **姓名(账号)**（原裸账号/姓名混杂），value=username 与下单口径一致；存量存姓名的 rep 自动归一为账号；商务负责人只读展示同步改 姓名(账号) | projects/create.vue |
| 6 | 修改 | 入口调整：列表页/详情页 pending 项目「审核订单」→ 审核页；**viewer 自己 pending 单显示「编辑」（可点）**→ 编辑页（`canEditProject`/`goEdit` 加角色分支） | projects/index.vue, projects/detail.vue |
| 7 | 修改 | `Project` 类型补 `creator?` 字段 | types.ts |

### 验证

- `npm run build` 0 error；lint 0。
- 冒烟（真实 API，已清理）：viewer 下单→编辑自己 pending 200 → 终止自己 pending 200（项目/记录 terminated、**锁定释放**）；商务负责人项目级终止 pending → 400（必须走审核）✓。

---

## 2026-10-19 ｜ 修改：废弃「报价金额/已回款」字段 + 销售项目页 UI 重设计 demo（未改原页面）

**关联任务**：用户确认编辑页「报价金额/已回款金额」无用，全部删除；并要求为详情页/编辑页出 UI 重设计单页 demo（先不动原页面）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 删除「报价金额/已回款金额」输入（编辑模式金额区 + 新建模式金额区）、「未回款」派生卡与 `editUnpaid` computed、form 字段/提交体/预填；金额区仅保留「销售金额合计」派生卡 | projects/create.vue |
| 2 | 修改 | 详情页删除「已回款」展示项 | projects/detail.vue |
| 3 | 修改 | 类型定义两字段改可选（`quoteAmount?`/`paidAmount?`），兼容存量数据与旧调用 | api/index.ts, types.ts |
| 4 | 新增 | **UI 重设计 demo**（单页 HTML，纯静态无依赖，顶部可切换详情页/编辑页视图）：现代 SaaS 风格（Linear/Stripe 式）——详情页 = 页头(名称+编号+状态+操作) → 4 统计卡 → 记录表主列 + 基本信息/备注侧栏；编辑页 = 双栏（左表单右金额+记录速览）+ 底部粘性操作条。mock 数据取自用户截图 | **public/sales-project-demo.html**（新文件，访问 `http://<host>:5173/sales-project-demo.html`，**原页面零改动**） |

后端配套：`ProjectInput.quoteAmount/paidAmount` 改可选（default 0，兼容不传）；`update_project` 白名单移除两字段（不再写入，存量值保留）。

### 验证

- `npm run build` 0 error；py_compile 0；lint 0；views 下两字段零残留引用。
- 冒烟：建单带旧字段 200（兼容）；PUT 不传两字段 → 存量值不被覆盖 ✓。
- demo 经 vite dev server 200 可访问。

---

## 2026-10-19 ｜ 修改：移除「新增销售项目」入口 + 项目编号列对齐优化（用户指示）

**关联任务**：用户标注销售项目列表截图：① 编号列折 3 行不美观、项目名称占宽过长；② 删除「新增销售项目」入口（要求先评估）。

**评估结论（已采纳）**：可安全移除——下单统一走产品下单（购物车/直接下单）；手动建单页**保留路由与 API**（直连 URL 可进，供代录/数据修复等特殊场景），仅删 UI 按钮；存量数据与既有入口零影响。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 列表页移除「新增销售项目」按钮（含 head-actions 包裹与 `Plus` import 清理）；手动建单页路由保留 | projects/index.vue |
| 2 | 修改 | **顺带发现的隐藏入口**：产品详情页「登记销售」原对商务/管理员跳手动建单页（带 assetId 预填）——改为直接打开下单对话框（与产品列表直接下单、viewer/遥感明细行为统一）；`isViewer` import 清理 | assets/detail.vue |
| 3 | 修改 | 项目编号列：width 110 → 185 + mono 等宽 12px + 不换行 + overflow tooltip（原 20 字符编号折 3 行）；项目名称列 min-width 200 → 150（超长省略+tooltip 原有） | projects/index.vue |
| 4 | 修改 | 列表提示条同步新规则（原「生态人员购物车下单后进入待审核」→「下单（购物车/直接下单）统一进入待审核…商务接手后确认或驳回」） | projects/index.vue |

### 验证

- `npm run build` 0 error；lint 0；无残留引用（Plus/isViewer import 已清）。

---

## 2026-10-19 ｜ 修改：下单对话框 UI 优化——删除「生态人员/商务负责人」填写项 + 结算预览三列对齐

**关联任务**：用户标注购物车下单弹窗截图要求优化（① 预览行排列不齐 ② 删除两个人员填写字段）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 下单对话框（购物车 + 直接下单共用）删除「生态人员」下拉与「商务负责人」输入框：rep 静默取**当前登录账号姓名**（原 viewer 自动本人行为推广到全角色，保证「自己下单」归属口径）；商务负责人**下单入口不再指定**——统一由下单后「接手」流程绑定（ADR-012 §5.1 纯移交制），恒空提交（后端 `_validate_business_owner` 校验保留兜底，空值跳过） | components/SalesOrderDialog.vue |
| 2 | 修改 | 结算预览区改三列 grid 对齐（客户名弹性+超长省略+title 提示 / 数量右对齐 64px / 金额右对齐 150px 等宽数字）——原 flex 流式排列因客户名长短不一列错位 | components/SalesOrderDialog.vue |
| 3 | 清理 | `reps` computed、`db`/`isViewer` import 无引用删除 | components/SalesOrderDialog.vue |

**范围说明**：仅下单类入口（购物车结算、直接下单）删除；手动建单页（`sales/projects/create.vue` 新建）的「生态人员/商务负责人」保留——商务代录订单场景 rep 可能指向真实生态人员，语义不同。

### 验证

- `npm run build` 0 error；lint 0。
- 冒烟（真实 API，测试数据已清理）：购物车/直接下单按新 payload（rep=本人姓名、businessOwner 空）→ 200，项目 rep 正确、owner 空、status pending ✓。

---

## 2026-10-19 ｜ 排查修复：viewer 编辑不可用 + admin 无主单无接手入口 + terminated 直连漏拦 + 死代码清理（子 Agent 前后端一致性排查）

**关联任务**：配合后端排查（见后端 changelog 同日条目），前端对照规则基线逐按钮排查，修复 3 处确定问题 + 清理 2 处死代码 + 2 处文案小修。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **viewer 自己 active 单可编辑**：`canEditForm` 原 `!canWrite → false` 使 viewer 全字段禁用 + 「保存修改」恒禁用，但列表/详情入口与后端 PUT 守卫均允许 viewer 编辑自己单——三方口径不一致。改 `!canWrite && !isViewer → false`，「保存修改」按钮/tooltip 改用 `canEditForm`（viewer 的 pending 自己单仍只读） | projects/create.vue |
| 2 | 修复 | **admin 无主单可接手**：TransferDialog「接手给我」选项原要求 `project.businessOwner` 非空——admin 在编辑页对无主单只能转给别人不能接手。去掉该条件；编辑页底部按钮文案改 `businessOwner ? '转交' : '接手'` | TransferDialog.vue, create.vue |
| 3 | 修复 | **terminated 直连 URL 漏拦**：onMounted 守卫只拦 delivered 与无合同非 active——有合同且派生 terminated 的项目可绕过进表单（提交才 400）。补 `p.status === 'terminated'` 守卫，与列表 `canEditProject` 同口径 | create.vue |
| 4 | 清理 | **死代码**：审核面板 alert 内「接手此单/转交给我」按钮与底部操作区同按钮均不可达（pending+非负责人已被 noEditAccess 提示页拦截）→ 删除；`claimLabel` computed 无引用删除；**noEditAccess 提示页新增接手按钮**（无主单商务「接手此单」/有主单 admin「接手给我（管理员）」，接手成功后 canReviewEdit 翻转、表单原地渲染） | create.vue |
| 5 | 修复 | viewer 小修：pending 入口禁用 tooltip 对 viewer 改「待审核项目由商务人员接手确认后生效」（viewer 不能接手，原「请先接手」误导）；`canClaimRow` 对 viewer 直接不渲染接手/转交按钮（原无主单灰显/有主单不显示口径不一） | projects/index.vue, detail.vue |

### 验证

- `npm run build` 0 error；lint 0；后端冒烟（viewer PUT 自己 active 单 200 等）全通过。
- 架构性限制记录在案：跨账号状态实时性（A 转交后 B 已打开页面不自动翻转，点击由后端 400 兜底）——如需实时需轮询/推送，属产品决策。

---

## 2026-10-19 ｜ 修改：所有角色建单统一进「待审核」的文案同步（配合后端 ADR-012 修订）

**关联任务**：后端建单入口统一 pending（见后端 changelog 同日条目）。前端仅文案/提示调整，状态展示逻辑（tag/筛选/入口按钮）零改动。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 购物车结算成功提示去角色分叉：统一「销售项目 X 待审核（数量已锁定 · N 份销售记录），商务接手确认后生效」 | cart/index.vue |
| 2 | 修改 | 直接下单成功提示（产品列表/产品详情两处）：「（进行中）」→「待审核，商务接手确认后生效」 | assets/list.vue, assets/detail.vue |
| 3 | 修改 | 购物车说明区：「生成进行中销售项目」→「进入待审核…商务接手确认（可改价）后生效」；手动建单「保存草稿」成功提示与注释 →「待审核」 | cart/index.vue, sales/projects/create.vue |

### 验证

- `npm run build` 0 error；lint 0。冒烟见后端 changelog（全角色建单 → pending 全链路通过）。

---

## 2026-10-19 ｜ 修复：驳回按钮幽灵显示 bug + pending 编辑入口禁止态（ADR-012 §5.1 入口权限收敛）

**关联任务**：用户实测「转交后 wuhao 仍能进编辑页做驳回操作；转交/未接手的单应只读，编辑按钮应是禁止符号不能进入」。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **「驳回」按钮 v-else 误绑定 bug**：原 `v-else` 挂在「接手/转交」按钮条件上 → 非负责人的普通商务也显示「驳回」（点击才被后端 400）。改为独立 `v-if="canReviewEdit"`，驳回/确认仅负责人（或 admin）可见 | projects/create.vue |
| 2 | 修改 | **列表 pending 入口按钮禁止态**：`canEditProject` 加 pending 门槛（仅 owner/admin）；按钮文案 pending→「审核订单」（warning 橙），无权限者禁用 + tooltip「仅商务负责人（或管理员）可进入，请先接手」；删除旧的独立「审核订单」按钮（与新按钮重叠） | projects/index.vue |
| 3 | 修改 | 详情页顶栏：pending 无权限者由「隐藏按钮」改为**禁用**「审核订单」（tooltip 说明） | projects/detail.vue |
| 4 | 新增 | **编辑页直连 URL 拦截**：`noEditAccess`（isEdit && pending && canWrite && !canReviewEdit）→ 只读提示页（el-alert「该订单由商务 X 负责，你暂无编辑/审核权限」+ 返回列表），不渲染表单；viewer 自己单只读视图与 admin 越过不受影响 | projects/create.vue |

### 验证

- `npm run build` 0 error；lint 0。后端守卫（review 仅负责人/admin、PUT pending 守卫）不变，UI 与后端口径已完全对齐。

---

## 2026-10-19 ｜ 修复：编辑页 pending 项目非负责人可编辑 + 幽灵「转交」按钮（配合后端越权修复）

**关联任务**：wuhao 转交给 wuhao2 后 wuhao 仍能看到转交按钮且表单可编辑。根因见后端 changelog 同日条目。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **`canEditForm`**（canWrite && !(pending 且非负责人)）：pending 项目对非负责人禁用基本信息全部输入（名称/生态人员/日期×2/报价/回款/备注）+「保存基本信息」按钮（tooltip「待审核项目仅商务负责人（或管理员）可编辑基本信息」）；active 项目商务均可编辑（原规则不变） | projects/create.vue |
| 2 | 修复 | 「商务负责人」输入框 → **只读展示**（绑定 `editProject.businessOwner`，变更入口=接手/转交） | projects/create.vue |
| 3 | 修复 | 底部操作区「接手此单/转交」按钮补条件 `(!businessOwner \|\| isAdmin)`：他人单据的普通商务不再显示（原显示、点击被后端 400） | projects/create.vue |

### 验证

- `npm run build` 0 error；lint 0；后端 4 场景冒烟通过（见后端 changelog）。

---

## 2026-10-19 ｜ 修改：转交语义修正为**纯移交制**前端（TransferDialog 下拉选人）

**关联任务**：配合后端 claim 纯移交制（见后端 changelog 同日条目）。原「他人单据→转交给我（抢单）」按钮废除；改为「负责人→转交（下拉选新负责人）」。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **`TransferDialog` 组件**：下拉选新负责人（`GET /users/options` 现取，排除当前负责人）；admin 额外选项「接手给我」；确认 → `claimProject(id, newOwner)` | components/TransferDialog.vue |
| 2 | 修改 | **按钮逻辑三处统一**（列表行/详情页顶栏/编辑页审核面板）：无主→「接手」（确认框直接接）；自己负责→「转交」（弹 TransferDialog）；他人负责→**仅 admin** 见「转交」（含「接手给我」），普通商务不显示按钮 | projects/index.vue, detail.vue, create.vue |
| 3 | 修改 | 编辑页审核面板：负责人/admin 在「确认下单/驳回」旁新增「转交」按钮；非可审核者 alert 区——无主单「接手此单」、他人单仅 admin「转交」 | create.vue |
| 4 | 修改 | `claimProject(id, newOwner='')` API 加参数（POST body `{newOwner}`） | api/index.ts |

### 验证

- `npm run build` 0 error；后端 9 场景冒烟通过（抢单拦截/负责人转交/admin 越过等，见后端 changelog）。

---

## 2026-10-19 ｜ 修改：「审核订单」按钮仅接手人可见（ADR-012 §5.1 增补）

**关联任务**：用户反馈——pending 项目未接手前商务也能看到「审核订单」按钮（点进去被拦截），易困惑。改为：仅接手人（或 admin 越过）展示，未接手/他人接手时隐藏；详情页补「接手/转交」按钮作接单入口。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 「审核订单」按钮显隐条件 `canWrite` → **`canReviewRow/canReview`**（canWrite && businessOwner 非空 && (isAdmin \|\| businessOwner===当前账号)）：列表行、抽屉底部、详情页顶栏、详情页记录卡四处统一 | projects/index.vue, detail.vue |
| 2 | 新增 | 详情页顶部「接手/转交」按钮（canWrite 且 pending/active 且非本人负责）+ `handleClaim`（确认弹框 → `claimProject` → refresh），补上「审核订单」隐藏后的接单入口 | detail.vue |
| 3 | 不变 | 直接打开编辑 URL 的兜底：审核面板内「接手此单/转交给我」按钮与后端 400 守卫保留 | - |

### 验证

- `npm run build` 0 error（修 1 处 v-else-if 类型收窄 TS2367）；lint 0。

---

## 2026-10-19 ｜ 修改：ADR-013 销售记录前端（「合同」→「销售记录」全量文案 + 多主体提示更新）

**关联任务**：配合后端一资产一记录/多主体改造（见后端 changelog 同日条目 + `docs/adr/ADR-013.md`）。代码标识（`Contract`/`contractAmount`/`/contracts/` API）全部不变。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **全量界面文案**（模板区 + 字符串字面量，代码注释保留）：「合同」→「销售记录」、「合同金额」→「销售金额」、「合同状态」→「销售记录状态」、「合同清单」→「销售记录清单」、「合同合计」→「销售金额合计」、「交付合同」→「交付」；列表列「关联合同」→「销售记录」、「合同金额」列→「销售金额」；抽屉/详情/审核面板/购物车/交付记录/直接下单对话框/产品页全部同步 | projects/index.vue, create.vue, detail.vue, cart/index.vue, outbound/index.vue, SalesOrderDialog.vue, assets/*.vue |
| 2 | 修改 | **过时规则文案更新**（ADR-013 废除同主体限制）：购物车说明改「每个产品生成一条销售记录（不同主体的产品可同单混装）」；直接下单对话框「结算时每个产品生成一条销售记录」；手动建单说明改「可含不同主体的产品明细」 | cart/index.vue, SalesOrderDialog.vue, create.vue |
| 3 | 不变 | 多主体展示沿用既有 `__multi__` 分支（直接下单对话框「所属主体：多主体」tag）；状态 tag/筛选/审核面板逻辑零改动（记录粒度变化对前端透明——contracts 数组只是更细了） | - |

### 验证

- `npm run build` 0 error；lint 0；替换后残留「合同」仅剩 script/style 注释（2 处，保留）。

---

## 2026-10-19 ｜ 新增：ADR-012 §5.1 商务接手机制前端（接手/转交 + 商务负责人列与筛选）

**关联任务**：配合后端 claim 接口与 review 接手人守卫（见后端 changelog 同日条目 + `docs/adr/ADR-012.md` §5.1）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **API 封装**：`claimProject(id)`（接手/转交）、`userOptions()`（商务账号选项）+ `UserOption` 类型 | `src/api/index.ts` |
| 2 | 新增 | **项目列表**：① 「商务负责人」列（username→name(username) 映射，空显示「未指派」）；② 筛选下拉（商务账号 + 「未指派/历史数据」档，businessOwner 账号关联查询）；③ 行操作：pending/active 且非自己负责 → 「接手」（success 绿）/「转交」（info 灰），二次确认后调 claim 并刷新；生态人员按钮禁用（tooltip 提示）；④ 抽屉商务负责人展示同步映射 | `src/views/sales/projects/index.vue` |
| 3 | 修改 | **编辑页审核面板**：按接手人控权——`canReviewEdit = canWrite && (isAdmin \|\| businessOwner === 当前 username)`；非接手人面板顶部橙色 alert + 「接手此单/转交给我」按钮，单价/金额输入禁用，底部「确认下单/驳回」隐藏改为接手按钮；接手成功后 db 镜像刷新，按钮自动翻转为可编辑态 | `src/views/sales/projects/create.vue` |

### 验证

- `npm run build` 0 error；lint 0；接手机制全链路冒烟见后端 changelog 同日条目。

---

## 2026-10-19 ｜ 新增：ADR-012 生态人员下单「待审核」前端配套（状态 tag / 审核面板 / 免填金额）

**关联任务**：配合后端 pending 状态机与 `POST /projects/{id}/review`（见后端 changelog 同日条目 + `docs/adr/ADR-012.md`）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **待审核状态**：`ProjectStatus` 联合类型 + `PROJECT_STATUS` 标签映射加 `pending = 待审核`（warning 橙）——列表 tag、筛选下拉（PROJECT_STATUS 遍历自动生成）、抽屉/详情合同 tag 全部自动生效 | `src/types.ts` |
| 2 | 新增 | **订单审核 API 封装** `reviewProject(id, {action, reason?, items?})`（confirm 带行级改价 / reject 带原因） | `src/api/index.ts` |
| 3 | 新增 | **项目列表审核入口**：操作列与快览抽屉底部对 pending 项目显示「审核订单」（仅商务/管理员，warning 色，跳编辑页）；生态人员仅见「待审核」tag；页头流程说明补充待审核环节 | `src/views/sales/projects/index.vue` |
| 4 | 新增 | **编辑页审核面板**（编辑态 + `pending` + canWrite 时替代只读合同清单）：按合同分区，行级控件随计价模式切换——unit 行「实际单价」输入（金额实时派生）、amount 行「合同金额（整数元）」输入（参考单价≈反算展示）、遥感明细行只读带提示；合同合计/项目总金额实时重算；底部「确认下单」（校验+二次确认+仅传改过的行）/「驳回」（原因必填 prompt）/「保存基本信息」；成功后跳详情页。生态人员视角：只读合同清单 + 橙色 alert「已提交商务确认」 | `src/views/sales/projects/create.vue` |
| 5 | 修改 | **项目详情页适配**：头部「编辑」按钮 pending 时变「审核订单」（warning 色）；合同卡 pending 分支——商务显示「审核订单」按钮、生态人员显示「待审核（等商务确认）」，不提供交付/终止快捷（后端对 pending 一律 400）；合同区说明补充待审核派生规则 | `src/views/sales/projects/detail.vue` |
| 6 | 修改 | **购物车生态人员免填金额**：amount 模式行金额输入对 viewer 放开必填（占位符「整数元（可留空）」、tooltip「留空按 挂牌价×数量 计价，商务确认订单时可再调整」、空值不再标红）；小计/下单预览金额留空时按挂牌价×数量取整占位（与后端回退口径一致）；结算成功提示 viewer 专属「已提交商务确认（数量已锁定）」；商务金额必填规则不变 | `src/views/cart/index.vue` |

### 验证

- `npm run build` 0 error；lint 0；后端全链路冒烟见后端 changelog 同日条目。

---

## 2026-10-19 ｜ 修改：撤销交付提示体现合同联动（配合后端状态回滚修复）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 交付记录页「撤销交付」：确认弹窗关联合同的记录提示「并把关联合同回退到「进行中」（明细重新锁定，可再次交付）」；成功提示按 `contractId` 区分「已撤销：产品数量已回退，关联合同已回退「进行中」」/「已撤销并生成调整流水」。撤销后 bootstrap 刷新，销售项目详情状态同步恢复「进行中」 | `src/views/sales/outbound/index.vue` |

### 验证

- `npm run build` 0 error；lint 0（后端联动逻辑冒烟见后端 changelog 同日条目）。

---

## 2026-10-19 ｜ 修复：全局主按钮样式覆盖误伤 plain 按钮（文字不可见）

**关联任务**：项目抽屉「查看详情」按钮渲染成空白蓝块的根因修复。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | 全局 `.el-button--primary` 实心蓝覆盖**未排除 `is-plain`**，导致 `type="primary" plain` 按钮被刷成实心蓝底，而 plain 文字色仍是主题蓝（蓝底蓝字不可见，典型现场：销售项目抽屉「查看详情」按钮显示为空白蓝块）。两条规则（默认/hover）均补上 `:not(.is-plain):not(.is-text):not(.is-link)` 排除，plain/text/link 恢复 Element 默认渲染 | `src/styles/global.css` |

### 验证

- 全平台 `type="primary" plain` 按钮仅此 1 处（修复目标本身）；`npm run build` 0 error。

---

## 2026-10-19 ｜ 修改：销售项目四项优化（抽屉状态变更 / 编辑页重构 / 交付记录列调整）

**关联任务**：销售项目页功能优化（用户指定 4 点）。编号时间戳方案见后端 changelog 同日条目。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **项目快览抽屉状态变更**：底部操作区新增「交付 / 终止」——商务/管理员双按钮（走项目级批量快捷 `PATCH /projects/{id}/status`，对全部进行中合同批量执行，确认弹窗说明影响范围）；生态人员仅「终止」（限自己项目，后端校验归属）。展示条件：名下有进行中合同且项目未终止 | `src/views/sales/projects/index.vue` |
| 2 | 修改 | **抽屉不展示合同编号**：合同行首的 HT 编号移除，保留 客户 + 主体/状态 tag + 金额 | `src/views/sales/projects/index.vue` |
| 3 | 修改 | **编辑页重构**（编辑/新建分流为两套模板）：编辑态进入即预填全部已有数据（基本信息/日期/金额/备注，onMounted 从 db 镜像）；布局 = ① 基本信息（名称/生态人员/商务负责人/两个日期，2 列网格）② **金额信息 4 卡**（报价金额/已回款可编辑 + 合同合计/未回款派生只读，统一浅底卡片、无步进按钮）③ 备注 ④ 合同清单（**只读概览**：客户+主体/状态 tag+合同金额，明细逐行 名称×数量 金额）；viewer 的 rep 仍只读 | `src/views/sales/projects/create.vue` |
| 4 | 修改 | **交付记录页**：移除「交付单号」列（搜索/占位符同步去掉单号）；「关联合同」列改 **客户-产品主体** 命名（如「客户A-安徽天枢智算人工智能科技有限公司」，tooltip 完整展示，纯文本不跳转） | `src/views/sales/outbound/index.vue` |
| 5 | 新增 | API 封装：`changeProjectStatus(id, status, reason)`（项目级批量状态快捷，抽屉用） | `src/api/index.ts` |

### 验证

- `npm run build` 0 error；lint 0；
- 冒烟：新建 2 客户项目 → 同秒生成 `SP-2026101915432005` + `HT-...21`/`HT-...86`（随机位防碰撞生效）；测试数据已清理。

---

## 2026-10-19 ｜ 修改：板块名精简（去掉"产品及服务"后缀）+ 清除「入库/出库」字样（纯文案，无逻辑变更）

**关联任务**：① 菜单及页面板块名按用户口径精简；② 平台不出现「入库/出库」仓储类字样（映射：入库→登记、出库→交付，与既有「登记产品」「交付」口径一致）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **板块名精简**（types.ts BOARDS 标签为单一事实源，菜单/面包屑/页面标题/筛选下拉自动同步）：具身智能产品及服务→具身智能、卫星产品及服务→卫星服务、软件产品及服务→软件产品、算力产品及服务→算力服务（硬件产品不变）；菜单组标题「产品及服务」保留 | `src/types.ts`, `src/layouts/MainLayout.vue`, `src/views/assets/compute.vue` |
| 2 | 修改 | **入库→登记**：概览列头「入库数量」→「总数量」；「入库合计」→「总数量」；「入库时间/日期/月份」→「登记时间/日期/月份」；「入库登记」→「登记」；「补入库/补充入库」→「补登记/补充登记」；「按原始个数入库」→「按原始个数登记」；「核入入库后登记」→「核入后登记」；「登记入库后生成」→「登记后生成」；流水类型 purchase_in 标签「入库」→「登记」；各板块 desc/rule 描述同步（embodied「登记、数量与销售追踪统一台账」「按套登记与销售」、hardware「核入后登记」） | `src/views/dashboard/index.vue`, `src/views/assets/*`, `src/views/cart/index.vue`, `src/views/settings/base.vue`, `src/types.ts` |
| 3 | 修改 | **出库→交付**：菜单/面包屑/页头「出库记录/销售出库记录」→「交付记录/销售交付记录」；「已出库」→「已交付」（概览列头/详情抽屉）；「序列号出库管理」→「序列号交付管理」；「生成/撤销出库记录」→「生成/撤销交付记录」（销售项目列表/详情、产品详情说明、购物车说明「执行『交付』即生成交付记录」）；补录对话框「出库性质/类型/日期/明细/单号」→「交付…」；流水类型 sale_out 标签「销售出库」→「销售交付」；「出入库流水」页签 → 「数量流水」；「已完成出库」→「已完成交付」 | `src/layouts/MainLayout.vue`, `src/views/sales/outbound/index.vue`, `src/views/sales/projects/*`, `src/views/assets/detail.vue`, `src/views/cart/index.vue`, `src/views/settings/users.vue`（日志筛选「出库」→「交付」）, `src/types.ts`, `src/constants.ts` |
| 4 | 不变 | 路由路径（/sales/outbound）、英文枚举（purchase_in/sale_out/shipped）、CK- 单号前缀、代码字段（shippedQty/inboundDate）均不变；仅用户可见文案 | - |

### 验证

- `grep -rn "入库\|出库\|具身智能产品及服务\|卫星产品及服务\|软件产品及服务\|算力产品及服务" frontend/src` 残留 **0**；
- `npm run build` 0 error；lint 0；后端 `py_compile` 通过、`/api/health` ok。

---

## 2026-10-19 ｜ 修改：全平台「资产/库存」术语切换为对外视角「产品及服务」（纯文案，无逻辑变更）

**关联任务**：对外产品平台视角调整——内部"资产"改为面向客户的"产品及服务"分类。
执行依据：`docs/asset-inventory-rename-checklist-20261019.md`（2026-10-19 全盘检查清单）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **板块（菜单/面包屑/下拉/标题）重命名**：具身智能→具身智能产品及服务、卫星服务→卫星产品及服务、软件库存→软件产品及服务、硬件库存→硬件产品、算力服务→算力产品及服务；菜单组「资产管理」→「产品及服务」 | `src/types.ts`, `src/layouts/MainLayout.vue` |
| 2 | 修改 | **平台名**：「蜂云资产管理平台」→「蜂云产品及服务平台」（顶栏/登录页/index.html 标题） | `src/layouts/MainLayout.vue`, `src/views/login/index.vue`, `index.html` |
| 3 | 修改 | **字段/列头/按钮/弹窗/提示全量替换**：资产→产品（产品名称/编号/类型/状态、资产台账→产品台账、登记/编辑/删除产品、关联产品、待关联产品、产品交付物设置、产品变更 等）；库存按语义映射：库存数量→可用数量、可售库存→可用数量、库存不足→可用数量不足、库存可售/暂无库存→可售/已售罄（状态 tag）、锁定库存→锁定数量、扣减库存→扣减数量、库存进度→数量进度、库存与归属→数量与归属、库存自动判定/限制→数量自动判定/限制 等；全量覆盖 登录/概览/产品列表/详情/创建/算力/购物车/销售项目（列表/创建/详情）/出库/基础设置（交付物/生态人员/账号与审计）/下单对话框/遥感明细选择器/常量 note（约 150 处用户可见文案） | `src/views/**`, `src/components/**`, `src/constants.ts`, `src/types.ts` |
| 4 | 不变 | 仅文案替换：路由路径（`/assets/**`）、API 路径、字段名（assetId 等）、英文枚举值（in_stock/no_stock/asset_change）、代码注释口径同步（便于后续检索）均未改逻辑；「入库/出库」等动词语不属目标字样，保留 | - |

### 验证

- `grep -rn "资产\|库存" frontend/src index.html` 残留 **0**（含注释已同步）；
- `npm run build`（vue-tsc + vite）0 error；lint 0。

---

## 2026-10-16 ｜ 修改：遥感数据「资产总数」改按「期」显示 + 卫星Token 单价去掉「约/≈」前缀

**关联任务**：平台优化第三轮（纯展示文案微调，无逻辑变更）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **资产列表「资产总数」列**：遥感数据（容器资产）行由「N 份明细」改为「N 期」（遥感明细按期售卖，quantity 对容器仍无意义） | `src/views/assets/list.vue` |
| 2 | 修改 | **包量定价（amount 模式，卫星Token）单价展示去掉「约/≈」前缀**（数值与「元/万Token」单位保留）：a) 资产列表「销售单价」列 `≈¥x/万Token` → `¥x/万Token`；b) 资产列表快览抽屉「约 ¥x/万Token（参考）」→ `¥x/万Token（参考）`；c) 资产详情页同改；d) 购物车行单价同改；e) 派生参考单价 `derivedUnitPrice`（项目详情/编辑明细、下单对话框）`约 x.xxxx 元/万Token` → 直接数值 | `src/views/assets/list.vue`, `src/views/assets/detail.vue`, `src/views/cart/index.vue`, `src/types.ts` |

### 验证

- `npm run build`（vue-tsc + vite）0 error；
- 全局检索 `约 ¥` / `≈` 无残留（`derivedUnitPrice` 内注释已同步更新）。

---

## 2026-10-16 ｜ 新增：资产列表「销售单价」列 + 销售项目对生态人员开放（可见性/权限收敛）

**关联任务**：平台优化两项需求（1 资产列表加销售单价列；2 销售项目生态人员可见自己下单的）。可见性过滤在后端 bootstrap 完成，前端仅做路由/菜单/按钮权限收敛。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **资产列表「销售单价」列**（库存数量与状态之间）：定宽 120 + 居中 + `show-overflow-tooltip`（过长省略、hover 显示全文）。口径与抽屉一致：unit 模式 `formatMoney`（repeatSale 带 `/unit`）；amount 模式紧凑参考值「≈¥x/万Token」；遥感容器/无单价显示「-」 | `src/views/assets/list.vue` |
| 2 | 修改 | **viewer 路由/菜单放开「销售项目」**：`viewerAllowedPath` 放行 `/sales/projects` + `/sales/projects/:id/(detail|edit)`（新建/出库仍禁）；侧边栏 viewer 区新增「销售项目」独立菜单项（销售管理整组仍不可见） | `src/router/index.ts`, `src/layouts/MainLayout.vue` |
| 3 | 修改 | **项目列表页 viewer 收敛**：新增 `canEditRow = canWrite \|\| isViewer`（可见行均是自己项目）——「编辑」对 viewer 解禁（后端同校验归属+rep 保护）；「新增销售项目」「删除」仍禁用 + READONLY_TIP | `src/views/sales/projects/index.vue` |
| 4 | 修改 | **项目详情页 viewer 收敛**：新增 `canOwn = canWrite \|\| isViewer`——「编辑」（active）与合同「终止」（active/delivered 撤销出库）对 viewer 解禁；「交付」保持仅商务/管理员（tooltip「交付需商务人员/管理员操作」）；越权 URL 访问 → 后端过滤后 el-empty「未找到该销售项目」 | `src/views/sales/projects/detail.vue` |
| 5 | 修改 | **项目编辑页 viewer 收敛**：新建模式进入即拦截（warning + 回列表，「新建请通过下单入口」）；编辑模式项目不存在/非自己（镜像无此项目）→ warning + 回列表；「生态人员」选择器 viewer 只读（与后端 rep 忽略口径一致） | `src/views/sales/projects/create.vue` |
| 6 | 修改 | **下单对话框 viewer rep 自动带自己 + 只读**：`reset()` 时 viewer 的 `form.rep` 锁定为当前用户姓名（选择器 disabled、不可清空，placeholder「本人」）；商务/管理员仍可代选。保证「自己下单」与 rep 口径一致 | `src/components/SalesOrderDialog.vue` |

### 验证

- `npm run build`（vue-tsc + vite）0 error；
- 临时库冒烟（8020）：viewer 可见性/越权 403/rep 禁改/终止放行/交付拦截 全过（详见后端 changelog 同日条目「自测」）。

---

## 2026-10-16 ｜ 修复：业务逻辑 bug 2 项（金额口径 / 合同金额静默丢弃）+ cart/index.vue 存量类型错误

**关联任务**：docs/business-logic-bugs-20261016.md 清单前端部分（#1、#8）；#1/#2 后端对应修复见后端 changelog 同日条目。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 ⚠️ | **availableValue 排除 amount 模式资产**：包量定价（卫星Token）资产返回 0——其 `salePrice` 为「元/万Token」参考值（ADR-008 不参与计价），`quantity` 为 Token 个数，两者相乘不是金额（此前首页/板块「可售金额」被污染虚高）。该类资产金额口径以合同 `contractAmount`（整数元）为准，已在项目/合同统计中体现。仅改 `types.ts` 纯函数，UI 布局/展示字段不变 | `src/types.ts` |
| 2 | 修复 | **unit 模式直接下单合同金额改只读**：后端 `_create_project_core` 对 unit 模式恒按 `price×qty` 权威重算（contractAmount 入参不采信），对话框中可编辑的「合同金额（元）」用户改值会被静默丢弃且无提示——改为 `:readonly="!hasAmountItem"`（amount 模式仍可编辑），placeholder 同步为「按 单价×数量 自动计算」。所见即所得，字段/布局不变 | `src/components/SalesOrderDialog.vue` |
| 3 | 修复 | **cart/index.vue 存量类型错误**（本次构建时发现，非本轮引入）：`CartRow.rsItem` 由可选属性 `rsItem?: RsItem` 改为显式 `rsItem: RsItem | undefined`（computed map 恒返回该键，可选属性使 filter 类型谓词 `r is CartRow` 不可赋值，TS2677/TS2769）。纯类型层修正，运行时行为与 UI 零变化 | `src/views/cart/index.vue` |

### 验证

- `npm run build`（vue-tsc -b && vite build）0 error 通过（修复前存在 cart/index.vue 2 个存量 TS 错误导致构建失败，已用 git stash 对照确认非本轮引入）；
- 行为回归：amount 模式下单对话框「合同金额（整数元）」仍可编辑（整数元校验不变）；unit 模式只读展示自动计算值；看板「可售金额」不再计入卫星Token 资产（seed 3 条）。

---

## 2026-10-16 ｜ 修改：对外页面（资产列表 + 抽屉）移除「累计售卖金额」展示（ADR-011）

**关联任务**：ADR-011（资产管理页对外口径收敛）——资产管理页为对外页面，资产列表与资产抽屉不得展示累计售卖金额（soldAmount 汇总），只保留「销售单价」口径。仅改 `list.vue`；`detail.vue`、首页概览、销售管理页（内部页面）保持现状不动。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 删除 | 抽屉「关键信息」区 repeatSale 普通资产 3 行补偿改为 2 行：保留 数据规模 / 售卖次数，移除「累计售卖金额」（formatMoney(soldAmount)）行 | `src/views/assets/list.vue` |
| 2 | 删除 | 抽屉「关键信息」区遥感容器 3 行改为 2 行：保留 明细份数 / 已售次数，移除「累计售卖金额」（formatMoney(dRsSoldAmount)）行；`dRsSoldAmount` computed（delivered 合同该资产明细 amount 求和）无其他引用，一并删除 | `src/views/assets/list.vue` |
| 3 | 确认 | 列表表格列检查：现有列为 资产名称/类型/所在主体/资产总数/锁定数量/售卖数量/库存数量/状态/操作，**本无**「累计售卖金额」列（或 soldAmount 展示列），无需删除；「销售单价」仅存在于抽屉（含 amount 模式「约 ¥x/万Token（参考）」口径），保留不动 | `src/views/assets/list.vue` |

**验证**：`npx vue-tsc --noEmit` 0 error；`grep -E 'soldAmount|10000|万元' list.vue` 代码 0 命中（仅注释中说明性文字提及「不展示累计售卖金额」）；`detail.vue` 未改动。未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 资产快览抽屉信息统一重构（方案 B：全类型去指标卡）

**关联任务**：抽屉信息统一重构（用户确认方案 B + 全类型去指标卡）——移除全部类型的 `dr-metrics` 指标卡，数字按类型分流补偿；关键信息字段、最近动态、视觉层级全类型统一。仅改 `list.vue`，后端零改动。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 删除 | 抽屉 `dr-metrics` 指标卡区块整体移除（非 repeatSale 4 卡 / repeatSale 3 卡均不再渲染），`.dr-metrics*` / `.m-cell` / `.m-label` / `.m-value` / `.m-unit` / `.m-purple` / `.m-hl` 样式一并清理；数字补偿：扣量资产保留在「库存进度」条图例（已出库/锁定/可售/入库合计，现状确认完整） | `src/views/assets/list.vue` |
| 2 | 新增 | repeatSale 普通资产关键信息区新增 3 行：数据规模（quantity + unit）、售卖次数（soldCount + 次）、累计售卖金额（formatMoney(soldAmount)）；遥感容器关键信息区新增 3 行：明细份数（db.rsItems 按 assetId 计数 + 份）、已售次数（`dRsSoldTotal` = 该资产明细的 dSoldMap 值求和）、累计售卖金额（`dRsSoldAmount` = db.contracts 中 delivered 合同该资产 itemId 非空明细的 amount 求和，与已售次数同口径） | `src/views/assets/list.vue` |
| 3 | 重构 | 关键信息两套（普通/容器）合并为全类型统一字段：销售单价 / 产品说明(spec) / 入库时间 / 有效期 / 备注(有值才显示) + 上述按类型追加行；销售单价行：unit 模式 formatMoney（repeatSale 带 /unit）、amount 模式「约 ¥x/万Token（参考）」、遥感容器弱文字「按明细定价」（新增 `.iv-weak`）；移除容器版 主体/状态/可重复售卖 三行（头部已有）；板块规则说明条（boardMeta.rule）全类型统一显示 | `src/views/assets/list.vue` |
| 4 | 重构 | 最近动态全类型统一：操作日志 + 出入库流水合并、时间倒序前 8 条、细线时间线 `.rs-tl`（原仅容器）；删除普通版纯流水列表（`flow-row` 模板与样式）及「（关联销售 N 项）」标题计数；段弱说明统一为「操作日志与出入库流水合并，倒序前 8 条 · 关联销售 N 项」；`dFlows` computed 移除 | `src/views/assets/list.vue` |
| 5 | 修改 | 视觉层级统一：`.sec-title` 13px → 15px（全类型大标题），`.sec-title-lg` 类及样式删除；每段补弱说明：产品清单「合同产品清单文件，支持在线预览」/ 关键信息「资产基础信息与销售口径」/ 交付物「该类型标准交付包」/ 库存进度「按库存扣减口径」 | `src/views/assets/list.vue` |

### 兼容性说明

- 保留不动：遥感「可售明细」插槽（关键信息之后、交付物之前）、repeatSale 说明条（仅 repeatSale 非容器）、产品清单/交付物区块、抽屉头部与底部按钮、容器不显示库存进度条与 repeatSale 说明条；
- 业务逻辑零改动：加购（含遥感明细选择）、登记销售、编辑跳转、查看详情均走原有函数；金额展示全部 formatMoney 元口径，无 EP 默认色。

### 验证

- `npx vue-tsc --noEmit` 0 error；
- dev :5173 逐一类走查（agent-browser，admin）：① 非 repeatSale「松延人形机器人M1」（CH-EMB-004）：无卡片、进度条图例完整（已出库 0/锁定 0/可售 35/入库合计 35 套）、关键信息 5 行、最近动态为时间线；② repeatSale「德数交遥感数据」（CH-SAT-012）：无卡片、含 数据规模 16 期 / 售卖次数 0 次 / 累计售卖金额 ¥0.00（与库内 soldCount/soldAmount 一致）、单价 ¥3,125,000.00 / 期；③ 遥感容器「遥感数据-2026」（CH-SAT-029）：无主体/状态/重复售卖行、单价行「按明细定价」、明细份数 2 份 / 已售次数 0 次 / 累计售卖金额 ¥0.00（与库内 rs_items=2、delivered 合同 0 条一致）、可售明细表格正常；④ 卫星 Token（CH-SAT-003，amount 模式）：单价行「约 ¥33333.33/万Token（参考）」；抽屉打开/加购/登记销售/编辑/查看详情入口均正常；未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 修改：遥感登记提示条移位 + 数量单价卡隐藏（ADR-011）

**关联任务**：ADR-011（遥感数据容器资产登记体验）——用户截图反馈：① info-bar 提示条位于表单很下方（到期时间之后），应紧跟「资产类型」；② 容器资产的数量/单价无意义（数量=明细数派生、单价在明细上），「数量单价」卡应隐藏。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `isRemote` 提示条（浅蓝 info-bar「遥感数据为容器资产，保存后请在资产详情「可售明细」页签维护 省/精度/月份 明细」）从基本信息卡之后移至基本信息 grid 内「资产类型」下拉正下方（资产名称之前），样式不变；补 scoped 规则 `.form-grid .info-bar { margin-bottom: 18px }` 与表单行距对齐 | `src/views/assets/create.vue` |
| 2 | 修改 | `isRemote` 时整个「数量单价」form-card（计量单位/资产总数/销售单价/可重复售卖）加 `v-if="!isRemote"` 隐藏；新建与编辑模式（isEdit）均生效，回显值不受影响 | `src/views/assets/create.vue` |
| 3 | 修改 | 提交兜底：`isRemote` 时 payload 覆盖 `quantity: 1`（后端 AssetIn 对 quantity 有 >0 校验）、`salePrice: 0`（单价忽略）、`unit: '份（可售明细）'`（与 constants.ts CATEGORY_UNITS 遥感条目一致）；其余类型 payload 完全不变 | `src/views/assets/create.vue` |

**验证**（agent-browser 实测，admin @ 127.0.0.1:5173 + 后端 :8000）：① 类型切到「遥感数据」→ 提示条紧跟类型下拉正下方、数量单价卡消失（snapshot 无「数量单价」/计量单位/资产总数/销售单价节点）；切回其他类型卡片恢复（选遥感前快照已含全部字段，回归通过）；② UI 填名称+主体后点「创建资产」→ 200 跳转 /assets/31/detail，落库 `qty=1 / unit=份（可售明细） / price=0.0`（bootstrap 核对）；③ 同 payload curl 直建（id=30）亦 200。两个测试资产（30/31）已 DELETE 清理（均 `{"ok":true}`）。`npx vue-tsc --noEmit` 0 error；`grep -E '10000|万元' create.vue` 0 命中；未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 修复：批量加购误把遥感数据父资产加进购物车（ADR-011 补漏）

**关联任务**：ADR-011（遥感数据明细售卖）——单行「加入购物车」已走 RsItemPicker 选明细，但顶部批量加购 `batchAddToCart` 对勾选行统一走 `addCartBatch`，父容器被直接加购（后端不拦，前端必须拦死）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `batchAddToCart` 勾选行按 `type === '遥感数据'` 分流：① 非遥感行照旧走 `addCartBatch`，成功/库存不足提示文案沿用原文案；② 遥感父资产行**不加入、不发 batch 请求**，`ElMessage.info` 提示「遥感数据需逐份选择明细，请单独点击对应行的"加入购物车"」；③ 勾选中只有遥感行时仅出提示直接 return；④ 遥感行勾选状态保留——`addCartBatch` 内部 `afterWrite()` 会全量刷新（表格行对象被替换），故 `clearSelection()` 后按 id 从新 `list` 重新取行 `toggleRowSelection` 勾回（不能直接 toggle 旧行对象）；请求失败（catch）时勾选全部保留（原行为） | `src/views/assets/list.vue` |

**验证**（agent-browser 实测，admin @ 127.0.0.1:5173，遥感父资产 id=29 含 2 份明细 / 普通卫星数据 id=17）：① 勾选 29+17 → 点「加入购物车（2）」→ 双提示（info 遥感提示 + success「已将 1 项资产加入购物车」），bootstrap.cart = `[(17,1)]`（29 未进），勾选态 `[true,false]`（29 保留、17 已清）；② 只勾 29 → 点「加入购物车（1）」→ 仅 info 提示、无 batch 请求，cart 不变 `[(17,1)]`，29 仍勾选；③ 只勾 17 → 行为与改前完全一致（success 提示 + 勾选全清）。测试购物车行已清理（DELETE 200，cart=0）。`npx vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 修改：遥感明细选择弹窗 92vw 限宽修复 + 三处使用点回归（ADR-011）

**关联任务**：ADR-011（RsItemPicker 弹窗放大，尺寸调整本体已于 2026-10-15 完成：width 520px→880px、树区 min 320px/max 55vh）。本次走查发现小屏限宽规则未生效并修复。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `max-width: 92vw` 原写在 scoped 块（编译为 `.el-dialog[data-v-xxx]`），但 el-dialog 内容 teleport 到 body 后 `.el-dialog` 节点不带本组件 data-v 属性 → 规则存在但不命中，小屏下弹窗会超 92vw。改为 el-dialog 加自定义 class `rs-picker-dialog` + 非 scoped 样式块（与 list.vue 抽屉样式同模式） | `src/components/RsItemPicker.vue` |

**验证**（agent-browser 实测，admin @ 127.0.0.1:5173，三处使用点全过）：① list.vue 加购入口（遥感行「加入购物车」）→ 弹窗 880px、标题「选择可售明细 · 遥感数据-2026」、footer「已选 0 份 + 取消/确定加入」；② list.vue 登记销售入口（快览抽屉「销售」）→ 880px、确认按钮「确定登记」；③ detail.vue 登记销售入口 → 880px、树区 min-height 320px / max-height 348px（=55vh @ 当前视口）/ overflow-y auto、6 个树节点三级展开正常；`max-width` 实测 1177.6px（=92vw @ 1280 视口）生效。顶部浅蓝说明条与底部「已选 N 份 + 取消/确定」区样式未动。`npx vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 修复：setCartAmount 误删购物车行 + 清理 CheckoutInput.items 死字段（架构门禁打回，T1f 契约 bug）

**关联任务**：T1f（包量定价 ADR-008）门禁打回修复。后端契约不变（`PUT /cart/{id}` 本就接受 qty+amount，api.md 实测 `{"qty":1,"amount":5000000}` 通过）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | ⚠️ **致命**：`setCartAmount(id, amount)` 只发 `{ amount }`，后端 `PUT /cart/{id}` 对 `int(request.get("qty", 0))` 缺省=0 → `set_cart_qty` 对 qty<=0 执行删行，用户一填合同金额购物车行即被删。签名改为 `setCartAmount(id, qty, amount)`，body 传 `{ qty, amount }`；唯一调用处（购物车金额输入失焦 `onAmountChange`）回传该行当前 `row.cart.qty`。金额输入从此绝不触发删行（qty=0 语义仅由数量输入/DELETE 触发） | `src/api/index.ts`、`src/views/cart/index.vue` |
| 2 | 修改 | 契约清理：删除 `CheckoutInput.items?` 死字段（后端 `CheckoutInput` 无此字段，Pydantic 静默忽略；权威金额已由 PUT/PATCH 持久化到 `cart_items.amount`），`CheckoutInput` 收敛为 `OrderFields` 类型别名；`onOrderSubmit` 删除 amountItems 拼装逻辑，结算只传订单字段。「amount 模式行未填金额则拦截结算」的前置校验保留不变 | `src/api/index.ts`、`src/views/cart/index.vue` |

**验证**：接口走查（admin）——Token 资产（pricingMode='amount'）加购 → `PUT {qty:2, amount:5000000}` 200，行仍在（qty 不变）金额生效 → 再 `PUT {qty:3}` 金额仍在 → 补客户后 checkout 200，`item.amount=5000000`，购物车清空；测试项目已删除、库存锁定回滚。`npx vue-tsc --noEmit` 0 error；未执行 build/deploy，dev server HMR 生效。

---

## 2026-10-16 ｜ 三份 ADR 前端落地：包量定价 pricingMode='amount'（ADR-008）+ viewer 权限对齐（ADR-009）+ 遥感数据资产类型（ADR-010）

**关联任务**：T1f（包量定价）/ T4（viewer 权限对齐）/ T5f（遥感数据）/ T2f（前端自查）。后端并行开发中，字段名按 ADR + 任务契约先行实现。

### T1f 包量定价（ADR-008）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `Asset.pricingMode?: 'unit' \| 'amount'`（可选：bootstrap 未就绪时容错）+ `isAmountMode()` 判定；`CartItem.amount?`（元，整数，仅 amount 模式行）；`formatTokens(n)`（300000000→"3 亿"、137000000→"13700 万"、<1e4→原数+"个"，内部用 1e4/1e8 常量避免字面量）；`formatAssetQty(asset, n)`（amount 模式走 formatTokens，其余 formatWan）；`derivedUnitPrice(amount, qty)`（金额÷数量÷1e4 保留 4 位 +「约 …元/万Token」，仅展示不参与计价） | `src/types.ts` |
| 2 | 修改 | `SaleOrderInput.items` 加 `amount?`（整数元）；`CheckoutInput` 加 `items?: { assetId; amount }[]`（仅含 amount 模式行）；新增 `setCartAmount(id, amount)`（`PUT /cart/{id}` `{ amount }`，整数元，后端校验 int>0）；`AssetInput` 加遥感 4 字段（见 T5f） | `src/api/index.ts` |
| 3 | 修改 | **SalesOrderDialog（直接下单/购物车结算共用）**：`OrderItem` 加 `amount?`；`totalYuan` 按 pricingMode 分支（amount 行取合同金额：购物车模式取行内金额、直接下单取金额输入框）；直接下单 amount 模式——数量输入旁显示 `formatTokens(qty)`、摘要行显示派生单价（`derivedUnitPrice`）、「合同金额（整数元）」输入框 + 浅蓝说明条（「Token 资产按包量售卖，下单以合同金额（整数元）为准，参考单价不参与计价」）；**非整数/非正金额提交拦截**（`合同金额须为整数元`）；amount 模式跳过合同金额自动重算；submit items 携带 `amount`；unit 模式行为不变 | `src/components/SalesOrderDialog.vue` |
| 4 | 修改 | **购物车**：新增「合同金额（元）」列（仅 amount 行渲染，整数输入 `onAmountInput` 仅留数字位，失焦 `onAmountChange` → `setCartAmount`，失败回滚刷新）；未填金额行输入框置灰（`.cart-amount-empty` opacity .45）+ tooltip「请填写合同金额（整数元）后方可结算」，`openOrder` 前置校验标红拦截；行合计按输入金额算（`subtotal = c.amount`）；单价列 amount 行显示「约 ¥x/万Token」参考口径；数量列下补 `formatTokens` 提示；结算提交携带 amount 行 `items`；info-bar 补包量定价说明 | `src/views/cart/index.vue` |
| 5 | 修改 | **项目创建页合同清单明细行**：amount 模式行切换录入——数量（原数提交 + `formatTokens` 提示）、金额列改整数元输入（`onItemAmountInput`）、单价列改派生只读展示（`derivedUnitPrice` 带「约」）；`calcItemAmount` 双模式（amount 行 `price = round(amount/qty, 6位)` 派生，unit 行 `amount = qty×price` 不变）；选资产时 amount 资产不预填参考单价；提交校验「合同金额须为整数元」；「登记销售」预填 amount 资产 price=0 | `src/views/sales/projects/create.vue` |
| 6 | 修改 | **项目详情只读展示**：合同明细与存量明细两表的单价列 amount 资产改派生展示（`derivedUnitPrice` 带「约」，muted），数量列 amount 资产走 `formatTokens` | `src/views/sales/projects/detail.vue` |
| 7 | 修改 | **资产列表/详情/抽屉**：资产总数/可售/入库/锁定/已售/流水/关联数量统一 `formatAssetQty`（Token 资产显示「3 亿」等）；抽屉「销售单价」与详情「销售单价」amount 资产显示「约 ¥x/万Token（参考）」；创建/编辑表单 amount（卫星Token）时单价 label 改「参考单价（元/万Token）」+ 浅蓝 info-bar 说明，数量输入下补 `formatTokens` 展示 | `src/views/assets/list.vue`, `src/views/assets/detail.vue`, `src/views/assets/create.vue` |

### T4 viewer 权限对齐（ADR-009）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 购物车「清空购物车」`:disabled="!canWrite \|\| !db.cart.length"` → `:disabled="!db.cart.length"`（已登录即可用），移除 READONLY_TIP tooltip 包裹；页面内 `canWrite`/`READONLY_TIP` 导入随之移除（数量调整/删行/结算本已对三角色放开，核查无其它下单链路 canWrite 残留） | `src/views/cart/index.vue` |
| 2 | 修改 | 资产列表 `batchAddToCart` 删除 `isViewer` 逐条单加降级分支与「后端 POST /cart/batch 仅 admin/editor」过期注释，三角色统一走 `addCartBatch`；`isViewer` 导入移除。资产编辑类入口（登记资产/编辑/删除/交付物）保持 `canWrite` 不变 | `src/views/assets/list.vue` |
| 3 | 修改 | axios viewer 写白名单补 `POST /cart/batch` 与 `DELETE /cart`（清空），注释改为「下单链路全部 require_order（ADR-009）」；新增 `isLoggedIn` computed（注释说明与后端 require_order 对齐） | `src/api/index.ts`, `src/auth.ts` |

### T5f 遥感数据资产类型（ADR-010）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `Asset` 加 4 个可选字段 `province?/city?/resolution?（米）/imageDate?（YYYY-MM-DD）`（仅 type==='遥感数据' 使用）；`TYPE_TAG_CLASS` 加 `遥感数据: 'tag-blue'`；`CATEGORY_UNITS` 卫星板块加 `{ board:'satellite', type:'遥感数据', unit:'份（区域·精度·日期）', note:'按 省/精度/日期 三维唯一售卖' }`；新增 `PROVINCES`（31 省级行政区内置常量） | `src/types.ts`, `src/constants.ts` |
| 2 | 修改 | 资产列表：卫星二级页签扩为「全部 / 卫星 Token / 卫星数据 / 遥感数据」（`satelliteTab` 加 `'remote'` + 过滤分支）；遥感数据行次级行显示「省/市 · 精度m · 影像日期」摘要（`remoteSummary`）；板块说明文案补遥感数据与包量定价口径 | `src/views/assets/list.vue` |
| 3 | 修改 | 资产创建/编辑表单：类型选「遥感数据」显示专属字段组（.form-card：省份 el-select PROVINCES 必填 / 城市 el-input 选填 / 精度 el-select 0.5m·1m·1.5m·2m 存米数值 必填 / 影像日期 el-date-picker YYYY-MM-DD 必填，条件 validator 非遥感类型不校验）；**名称自动生成** `省+市+精度(m)+日期`（三维/日期 watch 实时联动，`remoteNameTouched` 手改后不再覆盖，切回遥感类型重置标记）；数量固定 1 输入禁用、计量单位固定「份（区域·精度·日期）」禁用、可重复售卖默认勾选；**提交前本地判重**（db.assets 同 province+city+resolution+imageDate 已存在 → 「已存在相同 省/市 + 精度 + 日期 的遥感数据资产」，编辑排除自身，后端 400 同文案兜底）；payload 非遥感类型 delete 4 字段；编辑模式 4 字段回显可改 | `src/views/assets/create.vue` |
| 4 | 修改 | 资产详情「基本信息」：遥感数据追加展示 省/市、精度（1.5m）、影像日期 3 个 info-item（`v-if="asset.type === '遥感数据'"`，非遥感不显示） | `src/views/assets/detail.vue` |
| 5 | 修改 | 项目创建页资产树卫星板块补「遥感数据」节点（与列表页签同口径） | `src/views/sales/projects/create.vue` |

### T2f 自查与验证

- `grep -rn "10000\|万元" frontend/src` = **0 命中**（formatTokens/derivedUnitPrice 内部用 1e4/1e8；期间消除 2 处误命中：占位符示例数字、注释字面量）。
- `npx vue-tsc --noEmit` = **0 error**；IDE 诊断 0 error；未执行 build/deploy（按约束禁止），dev server HMR 自动生效。

### 遗留风险（后端并行开发，联调待确认）

- `pricingMode` 由后端入库时置值（卫星Token→'amount'），前端表单不提交该字段；bootstrap 未返回该字段前 amount 分支不触发（unit 行为完全不变，可回退）。
- `PUT /cart/{id}` 的 `{ amount }` 入参、`POST /cart/checkout` 的 `items[]`、`POST /sales/order` items 的 `amount?` 为按 ADR 推断的契约，需与后端最终 schema 对齐（字段名已按任务书冻结）。
- 遥感数据判重前端走 db.assets 镜像，bootstrap 未就绪时本地判重为空集（后端 400 兜底生效）。

---

## 2026-10-16 ｜ 资产详情「操作记录」changes 散列文件名展示为原始名（历史数据兼容，纯展示层翻译）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 新增 `translateFileNames(text)`：整段文本中散列 storedName → 原始文件名（取 `db.files` 中 `name !== storedName` 条目，按 storedName 长度降序替换避免短名误伤，无映射散列原样回退）；资产详情操作记录页签 `log.changes` 渲染前经该函数翻译（全站 changes 消费处仅此 1 处）。不写库、不改数据 | `src/api/index.ts`、`src/views/assets/detail.vue` |

## 2026-10-16 ｜ 角色权限前端：展示名改名（商务人员/生态人员）+ 生态人员菜单收窄与下单链路放权（契约冻结）

**关联任务**：内部角色标识不变（`admin`/`editor`/`viewer`），仅改展示名与前端可见/可操作范围。生态人员（viewer）：菜单只留资产管理 + 购物车，默认落地 `/assets/embodied`；放权登记销售（直接下单对话框）与购物车全部操作（加购/改数量/改客户/删行/结算）；资产编辑类保持禁用 + tooltip。商务人员（editor）仅文案改名，行为一行未动。

**角色矩阵（本次定稿）**：

| 能力 | 管理员 admin | 商务人员 editor | 生态人员 viewer |
|---|---|---|---|
| 菜单 | 首页概览/资产管理/销售管理/基础设置 | 首页概览/资产管理/销售管理 | 资产管理 + 购物车（独立项，含角标） |
| 默认落地 | `/dashboard` | `/dashboard` | `/assets/embodied` |
| 路由可达 | 全部 | 除 `/settings/*` | 仅 `/assets/**`（排除 create/edit 页）+ `/cart`，其余静默重定向 `/assets/embodied` |
| 资产写操作（登记/编辑/删除/上传/交付物维护） | ✅ | ✅ | ❌ 禁用 + tooltip「生态人员无此操作权限」 |
| 加购（批量/单个）/改数量/改客户/删行/结算/直接下单 | ✅ | ✅ | ✅（本次放权） |
| 清空购物车 | ✅ | ✅ | ❌（后端 `DELETE /cart` 仍 require_editor，保持禁用） |
| 批量加购端点 `POST /cart/batch` | ✅ | ✅ | 前端降级为逐条 `POST /cart`（后端该端点仍 require_editor） |

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 展示名全量替换：`ROLE_LABELS` → 管理员/商务人员/生态人员（顶栏角色 tag 自动生效）；`READONLY_TIP` → 「生态人员无此操作权限」（全站禁用 tooltip 统一生效）；新增 `isViewer` computed；用户管理页 `ROLE_OPTIONS`/页面 desc/权限说明条同步新展示名与新矩阵描述 | `src/auth.ts`、`src/views/settings/users.vue` |
| 2 | 修改 ⚠️ | axios 请求拦截器 viewer 写兜底由「全部非 GET 拒绝」改为**下单链路白名单**（与后端 `require_order` 对齐）：`POST /cart`、`POST /cart/checkout`、`PUT/PATCH/DELETE /cart/{id}`、`POST /sales/order` 放行；其余非 GET（含 `POST /cart/batch`、`DELETE /cart` 清空）仍前端拒绝 + 后端 403 双保险 | `src/api/index.ts` |
| 3 | 修改 | 路由守卫新增 viewer 收窄：`/assets/**`（排除 `/assets/create` 与 `/assets/:id/edit` 写页面）+ `/cart` 可达，其余路由（看板/销售/出库/基础设置/资产创建编辑/404 兜底）静默重定向 `/assets/embodied`（viewer 登录后 `/`→`/dashboard` 亦被拦截回资产首页）；admin/editor 守卫行为不变 | `src/router/index.ts` |
| 4 | 修改 | 菜单收窄：viewer 隐藏「首页概览」与「销售管理」整组（基础设置本就 `v-if="isAdmin"`），新增独立「购物车」菜单项（ShoppingCart 图标 + 角标，可点）；admin/editor 菜单结构不变（销售管理内购物车项 `:disabled="!canWrite"` 保留，对两角色恒可点） | `src/layouts/MainLayout.vue` |
| 5 | 修改 | 资产列表：批量「加入购物车」与行级「加入购物车」去掉 `canWrite` 禁用（三角色可用；批量仅未勾选时禁用）；viewer 批量加购降级为逐条 `POST /cart`（后端 batch 端点 require_editor），失败项逐条收集提示；抽屉「销售」（登记销售对话框入口）去掉禁用；「登记资产」/行级「编辑」/抽屉「编辑」「去上传」保持禁用 + 新 tooltip | `src/views/assets/list.vue` |
| 6 | 修改 | 资产详情：「登记销售」（头部 + 销售关联空态）去掉禁用——admin/editor 仍跳销售创建页（原行为），viewer 直接打开 `SalesOrderDialog` 直接下单对话框（新增该对话框实例，`allow-qty-edit`，提交走 `POST /sales/order`，成功后停留本页提示）；「编辑资产」/「删除资产」/交付物新增/标记就绪/退回待完善保持禁用 + tooltip | `src/views/assets/detail.vue` |
| 7 | 修改 | 购物车页 viewer 放权：行级客户输入框去掉 `:disabled`（tooltip 恒为「结算时按客户分组生成合同」）、「移除」与「下单」去掉禁用（数量输入框本就未禁用，拦截器放行后生效）；「清空购物车」保持禁用 + tooltip（后端 `DELETE /cart` require_editor，且不在本次放权清单） | `src/views/cart/index.vue` |
| 8 | 修复（存量类型错误，为达成 vue-tsc 0 error） | create.vue `stockState` 由向 `noSellableStock(Asset)` 传部分对象改为同口径内联计算（`quantity - lockedQty - shippedQty <= 0`），清理未用 import（`noSellableStock`/`fileUrl`）；detail.vue `projectSubject` 兜底分支 `assetId: number\|null` 收窄后再调 `getAsset`；MainLayout 清理未用 `ElMessage` import | `src/views/assets/create.vue`、`src/views/assets/detail.vue`、`src/layouts/MainLayout.vue` |

- **grep 排查定夺**（全仓 `只读`/`可编辑`/`viewer`/`editor`）：角色语义处全改（auth.ts/users.vue/README 属文档未动）；其余命中均为**字段级只读/不可编辑**语义（types.ts 资产编号注释、SalesOrderDialog 主体只读/合同合计只读、项目「不可编辑」业务约束、compute 板块建设中只读、deliverables 版本完善后可编辑等）→ 与角色无关，不改。
- **回归**：admin 登录落地 `/dashboard`、菜单 4 组完整、tag「管理员」；editor 落地 `/dashboard`、菜单 3 组（无基础设置）、tag「商务人员」；READONLY_TIP 场景（viewer 编辑资产 tooltip）实测新文案生效；editor 全部按钮/路由行为一行未动（仅文案）。
- **agent-browser 实测**（127.0.0.1:5173）：viewer/123456 → 落地 `/assets/embodied`，菜单仅「资产管理 + 购物车」，tag「生态人员」；行级加购成功（角标「购物车 1」）→ 购物车页改客户「回归测试客户A」生效（PATCH 200）、数量框可编辑、点「下单」打开结算对话框（默认「采购订单」，字段可填，**未提交**）→ 直访 `/sales/projects`、`/dashboard`、`/settings/users`、`/assets/create` 全部重定向 `/assets/embodied` → 资产详情「登记销售」打开直接下单对话框（合同金额自动 ¥3,200,000.00，**未提交**）、「编辑资产」禁用且 hover tooltip DOM 断言 `TOOLTIP_OK`（「生态人员无此操作权限」）→ 测试购物车行已「移除」清理（DELETE 200，购物车为空）→ admin/editor 登录回归如上。备注：admin 密码曾被历史 API 测试改掉且无记录，本地开发库已重置为种子默认 123456。
- HMR 200 + IDE 0 error + `vue-tsc -b --force` 0 error；未执行 build/deploy（按约束禁止）。
- **给后端回归的提示**：viewer 现可过端点 = `POST /cart`、`PUT /cart/{id}`、`PATCH /cart/{id}`、`DELETE /cart/{id}`、`POST /cart/checkout`、`POST /sales/order`（均 `require_order`，已就绪）；`POST /cart/batch` 与 `DELETE /cart`（清空）仍 `require_editor` → viewer 403（前端已分别降级为逐条单加 / 保持禁用）。如后续要 viewer 直用批量加购与清空，需将两端点改 `require_order`。

---

## 2026-10-16 ｜ 销售项目「主体」项目级展示全部移除（多合同多主体，项目级主体无意义；合同级主体保留）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 项目列表删除「主体」列（`el-table-column label="主体"`，列宽让给其它列自然回正，计数/文字/金额对齐规则未动）；快览抽屉头部 `dr-sub` 行删除「· 主体 xxx」片段（抽屉内合同卡片的主体 tag 保留）；文件头列清单注释同步更新 | `src/views/sales/projects/index.vue` |
| 2 | 修改 | 项目详情头部信息行删除「所属主体」info-item（合同清单卡片上的主体 tag 未动） | `src/views/sales/projects/detail.vue` |
| 3 | 核实（无改动） | 创建/编辑页本无项目级「主体」输入框（subject 由后端按合同内资产派生）；payload 的 `subject: ''` 保留——后端 `ProjectInput.subject: str`（schemas.py L134）必填但 services 明确不采信（派生口径 ADR-007），空串合法；SalesOrderDialog 的「所属主体」由所选资产主体推导（单合同语义，跨主体混装显示「多主体」），非项目级，保留；资产详情销售关联「签约主体」三级兜底（项目→合同→资产）与资产自身「所在/归属主体」均为非项目级展示，保留 | `src/views/sales/projects/create.vue`、`src/components/SalesOrderDialog.vue`、`src/views/assets/detail.vue`（均未动） |

- HMR 200（5173：index.vue/detail.vue 模块编译 200）+ IDE 0 error + `vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-16 ｜ 附件展示统一为「上传时的原始文件名」（产品清单此前显示类型标签，全仓收口）

**关联任务**：平台展示与下载的文档名必须=上传时的原始文件名（后端 file_meta 映射 + Content-Disposition 已就绪）；修复产品清单块显示「产品清单（Word）」类型标签而非原始名的问题。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | 编辑/创建页产品清单块主显示由 `contractTypeLabel` 类型标签改为 `fileDisplayName(form.contractFile)`（原始文件名，无映射回退散列名），类型降为次级小字「产品清单 · Word」（新增 `.cu-sub` 样式）；预览 dialog 去掉 `:title` 类型标签覆盖，FilePreview 回退显示原始名 | `views/assets/create.vue` |
| 2 | 修复 | 快览抽屉产品清单块主显示由 `contractKindLabel` 类型标签改为 `fileDisplayName(drawerAsset.contractFile)`，次级小字「产品清单 · Word」（新增 `.contract-sub` 样式）；预览 dialog 同步去掉 `:title` 覆盖；下载仍走 `fileUrl`（后端响应头已带原始名，实测 Content-Disposition filename*=UTF-8 与原始名一致） | `views/assets/list.vue` |
| 3 | 核实（无改动） | 基础件 `fileDisplayName`（`api/index.ts` L394，db.files 查原始名、无映射回退散列名）与 `db.files` 镜像（bootstrap `files[]` 填充）仍在，未误删；全仓附件展示位收口：FilePreview 标题（`title \|\| fileDisplayName`）、编辑页/抽屉产品清单行、两处下载链接均已用原始名；交付物（detail.vue/settings/deliverables.vue）为命名记录非文件附件，featureDoc 无 UI 展示位，均无需改 | `components/FilePreview.vue`、`views/assets/detail.vue`、`views/settings/deliverables.vue`（未动） |

- HMR 200（5173：create.vue 模块 200）+ IDE 0 error + `vue-tsc --noEmit` 0 error；bootstrap 实测（admin，16 个 files 映射）：资产 5 产品清单 `a75dfb27412246a897bcb8adb55eb84a.docx` → 原始名 `大语言知识模型服务系统.docx`；`curl` 下载响应头 `content-disposition: attachment; filename*=UTF-8''%E5%A4%A7...docx`（解码=原始名）；agent-browser 实测（admin）：抽屉与编辑页产品清单主显示 DOM 均为「大语言知识模型服务系统.docx」+ 次级「产品清单 · Word」，预览弹层标题=原始名。未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 恢复资产「产品清单」附件（此前随功能清单一并误删，用户只要求删「功能清单」）

**关联任务**：恢复 create.vue 产品清单上传块 / list.vue 抽屉产品清单展示预览下载 / detail.vue 核实未动；功能清单（featureDoc）维持已删状态零改动。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复/恢复 | 按 git HEAD（0d1bfd5）旧代码逐字恢复产品清单链路（字段 `contractFile`，payload 走 `{...form}` 自动携带；后端 `update_asset` 字段级 patch 白名单含 `contractFile`，传了才更新，存量文件编辑保存不误清）：① 编辑/创建页「状态与备注」卡片备注下方恢复产品清单上传块（上传/回显/预览/替换/移除）+ 预览 dialog + `.contract-up` 样式 + `contractInputRef`/`uploading`/`previewVisible`/`pickContract`/`onContractPicked`/`previewContract`/`removeContract`/`contractTypeLabel` + import（`Document`/`Upload` 图标、`fileUrl`/`uploadFile`、`FilePreview`）；状态/备注两行排版（tag 上、提示下）保持重做后现状不变；② 快览抽屉恢复「产品清单」区块（已上传态预览/下载行 + 未上传态「去上传」）+ 预览 dialog + `previewVisible`/`openPreview`/`contractKindLabel` + import（`Document`、`fileUrl`、`FilePreview`）+ `.contract-*` 样式；期间新增的抽屉交互（row-click 分工/勾选/状态默认筛选）零回退 | `views/assets/create.vue`、`views/assets/list.vue` |
| 2 | 核实（无改动） | detail.vue 产品清单从未存在（HEAD 与现状均无 `contractFile` 引用），上轮仅删功能清单附件行——维持现状不动；功能清单（featureDoc）前端仅存 2 处类型声明（`types.ts`/`api/index.ts`，后端字段保留口径），页面/组件 0 使用残留 | `views/assets/detail.vue`（未动） |

- HMR 200（5173：create.vue / list.vue 模块编译 200）+ vue-tsc 0 error + IDE 0 error；agent-browser 实测（admin）：资产 2 编辑页产品清单回显「产品清单（Word）」+ 预览/替换/移除，抽屉产品清单可见且预览 dialog 正常打开；未做实际上传，无脏数据。未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 销售项目快览抽屉概览区删除「客户」行（客户信息在合同卡中每份都有，概览冗余）

**关联任务**：用户截图确认——抽屉「概览」区第一行「客户：N 位客户」整行删除。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 抽屉概览 info-grid 删除「客户」表单项（原模板 L320-326）；同步删除仅该行使用的 `dCustomerText`/`dCustomerTip` computed（原 L97-103）及 `.iv-tip` 样式（原 L519-523）；**保留** `contractTip` 函数（列表「关联合同」列 tooltip 唯一引用，L219）；剩余行（商务负责人/生态人员/预计签约日期/合同合计）为 info-grid-1 单列布局，自动回正无空洞 | `views/sales/projects/index.vue` |

- HMR 200（5173），IDE 0 error，`vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 销售项目列表三处优化（列对齐规则对齐资产列表 + 客户列改关联合同 + 抽屉合同卡资产展示调大）

**关联任务**：用户明确要求——① 销售项目列表列对齐规则对齐资产列表；② 「客户」列改「关联合同」（展示合同数，原独立「合同数」列删除）；③ 抽屉合同卡资产展示太小、布局不美观，重做为三层结构。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 列表列对齐按资产列表（`assets/list.vue`）规则逐列核对：文字类左（资产名称 L335 / 所在主体 L351）、计数/数量/状态类居中（资产总数 L354 / 锁定 L359 / 状态 L377）、操作列居中（L384）。实际改动 2 处：「关联资产」列 `align="right"`→`"center"`（计数类，依据 L354）；「项目名称」补显式 `align="left"`（与资产名称列同写法）。其余列（项目编号/生态人员/主体=左、项目状态/操作=居中、合同金额=右）已符合规则未动；资产列表无金额列与日期列，合同金额右对齐按任务规则保留、日期列维持左对齐（el-table 表头 align 默认跟随内容 align，表头与内容天然一致） | `views/sales/projects/index.vue` |
| 2 | 修改 | 「客户」列改「**关联合同**」：单元格展示 `contractCount`（空/0 → muted '-'，不渲染 tooltip）；客户信息由 hover tooltip 承载（`contractTip`：多合同「N 位客户：A、B、C」按 `db.contracts` 过滤该项目合同客户名去空拼接，单合同直接客户名，无客户名 → 空串不渲染 tooltip）——取舍说明：用户未要求 tooltip，但客户列删除后客户信息不能丢，tooltip 是最小侵入的承载位；**原独立「合同数」列删除**（与新列重复）；新列 `width=100 align="center"`（计数类居中，依据资产列表 L354）；原 `customerText` 函数删除（唯一调用点已移除） | `views/sales/projects/index.vue` |
| 3 | 修改 | 抽屉合同卡由「主行 + 12px muted 次级行挤一行」重做为三层结构：**第一层**（保持）合同号 mono + 客户 + 主体/状态 tag 左、合同金额右（600 右对齐）；**第二层（资产展示调大）** 明细资产逐行独立：资产名 13px `var(--text-body)`（`contractItemName` 新函数替代原 `contractItemSummary` 拼接，超长省略 + el-tooltip 全文）+ 数量「× N」12px muted 紧跟（`gap:4px` 行距）；**第三层** 锁定/交付日期 12px muted 左对齐（与资产行同起点，视觉整齐）；卡内 `padding:10px 12px`→`12px`、卡间 `margin-bottom:10px`→`12px`（3 张卡行距更舒适）；左侧状态色条（`--primary-color`/`--success-color`/`--danger-color` token）保持；存量无合同兜底行（`ct-fallback`）不受影响 | `views/sales/projects/index.vue` |

### 核查结论

- **改动 1 列对齐对照表**（现 → 新，资产列表依据行号）：项目编号 左→左（L335 文字类）｜项目名称 左(隐式)→左(显式)（L335）｜客户→**关联合同** 左→**居中**（L354 计数类）｜合同数 居中→**删除**｜生态人员 左→左（L351）｜主体 左→左（L351）｜项目状态 居中→居中（L377）｜合同金额 右→右（资产列表无金额列，按任务规则金额右对齐）｜关联资产 **右→居中**（L354 计数类）｜预计签约/最近跟进 左→左（资产列表无日期列，维持左）｜操作 居中→居中（L384）。
- **改动 2 tooltip 内容与空态**：多合同 =「2 位客户：测试客户A、测试客户B」（实测 DOM tooltip 断言通过）；单合同 = 直接客户名；`contractCount` 空/0 = 单元格 '-'（muted）无 tooltip。
- **改动 3 合同卡三层字号/颜色**（实测 computed style 断言）：第一层金额 600 右对齐（保持）；第二层资产名 `13px / rgb(66,87,116)`（= `--text-body` #425774）逐行独立、数量 `12px / rgb(154,169,191)`（muted）；第三层日期 `12px / muted`；卡 `padding:12px`、卡间 `margin-bottom:12px`（末卡 0）、左色条 `rgb(23,105,212)`（`--primary-color`）。
- **回归**：筛选/搜索（searchText/statusFilter/repFilter 逻辑未动）、编辑/删除 `@click.stop`（实测列表点「编辑」→ `/sales/projects/1/edit` 且抽屉未开）、抽屉触发/关闭（点行开、点遮罩关）、查看详情跳转（实测 → `/sales/projects/1/detail`）、`canEditProject`（未动）、viewer 禁用（`canWrite` + READONLY_TIP 未动）均不受影响。
- **agent-browser 实测**（admin @ 127.0.0.1:5173，projects=0 起步）：购物车加 2 资产（具身智能数据采集全链路管理平台 / 松延人形机器人M1-爪手V1.3）填客户 A/B 下单 → SP-001（2 合同 2 资产）→ 列表「关联合同」列显示 2、无「合同数」列、hover tooltip「2 位客户：测试客户A、测试客户B」→ 点行开抽屉：合同卡三层结构（资产名 13px 正文色独立成行 + 「× 1」12px muted + 日期第三层「锁定 2026-10-15」，截图 + computed style 断言通过）→ 查看详情跳 detail → 回列表点编辑跳 edit（stop 生效）→ 点遮罩关抽屉 → 删除 SP-001（toast「项目已删除：库存锁定已释放…」，列表共 0 条）。
- HMR 200（5173），IDE 0 error，`vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 销售项目列表新增快览抽屉（交互对齐资产列表，内容聚焦合同）

**关联任务**：销售项目列表抽屉化——点击行打开快览抽屉（与资产列表 `assets/list.vue` 抽屉交互/视觉规格一致），抽屉聚焦「项目概览 + 合同清单（只读）」，「查看详情」才进详情页。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 列表 `el-table` `@row-click` 由 `goDetail` 改为 `openDrawer`（行数据传入 `drawerProject`）；行内操作按钮（编辑/删除）`@click.stop` 与 `.op-tip` span stop 保持原行为不冒泡；**行内「详情」按钮移除**（入口收敛到抽屉底部「查看详情」，操作列宽 230→160） | `views/sales/projects/index.vue` |
| 2 | 新增 | 快览抽屉 `el-drawer size=640px class="project-drawer"`（结构对齐资产抽屉：dr-head 图标+名称+状态 tag / dr-sub 编号 mono+主体 / dr-close 自定义关闭；非 scoped 样式块）：**概览区**（info-grid-1：客户（多合同「N 位客户」+ tooltip 列出各合同客户）/商务负责人/生态人员/预计签约日期/合同合计 `expectedAmount` formatMoney）；**合同清单区**（`db.contracts` 按 projectId 过滤、按 code 升序，每份合同一张卡片行：合同号 mono（与详情页 `.contract-code` 同字体栈）+ 客户 + 主体 tag（entityShort）+ 状态 tag（`tagInfo(PROJECT_STATUS, c.status)`，与详情页合同卡片同色 class）+ 合同金额右对齐；次级行 muted 12px：明细摘要「资产名 ×数量 · …」超长省略 + 锁定/交付日期（items 首个 lockedDate/shippedDate，口径同详情页）；**无操作按钮**（交付/终止仍在详情页））；**空合同兜底**：有存量明细 → muted 行「该项目暂无合同（存量数据），明细摘要：…」；无明细 → `el-empty` 小尺寸；底部 footer「查看详情」primary → 现有 `/sales/projects/{id}/detail` 路由（`goDetail` 不变） | `views/sales/projects/index.vue` |

### 核查结论

- **状态 tag 色对照**：抽屉合同行 `el-tag :type="tagInfo(PROJECT_STATUS, c.status).tag" size="small" effect="light"`（index.vue 抽屉模板）与详情页合同卡片 `detail.vue:258` 完全同一映射（active=primary / delivered=success / terminated=danger）；卡片左侧色条 `ct-active/ct-delivered/ct-terminated` 与 `detail.vue:413-422` `.contract-card.contract-*` 同 token 色（`--primary-color` / `--success-color` / `--danger-color`+opacity .85）。
- **回归**：列表筛选（搜索/状态/生态人员）/列/编辑可见性规则 `canEditProject`/viewer 禁用（`canWrite` + READONLY_TIP）全部未动；抽屉打开不改动列表筛选状态（仅新增 `drawerVisible/drawerProject` 两个 ref）。
- **agent-browser 实测**（admin @ 127.0.0.1:5173）：建 2 合同测试项目 SP-002（测试客户A·青牛企业大数据分析平台V1.0 ×1 ¥5,661,000 / 测试客户B·融合视讯云平台 ×1 ¥7,580,000，POST /projects 200）→ 列表点行 → 抽屉打开（DOM 断言：2 张 ct-row 均 `ct-active`「进行中」，金额 ¥5,661,000.00 / ¥7,580,000.00，合同合计 ¥13,241,000.00，客户「2 位客户」，次级行含「锁定 2026-10-15」）→ 抽屉「查看详情」→ `/sales/projects/2/detail`（2 合同均进行中）→ 回列表点操作列「编辑」→ 进 `/sales/projects/2/edit` 且抽屉未开（stop 生效）→ 点遮罩（200,300）抽屉关闭 → 页面删除 SP-002（确认框「确认删除」→ toast「项目已删除：库存锁定已释放…」，列表回到 1 条）。
- HMR 200（5173），IDE 0 error，`vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 购物车下单对话框移除「客户名称」字段（客户已行级填写，逻辑去重）

**关联任务**：用户反馈——购物车每行已填客户、结算按客户分组成合同（对话框顶部已有 N 份合同分组预览），下单对话框再必填「客户名称」冗余且与行级客户语义冲突。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `SalesOrderDialog` 新增 `cartMode` prop（默认 false，仅购物车结算传 true）：cartMode 下 ① 移除「客户名称」表单项与必填校验（placeholder 一并删）；② 「合同金额（元）」改为只读汇总展示「合同合计（元）」= Σ各行小计（`formatYuan(totalYuan)`，不可编辑）；③ 项目名称默认「采购订单」（可修改，不再跟随客户名）；④ 提交 payload 不带 `customer` 与 `contractAmount`（后端 `CheckoutInput` 已确认：customer 可选且不参与分组、contractAmount 不被消费，合同金额按分组小计派生）。直接下单模式（资产抽屉 `/sales/order`）行为一行未动（customer 必填 + 可编辑合同金额保留） | `components/SalesOrderDialog.vue` |
| 2 | 修改 | `OrderFields.customer` 由必填改为可选（`customer?: string`，直接下单仍恒传值）；购物车页 `SalesOrderDialog` 使用处加 `:cart-mode="true"`。空客户行拦截（`openOrder` 标红 + warning）、400 文案展示、viewer 禁用逻辑一行未动 | `api/index.ts`, `views/cart/index.vue` |

### 核查结论

- **后端契约确认**（`backend/src/schemas.py:356` `CheckoutInput` + `services.py:1177` `checkout`）：`customer` 默认 `""` 且不参与分组（项目 customer 强制 `""`，多客户显示「N 位客户」）；`contractAmount` 默认 0 且 checkout 路径**不读取**（项目/合同金额由分组小计派生）→ payload 删除两字段安全，**无需改后端**。实际消费字段：`projectName/rep/expectedSignDate/remark/deliveryReq`（`businessOwner` 不在 `CheckoutInput` 中，后端静默忽略——既有行为，前端保留传值未动）。
- **agent-browser 实测**（admin @ 127.0.0.1:5173，购物车 2 客户 2 行：优艾维 ¥3,200,000 / 优艾维2 ¥7,580,000）：点「下单」→ 对话框无「客户名称」字段，结算预览「将生成 1 个项目 · 2 份合同」正常，项目名称默认「采购订单」，合同合计只读 ¥10,780,000.00 → 直接「确认下单」→ `POST /api/cart/checkout` 200，bootstrap 验证 SP-001（采购订单）contractCount=2，HT-0001 customer=优艾维 ¥3,200,000 / HT-0002 customer=优艾维2 ¥7,580,000，购物车清空 → 页面删除测试项目，级联释放确认（projects=0 / contracts=0 / 两资产 lockedQty=0）。
- HMR 200（5173），IDE 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ ⚠️ Breaking：合同层级（ADR-007）前端核心页面——购物车客户列 / 建项目合同清单 / 项目详情合同卡片 / 移除项目级状态变更入口

**关联任务**：合同层级（ADR-007）前端·核心页面（购物车 + 项目创建/详情）。后端契约已生效（bootstrap 顶层 `contracts`、`projects[].contractCount`、`cart[].customer`、`PATCH /contracts/{id}/status`、`PATCH /cart/{id}`）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `Contract`/`ContractItem` 接口（`code` HT-xxxx / `customer` / `subject` / `contractAmount` 元 / `status` 三态 / `items[]` 挂 `contractId`）；`Project` 加 `contractCount?`（`customer`/`status`/`expectedAmount` 注释标注派生语义）；`ProjectItem` 加 `contractId?`（存量 null）；`CartItem` 加 `customer?`（行级客户，""=未填写） | `types.ts` |
| 2 | 新增 ⚠️ | `db` 镜像加 `contracts`（`refresh()` 落库 `data.contracts ?? []`）；新增 `changeContractStatus(id, 'delivered'\|'terminated', reason?)`（`PATCH /contracts/{id}/status`）与 `patchCartItem(id, customer)`（`PATCH /cart/{id}`）；新增 `ContractInput` 接口、`ProjectInput` 加 `contracts?`（`items` 保留兼容路径）；`ProjectOut` 加 `contractCount?` | `api/index.ts` |
| 3 | 删除 ⚠️ | **移除 `changeProjectStatus` 导出**（前端不再提供「改项目状态」入口，后端 `PATCH /projects/{id}/status` 仅作批量快捷保留、前端无调用）；全仓 `changeProjectStatus`/`openStatusDialog`/`修改状态`/`statusDialog` 残留 = 0 | `api/index.ts`, `views/sales/projects/index.vue`, `views/sales/projects/create.vue`, `views/sales/projects/detail.vue` |
| 4 | 修改 ⚠️ | **购物车允许跨主体混装**：info-bar/desc 文案去掉「仅可添加同一主体」，改为「可混装不同主体 + 按客户分组生成合同（同一客户须同一主体，否则拆分）」；删除 `cartSubject` computed；资产次级行补主体简称（`entityShort`）。加购链路本就无前端同主体拦截（已核查 `assets/list.vue` 单行/批量加购仅库存校验） | `views/cart/index.vue` |
| 5 | 新增 | **购物车「客户」列**（资产名称后）：`el-input size=small` 行内编辑（失焦/回车 = EP 内置 change），`onCustomerChange` → `patchCartItem`（成功走 `afterWrite` 刷新；400 弹后端原文案并 `refresh(true)` 回滚）；`customerErrors`（reactive Set）驱动标红——EP 2.14 独立 `el-input` 的 `validate` prop 已失效（只从 el-form-item 取状态，实测 DOM 无 is-error），改用 `:class="cart-customer-error"` + scoped `:deep(.el-input__wrapper)` danger 描边（实测 box-shadow 生效）；viewer 禁用 + READONLY_TIP tooltip | `views/cart/index.vue` |
| 6 | 新增 | **购物车结算前置校验 + 分组预览**：`openOrder()` 任一 `customer===""` → 不发请求，空行全部标红 + `ElMessage.warning('请为每件资产填写客户')`；`previewGroups` computed 按客户分组（保持行序，qty/amount 累加）传入 `SalesOrderDialog` 新 prop `previewGroups`，对话框顶部渲染「将生成 1 个项目 · N 份合同：客户A（2 件 ¥…）」浅蓝预览块；下单成功 toast 带合同数（`p.contractCount ?? previewGroups.length`） | `views/cart/index.vue`, `components/SalesOrderDialog.vue` |
| 7 | 修改 | **SalesOrderDialog 单合同语义**：组件头注释明确——`/sales/order` 的 `SaleOrderInput` **无 contracts 字段**（后端 schema + api.md 双确认，curl 实测旧格式 200 且自动包装单合同 contractCount=1），payload 维持 `customer + items + contractAmount`（customer 必填保持）；购物车结算按行级客户分组（对话框客户字段仅兼容保留，不参与分组）；主体行跨主体混装时显示「多主体（按客户分组生成合同）」 | `components/SalesOrderDialog.vue` |
| 8 | 重构 ⚠️ | **建项目页大改「合同清单」结构**：原单区「资产明细」改为 `contracts[]` 合同卡片（卡片头「合同 N · 客户名」+ 删除；卡内客户 el-input 必填 + 合同金额 el-input-number 元（默认=明细合计，`contractTouched` 手改后不覆盖）+ 明细行表格（资产 tree-select/数量/单价/金额，复用原实现，可加行删行））；「+ 添加合同」（默认 1 张卡）；**合同内主体预校验**：选资产与本合同已选资产主体不同 → `ElMessage.warning('该资产主体与本合同内其它资产不一致，请新建一份合同')` 并回退选择（后端 400 兜底）；提交 payload 用 `contracts` 结构（`customer`=首份合同客户兼容传值，`subject/expectedAmount/contractAmount` 传 0/"" 由后端派生）；项目级字段收敛为 项目名（默认跟随首份合同客户，`nameTouched`）/生态人员/商务负责人/预计签约/最近跟进/报价/已回款/备注（移除 行业/主体/预计销售/合同金额 4 个派生或弃用字段）；`?customer=&assetId=` 预填落首份合同 | `views/sales/projects/create.vue` |
| 9 | 修改 ⚠️ | **建项目编辑模式只读合同结构**：编辑页仅基本信息表单 + 顶部 `el-alert`「合同与明细在创建后不可修改，如需调整请终止对应合同后重新下单」；`buildPayload(false)` 不传 items/contracts（PUT 已收窄）；编辑守卫升级：存在 delivered 合同 → 拦截「已交付完成的项目不可编辑」（与后端 400 同文案），存量无合同项目沿用 `status!=active` 旧规则；移除编辑页「修改状态」对话框 | `views/sales/projects/create.vue` |
| 10 | 新增 ⚠️ | **项目详情「合同清单」区块**（基本信息下方）：`db.contracts` 按 projectId 过滤排序，每份合同一张卡片（状态左侧色条：active 主色 / delivered 成功色 / terminated 危险色+降透明度）——头部 合同号（mono）+ 客户 + 主体 tag（entityShort）+ 状态 tag（复用 `PROJECT_STATUS` 色系）；信息行 合同金额（formatMoney）/ 签约·锁定日期（items 首个 lockedDate）/ 交付日期（首个 shippedDate）/ 备注；明细 mini 表格（资产链接/数量/单价/金额/交付要求）并入卡片，**原独立「销售明细」区块移除**（存量无合同项目保留原明细表兜底展示）；头部 desc 多客户显示「N 位客户」 | `views/sales/projects/detail.vue` |
| 11 | 修改 ⚠️ | **合同级操作矩阵**（详情卡片右对齐 `.op-actions`）：active → 「交付」（primary small，确认「确认交付合同 HT-xxx？将扣减库存并生成出库记录」）+「终止」（danger plain，确认「确认终止？将释放该合同锁定库存」）；delivered → 「终止」（danger plain，确认「已交付合同终止将撤销出库并回退售出数量与金额」）；terminated → 无按钮（显示「已终止」）；viewer → 全部禁用 + READONLY_TIP；操作走 `changeContractStatus`（内部 `afterWrite` 刷新，卡片与项目派生状态自动更新）；**移除详情页「修改状态」按钮与对话框**，合同清单区块副标题说明「项目状态由合同状态自动派生」 | `views/sales/projects/detail.vue` |
| 12 | 修改 | **项目列表移除「状态」操作入口**（验收 5 全仓无残留要求）：删除操作列「状态」按钮 + 状态流转对话框 + `canGo`/`confirmStatus` 等全部状态机代码与 `status-radios/flow-*` 样式；info-bar 文案改为「项目状态由合同状态自动派生…在项目详情页对合同执行『交付』/『终止』」 | `views/sales/projects/index.vue` |

### 核查结论

- **payload 实测**（curl，admin）：`POST /projects` 双合同入参 → 200 `contractCount=2`、`customer=""`；合同内跨主体 → 400「客户「客户丙」的资产主体不一致，请拆分」；`POST /sales/order` 旧格式（customer+items）→ 200 自动包装单合同（`items[].contractId` 非空）——**故 SalesOrderDialog payload 不改 contracts 结构**（后端 `SaleOrderInput` 无该字段，api.md:318 同口径）。
- **agent-browser 冒烟**（admin @ 127.0.0.1:5173）：① 建 2 合同项目（冒烟客户A/资产21 + 冒烟客户B/资产22）→ 成功 toast「SP-011（2 份合同）」；② 详情页 2 张合同卡（HT-0001/HT-0002 均「进行中」，头部「客户 2 位客户 · 2 份合同」）；③ 交付 HT-0001 → 卡片变「已完成」，项目状态仍「进行中」；④ 终止 HT-0002 → 卡片「已终止」无按钮，项目状态派生「已终止」；⑤ 删除测试项目 → 合同级联回滚（bootstrap contracts=0）。截图 smoke_1~4。
- **购物车冒烟**：空客户点「下单」→ 不发请求 + warning「请为每件资产填写客户」+ 输入框 danger 描边（实测 box-shadow rgb(217,83,79)）；填客户失焦 → PATCH 成功、标红清除；下单对话框预览「将生成 1 个项目 · 1 份合同 购物车客户A 1 件 ¥1,205,000.00」；同资产改客户撞行 → 400 原文案「购物车中该资产在客户「购物车客户A」下已有行，无法修改客户（请先删除原行）」并回滚。截图 smoke_5c/6。**测试数据已清理**（购物车恢复 1 行空客户、测试项目已删）。
- **合同内主体预校验**（浏览器实测）：合同2（安徽天枢资产）内再选蜂云时代资产 → warning「该资产主体与本合同内其它资产不一致，请新建一份合同」且选择回退为空。
- **残留核查**：全仓搜 `changeProjectStatus|openStatusDialog|修改状态|statusDialog` = 0 处；「同一主体」购物车拦截文案 = 0 处（加购链路本就无前端拦截）。
- HMR 各改动模块 200（7 文件），IDE 0 error，`vue-tsc --noEmit` 0 error；未动 global.css token、未引入 Element 默认色（合同卡色条走 `--primary-color/--success-color/--danger-color` token）、金额全部 `formatMoney`（元）、无「万」字。

### 遗留（第二批：列表/看板/资产详情销售关联）

- 项目列表：客户列多合同显示「N 位客户」（现直接显示空 `customer`）；可加「合同数」列（`contractCount`）；关联资产数列口径确认（现 `items.length` 仍正确）。
- 资产详情「销售关联」页签：明细已挂 `contractId`，可补「所属合同」列（HT-xxxx）；签约主体列现取项目 subject（多合同为空），需改按明细所属合同 subject 兜底。
- 看板（dashboard）：`staleProjects`/销售统计走项目派生字段，口径自动兼容，无需改（走查确认即可）。
- 出库列表：`outbounds[].contractId` 已回传，可补「关联合同」列（与「关联项目」链接同规格）。
- 项目列表/详情「编辑」按钮可见性现按 `project.status === 'active'` 判定，与后端新规则（存在 delivered 合同即 400）在「混合 delivered+active」场景下不一致（此时 status 派生为 active 但不可编辑）——建议第二批改为「无 delivered 合同」判定（`db.contracts` 已可用）。

---

## 2026-10-15 ｜ 资产列表「资产名称」列点击分工终版：名称文字=跳详情，列内其余区域=切换勾选

**关联任务**：用户逐字拍板终版口径——名称文字（蓝色链接）点击跳详情页；该列其余区域（次级编号/类型行 + 单元格空白处）点击切换该行勾选；整列绝不打开抽屉（全部 `stop` 阻断 row-click）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 名称列 `<template #default>` 增加根容器 `.asset-cell`（`@click.stop="toggleRow(row)"`，恢复 `toggleRow` = `toggleRowSelection(row)`，与复选框共用 `selection-change → selectedAssets` 单一真源）；名称文字 `.asset-name` 独立 `@click.stop="goDetail(row)"`（先于根容器 stop，跳 `/assets/{id}/detail`，保留主色 + hover 下划线真链接语义）；次级行 `.asset-spec` 不再单独绑事件，走根容器 = 勾选（cursor:pointer 保留）；整格可点：名称列 td 加 `class-name="asset-name-col"` + `position:relative`，`.asset-cell::before` 绝对定位 `inset:0` 铺满整格（含上下 padding 与垂直居中留白），空白处点击也命中根容器勾选；`.asset-name` 加 `position:relative` 绘制在 `::before` 之上保证点击命中名称本身；其它列 row-click 开抽屉、复选框列/表头全选半选/批量加购计数、操作列（无「查看」、宽 160）均保持现状 | `views/assets/list.vue` |

---

## 2026-10-15 ｜ 资产列表名称列交互终版修正：名称/次级行点击 = 跳详情页，撤销「名称=勾选」与操作列「查看」

**关联任务**：资产台账列表（五板块共用）名称列交互终版拍板——撤销上一轮中断任务引入的「名称点击=勾选」与操作列「查看」按钮，恢复并扩展为「名称+次级行点击=跳详情页」，勾选只由复选框列承担。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 名称列终版：点击资产名称（`.asset-name`）与次级行（`.asset-spec`）均 `@click.stop="goDetail(row)"` 跳详情页 `/assets/{id}/detail`（次级行由原无绑定改为同跳详情）；恢复 `.asset-name:hover` 下划线（明确可跳转语义）；删除 `toggleRow` 函数及名称列上的 `toggleRow`/`click.stop` 勾选绑定，勾选唯一入口 = 复选框列（表头全选/半选、`selection-change → selectedAssets` 单一真源、批量加购计数同步均未动）；删除操作列「查看」link 按钮（上一轮加的 `openDrawer` 入口），操作列宽度 190→160（回退初始值，git HEAD 佐证）；抽屉入口仅剩行其它单元格 row-click（现状保留），无死功能（抽屉内「查看详情/编辑/销售」出口正常）；viewer 禁用 + tooltip、切板块筛选重置未动 | `views/assets/list.vue` |

---

## 2026-10-15 ｜ 资产列表「资产名称」点击行为：打开抽屉/跳详情 → 切换勾选（交互优化）

**关联任务**：资产台账列表（五板块共用）勾选判定范围 = 复选框列 + 资产名称列。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 点击资产名称（含名称下方编号/类型次级行）= 切换该行勾选（`toggleRowSelection(row)`，与复选框共用 `@selection-change` 单一真源），不再打开快览抽屉、不再跳详情页；名称保留主色 + pointer，去掉 hover 下划线跳转暗示；操作列新增「查看」link 按钮（主色，放「加入购物车」前，列宽 160→190）打开原快览抽屉，只读操作 viewer 可用；行其它单元格 row-click 开抽屉、抽屉内「查看详情」跳详情页、编辑入口均保留；抽屉内部逻辑/筛选/批量加购/权限禁用未动 | `views/assets/list.vue` |

---

## 2026-10-15 ｜ ⚠️ Breaking：金额单位 万元→元（拆全部换算桥接）+ 五项功能优化（F1-F5）

**关联任务**：ADR-006 前端侧——后端所有金额出参/入参已改**元**（Decimal 语义），前端拆除全部 ×10000/÷10000 换算桥接，金额展示位统一 `formatMoney` 元值直显。后端金额迁移窗口期内未对 8000 端口做任何写操作/数据验证，最终验证由迁移完成后回归统一做。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | ⚠️ Breaking | 金额单位 万元→元：`formatMoney` 去掉 `×10000`（元值直显 ¥+千分位+两位小数，0/空口径不变）；`formatYuan` 注释统一为元口径（输入框展示，行为不变）；`Asset.salePrice`/`soldAmount` 注释「万元」→「元」；拆除桥接点：资产创建/编辑销售单价输入（直存元）、项目创建/编辑 单价/预计/报价/合同/已回款 5 处输入（直存元）+ `calcItemAmount`（`amount = qty × price` 元值，2 位小数）+ 明细合计自动带出、`SalesOrderDialog` `totalYuan`（去 ×10000）/合同金额提交（去 ÷10000）/预计金额展示（去 ÷10000）、出库补录销售金额输入（直存元）；`api/index.ts` `OrderFields.contractAmount` 注释改元。全仓 grep `10000`/`万元`/`万` 残留 = 0 | `types.ts`, `views/assets/create.vue`, `views/sales/projects/create.vue`, `components/SalesOrderDialog.vue`, `views/sales/outbound/index.vue`, `api/index.ts` |
| 2 | 新增 | F1 资产列表状态筛选默认「库存可售」：`statusFilter` 默认值 `''`→`'in_stock'`（只展示库存可售资产），切板块 watch 中重置回 `'in_stock'`；筛选走既有 `assetStockState` 派生口径（与列表状态列一致），清空 = 全部（el-select clearable，placeholder「全部状态」） | `views/assets/list.vue` |
| 3 | 新增 | F2 项目名称跟随客户：`SalesOrderDialog`（下单/购物车结算共用）打开时项目名默认 = 客户名（客户为空留空），`projectNameTouched` 标记——用户手动输入项目名后不再跟随；`projects/create.vue` 新建模式同机制（`nameTouched`，watch customer），并支持 `?customer=` 预填（从「登记销售」入口带客户时项目名同步 = 客户名，仅预填阶段可改）；编辑模式不跟随 | `components/SalesOrderDialog.vue`, `views/sales/projects/create.vue` |
| 4 | 新增 | F3 销售项目「商务负责人」字段：`Project.businessOwner?`（存量空显示 `-`）；`ProjectInput`/`OrderFields` 加 `businessOwner?`；三个入口——项目创建/编辑页「更多设置」区（与生态人员同区，普通文本输入）、`SalesOrderDialog`（下单/购物车结算填写，走 OrderFields 提交）、项目详情页基本信息展示（空 `-`）；列表页不加列（现有 12 列已偏满，避免列过多） | `types.ts`, `api/index.ts`, `views/sales/projects/create.vue`, `views/sales/projects/detail.vue`, `components/SalesOrderDialog.vue` |
| 5 | 修改 | F4 销售项目列表金额列只保留「合同金额」：原金额列 3 个（预计销售/合同金额/已确认销售），移除「预计销售」「已确认销售」两列，保留「合同金额」（formatMoney 元值）；F5 移除 `.stat-cards` 整块（模板 + `summary` computed + `confirmedAmount` 函数 + 仅统计卡使用的 `CircleCheck`/`Document`/`Money` 图标 import），页面骨架 page-head/info-bar/表格保持 | `views/sales/projects/index.vue` |

### 核查结论

- **grep 自查**（frontend/src）：`10000` = 0 处；`万元`/`×10000`/`* 10000`/`/10000`/`万` = 0 处（含注释，全部清零）。
- **金额展示位清单**（拆桥接后全部 `formatMoney` 元值直显，无手工换算残留）：资产列表抽屉（累计售卖金额/销售单价）、资产详情（销售单价/关联明细金额/流水金额）、资产算力板块（soldAmount）、购物车（单价/小计/合计）、项目创建页（明细金额/合计）、项目详情（预计/合同/已回款/明细单价/金额）、项目列表（合同金额）、出库列表（销售金额/统计卡累计）、看板（可售金额/已售金额）、SalesOrderDialog（小计/预计金额）。
- **回归**：既有筛选（名称/主体/月份/状态/类型/生态人员）、分页、权限（canWrite/READONLY_TIP）、只读禁用均未动；`formatWan` 仅用于数量（非金额）展示，未动。
- HMR 各改动模块 200（9 个文件），IDE 0 error；`vue-tsc --noEmit` 仅存量 5 处报错（MainLayout ElMessage 未用 / create.vue 2 处未用 import + noSellableStock 入参 / detail.vue availableQty 入参），均非本次改动行。
- **待迁移完成后的浏览器验证清单**：① 资产列表/详情/看板金额显示为元值（如 ¥3,200,000.00）且与后端库值一致；② F1 资产列表默认只显示「库存可售」，切板块后仍为默认，清空可看全部；③ F2 下单对话框填客户名后项目名自动同步、手改后不再跟随，同客户多次下单得到同名项目；④ F3 项目创建/下单填写商务负责人后详情页正确展示（存量项目显示 `-`）；⑤ F4/F5 项目列表只剩「合同金额」金额列且无统计卡，页面骨架正常。

---

## 2026-10-15 ｜ 附件文件名展示改为原始名（散列名→原始名映射，纯展示层）

**关联任务**：后端 `GET /api/bootstrap` 已新增 `files: FileMetaOut[]`（`storedName`/`name`/`size`/`uploadedBy`/`createdAt`），`GET /api/files/{storedName}` 响应头已带原始名 `Content-Disposition`。前端存储口径不变（资产字段/URL 仍用散列名），仅展示层映射为原始名。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `FileMeta` 接口（`storedName`/`name`/`size`/`uploadedBy`/`createdAt`）；`Asset.contractFile`/`featureDoc` 注释更新为「散列文件名」 | `types.ts` |
| 2 | 修改 | `db` 响应式镜像加 `files: [] as FileMeta[]`，`refresh()` 落库 `db.files = data.files ?? []`（风格同现有镜像）；新增 `fileDisplayName(storedName)`：查 `db.files` 映射，无记录返回散列名本身（存量文件兜底） | `api/index.ts` |
| 3 | 修改 | 全仓附件展示位改为原始名（URL/预览 src 保持散列名）：① `list.vue` 快览抽屉「产品清单」行 `产品清单（{{ fileDisplayName(drawerAsset.contractFile!) }}）` + FilePreview 弹层 title 同步；② `detail.vue` 交付物页签功能清单附件行 `功能清单（{{ fileDisplayName(asset.featureDoc!) }}）` + 预览弹层 title 同步；③ `create.vue` 产品清单/功能清单上传后展示——本会话新上传用 `File.name` 兜底（`contractOrigName`/`featureOrigName` ref，上传成功时赋值、移除时清空），bootstrap 刷新后自动走映射（编辑回填的存量值 `origName` 为空直接查映射）；④ `FilePreview.vue` 标题兜底 `title \|\| fileDisplayName(filename)`。原 `contractKindLabel`/`featureKindLabel`/`contractTypeLabel`（PDF/Word/图片 标签）删除——原始名自带扩展名，信息不丢失 | `views/assets/list.vue`, `views/assets/detail.vue`, `views/assets/create.vue`, `components/FilePreview.vue` |

### 核查结论

- **全仓附件展示位清单**（搜 `contractFile`/`featureDoc`/`fileUrl`）：`list.vue:518`（抽屉产品清单行）、`list.vue:638`（预览弹层 title）、`detail.vue:511`（功能清单附件行）、`detail.vue:816`（预览弹层 title）、`create.vue:392/420`（表单上传后展示）、`create.vue:447/456`（预览弹层 title）、`FilePreview.vue:4`（标题兜底）——共 8 处全部改走原始名；`fileUrl()` 下载/预览 URL 全部保持散列名未动。交付物页签（`AssetDeliverable`）为纯文本字段（name/version/meta），无文件附件展示位，无需处理；操作记录 `changes` 后端已输出原始名，前端未改。
- **存量散列文件兜底**：`file_meta` 无记录的散列名（映射上线前上传的存量文件），`fileDisplayName` 返回散列名本身，展示不报错、下载/预览不受影响。
- HMR 各模块 200（types.ts / api/index.ts / list.vue / detail.vue / create.vue / FilePreview.vue），IDE 0 error；未动 global.css token、未引入 Element 默认色。
- **建议验证路径**：/assets/5/detail 交付物页签功能清单行与预览弹层显示原始名；列表抽屉产品清单行同；新上传中文名文件后（编辑页/抽屉/详情页）展示中文名，下载落盘为中文名（`Content-Disposition`）。

---

## 2026-10-15 ｜ 资产详情/编辑页四点对应改造（功能清单附件化 / 签约主体 / 流水操作人 / 日志变更明细）

**关联任务**：后端契约已生效（`featureDoc` / `projects[].subject` / `flows[].operator` / `logs[].changes`），前端按契约实现。`types.ts` 同步：`Asset.featureDoc`、`AssetFlow.operator`、`OpLog.changes`（`Project.subject` 原已存在，未重复加）；`api/index.ts` `AssetInput` 加 `featureDoc`。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 功能清单改为文档附件（`featureDoc`，与产品清单 `contractFile` 同模式）：详情页交付物页签移除原「功能清单」结构化模块树弹层（`featureDialog`/`openFeature`/模块树模板与 `feature-*` 样式全删），交付物清单卡片顶部新增附件行——未上传「未上传功能清单 [去上传]」（隐藏 `input[type=file]`，accept 与产品清单一致 → `uploadFile` → `updateAsset(id,{featureDoc:filename})`，loading/失败提示同产品清单）；已上传「功能清单（PDF/Word/图片）+ 预览（FilePreview 弹层）+ 下载（`fileUrl`）」；viewer 下「去上传」`:disabled="!canWrite"` + `READONLY_TIP` tooltip。创建/编辑页 `create.vue` 同步：表单加 `featureDoc`（编辑回填），「状态与备注」区新增功能清单上传区块（交互与产品清单一致：上传/预览/替换/移除），payload 随 `{...form}` 提交 `featureDoc`；**不再提交 `saleDetail`**（表单本就不含该字段，不清空存量）。说明：当前代码中 Univer 表格组件已不存在（仅 `types.ts`/`api/index.ts` 残留 `IWorkbookData` 类型引用与 `saleDetail` 出参类型，按任务要求保留不删） | `views/assets/detail.vue`, `views/assets/create.vue`, `types.ts`, `api/index.ts` |
| 2 | 修改 | 销售关联页签新增「签约主体」列：本地函数 `projectSubject(p)` = `p.subject \|\| 首条有资产明细（assetId 非空）的资产 subject \|\| '-'`，展示走 `entityShort`；存量项目 subject 为空时兜底生效（实测 SP-007 显示「安徽天枢」） | `views/assets/detail.vue` |
| 3 | 修改 | 出入库流水补操作账号：`AssetFlow.operator` 展示——空 → `-`，`"system"` → 「系统」，其余原样。落点说明：本页签为**时间线**而非表格（全仓流水唯一完整消费方；列表抽屉仅展示最近 4 条摘要，未动），故在时间线项标题行「类型」之后加次级文字「操作人：xxx」（`.fl-operator` 12px muted），原时间线结构/筛选/色点未动 | `views/assets/detail.vue` |
| 4 | 修改 | 操作记录展示变更内容：`log.changes` 非空时在动作行下方加一行次级文字（`.log-changes` 12px `.muted`），为空不渲染（`v-if`，布局不产生空行） | `views/assets/detail.vue` |
| 5 | 修改 | 全站 label「销售人员」→「生态人员」（rep 数据源 `db.reps` 生态人员名单未动）：`projects/create.vue` 页头注释 :6、更多设置说明 :489、表单项 label :505、placeholder :510；`assets/detail.vue` 交付步骤文案 :206、销售关联表头 :553。其余页面（projects/detail、projects/index、dashboard、SalesOrderDialog、settings/base）经全仓搜索确认原本即为「生态人员」，无需改 | `views/sales/projects/create.vue`, `views/assets/detail.vue` |

### 核查结论

- **回归**：交付物页签 CRUD（新增/查看/标记就绪/退回）未动；销售关联的项目跳转链接、状态 tag、原 7 列未动（仅插入签约主体列 + 改 1 个 label）；流水时间线原字段（日期/类型/数量/金额/关联单号/备注）与筛选按钮未动；操作记录原 action/detail/operator/time 未动。
- **浏览器实测**（agent-browser @ 127.0.0.1:5173，admin）：/assets/5/detail 交付物页签「未上传功能清单 [去上传]」→ 上传 PDF 后即时显示「功能清单（PDF）+ 预览 + 下载」，预览弹层正常；销售关联表出现「签约主体」列且 SP-007（subject 空）兜底显示「安徽天枢」；操作记录出现 changes 行（`功能清单: → xxx.pdf`、`销售单价: 320.0 → 33 万元`）；流水操作人：存量显示「操作人：-」，新流水（API 下单/删项目产生）显示「操作人：admin」。viewer 实测：未上传资产「去上传」禁用且悬停提示「只读账号无操作权限」，已上传资产预览/下载可用（与产品清单口径一致）。
- **测试数据已清理**：临时项目 SP-010/SP-011 已删除（删除回滚产生 1 条审计流水属正常留痕），资产 5 的 `salePrice` 恢复 320、`featureDoc` 恢复空。
- HMR 各模块 200（detail.vue / create.vue / projects/create.vue / types.ts / api/index.ts），IDE 0 error；未动 global.css token、未引入 Element 默认色、无「万」字。

---

## 2026-10-15 ｜ 资产列表抽屉「产品清单·去上传」改为直接弹文件选择框

**关联任务**：快览抽屉「产品清单」区未上传时的「去上传」原跳转资产编辑页，改为点击直接弹文件选择框上传，完成后抽屉内即时显示已上传状态（文件名/预览/下载，与编辑页口径一致）。小改，未重构。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 抽屉「去上传」`el-link` 的 `@click` 由 `goEdit(drawerAsset)` 改为 `pickContractFile()`（触发同区新增的隐藏 `<input type="file">` 的 `click()`）；上传中 `:loading` + 文案「上传中…」；`accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.gif,.webp,.xlsx"` 与编辑页 `create.vue:343` 完全一致 | `views/assets/list.vue`（模板「产品清单」区） |
| 2 | 修改 | 新增 `onContractPicked()`：`uploadFile(file)`（`POST /api/upload` 返回 filename）→ `updateAsset(id, { contractFile: filename })`（`PUT /assets/{id}`，内部已 `refresh(true)`）→ `drawerAsset` 重新指向刷新后的行对象，抽屉即时切到已上传展示（既有 `contract-row`：文件名 + 预览 `FilePreview` 弹层 + `fileUrl()` 下载，未新增组件）；失败 `ElMessage.error`（含后端错误文案），保留「去上传」可重试 | `views/assets/list.vue`（script） |

### 核查结论

- **viewer 只读**：「去上传」`el-link` 保留既有 `:disabled="!canWrite"` + `READONLY_TIP` tooltip（与其它写入口同规格），viewer 下禁用且悬停提示只读。
- **限制一致性**：文件类型（accept）与编辑页一致；前端无大小校验（编辑页同样仅文案提示「≤20MB」，由后端校验），口径一致，未新增前端限制。
- **最小改动**：未新增删除/替换入口（删除仍在编辑页）；未动编辑页上传逻辑、未动后端。
- 抽屉内同类「去上传」型跳转仅产品清单这一处；抽屉底部「编辑」按钮跳编辑页属正常入口，保留。
- HMR 200（list.vue @ 5173），IDE 0 error；未动 global.css token、未引入 Element 默认色、无「万」字。

---

## 2026-10-15 ｜ 基础设置菜单与路由收口为 admin 专属

**关联任务**：三角色（admin/editor/viewer）中除 admin 外，「基础设置」整个菜单组不可见、不可访问（与既有「账号与审计」`v-if="isAdmin"` 同规格）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 「基础设置」`el-sub-menu` 加 `v-if="isAdmin"`，editor/viewer 下整个一级菜单消失（不留空壳）；原「账号与审计」子项上的 `v-if="isAdmin"` 因整组已收口而移除（冗余） | `layouts/MainLayout.vue` |
| 2 | 修改 | 全局守卫在既有 `/settings/users` 拦截同款模式上，为 `/settings/deliverables`、`/settings/reps` 增加非 admin 拦截：`ElMessage.warning('仅管理员可访问「基础设置」')` → 回 `/`；`/settings/users` 既有守卫原样保留 | `router/index.ts` |

### 残留核查结论

- 未动：后端任何代码；两个 settings 页面内部写按钮 `canWrite` 禁用逻辑（保留作纵深防御）；`/settings/users` 既有守卫。
- 三角色真实浏览器实测（agent-browser @ 127.0.0.1:5173）：admin 侧边栏有「基础设置」3 子项；editor/viewer 侧边栏无「基础设置」，直达 `/settings/deliverables`、`/settings/reps` 均提示「仅管理员可访问「基础设置」」并回 `/dashboard`；editor/viewer 业务菜单（首页/资产/销售/购物车）正常。
- HMR 200，IDE 0 error；未动 global.css token，未引入 Element 默认色。
- 备注：验收账号 `editor`/`viewer`（密码 123456）为本次实测经 admin API 创建的测试账号（库内原本不存在），如需清理可在「账号与审计」中删除。

---

## 2026-10-15 ｜ 资产状态回退 unlimited 第三态（三态 → 两态）

**关联任务**：用户拍板资产状态只保留两态「库存可售」「暂无库存」，可重复售卖（repeatSale）资产归入「库存可售」。信息不丢失：数量列「重复售卖」tag、详情「可售数量：不限」、购物车「不限」均保留不动。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `AssetStockState` 联合类型移除 `'unlimited'`，恢复 `'in_stock' \| 'no_stock'` 两态；`assetStockState()` 移除 `a.repeatSale → 'unlimited'` 前置分支（`noSellableStock` 内 `!a.repeatSale` 短路使 repeatSale 资产自然归 `'in_stock'`）；`ASSET_STOCK_STATE` 标签表移除 `unlimited` 条目 | `types.ts` |
| 2 | 修改 | `stockState` computed 的 `form.repeatSale ? 'unlimited'` 分支改为 `form.repeatSale → 'in_stock'`，实时联动保留（repeatSale=true 即时显示「库存可售」绿）；repeatSale 开关下警示行（:317）保留不动 | `views/assets/create.vue` |
| 3 | 修改 | `statusPill()` 移除 unlimited 第三态（`na`/灰蓝 pill）映射，返回类型收窄为 `'ok' \| 'off'`；repeatSale 资产状态胶囊显示「库存可售」绿；同步删除已无引用的 `.status-pill.na` 样式块 | `views/assets/detail.vue` |

### 残留核查结论

- 全仓重搜 `'unlimited'`：**0 处残留**。
- 消费方 `list.vue`（筛选下拉 :320 遍历标签表、状态列 :380、抽屉 :417）与 `compute.vue`（:65）均走 `ASSET_STOCK_STATE[assetStockState(row)]`，标签表恢复两选项后自动收敛为两态，无 undefined 落点。
- 未动：数量列「重复售卖」tag、详情「可售数量：不限」、购物车「不限」、后端任何代码。
- HMR 各模块 200（types.ts / create.vue / detail.vue / list.vue / compute.vue），IDE 0 error；未引入 Element 默认色与「万」字，未动 global.css token。

---

## 2026-10-15 ｜ 前端同步「下单不再自动交付」新语义（文案 + 提示）

**关联任务**：后端 `POST /sales/order` 与 `POST /cart/checkout` 改为仅生成「进行中」销售项目并锁定库存（不再自动置已完成/出库），前端同步文案与用户预期（纯文案改动，零逻辑改动）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 下单成功 toast：`下单成功，已生成销售项目 ${p.code} 并完成出库` → `下单成功，已生成销售项目 ${p.code}（进行中）`（购物车 :126、资产列表 :121 两处） | `views/cart/index.vue`, `views/assets/list.vue` |
| 2 | 修改 | 购物车页 desc（:145）与 info-bar（:160）：「…下单后自动生成销售项目并完成出库」→「…下单后生成进行中销售项目并锁定库存，确认交付后在项目页置「已完成」即出库」；页头注释（:6）与下单区块注释（:108）同步 | `views/cart/index.vue` |
| 3 | 修改 | 下单对话框确认按钮「确认下单并出库」→「确认下单」；组件头注释同步。提交处理仅 emit payload，不依赖 `p.status`（已核查，无需改） | `components/SalesOrderDialog.vue` |
| 4 | 修改 | `checkoutCart`/`createSaleOrder` 的 JSDoc 注释由「并立即出库」改为「生成「进行中」销售项目并锁定库存（不自动出库）」（仅注释，函数体零改动） | `api/index.ts` |
| 5 | 修改 | 销售项目列表 info-bar 追加一句：「「进行中」项目已锁定库存，确认交付后请置为「已完成」以扣减库存并生成出库」（原「交付完成」流转说明保留） | `views/sales/projects/index.vue` |

### 落点选择说明（第 5 项）

选**项目列表 info-bar 追加**而非详情状态区：① 下单成功 toast 后用户被直接带到项目**详情**页，但详情状态区已有「修改状态」按钮 + 状态流转对话框内 `el-alert`（"已完成将自动：扣减锁定数量…并生成出库记录"）完整解释了置「已完成」的后果，再加一行属重复；② 列表 info-bar 是全站既有的"业务规则提示条"落点（本页已有同款），追加一句即可覆盖所有进行中项目的常驻提示，无需按状态条件渲染。

### 残留核查结论

- 全仓重搜 `出库/交付/下单`：剩余「已完成出库/撤销出库/出库记录/交付完成」等表述均属**状态流转与出库台账**的正确语义（`types.ts:175` ITEM_STATUS、outbound 页、项目状态对话框 el-alert、删除项目确认文案），未改动。
- `views/assets/detail.vue` 的「登记销售」跳转项目创建页，无下单 toast，无需改。

### 既有功能未受影响的依据

- 零逻辑改动：API 调用、事件处理、路由跳转（`/sales/projects/{id}/detail`）、`p.status` 依赖（无）、骨架、颜色 token 全部原样；未引入 Element 默认色与「万」字。
- 验证 = Vite HMR 五个改动模块 curl 200 + IDE 诊断 0 error；未执行 `build/deploy`（按约束禁止）。

---

## 2026-10-15 ｜ 购物车「清空购物车」按钮显性化

**关联任务**：购物车页「清空购物车」按钮显性化（1 处小改）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 「清空购物车」由 `el-button link type="danger" size="small"` 纯文字升级为**次级实体按钮** `el-button type="danger" plain`（default 尺寸，浅红底+红描边+红字，Element Plus 既有 danger 色，无新色值），保留 `:icon="Delete"`；`.th-right` 间距 10px→12px。行为一行未动（`clearAll` 二次确认 / `:disabled="!canWrite \|\| !db.cart.length"` / viewer `el-tooltip` 外包 span）；size 不超过底部结算条「下单」primary 按钮，主焦点不变 | `views/cart/index.vue` |

---

## 2026-10-15 ｜ 购物车页面 UI 优化（展示层收敛 + 底部结算条）

**关联任务**：购物车页面 UI 优化（保持平台风格，禁止重构逻辑）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **顶部按钮区移除，结算入口收敛到底部结算条**：`page-head` 的 `.head-actions`（清空 danger plain + 下单 primary 两按钮）整块删除，页面唯一主按钮为底部结算条「下单」（同一 `openOrder`、同一 `!canWrite \|\| !db.cart.length` 禁用条件 + viewer tooltip）。取舍理由：行业惯例「底部结算条为唯一结算入口」，避免顶部/底部双主按钮争夺视觉焦点；`page-head` 为 flex 布局，删右侧块后左侧标题区自然占满，布局不塌 | `views/cart/index.vue` |
| 2 | 修改 | **「清空购物车」移至表格卡 `.table-head` 右侧**（与「共 N 件」同行，scoped `.th-right` flex 容器），样式由 `danger plain` 红块降为 `el-button link type="danger" size="small"` 文字按钮；二次确认（ElMessageBox.confirm）与 viewer 禁用 tooltip 逻辑原样保留 | `views/cart/index.vue` |
| 3 | 修改 | **删除「主体」列**（购物车强制同主体，tag 冗余），主体信息改在 info-bar 文案开头体现「当前购物车主体：{subject 全称}」（新增展示用 computed `cartSubject`，取第一条 `cartRows[0].asset.subject`）；`entityShort` 导入随之移除 | `views/cart/index.vue` |
| 4 | 修改 | **单价/小计列右对齐**（`align="right" header-align="right"`，表头同步），列宽 140→130 / 150→130；**删除「可售」独立列**，库存状态并入「数量」列输入框下方 12px 次级文字：可重复售卖显示「不限」（.muted）、未达上限「可售 N」（.muted）、已达上限「已达上限 N」（`var(--danger-color)`，原硬编码 `#c62828` 清零）；「数量」列宽 150→160；「操作」列 90→70 并去掉 `fixed="right"`（列减少后无溢出风险）；border+stripe 保留 | `views/cart/index.vue` |
| 5 | 修改 | **底部合计行升级为独立结算条** `.cart-settle`：浅蓝底 `#f0f6ff`（与 info-bar 既有浅底色一致，未引入新色值）、圆角 8px、内边距 14px 16px、上边距 14px，flex 两端对齐——左「合计 N 件」（.muted 13px），右合计金额（18px/700/主色 + `font-variant-numeric: tabular-nums`）+「下单」主按钮；`.cart-subtotal` 同步加等宽数字 | `views/cart/index.vue` |
| 6 | 修改 | **空态按钮文案**「去资产列表添加」→「去选择资产」（与站内「资产管理」叫法一致，图标 ShoppingCart 保留） | `views/cart/index.vue` |

### 既有功能未受影响的依据

- 数据逻辑/API/权限零改动：`cartRows/totalQty/totalAmount` 计算、`onQtyChange`（超限回退提示）、`removeRow`、`clearAll`（二次确认）、`openOrder`/`onOrderSubmit`（下单对话框 + 成功跳项目详情）、`canWrite`/`READONLY_TIP` 全部原样；仅新增展示用 `cartSubject` computed。
- 未动 `global.css`（新增类均为本页 scoped：`.th-right`/`.cart-qty-hint`/`.cart-settle*`）；无 Element 默认色、无「万」字金额（继续 `formatMoney`）。

### 未验证 / 风险点

- 未执行 `build/deploy`（按约束禁止）；验证 = Vite HMR 模块 curl 200 + IDE 诊断 0 error。
- 结算条未加 info-bar 同款 1px 描边（任务仅要求底色/圆角/内边距），白卡内浅蓝块观感略"浮"，如需更贴 info-bar 规格可后续补 `border: 1px solid #e0ecff`。
- 数量列下方新增提示行使该行行高增大（约 20px），stripe 斑马纹跨行高度变化属预期。

---

## 2026-10-15 ｜ 账号与审计表格对齐规范 + 出库记录关联项目跳转

**关联任务**：两个前端修复（小改，禁止重构）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **账号与审计页「账号列表」表格对齐站内列表页规范**：账号表 6 列原全部固定 `width`（合计 790px），无 `min-width` 列吸收剩余空间，导致表格填不满卡片（实测容器 970px，右侧留白 ~180px）、操作列偏离卡片右缘（观感「又窄、操作列偏左」）；「姓名」列 `width="140"` → `min-width="140"`，表格撑满卡片、`fixed="right"` 操作列贴住右缘。经浏览器实测（整页刷新 / HMR 更新 / 页签切换）DOM 仅单组 `thead`、行高 40px 与销售项目列表一致，截图中的「双层表头/扁行」为 HMR 会话瞬态渲染残留，当前源码不可复现，无对应代码缺陷。「共 N 条」计数行、状态/角色 tag、「当前登录」标记、空态 `el-empty`、`.op-actions`（与项目列表同款）均为既有实现，未改动；审计日志表已含 `min-width` 列（对象/详情），同规格核对无问题 | `views/settings/users.vue` |
| 2 | 新增 | **出库记录「关联项目」列可点跳项目详情**：`projectId` 存在时项目名渲染为文字链接（scoped `.link`：`var(--primary-color)` / hover `var(--primary-hover)` + 下划线，与资产详情页 `.link` 同规格，未引入新色值），点击 `router.push('/sales/projects/{id}/detail')`（与项目列表 `goDetail` 同路由，整页路由非新窗口）；无 `projectId` 的行（历史补录带项目名 / 纯补录）保持纯文本或「补录」tag，不可点、无下划线。本页无抽屉详情，无需同步处理 | `views/sales/outbound/index.vue` |

### 既有功能未受影响的依据

- 账号 CRUD 弹窗（新增/编辑/删除、自己那行禁改角色/启用）、审计页签（筛选/分页）、路由守卫 admin 拦截均未改动；出库页补录/撤销逻辑、`canWrite` 只读禁用未动。
- 未改后端、API 层、权限逻辑；未动 `global.css` token，未引入 Element 默认色。

### 未验证 / 风险点

- 未执行 `build/deploy`（按约束禁止）；验证 = Vite HMR 两模块 curl 200 + IDE 诊断 0 error + 浏览器实测（账号表 970/970 撑满、单 thead、行高 40px；出库链接点击实跳 `/sales/projects/8/detail`，无项目行 `hasLink:false`）。
- 「双层表头」为截图态现象，当前源码多路径复现均为单表头；若用户浏览器仍见双层，硬刷新（Ctrl+Shift+R）即可消除 HMR 残留。

---

## 2026-10-15 ｜ 资产模块三项 UI 优化（销售单价展示 / 详情补字段 / 表单单列）

**关联任务**：资产模块三项 UI 优化（用户直接反馈，定点修改，不重构）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **资产侧「单价」展示标签统一为「销售单价」**：资产列表抽屉「关键信息」区 label（`list.vue:522`）、购物车表格列头（`cart/index.vue:195`，列值为 `asset.salePrice`）。销售项目侧「单价」（`sales/projects/detail.vue:235`、`sales/projects/create.vue:452` 的 item.price）与资产创建/编辑表单的输入标签「单价（元）」（`create.vue:296`，属表单 label 非展示标签）均未动 | `views/assets/list.vue`, `views/cart/index.vue` |
| 2 | 修改 | **资产详情「基本信息」补「销售单价」**：右栏「库存与归属」卡片在「可售数量」后新增 info-item，`formatMoney(asset.salePrice)`（0 显示 `-`，可重复售卖资产追加 `/ 单位`，与列表抽屉口径一致）；该卡片为 `info-grid-1` 单列栅格，加项不产生错位，库存数字未挪动 | `views/assets/detail.vue` |
| 3 | 修改 | **资产创建/编辑表单改单列**：scoped 覆盖全局 `.form-grid` 为 `grid-template-columns: 1fr; gap: 0`（仅本页生效，outbound/项目创建页的 `.form-grid` 不受影响）；行距交回组件既有 18px `margin-bottom`（删除原 grid 内 `margin-bottom:0` 覆盖）；控件宽度沿用模板既有 `style="width:100%"`（el-select/el-date-picker/el-input-number），el-input 默认 100%，上传按钮保持自然宽；内容区 `max-width` 1080px → 720px（单列下 1080px 输入框过宽过散）。骨架（.back-link/标题/.form-card/.bottom-actions）、金额 ×10000/÷10000 桥接、校验规则、提交 payload、viewer 禁用 tooltip 均未动 | `views/assets/create.vue` |
| 4 | 修改 | **资产创建/编辑表单「单价（元）」label 统一为「销售单价（元）」**（`create.vue:296`，与上一轮展示标签口径一致）；同区块提示语 `bh-hint`「…计量单位与单价（元）」一并改为「销售单价（元）」（`create.vue:287`）。v-model 绑定、×10000/÷10000 桥接、校验规则、placeholder 均未动 | `views/assets/create.vue` |

### 既有功能未受影响的依据

- 金额展示继续走 `formatMoney`（元口径 ¥+千分位+两位小数），未引入「万」字金额与 Element 默认色；global.css token 与既有骨架类名未动。
- 创建/编辑页金额桥接（`* 10000` / `/ 10000`）、`rules` 校验、`handleSubmit` payload、`perpetual` 联动（勾选长期买断禁用到期时间并清空）、卫星数据自动开启可重复售卖的 watch 均一行未改。
- viewer 只读禁用（READONLY_TIP tooltip + `:disabled="!canWrite"`）在三个改动文件中均保持原样。

### 未验证 / 风险点

- 未执行 `build`（按约束禁止）；验证方式 = Vite dev server 四个改动模块 curl 200 + IDE 诊断 0 error。
- 单列布局未在真实浏览器逐屏走查（无浏览器自动化），窄屏（<680px）下与全局 1 列媒体查询等效，预期无差异。

---

## 2026-10-15 ｜ 全站接入登录态与角色权限（⚠️ Breaking）

**关联任务**：core-holdings 前端接入权限管控系统（对齐后端 2026-10-15 认证/权限契约，`docs/backend/api.md`）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 ⚠️ | **认证态管理**：`localStorage` 持久化 `token`/`currentUser`；响应式 `currentUser` + `canWrite`（非 viewer）/`isAdmin` 权限辅助；`setSession/clearSession/setUser`。本模块不依赖 axios（避免与 api 循环导入） | `src/auth.ts`（新建） |
| 2 | 新增 ⚠️ | **axios 拦截器接入登录态**：请求拦截器统一附加 `Authorization: Bearer <token>`，并对 viewer 的任何非 GET 请求在发出前直接 reject「只读账号无操作权限」（全局写兜底）；响应拦截器新增 401 处理（清本地态 + 整页跳 `/login?redirect=…`，登录接口自身 401 不跳转、留在登录页提示），403 走既有 `detailMessage` 解析提示「无权限执行此操作」。既有 422 数组解析、`detailMessage`、`afterWrite` 时序均未改动 | `src/api/index.ts` |
| 3 | 新增 | **认证/账号/审计 API 函数**：`login/fetchMe/listUsers/createUser/updateUser/deleteUser/listAuditLogs`，字段逐字对齐 `docs/backend/api.md`（`UserOut` 不含 `createdAt`，前端按可选字段兜底显示 `-`） | `src/api/index.ts` |
| 4 | 新增 | **登录页 `/login`**（独立布局，不进 MainLayout）：居中白卡（平台 token 色，无 Element 默认色）+ 用户名/密码 + loading 防重复提交；成功 → `setSession` → `await refresh(true)` → `ElMessage.success('登录成功')` → 跳回 `route.query.redirect`（缺省 `/`）；错误提示走后端中文 detail | `src/views/login/index.vue`（新建） |
| 5 | 修改 ⚠️ | **路由守卫**：无 token → 非 `/login` 一律重定向 `/login?redirect=…`；有 token 访问 `/login` → 回 `/`；token 在但 `currentUser` 缺失（新标签页刷新）→ `fetchMe()` 校验（401 由拦截器清态跳登录）；`/settings/users` 仅 admin，非 admin 直接访问 → 提示并回 `/` | `src/router/index.ts` |
| 6 | 修改 | **MainLayout**：顶栏「系统运行中」旁新增当前用户名 + 角色标签（管理/可编辑/只读，复用 global.css `tag-blue/green/gray` 色板）+「退出」按钮（确认弹窗 → 清本地态 → 跳 `/login`）；侧边「基础设置」下新增「账号与审计」子项（仅 admin 显示）；购物车菜单项对 viewer 禁用 | `src/layouts/MainLayout.vue` |
| 7 | 新增 | **账号与审计页 `/settings/users`**（admin 专用，骨架沿用 settings 风格：.page-head + .stat-cards + .info-bar + 白卡表格）：「账号管理」页签（账号表格 + 新增/编辑/删除弹窗；自己那行禁用改角色/启用与删除，改密可空）；「审计日志」页签（操作类型/操作人筛选 + 表格 + 分页 pageSize 20，类型中文映射 sale/outbound/asset_change/setting/user_mgmt/auth/other） | `src/views/settings/users.vue`（新建） |
| 8 | 修改 | **角色化 UI（viewer 写入口禁用 + tooltip「只读账号无操作权限」，布局不变）**：资产列表（登记资产/加购/行内编辑/抽屉编辑·销售·去上传）、资产详情（编辑资产/登记销售×2/删除资产/交付物新增/标记就绪·退回）、资产创建（上传/替换/移除/提交）、销售项目列表（新增/编辑/状态/删除）、项目创建编辑（保存草稿/创建/修改状态/保存修改）、项目详情（编辑/修改状态）、出库（补录/撤销）、购物车（清空/下单/移除）、基础设置（新增/编辑/删除）、交付物模板（新增×2/编辑/删除）。行内按钮包 `span` 承载 tooltip，间距样式随各页补充，`.op-actions` 结构未破坏 | `views/assets/list.vue`, `views/assets/detail.vue`, `views/assets/create.vue`, `views/sales/projects/index.vue`, `views/sales/projects/create.vue`, `views/sales/projects/detail.vue`, `views/sales/outbound/index.vue`, `views/cart/index.vue`, `views/settings/base.vue`, `views/settings/deliverables.vue` |
| 9 | 修改 | **App 挂载拉取加登录态前置**：未登录不再请求 `/api/bootstrap`（避免首屏 401 噪音），登录页成功后自行 `refresh(true)` | `src/App.vue` |

### 既有功能未受影响的依据

- `refresh()` 全量拉取逻辑、`afterWrite()` 时序、422 `detailMessage` 解析、写操作 catch 提示、状态机 `canGo`、`.op-actions` 结构均未改动（仅拦截器在既有错误处理**之前**插入 401 分支）。
- 页面骨架类名（.page-head/.stat-cards/.info-bar/.table-head/.form-card）与 global.css token 未动；新页面/新标签全部复用既有 token 色板，无 Element 默认色。
- editor/admin 的写路径行为与接入前一致（请求仅多带 Bearer 头）。

### 未验证 / 风险点

- 未执行 `build`（按约束禁止）；验证方式 = Vite dev server 各改动模块 curl 200 + IDE 诊断 0 error + curl 模拟接口层（登录/401/403/400 自限/审计过滤均实测通过）。
- `UserOut` 实际不含 `createdAt`（任务描述与文档不一致，以 `docs/backend/api.md` 与后端 schema 为准），创建时间列显示 `-`。
- viewer 直接访问编辑页 URL（如 `/assets/1/edit`）仍可进入表单页，但提交/上传按钮均禁用且 API 层兜底拦截；未做整页级路由拦截（按任务要求以按钮禁用为准）。
- 测试账号 `viewer1`/`editor1`（密码 `t123456`）已创建，供三角色走查使用，可在「账号与审计」页删除。

---

## 2026-10-14 ｜ 高危/中危缺陷修复（H2/H3/H5/H6/H9/H10/H11/D2/M1-M11）

**关联任务**：core-holdings 前端缺陷修复（对齐后端 2026-10-14 冻结契约）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **H5** 明细金额改为元级精度：`calcItemAmount` 由 `round(×100)/100`（万元 2 位）改 `round(×10000)/10000`（万元 4 位） | `views/sales/projects/create.vue` |
| 2 | 修复 | **H6** 「更多设置」金额区恢复录入入口：预计销售 / 报价 / 合同 / 已回款 4 个金额面板（元口径 ×10000/÷10000 桥接）；未手填「预计销售金额」时自动跟随明细合计，手改后不再覆盖 | `views/sales/projects/create.vue` |
| 3 | 修复 | **H9** 数量输入统一整数：`assets/create.vue`（资产总数）、`sales/projects/create.vue`（明细数量）、`sales/outbound/index.vue`（出库数量）`:precision` 由 2 改 0、`:step="1"` | `views/assets/create.vue`, `views/sales/projects/create.vue`, `views/sales/outbound/index.vue` |
| 4 | 修复 | **H10** 资产详情增加「未找到该资产」空态（`v-else` + `el-empty` + 返回资产台账按钮），直达无效 id 不再白屏 | `views/assets/detail.vue` |
| 5 | 修复 ⚠️ | **D2** 项目删除由本地 `splice` 的「假删除」改为真实 `deleteProject(id)` → `DELETE /projects/{id}` + `afterWrite()`；二次确认文案说明「释放库存锁定并撤销该项目出库」，成功/失败均有提示 | `api/index.ts`, `views/sales/projects/index.vue` |
| 6 | 修复 ⚠️ | **H3** 创建/编辑表单移除「项目状态」选择项；`ProjectInput` 移除 `status` 字段、payload 不再提交 status（后端强制 active）；状态仅经「修改状态」动作流转 | `api/index.ts`, `views/sales/projects/create.vue` |
| 7 | 修复 | **H2** 已完成/已终止项目隐藏「编辑」入口并给出 tooltip 说明（列表 + 详情） | `views/sales/projects/index.vue`, `views/sales/projects/detail.vue` |
| 8 | 修复 | **M1/H11** 资产状态口径统一：`assets/create.vue` 由 `ASSET_STATUS`（库存可售/全部出售）改派生 `ASSET_STOCK_STATE`（库存可售/暂无库存）；首页「临期资产」待办筛选由 `a.status==='in_stock'` 改 `!noSellableStock(a)`；删除已无引用的 `ASSET_STATUS`/`AUTO_STATUSES` | `types.ts`, `api/index.ts`, `views/assets/create.vue` |
| 9 | 修复 | **M2** 操作记录按 `assetId` 精确过滤（`OpLog` 新增可选 `assetId`），消除重名资产日志串台 | `types.ts`, `views/assets/detail.vue` |
| 10 | 修复 | **M3** 切换板块时重置筛选：清空 `subjectFilter/inboundMonth/searchText`、`satelliteTab` 归位；移除原 `b==='satellite'?'all':'all'` 无效三元 | `views/assets/list.vue` |
| 11 | 修复 | **M4** 销售明细数量以 `availableQty(asset)` 为 `:max`（可重复售卖不限制），提交前校验数量 > 0 且不超可售上限 | `views/sales/projects/create.vue` |
| 12 | 修复 | **M5** 单资产下单对话框：数量变化且用户未手改合同金额时自动重算 `contractText` | `components/SalesOrderDialog.vue` |
| 13 | 修复 | **M7** 出库「新出库」校验 `qty ≤ 可售`（可重复售卖不限制），超量即时提示并阻止提交；资产下拉在新出库模式排除无可售库存资产，历史补录放开 | `views/sales/outbound/index.vue` |
| 14 | 修复 | **M8** 写操作补错误提示：资产删除、基础设置保存、交付物模板保存 补 `try/catch` + `ElMessage.error`，不再失败静默 | `views/assets/detail.vue`, `views/settings/base.vue`, `views/settings/deliverables.vue` |
| 15 | 修复 | **M9** 全局 `refresh()` 失败兜底：`App.vue` 挂载时拉取失败提示「数据加载失败，请检查后端服务」 | `App.vue` |
| 16 | 修复 | **M10**「登记销售」预填数量：可重复售卖 `availableQty` 为 null 时预填默认 `1`，避免 null | `views/sales/projects/create.vue` |
| 17 | 修复 | **M11** 响应拦截器兼容 422：`detail` 为数组时按 `loc`+`msg` 拼接为可读提示（字符串/对象亦兼容），不再退化为 status 422 | `api/index.ts` |
| 18 | 删除 ⚠️ | 契约 2：移除 `changeAssetStatus` 导出（后端已删 `PATCH /assets/{id}/status`，前端无调用） | `api/index.ts` |
| 19 | 修复 | 低优先：列表状态流转文案由旧 6 段流程改为 3 态（进行中/已完成/已终止）；`hasTodos` 更名语义正确的 `noTodos`；可重复售卖「可售数量」显示「不限」；返回入口改为「有历史 `router.back()`，否则 `router.push` 列表页」 | `views/sales/projects/index.vue`, `views/dashboard/index.vue`, `views/assets/detail.vue`, `views/assets/create.vue`, `views/sales/projects/create.vue`, `views/sales/projects/detail.vue` |

### 未改动 / 保持不变的既有行为（回归依据）

- 页面骨架、`global.css` token、`formatMoney` 口径（元 ¥+千分位+两位小数）均未改动。
- 购物车 → 下单 → 出库链路、单/多资产直接下单流程未改逻辑。
- 项目状态机 `canGo` 三处（列表/详情/编辑）保持完全一致；提交 `submitting` loading 防重复未变。
- 预填页 `onMounted` 内 `await refresh()` 的读取顺序未变。
- 资产列表/抽屉/算力页继续使用 `ASSET_STOCK_STATE` + `assetStockState`，视觉与配色未变。

### 未验证 / 风险点

- 未执行 `build`（按约束禁止），仅依赖开发服务 HMR + IDE 类型诊断（0 error）验证。
- `el-tooltip` 包裹 `span` 承载 disabled 按钮为 Element Plus 推荐用法，未在真机逐一点验；
- 「预计销售金额」自动跟随明细合计依赖 `watch(itemsTotal)` 的 flush 时序（编辑模式同步置 `expectedTouched` 后生效），未做极端并发输入测试。

---

## 2026-10-14 ｜ 前端收尾修正（写操作时序 + 编辑页 active 守卫）

**关联任务**：core-holdings 前端收尾修正（2 项，小改动，不重构）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **写操作「成功却弹失败」时序缺陷**：`afterWrite()` 内 `try/catch` 包裹 `refresh(true)`——刷新阶段失败时 `ElMessage.warning('操作已生效，但数据刷新失败，请手动刷新页面')` 并吞掉异常、不向上抛；**写请求本身失败仍照常上抛**，调用方 catch 提示不变。覆盖 `createAsset/updateAsset/deleteAsset`、`createProject/updateProject/changeProjectStatus/deleteProject`、`createOutbound/revertOutbound`、购物车全部写操作（`addToCart/addCartBatch/setCartQty/removeCartItem/clearCart/checkoutCart/createSaleOrder`）、基础资料（`addBase/updateBase/deleteBase`）、交付物（`add/update/deleteTemplateItem`、`add/update/removeAssetDeliverable`）全部调用点 | `api/index.ts` |
| 2 | 修复 | **编辑页缺 active 守卫（直达 URL 可绕过）**：`onMounted` 读取项目后（既有 `await refresh()` 预填逻辑之后）校验 `p.status === 'active'`；非 active 时 `ElMessage.warning('已完成/已终止项目不可编辑')` 并 `router.replace` 到该项目详情页（`/sales/projects/:id/detail`），不进入表单。项目不存在时不触发（仍走既有未找到处理）。 | `views/sales/projects/create.vue` |

### 说明

- 修正 1 采用方案 (a)：仅在 `afterWrite()` 内收敛刷新失败，各调用方代码零改动。
- 修正 2 的路由：任务书写作 `/sales/projects/:id`，实际详情页路由为 `/sales/projects/:id/detail`（与列表 `goDetail`、详情页自身一致），已按实际路由跳转。
- 「保持既有正确行为」回归依据：状态机 `canGo` 三处、`submitting` loading 防重复、`onMounted` 内 `await refresh()` 预填顺序、删除二次确认均未改动；未引入新 UI 组件，未改动 `global.css` token。

### 未验证 / 风险点

- 未执行 `build/deploy`（按约束禁止），仅依赖开发服务 HMR（`create.vue` / `api/index.ts` 模块均 200）+ IDE 类型诊断（0 error）验证。
- 非 active 直达编辑 URL 的跳转依赖 `db.projects` 已由 `refresh()` 填充；若后端 `/bootstrap` 返回滞后导致项目暂时缺失，会先走既有未找到路径（不误拦）。
- 刷新失败提示为单条 `ElMessage.warning`，未做「同页面多次写操作并发刷新失败」的合并去重。

---

## 2026-10-15 ｜ 销售项目列表「操作」列按钮对齐修复

**关联任务**：销售项目列表操作列按钮对齐优化（小改，禁止重构）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | 操作列「编辑」按钮去掉 `v-if/v-else` 双分支：改为**恒渲染单个** `el-button`（`:disabled="row.status !== 'active'"`，仅变灰占位），`el-tooltip` 恒包裹（启用行 `:disabled` 关闭提示），每行 DOM 结构与顺序完全一致 | `views/sales/projects/index.vue`（操作列模板 ~L257-282） |
| 2 | 修复 | 4 个按钮统一包进 `.op-actions`（`display:flex; gap:8px`），间距不再依赖 Element Plus `.el-button + .el-button` 相邻兄弟选择器（原禁用行因 tooltip 的 span 隔断，「状态」按钮丢失 12px margin 导致行间距不一致）；scoped 样式内 `:deep(.el-button + .el-button){margin-left:0}` 消除叠加 | `views/sales/projects/index.vue`（scoped style ~L355-370） |

### 核查结论（同项目其他列表页）

- `views/assets/list.vue` 操作列：2 个按钮（加入购物车/编辑）均恒渲染、无 disabled 分支，间距来自统一的 `.el-button + .el-button` 选择器，观感一致，**不改动**。
- `views/sales/outbound/index.vue` 操作列：单按钮「撤销」，非 done 行渲染 `<span class="muted">-</span>` 占位（列宽 90，居中），属既有设计且观感正常，**不改动**。

### 未改动 / 保持不变的既有行为（回归依据）

- 列宽（230）、其他列、表格骨架、`global.css` token 均未动；「删除」红色沿用既有 `type="danger"`，未引入新色值。
- 按钮风格保持既有 `link` + `size="small"`；`@click.stop` 阻止行点击冒泡的行为不变。

---

## 2026-10-15 ｜ repeatSale 前端配套：「不限」第三态 + 编辑页警示/实时联动

**关联任务**：repeatSale 的 2 项前端配套（警示 + "不限"第三态，小改）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `AssetStockState` 增加第三态 `'unlimited'`：`assetStockState()` 最优先判定 `a.repeatSale → 'unlimited'`（non-repeatSale 判定逻辑一行未动）；`ASSET_STOCK_STATE` 标签表加 `unlimited: { label: '不限', tag: 'info' }`（复用既有 info muted 色，未引入新色值）；`ProjectItem` 接口加 `locked?: boolean`（仅类型声明，对齐后端出参契约，存量数据 false） | `src/types.ts`（L117-128、L188） |
| 2 | 修改 | 编辑/创建页：repeatSale 开关下方新增警示行「开启后该资产不再受库存限制：售罄资产也可继续下单，销售只计次、不扣减库存数量」（muted 12px）；`stockState` computed 改为基于 form 实时值派生（`form.repeatSale → 'unlimited'`，否则 `form.quantity` + 编辑模式已存 lockedQty/shippedQty、创建模式 0 走 `noSellableStock`），勾选/取消瞬间状态标签即时联动 | `src/views/assets/create.vue`（L29-30、L97-114、L311、scoped style） |

### 展示面核查（unlimited 消费逐页确认，无 undefined/空白）

- **assets/list.vue**：状态列 L380-381 经 `ASSET_STOCK_STATE[assetStockState(row)]` 渲染 → repeatSale 资产显示「不限」（info muted tag）；快览抽屉 L417-418 同；状态筛选下拉 L320 遍历 `ASSET_STOCK_STATE` 自动多出「不限」选项，筛选逻辑 L82 走同一派生函数，口径一致；数量列「重复售卖」tag（success plain）保留——与状态列「不限」不冗余：前者解释数量列为何无数字，后者是库存状态，语义不同。
- **assets/detail.vue**：标题状态胶囊原二态 `ok/off`，`unlimited` 会误落红色 off 分支 → 已补第三态 `na`（灰蓝 muted，复用 global.css `.el-tag--info` 既有色值 #71829a/#eef2f8，dot 用 ∞）；「可售数量：不限」（L389 既有）与「不限」胶囊并存，无矛盾文案。
- **assets/compute.vue**：状态列 L65-66 同经标签表渲染，repeatSale 算力资产显示「不限」，无未知状态分支。
- **assets/create.vue**：状态标签 L320-321 经 `ASSET_STOCK_STATE[stockState]` 渲染，`stockState` 现恒为三态之一。
- 全仓 `assetStockState`/`ASSET_STOCK_STATE`/`'in_stock'` 消费点已逐一核查（仅上述 5 文件），无其它落入未知分支处；`noSellableStock`（禁止登记销售/编辑提示）逻辑未动，repeatSale 下单/购物车逻辑一行未动。

### 风险 / 未验证点

- 未执行 build/deploy（按约束禁止）；验证方式：HMR 各模块 200（5173）+ IDE 0 error。
- 编辑页 `stockState` 联动后，修改「资产总数」也会实时改变状态标签（预期行为，与「实时联动」口径一致）；保存前刷新页面会丢失未保存修改（既有行为）。
- 「不限」tag 采用 info muted 色；列表数量列「重复售卖」tag 仍为 success plain（既有实现，未动），两处色系不同但语义分工明确。

## 2026-10-15 ｜ 资产列表 selection 列点击不再触发快览抽屉

**关联任务**：资产列表复选框列（selection 列）点击禁止触发抽屉（小改）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `@row-click="openDrawer"` 改为 `@row-click="onRowClick"`：新增 `onRowClick(row, _column, event)`，`event.target.closest('.el-table-column--selection, .el-table-selection-column')` 命中 selection 列（行复选框 / 该列留白）时直接 return，不打开抽屉。根因：EP 2.14.2 行复选框已内置 `onClick: stopPropagation`（`config.mjs` renderCell），但 selection 单元格留白点击仍冒泡到 `<tr>` 触发 row-click 误开抽屉；表头全选框位于 thead 本就不在 row-click 覆盖范围。选择器同时兼容旧版 class `el-table-selection-column`。其它列 row-click 开抽屉、名称列整格 stop 分工（名称=详情 / 其余=勾选）一行未动 | `src/views/assets/list.vue`（L149-155 新增 onRowClick、L371 表格绑定） |

### 验证

- agent-browser 实测（127.0.0.1:5173，admin）：点行复选框 → `checked=true` 且 drawer 不可见；点表头全选 → 4/4 勾选、无抽屉；点 selection 列留白（td.click）→ 不勾选、无抽屉；点「资产总数」列 → 抽屉打开且标题正确；名称列次级行点击 → 该行勾选、无抽屉（行为不变）。
- HMR 模块 200（5173）+ IDE 0 error；未执行 build/deploy（按约束禁止）。

---

## 2026-10-15 ｜ 合同层级（ADR-007）第二批：列表/看板/关联展示收口

**关联任务**：合同层级（ADR-007）前端·第二批（列表/看板/关联展示收口）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `Outbound` 接口补 `contractId?: number \| null`（对齐 bootstrap 出参：合同交付自动出库非空，存量/手工补录 null；仅类型声明，无逻辑） | `src/types.ts`（L289） |
| 2 | 修改 | 销售项目列表：① 客户列改 `customerText(p)`——`p.customer \|\| (contractCount>1 ? 'N 位客户' : '-')`（存量无合同项目 customer 为空 → '-'，与原展示一致）；② 客户列后新增「合同数」窄列（width 80，0/缺失 → '-'）；③ 编辑按钮可见性从 `status==='active'` 改为 `canEditProject(p)`：有合同项目 = 名下**无 delivered 合同**且项目非 terminated（对齐后端 PUT /projects 400 规则，后端另对存量无合同项目保留 status!=active 旧规则，前端 `!contractCount` 分支沿用原判定）；tooltip 文案同步 | `src/views/sales/projects/index.vue`（L50-65 新增两函数、L157-165 客户/合同数列、L196-207 编辑按钮） |
| 3 | 修改 | 资产详情「销售关联」页签：① `projectSubject(p)` 扩展为 `projectSubject(p, item)` 三级兜底——项目 subject → 本行明细所属合同 subject（`db.contracts.find(c=>c.id===item.contractId)?.subject`）→ 明细资产自身 subject → '-'；存量行（contractId=null）走原资产主体兜底路径，既有行为不变；② 项目行「合同数」加在**名称次级行**（`SP-xxx · N 份合同`，contractCount 缺失/0 显示「1 份合同」）——次级行本为 12px muted 辅助信息位，不加新列，最不打扰布局 | `src/views/assets/detail.vue`（L46 引入 ProjectItem、L290-307 两函数、L619 次级行、L627 模板传 row.item） |
| 4 | 修改 | 出库列表新增「关联合同」列（放「关联项目」列后，width 110）：contractId 非空且合同存在 → 合同号整词**纯文本 mono**（`.contract-code` 与项目详情页同字体栈，**不跳转**——合同无独立详情页，避免死链），hover tooltip 显示「合同客户：X」；contractId 为 null 或合同已随项目删除 → '-' | `src/views/sales/outbound/index.vue`（L36-42 contractOf、L293-304 新列、L477-484 样式） |

### 编辑按钮可见性边界说明（`canEditProject`）

- **存量无合同**（contractCount=0/缺失，当前库内全部 10 个项目均为此态）：走 `status==='active'` 原判定，与后端 `p.contracts` 为空的旧规则分支逐字一致；
- **有合同·全 terminated**：`every(status!=='delivered')` 为 true，但派生 `status==='terminated'` → 禁用（后端此态不 400，前端从严禁用，避免编辑已终止项目的困惑；后端 400 仍为最终兜底）；
- **有合同·混合 active+terminated（无 delivered）**：可编辑（后端同样放行）；
- **有合同·含任一 delivered**：禁用，与后端 400「已交付完成的项目不可编辑」一致；
- 理论不一致态（contractCount>0 但 db.contracts 无对应行）：`every()` 空数组为 true → 按 terminated 与否放行；该态由后端派生保证不出现，且后端 400 兜底。

### 主体兜底三级顺序论证（`projectSubject`）

1. `p.subject` 非空（单合同派生值）→ 直接返回，与旧版第一级一致；
2. 空且 `item.contractId` 非空 → 取该合同 subject（合同内强制同一资产主体，与旧版「首条明细资产主体」结论等价但更贴近本行，且不受项目内其它明细干扰）；
3. 空且 `contractId` 为 null（存量明细）→ 走旧版原路径（本行 item 有 assetId 即取之，否则回退项目首条有资产明细），返回资产 subject 或 '-'。旧版两条既有分支的输入输出完全保留，未改坏既有行为。

### 看板 / 购物车角标走查结论（零改动）

- **看板 `views/dashboard/index.vue`**：全部指标来自 `getDashboard()`（`src/api/index.ts` L318-384），口径=资产字段（quantity/lockedQty/shippedQty/salePrice/soldAmount/status）+ 项目派生字段（status/contractAmount/lastFollowDate）。ADR-007 下这些字段由后端按合同重算后回传，前端不感知合同结构 → **零改动**。待办「长期未更新项目」仅筛 `status==='active'` 且跳编辑页：active 项目必含 active 合同且无 delivered（否则派生为 delivered/terminated），恰在可编辑集合内，跳转不会落到禁用编辑页。
- **购物车角标 `layouts/MainLayout.vue` L134**：`db.cart.reduce((s,c)=>s+c.qty,0)` 按**行**求和；跨主体混装后同资产不同客户为多行（后端唯一键 (userId, assetId, customer)），每行独立计数，角标=购物车总件数，语义正确无异常。购物车页 `views/cart/index.vue` 已是行级客户 + 按客户分组结算预览（ADR-007 第一批完成），本次复核无需改动。

### 验证

- curl 实测 bootstrap（admin）：`contracts[]`（含 code/customer/subject/status/items[].contractId）、`projects[].contractCount`、`outbounds[].contractId` 均回传，字段名与 `docs/backend/api.md` 一致；当前库 contracts=0、10 项目 contractCount 全 0（存量态），出库 CK-0014 contractId=1（合同已随项目删除 → 列显示 '-' 的兜底路径）。
- HMR 4 模块 200（5173：types.ts / projects/index.vue / assets/detail.vue / outbound/index.vue）+ vue-tsc 0 error + IDE 0 error；未执行 build/deploy（按约束禁止）。

## 2026-10-15 ｜ 资产创建/编辑页移除交付物附件上传 + 「状态与备注」排版重做；详情页同步清理

**关联任务**：资产创建/编辑页——移除交付物附件上传 + 「状态与备注」排版重做（小改）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 删除 | 创建/编辑页「状态与备注」卡片移除「产品清单」「功能清单」两个上传块（含隐藏 file input、已上传态预览/替换/移除操作、两个全屏预览对话框）；同步删除本地状态与函数：`contractInputRef`/`uploading`/`previewVisible`/`contractOrigName`/`pickContract`/`onContractPicked`/`previewContract`/`removeContract`/`contractDisplayName` 及 feature 同套 7 个；`form` 移除 `contractFile`/`featureDoc` 两字段（含 `loadAsset` 回显行）→ **提交 payload 不再携带 `contractFile`、`featureDoc`**（`AssetInput` 两字段均为可选，`types.ts` 未动）；无引用 import 一并清理（`uploadFile`/`fileDisplayName`/`fileUrl`/`FilePreview`/`Upload`/`Document`/`assetStockState`） | `src/views/assets/create.vue`（L8-12 注释、L14-33 import、L49-64 form、L118-139 loadAsset、原 L142-220 上传逻辑整段、原 L376-431 两个上传 form-item、原 L447-463 两个预览 dialog、`.contract-up` 样式） |
| 2 | 修改 | 「状态与备注」卡片排版重做：删完上传后仅剩两行规整表单行——① 资产状态行：沿用 `label-position="top"` 表单 label，控件区 `.status-line` 改 `flex-direction:column; align-items:flex-start; gap:6px`，muted 12px 提示「状态由库存自动判定，无需手动修改」置于 tag 正下方一行、左缘与 tag 对齐（原同行排布在大号 round tag 旁视觉拥挤）；② 备注行：label + 全宽 textarea 不变；卡片标题与图标样式不动 | `src/views/assets/create.vue`（L258-268 状态/备注 form-item、`.status-line`/`.status-tip` 样式） |
| 3 | 删除 | 详情页「交付物」页签内移除「功能清单」附件行（`.feature-doc-row`：已上传态文件名+预览+下载 / 未上传态「去上传」+ 隐藏 file input）及功能清单全屏预览对话框；同步删除 `featureInputRef`/`featureUploading`/`featurePreviewVisible`/`pickFeatureDoc`/`onFeaturePicked` 与无引用 import（`Document`/`fileUrl`/`fileDisplayName`/`uploadFile`/`updateAsset`/`FilePreview`）、`.feature-doc-row` 样式。**交付物页签本身保留**——其主体是标准交付物清单（`getAssetDeliverables` 独立数据集），并非 featureDoc 附件列表，仅移除其中 featureDoc 附件行 | `src/views/assets/detail.vue`（原 L261-286 脚本、原 L522-552 附件行、原 L826-833 预览 dialog、原 L1357-1382 样式） |
| 4 | 说明 | 详情页「产品清单」：`contractFile` 为**附件字段**（uploads 散列文件名，非纯文本），但详情页原本就**无任何展示区块**（全文无 contractFile 引用）→ 无内容可删，零改动。产品清单的现存展示面在资产列表页抽屉（`views/assets/list.vue` L529-555、L649-655），不在本次任务范围（A/B 限定 create.vue + detail.vue），如需一并收口请另行立项 | `src/views/assets/detail.vue`（无改动） |

### 兼容性说明（存量附件数据）

- 前端不再展示/上传 `featureDoc`/`contractFile`，但**后端字段与物理文件保留**（`models.py` 两列、`/upload` 落盘文件均不动，不回滚数据）；
- **编辑保存不会误清**：已读后端 `services.update_asset`（L243-259）确认其为字段级 patch——`for k, v in patch.items()` 仅处理 payload 中**实际存在**的键，未传键不触碰原值 → 前端不传 = 后端保持存量值，结论成立；
- 新建资产：`AssetInput.featureDoc/contractFile` 后端默认 `""`，新资产两字段为空，符合预期；
- 操作日志 diff（`ASSET_FILE_FIELDS`）仅在字段值变化时记录，不传不产生日志。

### 验证

- HMR 200（5173：`/`、`/src/views/assets/create.vue`、`/src/views/assets/detail.vue` 模块编译 200）+ vue-tsc 0 error + IDE 0 error；未执行 build/deploy（按约束禁止）。
## 2026-10-15 ｜ 资产列表快览抽屉移除「产品清单」附件块（收口）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 删除 | 快览抽屉移除「产品清单」附件整块（已上传态预览/下载行 + 未上传态「去上传」+ 隐藏 file input）及产品清单全屏预览 dialog；同步删除 `contractInputRef`/`contractUploading`/`pickContractFile`/`onContractPicked`/`previewVisible`/`openPreview` 与无引用 import（`Document`/`fileDisplayName`/`fileUrl`/`uploadFile`/`updateAsset`/`FilePreview`）、`.contract-*` scoped 样式。抽屉其余区块（关键信息、销售单价、库存、重复售卖标签、最近动态、操作按钮等）零改动；各 `.dr-section` 自带 `margin-bottom:18px`，删块后无空洞。与 create.vue/detail.vue 附件收口对齐，后端 `contractFile` 字段与存量文件保留不动 | `src/views/assets/list.vue`（原 L528-561 抽屉附件块、原 L649-655 预览 dialog、脚本 import 与上传/预览逻辑、`.contract-*` 样式） |

### 验证

- HMR 200（5173：`/src/views/assets/list.vue` 模块编译 200）+ vue-tsc 0 error + IDE 0 error；未执行 build/deploy（按约束禁止）。
## 2026-10-15 ｜ RsItemPicker 弹窗尺寸调大（遥感明细选择树局促）

**关联任务**：遥感数据「选择可售明细」树状弹窗整体调大一倍左右（小改）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `el-dialog` width 由 `520px` 调至 `880px`（约 ×1.7，落在 720–880px 区间），并新增 scoped 规则 `.el-dialog { max-width: 92vw }` 保证小屏下不超 92vw | `src/components/RsItemPicker.vue`（L107 width prop、style 区） |
| 2 | 修改 | 树区域 `.rs-tree` 高度约束调整：`max-height: 360px` → `min-height: 320px; max-height: 55vh`（保留 `overflow-y: auto` 内部滚动），明细多时可撑开至 55vh 后滚动，三级展开不再局促 | `src/components/RsItemPicker.vue`（`.rs-tree` 样式） |

### 兼容性说明

- 仅样式改动，脚本/模板逻辑零改动；顶部浅蓝说明条（`.info-bar`）与底部「已选 N 份 + 取消/确定」footer 原样保留；
- 两处使用方（`views/assets/list.vue` 加购、`views/assets/detail.vue` 登记销售）共用同一组件，自动生效，无需改动。

### 验证

- `npx vue-tsc --noEmit` 0 error；未执行 build/deploy（按约束禁止）。
## 2026-07-16 ｜ 平台弹窗（el-dialog）尺寸与表单排版统一优化

**关联任务**：全平台弹窗尺寸/表单排版统一（用户反馈：资产详情「新增明细」弹窗 label 折行、金额输入带步进按钮挤压、弹窗偏小）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | global.css 弹窗共享类：`.dlg-form`（640px / max-width 92vw）、`.dlg-wide`（880px / max-width 92vw）、`.dlg-hint`（12px #71829A 字段辅助说明）；`.dlg-form .el-form-item` 单列、label 96px 右对齐不折行（white-space: nowrap）、控件 100% 宽、表单项间距 18px；`.el-dialog` 基调统一：标题 16px/600 #1A2E4E、body padding 20px（原 22px 26px）、footer padding 16px 20px（原 14px 26px 20px）+ 上边框 1px #E7EDF5 + 按钮右对齐间距 12px | `src/styles/global.css` |
| 2 | 修改 | 「新增/编辑明细」弹窗 width `520px` → `.dlg-form`（640px）；label-width 90px → 96px；「单价（元）」label 不再折行；`el-input-number` 加 `:controls="false"` 去步进按钮、宽 100%、placeholder「整数元/份」；辅助说明改 `.dlg-hint`。「新增交付物」弹窗 `560px` → `.dlg-form`，label-width 90px → 96px | `src/views/assets/detail.vue` |
| 3 | 修改 | 「选择可售明细」弹窗 width `880px` + 局部 `.rs-picker-dialog` 样式 → 统一 `.dlg-wide`（880px / 92vw），删除组件内非 scoped 样式块 | `src/components/RsItemPicker.vue` |
| 4 | 修改 | 下单弹窗 width `560px` → `.dlg-wide`（880px）；内部唯一 input-number 为数量字段（非金额类）保留右侧步进，合同金额为 el-input 无步进按钮，无挤压折行 | `src/components/SalesOrderDialog.vue` |
| 5 | 修改 | 出库登记弹窗 width `720px` → `.dlg-form`（640px）；「销售金额（元）」input-number 加 `:controls="false"` 去步进按钮 | `src/views/sales/outbound/index.vue` |
| 6 | 修改 | 三处弹窗统一套 `.dlg-form`（640px）+ label-width 96px：生态人员 `560px`（label 90px）、交付物模板 `560px`（label 100px）、账号 `520px`（label 90px） | `src/views/settings/base.vue`、`src/views/settings/deliverables.vue`、`src/views/settings/users.vue` |

### 兼容性说明

- 仅 UI（结构/样式/属性）改动，业务逻辑与提交数据零改动；
- `views/assets/list.vue`、`views/assets/create.vue` 中的 el-dialog 均为 fullscreen 产品清单预览，非表单弹窗，不在本次范围内，未改动；
- el-popconfirm / ElMessageBox / el-drawer 按约定不动；detail.vue「交付物详情」为只读详情弹窗（560px）保留原尺寸。

### 验证

- `npx vue-tsc --noEmit` 0 error；`grep "10000|万元" src/` 0 命中；
- dev :5173 目测：新增明细弹窗 640px 放大、单价 label 不折行、无步进按钮；明细选择/下单/出库登记/settings 各弹窗打开确认无挤压折行错位；未执行 build/deploy（按约束禁止）。
## 2026-10-16 ｜ 容器资产（遥感数据）列表抽屉五段式重排

**关联任务**：ADR-011 容器资产抽屉五段式重排（用户要求 type='遥感数据' 的资产快览抽屉重排展示结构；其他类型资产抽屉保持现状）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 抽屉新增 `isRemote`（type='遥感数据'）分支：容器资产移除顶部统计卡（`.dr-metrics`）、库存进度条、可重复售卖说明条；其他类型资产均不受影响 | `src/views/assets/list.vue` |
| 2 | 新增 | 容器资产五段式第 1~2 段：产品清单（复用现有 contract-row 预览/下载与 FilePreview 弹层，无值灰色弱提示）+ 关键信息（info 行：主体 / 状态胶囊 / 可重复售卖胶囊 / 入库时间 / 到期时间（长期买断显示「长期」）/ 备注有值才显示） | `src/views/assets/list.vue` |
| 3 | 新增 | 五段式第 3 段可售明细：el-table（省/市「河北省 / 石家庄市」city 空只显示省 · 精度 1.5m 居中 · 月份居中 · 单价 formatMoney 元口径居中 110px · 已售次数派生居中）；已售次数 = db.contracts 中 delivered 合同明细按 itemId 计数；空态 el-empty「暂无可售明细，请在资产详情维护」；表格无竖线、行 hover #F8FBFF | `src/views/assets/list.vue` |
| 4 | 新增 | 五段式第 4~5 段：交付物（复用现有区块）+ 最近动态（db.logs 与 db.flows 该资产条目合并，按时间倒序取前 8 条：时间 + 标题 + 操作人有则显示；自定义细线时间线 `.rs-tl`，非 EP 默认时间线配色） | `src/views/assets/list.vue` |
| 5 | 新增 | 容器资产分区标题 15px/600 + 弱说明（`.sec-title-lg` / `.sec-desc`）；共享分区（产品清单/交付物）仅容器资产应用大标题，普通资产保持 13px 原样；抽屉内既有动作（编辑/销售/查看详情 footer、加购/登记销售入口）保留且位置不变 | `src/views/assets/list.vue` |

### 兼容性说明

- 仅 type='遥感数据' 抽屉结构变化；普通资产抽屉（统计卡/进度条/说明条/原关键信息/原最近动态流水）逐段核对无变化；
- 业务逻辑零改动：加购（RsItemPicker 明细选择）、登记销售、编辑跳转均走原有函数。

### 验证

- `npx vue-tsc --noEmit` 0 error；`grep -E "10000|万元" src/` 0 命中；
- dev :5173 走查：「遥感数据-2026」（CH-SAT-029）抽屉五段结构完整（2 份明细：河北省/石家庄市 1.5m 2026-09 ¥330,000.00、甘肃省 1m 2026-10 ¥280,000.00，已售次数 0；最近动态 8 条合并日志；到期时间显示「长期」）；「德数交遥感数据」（CH-SAT-012 卫星数据）抽屉保持原结构（统计卡/说明条/交付物 4 项/流水动态）；未执行 build/deploy（按约束禁止）。

## 2026-10-16 ｜ 修复：文件预览 URL 携带 token + inline 参数（配套后端 /files 鉴权）

**关联任务**：后端 `GET /api/files/{filename}` 补双通道鉴权（Bearer 头或 `?token=`）并新增 `inline` 参数；前端文件 URL 统一走查询参数通道，PDF/图片改内联预览。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `fileUrl(filename, inline = false)`：拼 `?token=<jwt>`（token 读取与 axios 拦截器同源，复用 `auth.getToken`）；`inline=true` 时追加 `&inline=true`（内联预览），缺省为下载语义 | `src/api/index.ts` |
| 2 | 修复 | `FilePreview`：img/iframe/docx fetch 用 `fileUrl(filename, true)`（inline，修复 attachment 头导致 PDF 预览变下载、弹层空白）；顶栏「新窗口打开 / 下载」改用 `downloadUrl`（非 inline，保持下载语义） | `src/components/FilePreview.vue` |

### 兼容性说明

- `list.vue` 合同下载 `<a :href="fileUrl(contractFile)" download>` 未改动：`fileUrl` 缺省非 inline（attachment 下载语义不变），且自动带上 token（端点已需鉴权，否则下载会 401）；
- 已自查 `fileUrl` 全部调用处（FilePreview、list.vue 下载链接），无其他遗漏。

### 验证

- `npx vue-tsc --noEmit` 0 error；
- dev :5173 走查：「遥感数据-2026」抽屉点「预览」→ 弹层内 PDF 内联显示（iframe src 含 `?token=...&inline=true`），「下载」仍触发下载；「智元机器人-G1」（docx 清单）预览 mammoth 解析正常；未执行 build/deploy（按约束禁止）。
