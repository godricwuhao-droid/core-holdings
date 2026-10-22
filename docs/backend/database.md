# 数据库结构与变更

> SQLite（`backend/core_holdings.db`），ORM：SQLAlchemy 2.x 声明式。字段 camelCase，与前端 `types.ts` 对齐。
> 变更方式：`main.py::_ensure_migration()` 轻量迁移（`ALTER TABLE ... ADD COLUMN`，幂等判断），`Base.metadata.create_all` 不会改已存在的表。
> **FIX-20261022 起（ADR-031）**：新增 `schema_migrations(name PK, appliedAt, note)` 标记表——启动期**只做结构迁移**，所有数据类一次性动作必须经 `_run_once(标记名, fn)`「查标记 → 执行一次 → 写标记」；**禁止**在启动期对业务表执行无标记的 `DELETE/UPDATE`。

---

## 2026-10-22 变更（ENTITIES-20261022 / ADR-035：资产主体表 `entities` + 存量回填）

### 1. 新增表

| 表 | 主键 | 字段 | 说明 |
|---|---|---|---|
| `entities` | `id` 自增 | `name` VARCHAR(128) **UNIQUE**（公司全称，与 `assets.subject` 存储口径一致）、`short` VARCHAR(64)（展示简称，默认=name）、`createdAt` VARCHAR(32)、`updatedAt` VARCHAR(32) | 资产主体清单（ADR-035），单一事实来源。不建外键（H7 策略）：引用完整性（删除前 `assets.subject` 计数校验）由服务层保证 |

### 2. 迁移语句（`main.py`，幂等；不引入 Alembic）

```sql
-- 结构：建表（create_all 直接建出 entities，name UNIQUE 随约束生成）

-- 数据类一次性动作（_run_once，标记 ADR035_entities_backfill 写入 schema_migrations）：
INSERT OR IGNORE INTO entities (name, short, createdAt, updatedAt)
SELECT DISTINCT subject, subject, :now, :now FROM assets WHERE subject <> '';
```

| 标记名 | 动作 | 存量库行为 |
|---|---|---|
| `ADR035_entities_backfill` | 存量 `assets.subject` 去重回填 `entities`（short 默认取 name，由管理员在设置页修正） | 首启回填 4 条（现库 subject 恰好 4 家）；第二次启动零写入（行数稳定 4、标记 1 行）；空库回填 0 条 |

### 3. 实测

副本库（`/tmp`）重复启动 2 次：`entities` 行数稳定（4）、`schema_migrations` 标记不重复（1 行）；空库启动：回填 0 条、0 行、标记 1 行。纯增量——只 INSERT `entities`，不动 `assets` 及其他业务表。

---

## 2026-10-22 变更（FIX-20261022 / ADR-031 ~ ADR-034：迁移治理 + 2 列 + 1 张表 + 2 个唯一索引）

### 1. 新增表

| 表 | 主键 | 字段 | 说明 |
|---|---|---|---|
| `schema_migrations` | `name` | `name` VARCHAR(64) PK、`appliedAt` VARCHAR(32)、`note` VARCHAR(255) | 迁移执行标记（ADR-031）。启动期结构迁移不写标记（靠 inspector 判列幂等）；**数据类一次性动作**必须写标记，执行前查标记 |
| `idempotency` | `id` 自增 | `userId` VARCHAR(64)、`scope` VARCHAR(32)（当前仅 `checkout`）、`requestId` VARCHAR(64)、`projectId` INTEGER NULL、`createdAt` VARCHAR(32)、**UNIQUE(`userId`,`scope`,`requestId`)** | 请求幂等键（BUG-10 / ADR-033 §1）。`POST /cart/checkout` 首次成功后写 `projectId`；同一键 24h 内重复请求直接返回首次项目。保留期 24h，过期记录在复用同键时被覆盖（不做自动清理任务） |

### 2. 新增列

| 表.列 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| `users.tokenVersion` | INTEGER | 是 | 0 | 凭据版本（BUG-11 / ADR-034 §2）：写入 JWT payload `ver`，`get_current_user` 每请求比对，不一致 401。改密 / 禁用 / 改角色时 +1。存量账号补列置 0（旧 token 无 `ver` 按 0 处理，仍然有效直至自然过期） |
| `logs.projectId` | INTEGER | 是 | NULL | 项目级操作日志的结构化归属外键（BUG-13 / ADR-030 §4）：viewer 日志可见性只看外键（`projectId`/`contractId`），不再用 detail 文本里的 `SP-` 正则。新建日志由 `add_log(..., project_id=...)` 写入；**存量 project 日志保持 NULL → 对 viewer 一律过滤**（宁可保守） |

### 3. 新增唯一索引

| 索引 | 定义 | 说明 |
|---|---|---|
| `uq_project_items_key` | `UNIQUE(contractId, assetId, COALESCE(itemId, 0))` WHERE 两列非空 | BUG-19：同一销售记录内不可重复同一产品/明细行。建前先跑查重 SQL，**存在重复行则跳过并打印告警**（不启动失败、不删数据）。实测存量库无重复 → 已建立 |
| ~~`uq_contracts_project_customer`~~ | ~~`UNIQUE(projectId, customer)`~~ | ⚠️ **未创建**（BUG-19 原文要求，技术冲突）：ADR-016 销售记录粒度 = 一产品（×客户）一条 ⇒ 同一项目同一客户**必然**多条（现库 `projectId=2` 即有 3 条 `customer='云从'`）。建该索引会阻断购物车「多产品同客户」结算（IntegrityError → 500）。**替代方案**：① 迁移期查重并打印警告（`main._ensure_unique_indexes`）；② 服务层禁止「同项目 + 同客户 + 同明细集合」重复（400「客户「X」下相同的销售明细不可重复建记录」）与同一记录内重复产品行（400）；③ `uq_project_items_key` 阻断记录内重复行 |

### 4. 迁移语句（`main.py`，幂等；不引入 Alembic）

```sql
-- 结构：建表（create_all 直接建出 schema_migrations / idempotency）
-- 结构：补列（inspector 判定，列已存在则 no-op）
ALTER TABLE users ADD COLUMN tokenVersion INTEGER DEFAULT 0;
ALTER TABLE logs  ADD COLUMN projectId INTEGER;

-- 结构：唯一索引（先查重，有重复则跳过 + 告警，不阻断启动）
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_items_key
  ON project_items (contractId, assetId, COALESCE(itemId, 0));
```

