# 蜂云产品及服务平台（core-holdings）— 架构与规范全景（当前生效版）

> 本文档是**新会话/新成员的入口**：所有当前生效的架构决策与硬约束的唯一事实来源。
> 历史变更看 changelog；被取代的决策以 `docs/adr/` 中的 Superseded 标记为准。
> 与本文档冲突的旧文档、旧记忆、旧注释，一律以本文档为准。
>
> 最后更新：2026-10-19

## 1. 系统定位与技术栈

面向五大业务板块（具身智能 / 卫星服务 / 软件产品 / 硬件产品 / 算力服务）的可售卖产品及服务平台：产品台账、数量、销售（合同）、购物车下单、交付、交付物一体化，三角色权限 + 审计。

> **对外术语口径（2026-10-19 起）**：平台是对外产品平台，全部用户可见文案不再出现「资产/库存」字样——内部"资产"= 面向客户的"产品"（板块按产品/服务划分）；库存按语义映射（库存数量=可用数量、库存可售=可售、暂无库存=已售罄、锁定/扣减库存=锁定/扣减数量…）。完整映射与执行清单见 `docs/asset-inventory-rename-checklist-20261019.md`。代码标识符（assetId、/assets 路径、asset_change 等）保持不变；历史日志/ADR 不回溯改写。

- 后端：FastAPI + SQLAlchemy 2.0 + **SQLite**（`backend/`，端口 8000，uvicorn --reload）；JWT HS256 标准库自实现；Pydantic 2，字段 **camelCase**（与前端 types.ts 一一对齐，DB 列名亦 camelCase）
- 前端：Vue 3.5 `<script setup>` + TS + Vite 5 + Element Plus + axios + Univer（`frontend/`，端口 5173，/api 代理 :8000）
- **非 mock**：前后端全量对接，本地 dev 运行（HMR / --reload 自动生效）；禁止自动构建/部署（用户明令时才执行）

## 2. 数据流（前端）

`src/api/index.ts` 是**唯一数据出入口**：axios 请求 + 响应式 `db` 镜像（由 `GET /api/bootstrap` 全量快照填充，含 rsItems）+ 写操作后 `refresh()`。页面不直接发请求；预填类页面须 `await refresh`。

## 3. 核心业务规则（后端权威，`backend/src/services.py`）

| 规则 | 内容 |
|---|---|
| 两阶段交付 | 下单 → 项目"进行中" + 锁定数量（lockedQty 只占可售不扣实物）；交付（合同置 delivered）→ 扣 shippedQty + 累加 soldAmount/soldCount + 自动生成交付单（CK-xxxx）；终止/删除 → 完整回滚 |
| 数量口径 | 可售 = quantity − lockedQty − shippedQty（非 repeatSale）；状态两态：可售 / 已售罄 |
| repeatSale | 只计次不扣量；开启后锁定自动清零 |
| **金额口径** | **全程"元"**（库内/接口/展示，前端 ¥+千分位+两位小数）。禁止"万"字、禁止 ×10000 桥接。`amount = price × qty`（Decimal）后端权威重算 |
| **包量定价（ADR-008）** | `Asset.pricingMode`：`'unit'`（默认）/ `'amount'`（卫星 Token 登记自动置）。amount 模式：销售明细**合同金额（整数元）为权威输入**（后端校验 int>0，否则 400），跳过 price×qty 重算，price 仅作派生展示（元/万Token 参考，2026-10-16 起不带"约"）；购物车 amount 模式行需填合同金额（`cart_items.amount`，经 `PUT /cart/{id}` **必须带 qty** 提交，缺 qty=0 会删行）；checkout 不再传 items，金额已在 cart_items 持久化 |
| 销售记录结构（ADR-007 → ADR-013） | 项目内**每个产品一条销售记录**（HT-xxxx，界面名「销售记录」；代码/表名/路由仍为 contracts），**允许多主体**（记录主体=各行主体全一致→该值，混合→空）；项目状态/金额由销售记录派生；状态变更走 `PATCH /contracts/{id}/status` |
| 状态机 | 项目状态只走 PATCH 状态接口（待审核项目例外：只走 `POST /projects/{id}/review`，ADR-012）；生态人员购物车结算建「待审核」（锁定照常），商务确认（可改价、实际价写回平台挂牌价）或驳回；已完成/已终止不可编辑 |
| 一致性 | 写操作单事务；数量前置校验（同产品多行合计防超卖）；被引用产品禁删 |
| **生态人员可见性（2026-10-16）** | viewer 仅见**自己下单**的销售项目：`Project.creator`（登录 username，三建单入口自动写入）== 自己；存量 creator 为空回退 `rep in (自己姓名, username)`。`bootstrap` 过滤 projects/contracts，前端全视角（列表/详情/产品「销售关联」）天然过滤；viewer 可编辑自己项目基本信息（rep 恒忽略）+ 终止（含撤销 delivered 交付），交付/删除/新建空项目仍仅商务/管理员 |

