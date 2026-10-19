# 后端变更日志

> 记录 core-holdings 后端（FastAPI + SQLAlchemy + SQLite）的接口与行为变更。

## 2026-10-20 ｜ 新增：GET /users/options/all 全量启用账号（含生态，仅供显示映射）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `GET /users/options/all`（`get_current_user`）：返回**全部启用账号**（admin/editor/viewer）——供项目页「账号 → 姓名」显示映射（生态 rep 列/编辑页生态人员下拉）；原 `/users/options`（仅商务）保持不动，继续供商务负责人筛选与接手/转交下拉（订单不得转给生态） | `src/routers/api.py` |

**根因背景**：前端 4 个项目页的显示映射误用了商务专属 `/users/options`，生态账号查不到 → 列表「生态人员」列裸账号外露、编辑页生态人员下拉选不到人。

### 验证

- 实测：`/users/options/all` 返回 8 账号含 3 个 viewer（lshangkun 等）✓；`/users/options` 仍 5 个商务 ✓；`py_compile` 0。

## 2026-10-20 ｜ 新增：POST /projects/{id}/resubmit 重新提交（旧单留痕 + 新建 pending 订单）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `POST /projects/{id}/resubmit`（`require_order`，生态/商务/管理员）：已终止项目（驳回/取消/终止）按**可修改的**明细（`ProjectInput` 原结构）复用 `_create_project_core` 新建 pending 项目（新编号、重新锁量、走完整接手审核流程），creator=当前账号；守卫：源项目须 `terminated`（400）、viewer 仅 `creator==自己`（403，`user_sees_project` 同口径） | `src/services.py`（`resubmit_project`）, `src/routers/api.py` |
| 2 | 新增 | 双向留痕：新单 remark 前置「重新提交自 旧编号（旧名）」；旧单 remark 追加「已重新提交为 新编号（新名）」；写「重新提交」操作日志 | `src/services.py` |

**设计口径（用户拍板）**：重提=预填重新下单，旧项目**不复活**（terminated 历史保留、驳回原因可查）；「已终止不可编辑」规则不变（编辑接口仍拒绝 terminated）。

### 验证

- 冒烟（真实 API，已清理）：下单→驳回→`resubmit`（改数量 2→3）→ 200 新单 pending、creator 正确、双向备注 ✓；viewer 重提他人单 403 ✓；pending 项目 resubmit 400 ✓；`py_compile` 0。

## 2026-10-20 ｜ 修改：审核 confirm 放开遥感明细行改价（仅本行金额，不回写主数据）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `review_project` confirm：遥感明细行（`itemId` 非空）原一律 400 → 接受 `amount`（整数元）——只改**本行** `amount`，`price` 派生反算（元/份）展示；**不进 `price_changes_by_asset`**（不写 `assets.salePrice`）、不改 `rs_items.price`（明细单价属产品「可售明细」主数据，订单级改价不污染）；订单日志 diffs 带「产品名·省/市 精度 月份」描述 | `src/services.py` |

### 验证

- 冒烟（真实 API，已清理）：下单 2 遥感行 → 接手 → confirm 改 1 行 330000→350000 → 200；本行生效、`rs_items.price`/`assets.salePrice` 均不变、项目 active ✓；`py_compile` 0。

---

## 2026-10-19 ｜ 修改：生态可终止自己待审核订单（取消订单）+ 修复 pending 合同终止漏释放锁定

**关联任务**：用户要求生态人员可终止项目（非删除、记录留存、终止后不可编辑）——其典型场景是取消自己刚下的待审核订单。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `change_project_status`：pending 守卫开例外——**下单生态人员（creator==自己）可终止自己的待审核订单**；商务/管理员对 pending 仍只能走订单审核接口（确认/驳回），不可绕过审核直接改状态 | `src/services.py` |
| 2 | 修改 | 批量目标集合：pending 项目终止时 targets = pending 合同（原仅 active）；文案/日志同步 | `src/services.py` |
| 3 | **修复** | `_change_contract_status_core` 终止分支原仅处理 active（释放锁定）/delivered（回退交付）——**pending 合同终止会漏释放锁定**（量永久占着）；改为 `from_status in ("active", "pending")` 均释放 | `src/services.py` |

生态编辑自己项目（PUT）此前已放开（仅 rep 不可改），本轮前端 `canEditForm` 对齐。

### 验证

- 冒烟：viewer 编辑自己 pending 200；viewer 终止自己 pending → 项目/记录 terminated、**锁定释放（lockedQty=0）**；wuhao（负责人）项目级终止 pending → 400 ✓；`py_compile` 0。

---

## 2026-10-19 ｜ 修改：废弃「报价金额/已回款」字段（用户确认无用）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `ProjectInput.quoteAmount/paidAmount` 改**可选**（`Field(default=0, ge=0)`）——前端不再提交这两字段，旧调用方传值仍兼容（建单时照旧入库） | `src/schemas.py` |
| 2 | 修改 | `update_project` 可写字段白名单移除 `quoteAmount`/`paidAmount`（不再写入；**存量值保留在库中不覆盖**，前端已无展示） | `src/services.py` |

### 验证

- 建单带旧字段 → 200（兼容）；PUT 不传两字段 → 存量值不变 ✓；`py_compile` 0。

---

## 2026-10-19 ｜ 排查修复：建单脏负责人漏洞 + 空草稿/悬挂明细可 confirm（子 Agent 全链路排查）

**关联任务**：用户要求派子 Agent 排查业务逻辑错误。对照「2026-10-19 规则基线」全量排查 sales 链路（services/routers/schemas 全文件），发现 1 个确定漏洞 + 2 个确认缝隙，已修；另记录 4 个低概率边缘问题（见下）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **建单入口 businessOwner 脏数据漏洞**：三个建单入口（checkout/sales/order/projects）原直接采信请求体 `businessOwner` 且零校验——viewer 可传不存在/已禁用/viewer 账号，导致单据**永久卡死 pending**（无人是「负责人」、无人可接手）。抽公共校验 `_validate_business_owner`（存在/启用/editor+admin，与 claim 转交同口径），`_create_project_core` 建单前调用；claim 内联校验改为复用 | `src/services.py` |
| 2 | 修复 | **空草稿 confirm 守卫**：0 明细项目（保存草稿）原可被 confirm 成 0 元 active 项目且可批量「交付」。confirm 前校验 `all_items` 非空 → 400 `该订单没有销售明细，请补充明细后再确认（或删除该草稿订单）` | `src/services.py` |
| 3 | 修复 | **悬挂明细 confirm 守卫**：`assetId=null`（pending_asset）明细行原可随 confirm 生效，之后交付恒 400 只能终止。confirm 前校验无 pending_asset 明细 → 400 `存在未关联产品的明细行，请先关联产品或删除该行再确认` | `src/services.py` |

### 验证（真实 API 冒烟，测试数据已清理）

- 建单传不存在/viewer 账号负责人 → 400 ✓；合法 editor → 200（owner=wuhao2）✓
- 空草稿 confirm → 400 ✓；悬挂明细 confirm → 400 ✓
- 回归：商务结算→pending→接手→改价确认→active ✓；viewer 自己 active 单 PUT ✓
- `py_compile` / `npm run build` / lint 全通过。

### 记录在案、暂不修复（低概率边缘场景，留待有需要时处理）

- **S3 review 并发竞态**：confirm 与 reject 交叉提交可产生「合同 active 但锁定已释放」→ 交付时出幽灵释放流水（需同毫秒级并发，SQLite 低频下概率极低）；
- **S4 claim 并发抢单**：两商务同时接手无主单均成功（最终态=后提交者，仅审计歧义）；
- **S5 同合同同产品双明细**（手动建单可造）逐条撤销交付时 `limit(1)` 可能漏重锁；
- **S6 repeatSale true→false 切换**后历史未锁明细交付可致可售为负（已知取舍的边界残留）。

---

## 2026-10-19 ｜ 修改：**所有角色建单统一进 pending 待审核流程**（ADR-012 决策点 2 修订，⚠️ 行为变更）

**关联任务**：用户反馈「wuhao（商务）直接下单后立即 active，接手了也改不了金额」——改价入口只存在于 pending 审核流程，而商务自建单永不进 pending。用户拍板：**所有人员创建的订单状态都是 pending 流程**，统一改价入口。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **`_create_project_core` 默认 `initial_status="active"` → `"pending"`**：购物车结算（`checkout`）、直接下单（`POST /sales/order`）、手动建单/草稿（`POST /projects`）**全部角色**一律建 pending（锁定/清空购物车等不变） | `src/services.py` |
| 2 | 修改 | `checkout` 移除角色分叉（原 `initial_status="pending" if viewer else "active"` → 恒 `pending`）；docstring/注释同步 | `src/services.py` |
| 3 | 不变 | 金额规则不变（viewer amount 行可免填回退挂牌价；商务/管理员金额必填）；接手/转交/审核/驳回/守卫全部零改动（pending 机制原已支持任意来源） | - |

### 验证（真实 API 冒烟，测试数据已清理、挂牌价已恢复）

- 商务（wuhao）购物车结算 → **pending** ✓（原 active）→ 接手 → 按 itemId 改价 800000 确认 → **active**、挂牌价写回 ✓
- 生态（viewer）结算 → pending ✓（不变）
- 商务直接下单 → **pending** ✓（原 active）
- admin 手动建单 → **pending** ✓（原 active）
- 非负责人确认他人 pending 单 → 400 ✓；接手+驳回 → terminated ✓
- `py_compile` / `npm run build` / lint 全通过。

### 影响提示

- 商务/管理员下单后需自己「接手 → 确认」（或转交他人）才生效；「保存草稿」建出的空单同样 pending，继续编辑前需先接手。
- 存量数据零影响（已 active 的项目不受影响）。

---

## 2026-10-19 ｜ 修复：businessOwner 越权重设漏洞 + pending 项目编辑权限收紧（ADR-012 §5.1 补漏，⚠️ 安全修复）

