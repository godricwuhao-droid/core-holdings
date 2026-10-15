# 数据库结构与变更

> SQLite（`backend/core_holdings.db`），ORM：SQLAlchemy 2.x 声明式。字段 camelCase，与前端 `types.ts` 对齐。
> 变更方式：`main.py::_ensure_migration()` 轻量迁移（`ALTER TABLE ... ADD COLUMN`，幂等判断），`Base.metadata.create_all` 不会改已存在的表。

---

## 2026-10-14 变更

### OpLog（表 `logs`）新增列 `assetId`

| 列名 | 类型 | 可空 | 说明 |
|------|------|------|------|
| assetId | INTEGER | 是 | 关联资产 id；仅 `target='asset'` 的日志写入，其余为 NULL（存量数据也为 NULL） |

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
| action | VARCHAR(50) | 否 | 中文动作，如「新建销售项目」「撤销出库」 |
| target | VARCHAR(50) | 否 | 目标类型，如 `project` / `asset` / `outbound` / `base` / `template` / `deliverable` / `user` / `file` / `auth` |
| targetName | VARCHAR(120) | 否 | 目标名称（资产名/项目名/用户名等） |
| detail | VARCHAR(255) | 是 | 补充信息（如 `status=delivered`、登录失败原因） |
| time | VARCHAR(32) | 否 | `YYYY-MM-DD HH:MM` |

与既有 `logs`（OpLog，实体级流水）的关系：**分表、互不回填**。`logs` 表及其调用方行为完全不动；`audit_logs` 只记录带操作者身份的业务写操作与认证事件，写入点在 router 层统一 `record_audit`（业务 services 不改）。旧 logs 数据**不回填** audit_logs。

建表方式：`Base.metadata.create_all`（新表，无 ALTER 迁移需求）。

---

## 主要表结构（摘要）

### assets（资产）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | 主键（DB 自增，禁止手写） |
| code | VARCHAR(32) UNIQUE | 资产编号 `CH-{板块}-{3位序号}` |
| name/board/type/subject/unit | VARCHAR | 基本信息 |
| quantity | INTEGER | 资产总数 |
| lockedQty | INTEGER | 锁定数量 |
| shippedQty | INTEGER | 已出库数量 |
| repeatSale | BOOLEAN | 可重复售卖（不扣库存） |
| salePrice/soldAmount | FLOAT | 单价 / 累计销售金额（万元，4 位小数） |
| soldCount | INTEGER | 授权/销售次数 |
| status | VARCHAR(32) | `in_stock` / `all_sold`（自动判定） |
| inboundDate/expiryDate/perpetual/spec/saleDetail/contractFile/remark/updatedAt | - | 其它 |

可售数量 = `quantity - lockedQty - shippedQty`。

### projects（销售项目）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| code | VARCHAR(32) UNIQUE | `SP-{3位序号}` |
| status | VARCHAR(32) | `active` / `delivered` / `terminated`（后端状态机权威决定） |
| expectedAmount/quoteAmount/contractAmount/paidAmount | FLOAT | 各口径金额 |
| items | 关系 | `ProjectItem`，cascade delete-orphan |

### project_items（项目明细）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| project_id | INTEGER FK→projects.id | 归属项目 |
| assetId | INTEGER NULL | 关联资产（空=待关联资产 `pending_asset`） |
| qty/price/amount | INTEGER/FLOAT | `amount = round(price*qty, 4)`（后端权威重算） |
| status | VARCHAR(32) | `pending_asset`/`pending_amount`/`locked`/`confirmed`/`shipped`/`released`（`pending_amount` 现不再产生） |
| locked | BOOLEAN | 下单时刻该资产是否真实加锁（= 非 repeatSale）。repeatSale 资产下单只记 `status='locked'` 但不加锁；交付/终止/编辑释放锁定均以此区分「真锁过要释放」与「从未锁过不可写 cancel_release 幽灵流水」。存量数据默认 `0`（未锁过，语义正确）；2026-10-15 幂等迁移补列 |
| lockedDate/confirmedDate/shippedDate/deliveryReq | - | - |

### outbounds（出库）

| 列 | 类型 | 说明 |
|----|------|------|
| id | INTEGER PK | DB 自增 |
| code | VARCHAR(32) UNIQUE | `CK-{4位序号}` |
| projectId/assetId | INTEGER | 关联项目/资产（普通列，非外键） |
| qty/amount | INTEGER/FLOAT | 金额 4 位小数 |
| status | VARCHAR(16) | `done` / `reverted` |

### 其它表

`flows`（资产流水）、`logs`（操作日志，见上）、`base_records`、`deliverable_templates`、`category_units`、`asset_deliverables`、`cart_items`。

---

## 编号与自增约定（2026-10-14 修复）

- 所有需要「拼 code」的自增表（assets/projects/outbounds）**不再手工指定主键**：`db.add(obj) → db.flush()` 由 SQLite 生成 id，再据此拼写 code。
- 编号格式不变：`CH-{板块}-{3位}`、`SP-{3位}`、`CK-{4位}`。
- 存量数据衔接：本库未启用 `AUTOINCREMENT`（无 `sqlite_sequence` 表），SQLite 默认取 `max(rowid)+1`，与既有 `max(id)` 连续，故 flush 生成的 id 与删除前序列自然衔接，不会重复。

## 约束说明（trade-off）

- 未新增数据库外键（SQLite 迁移风险高），资产删除的引用完整性改由 `services.delete_asset` 服务层校验实现同等约束。
- `Outbound.projectId` / `ProjectItem.assetId` 为普通整型列，非外键；删除项目时出库单不物理删除（保留审计），仅置 `reverted`。
