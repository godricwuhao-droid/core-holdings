# 业务逻辑 Bug 排查清单（2026-10-20）

排查性质：**只读审查**，未修改任何代码与数据；数据库仅用 `mode=ro` 连接核对现状。

排查范围：

- 后端：`backend/src/services.py`（业务规则核心）、`routers/api.py`、`models.py`、`schemas.py`、`security.py`、`main.py`
- 前端：`src/api/index.ts`、`types.ts`、`views/cart/index.vue`、`components/SalesOrderDialog.vue`、`views/sales/projects/{index,create,detail,review}.vue`、`views/sales/outbound/index.vue`、`views/assets/{list,create,detail}.vue`、`router/index.ts`、`layouts/MainLayout.vue`
- 数据：`backend/core_holdings.db`（28 产品 / 2 项目 / 8 合同 / 9 明细 / 0 交付记录 / 386 日志 / 150 流水）

> 状态标记：⬜ 待修复 / ✅ 已修复 / ❌ 评估为误报

## 结论摘要

| 编号 | 级别 | 问题 | 直接影响 |
|---|---|---|---|
| 1 | 高危 | 生态人员写操作被前端拦截器全部拦截 | 编辑/取消/终止/交付/重新提交全部不可用 |
| 2 | 高危 | 补录交付错误扣减 `lockedQty` | 交付后可售不减少、侵占他人锁定、可超卖 |
| 3 | 高危 | 购物车同产品多客户被合并成一条销售记录 | 客户归属与金额串账 |
| 4 | 中 | Token 包量定价的数量/单价/派生价三套量纲不一致 | 参考价展示错误、审核后跳变、免填金额可能错 1e4 倍 |
| 5 | 中 | 合同交付「经办人」写成生态人员，不是实际操作人 | 业务表与审计表操作人不一致 |
| 6 | 中 | viewer 可通过 `/bootstrap` 获取全量交付记录/流水/日志 | 跨客户信息泄露 |
| 7 | 中 | 合同内同产品多明细时，撤销交付可能还原错行 | 再交付重复计收入 |
| 8 | 轻 | 产品类型可编辑但 `pricingMode` 不重算 | 计价模式与产品类型脱钩 |
| 9 | 轻 | 补录交付缺少项目/产品归属校验 | 绕过审核、容器被误交付 |
| 10 | 轻 | `rep` 字段混存账号与姓名 | 筛选重复、统计拆分 |
| 11 | 轻 | 驳回覆盖合同原备注 | 备注丢失 |
| 12 | 轻 | UI/口径一致性问题（5 小项） | 展示误导 |
| 13 | 轻 | 接口层校验缺口（3 小项） | 可构造脏数据 |

---

## 一、高危

### 1. 生态人员（viewer）的编辑 / 取消 / 终止 / 交付 / 重新提交全部被前端拦截 ⬜

**现象**：后端已为 viewer 放开「编辑自己项目、终止自己项目（含取消待审核单）、重新提交、交付」，页面按钮也都展示（`views/sales/projects/detail.vue:34` `canOwn = canWrite || isViewer`；`create.vue:818-825`），但点击后统一弹「只读账号…」，请求不会发出。

**证据**：axios 请求拦截器的 viewer 白名单只有购物车和直接下单，未覆盖项目/合同写接口。

```59:81:frontend/src/api/index.ts
const VIEWER_ALLOWED_REQUESTS: { method: string; pattern: RegExp }[] = [
  { method: 'post', pattern: /^\/cart\/?$/ },
  { method: 'post', pattern: /^\/cart\/batch$/ },
  { method: 'post', pattern: /^\/cart\/checkout$/ },
  { method: 'put', pattern: /^\/cart\/\d+$/ },
  { method: 'patch', pattern: /^\/cart\/\d+$/ },
  { method: 'delete', pattern: /^\/cart\/\d+$/ },
  { method: 'delete', pattern: /^\/cart$/ },
  { method: 'post', pattern: /^\/sales\/order$/ },
]
...
if (config.method && config.method !== 'get' && currentUser.value?.role === 'viewer') {
  const allowed = VIEWER_ALLOWED_REQUESTS.some(
    (r) => r.method === config.method && r.pattern.test(url),
  )
  if (!allowed) return Promise.reject(new Error(READONLY_TIP))
}
```

缺失的四个端点（后端均为 `require_order`，已允许 viewer 操作自己项目）：

