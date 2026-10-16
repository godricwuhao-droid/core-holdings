# 后端 API 接口文档

> base path：`/api`｜服务：FastAPI + SQLAlchemy + SQLite｜字段与 `frontend/src/types.ts` 对齐（camelCase）

---

## 2026-10-16 变更（ADR-011 遥感数据「父资产 + 可售明细」两层模型，⚠️ Supersedes ADR-010）

### 遥感数据模型概览

- 资产列表里是 **1 个父资产**（`type='遥感数据'`，容器，本身不可直接加购/下单，`quantity/lockedQty/shippedQty` 仅承载明细 repeatSale=false 的锁定/出库口径）；
- 真正售卖单位 = **`rs_items` 明细**（省/市 × 精度 × 月份，每份一个整数元单价，默认 repeatSale=true 只计次不扣量）；
- **⚠️ ADR-010 资产三维字段全部移除**：`AssetOut` 不再输出 `province/city/resolution/imageDate`；`AssetInput` 不再接受（前端多传被 Pydantic 静默忽略）；`POST /assets`、`PUT /assets/{id}` 的三维必填/判重 400 文案作废。遥感数据按普通父资产登记。

### 新增端点（写均 admin+editor `require_editor`，读随 bootstrap 放行）

#### POST /api/assets/{asset_id}/rs-items

请求：`POST /api/assets/29/rs-items`，body `RsItemInput`：
```json
{"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000,"repeatSale":true}
```
- `province` 必填（空 400）；`city` 默认 `""`；`resolution` > 0（否则 422）；`saleMonth` 须匹配 `^\d{4}-\d{2}$`（否则 422）；`price` 整数元 > 0（否则 400）；`repeatSale` 默认 `true`。
- 父资产必须存在（404 `资产不存在`）且 `type='遥感数据'`（否则 400）。

响应（200，`RsItemOut`）：
```json
{"id":1,"assetId":29,"province":"河北省","city":"石家庄市","resolution":1.5,"saleMonth":"2026-09","price":330000.0,"repeatSale":true,"createdAt":"2026-10-16 11:41","updatedAt":"2026-10-16 11:41"}
```

#### PUT /api/rs-items/{item_id}

请求：`PUT /api/rs-items/1`，body 同 `RsItemInput`（全字段可改，含 `price`/`repeatSale`）。唯一性判重**排除自身**。
响应（200）：更新后的 `RsItemOut`。错误：404 `遥感数据明细不存在` / 404 `明细所属父资产不存在`。

#### DELETE /api/rs-items/{item_id}

请求：`DELETE /api/rs-items/1` → 200 `{"ok":true}`
- 任一 `project_items.itemId` 或 `cart_items.itemId` 引用该明细（含已完成/已终止合同）→ 400。
- 删除成功写 OpLog（`target='asset'`，关联父资产 id，action=`删除可售明细`）。

审计：新增/编辑/删除明细均写 audit_logs（`actionType=asset_change`，`target=asset`，`targetName`=父资产名，`detail=rsItemId=N`）。

### bootstrap 出参新增

| 字段 | 位置 | 说明 |
|------|------|------|
| `rsItems` | bootstrap 顶层（**新增**） | `RsItemOut[]` **全量**（前端 RsItemPicker / 资产详情「可售明细」页签消费） |
| `itemId` | `cart[]`（新增，nullable） | 购物车行挂的明细 id；非空行 `qty` 恒 1；存量/非遥感行 `null` |
| `itemId` | `projects[].items[]` / `contracts[].items[]`（新增，nullable） | 项目/合同明细行挂的明细 id；存量行 `null` |
| ~~`province`/`city`/`resolution`/`imageDate`~~ | `assets[]`（**移除 ⚠️**） | ADR-010 三维字段出参移除（列保留不删） |

### 购物车（含 itemId 行）

