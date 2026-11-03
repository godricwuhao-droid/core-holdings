# 后端变更日志

> 记录 core-holdings 后端（FastAPI + SQLAlchemy + SQLite）的接口与行为变更。

## 2026-10-22 ｜ ADR-044：`asset_deliverables.url`（外部链接）+ 协议白名单校验

> **依据 ADR-044（Accepted，2026-10-22，业务方要求「交付物支持填入 URL 链接」）**。删除端点（`api.py:836`，`DELETE /assets/{id}/deliverables/{item_id}`）**已存在，本任务未改**。
> `url` 会被渲染为可点击 `<a>`，`javascript:` / `data:` 伪协议 = 存储型 XSS 入口 → 后端白名单校验（400），不接受「只在前端校验」。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | `asset_deliverables.url`（外部链接）+ 协议白名单校验（仅 http/https，否则 400）+ schema 三处同步 | `backend/src/models.py`、`backend/main.py`、`backend/src/schemas.py`、`backend/src/services.py`；`docs/backend/{database,api,changelog}.md` | ADR-044 / DELIV-20261022-B | 结构迁移幂等（`deliv_cols` 复用，未重复 inspect）；存量行 `url=''`；删除端点未改；**未 commit** |

改动明细：
- `models.AssetDeliverable`：`file` 之后新增 `url: Mapped[str] = mapped_column(String(512), default="")`（`''` = 无链接；与 `file` 可并存、均非必填）。
- `main.py::_ensure_migration`：在 `asset_deliverables.file` 补列段之后追加第 18 段幂等补列——`if "url" not in deliv_cols: ALTER TABLE asset_deliverables ADD COLUMN url VARCHAR(512) DEFAULT ''`（**纯结构迁移**，不写 `_run_once`、不做数据回填，ADR-031）。
- `schemas.py`：`AssetDeliverableInput.url: str = ""`、`AssetDeliverableUpdate.url: str | None = None`（docstring 补「`url`：外部链接，`""`/null = 清空」）、`AssetDeliverableOut.url: str`。
- `services.py`：新增模块级 `DELIVERABLE_URL_MAX = 512` + `_normalize_deliverable_url`（**唯一出口**：`strip` → 空=`''` → 非 `http(s)://` 前缀 400「链接地址必须以 http:// 或 https:// 开头」→ 超长 400「链接地址过长（最多 512 字符）」）；`add_asset_deliverable` 写入归一值；`update_asset_deliverable` 在**任何 setattr 之前**归一 patch 里的 `url`，并把 `url` 加入 setattr 白名单元组，`exclude_unset` 语义保持不变（未传=不动 / `""`/null=清空）。
- `api.py` **未改**（`Input/Update/Out` 变更自动生效）；删除端点、权限、`file` 附件逻辑、`updatedAt` 刷新逻辑均未动。

实测（副本库 `/tmp/adr044.db`，独立进程 uvicorn :8013，真实 HTTP；生产库 `core_holdings.db` 仅只读核对 + dev `--reload` 触发的补列）：
- **迁移幂等**：副本库（预置删掉 `url` 列）连续两次执行迁移函数——第 1 次 `[migration] asset_deliverables.url 列已补充（ADR-044 交付物外链）`，第 2 次无输出/无动作；`PRAGMA table_info` → `url VARCHAR(512) dflt_value=''`。
- **新增带链接**：`POST /api/assets/1/deliverables` `{"name":"交付说明书",…,"url":"https://example.com/doc"}` → **200** `{"ok":true}`；bootstrap `assetDeliverables["1"]` 含 `"url":"https://example.com/doc"`。
- **协议白名单**：`javascript:alert(1)` / `data:text/html,<script>` / `ftp://x` → 均 **400**「链接地址必须以 http:// 或 https:// 开头」，行数不变、id 无跳号；`https://`（形似合法边界）→ **200**（只做前缀白名单，不做深度校验，已知边界）。
- **首尾空格**：`"  https://a.com/x  "` → 落库 `https://a.com/x`（`length=15`）。
- **更新语义**：`{"url":"  http://b.com  "}` → 落库 `http://b.com`；`{"status":"todo"}`（不传 url）→ `url` 保持 `http://b.com`（`exclude_unset` 未破坏）；`{"url":""}` 与 `{"url":null}` → 均落库 `''`；非法/超长 PUT → 400 且原值不变。
- **超长**：513 字符 https URL → **400**「链接地址过长（最多 512 字符）」，未落库；512 字符 → **200**（边界值可入库）。
- **删除端点回归**：`DELETE /api/assets/1/deliverables/8` → **200** `{"ok":true}`，行 8→7，审计 `删除交付物` 1→2（`detail="删除交付物「512边界」"`）。
- **生产库**：补列前后均 3 行，逐行 `id/name/file` 完全一致，仅多出 `url=''`；审计 `删除交付物` 仍为 1（本任务测试全部跑在副本库）。

## 2026-10-22 ｜ ADR-043：`refill-cart` 拒绝商务（editor）角色

> **依据 ADR-043（Accepted，2026-10-22，业务方要求「商务人员不能重新提交」）**。
> 回填目标**恒为下单人**（`_withdraw_owner`），商务点完自己购物车无任何变化，只是「提示成功但什么也没发生」；
> 合法路径 = 通知下单人本人重新提交，或由 admin 代操作。**无新表、无迁移**，`mode` 语义 / `replace` 双守卫 / 返回结构 / 撤销路径全部未变。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | `refill-cart` 拒绝商务（editor）角色（403），权限收敛为 viewer 本人 + admin | `backend/src/services.py`（`refill_project_cart` 守卫链 + docstring 权限段）；`docs/backend/api.md` | ADR-043 / REFILL-20261022-B4 | **Breaking（行为变更）**：editor 由 200 变 403；撤销权限未变；未 commit |

改动明细：
- `services.refill_project_cart`：守卫链在 `viewer` 权限判定之后、`owner` 解析之前追加 `if user.role == "editor": raise HTTPException(403, "商务人员不可使用「重新提交」，请通知下单人本人操作")`——**位于任何写操作之前**（购物车 / `projects.cartRefilled` / OpLog 一行未动）；docstring 权限段改写为「viewer 仅本人项目 / admin 放行 / **editor 403**」，注明**部分取代 ADR-027 的 editor 放行**。
- 路由 `POST /projects/{id}/refill-cart` 的 `require_order` **未动**（三角色都能进端点，由业务级守卫拒绝，错误信息更准确）；`withdraw_project` **未动**（商务仍可撤销）。
- 未改 `mode` 语义、未改 `_refill_cart_from_project`、未改返回值结构；未 commit、未重启 8000。

实测（副本库 `/tmp/adr043.db`，独立进程 uvicorn :8013，真实 HTTP；生产库 `core_holdings.db` 只读核对计数不变）：
- **editor 被拒**：`lshangkun`（副本库内置为 editor、且为项目 creator）本人项目 `mode=merge` → **403** `{"detail":"商务人员不可使用「重新提交」，请通知下单人本人操作"}`；调用前后该用户 `cart_items`（0 行）、`projects.cartRefilled`（0）、`logs`（669）、`audit_logs`（1118）**逐项未变**；
- **editor 对他人项目**（`creator=zyajie`）→ 同样 **403** 同文案（业务级拒绝优先于 viewer 归属判定）；另一真实 editor `wuhao` 对 `lshangkun` 项目 → 也 403；
- **viewer 不受影响**：`zyajie` 对自己项目 → **200**（`restored=1`）；对他人项目 → **403**「生态人员仅可重新提交自己下单的项目」（原文案）；
- **admin 不受影响**：admin 对 `lshangkun` 项目 `mode=merge` → **200**（`owner={id:2,username:lshangkun}`，2 行 `insufficient` 跳过）；同项目 `mode=replace` → **400**「只能对本人购物车执行『清空后回填』，他人项目请使用合并」（ADR-042 补遗2 未破坏）；
- **撤销不回归**：editor `lshangkun` 对 pending 项目 `withdraw` → **200** `{"ok":true,"restored":2,"amountFallback":0,"skipped":0,"skippedReasons":[]}`。

## 2026-10-22 ｜ ADR-042：重新提交回填购物车 —— 替换语义 + `mode` 参数 + 逐行结果 + 可售不足说明

> **依据 ADR-042（Accepted，2026-10-22，业务方确认「弹窗让用户选」+「合并=替换不累加」+「补可售不足说明」）**。
> 实测病灶：被驳回项目 `SP-2026102216581487`（`cartRefilled=0`）2 行明细，产品 27/32 库存 1、`lockedQty=1`（被 pending 项目 4 锁走）→ 可售 0 → 全部跳过 → 购物车空，前端仍跳 `/cart`；
> 另有两缺陷：同键累加导致**重试翻倍**、回填目标恒为**下单人**导致代操作者看到空车（本次只补后端 `owner` 归属信息，动线由前端改）。
> **无新表、无迁移、不改 `cartRefilled` 布尔含义、不改 `POST /cart`（加购仍累加）、不改 `cart/checkout`、不改撤销的日志文案与流转事件。**

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | 重新提交回填购物车：①同键由累加改替换（修重试翻倍）②新增 `mode=merge\|replace`（replace 清空后回填且跳过幂等）③响应增 `rows/owner/mode/forced/cleared` ④可售不足原因带库存数值与占用提示 | `backend/src/services.py`（`_cart_add_inner` / `_refill_cart_from_project` / `refill_project_cart` / `withdraw_project` 调用点）；`backend/src/routers/api.py`（`POST /projects/{project_id}/refill-cart` 增 `mode` 查询参数） | ADR-042 / REFILL-20261022-B | 旧字段全保留（非 Breaking）；`POST /cart` 累加语义未变；撤销日志文案未变；未 commit |
| 2026-10-22 | 修复 | replace 预检前移（全失败不清空，修数据破坏）+ replace 仅限本人购物车（防跨用户清空） | `backend/src/services.py`（`_refill_cart_from_project` 两阶段重构 / `refill_project_cart` owner 解析提前 + 新模式守卫） | ADR-042 补遗1/2 / REFILL-20261022-B2 | 非 Breaking（新参数内部加固）；未改 merge 语义、未改撤销路径；未 commit |
| 2026-10-22 | 修改 | `rows[]` 增补 `assetId/code/need`（供前端结构化渲染失败原因），`reason` 文案与 `skippedReasons` 均未变 | `backend/src/services.py`（`_refill_cart_from_project` 的 `_row` / `planned` 预检 / 写阶段跳过分支；新增常量 `REFILL_ROW_CODES`）；`docs/backend/api.md` | REFILL-20261022-B3 | 纯加性，非 Breaking；未 commit |

改动明细：
- `_cart_add_inner(..., *, existing_policy: str = "accumulate")`：新增关键字参数，取值 `accumulate`（默认，加购零变化）/ `replace`（命中同键行 → **覆盖** `qty/amount/serviceStart/serviceEnd` + `updatedAt` 刷新，不新增行、不累加）；非法取值 → 400；可售/区间/客户校验两条路径同等生效（`replace` 的净增按「本次值 − 原值」计，避免覆盖式回填被存量行误判超可售）。
- `_refill_cart_from_project(db, p, target_user_id, *, mode="merge")`：`replace` 先 `_clear_cart` + `db.flush()`（同事务、不 commit）并记 `cleared`；逐行**预检可售**（复用唯一实现 `_avail`）不足则不进 `_cart_add_inner`，直接产出带库存数值的原因；回填统一走 `existing_policy="replace"`；返回值扩展 `mode/cleared/rows`（旧 4 字段保留）。
- `refill_project_cart(db, project_id, user, mode="merge")`：`mode ∉ {merge,replace}` → 400「非法的回填模式」（写操作前校验，单事务）；幂等短路**仅对 merge 生效**（`replace` 返回 `forced=true`）；响应加 `owner/mode/forced/cleared/rows`；OpLog `replace` 追加「（mode=replace，清空原有 C 行）」、`merge` 保持原文案。
- `withdraw_project`：调用点改 `mode="merge"`（撤销**不清空**购物车），自动获得替换语义（撤销同键不再翻倍）；**返回结构与 OpLog 文案逐字未改**。
- 路由 `POST /api/projects/{project_id}/refill-cart`：增 `mode: str = Query("merge")` 透传，权限 `require_order` 不变；`replace` 时 `audit_logs.detail` 追加 `, mode=replace, cleared=C`。

实测（副本库 `/tmp/adr042.db`，进程内 TestClient；生产库 `core_holdings.db` 全程只读，未起 8000、未 build、未 commit）：
- **替换语义**：购物车预置 `(assetId=33, 客户X) qty=1 / amount=500 / 2026-01-01~01-31`（`updatedAt` 人为拨旧）→ 明细同键 qty=1/amount=800/2026-02-01~02-28 → `mode=merge` 回填后该键**仍 1 行**、`qty=1`（非 2）、`amount` 500→**800**、服务期限覆盖为 02-01~02-28、`updatedAt` 刷新；
- **重试不翻倍**：同上项目含一行被锁满明细（可售 0）→ 第 1 次 `restored=1/skipped=1`、`cartRefilled=0`；第 2 次（`merge`）→ 成功行 `qty` 仍为 **1**（未变 2）；
- **`mode=replace`**：购物车预置 3 行无关商品 → `cleared=3`、`restored=1`、`forced=true`、`alreadyRefilled=false`，无关行全清、仅剩本项目明细；`cartRefilled=1` 后再传 `replace` → `cleared=1/restored=1/forced=true`（**未被短路**）；同状态传 `merge` → `alreadyRefilled=true/mode=merge/rows=[]`，`cart_items`+`logs` 逐字节未变（672 → 672）；`mode=bogus` → 400「非法的回填模式」；
- **可售不足文案**：真实项目 `SP-2026102216581487` → `restored=0`、`skipped=2`，`rows` 两行 `ok=false`，reason 含「可售数量不足 / 库存 1 / 已锁定 1 / 已被其他订单占用」，**不含**「折扣」字样；`owner={id:2, username:lshangkun, name:刘尚坤}`；
- **撤销不回归**：pending 项目 `withdraw` → 返回键集合仍为 `{ok, restored, amountFallback, skipped, skippedReasons}`；OpLog detail 逐字等于改动前模板「待审核订单已撤销，1 行明细回填购物车（原价回填 0 行，跳过 0 行），原因：…」；回填成功、`cartRefilled=1`；另测撤销同键（购物车已有 qty=2）→ 回填后 **qty=1**（覆盖，非 3）；
- **加购不回归**：`POST /cart` 两次同产品同客户 → 单行 `qty=2`；
- **可重复售卖不误伤**：`repeatSale=1` 且可售 0 的产品回填 → `restored=1/skipped=0`（预检按既有 `_check_stock` 口径对 repeatSale 豁免）；
- `python3 -m compileall src main.py` 通过；副本库与临时脚本已清理。

补遗1/2 实测（REFILL-20261022-B2，副本库 `/tmp/adr042b2.db` + 进程内 TestClient；生产库 `core_holdings.db` 全程只读）：
- **A-1 全失败不清空**：真实项目 `SP-2026102216581487` + 下单人购物车预置 2 行 → `mode=replace` → `cleared=0`、`restored=0`、`skipped=2`、`rows` 两行 `ok=false`，**该用户 `cart_items` 仍为原来那 2 行（id 8/9 一条未删）**；
- **A-2 部分可行仍清空**：造场景 1 行可行（asset 26）+ 1 行可售 0（asset 27，库存 1/锁定 1）→ 预置 2 行无关 cart → `replace` → `cleared=2`、`restored=1`、`skipped=1`，购物车只剩可行那一行；
- **A-3 merge 不受影响**：同场景 `merge` → `cleared=0`、原有无关行仍在、同键行 `qty` 仍为 1（未累加）；
- **B 跨用户拒绝**：admin 对 creator=`lshangkun` 的项目调 `replace` → **400**「只能对本人购物车执行『清空后回填』，他人项目请使用合并」，且下单人购物车 2 行**一行未删**（守卫在写之前）；同项目 admin `merge` → 200，回填目标仍为下单人；
- **幂等优先级**：`cartRefilled=1` + `merge` → `alreadyRefilled=true/rows=[]` 且 `cart_items`/`logs` 计数不变；`replace` 由本人调用 → 跳过幂等、`cleared=4/restored=2`；
- **生产库**：`projects/cart_items/logs` = 4/4/658，改动前后一致；`compileall` 通过；副本库与临时脚本已清理。

B3 实测（REFILL-20261022-B3，副本库 `/tmp/adr042b3.db` + 进程内 TestClient；生产库 `core_holdings.db` 全程只读）：
- **insufficient**：真实项目 `SP-2026102216581487`（`mode=merge`）→ `rows` 两行 `ok=false, code="insufficient", assetId=32/27, need=1`；`mode=replace`（可行行 0 → 走阶段 2a 分支）同样两行带 `code/assetId/need`；
- **reason 逐字未变**：用「改动前基线模块」（对当前文件反向打补丁 10 处还原的旧实现）产出的 `rows` 做逐字节比对——`reason` 列表相等、旧 4 键（`assetName/qty/ok/reason`）整行相等、`skippedReasons` 相等；
- **no_asset**：`assetId=999999`（产品已不存在）→ `code="no_asset", assetId=999999`；`assetId=None`（未关联产品）→ `code="no_asset", assetId=null`；
- **other**：产品 26 明细 `amount=5000000`（非空）+ 服务期限 `2026-12-31 ~ 2026-01-01` → 首次与降级 `amount=None` 均 400 → `code="other"`（纯「金额超区间上限」降级后会成功，属 `amountFallback`/`ok`，故用降级后仍失败的期限校验构造）；
- **ok**：产品 26 明细 `qty=3`（副本库库存临时调为 5）→ `code="ok", need=3, assetId=26, reason=""`；
- **生产库**：`projects/contracts/project_items/cart_items/logs/audit_logs/flows/assets/users` 计数前后完全一致；`compileall` 通过；副本库与临时脚本已清理。

## 2026-10-22 ｜ USERS-20261022：新增 13 个生态人员账号（纯数据操作）

> 纯数据操作任务：**无代码改动**，走既有 `POST /api/users`（`require_admin` + `hash_password`（PBKDF2）+ `record_audit`），未手工 INSERT。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | 新增 13 个生态人员账号（viewer，随机初始密码单独交付，未入库文档） | `users` 表（纯数据，11 → 24 行；id 12–24）+ 无代码改动 | USERS-20261022 | 走真实 `POST /api/users`（PBKDF2 + 审计）；未改代码、未 build、未 commit |

实测（进程内 TestClient + 线上 8000 真实 HTTP）：
- 13 条均 HTTP 200 / `role=viewer` / `enabled=1` / `name` 与名单逐字一致；响应体不含 `passwordHash`；
- `passwordHash` 13/13 匹配 `^pbkdf2\$[0-9a-f]{32}\$[0-9a-f]{64}$` 且两两不同（salt 随机）；
- 13/13 真登录 200 + `GET /api/bootstrap` 200；抽查 `zyajie`：`POST /api/assets` 403、`GET /api/users/options` 403（ADR-030 §5）；
- `audit_logs`：`actionType='user_mgmt'`、`action='新增用户'`、`detail='role=viewer'` +13 条（操作者快照 `username='admin'`）；
- 存量 11 个账号 `passwordHash`/`tokenVersion` 逐字未变，`projects/contracts/cart_items` 计数不变（4/8/4）。

## 2026-10-22 ｜ ADR-041 补遗1：`delete_project` 删除后置空本项目日志 `projectId`

> **依据 ADR-041「补遗 1」（Accepted，2026-10-22）**：SQLite `INTEGER PRIMARY KEY` 无 `AUTOINCREMENT` → 删除项目后 id 被复用，
> 旧日志的 `projectId` 仍指向那个数字，新项目「流转过程」会混入已删除项目的日志（线上已发生）。
> 本次只在 `services.delete_project` 内做一处改动，**不改** `logs` 表结构 / 不加外键 / 不改 `add_log` / 不改 `Visibility.log_visible` / 不改前端。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | `delete_project` 删除前将本项目日志 `projectId` 置 NULL（保留日志文本），消除 SQLite id 复用导致的『旧项目日志挂到新项目流转过程』：新增 `db.execute(update(models.OpLog).where(models.OpLog.projectId == project_id).values(projectId=None))`，并补 `update` 到 `from sqlalchemy import func, select, update`。**执行时机在「删除」日志 INSERT + `db.flush()` 之后、`db.commit()` 之前**——按任务书的「`db.delete(p)` 之前」实测会**残留 1 条**（那条「删除」日志在 UPDATE 之后 INSERT，仍带旧 id，新项目复用同 id 时时间线里出现「删除项目 SP-…」），故按任务备注给出的修正路径下移 | `backend/src/services.py`（`delete_project`，L2722-2742；import L14） | ADR-041 补遗1 / FLOW-20261022-B2 | 存量已串台行**未清理**（前端 t0 守卫已覆盖展示）；审计日志不删；单事务性质不变（UPDATE 与删除同事务，任一步失败整体回滚）；未 commit。⚠️ 附带观察：8000 为 `--reload` 开发实例，改文件后 uvicorn 于 17:18:50 自动热重载 1 次（非人工重启），生产库数据零改动 |

实测（副本库 `/tmp/adr041b2.db`，独立 8123 实例 + curl；生产库全程只读）：
- 场景：建项目 A（id=**4**，日志 716 新增项目 / 717 接手订单 / 718 驳回订单，`projectId` 均=4）→ `DELETE /api/projects/4` 200 → 再建项目 B **id 仍为 4**（SQLite 复用 id 已复现）；
- 删除后 `logs WHERE projectId=4` = **0 条**；A 的 3 条日志 `projectId` 全部 NULL、`detail`/`targetName` 原样（日志总数 653 → 654，仅 +1 = 新增那条「删除」日志，无文本丢失）；
- 那条「删除」日志（id=719）也被置 NULL —— 与「`projectId` 仍有值」的预期不同，理由见上：保留旧 id 会让它在 B 的流转过程里重新串台（第一版位置实测确实如此）；
- B 的时间线 1 条 = 自己的「新增项目」，A 独有的 action（接手订单/驳回订单/删除）出现 **0** 次、`targetName` 非 B 的日志 **0** 条；
- 回归：`projects/contracts/project_items` 无残留（0/0/0）；删除仍锁定的项目 C 后 `assets#1.lockedQty` 2 → **0**（`shippedQty/soldCount/soldAmount` 不变）；`audit_logs` 删除前 1061 → 1062（仅路由层「删除销售项目」+1，旧行全部保留，服务层不碰审计表）；
- SQL 顺序（engine echo 抓取）：`INSERT INTO logs(…, projectId=4, '删除')` → `DELETE FROM project_items/contracts/projects` → `UPDATE logs SET projectId=NULL WHERE projectId=4` → `COMMIT`（`session` 为 `autoflush=False`，UPDATE 前无隐式 autoflush；`synchronize_session` 默认 evaluate 同步内存实例，commit 未重复发 UPDATE）；
- 副本库 / 临时脚本 / 8123 实例已清理；生产库 `logs` 650 条、`projectId` 非空 14 条（与改动前一致）。

## 2026-10-22 ｜ ADR-041：`LogOut` 增补 `projectId`（纯加性出参字段）

