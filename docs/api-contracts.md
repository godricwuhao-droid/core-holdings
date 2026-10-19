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
