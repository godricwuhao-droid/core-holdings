# 蜂云资产管理平台（core-holdings）

面向五大业务板块（**具身智能 / 卫星服务 / 软件库存 / 硬件库存 / 算力服务**）的**资产入库、库存、销售、出库全流程管理**平台：资产台账、销售项目、购物车下单、出库记录、交付物与基础资料一体化，内置三角色权限与操作审计。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + Uvicorn · SQLAlchemy 2.0 · **SQLite**（零外部依赖，标准库实现 JWT HS256）· Pydantic 2 |
| 前端 | Vue 3.5（`<script setup>`）· TypeScript 5.6 · Vite 5 · Element Plus · Vue Router 4 · axios · Univer（售卖内容明细内嵌电子表格） |
| 部署 | 本地部署（前后端分离，不使用容器） |

## 快速开始

### 后端（端口 8000）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

首次启动自动建表并写入种子数据（资产 / 供应商 / 分类单位 / 交付物模板，含遥感数据容器资产与可售明细演示），生成 SQLite 库文件 `backend/core_holdings.db`（已 gitignore）。

### 前端（端口 5173）

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

Vite 已将 `/api` 代理到 `:8000`，浏览器访问 `http://localhost:5173`。

### 登录

- 默认管理员：`admin` / `123456`（**首次使用请立即在「基础设置 → 账号与审计」修改密码**）
- 由 admin 创建其他角色账号

## 功能模块

| 模块 | 说明 |
|---|---|
| 首页概览 | 资产/销售统计、临期待办 |
| 资产管理 | 五板块资产列表（筛选/快览抽屉，抽屉为统一五段式：产品清单/关键信息/可售明细(仅遥感容器)/交付物/最近动态，对外不展示累计售卖金额）、创建/编辑（含文件上传）、资产详情（基本信息/销售内容明细/交付物/操作记录等页签；遥感容器资产含「可售明细」页签） |
| 卫星服务 · 遥感数据 | **父资产 + 可售明细两层结构**（ADR-011）：列表为 1 个容器资产，明细按 **省（可含市）× 精度 × 月份** 唯一维护（每份明细一个整数元单价，默认可重复售卖、只计次不扣量）；加购/登记销售通过**树状明细选择**（省→精度→月份）逐份下单 |
| 销售管理 | 销售项目（三步表单 + 状态流转）、出库记录（自动生成/补录/撤销）、购物车（**按登录用户隔离**、行级客户、结算按客户分组生成合同） |
| 基础设置 | 交付物设置、生态人员、**账号与审计**（admin 专属：账号 CRUD + 审计日志） |

## 权限体系

| 角色 | 菜单 | 写操作 |
|---|---|---|
| **admin** | 全部（含「基础设置」组：交付物/生态人员/账号与审计） | 全部 |
| **editor**（可编辑） | 业务菜单全部，**无「基础设置」** | 业务写操作全部可执行 |
| **viewer**（生态人员，只读） | 业务菜单全部（含购物车，带角标），**无「基础设置」** | **下单链路全放行**（单加/批量加购/改客户/改数量/删除行/清空/结算/直接下单，后端 `require_order` 认证即可）；资产维护类写操作禁用 + tooltip 提示，前端 axios 拦截，后端 403 兜底 |

- 认证：JWT Bearer（HS256，标准库实现零依赖，默认 7 天过期，密钥 `JWT_SECRET` 环境变量，缺省内置开发值）
- 购物车**按登录用户隔离**（ADR-009）：各账号购物车互不可见，结算只清空本人行
- 审计：登录/登出、全部写操作记录入独立 `audit_logs` 表，admin 可在「账号与审计」查看
- 前端：登录页 + 路由守卫（登录态 + 角色拦截）+ axios 拦截器；直达 URL 访问受限页面会被拦回首页

## 核心业务规则

- **两阶段销售交付**：
  - **下单**（购物车结算 / 直接下单 / 手动建项目）→ 项目「进行中」+ **锁定库存**（`lockedQty`，只占可售、不扣实物）
  - **交付**（人工将项目置「已完成」）→ 扣减 `shippedQty` + 累加 `soldAmount/soldCount` + **自动生成出库记录**（`CK-xxxx`）
  - **终止/删除项目** → 完整回滚：释放锁定 / 撤销该项目已完成出库 / 回退售出数量与金额