> **依据 ADR-041 Decision 2（Accepted，2026-10-22）**：前端抽屉「流转过程」需按项目 id 精确过滤日志。
> `logs.projectId` 列早已存在、`add_log` 全项目级动作早已写入、`Visibility.log_visible` 早已按它过滤——**唯一缺口是出参没吐**。
> 本次只补出参字段，**不动** `add_log` / `log_visible` / 任何写日志调用点 / `AuditLogOut` / 前端。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | `LogOut` 增补 `projectId: int \| None = None`（加性，响应结构不变，仅多一个可空键）：位置在 `contractId` 之后，注释风格对齐 `assetId`。`GET /api/bootstrap` 的 `logs[]` 与 `GET /api/assets/{id}/logs` 的 `items[]`（同一 `LogOut`）均随之多出该键；`target='asset'/'setting'/'contract'` 及 ADR-030 上线前存量 project 日志为**显式 `null`**（键始终存在） | `backend/src/schemas.py`（`LogOut`，L516-530） | ADR-041 / FLOW-20261022-B | **非 Breaking**：纯加性字段；visibility 过滤逻辑未动，viewer 可见性实测不回归；未重启 8000、未 commit |

实测（副本库 `/tmp/adr041-verify.db` + 进程内 TestClient；线上 8000 只读 curl 复核，均 200）：
- `logs` 650 条（`target='project'` 321 条）**全部含 `projectId` 键**；全量逐条与 `logs` 表比对**不一致 0 条**；
- `id=711`（撤销订单）→ `projectId=1`；`id=714`（驳回订单）→ `projectId=2`（与库值相等，非空）；
- `target='asset'`（308 条）/ `'setting'`（17 条）→ `projectId` 键存在且为显式 `null`；
- viewer（`lshangkun`）可见 project 日志 **33 条**（admin 322 条，差 289 条被过滤），`projectId` 集合 `[1,2,3]` = 其名下 3 个项目；自己项目撤销日志 `id=711` **可见**；副本库另造 `creator='yaoyuan'` 项目（id=4）+ 撤销日志 → `lshangkun` **不可见**、`yaoyuan` **可见**；
- 体积：`bootstrap` 255,878 → **266,886** 字节（**+11,008 字节 / +4.30%**，每行固定 +17 字节 `"projectId":null,`），可忽略；
- 副本库与临时脚本已删除，无残留进程。

## 2026-10-22 ｜ ADR-040：`DELETE /projects/{id}` 权限收紧至 admin + 一次性清理 2 条测试遗留项目

> **依据 ADR-040（Accepted，2026-10-22，业务方在 A 全删 / B 收敛 / C 软删除 三案中选定 B）**。
> ① ⚠️ **Breaking**：`DELETE /api/projects/{id}` 权限 `require_editor → require_admin`——**editor（商务）直调由 200 变 403**，
> 服务端与前端「删除项目仅 admin 可见」同口径收口（前端隐藏 ≠ 禁止删除）；
> ② 一次性运维清理 2 条测试遗留项目（`SP-2026102110215709` 云从项目、`SP-2026102120020331` QA034-UI验收单），
> 走「备份 → 前置断言 → 单事务删除 → 后置断言」流程，**脚本不入库**；
> ③ **ADR-028 §3 护栏（`terminated && cartRefilled` → 403）与 `services.delete_project` 的回滚逻辑逐字零改动**。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | ⚠️ **Breaking（权限面收窄）**：`DELETE /api/projects/{project_id}` 依赖 `Depends(security.require_editor)` → **`Depends(security.require_admin)`**。admin → 200；**editor（商务）→ 403 `{"detail":"无权限执行此操作"}`**（此前 200 可删）；viewer 403 不变。docstring/注释补 ADR-040 §2 说明（前端「更多▾ → 删除项目」仅 admin 可见，服务端必须同口径收口，防止 editor 持 token 直调）。路由层仅换依赖，**未新增任何业务判断** | `backend/src/routers/api.py:513-518`（`delete_project`） | ADR-040 §2 / ADR-028 §3 | 全局自查：`services.delete_project` 全仓**唯一调用点** = 本路由（grep `delete_project` 仅命中 `services.py` 定义 + `api.py:523` 调用 + 注释），无脚本/定时任务/其它端点调用 |
| 2026-10-22 | 删除 | **一次性清理 2 条测试遗留项目**（运维动作，非产品行为，脚本施后即删、未入仓库）：删除 `projects` **2 行**、`contracts` **4 行**、`project_items` **4 行**。<br>目标：`id=1 / SP-2026102110215709 / 云从项目`、`id=3 / SP-2026102120020331 / QA034-UI验收单`（均 `terminated` + `cartRefilled=1`）。<br>合同 4 条：`HT-2026102110215779`（客户「的」）、`HT-2026102110215742`（「33」）、`HT-2026102110215797`（「大」）、`HT-2026102120020335`（QA034-UI客户）。明细 4 条（id 1/2/3/7，资产 26/25/24/1）全 `released`。<br>**未动**：`audit_logs`（审计不可删）、`cart_items`、`outbounds`（唯一 1 条属 `projectId=8` / `status=reverted`）、`logs`/`flows`/`assets` 行内容 | 生产库 `backend/core_holdings.db` | ADR-040 附录 / §5 | 备份：`backend/core_holdings.db.bak-20261022-before-cleanup`（**516096 字节 / 504K**，`PRAGMA integrity_check=ok`，删除前 `projects/contracts/project_items/audit_logs/cart_items = 2/4/4/1035/4`）；见下方前后对照表 |
| 2026-10-22 | 修改 | **断言与结果留痕（同一批次，便于回溯）**：前端断言 → 事务内二次断言 → 删除 → 后置断言全部通过：三表归零、`project_items→projects` / `contracts→projects` / `project_items→contracts` 孤儿均为 **0**；资产 1/24/25/26 的 `lockedQty/shippedQty/soldCount/soldAmount` 删除前后**逐字相同**（全 0）；`cart_items` 4→4、`outbounds` 1→1 内容未变；`audit_logs` 备份中 1035 条 id **全部仍在**（零丢失） | `backend/core_holdings.db` | ADR-040 附录 | 执行期间有**真实用户同时在 8000 端口操作**（16:30 新建产品 `CH-SW-032`）：`audit_logs` 另 +1~3 条、`assets` +1、`logs` +3、`flows` +1，均为该用户写入，与本批删除无关（审计日志只增不减，无 id 缺失） |
| 2026-10-22 | 修改 | **权限变更真实验证（非静态检查）**：在库副本 `/tmp/adr040-verify.db` 上以 TestClient 实测三连——① `terminated && cartRefilled=0` 项目 + **editor** token → **403**（且项目未被删）；② 同一 id + **admin** token → **200 `{"ok":true}`** 且行已删；③ 另造 `terminated && cartRefilled=1` + admin → **403**「该订单已撤销（或已回填购物车）并将保留历史记录，不可删除」（护栏未破）。另在干净副本上 `GET /api/bootstrap` → `projects=[] / contracts=[]` | 临时副本库（已删） | ADR-040 §2 / ADR-028 §3 | 生产库未参与验证；临时库与临时进程已清理 |

**删除前后对照（生产库 `backend/core_holdings.db`）**

| 表 | 删除前 | 删除后（后置断言当时） | 说明 |
|---|---|---|---|
| `projects` | 2 | **0** | 目标项目即全表 |
| `contracts` | 4 | **0** | 全部属目标项目 |
| `project_items` | 4 | **0** | id 1/2/3/7 |
| `assets` | 25 | 25 | 行数不变（后为外部用户新增 +1，见上表） |
| `audit_logs` | 1035 | 1035 | **不删**，id 零丢失（后为外部用户 +N） |
| `cart_items` | 4 | 4 | 不动（与项目无外键） |
| `outbounds` | 1 | 1 | 不动（`projectId=8` / `reverted`） |
| `logs` / `flows` | 637 / 194 | 637 / 194 | 本批**未写** OpLog（纯运维直改库） |

资产四值对照（`lockedQty / shippedQty / soldCount / soldAmount`，删除前后逐字相同）：

| asset | 名称 | 删除前 | 删除后 |
|---|---|---|---|
| 1 | 智元机器人-G1 | 0 / 0 / 0 / 0.0 | 0 / 0 / 0 / 0.0 |
| 24 | 大语言知识模型服务系统 | 0 / 0 / 0 / 0.0 | 0 / 0 / 0 / 0.0 |
| 25 | 青牛企业大数据分析平台V1.0 | 0 / 0 / 0 / 0.0 | 0 / 0 / 0 / 0.0 |
| 26 | 电磁数据处理软件 | 0 / 0 / 0 / 0.0 | 0 / 0 / 0 / 0.0 |

## 2026-10-22 ｜ RS-STATUS-20261022：明细状态标识（in_stock / all_sold）+ 可售口径改为按状态计数 + DEFECT-1 修复

> **业务方指定方案（ADR-038 Decision 3 修订，2026-10-22）**：明细自带状态，与外层产品逻辑同构——
> `rs_items.status ∈ {in_stock(可售), all_sold(已售罄)}`，容器「可售数量」= **状态为可售的明细条数**。
> 上一版「明细总数 − 被非 terminated 合同占用且 `repeatSale=false` 的明细数」的 join 推导**整体替换**。
> **⚠️ 行为变更**：① 新增表列 `rs_items.status`（幂等启动迁移补列 + 索引，不做数据清除）；
> ② `availableCount` 口径改为 `COUNT(status='in_stock')`；③ 下单护栏 400 文案改为「该可售明细已售罄，请选择其他明细」；
> ④ **删除出参派生字段 `occupied`**（前端改用 `status`，避免两套语义并存）；⑤ 撤销交付的 shippedQty/soldCount/soldAmount 回退修复（DEFECT-1）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | **表列 `rs_items.status VARCHAR(32) default 'in_stock'` + `ix_rs_items_status` 索引**：`in_stock`=可售 / `all_sold`=已售罄（与 `assets.status` 同枚举）。启动期幂等结构迁移（`ALTER TABLE ... ADD COLUMN`，已存在则跳过），存量 60 行由列 DEFAULT 填充为 `in_stock`；**不做任何 DELETE/UPDATE 类数据动作**（真值归一走脚本，ADR-031） | `backend/src/models.py`（`RsItem.status`）、`backend/main.py`（`_ensure_migration`） | RS-STATUS-20261022 §1 / ADR-038 D3 | 索引 `ix_rs_items_status` 已建；`PRAGMA index_list(rs_items)` 可验 |
| 2026-10-22 | 新增 | **唯一状态维护入口 `services._sync_rs_item_status(db, item_id)`**（+ 批量版 `_sync_rs_item_statuses`）：按**真值**重算单条明细状态并落库——`repeatSale=true` → `in_stock`；否则被非 terminated 合同引用 → `all_sold`；未引用 → `in_stock`。幂等（无变化不写库）、无一处分处手写赋值；不回写 OpLog（派生字段，避免每单 N 条噪声日志）。调用点：`_create_project_core`（下单锁定后，**必须在明细行 flush 之后**，否则真值查询看不到本行）、`_apply_item_delivery`、`_apply_item_release`、`_revert_outbound_inner`、`update_rs_item`（repeatSale 切换）、`review_project`（驳回批量兜底）、`change_project_status`（批量兜底）、`delete_project`（删除后兜底） | `backend/src/services.py` | §2 | 冗余调用即自愈：任何遗漏点在后续动作/批量兜底中纠正 |
| 2026-10-22 | 修改 | ⚠️ **容器 `availableCount` 口径改为 `COUNT(status='in_stock') GROUP BY assetId`**（1 条聚合，替换原 2 条 join 推导）；`_rs_item_occupied_ids`（派生 `occupied` 的实现）已删除 | `backend/src/services.py`（`_rs_container_available_counts`、`bootstrap`） | §3.1 | 与产品口径同构：锁 1 条明细 ⇒ `lockedQty +1` 且该明细 `all_sold`（可售 −1） |
| 2026-10-22 | 修改 | ⚠️ **下单售罄护栏改为读明细状态**：`_validate_rs_item_ref` 中 `repeatSale=false 且 status='all_sold'` → **400「该可售明细已售罄，请选择其他明细」**（替换上一版基于 join 的占用检查）；同请求内重复选同一条单次售卖明细 → 400「同一条单次售卖明细不可在同一订单中重复下单，请选择其他明细」（`seen` 集合下沉进同一函数，仍是唯一实现） | `backend/src/services.py`（`_validate_rs_item_ref`、`_create_project_core`） | §3.2 | 三个下单入口（手动建单 / 购物车结算）自动同步 |
| 2026-10-22 | 修改 | ⚠️ **出参新增 `status`、删除派生 `occupied`**：`RsItemOut` / `RsItemOutWithSold` 增加 `status`（`in_stock`/`all_sold`），`occupied` 字段移除（`GET /assets/{id}/rs-items` 与 `bootstrap.rsItems` 同步） | `backend/src/schemas.py`、`backend/src/routers/api.py`、`backend/src/services.py` | §3.3 | 前端改用 `item.status === 'all_sold'` 置灰/文案（原 `occupied` 判断改为状态判断） |
| 2026-10-22 | 修复 | **DEFECT-1（P0）撤销交付不回退销量**：`_revert_outbound_inner` 先改 `a.shippedQty/soldCount/soldAmount`（session `autoflush=False`，尚未落库），随后 `apply_item_lock(add=True)` 内部 `db.refresh(a)` 把挂起修改**永久丢弃** → 撤销交付后 shippedQty 残留、soldCount/soldAmount 不回退。修法：在 `apply_item_lock(add=True)` 之前显式 `db.flush()`（同一事务，不改变原子性），并附 WHY 注释 | `backend/src/services.py`（`_revert_outbound_inner`） | RS-STATUS-20261022 §4 | 验证：撤销后 shippedQty=0 / soldCount=0 / soldAmount=0 / lockedQty 复原 |
| 2026-10-22 | 新增 | **存量/修复脚本 `backend/scripts/sync_rs_item_status.py`**：`--asset-id`（可选，缺省全表）、`--dry-run`、`--yes`、`--db`；按真值重算并落库（SQLite 在线备份 API + 单事务 + OpLog `action='明细状态归一'` + 回读校验）；**幂等**：0 变更直接退出（不备份、不写库）。真实库执行：60 条已全为 `in_stock`、0 变更 | `backend/scripts/sync_rs_item_status.py` | §1.3 | 同时作为「状态与真值漂移」的人工修复出口 |

**已知边界（非缺陷，业务方可决定是否收紧）**：把某条明细 `repeatSale` 由 `false` 切到 `true` 时，
该明细此前以「单次售卖」身份下的锁（`assets.lockedQty`）**不会自动释放**（`apply_item_lock` 对
repeatSale 明细短路，交付/终止都不再触碰它）。此时 `availableCount`（按状态，+1）与
`quantity − lockedQty − shippedQty`（不减）会差 1 条，方向是**更保守**（不会超卖），且把 `repeatSale`
切回 `false` 后两者自动重新对齐（状态按真值重算 ⇒ 缺口归零）。若要求严格恒等，需要「切到 true 时
释放该明细历史锁定并把对应 `project_items.locked` 置 0」（与 `update_asset` 对产品 repeatSale 的
幽灵锁清零同思路，属业务语义变更，需另行确认后实施）。

## 2026-10-22 ｜ RS-REPEAT-20261022-FIX：⚠️ 修复「明细默认单次售卖后容器只能卖出 1 条」

> **缺陷（P0）**：ADR-038 把 `rs_items.repeatSale` 默认改为 `false` 后，明细行下单改走真实扣量分支
> `apply_item_lock(asset_id=父容器, qty=1)`，而容器 `assets.quantity` 一直是登记占位值 **1**
> （实际 60 条明细）。于是 `UPDATE assets SET lockedQty=lockedQty+1 WHERE quantity-lockedQty-shippedQty>=1`
> 只有第 1 条能成功，第 2 条起 `rowcount=0` → 400「可用数量不足」；同一单两条明细
> `_validate_item_stock(asset, 2, repeat_override=False)` → 2 > 1 → 400；交付侧
> `shippedQty + qty > quantity` → `_invariant_violation`（500）。**结论：60 条单次售卖明细实际只能卖出 1 条。**
> 此前全部 `repeatSale=true` 时走「跳过扣量」分支，缺陷被掩盖。
> **无表结构变更、无新端点、无 Migration 上启动期**（存量数据走 `backend/scripts/`）；**非 Breaking**（仅新增 `occupied` 字段）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修复 | ⚠️ **容器 `quantity` 与可售明细条数自动同步**（新增 `_sync_container_quantity`）：产品 `type == RS_DATA_TYPE` 且 `lockedQty == 0 and shippedQty == 0` → `quantity = COUNT(rs_items)`；否则**不改数量**（避免冲掉在售统计）但校验 `quantity >= lockedQty + shippedQty`，不满足 → `_invariant_violation`（500 + 审计告警）。调用点：`create_rs_item` / `delete_rs_item`（提交前同事务；delete 先显式 `flush` 再 COUNT，因 session `autoflush=False`） | `backend/src/services.py`（`_sync_container_quantity`、`_rs_container_item_count`、`create_rs_item`、`delete_rs_item`） | RS-REPEAT-20261022-FIX §1 | 同步后 `availableCount`（明细总数 − 占用且 false）与 `quantity − lockedQty − shippedQty` 两个口径**天然一致** |
| 2026-10-22 | 修复 | **明细级占用护栏**：`_validate_rs_item_ref`（三个下单入口共用）在 `rs.repeatSale == False` 时，若已存在 `project_items.itemId == rs.id` 且所属 `contracts.status != 'terminated'` → 400「该可售明细已被占用（已售出或锁定），请选择其他明细」；`repeatSale == True` 不校验。检查与写入同一事务（checkout 单事务 + `apply_item_lock` 条件更新，SQLite 单写者），不新增读-改-写竞态 | `backend/src/services.py`（`_validate_rs_item_ref`） | §2 | 防「同一条明细卖两次」（lockedQty +2 而 availableCount 只扣 1 条） |
| 2026-10-22 | 修复 | **同一请求内重复选用单次售卖明细**同样 400（`_create_project_core`）：跨销售记录选同一条 `repeatSale=false` 明细时，占用检查查的是**已落库**的 `project_items`，本请求行尚未 flush → 会绕过，故补 `single_sale_seen` 集合，命中 → 400「同一条单次售卖明细不可在同一订单中重复下单，请选择其他明细」 | `backend/src/services.py`（`_create_project_core`） | §2 补充 | 与既有「同一销售记录内 (assetId,itemId) 不可重复」互补（后者只在合同内判重） |
| 2026-10-22 | 新增 | **`RsItemOutWithSold.occupied: bool = False`**（派生：被非 terminated 合同引用，**与 `repeatSale` 无关**，供前端置灰；扣减口径仍是 `_rs_container_available_counts`）。实现 `_rs_item_occupied_ids`（一条 `SELECT DISTINCT project_items.itemId`，全表或按页 id 批量），`bootstrap.rsItems` 与 `GET /assets/{id}/rs-items` 共用，**无 N+1** | `backend/src/schemas.py`、`backend/src/services.py`（`_rs_item_occupied_ids`、`bootstrap`）、`backend/src/routers/api.py`（`list_rs_items`） | §4 | 加性字段，非 Breaking；前端暂不消费 |
| 2026-10-22 | 新增 | **存量修正脚本 `backend/scripts/sync_container_quantity.py`**：`--asset-id`（缺省=全部遥感容器）/`--dry-run`/`--yes`（互斥，缺省只预览）；在线备份 `sqlite3.Connection.backup()` → `/tmp/container-quantity-backup-<ts>.db`；`BEGIN IMMEDIATE` 单事务 + 事务内二次复核（type/quantity/明细数/锁定交付）+ 逐容器 OpLog（`action='同步容器数量'`）+ 回读校验；幂等（无差异不写库、不写 OpLog） | `backend/scripts/sync_container_quantity.py`（新增） | §1 / ADR-031 | 在售容器（locked/shipped 非 0）只校验不改数量 |
| 2026-10-22 | 修改 | `import_rs_items.py` / `reset_rs_items.py` 写入/删除后同事务同步容器数量（脚本独立 `sync_container_quantity()`，与 `services._sync_container_quantity` 同口径；脚本不 import 业务包），OpLog detail 追加「容器数量 x → y」；reset 清空后 `quantity` 归 0 | `backend/scripts/import_rs_items.py`、`backend/scripts/reset_rs_items.py` | §1 | reset 文档口径更正：产品本体不再「完全不变」（quantity 随明细条数） |

### 存量执行（真实库，不重启服务）

- 命令：`python3 backend/scripts/sync_container_quantity.py --asset-id 29 --yes`（先 `--dry-run` 复核计划）
- **备份：`/tmp/container-quantity-backup-20261022-154000.db`（保留，integrity_check=ok，18 表）**
- 执行：`assets#29 遥感数据-2026` **`quantity 1 → 60`**（明细 60 条，`lockedQty=0`/`shippedQty=0`）；OpLog **#700**（`target='asset'`、`action='同步容器数量'`、`detail='容器数量按可售明细条数同步：1 → 60（明细 60 条）'`）。
- 回读：`quantity=60` = 明细 60 条；其它表行数不变（仅 `logs` +1）；`bootstrap.assets#29.availableCount` = **60**。
- 幂等：再次执行 → 「全部容器数量已与明细条数一致（重跑 0 变更）」，未写库。

### 验证（副本库逐条断言 + 真实服务 curl；`compileall` 通过）

**① 复现（修复前副本，`quantity=1`）**：同一单两条明细 → **400 可用数量不足：… 可售 1，本单需 2**；订单A 卖 item#1 → 200（`lockedQty=1`、`availableCount=59`）；订单B 卖 item#2 → **400 可用数量不足：… 可售 0，本单需 1**（核心缺陷）。

**② 修复后（副本 + TestClient，11/11 断言通过）**：`quantity=60`、`availableCount=60`；A 卖 item#1 → 200（`availableCount=59`/`lockedQty=1`）；**B 卖 item#2 → 200（`availableCount=58`/`lockedQty=2`）**；C 再卖 item#1 → **400「该可售明细已被占用（已售出或锁定），请选择其他明细」**；`/assets/29/rs-items` 与 `bootstrap.rsItems` 的 `occupied`（1/2=true、3=false）；删除被占用 item#2 → 400；同一请求内两条记录选同一条 false 明细 → 400。

**③ `repeatSale=true` 放行（副本，8/8）**：A+B 后 58；C 400；item#1 置 `repeatSale=true` → `availableCount=59`（该条不再扣减）；C 重试 → **200** 且 `availableCount` 仍 59、`lockedQty` 仍 2（true 不锁不扣）。

**④ 交付/撤销/终止（副本，17/17；含 1 条遗留缺陷记录）**：A 交付 → `shippedQty=1`、`lockedQty=1`（B 仍锁定）、`soldCount=1`、`soldAmount=27400`、`availableCount=58`；撤销交付 → 锁定恢复 2、`availableCount` 仍 58；终止 A → `lockedQty=1`（B）、item#1 `occupied=false`、`availableCount=59`、`quantity` 仍 60。
> ⚠️ **遗留缺陷 DEFECT-1（既有，非本次引入，未改）**：撤销交付后 `shippedQty` 应回 0，实际仍为 1（`soldCount`/`soldAmount` 同样未回退）。根因：`_revert_outbound_inner` 先改 ORM 属性（`a.shippedQty -= 1` 等）**未 flush**，随后 `apply_item_lock` 内部 `db.refresh(a)` 把未 flush 的挂起修改丢弃（session `autoflush=False`，已用最小复现验证）。修复前该路径还会直接 400「可用数量不足」（重新加锁无容量）；`quantity` 修正后表现为「静默残留」。建议最小修法：`_revert_outbound_inner` 重新加锁前 `db.flush()`（按指示未改动回滚路径，待确认）。