数据类一次性动作（`_run_once`，标记写入 `schema_migrations`；第二次启动**零写入**）：

| 标记名 | 动作 | 存量库行为 |
|---|---|---|
| `ADR024_cleanup_done` | **仅写标记**（原「每次启动全表 DELETE `asset_deliverables`」已删除，BUG-01/ADR-031） | 0 行 DELETE；实测预置 1 条交付物后启动/重启仍为 1 条 |
| `ADR027_cartrefilled_backfill` | 历史已撤销终止项目 `cartRefilled=1` | 首启命中 1 条（已存在标记的库不再执行） |
| `ADR011_demo_asset_cleanup` | 删除 ADR-010 演示遥感数据产品及其从属行（交付物用 Core Delete 按 `asset_id` 精确限定） | 命中 0 条 |
| `ADR008_pricingmode_backfill` | 卫星Token 产品 `pricingMode='amount'` | 命中 0 条 |
| `ADR009_cart_userid_backfill` | `cart_items.userId='admin'` → admin 的 `users.id` | 命中 0 条 |
| `LEGACY_project_status_3state` | 旧 8 态项目状态归一为 3 态 | 命中 0 条 |
| `assets_status_backfill` | 按 `services.auto_status` 回填 `assets.status` | 命中 0 条（此后不再每次启动扫描全表） |
| `file_meta_backfill_done` | 存量 `uploads/` 文件回填 `file_meta` | `file_meta` 非空 → 跳过并写标记（空库重建时回填 65 条） |

### 5. 存量库实测（28 产品 / 3 项目 / 7 合同 / 49 文件）

启动（含 `--reload` 热重载）后逐表计数与迁移前**完全一致**：`assets 28 / projects 3 / contracts 7 / project_items 7 / file_meta 49 / cart_items 11 / outbounds 1 / flows 194 / logs 571 / users 8 / asset_deliverables 0 / rs_items 97`；无 DELETE、无行数变化；`asset_deliverables` 保持 0 行（**历史交付物不恢复**，附件仍在 `uploads/`，可人工按审计日志重建）。

---

## 2026-10-21 变更（ADR-027 明细回填购物车幂等标记 `projects.cartRefilled`）

### 新增列

| 表.列 | 类型 | 可空 | 默认 | 说明 |
|-------|------|------|------|------|
| `projects.cartRefilled` | BOOLEAN | 否 | 0 | 该项目明细**是否已回填购物车**（ADR-027 幂等标记）。`withdraw_project`（撤销）回填成功后置 1；`POST /projects/{id}/refill-cart`（重新提交）见 1 直接返回 `alreadyRefilled=true` 不重复回填，首次回填成功后置 1 |

`ProjectOut` 同步输出 `cartRefilled`（bootstrap `projects[]` / 结算响应）。

### 迁移语句（幂等，`main.py::_ensure_migration` 第 18 项）

```sql
-- 1) 补列（幂等：projects 无该列才执行；SQLite 加列不能带 NOT NULL，故用 DEFAULT 0）
ALTER TABLE projects ADD COLUMN cartRefilled BOOLEAN DEFAULT 0;

-- 2) 一次性数据迁移：历史「已撤销」的终止项目置 1
--    判据：其名下任一合同 remark 含「撤销」（与 ADR-026 withdraw 写入格式「撤销：{reason}」一致）；
--    「驳回」项目的 remark 为「驳回：{reason}」，不含「撤销」→ 保持 0（首次点重新提交才回填）。
--    幂等：只更新 COALESCE(cartRefilled,0)=0 的行，已是 1 直接跳过（复跑命中 0 条）。
UPDATE projects SET cartRefilled = 1
WHERE COALESCE(cartRefilled, 0) = 0
  AND status = 'terminated'
  AND EXISTS (
    SELECT 1 FROM contracts
    WHERE contracts.projectId = projects.id AND contracts.remark LIKE '%撤销%'
  );
```

### 迁移说明

- 真实库首启命中 1 条（`SP-2026102110215709 云从项目`，3 个合同 remark 均为「撤销：213」→ `cartRefilled=1`），`projects/subjects` 其余行不变；重复启动（`touch main.py` 触发 reload 复跑）命中 0 条、值不再变化。
- 无索引变更；无表删除；`cartRefilled` 为纯增量列，回退只需忽略该列（代码不读即兼容）。

---

## 2026-10-21 变更（ADR-026 撤销待审核订单）

**无表结构变更（仅写既有字段）。**

| 操作 | 表/列 | 说明 |
|---|---|---|
| 更新 | `contracts.status` / `contracts.remark` / `contracts.updatedAt` | `pending → terminated`；`remark` 追加「撤销：{reason}」（追加不覆盖，已含同文案不重复追加） |
| 更新 | `projects.status` / `projects.businessOwner` / `projects.updatedAt` | 置 `terminated`；`businessOwner` 置空（原值写入 OpLog 详情） |
| 更新 | `projects.customer` / `subject` / `expectedAmount` / `contractAmount` | 由 `_recompute_project` 按合同派生重算（口径不变） |
| 更新 | `project_items.status` | `locked/confirmed → released` |
| 更新 | `assets.lockedQty` / `assets.status` / `assets.updatedAt` | 逐明细释放真实锁定（仅 `locked=true` 的行），由 `apply_item_lock(..., add=False)` + `refresh_status` 维护 |
| 新增行 | `flows` | `type='cancel_release'`（每行一条，repeatSale/明细 repeatSale 行不产生） |
| 新增行 | `cart_items` | 按 `(userId, assetId, itemId, customer)` 判重回填下单人购物车（命中即合并 qty / 覆盖 amount） |
| 新增行 | `logs`（OpLog）/ `audit_logs` | `撤销订单` 各 1 条（另有既有合同级「销售记录状态变更」日志） |

无新增表/列/索引，`_ensure_migration()` 无需改动。

---

## 2026-10-21 变更（ADR-024：交付物模板下线 + 交付物附件，⚠️ 破坏性）

### 删除表

| 表 | 说明 |
|---|---|
| `deliverable_templates`（已删除） | 交付物模板体系下线（ADR-024）：模型/端点/种子数据全删；启动迁移 `DROP TABLE IF EXISTS deliverable_templates` 幂等清理旧库物理表。交付物实例改为产品详情页完全手动维护 |