**关联任务**：用户实测发现「wuhao 转交给 wuhao2 后，wuhao 仍能编辑 + 编辑页还显示转交按钮」。排查发现三个问题：① **`PUT /projects/{id}` 会直接写入 `businessOwner` 入参**（任何商务改表单即可越权重设负责人，安全漏洞）；② pending 项目基本信息对全体商务开放编辑（后端无负责人守卫）；③ 编辑页底部「转交」按钮对他人单据的普通商务也显示（点击才被后端 400）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **`update_project` 移除 `businessOwner` 写入**：唯一写入口收敛为 claim（接手/转交）接口，PUT 入参同名值一律忽略（与派生字段同口径） | `src/services.py` |
| 2 | 新增 | **pending 编辑守卫**：`p.status == "pending"` 且非 viewer（viewer 已限定自己项目）且非 admin 且非负责人 → 400 `待审核项目仅商务负责人（或管理员）可编辑基本信息` | `src/services.py` |
| 3 | 修复 | 前端编辑页：新增 `canEditForm`（pending 且非负责人 → 整体禁用表单：名称/生态人员/日期/报价/回款/备注 + 「保存基本信息」按钮 tooltip 说明）；「商务负责人」输入框改**只读展示**（`editProject.businessOwner`）；底部「转交」按钮补条件 `(!businessOwner \|\| isAdmin)`（与 alert 区同口径） | create.vue |

### 验证（真实 API 冒烟 4 场景）

- wuhao（非负责人）PUT 改 owner → 400，DB owner 保持 wuhao2 ✓
- wuhao 仅改 remark → 400 ✓
- wuhao2（负责人）编辑 → 200 ✓
- admin PUT `businessOwner=zhaoyin` → 200 但 DB owner 不变（入参忽略）✓
- `py_compile` / `npm run build` / lint 全通过。

---

## 2026-10-19 ｜ 修改：转交语义修正为**纯移交制**（ADR-012 §5.1 修订，⚠️ 行为变更）

**关联任务**：用户指出原「转交=别人负责的单我抢过来归自己」（拉取式）语义反了——应为「我负责的单一转交给别人」（移交式）。决策确认：不能抢，仅负责人可转；admin 保留越过权。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **`claim_project` 纯移交制**：无主→任意商务/管理员接手（绑自己）；有主→**仅负责人**可转交（必传 `new_owner`，目标须启用商务/管理员账号、不能是自己）；admin 越过（接手/转交任意账号）；**非负责人普通商务 → 400** `该订单由商务负责人「X」负责，仅其本人可转交（如需介入请联系 admin 处理）`（原拉取式抢单废除） | `src/services.py` |
| 2 | 新增 | **`ClaimInput` 入参**：`POST /projects/{id}/claim` 可选 body `{"newOwner":"账号"}`（缺省空=接手给自己） | `src/schemas.py`, `src/routers/api.py` |
| 3 | 不变 | 审核守卫（review 仅负责人/admin）、终态 400、日志/审计格式（「转交订单 X → Y」）均不变 | - |

### 验证（真实 API 冒烟 9 场景，测试数据已清理）

- 无主单 editor 接手 ✓；wuhao 抢单（带/不带 newOwner）→ 400 ✓；负责人转给自己 → 400 ✓；转给 viewer（非商务角色）→ 400 ✓；负责人转给 wuhao ✓；admin 接手 ✓；admin 转给 editor ✓；admin 转给不存在账号 → 400 ✓。
- 注：测试用 wuhao 账号密码已重置为 `123456`（原密码未知，无法登录冒烟）。

---

## 2026-10-19 ｜ 修改：ADR-013 销售记录——一资产一条记录 + 多主体 + 文案改名（⚠️ 行为变更）

**关联任务**：同客户一次采购多家主体（供货公司）产品被「同主体」校验拦截（400 主体不一致）。业务澄清：单据非法律合同，称「销售记录」，每个资产的销售独立。2 个决策点与用户确认：① 一资产一条记录（遥感明细多行归父产品）；② 仅界面文案改名（代码/表名/HT 编号不变）。详见 `docs/adr/ADR-013.md`。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **`checkout` 分组键 customer → assetId**：每个产品一条销售记录（遥感明细行归父产品），customer=行级客户；**移除同主体校验**（同客户多主体=多条记录并列） | `src/services.py` |
| 2 | 修改 | **`_order_core`（直接下单）按产品拆记录**：移除同主体校验；按 assetId 分组 → 多条 `ContractInput`（customer=项目客户）；`ProjectInput` 改传 `contracts=` | `src/services.py` |
| 3 | 修改 | **`_create_project_core`**：移除「记录内同主体」校验（手动建单可混合主体）；记录 `subject` 派生 = 各行主体全一致→该值、混合→空（多主体记录） | `src/services.py` |
| 4 | 修改 | **`_recompute_project` 派生优化**：多记录但客户/主体全一致时仍取该值（原一律置空会误显「N 位客户」） | `src/services.py` |
| 5 | 修改 | **用户可见文案**：报错/操作日志/审计动作「合同」→「销售记录」、「合同金额」→「销售金额」（产品删除守卫、状态 API、审核、批量、交付/终止、撤销联动、新建日志共 20+ 处）；代码标识（`contracts` 表/`/contracts/` 路由/`contractAmount` 字段）全部不变 | `src/services.py`, `src/routers/api.py` |
| 6 | 不变 | 锁定/交付/审核/驳回/接手/转交均为行级逻辑零改动；审核改价按 assetId 写回挂牌价天然兼容；存量数据（多行合同）原样展示为「销售记录」，零迁移 | - |

### 验证（真实 API 全链路冒烟，测试数据已清理）

- viewer 同客户「优」加购 2 个**不同主体**产品（资产4 安徽天枢智算 + 资产13 四川蜂云星座）→ 结算成功：1 项目 `pending`、**2 条销售记录**（各自主体）、项目客户保留「优」、金额 959100=957100+2000 ✓（旧版此场景 400）；
- editor 接手 + 确认改价 900000 → active、挂牌价写回 900000、记录金额 900000/2000 ✓；
- 直接下单 2 个不同主体产品 → 项目 `active`、**2 条记录**（各自主体）✓；
- `py_compile` 通过、前端 build 0 error、lint 0。

---

## 2026-10-19 ｜ 新增：ADR-012 §5.1 商务接手机制（接手/转交 + 商务负责人账号关联查询）

**关联任务**：生态人员下单后由商务「接手」认领——businessOwner 自动绑定接手账号，仅该账号可改价/确认/驳回。3 个边界与用户确认：admin 可越过兜底（日志留痕实际操作人）；支持转交（接手人不可自行取消）；接手仅 pending、进行中仅可转交。详见 `docs/adr/ADR-012.md` §5.1。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **`POST /api/projects/{id}/claim`**（`require_editor`，`services.claim_project`）：pending 无负责人→**接手**（businessOwner=当前 username）；他人负责→**转交**（改绑，日志「X → Y」）；active 单同规则（仅转交/无主单可接手）；delivered/terminated 终态 400；已是自己 400。操作日志「接手订单/转交订单」+ 审计 | `src/services.py`, `src/routers/api.py` |
| 2 | 新增 | **`GET /api/users/options`**（任意登录用户）：返回 editor/admin 且 enabled 的账号（UserOut），供「商务负责人」筛选下拉与 username→姓名 展示映射（商务负责人与角色账号的关联查询）；存量自由文本值前端归「未指派/历史数据」档 | `src/routers/api.py` |
| 3 | 修改 | **review 接手人守卫**（`services.review_project` 新增 `user` 参数）：businessOwner 为空 → 400「该订单尚未被商务接手，请先接手后再操作」；操作人 ≠ businessOwner 且非 admin → 400「仅接手的商务负责人（X）可调整该订单价格，如需处理请先转交」；admin 可越过任意单（审计留痕实际操作人） | `src/services.py`, `src/routers/api.py` |
| 4 | 不变 | 接手不改变数量/锁定/合同状态，仅改 businessOwner + 日志；生态人员可见范围（creator 过滤）与订单上「商务负责人」展示不受影响 | - |

### 验证（真实 API 全链路冒烟，测试数据已清理）

- options 返回 4 个商务/admin 账号 ✓；viewer 下单 → pending；
- 未接手 editor 审核 → 400「尚未被商务接手」✓；editor 接手 ✓；重复接手 → 400「你已是该订单的商务负责人」✓；
- 非接手 editor 审核 → 400「仅接手的商务负责人（editor）…」✓；该 editor 转交 → 成功（日志「editor → u_test2」）✓；原接手人再审核 → 400 ✓；
- **非接手 admin 越过确认**（改价 33333）→ 成功，项目 active、挂牌价写回 33333 ✓；
- active 单再转交 → 成功（u_test2 → u_admin_x）✓；已确认单再审核 → 400 ✓；
- `py_compile` 通过、前端 build 0 error。

---

## 2026-10-19 ｜ 新增：ADR-012 生态人员下单「待审核」流程（⚠️ 新增状态 + 新端点）

**关联任务**：生态人员负责加购物车下单 → 商务修改单价/合同金额后确认生效；生态人员下单可不填金额；商务确认后实际价同步到平台单价展示。决策记录 `docs/adr/ADR-012.md`。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **`pending`（待审核）状态**：projects/contracts.status 新增值（VARCHAR 无迁移）。`_derive_project_status`：全合同 pending → 项目 pending（审核按项目整批迁移，无混合态） | `src/services.py` |
| 2 | 修改 | **结算角色分叉**：`checkout` 新增 `viewer` 参数——viewer 结算 → `_create_project_core(initial_status="pending")`（锁定照常）；editor/admin 保持 active。viewer + amount 模式 + 金额留空 → 回退 `round(挂牌价×数量)` 取整元（ROUND_HALF_UP）；挂牌价未设 → 400「未登记参考单价，无法免填金额」 | `src/services.py`, `src/routers/api.py` |
| 3 | 新增 | **订单审核接口 `POST /projects/{id}/review`**（`require_editor`）：confirm=行级改价（unit 传实际单价→amount 重算 / amount 传实际合同金额→price 派生反算；遥感明细行 400；数量不可改）+ **实际价写回 `assets.salePrice`**（同产品多行最后遍历生效，写「挂牌价更新」日志）+ 合同/项目 → active + 改价 diff 日志；reject=原因必填 + 逐明细释放锁定 + 合同/项目 terminated（`contract.remark="驳回：{原因}"` 留痕）。确认守卫：存在 amount≤0 行 → 400 | `src/services.py`, `src/schemas.py`（ReviewItemInput/ReviewInput）, `src/routers/api.py` |
| 4 | 修改 | **pending 守卫穿透**：合同/项目状态 API 对 pending → 400（唯一出口=审核接口）；项目删除回滚 pending 视同 active（释放锁定）；产品删除引用拦截扩为 `status IN (active, pending)` | `src/services.py` |
| 5 | 不变 | 商务/管理员手动建单、直接下单、购物车结算一律立即 active；viewer 直接下单（非购物车）不进 pending、金额必填；`update_project` 对 pending 项目允许改基本信息（沿用既有守卫）；驳回/确认均复用 `_apply_item_release`/`_recompute_project`，单事务（H8） | - |