**⑤ 删除明细（副本，7/7）**：无在售数据时删 item#3 → 200 且 `quantity` 同步 **59**、`availableCount=59`；删后再卖 item#1 → 200；删已被下单的 item#1 → 400「该明细存在销售关联」；脚本重跑 0 变更。

**⑥ 真实服务 curl（只读，生产库）**：`GET /api/assets/29/rs-items?page=1&pageSize=3` → `total=60`、`items[].occupied=false`；`GET /api/bootstrap` → `assets#29.quantity=60`、`availableCount=60`、`lockedQty=0`、`rsItems[].occupied`。

**⑦ 真实 HTTP 写链路（临时 uvicorn :8011 + 副本，不动生产数据）**：`quantity=1` 缺陷态 `POST /api/projects`（两条明细）→ **400**；执行同步脚本后同一请求 → **200**（`SP-2026102215402824`，`contractAmount=59100`）；随后 `bootstrap` → `quantity=60`/`lockedQty=2`/`availableCount=58`、item#1/#2 `occupied=true`；再卖 item#1 → **400 该可售明细已被占用**。

## 2026-10-22 ｜ RS-REPEAT-20261022：明细级「可重复售卖」默认关闭 + 可售口径修订 + 存量归一（ADR-038）

> 契约见 `docs/api-contracts.md`「RS-REPEAT-20261022 批次」。**⚠️ 行为变更（默认值 `true → false`）**：出参结构、端点、错误码均不变，故非 Breaking；但「不传 `repeatSale` 新建明细」的落库结果由 `true` 变为 `false`，「容器 `availableCount`」不再扣减可重复售卖的明细。无表结构变更（默认值只在 ORM 层，SQLite 不重建表）、无 Migration 放启动期（数据类动作走 `backend/scripts/`）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | ⚠️ **`models.RsItem.repeatSale` 默认值 `True → False`**（ORM 层默认，SQLite 无 DDL 变更）| `backend/src/models.py`（`RsItem`） | RS-REPEAT-20261022 / ADR-038 §1 | 同步更新类注释：明细默认**单次售卖**（一期通常只卖一次）|
| 2026-10-22 | 修改 | ⚠️ **`schemas.RsItemInput.repeatSale` 默认值 `True → False`**（`POST /assets/{id}/rs-items`、`PUT /rs-items/{id}` 入参）| `backend/src/schemas.py`（`RsItemInput`） | ADR-038 §1 | 字段仍在 `priceMax` 之后，与模型默认一致；`PUT` 整行覆盖，缺省即按 `false` 落库 |
| 2026-10-22 | 修改 | **可售口径修订**：`availableCount = 明细总数 − \|{ 被占用 且 repeatSale = false 的明细 }\|`；占用定义不变（`project_items.itemId` 命中 + 所属 `contracts.status != 'terminated'`），`repeatSale = true` 的明细**即使被引用也不扣减** | `backend/src/services.py`（`_rs_container_available_counts`） | ADR-038 §3（覆盖 UI-OPT-20261022 §1）| 实现改为 `rs_items JOIN project_items JOIN contracts` 单条聚合 `count(DISTINCT rs_items.id) GROUP BY rs_items.assetId`（不依赖调用方传入的 `rs_items`，防漏扣）；仍与 `Visibility` 无关，viewer 同值 |
| 2026-10-22 | 修改 | **`create_rs_item` / `update_rs_item` 落库显式取 `data.repeatSale`**，OpLog detail 追加售卖模式（「单次售卖 / 可重复售卖」）；`update` 在开关实际变化时追加「可重复售卖：是 → 否」 | `backend/src/services.py` | ADR-038 §2 | 校验顺序（省份→单价→区间→判重）完全不变 |
| 2026-10-22 | 新增 | **存量归一脚本 `backend/scripts/normalize_rs_repeat_sale.py`**：`--asset-id`（默认 29）/`--dry-run`/`--yes`（不带 `--yes` 只预览）；预检 `type == 遥感数据` + 条数/金额/精度/月份分布；执行 `UPDATE rs_items SET repeatSale = 0 WHERE assetId = :id AND repeatSale != 0`（`BEGIN IMMEDIATE` 单事务 + 事务内复核）→ 写 OpLog（`action='明细重复售卖归一'`）；在线备份 `sqlite3.Connection.backup()` → `/tmp/rs-repeat-backup-<ts>.db` | `backend/scripts/normalize_rs_repeat_sale.py`（新增） | ADR-038 §4 / ADR-031 | 回读校验：`repeatSale=1` 条数 0、总数 60、`sum(price)` 10354297 不变 |

### 存量执行（真实库，不重启服务）

- 命令：`python3 backend/scripts/normalize_rs_repeat_sale.py --asset-id 29 --yes`
- **备份：`/tmp/rs-repeat-backup-20261022-152740.db`（保留，503808 B，integrity_check=ok）**
- 预检：`assets#29 遥感数据-2026`（`type=遥感数据`）60 条明细全部 `repeatSale=1`，合计 10354297 元；分布 1m 6 / 1.5m 54；月份 9 期（2024-10 12 条，其余各 6 条）；占用 0 条。
- 执行：**60 条 `repeatSale 1 → 0`**；OpLog **#695**（`target='asset'`、`targetName='遥感数据-2026'`、`action='明细重复售卖归一'`、`assetId=29`、`detail='60 条明细 repeatSale 置为 false（ADR-038）；明细总数 60 条、合计金额 10354297 元不变'`）。
- 回读：`repeatSale=1` **0** 条、明细总数 **60**、`sum(price)` **10354297.00**（未动价/量）；产品本体未改（`quantity=1`/`unit='份（可售明细）'`/`soldCount=0`/`soldAmount=0`）；`bootstrap.assets#29.availableCount` **60**（脚本前按旧口径同为 60，因占用为 0）。

### 验证（`python3 -m compileall backend/src backend/main.py` 通过；真实库副本 + TestClient；真实服务 curl 复核）

- ① 编译：`compileall backend/src backend/main.py`、`compileall backend/scripts/normalize_rs_repeat_sale.py` 通过；`read_lints` 4 个文件 0 诊断。
- ② 默认值：副本上 `POST /api/assets/29/rs-items` **不传 `repeatSale`** → 响应 `repeatSale=false`、落库 false；**传 `true`** → 响应/落库均 true。
- ③ `PUT` 来回切换：`true → false → true → false` 四次均 200 且响应/落库一致；`GET /api/assets/29/rs-items` 的 `repeatSale` 同步变化（true / false 两向均验）。
- ④ 可售口径：60 条全 false + 0 占用 → **60**；造 1 条占用（`contracts.status='pending'` 的 project_items 指向 `rs_items#1`）→ **59**；该明细 `PUT repeatSale=true` → **60**（重复售卖不扣减）；切回 `false` → **59**。
- ⑤ 真实服务：`GET /api/bootstrap` → `assets#29.availableCount=60`、`rsItems(#29)` 60 条且 `repeatSale=true` 计 0；`GET /api/assets/29/rs-items?page=1&pageSize=2` → `total=60`、`items[].repeatSale=false`。
- ⑥ 真实服务 curl 写链路：`POST`（不传 repeatSale）→ `repeatSale=false`；`PUT` true / false → 200 且响应一致；`DELETE` 清理 → `{"ok":true}`，`/rs-items` 回到 `total=60`（未留测试数据）。

## 2026-10-22 ｜ RS-IMPORT-20261022：遥感明细重新录入 60 条（数据导入）

> **纯数据写入**：无代码变更（`backend/src/` 零改动）、无表结构/列变更、无 Migration、无 Breaking。写入脚本 `backend/scripts/import_rs_items.py`（在线备份 → `BEGIN IMMEDIATE` 内二次校验 → 单事务插入 → OpLog → 回读）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | **`assets#29`「遥感数据-2026」导入 60 条可售明细（1m 6 / 1.5m 54，金额 10354297 元）**：省份 6 组（新疆/陕西/甘肃/宁夏/青海/内蒙古，city 一律留空）、期次 1m 仅 `2024-10`、1.5m 9 期（2024-10~2025-04 + 2025-12~2026-01）；明细 `repeatSale=1`、`priceMin/priceMax=NULL`。OpLog #692（`target='asset'`、`assetId=29`、`action='导入可售明细'`、`operator='admin'`）。**备份路径 `/tmp/rs-items-import-backup-20261022-152059.db`（保留）** | `backend/core_holdings.db`（`rs_items` +60 行、`logs` +1 行） | RS-IMPORT-20261022 | 单价 = 面积(km²) × 费率（1m 25 元/km²、1.5m 18 元/km²，整数四舍五入）；城市留空；**产品本体未改**（quantity=1 / unit='份（可售明细）' / repeatSale=0 / soldCount=0 / soldAmount=0 / priceMin,priceMax 均不变）；`bootstrap.assets#29.availableCount` 97 → **60**（UI-OPT-20261022 派生口径，admin 与 viewer 同值） |

### 验证（不重启服务；回读全部通过）

- ① `rs_items where assetId=29` = **60**，按精度 1m **6** / 1.5m **54**。
- ② 按月份：`2024-10` **12**（1m 6 + 1.5m 6），其余 8 个月各 **6**（仅 1.5m）。
- ③ `sum(price)` = **10354297**（1m 110875 / 1.5m 10243422）。
- ④ 抽样：新疆 1m `2024-10` = 27400；新疆 1.5m `2026-01` = 342270；青海 1.5m `2024-10` = 141426。
- ⑤ 唯一键 `(province,city,resolution,saleMonth)` 重复组 **0**、唯一组合 **60**（`uq_rs_items_dim` 无冲突）。
- ⑥ 产品本体不变（同上）；其它表行数：assets 25 / projects 2 / contracts 4 / project_items 4 / cart_items 5 / file_meta 50 / logs 626→**627**（+1）。
- ⑦ 接口：`GET /api/bootstrap` → `assets#29.availableCount` = **60**（admin）；`GET /api/assets/29/rs-items?page=1&pageSize=10` → `total: 60`。
- ⑧ viewer 复核：`viewer`（可见 1 个项目）与 `zhaoyin2`（可见 0 个项目）→ `availableCount` 均 **60**、`rs-items total` 均 **60**，验证聚合与可见性无关。`lshangkun` 密码未知（历史已记录），改用同角色账号对照。

## 2026-10-22 ｜ UI-OPT-20261022：容器可售数量口径（`bootstrap.assets[].availableCount`）

> 契约见 `docs/api-contracts.md`「UI-OPT-20261022 批次」§1。**纯加性字段**（`int | null`，追加在 `AssetOut` 末尾）；无表结构变更、无列变更、无数据迁移、无新依赖、无 Breaking。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | **`schemas.AssetOut` 新增加性可选字段 `availableCount: int \| None = None`**（追加在 `pricingMode` 之后）——容器「可售数量」= 可售期数 | `backend/src/schemas.py`（`AssetOut`） | UI-OPT-20261022 §1 | 旧快照/旧客户端缺该字段不受影响；`POST/PUT /assets` 同 schema 会带 `null`（写入后前端统一以 bootstrap 刷新） |
| 2026-10-22 | 新增 | **`bootstrap.assets[]` 为容器填充 `availableCount`**：`type == RS_DATA_TYPE`（既有常量「遥感数据」）→ `该容器明细总数 − 已被非 terminated 销售记录占用的明细数`；占用 = `project_items.itemId` 非空且所属 `contracts.status != 'terminated'`（pending/active/delivering/delivered 全算占用）；非容器保持 `null`（前端继续用 `quantity-lockedQty-shippedQty`，双口径不混）；无明细容器 = `0` | `backend/src/services.py`（新增 `_rs_container_available_counts`、`bootstrap`) | UI-OPT-20261022 §1 | 存量 `#29 遥感数据-2026`：97 明细 / 0 占用 → `availableCount=97`（原前端显示 `quantity=1`） |
| 2026-10-22 | 新增 | **占用去重口径**：同一明细被多条非 terminated 合同占用只计 1 条（`DISTINCT itemId`）——`availableCount` 是「可售条数」而非「已售次数」（次数仍走 `rsItems[].soldCount`）。空库/无容器 → 聚合查询直接返回 `{}`，不发第二条 | `backend/src/services.py` | UI-OPT-20261022 §1 | 与 ADR-011 容器模型一致 |
| 2026-10-22 | 修改 | **性能：固定 2 条聚合查询、与可见性无关**——① `rs_items GROUP BY assetId`（明细总数）；② `project_items JOIN contracts` 的 `DISTINCT itemId`（占用集合）；itemId→assetId 映射取自 bootstrap 已整表读出的 `rs_items`（不发查询）。**不按产品循环、不 N+1**；两条查询均为全量、不过 Visibility（viewer 的 bootstrap 只含自己下单的项目/合同，用它算会失真，同 `_rs_item_sold_counts` 思路） | `backend/src/services.py`、`backend/src/routers/api.py`（未改，仅确认无 `GET /assets` 列表端点） | UI-OPT-20261022 §1 | 容器数 k=1、明细 97 → 复杂度 O(k + 占用行数)，与产品总数（25）无关 |

### 验证（不重启服务；`python -m compileall backend/src backend/main.py` 通过；进程内 TestClient + **数据库副本** `/tmp/uiopt_verify.db`，跑完已删）

- ① 语法：`compileall` 通过；`read_lints` 对 `services.py` / `schemas.py` 0 诊断。
- ② 基线：`bootstrap.assets` 中 `#29` → `type=遥感数据`、`availableCount=97`（97 条明细 / 0 占用）；全部非容器产品 `availableCount is None`（实测 `#1 智元机器人-G1` 为 `null`）。
- ③ 占用/释放：`POST /projects` 造单（明细行 `itemId` 命中 `#29` 明细）→ 合同 `pending` → **96**；viewer（`lshangkun`）同值 **96**（其 `bootstrap.contracts` 确实不含该合同）；审核 `confirm` → `active` → 仍 **96**；`PATCH /contracts/{id}/status terminated` → 回到 **97**（viewer 同值 97）。
- ④ 交付也算占用：另一条明细走完整流程 `pending → active → delivering（录 signedDate）→ delivered` → **96**（viewer 同值 96）。
- ⑤ 去重：同一条已占用明细再挂一条 `pending` 合同 → 仍 **96**（不重复扣减）。
- ⑥ 既有规则佐证（非本批改动）：`pending` 合同直接 `PATCH /contracts/{id}/status` → 400「待审核销售记录不可直接变更状态，请通过订单审核（确认下单/驳回）操作」，故 terminate 断言走 `confirm → active → terminated`。

## 2026-10-22 ｜ FORMS-20261022：产品登记规则 + 生态人员购物车口径（ADR-036 / ADR-037）

> 契约见 `docs/api-contracts.md`「FORMS-20261022 批次」。请求/响应字段形状零变化，全部为校验规则收紧/放宽；**无 schema 变更、无数据迁移**（`inboundDate` 用现有列）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | **`POST /api/assets` 登记时间自动生成（ADR-036 §1）**：`inboundDate` 不再是必填入参（`schemas.AssetInput` 改 `str = ""`）——不传/空 → 后端自动取当天 `YYYY-MM-DD`（`today()`，登记流水日期同口径）；传值仍走 `_validate_date_str`（非法 400 原文案）。`PUT /assets/{id}` 不动：`exclude_unset` 不传保持原值、传值可改（只读展示是前端约束） | `backend/src/schemas.py`（`AssetInput.inboundDate`）、`backend/src/services.py`（`create_asset`） | FORMS-20261022 / ADR-036 §1 | 无迁移：存量 `inboundDate` 原值保留 |
| 2026-10-22 | 新增 | **遥感数据容器禁重复售卖（ADR-036 §4）**：`create_asset` / `update_asset` 产品类型 `type == RS_DATA_TYPE`（新增模块常量 `"遥感数据"`，避免字符串两处硬编码）且 `repeatSale == true` → **400「遥感数据容器按明细售卖，不支持重复售卖」**。`update_asset` 按「存量值 + 本次 patch」最终落库值校验（覆盖 type 改遥感数据 / repeatSale 改 true 两条路径） | `backend/src/services.py`（`RS_DATA_TYPE`、`create_asset`、`update_asset`） | FORMS-20261022 / ADR-036 §4 | 存量核对：库中**存在 1 条**容器 `repeatSale=1`（`assets#29 遥感数据-2026`）——按任务口径**不强改**，仅报告；该容器明细行售卖以 `rs_items.repeatSale` 为权威（ADR-011），父产品值不参与明细判定 |
| 2026-10-22 | 修改 | **购物车区间校验分角色（ADR-037 §3）**：`_check_discount_range` / `_check_unit_price_range` 新增 `enforce_max: bool = True` 参数——**viewer 只校验下限**（`amount < priceMin` → 400 原文案；`amount > priceMax` 放行），**editor/admin 双向不变**；遥感明细行走明细自身区间（ADR-021）同口径。参数沿 `_rs_row_amount` / `_item_pricing` / `_normalize_contracts` / `_create_project_core` / `checkout` / `set_cart_qty` / `patch_cart_item` 透传，**改价与结算两入口复用同一校验函数**（未复制规则）；角色取当前登录用户（路由层 `user.role == "viewer"`）。viewer 行历史 `discountRate` 忽略：`_validate_discount_rate` 仅校验 0 < rate ≤ 1 格式（无「非空 400」、无与 amount 一致性校验），金额恒为权威、折扣率快照只写不改——确认无需新增跳过分支 | `backend/src/services.py`（上述 9 个函数）、`backend/src/routers/api.py`（`PUT/PATCH /cart/{id}` 传 `viewer`；checkout 已有 `viewer` 参数） | FORMS-20261022 / ADR-037 §3 | 加购入口（`POST /cart`）不在本批范围，维持双向（viewer 加购超上限仍 400，改价/结算放行）；`POST /sales/order` 等已下线/内部入口默认 `enforce_max=True` 行为不变 |

### 验证（不重启服务；`python3 -m compileall -q backend/src backend/main.py` 通过；进程内 TestClient + **数据库副本** `/tmp/ch_forms_test.db`，36 项断言全部通过，跑完已删）

- ① 新建产品不传 `inboundDate` → 200 且落库为当天；传 `2026-01-05` → 原样落库；空串 → 当天；`2026/01/05` → 400。
- ② 容器 `repeatSale=true`：POST/PUT 均 400 且文案 =「遥感数据容器按明细售卖，不支持重复售卖」；容器 `false`、普通产品 `true/false` 均 200。
- ③ viewer `PUT /cart/{id}`：金额 30000 > priceMax 25500 → 200；24000 < priceMin 25000 → 400 原文案；带历史 `discountRate=0.5` → 200 且 amount=26000（折扣不参与计算）。
- ④ editor `PUT /cart/{id}`：30000 > priceMax → 400、24000 < priceMin → 400、25200 区间内 → 200（原行为保持）；editor 遥感行超明细上限 → 400。
- ⑤ viewer checkout：unit 行 26000 超上限 + 遥感行 50000 超明细上限（20000~40000）+ 历史折扣 → 200，`item.amount` 分别为 26000/50000、`item.discountRate=0.5` 快照保留；行金额低于下限（unit 24000 / 遥感 10000，直改库模拟绕过改价入口）→ 权威链 400；editor checkout 超上限 → 400。

## 2026-10-22 ｜ ENTITIES-20261022：资产主体可维护（ADR-035）

> 主体清单从前端 `types.ts::ENTITIES` 硬编码 4 家改为后端 `entities` 表单一事实来源；契约见 `docs/api-contracts.md`「ENTITIES-20261022 批次」。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 新增 | **`entities` 表**（`id` / `name` UNIQUE / `short` / `createdAt` / `updatedAt`）+ 启动迁移：建表（`create_all`，name 唯一约束随约束生成）+ **存量回填** `INSERT OR IGNORE INTO entities SELECT DISTINCT subject, subject FROM assets WHERE subject <> ''`（short 默认取 name），标记 `ADR035_entities_backfill` 入 `schema_migrations`（ADR-031 口径，查标记再执行） | `backend/src/models.py`（`Entity`）、`backend/main.py` | ENTITIES-20261022 / ADR-035 | 存量库（assets.subject 恰好 4 家）回填 4 行；空库 0 行。纯增量（只 INSERT entities，不动 assets） |
| 2026-10-22 | 新增 | **4 个端点**：`GET /api/entities`（登录即可，createdAt/id 正序）、`POST /api/entities`、`PUT /api/entities/{id}`、`DELETE /api/entities/{id}`（均 `require_editor`）。校验：name 2–64 字、short 1–32 字（trim 后，400）；name 重复（新增 / 与其他主体重名）→ 400「主体已存在」；改名（name 变化）→ OpLog「修改主体」（detail 含 旧名称 → 新名称）+ audit，**不回写** `assets.subject`；只改简称不留改名日志；删除被产品引用 → 400「该主体下存在 N 个产品，不可删除」（H7 服务层校验，SQLite 无外键）；不存在 → 404。路由层 `record_audit`（target=`entity`，label=「资产主体」） | `backend/src/routers/api.py`、`backend/src/services.py`（`list_entities/add_entity/update_entity/delete_entity`）、`backend/src/schemas.py`（`EntityInput`/`EntityOut`） | ENTITIES-20261022 / ADR-035 | 风格对齐 `add_base/delete_base`（服务层引用校验 + `add_log` 留痕 + 路由层 audit） |
| 2026-10-22 | 新增 | **`GET /api/bootstrap` 顶层新增 `entities` 字段**（`EntityOut[]` 全量，**无角色过滤**——主体非敏感商业数据），位置在 `rsItems` 之后 | `backend/src/services.py`（`bootstrap`） | ENTITIES-20261022 / ADR-035 | 前端删除 `types.ts::ENTITIES` 常量后由 `db.entities` 提供下拉/简称映射；旧快照缺失时前端回退空数组 |

### 验证（不重启服务；进程内 TestClient + **数据库副本** `/tmp/entities-verify.db`，跑完已删）

- ① 语法：`python3 -m compileall -q src main.py` 通过；`read_lints` 对 5 个改动文件 0 诊断。
- ② 副本库端到端（admin token）：`GET /entities` → 4 家（回填结果，形状 `{id,name,short,createdAt,updatedAt}`）；`POST` 新增 → 200、重复 → 400「主体已存在」、trim 后长度不合规 → 400；`PUT` 改名 → 200 且 OpLog detail = `主体名称 旧 → 新`（+1 条）、audit = `编辑资产主体`（target=entity）、与其他主体重名 → 400、不存在 → 404、只改简称 → 200 且无「修改主体」日志；`DELETE` 被引用 → 400「该主体下存在 11 个产品，不可删除」、无引用 → 200 `{"ok":true}` + OpLog「删除主体」、重复删除 → 404；`bootstrap.entities` → 4 条形状正确；未登录 `GET /entities` → 401。
- ③ 迁移幂等：同一副本重复启动 2 次 → `entities` 行数稳定（4）、`ADR035_entities_backfill` 标记不重复（1 行）；空库启动 → 回填 0 条、0 行、标记 1 行。

