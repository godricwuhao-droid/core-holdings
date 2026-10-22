# 业务逻辑与架构设计审查报告（2026-10-22）

> **审查性质：只读**。未修改任何代码、未重启服务、未写入数据库；数据库仅以 `mode=ro` 只读连接核对现状。
> **基线**：`docs/architecture.md`（§2 数据流 / §3 核心业务规则 / §4 遥感模型 / §5 权限 / §6 UI 约束 / §9 已知技术债）+ `docs/adr/` 全部 28 条 ADR + `docs/api-contracts.md`。
> **范围**：后端 `services.py`(2886 行)/`routers/api.py`/`models.py`/`schemas.py`/`security.py`/`main.py`/`seed_data.py`；前端 `api/index.ts`/`types.ts`/`constants.ts`/`auth.ts`/`router` + 全部 14 个业务页面 + 5 个共享组件。
> **方法**：5 路并行静态审计（业务规则 / 接口与数据层 / 前端数据层 / 前端页面 / 契约交叉核对）→ 去重 → 对 **P0/P1 全部条目由架构侧直接读码或只读查库复核**。
> **与历史文档关系**：`business-logic-bugs-20261016.md`（18 项）、`business-logic-bugs-20261020.md`（13 项）已修复项**不重复报告**；本次标注了与历史遗留项的对应关系（见 §7）。

---

## 0. 结论摘要

| 结论 | 说明 |
|---|---|
| 核心链路**做得对** | 跨产品/跨合同按 `assetId` 聚合的防超卖校验、三个下单入口汇入同一 `_create_project_core`、购物车 7 个端点的用户隔离、50 个端点权限守卫无遗漏、密码 PBKDF2+盐、JWT 不含 role（改角色即时生效）、结算分组键 `(assetId, customer)` 前后端一致、审核改价不回写挂牌价 |
| 确证缺陷 | **29 条**（P0 1 条 / P1 10 条 / P2 18 条），其中 **1 条正在持续造成数据丢失**、**3 条可导致金额错误落库**、**2 条越权读 + 1 条账号信息暴露**。原 BUG-02 判"致命"，经只读查库复核后**降级为中**（文件仅来自产品附件，不存在跨客户合同附件） |
| 低危清理项 | **17 条**（P3，逐条 1–10 行改动），另含 1 条 ADR 既定设计的残余风险登记 |
| 架构级设计问题 | **7 条**（见 §5，每条含选项/trade-off/可逆性，需拍板后写 ADR） |
| 最紧急 | `BUG-01`：每次进程重启都会**物理清空 `asset_deliverables` 全表**（已用只读查库实证：表 0 行，但审计日志有 13 条交付物操作记录） |

**级别定义**

- **P0 致命**：正在造成数据丢失或可被直接利用的越权/接管
- **P1 高**：金额/数量错误落库、状态机失效、可用性系统性受损
- **P2 中**：特定状态组合下的数据不一致、越权读、交互误导
- **P3 低**：口径/文案/健壮性/契约噪声

---

## 1. 问题总表

> 「复核」列：✅ = 架构侧直接读码或只读查库确认；△ = 子审计静态通读结论，尚未逐行复核（修复前建议再确认一次）。

### P0 致命

| 编号 | 类别 | 问题 | 证据 | 复核 |
|---|---|---|---|---|
| BUG-01 | 数据丢失 | 启动迁移**每次都清空** `asset_deliverables` 全表 | `backend/main.py:215-222` | ✅ |

### P1 高

| 编号 | 类别 | 问题 | 证据 | 复核 |
|---|---|---|---|---|
| BUG-03 | 状态机 | 项目级「批量交付」绕过 ADR-019「先录签订时间」守卫 | `services.py:1720-1726` vs `1326` | ✅ |
| BUG-04 | 回滚 | 撤销部分交付后终止合同，剩余已交付明细**不回滚**（销量/交付单残留且不可再修） | `services.py:1771-1789`、`2045-2057` | ✅ |
| BUG-05 | 数量 | 遥感明细 `repeatSale=false` + 父产品 `repeatSale=true` → 可售校验被短路，同一明细可卖多次 | `services.py:323`、`1089-1096` | ✅ |
| BUG-06 | 金额 | 包量定价（卫星 Token）行的**折扣快捷入口回填出"权威合同金额"** | `cart/index.vue:271,737-748`；`services.py:2165-2172` | ✅ |
| BUG-07 | 金额 | 建单页切换产品后沿用上一产品的单价/金额，后端 unit 行**直接采信前端 price** | `projects/create.vue:191-209`；`services.py:313` | ✅ |
| BUG-08 | 契约 | 遗留下单端点（`POST /sales/order`、`POST /projects/{id}/resubmit`）viewer 可达且**绕过**参考区间/服务期限校验 | `services.py:306-313, 2582-2590`；`routers/api.py:639,477` | △ |
| BUG-09 | 可用性 | 多处写操作缺 `catch`，后端 400/422 **完全静默**（无 toast） | `projects/create.vue:580-613`；`assets/create.vue:205-218`；`assets/detail.vue:322,338`；`sales/outbound/index.vue:193` | ✅（create.vue 已复核） |
| BUG-10 | 并发 | 结算 / 交付 / 审核无幂等键、无「条件更新」，典型 TOCTOU 可重复锁量或重复交付 | `services.py:1093-1130, 1742-1743, 2637-2743` | ✅ |
| BUG-11 | 安全 | `JWT_SECRET` 硬编码兜底；无 token 版本/吊销，改密后旧 token 仍可用 7 天；无登出端点 | `security.py:27-29,74-84`；`routers/api.py:157-159` | △ |
| BUG-12 | 安全 | 登录可枚举账号；锁定维度仅 username（可喷洒绕过、可定向锁死管理员 15 分钟） | `routers/api.py:55-63`；`security.py:191-208` | △ |

### P2 中

