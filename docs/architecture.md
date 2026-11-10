# 蜂云产品及服务平台（core-holdings）— 架构与规范全景（当前生效版）

> 本文档是**新会话/新成员的入口**：所有当前生效的架构决策与硬约束的唯一事实来源。
> 历史变更看 changelog；被取代的决策以 `docs/adr/` 中的 Superseded 标记为准。
> 与本文档冲突的旧文档、旧记忆、旧注释，一律以本文档为准。
>
> 最后更新：2026-10-22

## 1. 系统定位与技术栈

面向五大业务板块（具身智能 / 卫星服务 / 软件产品 / 硬件产品 / 算力服务）的可售卖产品及服务平台：产品台账、数量、销售（合同）、购物车下单、交付、交付物一体化，五角色权限（admin/supervisor 商务主管/editor 商务/viewer 生态/finance 财务，ADR-051）+ 审计。

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
| **金额口径** | **全程"元"**（库内/接口/展示，前端 ¥+千分位+**最少两位、最多 6 位小数**，尾随 0 截到两位，ADR-048）。禁止"万"字、禁止 ×10000 桥接。`amount = price × qty`（Decimal，量化 1e-6）后端权威重算；卫星 Token（amount 模式）单价展示走 `salePrice×1e6` 元/百万Token 口径（ADR-025，仅展示层） |
| **包量定价（ADR-008）** | `Asset.pricingMode`：`'unit'`（默认）/ `'amount'`（卫星 Token 登记自动置）。amount 模式：销售明细**合同金额（元，最多 6 位小数，ADR-048）为权威输入**（后端校验 >0 且 ≤6 位小数，否则 400），跳过 price×qty 重算，price 仅作派生展示（元/万Token 参考，2026-10-16 起不带"约"）；购物车 amount 模式行需填合同金额（`cart_items.amount`，经 `PUT /cart/{id}` **必须带 qty** 提交，缺 qty=0 会删行）；checkout 不再传 items，金额已在 cart_items 持久化 |
| 销售记录结构（ADR-007 → ADR-013 → ADR-016） | 项目内**每个产品（×客户）一条销售记录**（ADR-016：同产品多客户拆多条）（HT-xxxx，界面名「销售记录」；代码/表名/路由仍为 contracts），**允许多主体**（记录主体=各行主体全一致→该值，混合→空）；项目状态/金额由销售记录派生；状态变更走 `PATCH /contracts/{id}/status` |
| 状态机 | 项目状态只走 PATCH 状态接口（待审核项目例外：只走 `POST /projects/{id}/review`，ADR-012）；生态人员购物车结算建「待审核」（锁定照常），商务确认（可终审改价/改数量/改客户名/改**合同总价**（按比例分摊到明细，保持 `合同总额=Σ明细`），**不回写挂牌价**，ADR-018/ADR-050）或驳回；录签订时间进「交付中」（ADR-019）；已完成/已终止不可编辑。**状态变更唯一入口 = `_change_contract_status_core`**（交付前置条件在此守卫，合同级/项目级共用，ADR-032）；项目级批量「全量或全不」（任一合同不合规整体 400 并列出全部原因）；终止**按明细状态回滚**（shipped→撤销交付回退销量，locked→释放锁定，缺明细/产品→400 不静默）；派生 `{delivered,terminated}`→`delivered`（ADR-032） |
| 一致性 | 写操作单事务；数量前置校验（同产品多行合计防超卖）；被引用产品禁删（**含 delivered 引用**，ADR-032）；**下单校验单一出口**（`_create_project_core` 权威链：明细存在性→归属/qty→折扣→服务期限→参考区间→按产品聚合数量；unit 行单价也过区间校验；`contractAmount` 传值必须 = Σ 明细，ADR-029）；**并发**：checkout 幂等键 `requestId`（24h）、状态变更/数量扣减条件更新、不变量破坏显式 500 + 审计（无静默夹断，ADR-033）；**参考区间只约束下限**：购物车/结算（任何角色）金额可高于区间上限，仅拦低于下限；商务审核改价不受区间限制；仅商务手工建单仍双向校验（ADR-049，部分取代 ADR-037） |
| **订单撤销（ADR-026）** | `POST /projects/{id}/withdraw`（require_order）：仅 `pending`；下单人本人或 admin（存量回退 rep）；原因必填 ≤200 字；单事务 = 合同 pending→terminated（释放真实锁定 + cancel_release 流水 + remark「撤销：原因」）+ 项目 terminated + 解绑负责人 + 明细回填下单人购物车（复用 `_cart_add_inner`，**同键替换不累加**——ADR-042 §1 起；此前为累加）+ OpLog/审计；回填失败行降级不中断（原价回填/跳过并回报） |
| **交付物（ADR-024）** | 模板体系（`/settings/deliverables` 页 + `deliverable_templates` 表 + bootstrap 惰性生成）彻底下线；交付物实例仅详情页「交付物」页签手动增改；每项单个附件 `asset_deliverables.file`（upload 散列名；前端 accept 仅 pdf/docx/png/jpg/jpeg/gif/webp，禁 .doc）；抽屉与详情页两处点击预览（复用 FilePreview）；存量实例已一次性清空 |
| **生态人员可见性（2026-10-16，编辑权 2026-10-21 收回）** | viewer 仅见**自己下单**的销售项目：`Project.creator`（登录 username，三建单入口自动写入）== 自己；存量 creator 为空回退 `rep in (自己姓名, username)`。`bootstrap` 过滤 projects/contracts，前端全视角（列表/详情/产品「销售关联」）天然过滤；**viewer 订单提交后不可编辑（ADR-028）** + 可终止 + 可撤销/重新提交，交付/新建空项目仍仅商务/管理员，**删除项目仅管理员（ADR-040）**，**「重新提交」仅下单人本人 + 管理员（商务 editor 403，ADR-043）** |
| **资产主体（ADR-035）** | 主体清单单一事实来源 = `entities` 表（设置页 `/settings/entities` 维护，`POST/PUT/DELETE` require_editor，`GET` 登录即可）；`assets.subject` 存**全称**（`name`），展示走 `short`（前端 `entityShort` 读 bootstrap `entities[]`，查不到回退原值）；被产品引用的主体禁删（400 带 N）；**改名不回写** `assets.subject`（存量产品需手动改选）；前端原 `ENTITIES` 硬编码常量已删除 |
| **可见性判定收口（ADR-030）** | viewer 可见性一律走 `services` 单一判定函数（`Visibility`），**只用结构化外键**（projectId/contractId/assetId/uploadedBy），禁止 detail 文本正则；bootstrap 与全部分页端点共用：logs 按 target=contract 的 contractId 过滤、flows 按引用过滤、**files** 按「被产品引用→全员可见 / 孤儿文件→上传人或 admin / 下载不可见返回 404」；`GET /users/options` 提权 `require_editor`（viewer 403） |
| **订单禁编辑与留痕（ADR-028）** | `PUT /projects/{id}` 对 viewer **一律 403**（系统无草稿态，「提交后禁编辑」≡「viewer 禁编辑」，不按状态分支）；唯一改单路径 =「撤销」→ 购物车重下（ADR-026/027）；撤销单不可删除：`DELETE /projects/{id}` 对 `terminated && cartRefilled` → 403（复用 cartRefilled 作留痕标记，无 schema 变更）；**撤销 ≠ 终止**：撤销仅 pending 且回填购物车，终止把已生效单作废但不回填（viewer 保留对自己项目的终止权，否则 active 单无退出路径）。**ADR-040（2026-10-22）：该端点权限 `require_editor` → `require_admin`，前端入口由列表常驻按钮收进行尾「更多▾」（仅 admin 渲染），护栏与回滚逻辑逐字不变** |