## 2026-10-22 ｜ FIX-20261022：业务逻辑审查缺陷全量修复（ADR-029 ~ ADR-034，含 1 项 P0 数据安全）

> 来源：`docs/business-logic-bugs-20261022.md`（只读，未修改）。**迁移继续用 `main.py` 幂等手写逻辑 + 新增 `schema_migrations` 标记表**（不引入 Alembic、不新增第三方依赖）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修复 ⚠️ | **BUG-01（P0 数据丢失）**：删除 `main.py` 启动迁移中「每次启动 `DELETE FROM asset_deliverables` 全表」的第 17 项；改为**只写一次性标记** `ADR024_cleanup_done`（表示历史清理已完成/不再执行）。新增 `schema_migrations(name PK, appliedAt, note)` 表 + `_applied/_mark_applied/_run_once` 助手：**启动期只做结构迁移**，所有数据类一次性动作（cartRefilled 回填、ADR-011 演示产品清理、pricingMode 回填、cart userId 回填、项目状态归一、assets.status 回填、file_meta 回填）全部改为「查标记 → 执行一次 → 写标记」，第二次启动零写入 | `backend/main.py`、`backend/src/models.py`（`SchemaMigration`） | FIX-20261022 / BUG-01 / ADR-031 | ⚠️ **数据安全**：该 DELETE 是此前唯一「持续发生」的数据丢失（每次 `--reload` 热重载都清空手工维护的交付物，审计日志有 13 条历史交付物操作、表已 0 行不可恢复）。**本次不尝试恢复数据**（附件仍在 `uploads/`，可人工按审计日志重建）。实测：预置 1 条交付物后启动 + 重启，行数仍为 1 |
| 2026-10-22 | 修复 | **BUG-02（文件 ACL）**：新增 `services.Visibility` 判定上下文（`visible_project_ids/visible_contract_ids/visible_flow/visible_log/visible_file` + `build_visibility`），`bootstrap.files` 与 `GET /files/{name}` **共用同一判定**：文件被任一产品引用（`assets.contractFile`/`featureDoc`/`asset_deliverables.file`）→ 所有登录用户可见；孤儿文件 → 仅 `uploadedBy == 当前用户` 或 admin 可见；不可见 **404**（不返回 403，避免探测文件名）；下载响应加 `X-Content-Type-Options: nosniff` | `backend/src/services.py`、`backend/src/routers/api.py`（`get_file` / `get_file_user`） | FIX-20261022 / BUG-02 / ADR-030 §3 | 实测（真实库只读 curl）：admin `bootstrap.files` 49 条 → viewer 24 条；孤儿文件 viewer `404`、admin `200` + `nosniff`；被引用文件 viewer `200` |
| 2026-10-22 | 修复 | **BUG-13（日志/流水可见性）**：删除 `_keep_log` 中的 detail 文本正则（`SP-`/`CK-`）与项目名匹配，`_SP_CODE_RE/_CK_CODE_RE` 一并移除；`logs` 新增 `projectId` 列，项目级日志统一写结构化外键（15 处 `add_log(..., project_id=...)`）；`target="contract"` 按 `contractId ∈ 可见合同` 过滤、`target="outbound"` 按 `projectId/contractId` 过滤、**无外键且非 asset/setting 的日志对 viewer 一律过滤**；`GET /assets/{id}/flows` 对 viewer 复用同一 `visible_flow()`（`total` 按过滤后集合计算） | `backend/src/services.py`、`backend/src/models.py`、`backend/main.py`（补列）、`backend/src/routers/api.py` | FIX-20261022 / BUG-13 / ADR-030 §4 | 实测：`bootstrap.logs` admin 571 → viewer 262；`/assets/1/flows` admin total 5 → viewer 3；viewer 侧看不到任何 `target=contract` 日志。存量 project 日志 `projectId=NULL` → 对 viewer 过滤（宁可保守不漏放，ADR-030 已知代价） |
| 2026-10-22 | 修复 ⚠️ | **BUG-03（状态机守卫下沉）**：交付前置条件（`from_status == "delivering"`、`signedDate` 非空、无 `pending_asset` 明细）下沉到 `_change_contract_status_core` 的 `_delivery_blocker()`，合同级与项目级批量**共用一道守卫**（项目级批量此前直接调 core 绕过 ADR-019）；项目级 `PATCH /projects/{id}/status` 改为**全量或全不**：先收集全部不合规合同，一次性 400 列出「编号 + 原因」。⚠️ 合同级 400 文案改为含合同编号：`合同 {code} 尚未录入签订时间，不可交付` | `backend/src/services.py`（`_delivery_blocker` / `_change_contract_status_core` / `change_project_status`） | FIX-20261022 / BUG-03 / ADR-032 §1-§2 | 实测：`{"detail":"以下销售记录不满足交付条件，请先补齐后重试：HT-2026102210265930 尚未录入签订时间，不可交付"}`；录签订时间后同接口 200 |
| 2026-10-22 | 修复 | **BUG-04（终止按明细回滚）**：`terminated` 分支不再按合同 `from_status` 二选一，改为按**明细实际状态**：`shipped` → 撤销该明细对应交付（回退 `shippedQty`/`soldCount`/`soldAmount`，Outbound 置 `reverted`）；`locked/confirmed` → 释放锁定；产品已删/明细缺失 → **400**「该产品/明细已不存在，无法回滚交付，请先联系管理员」（不再静默成功零回滚）；新增 `_outbound_of_item`（按 `projectItemId` 精确匹配，存量回退 `contractId+assetId`）与 `_revert_item_quantities`（缺交付单时按明细回退并留告警日志） | `backend/src/services.py` | FIX-20261022 / BUG-04 / ADR-032 §3 | 实测：交付 → 终止后 `project_items.status=released`、`outbounds.status=reverted`、asset `shippedQty/soldCount/soldAmount` 精确回到交付前 |
| 2026-10-22 | 修复 | **BUG-05（明细 repeatSale）**：`_validate_item_stock(a, qty, repeat_override=None)` 新增参数；`_create_project_core` 的按 assetId 聚合校验对「占用数量」的行传 `repeat_override=False`——**父产品 `repeatSale=true` 不再短路明细行**（明细 `repeatSale=false` 时仍受可售约束，修复 `lockedQty > quantity`） | `backend/src/services.py` | FIX-20261022 / BUG-05 / ADR-011 | 单测：父产品 repeatSale=true + `repeat_override=False` → 400；`repeat_override=True` → 放行 |
| 2026-10-22 | 修复 ⚠️ | **BUG-08 / BUG-18（单一权威校验链）**：`_create_project_core` 统一按序校验「明细存在性（**非空 assetId 必须存在**，BUG-16）→ 明细归属/qty → 折扣率 → 服务期限 → 参考区间/金额 → 按 assetId 聚合数量」；`_item_pricing` 对 unit 行补参考区间校验（400「销售单价超出该产品参考区间（…）」，不再无条件采信前端 price）；`contractAmount` 显式传入（> 0）且 ≠ Σ 明细 → 400「合同金额与明细合计不一致」（`0`/未传视为未填写，按 Σ 派生，兼容前端 `contractAmount: 0` 占位）；遥感行金额收口为 `_rs_row_amount`（显式 >0 金额过明细区间，否则挂牌价），保证 Σ 与落库同源；⚠️ `POST /sales/order`、`POST /projects/{id}/resubmit` **一律 410**「该接口已下线，请使用购物车结算」 | `backend/src/services.py`、`backend/src/routers/api.py` | FIX-20261022 / BUG-08 / BUG-16 / BUG-18 / ADR-029 §1-§3 | 实测：410 × 2；`所选产品不存在或已删除`；`合同金额与明细合计不一致`；`销售单价超出该产品参考区间（3,006,700.00~3,066,834.00 元/套）` |
| 2026-10-22 | 新增 | **BUG-10（并发与幂等）**：① checkout 新增可选 `requestId`，新表 `idempotency`(`userId`,`scope`,`requestId` 唯一) 记录 `projectId`，24h 内重复请求返回首次项目 + `idempotent:true`（不重复建单/锁量/清购物车），并发重复由唯一约束兜底（失败方回滚后返回首次项目或 400「该请求正在处理中」）；② 合同状态变更改**条件更新** `UPDATE contracts SET status=:new WHERE id=? AND status=:old`，`rowcount==0` → 400「状态已变更，请刷新后重试」（`_claim_contract_status`）；③ 数量改**原子条件更新** `UPDATE assets SET lockedQty=lockedQty+:q WHERE id=:id AND quantity-lockedQty-shippedQty>=:q`，失败即 400；④ **取消** `max(0,…)`/`min(quantity,…)` 静默夹断，改 `_invariant_violation`（写 OpLog「数据不变量告警」+ 500） | `backend/src/services.py`、`backend/src/schemas.py`（`CheckoutInput.requestId`、`CartQtyUpdate`）、`backend/src/models.py`（`IdempotencyRecord`）、`backend/src/routers/api.py` | FIX-20261022 / BUG-10 / ADR-033 | 实测：同 `requestId` 二次结算 → 200 `idempotent:true` 且 `project.id` 相同、购物车未被清、项目未重复创建；`_avail()` 的 `max(0,…)` 仅用于展示文案，不参与写路径 |
| 2026-10-22 | 修复 ⚠️ | **BUG-11（JWT 密钥与凭据吊销）**：`JWT_SECRET` 缺失或等于内置开发值时——`APP_ENV != "dev"` → **启动 fail-fast**（`RuntimeError`）；dev → 生成进程内随机密钥 + 醒目告警（重启即失效需重新登录）。`users.tokenVersion`（迁移补列）写入 JWT `ver` 并在 `get_current_user`（含 `?token=` 文件通道）每请求比对，不一致 401「登录状态已失效，请重新登录」；改密/禁用/改角色时 +1。**不做 `/auth/logout`**（ADR-034 §3） | `backend/src/security.py`、`backend/src/models.py`、`backend/main.py`、`backend/src/routers/api.py` | FIX-20261022 / BUG-11 / ADR-034 §1-§3 | 实测：改密后 `tokenVersion` 0→1→2；HTTP 状态与文案见 `api.md` |
| 2026-10-22 | 修复 ⚠️ | **BUG-12（登录加固）**：失败文案统一「用户名或密码错误」（禁用账号同文案，不再暴露账号存在性）；用户不存在也执行一次 PBKDF2（`verify_password_or_dummy`，恒定时间）；失败计数改 **`(ip, username)` 10/15min + 纯 IP 30/15min** 双维度，超限 **429**「登录尝试过于频繁，请稍后再试」；**不再因单账号计数全局封号**；`_login_fails` 改 `OrderedDict` 有界（≤10000 键 LRU） | `backend/src/security.py`、`backend/src/routers/api.py`（`login` 取 `request.client.host`） | FIX-20261022 / BUG-12 / ADR-034 §4 | 实测：10 次连续失败后第 11 次 429；纯 IP 维度 30 次喷洒后同 IP 拦截、其他 IP 不受影响 |
| 2026-10-22 | 修复 | **BUG-14（删除/撤销守卫）**：`delete_asset` 新增 `delivered` 合同引用校验 → 400「该产品存在已交付销售记录，不可删除」；`_revert_outbound_inner` 在产品已删 / 合同交付明细缺失时 → 400（不再「静默成功、零回滚」，避免合同永久卡 delivered） | `backend/src/services.py` | FIX-20261022 / BUG-14 / ADR-032 §4 | 实测：交付后删产品 → 400 原文案；构造「交付记录指向已删产品」→ 撤销交付 400 |
| 2026-10-22 | 修复 ⚠️ | **BUG-15（撤销回填标记）**：`withdraw_project` / `refill_project_cart` **仅当 `skipped == 0`** 才置 `cartRefilled=True`；有跳过行时返回 `skippedReasons` 并允许再次「重新提交」重试。⚠️ ADR-028 的撤销单删除护栏依赖该标记——**存在跳过行的撤销单仍可被删除**（属预期放开，此前「全部回填失败也置位」会导致明细丢失且原单不可删不可重提） | `backend/src/services.py` | FIX-20261022 / BUG-15 / ADR-026/ADR-027/ADR-028 | 实测：明细所属产品被物理删除 → withdraw 返回 `skipped=1`、`cartRefilled=0` |
| 2026-10-22 | 修复 | **BUG-17（项目派生）**：`_derive_project_status` 补 `statuses ⊆ {delivered, terminated}` 且含 `delivered` → `delivered`（此前误派「进行中」，且项目级接口对该单永久 400）；`{pending, terminated}` → `terminated` 保持 | `backend/src/services.py` | FIX-20261022 / BUG-17 / ADR-032 §5 | 单测：`{delivered,terminated}→delivered`、`{pending,terminated}→terminated` |
| 2026-10-22 | 新增 | **BUG-19（唯一索引）**：新增 `uq_project_items_key` = `UNIQUE(contractId, assetId, COALESCE(itemId,0))`（建前查重，有重复则跳过 + 告警）。`contracts` 的 `UNIQUE(projectId, customer)` **未创建**——与 ADR-016「一资产一客户一记录」直接冲突（同项目同客户必然多条，现库 `projectId=2` 即有 3 条 `云从`），建索引会阻断购物车「多产品同客户」结算；替代方案：迁移前查重打印告警 + 服务层禁止「同项目同客户+同明细集合」重复（400「客户「X」下相同的销售明细不可重复建记录」）+ 禁止同一记录内重复产品行（400） | `backend/main.py`、`backend/src/services.py` | FIX-20261022 / BUG-19 / ADR-016 | ⚠️ **未按原文实施并说明原因**（不可安全实施）；详见 `database.md` |
| 2026-10-22 | 修复 | **BUG-20（裸 dict → Pydantic）**：`PUT /cart/{id}`（`CartQtyUpdate`）、`POST /outbounds/{id}/revert`（`OutboundRevertInput`）、`PUT /assets/{id}/deliverables/{did}`（`AssetDeliverableUpdate`）三处改 Pydantic，沿用 `model_fields_set` 语义（未传=保持原值、显式 null=清空），非法入参 422（此前 500 或写脏值） | `backend/src/schemas.py`、`backend/src/routers/api.py` | FIX-20261022 / BUG-20 | 实测：`PUT /cart/1 {"qty":"abc"}` → 422 |
| 2026-10-22 | 修复 | **BUG-28（日期校验）**：`_validate_date_str` 增 `allow_empty` 参数；覆盖产品 `inboundDate/expiryDate`、交付 `date`、项目 `expectedSignDate/lastFollowDate`（建单/结算/编辑三处）。只校验写入值，**不清洗存量** | `backend/src/services.py` | FIX-20261022 / BUG-28 | 实测：`expectedSignDate="2026/10/22"` → 400「预计签订日期格式须为 YYYY-MM-DD」 |
| 2026-10-22 | 修改 ⚠️ | **BUG-32（提权）**：`GET /users/options` 守卫由 `get_current_user` 提升为 `require_editor`（viewer 403「只读账号不可执行该操作」） | `backend/src/routers/api.py` | FIX-20261022 / BUG-32 / ADR-030 §5 | ⚠️ 内部人员清单不再对 viewer 暴露；前端「商务负责人」筛选对 viewer 不渲染（前端同批） |
| 2026-10-22 | 修改 ⚠️ | **BUG-33（错误语义统一）**：① `change_contract_status` viewer 交付 → **403**（原 400）；② `review_project` 非接手人 → **403**（原 400；「尚未被商务接手」仍 400，属状态错误）；③ `DELETE /cart` 返回 `{"ok": true}`（原空 body）；其余成功体形状不动 | `backend/src/services.py`、`backend/src/routers/api.py` | FIX-20261022 / BUG-33 / `api-contracts.md §1` | 实测：viewer 交付 → 403「生态人员仅可终止销售记录（交付需商务人员/管理员操作）」 |
| 2026-10-22 | 修复 | **BUG-34（seed 自洽）**：三款卫星 Token `unit` 改「个」（ADR-025；当前库 `unit like '%颗%'` 已 0 条，**只影响空库重建**）；新增 `_apply_quantity_invariants`：`soldAmount>0` 但 `soldCount=0` → `soldCount=1`；非 repeatSale 且 `soldCount>0` → `shippedQty≥1`，售罄则 `status=all_sold`；repeatSale 恒 `shippedQty=0` | `backend/src/seed_data.py` | FIX-20261022 / BUG-34 / ADR-025 | 空库重建实测：28 产品、`unit` 全为「个」、CH-SAT-002/003 `shippedQty=1 soldCount=1 all_sold`。存量库不迁移 |
| 2026-10-22 | 修复 | **BUG-42（删除留痕）**：`delete_asset` 清理购物车行时统计行数并写入 OpLog detail（`已清理 N 行购物车引用（含其他账号）`） | `backend/src/services.py` | FIX-20261022 / BUG-42 | 实测：删除产品 → `删除产品 CH-SAT-029；已清理 3 行购物车引用（含其他账号）` |
| 2026-10-22 | 修复 | **BUG-43（rep 归一）**：`update_project` 的 `rep` 走 `_normalize_rep`（与建单侧一致，避免账号/姓名混存复发） | `backend/src/services.py` | FIX-20261022 / BUG-43 | 无 Breaking：行为与建单入口对齐 |
| 2026-10-22 | 修复 | **BUG-45（手动交付拦截）**：`create_outbound` 复核并保留 `asset.type == '遥感数据'` 容器 → 400「遥感容器不可直接交付，请交付其数据明细」（连同 `qty<=0` 400、`pending/terminated` 项目 400 一并纳入 ADR-029 §4 口径断言） | `backend/src/services.py` | FIX-20261022 / BUG-45 / ADR-029 §4 | 实测 400 原文案；`qty=0` → 400「交付数量必须大于 0」 |
| 2026-10-22 | 修改 | **附带（`api-contracts.md §7`）**：`POST /upload` 从白名单移除 `.doc`；改**流式写入**（1MB 分块，累计 >20MB 立即中断并删除半成品）；file 下载加 `nosniff`（同 BUG-02） | `backend/src/routers/api.py` | FIX-20261022 / BUG-31 | 不再「先整体读入内存再判大小」 |
| 2026-10-22 | 不做（明确） | **BUG-29（金额 Float→Numeric）未改**；bootstrap 瘦身、迁 PostgreSQL 未做（需独立 ADR/迁移窗口） | — | — | 按任务约束与 ADR §「后续/独立排期」 |
| 2026-10-22 | 修改 | **FIX-20261022-FOLLOWUP（3 项收尾）**：① **dev JWT 密钥持久化**——`_resolve_jwt_secret()` 优先级改为 `JWT_SECRET`（非默认值）> 开发密钥文件 `backend/.jwt_secret` > 生成并落盘（`O_CREAT\|O_EXCL` 原子创建 / 空文件原子覆盖重生成，权限 0600，启动打印一句来源提示）；`APP_ENV != "dev"` 且无有效 `JWT_SECRET` 的 fail-fast 不变；文件已进 `backend/.gitignore`。② **BUG-46 收尾**——`bootstrap.rsItems` 改输出 `RsItemOutWithSold`（补派生 `soldCount`），聚合逻辑抽为 `services._rs_item_sold_counts(db, item_ids=None)`（**一条 GROUP BY 查询**，`GET /assets/{id}/rs-items` 同函数复用，无 N+1/无第二套口径），其余字段与顺序不变。③ `POST /upload` 白名单确认无 `.doc`、保留 `.xlsx`，错误文案明确为「支持 pdf/docx/xlsx/图片」 | `backend/src/security.py`、`backend/src/services.py`、`backend/src/routers/api.py`、`backend/.gitignore`、`docs/backend/api.md` | FIX-20261022-FOLLOWUP / BUG-46 | 无 DB 变更、无新依赖、无 Breaking（`rsItems` 仅新增字段，`RsItemPicker` 只读既有字段）。静态/进程内验证（未重启服务）：`compileall` 通过；密钥文件 3 次独立进程导入 sha 前缀一致（`30c649c503ea`）+ `stat` 权限 `600` 长度 64；副本库 `/tmp` 上 `bootstrap` 97 条 `rsItems` 均含 `soldCount`、聚合 SQL **1 条**、构造 delivered 明细后 `itemId=1 → 2` 且 delivered 合同下 `confirmed` 明细也计入、active 合同与 `itemId IS NULL` 行不计；`.doc` 上传 400 文案、`.xlsx` 200 |

### 验证（不启动/不重启服务；进程内 TestClient + **数据库副本** `/tmp/fix-verify.db`，另有对运行中服务的**只读** curl 复核）

- ① 语法：`python3 -m compileall -q main.py src` → 通过；`read_lints` 对 7 个改动文件 0 诊断。（注：`backend/migrate_amount_to_wan.py` 存在**既有**语法错误，属历史一次性脚本，非本次改动）
- ② `grep -rn "DELETE FROM asset_deliverables" backend/` → **0 命中**（ADR-011 演示数据清理改为 Core Delete 按 `asset_id` 精确限定）。
- ③ 迁移幂等：预置 1 条 `asset_deliverables` → 启动后仍为 1 行；`_ensure_migration()` + `_ensure_unique_indexes()` 二次执行后行数不变、标记不重复。
- ④ 端到端 87 项断言全通过（`/tmp/verify_fix_20261022.py`）：登录/限流/tokenVersion、410、403、422、文件 ACL + nosniff、checkout 幂等、建单校验链（存在性/金额一致/区间/日期/重复行）、批量交付守卫 → 交付 → 按明细终止回滚、派生补组合、撤销回填标记、删除留痕、遥感容器拦截、日志与流水可见性。
- ⑤ 真实库（只读 curl，未产生新业务行：projects 3 / cart 11 / idempotency 0）：`/sales/order` 410、`/projects/2/resubmit` 410、`/users/options`(viewer) 403、`PUT /cart/1 {"qty":"abc"}` 422、`bootstrap.files` 49→24、`bootstrap.logs` 571→262、`/assets/1/flows` 5→3、孤儿文件 viewer 404 / admin 200+nosniff。

