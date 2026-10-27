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
- 后端校验（行更新时 + checkout 时）：`amount` 非空且产品区间已设时，`amount / qty`（保留 6 位小数）须 ∈ [priceMin, priceMax]，否则 **400「单价超出该产品参考区间（{min}~{max} 元/{unit}）」**（单边区间按单边校验）。
  - 文案沿革：本行原写「折扣**单价**超出…」，已于 `NO-DISCOUNT-20261022` 文案收口去掉「折扣」二字（折扣功能随 ADR-039 下线，见本文件末批）。**校验口径、区间数值格式、400 状态码从未变更**，仅错误字符串变化；前端若对该 `detail` 做字符串匹配需同步。
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

---

## OPTIONAL-SERVICEPERIOD-20261026 批次：服务期限改选填（ADR-047）

> 部分取代 ADR-022 §1 第三条（服务期限必填）；客户 / 销售金额必填口径**不变**。无接口签名变更、无 DB 迁移（`cart_items` / `project_items` 的 `serviceStart/serviceEnd` 本就 `nullable=True`）。前后端同批上线。

1. `POST /cart/checkout` 服务期限校验口径（三态）：
   - **两端都空** → 合法，`serviceStart` / `serviceEnd` 落库为 `null`；
   - **只填一端** → 仍 400，缺项文案 `{行标识}：服务期限（开始/结束日期需成对填写，或都留空）`（原 `（开始/结束日期均必填）` 文案作废）；
   - **两端都填** → 保持 ADR-020 校验（`YYYY-MM-DD` + start ≤ end，非法时 400 `服务开始日期不能晚于结束日期`）。
2. 遥感明细行（`itemId` 非空）继续豁免服务期限，行为不变。
3. 行更新（`POST/PUT/PATCH /cart`）允许任意暂存状态，行为不变。
4. 前端 `views/cart/index.vue`：`serviceMissing()` 改三态判定（都空 → 不标红；半填 / start>end → 两端标红）；`openOrder()` 前置校验复用同一函数；列头去必填红星、tooltip 改「选填（开始/结束日期需成对填写…）」；两个 date-picker placeholder 加「（选填）」；顶部提示条文案同步。

---

## CART-PATCH-20261021 批次：购物车行更新改为 PATCH 语义（修复金额被误清空）

> 背景（2026-10-21 用户反馈）：购物车先填「销售金额（元）」再选服务期限 → 金额被清空。根因：`PUT/PATCH /cart/{id}` 对未携带的 `amount` 执行清空，且 `discountRate` 每次无条件覆盖。

1. **语义约定**（前后端共同遵守）：`PUT/PATCH /cart/{id}` 的 `amount` / `serviceStart` / `serviceEnd` / `discountRate` 一律 **未传 = 保持原值不改；显式传 `null` = 清空**。`qty` 仍为 PUT 必传。
2. **例外（保留旧行为）**：数量**真的变化**且未传 `amount`、该行无 `discountRate` 时，后端清空该行手工折扣金额（旧总额对新数量已失真）；有 `discountRate` 的行由前端按 rate 重算并显式提交 `amount`。
3. 后端实现：`services.UNSET` 哨兵（PUT 按 body 键是否存在判断；PATCH 按 Pydantic `model_fields_set` 判断）。
4. 前端无需改动：`setCartService` / `setCartQty` / 客户更新继续只传变更字段即可。
5. 校验与 400 文案不变（必填口径 ADR-022、折扣区间 ADR-018/021）。

---

## WITHDRAW-20261021 批次：生态人员「撤销」待审核订单（ADR-026）

> 背景：生态人员提交的待审核订单没有撤回能力。撤销 = 终止原单 + 明细回填购物车（可改单重提）。按钮名「撤销」。

1. **新端点** `POST /api/projects/{id}/withdraw`，body `{"reason": "必填 1–200 字"}`。
2. **响应 200**：`{ ok: true, restored: number, amountFallback: number, skipped: number, skippedReasons: string[] }`
   - `restored` 回填成功行数；`amountFallback` 因区间/校验降级为原价成交的行数；`skipped` 无法回填行数 + 原因文案。
3. **错误码**：
   | 场景 | HTTP | detail |
   |---|---|---|
   | 项目不存在 | 404 | 销售项目不存在 |
   | 非本人且非 admin | 403 | 只能撤销自己提交的订单 |
   | 状态非 pending | 400 | 仅待审核订单可撤销 |
   | 原因为空 | 400 | 请填写撤销原因 |
   | 原因 > 200 字 | 400 | 撤销原因不能超过 200 字 |
   | 下单账号缺失（存量 creator/rep 均空） | 400 | 下单账号不存在，无法回填购物车 |