- `POST /api/cart`、`POST /api/cart/batch`（`CartItemInput`）新增可选 `itemId`：
  - 校验明细存在且其 `assetId` == 传入 `assetId`（否则 400；batch 路径跳过该行并记 skipped）；
  - **qty 恒 1**（传 ≠1 → 400；batch 路径强制 1）；
  - 判重键升级为 **(userId, assetId, itemId, customer)**——同键重复加购**幂等合并（qty 保持 1，不累加）**；无 itemId 行口径完全不变（`itemId IS NULL` 才与无明细行合并）；
  - 库存：明细 `repeatSale=true` 不占库存；`false` 按父资产可售（该资产全部行合计）校验。
- `PUT /api/cart/{id}`：含 itemId 的行 qty≠1 → 400（前端本就不允许改；删除走 `DELETE /cart/{id}`）。
- `PATCH /api/cart/{id}`（改客户）：判重同样带 itemId（明细行与无明细行互不冲突）。
- `CartItemOut` 新增 `itemId: int | null`。

### 销售链路（含 itemId 行，三条入口全覆盖）

`POST /api/projects`（`ProjectItemInput`）、`POST /api/sales/order`（`SaleOrderItemInput`）、`POST /api/cart/checkout`（购物车行）均支持 `itemId`：

- 含 itemId 的明细行：**`amount` 后端权威 = `rs_items.price × 1`**（Decimal 重算，**忽略前端传值**，整数元天然成立）；`qty` 强制 1（≠1 → 400）；
- 明细 `repeatSale=true` → 跳过库存锁定（走现有 repeatSale 分支，只计次）；`false` → 按现有 lockedQty 逻辑锁**父资产**（qty=1），交付扣 `shippedQty`、终止/撤销对称回退（含 `locked` 标记与出库撤销回退，全部明细感知）；
- `project_items.itemId` 落库；`ProjectItemOut` / 合同 items 输出 `itemId: int | null`；
- 明细不存在或不属于该资产 → 400（checkout 场景：`购物车中的遥感数据明细已删除或不属于该资产，请先移除后再下单`）。

### 400 文案表（ADR-011 新增）

| 场景 | 文案 |
|------|------|
| 非遥感资产维护明细 | `仅遥感数据资产可维护可售明细` |
| 明细省为空 | `遥感数据明细必须填写省份` |
| 明细单价非整数元/≤0 | `遥感数据明细单价须为整数元且大于 0` |
| 同父资产 省/市+精度+月份 重复（create / update 排除自身） | `该父资产下已存在相同 省/市 + 精度 + 月份 的明细` |
| 明细被项目/购物车引用时删除 | `该明细存在销售关联，无法删除` |
| 购物车/下单 明细行 qty≠1 | `遥感数据明细行数量固定为 1` |
| 购物车/下单 明细不存在或归属不符 | `遥感数据明细不存在或不属于该资产` |
| checkout 明细行失效 | `购物车中的遥感数据明细已删除或不属于该资产，请先移除后再下单` |

### 实测（curl）

```
POST /api/assets {"type":"遥感数据","name":"遥感数据-2026",...} → 200（AssetOut 无 province 等 4 字段）
POST /api/assets/29/rs-items ×2（河北石家庄 1.5m 2026-09 330000 / 甘肃 1m 2026-10 280000）→ 200；同组合再建 → 400「该父资产下已存在相同 省/市 + 精度 + 月份 的明细」
bootstrap.rsItems → 2 条；加购 itemId 行 qty=1 → 200、qty=2 → 400「遥感数据明细行数量固定为 1」、重复加购合并 qty 仍 1
POST /api/sales/order items=[{"assetId":29,"qty":1,"amount":999,"itemId":1}] → item.amount=330000.0（999 被忽略）、itemId=1、locked=false
交付合同 → soldCount+1/soldAmount+330000、无锁定动作；终止 → 全回退
repeatSale=false 明细下单 → 父资产 lockedQty+1（locked=true）；交付 → shippedQty+1；终止 delivered → 全回退
有引用 DELETE /rs-items/{id} → 400「该明细存在销售关联，无法删除」；无引用 → 200
回归：unit 下单（amount 重算）、卫星Token amount 模式下单、普通购物车结算 均正常
```