| 编号 | 类别 | 问题 | 证据 | 复核 |
|---|---|---|---|---|
| BUG-02 | 越权读（**范围已修正，原判致命→中**） | 文件下载无对象级 ACL，bootstrap 向 viewer 下发**全量**文件清单（含未被任何产品引用的孤儿文件与 `uploadedBy`）。注：`projects/contracts` 表**无附件字段**，文件只来自 `assets.contractFile/featureDoc` 与 `asset_deliverables.file`，产品本身对所有角色可见 → 不构成"跨客户合同泄露" | `services.py:2867,2885`；`routers/api.py:782-790`；库查：`file_meta` 49 条 vs 24 个产品引用 | ✅ |
| BUG-13 | 越权读 | 合同类操作日志（target=contract）与 `GET /assets/{id}/flows` 对 viewer 不过滤 | `services.py:2833-2846`；`routers/api.py:329-345` | ✅（`_keep_log` 只处理 project/outbound） |
| BUG-14 | 数据 | 被 delivered 合同引用的产品可删除；此后撤销交付「静默成功但零回滚」，合同永久卡 delivered | `services.py:532-541, 2005-2008` | △ |
| BUG-15 | 流程 | 撤销时**全部明细回填失败**仍置 `cartRefilled=True` → 明细丢失且原单不可删不可重提 | `services.py:813-828, 905` | ✅ |
| BUG-16 | 数据 | 手工建单不校验 `assetId` 是否存在 → 幽灵明细可被确认并「交付」（无交付单/无销量/无数量变动） | `services.py:190-195, 1068-1071, 1188-1204` | △ |
| BUG-17 | 状态机 | `delivered + terminated` 混合被派生为「进行中」，且项目级接口对该单永久 400 | `services.py:1265-1270` | ✅ |
| BUG-18 | 金额 | `contractAmount` 采信客户端值，不与 Σ 明细校验（pending 期报表/审批依据失真） | `services.py:997-1002` | ✅ |
| BUG-19 | 数据模型 | `contracts`/`project_items` 无唯一约束，可构造重复销售记录。**口径修正（实施时）**：`(projectId, customer)` 不能作为唯一键——ADR-016 规定同项目同客户多产品 = 多条销售记录（现库即有 3 条），正确语义由 `UNIQUE(contractId, assetId, COALESCE(itemId,0))` 覆盖 | `models.py:121-131`；`services.py:997-1003` | ✅（实施时口径已修正） |
| BUG-20 | 契约 | 3 个端点用裸 `dict` 收参（`PUT /cart/{id}`、`PATCH` 交付撤销、交付物更新）→ 非法入参 500 或脏值落库 | `routers/api.py:575-586, 550, 709` | △ |
| BUG-21 | 前端 | `delivering`（交付中）状态漏算：列表抽屉批量交付/终止按钮失效、详情页编辑按钮误禁 | `projects/index.vue:261-268`；`projects/detail.vue:372-374` | ✅（index.vue 已复核） |
| BUG-22 | 前端 | 购物车/建单的数量上限只按「本行」校验，后端按「同产品合计」→ 越界只能靠后端 400 回滚 | `cart/index.vue:395-403`；`projects/create.vue:436-440` | △ |
| BUG-23 | 前端 | 审核页「清空服务期限」无效（后端把 null 当"未传"），前端仍提示成功 | `review.vue:220-233`；`services.py:1579-1584` | △ |
| BUG-24 | 前端 | `refresh(true)` 绕过防重入且无请求序号 → 旧快照可覆盖新快照；`finally` 提前释放锁 | `api/index.ts:156-181,190-196` | ✅ |
| BUG-25 | 前端 | 折扣直接改写 db 镜像不发请求（离页即失同步）；步进器无 in-flight 保护，响应乱序则镜像失真 | `cart/index.vue:109-119,417-437`；`api/index.ts:207-218` | △ |
| BUG-26 | 前端 | 「保存草稿」跳过合同校验 → 生成 0 明细 0 元的 pending 空单（审核必 400，且 pending 不可编辑） | `projects/create.vue:575-591`；`services.py:1004-1006` | △ |
| BUG-27 | 前端 | 改数量（无折扣行）后端会**静默清空**已填金额，前端不提示不重算 | `services.py:2501-2505`；`cart/index.vue:424-437` | △ |
| BUG-28 | 数据模型 | 日期全用字符串且几乎无格式校验（仅签订/预计交付校验），`YYYY-M-D` 混入后排序/到期判断失真 | `schemas.py:61-62,311-312,361`；`services.py:1367,1387` | △ |
| BUG-29 | 数据模型 | 金额列全为 `Float`（SQLite REAL），Decimal 仅在业务边界转换（已知债，见 §9 备注） | `models.py:27-36`；`services.py:1977` | △ |

### P3 低（批量清单，逐条改动量 1–10 行）