- `PUT /projects/{id}`（编辑基本信息）
- `PATCH /projects/{id}/status`（取消待审核单 / 终止项目）
- `PATCH /contracts/{id}/status`（交付 / 终止销售记录）
- `POST /projects/{id}/resubmit`（重新提交）

**影响**：viewer 的「编辑 / 取消订单 / 终止 / 交付 / 重新提交」全部失效。后端 changelog 中「viewer 编辑自己 pending 200 / 终止释放锁定」的验证是直接调用 API，绕过了前端拦截，所以未被发现。当前库有 3 个启用中的 viewer 账号（`lshangkun`、`viewer`、`zhaoyin2`）。

**建议方向**：在白名单补齐上述端点；更稳妥的做法是**移除前端角色白名单**，统一由后端 `require_order` / `require_editor` 守卫兜底，避免两套权限清单再次漂移。

---

### 2. 「补录交付」错误扣减 `lockedQty`：交付后可售不减少、侵占其他订单锁定、可超卖 ⬜

**现象**：手动新建交付（交付记录页「补录交付」）并未关联到某条订单明细，也没有释放过对应的锁，却直接从 `a.lockedQty` 里扣减。

```1412:1418:backend/src/services.py
    if data.mode != "history":
        # 口径统一（与 _apply_item_delivery 对齐）：交付即一次销售，soldCount 一律 +1
        a.soldCount += 1
        if not a.repeatSale:
            a.lockedQty = max(0, a.lockedQty - data.qty)
            a.shippedQty += data.qty
```

按「可售 = 总数 − 锁定 − 已交付」，一减一加后**可售量完全不变**：交付掉的数量仍可再次售卖。

**推演**（产品总数 10、单次售卖）：

| 步骤 | lockedQty | shippedQty | 可售 | 说明 |
|---|---|---|---|---|
| 初始：待审核订单锁 5 | 5 | 0 | 5 | 正常 |
| 补录交付 2 | 3 | 2 | **5** | 应为 3（已交付 2 台） |
| 再下单 5 | 8 | 2 | 0 | 累计承诺 5+5+2=12 > 10，已超卖 |
| 两单都交付 | 0 | 10 | 0 | `min(quantity, …)` 把超出的 2 台夹掉，报表无异常 |

若不做后续下单、直接撤销这 2 台补录交付：`locked` 仍为 3、`shipped` 回到 0 → 可售 7（交付前是 5），**凭空多出 2 台**。

```777:777:backend/src/services.py
a.shippedQty = min(a.quantity, a.shippedQty + it.qty)
```

**影响**：库存账实不符、同一批货被卖给两个客户；超卖被 `min` 夹零掩盖，事后难发现。撤销补录交付还会凭空增加可售量。

**建议方向**：手动交付（无 `contractId`）只应 `shippedQty += qty`，不得触碰 `lockedQty`；若需要支持「对某项目交付」，应落到具体明细（`ProjectItem`）并走 `_apply_item_delivery`，同时校验明细归属与订单状态（见 9）。

---

### 3. 购物车同一产品、不同客户，结算时被合并成一条销售记录 ⬜

**现象**：结算分组键只有 `assetId`，合同 `customer` 取分组第一行的客户，同一产品的其他客户行被吞并。

```2008:2011:backend/src/services.py
        groups.setdefault(c.assetId, []).append((a, c.qty, amt, None, customer))
...
    # 每组（产品）→ 一条销售记录（ADR-013：一资产一记录，customer 取该行行级客户）
```

```2035:2036:backend/src/services.py
        contracts_in.append(schemas.ContractInput(
            customer=rows[0][4], items=items, contractAmount=float(total.quantize(CENT)), remark="",
```

**复现**：购物车加同一产品两次（第一次设为客户 A；再次加购生成新行后设为客户 B），结算：

- 前端预览按**客户**分组，提示「将生成 2 份销售记录」：

```87:101:frontend/src/views/cart/index.vue
const previewGroups = computed(() => {
  const groups: { customer: string; qty: number; amount: number }[] = []
  const idx = new Map<string, number>()
  for (const r of cartRows.value) {
    const customer = (r.cart.customer ?? '').trim()
    if (!customer) continue
    const i = idx.get(customer)
    ...
  }
```

- 后端实际只生成 1 条记录，客户 = A，B 的数量/金额全部记到 A 名下；项目派生客户也只剩 A。

**影响**：客户归属、对账、提成统计全部错乱；用户看到的预览与落库结果不一致。

