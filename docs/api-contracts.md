# API 接口契约（跨前后端约定）

> 本文件只记录**前后端必须对齐**的契约变更。完整字段定义以 `docs/backend/api.md` 为准。

## FIX-20261020 批次（分支 fix/business-logic-bugs-20261020）

### 1. 权限与错误响应（ADR-014）
- 前端移除 viewer 写请求预拦截，所有写请求直达后端。
- 后端所有写接口必须有守卫（`require_order` / `require_editor`）；viewer 越权时返回 **403**，`detail` 为可读中文提示（如"只读账号不可执行该操作"）。
- 前端 axios 响应拦截器对 403 统一 toast `err.detail`，**不再**出现前端本地 "只读账号…" 文案（文案来源统一为后端）。

### 2. POST /outbounds（补录交付，ADR-015）
- 请求体：**移除 `operator` 字段**（后端一直不采信，前端同步删掉该字段与输入框）。其余字段不变。
- 新增 400 场景：
  | 场景 | detail |
  |---|---|
  | `qty <= 0` | 交付数量必须大于 0 |
  | 项目状态为 pending 或 terminated | 该项目当前状态不可登记交付 |
  | `assetId` 不在该项目明细中 | 该产品不属于所选项目 |
  | `asset.type == '遥感数据'` 父产品 | 遥感容器不可直接交付，请交付其数据明细 |
- 库存口径：手动交付仅 `shippedQty += qty`，不再触碰 `lockedQty`。

### 3. 合同交付经办人（问题 5）
- `PATCH /contracts/{id}/status`（交付）与撤销交付：接口不变，Outbound 记录的 `operator` 统一取**触发请求的登录账号**（不再取 `project.rep`）。
- 前端交付记录页"经办人"列无需改动（展示后端返回值）。

### 4. Outbound 新增 projectItemId（问题 7）
- 响应体 `Outbound` 新增字段 `projectItemId: number | null`（合同交付时指向 `ProjectItem.id`；手动补录为 null）。
- 前端无需处理（当前界面不展示该字段），仅类型定义同步。

### 5. GET /bootstrap 与 GET /users/options/all（问题 6）
- viewer 请求 `/bootstrap`：`outbounds` 仅返回其可见项目相关记录（`projectId ∈ 可见项目` 或其 `contractId ∈ 可见合同`）；`flows` / `logs` 仅返回引用可见项目/产品/合同的记录（后端按引用关系过滤，过滤后无关联则不返回）。
- `/users/options/all`：viewer 仅返回本人 + 其可见项目中出现过的 `rep/creator/owner` 账号；admin/editor 返回全部启用账号（现状）。

### 6. 建单/加购校验（问题 13）
- `POST /projects`（`_create_project_core`）：任一合同 `customer` 为空 → **400** "请为每份销售记录填写客户"。
- `POST /cart`、`/cart/batch`、`POST /sales/order`、`POST /projects`：产品 `type == '遥感数据'` 父产品 → **400** "遥感数据容器不可直接购买，请购买其数据明细"。

### 7. 产品编辑与 rep 口径（问题 8 / 10）
- `PUT /assets/{id}`：`type` 变更时后端自动重算 `pricingMode`（卫星Token→amount，其余→unit），前端无需传 `pricingMode`。
- `rep` 字段统一存 **username**：`POST /sales/order`、`POST /projects` 的 `rep` 若传姓名，后端按用户表归一为 username（查不到则原样存）。前端两处入口统一改为传 username。
- Token 计价口径（ADR-017）：派生单价 = `amount / qty`（元/份），前后端一致，无 1e4 换算；展示文案统一为"元/{unit}"，删除所有"元/万Token"特判。

### 8. 合同金额只读（问题 12d）
- 建单页 `contractAmount` 改为**只读**（自动 = Σ 明细金额），前端不再发送手改值；后端 `review_project` 保持按 Σ 明细重算。

---

## CLEANUP-20261020 批次：移除「生态人员基础资料」（settings/reps）

> 生态人员已由 users 表 + viewer 角色承载，`base_records`（kind='reps'）为无人消费的遗留数据，整体移除。前后端同批上线。

1. `GET /bootstrap` 响应**移除 `reps` 字段**；前端 `db.reps` 镜像与 `BaseKind` 中的 `'reps'` 同步删除。
2. `POST/PUT/DELETE /bases/{kind}` 不再接受 `kind='reps'`（后端对 reps 返回 404 或 400 均可，取 400「该基础资料类型已下线」）；`suppliers` / `customers` 行为不变（暂保留）。
3. 前端删除：`views/settings/base.vue`、路由 `/settings/reps`、菜单项、「基础设置」菜单若因此变空则整个子菜单移除。

---

## PRICING-20261020 批次：价格体系（区间/折扣）+ 时间节点 + 状态机 + 服务期限

> 依据 ADR-018 / ADR-019 / ADR-020。前后端同批上线。

