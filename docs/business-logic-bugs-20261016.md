# 业务逻辑 Bug 排查清单（2026-10-16）

排查范围：后端 `backend/src/services.py`（业务规则核心）、`routers/api.py`、`schemas.py`、`models.py`、`security.py`；前端 `frontend/src/api/index.ts`、`types.ts`、购物车 `views/cart/index.vue`、下单对话框 `components/SalesOrderDialog.vue`、资产表单 `views/assets/create.vue`。

> 状态标记：⬜ 待修复 / ✅ 已修复 / ❌ 评估为误报

## 一、较严重（会造成数据/金额口径错误）

### 1. 看板「可售金额」把卫星 Token 资产算爆（评估✅ · 已修复）
`availableValue = 可售数量 × salePrice`，但 amount 模式（卫星Token）资产的 `salePrice` 单位是「元/万Token」（仅参考值，不参与计价），两者相乘在任何口径下都不是真实金额。
- 影响面：首页 `availableValue`（api/index.ts `getDashboard`）与五个板块统计 `boardStats[].availableValue`；seed 数据中有 3 条卫星Token资产（CH-SAT-001/002/003，`seed_data.py:37-51`）必然被计入。
- 位置：`frontend/src/types.ts:150-153`（`availableValue`）、`frontend/src/api/index.ts:351-375`（`getDashboard`）。
- 评估修正：「虚高数个数量级」仅对**按原始 Token 个数入库的用户新建资产**成立（如 3 亿 × 元/万Token 参考值）；seed 数据 quantity 是「颗」，虚高幅度有限，但口径错误始终存在。

### 2. `PUT /assets/{id}` 无任何入参校验（裸 dict）（评估✅ · 已修复）
其他写接口均有 Pydantic 模型，唯独编辑资产直接收 `request: dict`，`update_asset` 对 allowed 字段直接 `setattr` 落库。`quantity` / `salePrice` 可传负数、字符串等非法值——SQLite 动态类型会照单全收，直接破坏「可售 = 总数 − 锁定 − 已出库」不变量。
- 位置：`backend/src/routers/api.py:180-186`、`backend/src/services.py:286-331`（`update_asset`）。

### 3. 新建资产不跑状态自动判定，直接信任前端 `status`（评估✅ · 已修复）
平台规则是「状态两态、由库存自动判定」（`auto_status`），但 `create_asset` 使用 `status=data.status`（前端恒传 `in_stock`，见 `create.vue` form 默认值）且不调用 `refresh_status`。非重复售卖 + `quantity=0` 的新资产会落库 `in_stock`，与自动判定规则不一致，需等下一次编辑才被纠正。
- 位置：`backend/src/services.py:205-233`（`create_asset`）、`frontend/src/views/assets/create.vue:62`（`status: 'in_stock'` 固定值）。

### 4. 手动出库的 `operator` 取自前端入参，可伪造（评估✅ · 已修复）
`create_outbound` 落库 `operator=data.operator or "admin"`，而真实登录账号在路由层明明可用（审计日志用的是 `user.username`）。业务表与审计表的操作人可不一致。
- 位置：`backend/src/services.py:1063-1071`（`create_outbound`）、`backend/src/routers/api.py:297-302`。

### 5. `update_asset` 允许把 `quantity` 改到低于 `lockedQty + shippedQty`（评估✅ · 已修复）
无下限校验，可售直接变负（前端 `availableQty` 靠 `Math.max(0, …)` 夹零掩盖），库存口径被破坏且无留痕。
- 位置：`backend/src/services.py:286-331`（`update_asset` 无库存下限校验）。

## 二、中等（特定路径下的数据不一致 / 体验 bug）

### 6. 非重复售卖的遥感明细行「重复加购」被误判库存不足（评估✅ · 已修复）
幂等合并场景下，库存校验用「该资产购物车全部行合计 + 本次 qty」，而合计里已包含该明细行本身的 1 件。可售恰好为 1 时，第二次点击同一明细（本应幂等保持 qty=1）会被 400 拦截。
- 位置：`backend/src/services.py:1339-1385`（`add_to_cart`，`total_in_cart + qty > _avail(a)`）。