### 新增列

| 表.列 | 类型 | 可空 | 说明 |
|-------|------|------|------|
| `asset_deliverables.file` | VARCHAR(255) | 是 | 交付物单文件附件（存 `/api/upload` 返回的散列文件名；NULL/空=无附件）。`PUT /assets/{id}/deliverables/{item_id}` patch 白名单追加（`""`/null → 落库 NULL）；bootstrap `assetDeliverables` 行携带 `file`；`DELETE /upload/{filename}` 引用检查追加本列 |

### 存量数据一次性清空（幂等）

- `asset_deliverables` 表存在且**非空**时 `DELETE FROM asset_deliverables`（空表跳过，幂等）。模板体系下线后各产品交付物从零手动添加（用户已确认，ADR-024 §2）。
- 无其他表引用 `asset_deliverables`，直接清；`product 删除`（`delete_asset`）的级联清理逻辑不受影响。

### 迁移语句（`main.py::_ensure_migration`）

```sql
DROP TABLE IF EXISTS deliverable_templates;      -- 旧库物理表清理（表存在才执行）
ALTER TABLE asset_deliverables ADD COLUMN file VARCHAR(255);
DELETE FROM asset_deliverables;                   -- 一次性清空（仅表非空时执行）
```

> 注：沿用 inspector + ALTER TABLE / 条件 DDL 幂等模式，可重复启动；`asset_deliverables` 其余列（id/asset_id/name/category/required/note/version/meta/status/updatedAt）不变。

---

## 2026-10-21 变更（DISCOUNT-20261021：购物车折扣率，2 表 2 列，依据 ADR-023）

### 新增列（可空，存量数据不迁移——NULL 即无折扣/无快照，行为同现状）

| 列 | 类型 | 说明 |
|---|---|---|
| `cart_items.discountRate` | FLOAT NULL | 折扣率（0-1 小数，0.9=九折），选填快捷入口（ADR-023）。写接口（POST /cart、/cart/batch、PUT/PATCH /cart/{id}）接受，0 < rate ≤ 1 否则 400；NULL=无折扣；后端只存不算（金额权威原则，区间校验仍对 amount 生效） |
| `project_items.discountRate` | FLOAT NULL | 折扣率快照：下单时快照购物车行值（手动建单=商务手填），**只写不改**（与 origPrice/origAmount 同级口径，审核终审改价不触碰本列）；存量订单 NULL（展示端不显示） |

### 迁移语句（幂等，`main.py::_ensure_migration`）

```sql
ALTER TABLE cart_items ADD COLUMN discountRate FLOAT;
ALTER TABLE project_items ADD COLUMN discountRate FLOAT;
```

> 注：沿用 inspector + ALTER TABLE 模式（SQLite 追加可空列，存量行自动 NULL，不触碰业务数据）；列已存在时 no-op，可重复启动。

---

## 2026-10-20 变更（RSITEM-RANGE-20261020：遥感售卖明细参考区间，rs_items 2 列，依据 ADR-021）

### 新增列（可空，存量 98 条明细不迁移——NULL 即不限制，行为同现状）

| 列 | 类型 | 说明 |
|---|---|---|
| `rs_items.priceMin` | FLOAT NULL | 参考区间下限（元/份，ADR-021）。生态下单遥感明细行折扣单价（amount÷qty）须落在 [priceMin, priceMax]；NULL=未设置（不限制），只填其一=单边边界 |
| `rs_items.priceMax` | FLOAT NULL | 参考区间上限（元/份）。两者都有时 min ≤ max（服务层校验，400「参考区间下限不能大于上限」） |

> 注：遥感明细行折扣校验口径切换——区间来源由父产品容器 `assets.priceMin/priceMax` 改为**该明细自身**（ADR-021 §2，取代 ADR-018 §5「遥感行不限制」推断口径）；普通产品行仍用 assets 区间。

### 迁移语句（幂等，`main.py::_ensure_migration`）

```sql
ALTER TABLE rs_items ADD COLUMN priceMin FLOAT;
ALTER TABLE rs_items ADD COLUMN priceMax FLOAT;
```

---

## 2026-10-20 变更（PRICING-20261020：价格体系 + 时间节点 + 服务期限，4 表 9 列，依据 ADR-018/019/020）

### 新增列（全部可空，存量数据不迁移——旧数据 NULL 即兼容）

| 列 | 类型 | 说明 |
|---|---|---|
| `assets.priceMin` | FLOAT NULL | 参考区间下限（元/份，ADR-018 §1）。行折扣单价（amount÷qty）须落在 [priceMin, priceMax]；NULL=未设置（不限制），只填其一=单边边界 |
| `assets.priceMax` | FLOAT NULL | 参考区间上限（元/份）。两者都有时 min ≤ max（服务层校验，400） |
| `cart_items.serviceStart` | VARCHAR(10) NULL | 服务开始日期 YYYY-MM-DD（ADR-020）。下单人填，checkout 透传落 project_items；遥感行不填；存量 NULL |
| `cart_items.serviceEnd` | VARCHAR(10) NULL | 服务结束日期 YYYY-MM-DD。start ≤ end（服务层校验，400） |
| `project_items.origPrice` | FLOAT NULL | 原价快照（元，ADR-018 §2）：下单时快照写入、**永不覆盖**。普通行=asset.salePrice；遥感行=rs_items.price；存量订单 NULL（展示端按 price 兜底） |
| `project_items.origAmount` | FLOAT NULL | 原金额快照（元）：普通行=salePrice×qty；遥感行=同值。`price/amount` 语义=最终价（折扣/终审后） |
| `project_items.serviceStart` | VARCHAR(10) NULL | 服务开始日期（ADR-020）。购物车透传 / 手动建单填写 / 审核 confirm 可改 |
| `project_items.serviceEnd` | VARCHAR(10) NULL | 服务结束日期。start ≤ end |
| `contracts.signedDate` | VARCHAR(10) NULL | 合同签订时间（ADR-019）：商务填（`PATCH /contracts/{id}`），录入即 active→delivering；录后可改、不可清空；存量 active 合同 NULL（上线后商务补录） |
| `contracts.scheduledDeliveryDate` | VARCHAR(10) NULL | 预计交付时间（ADR-019）：仅 admin 填，仅 delivering 状态可录/改/清空 |