| 编号 | 问题 | 证据 |
|---|---|---|
| BUG-30 | `bootstrap` 全量快照：每次写后全表加载 + viewer 过滤靠「detail 文本正则/项目名匹配」判定可见性，文案一改即误放/漏放 | `services.py:2788-2800, 2833-2846` |
| BUG-31 | 上传先整体读入内存再判大小（20MB×N 并发即内存峰值）、后端白名单仍含 `.doc`（ADR-024 前端已禁）、响应无 `nosniff` | `routers/api.py:37-38,736-742` |
| BUG-32 | `GET /users/options` 向 viewer 暴露全部商务/管理员账号清单（同类 `/users/options/all` 已收敛，此端点漏改） | `routers/api.py:82-91` |
| BUG-33 | 错误语义不统一：权限类失败有 400（应 403）、成功体有 `{"ok":true}`/DTO/`null` 三种、`PUT` 实为部分更新 | `services.py:1312-1313,1483`；`routers/api.py:617-619` |
| BUG-34 | seed 数据自相矛盾：**「颗」在当前库 0 条**（全部为「个」），但 `seed_data.py` 的 CH-SAT-001/002/003 仍写 `unit="颗"`——空库重建即复现；另 `repeatSale=true` 却 `soldCount=0`、`soldCount=1` 却未扣 `shippedQty` | `seed_data.py:37-51`；库查：`unit like '%颗%'` = 0 |
| BUG-35 | `constants.ts` 与后端 `category_units` 文案漂移（遥感单位/note 仍是 ADR-010 口径），且 `bootstrap.categoryUnits` 前端从未消费 | `constants.ts:11-21`；`seed_data.py:166-176` |
| BUG-36 | 交付物详情弹窗持有刷新前的旧对象（标记就绪后弹窗仍显示旧状态）；上传中可提交、替换/移除不清理旧文件 | `assets/detail.vue:331-340`；`assets/create.vue:161-176,416` |
| BUG-37 | 交付记录数量列用 `formatWan`，Token 产品未走 `formatTokens`（显示 300,000,000 而非「3 亿」） | `outbound/index.vue:144,316` |
| BUG-38 | 撤销单删除入口未按 ADR-028 禁用（点完才 403，二次确认文案还承诺"释放锁定/撤销交付"） | `projects/index.vue:299-318,508-520` |
| BUG-39 | 详情页 tooltip 包裹全部动作按钮 → hover「重新提交/撤销」也弹「已完成/已终止不可编辑」 | `projects/detail.vue:332-394` |
| BUG-40 | 详情分页页签 `loaded` 一次性标记（同页写操作后「操作记录」不刷新）；流水类型筛选只作用于当前页但 total 为全量 | `assets/detail.vue:238-247,454-471` |
| BUG-41 | `fileUrl` 把 7 天 JWT 拼进 URL（进入 access log/历史/Referer）——**ADR 既定设计**，此处仅登记残余风险，勿擅自改 | `api/index.ts:447-454`；`architecture.md §5` |
| BUG-42 | `delete_asset` 静默删除**所有用户**购物车中该产品行（无提示无留痕），与 `delete_rs_item`「有引用禁删」口径不对称 | `services.py:559-561` |
| BUG-43 | `PUT /projects` 可改 `rep` 且不做 `_normalize_rep`（账号/姓名混存复发），而 `rep` 又是存量单 viewer 可见性依据 | `services.py:130-134,1672-1674` |
| BUG-44 | 金额输入 `el-input-number` 未加 `:controls="false"`（违反 §6 硬约束） | `assets/create.vue:337`；`projects/create.vue:944-952` |
| BUG-45 | 手动交付 `POST /outbounds` 未做遥感明细感知（§9.2 已知，前端无入口，勿重复报） | `architecture.md §9.2` |
| BUG-46 | 抽屉「已售次数」总数由前端遍历 `db.contracts` 派生，viewer 口径与行内后端 `soldCount` 不一致 | `assets/list.vue:303-317` vs `routers/api.py:310-320` |

---

## 2. P0 与重点问题详述（建议立即止血）

### BUG-01｜每次进程重启都会清空 `asset_deliverables` 全表（数据丢失）

**现象**：`main.py` 在 import 期执行 `_ensure_migration()`，其中第 17 条迁移把「一次性清空存量交付物」实现成了「表非空就清空」。

```python
# backend/main.py:215-222
# 17) ADR-024 存量交付物实例一次性清空（模板体系下线后各产品从零手动添加）；
# 幂等：空表跳过。无其他表引用 asset_deliverables，直接清。
if "asset_deliverables" in table_names:
    with engine.begin() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM asset_deliverables")).scalar()
        if n:
            conn.execute(text("DELETE FROM asset_deliverables"))
```

**实证（只读查库）**：

```text
asset_deliverables   → 0 行
audit_logs（action like '%交付物%'） → 13 条
assets               → 28 行（产品仍在，排除级联删除）
```

即：历史上确实录入过交付物（审计留痕 13 条），当前表已空。

**触发路径**：任何一次进程重启（`uvicorn --reload` 因改代码自动重启、部署、崩溃恢复）→ 全表 `DELETE`，无日志、无审计、不可恢复（附件仍在 `uploads/`，引用关系丢失）。

**影响**：ADR-024 之后**手工维护的所有交付物实例每次重启归零**。这是当前项目唯一「持续发生」的数据丢失，优先级高于其它所有问题。

**修复方向**：迁移必须是**带标记的一次性动作**（如 `_migrations(name)` 表记录 `ADR024_cleanup_done`），且启动期禁止对业务表做无幂等标识的 `DELETE`；本次先移除该语句并补一条「不再执行」的标记写入。

**是否已知债**：否。ADR-024 只授权"上线时一次性清空"，代码把"一次性"写成了"每次"。

---

### BUG-02｜文件下载无对象级 ACL + bootstrap 全量下发文件名（**复核后降级：致命 → 中**）

> **修正说明**：子审计初判为"可下载任意客户的合同扫描件"。架构侧复核 `models.py` + 实库表结构后确认：**`projects`/`contracts`/`outbounds`/`base_records` 均无附件字段**，文件只来自 `assets.contractFile`、`assets.featureDoc`、`asset_deliverables.file`；而产品目录对所有角色可见（viewer 也能在抽屉/详情看到这些附件）。因此**不存在"跨客户合同泄露"**，实际越权面为：**孤儿文件**（上传后未挂到任何产品/被替换下来的旧文件）+ `uploadedBy`/原始文件名清单枚举。

**现象**：`GET /api/files/{filename}` 只要求"任意登录用户"，不校验文件归属；`bootstrap.files` 全量返回（`file_meta` 49 条，产品实际引用 24 个文件）。

```python
# services.py:2866-2867, 2885
files = db.execute(select(models.FileMeta).order_by(models.FileMeta.storedName.asc())).scalars().all()
...
"files": [schemas.FileMetaOut.model_validate(f).model_dump() for f in files],
```

