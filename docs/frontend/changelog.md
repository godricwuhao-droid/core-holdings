# 前端变更日志

> 记录 core-holdings 前端（Vue3 + TS + Element Plus + Vite）的页面/组件/接口封装变更。

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