---

## 2026-10-16 变更（ADR-008 包量定价 / ADR-009 购物车按登录用户隔离 / ADR-010 遥感数据）

> ⚠️ 本节 **ADR-010 部分已被 ADR-011 取代**（资产三维入出参/判重/默认值全部移除，见上方 ADR-011 章节）；ADR-008/ADR-009 部分仍有效。

### 资产入出参（POST /api/assets、PUT /api/assets/{id}、bootstrap assets[]）

- `AssetOut` 新增：`pricingMode`（`unit`/`amount`，**后端按类型权威决定**：`type='卫星Token'` → `amount`，其余恒 `unit`）、`province`/`city`/`resolution`（精度，单位米）/`imageDate`（非遥感类型恒 `""`/`null`）。
- `AssetInput` 新增可选：`province`、`city`、`resolution`、`imageDate`。`type='遥感数据'` 时 省/精度/日期 必填（市可空，省级资产不填）；非遥感类型忽略/置空。**不接受 `pricingMode` 入参**（后端按类型决定，多传被忽略）。
- 遥感数据入库默认值（后端兜底）：`quantity` 0→1、`unit` 空→`份（区域·精度·日期）`；`repeatSale` 由前端传（默认 True，允许关闭）。
- 400 文案：

| 场景 | 文案 |
|------|------|
| 遥感数据缺 省/精度/日期 | `遥感数据资产必须填写 省、精度、影像日期` |
| 三维组合重复（create / update 排除自身） | `已存在相同 省/市 + 精度 + 日期 的遥感数据资产` |

实测（curl）：
```
POST /api/assets {"type":"遥感数据","province":"河北省","city":"石家庄市","resolution":1.5,"imageDate":"2026-09-15",...} → 200
  {"id":29,"code":"CH-SAT-029","pricingMode":"unit","province":"河北省","city":"石家庄市","resolution":1.5,"imageDate":"2026-09-15","quantity":1,"repeatSale":true,"unit":"份（区域·精度·日期）"}
同组合再建 → 400 {"detail":"已存在相同 省/市 + 精度 + 日期 的遥感数据资产"}
改 imageDate 后建 → 200（不冲突）
```

### 销售明细计价分支（POST /api/projects、POST /api/sales/order、POST /api/cart/checkout）

- 资产 `pricingMode='amount'` 时：
  - `POST /projects` 明细 `amount` 为**权威输入**（整数元且 >0，否则 400），**跳过** `price×qty` 权威重算；`price = round(amount/qty, 6)` 仅作派生展示值落库；合同/项目金额 = Σ 权威 amount。
  - `POST /sales/order` `items[]` 新增可选 `amount`（元，整数）：amount 模式资产**必填**（缺失/非整数 400）；unit 模式忽略。
  - `POST /cart/checkout`：amount 模式购物车行 `amount` 必填（缺失 400）。
- `pricingMode='unit'` 时行为**完全不变**（`amount = price×qty` Decimal 权威重算，前端传值忽略）。
- 400 文案：`包量计价资产的销售金额须为整数元`

实测（curl）：
```
POST /api/sales/order {"items":[{"assetId":6,"qty":1,"amount":10000000}]}（asset6=卫星Token，amount 模式）
  → 200，item: {"qty":1,"price":10000000.0,"amount":10000000.0,"status":"locked"}，expectedAmount=10000000.0
amount=10000000.5 → 400 {"detail":"包量计价资产的销售金额须为整数元"}；不传 amount → 400 同文案
unit 模式回归：{"assetId":16,"qty":2,"price":26800,"amount":99999} → item.amount=53600.0（重算，忽略 99999）
```