> 注：本批次共 **10 个新列**（4 表：assets 2 + cart_items 2 + project_items 4 + contracts 2）。

### 迁移语句（幂等，`main.py::_ensure_migration`）

```sql
ALTER TABLE assets ADD COLUMN priceMin FLOAT;
ALTER TABLE assets ADD COLUMN priceMax FLOAT;
ALTER TABLE cart_items ADD COLUMN serviceStart VARCHAR(10);
ALTER TABLE cart_items ADD COLUMN serviceEnd VARCHAR(10);
ALTER TABLE project_items ADD COLUMN origPrice FLOAT;
ALTER TABLE project_items ADD COLUMN origAmount FLOAT;
ALTER TABLE project_items ADD COLUMN serviceStart VARCHAR(10);
ALTER TABLE project_items ADD COLUMN serviceEnd VARCHAR(10);
ALTER TABLE contracts ADD COLUMN signedDate VARCHAR(10);
ALTER TABLE contracts ADD COLUMN scheduledDeliveryDate VARCHAR(10);
```

### 迁移说明

沿用 `inspect(engine).get_columns()` 检测 + `ALTER TABLE ADD COLUMN` 模式（SQLite 追加可空列，存量行自动 NULL，不触碰业务数据）；列已存在时 no-op，可重复启动。

- **无数据迁移**：全部新列可空，旧数据 NULL 语义正确（未设区间=不限制、无原价快照=展示端按 price/amount 兜底、无期限/签订时间）；
- 已在真实库副本验证：加列成功，各业务表行数不变（assets 28 / cart_items 3 / project_items 16 / contracts 15 / projects 6 / outbounds 0 / flows 162 / logs 507 / users 8 / rs_items 98）；
- 存量 active 合同（如有）不做 signedDate 回填，上线后由商务经 `PATCH /contracts/{id}` 补录（补录前该合同交付入口被新守卫拦截：400「合同尚未录入签订时间，不可交付」）。

## 2026-10-20 变更（FIX-20261020-#7：outbounds 新增 projectItemId 列）

### 新增列

| 列 | 类型 | 说明 |
|---|---|---|
| `outbounds.projectItemId` | INTEGER NULL INDEX | 所属项目明细，指向 `project_items.id`。合同交付（`_apply_item_delivery`）创建时写入被交付明细的 id；手动补录与存量记录为 NULL。撤销交付按此精确定位明细（同合同同产品多明细不再 `limit(1)` 猜行）；NULL 时回退 `contractId+assetId limit(1)` 兼容逻辑 |

### 迁移语句（幂等，`main.py::_ensure_migration`）

```sql
ALTER TABLE outbounds ADD COLUMN projectItemId INTEGER;
CREATE INDEX ix_outbounds_projectItemId ON outbounds (projectItemId);
```

### SQLite 兼容加列方式（存量库迁移）

`Base.metadata.create_all` **只会创建不存在的表，不会给已有表加列**。项目采用 `backend/main.py` 的 `_ensure_migration()` 轻量迁移（启动时执行，先例：`assets.contractFile`、`projects.creator`、`outbounds.contractId` 等）：

1. `sqlalchemy.inspect(engine).get_columns(<table>)` 检测目标列是否存在（等价 `PRAGMA table_info`）；
2. 不存在则 `ALTER TABLE <table> ADD COLUMN <col> <type>`（SQLite 仅支持追加可空/带默认值列，追加列对存量行自动填 NULL/默认值，不触碰业务数据）+ 需要时补 `CREATE INDEX`；
3. 幂等：列已存在时 no-op，可重复启动。

本次（FIX-20261020-#7）：

- 当前库 `outbounds` 为 0 行，**无数据迁移**（存量记录语义即 NULL=手动/未知明细，撤销走回退逻辑）；
- 已在真实库副本验证：加列 + 索引成功，各业务表行数不变。

## 2026-10-16 变更（ADR-011 遥感数据「父产品 + 可售明细」两层模型，⚠️ Supersedes ADR-010）

### 新表 rs_items（遥感数据可售明细）

父产品（`assets` 行，`type='遥感数据'`，容器，本身不可直接加购/下单）下的真正售卖单位。维度 = 省（可含市）× 精度（米）× 月份（YYYY-MM），每份一个单价（整数元/份），默认可重复售卖（只计次不扣量）。

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| `id` | INTEGER PK | 否 | DB 自增（禁止手写） |
| `assetId` | INTEGER INDEX | 否 | 父产品 id（`type='遥感数据'`；引用完整性由服务层保证，无 DB 外键） |
| `province` | VARCHAR(64) 默认 `''` | 否 | 省/自治区/直辖市，必填（服务层校验非空） |
| `city` | VARCHAR(64) 默认 `''` | 否 | 市，可空（省级明细不填） |
| `resolution` | FLOAT | 否 | 精度，单位**米**（如 1.5），> 0（Pydantic 422） |
| `saleMonth` | VARCHAR(7) 默认 `''` | 否 | 售卖月份 `YYYY-MM`（`^\d{4}-\d{2}$`，Pydantic 422） |
| `price` | FLOAT | 否 | 单价，**整数元/份**（元口径 ADR-006；服务层校验 >0 且整数，否则 400） |
| `repeatSale` | BOOLEAN | 否（默认 1） | 可重复售卖（true=只计次不扣量；false=下单锁父产品 lockedQty，交付扣 shippedQty） |
| `createdAt`/`updatedAt` | VARCHAR(32) | 否（默认 `''`） | `YYYY-MM-DD HH:MM` |

唯一性：`(assetId, province, city, resolution, saleMonth)` 组合唯一，**服务层判重**（create/update 排除自身，Python 层，resolution 容差 1e-9，无 DB 唯一约束/索引）；重复 400「该父产品下已存在相同 省/市 + 精度 + 月份 的明细」。

建表方式：`Base.metadata.create_all`（新表，无 ALTER 迁移需求）。

### cart_items / project_items 新增列 `itemId`（均幂等迁移）

