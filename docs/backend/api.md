# 后端 API 接口文档

> base path：`/api`｜服务：FastAPI + SQLAlchemy + SQLite｜字段与 `frontend/src/types.ts` 对齐（camelCase）

---

## 认证与权限（2026-10-15 新增，⚠️ Breaking）

### 认证方式

- **JWT Bearer（HS256，7 天有效期）**：登录后所有请求携带请求头
  `Authorization: Bearer <token>`。
- 匿名可访问（白名单，仅 3 个）：`POST /api/auth/login`、`GET /api/health`、`GET /api/files/{filename}`（合同文件预览）。
- 其余所有 `/api/*` 端点均需认证。

### 401 / 403 语义

| 状态码 | 响应体 | 触发条件 |
|--------|--------|----------|
| 401 | `{"detail":"未登录或登录已过期"}` | 未带 token / token 无效或过期 / 账号不存在或已禁用（禁用账号的旧 token 立即失效） |
| 401 | `{"detail":"用户名或密码错误"}` | 登录时凭据错误 |
| 401 | `{"detail":"账号已被禁用"}` | 登录时账号 `enabled=false` |
| 403 | `{"detail":"无权限执行此操作"}` | 已登录但角色不足 |

### 权限矩阵（固定三角色，无动态权限表）

| 能力 | admin | editor | viewer |
|------|:-----:|:------:|:------:|
| 读（所有 GET / 查询类） | ✅ | ✅ | ✅ |
| 业务写（资产 CRUD、销售项目、出库、购物车、下单、基础资料、交付物、上传） | ✅ | ✅ | ❌ |
| 账号管理 `/api/users/*` | ✅ | ❌ | ❌ |
| 审计查询 `GET /api/audit-logs` | ✅ | ❌ | ❌ |

### 新接口定义

#### POST /api/auth/login

请求：`POST /api/auth/login`，body `{"username":"admin","password":"123456"}`
响应（200）：
```json
{"token":"eyJhbGciOiJIUzI1NiIs...","user":{"id":1,"username":"admin","name":"系统管理员","role":"admin","enabled":true}}
```
错误：401 `{"detail":"用户名或密码错误"}`；禁用账号 401 `{"detail":"账号已被禁用"}`。
关键字段：`token`（后续请求的 Bearer 凭证，7 天有效）、`user`（不含密码）。

#### GET /api/auth/me

请求：`GET /api/auth/me`（需认证）
响应（200）：
```json
{"id":1,"username":"admin","name":"系统管理员","role":"admin","enabled":true}
```

#### GET /api/users（仅 admin）

请求：`GET /api/users`
响应（200）：`UserOut[]`（不含 passwordHash）：
```json
[{"id":1,"username":"admin","name":"系统管理员","role":"admin","enabled":true}]
```

#### POST /api/users（仅 admin）

请求：`POST /api/users`，body `{"username":"viewer1","password":"v123456","name":"只读员","role":"viewer"}`
响应（200）：user 对象（同上）。
错误：400 `{"detail":"用户名已存在"}`；role 非法 400（仅支持 admin/editor/viewer）。

#### PUT /api/users/{id}（仅 admin）

请求：`PUT /api/users/2`，body 字段均可选：`{"name"?,"role"?,"enabled"?,"password"?}`
响应（200）：更新后的 user 对象。
错误：400 `{"detail":"不能修改自己的角色或启用状态"}`（改自己的 role/enabled）；404 用户不存在。
注意：改自己的 `password` 允许（改密通道）。

#### DELETE /api/users/{id}（仅 admin）

请求：`DELETE /api/users/2`
响应（200）：`{"ok":true}`
错误：400 `{"detail":"不能删除自己的账号"}`；404 用户不存在。

#### GET /api/audit-logs（仅 admin）

请求：`GET /api/audit-logs?actionType=sale&username=admin&page=1&pageSize=20`
- query：`actionType`（sale/outbound/asset_change/setting/user_mgmt/auth/other）、`username` 可选过滤；`page` 默认 1；`pageSize` 默认 20、最大 100。
- 按时间倒序（自增 id 倒序，等价且更精确）。

响应（200）：
```json
{"total":2,"items":[{"id":10,"userId":1,"username":"admin","actionType":"sale","action":"变更项目状态","target":"project","targetName":"审计验证项目","detail":"status=delivered","time":"2026-10-15 01:15"}]}
```
关键字段：`total`（int）、`items[].actionType`（分类）、`items[].action`（中文动作，如「新建销售项目」）、`items[].username`（操作者快照，账号被删后仍可追溯）、`items[].detail`（可空）。

---