### 7. 批量加购不原子（评估✅ · 已修复）
`add_to_cart_batch` 循环内每条都走 `add_to_cart`（内部 `db.commit()`），逐条提交、不原子，中途失败时购物车呈「加了一半」的半状态。
- 位置：`backend/src/services.py:1423-1458`（`add_to_cart_batch` 调 `add_to_cart`）。
- 评估修正：资产不存在/明细不存在/超量在批量入口均为**软跳过**（记入 skipped），硬 400 主要经 amount 模式金额校验（`_validate_amount_yuan` 非整数元，批量未预检）触发；更常见的失败形态是「部分跳过 + 部分加入」。

### 8. unit 模式直接下单，用户输入的「合同金额」被静默丢弃（评估✅ · 已修复）
下单对话框中 unit 模式资产的「合同金额（元）」可编辑（默认值自动填充后仍可改写），但后端 `_create_project_core` 恒按 `price × qty` 权威重算，`contractAmount` 入参不采信（建项目时置 0 后由 `_recompute_project` 派生）。用户改过的金额不会生效，前端无提示，展示值与落库值可能不一致。
- 位置：`frontend/src/components/SalesOrderDialog.vue:211-239`（`onSubmit`）、`backend/src/services.py:606-616` + `749-765`。

### 9. `soldCount` 两条写入路径口径不一致（评估✅ · 已修复）
- 合同交付（`_apply_item_delivery`）：repeatSale 与否一律 `soldCount += 1`；
- 手动出库（`create_outbound`）：仅 `repeatSale` 分支 `soldCount += 1`。

撤销回退（`_revert_outbound_inner` FIX-3）虽按「创建做了啥逆做啥」对齐，但同一「累计销售次数」指标在不同入口统计口径不同，页面数字与业务直觉可能不符。
- 位置：`backend/src/services.py:694-697` vs `1074-1082`、`1122-1128`。

### 10. 含「待关联资产」行的合同可直接置 delivered（评估✅ · 已修复）
合同交付分支只处理 `locked/confirmed` 明细，`pending_asset` 行被跳过，但合同随即标记 delivered、项目状态派生为「已完成」——存在「已完成项目下挂着待关联资产明细」的悬挂状态（手动建项目路径可传 `assetId=null` 产生 pending 行）。
- 位置：`backend/src/services.py:892-901`（`_change_contract_status_core` delivered 分支）。
- 评估修正：触发需手动调 API 传 `assetId=null`（`ProjectItemInput.assetId` 允许 null）；前端正常下单/购物车链路不产生此类行，属 API 层可达的悬挂状态。

### 11. 删除用户不清理其购物车行（评估✅ · 已修复）
`delete_user` 只删 users 行，该用户的 `cart_items` 成为永久孤儿数据。
- 位置：`backend/src/routers/api.py:122-134`。

### 12. `GET /bootstrap` 是读接口却有写副作用（评估✅ · 已修复）
每次 bootstrap 都对全部资产做交付物惰性初始化并 `db.commit()`。在 SQLite 单写模型下，高并发浏览时读接口会抢写锁。
- 位置：`backend/src/services.py:1697-1701`（`bootstrap`）。
- 评估修正：实际写库仅发生在某资产交付物尚未初始化时（`_init_asset_deliverables` 有短路），但 `db.commit()` 本身每次 bootstrap 无条件执行，读接口持写事务的隐患成立。

### 13. 删除上传文件不检查引用（评估✅ · 已修复）
`DELETE /upload/{filename}` 不校验该文件是否仍被资产的 `featureDoc` / `contractFile` 引用，删除后资产详情页预览/下载直接 404（目前前端未暴露该入口，属 API 层隐患）。
- 位置：`backend/src/routers/api.py:544-555`。

## 三、轻微 / 设计脆弱点

