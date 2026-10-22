# 测试变更日志（QA）

> 记录 core-holdings 的测试活动、验收结论与测试资产变更。格式：日期、类型、变更内容、影响文件、关联任务、备注。

| 日期 | 类型 | 变更内容 | 影响文件 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 回归验证 | FORMS-20261022 批次（ADR-036 产品登记规则 + ADR-037 生态人员购物车口径）独立回归：7 个重点回归面（viewer 区间分角色 / viewer 历史折扣 / 容器 repeatSale / inboundDate 自动生成 / 登记页表单重构静态走查 / 购物车 viewer 折扣 + 幂等回归 / 菜单改名）**44 项进程内断言 + 前端静态走查，全部通过，无新缺陷** | `backend/src/services.py`、`backend/src/schemas.py`、`backend/src/routers/api.py`、`frontend/src/views/assets/create.vue`、`frontend/src/views/cart/index.vue`、`frontend/src/layouts/MainLayout.vue`、`frontend/src/router/index.ts`、`frontend/src/views/settings/entities.vue` | FORMS-20261022 / ADR-036 + ADR-037 | 独立复核（不依赖后端 agent 自测）：数据库副本 `/tmp/ch_forms_regress.db` + TestClient 进程内断言（跑完即删，`/tmp` 无残留）；真实库全程 `mode=ro` 只读，行数复核未变（25 产品 / 2 项目 / 4 合同 / 97 明细 / 8 购物车 / 11 用户，`assets#29.repeatSale` 仍为 1）；未重启服务、未 build、未 commit；明细见下 |
| 2026-10-21 | 新增 | ADR-028 验收：禁编辑 + 撤销留痕（13 条用例全量执行，13/13 通过） | `backend/src/services.py`（`update_project` / `delete_project`）、`backend/src/routers/api.py`（`PUT/DELETE /projects/{id}`、`POST /projects/{id}/withdraw`、`POST /projects/{id}/refill-cart`）、`frontend/src/views/sales/projects/{index,detail,create}.vue`、`frontend/src/router/index.ts` | TASK-QA-034 / ADR-028 | 只读验收，未改动任何业务代码；后端在数据库副本（`/tmp/qa034/core_holdings.db`、dev server :8001）执行 A/B 组，前端在真实 dev 栈（:5173 + :8000）与隔离栈（临时 vite :5174 → :8001）执行 C 组；结论与证据见下 |
| 2026-10-22 | 回归验证 | FIX-20261022 全量修复批次独立复核：8 个重点回归面（状态机/终止回滚/幂等/可见性/权限登录/迁移幂等/前端静态/契约一致性）85 项进程内断言 + 3 项 fail-fast 子进程断言 + 前端静态走查，**88/88 通过，无新缺陷** | `backend/main.py`、`backend/src/services.py`、`backend/src/routers/api.py`、`backend/src/security.py`、`backend/src/schemas.py`、`frontend/src/views/cart/index.vue`、`frontend/src/views/sales/projects/create.vue`、`frontend/src/api/index.ts` | FIX-20261022 / ADR-029~034 | 独立复核（不依赖后端 agent 自测）：数据库副本 `/tmp/fixqa/core_holdings.db` + TestClient 进程内断言（跑完即删，`/tmp` 无残留）；真实库全程 `mode=ro` 只读，行数复核未变（28 产品/3 项目/7 合同/49 文件）；未启动/重启服务、未 build、未 commit；明细见下 |

## 2026-10-22 ｜ FORMS-20261022 回归验证明细（44/44 通过，无新缺陷）

### 执行方式

- **后端**：真实库复制到 `/tmp/ch_forms_regress.db`，`DATABASE_URL` 指向副本，Python 进程内 `import main`（迁移在副本上执行）+ FastAPI `TestClient` 全链路造数（建产品/明细 → 加购 → 改价 → checkout → 幂等重放），断言同时查接口响应 + 只读查库落库值。
- **前端**：静态走查（grep + 逐行读码），未起 dev server、未 build。
- **约束遵守**：未碰 uvicorn 进程、未 `npm run build`、未 `git commit`；`/tmp/ch_forms_regress.db` 与断言脚本跑完即删（`/tmp` 无残留）。
- **真实库无副作用证据**：验证前后只读行数一致（25 产品 / 2 项目 / 4 合同 / 97 明细 / 8 购物车 / 11 用户）；`assets#29.repeatSale` 仍为 1（编辑测试只在副本上执行）。

### 结论：7 个回归面全部通过