### 验证（真实 API 全链路冒烟，测试数据已清理）

- viewer 结算 Token 产品（amount 模式免填）→ 项目 pending、金额 round(33333.33×2)=**66667** ✓；
- 守卫：pending 合同 PATCH status → 400 ✓；viewer 调 review → 403 ✓；
- 商务 confirm 改价（66667→50000）→ 项目/合同 active、行 price 派生 25000、**挂牌价 33333.33→25000 写回** ✓；
- 混合双客户单 confirm 改 unit 单价 888888 → 合同合计 1811109（1777776+33333）✓、未改价行挂牌价不动 ✓；
- reject 带原因 → 项目/合同 terminated、`remark="驳回：单价需重新询价"`、lockedQty 释放归 0、viewer bootstrap 仍可见驳回原因 ✓；
- `py_compile` 通过、`/api/health` ok。

---

## 2026-10-19 ｜ 修复：撤销交付联动回滚合同/项目状态（⚠️ 行为变更）

**关联任务**：交付记录页点「撤销」后，销售项目详情状态不变化——撤销只回退产品数量，合同仍停留 `delivered`。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `services._revert_outbound_inner` 新增**合同联动**（`restore_contract=True` 为默认，单条撤销生效）：撤销合同交付生成的记录且明细仍 `shipped` 时——明细 `shipped→locked` + 清 `shippedDate`，下单真加锁过（`locked=True`）的明细重新加锁（`lockedQty += qty`，project_lock 流水）；合同 `delivered→active`；项目状态 `_recompute_project` 重算（详情页同步恢复「进行中」）；操作日志追加「关联合同已回退「进行中」并重新锁定明细」 | `src/services.py` |
| 2 | 修复 | 批量级联例外：合同终止 / 项目终止 / 项目删除 4 处级联撤销均传 `restore_contract=False`——否则逐条回滚会先回滚合同再释放，把本应释放的数量**错误重新加锁**（幽灵锁） | `src/services.py` |
| 3 | 不变 | 手动交付（contractId=null）/ 历史补录无合同联动，行为同旧版；再交付安全性由既有机制保证——合同交付分支只处理 locked/confirmed 明细（跳过 shipped），撤销后再交付仅补交被撤销明细，不重复扣量 | - |

### 验证（全链路冒烟，测试数据已清理）

- 交付 → 项目/合同 `delivered`、明细 shipped、shippedQty 2、lockedQty 0；
- 撤销 → 项目/合同 **active**、明细 **locked**（locked=True）、shippedQty 0、lockedQty 2 ✓；
- 再交付 → 仅 1 条 done 交付记录、shippedQty 2（**无重复扣量**）✓；
- 终止已交付合同 → 明细 released、shippedQty/lockedQty 均 0（**无幽灵锁**）✓；
- `py_compile` 通过、`/api/health` ok。

---

## 2026-10-19 ｜ 修改：项目/合同编号改时间戳方式（⚠️ 编号格式变更，存量旧编号保留）

**关联任务**：项目编号与合同编号不再用自增序号，改为时间戳方案（位数由实现定：16 位）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **编号格式**：`SP-{3位序号}` → **`SP-{16位}`**、`HT-{4位序号}` → **`HT-{16位}`**；16 位 = 14 位本地时间戳（`yyyyMMddHHmmss`）+ 2 位随机数。例：`SP-2026101915432005` / `HT-2026101915432021`。设计理由（已写入代码注释 `services._ts_code`）：时间戳可读且按创建时间天然排序；尾部 2 位随机数防**同秒碰撞**（购物车结算一次请求为多客户生成多份合同必然同秒）；随机碰撞时换随机重试最多 10 次，兜底 16 位 uuid 后缀保证 UNIQUE 不破坏 | `src/services.py` |
| 2 | 不变 | 生成点仍为 `_create_project_core`（手动建单 / 直接下单 / 购物车结算共用）；`code` 列 VARCHAR(32) UNIQUE 容量足够（19 字符）；**存量旧编号（SP-001 / HT-0001）保留不动**，前端展示/跳转均按接口返回值，无格式假设；`CK-` 交付单号与 `CH-` 编号本次不变 | - |

### 验证

- 冒烟：手动建 2 客户项目 → `SP-2026101915432005` + 同秒双合同 `HT-...21` / `HT-...86`（随机位生效，无 UNIQUE 冲突）；
- `py_compile` 通过、`/api/health` ok；测试项目已删除（锁定已回滚）。

---

## 2026-10-19 ｜ 修改：清除「入库/出库」字样（入库→登记、出库→交付，纯文案，无逻辑变更）

**关联任务**：平台为对外产品平台，不出现仓储类「入库/出库」字样；与既有「登记产品」「交付」动作口径对齐。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **接口报错消息**：「出库数量超出可用数量/本次出库」→「交付数量超出可用数量/本次交付」；「明细已全部出库/释放」→「全部交付/释放」 | `src/services.py` |
| 2 | 修改 | **操作日志（新记录）**：动作「销售出库/出库补录/历史出库补录（不扣减数量）/出库撤销」→「销售交付/交付补录/历史交付补录（不扣减数量）/交付撤销」；「撤销出库 N 条」「（已回滚锁定与出库）」→「撤销交付 N 条」「（已回滚锁定与交付）」；新建产品动作「入库」→「登记」；字段级 diff 映射 inboundDate「入库日期」→「登记日期」 | `src/services.py` |
| 3 | 修改 | **审计日志（新记录）**：动作「新出库/撤销出库」→「新交付/撤销交付」（英文 action code `outbound` 不变） | `src/routers/api.py` |
| 4 | 不变 | 表/字段名（shippedQty/inboundDate）、flow_type 枚举（purchase_in/sale_out）、CK- 单号前缀、API 路径（/outbound）均不变；**存量 logs/audit_logs/flows 不回溯**（历史留痕保持原样，仅新记录用新口径）；一次性脚本 cleanup_sales_data.py 不动 | - |

### 验证

- `grep -rn "入库\|出库" backend`（除 cleanup_sales_data.py）残留 **0**；`py_compile` 全过；`--reload` 热加载后 `/api/health` ok。

---

## 2026-10-19 ｜ 修改：全平台「资产/库存」术语切换为对外视角「产品及服务」（纯文案，无逻辑变更）

**关联任务**：对外产品平台视角调整。执行依据：`docs/asset-inventory-rename-checklist-20261019.md`。
仅替换**用户可见文案**（接口报错、操作/审计日志动作与明细、字段级 diff 映射、种子数据），代码标识符（表名/字段名/英文枚举）与 API 路径不变。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | **接口报错消息**：资产不存在→产品不存在、库存不足→可用数量不足、可售库存→可用数量、资产主体不一致→产品主体不一致、父资产→父产品、下单资产→下单产品 等约 30 条 | `src/services.py`, `src/routers/api.py` |
| 2 | 修改 | **操作日志（logs 表新增记录）**：动作「新增资产/删除资产/更新资产信息」→「新增产品/删除产品/更新产品信息」；字段级 diff 映射（ASSET_FIELD_LABELS）资产名称/类型/总数/状态→产品名称/类型/总数/状态；「（不扣减库存）（不调整库存）」→「（不扣减数量）（不调整数量）」 | `src/services.py` |
| 3 | 修改 | **审计日志（audit_logs 新增记录）**：动作「新增/编辑/删除资产」→「新增/编辑/删除产品」（英文 action code `asset_change` 不变） | `src/routers/api.py` |
| 4 | 修改 | **种子数据**：category_units note「不扣减库存」→「不扣减数量」；assets 备注「集群库存」→「集群可售」、「演示父资产」→「演示父产品」、「总资产」→「总盘」 | `src/seed_data.py` |
| 5 | 数据 | **生产库存量数据**：同步 UPDATE assets 备注（id 18/28/29）与 category_units note（id 5）；**历史 logs/audit_logs 记录不回溯**（操作/审计留痕保持原样，仅新记录用新口径） | `core_holdings.db` |
| 6 | 不变 | 英文枚举/键（asset_change、in_stock、target='asset'）、表名/字段名、API 路径、状态机与权限逻辑均未改；一次性脚本 cleanup_sales_data.py 不动 | - |

### 验证

- `grep -rn "资产\|库存" backend --include='*.py'`（除 cleanup_sales_data.py）残留 **0**；
- `py_compile` 全过；`--reload` 服务热加载后 `/api/health` ok、bootstrap 正常；
- 冒烟：报错文案已按新口径返回（如「产品不存在」「合同不存在」）。

---

## 2026-10-16 ｜ 新增：销售项目对生态人员（viewer）开放「仅自己下单」可见 + 有限编辑/终止

**关联任务**：平台优化需求 2（销售项目生态人员可见范围）。口径（用户确认）：按**实际下单账号**判定（`Project.creator`）；存量项目 creator 为空时回退 `rep == 自己姓名`；可见范围全过滤（列表/详情/合同）；viewer 可编辑自己项目基本信息 + 可终止（不可交付、不可删除、不可新建空项目）。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 ⚠️ | **`projects` 加列 `creator`**（VARCHAR(64) 默认 `''` + 索引，幂等迁移）：实际登录下单的 username。`_create_project_core` 建项目时写入 `creator=operator`（三入口 POST /projects、POST /sales/order、POST /cart/checkout 均传登录账号）；存量项目为空 | `src/models.py`, `main.py`, `src/services.py` |
| 2 | 新增 ⚠️ | **可见性判定 `user_sees_project`**：admin/editor 全见；viewer 仅 `creator==自己 username`，creator 为空（存量）回退 `rep in (自己姓名, 自己 username)`。`bootstrap` 按该口径过滤 `projects` 与 `contracts`（合同跟随项目可见性）——前端项目列表/详情/资产「销售关联」页签均消费此镜像，天然全过滤；越权 URL 访问他人项目 → 镜像无此项目 → 前端 el-empty「未找到该销售项目」 | `src/services.py`, `src/routers/api.py` |
| 3 | 修改 ⚠️ | **三个写端点依赖 `require_editor` → `require_order`**（约束下沉服务层）：a) `PUT /projects/{id}`——viewer 可编辑**自己项目**基本信息，`rep` 字段对 viewer 恒忽略（防把项目转给他人造成越权转移）；b) `PATCH /projects/{id}/status`——viewer 仅可 `terminated`（自己项目），`delivered` 400「生态人员仅可终止项目（交付需商务人员/管理员操作）」；c) `PATCH /contracts/{id}/status`——viewer 仅可 `terminated`（自己项目合同，含 delivered 撤销出库），`delivered` 400。越权（非自己项目）一律 403「生态人员仅可操作自己下单的项目」 | `src/services.py`, `src/routers/api.py` |
| 4 | 不变 | `POST /projects`（新建空项目）、`DELETE /projects/{id}` 保持 `require_editor`——viewer 建项目只走下单链路（require_order）；删除仍仅商务/管理员 | - |