**触发路径**：viewer 登录 → `GET /api/bootstrap` 拿到全部 `storedName` + 原始文件名 + `uploadedBy` → `GET /api/files/{storedName}?token=...` 下载**未被任何产品引用**的文件（含被替换前的旧版产品清单/合同附件）。

**影响**：历史版本文件、误传文件、内部草稿一旦上传过且未被清理，任何登录用户都可枚举下载；`uploadedBy` 暴露上传人与内部文件名。路径穿越已被 `os.path.basename` 阻断（无问题）。

**修复方向**：可见性 = 被可见产品引用（`assets.contractFile/featureDoc`、`asset_deliverables.file`）**或** `uploadedBy == 当前用户` **或** admin；bootstrap 与 download 共用同一判定函数；孤儿文件由 admin 清理。

**是否已知债**：否。属 20261020 那轮「viewer bootstrap 过滤」的收敛遗漏（同批只修了 outbounds/flows/logs）。

---

## 3. P1 详述

### BUG-03｜项目级批量交付绕过「先录签订时间」守卫

```python
# 合同级入口有守卫（services.py:1326-1327）
if status == "delivered" and (c.status != "delivering" or not c.signedDate):
    raise HTTPException(400, "合同尚未录入签订时间，不可交付")

# 但项目级批量直接调 core，绕过了上面这段（services.py:1720-1726）
target_states = ("pending",) if p.status == "pending" else ("active", "delivering")
for c in targets:
    _change_contract_status_core(db, c, status, reason, operator=operator)
```

`_change_contract_status_core` 的 delivered 分支（`1744-1764`）只校验 `pending_asset` 明细，**不校验 `signedDate`/`delivering`**。

**触发路径**：购物车结算 → 商务确认（合同 `active`，`signedDate` 为空）→ 项目列表抽屉「确认交付」→ 直接 `delivered`，跳过 ADR-019 全流程。

**影响**：无签订时间的合同产生交付单与销售额，状态机失真；同一事实存在两套校验口径（合同级严、项目级松）。

**修复方向**：把"可交付前置条件"下沉到 `_change_contract_status_core`，所有交付入口共用一道守卫；项目级批量在遇到不合规合同时应**整体 400 并列出**，而不是逐条静默处理。

---

### BUG-04｜撤销部分交付后终止合同：剩余已交付明细不回滚

`_change_contract_status_core` 的 terminated 分支按**合同当前状态**二选一（`1771-1789`）：

- `from_status ∈ {active, pending, delivering}` → 走"释放锁定"；
- 否则（delivered）→ 走"撤销该合同全部 done 交付"。

而撤销单条交付后合同被置回 `delivering`（`2045-2057`），其余明细仍是 `shipped`。

**触发路径**：合同 2 条明细 A、B → 全部交付（`soldAmount` 累加，生成 CK 单）→ 撤销 A 的交付（合同回 `delivering`，A 回 `locked`）→ `PATCH /contracts/{id}/status=terminated` → 命中"释放锁定"分支 → **B 的 `shippedQty`/`soldAmount`/交付单全部保留**，且 `delete_project` 也不会再回滚（`terminated` 两个分支都不命中）。

**影响**：作废合同仍计入平台销量与已交付数量，数据永久残留、无修出口。

**修复方向**：终止时按**明细实际状态**分别处理（`shipped` → 走交付撤销；`locked/confirmed` → 走释放），而不是按合同状态二选一。

---

### BUG-05｜遥感明细「不可重复售卖」被父产品 `repeatSale=true` 短路

```python
# 数量校验按父产品（services.py:323）
if a.repeatSale:
    return                      # 父产品 repeatSale=true → 直接放行
# 但 demand 聚合时把 repeatSale=false 的明细行计入了需求（1089-1096）
# 加锁时又按明细的真实 repeatSale 处理（338-340）
```

**触发路径**：遥感父产品（容器，`repeatSale=true`）下建一条 `rs_items.repeatSale=false` 的明细 → 两个账号各自加购同一明细 → 两次都通过校验并各锁 1 → `lockedQty=2 > quantity=1`。

**影响**：同一"不可重复售卖"的明细被卖多次；`_avail()` 夹零后该产品后续正常订单全部被阻塞。

**修复方向**：数量上限判定以「行的有效 repeatSale（`_item_repeat`）」为唯一依据，父产品的 `repeatSale` 不参与明细行判定（ADR-011 本意即如此，是实现漏项）。

---

### BUG-06｜包量定价行的折扣快捷入口伪造"权威合同金额"

```ts
// cart/index.vue:268-271（折扣失焦）
row.cart.discountRate = rate / 10
row.cart.amount = Math.round(row.price * row.cart.qty * rate)  // price = asset.salePrice
```

折扣输入框对 **amount 模式行同样渲染**（`737-748`，仅 `rsItem` 行排除），而后端对 amount 行只校验"整数元 > 0"（`services.py:2165-2172`）——即前端算出来的值**原样成为权威合同金额**并写入 `project_items.amount` / `contracts.contractAmount` / `soldAmount`。

**触发路径**：加购「卫星 Token」→ 折扣填 9 折 → 失焦 → 金额被回填为 `salePrice × qty × 0.9` → 结算。（`salePrice` 在 ADR-008 下只是"参考展示值"，不参与计价。）

**影响**：与 ADR-008「合同金额为人工权威输入、`salePrice` 仅参考」直接冲突；生成的合同金额可能偏离真实成交额一个数量级，且审核页会把它显示为"原金额"，掩盖真实报价。

**修复方向**：amount 模式行不渲染折扣输入/摘要/placeholder，折扣仅对 unit 行生效；金额必须人工录入。

---

### BUG-07｜建单页切换产品后沿用上一产品的单价/金额