## 4. 遥感数据模型（ADR-011，Supersedes ADR-010）

**父产品 + 可售明细两层**：
- 父产品（assets，type='遥感数据'）：容器，不可直接加购/下单；登记时表单隐藏"数量单价"卡（quantity=1/unit=份（可售明细）兜底），提示条在"产品类型"下方
- 明细（`rs_items` 表）：省/市（可空）× 精度（米，0.5–2）× **月份（YYYY-MM）** 同父产品下唯一；每份一个单价（元/份，最多 6 位小数，ADR-048）；`repeatSale` **默认 false（单次售卖，售出即占用）**，可按明细逐条开启（true = 只计次不扣量，ADR-038）；列表「可重复售卖」列为内联开关（行级互斥 + 失败回滚），新增/编辑弹窗同样可设
- 接口：`POST /assets/{id}/rs-items`、`PUT/DELETE /rs-items/{id}`（require_editor；有 project_items/cart_items 引用的明细禁删 400）
- 售卖：明细行购物车数量恒 1（qty≠1 → 400），判重键 (userId, assetId, itemId, customer)；金额 = 明细单价后端权威重算；`project_items.itemId` / `cart_items.itemId` 关联
- **明细状态（ADR-038 修订 2 / RS-STATUS-20261022，业务方指定方案）**：`rs_items.status ∈ {in_stock(可售), all_sold(已售罄)}`，与外层 `assets.status` 同枚举、同语义；**唯一维护入口** `services._sync_rs_item_status`（按真值重算：`repeatSale=true` 或未被非 terminated 合同引用 → `in_stock`，否则 `all_sold`），在下单锁定/释放/交付/撤销交付/repeatSale 切换/驳回/批量状态变更/删项目处调用；下单护栏：`repeatSale=false` 且 `all_sold` → 400「该可售明细已售罄」；`repeatSale=true` 的明细永不置 `all_sold`
- **数量口径（UI-OPT-20261022，口径经 ADR-038 修订 2）**：容器的「可售数量」= **`status = in_stock` 的明细条数**（`bootstrap.assets[].availableCount`）；容器 `assets.quantity` = 明细总条数（`_sync_container_quantity` 自动维护，`PUT /assets` 手改被忽略），因此 `quantity − lockedQty − shippedQty` 与 `count(in_stock)` 恒等——**外层产品逻辑与明细逻辑完全同构**；由 `bootstrap.assets[].availableCount` 后端派生（全量聚合，**viewer 视角同值**），前端 `availableQty()` 对容器优先读该字段。列表「可售数量」列、抽屉图例、详情、状态派生（可售/售罄）**统一走该函数**，禁止再用父产品 `quantity=1` 另算
- 交互：加购/登记销售走 `RsItemPicker.vue` 树状选择（省→精度→月份·单价）；产品详情"可售明细"页签 CRUD；批量加购按钮对遥感父产品**分流拦截**（不进购物车，提示逐份选择，保留勾选）
- 技术债：assets 表 ADR-010 的 4 列（province/city/resolution/imageDate）已废弃（列保留，schema/代码不再使用）；手动交付（POST /outbounds）未做明细感知（前端无该入口）