### 自测（临时库 8020 冒烟，curl 走查）

- 张三（viewer）/李四（editor）均 rep=张三 各自下单 → 张三 bootstrap 仅见自己单（creator 口径优先）；admin 手建 rep=张三 的项目张三不可见 ✓
- 存量模拟（李四代单 creator 置空）→ 张三可见（rep 回退口径）✓
- 张三编辑自己项目 200（name/remark 生效），`rep` 传「李四」不生效（仍=张三）✓
- 张三 PUT/终止他人项目合同 → 403；交付自己合同 → 400；终止自己合同 → 200 且项目派生 terminated ✓

---

## 2026-10-16 ｜ 修复：业务逻辑 bug 批量修复 17 项（docs/business-logic-bugs-20261016.md，子 Agent 独立评估 18 条全成立）

**关联任务**：业务逻辑 bug 清单全量修复（#1 前端 availableValue 见前端 changelog；#16 保持现状见文末说明）。临时库（/tmp/cho_smoke.db）逐项冒烟 + 生产库唯一索引迁移已验证，生产 8000（--reload）已自动生效。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 ⚠️ | **BUG-A `PUT /assets/{id}` 裸 dict 无校验**：路由入参改 Pydantic `schemas.AssetUpdate`（全字段可选，`quantity: int ≥0`、`salePrice: float ≥0`，非法 422），`exclude_unset=True` 仅采信实际传参（未传字段不覆盖） | `src/schemas.py`, `src/routers/api.py` |
| 2 | 修复 ⚠️ | **BUG-B `update_asset` 库存下限守卫**：setattr 循环与 repeatSale 锁定清零之后、`refresh_status` 之前新增校验 `quantity ≥ lockedQty + shippedQty`，违反 400「资产总数不能低于已锁定 X + 已出库 Y（合计 Z），请先处理相关销售项目/出库记录」（可售变负将破坏「可售=总数−锁定−出库」口径） | `src/services.py` |
| 3 | 修复 | **BUG-C `create_asset` 状态不再采信前端**：构造后 `asset.status = auto_status(asset)` 覆盖（两态自动判定，与 update/refresh 口径一致）；修复 quantity=0 非重复售卖资产被误存 `in_stock` | `src/services.py` |
| 4 | 修复 | **BUG-D 手动出库 operator 真实化**：`create_outbound` 出库单 operator 改取路由层登录账号（`operator or "admin"`），不再采信可伪造的 `data.operator`（入参字段保留兼容，OutboundInput 不变） | `src/services.py` |
| 5 | 修复 ⚠️ | **BUG-E 遥感明细重复加购 double-count**：`add_to_cart`/`add_to_cart_batch` 库存校验改用**净增**口径 `delta = 0 if (rs 行且已在车) else qty`（total_in_cart 已含目标行存量）；修复非重复售卖明细行（repeatSale=false）重复加购（本应幂等）在可售恰为边界值时被 400 | `src/services.py` |
| 6 | 修复 ⚠️ | **BUG-F 批量加购原子化**：`add_to_cart` 拆出无提交核心 `_cart_add_inner`，`add_to_cart_batch` 循环走 inner、整批末尾单次 `db.commit()`——任一行硬 400（如 amount 模式金额非整数）整批回滚，不再「加一半」（已实测 before/after 行数一致） | `src/services.py` |
| 7 | 修复 ⚠️ | **BUG-G soldCount 口径统一**：手动出库（非 history）一律 `soldCount += 1`（对齐合同交付「出库=一次销售」，此前仅 repeatSale 分支 +1）；`_revert_outbound_inner` 对应改为撤销一律 -1（max(0) 夹零，口径统一前的存量非 repeatSale 手动出库撤销最多少计一次，可接受） | `src/services.py` |
| 8 | 修复 ⚠️ | **BUG-H 含 pending 明细禁止置 delivered**：`_change_contract_status_core`（合同）与 `_legacy_change_project_status`（无合同存量项目）交付分支前置校验——存在 `status='pending_asset'` 明细 400「尚有 N 项明细未关联资产，无法交付完成（请先终止）」，杜绝「已完成项目悬挂待关联明细」 | `src/services.py` |
| 9 | 修复 | **BUG-I 删除用户清理购物车**：`DELETE /users/{id}` 先删该用户 `cart_items`（userId 存 users.id 字符串），不再留永久孤儿行 | `src/routers/api.py` |
| 10 | 修复 | **BUG-J bootstrap 读接口写副作用收敛**：交付物惰性初始化仅在确有资产未初始化时进入写路径 + commit，稳态 bootstrap 纯读，不再抢 SQLite 写锁 | `src/services.py` |
| 11 | 修复 | **BUG-K 删除上传文件引用校验**：`DELETE /upload/{filename}` 前置校验 `assets.contractFile/featureDoc` 引用，被引用 400「该文件仍被资产「X」引用（产品清单/功能清单），请先修改资产附件后再删除」 | `src/routers/api.py` |
| 12 | 修复 ⚠️ | **BUG-L `PUT /cart/{id}` 不再兼作删行**：`qty <= 0` 由静默 `db.delete` 改 400「数量必须大于 0（移除行请使用删除操作）」（前端数量输入 min=1、删除走 `DELETE /cart/{id}`，无功能影响；修复漏传 qty 默认 0 误删行） | `src/services.py` |
| 13 | 新增 ⚠️ | **BUG-M 唯一约束 DB 兜底**：`main._ensure_unique_indexes`（启动幂等迁移）——`uq_rs_items_dim`（rs_items 五维）+ `uq_cart_items_key`（cart_items `COALESCE(itemId, 0)` 表达式索引，SQLite 唯一索引不认 NULL 相等）；存量重复数据时跳过建索引并告警（服务层判重仍为主防线）。生产库已建成功（无重复数据）。RsItem 模型同步声明 `UniqueConstraint` | `main.py`, `src/models.py` |
| 14 | 新增 ⚠️ | **BUG-N 登录失败限流**：`security` 新增进程内失败计数（15 分钟窗口 ≥10 次锁定 15 分钟，标准库实现零依赖），`POST /auth/login` 锁定中 429「登录失败次数过多，请 15 分钟后再试」，失败累加/成功清零 | `src/security.py`, `src/routers/api.py` |
| 15 | 修复 | **BUG-O 项目名非空校验**：`_create_project_core`（建项目三入口共用）与 `update_project` 前置 `name.strip()` 非空 400「项目名称不能为空」，并 strip 落库 | `src/services.py` |

### 400/422/429 错误文案清单（新增）

- `资产总数不能低于已锁定 X{单位} + 已出库 Y{单位}（合计 Z{单位}），请先处理相关销售项目/出库记录`（PUT /assets/{id}）
- `尚有 N 项明细未关联资产，无法交付完成（请先终止该合同/项目）`（PATCH 合同/项目状态 → delivered）
- `该文件仍被资产「X」引用（产品清单/功能清单），请先修改资产附件后再删除`（DELETE /upload/{filename}）
- `数量必须大于 0（移除行请使用删除操作）`（PUT /cart/{id} qty≤0）
- `项目名称不能为空`（POST /projects、PUT /projects/{id}）
- 422：quantity 非整数/负数、salePrice 负数（PUT /assets/{id}）；429：登录失败次数过多

### 自测（临时库 8017 冒烟，Bearer admin，curl 走查）

- 新建 quantity=0 非重复售卖资产 → status=`all_sold`（BUG-C）✓；PUT quantity=-1 / "abc" → 422（BUG-A）✓
- 锁定 1 台后 PUT quantity=0 → 400 BUG-B 文案 ✓（quantity=1 恰好可售 0 放行，为合法状态）
- 遥感明细（repeatSale=false，父资产可售=1）加购 2 次均 200（BUG-E，修复前第二次 400）✓
- 批量加购（合法行 + 金额非整数行）→ 400 且购物车 before=after（BUG-F 整批回滚）✓
- 非 repeatSale 手动出库 → soldCount+1、operator=登录账号（传「伪造操作人」不采信，BUG-D/G）✓；合同交付+终止 → shippedQty/lockedQty/soldCount 全回 0（互逆）✓
- 含 pending 明细合同 → delivered 400（BUG-H）✓；正常合同交付/终止回归 200 ✓
- PUT /cart/{id} qty=0 → 400 且行仍在（BUG-L）✓；DELETE /users → 其 cart_items 0 残留（BUG-I）✓
- 上传文件挂 contractFile → DELETE 400，解引用后 200（BUG-K）✓
- 连续 10 次错误密码 → 第 11 次 429（BUG-N）✓；生产库 `uq_rs_items_dim`/`uq_cart_items_key` 已建（BUG-M）✓

### 保持现状说明（#16）

文件端点 `?token=<jwt>` 查询参数通道与「三角色可下载任意上传文件」为**既有设计取舍**（iframe/img 无法带请求头；viewer 需预览资产附件），修复将破坏现有功能，不改动。风险已知悉：JWT 可能进入访问日志/Referer。

---

## 2026-10-16 ｜ 新增：遥感数据「父资产 + 可售明细」两层模型（ADR-011，⚠️ Supersedes ADR-010）

