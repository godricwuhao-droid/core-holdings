# 数据库结构与变更

> SQLite（`backend/core_holdings.db`），ORM：SQLAlchemy 2.x 声明式。字段 camelCase，与前端 `types.ts` 对齐。
> 变更方式：`main.py::_ensure_migration()` 轻量迁移（`ALTER TABLE ... ADD COLUMN`，幂等判断），`Base.metadata.create_all` 不会改已存在的表。

---

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
| qty/amount | INTEGER/FLOAT | 金额 4 位小数 |
| status | VARCHAR(16) | `done` / `reverted` |

### 其它表

`flows`（产品流水）、`logs`（操作日志，见上）、`base_records`、`deliverable_templates`、`category_units`、`asset_deliverables`、`cart_items`、`file_meta`（上传文件原名映射，见上）。

---

## 编号与自增约定（2026-10-14 修复）

- 所有需要「拼 code」的自增表（assets/projects/outbounds）**不再手工指定主键**：`db.add(obj) → db.flush()` 由 SQLite 生成 id，再据此拼写 code。
- 编号格式不变：`CH-{板块}-{3位}`、`SP-{16位时间戳}`（2026-10-19 起）、`CK-{4位}`。
- 存量数据衔接：本库未启用 `AUTOINCREMENT`（无 `sqlite_sequence` 表），SQLite 默认取 `max(rowid)+1`，与既有 `max(id)` 连续，故 flush 生成的 id 与删除前序列自然衔接，不会重复。

## 约束说明（trade-off）

- 未新增数据库外键（SQLite 迁移风险高），产品删除的引用完整性改由 `services.delete_asset` 服务层校验实现同等约束。
- `Outbound.projectId` / `ProjectItem.assetId` 为普通整型列，非外键；删除项目时交付单不物理删除（保留审计），仅置 `reverted`。
