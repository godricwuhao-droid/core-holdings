# 后端变更日志

> 记录 core-holdings 后端（FastAPI + SQLAlchemy + SQLite）的接口与行为变更。

---

## 2026-10-15 ｜ 修复 repeatSale 翻转的 2 个业务逻辑 bug（幽灵锁定 + 反向切换超卖/幽灵流水）

**关联任务**：repeatSale 翻转缺陷修复（含契约：`project_items` 新增 `locked` 列 + 幂等迁移）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **BUG1 幽灵锁定**：`update_asset` 检测 `repeatSale` false→true 且 `lockedQty>0` 时清零 `lockedQty` 并写 OpLog（action='清零锁定'，含原锁定数，带 assetId）；lockedQty=0 不打日志，true→false 不做库存动作。WHY：`apply_item_lock` 对 repeatSale 资产直接 return，存量锁定在翻转后交付/终止都无法释放，列表锁定列永久虚高 | `src/services.py` |
| 2 | 修复 | **BUG2 反向切换超卖+幽灵流水**：`project_items` 新增 `locked` 列（Boolean 默认 False，下单时刻是否真实加锁；`main.py` 幂等迁移补列）；建/重建明细落 `locked=(非 repeatSale)`；交付/终止/编辑释放锁定均**仅当 `it.locked`** 才调 `apply_item_lock(...,False)`；交付非 repeatSale 分支 `shippedQty = min(quantity, shippedQty+qty)` 防御超卖。WHY：明细仅 status 标记无法区分"真锁过"与"repeatSale 未锁"，导致 shippedQty 可超 quantity、对从未存在的锁定写 cancel_release 幽灵流水 | `src/models.py`, `src/schemas.py`, `src/services.py`, `main.py` |

### 未改动 / 保持不变的既有行为（回归依据）

- `apply_item_lock` 的 repeatSale 早退逻辑保持不变（最终防线）；金额 4 位、同主体校验、聚合校验、状态机、审计均不动。
- 非 repeatSale 正常链路（锁定→交付→扣减→出库；终止→释放 + cancel_release 流水）与 repeatSale 正常链路（不锁、只计次 soldCount）实测不回归。
- `ProjectItemOut` 出参新增 `locked` 字段（前端可用），其余字段不变。

### 提交后自测（临时库 8012 隔离，curl 实测摘要）

- qty=1 非 repeatSale 下单 1 台（lockedQty=1）→ `PUT repeatSale=true` → `lockedQty=0`，logs 出现「清零锁定 1台」。
- 该项目交付 → 200，`soldCount=1`，flows 无 cancel_release。
- repeatSale 期间下单 3 台（item.locked=false）→ 改回 false → 交付 → `shippedQty=1 ≤ quantity=1`，flows 无任何 release 类记录。
- 正常链路：qty=2 资产两项目（locked=true），交付 → lockedQty 释放、shippedQty=1、出库 1 条；终止 → cancel_release 流水正常存在。
- 存量库删列后重启 → `[migration] project_items.locked 列已补充`，幂等。

---

## 2026-10-15 ｜ 下单/结算不再自动置 delivered（⚠️ Breaking：下单/结算不再自动完成交付，交付需手动置"已完成"）

**关联任务**：状态语义修正 — 销售与交付两动作分离

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 ⚠️ | `_order_core` 删除建项目后自动调用 `_change_project_status_core(status="delivered")` 的逻辑：`POST /sales/order` 与 `POST /cart/checkout` 现只生成 **active（进行中）** 项目并锁定库存（`lockedQty`）；扣库存 + 生成出库（`shippedQty`/`CK-*`）改由人工 `PATCH /projects/{id}/status` 置 `delivered` 触发。WHY：销售与交付分离，便于纠错编辑与审计留痕各自独立 | `src/services.py` |
| 2 | 修改 | 同步更新 `_order_core` / `checkout` / `create_sale_order` docstring 及 `SaleOrderInput` 注释为"进行中 + 锁定，交付由人工触发" | `src/services.py`, `src/schemas.py` |

### 未改动 / 保持不变的既有行为（回归依据）

- `change_project_status`（人工交付入口）、`_terminate_project`、`delete_project`、`_validate_item_stock`、库存/金额规则均未改动。
- 下单同主体校验、可售校验、`_create_project_core`（锁定明细）、返回 project 对象不变；购物车清空仍在建项目之后、同一事务内（H8）。
- 无数据库迁移、无数据变更（纯行为变化）。

### 提交后自测（临时库 8012 隔离，curl 实测摘要）

