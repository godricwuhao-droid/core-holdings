# 后端 API 接口文档

> base path：`/api`｜服务：FastAPI + SQLAlchemy + SQLite｜字段与 `frontend/src/types.ts` 对齐（camelCase）

---

## 2026-10-22 变更（FORMS-20261022 / ADR-036 + ADR-037：产品登记规则 + 生态人员购物车口径）

> 契约见 `docs/api-contracts.md`「FORMS-20261022 批次」。**请求/响应字段形状零变化**，本批全部是校验规则收紧/放宽；无 schema 变更、无数据迁移。

### `POST /api/assets`（新建登记，ADR-036 §1/§4）

- `inboundDate` **不再是必填入参**：不传 / 空串 → 后端自动取当天 `YYYY-MM-DD`（登记流水日期同口径）；传值仍走 `_validate_date_str` 校验（非法 → 400「登记日期格式须为 YYYY-MM-DD」）。
- `type == "遥感数据"`（容器）且 `repeatSale == true` → **400**：
```json
{"detail":"遥感数据容器按明细售卖，不支持重复售卖"}
```
- 其余字段（`perpetual` 等）语义不变（「长期买断」→「产品有效期」为前端文案）。

### `PUT /api/assets/{id}`（编辑，ADR-036 §4）

- 容器 `repeatSale` 同规则：按「存量值 + 本次 patch」的**最终落库值**校验——`type=遥感数据` 且 `repeatSale=true` → 400（同上文案；覆盖「type 改为遥感数据」与「repeatSale 改为 true」两条路径）。
- `inboundDate` 传值可改（只读展示是前端约束，后端不锁）；**不传 = 保持原值**（`exclude_unset`，不会把登记时间清空）。

### `PUT /api/cart/{id}` / `PATCH /api/cart/{id}` / `POST /api/cart/checkout` 区间校验分角色（ADR-037 §3）

- **viewer（生态人员）**：行金额仅校验**下限**——`amount < priceMin` → 400（原文案不变）；`amount > priceMax` **允许**（原 400 取消，加价成交放行）。遥感明细行用明细自身区间（ADR-021），同分角色规则。
- **editor/admin**：双向校验不变（`amount > priceMax` → 400）。
- **viewer 行携带历史 `discountRate`**：忽略（不 400、不参与任何计算，金额恒为权威；折扣率快照只写不改，仍原样落 `project_items.discountRate`）。
- 实现为**单函数**：改价入口（`set_cart_qty` / `patch_cart_item`）与 checkout 权威链（`checkout` → `_create_project_core`）共用 `_check_discount_range` / `_check_unit_price_range`（新增 `enforce_max` 参数，viewer 传 False），角色取当前登录用户。

实测（数据库副本 + TestClient，asset 9 区间 25000~25500 元/轨）：
```
viewer PUT /cart/{id} {"qty":1,"amount":30000} → 200，amount=30000（超上限放行）
viewer PUT /cart/{id} {"qty":1,"amount":24000} → 400 {"detail":"折扣单价超出该产品参考区间（25,000.00~25,500.00 元/轨）"}
editor PUT /cart/{id} {"qty":1,"amount":30000} → 400（同文案，原行为保持）
viewer POST /cart/checkout（行金额超上限 + 历史 discountRate=0.5）→ 200，item.amount=26000.0（折扣不参与计算）、item.discountRate=0.5（快照保留）
```

---

## 2026-10-22 变更（ENTITIES-20261022 / ADR-035：资产主体可维护，4 个新端点 + bootstrap 新字段）

> 主体清单从前端 `types.ts::ENTITIES` 硬编码改为后端 `entities` 表单一事实来源。契约见 `docs/api-contracts.md`「ENTITIES-20261022 批次」。元素形状：`{ id: number, name: string, short: string, createdAt: string, updatedAt: string }`。

### `GET /api/entities`（登录即可，三角色放行）

请求：`GET /api/entities`（需 `Authorization: Bearer <jwt>`）
响应（200，实测节选，存量库回填 4 家）：
```json
[{"id":1,"name":"安徽天枢智算人工智能科技有限公司","short":"安徽天枢智算人工智能科技有限公司","createdAt":"2026-10-22 15:03","updatedAt":"2026-10-22 15:03"}, ...]
```
关键字段：数组元素 = `EntityOut`（`name`=公司全称，与 `assets.subject` 存储口径一致；`short`=展示简称）。排序：`createdAt` 正序、`id` 正序（存量展示顺序稳定）。

### `POST /api/entities`（admin+editor `require_editor`）

请求：
```json
{"name": "测试主体科技有限公司", "short": "测试主体"}
```
响应（200，实测）：
```json
{"id":5,"name":"测试主体科技有限公司","short":"测试主体","createdAt":"2026-10-22 15:03","updatedAt":"2026-10-22 15:03"}
```
错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 400 | 主体已存在 | `name`（trim 后）与现有主体重复 |
| 400 | 主体名称须为 2–64 个字符 | `name` trim 后长度不合规 |
| 400 | 主体简称须为 1–32 个字符 | `short` trim 后长度不合规 |

### `PUT /api/entities/{id}`（admin+editor `require_editor`）

请求：body 同 `POST`（`name`/`short` 均必填，同校验）。
响应（200，实测）：更新后的 `EntityOut`。
行为：**`name` 变化**时 OpLog「修改主体」（detail = `主体名称 旧名称 → 新名称`）+ audit「编辑资产主体」，**不回写** `assets.subject`（存量产品主体仍为旧全称，需逐个产品手动改选）；只改 `short` 不留改名日志。
错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 400 | 主体已存在 | `name` 与**其他**主体重复 |
| 400 | 主体名称须为 2–64 个字符 / 主体简称须为 1–32 个字符 | 长度不合规 |
| 404 | 主体不存在 | `id` 不存在 |

### `DELETE /api/entities/{id}`（admin+editor `require_editor`）

响应（200，实测）：`{"ok": true}`（成功留 OpLog「删除主体」+ audit）。
错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 400 | 该主体下存在 N 个产品，不可删除 | 被任一产品引用（`assets.subject == name`，H7 服务层校验，SQLite 无外键）。实测：`该主体下存在 11 个产品，不可删除` |
| 404 | 主体不存在 | `id` 不存在 |

### `GET /api/bootstrap` 新增顶层字段

- `entities: EntityOut[]`（**全量，无角色过滤**——主体非敏感商业数据），位置在 `rsItems` 之后。实测（admin）：4 条，形状与 `GET /entities` 一致。前端删除 `types.ts::ENTITIES` 常量后由 `db.entities` 提供建产品「所在主体」下拉、产品列表主体筛选与 `entityShort()` 简称映射（查不到回退原值）。

---

## 2026-10-22 变更（FIX-20261022 / ADR-029 ~ ADR-034：2 处端点下线、1 处请求体可选字段、1 处提权、若干行为收紧，⚠️ 部分 Breaking）

> 契约基线见 `docs/api-contracts.md`「FIX-20261022 批次」。**响应形状不变**（唯一新增字段 = checkout 响应的可选 `idempotent`）。

### 1. `POST /api/sales/order`、`POST /api/projects/{id}/resubmit` —— 已下线（⚠️ Breaking）

两端点**一律 410 Gone**，不再执行任何业务逻辑（此前 `sales/order` 对 viewer 开放且只做部分校验，`resubmit` **完全不做**参考区间/服务期限校验，形成第二/第三套下单口径）。

请求（实测，任意 body 均同样返回）：
```
POST /api/sales/order      -H "Authorization: Bearer <viewer token>" -d '{}'
POST /api/projects/2/resubmit -H "Authorization: Bearer <viewer token>" -d '{}'
```
响应（410，实测）：
```json
{"detail":"该接口已下线，请使用购物车结算"}
```
关键字段：无。**唯一下单链路 = `POST /api/cart/checkout`**；唯一「重新提交」路径 = `POST /api/projects/{id}/refill-cart` → `/cart` 改单 → 结算。前端已无封装/入口。

### 2. `POST /api/cart/checkout` —— 新增可选 `requestId`（幂等）

请求：`POST /api/cart/checkout`
```json
{"projectName":"BUG10幂等验证单","expectedSignDate":"2026-10-22","requestId":"verify-request-0001"}
```
响应（200，首次，实测节选）：
```json
{"id":4,"code":"SP-2026102210263819","name":"BUG10幂等验证单","status":"pending","expectedAmount":3006700.0,"contractAmount":3006700.0,"creator":"admin","idempotent":false,"items":[...],"contracts":[...]}
```
响应（200，同一 `(userId, requestId)` 24h 内重复请求，实测）：
```json
{"id":4,"code":"SP-2026102210263819","idempotent":true,...}
```
关键字段：
- `idempotent`：bool（**本次新增，可选字段**）。`false` = 本次真实建单；`true` = 命中首次请求，`id` 为首次项目，**未重复建单/锁量/清购物车**。
- 其余字段形状与 `ProjectOut` 完全一致（不变）。

错误码（本次相关）：

| HTTP | 文案 | 场景 |
|---|---|---|
| 400 | 请求标识过长（requestId 最多 64 字符） | `requestId` 长度 > 64 |
| 400 | 该请求正在处理中，请稍后刷新查看结果 | 同一键并发请求，唯一约束冲突且首次尚未落库 |
| 400 | 购物车存在必填缺项，请补齐后再结算：… | 既有 ADR-022 校验（不变） |

### 3. `POST /api/projects/{id}/review` —— 服务期限可显式清空（BUG-23 后端部分）

`items[].serviceStart` / `items[].serviceEnd` 语义改为：**未传 = 保持原值；显式 `null` = 清空**（与 `PUT /cart/{id}` 的 `UNSET` 哨兵口径一致）。

请求（实测节选）：
```json
{"action":"confirm","items":[{"itemId":11,"serviceStart":null,"serviceEnd":null}]}
```
响应（200，实测）：`{"ok":true}`；随后 `project_items.serviceStart/serviceEnd` 均为 `NULL`（此前被当作「未传」而无法清空）。
另：非接手人调用 → **403**（原 400）「仅接手的商务负责人（…）可调整该订单价格，如需处理请先转交」。

### 4. 权限类失败统一 403（BUG-33）

| 接口 | 场景 | 变更 |
|---|---|---|
| `PATCH /api/contracts/{id}/status` | viewer 执行「交付」 | **400 → 403**「生态人员仅可终止销售记录（交付需商务人员/管理员操作）」 |
| `POST /api/projects/{id}/review` | 非接手人（非 admin） | **400 → 403**（文案不变） |
| `GET /api/users/options` | viewer | **200 → 403**「只读账号不可执行该操作」（守卫提升为 `require_editor`，BUG-32） |
| `DELETE /api/cart` | 所有角色 | 响应由空 body 改为 `{"ok": true}` |
| `POST /api/auth/login` | 同 `(ip, username)` 15min 内失败 ≥10 次，或同 IP ≥30 次 | **429**「登录尝试过于频繁，请稍后再试」 |

`POST /api/auth/login` 其余变更（⚠️）：账号不存在 / 密码错误 / 账号被禁用 **统一 401**「用户名或密码错误」（不再返回「账号已被禁用」，避免账号枚举）；`tokenVersion` 变更后旧 token → 401「登录状态已失效，请重新登录」。

### 5. `GET /api/files/{filename}` —— 对象级 ACL（BUG-02，⚠️ 行为收紧）

可见性 = 被任一产品引用（`assets.contractFile`/`featureDoc`/`asset_deliverables.file`）→ 所有登录用户可见；未被引用的孤儿文件 → 仅 `uploadedBy == 当前用户` 或 admin。

请求（实测，viewer 请求孤儿文件）：
```
GET /api/files/1635df668b4345cb88dcd432bc1a0cf4.doc?token=<viewer jwt>
```
响应（404，实测；**不返回 403**，避免探测文件名存在性）：
```json
{"detail":"文件不存在或已被删除"}
```
响应（200，admin 或引用文件，实测响应头）：
```
HTTP/1.1 200 OK
x-content-type-options: nosniff
content-disposition: attachment; filename*=UTF-8''…
```
关键变更：
- 新增响应头 `X-Content-Type-Options: nosniff`；
- `GET /api/bootstrap` 的 `files` 按同一规则过滤（实测 admin 49 条 → viewer 24 条）；
- `POST /api/upload`：`.doc` 移出白名单（400「不支持的文件格式：.doc（支持 pdf/docx/图片/xlsx）」），改流式写入，>20MB 立即中断（400「文件过大（上限 20MB）」）。

### 6. 状态机/可见性相关的 400 文案变更

| 接口 | 场景 | 文案（HTTP 400） |
|---|---|---|
| `PATCH /api/contracts/{id}/status`（delivered） | 合同未进入 `delivering` / `signedDate` 为空 | **`合同 {code} 尚未录入签订时间，不可交付`**（⚠️ 现包含合同编号） |
| 同上 | 存在 `pending_asset` 明细 | `合同 {code} 尚有 N 项明细未关联产品，无法交付完成` |
| `PATCH /api/projects/{id}/status`（delivered，批量） | 任一合同不合规 | **全量或全不**：`以下销售记录不满足交付条件，请先补齐后重试：{code} 尚未录入签订时间，不可交付；…`（一次列出全部不合规合同） |
| `PATCH /api/projects/{id}/status`（terminated）/ 合同终止 | 已交付明细的产品已删或明细缺失 | `该产品/明细已不存在，无法回滚交付，请先联系管理员（…）` |
| `POST /api/outbounds/{id}/revert` | 产品已删 / 合同交付明细缺失 | 同上（不再「静默成功零回滚」） |
| `DELETE /api/assets/{id}` | 存在 `delivered` 销售记录引用 | `该产品存在已交付销售记录，不可删除` |
| 建单（`POST /projects`、`POST /cart/checkout`） | 非空 `assetId` 指向不存在产品 | `所选产品不存在或已删除` |
| 同上 | `contractAmount` 显式传入（> 0）且 ≠ Σ 明细金额 | `合同金额与明细合计不一致`（`0`/未传 = 未填写，按 Σ 明细派生，不报错） |
| 同上 | unit 行单价超出产品参考区间 | `销售单价超出该产品参考区间（{min}~{max} 元/{unit}）` |
| 同上 | 同一记录内重复产品行 | `同一销售记录中同一产品（含明细）不可重复，请合并为一行` |
| 同上 | 同项目内「客户 + 明细集合」完全重复 | `客户「{customer}」下相同的销售明细不可重复建记录` |
| 同上 | 日期格式非法 | `{label}格式须为 YYYY-MM-DD`（label：预计签订日期 / 最后跟进日期 / 登记日期 / 到期日期 / 交付日期） |
| 同上 | 数量/金额不变量被破坏（并发或脏数据） | `数据不变量被破坏：…（请联系管理员核对台账）`（**HTTP 500** + OpLog「数据不变量告警」） |

### 7. 分页端点可见性（BUG-13）