## 接口清单（当前）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（匿名） |
| **POST** | **`/api/auth/login`** | **登录（匿名，新增）** |
| **GET** | **`/api/auth/me`** | **当前登录用户（新增）** |
| **GET/POST** | **`/api/users`** | **用户列表 / 新增用户（仅 admin，新增）** |
| **PUT/DELETE** | **`/api/users/{id}`** | **编辑 / 删除用户（仅 admin，新增）** |
| **GET** | **`/api/audit-logs`** | **审计日志查询（仅 admin，新增）** |
| GET | `/api/bootstrap` | 全量初始化数据（需认证） |
| POST | `/api/assets` | 新增资产 |
| PUT | `/api/assets/{asset_id}` | 编辑资产 |
| DELETE | `/api/assets/{asset_id}` | 删除资产（有引用时 400） |
| POST | `/api/projects` | 新增项目（强制 active） |
| PUT | `/api/projects/{project_id}` | 编辑项目（仅 active） |
| PATCH | `/api/projects/{project_id}/status` | 项目状态流转 |
| **DELETE** | **`/api/projects/{project_id}`** | **删除项目（新增）** |
| POST | `/api/outbounds` | 出库登记 |
| POST | `/api/outbounds/{outbound_id}/revert` | 撤销出库 |
| POST | `/api/cart` / `POST /api/cart/batch` | 加购 / 批量加购 |
| PUT | `/api/cart/{cart_id}` | 修改购物车数量 |
| DELETE | `/api/cart/{cart_id}` / `DELETE /api/cart` | 删除购物车项 / 清空 |
| POST | `/api/cart/checkout` | 购物车下单（进行中 + 锁定，不自动交付） |
| POST | `/api/sales/order` | 资产直接下单（进行中 + 锁定，不自动交付） |
| POST | `/api/bases/{kind}` 等 | 基础资料（suppliers/customers/reps） |
| POST | `/api/deliverable-templates` 等 | 交付物模板 |
| POST | `/api/assets/{asset_id}/deliverables` 等 | 资产交付物 |
| POST | `/api/upload` / `GET /api/files/{filename}` / `DELETE /api/upload/{filename}` | 文件上传/访问/删除 |

---

### POST /api/sales/order

用途：资产直接下单（单/多资产，主体由资产带出）。**语义（2026-10-15 起）**：只生成 **active（进行中）** 销售项目并锁定库存（`lockedQty`），**不再自动交付**——扣库存 + 生成出库（`shippedQty` / `CK-*`）由人工 `PATCH /projects/{id}/status` 置 `delivered` 触发。

请求：`POST /api/sales/order`，body：`{"projectName","customer","rep","contractAmount","expectedSignDate","remark","deliveryReq","items":[{"assetId","qty"}]}`
响应（200）：
```json
{"id":1,"code":"SP-001","name":"验收项目1","customer":"客户X","subject":"主体A","status":"active","expectedAmount":1.0,"items":[{"assetId":29,"qty":1,"price":1.0,"amount":1.0,"status":"locked"}]}
```
关键字段：data.status（恒为 `active`）、data.code（SP-xxx，前端跳转用）、items[].status=`locked`、items[].locked（2026-10-15 起新增：下单时刻该资产是否真实加锁，非 repeatSale 为 `true`；repeatSale 资产下单不加锁为 `false`，`GET /api/bootstrap` 的 projects[].items 同样返回该字段）
错误：400 主体不一致 / 可售不足（`「xxx」可售库存仅 N台，无法下单 M台`）；404 资产不存在

### POST /api/cart/checkout

用途：购物车结算下单。**语义（2026-10-15 起）**：与 `/sales/order` 相同——生成 **active（进行中）** 项目并锁定库存，**不自动交付**；结算后清空购物车（同一事务，任一步失败整体回滚）。交付需人工置 `delivered`。

请求：`POST /api/cart/checkout`，body：`{"projectName","customer","rep","contractAmount","expectedSignDate","remark","deliveryReq"}`
响应（200）：
```json
{"id":2,"code":"SP-002","name":"验收结算项目","customer":"客户Y","status":"active","expectedAmount":1.0,"items":[{"assetId":29,"qty":1,"status":"locked"}]}
```
关键字段：data.status（恒为 `active`）、data.code；结算成功后购物车为空
错误：400 购物车为空 / 购物车资产已删除

---

### DELETE /api/projects/{project_id}

用途：删除项目。语义 = **先回滚**（释放未出库的锁定；撤销该项目名下所有 `status='done'` 的出库并回退对应 `shippedQty`/`soldAmount`/`soldCount`）→ **再硬删** 项目及其 items → 写 OpLog。

请求：`DELETE /api/projects/8`

响应（200）：
```json
{"ok":true}
```
不存在（404）：
```json
{"detail":"项目不存在"}
```

关键字段：无（仅 `ok`）。回滚副作用：相关出库单 `status` 置 `reverted`，资产 `shippedQty`/`soldAmount`/`soldCount` 回退。
实测（`DELETE /api/projects/8`）：项目及明细消失，出库单 `CK-0006/CK-0007` 变 `reverted`，`asset1` shippedQty 4→3、soldAmount 1202.68→902.01，日志 `target=project action=删除`。