- 资产 qty=2 下单 1 台 → 200，项目 `active`、`lockedQty=1`、`shippedQty=0`、outbounds 无新记录。
- 再下 1 台 → 200（`lockedQty=2`）；再下 1 台 → 400（锁定占满）。
- `PATCH /projects/1/status` 置 `delivered` → 200，`shippedQty=1`、`lockedQty=1`、新增 1 条 done 出库 `CK-0001`。
- 购物车加 1 台 → 结算 → 200、购物车空、新项目 `active`、锁定 +1、无新出库；删除该项目 → 锁定释放。

---

## 2026-10-15 ｜ 权限管控系统（⚠️ Breaking：所有接口新增鉴权）

**关联任务**：core-holdings 权限管控系统 — 后端实现（认证 + 角色鉴权 + 操作审计）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 ⚠️ | **全平台鉴权**：除 `POST /api/auth/login`、`GET /api/health`、`GET /api/files/{filename}` 外，所有 `/api/*` 端点要求 `Authorization: Bearer <jwt>`；无/错/过期 → 401 `未登录或登录已过期`；角色不足 → 403 `无权限执行此操作`。依赖逐个端点明确挂载（`get_current_user` / `require_editor` / `require_admin`），不用 router 级全挂 | `src/routers/api.py`, `src/security.py` |
| 2 | 新增 | **JWT 认证（HS256 自实现）**：仅标准库 hmac/hashlib/base64/json，零新依赖；exp 7 天；secret 取环境变量 `JWT_SECRET`（默认值仅本地开发，生产必须更换）；`POST /api/auth/login`（401 `用户名或密码错误` / 禁用账号 `账号已被禁用`）、`GET /api/auth/me` | `src/security.py`, `src/routers/api.py`, `src/schemas.py` |
| 3 | 新增 | **密码哈希**：`pbkdf2_hmac('sha256', pwd, salt, 100_000)` + 16 字节随机 salt，存 `pbkdf2$<salt_hex>$<hash_hex>`；明文密码不出现在任何响应体/日志 | `src/security.py` |
| 4 | 新增 | **用户管理（仅 admin）**：`GET/POST /api/users`、`PUT/DELETE /api/users/{id}`；禁止修改自己的 role/enabled（400 `不能修改自己的角色或启用状态`）、禁止删除自己（400 `不能删除自己的账号`）；role 仅 admin/editor/viewer，非法 400 | `src/routers/api.py`, `src/schemas.py` |
| 5 | 新增 | **审计日志（仅 admin）**：`GET /api/audit-logs`（actionType/username 过滤 + 分页，pageSize 上限 100，按时间倒序）；新表 `audit_logs` 与既有 `logs`（OpLog）分表，OpLog 调用方行为完全不动 | `src/routers/api.py`, `src/models.py`, `src/schemas.py` |
| 6 | 新增 | **审计记录点（router 层统一 `record_audit`，业务 services 零改动）**：sale（新建/编辑/变更项目状态/删除销售项目/下单/购物车结算）、outbound（新出库/撤销出库）、asset_change（新增/编辑/删除资产）、setting（基础资料/交付物模板/资产交付物增删改）、user_mgmt（用户增删改、删除上传文件）、auth（登录成功/失败，失败 detail 带原因） | `src/routers/api.py`, `src/security.py` |
| 7 | 新增 | **启动迁移**：`Base.metadata.create_all` 自动建 `users`/`audit_logs` 表；`users` 为空时种子 `admin`（密码 123456，role=admin），非空不创建；旧 logs **不回填** audit_logs | `main.py` |

### 权限矩阵

| 能力 | admin | editor | viewer |
|------|:-----:|:------:|:------:|
| 读（所有 GET/查询） | ✅ | ✅ | ✅ |
| 业务写（资产/项目/出库/购物车/下单/基础资料/交付物/上传） | ✅ | ✅ | ❌ 403 |
| 账号管理 `/api/users/*` | ✅ | ❌ 403 | ❌ 403 |
| 审计查询 `GET /api/audit-logs` | ✅ | ❌ 403 | ❌ 403 |

### 未改动 / 保持不变的既有行为（回归依据）

- 业务 services（库存/金额/状态机）一行未动；既有接口请求/响应契约不变。
- 购物车 `DEFAULT_USER="admin"` 语义不变（本轮**不**按登录用户隔离）。
- camelCase 字段风格不变；`requirements.txt` 未动（零新依赖）。
- `GET /api/files/{filename}` 保持匿名可访问（合同文件预览不破坏）。

### 自测（临时库 /tmp/perm.db + 8012 端口，未污染真实库；验证后已清理）