```ts
// projects/create.vue:191-209
if (a && !isAmountMode(a) && !it.price && a.salePrice) it.price = a.salePrice  // 仅 price 为空才预填
calcItemAmount(c, it)                                                          // 用旧 price 重算 amount
```

amount 模式分支（`163-167`）只反算 `price`，**不重置 `it.amount`**。

**触发**：选产品 A（单价 1000）→ 数量 2（金额 2000）→ 改选产品 B（单价 5000）→ 提交。后端 unit 行 `_item_pricing` **直接采信前端 price**（`services.py:313`，无区间校验）→ 按 A 的 1000/2000 落库。

**影响**：合同明细单价/金额错误落库且无提示；若改选的是 Token 产品，A 的 2000 元会被当作 Token 的权威合同金额（整数校验照样通过）。

**修复方向**：产品变更时同步重置 `price/amount`（amount 行金额置空），仅对"用户未手改过"的字段做预填。

---

### BUG-08｜4 个下单入口 = 3 套校验口径

| 入口 | 权限 | 参考区间校验 | 服务期限必填 |
|---|---|---|---|
| `POST /cart/checkout` | viewer | ✅ (`_check_discount_range`) | ✅ (ADR-022) |
| `POST /projects` | editor | ❌（`_item_pricing` 直接 `price×qty`） | 不校验 |
| `POST /sales/order` | **viewer** | 部分（金额传了才校验） | ❌ |
| `POST /projects/{id}/resubmit` | **viewer** | ❌ | 由请求体自带 |

ADR-020/027 只把后两者标为"deprecated 保留兼容"，**没有授权其免校验**。风险：审核确认（`review_project`）也不校验区间，等于"绕过购物车 → 进审核队列 → 确认即生效"。

**修复方向**：把区间/必填/存在性校验下沉到 `_create_project_core` + `_item_pricing`（单一出口），deprecated 端点改为 `410 Gone`。

---

### BUG-09｜写操作缺 `catch`，400/422 静默

`try { ... } finally { submitting = false }` 模式在以下位置反复出现，**没有 `catch`**：

- `projects/create.vue:580-613`（保存草稿 / 提交）
- `assets/create.vue:205-218`（产品新增/编辑）
- `assets/detail.vue:322,338`（交付物增删/状态）
- `sales/outbound/index.vue:193`（撤销交付）

403 会被 axios 拦截器统一 toast（ADR-014），但**400/422 才是业务校验的主战场**（库存不足、区间越界、min>max、服务期限非法…）。用户看到的现象是"按钮转一圈，什么都没发生"，进而重复点击（放大 BUG-07/BUG-10）。

**修复方向**：所有写操作统一 `catch (e) { showError(e, '…') }`；在 `api/index.ts` 暴露 `showError` 并纳入 code review checklist。

---

### BUG-10｜关键写路径无幂等键 / 无并发护栏

- `checkout`（`2637-2743`）：读购物车 → 校验 → 建单锁量 → 清购物车，单次 commit，**无请求幂等键**；
- `_change_contract_status_core`（`1742-1743`）：`if status == from_status: return` 基于会话内存状态，非条件更新；
- `apply_item_lock`（`340`）：`a.lockedQty = max(0, a.lockedQty ± qty)` 是典型读-改-写；
- `database.py`：无 `BEGIN IMMEDIATE`、无重试、无版本号。

**触发**：并发双击「结算」/「确认交付」→ 两个会话都读到 `locked=0`/`status=delivering` → 各自加锁、各自生成交付单 → 后写覆盖前写（lost update）。

**影响**：重复锁量、重复交付、`soldAmount` 多计；需人工终止/撤销修正。

**修复方向**：结算用请求级幂等键（前端生成 `requestId` + 后端唯一表）；状态变更改「带条件 UPDATE 并判影响行数」；数量改原子 `UPDATE ... WHERE quantity-locked-shipped >= :q`。

---

### BUG-11｜JWT 密钥兜底 + 凭据不可吊销

```python
JWT_SECRET = os.getenv("JWT_SECRET", "core-holdings-local-dev-secret-change-in-production")
```

未设环境变量时，任何拿到源码的人可离线签发 `{"sub":"1"}`（admin 是 `users.id=1`）直通全站。另外 payload 无 `jti`/`tokenVersion`，改密后旧 token 仍有效 7 天，且无 `POST /auth/logout`（前端登出仅清 localStorage）。

**修复方向**：无 `JWT_SECRET` 时 fail-fast 或生成随机密钥落盘并告警；users 增 `tokenVersion` 写入 JWT 并在校验时比对；补登出端点。

---

### BUG-12｜登录枚举与锁定 DoS

- 禁用账号返回「账号已被禁用」，错误口令返回「用户名或密码错误」→ 可判定账号存在；
- `user is None` 时短路不做 PBKDF2 → 响应时间差可单独判定用户名存在；
- 失败计数只有 username 维度：换用户名喷洒永不触发；连续 10 次错密码可把 `admin` 锁死 15 分钟（无验证码、无解锁入口、无 IP 维度）；
- `_login_fails` 为进程内无界 dict。

**修复方向**：统一失败文案 + 恒定时间（不存在用户也跑一次 PBKDF2）；增加 IP 维度 + 指数退避；锁定只对来源生效，不做全局封号。

---

## 4. P2 要点（按主题归并）

### 4.1 越权读（同源问题，建议一次收口）

- **BUG-13**：`_keep_log` 只处理 `target ∈ {project, outbound}`，`target == "contract"` 一律 `return True` → viewer 在 bootstrap.logs 里能看到其他客户的合同编号/客户名/签订时间；`GET /assets/{id}/flows` 甚至完全不过滤（谁都能拿到任意合同的 `HT-xxxx` + 数量 + 金额）。
- 与 BUG-02 的 files 属同一批"可见性判定分散"问题：**bootstrap 一份口径、分页端点另一份口径、文件又一份口径**。