---

### POST /api/projects

请求体（**`status` 字段已移除**，后端强制 `active`；前端多传的 `status` 会被忽略不报错）：
```
POST /api/projects
{
  "name":"...","customer":"...","industry":"...","rep":"...","subject":"...",
  "expectedAmount":100,"quoteAmount":0,"contractAmount":0,"paidAmount":0,
  "expectedSignDate":"2026-10-14","lastFollowDate":"2026-10-14","remark":"",
  "items":[{"assetId":1,"qty":1,"price":300.67,"amount":99999,"deliveryReq":""}]
}
```
响应（200，`ProjectOut`，节选）：
```json
{"id":8,"code":"SP-008","status":"active",
 "items":[{"id":11,"assetId":1,"qty":1,"price":300.67,"amount":300.67,"status":"locked"}]}
```
关键字段：`status` 恒为 `active`；`items[].amount` 由后端重算 `round(price*qty,4)`（请求中的 `amount` 被忽略）。
- 库存不足（**按 assetId 聚合本单需求量后**校验，同一资产多条明细合计比较）→ 400：
```json
{"detail":"库存不足：数采软件及设备接入 可售 1套，本单需 2"}
```

---

### PUT /api/projects/{project_id}

请求体同 `POST /projects`。**忽略传入 status**；仅当项目当前为 `active` 可编辑。
- 非 active（delivered/terminated）→ 400：
```json
{"detail":"已完成/已终止项目不可编辑"}
```
- 库存不足（**按 assetId 聚合本单需求量后**校验）→ 400：
```json
{"detail":"库存不足：数采软件及设备接入 可售 1套，本单需 5"}
```
- 校验规则：先按 `assetId` 汇总本项目内全部明细的 `qty` 合计，再与该资产可售（`quantity-lockedQty-shippedQty`）比较；`{m}` 为该资产**合计**需求量。`update_project` 在释放旧锁定之后按新明细聚合（不把本单旧占用计入）。`repeatSale` 资产跳过上限校验。

---

### PATCH /api/projects/{project_id}/status

请求：`{"status":"delivered","reason":"..."}` → 200 `{"ok":true}`

---

### POST /api/assets

请求体校验（Pydantic v2，`Field(ge=0)`）：`quantity`、`salePrice` 必须 ≥ 0。
`quantity=-5` → 422：
```json
{"detail":[{"type":"greater_than_equal","loc":["body","quantity"],
  "msg":"Input should be greater than or equal to 0","input":-5,"ctx":{"ge":0}}]}
```

---

### DELETE /api/assets/{asset_id}

若资产被**任何非 terminated 项目的明细**引用，或存在 **`status='done'` 的出库**引用 → 400：
```json
{"detail":"该资产仍被销售项目或出库记录引用，请先终止相关项目/撤销出库后再删除"}
```
通过校验时：清理引用该资产的购物车项 → 级联删除交付物 + 流水 → 删除资产 → 200 `{"ok":true}`。

---

## 错误码表

| HTTP | 场景 | 响应体 |
|------|------|--------|
| 200 | 成功（写操作） | `{"ok":true}` |
| 400 | 业务校验失败（库存不足 / 项目不可编辑 / 资产被引用 / 购物车主体不一致等） | `{"detail":"<中文说明>"}` |
| 404 | 资源不存在（项目/资产/购物车项） | `{"detail":"<中文说明>"}` |
| 422 | 请求体校验失败（负数量/负金额等） | `{"detail":[{...pydantic...}]}` |

---

## 变更摘要（2026-10-14）

- **新增** `DELETE /api/projects/{project_id}` → 200 `{"ok":true}`；不存在 404。
- **移除 ⚠️** `PATCH /api/assets/{asset_id}/status`（与资产 2 态自动判定冲突；前端从不调用）。
- **修改 ⚠️** `POST /api/projects`：请求体移除 `status` 字段，后端强制 `active`。
- **修改 ⚠️** `PUT /api/projects/{project_id}`：忽略 `status`；仅 `active` 可编辑。
- **修改 ⚠️** `OpLog`/`LogOut`：新增可选字段 `assetId`（`target='asset'` 时非空）。
- **修复** `POST /api/projects` 与 `PUT /api/projects/{project_id}`：库存校验改为**按 assetId 聚合本单需求量**后再比较可售（同一 assetId 多条明细合计超量才 400）；错误消息格式不变，`本单需 {m}` 为合计需求量。
- **修复** `POST /api/assets/{asset_id}/deliverables`：`GET /api/bootstrap` 中产生的 `target='asset' action='新增交付物'` 日志现携带 `assetId`（此前为空，前端按 assetId 过滤会漏显）。