## 4. 遥感数据模型（ADR-011，Supersedes ADR-010）

**父产品 + 可售明细两层**：
- 父产品（assets，type='遥感数据'）：容器，不可直接加购/下单；登记时表单隐藏"数量单价"卡（quantity=1/unit=份（可售明细）兜底），提示条在"产品类型"下方
- 明细（`rs_items` 表）：省/市（可空）× 精度（米，0.5–2）× **月份（YYYY-MM）** 同父产品下唯一；每份一个单价（整数元/份）；`repeatSale` 默认 true（只计次不扣量）
- 接口：`POST /assets/{id}/rs-items`、`PUT/DELETE /rs-items/{id}`（require_editor；有 project_items/cart_items 引用的明细禁删 400）
- 售卖：明细行购物车数量恒 1（qty≠1 → 400），判重键 (userId, assetId, itemId, customer)；金额 = 明细单价后端权威重算；`project_items.itemId` / `cart_items.itemId` 关联
- 交互：加购/登记销售走 `RsItemPicker.vue` 树状选择（省→精度→月份·单价）；产品详情"可售明细"页签 CRUD；批量加购按钮对遥感父产品**分流拦截**（不进购物车，提示逐份选择，保留勾选）
- 技术债：assets 表 ADR-010 的 4 列（province/city/resolution/imageDate）已废弃（列保留，schema/代码不再使用）；手动交付（POST /outbounds）未做明细感知（前端无该入口）

## 5. 购物车与权限

- **购物车按登录用户隔离（ADR-009）**：全部购物车端点用登录用户 id；bootstrap.cart 只返回本人行；结算只清本人
- 权限矩阵：admin（全部含基础设置）/ editor（业务写全放行，无基础设置）/ viewer（生态人员）
- **下单链路 = require_order（认证即放行）**：viewer 可 单加/批量加购/改客户/改数量/删行/清空/结算/直接下单；产品维护类（增删改产品、明细维护、交付物、基础资料、交付）= require_editor；账号/审计 = require_admin。前端 canWrite/isLoggedIn 与后端一致（**不要再加 viewer 降级分支**）
- **自己项目有限操作（2026-10-16，require_order + 服务层归属校验）**：`PUT /projects/{id}`、`PATCH /projects/{id}/status`（仅 terminated）、`PATCH /contracts/{id}/status`（仅 terminated，含撤销 delivered 交付）对 viewer 放开但**限自己下单项目**（`user_sees_project`），viewer 的 `rep` 入参恒忽略；越权 403、交付 400。viewer 前端入口：侧边「销售项目」菜单 + 列表/详情/编辑页（`isViewer` 分支只放宽「编辑/终止」，新建/删除/交付仍禁用）
- 审计：写操作与登录/登出入 audit_logs
- **文件端点** `GET /api/files/{filename}`：JWT 双通道鉴权（`Authorization` 头或 `?token=` 查询参数，iframe/img 无法带头所以前端 fileUrl 统一拼 token）；`?inline=true` 返回 `Content-Disposition: inline`（预览 iframe/img 用），缺省 attachment（下载用）。前端统一走 `fileUrl(filename, inline?)`，勿手拼 /api/files URL