## 2026-10-21 ｜ 修改：生态人员订单提交后禁止编辑 + 撤销单删除护栏（ADR-028）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修改 ⚠️ | **`PUT /api/projects/{id}` 权限收紧（Breaking）**：`services.update_project` 在 404 校验之后、其他业务校验之前新增 `user.role == "viewer"` → `403 "订单已提交，不可编辑；如需修改请「撤销」后重新下单"`（不看状态与归属，含自己下单的 pending 单；404 优先于 403）；**删除**原「viewer 可编辑自己 pending 项目」分支（`user_sees_project` 判断）与写字段循环内 `k == "rep"` 的 viewer 特判（父权限收回后为死代码）；docstring 同步改写（viewer 一律 403，商务/管理员规则不变）。路由层**不重复**加判断，注释与新口径对齐 | `backend/src/services.py`（`update_project`）、`backend/src/routers/api.py`（`PUT /projects/{project_id}` 注释） | ADR-028 §1 / TASK-BE-032 | ⚠️ **Breaking：viewer 编辑接口由 200 变 403**——改单唯一路径 = `POST /projects/{id}/withdraw`（撤销）→ 明细回填购物车 → 重新结算；无新增列、无迁移；前端已同步收敛入口（TASK-FE-032） |
| 2026-10-21 | 修改 | **`DELETE /api/projects/{id}` 新增留痕护栏**：`services.delete_project` 在 `get_project` 之后、任何写操作之前校验 `p.status == "terminated" and p.cartRefilled` → `403 "该订单已撤销（或已回填购物车）并将保留历史记录，不可删除"`（先校验后写，保持单事务语义）；docstring 补充说明「复用 `cartRefilled` 作为撤销留痕标记，不新增列」（语义由「购物车已回填」扩为「该终止单已产生回填/撤销留痕」，避免为一次权限收紧引入 schema 变更）；路由注释对齐 | `backend/src/services.py`（`delete_project`）、`backend/src/routers/api.py`（`DELETE /projects/{project_id}` 注释） | ADR-028 §3（Decision 3）/ TASK-BE-032 | 被驳回且从未回填的终态项目**仍可删除**（既有回滚逻辑不变，实测 asset 锁定/状态无残留）；管理员确需清理撤销单走数据库运维，不做接口后门 |
| 2026-10-21 | 不改动（明确） | `withdraw_project` / `refill_project_cart` / `change_project_status` 行为零改动：viewer 对**自己 active 项目仍可终止**（撤销≠终止：撤销=待审核单撤回**并回购物车**；终止=已生效单作废**不回购物车**），撤销仍仅 `pending` 可调 | `backend/src/services.py` | ADR-028 §4 | 回归实测：viewer `PATCH /projects/3/status {"status":"terminated"}` → 200 |

### 验证（dev server 127.0.0.1:8123 + **数据库副本** `/tmp/be032_test.db`，curl 实测，真实库与真实数据未被触碰）

- ① 验收 1（viewer 编辑 403）：viewer 对**自己下单的 pending 项目**（id=3）`PUT /api/projects/3` → `403 {"detail":"订单已提交，不可编辑；如需修改请「撤销」后重新下单"}`；对他人 `terminated` 项目（id=1）同文案 403。
- ② 验收 2（商务规则不变）：非负责人 editor 编辑 pending 项目 → `400 {"detail":"待审核项目仅商务负责人（或管理员）可编辑基本信息"}`（原文案）；该 editor 接手（`claim`）后 `PUT` → `200 {"ok":true}`；商务 `wuhao2` 编辑自己 `active` 项目（id=2）→ `200 {"ok":true}`。
- ③ 验收 3（删除护栏）：`DELETE /api/projects/1`（`terminated` 且 `cartRefilled=1`，历史已撤销单）→ `403 {"detail":"该订单已撤销（或已回填购物车）并将保留历史记录，不可删除"}`；viewer 终止自己 pending 单（id=3）后 `cartRefilled=0` → `DELETE` → `200 {"ok":true}`，项目/明细消失，asset4 `lockedQty` 0→0、`status` 仍 `in_stock`（回滚逻辑正常）。
- ④ 验收 4（404 优先）：viewer/admin 调 `PUT` / `DELETE /api/projects/999999` → 均 `404 {"detail":"项目不存在"}`，未被 403 抢占。
- ⑤ 语法/静态：`python3 -m compileall -q src` → 通过；`read_lints` 对 `services.py`/`api.py` 0 诊断。仓库无 pytest 用例（无 `tests/` 目录），故以 curl 端到端覆盖代替。
- ⑥ 残留注释 grep：`grep -rn "可编辑自己下单|rep 字段对 viewer|恒忽略"` → 仅剩本 ADR-028 说明「旧分支已删除」的**新增注释**，无过期口径遗留（`docs/backend/api.md` 两处历史表述已加删除线并标注 ADR-028）。

## 2026-10-21 ｜ 新增：「重新提交」收口购物车（`refill-cart` 幂等回填，ADR-027）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | 新增端点 `POST /api/projects/{id}/refill-cart`（守卫 `require_order`，**无 body**）：已终止项目「重新提交」= 把原单全部明细回填**下单人**购物车（前端跳 `/cart` 改单再结算），不再走 create 页 copy 模式。响应 `{ok, alreadyRefilled, restored, amountFallback, skipped, skippedReasons}` | `backend/src/services.py`（新增 `refill_project_cart`）、`backend/src/routers/api.py` | ADR-027 / TASK-BE-027 | 回填逻辑与 `withdraw` **共用** `_refill_cart_from_project`（口径零漂移）；不新建订单、不改项目/合同状态、不锁量 |
| 2026-10-21 | 新增 | 数据库列 `projects.cartRefilled`（BOOLEAN 默认 0）+ 启动幂等补列 + **一次性数据迁移**：历史「已撤销」的终止项目置 1（判据：名下任一合同 `remark` 含「撤销」，与 ADR-026 写入格式「撤销：{reason}」一致）；「驳回」项目保持 0 | `backend/src/models.py`、`backend/main.py`（`_ensure_migration` 第 18 项） | ADR-027 §1/§2 | 幂等：`COALESCE(cartRefilled,0)=0` 才更新；实测真实库 1 条历史撤销项目被置 1，重复启动命中 0 条 |
| 2026-10-21 | 修改 | `withdraw_project` 回填成功后置 `p.cartRefilled = True`（撤销已回填 → 之后点「重新提交」不再重复回填）；回填循环抽为共享私有函数 `_refill_cart_from_project(db, p, target_user_id)`（行为/容错/日志文案完全不变） | `backend/src/services.py` | ADR-027 §4 | withdraw 响应字段与既有语义不变（回归实测通过） |
| 2026-10-21 | 修改 | `ProjectOut` 增 `cartRefilled: bool = False`（bootstrap `projects[]` / 结算响应同步输出），供前端提示「明细已在购物车」 | `backend/src/schemas.py` | ADR-027 §5 | 纯增量字段，无 Breaking |
| 2026-10-21 | 修改 | `POST /api/projects/{id}/resubmit` **标记 deprecated（ADR-027）**：docstring 说明「前端入口已改为 refill-cart，本端点无入口保留兼容」；**行为完全不变**（不删、不改校验） | `backend/src/routers/api.py`、`backend/src/services.py` | ADR-027 §5 | 既有脚本/外部调用不受影响 |

### 验证（dev server 8000 --reload 热生效，curl 实测，测试数据已全部清理）

- ① 正常路径：临时 viewer 下单（pending）→ `POST /projects/{id}/withdraw` → `cartRefilled=true` → 再点 `refill-cart` → 200 `{"ok":true,"alreadyRefilled":true,"restored":0,...}`，购物车行数与行 id 不变（不翻倍）。
- ② 驳回路径：pending 单由 admin 接手 + `review reject`（remark「驳回：…」，`cartRefilled` 保持 0）→ 首次 `refill-cart` → 200 `{"alreadyRefilled":false,"restored":2,...}`，2 行明细（含 `customer/qty/amount/serviceStart/serviceEnd/discountRate=0.95`）正确回填；再次调用 → `alreadyRefilled:true`，购物车不变。
- ③ 权限：他人 viewer → 403「生态人员仅可重新提交自己下单的项目」；editor 调用 → 200 且回填落在**下单人**购物车（`cart_items.userId` = 下单人 `users.id`，editor 自己购物车仍为空）；admin 重复调用 → `alreadyRefilled:true`。
- ④ 边界：pending 项目 → 400「仅已终止的项目可重新提交」；active 项目 → 400 同上；`/projects/999999` → 404「销售项目不存在」；`creator`/`rep` 均查不到账号的终止项目 → 400「下单账号不存在，无法回填购物车」。
- ⑤ 幂等与数据一致：refill 前后 `assets.lockedQty` 全部不变（回填不锁量，实测 asset2/asset4 均 0→0）；`flows` 计数不变（198→198）；OpLog 仅首次 1 条「重新提交（回填购物车）」，重复调用不新增（`refill logs count: 1`）。
- ⑥ 历史迁移：把 4 个测试 terminated 项目 `cartRefilled` 全部重置为 0 后 `touch main.py` 触发 `_ensure_migration` → 合同 remark 含「撤销」的项目置 1、含「驳回」的 3 个项目保持 0；再次触发（幂等复跑）值不再变化。
- ⑦ 清理：测试用户/项目（合同/明细级联）/购物车行/流水/OpLog 已删除，重建后 `assets/projects/contracts/project_items/cart_items/users/flows/logs` 计数与测试前快照完全一致（真实历史项目 `SP-2026102110215709` 的 `cartRefilled=1` 保留）。

## 2026-10-21 ｜ 新增：生态人员「撤销」待审核订单（终止 + 明细回填购物车）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | 新增端点 `POST /api/projects/{id}/withdraw`（守卫 `require_order`，body `{"reason": string}`，1–200 字）：撤销 = **终止原单（释放真实锁定 + `cancel_release` 流水 + 合同 remark 追加「撤销：{reason}」）+ 全部明细自动回填下单人购物车**；项目置 `terminated`、有 `businessOwner` 则解绑并留痕；响应 `{ok, restored, amountFallback, skipped, skippedReasons}` | `backend/src/services.py`（新增 `withdraw_project` / `_can_withdraw` / `_withdraw_owner` / `WITHDRAW_REASON_MAX`）、`backend/src/schemas.py`（`WithdrawInput`）、`backend/src/routers/api.py` | ADR-026 / TASK-BE-026 | 复用既有终止链路 `_change_contract_status_core`（锁定释放 + 流水 + `_recompute_project`）与加购核心 `_cart_add_inner`（判重合并/区间校验）；回填失败降级 `amount=None`（原价成交）→ 仍失败跳过，绝不中断撤销；不改终止/驳回/重新提交/购物车/结算任何既有行为；无 schema 变更 |
| 2026-10-21 | 新增 | 边界与容错：404「销售项目不存在」/403「只能撤销自己提交的订单」/400「仅待审核订单可撤销」「请填写撤销原因」「撤销原因不能超过 200 字」「下单账号不存在，无法回填购物车」；回填目标恒为**下单人**（`p.creator`→`users.id`，admin 代撤销同样回填下单人） | 同上 | ADR-026 §2/§4 | 校验全部前置（进入写路径后不再抛 400，避免半途部分写入）；幂等：非 pending 再次调用 400，不重复回填/重复释放 |

### 验证（dev server 8000 --reload 热生效，curl 实测，测试数据已全部清理）

- 正常流：viewer A 购物车 3 行（智元G1 / 宏大低轨 / 卫星Token，客户+金额+服务期限+折扣率）结算 → `SP-2026102116543839`（3 合同/3 明细，lockedQty：asset1=1、asset6=1，asset9 repeatSale 不锁）→ `POST /projects/3/withdraw {"reason":"价格需重新确认"}` → `{"ok":true,"restored":3,"amountFallback":0,"skipped":0,"skippedReasons":[]}`；项目/3 合同 `terminated`，remark=「撤销：价格需重新确认」，lockedQty 全部回退 0，新增 `cancel_release` 流水 2 条（asset1/asset6，asset9 无幽灵流水），`project_items.status` 全 `released`，购物车 3 行字段与订单逐字段一致。
- 边界：viewer B 撤销 A 的单 → 403；reason 空白 → 400「请填写撤销原因」；201 字 → 400「撤销原因不能超过 200 字」；`/projects/999999` → 404；active 项目 → 400「仅待审核订单可撤销」；已撤销再调 → 400 且 flows/cart/资产锁定零变化（幂等）。
- admin 代撤销 viewer B 的单 → 200 `restored:1`，购物车行落在 `userId='10'`（下单人 B），admin 购物车为空。
- 合并累加：撤销前购物车已有同 `(asset2, customer)` 行 qty1 → 撤销回填后合并为 1 行 `qty=3`（1+2）不报错。
- 降级/跳过：参考区间收紧导致回填金额失配 → `{"restored":1,"amountFallback":1}`（购物车行 amount=null 原价成交）；明细 assetId 指向已删除产品 → `{"restored":0,"skipped":1,"skippedReasons":["产品 #999999 已不存在"]}`，撤销本身仍 200。
- 遥感明细行：itemId=1 回填保留 `itemId/qty=1/amount=330000`，服务期限保持 null，无流水（明细 repeatSale）。
- 回归：review 驳回（remark「驳回：…」）、`PATCH /projects/{id}/status` 取消订单、`POST /projects/{id}/resubmit`（重新提交后再撤销 → 200）行为不变。
- 日志：OpLog「撤销订单」1 条 + `audit_logs`「撤销订单」1 条（detail=`reason=…`）；测试项目/购物车行/临时用户/临时产品已清理，资产 lockedQty 与基线一致。

## 2026-10-21 ｜ 修复：`ProjectOut` 补输出 `creator`（撤销/编辑归属判定依赖）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修复 | `ProjectOut` 新增 `creator: str = ""`（bootstrap `projects[]` 同步输出）——此前投影漏该字段，前端无法做「本人单」精确判定，连带既有 viewer「编辑/终止」入口失效；纯增量字段，无 Breaking | `backend/src/schemas.py` | ADR-026 / 契约 WITHDRAW-20261021 | 实测 bootstrap 返回 `creator='lshangkun'` 等真实值；存量项目为空串，前端按可见性兜底 |

---

## 2026-10-21 ｜ 修复：购物车行更新误清空销售金额（PATCH 语义）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修复 | `PUT/PATCH /cart/{id}` 改为 PATCH 语义：`amount`/`serviceStart`/`serviceEnd`/`discountRate` **未传 = 保持原值**（`services.UNSET` 哨兵；PUT 按 body 键、PATCH 按 `model_fields_set` 判断），显式 `null` = 清空。修复「填销售金额后选服务期限/改客户 → 金额被清空」（旧逻辑 `elif is_discount_row: c.amount = None` 无条件清空；`discountRate` 每次无条件覆盖） | `backend/src/services.py`（set_cart_qty / patch_cart_item）、`backend/src/routers/api.py` | 用户反馈 / 契约 CART-PATCH-20261021 | 保留旧行为：数量**真的变化**且未传 amount、无 discountRate 时清空手工金额（旧总额对新数量失真）；前端零改动；必填/区间校验与 400 文案不变 |

### 验证（dev server 8000 --reload，admin，curl 实测）

- ① PUT `{qty:1, amount:7600000}` → amount=7600000；② PUT `{qty:1, serviceStart, serviceEnd}` → **amount 保持 7600000**；③ PATCH `{customer}` → amount 保持；④ PUT `{qty:1→2}` → amount 清空（预期旧行为）；⑤ `{amount, discountRate:0.9}` 后改服务期限 → amount 与 rate 均保持；⑥ PUT `{amount:null}` → 清空。测试购物车行已清理。

---

## 2026-10-21 ｜ 修复：参考区间与金额变更文案的科学计数法显示

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修复 | 金额文案格式化：新增 `_fmt_money()`（千分位 + 两位小数，禁止科学计数法），替换 `_check_discount_range` 三处区间文案（双区间/单边下限/单边上限）与 OpLog 三处金额变更文案（销售金额 ×2、单价 ×1）的 `:g` 格式；报错文案由「（7.58e+06~7.7316e+06 元/套）」改为「（7,580,000.00~7,731,600.00 元/套）」 | `backend/src/services.py` | 用户反馈（购物车改价显示异常）/ ADR-018·ADR-025 金额口径 | `:g` 在 7 位以上数字会输出科学计数法；金额一律两位小数千分位，无接口结构变更 |

### 验证（dev server 8000 --reload，admin，curl 实测）

- 单元：`_check_discount_range(asset(7,580,000~7,731,600 元/套), qty=1, amount=1,000,000)` → 400 `折扣单价超出该产品参考区间（7,580,000.00~7,731,600.00 元/套）`。
- 端到端：加购 CH-SW-007（assetId=27）→ `PUT /api/cart/7 {"qty":1,"amount":1000000}` → 400 同上文案；测试购物车行已删除。

---

## 2026-10-21 ｜ ADR-025 卫星 Token 单位与挂牌价修正（一次性数据脚本）

> 依据 ADR-025：salePrice 单位是**元/个（1 个 = 1 Token）**，前端展示层 `×1e6` 换算为「/百万Token」口径。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修改 | 卫星Token 3 产品（CH-SAT-001/002/003）`unit` → `个`、`salePrice` → `0.03333333`（8 位小数，字符串直写禁止 float 运算）；`category_units` 卫星Token 行单位文案同步；`seed_data.py` CATEGORY_UNITS 卫星Token 行同步（`颗（Token 额度）` → `个`） | `assets.unit/salePrice`（3 行）、`category_units.unit`（1 行）、`backend/src/seed_data.py:170` | ADR-025 / TASK-BE-026 | 一次性脚本 `backend/update_sat_token_unit_price.py`（不进 `_ensure_migration`），执行前备份 `core_holdings.db.bak.20261021-token-unit-fix`；amount 模式合同金额整数元权威不变，接口零变更 |

### 验证（dev server 8000 --reload，admin，curl 实测）

- bootstrap 实测：3 产品 `salePrice == 0.03333333`、`unit == 个`、`pricingMode == amount`、`priceMin/priceMax` 保持 NULL（不限制）；前端换算式 `0.03333333 × 1e6 = ¥33,333.33/百万Token`。
- unit 模式有价产品仍为 21 个（0 变化）；脚本二次执行报告「已符合，无写入」（幂等）。
- 首轮曾误写 `salePrice=33333.33`（元/百万Token 口径混入元/个字段），已由 TASK-BE-026 返工修正。

---

## 2026-10-21 ｜ 修改：批量写入产品参考价区间（一次性数据脚本）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修改 | 批量写入产品参考价区间：下限=挂牌价（priceMin=salePrice 原值不动）、上限=挂牌价×1.02 取整（Decimal ROUND_HALF_UP 先算后转 int）；一次性脚本 `backend/fill_asset_price_range.py`（参照既有迁移脚本模式，不进 `_ensure_migration`）：执行前备份 `core_holdings.db.bak.20261021-price-range`，事务内 21 条 UPDATE，幂等（二次执行 0 写入）；rs_items 明细级区间一律不动（前后指纹 diff 为 0） | `assets.priceMin/priceMax`（21 个产品写入，7 个跳过） | TASK-BE-025 | 跳过 amount 模式（卫星Token #6/#7/#8）与无挂牌价产品（#18/#19/#20/#29）；纯数据脚本不写 OpLog；接口/字段结构零变更 |

### 验证（dev server 8000 --reload，admin，curl 实测）

- 脚本在 /tmp 副本预演通过（含幂等二次执行）后对真实库执行：共扫描 28 个产品，写入 21 个，跳过 7 个（amount 模式 3 + salePrice=0 4）。
- 抽查被写产品（DB + bootstrap 双通道）：#1 `priceMin=3006700.0/priceMax=3066834.0`、#10 `24243.0/24728.0`（24243×1.02=24727.86→24728）、#28 `32560000.0/33211200.0`，均满足 `priceMin==salePrice`、`priceMax==int(salePrice×1.02 四舍五入)`。
- 抽查跳过产品：#6（amount 模式）、#18（salePrice=0）区间保持 NULL 未触碰。
- rs_items：执行前后行数 97、(id, priceMin, priceMax) SHA256 指纹一致（0 变化）。
- 幂等：真实库二次执行报告「写入 0 / 已符合目标值 21」，无报错。
- `GET /api/health` 200，bootstrap 正常返回 28 assets / 97 rsItems；未执行构建/部署/重启，未 git commit。

---

## 2026-10-21 ｜ ADR-024 交付物模板彻底下线 + 交付物单文件附件（⚠️ Breaking）

> 依据 ADR-024：交付物全部在产品详情页手动维护（不再有模板→实例两层概念）；每项交付物挂单个附件（复用 `/api/upload`，交互同产品清单 contractFile）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 删除 | ⚠️ 交付物模板体系彻底下线：删 `DeliverableTemplate` 模型/`deliverable_templates` 表（启动迁移 `DROP TABLE IF EXISTS` 幂等清理旧库）、`DeliverableTemplateInput/Out` schema、3 个 `/api/deliverable-templates` 端点（现 404）、services 模板 CRUD 3 函数 + `_init_asset_deliverables` 惰性初始化及全部调用点（bootstrap 补生成、add 首增触发）、`seed_data.DELIVERABLE_TEMPLATES` 与 main.py 种子写入；bootstrap 返回体**移除 `deliverableTemplates`** | `backend/src/models.py`、`backend/src/schemas.py`、`backend/src/services.py`（bootstrap）、`backend/src/routers/api.py`、`backend/src/seed_data.py`、`backend/main.py` | ADR-024 | 建产品不再自动生成交付物实例，完全手动维护；`/upload` 白名单与交付物权限（require_editor）不变 |
| 2026-10-21 | 新增 | `asset_deliverables.file` 单文件附件列（VARCHAR(255) 可空，存 upload 散列名；NULL=无附件），幂等补列（inspector + ALTER TABLE 模式）；`PUT /assets/{id}/deliverables/{item_id}` patch 白名单追加 `file`（`""`/null → 落库 NULL 清空附件），OpLog「更新交付物」`changes` 体现附件变化（与产品文件字段同格式，散列名还原原始名）；bootstrap `assetDeliverables` 行携带 `file`；`DELETE /api/upload/{filename}` 引用检查追加 `asset_deliverables.file`（被引用 400） | `backend/src/models.py`（AssetDeliverable）、`backend/src/schemas.py`（AssetDeliverableOut）、`backend/src/services.py`（update_asset_deliverable）、`backend/src/routers/api.py`（delete_file）、`backend/main.py`（迁移） | ADR-024 | 上传复用通用 `/api/upload`，不改后端白名单/大小限制；交付物前端 accept 更严（.pdf/.docx/图片，禁 .doc/.xlsx）由前端校验 |
| 2026-10-21 | 修改 | ⚠️ 存量交付物实例一次性清空：`_ensure_migration` 中 `asset_deliverables` 表存在且非空时 `DELETE FROM asset_deliverables`（幂等：空表跳过），模板体系下线后各产品交付物从零手动添加 | `backend/main.py`（`_ensure_migration`） | ADR-024 | 用户已拍板确认；无其他表引用该表，直接清；revert 需从 `core_holdings.db.bak-*` 恢复 |

### 验证（dev server 8000 --reload，admin，curl 实测）

- 语法检查：`python3 -m py_compile main.py src/{models,schemas,services,seed_data}.py src/routers/api.py` 通过；服务热重载后 `GET /api/health` 200。
- `GET /api/bootstrap`：响应**无 `deliverableTemplates`**；`assetDeliverables` 为 `{}`（存量已清空）；sqlite_master 确认 `deliverable_templates` 表已 drop、`asset_deliverables` 含 `file` 列、行数 0。
- `POST /api/assets` 建测试产品 → bootstrap `assetDeliverables` 无该产品 key（实例不自动生成，完全手动）。
- `POST /api/assets/30/deliverables` → 200，bootstrap 新行 `file: null`；`POST /api/upload`（PNG）→ 200 得散列名；`PUT .../deliverables/1` `{"file":"<散列名>"}` → 200，bootstrap `file` = 散列名（查到）。
- `DELETE /api/upload/<散列名>`（被交付物引用）→ 400 `{"detail":"该文件仍被产品「BE024测试产品」的交付物「测试交付物」引用（交付物附件），请先移除交付物附件后再删除"}`。
- OpLog「更新交付物」`changes` = `附件: → f00ed2c0c4da4b329b1a0d077e985f74.png`（挂附件）；`PUT` `{"file":""}` → 200，bootstrap `file: null`（清空）。
- 清空后 `DELETE /api/upload/<散列名>` → 200（引用解除）。
- 模板端点 `POST/PUT/DELETE /api/deliverable-templates` → 均 404。
- 测试数据已清零（测试交付物 + 测试产品已删），未执行构建/部署、未 git commit。