### 购物车（⚠️ 按登录用户隔离 + 行级 amount）

- **按登录用户隔离（ADR-009）**：全部 7 端点（`POST /cart`、`POST /cart/batch`、`PUT/PATCH/DELETE /cart/{id}`、`DELETE /cart`、`POST /cart/checkout`）以 `get_current_user` 的 `user.id` 为桶；`bootstrap.cart` 仅返回当前用户行；A 结算不清空 B 的行。判重 (userId, assetId, customer) 与库存校验规则不变。
- 行级 `amount`（ADR-008，元，整数，可选）：
  - `CartItemInput`（POST /cart、POST /cart/batch items[]）、`PUT /cart/{id}`（body 可选 `amount`）、`PATCH /cart/{id}` 均接受；
  - amount 模式资产行：传入时校验整数元（非整数 400 `包量计价资产的销售金额须为整数元`）后落库；**结算时必填**（缺失 400 同文案）；
  - unit 模式行：忽略（不采信、不落库，`CartItemOut.amount` 恒 `null`）。
- `CartItemOut` 新增 `amount`（float|null）。

实测（curl）：
```
editor(id=3) 加购 asset16 → bootstrap(editor).cart 仅 1 行；viewer(id=4) 加购 asset17 → bootstrap(viewer).cart 仅自己 1 行
viewer checkout → 200（生成项目+合同），viewer 购物车清空，editor 行不受影响
viewer：POST /cart/batch 200、DELETE /cart 清空 200（require_order 放行）
admin 加购卫星Token 行（不带 amount）→ checkout 400「包量计价资产的销售金额须为整数元」
PUT /cart/{id} {"qty":1,"amount":5000000} → checkout 200，item.amount=5000000.0（price 派生同值）
unit 模式行 PUT 传 amount=12345 → 忽略，行 amount 仍为 null
```

---

## 业务逻辑审计 6 项修复（2026-10-15，行为收紧）

### POST /api/outbounds（FIX-1 新增可售校验）

请求：`POST /api/outbounds`，body 同既有（`assetId/qty/amount/type/mode/date/projectId?/customer?/operator?/remark?`）
新增校验：`mode != "history"` 且资产**非 repeatSale** 时，`qty > quantity - lockedQty - shippedQty`（按当前库值）→ 400。
`mode = "history"`（历史补录，不扣库存）与 repeatSale 资产跳过校验。

响应（超量）：
```json
{"detail": "出库数量超出可售库存：FIX1-非重复 可售 2套，本次出库 5套"}
```
关键字段：无（400 detail 文案）；通过时响应同既有 `OutboundOut`

### DELETE /api/projects/{project_id}（FIX-2 回滚范围扩大）

删除项目除既有级联（active 合同释放锁定、delivered 合同撤销名下 done 出库）外，**同时撤销 `projectId == 项目id 且 contractId == null 且 status='done'` 的手动出库**（写「出库撤销」OpLog + manual_adjust 回退流水 + 回退 shippedQty/soldCount/soldAmount）。与前端删除确认文案「撤销该项目已生成的出库记录」对齐。
注意：**项目终止（PATCH status=terminated）不做**此回滚——终止≠删除，手动出库是独立动作。

### POST /api/outbounds/{outbound_id}/revert（FIX-3 soldCount 回退口径）

撤销出库的 `soldCount` 回退改为精确逆操作（其余回退不变）：
- 合同交付出库（`contractId != null`）：撤销 soldCount -1（创建时两种资产均 +1）；
- 手动出库（`contractId == null`）：**仅资产 repeatSale 时** soldCount -1（创建时仅 repeatSale 分支 +1）。

### DELETE /api/assets/{asset_id}（FIX-4 合同感知口径）