**关联任务**：ADR-011 后端全量实现（契约冻结）。**ADR-010 设计被取代**：assets 三维 4 列废弃（列保留不删）、三维必填/判重逻辑移除、遥感入库默认值移除；遥感售卖粒度改由新表 `rs_items` 承载。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **新表 `rs_items`**（id / assetId INDEX / province / city 默认 `''` / resolution 米 / saleMonth `YYYY-MM` / price 整数元·份 / repeatSale 默认 true / createdAt / updatedAt）：遥感数据可售明细（省/市 × 精度 × 月份），真正售卖单位。唯一性 `(assetId, province, city, resolution, saleMonth)` 服务层判重（resolution 容差 1e-9，无 DB 约束）。`Base.metadata.create_all` 建表 | `src/models.py`, `src/schemas.py` |
| 2 | 新增 | **3 个端点**（均 `require_editor`）：`POST /assets/{asset_id}/rs-items`（父资产须 `type='遥感数据'`，否则 400「仅遥感数据资产可维护可售明细」）、`PUT /rs-items/{item_id}`（判重排除自身）、`DELETE /rs-items/{item_id}`（任一 `project_items.itemId`/`cart_items.itemId` 引用 → 400「该明细存在销售关联，无法删除」）。增/删/改均写 OpLog（`target='asset'` 关联父资产）+ router 层 `record_audit`（`asset_change`，detail=`rsItemId=N`） | `src/routers/api.py`, `src/services.py` |
| 3 | 修改 ⚠️ | **`cart_items` / `project_items` 加列 `itemId`**（INTEGER NULL INDEX，幂等迁移）：购物车行/项目明细行挂 rs_items。购物车含 itemId 行：qty 恒 1（≠1 → 400「遥感数据明细行数量固定为 1」，`set_cart_qty` 同）、判重键升级 **(userId, assetId, itemId, customer)**（无 itemId 行 = `itemId IS NULL` 口径不变，重复加购幂等合并 qty 保持 1）、归属校验（明细不存在/不属于该资产 400；batch 路径跳过该行）、库存按**明细** repeatSale 判定。`CartItemOut`/`ProjectItemOut` 新增 `itemId: int | null` | `src/models.py`, `src/schemas.py`, `src/services.py`, `main.py` |
| 4 | 修改 ⚠️ | **销售链路明细行权威计价**（`POST /projects`、`POST /sales/order`、`POST /cart/checkout` 三入口，收敛在 `_create_project_core`）：含 itemId 行 `amount` 权威 = `rs_items.price × 1`（Decimal 重算，**忽略前端传值**）、qty 强制 1；明细 `repeatSale=true` → 不锁库存只计次，`false` → 锁**父资产** lockedQty（qty=1）。锁定/交付/终止/出库撤销回退全部明细感知：`apply_item_lock` 新增 `repeat_override` 参数，`_apply_item_delivery`/`_apply_item_release`/`_revert_outbound_inner` 按明细 repeatSale 判定（修复父资产 repeatSale=true 时明细行锁定无法释放的问题）；库存需求聚合（H10）按明细 repeatSale 过滤 | `src/services.py` |
| 5 | 修改 ⚠️ | **ADR-010 逻辑全部移除**：`AssetOut`/`AssetInput` 移除 `province/city/resolution/imageDate`（前端多传被 Pydantic 静默忽略）；`create_asset`/`update_asset` 三维必填/判重/入库默认值（quantity 0→1、unit 兜底）移除，服务层不再读写 4 个废弃列（列保留不删，技术债）；`_find_remote_sensing_dup` 删除。遥感数据按普通父资产登记 | `src/schemas.py`, `src/services.py` |
| 6 | 修改 | **bootstrap 出参**：新增顶层 `rsItems: RsItemOut[]`（全量）；`assets[]` 移除 4 个三维字段；`cart[]`/`projects[].items[]`/`contracts[].items[]` 增 `itemId`（nullable） | `src/services.py`, `src/schemas.py` |
| 7 | 修改 | **`delete_asset` 级联清理 rs_items**：父资产删除（通过既有引用校验后）同步删除其名下明细（走到删除说明无 active 合同/非 terminated 项目引用，明细不可能有销售关联） | `src/services.py` |
| 8 | 修改 | **数据清理（幂等一次性迁移）**：删除 ADR-010 演示遥感数据资产（`type='遥感数据'` 且三维字段非空的存量行，即「河北省石家庄市 1.5m 2026-09-15」id=29）及其 flows/deliverables；删前 assert 无 project_items/cart_items 引用（有则启动失败）。匹配条件限定三维字段非空——ADR-011 新建父资产容器 4 列恒空不会被误删，执行一次后命中 0 行 | `main.py` |

### 400 错误文案清单（新增）

- `仅遥感数据资产可维护可售明细`（POST /assets/{id}/rs-items 非遥感父资产）
- `遥感数据明细必须填写省份` / `遥感数据明细单价须为整数元且大于 0`
- `该父资产下已存在相同 省/市 + 精度 + 月份 的明细`（create / update 排除自身）
- `该明细存在销售关联，无法删除`（DELETE /rs-items/{id}）
- `遥感数据明细行数量固定为 1`（购物车加购/改数/下单 明细行 qty≠1）
- `遥感数据明细不存在或不属于该资产`（购物车/下单归属校验）
- `购物车中的遥感数据明细已删除或不属于该资产，请先移除后再下单`（checkout）
- 404：`遥感数据明细不存在` / `明细所属父资产不存在`
- 422：`saleMonth` 不匹配 `^\d{4}-\d{2}$` / `resolution` ≤ 0（Pydantic）

### 自测（真实库 8000 --reload，Bearer admin，curl 走查）

- 建父资产「遥感数据-2026」（id=29，AssetOut 无 4 废弃字段）→ 加 2 条明细（河北石家庄 1.5m 2026-09 330000 元 / 甘肃 1m 2026-10 280000 元）→ 重复组合 400 ✓
- bootstrap.rsItems 2 条 ✓；加购 itemId 行 qty=1 → 200、qty=2 → 400、重复加购合并 qty 仍 1、归属错误 400、PUT 改数 400 ✓
- `POST /sales/order` 传 itemId 行 + 乱传 amount=999 → 落库 amount=330000（明细 price）、items/合同输出 itemId ✓
- 交付合同（repeatSale=true 明细）→ soldCount+1/soldAmount+330000、无锁定动作；终止 → 全回退 ✓
- repeatSale=false 明细：下单 → 父资产 lockedQty+1（locked=true）；终止 active → 锁定释放；交付 → shippedQty+1；终止 delivered → 全回退 ✓
- 有购物车/项目引用 DELETE rs-item → 400；无引用 → 200 ✓
- 回归：unit 资产下单（amount 重算 53600）、卫星Token amount 模式下单（10000000）、普通购物车结算（2 客户 2 合同、主体不一致 400 正确拦截）✓
- `python3 -c "import main"` 通过；迁移幂等（二次启动 0 变更）；测试项目/购物车行已清理，库存锁定回滚，保留父资产 29 + 2 条明细作演示

---

## 2026-10-15 ｜ 修复：业务逻辑审计 6 项（已实测坐实，契约冻结）

**关联任务**：业务逻辑审计修复（FIX-1 ~ FIX-6，隔离库 8011 全量验收 + e2e_auth 22 项 / e2e_check 86 项回归全绿）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **FIX-1 手动出库补可售校验**：`create_outbound` 在 `mode != "history"`（补录不扣库存，跳过）且资产**非 repeatSale**（可重复售卖不占库存，跳过）时，出库前校验 `qty <= quantity - lockedQty - shippedQty`（按当前库值，出库是独立动作）；超量 400「出库数量超出可售库存：{资产名} 可售 {n}{unit}，本次出库 {qty}{unit}」。WHY：此前手动出库可无限超卖（如库存 2 出 5），shippedQty 超 quantity，资产状态/可售口径失真 | `src/services.py` |
| 2 | 修复 | **FIX-2 项目删除回滚挂项目的手动出库**：`delete_project`（合同分支）在级联撤销合同出库之外，同时撤销 `projectId == p.id 且 contractId == null 且 status='done'` 的手动出库（复用 `_revert_outbound_inner`：写「出库撤销」日志 + 回退流水 + 回退 shippedQty/soldCount/soldAmount），与前端删除确认文案「撤销该项目已生成的出库记录」对齐。`_terminate_project`（项目终止）**不做**此回滚——终止≠删除，手动出库是独立动作（已加注释说明；合同口径终止本就不触碰手动出库，legacy 无合同路径保留旧全量撤销语义）。WHY：此前删除项目后挂项目的手动出库成为孤儿 done 记录，资产 shippedQty/soldAmount 残留不回退 | `src/services.py` |
| 3 | 修复 | **FIX-3 出库撤销 soldCount 精确逆操作**：`_revert_outbound_inner` 由无条件 `soldCount-1` 改为按创建分支对称回退——合同交付出库（`contractId != null`，创建时 repeatSale/非 repeatSale 均 +1）撤销一律 -1；手动出库（`contractId == null`，创建时仅 repeatSale 分支 +1）撤销**仅 repeatSale 时** -1。shippedQty/soldAmount 回退保持现状。WHY：此前撤销非 repeatSale 手动出库会误减 soldCount（1→0），累计销售次数与创建侧不对称 | `src/services.py` |
| 4 | 修复 | **FIX-4 资产删除保护改为合同感知**：`delete_asset` 引用校验拆为两条——合同明细（contractId 非空）：仅当存在 `status='active'` 合同引用时 400「该资产仍被进行中的合同 {HT-xxxx}（客户 {X}）引用，请先终止该合同后再删除」，delivered/terminated 合同引用放行（前端已有「未关联资产」兜底、交付分支已有 `if a:` 防御）；无合同 legacy 项目明细：保持原规则（项目 status != terminated 拦截）。done 出库拦截保持。WHY：原规则按「项目非 terminated」拦截，delivered 合同（出库已撤销）或 terminated 混合场景下资产无法删除，与合同生命周期脱节 | `src/services.py` |
| 5 | 修复 | **FIX-5 OpLog operator 真实化**：`add_log` 新增 `operator` 参数（默认 `"admin"` 兼容 seed/内部路径）；router 层已透传 `user.username` 的写路径全部落到 OpLog——合同交付/终止（`_change_contract_status_core`）、项目新增/编辑/状态变更/删除（含 `_terminate_project`/legacy 交付）、出库创建/撤销、资产新增/编辑/删除（`update_asset`/`delete_asset` 补 operator 参数，router 调用点传入）。未透传（保持默认 "admin"）：基础资料/交付物模板/资产交付物增删改（非重点写路径，避免签名扩散）。WHY：操作记录 operator 恒为 "admin"，editor 账号的实际操作无法审计到人 | `src/services.py`, `src/routers/api.py` |
| 6 | 修复 | **FIX-6 编辑规则对齐 + 购物车行级合计校验**：a) `update_project` 新增拦截——项目派生状态 `terminated`（全合同终止/混合 delivered+terminated；legacy terminated）→ 400「项目已终止，不可编辑」（与前端 canEditProject 对齐；既有「存在 delivered 合同不可编辑」保持）；b) `set_cart_qty` 数量上限从「本行 qty ≤ 可售」升级为「该资产在购物车**全部行合计**（本次修改后）≤ 可售」（repeatSale 跳过），超量 400「购物车中 {资产名} 合计 {n} 超出可售 {m}」。`add_to_cart`/`add_to_cart_batch` 已是行级合计口径，无需改动。WHY：a) 前端已禁编辑 terminated 项目但后端放行，直连 API 可改已终止项目；b) 两客户行各 1、可售 2 时把某行改 2（合计 3）原校验放行，结算时才 400，超卖风险前置到改数时刻 | `src/services.py` |