| 表.列 | 类型 | 可空 | 说明 |
|-------|------|------|------|
| `cart_items.itemId` | INTEGER INDEX | 是 | 挂 `rs_items` 明细；非空行 qty 恒 1（≠1 → 400）、结算金额=明细 price 权威；判重键升级为 **(userId, assetId, itemId, customer)**（无 itemId 行 = `itemId IS NULL`，口径不变）；存量/非遥感行恒 NULL |
| `project_items.itemId` | INTEGER INDEX | 是 | 挂 `rs_items` 明细；非空行 qty 恒 1、`amount` 权威 = 明细 price × 1（忽略前端传值）、锁定/交付/回滚按**明细** repeatSale（true 不锁只计次，false 锁父产品 lockedQty）；存量/非遥感行恒 NULL |

迁移语句（幂等，`main.py::_ensure_migration`）：

```sql
ALTER TABLE cart_items    ADD COLUMN itemId INTEGER;
CREATE INDEX ix_cart_items_itemId    ON cart_items (itemId);
ALTER TABLE project_items ADD COLUMN itemId INTEGER;
CREATE INDEX ix_project_items_itemId ON project_items (itemId);
```

### 数据清理（幂等一次性迁移）

删除 ADR-010 演示遥感数据产品（`type='遥感数据'` 且带三维字段值的存量行，即「河北省石家庄市 1.5m 2026-09-15」id=29）及其 `rs_items`/`asset_deliverables`/`flows` 关联行。删前 **assert 无 project_items/cart_items 引用**（有引用则启动失败暴露问题，等价 delete_asset 的 400 逻辑）。匹配条件限定「三维字段非空」——ADR-011 新建的父产品容器 4 列恒空，**不会被误删**；执行一次后命中 0 行，幂等。

### assets 4 列废弃标注（ADR-010 遗留，列保留不删）

`assets.province` / `assets.city` / `assets.resolution` / `assets.imageDate` **已废弃（ADR-011）**：schema（AssetIn/AssetOut）移除、服务层不再读写、`update_asset` 不再接受；仅作为技术债保留列与存量值。遥感数据售卖粒度全部由 `rs_items` 承载。

---

## 2026-10-16 变更（ADR-008 包量定价 + ADR-009 购物车隔离 + ADR-010 遥感数据）

> ⚠️ 本节 ADR-010 部分（assets 三维 4 列 + 三维判重 + 登记默认值）**已被 ADR-011 取代**：4 列废弃保留、判重/默认值逻辑移除，见上方 ADR-011 章节。ADR-008/ADR-009 部分仍有效。

### assets 新增列（6 列，均幂等迁移）

| 表.列 | 类型 | 可空 | 说明 |
|-------|------|------|------|
| `assets.pricingMode` | VARCHAR(16) NOT NULL 默认 `'unit'` | 否 | 计价模式（ADR-008）：`unit`（单价×数量，默认）/ `amount`（包量合同金额整数元权威）。卫星 Token 产品登记置 `amount`（后端按类型权威决定，不接受前端入参）；`amount` 模式下 `salePrice` 仅参考值，不参与金额计算 |
| `assets.province` | VARCHAR(64) 默认 `''` | 否 | 遥感数据省（ADR-010）；仅 `type='遥感数据'` 使用，其余类型恒空 |
| `assets.city` | VARCHAR(64) 默认 `''` | 否 | 遥感数据市（可空，省级产品不填） |
| `assets.resolution` | FLOAT | 是 | 遥感数据精度，单位**米**（如 1.5） |
| `assets.imageDate` | VARCHAR(10) 默认 `''` | 否 | 遥感数据影像日期 `YYYY-MM-DD` |

唯一性：遥感数据 `(province, city, resolution, imageDate)` 组合唯一，**服务层判重**（`create_asset` / `update_asset` 排除自身，Python 层，SQLite 单写模型，无 DB 唯一约束/索引）。

### cart_items 新增列

| 表.列 | 类型 | 可空 | 说明 |
|-------|------|------|------|
| `cart_items.amount` | FLOAT | 是 | 包量计价合同金额（ADR-008，元，整数）：仅 `pricingMode='amount'` 产品行使用，结算时必填（缺失 400）；unit 模式恒 NULL（忽略入参） |

### 存量数据回填（幂等）

- ADR-008：`UPDATE assets SET pricingMode='amount' WHERE type='卫星Token' AND pricingMode='unit'`（`salePrice` 原值保留，语义转参考值）；
- ADR-009：`UPDATE cart_items SET userId='<admin 账号 users.id>' WHERE userId='admin'`（购物车改按登录用户隔离后，存量行归属 admin）。

迁移语句（幂等，`main.py::_ensure_migration`）：

```sql
ALTER TABLE assets ADD COLUMN pricingMode VARCHAR(16) NOT NULL DEFAULT 'unit';
ALTER TABLE cart_items ADD COLUMN amount FLOAT;
ALTER TABLE assets ADD COLUMN province   VARCHAR(64) DEFAULT '';
ALTER TABLE assets ADD COLUMN city       VARCHAR(64) DEFAULT '';
ALTER TABLE assets ADD COLUMN resolution FLOAT;
ALTER TABLE assets ADD COLUMN imageDate  VARCHAR(10) DEFAULT '';
```

### 行为变更（无新列）

- **购物车按登录用户隔离（ADR-009）**：router 层购物车 7 端点传 `str(user.id)`（`get_current_user`）；`bootstrap.cart` 仅返回当前请求用户的行；`DEFAULT_USER` 常量保留但 router 不再使用。判重 (userId, assetId, customer) 与数量校验规则不变。
- **销售明细计价分支（ADR-008）**：`amount` 模式明细以 `amount`（整数元，>0，否则 400）为权威输入，`price = round(amount/qty, 6)` 派生展示值，跳过 `price×qty` 权威重算；`unit` 模式行为完全不变。覆盖 `POST /projects`、`POST /sales/order`、`POST /cart/checkout`。
- **遥感数据登记默认值（ADR-010）**：`quantity` 0→1、`unit` 空→`份（区域·精度·日期）`；`repeatSale` 由前端传（默认 True，允许关闭）。

---

## 2026-10-15 变更（ADR-007 合同层级：新表 contracts + 5 个新列 + 清理脚本）

### 新表 contracts（合同）