引用拦截拆为两条（done 出库拦截保持）：
- 合同明细（contractId 非空）：仅当存在 **`status='active'`** 合同引用 → 400；delivered/terminated 合同引用放行；
- 无合同 legacy 项目明细：保持原规则（项目 status != terminated → 400）。

响应（active 合同引用）：
```json
{"detail": "该资产仍被进行中的合同 HT-0005（客户 C1）引用，请先终止该合同后再删除"}
```

### PUT /api/projects/{project_id}（FIX-6a 新增终止拦截）

项目派生状态为 `terminated`（全合同终止/混合 delivered+terminated；legacy terminated）→ 400（先于既有「存在 delivered 合同不可编辑」判断）：
```json
{"detail": "项目已终止，不可编辑"}
```

### PUT /api/cart/{cart_id}（FIX-6b 行级合计校验）

数量上限从「本行 qty ≤ 可售」升级为「该资产在购物车**全部行合计**（本次修改后）≤ 可售」（repeatSale 跳过；`POST /cart`、`POST /cart/batch` 已是同口径）：
```json
{"detail": "购物车中 FIX6-购物车 合计 3 超出可售 2"}
```

### OpLog operator 真实化（FIX-5，出参语义变更）

`bootstrap.logs[].operator` 不再恒为 `"admin"`：合同交付/终止、项目新增/编辑/状态变更/删除、出库创建/撤销、资产新增/编辑/删除等写路径记录**实际登录用户名**（如 `editor`）。基础资料/交付物模板/资产交付物增删改仍为默认 `"admin"`（未透传）。

---

## 合同层级（ADR-007，2026-10-15，⚠️ Breaking）

### 数据模型概览

- 新增 `contracts` 表：项目下按客户拆分的合同，**库存联动的最小单位**。合同内强制同一资产主体；合同一经生成不可增删改明细（终止再重下）。
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
关键字段：`code`（HT-{4位序号}）、`status`（active/delivered/terminated）、`items[].contractId`（明细挂合同，存量明细为 null）、`items[].locked`（下单时刻是否真实加锁）。

### PATCH /api/contracts/{contract_id}/status（新增，admin+editor）

请求：`PATCH /api/contracts/1/status`，body `{"status":"delivered","reason":"..."}`
响应（200）：`{"ok":true}`
行为：
- `delivered`：逐明细交付——释放锁定（仅 `it.locked`）、非 repeatSale 扣 `shippedQty`、`soldCount`/`soldAmount` 均累计、**每明细生成出库记录**（`contractId`=合同 id，备注「合同「HT-xxxx」交付完成自动生成」）；
- `terminated`：active 合同→释放锁定（cancel_release 流水带 contractId）；delivered 合同→撤销该合同名下 `done` 出库（reverted）+ 回退 shippedQty/soldCount/soldAmount（负数流水）；
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
- `contracts`（可选）：每客户一个合同；`customer` 必填；`contractAmount` 缺省=该组明细 amount 合计（Decimal 重算）。
- **向后兼容**：不传 `contracts` 仍传 `items` → 按**单合同**自动包装，customer 取项目 `customer` 字段。`items` 现为可选字段（`default=[]`）。
- 逐合同校验同主体 → 400 `客户「X」的资产主体不一致，请拆分`；库存按 assetId **跨合同聚合**校验（超量 400 `库存不足：...`）。
- 项目 `subject`/`customer`/`expectedAmount` 由合同派生（请求体同名值不再采信）；`status` 恒为 `active`。
响应（200，`ProjectOut`）：新增 `contractCount`（int）；`items[].contractId` 非空。

### PUT /api/projects/{project_id}（⚠️ 收窄为基本信息编辑）

