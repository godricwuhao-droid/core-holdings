# CODEBUDDY.md — core-holdings 项目记忆

> **新会话开始先读**：本文件（当前进度/决策/约定/坑）+ `README.md`（概览/快速开始）+ `docs/architecture.md`（架构全景 + **ADR 索引**，权威、逐条含 trade-off/可逆性）。
> 与代码不一致时，以**代码 + `docs/architecture.md`** 为准，并回头修正本文件。

## 一、项目一句话
蜂云产品及服务平台：面向五板块（**具身智能/卫星服务/软件/硬件/算力**）的产品登记 → 销售（购物车下单）→ 交付全流程管理。
后端 **FastAPI + SQLAlchemy 2.0 + SQLite**（:8000，标准库实现 JWT）/ 前端 **Vue 3.5 + TS + Element Plus + Vite**（:5173）。本地部署、前后端分离、**金额全程「元」**。

## 二、当前进度（截至 2026-11-05）
- **ADR-050~057 全部 Accepted 并已 git 提交**：commit `b180ea1`，分支 `feat/pricing-discount-timelines`，作者 `DevOps <devops@xhwltech.com>`。
- **测试数据已清理**（ADR 开发期 `QA05x-`/`FE057-` 项目、产品、测试账号均已删）；备份 `backend/backups/core-holdings-20261105-074052.db`（恢复=停服→`cp` 回 `backend/core_holdings.db`→起服）。
- 工作区当前仅 `.gitignore` +1 行（`backend/backups/`）**未提交**（等确认）。
- 每个 ADR 的决策/理由详见 `docs/adr/ADR-0XX.md` + `docs/architecture.md` 索引。

## 三、最近关键决策（ADR-050~057 摘要，细节读 ADR 文件）
- **ADR-051 权限升级五角色**（静态集中式）：`admin` / `supervisor`(商务主管) / `editor`(商务) / `viewer`(生态) / `finance`(财务)。能力=角色→权限点，数据域=角色→行级（editor 仅名下、supervisor/admin 全部、viewer 仅自己、finance 无）；**商务主管分配制**（未分配池 `businessOwner=""` 仅 admin/supervisor 可见，`claim` 分配/改派）。
- **ADR-055/056 销售项目列表**：服务端分页 `GET /projects` + **服务端排序**（status 用 SQL `case` 按生命周期档位 pending→active→delivering→delivered→terminated、金额/日期/编号；**恒定 `id.desc()` 兜底保翻页稳定**）。
- **合同级部分操作（ADR-056 §2 勾选驳回 / ADR-057 部分确认）**：**核心派生规则——只要有 pending 合同，项目就保持 pending（可续审）**；`_derive_project_status` 已按此统一（`[active,pending]`、`[terminated,pending]` 等均 → pending）。
- **ADR-057 审核订单页美化**：每合同一张表（合同头+`el-table`）+ **sticky 底部条** + **每合同勾选（默认全选）** 控制部分确认/驳回；确认走 `review` 加**可选 `contractIds`**（缺省=整单，向后兼容）；驳回复用 `reject-contracts`。
- **ADR-048 金额精度**：放开到**最多 6 位小数**（全链路 Decimal 量化 1e-6）。

## 四、必须遵守的约定
1. **UI 硬规范**：遵循项目 skill **`core-holdings-ui`**（`.codebuddy/skills/core-holdings-ui/`）——主蓝 `#1769D4`、圆角仅 4 档(999/10/8/7)、边框仅 3 token、**金额/数字列 `align="center"`（禁 right）**、`el-input-number :controls="false"`、`formatMoney`（¥+千分位+最少 2 位最多 6 位）、信息条浅蓝 `.info-bar`；**禁用 Element 默认色板**。
2. **文档流程**：架构决策→`docs/adr/ADR-0XX.md` + 更新 `docs/architecture.md` 索引；实现→对应 `docs/{backend,frontend,qa}/changelog.md`（统一表格格式，Breaking 标 ⚠️）；QA→`docs/qa/bug-tracker.md`。**文档未更新 = 打回。**
3. **金额口径**：全程「元」，后端权威重算 `amount = price × qty`；**对外页面（产品列表/抽屉）不展示累计售卖金额**。
4. **状态机单一入口**：项目状态变更只走 `PATCH /projects/{id}/status`（**pending 项目例外只走 `POST /projects/{id}/review`**）；`POST/PUT` 不受理 status。
5. **两阶段销售交付**：下单→锁 `lockedQty`（不扣实物）；交付（置已完成）→扣 `shippedQty`+累加 `soldAmount/soldCount`+生成交付记录；终止/删除→完整回滚。`repeatSale` 产品只计次不扣量。

## 五、环境 / 命令
- **后端**：`cd backend && python3 -m uvicorn main:app --port 8000 --reload`（首次自动建表 + seed；库 `backend/core_holdings.db` 已 gitignore）。
- **前端**：`cd frontend && npm run dev`（:5173，`/api` 代理 :8000）。
- **前端类型检查**：`cd frontend && LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu npx vue-tsc -p tsconfig.app.json --noEmit`（**必须带 `LD_LIBRARY_PATH`**，否则报缺共享库）。
- **登录**：`admin` / `123456`；测试角色账号（sup01/fin01/biz01/biz02/eco01，密码 123456）**已在 2026-11-05 清理中删除**，如需可自建。
- **git**：仓库未配作者身份 → 提交用 `git -c user.name="DevOps" -c user.email="devops@xhwltech.com" commit ...`（沿用既有作者，**别改 git config**）。提交信息惯例 `feat: 描述（ADR-XXX）`，**常多个相关 ADR 合并一次提交**（见既有 log）。

## 六、已知坑 / 观察项
- **⚠️ README「权限体系」表已过时**（写的是 3 角色 admin/editor/viewer），实际是 **ADR-051 五角色**——以 ADR-051/代码为准，README 该表待更新。
- **SQLite 无外键 + id 复用** → 库中存在历史孤儿行（contracts/items/logs 等，属删前已存在的已知行为，非 bug）。
- **金额列对齐**：`core-holdings-ui` 规范写 center，但**购物车小计列历史用 right**（既有特例）；新表格跟规范用 center。
- **挂起 OBS 观察项**（未做，可后续单开 ADR）：OBS-01 手动补录交付不受剩余数量上限约束；OBS-ADR056-01 合同级「已驳回」tag 细分显示（现合同行 terminated 统一显示「已终止」，细分只在项目级 + 展开行 remark）。

## 七、文档地图
- `docs/architecture.md` — **架构全景 + ADR 索引**（新会话必读）
- `docs/adr/ADR-*.md` — 各决策详述（Status / Context / Decision / Consequences）
- `docs/backend/api.md` — 接口清单与语义；`docs/backend/database.md` — 数据模型
- `docs/{backend,frontend,qa}/changelog.md` — 变更日志；`docs/qa/bug-tracker.md` — 缺陷跟踪
- `design.md` — 设计说明；`README.md` — 概览 / 快速开始