| # | 回归面 | 结果 | 关键断言（节选） |
|---|---|---|---|
| 1 | viewer 区间分角色（ADR-037 §3） | ✅ 12 项 | viewer `PUT /cart/{id}` 金额 1200>priceMax 1050 → 200、900<priceMin 1000 → 400（文案含参考区间）；**editor 同两方向均 400（原行为保持）**、区间内 1020 → 200；viewer checkout（unit 行 1200 超上限 + 遥感明细行 50000 超明细上限 20000~40000）→ 200 且落库 1200/50000；viewer checkout 低于下限（unit 900 / 遥感 10000）→ 400；editor checkout 超上限 → 400 |
| 2 | viewer 历史 discountRate（ADR-037 §2） | ✅ 7 项 | 造 viewer 行 `discountRate=0.5` + 手填 amount=1200 → 200 不 400、amount=1200 落库（**非 1200×0.5**）、rate 快照保留；改价 amount=1100（不传 rate）→ 200 且落库 1100（**非 550**）；checkout → 200 且 `project_items` 落库 amount=1100 + discountRate=0.5 快照保留 |
| 3 | 容器 repeatSale 规则（ADR-036 §4） | ✅ 8 项 | 新建容器 `repeatSale=true` → 400（文案「遥感数据容器按明细售卖，不支持重复售卖」）；**编辑存量 `assets#29`（repeatSale=1，前端提交 false）→ 200 且落库 false（不 400 卡死）**；容器改回 true → 400；普通产品 true/false 均 200；普通产品改 `type=遥感数据` + `repeatSale=true` → 400（type 变更路径） |
| 4 | inboundDate 自动生成（ADR-036 §1） | ✅ 11 项 | 新建不传 → 200 且落库=当天；传空串 → 当天；传 `2026-01-05` → 原样；传 `2026/01/05` → 400；**编辑产品不传 inboundDate → 原值保留**（unit 机器人 2026-03-15 + 遥感容器 2026-05-20 两类型均验证）；编辑传值可改（2026-06-01） |
| 5 | 登记页表单重构静态走查（ADR-036 §5） | ✅ 静态 | 三形态字段齐全无新增：新建普通 4 卡（基本信息/数量与价格/有效期与附件/状态与备注）、新建遥感容器（数量与价格整卡隐藏 + 容器禁用态开关 + info-bar）、编辑（board/type 禁用 + 登记时间只读文本行）；必填 rules 保留 name/board/type/subject/unit/quantity（inboundDate 已移除）；区间自动同步 `watch(salePrice)` 有 `isEdit/isRemote/v>0` 守卫（编辑不同步）、salePrice 联动**不置位** touchedMin/touchedMax、区间输入 `@change` 置位后不再覆盖；`handleSubmit` 新建 `inboundDate:''` |
| 6 | 购物车 viewer 折扣 + 幂等回归（ADR-037 / ADR-033） | ✅ 3 项 + 静态 | 折扣输入 `v-if="!row.isAmount && !isViewer"`（amount 行叠加）、折扣摘要 `v-if="discountPreviewRate!=null && !isViewer"`、金额 placeholder/顶部提示条角色条件；`onAmountChange` viewer 手改不清镜像 rate（195）、`stepQty` viewer 不用旧 rate 回填金额（490）；**editor/admin 折扣计算函数（discountPreviewRate/discountSummary/amountPlaceholder/onDiscountChange）零 isViewer、渲染层加角色条件，路径零变化**；requestId 幂等（首次 idempotent=false、重复命中 true 同项目 id）未被本批破坏 |
| 7 | 菜单改名（ADR-036） | ✅ 静态 | 「公司主体」在侧边栏菜单（`MainLayout.vue:114`）、viewer 直达提示（`router/index.ts:173`）、设置页面包屑+页头（`entities.vue:120/121`）三处一致；全仓 grep「资产主体」「长期买断」用户可见文案 **0 残留**（命中均为注释中的改名引述，任务允许保留） |

### 观察项（不计缺陷，供排期参考，详见 `bug-tracker.md`）

1. **ADR-036 §3 区间自动同步「跟随」语义与实现略有出入**：ADR 正文括注「重新填单价且区间仍为『上次自动值』时继续跟随」，实现采用 `touchedMin/touchedMax` 布尔标记（手改一次即永久停止跟随该边界，即使后续值恰好回到上次自动值也不再跟随）。属极窄边界（用户手改区间后再改单价的叠加场景），changelog 已按标记口径记录「手改后不再自动覆盖」，功能无异常，建议下轮文档维护时统一 ADR §3 括注与实现口径。