### 400 错误文案清单（新增/变更）

- `出库数量超出可售库存：{资产名} 可售 {n}{unit}，本次出库 {qty}{unit}`（FIX-1，POST /outbounds）
- `该资产仍被进行中的合同 {HT-xxxx}（客户 {X}）引用，请先终止该合同后再删除`（FIX-4，DELETE /assets/{id}）
- `项目已终止，不可编辑`（FIX-6a，PUT /projects/{id}）
- `购物车中 {资产名} 合计 {n} 超出可售 {m}`（FIX-6b，PUT /cart/{id}）

---

## 2026-10-15 ｜ 修复：checkout 入参补 businessOwner

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | `CheckoutInput` 新增 `businessOwner: str = ""`（此前前端已传但被 Pydantic 静默忽略，购物车结算生成的项目商务负责人恒为空）；`checkout` 建项目处透传落库（对齐 `POST /projects` 的 `ProjectInput.businessOwner` 口径）。不传默认 `""` 兼容；分组/金额派生/锁定/事务逻辑不变 | `src/schemas.py`, `src/services.py` |
| 2 | 修复 | `SaleOrderInput` 新增 `businessOwner: str = ""`（同上一条同构问题：直接下单 `POST /sales/order` 生成的项目商务负责人恒为空）；`_order_core` 建 `ProjectInput` 处透传落库。不传默认 `""` 兼容，其它逻辑不变 | `src/schemas.py`, `src/services.py` |

---

## 2026-10-15 ｜ ⚠️ Breaking：合同层级（ADR-007）——合同表 + 购物车跨主体按客户归组 + 项目状态派生 + 清理脚本

**关联任务**：合同层级（ADR-007）后端全量实现（契约冻结）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 ⚠️ | **新表 `contracts`**（id / code `HT-{4位}` UNIQUE / projectId INDEX / customer / subject / contractAmount 元 / status `active`·`delivered`·`terminated` / remark / createdAt / updatedAt）：项目下按客户拆分的合同，**库存联动的最小单位**。合同内强制同一资产主体（后端校验，不一致 400）；合同一经生成不可增删改明细（终止再重下）。`Base.metadata.create_all` 建表 | `src/models.py`, `src/schemas.py` |
| 2 | 修改 ⚠️ | **`project_items` 加 `contractId`**（INTEGER NULL INDEX）：新数据必填；存量项 NULL（清理后消失）。**`outbounds` 加 `contractId`**（INTEGER NULL INDEX）：合同交付自动出库精确关联合同（projectId 保留）。**`cart_items` 加 `customer`**（VARCHAR(128) 默认 `''`）：购物车行级客户。`flows` / `logs` 加 `contractId`（INTEGER NULL）：合同级流水/日志关联。均幂等迁移（`main.py`） | `src/models.py`, `main.py` |
| 3 | 修改 ⚠️ | **项目 status 改为派生**：任何合同状态变更后 `_recompute_project`——无合同→active（存量兼容）；有 active→active；全 delivered→delivered；全 terminated→terminated；混合 delivered+terminated（无 active）→terminated（保守）。`expectedAmount`（及兼容口径 `contractAmount`）=Σ合同 contractAmount（Decimal 重算落库）；`customer`/`subject`：多合同=空字符串（前端显示「N 位客户」）、单合同=该合同值、无合同=保持存量值。`ProjectOut` 新增派生字段 `contractCount`（int，模型 property） | `src/services.py`, `src/models.py`, `src/schemas.py` |
| 4 | 新增 | **合同级业务动作 `PATCH /api/contracts/{id}/status`**（admin+editor）：`delivered`=逐明细交付（释放锁定仅 `it.locked`、非 repeatSale 扣 shippedQty、soldCount/soldAmount 均累计、每明细生成出库记录 contractId=合同 id、备注「合同「HT-xxxx」交付完成自动生成」）；`terminated`=active 合同释放锁定（cancel_release 流水带 contractId）、delivered 合同撤销名下 done 出库并回退 shippedQty/soldCount/soldAmount（manual_adjust 负数流水）。每次动作后重算项目派生字段 + OpLog（action 含合同 code，contractId 落库）。与项目级逻辑抽取共用 `_apply_item_delivery` / `_apply_item_release`（避免两套逻辑漂移）。审计：`变更合同状态 | HT-xxxx | status=...` | `src/services.py`, `src/routers/api.py` |
| 5 | 修改 ⚠️ | **`PATCH /api/projects/{id}/status` 行为改为批量快捷**：对名下全部 **active** 合同批量执行该状态动作（delivered=全部交付、terminated=全部终止）；`active` 不再可设（400「项目状态由合同状态派生…」）；无 active 合同 400。前端主入口用合同级。存量无合同项目走旧的项目级明细逻辑（`_legacy_change_project_status`，行为不变） | `src/services.py` |
| 6 | 修改 ⚠️ | **`POST /api/projects` 入参支持 `contracts` 结构**：`contracts: [{customer(必填), items:[{assetId,qty,price,deliveryReq}], contractAmount?(缺省=明细合计), remark?}]`；**向后兼容**：仍传 `items` 时按单合同自动包装（customer 取项目 customer 字段），两种入参都支持。`items` 改为可选（`default=[]`）。逐合同校验同主体（400「客户「X」的资产主体不一致，请拆分」）；库存校验按 assetId 跨合同聚合。项目 subject/customer/expectedAmount 由合同派生（请求体同名值不再采信） | `src/schemas.py`, `src/services.py` |
| 7 | 修改 ⚠️ | **`PUT /api/projects/{id}` 收窄为项目基本信息编辑**（name/industry/rep/businessOwner/remark/日期/quoteAmount/paidAmount）：不再接受 items/contracts 变更（收到即忽略，合同结构编辑本次不做）；编辑约束改为**存在 delivered 合同则 400**「已交付完成的项目不可编辑」（存量无合同项目沿用 `status!=active` 旧规则） | `src/services.py` |
| 8 | 修改 ⚠️ | **购物车跨主体 + 按客户归组**：删除同主体限制（`_cart_subject`/`_check_entity` 移除，跨主体加购成功）；`POST /cart`、`POST /cart/batch` 行级带 `customer`；**唯一键语义改为 (userId, assetId, customer)**（不同 customer 同资产=两行，库存上限按该资产全部行合计校验）；新增 **`PATCH /api/cart/{id}`** 改行级客户（目标 (userId,assetId,customer) 已有其它行 400）。`CartItemOut` 新增 `customer` | `src/services.py`, `src/routers/api.py`, `src/schemas.py` |
| 9 | 修改 ⚠️ | **`POST /api/cart/checkout` 按客户分组拆合同**：行级 customer 为空 → 400「请为每件资产填写客户」；同客户资产主体不一致 → 400「客户「X」的资产主体不一致，请拆分」；每客户一个合同（code HT-xxxx、subject 推导、contractAmount=该组明细合计）→ 建项目（name=请求 projectName 或默认「销售项目-日期」）→ 锁定 → 清空购物车，**全部单事务**。`CheckoutInput.projectName`/`customer` 改为可选（customer 兼容保留不参与分组）。**不自动交付**（下单=active+锁定，维持现行为） | `src/services.py`, `src/schemas.py` |
| 10 | 修改 | **`POST /api/sales/order` 单合同语义保留**：items 按各自资产主体校验同主体（原逻辑），customer 必填 → 建项目 + 单合同 | `src/services.py` |
| 11 | 修改 ⚠️ | **`DELETE /api/projects/{id}` 合同级联**：active 合同释放锁定、delivered 合同撤销名下 done 出库并回退数量/金额 → 硬删项目及其合同、明细（cascade）。存量无合同项目沿用旧 `_terminate_project` 回滚 | `src/services.py` |
| 12 | 修改 | **交付/撤销 soldCount 口径对称化**：交付（`_apply_item_delivery`）对 repeatSale 与非 repeatSale **均**累计 soldCount/soldAmount（交付=一次销售）；`_revert_outbound_inner` 撤销时对称回退（非 repeatSale 回退 shippedQty，两者均回退 soldCount/soldAmount）。手动出库 `create_outbound` 路径不变（仍仅 repeatSale 累计 soldCount） | `src/services.py` |
| 13 | 修改 | **bootstrap 出参**：新增 `contracts: ContractOut[]`（全量，含 items 挂 contractId）；`projects[]` 增 `contractCount`；`outbounds[]`/`flows[]`/`logs[]` 增 `contractId`（nullable，存量 null）；`cart[]` 增 `customer` | `src/services.py`, `src/schemas.py` |
| 14 | 新增 | **数据清理脚本 `backend/cleanup_sales_data.py`**（⚠️ 仅供架构师审核后在**停服窗口**手动执行，应用启动不调用）：备份库 → 单事务按序删 project_items → outbounds（全部）→ 销售类 flows（project_lock/sale_out/cancel_release/manual_adjust，**purchase_in 保留**）→ cart_items → contracts → projects → 资产 `lockedQty/shippedQty/soldCount/soldAmount` 清零 → status 重刷（auto_status 同规则）→ 输出清理前后计数；幂等保护（projects+contracts 均空则跳过）；支持 `--db` / `--dry-run` | `backend/cleanup_sales_data.py` |

### 400 错误文案清单（新增/变更）

- `请为每件资产填写客户`（checkout 空客户行）
- `客户「X」的资产主体不一致，请拆分`（checkout 同客户跨主体 / POST /projects 合同内跨主体）
- `下单资产必须属于同一主体，请拆分下单`（sales/order 同主体校验，文案微调）
- `合同不存在` / `合同所属项目不存在`（404）
- `不支持的合同状态：X` / `合同已终止，不可再变更状态` / `已交付完成的合同不可回退到进行中`
- `项目状态由合同状态派生，仅支持批量 delivered/terminated（active 请直接变更合同状态）` / `项目下没有进行中的合同，无可批量执行`
- `购物车中该资产在客户「X」下已有行，无法修改客户（请先删除原行）`（PATCH /cart/{id}）

### 自测（临时库 8012 隔离，全部 Bearer admin，验证后已 kill 8012 删临时库）