### 14. `PUT /cart/{id}` 用 `qty <= 0` 表示「删行」（评估✅ · 已修复）
同一接口兼具「改数量」与「删除」两种语义，任何调用方漏传 qty（router 默认取 0）就会误删行。前端已靠 `setCartAmount` 回传当前 qty 的防御性写法绕开（`frontend/src/api/index.ts:660-663` 注释），但接口本身脆弱。
- 位置：`backend/src/services.py:1461-1487`（`set_cart_qty`）、`backend/src/routers/api.py:330-336`。

### 15. 遥感明细判重只在 Python 层（评估✅ · 已修复）
`_rs_item_dup` 无 DB 唯一约束，并发下可插入重复明细；`cart_items` 的 `(userId, assetId, itemId, customer)` 复合唯一键同理无 DB 约束。
- 位置：`backend/src/services.py:393-411`、`backend/src/models.py:344-363`（`RsItem`）。

### 16. 文件预览走 `?token=<jwt>` 查询参数（评估✅ · 保持现状）
JWT 会出现在 URL 中（访问日志 / Referer 泄露风险）；且所有三角色均可下载任意上传文件，无归属隔离（代码注释已声明为 iframe/img 无法带请求头的取舍）。
- 位置：`backend/src/routers/api.py:506-541`（`get_file_user` / `get_file`）。

### 17. 登录接口无频率限制/失败锁定（评估✅ · 已修复）
叠加默认密码 `admin/123456`（README 已提示生产必改），内网环境下存在撞库风险。
- 位置：`backend/src/routers/api.py:48-58`。

### 18. `update_project` 无字段级校验（评估✅ · 已修复）
项目名可被清空为空串（`ProjectInput.name: str` 无 `min_length`），`update_project` 直接覆盖。
- 位置：`backend/src/schemas.py:176`、`backend/src/services.py:815-847`。

## 修复优先级建议（历史）

若只修 3 个，优先：
1. **#1** 金额口径错误——直接影响首页/板块经营数据展示；
2. **#2** 无校验的资产编辑接口——可被传非法值破坏库存不变量；
3. **#6** 加购幂等误判——普通下单链路上的确定性 400。

## 修复记录（2026-10-16，全部完成）

**结果：18 项中 17 项已修复并逐项冒烟验证，#16 评估后保持现状（设计取舍，修复会破坏现有功能）。** 约束：不改前端 UI 布局与展示字段，仅改代码逻辑；正常功能回归通过。

- 后端 15 项（#2–#15、#17、#18 中的后端部分）：详见 `docs/backend/changelog.md` 同日条目（BUG-A ~ BUG-O），影响文件 `backend/src/services.py`、`schemas.py`、`routers/api.py`、`security.py`、`models.py`、`backend/main.py`。
- 前端 2 项（#1、#8）+ 1 项顺带修复：详见 `docs/frontend/changelog.md` 同日条目——#1 `types.ts availableValue` 排除 amount 模式；#8 下单对话框 unit 模式合同金额改只读；另修复 `cart/index.vue` 存量 TS 类型错误（非本轮引入，git stash 对照确认），`npm run build` 由失败恢复为 0 error 通过。
- **#16 保持现状**：`?token=<jwt>` 通道与文件无归属隔离为既有取舍（iframe/img 无法带请求头、viewer 需预览资产附件），已知风险见后端 changelog「保持现状说明」。
- 验证：临时库（/tmp/cho_smoke.db）逐项 curl 冒烟全过（状态判定/422/库存下限/加购幂等/批量原子回滚/soldCount 互逆/pending 拦截/删行语义/删用户清理/文件引用/登录 429/空项目名）；生产库（8000 --reload）已自动重载并成功建立 `uq_rs_items_dim`/`uq_cart_items_key` 唯一索引（存量无重复数据）；前端 `npm run build` 通过。
- 行为变更提示（有意为之，均与清单结论一致）：`PUT /cart/{id}` qty≤0 由删行改 400；手动出库 soldCount 口径改为与合同交付一致（一律计次）；含 pending 明细的合同/项目交付被 400 拦截；`PUT /assets/{id}` 非法入参由静默落库改 422。

## 子 Agent 独立评估记录（2026-10-16）