- 未带 token `GET /bootstrap` → 401；`admin/123456` 登录 200 得 token；错误密码 401。
- viewer：`GET /bootstrap` 200；`POST /assets` 403；`GET /users` 403。
- editor：`POST /assets` 200；`GET /users` 403；`GET /audit-logs` 403。
- admin 全流程：建项目 SP-001 → 置 delivered → `GET /audit-logs?actionType=sale` 命中「新建销售项目/变更项目状态」且 `username=admin`。
- admin 改自己 role → 400；删自己 → 400；改自己密码后旧密码 401、新密码 200。
- 禁用账号后其旧 token 访问 → 401；匿名 `GET /files/xxx` → 404（不要求 401）。
- 回归：53 项端到端脚本（带 admin token，含 A2 多明细交付 / A6 删除项目 / B11 购物车链路 / B12 下单）→ **PASS 53 / FAIL 0**。

---

## 2026-10-14 ｜ 收尾修正（3 项：新增交付物日志 assetId / 库存聚合校验 / 存量 status 回填）

**关联任务**：core-holdings 后端收尾修正（后端验收 3 点）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **回归缺陷** `services.add_asset_deliverable` 的 `add_log(...)` 遗漏 `asset_id`，导致前端资产详情「操作记录」（按 `l.assetId === assetId` 过滤）看不到「新增交付物」记录；补 `asset_id=a.id`（`target='asset'`、`action='新增交付物'` 不变）。同轮排查：全部 `target=='asset'` 的 `add_log` 调用（新增资产 / 编辑 / 删除 / 新增·更新·删除交付物）均已带 assetId；`target != 'asset'`（project/outbound/setting）保持不变 | `src/services.py` |
| 2 | 修复 | **超卖/超锁漏洞** 库存校验由「逐条按全量可售」改为**按 assetId 聚合后再比较**：先汇总本项目内同一 assetId 全部明细的 qty 合计，再与可售比较，超量 400。`update_project` 在释放旧锁定之后按新明细聚合（不把本单旧占用计入）。错误消息格式不变，`{m}` 为该资产合计需求量 | `src/services.py` |
| 3 | 修复 | **存量数据自洽** `main.py::_ensure_migration` 追加幂等回填：**复用 `services.auto_status`**（避免规则二次实现）逐条比对 `assets`，仅当 `status` 与计算值不同才 UPDATE，并 `print` 更新条数；只改 `status`，不触碰 `lockedQty/shippedQty/quantity`。第二次启动命中 0 条、无写入 | `main.py` |

### 变更说明 / WHY

- 修正 2：同一项目可能含多条引用同一 assetId 的明细（如 qty 各 1、可售仅 1），逐条按「全量可售」校验会全部通过而合计超卖/超锁。现按 assetId 聚合需求后再比较，`m` 用该资产合计需求量。
- 修正 3：新增 `auto_status` 规则（`(qty - lockedQty - shippedQty) <= 0` 且非 `repeatSale` → `all_sold`）后，历史行可能仍是旧口径。回填直接调用 `services.auto_status`，保证与运行时判定完全一致。

### 自测（临时库，未污染真实库）

- 修正 1：新建资产(id=29)→新增交付物；`GET /api/bootstrap` 中「新增交付物」日志 `assetId=29`（非空且等于资产 id）。
- 修正 2：同资产两条明细合计 2 > 可售 1 → 400 `{"detail":"库存不足：B4聚合A 可售 1台，本单需 2"}`；合计 2 ≤ 可售 3 → 200 且 `lockedQty=2`；`update_project` 路径合计 4 > 释放后 3 → 400 `本单需 4`、合计 3 → 200 且 `lockedQty=3`。
- 修正 3：临时库人工造错（qty=1/locked=1/status=in_stock）→ 启动回填 `1 条` → 该行 `all_sold` 且数量字段不变；再次启动 `0 条`（幂等）。

---

## 2026-10-14 ｜ 致命/高危功能缺陷修复（D1/H1-H8/M6/M12/F9）