- `GET /api/assets/{id}/flows`：viewer 走与 `bootstrap` **同一** `visible_flow()` 过滤，`total` 为过滤后总数（实测 asset 1：admin 5 → viewer 3）。
- `GET /api/bootstrap`：`logs` 的 `target="contract"` 日志对 viewer 全部过滤（实测 571 → 262）；`target="project"` 按 `logs.projectId`/`contractId` 判定，无外键的存量日志对 viewer 过滤。

---

## 2026-10-21 变更（EDITLOCK-20261021 / ADR-028 生态人员订单提交后禁止编辑 + 撤销单删除护栏，⚠️ Breaking）

> 语义：**订单一旦提交即冻结**，生态人员改单唯一路径 = `POST /projects/{id}/withdraw`（撤销）→ 明细回填购物车（`refill-cart`）→ 改单重新结算。**无新增端点、无 schema 变更**（复用 `projects.cartRefilled` 作撤销留痕标记），仅收紧两个既有端点的权限。

### `PUT /api/projects/{id}`（权限：viewer 一律 403）

权限：`require_order`；**`role == "viewer"` 一律 403**，不看状态与归属（系统无草稿态：`POST /projects` 直接生成 `pending`，故「提交后禁编辑」等价于「viewer 禁止编辑」）。商务/管理员规则不变。

请求（viewer 账号，项目为自己下单的 pending 单；实测项目 id=3）：
```
PUT /api/projects/3
{"name":"ADR028自测-viewer订单","customer":"ADR028自测客户","industry":"","rep":"viewer","expectedSignDate":"2026-10-21","lastFollowDate":"2026-10-21","remark":"x","expectedAmount":0,"contractAmount":0}
```
响应（403，实测）：
```json
{"detail":"订单已提交，不可编辑；如需修改请「撤销」后重新下单"}
```

错误码（实测）：

| HTTP | 文案 | 场景 |
|---|---|---|
| 403 | 订单已提交，不可编辑；如需修改请「撤销」后重新下单 | `role=viewer`（任意项目：自己的 pending 单、他人项目、终止单均同文案） |
| 404 | 项目不存在 | `id` 不存在（**404 优先于 403**，viewer 调用亦返回 404） |
| 400 | 待审核项目仅商务负责人（或管理员）可编辑基本信息 | 商务非负责人编辑 `pending` 项目（实测 editor → 非本人 `pending` 单） |
| 400 | 已交付完成的项目不可编辑 / 项目已终止，不可编辑 / 项目名称不能为空 | 不变（既有校验） |

响应（200，商务负责人编辑自己 `pending` 项目 / 自己 `active` 项目，实测）：
```json
{"ok": true}
```
关键字段：无（仅 `ok`）；viewer 编辑权限已整体收回，`rep` 入参特判随之删除（父权限不存在后为死代码）。

### `DELETE /api/projects/{id}`（新增撤销留痕护栏）

权限：`require_editor`（admin/editor）。**新增守卫**：`status == "terminated" and cartRefilled == true` → 403。

请求：`DELETE /api/projects/1`（已撤销项目，`status=terminated`、`cartRefilled=1`）

响应（403，实测）：
```json
{"detail":"该订单已撤销（或已回填购物车）并将保留历史记录，不可删除"}
```

响应（200，被驳回/终止且**从未回填**的项目，实测项目 id=3）：`{"ok":true}`（既有回滚逻辑不变：释放锁定、撤销 done 交付并回退 `shippedQty`/`soldAmount`/`soldCount`，实测 asset 4 的 `lockedQty` 0→0、`status` 仍 `in_stock`）。

错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 403 | 该订单已撤销（或已回填购物车）并将保留历史记录，不可删除 | `terminated` 且 `cartRefilled=true`（已撤销，或撤销后点过「重新提交」） |
| 404 | 项目不存在 | `id` 不存在 |
| 200 | `{"ok":true}` | 其他终态（被驳回且从未回填）仍可清理；进行中/待审核项目删除行为不变 |

关键字段：无（仅 `ok`）。**不提供绕过接口**——管理员确需清理撤销单走数据库运维。校验在 `get_project` 之后、任何写操作之前（先校验后写，保持单事务语义）。

### 不变的部分

`POST /projects/{id}/withdraw`（仅 `pending` 可调）、`POST /projects/{id}/refill-cart`（幂等）、`PATCH /projects/{id}/status`（viewer 仍可终止**自己**项目并填原因：撤销 = 待审核单撤回**并回购物车**；终止 = 已生效单作废**不回购物车**）。

---

## 2026-10-21 变更（ADR-027「重新提交」收口购物车，新增端点；resubmit 标废弃）

> 语义：终止项目（撤销/驳回）的「重新提交」= **确保原单明细在购物车 → 前端跳 `/cart` 改单再结算**（与撤销后动线一致），不再跳 create 页 copy 模式。**幂等只回填一次**（`Project.cartRefilled` 标记）。

### `POST /api/projects/{id}/refill-cart`

权限：`require_order`（已认证即可）——`admin` / `editor` 放行（代操作也回填到**下单人**购物车）；`viewer` 仅**自己下单**的项目（`creator` 口径，存量回退 `rep`，同 resubmit），否则 403。

请求：`POST /api/projects/4/refill-cart`（**无 body**，不要传 `Content-Type` 之外的任何字段）

响应（200，首次回填——实测 viewer 对 2 行明细的被驳回项目调用）：
```json
{"ok": true, "alreadyRefilled": false, "restored": 2, "amountFallback": 0, "skipped": 0, "skippedReasons": []}
```

响应（200，已回填过——实测撤销后 / 二次点击 / admin 重复调用）：
```json
{"ok": true, "alreadyRefilled": true, "restored": 0, "amountFallback": 0, "skipped": 0, "skippedReasons": []}
```

关键字段：
- `ok`：bool，固定 true（失败走 HTTP 错误码）。
- `alreadyRefilled`：bool，`true` = 该项目明细此前已回填过（`cartRefilled` 已为 1），本次**未写库、未回填、未打日志**；前端据此提示「明细已在购物车」。
- `restored`：int，本次成功回填购物车的明细行数（`alreadyRefilled=true` 时恒 0）。
- `amountFallback`：int，因参考区间/金额口径失配降级「原价成交（`amount=null`）」的行数（计入 `restored`）。
- `skipped` / `skippedReasons`：int / string[]，无法回填的行数与逐行原因（口径与 `withdraw` 完全一致）。

错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 404 | 销售项目不存在 | `id` 不存在 |
| 400 | 仅已终止的项目可重新提交 | 项目 `status ≠ terminated`（pending/active/delivered；含进行中、待审核） |
| 403 | 生态人员仅可重新提交自己下单的项目 | viewer 且非本人下单（`creator` 口径） |
| 400 | 下单账号不存在，无法回填购物车 | `creator`/`rep` 都查不到用户账号（无法确定回填目标） |

副作用（单事务，仅**首次**回填发生时）：
- `cart_items` 新增/合并**下单人**（`users.id` 字符串）的行，保留 `customer/qty/amount/serviceStart/serviceEnd/discountRate/itemId`；判重键 `(userId, assetId, itemId, customer)` 命中已有行 → 合并累加 qty / 覆盖 amount（不报错、不翻倍）。
- `projects.cartRefilled = 1`（幂等标记）；`updatedAt` 不变。
- OpLog `project/重新提交（回填购物车）` 1 条（detail：`N 行明细已回填购物车（原价回填 M 行，跳过 K 行），由下单人 {username} 购物车改单后重新提交`）+ `audit_logs` 1 条（action=`重新提交（回填购物车）`；`alreadyRefilled` 时不记录）。
- **不锁量**（`assets.lockedQty` 不变）、**不改**项目/合同状态、**不新建**订单、**不产生** `flows`。

### `POST /api/projects/{id}/resubmit`（⚠️ deprecated，ADR-027）

**行为不变**（按明细新建 pending 订单，旧项目保留 terminated 历史），但**前端已无入口**：入口改为 `POST /api/projects/{id}/refill-cart` → 跳 `/cart`。端点保留仅为兼容既有脚本/外部调用，新代码请勿依赖。

---

## 2026-10-21 变更（ADR-026 生态人员「撤销」待审核订单，新增端点）

> 语义：**撤销 = 终止原单（释放锁定 + 流水 + 合同备注留痕）+ 全部明细自动回填下单人购物车**（用户在购物车改完重新结算）。原单保留 `terminated` 历史（原因可查），不删除、不新增「草稿」状态。不改现有终止/驳回/重新提交口径。

### `POST /api/projects/{id}/withdraw`

权限：`require_order`（已认证即可）——**下单人本人**（`creator`）或 **admin**（admin 可代撤销，购物车仍回填到**下单人**）；其余账号 403。

请求：`POST /api/projects/3/withdraw`
```json
{"reason": "价格需重新确认"}
```

响应（200，实测 viewer 账号撤销 3 行明细的待审核单）：
```json
{"ok": true, "restored": 3, "amountFallback": 0, "skipped": 0, "skippedReasons": []}
```

单行回填降级/跳过时的响应（实测）：
```json
{"ok": true, "restored": 0, "amountFallback": 0, "skipped": 1, "skippedReasons": ["产品 #999999 已不存在"]}
```
```json
{"ok": true, "restored": 1, "amountFallback": 1, "skipped": 0, "skippedReasons": []}
```

关键字段：
- `ok`：bool，固定 true（失败走 HTTP 错误码）。
- `restored`：int，成功回填购物车的明细行数。
- `amountFallback`：int，因参考区间/金额口径失配而降级「原价成交（`amount=null`）」回填的行数（计入 `restored`）。
- `skipped`：int，无法回填的明细行数（无 `assetId` / 产品已删除 / 降级后仍 400）。
- `skippedReasons`：string[]，逐行跳过原因（如「产品 #12 已不存在」）。

错误码：

| HTTP | 文案 | 场景 |
|---|---|---|
| 404 | 销售项目不存在 | `id` 不存在 |
| 403 | 只能撤销自己提交的订单 | 非下单人且非 admin |
| 400 | 仅待审核订单可撤销 | 项目非 `pending`（active/terminated 等；含重复撤销） |
| 400 | 请填写撤销原因 | `reason` strip 后为空 |
| 400 | 撤销原因不能超过 200 字 | `reason` 长度 > 200 |
| 400 | 下单账号不存在，无法回填购物车 | `creator`/`rep` 查不到用户账号 |

副作用（单事务）：
- 合同 `pending → terminated`（复用终止链路：逐明细释放真实锁定 `it.locked` + 写 `cancel_release` 流水；repeatSale 明细不产生幽灵流水），`contracts.remark` 追加「撤销：{reason}」（追加不覆盖，已含同文案不重复追加）。
- 项目 `status=terminated`，派生字段重算（`customer/subject/expectedAmount` 口径与合同一致）；`businessOwner` 有值时置空并在 OpLog 详情留痕（「原商务负责人 X 已解绑」）。
- `project_items.status` 全部 → `released`。
- 购物车：回填到下单人（`users.id` 字符串）的行，保留 `customer/qty/amount/serviceStart/serviceEnd/discountRate/itemId`；判重键 `(userId, assetId, itemId, customer)` 命中已有行则**合并累加 qty / 覆盖 amount**，不报错；遥感明细行 `qty` 恒 1、`itemId` 保留。
- 日志：OpLog `project/撤销订单` 1 条（detail：`待审核订单已撤销，N 行明细回填购物车（原价回填 M 行，跳过 K 行），原因：…`）+ `audit_logs` 1 条（action=`撤销订单`，detail=`reason=…`）；各合同另有既有「销售记录状态变更」终止日志。

---

## 2026-10-21 变更（CART-PATCH-20261021：购物车行更新改为 PATCH 语义）

> 修复：购物车填「销售金额」后选服务期限/改客户，金额被清空。

| 接口 | 语义 |
|---|---|
| `PUT /api/cart/{id}` | `qty` 必传；`amount`/`serviceStart`/`serviceEnd`/`discountRate` **未传 = 保持原值不改**，显式 `null` = 清空 |
| `PATCH /api/cart/{id}` | 按 Pydantic `model_fields_set` 判断（只更新 body 里出现的字段） |

例外（保留旧行为）：数量**真的变化**且未传 `amount`、该行无 `discountRate` 时，清空该行手工折扣金额（旧总额对新数量失真；有折扣率的行由前端按 rate 重算并显式提交 amount）。校验/400 文案/响应体（`CartItemOut`）均不变。

---

## 2026-10-21 变更（ADR-024 交付物模板彻底下线 + 交付物单文件附件，⚠️ Breaking）

> 交付物全部在产品详情页手动维护（不再由模板惰性生成）；每项交付物可挂单个附件（复用 `/api/upload`，前端 accept 更严：`.pdf,.docx,.png,.jpg,.jpeg,.gif,.webp`）。

### 删除端点（⚠️ 全部 404，前端同批移除模板 CRUD 函数）

| 方法 | 路径 |
|---|---|
| POST | `/api/deliverable-templates` |
| PUT | `/api/deliverable-templates/{item_id}` |
| DELETE | `/api/deliverable-templates/{item_id}` |

### `GET /api/bootstrap` 返回体变更

- **移除** `deliverableTemplates` 字段（模板体系下线）。
- `assetDeliverables` 行新增 `file` 字段：string|null（单文件附件散列名，null=无附件）。
- **存量清空**：部署后首次启动迁移清空 `asset_deliverables` 全表（幂等），`assetDeliverables` 初始为 `{}`；建产品**不再自动生成**交付物实例。

### `PUT /api/assets/{asset_id}/deliverables/{item_id}`

- patch 白名单追加 `file`（其余 `name/category/required/note/version/meta/status` 不变）；
- `file` 传 `/api/upload` 返回的散列名；传 `""` 或 `null` = **清空附件**（落库 NULL）；
- 权限不变（`require_editor`）。

请求：`PUT /api/assets/30/deliverables/1`，body：
```json
{"file": "f00ed2c0c4da4b329b1a0d077e985f74.png"}
```
响应（200，实测）：
```json
{"ok": true}
```
关键字段：bootstrap `assetDeliverables["30"][0].file` = `"f00ed2c0c4da4b329b1a0d077e985f74.png"`（挂附件后）/ `null`（`file:""` 清空后）。
OpLog「更新交付物」的 `changes` 体现附件变化，与产品文件字段同格式（散列名还原为原始名）：`附件: → be024_e92db823.png`（清空时为 `附件: be024_e92db823.png →`）。

### `DELETE /api/upload/{filename}` 引用检查追加

被交付物附件（`asset_deliverables.file`）引用时 400（与产品清单/功能清单同文案风格，实测）：
```json
{"detail": "该文件仍被产品「BE024测试产品」的交付物「测试交付物」引用（交付物附件），请先移除交付物附件后再删除"}
```
`POST /api/upload` 白名单与 20MB 大小限制不变。

---