### 1. /bootstrap 新增字段（均为可空）
- `assets`：`priceMin` / `priceMax`（number | null，元/份）
- `cartItems`：`serviceStart` / `serviceEnd`（string 'YYYY-MM-DD' | null）
- `projectItems`：`origPrice` / `origAmount`（number | null，原价快照）、`serviceStart` / `serviceEnd`
- `contracts`：`signedDate`（'YYYY-MM-DD' | null）、`scheduledDeliveryDate`（'YYYY-MM-DD' | null）
- `contracts.status` / 项目 status 新增值 `delivering`（中文「交付中」）

### 2. 产品参考价（POST/PUT /assets）
- 入参新增 `priceMin` / `priceMax`（number ≥ 0 | null）；后端校验：只填其一允许（视为单边边界），两者都有时 min ≤ max 否则 400。

### 3. 购物车金额与区间校验（PUT /cart/{id}、POST /cart、/cart/batch、/cart/checkout）
- unit 模式行 `amount` 放开（整数元，≥ 0 可空）；viewer 与商务同口径可输。
- 后端校验（行更新时 + checkout 时）：`amount` 非空且产品区间已设时，`amount / qty`（保留 6 位小数）须 ∈ [priceMin, priceMax]，否则 **400「折扣单价超出该产品参考区间（{min}~{max} 元/{unit}）」**（单边区间按单边校验）。
- 不输 amount = 原价成交（unit 行 salePrice×qty；amount 行现状兜底逻辑不变）。

### 4. 下单落库（checkout / 手动建单 POST /projects）
- `ProjectItem` 写入 `origPrice` / `origAmount`（下单时快照，见 ADR-018 §2）；`serviceStart` / `serviceEnd` 透传（YYYY-MM-DD，start ≤ end 否则 400）。

### 5. 合同字段与状态（新端点）
- **PATCH /contracts/{id}**（require_order + 归属守卫）：body `{ signedDate?: 'YYYY-MM-DD', scheduledDeliveryDate?: 'YYYY-MM-DD' | null }`
  - `signedDate`：editor/admin（接手人/admin，与审核同守卫口径）；仅合同 active 可录；录入后合同自动 active→delivering；录后可改、**不可传 null 清空**（400）。
  - `scheduledDeliveryDate`：**仅 admin**；仅合同 delivering 可录/改；可传 null 清空。
- `PATCH /contracts/{id}/status`：`active→delivered` 新守卫——合同非 delivering（signedDate 空）时 400「合同尚未录入签订时间，不可交付」；`delivering→delivered` 为交付路径（扣量/流水/Outbound 在此发生）；`delivered→terminated` 撤销后合同回 **delivering**（signedDate 仍在）。

### 6. 审核（POST /projects/{id}/review）
- confirm 行级入参新增 `serviceStart` / `serviceEnd`（可改服务期限）。
- **删除**终审改价回写 `assets.salePrice` 的逻辑（ADR-018 §4）；改价只写 ProjectItem。

### 7. 下单入口（ADR-020）
- 前端删除「登记销售」入口与 SalesOrderDialog 非购物车模式；`POST /sales/order` 后端保留、文档标记 deprecated。

---

## RSITEM-RANGE-20261020 批次：遥感售卖明细参考区间（ADR-021）

> 取代 ADR-018 §5「遥感行不限制」口径。前后端同批上线。

1. `/bootstrap` 的 `rsItems`：每行新增 `priceMin` / `priceMax`（number | null，元/份）。
2. `POST /assets/{id}/rs-items`、`PUT /assets/{id}/rs-items/{item_id}` 入参新增 `priceMin` / `priceMax`（number ≥ 0 | null）；两者都有时 min ≤ max 否则 400「参考区间下限不能大于上限」。
3. 折扣区间校验口径变更：生态下单链路（购物车行更新 / checkout / sales/order）中**遥感明细行（itemId 非空）金额校验改用该 rs_item 自身区间**（不再取父产品容器区间）；普通产品行仍用 assets 区间；未设区间 = 不限制。400 文案口径同 PRICING 批次。
4. 原价快照不变：遥感行 origPrice/origAmount = 明细 price 快照。

---

## PAGE-20261021 批次：产品相关列表服务端分页（单页 10 条）

> 背景：抽屉/详情页的可售明细、数量流水、操作记录此前随 bootstrap 全量下发前端渲染（遥感明细 96 条，日志随时间累积），改服务端分页。**bootstrap 快照字段（rsItems/flows/logs）保留不动**——RsItemPicker 树、项目页名称查找等 5 处消费方仍依赖全量镜像。

### 统一口径（对齐 GET /audit-logs 先例）
- 参数：`page: int = Query(1, ge=1)`、`pageSize: int = Query(10, ge=1, le=100)`（**默认 10**）
- 返回：`{ "total": number, "items": [...] }`
- 守卫：`get_current_user`（读接口三角色放行，与 bootstrap 读同口径；asset 级 flows/logs 对 viewer 全量放行是现状口径，保持一致）

### 新端点
1. **GET /assets/{asset_id}/rs-items**
   - items = `RsItemOut` + 新增派生字段 `soldCount`（number，后端按 delivered 合同 project_items 按 itemId 计数，替代前端遍历 contracts 派生）。
   - 排序：`id ASC`（录入顺序稳定）。
   - 产品不存在 404。