4. **副作用（单事务）**：合同 pending→terminated（释放真实锁定 + `cancel_release` 流水 + remark「撤销：原因」）、项目 terminated、解绑 businessOwner、明细按 (customer/assetId/itemId/qty/amount/serviceStart/serviceEnd/discountRate) 回填**下单人**购物车（judge 键合并累加）、OpLog + audit 各 1 条。
5. **契约补漏（同批）**：`ProjectOut` 新增 `creator: string`（bootstrap `projects[]` 同步输出，存量为空串）——前端按钮归属判定与既有 viewer 编辑/终止入口依赖该字段。

---

## REFILL-20261021 批次：「重新提交」收口购物车（ADR-027）

1. **新端点** `POST /api/projects/{id}/refill-cart`（`require_order`，无 body）：
   - 首次：`{ ok: true, alreadyRefilled: false, restored: n, amountFallback: n, skipped: n, skippedReasons: [] }`（明细回填**下单人**购物车，回填不锁量、不写流水）；
   - 幂等：项目已回填过（`projects.cartRefilled = true`）→ `{ ok: true, alreadyRefilled: true, restored: 0, ... }`；
   - 错误：404 销售项目不存在 / 400 仅已终止的项目可重新提交 / 403 生态人员仅可重新提交自己下单的项目 / 400 下单账号不存在，无法回填购物车。
2. **前端动线**：列表行与详情页「重新提交」→ 调本端点 → `refresh()` → 跳 `/cart`；toast 区分「已回填」与「已在购物车」。
3. **已下线**：`/sales/projects/create?copy={id}`（create 页 copy 模式）——页面保留（`/create` 新建、`/:id/edit` 编辑仍用）；后端 `POST /projects/{id}/resubmit` 保留但无入口（deprecated）。
4. `ProjectOut` 新增 `cartRefilled: boolean`（bootstrap 同步）。

---

## EDITLOCK-20261021 批次：生态人员订单提交后禁止编辑（ADR-028）

> 背景：业务要求生态人员提交订单后不可编辑，改单只能「撤销 → 购物车重下」，且撤销记录不得删除。**无新增端点、无 schema 变更**，仅收紧两个既有端点的权限。

1. **`PUT /api/projects/{id}`（`require_order`）**：`role == "viewer"` **一律 403**，不区分状态与归属。
   | 场景 | HTTP | detail |
   |---|---|---|
   | viewer（生态人员）调用 | 403 | 订单已提交，不可编辑；如需修改请「撤销」后重新下单 |
   | 项目不存在 | 404 | 项目不存在 |
   | 商务/管理员既有校验 | 400 | 不变（待审核仅负责人或 admin、已交付/已终止不可编辑、名称非空） |
   - 同批删除 viewer 的 `rep` 字段特判（父权限已收回，特判为死代码）。
2. **`DELETE /api/projects/{id}`（`require_editor`）**：新增留痕护栏。
   | 场景 | HTTP | detail |
   |---|---|---|
   | `status == "terminated" and cartRefilled == true` | 403 | 该订单已撤销（或已回填购物车）并将保留历史记录，不可删除 |
   - 其他终态（被驳回且从未回填）仍可删除；不提供绕过接口。
3. **不变的部分**：`POST /projects/{id}/withdraw`（仅 pending）、`POST /projects/{id}/refill-cart`（幂等）、`PATCH /projects/{id}/status`（viewer 仍可终止自己项目并填原因，撤销≠终止：撤销回购物车、终止不回）。
4. **前端契约消费**：
   - 列表「编辑」列、详情页「编辑」按钮对 viewer 不渲染；
   - `/sales/projects/:id/edit` 路由对 viewer 不放行（`viewerAllowedPath` 只放行 `detail`），直达时提示后回详情页；
   - 详情页 `terminated && cartRefilled` 展示「订单已撤销，历史记录已保留」提示行，原因取自合同 `remark`。

---

## FIX-20261022 批次：业务逻辑与架构审查问题修复（ADR-029 ~ ADR-034）

> 来源：`docs/business-logic-bugs-20261022.md`。**本批含 2 处请求体新增字段（均可选）、1 处端点下线、1 处权限提升**，其余为服务端行为收紧，前端契约形状不变。

### 1. `POST /cart/checkout` 新增可选 `requestId`（ADR-033 幂等）

