# 后端 API 接口文档

> base path：`/api`｜服务：FastAPI + SQLAlchemy + SQLite｜字段与 `frontend/src/types.ts` 对齐（camelCase）

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

实测：`GET /api/bootstrap` 响应 keys 为 `assetDeliverables / assets / cart / categoryUnits / contracts / customers / deliverableTemplates / files / flows / logs / outbounds / projects / rsItems / suppliers`（**无 `reps`**）。

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
- **`PUT /api/projects/{id}`（依赖 `require_editor` → `require_order`）**：viewer 可编辑**自己下单**的项目基本信息；`rep` 字段对 viewer **恒忽略**（防转移项目越权）；非自己项目 → 403 `生态人员仅可编辑自己下单的项目`。
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
权限（2026-10-16）：`require_order`；viewer 仅自己下单项目（403 `生态人员仅可编辑自己下单的项目`），且 `rep` 入参对 viewer 忽略。
**pending 守卫（ADR-012 §5.1，2026-10-19）**：待审核项目基本信息仅**负责人（或 admin 越过）**可编辑 → 非负责人 editor PUT → 400 `待审核项目仅商务负责人（或管理员）可编辑基本信息`（viewer 自己下单的 pending 项目不受限）。

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

**ADR-012 修订（2026-10-19）：所有角色结算统一建 `pending`**（待审核，锁定照常）——原「仅 viewer 结算进 pending、商务/管理员立即 active」的角色分叉废除；商务/管理员需「接手 → 审核（改价确认/驳回）」后生效。**viewer 的 amount 模式行金额可免填**——留空回退 `round(挂牌价×数量)` 取整元（挂牌价未设 → 400 `产品「X」未登记参考单价，无法免填金额，请填写销售金额或先联系商务登记参考单价`）；显式填写仍走整数元校验；商务/管理员金额必填不变。
**同规则适用于全部建单入口**：`POST /api/sales/order`（直接下单）与 `POST /api/projects`（手动建单/草稿）一律建 `pending`（`_create_project_core` 默认 `initial_status="pending"`）。
错误（400）：
```json
{"detail":"请为每件产品填写客户"}
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

### 400 错误文案清单（ADR-007 新增/变更）

| 场景 | 文案 |
|------|------|
| checkout 空客户行 | `请为每件产品填写客户` |
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
| 自己项目有限操作（2026-10-16 起，`require_order` + 服务层归属校验，仅限**自己下单**项目）：`PUT /projects/{id}` 基本信息编辑（rep 不可改）、`PATCH /projects/{id}/status` 仅 terminated、`PATCH /contracts/{id}/status` 仅 terminated（含撤销 delivered 交付） | ✅ | ✅ | ✅（限自己项目） |
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
| POST | `/api/deliverable-templates` 等 | 交付物模板 |
| POST | `/api/assets/{asset_id}/deliverables` 等 | 产品交付物 |
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
错误：400 购物车为空 / 购物车产品已删除

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