**关联任务**：core-holdings 后端缺陷修复（三路审计 D1/D2/H1-H4/H7/H8/M1/M6/M12/F9）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **D1** 出库单/资产/项目主键手工取自 `max(id)+1`（autoflush=False 时循环内重复）→ 改为不手写主键，`db.add + flush` 由 DB 生成 id 再拼 code；编号格式不变（CH-EMB-001 / SP-001 / CK-0001） | `src/services.py` |
| 2 | 修复 | **H8** `change_project_status` / `create_project` / `update_project` / `delete_project` / `create_outbound` / `revert_outbound` / `cart/checkout` / `sales/order` 写操作收敛为单事务（函数内仅 commit 一次，异常整体回滚）；`checkout` 的 建项目→交付出库→清空购物车 同一事务 | `src/services.py` |
| 3 | 修复 | **H1** 建/编辑项目加锁前校验可售库存（`quantity-lockedQty-shippedQty`），不足返回 400 `库存不足：{name} 可售 {n}{unit}，本单需 {qty}`；`qty<=0` 拒绝；`update_project` 在释放旧锁定之后校验 | `src/services.py` |
| 4 | 修复 | **H2** `PUT /projects/{id}` 仅允许 `status=='active'` 项目编辑；重建明细时保留已 `shipped` 明细不被误删/误改 | `src/services.py` |
| 5 | 修复 | **H3** 由请求体契约收敛解决：`ProjectInput` 移除 `status`，编辑不采信传入 status | `src/schemas.py`, `src/services.py` |
| 6 | 修复 | **H4** `item_status_of_input` 不再以金额是否为 0 判定：`assetId` 空→`pending_asset`，否则→`locked`；零价明细交付时正常扣库存/出库。`pending_amount` 自此不再产生（预期） | `src/services.py` |
| 7 | 修复 | **H7** `delete_asset` 增加引用完整性校验：被非终止项目明细或 `status='done'` 出库引用则 400；并清理引用该资产的购物车项。用服务层校验替代数据库外键（SQLite 迁移风险） | `src/services.py` |
| 8 | 新增 | **D2** `DELETE /projects/{id}`：先回滚（复用 `_terminate_project`：释放未出库锁定 + 撤销该项目名下所有 done 出库并回退 shippedQty/soldAmount/soldCount）→ 再硬删项目及明细 → 写 OpLog（target='project', action='删除'）；不存在 404 | `src/routers/api.py`, `src/services.py` |
| 9 | 删除 ⚠️ | **M6** 移除 `PATCH /assets/{asset_id}/status` 端点及 `services.change_asset_status`（与 2 态自动判定冲突；前端从不调用） | `src/routers/api.py`, `src/services.py` |
| 10 | 修改 ⚠️ | **契约 3** `POST /projects` 请求体移除 `status` 字段，后端强制 `status='active'`；前端若仍传 status 被忽略（Pydantic 忽略未知字段） | `src/schemas.py`, `src/services.py` |
| 11 | 修改 ⚠️ | **契约 4** `PUT /projects/{id}` 忽略传入 status（不写入 p.status）；仅 `status=='active'` 可编辑，否则 400 `已完成/已终止项目不可编辑` | `src/services.py` |
| 12 | 修改 | **契约 5** 金额精度统一为万元 4 位小数（=元级精度）：`ProjectItemInput.amount` 由后端权威重算 `round(price*qty,4)`，忽略前端传值（create/update 均重算）；`soldAmount` 累加/回退统一 `round(...,4)` 且**取消 `max(0,...)` 静默夹零**；`create_outbound` 金额同样 4 位；`_order_core` 由 `round(...,2)` 改 `4` 位 | `src/services.py` |
| 13 | 修改 | **M12** Pydantic v2 `Field` 校验：`quantity`/`qty` `ge=0`；`salePrice`/`price`/`amount`/`expectedAmount`/`quoteAmount`/`contractAmount`/`paidAmount` `ge=0` | `src/schemas.py` |
| 14 | 修复 | **F9/M1** `auto_status` 改为 `no_sellable = (not repeatSale) and (quantity - lockedQty - shippedQty) <= 0` → `all_sold`，否则 `in_stock`（与前端 `noSellableStock` 完全一致） | `src/services.py` |
| 15 | 新增 | **契约 8** `OpLog` 新增列 `assetId`（Integer, nullable）；所有 `target=='asset'` 的 `add_log` 调用带 assetId；`LogOut` 增加可选 `assetId`。加列走 `main.py` 幂等轻量迁移 | `src/models.py`, `src/schemas.py`, `src/services.py`, `main.py` |

### 未改动 / 保持不变的既有行为（回归依据）

- 项目状态机取值不变（active/delivered/terminated）；仅「编辑入口」加了 active 前置约束。
- 资产 2 态（in_stock/all_sold）、明细 6 态取值不变。
- 可重复售卖资产不扣库存、终止完整回滚、删除资产级联删交付物/流水、历史补录不扣库存等行为保持不变。
- `models.py` camelCase 字段名与 `frontend/src/types.ts` 对齐关系未变。
- `seed_data.py` 未改动。
- 购物车加购/改量/清空、基础资料、交付物模板等接口未改动逻辑。

### 提交后自测（curl 实测摘要，详见 api.md）

- 2 明细项目交付：生成 2 条出库单 `CK-0006`/`CK-0007`（id 6/7 互异），HTTP 200，不再 500。
- 超卖：`asset3 qty=5`（可售 1）→ 400，资产未扣减、项目未落库。
- `POST /projects` 传 `status=delivered` → 实际落库 `active`。
- delivered 项目 `PUT` → 400 `已完成/已终止项目不可编辑`。
- `DELETE /projects/{id}` → 出库回退 `reverted`、shippedQty/soldAmount 回退、项目与明细消失、写删除日志。
- 零价资产（salePrice=0）delivered → 库存扣减、状态 `all_sold`、明细 `shipped`。
- `POST /assets quantity=-5` → 422。
- 删除被非终止项目引用的资产 → 400。