- 建 A1/S1(qty2)/A2/S1(qty1)/B1/S2(qty1) → 购物车加 A1×1(甲)+A2×1(甲)+B1×1(乙) **跨主体加购成功** → checkout 200：1 项目 SP-001 + **2 合同**（HT-0001 甲 S1 150 元 / HT-0002 乙 S2 30 元），项目 status=active、expectedAmount=180=Σ合同，锁定 A1=1/A2=1/**B1=1**（非 repeatSale 正确锁定）。
- 同客户跨主体（丙：A1+B1）→ checkout **400** `客户「丙」的资产主体不一致，请拆分`；空客户行 → **400** `请为每件资产填写客户`。
- 交付甲合同 → A1/A2 shippedQty+1、出库 2 条（contractId=1、备注「合同「HT-0001」交付完成自动生成」）、**项目仍 active**（乙未交付）；再交付乙合同 → 项目 **delivered**（派生）。
- POST /projects 带 contracts（丁=A1/戊=B1）→ 2 合同 HT-0006/HT-0007、expectedAmount=130；终止 HT-0007 → B1 锁定释放（2→1）、项目回 active、cancel_release 流水 contractId=7。
- POST /projects 旧 items 入参 → 单合同 HT-0008 自动包装（customer=己 取项目字段、subject=S1 推导、金额=明细合计）。
- 项目级 PATCH delivered → 名下 active 合同全部交付（SP-006 单合同→项目 delivered；SP-005 丁交付后混合 delivered+terminated → 项目 terminated，保守规则）。
- 删除项目：SP-002（active）→ A1 锁定 2→1；SP-006（delivered）→ CK-0004 置 reverted、A1 shipped 3→2、soldCount 3→2、soldAmount 300→200（数值闭环）；合同/明细级联删除。
- 权限：viewer `POST /cart` 403、`PATCH /contracts/{id}/status` 403；audit-logs 含 `变更合同状态 | HT-0001/0002/0007 | status=...`。
- 清理脚本在临时库副本上实测：dry-run 只读；正式执行删 7 明细/5 出库/22 销售流水（purchase_in 31 条保留）/6 合同/4 项目、资产清零、status 重刷；再跑幂等跳过。
- 真实库 8000（--reload）自动加载：bootstrap 含 `contracts`（存量 0 条）、`contractCount`、`contractId: null` 兼容字段，存量 10 项目不受影响。

### 未改动 / 保持不变的既有行为（回归依据）

- 资产 CRUD、2 态自动判定、出库登记/撤销、基础资料、交付物、上传、认证/权限矩阵、审计机制均不变。
- `POST /api/sales/order` 入参契约不变（customer 仍必填），仅内部改为单合同包装。
- 存量数据（无合同项目）全链路兼容：状态流转/编辑/删除走 legacy 路径，行为与 ADR-007 前一致。

---

## 2026-10-15 ｜ DELETE /upload 同步清理 file_meta + 一次性孤儿数据清理

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | **`DELETE /api/upload/{filename}` 同步删除 `file_meta` 对应行**：物理文件删除成功后按 storedName 删除 file_meta 映射（无行则忽略，幂等），返回体保持 `{"ok": true}` 不变。另执行一次性真实库孤儿清理：删除 2 条前端探针残留记录（`6cbc2d31…pdf` 功能清单-原始名测试 / `fe11263a…pdf` 浏览器上传-中文名，物理文件已删）；全量孤儿扫描（file_meta 中 storedName 在 uploads/ 无物理文件）无其它命中；file_meta 行数 14 → 12。9 个「物理文件存在但未被资产引用且 uploadedBy 为空」的旧文件未删除，仅列出待决策 | `src/routers/api.py`, `core_holdings.db`（数据） |

---

## 2026-10-15 ｜ 文件原名映射（file_meta）+ 操作记录金额 diff 元值化

**关联任务**：① 文件原名映射 ② 操作记录金额 diff 元值化

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **`file_meta` 表**（storedName 主键=散列落盘名 / name=原始文件名 / size / uploadedBy / createdAt）：上传文件以散列名落盘 `uploads/`，本表记录散列名→原始名映射。`POST /api/upload` 落盘成功后写 file_meta（不写 OpLog，上传非资产操作）；返回体新增 `storedName`；`GET /api/files/{filename}` 加 `Content-Disposition: attachment; filename*=UTF-8''{urlencoded原始名}`（查 file_meta 无记录用散列名兜底，MIME 仍按扩展名）；`GET /api/bootstrap` 返回体新增 `files: FileMetaOut[]`（全量，当前量级小无分页）。启动 `_backfill_file_meta` 幂等回填（file_meta 为空才执行）：扫描 uploads，散列名文件若存在**内容相同**的非散列（可读）文件则以其为原始名，否则 name=自身名；**纯数据库操作，不移动/重命名/删除 uploads 任何文件**。`UPLOAD_DIR` 可用环境变量覆盖（验收用临时目录） | `src/models.py`, `src/schemas.py`, `src/services.py`, `src/routers/api.py`, `main.py` |
| 2 | 修改 | **`update_asset` changes diff 元值化 + 文件字段还原原始名**：金额类字段（`salePrice`）由「万元」口径改为**元值**（`value*10000` 千分位 + 「 元」，空/0 显示「0 元」，如「销售单价: 3,200,000 元 → 330,000 元」）；文件类字段（`featureDoc`/`contractFile`）值由散列名改为**原始名**（查 file_meta 无记录用散列名兜底，如「功能清单: → 产品说明书.pdf」）。**changes 中「万」字清零**。`logs.changes` 列维持 VARCHAR(512) 不变（元值最长 ~15 字符×2×2 字段 + 字段名，512 够用，无需迁移） | `src/services.py` |

### 未改动 / 保持不变的既有行为（回归依据）

- 上传文件仍以散列名落盘（`uuid4().hex.ext`），`uploads/` 文件名与既有资产/日志中存的散列名不变；`fileUrl` 契约不变。
- 其它 OpLog 写入点、金额 4 位小数、状态机、审计、锁定规则均不动。
- `logs.changes` 列长度不变（512），无数据库结构迁移。

### 自测（临时库 + 临时 uploads，8012 隔离，验证后已清理）

- 新库空 uploads 启动 → `file_meta 存量回填 0 条`；放 `abc123.pdf`+`产品说明书.pdf`（同内容）重启 → 回填 2 条且 `abc123.pdf→产品说明书.pdf`。
- `POST /upload 测试文件.pdf` → 返回 `storedName`（散列）+ `name=测试文件.pdf`；file_meta 新增 `uploadedBy=admin`。
- `GET /files/{storedName}` → `Content-Disposition: attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95%E6%96%87%E4%BB%B6.pdf`（解码=测试文件.pdf）。
- `PUT /assets/28` 改 salePrice 320→33、featureDoc→散列名 → `changes="销售单价: 3,200,000 元 → 330,000 元；功能清单: → 测试文件.pdf"`，无「万」字。
- 二次启动 0 新记录（幂等）；uploads 文件前后 ls 对比零移动/零增删。

---

## 2026-10-15 ｜ 资产详情四点对应的后端改造（2 字段迁移 + 4 处行为）

**关联任务**：资产详情四点后端改造（Architect 冻结契约）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | **`assets.featureDoc` 列**（VARCHAR(255) 默认 `''`）：功能清单附件（`/upload` 返回的 filename），替换原 `saleDetail` 电子表格的 UI 载体；`AssetOut`/`AssetInput` 加字段，`create_asset`/`update_asset` 白名单放行；**`saleDetail` 列与存量数据保留不动**（UI 不再展示，列不删）。`main.py` 幂等迁移补列 | `src/models.py`, `src/schemas.py`, `src/services.py`, `main.py` |
| 2 | 新增 | **`projects.subject` 后端权威推导**：`_create_project_core` 统一为 `project_input.subject or 首条有资产明细的 asset.subject`（手动建项目不传 subject 也有值；下单路径原已传，行为不变）；`update_project` 若明细里任一资产 subject 与 `p.subject` 不同，取首条明细资产 subject 覆盖；**存量项目 subject 为空不做批量回填**（前端展示时用资产主体兜底）。`projects.subject` 列已存在，`main.py` 仍加幂等补列（现有库 no-op） | `src/services.py`, `main.py` |
| 3 | 新增 | **`flows.operator` 列**（VARCHAR(64) 默认 `''`）：流水操作账号。所有写流水点（`add_flow`：purchase_in/project_lock/cancel_release/sale_out/manual_adjust）统一加 `operator: str = ""` 参数，`routers/api.py` 9 个写端点把 `get_current_user` 的 `user.username` 沿调用链传入（显式参数而非 contextvars：机械透明、默认 `""` 不改公共 API 语义、易审计）；`main.py` seed 路径写 `operator="system"`；存量流水保持空（前端显示 `-`）。`FlowOut` 加字段 | `src/models.py`, `src/schemas.py`, `src/services.py`, `src/routers/api.py`, `main.py` |
| 4 | 新增 | **`logs.changes` 列**（VARCHAR(512) 默认 `''`）+ `update_asset` 字段级 diff：对本次**实际变更**的白名单字段生成中文描述（映射表：name=资产名称/quantity=资产总数/salePrice=销售单价/repeatSale=可重复售卖/subject=所属主体/status=资产状态/featureDoc=功能清单/contractFile=产品清单 等，未映射用原名；quantity 带资产单位、salePrice 带「万元」，金额展示原值不换算；长文本字段 spec/saleDetail/remark 只记「已变更」不贴全文）；**仅 changes 非空时写 add_log**（无变更不打日志，替换原无条件「编辑」日志）。`LogOut` 加字段 | `src/models.py`, `src/schemas.py`, `src/services.py`, `main.py` |

### 未改动 / 保持不变的既有行为（回归依据）

- 金额 4 位小数、状态机（项目 3 态/资产 2 态）、审计（`record_audit`）、锁定规则（`it.locked`/repeatSale 早退/聚合校验）、BUG1/BUG2 修复逻辑均不动。
- 其它 OpLog 写入点（新建/删除/状态变更/出库…）行为不变，`changes` 为空。
- `update_asset` 的 repeatSale 切换「清零锁定」日志保留，与 changes 日志并存。
- 请求体契约不变（`featureDoc` 可选默认 `""`；`saleDetail` 入参保留兼容）。

### 提交后自测（临时库 8012 隔离，真实库副本 + 模拟旧库，curl 实测摘要）

- 建资产带 `featureDoc`（先 `POST /upload` 拿 filename）→ 200，bootstrap `assets[].featureDoc` 可见。
- 手动建项目（2 资产同主体、`subject=""`）→ `project.subject="验收主体A"`；`POST /sales/order` 同。
- `PUT /assets/29` 改 salePrice 1.5→2.5、quantity 5→8 → 最新编辑日志 `changes="销售单价: 1.5 → 2.5 万元；资产总数: 5 → 8 套"`；未变更字段（name/remark）不出现；改 spec → `changes="规格描述: 已变更"`；同值再 PUT → 不产生新日志。
- 建项目锁定 → flows 最新 `project_lock` 行 `operator="admin"`；交付 → `sale_out` 行 `operator="admin"`；存量 69/75 条流水 operator 为空不报错。
- 模拟旧库（DROP 3 新列）启动 → 3 行 `[migration] ... 列已补充`；二次启动 0 行（幂等）。
- 全新空库 seed → 全部 `purchase_in` 流水 `operator="system"`。

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

## 2026-10-16 ｜ 角色权限矩阵调整：生态人员（viewer）开放下单链路（契约冻结）

**关联任务**：角色权限矩阵调整（内部角色标识不变，仅权限矩阵 + 展示名口径）

**角色展示名口径（仅前端展示，内部标识不变）**：admin=管理员、editor=**商务人员**、viewer=**生态人员**。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `security.require_order` 依赖：已认证即可（admin/editor/viewer 均放行），用于下单链路端点；与 `require_editor`/`require_admin` 同风格（`Depends(get_current_user)` 包装） | `src/security.py` |
| 2 | 修改 | **viewer（生态人员）放行 6 个端点**（依赖 `require_editor` → `require_order`）：`POST /api/cart`、`PUT /api/cart/{id}`、`PATCH /api/cart/{id}`、`DELETE /api/cart/{id}`、`POST /api/cart/checkout`、`POST /api/sales/order`。其余端点依赖一律不动（`POST /projects`、`PATCH /contracts/{id}/status`、资产/出库/基础资料/交付物/用户管理写操作仍 `require_editor`/`require_admin`，viewer 维持 403）；`POST /cart/batch`、`DELETE /cart`（清空）维持 `require_editor`（不在本次放行清单） | `src/routers/api.py` |
| 3 | 不变 | editor（商务人员）维持现状全部可写（含合同状态变更、手动建项目）；admin 不变；业务逻辑/schemas/models 零改动 | — |
| 4 | 修改 | 收尾：`POST /api/cart/batch`、`DELETE /api/cart`（清空）依赖 `require_editor` → `require_order`，购物车 7 端点权限矩阵统一（viewer/生态人员放行），业务逻辑不动 | `src/routers/api.py` |

### 自测（隔离库 8011，/tmp/perm.db，已清理）

- viewer：`POST /cart` 200、`PUT /cart/{id}` 200、`PATCH /cart/{id}` 200、`POST /cart/checkout` 200（生成项目+合同）、`POST /sales/order` 200。
- viewer 403：`POST /projects`、`PATCH /contracts/{id}/status`、`DELETE /projects/{id}`、`POST /assets`、`POST /outbounds`。
- editor：`PATCH /contracts/{id}/status`（delivered）200（维持）。
- 匿名：`POST /cart`、`POST /sales/order` 均 401。

## 2026-10-16 ｜ OpLog 文件字段 diff 展示原始文件名

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | `update_asset` 字段级 diff 中文件字段（`contractFile`/`featureDoc`）old/new 值经 `_file_display_name` 查 `file_meta` 还原为原始文件名（无映射回退散列名），仅翻译展示值，存储值与其它日志路径不动 | `src/services.py` |

## 2026-10-16 ｜ 包量定价 pricingMode（ADR-008）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `assets.pricingMode` 列（VARCHAR(16) NOT NULL 默认 `'unit'`，幂等迁移）：`unit`（单价×数量）/ `amount`（包量合同金额整数元权威）；`AssetOut.pricingMode` 同步出参；**后端按类型权威决定**（`type='卫星Token'` → `amount`，其余恒 `unit`），不接受前端入参 | `src/models.py`、`main.py`、`src/schemas.py`、`src/services.py` |
| 2 | 修改 | 存量回填：`type='卫星Token'` 资产 `pricingMode='amount'`（幂等 UPDATE，`salePrice` 原值保留转参考值）；seed 数据卫星 Token 3 条同步置 `amount` | `main.py`、`src/seed_data.py` |
| 3 | 修改 | 销售明细计价分支：`amount` 模式明细 `amount`（整数元且 >0，否则 400「包量计价资产的销售金额须为整数元」）为权威输入，跳过 `price×qty` 重算，`price = round(amount/qty, 6)` 派生展示值；`unit` 模式行为完全不变。覆盖 `_create_project_core`（POST /projects）、`create_sale_order`（POST /sales/order，`items[]` 新增可选 `amount`）、`checkout`（POST /cart/checkout）；合同/项目金额合计同步按权威 amount | `src/services.py`、`src/schemas.py` |
| 4 | 修改 | `cart_items.amount` 列（FLOAT NULL，元，整数，幂等迁移）：`CartItemInput`/`PUT /cart/{id}`/`PATCH /cart/{id}` 接受可选 `amount`（amount 模式校验整数元后落库，unit 模式忽略）；checkout 时 amount 模式行必填（缺失 400）；`CartItemOut.amount` 出参 | `src/models.py`、`main.py`、`src/schemas.py`、`src/services.py` |

自测（curl 实测，详见 api.md 2026-10-16 小节）：卫星 Token 下单传整数金额 → item.amount 落库原值、price 派生；非整数/缺失 → 400；unit 模式回归不变（amount=price×qty 重算，前端传值忽略）。

## 2026-10-16 ｜ 购物车按登录用户隔离（ADR-009）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 ⚠️ | 购物车全部 7 端点（POST /cart、POST /cart/batch、PUT/PATCH/DELETE /cart/{id}、DELETE /cart、POST /cart/checkout）将 `get_current_user` 的 `user.id`（str）传入 services `user_id`；删除「本轮不按登录用户隔离」注释；`DEFAULT_USER` 常量保留但 router 不再使用 | `src/routers/api.py` |
| 2 | 修改 ⚠️ | `bootstrap` 签名改为 `bootstrap(db, user_id)`，`cart` 仅返回当前请求用户的行（不再用 DEFAULT_USER） | `src/services.py`、`src/routers/api.py` |
| 3 | 修改 | 存量回填：`cart_items.userId='admin'` 行 UPDATE 为 admin 账号 `users.id`（幂等，隔离后 admin 仍可见自己的存量行） | `main.py` |

不变：判重 (userId, assetId, customer)、库存校验、行级 customer 规则。

自测（curl 实测）：editor(id=3)/viewer(id=4) 分别加购不同资产，bootstrap 各自只看到自己的行；viewer 结算后自己购物车清空、editor 行不受影响；viewer 单加/批量加购/清空/结算均 200（require_order 放行）。

## 2026-10-16 ｜ 遥感数据资产类型（ADR-010）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 新增 | `assets` 4 个维度列（幂等迁移）：`province` VARCHAR(64) 默认 `''`、`city` VARCHAR(64) 默认 `''`、`resolution` FLOAT（单位**米**）、`imageDate` VARCHAR(10) 默认 `''`；`AssetIn`（可选入参）/`AssetOut` 同步（camelCase） | `src/models.py`、`main.py`、`src/schemas.py` |
| 2 | 新增 | `create_asset`：`type='遥感数据'` 时 省/精度/日期 必填（市可空）→ 缺失 400「遥感数据资产必须填写 省、精度、影像日期」；`(province, city, resolution, imageDate)` 组合重复 → 400「已存在相同 省/市 + 精度 + 日期 的遥感数据资产」（Python 层判重，无 DB 约束）；非遥感类型 4 字段忽略/置空 | `src/services.py` |
| 3 | 修改 | `update_asset`：允许修改 4 维度字段（含 diff 中文标签），同样唯一性校验（排除自身） | `src/services.py` |
| 4 | 修改 | 遥感数据入库默认值（后端兜底）：quantity 0→1、unit 空→`份（区域·精度·日期）`；repeatSale 由前端传（默认 True，允许关闭）；seed `category_units` 新增卫星板块「遥感数据」条目（新库生效） | `src/services.py`、`src/seed_data.py` |

自测（curl 实测）：创建遥感数据资产 200（id=29，保留为演示数据）；同三维组合再建 400 指定文案；改 imageDate 后建 200；update 改 city+imageDate 撞已有组合 400；bootstrap 输出含 4 新字段（其他类型为空/null）。

## 2026-10-16 ｜ 文档修正：万元口径过期描述（T2）

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修改 | 金额口径描述由「库内万元、4 位小数，前端展示为元」修正为「全程元（库内/接口/展示均为元，前端 ¥+千分位+两位小数）」；changelog 历史万元记录为历史事实，不改 | `README.md`、`docs/backend/database.md` |

## 2026-10-16 ｜ 修复：文件端点补鉴权 + PDF 预览 inline 参数

**关联任务**：修复 `GET /api/files/{filename}` 未鉴权安全洞（散列名被猜到即可下载任意上传文件）+ PDF 预览被强制下载导致 iframe/img 预览空白。

| # | 类型 | 变更内容 | 影响文件 |
|---|------|----------|----------|
| 1 | 修复 | 新增双通道认证依赖 `get_file_user`：优先 `Authorization: Bearer` 头，无头时接受 `?token=<jwt>` 查询参数（iframe/img 无法带请求头）；复用 `security.jwt_decode` 校验（未改动 security.py 公共函数签名），token 缺失/无效/过期/账号禁用一律 401「未登录或登录已过期」。`/files/{filename}` 由此移出匿名白名单（白名单仅剩 login/health） | `src/routers/api.py` |
| 2 | 修复 | `GET /api/files/{filename}` 新增查询参数 `inline: bool = Query(False)`：`true` → `Content-Disposition: inline; filename*=UTF-8''{quoted}`（内联预览）；缺省/`false` → 保持 `attachment`（下载行为不变） | `src/routers/api.py` |

自测（curl 实测）：无 token → 401；Bearer 头 → 200 + `attachment`；`?token=...&inline=true` → 200 + `inline`；坏 token → 401。浏览器（dev :5173）：「遥感数据-2026」抽屉点「预览」PDF 内联显示（不再下载），「下载」仍触发下载；docx 资产（智元机器人-G1）mammoth 解析正常。`python3 -c "import main"` 通过。