- 请求体新增 `requestId?: string`（建议 UUID；同一次提交重试沿用，成功后丢弃）。
- 首次请求：行为不变（200 + `ProjectOut` 字段），响应额外含 `idempotent: false`。
- 同一 `(userId, requestId)` 在 24h 内重复请求：**200**，返回首次创建的项目，响应含 `idempotent: true`，**不重复建单/锁量/清购物车**。
- 前端：点击「结算下单」时生成 `requestId`，按钮 loading 期间禁用；失败重试沿用同一 id。

### 2. `POST /sales/order`、`POST /projects/{id}/resubmit` 下线

- 两端点一律返回 **410 Gone**，detail：`该接口已下线，请使用购物车结算`。
- 前端已无封装/入口（`api/index.ts` 已删），无需改动；若有外部脚本直调需改造。

### 3. `POST /projects/{id}/review`（确认）服务期限可显式清空

- `items[].serviceStart` / `items[].serviceEnd` 语义改为：**未传 = 保持原值；显式 `null` = 清空**（与 `PUT /cart/{id}` 的 `UNSET` 哨兵口径一致）。
- 前端审核页「清空日期」可直接生效，无需改调用方式。

### 4. 金额/数量不变量（后端返回 400，前端展示 detail）

| 场景 | detail |
|---|---|
| `contractAmount` 传入且 ≠ Σ 明细 amount | 合同金额与明细合计不一致 |
| 项目级批量交付存在未录签订时间的合同 | 以「以下销售记录不满足交付条件：」开头的**全量清单**（逐条含合同编号 + 原因，一次报全，QA 实测文案以此为准） |
| 终止/撤销交付时产品已删除或明细缺失 | 该产品/明细已不存在，无法回滚交付，请先联系管理员 |
| 并发状态变更冲突（条件更新影响 0 行） | 状态已变更，请刷新后重试 |
| 登录尝试超限 | 登录尝试过于频繁，请稍后再试（HTTP 429） |

- **删除**：`apply_item_lock` 的 `max(0, ...)` 静默夹断、`shippedQty` 的 `min(quantity, ...)` 夹断 → 改为显式校验失败（500 视为不变量被破坏，写审计告警）。

### 5. 文件与日志可见性（ADR-030）

- `GET /api/files/{filename}`：文件未被任何可见产品引用、且 `uploadedBy != 当前用户` 且非 admin → **404**（不返回 403，避免探测）。
- `bootstrap.files`：同上规则过滤（admin 全量）。
- `bootstrap.logs` / `GET /assets/{id}/logs`：`target == "contract"` 按可见合同过滤；无法归属的日志对 viewer 一律不返回。
- `GET /api/users/options`：权限由「任意登录」提升为 **`require_editor`**（viewer 403）。前端商务负责人筛选对 viewer 不渲染。

### 6. 状态派生口径（ADR-032）

- 合同状态集合 ⊆ `{delivered, terminated}` 且含 `delivered` → 项目 `delivered`（已完成，剩余作废）。
- 项目级 `PATCH /projects/{id}/status` 批量语义改为**全量或全不**：任一合同不合规即 400，并列出全部不合规合同编号。

### 7. 上传与安全响应头

- `POST /upload`：`.doc` 从白名单移除（与 ADR-024 前端 `accept` 一致）；改流式写入，超 20MB 立即中断并 400。
- 文件下载响应增加 `X-Content-Type-Options: nosniff`。

---

## ENTITIES-20261022 批次：资产主体可维护（ADR-035）

> 背景：主体清单原硬编码于 `frontend/src/types.ts::ENTITIES`，新增主体须发版。改为后端表 + 设置页维护 + 前端动态清单。