## 2026-10-21 变更（CART-PERF-20261021 购物车行更新性能：`PATCH /api/cart/{id}` 响应变更）

> 背景：行级更新（qty/amount/discountRate/service）每次写后前端全量重拉 bootstrap（含 97 条 rsItems/122 条 logs）整表重建 → 输入卡顿。改「写接口返回更新行 → 前端本地打补丁」。契约见 api-contracts.md「CART-PERF-20261021 批次」。

**响应变更**：`PATCH /api/cart/{id}` 由 `{"ok": true}` 改为**返回更新后的完整 `CartItemOut`**（含最新 customer/qty/amount/serviceStart/serviceEnd/discountRate）。入参、校验、400/404 文案、审计日志均不变。

请求：`PATCH /api/cart/6`，body `{"customer":"CART-PERF测试客户","amount":30000000,"discountRate":0.93}`

响应（200，实测）：

```json
{"id":6,"userId":"1","assetId":28,"customer":"CART-PERF测试客户","qty":1,"amount":30000000.0,"itemId":null,"serviceStart":null,"serviceEnd":null,"discountRate":0.93,"createdAt":"2026-10-21 10:52","updatedAt":"2026-10-21 10:52"}
```

关键字段：与 `POST /api/cart` 出参同构（`CartItemOut` 全字段）——`amount`（number|null，本次更新后的合同/折扣金额）、`discountRate`（number|null，0-1 小数）、`customer`（行级客户）、`qty`、`serviceStart`/`serviceEnd`（YYYY-MM-DD|null）、`updatedAt`（有字段变更时刷新）。

补漏（CART-PERF-20261021）：`PUT /api/cart/{id}`（set_cart_qty，数量端点）同口径返回 `CartItemOut`（原 `{"ok": true}`），入参、校验、400/404 文案不变。

---

## 2026-10-22 变更（FIX-20261022-FOLLOWUP：`bootstrap.rsItems` 补齐派生 `soldCount`）

> 抽屉「已售次数」列此前只能回退产品级 `asset.soldCount`（产品维累计），现与 `GET /assets/{id}/rs-items` 同口径下沉到明细级。**无 Breaking**：仅新增一个字段，其余字段与顺序不变，`RsItemPicker` 只读既有字段不受影响。

### GET /api/bootstrap（`rsItems[]` 元素形状 = `RsItemOutWithSold`）

请求：`GET /api/bootstrap`（需 `Authorization: Bearer <jwt>`）
响应（200，实测节选 1 条 `rsItems[]` 元素）：
```json
{"rsItems":[{"id":1,"assetId":29,"province":"河北","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000.0,"priceMin":null,"priceMax":null,"repeatSale":true,"createdAt":"2026-10-16 11:41","updatedAt":"2026-10-20 17:31","soldCount":0}]}
```
关键字段：`rsItems`（数组，全量明细，`id ASC`）；`rsItems[].soldCount`（number，**派生口径**：该明细被 `status='delivered'` 合同的项目明细计数——`project_items.itemId == rs_items.id` 且所属合同 `status='delivered'`，与 `GET /api/assets/{id}/rs-items` 的 `items[].soldCount` **同一实现** `services._rs_item_sold_counts`；无关联为 0）。其余 12 个字段与 `GET /api/assets/{id}/rs-items` 的 `RsItemOut` 完全一致，`soldCount` 追加在末尾。

实现说明：一次 `SELECT project_items.itemId, count(*) ... JOIN contracts ... WHERE contracts.status='delivered' GROUP BY project_items.itemId`（无 `IN` 条件，全表一次算完），复杂度 O(log n + k)，**无 N+1**；`item_ids=[]` 时直接返回 `{}` 不发查询。

---

## 2026-10-21 变更（DISCOUNT-20261021 购物车折扣率输入，新增可选字段 `discountRate`，依据 ADR-023）

> 选填快捷入口；销售金额仍是权威必填值（ADR-022 不变）。前后端同批上线（契约见 api-contracts.md「DISCOUNT-20261021 批次」）。**后端只存不算**：不做金额回填计算（前端回填 `amount = round(salePrice × qty × rate)` 后一次性提交 amount+discountRate；手动改 amount → 前端提交 `discountRate: null`），amount 现有校验（必填/整数元/参考区间）完全不变。

**字段口径**：`discountRate` = number 0-1 小数（0.9=九折，**前端传小数**），可空。

| 接口 | 变更 |
|---|---|
| `GET /api/bootstrap` | `cartItems[].discountRate`、`projectItems[].discountRate` 新增出参（均可空，存量行/存量订单为 null） |
| `POST /api/cart`、`POST /api/cart/batch` | 入参新增可选 `discountRate`；0 < rate ≤ 1 否则 400「折扣率须为 0 到 1 之间的正数」；null 允许=清空 |
| `PUT /api/cart/{id}`、`PATCH /api/cart/{id}` | 入参新增可选 `discountRate`，同口径校验；null=清空（无折扣） |
| `POST /api/cart/checkout` | 不改入参；落 `project_items.discountRate` = 购物车行值（**快照，只写不改**，与 origPrice/origAmount 同级口径） |
| `POST /api/projects`（手动建单） | `items[].discountRate` 可选（商务手填场景），同口径校验（`_create_project_core` 统一校验，覆盖购物车结算/手动建单/直接下单/重新提交全部入口） |
| review 接口 | **不改**：discountRate 只读展示（快照），终审改价仍只写 price/amount |

400 边界（实测）：`discountRate` = 0 / 1.5 / -1 → `{"detail":"折扣率须为 0 到 1 之间的正数"}`；`null` → 200（清空）。

---

## 2026-10-21 变更（PAGE-20261021 产品相关列表服务端分页，新增 3 个 GET 端点）

> 抽屉/详情页的可售明细、数量流水、操作记录改服务端分页（单页默认 10 条）。**`GET /api/bootstrap` 快照字段（rsItems/flows/logs）保留不动**（RsItemPicker 树等消费方仍依赖全量镜像）。契约见 api-contracts.md「PAGE-20261021 批次」。

**统一口径**（对齐 `GET /api/audit-logs` 先例）：

- 参数：`page: int ≥ 1`（默认 1）、`pageSize: int 1~100`（**默认 10**）
- 返回：`{ "total": number, "items": [...] }`
- 守卫：`get_current_user`（读接口三角色放行，与 bootstrap 读同口径；asset 级 flows/logs 对 viewer 全量放行是现状口径）
- 产品不存在（`asset_id` 无对应 assets 行）：三端点均 404 `{"detail":"产品不存在"}`

### `GET /api/assets/{asset_id}/rs-items`

可售明细分页，`id ASC`（录入顺序稳定）。items = `RsItemOut` 全部 13 字段 + 派生字段 `soldCount`。

请求：`GET /api/assets/29/rs-items?page=1&pageSize=10`

响应（200，实测）：

```json
{"total":97,"items":[{"id":1,"assetId":29,"province":"河北","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000.0,"priceMin":null,"priceMax":null,"repeatSale":true,"createdAt":"2026-10-16 11:41","updatedAt":"2026-10-20 17:31","soldCount":0}]}
```

关键字段：`total`（该产品明细总数）、`items[].soldCount`（number，**派生口径**：该明细被 delivered 状态合同的项目明细计数——`project_items.itemId == rs_item.id` 且所属合同 `status='delivered'`，后端一条聚合查询计算，替代前端遍历 contracts 派生「已售次数」列；无关联为 0）。

### `GET /api/assets/{asset_id}/flows`

产品级数量流水分页（仅该 `assetId`），`id DESC`。items = `FlowOut`。

请求：`GET /api/assets/29/flows?page=1&pageSize=10`

响应（200，实测）：

```json
{"total":12,"items":[{"id":78,"assetId":29,"type":"cancel_release","qty":1,"unit":"份","amount":0.0,"date":"2026-10-16","ref":"HT-0007","note":"项目释放锁定","operator":"admin","contractId":7}]}
```

关键字段：`total`（该产品流水总数）、`items[]`（FlowOut，`contractId` 非合同场景为 null）。

### `GET /api/assets/{asset_id}/logs`

产品操作日志分页（`target='asset'` 且 `assetId` 过滤），`id DESC`。items = `LogOut`。

请求：`GET /api/assets/29/logs?page=1&pageSize=10`

响应（200，实测）：

```json
{"total":122,"items":[{"id":542,"target":"asset","targetName":"遥感数据-2026","action":"删除可售明细","detail":"删除明细 #2：甘肃省 1m 2026-10","operator":"admin","time":"2026-10-20 17:34","assetId":29,"changes":"","contractId":null}]}
```

关键字段：`total`（该产品操作日志总数）、`items[]`（LogOut，`changes` 仅产品字段级编辑时非空）。

> 抽屉「最近动态」沿用前端合并逻辑：分页取 flows/logs 各一页后前端合并排序取 10 条，不新增合并端点（契约 §3）。

---

## 2026-10-24 变更（REQUIRED-20261024 购物车结算必填口径，⚠️ checkout 400 场景扩充，依据 ADR-022）

> 取代 ADR-018 §3「留空按挂牌价成交」兜底：后端 amount 为空回退 `salePrice×qty`（遥感行回退明细 price）的分支已删除，viewer 金额免填口径同步作废。前后端同批上线（契约见 api-contracts.md「REQUIRED-20261024 批次」）。

### `POST /api/cart/checkout` 逐行必填校验（缺项 400，一次报全）

逐行收集全部缺项后一次 400 报全（多缺项以「；」分隔），文案含行标识（产品名；遥感明细行为「产品名·明细名」）。行更新接口（`PUT/PATCH /cart/{id}`、加购）**不加**必填校验——允许暂存缺项（加购后分批补），仅结算强制齐全。

| 缺项场景 | 400 文案（示例） |
|---|---|
| 客户为空 | `购物车存在必填缺项，请补齐后再结算：{产品名}：客户` |
| 销售金额缺失 / ≤0 / 非整数元（**所有行类型**：unit/amount/遥感明细行） | `购物车存在必填缺项，请补齐后再结算：{产品名}：销售金额（整数元，大于 0）` |
| 普通产品行服务期限缺开始或结束（任一为空） | `购物车存在必填缺项，请补齐后再结算：{产品名}：服务期限（开始/结束日期均必填）` |
| 服务期限 start > end（绕过行更新直接改库的兜底；行更新接口本身先拦截） | `服务开始日期不能晚于结束日期` |
| 多缺项并存 | 一次报全，如 `...：客户；...：销售金额（整数元，大于 0）；...：服务期限（开始/结束日期均必填）` |

- **遥感明细行服务期限豁免**（itemId 非空的行不校验期限，ADR-020：期数即服务时间）；其余必填项（客户/金额）与普通行相同。行标识示例：`遥感数据-2026·河北/石家庄市 1.5m 2026-09`。
- 区间校验不受影响（ADR-018/021）：必填金额仍须落在参考区间内（未设区间不限制）。
- 下游影响：checkout 明细 amount 恒非空 → `price` 为派生展示值 `round(amount÷qty, 6)`；原价快照 origPrice/origAmount（下单时刻挂牌价）与合同金额派生口径不变（见 PRICING 批次章节）。

实测响应示例：

```json
{"detail":"购物车存在必填缺项，请补齐后再结算：区县级优质资源共建共享平台：销售金额（整数元，大于 0）；区县级优质资源共建共享平台：服务期限（开始/结束日期均必填）"}
```

---

## 2026-10-20 变更（RSITEM-RANGE-20261020 遥感售卖明细参考区间，⚠️ 折扣校验口径变更，依据 ADR-021）

> 取代 ADR-018 §5「遥感行不限制」口径（契约见 api-contracts.md「RSITEM-RANGE-20261020 批次」）。

### `POST /api/assets/{id}/rs-items`、`PUT /api/rs-items/{item_id}` 入参新增字段

`RsItemInput` 新增 `priceMin` / `priceMax`（number ≥ 0 | null，元/份，选填，单边允许；PUT 传 null 清空）。两者都有时 min ≤ max，否则 400「参考区间下限不能大于上限」（与产品区间同口径）。出参 `RsItemOut` 同步带出两字段。

请求：`PUT /api/rs-items/1`

```json
{"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000,"priceMin":200000,"priceMax":400000,"repeatSale":true}
```

响应（200，RsItemOut）：

```json
{"id":1,"assetId":29,"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000.0,"priceMin":200000.0,"priceMax":400000.0,"repeatSale":true,"createdAt":"2026-10-16 11:41","updatedAt":"2026-10-20 15:53"}
```

关键字段：`priceMin`/`priceMax`（number | null，null=不限制）。min>max → 400 `参考区间下限不能大于上限`。

### `GET /api/bootstrap`

`rsItems[]` 每行新增 `priceMin` / `priceMax`（number | null，元/份）；存量明细为 null（不限制）。

### ⚠️ 折扣区间校验口径变更（生态下单链路）

`POST /cart`、`POST /cart/batch`、`PUT /cart/{id}`、`PATCH /cart/{id}`、`POST /cart/checkout`、`POST /sales/order` 中**遥感明细行（itemId 非空）**的金额区间校验改用**该 rs_item 自身的 priceMin/priceMax**（不再取父产品容器 assets 的区间）；普通产品行仍用 assets 区间，行为完全不变；未设区间 = 不限制。超限 400 文案口径同 PRICING 批次：

```json
{"detail":"折扣单价超出该产品参考区间（200000~400000 元/份（可售明细））"}
```

原价快照不变：遥感行 origPrice/origAmount = 明细 price 快照（ADR-018 §2）。

---

## 2026-10-20 变更（PRICING-20261020 价格体系 + 时间节点 + 状态机 + 服务期限，⚠️ 部分行为变更）

> 依据 ADR-018 / ADR-019 / ADR-020，前后端同批上线（契约见 api-contracts.md「PRICING-20261020 批次」）。

### 新端点 `PATCH /api/contracts/{id}`（录入合同时间节点，ADR-019）

权限：`require_order`（已认证）+ 服务层守卫——**viewer 直接 403**；`signedDate` 仅该单商务负责人（businessOwner）/admin；`scheduledDeliveryDate` **仅 admin**。

请求：`PATCH /api/contracts/{id}`，body 两字段均可选（按字段分别校验，未传字段不处理）：

```json
{ "signedDate": "2026-10-20", "scheduledDeliveryDate": "2026-11-15" }
```

响应（200，更新后的 ContractOut，新增字段见下）：

```json
{"id": 23, "code": "HT-2026102014420888", "projectId": 7, "customer": "测试客户",
 "subject": "主体A", "contractAmount": 46000, "status": "delivering",
 "signedDate": "2026-10-20", "scheduledDeliveryDate": "2026-11-15",
 "remark": "", "items": [], "createdAt": "2026-10-20", "updatedAt": "2026-10-20"}
```

关键字段：`status`（新增值 `delivering`「交付中」）、`signedDate`（合同签订时间，录入即 active→delivering）、`scheduledDeliveryDate`（预计交付时间）。