---

## 2026-10-21 ｜ 修改：CART-PERF-20261021 购物车行更新性能——`PATCH /cart/{id}` 返回更新后的 CartItemOut（分支 feat/pricing-discount-timelines）

> 背景：行级更新（qty/amount/discountRate/service）每次写后前端全量重拉 bootstrap（含 97 条 rsItems/122 条 logs）整表重建 → 输入卡顿。改「写接口返回更新行 → 前端本地打补丁」（契约见 api-contracts.md「CART-PERF-20261021 批次」）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 修改 | ⚠️ `PATCH /api/cart/{id}` 响应由 `{"ok": true}` 改为**更新后的完整 `CartItemOut`**（含最新 customer/qty/amount/serviceStart/serviceEnd/discountRate）：`services.patch_cart_item` 由返回 None 改为 commit 后 `db.refresh(c)` 返回行对象，路由加 `response_model=schemas.CartItemOut` 直接返回。入参/校验/400/404 文案/审计日志零变更 | `backend/src/services.py`（`patch_cart_item`）、`backend/src/routers/api.py`（`patch_cart_item`） | CART-PERF-20261021 | 前端行级写函数改用响应体本地替换对应行，`afterWrite()` 全量刷新仅保留给结构性操作（加购/批量加购/删行/清空/结算） |

### 验证（dev server 8000，admin，curl 实测）

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` → import ok。
- `POST /api/cart`（asset #28，qty=1，customer=CART-PERF测试客户）→ 200，建测试行 id=6。
- `PATCH /api/cart/6`（amount=30000000 + discountRate=0.93）→ 200，响应为完整 `CartItemOut`：`{"id":6,"userId":"1","assetId":28,"customer":"CART-PERF测试客户","qty":1,"amount":30000000.0,"itemId":null,"serviceStart":null,"serviceEnd":null,"discountRate":0.93,...}`（全字段齐全、值正确）。
- 测试数据已清零：`DELETE /api/cart/6` → 200，未触碰任何存量业务数据。
- 未修改 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-21 ｜ 新增：DISCOUNT-20261021 购物车折扣率输入（分支 feat/pricing-discount-timelines）

> 依据 ADR-023（购物车下单处加选填折扣快捷入口，销售金额仍是权威必填值，ADR-022 不变）。前后端同批上线（契约见 api-contracts.md「DISCOUNT-20261021 批次」）。**后端只存不算**：不做金额回填计算（前端回填 amount 后一起提交，金额权威原则），amount 现有校验（必填/整数元/参考区间）完全不变。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | `cart_items.discountRate` / `project_items.discountRate` 两可空列（FLOAT，0-1 小数，0.9=九折；NULL=无折扣/无快照），`main.py::_ensure_migration` 幂等补列（inspector + ALTER TABLE 模式，沿用 PRICING 批次先例）；存量数据不迁移（NULL 语义正确） | `backend/src/models.py`（CartItem/ProjectItem）、`backend/main.py` | DISCOUNT-20261021 | project_items 为**下单快照，只写不改**（与 origPrice/origAmount 同级口径，审核终审改价不触碰） |
| 2026-10-21 | 新增 | 购物车写接口接受 `discountRate`：`POST /cart`、`POST /cart/batch`、`PUT /cart/{id}`、`PATCH /cart/{id}`。校验：0 < rate ≤ 1 否则 400「折扣率须为 0 到 1 之间的正数」（服务层 `_validate_discount_rate`）；null 允许=清空（无折扣）。加购合并既有行时 null 同样清空 | `backend/src/schemas.py`（CartItemInput/CartPatchInput/CartItemOut）、`backend/src/services.py`（`_cart_add_inner`/`set_cart_qty`/`patch_cart_item`/`add_to_cart_batch`）、`backend/src/routers/api.py`（PUT 裸 dict 透传） | DISCOUNT-20261021 | 后端只存不算：不回填 amount，区间校验仍对 amount 生效 |
| 2026-10-21 | 新增 | checkout 快照：`_create_project_core` 落 ProjectItem 时写 `discountRate` = 购物车行值（分组透传，只写不改）；**手动建单 POST /projects 的 ProjectItemInput 同口径支持**（可选，商务手填场景，`_create_project_core` 统一校验，覆盖购物车结算/手动建单/直接下单/重新提交全部入口） | `backend/src/services.py`（`checkout`/`_create_project_core`）、`backend/src/schemas.py`（ProjectItemInput/ProjectItemOut） | DISCOUNT-20261021 | 手动建单入参改造成本小（schema 加可选字段 + core 统一校验一处），已实现 |
| 2026-10-21 | 新增 | bootstrap 带出：`cartItems[].discountRate` / `projectItems[].discountRate`（CartItemOut/ProjectItemOut 加字段，bootstrap 序列化自动带出）；review 接口不改（discountRate 只读展示，终审改价仍只写 price/amount） | `backend/src/schemas.py` | DISCOUNT-20261021 | 存量行/存量订单为 null（前端审核页「折扣」列 null 不显示） |

### 验证（dev server 8000，admin，curl 实测）

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` → import ok。
- `POST /api/cart`（asset #21，discountRate=0.9）→ 200，出参 `discountRate: 0.9`；bootstrap `cartItems[]` 带出 0.9。
- `PUT /api/cart/4` discountRate=0 / 1.5 / -1 → 均 400 `{"detail":"折扣率须为 0 到 1 之间的正数"}`；传 `null` → 200，bootstrap 显示 `discountRate: null`（清空生效）。
- `PATCH /api/cart/4`（amount=91980 + 服务期限 + discountRate=0.9）→ 200；`POST /api/cart/checkout` → 200，项目 pending，明细 `amount=91980.0 / origAmount=102200.0 / discountRate=0.9`（快照落库，bootstrap `projectItems[]` 带出）。
- 手动建单 `POST /api/projects`（asset #1，discountRate=0.85）→ 200，明细 `discountRate=0.85`；discountRate=2 → 400 同文案。
- 测试数据已清零：两个测试项目删除（projects 恢复 1 行云从项目）、购物车行恢复基线 3 行（discountRate 全 NULL）、asset #1/#21 lockedQty=0、project_items 恢复存量 3 行，库恢复现状。
- 未修改 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-21 ｜ 新增：PAGE-20261021 产品相关列表服务端分页（分支 feat/pricing-discount-timelines）

> 抽屉/详情页的可售明细、数量流水、操作记录由 bootstrap 全量下发改服务端分页（单页默认 10 条）。**bootstrap 快照字段（rsItems/flows/logs）保留不动**——RsItemPicker 树、项目页名称查找等消费方仍依赖全量镜像。契约见 api-contracts.md「PAGE-20261021 批次」，口径对齐 `GET /audit-logs` 先例（`page`/`pageSize` 参数、`{total, items}` 返回）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-21 | 新增 | `GET /api/assets/{asset_id}/rs-items`：可售明细分页（`id ASC`，默认 pageSize=10），items = `RsItemOut` 全 13 字段 + 派生 `soldCount`（该明细被 delivered 状态合同的项目明细计数：`project_items.itemId == rs_item.id` 且所属合同 `status='delivered'`；一条聚合查询按当页 id 批量计算，避免逐行查）。产品不存在 404「产品不存在」 | `backend/src/routers/api.py`（`list_rs_items`）、`backend/src/schemas.py`（`RsItemOutWithSold`） | PAGE-20261021 | 守卫 `get_current_user`（读接口三角色放行，与 bootstrap 读同口径）；替代前端遍历 contracts 派生「已售次数」列 |
| 2026-10-21 | 新增 | `GET /api/assets/{asset_id}/flows`：产品级数量流水分页（`assetId` 过滤，`id DESC`），items = `FlowOut`。产品不存在 404 | `backend/src/routers/api.py`（`list_asset_flows`） | PAGE-20261021 | asset 级流水对 viewer 全量放行是现状口径，保持一致 |
| 2026-10-21 | 新增 | `GET /api/assets/{asset_id}/logs`：产品操作日志分页（`target='asset'` 且 `assetId` 过滤，`id DESC`），items = `LogOut`。产品不存在 404 | `backend/src/routers/api.py`（`list_asset_logs`） | PAGE-20261021 | 抽屉「最近动态」由前端取两接口各一页后合并排序取 10 条（契约 §3，不新增合并端点） |

### 验证（dev server 8000，admin + viewer，curl 实测）

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` → import ok。
- `GET /api/assets/29/rs-items?page=1&pageSize=10`（admin）→ 200，`total=97`、items 10 条、每行 13 字段 + `soldCount`；`page=10` → 7 条（lastId=98）；`page=11` → 0 条。
- soldCount 口径核对：当前库 `contracts.status='delivered'` 为 0 条 → 全部明细 `soldCount=0`（SQL 基准查询同口径核对一致）。
- `GET /api/assets/29/flows` → 200 `{total:12, items:10}`（首条 id=78，id DESC）；`GET /api/assets/29/logs` → 200 `{total:122, items:10}`（首条 id=542，target='asset' 且 assetId=29）。
- viewer 三角色放行：三端点 viewer token 均 200（rs-items total=97 / flows total=12 / logs total=122）。
- 不存在产品：`GET /api/assets/9999/{rs-items,flows,logs}` → 404 `{"detail":"产品不存在"}`；无 token → 401。
- 只读操作，未动任何业务数据；未修改 frontend/、未执行构建/部署、未 git commit。

## 2026-10-24 ｜ 修改：REQUIRED-20261024 购物车结算必填口径（分支 feat/pricing-discount-timelines）

> 依据 ADR-022（业务拍板：购物车所有都是必填项），取代 ADR-018 §3「留空按挂牌价成交」兜底。前后端同批上线（契约见 api-contracts.md「REQUIRED-20261024 批次」）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-24 | 修改 | ⚠️ `checkout`（POST /cart/checkout）逐行必填校验，缺项 400 **一次报全**（文案含行标识：产品名 / 遥感明细「产品名·明细名」）：① 客户非空（原「请为每件产品填写客户」文案并入统一缺项格式）；② 销售金额 > 0 整数元（**所有行类型**：unit/amount/遥感明细行）；③ 普通产品行 serviceStart/serviceEnd 均必填且 start ≤ end（格式校验现状保留）；④ **遥感明细行（itemId 非空）服务期限豁免**（ADR-020） | `backend/src/services.py`（`checkout`）、`backend/src/routers/api.py`（docstring） | REQUIRED-20261024 | 400 文案：`购物车存在必填缺项，请补齐后再结算：{行标识}：客户 / 销售金额（整数元，大于 0）/ 服务期限（开始/结束日期均必填）`，多缺项以「；」分隔 |
| 2026-10-24 | 删除 | ⚠️ 删除 amount 为空回退 `salePrice×qty`（unit 行）/ 明细 price（遥感行）的**结算兜底分支**，及 viewer amount 模式行「免填回退 `round(挂牌价×数量)`」分支（ADR-012 免填口径作废）；`ROUND_HALF_UP` 导入随之移除 | `backend/src/services.py`（`checkout`） | REQUIRED-20261024 | ADR-018 §3「留空=原价成交」在结算链路下线；checkout 明细 amount 恒非空，`price` 恒为派生展示值 `round(amount÷qty, 6)` |
| 2026-10-24 | 不变 | 行更新接口（`PUT/PATCH /cart/{id}`、加购 `POST /cart`、`/cart/batch`）**不加**必填校验——允许暂存缺项（加购后分批补），仅 checkout 强制；区间校验（`_check_discount_range`，ADR-018/021）在 amount 填写时仍生效；手动建单（POST /projects）与 `POST /sales/order`（deprecated）不做本次必填变更（商务路径，不在 ADR-022 范围） | — | REQUIRED-20261024 | 契约 §2 |

### 下游自查（删兜底分支后）

- `_create_project_core`：checkout 传入的 `ProjectItemInput.amount` 恒非空——unit 行 `_item_pricing` 按派生 price×qty 重算（与 PRICING 批次折扣行行为一致）；amount 模式行 `_validate_amount_yuan` 幂等通过；遥感行 amount=明细金额权威（qty 恒 1）。
- 原价快照（ADR-018 §2）：`origPrice/origAmount` 取下单时刻挂牌价（asset.salePrice / rs.price），与 amount 是否填写无关，不受影响（实测 origAmount=102200 正确）。
- 合同金额派生：checkout 显式传 `contractAmount=Σ行 amount`，`_normalize_contracts` 直接采信，链路成立。

### 验证（dev server 8000，admin，curl 实测）

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` → import ok。
- 缺金额+缺期限（unit 行，产品 #21）→ 400 `购物车存在必填缺项，请补齐后再结算：区县级优质资源共建共享平台：销售金额（整数元，大于 0）；…：服务期限（开始/结束日期均必填）`（一次报全）。
- 客户改空 → 400 三项缺项一次报全（客户/销售金额/服务期限）。
- 补客户+金额（无期限）→ 400 仅缺服务期限；start>end（行更新层先 400 `服务开始日期不能晚于结束日期`；直接改库构造后 checkout 兜底同文案 400）。
- 补齐（amount=100000 + 2026-11-01~2026-12-31）→ **200**，项目 pending、contractAmount=100000.0；明细 amount=100000.0 / origAmount=102200.0 / 期限落库正确。
- 遥感明细行（asset #29·明细 #1，无金额无期限）→ 400 **仅**缺销售金额（期限豁免生效，行标识 `遥感数据-2026·河北/石家庄市 1.5m 2026-09`）；补 amount=300000 → **200**（contractAmount=300000.0）。
- 测试数据已清零：两个测试项目删除（projects 0 行）、购物车行 0 行、产品 #21/#29 lockedQty=0，库恢复现状。
- 未修改 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-20 ｜ 修改：数据订正——rs_items 删旧留新（「甘肃省」旧行删除 + 「河北省」→「河北」改名收尾，业务确认方案 A）

> 无代码变更，纯数据订正。前置备份 `backend/core_holdings.db.bak-province-cleanup`（保留不入库）。业务确认方案 A：清掉引用旧行的测试草稿购物车行后删旧明细。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修改 | 改名（上一轮已完成，本轮记录收尾）：`rs_items` id=1 明细 `province` 「河北省」→「河北」（`PUT /api/rs-items/1` 200）；行其余字段不变（石家庄市 / 1.5m / 2026-09 / ¥330,000） | `backend/core_holdings.db`（rs_items id=1） | rs_items 删旧留新 | 全表 province 去「省」后缀口径统一 |
| 2026-10-20 | 删除 | 删除测试草稿购物车行 `cart_items` id=9（lshangkun / userId=2 的草稿：assetId=29、itemId=2、qty=1、customer=''、amount=NULL、无服务期限，2026-10-20 17:19 创建）。**执行方式偏离说明**：`DELETE /api/cart/9`（admin token）被 ADR-009 购物车用户隔离拦截（`remove_cart_item` 强制 `userId == 当前登录用户`，admin id=1 ≠ 2 → 404「购物车项不存在」）；lshangkun 密码未知且约束不改代码，故按业务确认直接 SQL 删除（条件收紧 `id=9 AND userId='2' AND itemId=2`，命中 1 行）；该 API 路径本身不写审计日志，无审计差异 | `backend/core_holdings.db`（cart_items id=9） | rs_items 删旧留新 | 删除后 cart_items 12 行，无任何行再引用 itemId=2 |
| 2026-10-20 | 删除 | 删除旧明细 `rs_items` id=2（`DELETE /api/rs-items/2` admin → 200 `{"ok":true}`）。**被删行快照**：id=2 / assetId=29 / province=甘肃省 / city='' / resolution=1.0 / saleMonth=2026-10 / price=¥280,000 / repeatSale=true / createdAt=2026-10-16 11:42 / updatedAt=2026-10-16 11:46（新甘肃行 id=35–50 已覆盖 2024-10~2026-01 各期，本旧行为冗余） | `backend/core_holdings.db`（rs_items id=2） | rs_items 删旧留新 | 删除前 `DELETE /api/rs-items/2` 曾被 cart_items id=9 引用拦截 400「该明细存在销售关联，无法删除」，清草稿行后重试通过 |

### 删除后验证（全部通过）

- 资产 29 明细数：98 → **97**（`rs_items` 全表亦 97 条，资产 29 为唯一持有者）。
- 全表 province 无「省」后缀残留：`SELECT DISTINCT province` = **内蒙古 / 宁夏 / 新疆 / 河北 / 甘肃 / 陕西 / 青海**（7 省，`LIKE '%省'` 命中 0）。
- `project_items` 行数不变（0 行）；`cart_items` 12 行，无行引用 itemId=2。
- `GET /api/bootstrap`（admin）：`rsItems` = **97** 条，无「甘肃省」、无 id=2；河北行 = `{id:1, province:'河北', city:'石家庄市', resolution:1.5, saleMonth:'2026-09', price:330000}`。

### 97 条明细 province 清单（id / province / city / resolution / saleMonth / price）

- 河北（1 条）：1 / 河北 / 石家庄市 / 1.5 / 2026-09 / 330000
- 新疆（16 条，id 3–18）：1.0m × 2024-10~2026-01 各期 / 27400
- 陕西（16 条，id 19–34）：1.0m × 2024-10~2026-01 各期 / 31700
- 甘肃（16 条，id 35–50）：1.0m × 2024-10~2026-01 各期 / 20600
- 宁夏（16 条，id 51–66）：1.0m × 2024-10~2026-01 各期 / 11450
- 青海（16 条，id 67–82）：1.0m × 2024-10~2026-01 各期 / 6350
- 内蒙古（16 条，id 83–98）：1.0m × 2024-10~2026-01 各期 / 13375

- 约束遵守：未动其他数据、未改代码、未 git commit、备份文件 `core_holdings.db.bak-province-cleanup` 保留不入库。

## 2026-10-20 ｜ 新增/修改：RSITEM-RANGE-20261020 遥感售卖明细（rs_items）参考价区间（分支 feat/pricing-discount-timelines）

> 依据 ADR-021（取代 ADR-018 §5「遥感行不限制」口径），前后端同批上线（契约见 api-contracts.md「RSITEM-RANGE-20261020 批次」）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 新增 | ⚠️ 数据模型：`rs_items.priceMin/priceMax`（参考区间，元/份，可空=不限制，同 ADR-018 产品区间口径）；`main.py::_ensure_migration` 幂等加列（inspector + ALTER TABLE，沿用现有模式） | `backend/src/models.py`、`backend/main.py` | RSITEM-RANGE-20261020 | 存量 98 条明细区间 NULL=不限制（行为同现状）；见 database.md 本批次章节 |
| 2026-10-20 | 新增 | `POST /assets/{id}/rs-items`、`PUT /rs-items/{id}` 入参新增 `priceMin/priceMax`（≥0 可空，单边允许；传 null 清空）；两者都有时 min ≤ max 否则 400「参考区间下限不能大于上限」（复用 `_validate_price_range`，与产品区间同口径）；出参 `RsItemOut` 同步带出 | `backend/src/schemas.py`、`backend/src/services.py` | RSITEM-RANGE-20261020 | 契约 §2 |
| 2026-10-20 | 修改 | ⚠️ 折扣校验口径切换（ADR-021 §2）：`_check_discount_range` 新增 `rs` 参数——遥感明细行（itemId 非空）区间取**该 rs_item 自身** priceMin/priceMax（不再取父产品容器 assets 区间）；普通产品行行为完全不变；未设区间=不限制。覆盖全部 5 个调用点：加购 `_cart_add_inner`（POST /cart、/cart/batch 共用）、行更新 `update_cart_item`（PUT /cart/{id}）、行改客户 `patch_cart_item`（PATCH /cart/{id}）、直接下单 `_create_project_core`（POST /sales/order）、checkout `checkout`（POST /cart/checkout） | `backend/src/services.py` | RSITEM-RANGE-20261020 | 契约 §3；400 文案口径同 PRICING 批次 |
| 2026-10-20 | 修改 | bootstrap 快照：`rsItems[]` 每行带出 `priceMin/priceMax`（RsItemOut 出参自动带出） | `backend/src/schemas.py` | RSITEM-RANGE-20261020 | 契约 §1 |