项目下按客户拆分的合同，数量联动的最小单位。合同内强制同一产品主体；合同一经生成不可增删改明细。

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| id | INTEGER PK | 否 | DB 自增（禁止手写） |
| code | VARCHAR(32) UNIQUE INDEX | 否 | `HT-{16位时间戳}`（2026-10-19 起，14 位 yyyyMMddHHmmss + 2 位随机，见 services._ts_code） |
| projectId | INTEGER INDEX | 否 | 归属项目（ForeignKey 声明，SQLite 默认不启用外键约束，引用完整性由服务层保证） |
| customer | VARCHAR(128) | 否（默认 `''`） | 合同客户（必填语义由入参校验保证） |
| subject | VARCHAR(128) | 否（默认 `''`） | 签约主体：建单时从记录内产品主体派生（ADR-013：各行全一致→该值；混合→空串=多主体记录，前端显示「多主体」） |
| contractAmount | FLOAT | 否（默认 0） | 合同金额，单位=**元**（ADR-006，Decimal 计算落 float） |
| status | VARCHAR(32) INDEX | 否（默认 `active`） | `active` / `delivered` / `terminated` |
| remark | TEXT | 否（默认 `''`） | 备注 |
| createdAt/updatedAt | VARCHAR(32) | 否（默认 `''`） | `YYYY-MM-DD` |

建表方式：`Base.metadata.create_all`（新表，无 ALTER 迁移需求）。ORM 关系：`Project.contracts`（cascade delete-orphan）、`Contract.items`（cascade delete-orphan，按 `project_items.contractId` 关联）。

### 新增列（均幂等迁移，`main.py::_ensure_migration`）

| 表.列 | 类型 | 可空 | 说明 |
|-------|------|------|------|
| `project_items.contractId` | INTEGER INDEX | 是 | 所属合同（ADR-007）：新数据必填；**存量项为 NULL**（清理脚本执行后消失） |
| `outbounds.contractId` | INTEGER INDEX | 是 | 所属合同：合同交付自动交付精确关联；项目级手动交付为 NULL（`projectId` 保留） |
| `flows.contractId` | INTEGER INDEX | 是 | 合同级交付/终止产生的流水（sale_out/cancel_release/manual_adjust）关联合同；非合同场景 NULL |
| `logs.contractId` | INTEGER | 是 | 合同级状态变更日志（`action='合同状态变更'`）关联合同；其余日志 NULL |
| `cart_items.customer` | VARCHAR(128) 默认 `''` | 否 | 购物车行级客户；唯一键语义 (userId, assetId, customer)（服务层判重，无 DB 唯一约束） |

迁移语句（幂等）：

```sql
ALTER TABLE project_items ADD COLUMN contractId INTEGER;
CREATE INDEX ix_project_items_contractId ON project_items (contractId);
ALTER TABLE outbounds  ADD COLUMN contractId INTEGER;
CREATE INDEX ix_outbounds_contractId ON outbounds (contractId);
ALTER TABLE flows      ADD COLUMN contractId INTEGER;
CREATE INDEX ix_flows_contractId ON flows (contractId);
ALTER TABLE logs       ADD COLUMN contractId INTEGER;
ALTER TABLE cart_items ADD COLUMN customer VARCHAR(128) DEFAULT '';
```

### 项目派生字段（无新列，行为变更）

`projects.status` / `expectedAmount` / `contractAmount` / `customer` / `subject` 由合同派生（`services._recompute_project`，任何合同状态变更后重算落库）：无合同→status=active（存量兼容）；有 active→active；全 delivered→delivered；全 terminated→terminated；混合 delivered+terminated→terminated（保守）。`expectedAmount`=Σ合同 contractAmount；多合同 customer/subject=空字符串（前端显示「N 位客户」）、单合同=该合同值。`quoteAmount`/`paidAmount` 保留项目级手动。

### 数据清理脚本（迁移窗口专用）

`backend/cleanup_sales_data.py`（⚠️ 仅架构师审核后在**停服窗口**手动执行，应用启动不调用）：备份库 → 单事务按序删 `project_items` → `outbounds`（全部）→ 销售类 `flows`（`project_lock`/`sale_out`/`cancel_release`/`manual_adjust`，**`purchase_in` 保留**）→ `cart_items` → `contracts` → `projects` → 产品 `lockedQty=0, shippedQty=0, soldCount=0, soldAmount=0` → 产品 status 重刷（auto_status 同规则）→ 输出清理前后计数。幂等保护（projects+contracts 均空则跳过）。用法：`python3 cleanup_sales_data.py [--db path] [--dry-run]`。

---

## 2026-10-14 变更

### OpLog（表 `logs`）新增列 `assetId`

| 列名 | 类型 | 可空 | 说明 |
|------|------|------|------|
| assetId | INTEGER | 是 | 关联产品 id；仅 `target='asset'` 的日志写入，其余为 NULL（存量数据也为 NULL） |

迁移语句（幂等，`main.py`）：

```sql
ALTER TABLE logs ADD COLUMN assetId INTEGER;
```

影响：
- `models.py::OpLog` 增加 `assetId: Mapped[int | None]`。
- `schemas.py::LogOut` 增加可选 `assetId`。
- `services.add_log(..., asset_id=...)`：当 `target=='asset'` 时写入 assetId；所有 `target=='asset'` 调用点已补 assetId。
- `main.py` 种子日志直接写入 `OpLog(..., assetId=asset.id)`。

---

## 2026-10-15 变更

### 新表 users（平台账号）

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| id | INTEGER PK | 否 | DB 自增 |
| username | VARCHAR(50) UNIQUE | 否 | 登录名 |
| passwordHash | VARCHAR(128) | 否 | `pbkdf2$<salt_hex>$<hash_hex>`（PBKDF2-SHA256，100_000 轮，16 字节随机 salt）；明文不落库、不进响应 |
| name | VARCHAR(50) | 否 | 显示名 |
| role | VARCHAR(20) | 否 | 固定三角色：`admin` / `editor` / `viewer`（无动态权限表） |
| enabled | BOOLEAN | 否 | 默认 1；禁用后该账号旧 token 立即 401 |
| createdAt | VARCHAR(32) | 否 | `YYYY-MM-DD HH:MM`（现有字符串时间风格） |

种子：`main.py::seed_admin_user()` 幂等——`users` 为空时创建 `admin`（密码 123456，role=admin），非空不创建。