**统一方向**：抽一个 `visible_*()` 判定模块，bootstrap 与分页端点共用；判定依据用**结构化外键**（`projectId`/`contractId`），不用 detail 文本正则或项目名。

### 4.2 回滚与流程漏洞

- **BUG-14**：`delete_asset` 的引用校验只拦 `active/pending/delivering`，被 delivered 合同引用的产品可删；此后撤销交付因 `asset` 为 None 跳过整段回退，仅写"已撤销"日志并返回 200 → 合同永久卡 delivered。**方向**：缺产品即 400，交付撤销不允许"静默成功"。
- **BUG-15**：`withdraw` 单行失败降级是 ADR-026 授权的，但**全部失败仍置 `cartRefilled=True`** 未授权 → 订单 terminated、购物车无行、原单不可删（ADR-028）、重提幂等直接返回空。**方向**：`skipped > 0` 时不置标记，UI 列出跳过原因并允许重试。
- **BUG-16**：`item_status_of_input` 只按"有没有 assetId"判定 locked，不查库；容器拦截在 `a is None` 时直接放过；交付时 `if a:` 才累计、`it.status="shipped"` 无条件 → 可造出"已完成但零交付单、零销量"的幽灵单。**方向**：非空 `assetId` 强制存在性校验。

### 4.3 金额与数量口径

- **BUG-18**：`contractAmount` 传了就覆盖（`1001`），不校验 = Σ明细 → pending 期金额与明细合计矛盾，只有走到 review confirm 才被重算。
- **BUG-22 / BUG-27**：前端数量校验按单行、后端按合计；改数量时后端静默清 `amount`（`2501-2505`）而前端只在有折扣时重算 → "改个数量，金额没了"。
- **BUG-29**：金额列 Float（已知债）；`amount/qty` 派生单价 6 位小数 + 反复读改写会累积末位误差。

### 4.4 状态机与前端一致性

- **BUG-17**：`{delivered, terminated}` 混合 → `active`，项目级接口永久 400（无进行中合同却显示"进行中"）。
- **BUG-21**：ADR-019 引入 `delivering` 后前端两处未跟进（列表抽屉的 `dActiveCount` 只数 `active`；详情页编辑按钮把 `delivering` 一起禁了，而列表页/后端允许）。
- **BUG-24/25**：`refresh` 并发语义 + 折扣镜像写 + 步进器无互斥 → CART-PERF 用"本地打补丁替代全量刷新"换性能，却丢掉了"刷新自动收敛"的兜底。

### 4.5 数据模型与接口契约

- **BUG-19**：ADR-016 的"一资产一客户一记录"只在 checkout 实现，**DB 层无唯一约束**；手工建单/重提可传两条同客户同产品记录。
- **BUG-20**：3 个裸 `dict` 端点（`PUT /cart/{id}` 最典型）→ `{"qty":"abc"}` 直接 500。
- **BUG-28**：日期字符串无校验（`"2026/3/5"`、`"下周三"` 都能入库），字符串比较式排序/到期判断随之失真。
- **BUG-33**：权限失败混用 400/403（`services.py:1312`、`1483`），与 `api-contracts.md §1`「越权一律 403」冲突。

---

## 5. 架构层设计问题（不是单点 bug，需要 ADR 决策）

> 以下每条都给出选项与 trade-off，请拍板后我再写正式 ADR；**在拍板前不建议动代码**。

### DSGN-1｜下单校验分散在 4 个入口，缺少唯一权威出口 → **已决策：ADR-029（2026-10-22 实施）**

- 现象：checkout / projects / sales/order / resubmit 各有一套校验组合（区间、服务期限、存在性、折扣率），已产生 BUG-07/08/18。
- 选项 A：**收口到 `_create_project_core` + `_item_pricing` 单一校验链**，deprecated 端点返回 410。
  - 得到：一条规则解释全部下单；新增入口零成本继承校验。放弃：旧脚本/旧前端若还调 `/sales/order` 会直接失败（可先打日志观察一周）。
  - **可逆性：高**（薄适配层即可恢复）。
- 选项 B：保留 4 入口，各自补校验。
  - 得到：零兼容风险。放弃：4 份逻辑长期漂移（已经在漂）。

### DSGN-2｜可见性判定基于「detail 文本正则 / 项目名」，而非结构化归属 → **已决策：ADR-030（2026-10-22 实施）**

- 现象：BUG-02/13/30 同一个根因；文案一改、项目重名即误放/漏放。
- 选项 A：建 `visibility` 判定模块 + 文件归属表（`file_owner(kind, refId)`），bootstrap 与分页端点共用。
  - 得到：可测试、可解释的 ACL；新增资源只需登记归属。放弃：一次性 schema 变更 + 历史文件回填。
  - **可逆性：中**（加表可回退，但数据回填成本不可逆）。
- 选项 B：维持现状，逐处打补丁。
  - 得到：零成本。放弃：下一个新资源（如导出报表）必然再漏一次。

### DSGN-3｜`bootstrap` 全量快照承担了「数据总线 + 权限边界 + 性能边界」三重角色 → **未动（待独立 ADR：快照瘦身/资源拆分，独立排期）**

- 现象：每次写后全表加载、Python 侧过滤、前端派生（BUG-24/30/46）。
- 选项 A：**快照瘦身**——bootstrap 只保留"必备小表"（assets/categoryUnits/cart/users），projects/contracts/flows/logs/deliverables 改分页端点（PAGE-20261021 已有先例）。
  - 得到：写后刷新成本与数据量解耦；权限收口到各自端点。放弃：前端需要从"一个 db 镜像"改为"多资源 store"，页面改动面较大。
  - **可逆性：中**。
- 选项 B：保留全量，但加 `ETag/updatedAt` 增量与请求序号。
  - 得到：改动小。放弃：数据量到 10 万级仍会痛；权限过滤逻辑仍在前端快照上做。