### 验证

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` → import ok。
- 迁移：dev server 重启触发 `_ensure_migration`，`rs_items` 表 PRAGMA 确认 `priceMin/priceMax` 列已补；98 条存量明细区间全 NULL（不限制，行为同现状）。
- dev server（uvicorn --reload）全链路 curl 实测（admin）：`PUT /api/rs-items/1`（priceMin=200000/priceMax=400000）→ 200 出参含新字段；`PUT /api/rs-items/1`（min=500000 > max=200000）→ 400「参考区间下限不能大于上限」；`GET /api/bootstrap` rsItems 全行含 priceMin/priceMax 键（存量 null）。
- 校验口径实测：明细 #1 设区间 200000~400000 后——`POST /api/cart`（itemId=1, amount=100000 低于下限）→ 400「折扣单价超出该产品参考区间（200000~400000 元/份（可售明细））」（父产品容器区间为 NULL，证明取的是明细自身区间）；amount=250000 区间内 → 200；`PUT /api/cart/{id}`（amount=500000 超上限）→ 400；checkout 路径 Python 直调干跑（临时行 amount=900000）→ 400 同文案，回滚无残留；区间改回 null 后任意金额（amount=1）→ 200（不限制，现状行为保持）。
- 原价快照自查：`_create_project_core` 遥感行 `origPrice=rs.price` 分支未触碰，不受影响。
- 测试数据已还原：明细 #1 区间改回 null（rs_items 非空区间行数 0）、临时购物车行全部删除（残留 0）。
- 未修改 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-20 ｜ 新增/修改：PRICING-20261020 价格体系（区间/折扣）+ 时间节点 + 状态机 + 服务期限（分支 feat/pricing-discount-timelines）

> 依据 ADR-018 / ADR-019 / ADR-020，前后端同批上线（契约见 api-contracts.md「PRICING-20261020 批次」）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 新增 | ⚠️ 数据模型 4 表 10 列（全部可空，存量不迁移）：`assets.priceMin/priceMax`（参考区间，ADR-018 §1）、`cart_items.serviceStart/serviceEnd`（ADR-020）、`project_items.origPrice/origAmount`（原价快照，ADR-018 §2）+ `serviceStart/serviceEnd`、`contracts.signedDate/scheduledDeliveryDate`（ADR-019）；`main.py::_ensure_migration` 幂等加列 | `backend/src/models.py`、`backend/main.py` | PRICING-20261020 | 见 database.md 本批次章节 |
| 2026-10-20 | 新增 | `POST/PUT /assets` 接受 `priceMin/priceMax`（≥0 可空，单边允许）；两者都有时 min ≤ max 否则 400「参考区间下限不能大于上限」（update 按「存量+patch」组合值校验，防分两次编辑造成倒挂）；diff 日志新增「参考区间下限/上限」字段 | `backend/src/schemas.py`、`backend/src/services.py` | PRICING-20261020 | 契约 §2 |
| 2026-10-20 | 修改 | ⚠️ 购物车金额口径（ADR-018 §3）：unit 行与遥感明细行 `amount` 放开为折扣金额（整数元 ≥0，传入即采信 + 参考区间校验，不传 = NULL 原价成交）；amount 模式行口径不变（整数元权威）。覆盖入口：`POST /cart`、`/cart/batch`、`PUT /cart/{id}`、`PATCH /cart/{id}`、`POST /cart/checkout`、`POST /sales/order`（防直调绕过）。超限 400「折扣单价超出该产品参考区间（{min}~{max} 元/{unit}）」（单边区间按单边校验，未设区间不限制）；折扣单价 = amount÷qty（Decimal 6 位） | `backend/src/services.py`（新增 `_check_discount_range`）、`backend/src/schemas.py` | PRICING-20261020 | 契约 §3 |
| 2026-10-20 | 新增 | 服务期限（ADR-020）：`CartItemInput/CartPatchInput/ProjectItemInput/ReviewItemInput` 新增 `serviceStart/serviceEnd`（YYYY-MM-DD，start ≤ end 否则 400「服务开始日期不能晚于结束日期」）；购物车行填写 → checkout 透传落 `project_items`；审核 confirm 行级可改（只传一边时与存量另一边组合校验）；遥感行不填期限 | `backend/src/schemas.py`、`backend/src/services.py` | PRICING-20261020 | 契约 §4/§6 |
| 2026-10-20 | 新增 | 下单落库原价快照（ADR-018 §2）：`_create_project_core` 明细写入 `origPrice/origAmount`——普通行 = asset.salePrice / salePrice×qty（改价前的原始挂牌价），遥感行 = rs_items.price / 同值；**永不覆盖**（审核改价/终审不触碰）；`price/amount` 语义 = 最终价（折扣/终审后） | `backend/src/services.py` | PRICING-20261020 | 存量订单 orig 为 null（展示端按 price/amount 兜底） |
| 2026-10-20 | 删除 | ⚠️ `review_project` confirm **整体删除**终审改价回写 `assets.salePrice` 的逻辑（含「挂牌价更新」日志与 price_changes_by_asset 装配）——挂牌价/参考区间仅由产品管理维护，改价只写 ProjectItem.price/amount（ADR-018 §4） | `backend/src/services.py` | PRICING-20261020 | 行为变更：终审改价不再污染挂牌价 |
| 2026-10-20 | 新增 | ⚠️ 新端点 `PATCH /contracts/{id}`（require_order）：录入 `signedDate`（editor/admin，接手人守卫与审核同口径；仅合同 active 可录入，录入即 active→delivering + 项目重算 + 日志「录入合同签订时间」；录后可改、传 null 清空 400「签订时间录入后不可清空」）/ `scheduledDeliveryDate`（**仅 admin**，非 admin 403；仅 delivering 可录/改/清空，null 允许；日志「录入预计交付时间」）；viewer 403「只读账号不可执行该操作」；返回 ContractOut | `backend/src/routers/api.py`、`backend/src/services.py`（新增 `patch_contract_fields`）、`backend/src/schemas.py`（新增 `ContractFieldPatch`） | PRICING-20261020 | 契约 §5；ADR-019 |
| 2026-10-20 | 修改 | ⚠️ 合同状态机扩展（ADR-019）：`pending → active → delivering（新）→ delivered`，terminated 各阶段可达。`PATCH /contracts/{id}/status` 白名单加 delivering（但直接变更到 delivering 400，仅录签订时间自动触发）；`active→delivered` 新守卫 400「合同尚未录入签订时间，不可交付」（存量 active 合同需商务先补录）；`delivering→delivered` 为交付路径（扣量/流水/Outbound 不变，仍在交付时发生）；`delivered` 撤销交付后合同回 **delivering**（原回 active，signedDate 仍在不能回合同签订中）；delivering 合同终止释放锁定；项目批量交付/删除项目/产品删除守卫同步覆盖 delivering | `backend/src/services.py` | PRICING-20261020 | 契约 §5 |
| 2026-10-20 | 修改 | ⚠️ `_derive_project_status` 按 ADR-019 §3 重写：全 pending→pending；全 delivered→delivered；含 terminated 且其余全 pending/terminated→terminated；全部合同 ∈ {delivering, delivered}（全部已签）→**delivering（交付中）**；其余→active。项目金额/customer 派生逻辑不动 | `backend/src/services.py` | PRICING-20261020 | 项目/合同 status 新增值 `delivering`（中文「交付中」） |
| 2026-10-20 | 修改 | bootstrap 快照新字段（均随 schemas 出参自动带出，viewer 过滤为行级、对新字段无影响）：`assets[].priceMin/priceMax`、`cart[].serviceStart/serviceEnd`、`projectItems[].origPrice/origAmount/serviceStart/serviceEnd`、`contracts[].signedDate/scheduledDeliveryDate` | `backend/src/schemas.py` | PRICING-20261020 | 契约 §1 |
| 2026-10-20 | 修改 | ⚠️ `POST /sales/order` 标记 **deprecated**（ADR-020：前端移除「登记销售」入口，购物车为唯一下单链路）；端点保留兼容潜在直调方，折扣金额同样过区间校验 | `backend/src/routers/api.py` | PRICING-20261020 | 契约 §7 |

### 验证

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` 无错。
- 内存 SQLite 冒烟（不碰真实库）42 项断言全部通过，覆盖：区间校验三态（双边内/超上限/低于下限/单边/无区间）、非整数元 400、unit 行 amount 采信与原价快照、checkout 落 orig+servicePeriod、服务期限 start>end 400、审核改价后 salePrice 不变 + orig 不变 + 服务期限可改、viewer/非接手人 403、录 signedDate→delivering、2 合同 1 签 1 未签→项目 active、全签→delivering、active 未签直接交付 400、scheduledDeliveryDate editor 403 / 非 delivering 400 / admin 可录、清空 signedDate 400、直接变更 status=delivering 400、delivering 交付扣量 + Outbound 关联明细、撤销交付回 delivering + 回退扣量、sales/order 直调超区间 400、产品 min>max 400。
- 真实库副本迁移验证：副本删 10 新列模拟存量库 → 执行 `_ensure_migration` → 4 表 10 列全部补齐，10 张业务表行数完全不变（assets 28 / cart_items 3 / project_items 16 / contracts 15 / projects 6 / outbounds 0 / flows 162 / logs 507 / users 8 / rs_items 98）；二次执行幂等 no-op。
- dev server（uvicorn --reload）全链路 curl 实测（admin）：`POST /assets`（min>max）→ 400「参考区间下限不能大于上限」；`POST /projects`（unit 行折扣 23000×2 + 服务期限）→ 200，明细 `origPrice=25000 / origAmount=50000 / amount=46000 / serviceStart=2026-11-01 / serviceEnd=2026-12-01`；`POST /projects/{id}/review`（confirm）→ 200；`PATCH /contracts/{id}`（signedDate=2026-10-20）→ 200 `status=delivering`；`PATCH /contracts/{id}`（signedDate=null）→ 400「签订时间录入后不可清空」；`PATCH /contracts/{id}`（scheduledDeliveryDate=2026-11-15）→ 200；`PATCH /contracts/{id}/status`（delivered）→ 200；`DELETE /projects/{id}` 清理 → 200（产品 shippedQty 回退 0、项目/合同级联删除）；`GET /bootstrap` 响应含全部新字段（存量行值为 null）。
- 存量数据：当前库无 active 合同（全部 pending/terminated），无需补录；上线后如有 active 合同由商务经新端点补录 signedDate。
- 未修改 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-20 ｜ 新增：资产 29（CH-SAT-029「遥感数据-2026」）批量录入 96 条遥感售卖明细

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 新增 | 数据录入（无代码变更）：资产 29（type='遥感数据' 父产品容器）下批量录入 **96 条** `rs_items` 可售明细 = 6 省（新疆/陕西/甘肃/宁夏/青海/内蒙古）× 精度 1.0m × 16 期（2024-10 至 2026-01 含首尾）；单价口径 25 元/km² × 面积（新疆 27400 / 陕西 31700 / 甘肃 20600 / 宁夏 11450 / 青海 6350 / 内蒙古 13375 元/份），同一省各期单价相同；city=''、repeatSale=true | `backend/core_holdings.db`（rs_items id 3–98） | 资产 29 遥感明细批量录入 | 执行方式：正式 API 路径（admin 登录取 token → `POST /api/assets/29/rs-items` 循环 96 次，全部 200，0 判重、0 失败）；服务层判重与唯一索引 `uq_rs_items_dim` 全程生效 |

### 录入前现状

- 资产 29 下原有 2 条明细（均保留未动）：id=1 河北省/石家庄市 1.5m 2026-09（330000 元）、id=2 甘肃省 1.0m 2026-10（280000 元）。
- 目标组合（6 省 × 1.0m × 16 期）与存量无判重命中（服务层判重键为 省/市+精度+月份 精确匹配），96 条全部新增、无跳过。
- ⚠️ 命名口径提示：存量 id=2「**甘肃省**」1.0m 2026-10（280000 元）与本次新增「**甘肃**」1.0m 2026-10（id=50，20600 元）语义为同一维度，仅省份名写法不同（带/不带「省」），唯一约束不判重。本次按业务给定省份名（不带「省」）录入；两条并存是否需归并/清理，留待业务确认，本次未擅自处理。

### 验证

- 录入后 `rs_items` 中 assetId=29 总数 = **98**（原有 2 + 新增 96）；新增部分按省分组各省均 16 条，月份 distinct = 16，resolution 均为 1.0。
- 抽查 3 条：id=3 新疆 1.0m 2024-10 27400 元 ✓；id=59 宁夏 1.0m 2025-06 11450 元 ✓；id=98 内蒙古 1.0m 2026-01 13375 元 ✓。
- `GET /api/bootstrap`（admin token）响应 `rsItems` 共 98 条，其中 assetId=29 为 98 条，前端可正常取到。
- 回滚方式（如需清理）：`DELETE FROM rs_items WHERE assetId=29 AND id BETWEEN 3 AND 98`（本次 96 条无销售关联，`DELETE /api/rs-items/{id}` 亦可逐条删除）。
- 未修改任何代码文件、未执行构建/部署、未 git commit。

## 2026-10-20 ｜ 删除：CLEANUP-20261020 移除「生态人员基础资料」（base_records kind='reps'）

> 生态人员已由 `users` 表 + viewer 角色承载，`base_records`（kind='reps'）为无人消费的遗留数据，整体下线。前后端同批上线（契约见 api-contracts.md「CLEANUP-20261020 批次」）。

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修改 | ⚠️ `POST/PUT/DELETE /bases/{kind}` 对 `kind='reps'` 统一返回 400「该基础资料类型已下线」（新增 `_check_base_kind` 守卫）；`suppliers` / `customers` 行为不变 | `backend/src/routers/api.py` | CLEANUP-20261020 | 契约 §2；`_BASE_LABEL` 同步移除 `reps` 项 |
| 2026-10-20 | 删除 | ⚠️ `GET /bootstrap` 响应**移除 `reps` 字段**（快照组装不再查询 kind='reps'）；`add_base` 日志文案清理（仅保留 suppliers/customers 分支） | `backend/src/services.py` | CLEANUP-20261020 | 契约 §1；bootstrap 为纯 dict 返回，schemas 无对应字段需删；前端并行删除 `db.reps` 镜像 |
| 2026-10-20 | 修改 | `models.BaseRecord` 注释更新（标注 reps 已下线） | `backend/src/models.py` | CLEANUP-20261020 | 仅注释，无结构变更 |
| 2026-10-20 | 删除 | 数据清理：`DELETE FROM base_records WHERE kind='reps'`。执行前备份 `core_holdings.db.bak-reps-cleanup`（已被 .gitignore 的 `*.bak*` 规则忽略，未 git add） | `backend/core_holdings.db` | CLEANUP-20261020 | 见下方行数报告 |

### 数据清理行数报告

清理前 / 清理后（`base_records`）：

| kind | 清理前 | 清理后 |
|---|---|---|
| reps | 0 | 0 |
| suppliers | 8 | 8 |
| customers | 0 | 0 |
| 合计 | 8 | 8 |

- 执行 `DELETE FROM base_records WHERE kind='reps'` 实际删除 **0 行**（reps 数据此前已无存量，删除为幂等操作）。
- 其余各表行数清理前后完全一致（assets 28 / projects 4 / outbounds 0 / flows 156 / logs 392 / deliverable_templates 32 / category_units 8 / project_items 10 / asset_deliverables 123 / cart_items 3 / users 8 / audit_logs 633 / file_meta 48 / contracts 9 / rs_items 2），无其他表受影响。

### 验证

- `python3 -m compileall -q src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models / main` 无错。
- 全局检索 `reps`（backend/）：仅命中注释说明与 `_check_base_kind` 的 `if kind == "reps"` 守卫，无残留业务逻辑。
- 实测（dev server --reload，admin 登录）：`POST /api/bases/reps` → 400 `{"detail":"该基础资料类型已下线"}`；`DELETE /api/bases/reps/1` → 400 同文案；`POST /api/bases/suppliers` → 200 `{"ok":true}`；`GET /api/bootstrap` 响应 keys 中**无 `reps`**（suppliers/customers 均在）。
- 未触碰 frontend/ 任何文件、未执行构建/部署、未 git commit。

## 2026-10-20 ｜ 修复：FIX-20261020 业务逻辑 13 项修复（分支 fix/business-logic-bugs-20261020）

| 日期 | 类型 | 变更内容 | 影响文件范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-20 | 修复 | 权限守卫自查：遍历 `routers/api.py` 全部写接口（POST/PUT/PATCH/DELETE），确认每个均有 `require_editor` / `require_order` / `require_admin` 守卫（自查结果：无裸接口，未新增守卫）；`require_editor` 的 403 `detail` 由「无权限执行此操作」改为「只读账号不可执行该操作」（契约文案，前端 403 统一 toast detail） | `backend/src/security.py` | FIX-20261020-#1 | ADR-014：前端移除 viewer 写请求白名单后，后端守卫为唯一安全边界；`require_admin` 文案保持「无权限执行此操作」（该守卫拦截对象含 editor，不适用"只读账号"措辞） |
| 2026-10-20 | 修复 | `create_outbound`（补录交付）库存口径：`mode != "history"` 时不再执行 `lockedQty = max(0, lockedQty - qty)`，仅 `shippedQty += qty`（保留 `min(quantity, …)` 夹零防御）；可售校验保留且基于**未改动**的 `lockedQty` | `backend/src/services.py` | FIX-20261020-#2 | ADR-015：补录交付不对应订单明细、未释放过锁，偷减 lockedQty 会侵占其他订单锁定并造成超卖/撤销后凭空增可售 |
| 2026-10-20 | 新增 | `create_outbound` 新增 400 校验（文案见 api-contracts.md）：`qty <= 0` →「交付数量必须大于 0」；项目状态 pending/terminated →「该项目当前状态不可登记交付」；`assetId` 不在所选项目明细中 →「该产品不属于所选项目」；`asset.type == '遥感数据'` 父产品 →「遥感容器不可直接交付，请交付其数据明细」 | `backend/src/services.py` | FIX-20261020-#9、FIX-20261020-#13a | ADR-015 §2-§4；校验顺序：qty → 产品存在 → 遥感容器 → 项目状态 → 产品归属 → 防重复 → 可售 |
| 2026-10-20 | 删除 | ⚠️ `OutboundInput` 请求体移除 `operator` 字段（后端一直不采信，操作人取路由层登录账号）；前端旧版本多传该字段时 Pydantic 默认忽略未知字段，不报错 | `backend/src/schemas.py` | FIX-20261020-#2 | 契约 FIX-20261020 §2：前端同步删除该字段与输入框 |
| 2026-10-20 | 修复 | `checkout`（购物车结算）分组键由 `assetId` 单键改为 `(assetId, customer)`，每组合并数量/金额后生成一条 `ContractInput`，合同 `customer` 取分组键；容器明细行（itemId 非空）与产品行的组合方式不变 | `backend/src/services.py` | FIX-20261020-#3 | ADR-016：一资产一客户一记录；修复同产品多客户行被静默合并为一条记录（客户归属/金额串账）；前端预览口径同步改双键分组 |
| 2026-10-20 | 修复 | `_apply_item_delivery` 生成的 `Outbound.operator` 由 `project.rep`（生态人员/下单人）改为实际触发交付的登录账号（`operator` 参数，调用方透传 `user.username`）；合同交付（`change_contract_status`）与存量项目交付（legacy 路径）两条调用链均已透传 | `backend/src/services.py` | FIX-20261020-#5 | 契约 §3：交付记录「经办人」与审计日志操作人一致，可追溯实际操作人 |
| 2026-10-20 | 修复 | `bootstrap` viewer 过滤补齐：`outbounds` 仅返回 `projectId ∈ 可见项目` 或 `contractId ∈ 可见合同` 的记录；`flows` 按引用过滤（contractId ∈ 可见合同，或 ref 指向可见 SP-/HT-/CK- 编号；产品级流水如登记 purchase_in 放行）；`logs` 按引用过滤（project 日志按 detail 中 SP- 编号 / contractId / 项目名匹配，outbound 日志按 CK- 编号匹配，asset/setting 日志放行） | `backend/src/services.py` | FIX-20261020-#6 | 修复 viewer 经 /bootstrap 获取全量交付记录/流水/日志的跨客户信息泄露；过滤口径宁可保守不漏放 |
| 2026-10-20 | 修复 | `GET /users/options/all`：viewer 仅返回本人 + 其可见项目中 `rep`/`creator`/`businessOwner` 出现过的启用账号；admin/editor 返回全部启用账号（现状不变） | `backend/src/routers/api.py` | FIX-20261020-#6 | 契约 §5；可见项目判定复用 `services.user_sees_project` |
| 2026-10-20 | 新增 | `Outbound` 新增 `projectItemId: int \| None`（nullable）列，指向 `ProjectItem.id`：合同交付（`_apply_item_delivery`）创建交付记录时写入对应明细 id；手动补录为 None。`schemas.OutboundOut` 同步新增该字段 | `backend/src/models.py`、`backend/src/schemas.py`、`backend/src/services.py` | FIX-20261020-#7 | 契约 §4；前端无需处理（不展示该字段），仅类型定义同步 |
| 2026-10-20 | 修复 | 撤销交付（`_revert_outbound_inner`）明细定位：`projectItemId` 非空时按 id 精确定位（明细已随项目删除时回退 limit(1)）；为 None 时回退现有 `contractId+assetId limit(1)` 逻辑（兼容存量） | `backend/src/services.py` | FIX-20261020-#7 | 修复同合同同产品多明细时撤销取错行、再交付重复计收入 |
| 2026-10-20 | 新增 | SQLite 兼容加列：`main._ensure_migration` 幂等补 `outbounds.projectItemId`（`PRAGMA table_info` 检测 + `ALTER TABLE ADD COLUMN` + 索引 `ix_outbounds_projectItemId`），与项目既有迁移先例一致 | `backend/main.py` | FIX-20261020-#7 | `create_all` 不会给已有表加列；当前库 outbounds=0 行，无数据迁移；幂等（列已存在时 no-op） |
| 2026-10-20 | 修复 | `update_asset`：`type` 变更时重算 `pricingMode`（卫星Token → `amount`，其余 → `unit`），与新建逻辑（`create_asset`）一致；变更时追加「计价模式: x → y」日志 | `backend/src/services.py` | FIX-20261020-#8 | `pricingMode` 不在可更新白名单内，只能由类型权威推导，前端无需传 |
| 2026-10-20 | 修复 | `rep`（生态人员）口径归一：新增 `_normalize_rep`——值在用户表中匹配 `name` 则替换为对应用户 `username`，已是 username 或无匹配则原样保存；应用于 `_create_project_core` 与 `_order_core` 入口（覆盖手动建单/重新提交/购物车结算/直接下单全部链路） | `backend/src/services.py` | FIX-20261020-#10 | 前端两处入口同步改传 username，后端归一为兜底；存量数据不迁移 |
| 2026-10-20 | 修复 | `review_project` 驳回分支：合同备注由覆盖（`c.remark = f"驳回：{reason}"`）改为追加——原备注非空时 `c.remark = 原备注 + "｜驳回：" + reason`，空时保持原文案 | `backend/src/services.py` | FIX-20261020-#11 | 保留下单时的原合同备注，驳回原因仍留痕可见 |
| 2026-10-20 | 新增 | `_create_project_core`：任一合同 `customer` 为空 → 400「请为每份销售记录填写客户」（覆盖 contracts 入参与 items 自动包装单合同两条路径） | `backend/src/services.py` | FIX-20261020-#13b | 契约 §6；前端有校验，此为 API 直调兜底 |
| 2026-10-20 | 新增 | 遥感父产品（容器）购买拦截：`_cart_add_inner` / `_order_core` / `_create_project_core` 三个入口，产品 `type == '遥感数据'` 且非容器明细行（itemId 为空）→ 400「遥感数据容器不可直接购买，请购买其数据明细」；容器明细行（itemId 非空，指向 rs_items）放行 | `backend/src/services.py` | FIX-20261020-#13c | 契约 §6；覆盖 POST /cart、/cart/batch、POST /sales/order、POST /projects |
| 2026-10-20 | 修改 | ADR-017 后端计价自查：确认 `_derived_price = amount / qty`（元/份）与免填金额兜底 `salePrice × qty`（取整元）全程无 1e4 换算，现状即符合，无代码改动 | （无） | FIX-20261020-#4 | 仅自查确认；全库检索 `1e4/10000/万Token` 仅命中注释与 seed 数据值 |

### 验证

- `python3 -m compileall src main.py` 通过；`import src.services / src.routers.api / src.schemas / src.models` 无错。
- 内存 SQLite 冒烟测试 39 项断言全部通过（不触碰真实库）：rep 归一、空客户 400、遥感父产品三入口拦截 + 明细行放行、补录交付 4 个 400 场景 + lockedQty 不触碰 + 撤销对称、checkout 同产品双客户拆 2 条记录、驳回备注追加、合同交付 operator/projectItemId 落库、同合同同产品双明细撤销精确定位、type 变更 pricingMode 双向重算、bootstrap viewer 项目/合同/交付/流水/日志过滤 + admin 全量。
- 真实库副本验证：`outbounds.projectItemId` 列（INTEGER，可空）+ 索引 `ix_outbounds_projectItemId` 存在，各业务表行数不变（无数据迁移）。
- 未触碰 frontend/ 任何文件、未修改 core_holdings.db 业务数据、未 commit。

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

## 2026-10-22 ｜ FIX-20261022-OBS01：一次性数据修复——按 contractId 回填 flows.ref

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修复 | 新增一次性脚本 `backend/scripts/backfill_flow_refs.py`（幂等、可重复执行，支持 `--dry-run`）：`UPDATE flows SET ref = contracts.code WHERE contractId IS NOT NULL AND ref != contracts.code`，修复历史清理脚本改合同编号未同步流水导致 `ref` 指向已不存在旧编号的问题（仅展示层，可见性按 `contractId` 权威外键判定不受影响）。**实际执行一次，影响 64 行**（QA 标记的 5 行 id 78/136/160/164/212 均在其中，其余为同因未标记的历史流水）；复跑影响 0 行，验收只读查询（`contractId IS NOT NULL AND ref != c.code`）= 0 | `backend/scripts/backfill_flow_refs.py`（新增）、`backend/core_holdings.db`（flows.ref × 64） | FIX-20261022-OBS01 / OBS-FIX20261022-01 / ADR-031 | 执行前备份：`/tmp/flows-backup-1792638499.db`（保留）；未改 `backend/src/` 业务代码，数据变更无需重启服务 |