## 6. UI 硬约束（新页面/改页面必须遵守）

- 色彩 token（global.css :root）：主蓝 #1769D4、背景 #F5F7FB、主文字 #1A2E4E、正文 #425774、辅助 #71829A、边框 #D8E1EC、可售绿 #0C7B51/#EAF8F1、可重复紫蓝 #4E63A8/#EEF0FF、建设中橙 #A86514/#FFF5E7；**禁用 Element Plus 默认色板**（#409EFF/#67C23A 等，EP 变量已在 global.css 全量覆盖）
- 列表页骨架：面包屑 + 22px 标题 + 13px 说明 + 右侧主按钮（.page-head）→ 统计卡 → 浅蓝 .info-bar → 白卡表格；数字/金额列 `align="center"`（禁 right）、列宽 90–150px
- 表单页骨架：.back-link → 22px 标题+说明 → .form-card（18px 内边距 + .block-head）→ 2/3/4 列 form-grid → 右对齐 .bottom-actions（不悬浮）；内容区 max-width 1080px
- **弹窗规范（global.css 共享类）**：表单类 `.dlg-form`（640px）；选择器/大表单 `.dlg-wide`（880px）；均 max-width 92vw；标题 16px/600；body padding 20px；footer 上分割线 + 按钮右对齐间距 12px；label 96px 右对齐不换行、控件 100% 宽、间距 18px；**金额输入 el-input-number 必须 `:controls="false"`（无步进按钮）**，数量类可保留
- **产品列表抽屉（全类型统一，ADR-011 后）**：零指标卡；区块 = 数量进度（仅扣量产品，图例承担数字）→ repeatSale 说明条（仅 repeatSale 非容器）→ 产品清单 → 关键信息（统一 5 行：销售单价/产品说明/登记时间/有效期/备注有值；repeatSale 追加 数据规模+售卖次数；容器追加 明细份数+已售次数；容器单价行显示"按明细定价"；不重复展示主体/状态）→ 可售明细（仅容器）→ 交付物 → 最近动态（全类型：日志+流水合并倒序前 8 条细线时间线）；分区 15px 标题 + 段弱说明
- **对外展示口径**：产品及服务列表 + 抽屉属对外页面——**只展示销售单价，禁止展示累计售卖金额（soldAmount 汇总）**；详情页/销售管理/首页等内部视角不受限
- 提示一律浅蓝 .info-bar，禁用警告黄/错误红做提示；胶囊标签 999px、卡片 10px、按钮 7px 圆角（仅实心主按钮轻蓝投影）
- Token 数量展示用 `formatTokens`（3 亿/13700 万）；金额展示用 `formatMoney`

### 边框与间距纪律（防"边框重叠/双线"，写 UI 前必读，global.css 已按此实现）