### DSGN-4｜启动期迁移承担业务数据清理（BUG-01 的制度性根因） → **已决策：ADR-031（2026-10-22 实施）**

- 选项 A：引入 `schema_migrations(name, appliedAt)`，所有"一次性"动作必须写标记，启动期只做结构迁移（`CREATE/ALTER`），**禁止 DELETE 业务行**；数据清理改为显式脚本 + 人工执行。
  - 得到：重启安全；迁移可审计。放弃：多一张表与一点样板代码。
  - **可逆性：高**。

### DSGN-5｜并发模型未定义（SQLite + 单进程假设未落到文档/代码） → **部分决策：ADR-033（关键写路径幂等/条件更新，已实施）；SQLite→PG 迁移待独立 ADR**

- 现象：BUG-10 的 TOCTOU；`uvicorn --reload` 下多 worker 时风险更高。
- 选项 A：短期在本机语义内解决——请求幂等键 + 条件 UPDATE（`WHERE status=:old` / `WHERE avail>=:q`）+ 关键路径审计告警。
- 选项 B：迁 PostgreSQL，用行锁/事务隔离解决。
  - 得到：根治。放弃：部署复杂度上升（当前是本地 SQLite 单文件交付）。
  - **可逆性：低**（迁移一旦发生难回退）。
- 建议：**先 A**（本迭代），把 B 写成"数据量/并发阈值触发条件"的 ADR，而不是现在迁。

### DSGN-6｜状态机规则散落在服务函数 + 派生表不完整 → **已决策：ADR-032（2026-10-22 实施）**

- 现象：BUG-03/04/17 都源于"守卫写在某个入口而不是状态机本身"、"派生规则表漏一个组合"。
- 选项 A：把守卫下沉到 `_change_contract_status_core`（唯一变更点），派生函数补全组合表并单测覆盖（`{delivered,terminated}` 等）。
  - 得到：一个入口一套规则，可枚举测试。放弃：core 变重，需要区分"合同级批量"与"项目级批量"的语义差异（列出违规项而不是静默跳过）。
  - **可逆性：高**。

### DSGN-7｜金额端到端 Decimal（已知债，需排期而非"顺手改"） → **未动（待独立 ADR + 数据迁移窗口，见 BUG-29）**

- 现象：BUG-29；`Numeric(18,2)` 与 float 混用会在对账时暴露分位差。
- 影响面：涉及 7 张表 + 全部序列化 + 前端 `formatMoney`。**建议独立 ADR + 一次性迁移窗口**，不要混在业务修复里。

---

## 6. 已核查「确认没问题」的点（避免下一轮重复排查）

1. **端点守卫完整性**：50 个端点除 `/health`、`/auth/login` 外全部挂了 `get_current_user/require_order/require_editor/require_admin`，未发现"忘挂守卫"的写接口。
2. **密码存储**：PBKDF2-SHA256/100k + 16B 随机盐 + `compare_digest`，响应体统一走白名单（bootstrap 不含 `passwordHash`）。
3. **JWT 算法降级**：先校验 HS256 签名再读 header，`alg:none` 无效。
4. **路径穿越**：`_resolve_upload` 用 `os.path.basename` + `isfile` 双重约束，`..%2F` 归一后 404。
5. **防超卖聚合**：`_create_project_core` 先按 `assetId` 聚合 `demand` 再逐条校验（`1084-1096`），跨合同多行确实生效。
6. **购物车隔离**：7 个端点 `userId == user.id` 逐处核对通过；结算只清本人。
7. **结算分组键**：前端 `assetId::customer` 与后端 `(assetId, customer)` 一致（ADR-016）。
8. **审核改价不回写挂牌价**：后端回写逻辑已删，前端仅文案声明。
9. **viewer 前端入口收口**：侧边栏 / 路由守卫 / 列表详情按钮与 ADR-028 一致；手改 URL 只能拿到后端 403。
10. **无前端局部 push**：全仓无 `db.*.push/splice`，写操作一律 `afterWrite()`；表单弹窗均在 `watch(modelValue)` 打开时重置，未发现串数据。
11. **会话生命周期**：`get_db` `finally: close()`；业务服务"单事务 + 末尾 commit"；`record_audit` 失败不污染业务。

---

## 7. 与历史排查文档的对应关系

| 历史项 | 现状 |
|---|---|
| 20261020 #1（前端 viewer 白名单拦截写操作） | ✅ 已修复（白名单已移除，改后端守卫） |
| 20261020 #2（补录交付错误扣 `lockedQty`） | ✅ 已修复（改为只 `shippedQty +=`） |
| 20261020 #3（结算按 assetId 合并客户） | ✅ 已修复（ADR-016 分组键） |
| 20261020 #4（Token 三套量纲） | ✅ 已修复（ADR-017/025） |
| 20261020 #5（经办人写成生态人员） | ✅ 已修复 |
| 20261020 #6（viewer bootstrap 全量 outbounds/flows/logs） | ⚠️ **部分修复**：projects/contracts/outbounds/flows/logs 已过滤，但 **files 仍全量**（BUG-02）、**contract 日志仍放行**（BUG-13）、`/assets/{id}/flows` 端口径不一致（BUG-13） |
| 20261020 #7（撤销交付取错明细行） | ⚠️ **未确认修复**：本次未复现，但 `Outbound` 仍无 `itemId`（建议随 BUG-14 一并处理） |
| 20261020 #8（pricingMode 不随类型重算） | ✅ 已修复（`update_asset:491-492` 已重算并留痕） |
| 20261020 #9（补录交付缺归属校验） | ⚠️ 部分修复（§9.2 仍列为已知边界，前端无入口） |
| 20261020 #10（rep 混存账号/姓名） | ⚠️ 建单侧已归一，**编辑侧未归一**（BUG-43） |
| 20261020 #11（驳回覆盖备注） | ✅ 已修复 |
| 20261020 #13（接口校验缺口） | ⚠️ 部分：客户非空/容器拦截已补，`qty=0` 补录交付未见校验 |

