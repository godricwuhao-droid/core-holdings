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