| 场景 | 响应 |
|---|---|
| viewer 调用 | 403 `只读账号不可执行该操作` |
| editor 非该单 businessOwner 录 signedDate | 403 `仅接手的商务负责人（{owner}）可录入合同签订时间，如需处理请先转交` |
| 非 admin 录 scheduledDeliveryDate | 403 `仅管理员可录入预计交付时间` |
| 合同非 active/delivering 录/改 signedDate（如 pending/delivered/terminated） | 400 `仅「合同签订中」状态的合同可录入/修改签订时间` |
| signedDate 传 null/空清空（已有值） | 400 `签订时间录入后不可清空` |
| 合同非 delivering 录/改/清空 scheduledDeliveryDate | 400 `仅「交付中」状态的合同可录入/修改/清空预计交付时间` |
| 日期非 YYYY-MM-DD | 400 `合同签订时间格式须为 YYYY-MM-DD` / `预计交付时间格式须为 YYYY-MM-DD` |

行为：录 `signedDate`（合同 active）→ 写入 + 合同 **active→delivering** + 项目重算 + 操作日志「录入合同签订时间」；录 `scheduledDeliveryDate` → 日志「录入预计交付时间」（可传 null 清空，可纠正）。

### `PATCH /api/contracts/{id}/status` 状态机（ADR-019）

合同状态：`pending → active（合同签订中）→ delivering（交付中）→ delivered`，terminated 各阶段可达。

```
                 录 signedDate                交付（扣量/流水/Outbound）
  pending ──审核confirm──▶ active ──────────────▶ delivering ──────────────▶ delivered
     │                        │                      │                          │
     └────────────────────────┴─────── terminated ◀───┴──────────────────────────┘
                          （撤销交付：delivered → delivering，signedDate 仍在）
```

| 场景 | 响应 |
|---|---|
| `active → delivered`（未录签订时间） | 400 `合同尚未录入签订时间，不可交付` |
| 直接变更 `status=delivering` | 400 `「交付中」状态由录入合同签订时间自动触发，不可直接变更` |
| `delivering → delivered` | 200（交付路径：扣量/流水/Outbound 在此发生，进入 delivering 不扣量） |
| `delivered → terminated`（撤销交付） | 合同回 **delivering**（原回 active） |
| `active → terminated` | 不变（释放锁定）；`delivering → terminated` 同样释放锁定 |

项目派生（`_derive_project_status`）：全 pending→pending；全 delivered→delivered；含 terminated 且其余全 pending/terminated→terminated；**全部合同 ∈ {delivering, delivered}（全部已签）→ delivering（交付中）**；其余→active。

### 产品参考价（`POST/PUT /assets`，ADR-018 §1）

- 入参新增 `priceMin` / `priceMax`（number ≥ 0 | null，元/份，选填；只填其一 = 单边边界）。
- 两者都有时 min ≤ max，否则 **400 `参考区间下限不能大于上限`**（PUT 按「存量值 + 本次 patch」组合值校验）。
- 未设置区间 = 折扣不限制。

### 购物车金额与区间校验（`PUT /cart/{id}`、`PATCH /cart/{id}`、`POST /cart`、`/cart/batch`、`/cart/checkout`，ADR-018 §3）

- unit 模式行与遥感明细行 `amount` 放开（整数元 ≥ 0，可空）；**传入即采信（折扣）+ 区间校验；不传 = 保持原值不改（CART-PATCH-20261021 起；此前为置 NULL=原价成交），显式传 null = 清空**；amount 模式行口径不变（整数元权威，viewer 免填兜底不变）。
- 校验：`amount/qty`（保留 6 位小数）须 ∈ [priceMin, priceMax]，超限 **400 `折扣单价超出该产品参考区间（{min}~{max} 元/{unit}）`**（单边区间按单边校验，文案 `≥{min} 元/{unit}` / `≤{max} 元/{unit}`）；非整数元 400 `销售金额须为非负整数元`。
- 行更新时 + checkout 时双重校验（防绕过）。
- 服务期限：上述行级入参新增 `serviceStart` / `serviceEnd`（YYYY-MM-DD，start ≤ end 否则 400 `服务开始日期不能晚于结束日期`）。

### 下单落库（checkout / `POST /projects` / `POST /sales/order`，ADR-018 §2）

- `ProjectItem` 新增 `origPrice` / `origAmount`（下单时原价快照，**永不覆盖**）：普通行 = asset.salePrice / salePrice×qty；遥感行 = rs_items.price / 同值。`price/amount` = 最终价（折扣/终审后）。
- `ProjectItem` / 购物车行新增 `serviceStart` / `serviceEnd` 透传（手动建单不做区间校验——商务/管理员不受生态折扣约束）。

### 审核（`POST /projects/{id}/review`，ADR-018 §4 + ADR-020）

- confirm 行级入参新增 `serviceStart` / `serviceEnd`（可改服务期限，格式/顺序校验）。
- ⚠️ **删除**终审改价回写 `assets.salePrice` 的逻辑：改价只写 ProjectItem.price/amount（orig 快照不动），挂牌价仅由产品管理维护。

### `GET /api/bootstrap` 新增字段（均可空，存量数据为 null）

- `assets[]`：`priceMin` / `priceMax`（number | null，元/份）
- `cart[]`：`serviceStart` / `serviceEnd`（string 'YYYY-MM-DD' | null）
- `projects[].items[]`：`origPrice` / `origAmount`（number | null）、`serviceStart` / `serviceEnd`
- `contracts[]`：`signedDate` / `scheduledDeliveryDate`（'YYYY-MM-DD' | null）
- `contracts[].status` / 项目 `status` 新增值 `delivering`（中文「交付中」）
- viewer 过滤为行级（项目/合同/交付/流水/日志），对上述新字段无影响。

### ⚠️ `POST /api/sales/order` deprecated（ADR-020）

前端已移除「登记销售」入口，**购物车为唯一下单链路**；本端点保留兼容潜在直调方（折扣金额同样过区间校验），后续版本可能移除，请勿新增调用。

---

## 2026-10-20 变更（CLEANUP-20261020 移除「生态人员基础资料」，⚠️ 接口下线 + bootstrap 字段移除）

> 生态人员已由 `users` 表 + viewer 角色承载，`base_records`（kind='reps'）为无人消费的遗留数据，整体下线。前后端同批上线（契约见 api-contracts.md「CLEANUP-20261020 批次」）。

### `/bases/{kind}` 接口（⚠️ reps 下线）

`POST /api/bases/{kind}`、`PUT /api/bases/{kind}/{rec_id}`、`DELETE /api/bases/{kind}/{rec_id}`：

- **`kind='reps'` → 400**：`{ "detail": "该基础资料类型已下线" }`（三个方法一致）。
- `kind='suppliers'` / `kind='customers'` 行为不变（暂保留）。

实测（admin 登录）：`POST /api/bases/reps` → `400 {"detail":"该基础资料类型已下线"}`；`POST /api/bases/suppliers` → `200 {"ok":true}`。

### `GET /api/bootstrap` 响应（⚠️ 移除 `reps` 字段）

- 响应顶层**移除 `reps` 字段**（此前为 `BaseRecordOut[]`，kind='reps' 快照）。
- `suppliers` / `customers` 字段保留不变。
- 前端并行删除 `db.reps` 镜像与 `BaseKind` 中的 `'reps'`，同批上线。

实测：`GET /api/bootstrap` 响应 keys 为 `assetDeliverables / assets / cart / categoryUnits / contracts / customers / files / flows / logs / outbounds / projects / rsItems / suppliers`（**无 `reps`**；`deliverableTemplates` 已于 2026-10-21 ADR-024 下线移除）。

---

## 2026-10-20 变更（FIX-20261020 业务逻辑 13 项修复，分支 fix/business-logic-bugs-20261020，⚠️ 部分行为变更）

### 权限与 403 语义（ADR-014，FIX-20261020-#1）

- 所有写接口（POST/PUT/PATCH/DELETE）均有守卫，无裸接口：
  - `require_editor`：业务写操作（产品/项目/合同审核/交付/基础资料/上传等），admin + editor 可执行；
  - `require_order`：下单链路（购物车 7 端点、`POST /sales/order`、项目编辑/状态/重新提交、合同状态），三角色放行，归属约束在 services 层（viewer 仅自己下单的项目）；
  - `require_admin`：账号管理 / 审计查询，仅 admin。
- **viewer 越权统一返回 403**，`detail` 为可读中文提示（文案来源统一为后端，前端拦截器对 403 直接 toast `detail`，不再有前端本地"只读账号…"文案）：
  - `require_editor` 拦截：`403 { "detail": "只读账号不可执行该操作" }`
  - `require_admin` 拦截：`403 { "detail": "无权限执行此操作" }`
  - services 层归属拦截（viewer 操作非自己项目）：`403 { "detail": "生态人员仅可…自己下单的项目" }`（各端点具体文案）

### Outbound 输出（FIX-20261020-#7）

`OutboundOut` 新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `projectItemId` | `number \| null` | 所属项目明细（`ProjectItem.id`）。合同交付自动生成的交付记录非空；手动补录与存量记录为 `null`。前端不展示，仅类型定义同步 |

响应示例（`GET /bootstrap` 的 `outbounds[]` 元素、`POST /outbounds` 返回值）：

```json
{
  "id": 12, "code": "CK-0012", "projectId": 3, "contractId": 8,
  "projectItemId": 21,
  "projectName": "项目一", "customer": "客户甲", "assetId": 1, "assetName": "软件A",
  "qty": 2, "unit": "套", "amount": 200.0, "type": "physical", "mode": "new",
  "date": "2026-10-20", "operator": "biz", "status": "done", "remark": ""
}
```

### POST /api/outbounds（补录交付，ADR-015，FIX-20261020-#2/#9/#13a）

请求：`POST /api/outbounds`（守卫 `require_editor`，viewer 403）

请求体（⚠️ `operator` 字段已移除，后端不采信，操作人取登录账号）：

```json
{
  "projectId": 3, "customer": "客户甲", "assetId": 1, "qty": 2,
  "amount": 200, "type": "physical", "mode": "new", "date": "2026-10-20", "remark": ""
}
```

#### 400 场景表（本次新增，文案为契约原文）

| 场景 | detail |
|---|---|
| `qty <= 0` | 交付数量必须大于 0 |
| 项目状态为 pending 或 terminated | 该项目当前状态不可登记交付 |
| `assetId` 不在该项目明细中 | 该产品不属于所选项目 |
| `asset.type == '遥感数据'` 父产品 | 遥感容器不可直接交付，请交付其数据明细 |

既有 400 场景保持不变：产品不存在 / 项目下该产品明细已全部交付/释放（防重复）/ 交付数量超出可用数量。

#### 库存口径（ADR-015）

- 手动交付（`mode != "history"`）仅 `shippedQty += qty`（`min(quantity, …)` 夹零防御），**不再触碰 `lockedQty`**；
- 可售校验 `qty <= quantity - lockedQty - shippedQty` 基于**未改动**的 `lockedQty` 计算；
- `soldCount + 1`、`soldAmount += amount` 口径不变；`mode == "history"`（历史补录）不扣数量、不累计销售。

### GET /api/bootstrap（viewer 过滤口径补齐，FIX-20261020-#6）

admin/editor：全量（现状）。**viewer（生态人员）**：

| 数据集 | 过滤口径 |
|---|---|
| `projects` | 仅自己下单的项目（`creator == 自己`；存量 creator 为空回退 rep 判定）——既有口径 |
| `contracts` | 跟随项目可见性（`projectId ∈ 可见项目`）——既有口径 |
| `outbounds` | `projectId ∈ 可见项目` **或** `contractId ∈ 可见合同` |
| `flows` | `contractId ∈ 可见合同`，或 `ref` 指向可见编号（`SP-` 项目 / `HT-` 合同 / `CK-` 交付）；产品级流水（ref=产品编号，如登记 `purchase_in`）放行（产品目录对 viewer 全量可见） |
| `logs` | `target=project`：detail 中 `SP-` 编号 ∈ 可见项目，或 `contractId ∈ 可见合同`，或（无编号时）项目名 ∈ 可见项目名；`target=outbound`：detail 中 `CK-` 编号 ∈ 可见交付；`target=asset/setting`：放行（引用产品/基础资料，全量可见） |
| 其余（assets/rsItems/基础资料/模板/购物车/文件） | 不变（assets 等为全量可见的主数据；cart 按登录用户隔离） |

过滤原则：宁可保守过滤，不漏放跨客户信息。

### GET /api/users/options/all（viewer 过滤口径，FIX-20261020-#6）

- admin/editor：全部启用账号（现状）。
- **viewer**：仅返回本人 + 其可见项目中 `rep` / `creator` / `businessOwner` 出现过的启用账号（供「账号 → 姓名」显示映射，不暴露其他客户相关账号）。

### 建单/加购校验（FIX-20261020-#13b/#13c）

| 端点 | 场景 | 400 detail |
|---|---|---|
| `POST /projects` | 任一合同 `customer` 为空 | 请为每份销售记录填写客户 |
| `POST /cart`、`POST /cart/batch`、`POST /sales/order`、`POST /projects` | 产品 `type == '遥感数据'` 父产品（非其明细行） | 遥感数据容器不可直接购买，请购买其数据明细 |

容器明细行（`itemId` 非空，指向 `rs_items`）放行，仅拦父产品本身。

### 其他口径（FIX-20261020）

- `PATCH /contracts/{id}/status`（交付）与撤销交付：接口不变；生成的 `Outbound.operator` 统一取**触发请求的登录账号**（不再取 `project.rep`），`projectItemId` 指向被交付明细。
- `PUT /assets/{id}`：`type` 变更时后端自动重算 `pricingMode`（卫星Token → `amount`，其余 → `unit`），前端无需传 `pricingMode`。
- `rep` 字段统一存 **username**：`POST /sales/order`、`POST /projects` 的 `rep` 若传姓名，后端按用户表归一为 username（查不到则原样存）。
- `POST /projects/{id}/review`（驳回）：合同备注改为**追加**（原备注非空时 `原备注｜驳回：{reason}`），不再覆盖。

## 2026-10-19 变更（ADR-013 销售记录：一资产一条记录 + 多主体 + 文案改名，⚠️ 行为变更）

- **记录粒度**：`POST /api/cart/checkout` 与 `POST /api/sales/order` 改为**按产品分组**——每个产品一条销售记录（遥感明细行归父产品），同客户多主体产品可一单混装（原「同主体」400 校验全部移除）；手动建单 `POST /projects` 保留自由结构（不再校验同主体）。
- **主体派生**：记录 `subject` = 各行主体全一致→该值，混合→空（多主体记录，前端显示「多主体」）；项目 `customer/subject` 多记录但全一致时仍取该值（不再误显「N 位客户」）。
- **文案**：用户可见字符串「合同」→「销售记录」、「合同金额」→「销售金额」（报错/日志/审计动作）；代码/表名/路由/`HT-` 编号不变。详见 `docs/adr/ADR-013.md`。