---

## 8. 建议修复批次

### 第 0 批（今天，止血，最小改动）

1. **BUG-01** 移除启动期无标记 `DELETE`（一行删除 + 补一次性标记）。
2. **BUG-02 / BUG-13** 文件与 contract 日志的可见性过滤（同一批判定函数）。BUG-02 已降级为中，但改动集中在同一函数，随本批一起做更省事。
3. **BUG-06** 折扣输入对 amount 行置灰（`v-if` 条件 + `onDiscountChange` 提前 return）。

### 第 1 批（本迭代，金额与状态机正确性）

4. **BUG-03 / BUG-04 / BUG-17** 状态机守卫下沉 + 终止按明细状态回滚 + 派生补组合（同一次改动，需补 3 个回归用例）。
5. **BUG-05** 数量判定改用 `_item_repeat`。
6. **BUG-07 / BUG-09 / BUG-22 / BUG-27** 前端单价重置 + 统一 `catch` + 合计口径 + 金额清空提示。
7. **BUG-08 / BUG-18** 校验下沉到 core；`contractAmount` 以 Σ明细为准（不一致直接 400）。

### 第 2 批（下迭代，一致性与并发）

8. **BUG-10** 幂等键 + 条件更新（先覆盖 checkout 与交付两条路径）。
9. **BUG-14 / BUG-15 / BUG-16** 回滚出口补齐（撤销交付不允许静默成功、`cartRefilled` 仅全成功时置位、`assetId` 存在性校验）。
10. **BUG-19 / BUG-20 / BUG-28** 唯一约束 + Pydantic 化裸 dict + 日期校验。
11. **BUG-11 / BUG-12** 安全加固（密钥 fail-fast、tokenVersion、登录限流改造）。

### 第 3 批（清理，可随迭代顺带）

12. BUG-21 ~ BUG-46 中的前端一致性/文案/口径项；UI 硬约束项（BUG-44）合并到下一次 UI 走查。

> 每批完成后需更新 `docs/backend|frontend/changelog.md`，并在本文件对应条目行尾标记 `✅ 已修复（日期/任务号）`；**BUG-01 修复后需在 changelog 标注 ⚠️ 数据安全**。

---

## 9. 本次审查的边界与未覆盖项

- 未做**动态验证**（未启动服务、未发请求、未跑并发压测）：BUG-10/12 属静态推理 + 代码路径确证，实际触发概率需压测确认。
- 未读 `frontend/node_modules` 与构建产物；未审计第三方依赖漏洞（无 lockfile 安全扫描）。
- 未做**存量数据全量体检**：仅抽查了 `asset_deliverables`（BUG-01 实证）与核心表行数；BUG-19/28/34 的存量脏数据规模未统计。
- 前端 14 个页面均已通读，但**未逐屏比对 UI 规范**（仅顺带记录 BUG-44 一处硬约束违反）；视觉走查不在本次范围。

---

**说明**：本文件记录审查结论；代码修复已于 2026-10-22 实施，见 §9 修复状态与 `docs/backend/changelog.md` / `docs/frontend/changelog.md`（任务号 `FIX-20261022`）。

---

## 9. 修复状态（2026-10-22 实施，任务号 FIX-20261022 / -FOLLOWUP）

| 范围 | 状态 | 依据 |
|---|---|---|
| BUG-01 ~ BUG-46 中 **43 条** | ✅ 已实施（后端 24 条 + 前端 19 条 + 收尾 3 项） | `docs/backend/changelog.md`、`docs/frontend/changelog.md` 对应批次 |
| **BUG-29**（金额 Float→Numeric） | ⏸ 未动，待独立 ADR + 数据迁移窗口（DSGN-7） | 属迁移窗口类改造，不随本批 |
| **BUG-45**（手动交付遥感感知） | ✅ 已按"显式拒绝遥感容器（400）"实施 | ADR-029 §4 |
| BUG-19（唯一约束） | ✅ 按修正口径实施：`project_items` 唯一索引 `uq_project_items_key`（建前查重，有重复则跳过+告警）；`contracts (projectId, customer)` 唯一键**不成立**（与 ADR-016 冲突），改由服务层判重兜底 | `docs/backend/changelog.md` ⚠️ 条目 |
| DSGN-1/2/4/6 | ✅ 已决策并实施：ADR-029 / ADR-030 / ADR-031 / ADR-032 | `docs/adr/` |
| DSGN-5 | 🔶 部分：关键写路径幂等/条件更新已实施（ADR-033）；SQLite→PG 待独立 ADR | `docs/adr/ADR-033.md` |
| DSGN-3（快照瘦身）/ DSGN-7（Decimal） | ⏸ 待独立 ADR | — |

**验证方式**：后端 88 项进程内断言（数据库副本 + TestClient）全通过 + 只读 curl 复核；前端 `vue-tsc` 无新增错误；存量库逐表行数与修复前一致（28 产品 / 3 项目 / 7 合同 / 97 明细 / 49 文件），未丢数据。

**已知取舍（预期内）**：
1. dev 环境 JWT 密钥持久化到 `backend/.jwt_secret`（0600，已 git 忽略）——密钥首次落盘时旧 token 失效一次，之后重启不再失效；生产必须用 `JWT_SECRET` 环境变量（否则启动即失败）。
2. 存量 `logs.projectId` 为 NULL → viewer 看不到历史项目日志（ADR-030 保守口径，新日志已写该字段）。
3. `uq_project_items_key` 若因历史重复被跳过，需人工清理重复明细后重启（服务层判重不受影响）。
4. `asset_deliverables` 历史数据（13 条审计可证）未恢复——附件仍在 `uploads/`，可人工按审计日志重建。