仅接受项目基本信息：`name`/`industry`/`rep`/`businessOwner`/`remark`/`expectedSignDate`/`lastFollowDate`/`quoteAmount`/`paidAmount`。
**不再接受 items/contracts 变更**（收到即忽略——合同结构编辑本次不做，终止再重下）；`customer`/`subject`/`expectedAmount`/`contractAmount` 为派生字段，传入不采信。
编辑约束：**存在 delivered 合同 → 400 `已交付完成的项目不可编辑`**（存量无合同项目沿用 `status!=active` 旧规则）。

### PATCH /api/projects/{project_id}/status（⚠️ 批量快捷语义）

请求：`{"status":"delivered","reason":"..."}` → 200 `{"ok":true}`
- 行为改为：对名下全部 **active** 合同批量执行该状态动作（delivered=全部交付、terminated=全部终止）。前端主入口用合同级 `PATCH /contracts/{id}/status`，本接口作为批量快捷保留。
- `status=active` → 400 `项目状态由合同状态派生，仅支持批量 delivered/terminated（active 请直接变更合同状态）`；无 active 合同 → 400 `项目下没有进行中的合同，无可批量执行`。
- 存量无合同项目：走旧的项目级明细逻辑（行为不变）。

### 购物车（⚠️ 跨主体 + 行级客户）

- `POST /api/cart`：body `{"assetId":1,"qty":1,"customer":"甲"}`（`customer` 新增，可选默认 `""`）。**同主体限制已删除**（跨主体加购成功）。
- `POST /api/cart/batch`：`items[]` 每行可带 `customer`。
- **唯一键语义：(userId, assetId, customer) 相同才合并**（不同 customer 同资产 = 两行）；库存上限按该资产**全部行合计**校验。
- **新增 `PATCH /api/cart/{id}`**：body `{"customer":"庚"}` 改行级客户；目标 (userId,assetId,customer) 已有其它行 → 400 `购物车中该资产在客户「X」下已有行，无法修改客户（请先删除原行）`。
- `CartItemOut` 新增 `customer`（默认 `""`）。

### POST /api/cart/checkout（⚠️ 按客户分组拆合同）

请求：`{"projectName":"...","rep":"...","businessOwner":"..."}`（`projectName` 可空，缺省「销售项目-日期」；`customer` 字段兼容保留，**不参与分组**；`businessOwner` 商务负责人，可选，默认 `""`）。
行为：按购物车**行级 customer** 分组 → 每组（客户）校验合同内同主体 → 每客户一个合同（code HT-xxxx、subject 推导、contractAmount=该组明细合计）→ 建项目（active+锁定）→ 清空购物车，**全部单事务**。不自动交付。
错误（400）：
```json
{"detail":"请为每件资产填写客户"}
{"detail":"客户「丙」的资产主体不一致，请拆分"}
```
响应（200，`ProjectOut`）：`contractCount`=客户组数、`customer` 多客户为空串、`expectedAmount`=Σ合同。

### bootstrap / 出参变更（2026-10-15）

| 字段 | 位置 | 说明 |
|------|------|------|
| `contracts` | bootstrap 顶层（**新增**） | `ContractOut[]` 全量（含 items 挂 contractId） |
| `contractCount` | `projects[]`（新增） | int，合同数量（派生） |
| `contractId` | `projects[].items[]` / `outbounds[]` / `flows[]` / `logs[]`（新增，nullable） | 关联合同 id；存量数据为 `null` |
| `customer` | `cart[]`（新增，默认 `""`） | 购物车行级客户 |

### DELETE /api/projects/{project_id}（⚠️ 合同级联）

active 合同释放锁定、delivered 合同撤销名下 done 出库并回退 shippedQty/soldCount/soldAmount → 硬删项目及其合同、明细。存量无合同项目沿用旧回滚逻辑。

### 400 错误文案清单（ADR-007 新增/变更）