## 2026-10-22 ｜ RS-RESET-20261022：一次性数据操作——清空「遥感数据-2026」可售明细

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 删除 | 新增一次性脚本 `backend/scripts/reset_rs_items.py`（显式 `--asset-id` + `--yes` 才写库，支持 `--dry-run`；预检强制 `type='遥感数据'`、`project_items.itemId` 有销售引用即中止；单事务删除 + 回读校验）：**实际执行一次，删除 `rs_items` 97 条**（assets#29「遥感数据-2026」，月份 2024-10 ~ 2026-09，单价 6350 ~ 330000 元/份），**同时清理 `cart_items` 3 行**指向这些明细的购物车引用（userId=8，itemId=1/3/4，qty=1，均为未结算草稿，不清理会留悬空 itemId 导致前端坏行/结算 400）；补写 OpLog #691（`target=asset`、`assetId=29`、`action=清空可售明细`、`operator=admin`） | `backend/scripts/reset_rs_items.py`（新增）、`backend/core_holdings.db`（rs_items −97 / cart_items −3 / logs +1） | RS-RESET-20261022 / ADR-011 / ADR-031 | 执行前备份：`/tmp/rs-items-backup-20261022-151059.db`（SQLite 在线备份 API，integrity_check=ok，保留不删）；**无销售引用**（`project_items.itemId` 全为 NULL），**未回滚任何销量**（assets#29 soldCount/soldAmount 仍为 0）；产品本体（quantity=1 / unit / repeatSale / 价格区间）未改动；未改 `backend/src/` 业务代码，数据变更无需重启服务，前端刷新即为空明细 |
## 2026-10-22 ｜ NO-DISCOUNT-20261022：购物车折扣功能下线（⚠️ 行为变更：折扣率不再受理，历史值保留；ADR-039 / Deprecates ADR-023）

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-22 | 修改 | ⚠️ **折扣率入参全线「容忍但忽略」**：`PUT /api/cart/{id}`（`set_cart_qty`）、`PATCH /api/cart/{id}`（`patch_cart_item`）、`POST /api/cart`、`POST /api/cart/batch`（`_cart_add_inner`）不再读取/校验/写入 `discountRate`；`POST /api/projects`、`POST /api/sales/orders`、`POST /api/cart/checkout` 共用的权威校验链（`_create_project_core`）删掉「③ 折扣率」一步，新 `project_items.discountRate` **一律写 `null`**；checkout 分组元组去掉购物车行的历史 rate（历史快照不再透传）。旧客户端传 0 / 1.5 / 999 → 200（此前 400「折扣率须为 0 到 1 之间的正数」） | `backend/src/services.py`（`_cart_add_inner` / `patch_cart_item` / `set_cart_qty` / `checkout` / `_create_project_core` / `_restore_items_to_cart`）、`backend/src/routers/api.py`（2 端点）、`backend/src/schemas.py`（6 处字段注释） | NO-DISCOUNT-20261022 / ADR-039 | **列保留不清洗**（`cart_items.discountRate` / `project_items.discountRate` 均在，历史值原样可查）；存量行被 PUT/PATCH/加购合并时该列**保持原值**（不覆盖、不清空）；`POST /projects/{id}/review` 改价本就不写该列，本批补注释锁定不变量 |
| 2026-10-22 | 删除 | 死代码清理：`services._validate_discount_rate`（原 ADR-023 的 `0 < rate ≤ 1` 校验）**调用点全部移除后删除**；删除前全部调用点 = `_create_project_core`（L1706）、`_cart_add_inner`（L3215）、`patch_cart_item`（L3309）、`set_cart_qty`（L3449），共 4 处，均已去掉调用 | `backend/src/services.py` | NO-DISCOUNT-20261022 / ADR-039 | `schemas` 中 `discountRate` 字段定义**保留**（旧客户端传值不 422），注释改为「已下线（ADR-039），后端忽略」 |
| 2026-10-22 | 修改 | 不改动：`_check_discount_range` / `_check_unit_price_range` 的**金额区间校验**逻辑（`unit_price = amount ÷ qty` 与 `priceMin/priceMax` 比较、viewer 单边 / editor 双向）**逐字未动**；仅确认二者内部无「用折扣率推算金额」的路径（函数名 `discount` 为 ADR-018 历史命名），并在 docstring 注明 | `backend/src/services.py` | NO-DISCOUNT-20261022 / ADR-018 / ADR-021 / ADR-037 | 回归实测：viewer 超上限 30000 → 200、低于下限 20000 → 400；editor 双向 400；区间内 200；checkout 权威链 editor 超上限 → 400 |
| 2026-10-22 | 修改 | 验证方式：**副本库 + TestClient**（`/tmp/nodiscount-verify.db`，TestClient 35 条断言全 PASS）+ 副本库上临时端口 8123 的真实 HTTP curl（不触碰 8000 运行中服务、不重启、无 schema 变更）。另：`python3 -m compileall src main.py` 通过 | `backend/src/**` | NO-DISCOUNT-20261022 | 前端需知：响应体仍返回 `discountRate`（存量值原样、新单恒 `null`）；前端已按 ADR-039 移除折扣入口，该字段仅作历史追溯 |
| 2026-10-22 | 修改 | **400 文案去「折扣」字样（纯文案收口，逻辑/表零改动）**：`_check_discount_range` 超区间 400 `折扣单价超出该产品参考区间（…）` → **`单价超出该产品参考区间（…）`**；区间数值、单边/双边 `_range_label` 格式、viewer 单边 / editor 双向判定、错误码 400 全部不变 | `backend/src/services.py`（`_check_discount_range` 的 `raise HTTPException(400, ...)` + docstring 引用句）、`docs/backend/api.md`（5 处文案示例 + 收口说明） | NO-DISCOUNT-20261022 / ADR-039 | 全后端 grep 复核：用户可见字符串已无「折扣」，仅注释/启动期 `print` 保留 ADR-023/039 历史引述（`main.py` print 属运维日志，非业务文案，未改）；实测（副本库 TestClient + 临时端口 8123 真实 curl）：viewer `amount=20000`→400、editor `30000`→400 均返回新文案且不含「折扣」，editor `25200`→200；`python3 -m compileall src main.py` 通过，未重启服务（8000 为 `--reload`，改动已自动热载），未 commit |

## 2026-10-23 ｜ TASK-USER-FINANCE-01：新建 4 个商务人员（editor）账号

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-23 | 新增 | 新建 4 个商务人员（editor）账号：luojie/罗杰、ldanhong/刘丹红、xieyou/谢优、zjingren/周靖人 | users 表 + audit_logs（经 POST /api/users） | TASK-USER-FINANCE-01 | 初始密码 123456，需首次登录后修改 |

> 纯数据操作（**未改任何业务代码**，服务未重启）：4 次 `POST /api/users` 均 200，返回 id=25/26/27/28、role=editor、enabled=true；`GET /api/users` 复核 4 条在列；`POST /api/auth/login`（luojie/123456）200 且 role=editor；`audit_logs` 新增 4 条 `actionType=user_mgmt / action=新增用户 / target=user`（`targetName` 分别 luojie、ldanhong、xieyou、zjingren，`detail=role=editor`，id 1232~1235）。

## 2026-10-26 ｜ 修改：购物车服务期限由必填改选填（ADR-047）

**关联任务**：OPTIONAL-SERVICEPERIOD-20261026（决策 ADR-047，部分取代 ADR-022 §1 第三条）。业务拍板：服务期限改为可选，只放开「两端都空」，半填仍拦截。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-26 | 修改 | ⚠️ `checkout` 服务期限由必填改**选填**：普通产品行 `serviceStart`/`serviceEnd` **两端都空 → 放行**（落库 `null`）；**只填一端 → 仍计入缺项**（400 文案改 `{行标识}：服务期限（开始/结束日期需成对填写，或都留空）`，原「（开始/结束日期均必填）」作废）；**两端都填 → 保持 ADR-020 校验**（`YYYY-MM-DD` + start ≤ end，非法仍 400 `服务开始日期不能晚于结束日期`）；客户 / 销售金额必填口径**不变**（ADR-022 §1 前两条继续有效）；遥感明细行（`itemId` 非空）豁免不变 | `backend/src/services.py`（`checkout` 必填校验分支 + docstring / 校验注释）、`backend/src/routers/api.py`（`POST /cart/checkout` docstring） | ADR-047 / OPTIONAL-SERVICEPERIOD-20261026 | **无 schema 变更**：`cart_items` 与 `project_items` 的 `serviceStart/serviceEnd` 本就 `nullable=True`，无迁移；`_validate_service_period()` 本来就支持 None/空串，**零改动**；行更新接口（`POST/PUT/PATCH /cart`）允许暂存行为不变；存量数据无需回填 |
| 2026-10-26 | 修改 | 文档同步：新增 `docs/adr/ADR-047.md`；`ADR-022` 标注「部分被取代」；`architecture.md` ADR 表补 ADR-047、ADR-022 行注明服务期限一条已取代；`api-contracts.md` 新增 OPTIONAL-SERVICEPERIOD-20261026 批次；`api.md` 更新错误码表 3 处文案 + 2 处引用 | `docs/**` | ADR-047 | — |

> 验证方式：把 `core_holdings.db` 复制到 `/tmp/ch_test.db`，以 `DATABASE_URL` 指向副本另起 **8001** 实例做真实 HTTP 实测（**不触碰 8000 运行中服务、不动生产库**，测完关闭实例并清理临时文件）：① 两端都不填 → **200 建单**，`project_items.serviceStart/serviceEnd` 均 `NULL`；② 只填开始 → **400** `…智元机器人-X2：服务期限（开始/结束日期需成对填写，或都留空）`；③ 只填结束 → **400** 同上（对称）；④ 两端都填且 start ≤ end → **200**，落库 `2026-11-01` / `2026-12-31`。另：`python3 -m compileall -q src main.py` 通过。未构建、未部署、未 commit。

## 2026-10-27 ｜ 数据订正：销售单价与区间最低价统一上调 1%（PRICE-UP-20261027）

**关联任务**：PRICE-UP-20261027。业务要求：除遥感数据销售明细价格（`rs_items.price`）外，其余产品的**销售单价**（`assets.salePrice`）与**参考区间最低价**（`assets.priceMin`）上调 1%。**纯数据订正，未改任何业务代码**（脚本 `backend/scripts/adjust_price_up_1pct.py`，dry-run + `--yes` 两段式）。

| 日期 | 类型 | 变更内容 | 影响范围 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-10-27 | 修改 | **19 个产品** `salePrice` / `priceMin` × 1.01（round 2 位）：#1 3006700→3036767、#2 1305000→1318050、#3 7600000→7676000、#4 955000→964550、#5 3130000→3161300、#9 25000→25250、#15 35100→35451、#16 26800→27068、#21 102200→103222、#22/#23 5500000→5555000、#24 3160000→3191600、#25 5550000→5605500、#26 5000000→5050000、#27 7430925→7505234.25、#28 32560000→32885600、#30 24213.65→24455.79、#31 24243→24485.43、#32 6700000→6767000 | `assets`（salePrice / priceMin） | PRICE-UP-20261027 | 每个产品写 1 条 `logs`（`action='调整价格'`，共 19 条）；`priceMin` 与 `salePrice` 调后仍相等（ADR-036「min=单价」口径未破） |
| 2026-10-27 | 不变 | **排除**：① Token 服务 #6/#7/#8（宏大卫星 26年10月发射 / 46号卫星 / 38号卫星，业务明确不调，仍为 `0.03333333`）；② 无实际价格产品 #18/#19/#20 算力服务器、#29 遥感数据容器（`salePrice=0` 且 `priceMin=NULL`）；③ **`rs_items.price` 60 条未动**（Σ=10,354,297 执行前后一致）；④ `project_items.origPrice/origAmount/price/amount`（历史快照，Σ 79,773,700 / 142,498,850 前后一致）、`contracts.contractAmount`（Σ 142,498,850 前后一致）；⑤ **`priceMax` 全部未动**（Σ 89,388,341.78 前后一致） | — | PRICE-UP-20261027 | 副作用：`priceMin` 上移而 `priceMax` 不变 → 可谈价区间由约 2% 收窄至约 1%（如 #1：3036767~3066834） |
| 2026-10-27 | 修改 | 购物车在途行同步：`cart_items#7`（产品 #1 智元机器人-G1，客户 `QA034-UI客户`）`amount` 3006700 → **3036767**，避免结算时低于新区间下限被 400 拦截 | `cart_items` | PRICE-UP-20261027 | 其余 5 行 `amount` 为空，不受影响；购物车行的 `serviceStart/serviceEnd` 未动 |

> 安全措施：执行前用 **SQLite 在线备份 API** 备份到 `backend/core_holdings.db.bak.20261027-094358-price-up-1pct`（服务在线运行，未用 `cp`）；单事务 UPDATE + 事务内回读校验（19 行逐行比对预览值），异常即回滚；`priceMin > priceMax` 前置拦截（本次无命中）。
> 校验结果：`min <= max` 全部合法（无违规行）；`priceMin == salePrice` 全部成立；`logs` 719 → 738（+19），样例 `智元机器人-G1 / 调整价格 / 销售单价 3006700.0 → 3036767.00；区间最低价 3006700.0 → 3036767.00（统一上调 1%）`。
> 前端需知：产品列表/表单/购物车读 bootstrap 实时值，**刷新页面即生效**；无需重启服务（未改代码、未构建、未 commit）。回滚方式：用上述备份文件覆盖 `core_holdings.db`。

## 2026-10-27 ｜ 新增：每日数据备份脚本 + cron 定时任务（BACKUP-DAILY-20261027）

**关联任务**：BACKUP-DAILY-20261027。数据只有三处：SQLite 库 + `uploads/` 附件 + `.jwt_secret`，合计约 11.5 MB，采用「每天全量、保留 30 天」策略。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-27 | 新增 | 备份脚本 `backend/scripts/backup.sh`：① `core_holdings.db` 走 SQLite 在线备份 API（服务不停机、不产生半写文件）；② `uploads/` 打 tar.gz（83 个文件 / 10 MB）；③ `.jwt_secret`；④ `manifest.txt`（md5 + 行数 + 恢复步骤） | `backend/scripts/backup.sh` | BACKUP-DAILY-20261027 | 目标 `/backup/core-holdings/<YYYYMMDD-HHMMSS>/`，`KEEP_DAYS=30` 自动清理，`BACKUP_ROOT` / `KEEP_DAYS` 可用环境变量覆盖 |
| 2026-10-27 | 新增 | 校验链（任一失败即回滚清理，非零退出）：`pragma integrity_check`、表集合与源库一致（18 张）、12 张关键表行数逐表比对、**附件引用完整性**（`file_meta.storedName` + `assets.contractFile/featureDoc` + `asset_deliverables.file` 去重后必须在 tar 内）、搬运后 **md5 逐个比对** | 同上 | BACKUP-DAILY-20261027 | 当前实测：DB 引用 67 个附件 0 缺失；uploads 另有 16 个未被引用的孤儿文件（全量带上） |
| 2026-10-27 | 新增 | cron 定时任务（`crontab -l`）：`0 2 * * * /data/core-holdings/backend/scripts/backup.sh >> /var/log/core-holdings-backup.log 2>&1`，每日 02:00 执行 | 系统 crontab（root） | BACKUP-DAILY-20261027 | 日志写**本地** `/var/log/core-holdings-backup.log`（不写 NFS，避免掉线时卡住）；已用 `env -i` 模拟 cron 极简环境验证通过 |

### 踩坑记录（NFS 目标盘）

目标 `/backup` 是 NFS4 挂载（`192.168.180.50:/kubernetes`，`hard`、`local_lock=none`），有三个必须规避的行为：

1. **SQLite 不能直接建库在 NFS 上**：`sqlite3.connect('/backup/.../core_holdings.db')` 直接报 `unable to open database file`（POSIX 锁语义不兼容）。
   → 解法：**先在本地 `/tmp` 工作区生成 + 校验，再整目录 `cp -a` 到 NFS**，搬运后比对 md5。
2. **NFS 会瞬时 `Remote I/O error`**：首次执行时 db/tar 写入看似成功，随后读取即报错（服务端 ping 通、`df` 也正常）。
   → 解法：写入-回读**探测文件** + 全链路 `timeout`（`IO_TIMEOUT=300`）+ 事后 md5 校验；任一步失败即清理半成品并退出非零。
3. **刚写入后 `stat`/`du` 返回 0 或 512 字节**（属性缓存未刷新），日志里的体积会显示成 `1.0K` / `512`。
   → 解法：日志体积取自**本地工作区**字节汇总，不用 NFS 上的 `du`。

### 恢复步骤（务必先停服务）

1. 停掉 uvicorn（8000）
2. `cp /backup/core-holdings/<时间戳>/core_holdings.db  backend/core_holdings.db`
3. `tar -xzf /backup/core-holdings/<时间戳>/uploads.tar.gz -C /data/core-holdings/backend`（还原 `uploads/` 全量）
4. `cp .jwt_secret` 并 `chmod 600`（不恢复则已登录会话全部失效，用户需重新登录）
5. 启动服务，前端刷新（数据来自 `/api/bootstrap`）

> 手工执行：`/data/core-holdings/backend/scripts/backup.sh`（默认目标 `/backup/core-holdings`）；改了别的目录：`BACKUP_ROOT=/xxx ./backup.sh`。
> 已验证：完整跑通 4 次（本地目录 1 次、NFS 2 次、`env -i` 模拟 cron 1 次），均 `EXIT=0` 且四项校验全通过。未构建、未部署、未 commit。

## 2026-10-29 ｜ 金额精度放开到最多 6 位小数（ADR-048，全量页面与销售明细价格）

**关联任务**：ADR-048（用户反馈「购物车下单手动填入金额不支持输入小数点」→ 业务拍板全量放开多位小数）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-29 | 新增 | `docs/adr/ADR-048.md`：金额精度 = 最多 6 位小数（1e-6 元），展示「最少两位、最多六位、尾随 0 截到两位」；部分取代 ADR-008/ADR-022 的「整数元」条款，业务规则（必填/区间/分组/锁定）不变 | `docs/adr/ADR-048.md`、`docs/architecture.md` | ADR-048 | 无 DB 迁移（金额列本就是 Float） |
| 2026-10-29 | 修改 | 后端金额精度统一：新增 `AMOUNT_QUANT = Decimal("0.000001")`，全部金额 `quantize(CENT)` 改为 `quantize(AMOUNT_QUANT)`（行金额/合同金额/项目金额/流水/原价快照/审核改价/交付补录），保证 Σ明细 = 合同金额 | `backend/src/services.py` | ADR-048 | 取消「强制到分」后，3~6 位小数不再被静默舍入；`CENT` 保留为历史常量 |
| 2026-10-29 | 修改 | 校验放宽：`_validate_amount_yuan`（>0 且 ≤6 位小数）、`_check_discount_range`（非负且 ≤6 位小数）、checkout 缺项校验同口径；`_rs_item_fields` 遥感明细单价由「整数元」改为「>0 且 ≤6 位小数」；`_derived_price`/`_fmt_money` 同精度 | `backend/src/services.py` | ADR-048 | 7 位及以上直连接口仍 400（Float 落地失真） |
| 2026-10-29 | 修改 | 前端公共金额函数：`formatMoney`/`formatYuan`/`derivedUnitPrice` 改为「千分位 + 最少两位 / 最多六位 / 尾随 0 截断」（去掉 Intl 的 2 位四舍五入）；新增 `roundAmount`、`amountInputFormatter`/`amountInputParser`、`sanitizeAmountInput`、`isAmountTextValid`、`isAmountPrecisionValid` | `frontend/src/types.ts` | ADR-048 | 30+ 处 `formatMoney` 调用点自动生效 |
| 2026-10-29 | 修改 | 各页面金额/单价输入放开到 6 位小数（inputs 用 formatter/parser，去掉 `:precision="0"/"2"`）：购物车行金额、结算弹窗合计（去 `Math.round`）、销售建单单价与包量金额、审核改价单价/金额（原步进 1000 一并去掉）、产品登记销售单价与参考区间（区间自动同步改 `roundAmount`）、遥感明细单价与区间、交付补录金额；行合计统一 `roundAmount` 规整 | `frontend/src/views/cart/index.vue`、`components/SalesOrderDialog.vue`、`views/sales/projects/create.vue`、`views/sales/projects/review.vue`、`views/sales/outbound/index.vue`、`views/assets/create.vue`、`views/assets/detail.vue`、`components/RsItemPicker.vue` | ADR-048 | 文案「整数元」全量改为「元（最多 6 位小数）」；数量类输入（`:precision="0"`）不受影响 |

> 验证（副本库 `/tmp` 副本 + 服务层直调，不触碰生产库）：`100.123456 / 1234.5 / 0.000001 / 0.5` 加购→改价→结算→审核改价→交付全链路往返一致；`1.1234567 / 0.0000001` 均 400；合同金额、项目 `expectedAmount`、行金额三者相等；`python3 -m py_compile` 与前端 `read_lints` 通过。
> 未构建、未部署、未 commit。

## 2026-10-29 ｜ 参考区间只约束下单下限、审核改价不受区间限制（ADR-049）

**关联任务**：ADR-049（用户反馈「购物车订单输入允许超过最高区间，商务审核填入金额不限制区间范围」）。

| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |
|---|---|---|---|---|---|
| 2026-10-29 | 新增 | `docs/adr/ADR-049.md`：参考区间只约束**下限**；购物车/结算任何角色金额可高于区间上限；审核改价不受区间限制；商务手工建单保留双向校验（部分取代 ADR-037 §3） | `docs/adr/ADR-049.md`、`docs/architecture.md` | ADR-049 | 无数据结构变更 |
| 2026-10-29 | 修改 | 购物车链路 `enforce_max` 统一为 `False`：`_cart_add_inner` 显式传 `False`；`patch_cart_item` / `set_cart_qty` / `checkout` 的 `enforce_max = not viewer` → `False`（`viewer` 参数保留仅兼容签名）；结算透传 `_create_project_core(enforce_max=False)`，避免「购物车放行、结算 400」 | `backend/src/services.py` | ADR-049 | 低于下限仍 400 原文案 |
| 2026-10-29 | 修改 | 审核改价补精度兜底：`items[].price` 增加「≤6 位小数」校验（ADR-048 口径），并明确该入口**不调用**区间校验函数、不回写挂牌价 | `backend/src/services.py` | ADR-048/049 | 审核改价仍只受「>0 + 精度」约束 |

> 验证（副本库）：区间 `[3,036,767, 3,066,834]` 下金额 3,680,200.80（超上限 20%）PATCH/PUT/checkout 全部通过且金额一致；2,429,413.60（低于下限）400；审核改价 9,200,502（3 倍上限）通过、7 位小数 400。`py_compile` + `vue-tsc` 通过，临时脚本已清理。
> 未构建、未 commit；后端 `--reload` 已热加载。