独立评审方式：code-explorer 子 Agent 只读代码、不信任本清单描述，逐条读源码取证后给出结论。

**结论：18 条全部成立，无一条误报**；文件/行号定位经逐一比对全部准确。其中 4 条存在轻微描述偏差（#1 / #7 / #10 / #12），已在对应条目下以「评估修正」标注，均不影响结论。

| 编号 | 结论 | 一句话理由 |
|---|---|---|
| #1 | ✅ 成立 | `availableValue` 无 pricingMode 过滤，amount 模式卫星Token（seed 确有 3 条）必被计入；偏差：seed 的 quantity 是「颗」，数量级虚高仅适用于按原始 Token 个数入库的用户新建资产 |
| #2 | ✅ 成立 | `PUT /assets/{id}` 收裸 dict（api.py:181），`update_asset` 对 quantity/salePrice 无类型/范围校验直接 setattr，负数/字符串可落库 |
| #3 | ✅ 成立 | `create_asset` 用 `status=data.status` 且全函数无 `refresh_status`；前端恒传 `in_stock`；bootstrap 等任何路径均不纠正 |
| #4 | ✅ 成立 | 出库单 `operator=data.operator or "admin"` 取前端入参，而流水/日志/审计用路由层真实 `user.username`，两表操作人可不一致 |
| #5 | ✅ 成立 | `update_asset` 无 `quantity ≥ lockedQty+shippedQty` 下限校验，可售可被改负，前端 `Math.max(0,…)` 夹零掩盖 |
| #6 | ✅ 成立 | 明细行 repeatSale=false 时校验用「含该行自身的 total_in_cart + 本次 qty」，幂等合并场景 double-count，可售恰为 1 时二次点击 400 |
| #7 | ✅ 成立 | 批量循环逐条调 `add_to_cart`（内部 commit）不原子；偏差：多数失败为软跳过，硬 400 主要经 amount 模式金额校验触发 |
| #8 | ✅ 成立 | 对话框合同金额可改写并提交，但 `_create_project_core` 恒置 `contractAmount=0` 后按 price×qty 派生，用户改值被静默丢弃且无提示 |
| #9 | ✅ 成立 | `_apply_item_delivery` 一律 soldCount+1（:695），`create_outbound` 仅 repeatSale 分支 +1（:1076）；FIX-3 回退确与两条创建路径互逆 |
| #10 | ✅ 成立 | delivered 分支只处理 locked/confirmed（:895），pending 行被跳过但合同仍置 delivered、项目派生「已完成」；偏差：需手动 API 传 assetId=null 触发 |
| #11 | ✅ 成立 | `delete_user` 仅删 users 行，无 cart_items 清理，该用户购物车行成永久孤儿 |
| #12 | ✅ 成立 | `bootstrap` 无条件 `db.commit()`（:1701）；偏差：实际写库仅在交付物未初始化时发生 |
| #13 | ✅ 成立 | `DELETE /upload/{filename}` 不检查 featureDoc/contractFile 引用即 `os.remove`，删除后资产预览 404；前端确未暴露该入口 |
| #14 | ✅ 成立 | router `int(request.get("qty", 0))` 缺省 0，`set_cart_qty` 对 `qty<=0` 执行 `db.delete`，漏传即误删行；前端 `setCartAmount` 已靠回传 qty 防御 |
| #15 | ✅ 成立 | `_rs_item_dup` 与购物车判重均仅 Python 层查询，`RsItem`/`CartItem` 模型均无 DB 唯一约束，并发可插重复 |
| #16 | ✅ 成立 | `get_file_user` 支持 `?token=<jwt>` 查询参数通道；文件端点仅要求已认证，三角色可下载任意上传文件，无归属隔离 |
| #17 | ✅ 成立 | `login` 无失败计数/锁定/限流，仅记审计后 401；默认 `admin/123456`（main.py seed、README 已提示）属实 |
| #18 | ✅ 成立 | `ProjectInput.name: str` 无 min_length，`update_project` 直接 setattr 覆盖，传空串即可清空项目名 |