### 1. 新端点

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /api/entities` | 登录即可 | 全量返回，按 `createdAt` 正序（保持存量展示顺序稳定） |
| `POST /api/entities` | require_editor | body `{ name: 必填 2–64 字, short: 必填 1–32 字 }`；`name` 重复 → 400「主体已存在」 |
| `PUT /api/entities/{id}` | require_editor | body `{ name, short }`（同必填）；`name` 与**其他**主体重复 → 400「主体已存在」；**不改名只改简称时无失联风险** |
| `DELETE /api/entities/{id}` | require_editor | 被产品引用 → **400**「该主体下存在 N 个产品，不可删除」；不存在 → 404 |

- 元素形状：`{ id: number, name: string, short: string, createdAt: string, updatedAt: string }`。
- 改名（`name` 变化）时后端在 OpLog/audit 留痕（detail 含 旧名称 → 新名称）；**不回写** `assets.subject`（ADR-035 Decision 5，前端弹窗二次确认提示"存量产品主体仍为旧名称，需逐个产品手动改选"）。

### 2. `GET /bootstrap` 新增顶层字段

- `entities: { id, name, short, createdAt, updatedAt }[]`（全量，**无角色过滤**——主体非敏感商业数据；旧快照缺失时前端回退空数组 + 下拉禁用提示，不报错）。

### 3. 前端消费变更

- `types.ts::ENTITIES` 常量**删除**；`entityShort(name)` 改读 `db.entities`（查不到回退原值）。
- 建产品页「所在主体」下拉、产品列表主体筛选：数据源改 `db.entities`（`label = short（或 name）`，`value = name` 存储口径不变）。
- 新页面 `/settings/entities`（仅 admin/editor；菜单「基础设置」组，与「账号与审计」同组；viewer 不渲染菜单项，路由直达被 `canWrite` 守卫拦回）。

---

## FORMS-20261022 批次：产品登记规则 + 生态人员购物车口径（ADR-036 / ADR-037）

> 请求/响应**字段形状零变化**，本批全部是校验规则与前端展示口径收紧/放宽。

### 1. `POST /assets`（新建登记，ADR-036 §1/§4）

- `inboundDate` 不再是必填入参：**不传/空 → 后端自动取当天** `YYYY-MM-DD`；传值仍走 `_validate_date_str` 校验。
- `type == '遥感数据'`（容器）且 `repeatSale == true` → **400**「遥感数据容器按明细售卖，不支持重复售卖」。
- 其余字段（`perpetual` 等）语义不变，仅前端文案「长期买断」→「产品有效期」。

### 2. `PUT /assets/{id}`（编辑，ADR-036 §4）

- 容器 `repeatSale` 同规则：改为 `true` → 400（同文案）。
- `inboundDate` 传值可改（只读展示是前端约束，后端不锁）。

### 3. `PUT /cart/{id}` 与 `POST /cart/checkout` 区间校验分角色（ADR-037 §3）

- **viewer**：行金额仅校验**下限**——`amount < priceMin` → 400（原文案不变）；`amount > priceMax` **允许**（原 400 取消）。遥感明细行用明细自身区间（ADR-021），同分角色规则。
- **editor/admin**：双向校验不变。
- **viewer 行携带历史 `discountRate`**：忽略（不 400、不参与任何计算，金额权威不变）；editor/admin 行 `discountRate` 行为不变（ADR-023）。
- 校验实现必须**单函数**（下单权威链 `_create_project_core` 与改价入口复用），角色取当前登录用户。

### 4. 前端消费变更

- 菜单「资产主体」→「**公司主体**」（`/settings/entities` 路由路径不变，仅文案/路由 meta 改名）。
- 登记页（`assets/create.vue`，含编辑模式）重构（ADR-036 §5，仅 UI）：
  - 新建：移除「登记时间」输入；「长期买断」改「产品有效期」；「销售单价」填写后自动同步 `priceMin = salePrice`、`priceMax = round(salePrice×1.02, 2)`（手改区间后不再覆盖）；
  - 编辑：「登记时间」只读展示；参考区间不自动同步；
  - 重复售卖：移除「卫星数据自动勾选」；容器显示禁用态开关 + 说明「容器按可售明细售卖，剩余数量 = 未售明细数」；非容器开关可开可关。
- 购物车（`cart/index.vue`）：**viewer 不渲染折扣列/输入**（editor/admin 不变）；viewer 金额超上限不再出现 400。

---

## UI-OPT-20261022 批次：容器可售口径 + 登记页状态块 + 站点标题

### 1. `GET /bootstrap` 的 `assets[]` 新增派生字段 `availableCount`（仅容器非空）

- 字段：`availableCount: int | null`（**加性字段**，非容器恒 `null`）。
- 口径（ADR-011 容器模型）：`明细总数 − 已被"非 terminated 销售记录"占用的明细数`；占用 = `project_items.itemId` 命中且所属 `contracts.status != 'terminated'`（锁定 pending/active/delivering 与已交付 delivered 都算占用）。
- 语义：与普通产品的 `quantity − lockedQty − shippedQty` 对齐，只是容器的"数量"是明细条数。
- 存量示例：`assets#29 遥感数据-2026` → 97 明细、0 占用 → `availableCount = 97`。
- **viewer 视角同样正确**（后端派生，不依赖前端可见的销售记录）——避免重演 BUG-46「前端本地汇总在 viewer 下失真」。

### 2. 前端消费