## 2026-10-19 变更（ADR-012 §5.1 商务接手机制，⚠️ review 接口权限收紧）

- **新端点 `POST /api/projects/{id}/claim`**（`require_editor`）：商务接手/转交——`businessOwner` 绑定接手账号（username）；pending 无主→接手、他人负责→转交；active 仅转交；终态 400。
- **新端点 `GET /api/users/options`**（任意登录）：editor/admin 有效账号列表，供商务负责人筛选与 username→姓名 映射（商务负责人与角色账号的关联查询）。
- `POST /projects/{id}/review` **权限收紧**：`businessOwner` 为空 → 400「尚未被商务接手」；操作人 ≠ businessOwner 且非 admin → 400「仅接手的商务负责人可调整该订单价格」；admin 可越过任意单（审计留痕实际操作人）。

## 2026-10-19 变更（ADR-012 生态人员下单「待审核」流程，⚠️ 新增状态 + 新端点）

- `projects.status` / `contracts.status` 新增 `pending`（待审核，无 schema 迁移）：**仅 viewer 购物车结算**产生（锁定照常）；商务/管理员所有建单入口不变。
- **新端点 `POST /api/projects/{id}/review`**（`require_editor`）：confirm=确认下单（可带行级改价，**实际价写回平台挂牌价**）/ reject=驳回（释放锁定+原因留痕）。详见下方该端点小节。
- `POST /api/cart/checkout` 角色分叉：viewer 进 pending + amount 模式金额可免填（回退挂牌价×数量取整）；editor/admin 不变。
- 守卫：pending 项目/合同对 `PATCH /projects/{id}/status`、`PATCH /contracts/{id}/status` 一律 400（唯一出口=审核接口）；项目删除/产品删除把 pending 视同 active（锁定需释放/引用拦截）。

## 2026-10-19 变更（交付记录「撤销」联动回滚合同/项目状态，⚠️ 行为变更）

- `POST /api/outbounds/{id}/revert` 撤销**合同交付**生成的记录后：明细 `shipped→locked`（真锁过的重新加锁）+ 合同 `delivered→active` + 项目状态重算——修复「撤销交付后销售项目详情页状态不变」的问题。详见下方该端点小节。

## 2026-10-19 变更（对外术语切换「资产/库存 → 产品及服务」，纯文案）

- 全部**用户可见文案**按 `docs/asset-inventory-rename-checklist-20261019.md` 切换：接口报错、操作/审计日志动作与明细、字段级 diff 映射、种子数据（资产→产品；库存按语义 → 可用数量/数量/可售/已售罄）。
- **不变**：API 路径、字段名（assetId 等）、英文枚举（`asset_change`/`in_stock`）、表名/列名、状态机与权限逻辑。本文档下文各小节的报错示例已同步为新口径。

## 2026-10-16 变更（销售项目对生态人员 viewer 开放「仅自己下单」，⚠️ 权限放宽）

- **`projects.creator` 新列**（VARCHAR(64) 默认 `''`，索引）：实际登录下单的 username。三个建单入口（`POST /projects`、`POST /sales/order`、`POST /cart/checkout`）自动写入 `operator`；存量项目为空。
- **`GET /api/bootstrap`（出参过滤，⚠️）**：viewer 的 `projects[]`/`contracts[]` 仅返回**自己下单**的项目及跟随合同——`creator == 自己 username`，creator 为空（存量）回退 `rep in (自己姓名, 自己 username)`；admin/editor 全量。前端项目列表/详情/产品「销售关联」均消费此镜像；viewer 经 URL 访问他人项目 → 镜像无此项目 → 前端空态。
- **`PUT /api/projects/{id}`（依赖 `require_editor` → `require_order`）**：~~viewer 可编辑**自己下单**的项目基本信息；`rep` 字段对 viewer 恒忽略；非自己项目 → 403 `生态人员仅可编辑自己下单的项目`~~ ⚠️ **已由 EDITLOCK-20261021（ADR-028，2026-10-21）收回**：viewer 一律 403 `订单已提交，不可编辑；如需修改请「撤销」后重新下单`，`rep` 特判随之删除（详见文首该批次章节）。
- **`PATCH /api/projects/{id}/status`（同上）**：viewer 仅可 `terminated`（自己项目）；`delivered` → 400 `生态人员仅可终止项目（交付需商务人员/管理员操作）`。
- **`PATCH /api/contracts/{id}/status`（同上）**：viewer 仅可 `terminated`（自己项目合同，含 delivered 撤销交付）；`delivered` → 400 `生态人员仅可终止合同（交付需商务人员/管理员操作）`；非自己项目 → 403。
- **不变**：`POST /projects`（新建空项目）、`DELETE /projects/{id}`、交付/交付物/基础资料等仍 `require_editor`；下单链路三入口本就 `require_order`。

## 2026-10-16 变更（ADR-011 遥感数据「父产品 + 可售明细」两层模型，⚠️ Supersedes ADR-010）

### 遥感数据模型概览

- 产品列表里是 **1 个父产品**（`type='遥感数据'`，容器，本身不可直接加购/下单，`quantity/lockedQty/shippedQty` 仅承载明细 repeatSale=false 的锁定/交付口径）；
- 真正售卖单位 = **`rs_items` 明细**（省/市 × 精度 × 月份，每份一个整数元单价，默认 repeatSale=true 只计次不扣量）；
- **⚠️ ADR-010 产品三维字段全部移除**：`AssetOut` 不再输出 `province/city/resolution/imageDate`；`AssetInput` 不再接受（前端多传被 Pydantic 静默忽略）；`POST /assets`、`PUT /assets/{id}` 的三维必填/判重 400 文案作废。遥感数据按普通父产品登记。

### 新增端点（写均 admin+editor `require_editor`，读随 bootstrap 放行）

#### POST /api/assets/{asset_id}/rs-items

请求：`POST /api/assets/29/rs-items`，body `RsItemInput`：
```json
{"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000,"repeatSale":true}
```
- `province` 必填（空 400）；`city` 默认 `""`；`resolution` > 0（否则 422）；`saleMonth` 须匹配 `^\d{4}-\d{2}$`（否则 422）；`price` 整数元 > 0（否则 400）；`repeatSale` 默认 `true`。
- 父产品必须存在（404 `产品不存在`）且 `type='遥感数据'`（否则 400）。

响应（200，`RsItemOut`）：
```json
{"id":1,"assetId":29,"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000.0,"repeatSale":true,"createdAt":"2026-10-16 11:41","updatedAt":"2026-10-16 11:41"}
```

#### PUT /api/rs-items/{item_id}

请求：`PUT /api/rs-items/1`，body 同 `RsItemInput`（全字段可改，含 `price`/`repeatSale`）。唯一性判重**排除自身**。
响应（200）：更新后的 `RsItemOut`。错误：404 `遥感数据明细不存在` / 404 `明细所属父产品不存在`。

#### DELETE /api/rs-items/{item_id}

请求：`DELETE /api/rs-items/1` → 200 `{"ok":true}`
- 任一 `project_items.itemId` 或 `cart_items.itemId` 引用该明细（含已完成/已终止合同）→ 400。
- 删除成功写 OpLog（`target='asset'`，关联父产品 id，action=`删除可售明细`）。

审计：新增/编辑/删除明细均写 audit_logs（`actionType=asset_change`，`target=asset`，`targetName`=父产品名，`detail=rsItemId=N`）。

### bootstrap 出参新增

| 字段 | 位置 | 说明 |
|------|------|------|
| `rsItems` | bootstrap 顶层（**新增**） | `RsItemOut[]` **全量**（前端 RsItemPicker / 产品详情「可售明细」页签消费） |
| `itemId` | `cart[]`（新增，nullable） | 购物车行挂的明细 id；非空行 `qty` 恒 1；存量/非遥感行 `null` |
| `itemId` | `projects[].items[]` / `contracts[].items[]`（新增，nullable） | 项目/合同明细行挂的明细 id；存量行 `null` |
| ~~`province`/`city`/`resolution`/`imageDate`~~ | `assets[]`（**移除 ⚠️**） | ADR-010 三维字段出参移除（列保留不删） |

### 购物车（含 itemId 行）

- `POST /api/cart`、`POST /api/cart/batch`（`CartItemInput`）新增可选 `itemId`：
  - 校验明细存在且其 `assetId` == 传入 `assetId`（否则 400；batch 路径跳过该行并记 skipped）；
  - **qty 恒 1**（传 ≠1 → 400；batch 路径强制 1）；
  - 判重键升级为 **(userId, assetId, itemId, customer)**——同键重复加购**幂等合并（qty 保持 1，不累加）**；无 itemId 行口径完全不变（`itemId IS NULL` 才与无明细行合并）；
  - 数量：明细 `repeatSale=true` 不占数量；`false` 按父产品可售（该产品全部行合计）校验。
- `PUT /api/cart/{id}`：含 itemId 的行 qty≠1 → 400（前端本就不允许改；删除走 `DELETE /cart/{id}`）。
- `PATCH /api/cart/{id}`（改客户）：判重同样带 itemId（明细行与无明细行互不冲突）。
- `CartItemOut` 新增 `itemId: int | null`。

### 销售链路（含 itemId 行，三条入口全覆盖）

`POST /api/projects`（`ProjectItemInput`）、`POST /api/sales/order`（`SaleOrderItemInput`）、`POST /api/cart/checkout`（购物车行）均支持 `itemId`：

- 含 itemId 的明细行：**`amount` 后端权威 = `rs_items.price × 1`**（Decimal 重算，**忽略前端传值**，整数元天然成立）；`qty` 强制 1（≠1 → 400）；
- 明细 `repeatSale=true` → 跳过数量锁定（走现有 repeatSale 分支，只计次）；`false` → 按现有 lockedQty 逻辑锁**父产品**（qty=1），交付扣 `shippedQty`、终止/撤销对称回退（含 `locked` 标记与交付撤销回退，全部明细感知）；
- `project_items.itemId` 落库；`ProjectItemOut` / 合同 items 输出 `itemId: int | null`；
- 明细不存在或不属于该产品 → 400（checkout 场景：`购物车中的遥感数据明细已删除或不属于该产品，请先移除后再下单`）。

### 400 文案表（ADR-011 新增）

| 场景 | 文案 |
|------|------|
| 非遥感产品维护明细 | `仅遥感数据产品可维护可售明细` |
| 明细省为空 | `遥感数据明细必须填写省份` |
| 明细单价非整数元/≤0 | `遥感数据明细单价须为整数元且大于 0` |
| 同父产品 省/市+精度+月份 重复（create / update 排除自身） | `该父产品下已存在相同 省/市 + 精度 + 月份 的明细` |
| 明细被项目/购物车引用时删除 | `该明细存在销售关联，无法删除` |
| 购物车/下单 明细行 qty≠1 | `遥感数据明细行数量固定为 1` |
| 购物车/下单 明细不存在或归属不符 | `遥感数据明细不存在或不属于该产品` |
| checkout 明细行失效 | `购物车中的遥感数据明细已删除或不属于该产品，请先移除后再下单` |

### 实测（curl）

```
POST /api/assets {"type":"遥感数据","name":"遥感数据-2026",...} → 200（AssetOut 无 province 等 4 字段）
POST /api/assets/29/rs-items ×2（河北石家庄 1.5m 2026-09 330000 / 甘肃 1m 2026-10 280000）→ 200；同组合再建 → 400「该父产品下已存在相同 省/市 + 精度 + 月份 的明细」
bootstrap.rsItems → 2 条；加购 itemId 行 qty=1 → 200、qty=2 → 400「遥感数据明细行数量固定为 1」、重复加购合并 qty 仍 1
POST /api/sales/order items=[{"assetId":29,"qty":1,"amount":999,"itemId":1}] → item.amount=330000.0（999 被忽略）、itemId=1、locked=false
交付合同 → soldCount+1/soldAmount+330000、无锁定动作；终止 → 全回退
repeatSale=false 明细下单 → 父产品 lockedQty+1（locked=true）；交付 → shippedQty+1；终止 delivered → 全回退
有引用 DELETE /rs-items/{id} → 400「该明细存在销售关联，无法删除」；无引用 → 200
回归：unit 下单（amount 重算）、卫星Token amount 模式下单、普通购物车结算 均正常
```

---

## 2026-10-16 变更（ADR-008 包量定价 / ADR-009 购物车按登录用户隔离 / ADR-010 遥感数据）

> ⚠️ 本节 **ADR-010 部分已被 ADR-011 取代**（产品三维入出参/判重/默认值全部移除，见上方 ADR-011 章节）；ADR-008/ADR-009 部分仍有效。

### 产品入出参（POST /api/assets、PUT /api/assets/{id}、bootstrap assets[]）

- `AssetOut` 新增：`pricingMode`（`unit`/`amount`，**后端按类型权威决定**：`type='卫星Token'` → `amount`，其余恒 `unit`）、`province`/`city`/`resolution`（精度，单位米）/`imageDate`（非遥感类型恒 `""`/`null`）。
- `AssetInput` 新增可选：`province`、`city`、`resolution`、`imageDate`。`type='遥感数据'` 时 省/精度/日期 必填（市可空，省级产品不填）；非遥感类型忽略/置空。**不接受 `pricingMode` 入参**（后端按类型决定，多传被忽略）。
- 遥感数据登记默认值（后端兜底）：`quantity` 0→1、`unit` 空→`份（区域·精度·日期）`；`repeatSale` 由前端传（默认 True，允许关闭）。
- 400 文案：

| 场景 | 文案 |
|------|------|
| 遥感数据缺 省/精度/日期 | `遥感数据产品必须填写 省、精度、影像日期` |
| 三维组合重复（create / update 排除自身） | `已存在相同 省/市 + 精度 + 日期 的遥感数据产品` |

实测（curl）：
```
POST /api/assets {"type":"遥感数据","province":"河北省","city":"石家庄市","resolution":1.5,"imageDate":"2026-09-15",...} → 200
  {"id":29,"code":"CH-SAT-029","pricingMode":"unit","province":"河北省","city":"石家庄市","resolution":1.5,"imageDate":"2026-09-15","quantity":1,"repeatSale":true,"unit":"份（区域·精度·日期）"}
同组合再建 → 400 {"detail":"已存在相同 省/市 + 精度 + 日期 的遥感数据产品"}
改 imageDate 后建 → 200（不冲突）
```

### 销售明细计价分支（POST /api/projects、POST /api/sales/order、POST /api/cart/checkout）