| 场景 | 文案 |
|------|------|
| checkout 空客户行 | `请为每件资产填写客户` |
| checkout 同客户跨主体 / POST /projects 合同内跨主体 | `客户「X」的资产主体不一致，请拆分` |
| sales/order 同主体校验 | `下单资产必须属于同一主体，请拆分下单` |
| 项目级设 active | `项目状态由合同状态派生，仅支持批量 delivered/terminated（active 请直接变更合同状态）` |
| 项目级批量无目标 | `项目下没有进行中的合同，无可批量执行` |
| PATCH /cart/{id} 客户冲突 | `购物车中该资产在客户「X」下已有行，无法修改客户（请先删除原行）` |
| 合同状态机 | `不支持的合同状态：X` / `合同已终止，不可再变更状态` / `已交付完成的合同不可回退到进行中` |
| 编辑约束 | `已交付完成的项目不可编辑` |

### 数据清理脚本（⚠️ 迁移窗口专用）

`backend/cleanup_sales_data.py`：备份库 → 单事务删 project_items → outbounds（全部）→ 销售类 flows（project_lock/sale_out/cancel_release/manual_adjust，**purchase_in 保留**）→ cart_items → contracts → projects → 资产 `lockedQty/shippedQty/soldCount/soldAmount` 清零 + status 重刷 → 输出清理前后计数。幂等保护（projects+contracts 均空则跳过）。用法：`python3 cleanup_sales_data.py [--db path] [--dry-run]`。**仅架构师审核后在停服窗口执行，应用启动不调用。**

---

## 文件原名映射 + 金额 diff 元值化（2026-10-15）

上传文件以散列名（`uuid4().hex.ext`）落盘 `uploads/`，`fileUrl` / 资产 `featureDoc`/`contractFile` 仍存**散列名**（契约不变）。新增 `file_meta` 表记录散列名→原始文件名映射，供前端展示与下载还原。

### POST /api/upload（返回体新增 `storedName`）

请求：`POST /api/upload`，`multipart/form-data`，字段 `file`。
响应（200）：
```json
{"filename":"9ca6885e569946ce85b33f28354ca033.pdf","name":"测试文件.pdf","size":22,"storedName":"9ca6885e569946ce85b33f28354ca033.pdf"}
```
关键字段：`filename`（=散列落盘名，同 `storedName`）、`name`（原始文件名）、`size`（字节）、`storedName`（散列落盘名，**新增**）。落盘成功后写 `file_meta`（`uploadedBy`=登录 username），上传非资产操作，不写 OpLog。

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
| 403 | `{"detail":"无权限执行此操作"}` | 已登录但角色不足 |

### 权限矩阵（固定三角色，无动态权限表）

> 角色展示名（仅前端展示，内部标识不变）：admin=管理员、editor=**商务人员**、viewer=**生态人员**（2026-10-16 起）。

| 能力 | admin | editor（商务人员） | viewer（生态人员） |
|------|:-----:|:------:|:------:|
| 读（所有 GET / 查询类） | ✅ | ✅ | ✅ |
| 下单链路（2026-10-16 起 viewer 放行，依赖 `require_order`）：购物车全部 7 端点（`POST /api/cart`、`POST /api/cart/batch`、`PUT /api/cart/{id}`、`PATCH /api/cart/{id}`、`DELETE /api/cart/{id}`、`DELETE /cart` 清空、`POST /api/cart/checkout`）+ `POST /api/sales/order` | ✅ | ✅ | ✅ |
| 业务写（资产 CRUD、手动建项目 `POST/PUT/PATCH/DELETE /projects*`、合同状态 `PATCH /contracts/{id}/status`、出库、基础资料、交付物、上传） | ✅ | ✅ | ❌ |
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

## 资产详情四点字段变更（2026-10-15）

`GET /api/bootstrap` 出参新增/语义变更字段（请求体契约不变，新入参字段均可选默认 `""`）：