2. **GET /assets/{asset_id}/flows**
   - items = `FlowOut`（仅该 assetId 的产品级流水）。排序 `id DESC`。
3. **GET /assets/{asset_id}/logs**
   - items = `LogOut`（`target='asset' && assetId` 的操作日志）。排序 `id DESC`。
   - **抽屉「最近动态」沿用前端合并逻辑**（flows+logs 合并倒序）改成分页取两个接口各一页后前端合并排序取 10 条——不新增合并端点（trade-off：抽屉动态条数多时可能有 1-2 条口径误差，可接受；避免维护第三个合并接口）。

### 前端
4. 抽屉（assets/list.vue）：可售明细表 → 分页加载（el-pagination，`layout="total, prev, pager, next"`，照 settings/users.vue 模式）；最近动态保持"只看前 10 条"语义（分页参数 10）。
5. 产品详情（assets/detail.vue）：「可售明细」tab（遥感）分页；「数量流水」「操作记录」tab 分页（替换全量时间线渲染）。
6. 表格内原「已售次数」前端派生列改用后端 `soldCount`。

---

## DISCOUNT-20261021 批次：购物车折扣率输入（ADR-023）

> 选填快捷入口；销售金额仍是权威必填值（ADR-022 不变）。前后端同批上线。

1. `/bootstrap` 新增字段（均可空）：`cartItems[].discountRate`、`projectItems[].discountRate`（number 0-1 小数，0.9=九折）。
2. 购物车写接口（POST /cart、/cart/batch、PUT/PATCH /cart/{id}）接受 `discountRate`（number，0 < rate ≤ 1，后端存小数；**前端传小数**，如 9 折传 0.9）；null 允许（清空）。
3. **一致性规则（前端执行，后端不重算金额）**：折扣率变更 → 前端自动回填 `amount = round(salePrice × qty × rate)`（整数元）后一次性提交 amount+discountRate；手动改 amount → 前端提交时 `discountRate: null`。后端只存不算（金额权威原则，区间校验仍对 amount 生效）。
4. **checkout**：`project_items.discountRate` 快照 = 购物车行值（只写不改）；其余落库逻辑不变。
5. 审核（review）接口不改：discountRate 只读展示（快照），终审改价仍只写 price/amount。
6. 前端：购物车金额列内联小型「折扣」输入（折，0-10 一位小数）+ 提示行展示 `原价总额 ¥X · 折后单价 ¥Z`（11px 辅助色，超长省略+tooltip）；审核页明细行加「折扣」列（"九折"，null 不显示）。

---

## CART-PERF-20261021 批次：购物车行更新性能（修复输入卡顿）

> 背景：行级更新（qty/amount/discountRate/service）每次 PUT 后前端全量重拉 bootstrap（含 97 条 rsItems/122 条 logs），整表重建 → 输入卡顿。改「PUT 返回更新行 → 前端本地打补丁」。

1. **PUT/PATCH /cart/{id} 响应变更**：由 `{"ok": true}` 改为**返回更新后的完整 `CartItemOut`**（含最新 customer/qty/amount/serviceStart/serviceEnd/discountRate）。
2. 前端行级写函数（setCartQty/setCartAmount/setCartService/客户更新）：成功后**用响应体本地替换 db.cartItems 对应行**（仅该行对象变更，不重拉 bootstrap）；**`afterWrite()` 全量刷新仅保留给结构性操作**（加购/批量加购/删行/清空/结算）。
3. 购物车页输入交互：金额输入改**本地草稿**（敲字不碰共享镜像，失焦提交——与折扣输入同模式）；折扣**输入过程实时预览**（草稿合法 0<r≤10 即显示摘要与预计金额，不等失焦）；摘要文案压缩为 `原价 ¥{origPrice×qty} · 折后 ¥{rate单价}`（折后单价保留 2 位，11px 单行，超长省略 + tooltip 全文）。

---

## REQUIRED-20261024 批次：购物车结算必填口径（ADR-022）

> 取代 ADR-018 §3「留空按原价成交」兜底。前后端同批上线。

1. `POST /cart/checkout` 逐行必填校验（缺项 400，文案含行标识：产品名/明细名）：
   - 客户非空（现状保留）；
   - `amount` > 0 整数元（**所有行类型**，含遥感行）——**删除 amount 为空回退 salePrice×qty 的兜底分支**；
   - 普通产品行：`serviceStart` / `serviceEnd` 均非空且 start ≤ end（现状格式校验保留）；
   - **遥感明细行服务期限仍豁免**（ADR-020）。
2. 行更新（PUT/PATCH /cart/{id}）允许暂存缺项（加购后可分批补），仅结算强制齐全。
3. 前端：购物车金额 placeholder 改「必填，整数元」；服务期限 placeholder「开始日期/结束日期」且缺项标红；结算按钮前置校验同口径（缺项行标红 + 提示，不弹结算窗）。
4. 区间校验（ADR-018/021）不受影响：必填金额仍须落在参考区间内。