- 产品 `pricingMode='amount'` 时：
  - `POST /projects` 明细 `amount` 为**权威输入**（整数元且 >0，否则 400），**跳过** `price×qty` 权威重算；`price = round(amount/qty, 6)` 仅作派生展示值落库；合同/项目金额 = Σ 权威 amount。
  - `POST /sales/order` `items[]` 新增可选 `amount`（元，整数）：amount 模式产品**必填**（缺失/非整数 400）；unit 模式忽略。
  - `POST /cart/checkout`：amount 模式购物车行 `amount` 必填（缺失 400）。
- `pricingMode='unit'` 时行为**完全不变**（`amount = price×qty` Decimal 权威重算，前端传值忽略）。
- 400 文案：`包量计价产品的销售金额须为整数元`

实测（curl）：
```
POST /api/sales/order {"items":[{"assetId":6,"qty":1,"amount":10000000}]}（asset6=卫星Token，amount 模式）
  → 200，item: {"qty":1,"price":10000000.0,"amount":10000000.0,"status":"locked"}，expectedAmount=10000000.0
amount=10000000.5 → 400 {"detail":"包量计价产品的销售金额须为整数元"}；不传 amount → 400 同文案
unit 模式回归：{"assetId":16,"qty":2,"price":26800,"amount":99999} → item.amount=53600.0（重算，忽略 99999）
```

### 购物车（⚠️ 按登录用户隔离 + 行级 amount）

- **按登录用户隔离（ADR-009）**：全部 7 端点（`POST /cart`、`POST /cart/batch`、`PUT/PATCH/DELETE /cart/{id}`、`DELETE /cart`、`POST /cart/checkout`）以 `get_current_user` 的 `user.id` 为桶；`bootstrap.cart` 仅返回当前用户行；A 结算不清空 B 的行。判重 (userId, assetId, customer) 与数量校验规则不变。
- 行级 `amount`（ADR-008，元，整数，可选）：
  - `CartItemInput`（POST /cart、POST /cart/batch items[]）、`PUT /cart/{id}`（body 可选 `amount`）、`PATCH /cart/{id}` 均接受；
  - amount 模式产品行：传入时校验整数元（非整数 400 `包量计价产品的销售金额须为整数元`）后落库；**结算时必填**（缺失 400 同文案）；
  - unit 模式行：忽略（不采信、不落库，`CartItemOut.amount` 恒 `null`）。
- `CartItemOut` 新增 `amount`（float|null）。

实测（curl）：
```
editor(id=3) 加购 asset16 → bootstrap(editor).cart 仅 1 行；viewer(id=4) 加购 asset17 → bootstrap(viewer).cart 仅自己 1 行
viewer checkout → 200（生成项目+合同），viewer 购物车清空，editor 行不受影响
viewer：POST /cart/batch 200、DELETE /cart 清空 200（require_order 放行）
admin 加购卫星Token 行（不带 amount）→ checkout 400「包量计价产品的销售金额须为整数元」
PUT /cart/{id} {"qty":1,"amount":5000000} → checkout 200，item.amount=5000000.0（price 派生同值）
unit 模式行 PUT 传 amount=12345 → 忽略，行 amount 仍为 null
```

---

## 业务逻辑审计 6 项修复（2026-10-15，行为收紧）

### POST /api/outbounds（FIX-1 新增可售校验）

请求：`POST /api/outbounds`，body 同既有（`assetId/qty/amount/type/mode/date/projectId?/customer?/operator?/remark?`）
> 注（2026-10-20 FIX-20261020）：`operator` 字段已从 `OutboundInput` 移除（后端不采信，操作人取登录账号）；新增 4 个 400 场景与库存口径（不再触碰 `lockedQty`）见文首「2026-10-20 变更」节。
新增校验：`mode != "history"` 且产品**非 repeatSale** 时，`qty > quantity - lockedQty - shippedQty`（按当前库值）→ 400。
`mode = "history"`（历史补录，不扣数量）与 repeatSale 产品跳过校验。

响应（超量）：
```json
{"detail": "交付数量超出可用数量：FIX1-非重复 可售 2套，本次交付 5套"}
```
关键字段：无（400 detail 文案）；通过时响应同既有 `OutboundOut`

### DELETE /api/projects/{project_id}（FIX-2 回滚范围扩大）

删除项目除既有级联（active 合同释放锁定、delivered 合同撤销名下 done 交付）外，**同时撤销 `projectId == 项目id 且 contractId == null 且 status='done'` 的手动交付**（写「交付撤销」OpLog + manual_adjust 回退流水 + 回退 shippedQty/soldCount/soldAmount）。与前端删除确认文案「撤销该项目已生成的交付记录」对齐。
注意：**项目终止（PATCH status=terminated）不做**此回滚——终止≠删除，手动交付是独立动作。

### POST /api/outbounds/{outbound_id}/revert（交付撤销；2026-10-19 起联动回滚合同状态）

**数量回退**（历史补录 `mode=history` 不调数量）：非 repeatSale（合同明细行以 rs_items 为权威）`shippedQty -= qty`；`soldCount -1`（口径统一后创建侧一律 +1，撤销一律 -1）；`soldAmount -= amount`；生成负数调整流水。

**合同联动（2026-10-19 新增，`services._revert_outbound_inner(restore_contract=True)`）**：当撤销的是**合同交付**生成的记录（`contractId != null`）且对应明细仍为 `shipped` 时：
- 明细回滚：`status shipped→locked`、`shippedDate` 清空；下单时真实加锁过（`locked=True`）的明细**重新加锁**（`lockedQty += qty`，project_lock 流水）；
- 合同回滚：`delivered→active`（`updatedAt` 更新），项目状态随 `_recompute_project` 重算（销售项目详情页同步恢复「进行中」）；
- 操作日志追加「关联合同已回退「进行中」并重新锁定明细」。
- **再交付安全**：合同交付分支只处理 `locked/confirmed` 明细（跳过 `shipped`），重新交付时仅补交被撤销的明细，不重复扣量；
- **批量级联例外**：合同终止 / 项目终止 / 项目删除内部级联撤销均传 `restore_contract=False`（最终状态由调用方统一决定，避免把本应释放的数量错误重新加锁）；
- 手动交付（`contractId == null`）/ 历史补录不受合同联动影响（行为同旧版）。

### DELETE /api/assets/{asset_id}（FIX-4 合同感知口径）

引用拦截拆为两条（done 交付拦截保持）：
- 合同明细（contractId 非空）：仅当存在 **`status='active'`** 合同引用 → 400；delivered/terminated 合同引用放行；
- 无合同 legacy 项目明细：保持原规则（项目 status != terminated → 400）。

响应（active 合同引用）：
```json
{"detail": "该产品仍被进行中的合同 HT-0005（客户 C1）引用，请先终止该合同后再删除"}
```

### PUT /api/projects/{project_id}（FIX-6a 新增终止拦截）

项目派生状态为 `terminated`（全合同终止/混合 delivered+terminated；legacy terminated）→ 400（先于既有「存在 delivered 合同不可编辑」判断）：
```json
{"detail": "项目已终止，不可编辑"}
```

### PUT /api/cart/{cart_id}（FIX-6b 行级合计校验）

数量上限从「本行 qty ≤ 可售」升级为「该产品在购物车**全部行合计**（本次修改后）≤ 可售」（repeatSale 跳过；`POST /cart`、`POST /cart/batch` 已是同口径）：
```json
{"detail": "购物车中 FIX6-购物车 合计 3 超出可售 2"}
```

FORMS-20261022（ADR-037 §3）：行金额参考区间校验**分角色**——viewer 仅校验下限（`amount < priceMin` → 400 原文案；`amount > priceMax` 允许），editor/admin 双向不变；遥感明细行走明细自身区间（ADR-021）同口径；viewer 行历史 `discountRate` 忽略（不 400、不参与计算）。与 `PATCH /cart/{id}`、`POST /cart/checkout` 复用同一校验函数（详见文首 FORMS-20261022 章节）。

### OpLog operator 真实化（FIX-5，出参语义变更）

`bootstrap.logs[].operator` 不再恒为 `"admin"`：合同交付/终止、项目新增/编辑/状态变更/删除、交付创建/撤销、产品新增/编辑/删除等写路径记录**实际登录用户名**（如 `editor`）。基础资料/交付物模板/产品交付物增删改仍为默认 `"admin"`（未透传）。

---

## 合同层级（ADR-007，2026-10-15，⚠️ Breaking）

### 数据模型概览

- 新增 `contracts` 表：项目下按客户拆分的合同，**数量联动的最小单位**。合同内强制同一产品主体；合同一经生成不可增删改明细（终止再重下）。
- 项目 `status` 为**派生字段**：无合同→active；有 active→active；全 delivered→delivered；全 terminated→terminated；混合 delivered+terminated（无 active）→terminated。
- 项目 `expectedAmount`（及兼容口径 `contractAmount`）=Σ合同 contractAmount；`customer`/`subject`：多合同=空字符串（前端显示「N 位客户」）、单合同=该合同值。
- 金额单位=**元**（Decimal 计算，ADR-006）。

### ContractOut 结构（bootstrap.contracts / 合同展示）

```json
{
  "id": 1, "code": "HT-0001", "projectId": 1,
  "customer": "甲", "subject": "S1",
  "contractAmount": 150.0, "status": "active", "remark": "",
  "items": [
    {"id":1,"assetId":29,"contractId":1,"qty":1,"unit":"台","price":100.0,"amount":100.0,
     "status":"locked","deliveryReq":"","locked":true,"lockedDate":"2026-10-15","confirmedDate":"","shippedDate":""}
  ],
  "createdAt": "2026-10-15", "updatedAt": "2026-10-15"
}
```
关键字段：`code`（HT-{16位时间戳}，2026-10-19 起）、`status`（active/delivered/terminated）、`items[].contractId`（明细挂合同，存量明细为 null）、`items[].locked`（下单时刻是否真实加锁）。

### PATCH /api/contracts/{contract_id}/status（新增，admin+editor；2026-10-16 起 viewer 仅可终止自己项目合同）

请求：`PATCH /api/contracts/1/status`，body `{"status":"delivered","reason":"..."}`
响应（200）：`{"ok":true}`
行为：
- `delivered`：逐明细交付——释放锁定（仅 `it.locked`）、非 repeatSale 扣 `shippedQty`、`soldCount`/`soldAmount` 均累计、**每明细生成交付记录**（`contractId`=合同 id，备注「合同「HT-xxxx」交付完成自动生成」）；
- `terminated`：active 合同→释放锁定（cancel_release 流水带 contractId）；delivered 合同→撤销该合同名下 `done` 交付（reverted）+ 回退 shippedQty/soldCount/soldAmount（负数流水）；
- 每次动作后重算项目派生字段（status/expectedAmount/customer/subject）+ OpLog（action 含合同 code）。
错误：404 `合同不存在`；400 `不支持的合同状态：X` / `合同已终止，不可再变更状态` / `已交付完成的合同不可回退到进行中`。
审计：`变更合同状态 | HT-xxxx | status=...`（target=contract）。
合同生命周期：`POST /projects`（contracts 入参）或 `POST /cart/checkout` 生成；**无独立创建/删除端点**，删除随 `DELETE /projects/{id}` 级联。

### POST /api/projects（入参新增 `contracts`，⚠️ 两种入参都支持）

```
POST /api/projects
{
  "name":"...","customer":"...","industry":"...","rep":"...","businessOwner":"",
  "subject":"","expectedAmount":0,"quoteAmount":0,"contractAmount":0,"paidAmount":0,
  "expectedSignDate":"2026-10-15","lastFollowDate":"2026-10-15","remark":"",
  "contracts":[
    {"customer":"甲","items":[{"assetId":1,"qty":1,"price":100,"deliveryReq":""}],
     "contractAmount":null,"remark":"合同甲"},
    {"customer":"乙","items":[{"assetId":2,"qty":1,"price":30,"deliveryReq":""}],
     "contractAmount":30,"remark":""}
  ]
}
```
- `contracts`（可选）：每客户一份**销售记录**（ADR-013：可含多主体产品明细，不再校验同主体）；`customer` 必填；`contractAmount` 缺省=该组明细 amount 合计（Decimal 重算）。
- **向后兼容**：不传 `contracts` 仍传 `items` → 按**单条记录**自动包装，customer 取项目 `customer` 字段。`items` 现为可选字段（`default=[]`）。
- ADR-013：记录主体派生 = 各行主体全一致→该值，混合→空（多主体记录）；数量按 assetId **跨记录聚合**校验（超量 400 `可用数量不足：...`）。
- 项目 `subject`/`customer`/`expectedAmount` 由销售记录派生（请求体同名值不再采信）；`status` 恒为 `active`。
响应（200，`ProjectOut`）：新增 `contractCount`（int）；`items[].contractId` 非空。

### PUT /api/projects/{project_id}（⚠️ 收窄为基本信息编辑）

仅接受项目基本信息：`name`/`industry`/`rep`/`remark`/`expectedSignDate`/`lastFollowDate`/`quoteAmount`/`paidAmount`。
**不再接受 items/contracts 变更**（收到即忽略——销售记录结构编辑本次不做，终止再重下）；`customer`/`subject`/`expectedAmount`/`contractAmount` 为派生字段，传入不采信；**`businessOwner` 传入一律忽略（ADR-012 §5.1：唯一写入口是 claim 接手/转交接口，防越权重设负责人）**。
编辑约束：**存在 delivered 合同 → 400 `已交付完成的项目不可编辑`**（存量无合同项目沿用 `status!=active` 旧规则）。
权限（⚠️ ADR-028 / EDITLOCK-20261021，2026-10-21 起）：`require_order`；**`role=viewer` 一律 403** `订单已提交，不可编辑；如需修改请「撤销」后重新下单`（不看状态与归属，含自己下单的 pending 单；404 项目不存在优先于 403）。~~viewer 仅自己下单项目、`rep` 入参对 viewer 忽略~~（已随编辑权收回删除）。
**pending 守卫（ADR-012 §5.1，2026-10-19）**：待审核项目基本信息仅**负责人（或 admin 越过）**可编辑 → 非负责人 editor PUT → 400 `待审核项目仅商务负责人（或管理员）可编辑基本信息`（ADR-028 起 viewer 已被上面 403 拦下，该校验实际只对商务生效）。

### PATCH /api/projects/{project_id}/status（⚠️ 批量快捷语义）

请求：`{"status":"delivered","reason":"..."}` → 200 `{"ok":true}`
- 行为改为：对名下全部 **active** 合同批量执行该状态动作（delivered=全部交付、terminated=全部终止）。前端主入口用合同级 `PATCH /contracts/{id}/status`，本接口作为批量快捷保留。
- `status=active` → 400 `项目状态由合同状态派生，仅支持批量 delivered/terminated（active 请直接变更合同状态）`；无 active 合同 → 400 `项目下没有进行中的合同，无可批量执行`。
- 存量无合同项目：走旧的项目级明细逻辑（行为不变）。
- 权限（2026-10-16）：`require_order`；viewer 仅自己项目 + 仅 `terminated`（`delivered` → 400）。
- **ADR-012（2026-10-19）**：`pending`（待审核）项目 → 400 `待审核项目不可直接变更状态，请通过订单审核（确认下单/驳回）操作`。