## 2026-10-22 ｜ FIX-20261022 回归验证明细（88/88 通过，无新缺陷）

### 执行方式

- **后端**：真实库复制到 `/tmp/fixqa/core_holdings.db`，`DATABASE_URL` 指向副本，Python 进程内 `import main`（迁移在副本上执行）+ FastAPI `TestClient` 全链路造数（加购 → checkout → claim → review → 录签订时间 → 交付 → 撤销 → 终止），断言同时查接口响应 + 只读查库；迁移幂等用**独立子进程二次 `import main`** 对比 17 张表行数。
- **前端**：静态走查（grep + 逐行读码），未起 dev server、未 build。
- **约束遵守**：未碰 uvicorn 进程、未 `npm run build`、未 `git commit`；`/tmp/fixqa` 跑完即删。
- **真实库无副作用证据**：验证前后只读行数一致（28 产品 / 3 项目 / 7 合同 / 97 明细 / 49 文件 / 0 交付物 / 0 幂等记录）；期间 `cart_items` 11→8 为运行中服务的正常业务活动（审计日志 11:00-11:04 有真实用户登录/操作），非 QA 写入。

### 结论：8 个回归面全部通过

| # | 回归面 | 结果 | 关键断言（节选） |
|---|---|---|---|
| 1 | 状态机（ADR-032） | ✅ 14 项 | 合同级无签订时间交付 400（文案含合同编号）；项目级批量「1 有签订时间 + 1 无」→ 整体 400 列出全部不合规合同且**两条合同状态都不变**；部分合规场景合规项也不被部分执行（全量或全不）；补齐后批量 200；合同级既有交付路径不变 |
| 2 | 终止回滚（ADR-032 §3） | ✅ 16 项 | delivered 合同终止 → `shippedQty/soldCount/soldAmount/lockedQty` 精确回到交付前基线、交付单 `reverted`、`manual_adjust` 流水与结构化日志齐全；**BUG-04 原始场景**（单合同 2 明细 → 全交付 → 撤销 1 条 → 终止）剩余 shipped 明细精确回退、零残留、项目派生 terminated；产品已删（物理删模拟存量）→ 400「该产品/明细已不存在」且合同/明细/交付单均不变（无半回滚） |
| 3 | 幂等（ADR-033） | ✅ 11 项 | 同 `requestId` 重复请求（购物车已空）→ 200 `idempotent:true` 同一项目、不重复建单、`idempotency` 表该键仅 1 行；不带 `requestId` 行为与旧版一致（空车 400 / 正常结算）；**失败请求回滚占位**（400 后同 `requestId` 可重试成功）；表行数不异常增长 |
| 4 | 可见性（ADR-030） | ✅ 12 项 | admin/editor files 全量 49、viewer 被过滤且**全部为被产品引用文件**（无孤儿、无 `uploadedBy` 泄漏）；viewer logs 无 `target=contract`；viewer flows 全部可归属可见项目/合同（按 `contractId` 权威外键）；被引用文件 viewer 下载 200 + `nosniff`；孤儿文件 viewer 404 / admin 200 |
| 5 | 权限与登录（ADR-034） | ✅ 11 项 | `/users/options` viewer 403 / editor 200（且不含 viewer 账号）；错密码 10 次后第 11 次 429 文案一致；禁用/不存在账号失败文案统一（不暴露存在性）；改密 `tokenVersion` 0→1 后旧 token 401「登录状态已失效」；进程内签旧 `ver` token → `user_from_token` 401；生产 fail-fast 3 例（默认密钥/未设置 → RuntimeError，强密钥 → 正常） |
| 6 | 迁移幂等（ADR-031） | ✅ 5 项 | 同副本连续 `import main` 两次：17 张业务表行数**零变化**、`schema_migrations` 无重复、预置 1 行 `asset_deliverables` 未被清空（BUG-01 修复有效） |
| 7 | 前端静态走查 | ✅ 4 面 | BUG-09：全仓 grep 写操作 `await` 共 45 处，仅 5 处「函数内无 try」且均为包装函数/`.then().catch()` 链（调用方均有 catch），无漏网；BUG-06：amount 行折扣三处拦截全部落实（模板 `v-if="!row.isAmount"`、`discountPreviewRate` 提前 return null、`onDiscountChange` 提前 return）；`qtyBusy` 行级锁 `finally` 释放 + 按钮 `:disabled` 联动，无死锁/泄漏；`refreshSeq` 序号丢弃旧快照 + `finally` 只清自己持有的锁；`crypto.randomUUID` 唯一使用点为 cart 结算，部署形态 `http://localhost:5173`（安全上下文，可用） |
| 8 | 契约一致性 | ✅ 9 项 + 静态比对 | `POST /sales/order`、`POST /projects/{id}/resubmit` → 410 文案逐字一致；review `serviceStart/serviceEnd` 显式 `null` 清空生效、未传保持原值；checkout 响应字段名 `idempotent`；`contractAmount ≠ Σ明细` → 400 文案一致且先校验后写；`PUT /cart/{id}` 非法入参 422；429/nosniff/404 探测口径均与 `api-contracts.md` FIX-20261022 批次一致 |