**建议方向**：分组键改为 `(assetId, customer)`（与 ADR-013「一资产一记录」组合成「一资产一客户一记录」），并把前端预览口径改为同一维度；若业务上要求同资产只能一个客户，则应在加购/改客户时就拒绝，而不是结算时静默合并。

---

## 二、中等

### 4. Token 包量定价的「数量 / 参考单价 / 派生价」三套量纲互不一致 ⬜

**现象**：同一 Token 产品上同时存在三种口径：

| 环节 | 口径 | 证据 |
|---|---|---|
| 产品登记 | 数量 = 原始 Token 个数；单价标注「元/万Token」 | `views/assets/create.vue:260-311`（数量按原始个数登记）、`list.vue:308-311`（`¥salePrice/万Token`） |
| 实际订单 | 明细 qty=1（按「1 份/颗」卖） | DB：`assets.id=6` quantity=300,000,000；`SP-2026101923283410` 的明细 qty=1、amount=582,000 |
| 派生参考价 | 前端 `amount ÷ qty ÷ 1e4`；后端 `amount ÷ qty` | 见下 |

```504:507:frontend/src/types.ts
export function derivedUnitPrice(amount: number, qty: number): string {
  if (!amount || !qty) return '-'
  return `${(amount / qty / 1e4).toFixed(4)} 元/万Token`
}
```

```179:181:backend/src/services.py
def _derived_price(amt: Decimal, qty: int) -> float:
    """ADR-008：amount 模式派生展示单价 price = round(amount / qty, 6)（不参与金额计算）"""
    return float((amt / qty).quantize(Decimal("0.000001")))
```

审核确认改价时，后端把 `_derived_price`（元/Token）直接写回 `assets.salePrice`：

```1019:1022:backend/src/services.py
                amt = _validate_amount_yuan(ri.amount)
                it.amount = float(amt)
                it.price = _derived_price(amt, it.qty)  # 派生参考单价（元/个）反算展示
                price_changes_by_asset[it.assetId] = it.price
```

**具体失真**（当前库 `CH-SAT-001`）：

- `quantity=300,000,000`、`salePrice=33,333.33`（页面按元/万Token 展示，隐含总价 ≈ 10 亿元）
- 实际订单：`qty=1`、`amount=582,000`
- 项目详情派生单价：`582000 / 1 / 1e4 = 58.2 元/万Token`
- 若按登记口径 `qty=3 亿`：`582000 / 3e8 / 1e4 = 0.0000 元/万Token`
- 审核改价后写回：`salePrice = 582000`，页面显示 `¥582000/万Token`

**连带风险**：生态人员免填金额时按 `salePrice × qty` 兜底（`cart/index.vue:44`、`services.py:2006`），两个不同量纲直接相乘，金额可能放大或缩小 1e4 倍。

**建议方向**：先由业务拍板唯一口径（建议：数量=原始 Token 个数、单价=元/万Token），然后：

1. 派生价统一为 `amount / qty × 1e4`；
2. 审核回写 `salePrice` 时同样换算成元/万Token；
3. 免填金额兜底改为 `salePrice × qty / 1e4`；
4. 清理/迁移存量 Token 资产与订单数据（当前库已有 qty=1 与 qty=3 亿混存）。

---

### 5. 合同交付记录的「经办人」写成生态人员/下单人，不是实际操作人 ⬜

**现象**：合同交付由商务点击，但生成的 `Outbound.operator` 取的是 `project.rep`；交付记录页「经办人」列直接展示该字段。

```788:794:backend/src/services.py
        ob = models.Outbound(
            ...
            operator=(project.rep if project else "") or "admin",
```

```324:324:frontend/src/views/sales/outbound/index.vue
<el-table-column prop="operator" label="经办人" width="100" align="left" />
```

补录交付弹窗里还有一个「经办人」输入框（`outbound/index.vue:411`），但后端明确不采信 `data.operator`（`services.py:1407-1409` 注释与实现），字段无效。

**影响**：交付记录经办人与审计日志（真实登录账号）不一致；无法据此追溯实际操作人。建议传 `_apply_item_delivery(..., operator=user.username)`，并移除前端无效的经办人输入框。

---

### 6. viewer 可通过 `/bootstrap` 获取全量交付记录、流水、操作日志 ⬜

**现象**：`bootstrap` 对 `projects/contracts` 做了 viewer 可见性过滤，但 `outbounds / flows / logs` 全量返回。