### POST /api/projects/{project_id}/review（ADR-012 订单审核，2026-10-19 新增）

订单审核唯一入口（仅 `pending` 项目；权限 `require_editor`，viewer → 403）。
请求：
```json
{"action":"confirm","items":[{"itemId":12,"price":888888},{"itemId":15,"amount":50000}]}
{"action":"reject","reason":"单价需重新询价"}
```
- `itemId` = `project_items.id`（行 id，非产品 id）；`items` 可省略（不改价直接确认）。
- **confirm（确认下单，可带改价）**：unit 行传 `price`（实际单价 >0，amount=price×qty 重算）；amount 行传 `amount`（整数元 >0，price 派生反算）；遥感明细行（含 itemId 的明细）传改价 → 400 `遥感数据明细行不接受审核改价（请在产品「可售明细」中维护明细单价）`；**数量不可改**。
  - **写回平台**：改价行按 assetId 回写 `assets.salePrice`（unit=实际单价、amount=派生单价 amount÷qty；同产品多行最后遍历到的行生效），并写产品「挂牌价更新」日志——平台各展示位单价同步为最近成交价（ADR-012 §3）。
  - 确认后存在 `amount<=0` 行 → 400 `存在未定价明细，请先填写单价/销售金额`。
  - 销售记录 `pending→active`、项目派生 → `active`；记录 `contractAmount` 重算 = Σ行，项目 `expectedAmount/contractAmount` = Σ记录。
- **reject（驳回）**：`reason` 必填（空 → 400）；逐明细释放锁定（仅 `it.locked`，cancel_release 流水带 contractId）；合同 `pending→terminated` 且 `remark="驳回：{reason}"` 留痕；项目 → `terminated`。
- 日志：操作日志「确认下单（含改价 diff）/ 驳回订单」+ 审计日志（`actionType=sale`）。
- 守卫：非 pending 项目 → 400 `仅待审核项目可审核（确认下单/驳回）`；**接手人守卫（§5.1）**：`businessOwner` 为空 → 400 `该订单尚未被商务接手，请先接手后再操作`；操作人 ≠ `businessOwner` 且非 admin → 400 `仅接手的商务负责人（X）可调整该订单价格，如需处理请先转交`；admin 可越过任意单（审计留痕实际操作人）。

### POST /api/projects/{project_id}/claim（商务接手/转交，ADR-012 §5.1 **纯移交制**）

请求：可选 body `{"newOwner":"账号"}`（缺省 `""`）→ 200 `{"ok":true}`（权限 `require_editor`）。
- **无负责人**（pending/active 均可）：任意商务/管理员 → **接手**（绑定操作人 username）；
- **已有负责人（移交）**：仅**当前负责人本人**可转交——body 必传 `newOwner`（缺省 → 400 `请指定转交的目标商务账号`；=自己 → 400 `转交目标不能是自己`）；目标校验 → 400 `「X」不是可用的商务账号，请重新选择`（须存在/启用/editor+admin 角色）；
- **admin 越过**：他人单据可不传 `newOwner` 直接接手给自己，或传 `newOwner` 转交给任意账号；
- **非负责人的普通商务 → 400** `该订单由商务负责人「X」负责，仅其本人可转交（如需介入请联系 admin 处理）`（原「拉取式抢单」已废除）；
- `delivered`/`terminated` 终态 → 400 `该订单已完成/已终止，不可接手或转交`；
- 不改变数量/锁定/记录状态，仅改 `businessOwner`；操作日志「接手订单 / 转交订单（X → Y）」+ 审计。

### GET /api/users/options（商务账号选项，ADR-012 §5.1，2026-10-19 新增）

任意登录用户 → 200 `UserOut[]`：`role ∈ (editor, admin)` 且 `enabled=true` 的账号，按 id 升序。供前端「商务负责人」筛选下拉与 username→姓名 展示映射；存量自由文本 businessOwner 对不上账号时前端原样展示并归「未指派/历史数据」筛选档。

### 购物车（⚠️ 跨主体 + 行级客户）

- `POST /api/cart`：body `{"assetId":1,"qty":1,"customer":"甲"}`（`customer` 新增，可选默认 `""`）。**同主体限制已删除**（跨主体加购成功）。
- `POST /api/cart/batch`：`items[]` 每行可带 `customer`。
- **唯一键语义：(userId, assetId, customer) 相同才合并**（不同 customer 同产品 = 两行）；数量上限按该产品**全部行合计**校验。
- **新增 `PATCH /api/cart/{id}`**：body `{"customer":"庚"}` 改行级客户；目标 (userId,assetId,customer) 已有其它行 → 400 `购物车中该产品在客户「X」下已有行，无法修改客户（请先删除原行）`。
- `CartItemOut` 新增 `customer`（默认 `""`）。

### POST /api/cart/checkout（⚠️ ADR-013 起按产品拆销售记录）

请求：`{"projectName":"...","rep":"...","businessOwner":"..."}`（`projectName` 可空，缺省「销售项目-日期」；`customer` 字段兼容保留，**不参与分组**；`businessOwner` 商务负责人，可选，默认 `""`）。
行为（ADR-013）：按购物车**产品（assetId）**分组（遥感明细行归父产品）→ **每个产品一条销售记录**（code HT-xxxx、customer=该行行级客户、subject=产品主体、contractAmount=该记录明细合计）→ 建项目（active+锁定）→ 清空购物车，**全部单事务**。不自动交付。**同客户多主体产品可一单混装**（各产品各自成记录，不再校验同主体）。

**ADR-012 修订（2026-10-19）：所有角色结算统一建 `pending`**（待审核，锁定照常）——原「仅 viewer 结算进 pending、商务/管理员立即 active」的角色分叉废除；商务/管理员需「接手 → 审核（改价确认/驳回）」后生效。**⚠️ ADR-022（2026-10-24）：viewer 金额免填已作废**——「留空回退 `round(挂牌价×数量)`」兜底删除，所有行类型销售金额必填（整数元 > 0），逐行必填校验（客户/金额/普通行服务期限）见文首 REQUIRED-20261024 章节。
**同规则适用于全部建单入口**：`POST /api/sales/order`（直接下单）与 `POST /api/projects`（手动建单/草稿）一律建 `pending`（`_create_project_core` 默认 `initial_status="pending"`）。
错误（400，ADR-022 起逐行必填缺项一次报全）：
```json
{"detail":"购物车存在必填缺项，请补齐后再结算：{产品名}：客户；{产品名}：销售金额（整数元，大于 0）；{产品名}：服务期限（开始/结束日期均必填）"}
```
响应（200，`ProjectOut`）：`contractCount`=产品记录数、`customer` 多客户为空串（同客户多记录仍取该客户，ADR-013）、`expectedAmount`=Σ记录。

**直接下单 `POST /api/sales/order` 同规则（ADR-013）**：不再校验同主体（原 400 `下单产品必须属于同一主体，请拆分下单` 已移除）；`items[]` 按产品分组拆为多条销售记录（同 customer=项目客户），遥感明细行归父产品。

### bootstrap / 出参变更（2026-10-15）

| 字段 | 位置 | 说明 |
|------|------|------|
| `contracts` | bootstrap 顶层（**新增**） | `ContractOut[]` 全量（含 items 挂 contractId） |
| `contractCount` | `projects[]`（新增） | int，合同数量（派生） |
| `contractId` | `projects[].items[]` / `outbounds[]` / `flows[]` / `logs[]`（新增，nullable） | 关联合同 id；存量数据为 `null` |
| `customer` | `cart[]`（新增，默认 `""`） | 购物车行级客户 |

### DELETE /api/projects/{project_id}（⚠️ 合同级联）

active 合同释放锁定、delivered 合同撤销名下 done 交付并回退 shippedQty/soldCount/soldAmount → 硬删项目及其合同、明细。存量无合同项目沿用旧回滚逻辑。

⚠️ **ADR-028（2026-10-21）新增留痕护栏**：`status == "terminated" and cartRefilled` → 403 `该订单已撤销（或已回填购物车）并将保留历史记录，不可删除`（校验在任何写操作之前）；被驳回且从未回填的终态项目仍可删除，无绕过接口。

### 400 错误文案清单（ADR-007 新增/变更）

| 场景 | 文案 |
|------|------|
| checkout 空客户行 | ~~`请为每件产品填写客户`~~ → ADR-022（2026-10-24）起并入逐行必填缺项一次报全：`购物车存在必填缺项，请补齐后再结算：{产品名}：客户`（见文首 REQUIRED-20261024 章节） |
| ~~checkout/sales/order 同主体校验~~ | ADR-013 已移除（一资产一记录，多主体可混装） |
| 项目级设 active | `项目状态由销售记录状态派生，仅支持批量 delivered/terminated（active 请直接变更销售记录状态）` |
| 项目级批量无目标 | `项目下没有进行中的销售记录，无可批量执行` |
| PATCH /cart/{id} 客户冲突 | `购物车中该产品在客户「X」下已有行，无法修改客户（请先删除原行）` |
| 销售记录状态机 | `不支持的销售记录状态：X` / `销售记录已终止，不可再变更状态` / `已交付完成的销售记录不可回退到进行中` |
| 编辑约束 | `已交付完成的项目不可编辑` |

### 数据清理脚本（⚠️ 迁移窗口专用）

`backend/cleanup_sales_data.py`：备份库 → 单事务删 project_items → outbounds（全部）→ 销售类 flows（project_lock/sale_out/cancel_release/manual_adjust，**purchase_in 保留**）→ cart_items → contracts → projects → 产品 `lockedQty/shippedQty/soldCount/soldAmount` 清零 + status 重刷 → 输出清理前后计数。幂等保护（projects+contracts 均空则跳过）。用法：`python3 cleanup_sales_data.py [--db path] [--dry-run]`。**仅架构师审核后在停服窗口执行，应用启动不调用。**

---

## 文件原名映射 + 金额 diff 元值化（2026-10-15）

上传文件以散列名（`uuid4().hex.ext`）落盘 `uploads/`，`fileUrl` / 产品 `featureDoc`/`contractFile` 仍存**散列名**（契约不变）。新增 `file_meta` 表记录散列名→原始文件名映射，供前端展示与下载还原。

### POST /api/upload（返回体新增 `storedName`）

请求：`POST /api/upload`，`multipart/form-data`，字段 `file`。
响应（200）：
```json
{"filename":"9ca6885e569946ce85b33f28354ca033.pdf","name":"测试文件.pdf","size":22,"storedName":"9ca6885e569946ce85b33f28354ca033.pdf"}
```
关键字段：`filename`（=散列落盘名，同 `storedName`）、`name`（原始文件名）、`size`（字节）、`storedName`（散列落盘名，**新增**）。落盘成功后写 `file_meta`（`uploadedBy`=登录 username），上传非产品操作，不写 OpLog。

### GET /api/files/{filename}（2026-10-16 起需鉴权 + 新增 inline 参数）

请求：`GET /api/files/{storedName}`（`storedName` 即散列落盘名）。

**鉴权（双通道，2026-10-16 起，此前为匿名可访问）**：
- 优先 `Authorization: Bearer <jwt>` 请求头；
- 无头时接受 `?token=<jwt>` 查询参数（iframe/img 等无法带请求头的场景）；
- 两通道均缺失或 token 无效/过期/账号禁用 → 401「未登录或登录已过期」。

**查询参数**：
- `inline`（bool，默认 `false`）：`true` → `Content-Disposition: inline`（内联预览，供 iframe/img 使用）；缺省/`false` → `attachment`（下载，行为不变）。

响应头：
```
# inline=true
Content-Disposition: inline; filename*=UTF-8''%E5%BE%B7%E6%95%B0%E4%BA%A4%E9%81%A5%E6%84%9F%E6%95%B0%E6%8D%AE.pdf
# 缺省（下载）
Content-Disposition: attachment; filename*=UTF-8''%E5%BE%B7%E6%95%B0%E4%BA%A4%E9%81%A5%E6%84%9F%E6%95%B0%E6%8D%AE.pdf
```
关键字段：`filename*` 为 **UTF-8 URL 编码的原始文件名**（查 `file_meta`，无记录用散列名兜底）；`Content-Type` 仍按扩展名推断（如 `application/pdf`）。

### GET /api/bootstrap（返回体新增 `files[]`）

响应体新增 `files: FileMetaOut[]`（**全量**，当前量级小无分页问题）。
```json
{"files":[{"storedName":"9ca6885e569946ce85b33f28354ca033.pdf","name":"测试文件.pdf","size":22,"uploadedBy":"admin","createdAt":"2026-10-15 14:02"}]}
```
关键字段：`storedName`（散列名）、`name`（原始名）、`size`（int）、`uploadedBy`（上传账号，存量回填为空串）、`createdAt`（`YYYY-MM-DD HH:MM`）。前端据此把散列名展示为原始名。

### DELETE /api/upload/{filename}（2026-10-15 起同步清理 file_meta）

请求：`DELETE /api/upload/{storedName}`（需 Bearer token，admin+editor）。
响应（200）：
```json
{"ok": true}
```
行为：物理删除 `uploads/{storedName}` 成功后**同步删除 `file_meta` 中 storedName 对应的行**（无行则忽略，幂等）；返回体不变。物理文件不存在返回 404。

### PUT /api/assets/{id}（`changes` 新格式：金额元值 + 文件字段原始名）

`logs[].changes` 中：**金额类字段**（`salePrice`）由「万元」改为**元值**（`value*10000` 千分位 + 「 元」，空/0 显示「0 元」）；**文件类字段**（`featureDoc`/`contractFile`）值由散列名改为**原始名**（查 `file_meta` 兜底散列名）。**changes 中「万」字清零**。
实测示例：
```
销售单价: 3,200,000 元 → 330,000 元；功能清单: → 测试文件.pdf
```

---

## 认证与权限（2026-10-15 新增，⚠️ Breaking）

### 认证方式

- **JWT Bearer（HS256，7 天有效期）**：登录后所有请求携带请求头
  `Authorization: Bearer <token>`。
- 匿名可访问（白名单，仅 2 个，2026-10-16 起）：`POST /api/auth/login`、`GET /api/health`。
- 其余所有 `/api/*` 端点均需认证；`GET /api/files/{filename}` 为双通道认证（Bearer 头或 `?token=` 查询参数，见该端点小节）。

### 401 / 403 语义

| 状态码 | 响应体 | 触发条件 |
|--------|--------|----------|
| 401 | `{"detail":"未登录或登录已过期"}` | 未带 token / token 无效或过期 / 账号不存在或已禁用（禁用账号的旧 token 立即失效） |
| 401 | `{"detail":"用户名或密码错误"}` | 登录时凭据错误 |
| 401 | `{"detail":"账号已被禁用"}` | 登录时账号 `enabled=false` |
| 403 | `{"detail":"无权限执行此操作"}` | 已登录但角色不足（`require_admin` 拦截；2026-10-20 起 `require_editor` 拦截文案改为下行） |
| 403 | `{"detail":"只读账号不可执行该操作"}` | viewer 触发 `require_editor` 写接口（2026-10-20 FIX-20261020 起文案；前端 403 统一 toast `detail`） |