### 观察项（不计缺陷，供排期参考，详见 `bug-tracker.md`）

1. **存量流水 ref 与合同编号漂移**：5 条历史 `flows`（id 78/136/160/164/212）`contractId` 指向可见合同但 `ref` 为已不存在的旧编号（`HT-0007` 等，合同编号被历史清理脚本改过、流水 ref 未同步）。可见性判定按 `contractId` 权威外键放行，**无越权泄漏**，仅展示层编号对不上；属历史数据卫生问题。
2. **ADR-034 §1 文档与实现口径漂移**：ADR 正文写 dev「进程内随机密钥（重启即失效）」，实际按 FIX-20261022-FOLLOWUP 实现为**持久化开发密钥文件** `backend/.jwt_secret`（0600，重启不换密钥）——实现与 changelog/已知取舍一致且更优，建议下轮文档维护时把 ADR-034 §1 的 Decision 1 同步为持久化口径。
3. **`api-contracts.md` §4 表格文案为摘要口径**：「项目级批量交付」一行 detail 写 `合同 {code} 尚未录入签订时间，不可交付（可多条）`，实际文案为 `以下销售记录不满足交付条件，请先补齐后重试：{code} 尚未录入签订时间，不可交付`（与后端 changelog 实测一致）。前端只透传 detail 不依赖具体文案，无功能影响。

## 2026-10-21 ｜ ADR-028 验收明细（禁编辑 + 撤销留痕）

### 执行方式（不改代码、不清理真实业务数据）

- **A/B 组（接口级）**：复制真实库到 `/tmp/qa034/core_holdings.db`，以 `DATABASE_URL` 指向副本启动 `uvicorn main:app --port 8001`；造数走真实业务链路（加购 → `/cart/checkout` 生成 pending），断言同时查接口响应 + 只读查库。
- **C 组（浏览器实测）**：
  - 真实栈 `:5173`（代理 `:8000`）：`viewer / 123456` 走「购物车下单 → 撤销 → 重下」，实测 UI 入口与文案；
  - 隔离栈临时 vite `:5174`（临时配置 `/tmp/qa034/vite.qa034.config.mjs`，代理 `:8001`）：补齐「pending 单在 admin / 商务视角」的入口回归（避免在真实库再留 pending 测试单）；
  - 用例完成后临时服务（8001 / 5174）已停止，`:8000`、`:5173` 保持原状。
- 真实库仅新增 1 条按产品预期**应当保留**的撤销留痕单（`SP-2026102120020331`，`terminated` + `cartRefilled=1`，creator=`viewer`），未执行任何 DELETE 清理，未改 schema。

### 结论：13/13 通过，无缺陷