```2119:2125:backend/src/services.py
    if user is not None and user.role == "viewer":
        projects = [p for p in projects if user_sees_project(user, p)]
        visible_project_ids = {p.id for p in projects}
        contracts = [c for c in contracts if c.projectId in visible_project_ids]
    outbounds = db.execute(select(models.Outbound).order_by(models.Outbound.id.desc())).scalars().all()
    flows = db.execute(select(models.AssetFlow).order_by(models.AssetFlow.id.asc())).scalars().all()
    logs = db.execute(select(models.OpLog).order_by(models.OpLog.id.asc())).scalars().all()
```

**影响**：viewer 直接请求 `/api/bootstrap` 即可看到全部客户的交付记录（客户名、数量、金额）、关联合同号的流水，以及包含客户/项目信息的操作日志，与「仅自己下单的项目可见」口径冲突。

**建议方向**：viewer 返回 `outbounds` 按 `projectId ∈ visible_project_ids`（含 `contractId` 对应合同）过滤；`flows/logs` 至少过滤掉含其他客户/合同引用的记录（或对 viewer 只返回本人项目相关部分）。同时注意 `/users/options/all` 也会暴露全部账号（影响较小）。

---

### 7. 合同内同产品多明细时，撤销交付可能还原错行，再交付会重复计收入 ⬜

**现象**：`Outbound` 只存 `contractId + assetId`，撤销时用 `limit(1)` 猜明细；同一合同里同一产品有多条明细（例如两条遥感明细，`assetId` 相同、`itemId` 不同）时会取错行。

```1455:1461:backend/src/services.py
        if ob.contractId is not None:
            it = db.execute(
                select(models.ProjectItem).where(
                    models.ProjectItem.contractId == ob.contractId,
                    models.ProjectItem.assetId == ob.assetId,
                ).limit(1)
            ).scalars().first()
```

```1483:1497:backend/src/services.py
        if restore_contract and it is not None and it.status == "shipped":
            if it.locked and not eff_repeat:
                apply_item_lock(db, it.assetId, it.qty, True, ob.code, ...)
            it.status = "locked"
            it.shippedDate = ""
            c = db.get(models.Contract, ob.contractId)
            if c is not None and c.status == "delivered":
                c.status = "active"
                ...
                contract_restored = True
```

**推演**：合同含两行同父产品明细 A、B（各 qty=1）。撤销 B 的交付时取到 A（A 已 shipped）→ A 被改回 `locked`，B 仍是 `shipped`，合同回到 active。再次交付该合同时，只处理 `locked/confirmed` 明细 → **A 被重复交付**，`soldCount/soldAmount` 再累加一次；`shippedQty` 被 `min(quantity, …)` 夹住，报表看不出来。

**建议方向**：`Outbound` 增加 `itemId`（或 `projectItemId`），撤销时按明细精确定位；存量记录可按 `contractId + assetId + 未撤销` 一一配对迁移。

---

## 三、轻度 / 一致性

### 8. 产品类型可编辑，但 `pricingMode` 不随之重算 ⬜

- `update_asset` 的 allowed 字段包含 `type`（`services.py:330`），但 `pricingMode` 只在新建时按类型决定（`services.py:258`），且不在可更新白名单内。
- 前端编辑模式用存量 `pricingMode` 判断表单形态（`create.vue:74-76`），产品类型下拉在编辑时**未禁用**（`create.vue:260-263`，仅所属板块禁用）。

**后果**：Token → 机器人后仍走 amount 模式（表单继续显示「参考单价（元/万Token）」，后端强制整数金额、忽略单价×数量）；机器人 → Token 则仍按 unit 模式计价。建议编辑禁用类型，或按类型重算 `pricingMode` 并做数据迁移。

### 9. 补录交付缺少项目/产品归属校验 ⬜

`create_outbound`（`services.py:1380-1425`）只校验产品存在与可售数量，未校验：

- 所选项目状态（前端下拉仅排除 terminated，pending 也可选，`outbound/index.vue:89-91`）→ 可在审核前直接产生交付与销售额；
- 产品是否属于该项目明细 → 任意产品可挂任意项目（`services.py:1385-1391` 只在明细存在且全部交付时拦截）；
- 产品是否遥感容器 → 容器本身可被交付（`shippedQty=1`），之后所有单次售卖明细都不可再卖。

### 10. `rep` 字段混存账号与姓名 ⬜

- 下单弹窗写姓名：`form.rep = currentUser.value?.name`（`SalesOrderDialog.vue:156`）
- 建单页写账号：`value=username`（`create.vue:313-320`）
- 当前库证据：项目 1 `rep=lshangkun`，项目 2 `rep=刘尚坤`