### 权限矩阵（固定三角色，无动态权限表）

> 角色展示名（仅前端展示，内部标识不变）：admin=管理员、editor=**商务人员**、viewer=**生态人员**（2026-10-16 起）。

| 能力 | admin | editor（商务人员） | viewer（生态人员） |
|------|:-----:|:------:|:------:|
| 读（所有 GET / 查询类） | ✅ | ✅ | ✅ |
| 下单链路（2026-10-16 起 viewer 放行，依赖 `require_order`）：购物车全部 7 端点（`POST /api/cart`、`POST /api/cart/batch`、`PUT /api/cart/{id}`、`PATCH /api/cart/{id}`、`DELETE /api/cart/{id}`、`DELETE /cart` 清空、`POST /api/cart/checkout`）+ `POST /api/sales/order` | ✅ | ✅ | ✅ |
| 业务写（产品 CRUD、手动建项目 `POST /projects`、删项目 `DELETE /projects/{id}`、交付、基础资料、交付物、上传） | ✅ | ✅ | ❌ |
| 自己项目有限操作（2026-10-16 起，`require_order` + 服务层归属校验，仅限**自己下单**项目）：`PATCH /projects/{id}/status` 仅 terminated、`PATCH /contracts/{id}/status` 仅 terminated（含撤销 delivered 交付）；~~`PUT /projects/{id}` 基本信息编辑~~ ⚠️ **ADR-028（2026-10-21）起 viewer 编辑权收回**（403，改单走撤销→回填购物车→重下） | ✅ | ✅ | ✅（限自己项目，**不含编辑**） |
| 撤销/回填：`POST /projects/{id}/withdraw`（仅 pending）、`POST /projects/{id}/refill-cart`（幂等）、`DELETE /projects/{id}` 对 `terminated && cartRefilled` 硬拦 403（ADR-026/027/028） | ✅（可代撤销/删非撤销单） | ✅（同上） | 撤销/回填仅本人单；删除 ❌ |
| 订单审核 `POST /projects/{id}/review`（ADR-012，2026-10-19）：确认下单（改价+写回挂牌价）/ 驳回（原因留痕）；viewer 403；**仅接手账号可操作（admin 可越过）** | ✅（任意单） | ✅（仅接手单） | ❌ |
| 商务接手/转交 `POST /projects/{id}/claim` + 账号选项 `GET /users/options`（ADR-012 §5.1，2026-10-19） | ✅ | ✅ | ❌（options 任意登录可见） |
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

## 产品详情四点字段变更（2026-10-15）

`GET /api/bootstrap` 出参新增/语义变更字段（请求体契约不变，新入参字段均可选默认 `""`）：

| 字段 | 位置 | 说明 |
|------|------|------|
| `featureDoc` | `assets[]`（`AssetOut`/`AssetInput`） | 功能清单附件 filename（`POST /api/upload` 返回值）；`""` = 未上传。`POST /assets`、`PUT /assets/{id}` 均可写入。`saleDetail` 字段保留出参（存量数据），UI 载体已由 `featureDoc` 替代 |
| `subject` | `projects[]`（`ProjectOut`） | 签约主体，**后端权威推导**：`POST /projects` 输入 `subject` 为空时取首条有产品明细的产品主体；`PUT /projects/{id}` 若明细产品主体与原值不同，取首条明细产品主体覆盖。存量项目可能为空（不回填），前端展示时用产品主体兜底 |
| `operator` | `flows[]`（`FlowOut`） | 流水操作账号（登录 username）；**存量流水为空**（前端显示 `-`）；启动 seed 的 `purchase_in` 为 `"system"` |
| `changes` | `logs[]`（`LogOut`） | 字段级变更描述，**仅 `PUT /assets/{id}` 有实际变更时非空**，格式：`字段中文名: 旧值 → 新值 [单位]`，多项以 `；` 分隔。金额类字段（salePrice）显示**元值**（千分位 + 「 元」，2026-10-15 起，禁止「万」字）；文件类字段（featureDoc/contractFile）显示**原始名**（查 file_meta 兜底散列名）；长文本字段（spec/saleDetail/remark）只记 `规格描述: 已变更`。示例（实测）：`销售单价: 3,200,000 元 → 330,000 元；功能清单: → 测试文件.pdf`。无变更不打编辑日志 |

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
| POST | `/api/assets` | 新增产品 |
| PUT | `/api/assets/{asset_id}` | 编辑产品 |
| DELETE | `/api/assets/{asset_id}` | 删除产品（有引用时 400） |
| **POST** | **`/api/assets/{asset_id}/rs-items`** | **新增遥感数据可售明细（ADR-011，admin+editor）** |
| **PUT** | **`/api/rs-items/{item_id}`** | **编辑遥感数据可售明细（ADR-011，admin+editor）** |
| **DELETE** | **`/api/rs-items/{item_id}`** | **删除遥感数据可售明细（ADR-011，有销售关联时 400）** |
| POST | `/api/projects` | 新增项目（强制 active；支持 `contracts` 结构或 `items` 单合同包装） |
| PUT | `/api/projects/{project_id}` | 编辑项目基本信息（存在 delivered 合同不可编辑） |
| PATCH | `/api/projects/{project_id}/status` | 项目状态批量快捷（名下 active 合同批量执行） |
| **PATCH** | **`/api/contracts/{contract_id}/status`** | **合同状态流转（ADR-007 新增，数量联动最小单位）** |
| **DELETE** | **`/api/projects/{project_id}`** | **删除项目（合同级联回滚）** |
| POST | `/api/outbounds` | 交付登记 |
| POST | `/api/outbounds/{outbound_id}/revert` | 撤销交付 |
| POST | `/api/projects/{project_id}/review` | 订单审核（确认下单/驳回，ADR-012） |
| POST | `/api/projects/{project_id}/claim` | 商务接手/转交（ADR-012 §5.1） |
| GET | `/api/users/options` | 商务账号选项（负责人筛选/展示映射） |
| POST | `/api/cart` / `POST /api/cart/batch` | 加购 / 批量加购（跨主体，行级 customer） |
| PUT | `/api/cart/{cart_id}` | 修改购物车数量 |
| **PATCH** | **`/api/cart/{cart_id}`** | **修改购物车行级客户（ADR-007 新增）** |
| DELETE | `/api/cart/{cart_id}` / `DELETE /api/cart` | 删除购物车项 / 清空 |
| POST | `/api/cart/checkout` | 购物车下单（进行中 + 锁定，不自动交付） |
| POST | `/api/sales/order` | 产品直接下单（进行中 + 锁定，不自动交付） |
| POST | `/api/bases/{kind}` 等 | 基础资料（suppliers/customers；**reps 已下线 → 400**，2026-10-20 CLEANUP-20261020） |
| POST | `/api/assets/{asset_id}/deliverables` 等 | 产品交付物（2026-10-21 ADR-024：模板端点已下线，实例完全手动维护；支持单文件附件 `file`） |
| POST | `/api/upload` / `GET /api/files/{filename}` / `DELETE /api/upload/{filename}` | 文件上传/访问/删除 |

---

### POST /api/sales/order

用途：产品直接下单（单/多产品，主体由产品带出）。**语义（2026-10-15 起）**：只生成 **active（进行中）** 销售项目并锁定数量（`lockedQty`），**不再自动交付**——扣数量 + 生成交付（`shippedQty` / `CK-*`）由人工 `PATCH /projects/{id}/status` 置 `delivered` 触发。

请求：`POST /api/sales/order`，body：`{"projectName","customer","rep","businessOwner","contractAmount","expectedSignDate","remark","deliveryReq","items":[{"assetId","qty"}]}`（`businessOwner` 商务负责人，可选，默认 `""`，2026-10-15 起透传落库）
响应（200）：
```json
{"id":1,"code":"SP-001","name":"验收项目1","customer":"客户X","subject":"主体A","status":"active","expectedAmount":1.0,"items":[{"assetId":29,"qty":1,"price":1.0,"amount":1.0,"status":"locked"}]}
```
关键字段：data.status（恒为 `active`）、data.code（SP-{16位时间戳}，2026-10-19 起；前端跳转用）、items[].status=`locked`、items[].locked（2026-10-15 起新增：下单时刻该产品是否真实加锁，非 repeatSale 为 `true`；repeatSale 产品下单不加锁为 `false`，`GET /api/bootstrap` 的 projects[].items 同样返回该字段）
错误：400 主体不一致 / 可售不足（`「xxx」可用数量仅 N台，无法下单 M台`）；404 产品不存在

### POST /api/cart/checkout

用途：购物车结算下单。**语义（2026-10-15 起）**：与 `/sales/order` 相同——生成 **active（进行中）** 项目并锁定数量，**不自动交付**；结算后清空购物车（同一事务，任一步失败整体回滚）。交付需人工置 `delivered`。

请求：`POST /api/cart/checkout`，body：`{"projectName","customer","rep","businessOwner","contractAmount","expectedSignDate","remark","deliveryReq"}`（`businessOwner` 商务负责人，可选，默认 `""`，2026-10-15 起透传落库）
响应（200）：
```json
{"id":2,"code":"SP-002","name":"验收结算项目","customer":"客户Y","status":"active","expectedAmount":1.0,"items":[{"assetId":29,"qty":1,"status":"locked"}]}
```
关键字段：data.status（恒为 `active`）、data.code；结算成功后购物车为空
错误：400 购物车为空 / 购物车产品已删除 / 必填缺项（ADR-022 起：客户/销售金额/普通行服务期限，逐行一次报全，遥感明细行期限豁免，详见文首 REQUIRED-20261024 章节）

FORMS-20261022（ADR-037 §3）：权威链区间校验**分角色**——viewer 行金额仅校验下限（`amount < priceMin` → 400；超上限放行），editor/admin 双向不变；遥感明细行走明细自身区间同口径；viewer 行历史 `discountRate` 忽略（金额权威不变，快照只写不改）。与 `PUT/PATCH /cart/{id}` 复用同一校验函数（详见文首 FORMS-20261022 章节）。

---

### DELETE /api/projects/{project_id}

用途：删除项目。语义 = **先回滚**（释放未交付的锁定；撤销该项目名下所有 `status='done'` 的交付并回退对应 `shippedQty`/`soldAmount`/`soldCount`）→ **再硬删** 项目及其 items → 写 OpLog。

请求：`DELETE /api/projects/8`

响应（200）：
```json
{"ok":true}
```
不存在（404）：
```json
{"detail":"项目不存在"}
```
已撤销（403，ADR-028 / 2026-10-21，`status=terminated` 且 `cartRefilled=true`）：
```json
{"detail":"该订单已撤销（或已回填购物车）并将保留历史记录，不可删除"}
```

关键字段：无（仅 `ok`）。回滚副作用：相关交付单 `status` 置 `reverted`，产品 `shippedQty`/`soldAmount`/`soldCount` 回退。
实测（`DELETE /api/projects/8`）：项目及明细消失，交付单 `CK-0006/CK-0007` 变 `reverted`，`asset1` shippedQty 4→3、soldAmount 1202.68→902.01，日志 `target=project action=删除`。

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
- 可用数量不足（**按 assetId 聚合本单需求量后**校验，同一产品多条明细合计比较）→ 400：
```json
{"detail":"可用数量不足：数采软件及设备接入 可售 1套，本单需 2"}
```

---

### PUT /api/projects/{project_id}

请求体同 `POST /projects`。**忽略传入 status**；仅当项目当前为 `active` 可编辑。
- 非 active（delivered/terminated）→ 400：
```json
{"detail":"已完成/已终止项目不可编辑"}
```
- 可用数量不足（**按 assetId 聚合本单需求量后**校验）→ 400：
```json
{"detail":"可用数量不足：数采软件及设备接入 可售 1套，本单需 5"}
```
- 校验规则：先按 `assetId` 汇总本项目内全部明细的 `qty` 合计，再与该产品可售（`quantity-lockedQty-shippedQty`）比较；`{m}` 为该产品**合计**需求量。`update_project` 在释放旧锁定之后按新明细聚合（不把本单旧占用计入）。`repeatSale` 产品跳过上限校验。

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

FORMS-20261022（ADR-036）：
- `inboundDate` 改为**可选**（默认 `""`）：不传/空 → 后端自动生成当天 `YYYY-MM-DD`；传值仍校验格式（详见文首 FORMS-20261022 章节）。
- 遥感数据容器（`type="遥感数据"`）`repeatSale=true` → 400「遥感数据容器按明细售卖，不支持重复售卖」。

---

### DELETE /api/assets/{asset_id}

若产品被**任何非 terminated 项目的明细**引用，或存在 **`status='done'` 的交付**引用 → 400：
```json
{"detail":"该产品仍被销售项目或交付记录引用，请先终止相关项目/撤销交付后再删除"}
```
通过校验时：清理引用该产品的购物车项 → 级联删除交付物 + 流水 → 删除产品 → 200 `{"ok":true}`。

---

## 错误码表

| HTTP | 场景 | 响应体 |
|------|------|--------|
| 200 | 成功（写操作） | `{"ok":true}` |
| 400 | 业务校验失败（可用数量不足 / 项目不可编辑 / 产品被引用 / 购物车主体不一致等） | `{"detail":"<中文说明>"}` |
| 404 | 资源不存在（项目/产品/购物车项） | `{"detail":"<中文说明>"}` |
| 422 | 请求体校验失败（负数量/负金额等） | `{"detail":[{...pydantic...}]}` |

---

## 变更摘要（2026-10-14）

- **新增** `DELETE /api/projects/{project_id}` → 200 `{"ok":true}`；不存在 404。
- **移除 ⚠️** `PATCH /api/assets/{asset_id}/status`（与产品 2 态自动判定冲突；前端从不调用）。
- **修改 ⚠️** `POST /api/projects`：请求体移除 `status` 字段，后端强制 `active`。
- **修改 ⚠️** `PUT /api/projects/{project_id}`：忽略 `status`；仅 `active` 可编辑。
- **修改 ⚠️** `OpLog`/`LogOut`：新增可选字段 `assetId`（`target='asset'` 时非空）。
- **修复** `POST /api/projects` 与 `PUT /api/projects/{project_id}`：数量校验改为**按 assetId 聚合本单需求量**后再比较可售（同一 assetId 多条明细合计超量才 400）；错误消息格式不变，`本单需 {m}` 为合计需求量。
- **修复** `POST /api/assets/{asset_id}/deliverables`：`GET /api/bootstrap` 中产生的 `target='asset' action='新增交付物'` 日志现携带 `assetId`（此前为空，前端按 assetId 过滤会漏显）。