### 新表 audit_logs（操作审计日志）

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| id | INTEGER PK | 否 | DB 自增 |
| userId | INTEGER | 是 | 操作者用户 id（登录失败时为 NULL） |
| username | VARCHAR(50) | 否 | 操作者快照（账号被删后仍可追溯；登录失败用输入值） |
| actionType | VARCHAR(20) INDEX | 否 | `sale` / `outbound` / `asset_change` / `setting` / `user_mgmt` / `auth` / `other` |
| action | VARCHAR(50) | 否 | 中文动作，如「新建销售项目」「撤销交付」 |
| target | VARCHAR(50) | 否 | 目标类型，如 `project` / `asset` / `outbound` / `base` / `template` / `deliverable` / `user` / `file` / `auth` |
| targetName | VARCHAR(120) | 否 | 目标名称（产品名/项目名/用户名等） |
| detail | VARCHAR(255) | 是 | 补充信息（如 `status=delivered`、登录失败原因） |
| time | VARCHAR(32) | 否 | `YYYY-MM-DD HH:MM` |

与既有 `logs`（OpLog，实体级流水）的关系：**分表、互不回填**。`logs` 表及其调用方行为完全不动；`audit_logs` 只记录带操作者身份的业务写操作与认证事件，写入点在 router 层统一 `record_audit`（业务 services 不改）。旧 logs 数据**不回填** audit_logs。

建表方式：`Base.metadata.create_all`（新表，无 ALTER 迁移需求）。

---

## 2026-10-15 变更（产品详情四点：3 个新列）

### assets 新增列 `featureDoc`

| 列名 | 类型 | 可空 | 说明 |
|------|------|------|------|
| featureDoc | VARCHAR(255) | 否（默认 `''`） | 功能清单附件 filename（`/upload` 返回值）；替换 `saleDetail` 电子表格的 UI 载体。`saleDetail` 列与存量数据保留不删 |

### flows 新增列 `operator`

| 列名 | 类型 | 可空 | 说明 |
|------|------|------|------|
| operator | VARCHAR(64) | 否（默认 `''`） | 流水操作账号（登录 username）；存量流水为空（前端显示 `-`）；启动 seed 路径写 `"system"` |

### logs 新增列 `changes`

| 列名 | 类型 | 可空 | 说明 |
|------|------|------|------|
| changes | VARCHAR(512) | 否（默认 `''`） | 字段级变更描述，仅 `update_asset` 有实际变更时写入，如 `销售单价: 330,000 元 → 3,200,000 元；产品总数: 5 → 8 套`（元值千分位 + 「 元」）；长文本字段只记 `规格描述: 已变更` |

迁移语句（均幂等，`main.py::_ensure_migration`）：

```sql
ALTER TABLE assets ADD COLUMN featureDoc VARCHAR(255) DEFAULT '';
ALTER TABLE flows  ADD COLUMN operator   VARCHAR(64)  DEFAULT '';
ALTER TABLE logs   ADD COLUMN changes    VARCHAR(512) DEFAULT '';
```

另：`projects.subject`（签约主体）列此前已存在，本轮仅补行为（后端权威推导，见 changelog 2026-10-15），`main.py` 加幂等补列判断（现有库 no-op）。

---

## 2026-10-15 变更（文件原名映射：新表 file_meta）

### 新表 file_meta（上传文件原名映射）

上传文件以散列名（`uuid4().hex.ext`）落盘 `uploads/`，产品/日志直接存散列名；本表记录散列名→原始文件名映射，供前端展示与下载时还原原始名。

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| storedName | VARCHAR(255) PK | 否 | 散列落盘名（主键） |
| name | VARCHAR(255) | 否（默认 `''`） | 原始文件名 |
| size | INTEGER | 否（默认 0） | 文件字节数 |
| uploadedBy | VARCHAR(64) | 否（默认 `''`） | 上传账号 username（存量回填为空） |
| createdAt | VARCHAR(32) | 否（默认 `''`） | `YYYY-MM-DD HH:MM`（同 `logs.time` 风格） |

建表方式：`Base.metadata.create_all`（新表，无 ALTER 迁移需求）。

写入点：
- `POST /api/upload` 落盘成功后 `services.add_file_meta(...)`（上传非产品操作，**不写 OpLog**）。
- 启动 `main.py::_backfill_file_meta()` **幂等回填**（`file_meta` 为空才执行）：扫描 `uploads/`，散列名文件若存在**内容相同（MD5）**的非散列（可读）文件则以其为原始名，否则 `name=自身名`；**纯数据库操作，不移动/重命名/删除 uploads 任何文件**。

---

## 主要表结构（摘要）

### assets（产品）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 主键（DB 自增，禁止手写） |
| code | VARCHAR(32) UNIQUE | 产品编号 `CH-{板块}-{3位序号}` |
| name/board/type/subject/unit | VARCHAR | 基本信息 |
| quantity | INTEGER | 产品总数 |
| lockedQty | INTEGER | 锁定数量 |
| shippedQty | INTEGER | 已交付数量 |
| repeatSale | BOOLEAN | 可重复售卖（不扣数量） |
| salePrice/soldAmount | FLOAT | 单价 / 累计销售金额（**元**，ADR-006；`pricingMode='amount'` 时 salePrice 仅参考值） |
| soldCount | INTEGER | 授权/销售次数 |
| pricingMode | VARCHAR(16) | 计价模式 `unit` / `amount`（ADR-008，2026-10-16 新增） |
| province/city/resolution/imageDate | VARCHAR/FLOAT | ⚠️ **已废弃（ADR-011）**：ADR-010 遥感三维字段，列保留不删（技术债），服务层不再读写；遥感售卖粒度见 `rs_items` 表 |
| status | VARCHAR(32) | `in_stock` / `all_sold`（自动判定） |
| inboundDate/expiryDate/perpetual/spec/saleDetail/featureDoc/contractFile/remark/updatedAt | - | 其它（featureDoc=功能清单附件 filename，2026-10-15 新增） |

可售数量 = `quantity - lockedQty - shippedQty`。

