# 前端变更日志

> 记录 core-holdings 前端（Vue3 + TS + Element Plus + Vite）的页面/组件/接口封装变更。

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