| # | 用例 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | viewer 编辑自己 pending | 通过 | `PUT /projects/3` → 403 `订单已提交，不可编辑；如需修改请「撤销」后重新下单`；库内 `name` 未被改写 |
| 2 | viewer 编辑他人 / 不存在项目 | 通过 | 他人项目 → 403 同文案；`/projects/999999` → **404 `项目不存在`（404 优先）** |
| 3 | 商务非负责人 → 负责人 / admin | 通过 | 非负责人 `PUT` → 400 `待审核项目仅商务负责人（或管理员）可编辑基本信息`；`claim` 后（businessOwner=editor）→ 200；admin → 200 |
| 4 | viewer `PATCH /contracts/{id}` | 通过 | 403 `只读账号不可执行该操作`，`contracts.signedDate` 仍为 NULL（无旁路编辑） |
| 5 | viewer 终止自己 active/pending | 通过 | pending → 200 且 `status=terminated`；admin 确认下单转 active 后 viewer 再终止 → 200（撤销≠终止，ADR-028 Decision 4 保留） |
| 6 | 撤销 + 留痕（端到端） | 通过 | `POST /projects/{id}/withdraw` → 200 `{restored:1, skipped:0}`；项目行仍在且 `status=terminated`、`cartRefilled=1`；合同 `status=terminated`、`remark='撤销：QA-034撤销原因'`；product `lockedQty` 1→0；`flows` 出现 `cancel_release`（ref=合同号）；`logs` 有「撤销订单」含原因；`audit_logs` 有撤销记录；`cart_items(userId=viewer)` 已回填（asset/qty/amount/customer 一致） |
| 7 | 撤销后 admin `DELETE` | 通过 | 403 `该订单已撤销（或已回填购物车）并将保留历史记录，不可删除`；库内 `projects` 行=1、`project_items` 行仍存在（**记录不删除核心断言**） |
| 8 | 被驳回从未回填 → 仍可删除 | 通过 | admin 接手后 `review reject` → `terminated` 且 `cartRefilled=0` → `DELETE` → 200，项目行消失（既有清理能力未误伤） |
| 9 | 重新提交幂等 + 重下 | 通过 | 连续两次 `refill-cart` → 均 `alreadyRefilled:true`，`cart_items` 行与数量不变（无翻倍）；随后 `/cart/checkout` 生成新 pending 单，旧单仍 `terminated` 且存在 |
| 10 | viewer 列表/详情/直达 edit | 通过 | 列表快照「编辑/审核订单」出现次数 **0**；详情页「编辑」出现次数 **0**；直达 `/sales/projects/3/edit` → toast `订单已提交，不可编辑，如需修改请「撤销」后重新下单` + 落地 `/sales/projects/3/detail`（无白屏、无重定向死循环） |
| 11 | viewer 撤销 / 重新提交入口 | 通过 | pending 详情头部只有「撤销」；撤销成功后跳 `/cart`；已撤销详情头部「重新提交」可点且跳 `/cart`；列表该行操作列 = 「重新提交 + 删除(禁用)」 |
| 12 | 已撤销单留痕可见性 | 通过 | 详情页出现 `该订单已撤销，历史记录已保留；撤销原因见下方销售记录备注`；销售记录卡片显示 `撤销：UI验收撤销原因` |
| 13 | 商务/管理员入口无回归 | 通过 | 列表/详情实测：pending 未接手 → `接手 + 撤销 + 审核订单(禁用)`；pending 已接手 → `转交 + 审核订单`；active → `转交 + 编辑 + 删除`；terminated → `编辑(禁用) + 重新提交 + 删除`（admin 列表另有 `撤销`，符合既有口径） |

### 真实库关键证据（读接口 + 只读查库）

- 撤销后：`projects(3)` = `('SP-2026102120020331','QA034-UI验收单','terminated', cartRefilled=1, creator='viewer')`；合同 `('HT-2026102120020335','terminated','撤销：UI验收撤销原因')`。
- 锁定释放：`assets(1).lockedQty` 1 → 0；`flows` = `(asset 1, cancel_release, qty 1, ref=HT-2026102120020335)`。
- 留痕：`logs` 三条（新增项目 / 销售记录状态变更 / **撤销订单**「待审核订单已撤销，1 行明细回填购物车…原因：UI验收撤销原因」）；`audit_logs` = `(viewer, 撤销订单, target=3, reason=UI验收撤销原因)`。
- 回填：`cart_items(userId='4')` = `(asset 1, qty 1, amount 3006700, customer 'QA034-UI客户')`。
- 删除护栏（真实库实打）：`DELETE /api/projects/3`（admin）→ `403 {"detail":"该订单已撤销（或已回填购物车）并将保留历史记录，不可删除"}`，随后复查 `projects.id=3` 仍存在。

### 备注（非缺陷观察，供后续排期参考）

1. 仓库当前**无自动化测试套件**（无 `tests/`、无 pytest/vitest/playwright 配置），本批次以接口脚本 + 浏览器实测覆盖；建议后续补 ADR-028 相关后端用例基线（`update_project` viewer 403、`delete_project` 留痕护栏、`withdraw` 链路）。
2. `review`（确认下单/驳回）对**未接手**订单一律 400「该订单尚未被商务接手，请先接手后再操作」，admin 亦需先 `claim`——属既有守卫（ADR-012 §5.1），与 ADR-028 无关，仅记录以免误判为回归。
3. 撤销成功后前端统一跳 `/cart`（详情/列表同口径），已撤销提示条需回详情页查看——与 ADR-028 Decision 5 文案设计一致，非缺陷。