- `availableQty(asset)`：容器优先读 `asset.availableCount`（缺失时回退旧口径 `quantity−lockedQty−shippedQty`，兼容旧快照）；非容器逻辑不变。
- 产品列表「可售数量」列、列表抽屉「可售 N 份」、状态派生（可售/售罄）三处统一走该函数——容器不应再显示父产品 `quantity=1`。
- 登记/编辑页「状态与备注」卡片：**移除「产品状态」展示块**（自动派生、无输入价值），仅保留备注；卡片标题改「备注」。新建页同样处理。

### 3. 站点标题

- `index.html` `<title>` → **蜂云产品及服务平台**（顶栏与登录页文案已是该值，本次仅统一浏览器标签标题）。

---

## RS-REPEAT-20261022 批次：明细级重复售卖开关（ADR-038）

### 1. 明细入参新增 `repeatSale`（默认 false）

- `POST /api/assets/{id}/rs-items`、`PUT /api/rs-items/{id}` 请求体新增 **`repeatSale?: boolean`（缺省 false）**；此前该字段**不接受**（前端无法设置）。
- 语义：`true` = 该明细可重复售卖（售出不占用可售数，只计次）；`false`（默认）= 单次售卖，售出/锁定即占用。
- `PUT` 仍为**整行覆盖**（province/city/resolution/saleMonth/price/priceMin/priceMax/repeatSale 全量提交），本批不引入 PATCH。

### 2. `bootstrap.assets[].availableCount` 口径修订（覆盖 UI-OPT-20261022 §1）

- 新口径：`明细总数 − 被占用且 repeatSale = false 的明细数`。
- 占用仍指「被非 terminated 销售记录引用」；但 `repeatSale = true` 的明细**不参与扣减**（售出后仍可售）。
- 存量示例：`#29` 60 条全部置 `false`、当前 0 占用 → `availableCount = 60`。

### 3. 前端消费

- **可售明细页签**（`assets/detail.vue`）：
  - 「可重复售卖」列由只读 pill 改为 **`el-switch`（小号）**，切换即 `PUT /rs-items/{id}` 提交整行；请求期间该行开关禁用（防连点）；失败回滚开关状态 + `showError`；成功后 `afterWrite()` 同步。
  - 页签顶部说明文案改为「按省/精度/月份维护可售明细，每份明细独立计价（整数元/份）；**默认为单次售卖**（售出即占用），开启「可重复售卖」后只计次不扣量」。
  - 新增/编辑弹窗增加「可重复售卖」开关（默认关，带一行说明）。
- 明细行 `repeatSale` 仍照常返回于 `GET /assets/{id}/rs-items`（`RsItemOut` 不变）。

---

## NO-DISCOUNT-20261022 批次：购物车折扣功能下线（ADR-039，Deprecates ADR-023）

### 1. 入参不再接收 `discountRate`

| 端点 | 变化 |
|---|---|
| `PUT /api/cart/{id}` | `discountRate` **忽略**（传 null/数字均不校验、不落库，不再返回 400「折扣率须为 0 到 1 之间的正数」） |
| `POST /api/cart/checkout` | 同上；新单 `discountRate` 恒为 `null` |
| `POST /api/projects/{id}/review` | 同上（审核改价不再写折扣快照） |

- 存量行的 `discountRate` **保留在库里**（历史快照可查），响应体可继续返回该字段，前端不再展示。

### 2. 前端移除清单

- 购物车：折扣输入、折扣摘要提示行、金额 placeholder 的折扣预览、顶部提示条折扣说明、`discountDrafts` 及 `onDiscountInput/onDiscountChange/discountDraft/discountInvalid/discountSummary/discountPreviewRate` 等全部删除。
- 审核页：删除「折扣」只读列 + `discountRateText`（列宽重排，其余列不压缩）。
- 金额 placeholder 统一「必填，整数元」；金额仍是唯一权威（ADR-022 不变）。

### 3. 文案/提示

- 顶部提示条去掉折扣相关句子，保留「销售金额必填、整数元、参考区间」提示。
- 不新增任何页面、区块或字段。
- **区间校验 400 文案收口**（本批附带，纯字符串）：`折扣单价超出该产品参考区间（{min}~{max} 元/{unit}）` → `单价超出该产品参考区间（{min}~{max} 元/{unit}）`。同批前端产品登记页/详情页「参考区间」说明小字由「下单折扣区间校验用」改为「下单时单价校验用」。**逻辑、区间算法、错误码、响应结构零改动**；前端不得依赖该 `detail` 的文案做分支判断（历史上也未依赖）。