| 字段 | 位置 | 说明 |
|------|------|------|
| `featureDoc` | `assets[]`（`AssetOut`/`AssetInput`） | 功能清单附件 filename（`POST /api/upload` 返回值）；`""` = 未上传。`POST /assets`、`PUT /assets/{id}` 均可写入。`saleDetail` 字段保留出参（存量数据），UI 载体已由 `featureDoc` 替代 |
| `subject` | `projects[]`（`ProjectOut`） | 签约主体，**后端权威推导**：`POST /projects` 输入 `subject` 为空时取首条有资产明细的资产主体；`PUT /projects/{id}` 若明细资产主体与原值不同，取首条明细资产主体覆盖。存量项目可能为空（不回填），前端展示时用资产主体兜底 |
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
| POST | `/api/assets` | 新增资产 |
| PUT | `/api/assets/{asset_id}` | 编辑资产 |
| DELETE | `/api/assets/{asset_id}` | 删除资产（有引用时 400） |
| **POST** | **`/api/assets/{asset_id}/rs-items`** | **新增遥感数据可售明细（ADR-011，admin+editor）** |
| **PUT** | **`/api/rs-items/{item_id}`** | **编辑遥感数据可售明细（ADR-011，admin+editor）** |
| **DELETE** | **`/api/rs-items/{item_id}`** | **删除遥感数据可售明细（ADR-011，有销售关联时 400）** |
| POST | `/api/projects` | 新增项目（强制 active；支持 `contracts` 结构或 `items` 单合同包装） |
| PUT | `/api/projects/{project_id}` | 编辑项目基本信息（存在 delivered 合同不可编辑） |
| PATCH | `/api/projects/{project_id}/status` | 项目状态批量快捷（名下 active 合同批量执行） |
| **PATCH** | **`/api/contracts/{contract_id}/status`** | **合同状态流转（ADR-007 新增，库存联动最小单位）** |
| **DELETE** | **`/api/projects/{project_id}`** | **删除项目（合同级联回滚）** |
| POST | `/api/outbounds` | 出库登记 |
| POST | `/api/outbounds/{outbound_id}/revert` | 撤销出库 |
| POST | `/api/cart` / `POST /api/cart/batch` | 加购 / 批量加购（跨主体，行级 customer） |
| PUT | `/api/cart/{cart_id}` | 修改购物车数量 |
| **PATCH** | **`/api/cart/{cart_id}`** | **修改购物车行级客户（ADR-007 新增）** |
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

请求：`POST /api/sales/order`，body：`{"projectName","customer","rep","businessOwner","contractAmount","expectedSignDate","remark","deliveryReq","items":[{"assetId","qty"}]}`（`businessOwner` 商务负责人，可选，默认 `""`，2026-10-15 起透传落库）
响应（200）：
```json
{"id":1,"code":"SP-001","name":"验收项目1","customer":"客户X","subject":"主体A","status":"active","expectedAmount":1.0,"items":[{"assetId":29,"qty":1,"price":1.0,"amount":1.0,"status":"locked"}]}
```
关键字段：data.status（恒为 `active`）、data.code（SP-xxx，前端跳转用）、items[].status=`locked`、items[].locked（2026-10-15 起新增：下单时刻该资产是否真实加锁，非 repeatSale 为 `true`；repeatSale 资产下单不加锁为 `false`，`GET /api/bootstrap` 的 projects[].items 同样返回该字段）
错误：400 主体不一致 / 可售不足（`「xxx」可售库存仅 N台，无法下单 M台`）；404 资产不存在

### POST /api/cart/checkout

用途：购物车结算下单。**语义（2026-10-15 起）**：与 `/sales/order` 相同——生成 **active（进行中）** 项目并锁定库存，**不自动交付**；结算后清空购物车（同一事务，任一步失败整体回滚）。交付需人工置 `delivered`。

请求：`POST /api/cart/checkout`，body：`{"projectName","customer","rep","businessOwner","contractAmount","expectedSignDate","remark","deliveryReq"}`（`businessOwner` 商务负责人，可选，默认 `""`，2026-10-15 起透传落库）
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