| 规则 | 现状依据（global.css） | 反例 |
|---|---|---|
| **分隔线只留一条 1px**：区块之间用 `--divider-color`（#E7EDF5）单分隔线；容器与区块不同时各自带边框 | 表格外框只留左/下（`.el-table--border` 去 top/right/竖线）；block-head 用 `padding-bottom 12px + border-bottom` 且输入框自带 `--input-border`，二者靠 16px margin 隔开 | 容器 border-bottom 紧贴区块 border-top → 双线重叠 |
| **末子元素 margin-bottom 归零**：`* + *` 型间距写法必须在最后一个子元素上清零 | `.form-grid > * + * { margin-bottom: 18px } ... > :last-child { margin-bottom: 0 }`（.dlg-form / .form-grid 同款） | 末项留 margin → 卡片底部出现双倍间距 |
| **卡片内间距统一 18px**（form-card）、页面级区块间距 16–20px；抽屉 header/footer 靠 border + 各自 padding，**header 不再加 margin-bottom** | `.form-card { padding: 18px }`；`.asset-drawer .el-drawer__header { margin-bottom: 0; border-bottom }`；dialog body 20px / footer 16px 20px + 上分割线 | 子区块各自再加大 margin，与父容器 padding 叠加留白失控 |
| **边框色只用两个 token**：`--border-color` #E1E8F1（卡片/外框）、`--input-border` #D8E1EC（输入控件）、`--divider-color` #E7EDF5（内部分隔线）；hover 蓝 #1769D4 | :root token + EP 变量全量覆盖 | 硬编码 #dcdfe6（EP 默认灰）、#E4E7ED 等第二套灰 |
| **圆角只允许 4 档**：999px 胶囊 / 10px 卡片 / 8px 输入与次级块 / 7px 按钮（实心主按钮可加轻蓝投影） | 全局各组件已统一 | 随手写 4px/12px 混合 |
| **表格无竖线、行 hover #F8FBFF**；表头背景 #F8FAFC；行高靠 9px 0 padding + border-bottom，不再用 el-table 默认 12px 行边距 | `.el-table` 覆盖段 | 保留 EP 默认 `--border` 全边框样式 |
| **新增/改动任何区块后自查**：①相邻两块之间是否出现两条贴近的线；②容器内最后一个子元素是否留了多余底部间距；③是否引入 token 之外的颜色/圆角 | — | — |

## 7. ADR 索引

| ADR | 状态 | 主题 |
|---|---|---|
| ADR-008 | Accepted | 卫星 Token 包量定价（pricingMode='amount'，合同金额整数元权威） |
| ADR-009 | Accepted | 购物车按登录用户隔离 + viewer 下单链路权限对齐 |
| ADR-010 | **Superseded by ADR-011** | 遥感数据三维字段挂 assets（已废弃，勿参考实现） |
| ADR-011 | Accepted | 遥感数据"父产品 + 可售明细"两层模型（省×精度×月份） |
| ADR-012 | Accepted | 生态人员下单「待审核」流程（pending 状态 + 商务改价确认/驳回，仅 viewer 购物车结算进流程） |
| ADR-013 | Accepted | 销售记录：一资产一条记录 + 多主体（移除同主体校验）+ 界面「合同」改称「销售记录」（代码/表名/编号不变） |

## 8. 文档地图与变更流程

- `docs/adr/` — 架构决策（新决策先写 ADR 再开发）
- `docs/backend/{api.md, database.md, changelog.md}` — 后端契约/表结构/流水
- `docs/frontend/changelog.md` — 前端流水
- `README.md` — 项目入口（与本文档保持同步）
- `docs/asset-inventory-rename-checklist-20261019.md` — 「资产/库存 → 产品及服务」术语切换清单（含映射总表与执行记录，2026-10-19 已执行）
- 变更记录格式：`| 日期 | 类型 | 变更内容 | 影响文件/范围 | 关联任务/ADR | 备注 |`；Breaking 加 ⚠️
- 金额/单位改动禁止混入"万"字（grep `10000|万元` 必须 0 命中）

## 9. 已知边界与技术债（勿当作 bug 重复修，改动前先确认）

1. assets 表 4 个 ADR-010 废弃列（列保留，代码停用）
2. 手动交付 POST /outbounds 未做遥感明细感知（前端无入口）
3. 存量库 category_units 表无"遥感数据"条目（前端走 constants.ts，无影响）
4. 算力服务板块只读占位（建设中）；预留页占位
5. 开发态：admin/123456、editor/viewer 测试账号；backend 下有 .db.bak 与一次性迁移脚本
6. 购物车行"数量"语义：普通产品可调（受行级合计≤可售约束）；遥感明细行恒 1