- **库存口径**：`可售 = quantity − lockedQty − shippedQty`（非 repeatSale）；状态两态：**库存可售 / 暂无库存**
- **可重复售卖（repeatSale）**：授权/算力类资产不受库存限制，销售只计次不扣量；开启后该资产锁定自动清零（编辑保存触发，带审计）
- **金额口径**：全程**元**（库内 / 接口 / 展示均为元，前端展示 ¥ + 千分位 + 两位小数）；`amount = price × qty`（Decimal 精确到分）由**后端权威重算**；包量计价资产（`pricingMode='amount'`，如卫星 Token）以**合同金额（整数元）为权威输入**，单价为派生展示值（元/万Token 参考口径，ADR-008）
- **遥感数据售卖**（ADR-011）：容器资产本身不可加购/下单，售卖单位是其下的**可售明细**（`rs_items`：省/市 × 精度 × 月份唯一）；明细行购物车数量恒 1，金额 = 明细单价（后端权威，忽略前端传值）；明细默认可重复售卖（只计次不扣量）；有销售关联的明细禁删
- **状态机单一入口**：项目状态变更只走 `PATCH /projects/{id}/status`；`POST/PUT` 不受理 status；已完成/已终止项目不可编辑
- **一致性保障**：写操作单事务（建项目→交付→清空购物车原子完成）、库存前置校验（同资产多明细聚合防超卖）、被引用资产禁删（先终止项目/撤销出库）

## 目录结构

```
core-holdings/
├── backend/
│   ├── main.py                 # 入口：建表 + 幂等迁移 + seed + 装配路由
│   ├── requirements.txt
│   ├── core_holdings.db        # SQLite 库（运行后生成，gitignore）
│   ├── uploads/                # 上传文件（gitignore）
│   └── src/
│       ├── database.py         # SQLite 引擎 / 会话
│       ├── models.py           # ORM：Asset/Project/Contract/ProjectItem/Outbound/Flow/Log/User/AuditLog/RsItem...
│       ├── schemas.py          # Pydantic 模型（camelCase，与前端 types.ts 一一对齐）
│       ├── services.py         # 业务规则：状态判定/锁定/交付/出库/撤销/审计/鉴权辅助
│       ├── seed_data.py        # 种子数据
│       └── routers/api.py      # REST 路由（/api：bootstrap + 资源 CRUD + auth/users/audit-logs）
├── frontend/
│   └── src/
│       ├── api/index.ts        # 唯一数据出入口：axios + 响应式 db 镜像 + refresh()
│       ├── auth.ts             # 登录态 / 角色 / canWrite / isAdmin
│       ├── constants.ts        # 分类单位 / 功能清单
│       ├── components/         # UniverSheet / SalesOrderDialog 等
│       ├── layouts/MainLayout.vue  # 顶栏 + 角色化侧边菜单
│       ├── router/index.ts     # 路由 + 登录/角色守卫
│       ├── styles/global.css   # 全局设计体系（色彩 token + 骨架类）
│       ├── types.ts            # 领域类型与状态字典（前端单一事实来源）
│       └── views/              # dashboard / assets / sales / cart / settings / login
├── docs/                       # 变更日志（前后端）+ API 文档
└── design.md / 资产情况.md      # 设计说明
```

## 文档

- **`docs/architecture.md` — 架构与规范全景（当前生效版，二次开发/新会话必读）**：数据流、核心业务规则、遥感数据模型、权限矩阵、UI 硬约束（弹窗/抽屉/对外展示口径）、ADR 索引、技术债清单
- `docs/adr/` — 架构决策记录（ADR-008 包量定价 / ADR-009 购物车用户隔离 / ADR-011 遥感数据两层模型）
- `docs/backend/changelog.md` / `docs/frontend/changelog.md` — 变更日志（含 Breaking 标注）
- `docs/backend/api.md` — 接口清单与语义
- `docs/backend/database.md` — 数据模型

## ⚠️ 注意事项

1. **默认密码**：`admin/123456` 为初始凭据，**生产使用必须修改**；生产环境请通过环境变量设置 `JWT_SECRET`。
2. **数据文件不入库**：`core_holdings.db` 与 `uploads/` 已 gitignore。克隆后首次启动自动建表 + 写**示例种子数据**；迁移真实数据请自行拷贝库文件与 uploads 目录。
3. **开发模式运行**：当前为本地 dev 部署（uvicorn `--reload` + Vite HMR），未做容器化；生产化建议 Nginx 反代 + 前端 `build` 静态托管（本仓库不含生产部署配置）。
4. **测试账号**：库中可能存在 `editor`/`viewer`（123456）测试账号，如不需要请在「账号与审计」删除。
5. **金额单位**：数据库 / 接口 / 展示金额字段均为**元**（前端展示 ¥ + 千分位 + 两位小数）——二次开发时勿引入其它金额口径。
6. **对外展示口径**：资产管理列表与快览抽屉属对外页面，**只展示销售单价，不展示累计售卖金额**（soldAmount 汇总仅限详情页/销售管理等内部视角）。
7. **SQLite 约束**：单写并发模型，适合内网小团队规模；如需多实例/高并发请更换 Postgres（SQLAlchemy 层已隔离，`DATABASE_URL` 环境变量可切换）。

## License

Internal use — 公司内部项目，未开放。