## 5. 购物车与权限

- **购物车按登录用户隔离（ADR-009）**：全部购物车端点用登录用户 id；bootstrap.cart 只返回本人行；结算只清本人
- 权限矩阵（**五角色，ADR-051**）：admin（全部含基础设置）/ supervisor 商务主管（业务写全放行 + 查看所有销售项目 + 分配/改派 + 审核兜底）/ editor 商务（业务写全放行，无基础设置；**仅见名下销售项目**）/ viewer 生态（可下单、仅见自己下单的项目）/ finance 财务（**只读，仅产品/服务**，不可下单/编辑/看销售项目/主体）。能力=角色→权限点（守卫），数据=角色+归属→行级域（`user_sees_project`/`Visibility`），两层正交、均服务端强制
- **下单链路 = require_order（认证即放行，唯 finance 排除→403）**：viewer/supervisor/editor/admin 可 单加/批量加购/改客户/改数量/删行/清空/结算/直接下单；产品维护类（增删改产品、明细维护、交付物、基础资料、交付）+ 审核/接手/分配 = require_editor（admin/supervisor/editor）；**分配/改派 = require_supervisor（admin/supervisor）**；账号/审计 = require_admin。前端 canWrite（admin/supervisor/editor）与后端一致（**不要再加 viewer/finance 降级分支**）
- **销售项目可见性（ADR-051，唯一口径 `user_sees_project`/`Visibility`）**：admin/supervisor 全部；editor 仅 `businessOwner==自己`；viewer 仅 `creator==自己`；finance 无。未分配池（`businessOwner=""`）仅 admin/supervisor（+creator 本人）可见；下单后由商务主管「分配」给商务（复用 `claim`，分配=主管身份 claim with newOwner）→ 被分配商务 + 主管可见并处理
- **自己项目有限操作（2026-10-16，ADR-028 起编辑权收回）**：`PATCH /projects/{id}/status`（仅 terminated）、`PATCH /contracts/{id}/status`（仅 terminated，含撤销 delivered 交付）、`POST /projects/{id}/withdraw`（仅 pending）、`POST /projects/{id}/refill-cart`（仅 terminated）对 viewer 放开但**限自己下单项目**（`user_sees_project`），越权 403、交付 400。**`PUT /projects/{id}` 对 viewer 不再放开（一律 403）**——订单提交即冻结，改单走撤销重下。viewer 前端入口：侧边「销售项目」菜单 + 列表/详情（**无编辑入口**；`/edit` 路由不对 viewer 放行）+ 撤销 + 重新提交；新建/删除/交付仍禁用
- 审计：写操作与登录/登出入 audit_logs
- **文件端点** `GET /api/files/{filename}`：JWT 双通道鉴权（`Authorization` 头或 `?token=` 查询参数，iframe/img 无法带头所以前端 fileUrl 统一拼 token）；`?inline=true` 返回 `Content-Disposition: inline`（预览 iframe/img 用），缺省 attachment（下载用）。前端统一走 `fileUrl(filename, inline?)`，勿手拼 /api/files URL；文件删除的引用检查含 `asset_deliverables.file`（ADR-024）

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
| ADR-008 | Accepted（金额精度一条被 ADR-048 取代） | 卫星 Token 包量定价（pricingMode='amount'，合同金额为权威输入；精度见 ADR-048） |
| ADR-009 | Accepted | 购物车按登录用户隔离 + viewer 下单链路权限对齐 |
| ADR-010 | **Superseded by ADR-011** | 遥感数据三维字段挂 assets（已废弃，勿参考实现） |
| ADR-011 | Accepted | 遥感数据"父产品 + 可售明细"两层模型（省×精度×月份） |
| ADR-012 | Accepted | 生态人员下单「待审核」流程（pending 状态 + 商务改价确认/驳回，仅 viewer 购物车结算进流程） |
| ADR-013 | Accepted（分组键部分被 ADR-016 修订） | 销售记录：一资产一条记录（ADR-016 起为**一资产一客户一记录**）+ 多主体（移除同主体校验）+ 界面「合同」改称「销售记录」（代码/表名/编号不变） |
| ADR-014 | Accepted | viewer 只读拦截收口后端权限守卫，移除前端 axios 角色白名单 |
| ADR-015 | Accepted | 手动补录交付不触碰 lockedQty（仅 shippedQty += qty）+ 归属/状态/遥感容器校验 |
| ADR-016 | Accepted | 购物车结算分组键 (assetId, customer)，前端预览同口径 |
| ADR-017 | Accepted | Token 产品数量/单价口径与普通产品统一（数量=份数，单价=元/份，无 1e4 换算） |
| ADR-018 | Accepted | 价格体系：产品参考价区间 + 原价快照（origPrice/origAmount 永不覆盖）+ 生态下单金额可输区间校验 + 删除审核改价回写挂牌价 |
| ADR-019 | Accepted | 关键时间节点与状态机：合同 signedDate（录即 active→delivering，不可清空）/scheduledDeliveryDate（仅 admin）；交付前置签订时间；撤销交付回 delivering；项目派生新增「交付中」 |
| ADR-020 | Accepted | 销售明细服务期限（购物车填写、审核可改、遥感行不填）+ 下单入口统一收口购物车（移除「登记销售」，sales/order 端点保留标废弃） |
| ADR-021 | Accepted | 遥感售卖明细（rs_items）参考价区间（取代 ADR-018 §5「遥感行不限制」口径）：区间挂明细级，遥感行折扣校验取该明细自身区间 |
| ADR-022 | Accepted（服务期限一条被 ADR-047 取代） | 购物车结算必填校验（客户/金额/服务期限，遥感行豁免服务期限，缺项 400 一次报全）；服务期限已由 ADR-047 改为选填，客户/金额必填不变 |
| ADR-023 | Accepted | 购物车折扣率选填快捷入口（discountRate，金额仍权威必填，手改金额清 rate） |
| ADR-024 | Accepted | 交付物模板彻底下线 + 存量实例清空 + 交付物单文件附件（file 列）+ 抽屉/详情两处预览 + 抽屉删「最近动态」 |
| ADR-025 | Accepted | 卫星 Token 单位「个」+ 单价展示百万Token 口径（amount 模式 salePrice×1e6 两位小数，交易链路零改动） |
| ADR-026 | Accepted | 生态人员「撤销」待审核订单（终止原单 + 明细回填购物车，本人/admin，原因必填） |
| ADR-027 | Accepted | 「重新提交」收口购物车（`POST /projects/{id}/refill-cart` + `cartRefilled` 幂等）+ 移除 create 页 copy 模式（resubmit 端点保留标废弃） |
| ADR-028 | Accepted | 生态人员订单提交后禁编辑（`PUT /projects` 对 viewer 一律 403，改单走撤销重下）+ 撤销单删除护栏（`terminated && cartRefilled` → 403）+ 保留 viewer 终止权 |
| ADR-029 | Accepted | 下单校验单一出口（`_create_project_core` 权威链）+ `POST /sales/order`、`/resubmit` 410 下线 + `contractAmount` 与 Σ 明细强校验 |
| ADR-030 | Accepted | 可见性判定收口（`Visibility` 单一函数：文件 ACL + 日志/流水按结构化外键过滤，禁 detail 文本正则）+ `/users/options` 提权 require_editor |
| ADR-031 | Accepted | 启动迁移治理：`schema_migrations` 标记表，启动期禁业务数据 DELETE/UPDATE（修复「每次重启清空交付物」） |
| ADR-032 | Accepted | 状态机守卫下沉 `_change_contract_status_core`（合同级/项目级共用）+ 项目级批量全量或全不 + 终止按明细状态回滚 + 派生补全（`{delivered,terminated}`→delivered） |
| ADR-033 | Accepted | checkout 幂等键 `requestId`（24h）+ 状态变更/数量扣减条件更新 + 取消 `max/min` 静默夹断（不变量破坏显式 500 + 审计） |
| ADR-034 | Accepted | 登录加固：JWT_SECRET fail-fast（dev 持久化 `backend/.jwt_secret`）+ `users.tokenVersion` 凭据吊销 + 登录限流 (ip,username)/IP 双维度 429 |
| ADR-035 | Accepted | 资产主体可维护：`entities` 表（name UNIQUE/short）+ 设置页 `/settings/entities`（菜单名「公司主体」）增删改（被产品引用禁删）+ 前端 `ENTITIES` 硬编码常量删除、改读 bootstrap `entities[]`；改名不回写存量 `assets.subject` |
| ADR-036 | Accepted | 产品登记规则：`inboundDate` 新建自动生成当天（编辑只读展示）+「长期买断」改「产品有效期」+ 新建销售单价自动同步参考区间（min=单价、max=×1.02，手改后停跟）+ 移除卫星数据自动勾选重复售卖（默认全关）+ 遥感容器强制 `repeatSale=false`（400 兜底）+ 登记页 4 卡重构（零字段增减） |
| ADR-037 | Accepted | 生态人员购物车口径：viewer 不渲染折扣输入（后端忽略 viewer 行历史 `discountRate`，不 400）+ 区间校验分角色（viewer 仅下限、上限放开；editor/admin 双向不变；单函数两入口复用） |
| ADR-038 | Accepted | 遥感可售明细级「可重复售卖」开关：默认 **false（单次售卖）** + 入参新增 `repeatSale` + 列表内联开关/弹窗可设 + `availableCount` 只扣 `repeatSale=false` 的占用明细 + 存量 60 条归一脚本（ADR-011 的"明细默认 true"被本 ADR 取代） |
| ADR-039 | Accepted | 购物车折扣功能整体下线（Deprecates ADR-023）：前端折扣输入/摘要/预览全删，后端 `discountRate` 入参「容忍但忽略」、新单恒 `null`、列保留不清洗 |
| ADR-040 | Accepted | 销售项目删除入口收敛：列表常驻「删除」→ 行尾「更多▾」仅 admin + `DELETE /projects/{id}` 权限 `require_editor` → `require_admin`（ADR-028 §3 护栏与回滚链零改动）；附带移除产品列表「编辑」按钮（入口 3→2） |
| ADR-047 | Accepted | 购物车服务期限由必填改**选填**（部分取代 ADR-022 §1 第三条）：两端都空放行（落库 `NULL`）、只填一端仍 400（成对校验）、两端都填保持 ADR-020 校验；客户/金额必填不变；前端去列头红星并同步提示文案 |
| ADR-048 | Accepted | 金额精度放开到**最多 6 位小数**（部分取代 ADR-008/022 的「整数元」）：全链路 `Decimal` 量化 1e-6（取消强制到分），展示「最少两位、最多六位、尾随 0 截到两位」，覆盖购物车/建单/审核改价/产品单价与区间/遥感明细单价/交付补录；业务规则（必填/区间/分组/锁定）不变，无 DB 迁移 |
| ADR-049 | Accepted（部分取代 ADR-037 §3；**§购物车「只卡下限」部分被 ADR-052 取代**） | 参考区间**只约束下单下限**：购物车加购/改数量/改金额/结算（任何角色）金额可高于区间上限，仅低于下限 400；商务审核改价不受区间限制（仅校验 >0 与 ≤6 位小数）；商务手工建单保留双向校验；无数据结构变更 |
| ADR-050 | Accepted | 审核阶段可编辑性增强：`POST /projects/{id}/review` 支持改**合同总价**（按各明细行金额比例分摊、残差归最大行、保持 `合同总额=Σ明细`、不回写挂牌价）+ 改**客户公司名称**（写权威 `Contract.customer`、`Project.customer` 重派生、同客户+同明细集冲突 400）+ 改**非遥感数量**（unit 行 `amount=price×qty`、amount 行按比例缩放、改大校验可用库存不足 400 整事务回滚、repeatSale 只计次、遥感恒 1）；reject 忽略新字段、旧 payload 行为不变 |
| ADR-051 | Accepted | 权限体系升级（**固定五角色** admin/supervisor 商务主管/editor 商务/viewer 生态/finance 财务，静态集中式不引动态权限表）：能力=角色→权限点（`require_order` 排除 finance、新增 `require_supervisor`）+ 数据域=角色→行级（`user_sees_project`/`Visibility`：editor 仅名下、supervisor/admin 全部、viewer 仅自己、finance 无）+ **商务主管分配制**（未分配池 `businessOwner=""` 仅 admin/supervisor 可见，复用 `claim` 由主管分配/改派给商务、被分配商务+主管可见并可审核兜底）+ 财务只读仅产品/服务；无 schema 迁移 |
| ADR-052 | Accepted | 购物车销售金额**双向区间约束**（部分取代 ADR-049 §购物车「只卡下限」）：购物车 4 入口 `_check_discount_range` `enforce_max=False→True`（加购/批量、改客户改金额、改数量、结算含全量行重校验）→ unit 行低于下限/高于上限均 400；**包量（amount）行不覆盖**（仅 >0+≤6 位）、**审核改价不限制**、**手工建单仍双向**均不变；存量超上限行结算拦截（无迁移）；前端去「销售单价」列（纯展示派生，hint 迁移）+ 销售金额输入加双向区间校验/标红/阻断结算 |
| ADR-053 | Accepted | 产品域三处：① **税点** `Asset.taxPoint`（整数百分比、nullable、纯展示不计算）→ 列表/详情展示 + 登记可录；② 列表删「**售卖数量**」列（`shippedQty`），「重复售卖」tag 保留；③ **销售单价→采购单价**（复用 `salePrice` 列无迁移、对外不展示仅编辑可见）+ 列表/详情/抽屉销售单价改展示**区间下限 `priceMin`** + 填采购价**自动按 ×1.01/×1.02 生成参考区间**（新建+编辑、手改不覆盖、仅非容器、前端实现）+ `availableValue`（可售金额）切 `priceMin` |
| ADR-054 | Accepted | 账号/用户管理三处：① 账号列表**客户端分页 + 过滤**（关键字 username/name + 角色 + 状态；`GET /users` 不变、统计卡照常）；② **自助改密** `POST /auth/change-password`（全角色、需校验旧密码、`tokenVersion+1` 踢旧会话、返回新 token 保持登录）+ 顶栏 user-chip 改 `el-dropdown`（改密/退出，全角色可见）；③ 建号**随机密码**（12 位大小写+数字去易混、明文可见可复制、仅新建）；顺带 `UserOut` 补 `createdAt` 修「创建时间」列恒 `-` |
| ADR-055 | Accepted | 销售项目列表页 `/sales/projects` **服务端分页**：新增 `GET /projects`（page/pageSize + 可见性 `build_visibility` + 4 过滤 keyword/status/rep/businessOwner 转 query 参数、服务端 filter+count+切片、排序 id.desc、`{total,items}`）；**bootstrap 全量 projects 不动**（13 消费点零影响）；列表页改分页请求驱动 + el-pagination + 卡头显后端 total + 写操作后重载；rep/owner 下拉选项仍取 db.projects 全量 |
| ADR-056 | Accepted | 三处：§1 销售项目列表**服务端排序**（`GET /projects` 加 `sortBy/sortOrder`，状态按生命周期档位 5 序 + 金额/最近跟进/预计签约/编号，`id.desc()` 兜底保翻页稳定，5 列 `sortable="custom"`）；§2 详情页**勾选驳回订单**（合同改列表+selection，仅 pending 合同、批量/单一驳回，新增 `POST /projects/{id}/reject-contracts` 复用 terminated+remark 零迁移、部分驳回项目保持 pending 可续审）；§3 新增「**产品统计**」一级菜单（按 `Asset.subject` 主体聚合资产数量/金额、纯前端、可展开对账 Excel、采购口径、仅 viewer 不可见、finance 守卫放开） |
| ADR-057 | Accepted | 审核订单页 `review.vue` **美化 + 合同勾选部分确认/驳回**：§1 视觉改**方案A 每合同一张表**（合同头=客户名降级+主体tag+合同总价input+小计，下方 el-table 产品/数量/原价/实际价/金额/服务期限、行内可编辑、行高统一、金额列 center 跟规范、`.info-bar`）；§2 合并**sticky 底部条**（已选 N/M 合同+勾选合同合计+确认下单/驳回，照购物车 `.cart-checkout`、豁免全局非悬浮规范）；§3 **每合同勾选（默认全选）** 控制确认/驳回只作用于勾选：确认走 `review` 加可选 `contractIds`（部分确认、未勾保持 pending、项目有 pending 时保持 pending 可续审）、驳回复用 `reject-contracts`；缺省整单向后兼容 |
| ADR-058 | Accepted | 流转日志与分配下拉显示「**姓名**」而非「账号」：username 作稳定存储标识、name 作展示标签（日志 detail 与 businessOwner 仍存 username）；① 展示 project 流转日志 detail 的所有位置（列表抽屉+详情页）前端做 username→name 解析（`/users/options/all` 映射、最长优先+词边界、未知/空回退），**存量+新日志同时生效**、不动后端不迁移；② `TransferDialog` 选项 label 由「姓名（账号）」改「姓名」（value 仍提交 username）+ 顺手修同对话框裸账号；抽共享 username→name helper |
| ADR-059 | Accepted | 审核订单页 `review.vue` 优化：**① 删顶部 4 行 `.info-bar` 说明**；**② 点击即改（保留 6 列）**——「实际单价(unit)/销售金额(amount·rs)/数量(非rs)」常驻 `el-input-number` 改为"常态显数值、点击该值才出输入框（复用 el-input-number+amountInputFormatter/Parser）、失焦/回车提交、Esc 取消"、hover 轻微可编辑提示，派生/不适用格静态不可点；**③ 服务期限拆两列**「开始时间/结束时间」各自 `el-date-picker`（rs 行两列 `-`）；**纯展示层**——编辑仍写 `l.price/l.qty/l.amount/l.serviceStart/l.serviceEnd`，ADR-050/057 计算链/只传变更/派生/校验零改动 |
| ADR-060 | Accepted | 审核订单页 `review.vue` 合同头字段**点击即改** + **合同头字号调大**：① 合同头「客户名称」(文本,绑 customer) 改点击即改(新建 `ClickEditText`：常态显客户名/空弱提示、点击出 el-input maxlength128+trim、失焦/回车提交/Esc 还原，提交写回 customer、"客户名空→确认被拦"校验不回归) +「合同总价」(数值,绑 amount)**复用 `ClickEditNumber`**(常态显所填总价/空则"留空=明细合计"、点击出 el-input-number)、小计保持只读；② `.rv-ct-head` 那行 12px 小字调大(客户名~14px/600、标签~13px、小计金额维持 16px/700)；**纯展示层**，提交仍写回原字段、合同级只传变更/确认校验/计算链零改动 |
| ADR-061 | Accepted | 购物车数量输入优化：`/cart` 步进器（`cart/index.vue` 内联 `.step-input`）**① 去 6 位硬限**（删 `onQtyInput` 的 `.slice(0,6)`，保留 `\D` 过滤）→ 库存上限 `qtyMax=avail` 成唯一约束（已存在：`applyQty` 超限截断+提示、加号到上限禁用、后端 400 兜底；`repeatSale` 行保持不限）；**② 长数字可见**（业界 scrollCaretIntoView）：`.step-input` `text-align:center→left` + 输入时 `setSelectionRange(len,len)` 滚到末尾（始终见正在输入位）+ 适度加宽（stepper ~104→~128px/列 ~120→~148px 让 ≤6-7 位免滚动，若加宽明显变差退化仅 left+scroll-caret）；纯前端，后端 400 口径不变（注：其步进器输入控件被 ADR-062 换成 `ClickEditNumber`，但"无位数限制+库存上限唯一约束"意图保留）|
| ADR-062 | Accepted | 购物车数量改**点击即改（去 +/-）** + 审核页数量**超库存截断对齐购物车**：① `ClickEditNumber` 加 `max`/`maxMessage`（commit 超 max→截断+`ElMessage.warning`，Esc 还原不触发）；② 购物车步进器(减号+input+加号)→`ClickEditNumber`、删 `+`/`-`/`stepQty`、`:max=qtyMax(row)`(avail 口径)、rs 恒1/repeatSale 不限/库存副提示保留、超上限只弹一次；③ 审核页 `ReviewLine` 存 `assetId`+`import availableQty`+`qtyMax(l)=repeatSale?null:max(origQty+availableQty(asset),1)`(asset缺失→origQty)、数量格加 `:max`；提示文案对齐购物车「可用数量仅 N，已按上限填写」；**后端不动、只传变更/计算链/派生零改动** |
| ADR-063 | Accepted | 购物车 `cart/index.vue` 两处 UI：① **库存行内提示回移数量列修错位**——`已达上限/可售` 提示本在**销售金额列**(754-759，ADR-052 删单价列时迁入的遗留)，与数量值跨列致"偏右一列"视觉错位 → 移入**数量列** `.cell-hint`(702-706) `v-else` 分支、保持列内居中(与数量值同轴)、`cart-sellable-max` 着色保留，金额列只留参考区间提示；isAmount(Token)行显 `X Token`(核 `availOf` 是否真有限)；② **删顶部 `.cart-notice` 说明条**(模板 586-595 + CSS 982-1005 + `InfoFilled` import + 陈旧注释)——已被列内提示+列头 tooltip 覆盖，必填校验不受影响(列头红星/标红/placeholder/后端400 独立)；纯前端展示层，无数据/接口/计算链改动 |

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
7. **【硬规则】禁止裸用 secure-context-only 浏览器 API**（BUG-LAN-20261022，2026-10-22）：本项目当前部署形态是 **http + 局域网 IP**（`vite --host 0.0.0.0`、uvicorn 8000），此时 `crypto.randomUUID`、`crypto.subtle`、`navigator.clipboard`、`navigator.mediaDevices`、`serviceWorker` 等一律为 `undefined` —— 直调即 TypeError（曾导致局域网下购物车下单 100% 失败）。**必须封装降级后再用**：
   - 唯一 UUID 需求 → `genRequestId()`（`src/api/index.ts`，三级降级：`randomUUID` → `getRandomValues` 手工 v4 → `Math.random`）
   - 剪贴板 → `copyCode()` 的三级降级范式（Clipboard API → `execCommand('copy')` → 弹窗展示）
   - 新增此类 API 前先问：**没有安全上下文时如何工作**；不可降级的改用服务端能力
   - 注：后续若改为 nginx 反代 + HTTPS，secure context 会成立、降级分支不再触发，但**封装必须保留**（本地 http 调试、内网降级场景仍会走）
8. **【硬规则】前端类型检查必须用 `npx vue-tsc -p tsconfig.app.json --noEmit`**（REFILL-20261022-F3，2026-10-22）：根 `tsconfig.json` 是 solution-style（`files: []` + `references`），直接跑 `vue-tsc --noEmit` **退出码恒 0 但一行业务源码都没检查** —— 此前多批次据此汇报「类型检查通过」，实为假通过。今后验收一律带 `-p tsconfig.app.json`，且退出码必须为 0（当前基线：4 条 TS6133 已于同批清理，基线 0 错误）