### projects（销售项目）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| code | VARCHAR(32) UNIQUE | `SP-{16位时间戳}`（2026-10-19 起；14 位 yyyyMMddHHmmss + 2 位随机，防同秒碰撞；存量 SP-001 式旧编号保留） |
| status | VARCHAR(32) | `pending` / `active` / `delivered` / `terminated`（后端状态机权威决定；`pending`=待审核，ADR-012 生态人员购物车结算产生，由 `POST /projects/{id}/review` 确认/驳回，无 schema 迁移） |
| expectedAmount/quoteAmount/contractAmount/paidAmount | FLOAT | 各口径金额（expectedAmount/contractAmount 为合同派生，2026-10-15 起） |
| rep | VARCHAR(64) | 生态人员（销售对接人姓名，展示字段） |
| creator | VARCHAR(64) INDEX | 实际登录下单的 username（2026-10-16 新增，幂等补列）；三个建单入口自动写入，存量项目为空。生态人员「仅可见自己下单项目」的判定依据（`services.user_sees_project`：creator==自己，存量回退 rep==自己姓名） |
| cartRefilled | BOOLEAN 默认 0 | 明细是否已回填购物车（ADR-027，2026-10-21 幂等补列）。撤销（`withdraw`）回填成功后置 1；`POST /projects/{id}/refill-cart`（重新提交）见 1 直接返回 `alreadyRefilled=true` 不重复回填，首次回填成功后置 1。历史已撤销项目在启动迁移中按「合同 remark 含撤销」置 1 |
| items | 关系 | `ProjectItem`，cascade delete-orphan |
| contracts | 关系 | `Contract`，cascade delete-orphan（2026-10-15 新增） |

### contracts（销售记录，2026-10-15 新增；表名/编号保留，界面名 ADR-013 起为「销售记录」）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| code | VARCHAR(32) UNIQUE | `HT-{16位时间戳}`（2026-10-19 起，同 SP 方案） |
| projectId | INTEGER INDEX | 归属项目 |
| customer/subject | VARCHAR | 销售记录客户 / 签约主体（ADR-013：主体全一致→该值，混合→空=多主体） |
| contractAmount | FLOAT | 合同金额（元，ADR-006） |
| status | VARCHAR(32) | `pending` / `active` / `delivered` / `terminated`（`pending`=待审核，ADR-012，与项目同批迁移） |
| remark/createdAt/updatedAt | - | -（驳回时 remark 留痕「驳回：{原因}」） |

### project_items（项目明细）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| project_id | INTEGER FK→projects.id | 归属项目 |
| contractId | INTEGER NULL INDEX | 所属合同（2026-10-15 新增；新数据必填，存量 NULL） |
| assetId | INTEGER NULL | 关联产品（空=待关联产品 `pending_asset`） |
| qty/price/amount | INTEGER/FLOAT | `amount = round(price*qty, 4)`（后端权威重算） |
| status | VARCHAR(32) | `pending_asset`/`pending_amount`/`locked`/`confirmed`/`shipped`/`released`（`pending_amount` 现不再产生） |
| locked | BOOLEAN | 下单时刻该产品是否真实加锁（= 非 repeatSale；ADR-011 起明细行 = 非**明细** repeatSale）。repeatSale 产品下单只记 `status='locked'` 但不加锁；交付/终止/编辑释放锁定均以此区分「真锁过要释放」与「从未锁过不可写 cancel_release 幽灵流水」。存量数据默认 `0`（未锁过，语义正确）；2026-10-15 幂等迁移补列 |
| itemId | INTEGER NULL INDEX | 遥感数据明细（ADR-011，2026-10-16 新增）：非空行 qty 恒 1、amount=明细 price 权威、锁定/交付按明细 repeatSale；存量/非遥感行 NULL |
| lockedDate/confirmedDate/shippedDate/deliveryReq | - | - |

### rs_items（遥感数据可售明细，ADR-011，2026-10-16 新增）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| assetId | INTEGER INDEX | 父产品（`type='遥感数据'` 容器行） |
| province/city | VARCHAR(64) | 省（必填）/ 市（可空 `''`） |
| resolution | FLOAT | 精度（米），> 0 |
| saleMonth | VARCHAR(7) | 售卖月份 `YYYY-MM` |
| price | FLOAT | 单价，整数元/份（元口径） |
| repeatSale | BOOLEAN | 默认 1（true=只计次不扣量；false=锁父产品数量） |
| createdAt/updatedAt | VARCHAR(32) | `YYYY-MM-DD HH:MM` |

唯一性 `(assetId, province, city, resolution, saleMonth)` 服务层判重（无 DB 约束）。引用完整性：`project_items.itemId` / `cart_items.itemId` 有引用时禁止删除（400「该明细存在销售关联，无法删除」）；父产品删除时级联清理（delete_asset 通过引用校验后才可达）。

### outbounds（交付）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| code | VARCHAR(32) UNIQUE | `CK-{4位序号}` |
| projectId/assetId | INTEGER | 关联项目/产品（普通列，非外键） |
| contractId | INTEGER NULL INDEX | 关联合同（2026-10-15 新增；合同交付自动交付时非空） |
| projectItemId | INTEGER NULL INDEX | 关联项目明细（2026-10-20 FIX-20261020-#7 新增；合同交付时非空，手动补录/存量为 NULL，撤销交付据此精确定位明细） |
| qty/amount | INTEGER/FLOAT | 金额 4 位小数 |
| status | VARCHAR(16) | `done` / `reverted` |

### 其它表

`flows`（产品流水）、`logs`（操作日志，见上）、`base_records`、~~`deliverable_templates`~~（已删除，ADR-024）、`category_units`、`asset_deliverables`（2026-10-21 起含 `file` 附件列，ADR-024）、`cart_items`、`file_meta`（上传文件原名映射，见上）。

---

## 编号与自增约定（2026-10-14 修复）

- 所有需要「拼 code」的自增表（assets/projects/outbounds）**不再手工指定主键**：`db.add(obj) → db.flush()` 由 SQLite 生成 id，再据此拼写 code。
- 编号格式不变：`CH-{板块}-{3位}`、`SP-{16位时间戳}`（2026-10-19 起）、`CK-{4位}`。
- 存量数据衔接：本库未启用 `AUTOINCREMENT`（无 `sqlite_sequence` 表），SQLite 默认取 `max(rowid)+1`，与既有 `max(id)` 连续，故 flush 生成的 id 与删除前序列自然衔接，不会重复。

## 约束说明（trade-off）

- 未新增数据库外键（SQLite 迁移风险高），产品删除的引用完整性改由 `services.delete_asset` 服务层校验实现同等约束。
- `Outbound.projectId` / `ProjectItem.assetId` 为普通整型列，非外键；删除项目时交付单不物理删除（保留审计），仅置 `reverted`。