列表筛选选项直接收集原始 `p.rep`（`index.vue:99-103`），同一个人会出现两个同名选项（值不同），筛选和按生态人员统计会被拆开。显示层 `repName` 能兜住，但数据口径未统一。

### 11. 驳回覆盖合同原备注 ⬜

```979:979:backend/src/services.py
            c.remark = f"驳回：{reason}"  # 留痕：生态人员经 bootstrap 仍可见驳回原因
```

原合同备注（下单时的说明）被直接覆盖。建议改为追加（如原备注 + 换行 + 驳回原因），或单独的驳回原因字段。

### 12. UI / 口径一致性问题（小项）

1. **空客户合同显示「N 位客户」**：`customerText` 在项目客户为空时回退 `contracts.length`（`projects/detail.vue:92-98`），空草稿/空客户合同会显示「1 位客户」。
2. **资产详情「销售关联」的生态人员仍是裸账号**：`detail.vue:798` 直接输出 `row.project.rep`，未走 2026-10-20 的账号→姓名映射（本次只修了 4 个项目页面）。
3. **建单页合同内仍强制同一产品主体**：`create.vue:196-199` 仍预校验，但后端已在 ADR-013 移除该限制（`services.py:673` 注释、`_normalize_contracts` 无主体校验），页面注释「后端 400 兜底」已失效 → 手工混合主体合同只能走 API。
4. **手工改的合同金额在审核确认时被重算丢弃**：建单页允许手改 `contractAmount`（`create.vue:169-170, 886`），但 `review_project` confirm 按 Σ 明细金额重算（`services.py:1036-1038`），覆盖值静默失效。
5. **补录交付「经办人」输入框无效**：见问题 5。

### 13. 接口层校验缺口（小项）

1. `OutboundInput.qty` 仅 `ge=0`（`schemas.py:279`），`POST /outbounds` 传 `qty=0` 可通过：仍 `soldCount+1`、累加 `soldAmount`，生成 0 数量交付记录。建议服务层校验 `qty > 0`。
2. 客户为空可通过 API 建单：`_create_project_core` 未校验合同 `customer` 非空（前端有校验），会生成客户为空的记录，详情显示「N 位客户」。
3. 遥感容器可通过 API 直接加购/下单：`_cart_add_inner` / `_order_core` / `_create_project_core` 均未拒绝 `type='遥感数据'` 的父产品（UI 隐藏了入口），可生成 0 元且无法确认的单据（确认守卫会拦截，只能终止/删除）。

---

## 四、数据核验附录

只读查询结果（`mode=ro`）：

```text
assets.id=6  CH-SAT-001  宏大卫星（26年10月发射）  卫星Token
  unit=个  quantity=300000000  salePrice=33333.33  pricingMode=amount
  锁定 lockedQty=1（来自待审核订单明细 qty=1）

projects:
  SP-2026101923283410  pending     creator=lshangkun  rep=lshangkun  owner=wuhao  amount=766,623
  SP-2026102000070403  terminated  creator=lshangkun  rep=刘尚坤       owner=wuhao  amount=610,000

users: 2 admin / 3 editor / 3 viewer（均启用）
outbounds: 0 条（补录/交付问题尚未在库中留下数据）
```

> 注：项目 1/2 的 `rep` 同时出现账号与姓名，即问题 10 的实证。

---

## 五、建议修复顺序

1. **问题 1**（前端白名单）—— 一行改动即可恢复 viewer 全部功能，风险最低、收益最大。
2. **问题 2**（补录交付库存口径）—— 先止血，避免继续产生超卖；同时排查是否需要修复已产生的数据（当前库 `outbounds=0`，尚无历史脏数据）。
3. **问题 3**（结算合并）—— 影响客户归属与金额，修复前建议在页面提示「同产品请合并为一个客户」。
4. **问题 4**（Token 口径）—— 需业务先拍板唯一口径，再改公式 + 回写 + 存量迁移。
5. 问题 6（bootstrap 过滤）、5（经办人）、7（撤销精确匹配）。
6. 其余按迭代处理。

## 六、未重复报告

- `docs/business-logic-bugs-20261016.md` 的 18 项已全部修复，未重复。
- `review_project` 的空明细 / 未关联产品守卫（S1/S2）当前已存在，未列为问题。
- 文件预览 `?token=`、登录限流等安全项此前已评估，保持现状。

---

**说明**：本文档仅记录排查结果，未对代码或数据库做任何修改。
