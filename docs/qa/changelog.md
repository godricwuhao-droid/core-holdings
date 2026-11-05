# 测试变更日志（QA）

> 记录 core-holdings 的测试活动、验收结论与测试资产变更。格式：日期、类型、变更内容、影响文件、关联任务、备注。

| 日期 | 类型 | 变更内容 | 影响文件 | 关联任务 | 备注 |
|---|---|---|---|---|---|
| 2026-11-04 | 回归验证 | ADR-057「审核订单页 review.vue 美化 + 合同勾选部分确认/驳回」独立回归：A 视觉 4 项（**每合同=容器块 10px 圆角+--border-color 边框、合同间 16px 分隔** / 合同头=勾选+客户名 small(12px 非 16px 大标题)+主体 tag+合同总价 input(:controls=false)+小计 / 明细 el-table 表头一次声明 6 列、行高统一 40+18px cell 骨架、**金额/数字列 align=center（非 right）**、服务期限并入单列单层行 / 说明条=全局 .info-bar 浅蓝 #F0F6FF 含「只作用于勾选合同」说明 / **sticky 底部条 position:sticky 滚动悬浮、左「已选 N/M · 合计」22px/700 主蓝 #1769D4 + 右 返回详情/改派转交/驳回/确认下单**）、B 编辑链路 5 项（**实时联动：改单价 100→120 行金额 200→240/小计/sticky 6200→6240 即时正确；改数量 10→12 参考单价 150→125 元/个 即时；改服务期限金额不变** / **合同总价权威：填 300→小计 300、确认后后端按明细比例分摊落库（it186 price 120→150 派生、amount 300、contractAmount 300）** / **★只传变更项：F12 抓包 items 仅含改动的 it186(price+svc)+it187(qty)，未改 it188 不出现；contracts 仅含改总价的 171；contractIds=[171,173,172]** / 校验：单价空→点击 toast「请填写实际单价」拦截、客户名空→确认禁用+tooltip「客户公司名称不能为空」、amount 空→toast / 备注 saveRemark 独立保存不回归）、C 勾选+部分确认/驳回 8 项（**默认全选：进 3 合同 pending 页全勾、sticky「已选 3/3 · 合计=项目总额 6200/700」** / **★部分确认核心：取消勾 1 个→sticky「已选 2/3」+合计减该合同；确认→只确认勾选的（active）、未勾保持 pending、项目仍 pending；刷新后 review 只剩未勾的 pending 合同、已确认消失；再确认剩余→项目 active**（curl+浏览器双验证）/ 勾全选=整单等价（全部 active+项目流转）/ 0 勾选→确认+驳回均禁用 / 部分驳回→只驳回勾选的（terminated+remark「驳回：」）、剩余 pending、项目仍 pending / 混用 confirm→reject→confirm 派生正确（[active,terminated]→active、[active,terminated,pending]→pending、零 pending→active）/ **校验范围=勾选：取消勾零元合同、只确认正常合同→200 不被未勾异常阻断；只确认零元合同→400「存在未定价明细」** / sticky 合计=勾选 contractTotal 之和实时变）、D 权限/守卫 4 项（viewer eco01 直访 review 静默重定向 /assets/embodied、finance fin01 提示「财务账号仅可浏览产品及服务」重定向 / 未分配项目→提示卡+「分配」按钮（sup01）/ 非负责人 editor 看不到非名下项目（bootstrap 可见性）重定向列表、后端 403 兜底「仅接手的商务负责人（biz01）…」/ 后端鉴权：viewer·finance review+reject-contracts 403、未分配 400「尚未分配…商务主管分配」）、E 护栏 6 项（**详情页 ADR-056 勾选/单一/批量驳回 UI 不回归（detail.vue 未被本批改动物证+批量驳回按钮在）** / **整单确认（不传 contractIds）=改前行为：改价/数量/金额/期限/客户名全落库、锁定调整（asset50 6→8、asset51 7→6）、日志无「（N 份）」后缀** / 审核页→返回详情正常、确认全部后跳详情项目 active / 派生 [active,pending]→pending、[active,terminated]→active、[active,terminated,pending]→pending 全对 / 下游：确认不改锁定（数量不变时）、驳回释放锁定（asset50 8→6）、遥感合同驳回 rs_item 回 in_stock（rs10）+ 项目派生 / **vue-tsc EXIT=0**）；**缺陷 1 条 BUG-ADR057-001（中）：部分确认/驳回后剩余 pending 合同丢失默认勾选（watch 不重勾「仍在列表但曾被取消」的 id），sticky「已选 0/N」按钮禁用需手动重勾才能续审——后端全对，前端状态问题，指派 frontend-dev**；观察项 1 条（OBS-ADR057-01：前端恒传 contractIds，勾全选时日志带「（N 份）」后缀，与 ADR「整单确认日志格式不变」字面有出入，语义等价） | `frontend/src/views/sales/projects/review.vue`（整体重写：方案 A 每合同一张表 + sticky 底部条 + 勾选）、`backend/src/schemas.py`（ReviewInput.contractIds）、`backend/src/services.py`（review_project targets 过滤 + _derive_project_status [active,pending] 分支） | ADR-057 | 独立复核（不依赖前后端自测）：:8000/:5173 测试库真实 HTTP curl（admin/sup01/biz01/biz02/eco01/fin01 Bearer）+ 自造 QA057- 前缀项目 99-115（17 个）全链路流转 + agent-browser 浏览器实测（F12 抓包 + console 日志定位根因 + 截图 10 张 /tmp/qa057/*.png）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；验证期间临时加 console 日志定位 BUG-001 后**已全部还原（git diff 无残留）**；测试数据保留供验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-056「销售项目列表排序 / 详情页勾选驳回订单 / 产品统计页」独立回归：A 列表排序（5 排序键 × asc/desc 全对、状态按档位 pending→active→delivering→delivered→terminated 且三终止子型同档、**翻页稳定 10 组合 page1+page2 与 pageSize=100 全量 id 序列完全一致无重复/遗漏、total 恒 80**、点排序回第 1 页、第三次点击取消回 id.desc、status=pending×amount 组合正确、非法 sortBy 按无排序）、B 勾选驳回（**部分驳回 3 勾 2：2 合同 terminated+remark 追加「驳回：」、项目仍 pending、剩 1 合同 review confirm→active 可续审** / 单一驳回 / **全部驳回→项目 terminated** / 空与纯空格原因弹窗内拦截不发请求 / active 项目无勾选列无批量驳回且交付/终止/录签订时间按钮保留 / 守卫 11 项：viewer·finance 403、未分配 400、非负责人 403、非本项目合同 400、非 pending 合同 400、reason 缺/空 422、纯空格 400、contractIds 空 422、非 pending 项目 400、404 / **下游数量：lockedQty 精确回退（52:2→0、50:3→0、51/29 不动）、遥感 rsItem 驳回回 in_stock、shippedQty/soldAmount 不动** / 审核页整单确认·整单驳回回归不变）、C 产品统计（**viewer 菜单无+直访静默拦回 / finance 菜单有+可打开+/assets 只读不回归 / admin·sup01·biz01 可见** / **7 主体汇总与手工对 db.assets 按 subject 求和逐值全等** / 展开明细列口径正确（采购单价=salePrice、剩余量=availableQty、采购总价=数量×单价、可售/已售罄）/ 剩余金额=剩余量×采购单价）、D 护栏（ADR-055 分页/4 过滤/可见性不回归、详情/创建/审核/交付链路正常、合同展开行原卡片信息完整、五角色守卫无冲突、**vue-tsc EXIT=0**）**全部通过，无阻断缺陷，可交付**（观察项 1 条 OBS-ADR056-01：合同行状态 tag 显示「已终止」非「已驳回」，与 ADR-056 前旧卡片口径一致非回归） | `backend/src/routers/api.py`（`GET /projects` sortBy/sortOrder + `POST /projects/{id}/reject-contracts`）、`backend/src/services.py`（`_reject_contracts` 共用 helper + `_derive_project_status` 混合态分支）、`frontend/src/views/sales/projects/index.vue`（5 列 sortable+onSortChange）、`frontend/src/views/sales/projects/detail.vue`（合同卡片→表格+selection+批量/单一驳回）、`frontend/src/views/statistics/index.vue`（新增）、`frontend/src/{router/index.ts,layouts/MainLayout.vue}`（/statistics 路由+菜单+finance 白名单） | ADR-056 | 独立复核（不依赖前后端自测）：:8000/:5173 测试库真实 HTTP curl（admin/sup01/biz01/fin01/eco01 Bearer）+ 翻页稳定 10 组合脚本比对 + 手工按主体求和比对 + agent-browser 浏览器实测（截图 8 张 /tmp/qa056_*.png）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；测试数据保留（QA056- 前缀：项目 86/87/88/89/90 + 合同 124-133）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-055「销售项目列表服务端分页」独立回归：A 分页（第一页 20 条+分页器 / 翻页数据切换无重复 id / 切 10·50 条每页行数正确且回第 1 页 / 超尾页 items `[]` 且 total 不变 / **卡头「共 N 条」= 后端 total**）、B 过滤+分页联动（keyword 搜后卡头 total 更新为过滤后数+自动回第 1 页 / **大小写敏感：`QA0` 43 条、`qa0` 0 条空态（与后端 instr 一致）** / status·rep·businessOwner（含 `__none__`）单过滤+组合（待审核×未指派=2 条）count 正确 / 清空回全量）、C 可见性（**eco01 viewer total=20 全部 creator 是自己** / **biz01 editor total 全部 businessOwner 是自己** / admin·sup01 全量 75 / **fin01 直访 /sales/projects 被守卫拦（提示+重定向 /assets/embodied）且接口 total=0**）、D 对齐校验（**admin/eco01/biz01 三角色 × 7 组条件（无过滤/QA0/qa0/__none__/pending/组合/rep/owner）：`GET /projects?pageSize=100` 的 code 集合 == 对 bootstrap `projects[]` 本地同条件 filter 的 code 集合，集合/数量/顺序(id.desc)/total 口径四项全等** / `pageSize=5&keyword=QA0` total=43 items=5）、E 写操作后重载（**UI 删除项目→行消失+total 75→74 无 F5** / **UI 改派 biz02→biz01→行内负责人即时刷新且与 API 一致** / 跳详情返回后数据正常 onMounted 重拉）、F 护栏（详情/编辑/审核页正常 / **outbound 补录「关联项目」下拉 42 项 = db.projects 排除 terminated·pending 全量口径精确一致** / 资产详情「销售关联（4）」tab 正常 / 看板统计正常 / **rep 下拉 12 项=全量可见 rep、owner 下拉=全量名册，不随当前页缩减** / 参数边界 page=0·pageSize=0·pageSize=101·page=abc→422、无 token→401 / `vue-tsc` EXIT=0）**全部通过，无新缺陷，可交付** | `backend/src/routers/api.py`（`GET /projects`）、`frontend/src/views/sales/projects/index.vue`（分页状态+el-pagination+卡头 total+写操作重载）、`frontend/src/api/index.ts`（`listProjects`） | ADR-055 | 独立复核（不依赖前后端自测）：:8000/:5173 测试库真实 HTTP curl（admin/sup01/biz01/fin01/eco01 Bearer）+ 三角色 code 集合逐条比对脚本（/tmp/qa055/align.py）+ agent-browser 浏览器实测（截图 7 张 /tmp/qa055/）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；测试数据保留（QA051-/QA052- 前缀；QA051-E5-超可售 id=74 已按 E1 用例删除，QA052-eco01下单 id=78 负责人 biz02→biz01）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-054「账号/用户管理三处增强」（列表分页+过滤 / 自助改密 / 建号随机密码）独立回归：A 列表（关键字「QA」3 条大小写不敏感 / 角色「商务人员」9 条 / 状态「禁用」空态 / 组合 QA×商务人员=0 交集 / 清空回 38 全量 / 第 2 页首行 admin2 / 切 20·50 条/页行数 20·38 / 改过滤自动回第 1 页 / **统计卡 38/38/4 在过滤·翻页·切条数下恒为全量值**）、B 自助改密（旧密码错 400「旧密码不正确」+前端提示 / 成功 200 返回新 token+user / **改后不刷新不掉线（切菜单数据 200）+ localStorage token ver 6→7→8 / 旧 token 立即 401** / 新密码 <6 后端 422 + 前端拦截「至少 6 位」/ fin01 在 /assets、eco01 viewer 均可改密成功不掉线 / 改后新密码可登录 / 审计「修改密码」「修改密码失败 旧密码不正确」均落审计）、C 随机密码（12 位·大小写+数字·无 0/O/1/l/I·两次生成不同·show-password 切明文 / 编辑弹窗无随机按钮（「留空则不修改」语义）/ 随机密码建号成功且可登录）、D 护栏（admin PUT 重置他人/自己密码不校验旧密码仍工作 / 登录登出正常（退出确认弹窗→登录页）/ fin01 菜单仅「产品及服务」+直访 /settings/users·/dashboard 拦回 /assets/embodied / biz01 直访 /settings/users 拦回 /dashboard / 账号 CRUD 建·改角色·禁用 401·启用·删除全通 / 新号 createdAt 有值且列表列显示时间 / vue-tsc EXIT=0）**全部通过，无新缺陷，可交付** | `backend/src/{routers/api,schemas}.py`（`POST /auth/change-password` + `UserOut.createdAt`）、`frontend/src/views/settings/users.vue`（客户端过滤+分页+随机按钮）、`frontend/src/layouts/MainLayout.vue`（user-chip dropdown+改密弹窗）、`frontend/src/utils/randomPassword.ts`、`frontend/src/api/index.ts`（`changeMyPassword`） | ADR-054 | 独立复核（不依赖前后端自测）：:8000/:5173 测试库真实 HTTP curl（admin/biz01/fin01/eco01 Bearer，JWT payload ver 解码核对）+ agent-browser 浏览器实测（截图 12 张 /tmp/qa054-*.png）+ 审计日志核对；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；改过密码的账号（biz01/fin01/eco01）已用 admin 重置回 `123456` 并复验登录；测试数据保留（QA054- 前缀：QA054-selfpw/qa054rand/QA054-rand2/QA054-ui-rand，QA054-crud 已删）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-053「产品域三处改动」（税点属性 + 去「售卖数量」列 + 销售单价改采购单价/自动参考区间）独立回归：A 税点（POST/PUT 带 13 → 200 落库、列表/详情/抽屉/fin01 视角均显示 `13%`、PUT 只改 remark 保持 13（exclude_unset）、PUT null 清空、存量 id=52 列表/详情 `-` 无 `undefined%`、101/-1 → 422、fin01 只读 403）、B 去售卖数量列（4 板块表头逐项核对无该列 + 「重复售卖」tag 保留 + 抽屉已交付/锁定/可售进度正常）、C 采购单价（列表/详情/抽屉销售单价均显示 priceMin+区间、容器 `-`、表单 label「采购单价（元）」+「税点（%）」、新建 100→101~102 自动区间、手改下限 500 后改价不覆盖（上限 ×1.02 重算）、编辑初始加载不重算/改价重算/手改后不覆盖、容器编辑无价格卡、采购价 200 落库 salePrice=200）、D 护栏（ADR-052 双向区间加购 400×2、看板可售金额三板块与 priceMin 口径逐分一致、正常下单 SP-2026110408371149 金额 121 正确、embodied/hardware 一致 + compute 无单价列原样、详情 5 tab 无回归、stale 文案已改双向口径、vue-tsc EXIT=0）**全部通过，无新缺陷，可交付** | `backend/src/{models,schemas,services}.py`、`backend/main.py`（taxPoint 迁移）、`frontend/src/views/assets/{list,create,detail}.vue`、`frontend/src/types.ts`（availableValue→priceMin） | ADR-053 | 独立复核（不依赖前后端自测）：:8000/:5173 测试库真实 HTTP curl（admin/fin01 Bearer）+ bootstrap 字段级核对 + agent-browser 浏览器实测（截图 5 张 /tmp/qa053-*.png）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；测试数据保留（QA053- 前缀：产品 54/55 + 项目 80）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-052「购物车销售金额双向区间约束 + 去销售单价列」独立回归：A 后端双向（POST/PATCH/PUT /cart 三入口 × 低于min/高于max/区间内 9 档 + 结算全量重校验存量超上限 400 + 改回区间内结算 200 + 透传一致性 + amount 包量不卡区间（5000/0.05/999999 均 200、0 仍 400）+ 审核改价超上限 200 落库 + 手工建单双向 400 + 无区间/仅下限/仅上限兜底 6 档 + viewer eco01 双向复核）、B 前端（销售单价列已删表头 7 列逐项核对 / 「可售 N / 已达上限 N」迁至销售金额列副提示 / unit 低于min·高于max 标红+结算拦截·区间内放行 / amount 超 max 不标红 / 无区间不标红 / 顶部+行内双向文案 / 越界拦截提示含「销售金额须在参考区间内」）、C 护栏（ADR-049 保留结论复核 / eco01 下单+sup01 分配 / 删列后小计·落库·结算 payload 金额一致 / 数量超可售 400 回滚 / vue-tsc EXIT=0）**全部通过，无新缺陷，可交付** | `backend/src/services.py`（`_check_discount_range`/`_check_unit_price_range`/`_cart_add_inner`/`patch_cart_item`/`set_cart_qty`/`checkout`）、`frontend/src/views/cart/index.vue` | ADR-052 | 独立复核（不依赖 Architect 手工实现自测）：:8000/:5173 测试库真实 HTTP curl（admin/eco01/sup01 Bearer）+ SQLite 落库核对 + agent-browser 浏览器实测（截图 5 张 /tmp/qa052_B*.png）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；测试数据保留（QA052- 前缀：产品 48/49/50/51/52 + 项目 77/78/79）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | ADR-051「权限体系升级」（固定五角色 + 商务主管分配制 + 财务只读）独立回归：A 角色×能力矩阵 5 角色 × 6 端点 + signedDate/scheduledDeliveryDate 分权（35 项）、B 数据隔离 bootstrap 字段级核对（未分配池/名下/creator/财务空集 18 项）、C 分配链路（分配/改派/抢单 400/未分配审核 400/终态 claim 400 + 日志审计「分配订单/改派订单」）、D 财务只读（读放行 + 写 403 + entities []）、E 回归（生态全链路/admin 全权/ADR-012 接手转交审核/ADR-050 改价改客户名/数量锁定超可售 400 回滚/主体编辑权三角色）、F UI（五角色菜单与 tag/分配按钮与下拉仅 editor/未指派筛选/审核页分配入口与提示/财务直连拦截+提示/配色 token）**全部通过，无新缺陷，可交付** | `backend/src/security.py`、`backend/src/services.py`（`user_sees_project`/`Visibility`/`claim`/`review`）、`backend/src/routers/api.py`、`frontend/src/{auth.ts,router/index.ts,layouts/MainLayout.vue,views/sales/projects/{index,review}.vue,views/settings/users.vue}` | ADR-051 | 独立复核（不依赖开发自测）：:8000/:5173 测试库真实 HTTP curl（6 账号 Bearer）+ bootstrap 落库/日志/审计核对 + agent-browser 五角色浏览器实测（截图 3 张 /tmp/qa051/）；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；测试数据保留（QA051- 前缀）供用户验收；明细见下 |
| 2026-11-04 | 回归验证 | 全站金额输入框 bug 修复（`amountInputFormatter` 编辑期纯数字透传 + 新增 `amountDisplayFormatter`）独立回归，补齐 frontend-dev 未覆盖的 7 个输入框（assets/detail 遥感明细单价/参考价下限/上限、outbound 补录销售金额、projects/create 单价行、assets/create 参考价下限/上限+销售单价复测）：每框 5 项用户症状（逐字输入/粘贴千分位/连续 Backspace/`12.`·`0.` 中间态/7 位小数截断）**35/35 通过**；提交正确性 3 链路（rs-item 保存、出库登记、项目创建）落库均为干净 number（无 NaN/无逗号串/≤6 位小数）；只读展示（`¥27,400.123456`、`74,073.60` 千分位+≥2 位小数）与数量 `:precision="0"` 输入框（12.7→13 取整、步进按钮）均不受影响；**无新缺陷，可交付** | `frontend/src/types.ts`（`amountInputFormatter` / `amountDisplayFormatter` / `amountInputParser`）、`frontend/src/views/assets/{detail,create}.vue`、`frontend/src/views/sales/{outbound/index,projects/create,projects/review}.vue` | 金额输入框修复（ADR-048 编辑期透传） | 独立复核（不依赖 frontend-dev 自测）：agent-browser 登录 editor 在 :5173/:8000 真实数据页逐框实测（键盘逐字/inserttext 粘贴/Backspace 序列 + DOM value 断言）+ `GET /api/bootstrap` 落库核对 + 截图 2 张（/tmp）；前端 `vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；未改任何业务代码、未 build、未 commit；明细见下 |
| 2026-11-03 | 回归验证 | ADR-050「审核阶段可编辑性增强」（合同总价 / 客户名称 / 非遥感数量）独立回归：A 合同总价（单合同/多合同/残差归最大行/边界 400/留空派生）、B 客户名（落库+重派生/冲突守卫 400/重叠放行/空与超长 400+前端禁用）、C 数量（unit 放大缩小锁定净调整/超卖 400 整事务回滚/amount 行比例缩放与 amount 权威/repeatSale 不锁库存/遥感行 qty 忽略）、D 回归（reject 忽略新字段/旧 payload 行为不变/ADR-049 参考区间豁免/ADR-018 挂牌价与 orig 快照不动）、E UI（三处新输入 + 只提交变更项 + 配色规范）**18 项后端断言 + 前端类型检查 + 浏览器实测，全部通过，无新缺陷** | `backend/src/services.py`（`review_project`）、`backend/src/schemas.py`（`ReviewItemInput.qty` / `ReviewContractInput`）、`frontend/src/views/sales/projects/review.vue`、`frontend/src/api/index.ts`、`frontend/src/types.ts` | ADR-050 | 独立复核（不依赖前后端自测结论）：拷贝测试库（:8000/:5173 已运行）curl 全链路 + bootstrap 落库核对 + 流水核对；前端 `vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；浏览器（agent-browser）实测审核页交互 + XHR 抓包核对 payload；未改任何业务代码、未 build、未 commit；明细见下 |
| 2026-10-22 | 回归验证 | FORMS-20261022 批次（ADR-036 产品登记规则 + ADR-037 生态人员购物车口径）独立回归：7 个重点回归面（viewer 区间分角色 / viewer 历史折扣 / 容器 repeatSale / inboundDate 自动生成 / 登记页表单重构静态走查 / 购物车 viewer 折扣 + 幂等回归 / 菜单改名）**44 项进程内断言 + 前端静态走查，全部通过，无新缺陷** | `backend/src/services.py`、`backend/src/schemas.py`、`backend/src/routers/api.py`、`frontend/src/views/assets/create.vue`、`frontend/src/views/cart/index.vue`、`frontend/src/layouts/MainLayout.vue`、`frontend/src/router/index.ts`、`frontend/src/views/settings/entities.vue` | FORMS-20261022 / ADR-036 + ADR-037 | 独立复核（不依赖后端 agent 自测）：数据库副本 `/tmp/ch_forms_regress.db` + TestClient 进程内断言（跑完即删，`/tmp` 无残留）；真实库全程 `mode=ro` 只读，行数复核未变（25 产品 / 2 项目 / 4 合同 / 97 明细 / 8 购物车 / 11 用户，`assets#29.repeatSale` 仍为 1）；未重启服务、未 build、未 commit；明细见下 |
| 2026-10-21 | 新增 | ADR-028 验收：禁编辑 + 撤销留痕（13 条用例全量执行，13/13 通过） | `backend/src/services.py`（`update_project` / `delete_project`）、`backend/src/routers/api.py`（`PUT/DELETE /projects/{id}`、`POST /projects/{id}/withdraw`、`POST /projects/{id}/refill-cart`）、`frontend/src/views/sales/projects/{index,detail,create}.vue`、`frontend/src/router/index.ts` | TASK-QA-034 / ADR-028 | 只读验收，未改动任何业务代码；后端在数据库副本（`/tmp/qa034/core_holdings.db`、dev server :8001）执行 A/B 组，前端在真实 dev 栈（:5173 + :8000）与隔离栈（临时 vite :5174 → :8001）执行 C 组；结论与证据见下 |
| 2026-10-22 | 回归验证 | FIX-20261022 全量修复批次独立复核：8 个重点回归面（状态机/终止回滚/幂等/可见性/权限登录/迁移幂等/前端静态/契约一致性）85 项进程内断言 + 3 项 fail-fast 子进程断言 + 前端静态走查，**88/88 通过，无新缺陷** | `backend/main.py`、`backend/src/services.py`、`backend/src/routers/api.py`、`backend/src/security.py`、`backend/src/schemas.py`、`frontend/src/views/cart/index.vue`、`frontend/src/views/sales/projects/create.vue`、`frontend/src/api/index.ts` | FIX-20261022 / ADR-029~034 | 独立复核（不依赖后端 agent 自测）：数据库副本 `/tmp/fixqa/core_holdings.db` + TestClient 进程内断言（跑完即删，`/tmp` 无残留）；真实库全程 `mode=ro` 只读，行数复核未变（28 产品/3 项目/7 合同/49 文件）；未启动/重启服务、未 build、未 commit；明细见下 |

## 2026-11-04 ｜ ADR-057 审核订单页美化 + 合同勾选部分确认/驳回回归明细

> 事实来源：`docs/adr/ADR-057.md` + `docs/backend/api.md` review 小节（contractIds）。验收基准 = 用户 3 条需求（① 审核页每行订单/合同参考购物车展示、更规整美观；② sticky 合计+操作；③ 每合同勾选、默认全选、可部分确认/部分驳回、未勾保持待审核可续审）。

**测试数据（保留供验收，QA057- 前缀）**：项目 99（部分确认3合同，已全 active）/ 100（混用3合同，active）/ 101（守卫按选中2合同，1 pending）/ 102（只传变更3合同，active）/ 103（整单确认2合同，active）/ 104（遥感派生2合同，active）/ 105（遥感驳回2合同，active）/ 106（整单驳回回归2合同，terminated）/ 107（前端链路3合同，active）/ 108（前端部分确认3合同，active）/ 109（部分确认复现，active）/ 110（部分确认复现2，active）/ 111（部分确认复现3，1 pending）/ 112（部分驳回复现，1 pending）/ 113（细查复现，1 pending）/ 114（细查2，1 pending）/ 115（sticky长页6合同，pending）；合同 152-209。

### A. 视觉（方案 A 每合同一张表，biz01 浏览器 :5173/sales/projects/115/review）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | 每合同=容器块（10px 圆角+边框、合同间清晰分隔、多合同不糊） | ✅ | computed：`.rv-ct` borderRadius=10px、border=1px solid rgb(225,232,241)（=--border-color #E1E8F1）、`.rv-contracts` gap=16px；截图 /tmp/qa057/A4_sticky_scrolled.png（3 合同块清晰分隔） |
| A.2 | 合同头=勾选框+客户名(常规 small 非 16px 大标题)+主体 tag+合同总价 input+小计 | ✅ | 客户名 input fontSize=12px（small）；`.rv-ct-amount-input` :controls=false；小计=contractTotal 实时（截图 A1_review_full.png） |
| A.3 | 明细 el-table：表头一次声明 6 列、行高统一、跨列输入框水平对齐、金额/数字列 align=center（非 right）、服务期限并入单列单层行 | ✅ | 表头 产品/数量/原单价金额/实际单价/销售金额/服务期限 各表头仅 1 次；cell 骨架 40px 主区+18px 副区（.rv-cell）；computed textAlign=[left,center×5]×6 行（产品列 left、其余 center，无 right）；服务期限双 date-picker 单列内、行无第二层 |
| A.4 | 说明条=全局 .info-bar（浅蓝，含「只作用于勾选合同」说明）；无自造浅蓝残留 | ✅ | `.info-bar.rv-rules` backgroundColor=rgb(240,246,255)（=#F0F6FF）；第 2 条 bullet「『确认下单/驳回』只作用于勾选的合同（默认全选）；未勾选合同保持待审核」；scoped 样式仅补 margin/列表缩进（.rv-rules 无自造底色） |
| A.5 | sticky 底部条：滚动悬浮底部、左「已选 N/M · 合计」22px 主蓝+右 返回详情/改派转交/驳回/确认下单 | ✅ | `.rv-checkout` position=sticky bottom:16px；`.co-total` fontSize=22px/700/rgb(23,105,212)（=#1769D4）；scrollTop=600 后条仍悬浮底部（截图 A4_sticky_scrolled.png）；按钮齐全（biz01 显示「转交」、sup01 显示「改派」） |

### B. 编辑链路回归（biz01，项目 107，F12 抓包）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | 实时联动：改单价→行金额/小计/sticky 即时重算；改数量→同上；改 amount 行→联动；改服务期限→无金额影响 | ✅ | 单价 100→120：小计 ¥200→¥240、sticky 6200→6240；数量 10→12（amount 行）：参考单价 150→125 元/个 即时；服务期限 2026-06-01→2026-08-01：sticky 保持 6240 不变 |
| B.2 | 合同总价权威：手填→小计以总价为准；确认后后端按明细行金额比例分摊 | ✅ | 填 300→小计 ¥300、sticky 6300；确认后落库：it186 price 120→150（派生）、amount 300、contractAmount 300、日志「HT-…合同总价 → 300.00 元（按明细比例分摊）」 |
| B.3 | ★只传变更项：未改动的行/合同不出现在 items[]/contracts[]；改了才出现对应字段 | ✅ | **F12 抓包（XHR 拦截）请求体**：`{"action":"confirm","items":[{"itemId":186,"price":120,"serviceStart":"2026-08-01","serviceEnd":"2026-12-31"},{"itemId":187,"qty":12,"serviceStart":null,"serviceEnd":null}],"contracts":[{"contractId":171,"amount":300}],"contractIds":[171,173,172]}`——未改的 it188 不出现；未改客户/总价的 172/173 不在 contracts；it186 只带 price+svc（未改 qty 不带 qty）；it187 只带 qty+svc（amount 未改不带 amount）。svc 字段恒显式传（FIX-20261022「显式 null=清空」语义，与改前一致） |
| B.4 | 校验：单价空/0→确认被拦；客户名清空→确认禁用（tooltip） | ✅ | 单价清空→点确认 toast「『QA052-Unit-无区间』请填写实际单价」不发请求；客户名清空→确认按钮 disabled + hover tooltip「客户公司名称不能为空」；amount 行金额清空→toast「销售金额须大于 0，且最多 6 位小数」 |
| B.5 | 备注独立保存（saveRemark）不回归 | ✅ | 备注卡+保存按钮在（截图 A1）；PUT /projects 白名单口径未改动（代码走查 saveRemark 逻辑与改前一致） |

### C. 勾选 + 部分确认/驳回

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| C.1 | 默认全选：进 pending 项目（N 合同）→全勾、sticky「已选 N/N · 合计=项目总额」 | ✅ | 项目 107（3 合同）：「已选 3/3 · 合计 ¥6,200.00」=项目总额；项目 108（3 合同）：「已选 3/3 · 合计 ¥700.00」 |
| C.2 | ★部分确认：取消勾 1 个→sticky 减；确认→只确认勾选的（active）、未勾保持 pending、项目仍 pending；刷新后 review 只剩未勾的 pending、已确认消失；再确认剩余→项目 active | ✅ | **curl**：`POST /projects/99/review {"action":"confirm","contractIds":[152,153]}`→200；落库 152/153 active、**154 pending 一字不动**（qty/price/amount/svc/locked 全不变）、**项目 pending**、日志「订单已确认（2 份）」；续审 `contractIds:[154]`→200、项目 active。**浏览器**（项目 108）：取消勾 175→「已选 2/3 · 合计 ¥400.00」→确认（弹窗「确认勾选的 2/3 个合同？…未勾选合同保持待审核」）→toast「已确认 2 个合同，剩余待审核合同可继续审核」→页面只剩 175、174/176 消失；再确认→项目 active 跳详情。⚠️ 遗留 BUG-ADR057-001：部分操作后剩余合同默认勾选丢失（需手动重勾） |
| C.3 | 勾全选=整单：全部 active、项目流转 | ✅ | 项目 107 全勾确认→3 合同 active、项目 active；项目 103 不传 contractIds 整单确认→163/164 active、项目 active |
| C.4 | 0 勾选→确认/驳回均禁用 | ✅ | 全取消后 computed：驳回 disabled=true、确认下单 disabled=true（截图 C4_none_checked.png） |
| C.5 | 部分驳回：勾选部分→填原因→reject-contracts→只驳回勾选的（terminated+remark）、剩余 pending、项目仍 pending | ✅ | `POST /projects/100/reject-contracts {"contractIds":[156],"reason":"QA057 部分驳回测试"}`→200；156 terminated+remark「驳回：QA057 部分驳回测试」、155/157 不动、项目 pending、锁定释放（asset50 8→6）；浏览器路径同（项目 112） |
| C.6 | 确认+驳回混用：confirm 部分→reject 部分→剩余 confirm→派生正确 | ✅ | 项目 100：confirm[155]→[active,pending,pending]→pending；reject[156]→[active,terminated,pending]→**pending**；confirm[157]→[active,terminated,active]→**active**（日志 3 条「确认下单（1 份）×2 + 驳回订单」） |
| C.7 | 校验范围=勾选：取消勾 0 元/空合同、只确认正常合同→能确认 | ✅ | 项目 101：confirm[159]（158 零元不勾）→**200**、159 active、158 仍 pending、项目 pending；反向 confirm[158]→400「存在未定价明细，请先填写单价/销售金额」（守卫按选中集合判定） |
| C.8 | sticky 合计=勾选 contractTotal 之和（实时、勾/取消实时变） | ✅ | 6300（全勾含总价 300）→取消勾 1500 合同→4800；700→取消勾 300 合同→400，均即时 |

### D. 权限 / 守卫 / 提示卡

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| D.1 | viewer/finance 进 review 页被守卫拦；未分配→提示卡+「分配」；非负责人（非 admin/supervisor）→无权限卡 | ✅ | eco01(viewer) 直访 /sales/projects/115/review→静默重定向 /assets/embodied（viewerAllowedPath 不含 review）；fin01(finance)→toast「财务账号仅可浏览『产品及服务』」+重定向；未分配项目 95（sup01）→提示卡「该订单尚未分配商务负责人，请先由商务主管『分配』后再审核」+「分配」按钮（截图 D1_unassigned.png）；非负责人 editor（biz02 看 biz01 名下 115）→bootstrap 可见性过滤（editor 仅名下）→「项目不存在或无查看权限」重定向列表（无权限卡为兜底分支，正常可见性下 editor 遇不到，后端 403 兜底见 D.2） |
| D.2 | 确认/驳回后端鉴权：viewer/finance 403、非负责人 403 | ✅ | eco01 review→403「只读账号不可执行该操作」；fin01 reject-contracts→403 同文案；biz02（非负责人）review→403「仅接手的商务负责人（biz01）可调整该订单价格，如需处理请先转交」；未分配 95 review→400「该订单尚未分配，请先由商务主管分配」 |

### E. 护栏回归

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| E.1 | 详情页 ADR-056 勾选/单一/批量驳回不回归 | ✅ | `detail.vue` 未被 ADR-057 改动（git log 最近提交 ADR-045/046 早于本批）；reject-contracts 接口经 C.5/C.6 全链路复验；浏览器详情页（115）「销售记录清单」+「批量驳回（0）」按钮+勾选列在（截图） |
| E.2 | 整单确认（不传 contractIds）=改前行为 | ✅ | 项目 102 不传 contractIds：改价（150→160）/数量（4→6 锁定 6→8、5→4 锁定 7→6）/amount 缩放（1500→1200）/客户名（戊客户→戊客户改名）/服务期限（2026-07-01~2026-12-31）全落库；**日志无「（N 份）」后缀**「订单已确认，改价：…」；项目 103 纯整单确认 200；项目 95 未分配整单确认 400（守卫先于 targets）；整单 reject（项目 106）→2 合同 terminated+remark、项目 terminated、锁定释放（52:22→21、50:9→8） |
| E.3 | 审核页→返回详情正常；确认全部后跳详情、项目状态正确 | ✅ | 「返回详情」按钮跳 /detail 数据正常；项目 107 全确认后自动跳 /sales/projects/107/detail、项目 active（截图 E3_detail_after.png） |
| E.4 | 派生：[active,pending]→pending、[active,terminated]→active、[active,terminated,pending]→pending | ✅ | 项目 99 部分确认后 [active,active,pending]→pending；项目 100 混用过程 [active,terminated,pending]→pending、[active,terminated,active]→active；项目 104 [active,terminated]→active；项目 101 [active,pending]→pending |
| E.5 | 下游：确认不改锁定（数量不变）、驳回释放锁定、遥感明细回 in_stock | ✅ | 项目 99 部分确认 154 未勾期间锁定保持（locked=true 不变）；项目 100 驳回 156→asset50 8→6；项目 105 遥感合同 167 驳回→**rs10 回 in_stock**、asset29 10→9、项目 pending；项目 104 遥感确认后 rs9 保持 all_sold（确认不释放） |
| E.6 | vue-tsc EXIT=0 | ✅ | `cd frontend && LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu npx vue-tsc -p tsconfig.app.json --noEmit` → EXIT=0 |

### 缺陷与观察

1. **BUG-ADR057-001（中，frontend-dev）**：部分确认/驳回后剩余 pending 合同丢失默认勾选（详见 bug-tracker；根因=watch 不重勾「仍在列表但曾被取消」的 id；修复建议=watch 幂等重置或 refresh 后显式重勾）。
2. **OBS-ADR057-01（低，非缺陷）**：前端恒传 `contractIds`（含勾全选场景），后端按「contractIds 非 null」加日志「（N 份）」后缀——勾全选时日志为「订单已确认（3 份）」，与 ADR「整单确认日志格式不变」字面有出入；行为语义等价（勾全选=整单），仅日志展示差异。若要求严格一致，可前端在勾全选时不传 contractIds（或后端按 targets==全部 pending 判定）。
3. 本轮写操作流转了 QA 产品 47/48/49/50/51/52/53 与遥感明细 9/10 的锁定/售卖数量，测试数据 QA057- 前缀全部保留供验收（项目 99-115、合同 152-209）。

## 2026-11-04 ｜ ADR-054 账号/用户管理三处增强回归明细（A/B/C/D 全量，无新缺陷）

> 事实来源：`docs/adr/ADR-054.md` + `docs/backend/api.md` 改密小节。验收基准 = 用户 3 条需求（① 账号列表分页+过滤；② 非管理员自助改密（校验旧密码、改后保持登录、踢旧会话）；③ 建号密码自动随机）。

**测试数据（保留供验收）**：`QA054-selfpw`（id 36，viewer）、`qa054rand`（id 37，viewer）、`QA054-rand2`（id 38，viewer，密码 `Ab3kQ7mZx9wL`）、`QA054-ui-rand`（id 39，viewer，密码 `F4kADQzx4LTU`，UI 随机生成）；`QA054-crud`（id 40）CRUD 回归后已删除。改过密码的 biz01/fin01/eco01/admin 均已重置回 `123456` 并复验登录 200。

### A. 账号列表分页 + 过滤（admin，浏览器 :5173/settings/users）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | 关键字「QA」→ 仅 3 条（QA054-selfpw/qa054rand/QA054-rand2），大小写不敏感（`qa054rand` 命中） | ✅ | 「共 3 条」；截图 /tmp/qa054-a2-filter-qa.png |
| A.2 | 角色「商务人员」→ 仅 9 条 editor | ✅ | 「共 9 条」，首行 editor；截图 /tmp/qa054-a3-filter-editor.png |
| A.3 | 状态「禁用」→ 0 条空态「暂无账号」（当前无禁用账号） | ✅ | 「共 0 条」；截图 /tmp/qa054-a4-filter-disabled-empty.png |
| A.4 | 组合（关键字 QA + 角色商务人员 + 状态启用）→ 0 条（QA 号均 viewer，交集正确） | ✅ | 「共 0 条」；截图 /tmp/qa054-a5-filter-combo.png |
| A.5 | 清空过滤 → 回 38 全量 | ✅ | 「共 38 条」 |
| A.6 | 翻第 2 页（10/页）→ 首行 admin2（全量第 11 条） | ✅ | 截图 /tmp/qa054-a6-page2.png |
| A.7 | 切 20 条/页 → 20 行；切 50 条/页 → 38 行（全量） | ✅ | 行数 120/38 单元格计数；截图 /tmp/qa054-a7-size50.png |
| A.8 | 第 2 页输入关键字 → 自动回第 1 页且表格为过滤结果 | ✅ | 输入 QA 后首行 QA054-selfpw、页码仅「1」 |
| A.9 | **统计卡（总数/启用/管理员）在过滤、翻页、切条数时恒为全量值 38/38/4**（客户端分页未把统计卡算成当前页） | ✅ | 初始/第 2 页/20 条/页/50 条/页四次读取均为 38/38/4；代码核对 `stats` computed 基于全量 `users`（users.vue L74-78） |

### B. 自助改密（跨角色）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | biz01 顶栏 user-chip 下拉出现「修改密码 / 退出登录」 | ✅ | 截图 /tmp/qa054-b1-wrong-oldpw.png |
| B.2 | 旧密码错 → 400「旧密码不正确」，前端 toast 同文案 | ✅ | curl 400 `{"detail":"旧密码不正确"}`；浏览器 StaticText「旧密码不正确」 |
| B.3 | 旧密码对 + 新密码 ≥6 + 确认一致 → 200 返回 `{token,user}` + toast「密码已修改」 | ✅ | curl 200；浏览器「密码已修改」；截图 /tmp/qa054-b2-pwd-changed.png |
| B.4 | **改密后不刷新不掉线**：继续切菜单（销售项目/首页）数据请求 200，无「登录状态已失效」 | ✅ | 截图 /tmp/qa054-b3-no-logout.png（132 单元格数据正常） |
| B.5 | **localStorage token 已换发**：JWT payload `ver` 6→7（第一次）、7→8（第二次） | ✅ | `agent-browser eval` 解码前后 token |
| B.6 | **旧会话被踢**：改密前签发的旧 token `GET /auth/me` → 401「登录状态已失效，请重新登录」；`/bootstrap` 亦 401 | ✅ | curl 401；新 token 同接口 200 |
| B.7 | 新密码 <6 位：后端 422（`string_too_short min_length=6`）；前端拦截「新密码不能为空且至少 6 位」不发请求 | ✅ | curl 422；浏览器 toast 文案 |
| B.8 | fin01（finance，/assets 页面）改密成功、不掉线（切卫星服务数据正常） | ✅ | 「密码已修改」+ ver=4；截图 /tmp/qa054-b5-eco01-assets.png |
| B.9 | eco01（viewer）改密成功、不掉线 | ✅ | 「密码已修改」+ ver=3；切菜单 110 单元格数据正常 |
| B.10 | 改后能用新密码登录（biz01 `qa054b` 登录 200） | ✅ | 浏览器登录成功 |
| B.11 | 审计落「修改密码」/「修改密码失败 旧密码不正确」（auth 类） | ✅ | `GET /audit-logs` 多条记录 |
| B.12 | 改过密码的账号已重置回 `123456`（admin PUT）并复验登录 200 | ✅ | biz01/fin01/eco01 均 200 |

### C. 建号随机密码（admin）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| C.1 | 新建弹窗密码框有「随机生成」按钮；点击填入 12 位、含大写+小写+数字、无 0/O/1/l/I | ✅ | `jkcFsfq7mJR2` / `F4kADQzx4LTU`（脚本断言 len=12、三类齐、无易混） |
| C.2 | 再点重新生成 → 值变化 | ✅ | 两次值不同 |
| C.3 | `show-password` 可切明文（input type password→text） | ✅ | `get attr type` = text，值明文可见 |
| C.4 | 编辑已有账号弹窗**无**随机按钮，密码框为「重置密码 / 留空则不修改密码」语义 | ✅ | 截图 /tmp/qa054-c2-edit-no-random.png；代码核对 `v-if="!dialog.editing"`（users.vue L524） |
| C.5 | 用随机密码保存建号成功（QA054-ui-rand），且能用该随机密码登录 | ✅ | 「账号已创建」；curl 登录 200；截图 /tmp/qa054-c1-create-random.png |

### D. 护栏回归

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| D.1 | admin `PUT /users/{id}` 带 password 重置他人（biz01/fin01/eco01）与**自己**（admin id=1）密码，不校验旧密码，仍工作 | ✅ | 均 200，重置后登录 200 |
| D.2 | 登录/登出正常：退出确认弹窗「确定退出当前账号吗？」→ 退出 → /login；顶栏 dropdown 未破坏退出 | ✅ | 截图 /tmp/qa054-d1-logout-check.png、/tmp/qa054-d2-logout-confirm.png |
| D.3 | 五角色可见性：fin01 菜单仅「产品及服务」；直访 /settings/users、/dashboard 均拦回 /assets/embodied；biz01 直访 /settings/users 拦回 /dashboard；admin 正常访问 | ✅ | URL 实测；eco01 菜单亦仅「产品及服务」 |
| D.4 | 账号 CRUD：建（200）/改角色 viewer→editor（200）/禁用（200，期间登录 401）/启用（200）/删除（200，删后登录 401） | ✅ | curl 全链路（QA054-crud id 40） |
| D.5 | 新号 `createdAt` 有值且列表「创建时间」列显示时间（不再恒 `-`）；全量 37→38 号均有时分值 | ✅ | QA054-ui-rand 列显 `2026-11-04 09:15`；`UserOut` 含 createdAt |
| D.6 | `vue-tsc -p tsconfig.app.json --noEmit` EXIT=0 | ✅ | 日志 /tmp/qa054-vue-tsc.log |

**观察项（非缺陷）**：改密弹窗提交失败（如旧密码错）时弹窗保持打开、表单值保留，符合「失败可重试」交互；成功才关闭。

**结论**：A/B/C/D 全量通过，无新缺陷；满足用户 3 条需求，可交付。

---

## 2026-11-04 ｜ ADR-052 购物车销售金额双向区间约束回归明细（A/B/C 全量，无新缺陷）

> 事实来源：`docs/adr/ADR-052.md` + `docs/backend/api.md` 购物车小节。验收基准 = 用户拍板三条口径（① 包量/Token amount 模式不卡区间；② 存量超上限行结算拦截、无迁移；③ 审核改价不限区间、手工建单保持双向）。

**测试数据（保留供验收）**：admin 建 5 个产品——`QA052-Unit-区间`（id 48，unit，[1000,2000] 元/套）、`QA052-包量-Token`（id 49，amount，[100,200]）、`QA052-Unit-仅下限`（id 50，[100,∞)）、`QA052-Unit-仅上限`（id 51，(0,500]）、`QA052-Unit-无区间`（id 52）；产生项目 77（QA052-C2-结算改回区间内，active）、78（QA052-eco01下单，pending/biz02）、79（QA052-结算-UI，pending）。

### A. 后端（curl，真实 :8000）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | `POST /cart` 产品48：999→400 / 2001→400 / 1500→200 | ✅ | 400 文案 `销售金额超出该产品参考区间（1,000.00~2,000.00 元/套）` |
| A.1 | `PATCH /cart/25`（带 customer）：999→400 / 2001→400 / 1500→200 | ✅ | 同文案；不带 customer 为 422（`customer` 必填，既有契约） |
| A.1 | `PUT /cart/25`：999→400 / 2001→400 / 1500→200 | ✅ | 同文案 |
| A.2 | 造存量超上限行（SQLite 直插 cart_items id26 amount=2500>max）→ `POST /cart/checkout` → 400，事务回滚（2 行原样保留、未建项目） | ✅ | 400 同文案；回滚后 `SELECT` 两行未变 |
| A.2 | 该行改回 1800（区间内）→ checkout 200，项目 77：expectedAmount=3300=1500+1800，items 金额 1500/1800 落库正确 | ✅ | `SP-2026110406311573` |
| A.3 | amount 产品49：POST 5000（>max）→200；PATCH 0.05（<min）→200；PUT 999999→200；amount=0→400（`>0 + ≤6 位小数` 校验保留） | ✅ | 不卡区间，仅走 `_cart_amount` |
| A.4 | 项目77（pending，先 claim→biz01）`POST /review` confirm `price=5000`（>max 2000）→200，落库 price/amount=5000，项目 active | ✅ | 审核改价不受区间限制（唯一高于上限合规出口） |
| A.5 | `POST /projects` 产品48：price=2500→400 / price=900→400（`销售单价超出该产品参考区间（…）`，ADR-029 既有文案） | ✅ | 手工建单双向未变 |
| A.6 | 产品52 无区间：50→200 / 99999→200；产品50 仅下限：99→400（`≥100.00 元/套`）/ 99999→200；产品51 仅上限：501→400（`≤500.00 元/套`）/ 1→200 | ✅ | 单边/无区间兜底未变 |
| A.7 | 透传一致性：区间内加购放行 → 结算不 400（A.2 改回后 200 已覆盖；无「购物车放行、结算 400」） | ✅ | 与 `checkout` 内 `enforce_max=True` 透传 `_create_project_core` 同口径 |
| A+ | viewer（eco01）双向复核：2001→400 / 999→400 / 1500→200（ADR-037 分角色口径已作废，任何角色一致） | ✅ | 同文案 |

### B. 前端（:5173，agent-browser 登录 admin）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | 表头 = 产品名称/客户*/数量/销售金额（元）*/服务期限/小计/操作，**无「销售单价」列** | ✅ | snapshot columnheader 逐项 + 截图 `/tmp/qa052_B1_headers.png` |
| B.2 | 「可售 N」副提示在销售金额列（`可售 97`/`可售 1000`/`可售 100`）；qty=100 达可售时显示 `已达上限 100` | ✅ | 截图 `/tmp/qa052_B2_limit_reached.png` |
| B.3 | unit 行金额 999（<min）→ 标红（`.cart-customer-error`，box-shadow `rgb(217,83,79) inset`）+ 点结算被拦；2001（>max，本次新增）→ 同样标红+被拦；1500 区间内 → 不标红、可结算 | ✅ | 截图 `/tmp/qa052_B3_below_min.png`、`/tmp/qa052_B3_above_max.png` |
| B.4 | amount 行金额 5000（>max 200）→ **不标红**（无 error class），可提交 | ✅ | 截图 `/tmp/qa052_B4_B5_no_red.png` |
| B.5 | 无区间 unit 行金额 99999 → 不标红（且无区间提示行） | ✅ | 同上截图 |
| B.6 | 顶部提示条「设参考区间时销售金额须在参考区间内（**不得低于下限、不得高于上限**）」；行内「参考区间 1000~2000 元/套（须在此范围内）」 | ✅ | snapshot StaticText 逐字核对 |
| B.7 | 越界行点结算 → `1 行信息未填齐：请填写销售金额须在参考区间内`（含要求文案）；改回 1500 → 结算成功（项目 79，3 份销售记录） | ✅ | 截图 `/tmp/qa052_B7_blocked_below.png` |

### C. 护栏回归

| # | 断言 | 结果 |
|---|---|---|
| C.1 | ADR-049 保留结论：审核改价不限区间（A.4）+ 手工建单双向（A.5）复核 | ✅ |
| C.2 | ADR-012/051 不受影响：eco01 下单（项目78 pending）→ sup01 claim 转交 biz02 成功 | ✅ |
| C.3 | 删列不影响金额：UI 下单项目79 落库 items 1500/5000/99999，expectedAmount=contractAmount=106499=Σ，与前端小计一致 | ✅ |
| C.4 | 数量锁定/库存约束：eco01 `PUT /cart/25 qty=101`（可售 98）→ 400 `购物车中 QA052-Unit-区间 合计 101 超出可售 98`，行未变（回滚） | ✅ |
| C.5 | `vue-tsc -p tsconfig.app.json --noEmit` EXIT=0 | ✅ |

**观察项（不计缺陷）**：越界拦截提示为 `请填写销售金额须在参考区间内`（「请填写」前缀 + 区间短语拼接，语义略拗口但含 ADR 要求文案，属既有 `openOrder` 拼接模式，非 ADR-052 引入）。

---

## 2026-11-04 ｜ ADR-051 权限体系升级回归明细（A–F 全量，无新缺陷）

### 执行方式

- **环境**：:8000（测试库，可写）+ :5173（vite dev）；测试账号 `admin`/`sup01`/`biz01`/`biz02`/`fin01`/`eco01`（角色 admin/supervisor/editor/editor/finance/viewer，登录响应角色字段已核对）。
- **后端**：curl 真实 HTTP（Bearer token），bootstrap 字段级核对 + `GET /audit-logs` 审计核对 + 落库（businessOwner/status/lockedQty/customer）复核。
- **前端**：agent-browser 五角色浏览器实测（菜单/tag/按钮/下拉/拦截提示/配色 computed style）；`vue-tsc -p tsconfig.app.json --noEmit` EXIT=0。
- **测试数据（保留，QA051- 前缀）**：项目 59（QA051-P1，delivering，owner=biz01）、60（QA051-P2，pending，owner=biz02）、61（QA051-P3，pending，owner=biz01）、62（QA051-P4，active，owner=biz01）、63（QA051-E1-撤销单，terminated）、64（QA051-E1-终止单，terminated）、65/69（QA051-E1-主管撤销，terminated，首跑截断重复建单）、66/70（QA051-E3-自接单，active，owner=biz02）、67/71（QA051-E3-主管审核，active，owner=biz01）、68/72（QA051-E3-驳回单，terminated，owner=biz01）、73（QA051-E3-客户名单，active，owner=biz01，客户「QA051改客户」）、74（QA051-E5-超可售，terminated，owner=biz02）、75（QA051-F-待分配，pending，owner=biz01，浏览器分配）、76（QA051-F-审核页待分配，pending，**未分配**，供验收分配入口）；产品 45/46/47（QA051-矩阵测试产品 ×3，可删）；交付单 3 条（P1，biz01/sup01/admin 各 1）；主体 QA051-主体-* 已清理。

### A. 角色 × 能力矩阵（35/35 ✅）

| 角色 | 下单 POST /cart | 编辑产品 POST /assets | 看销售项目(bootstrap) | 审核 POST /projects/{id}/review | 交付 POST /outbounds | 主体 GET /entities |
|---|---|---|---|---|---|---|
| eco01 viewer | ✅ 200 | ✅ 403「只读账号不可执行该操作」 | ✅ 仅自己（含 P1/P2，creator 全状态） | ✅ 403 | ✅ 403 | ✅ 200 全量(6) |
| biz01 editor | ✅ 200 | ✅ 200(id=45) | ✅ 仅 businessOwner==biz01（P2 未分配不可见） | ✅ 名下 200 / 未分配 400 | ✅ 200 | ✅ 200 全量 |
| sup01 supervisor | ✅ 200 | ✅ 200(id=46) | ✅ 全部（含未分配池 P2） | ✅ 任意可见单（未分配 400 文案正确） | ✅ 200 | ✅ 200 全量 |
| fin01 finance | ✅ 403「财务账号为只读，不可执行该操作」 | ✅ 403 | ✅ 0 条 | ✅ 403 | ✅ 403 | ✅ 200 `[]` |
| admin | ✅ 200 | ✅ 200(id=47) | ✅ 全部 | ✅ 任意（未分配 400） | ✅ 200 | ✅ 200 全量 |

- 未分配单审核：`biz01/sup01/admin` 均 400「该订单尚未分配，请先由商务主管分配」（守卫正确，非 403 泄漏）。
- 合同时间分权：`sup01` 录 `signedDate` 200（合同 → delivering）；`sup01` 录 `scheduledDeliveryDate` **403「仅管理员可录入预计交付时间」**；`admin` 录 200。

### B. 数据隔离（18/18 ✅，bootstrap 字段级）

| 断言 | 结果 |
|---|---|
| biz01/biz02 不含未分配 P2 | ✅ |
| sup01/admin 含 P2（未分配池）；eco01 含 P2（creator 本人） | ✅ |
| fin01：projects=contracts=outbounds=0、entities=0、assets 全量(40) | ✅ |
| 已分配 P3（owner=biz01，creator=biz01）：biz01 可见 / biz02 不可见 / sup01+admin 可见 / eco01（非 creator）不可见 | ✅ |
| 已分配 P1（owner=biz01，creator=eco01）：biz01 可见 / biz02 不可见 / eco01 可见（creator 分支） | ✅ |
| 关联资源同域：biz01 contracts 项目集 {54,56,58,59,61}、outbounds 仅 P1；biz02 仅存量 {55} | ✅ |

### C. 分配链路（13/13 ✅）

1. `sup01 claim P2→biz01` 200；落库 `businessOwner=biz01`；OpLog「分配订单（商务负责人绑定为 biz01）」+ 审计「分配订单」✅。
2. 分配后 biz01 bootstrap 立即可见 P2；biz02 仍不可见 ✅。
3. `sup01 claim P2→biz02` 200；落库 biz02；OpLog「改派订单（商务负责人 biz01 → biz02）」+ 审计「改派订单」；biz01 转不可见、biz02 可见 ✅。
4. `biz01` 对 biz02 名下单 claim（带/不带 newOwner）→ **400「该订单由商务负责人「biz02」负责，如需改派请联系商务主管处理」**（含「商务主管」，不可抢单）✅。
5. `sup01` 对未分配 pending（P4）review → **400「该订单尚未分配，请先由商务主管分配」**；分配后 review 200 ✅。
6. 分配下拉（浏览器，sup01 分配对话框）：选项 = 8 个 **全部 editor**（测试编辑/吴浩/吴浩二/罗杰/刘丹红/谢优/周靖人/商务01/商务02 去重后 8 项），**无 admin（系统管理员/刘尚坤-admin/龚俊明）、无 supervisor（商务主管01）** ✅（已对照 `/users` 角色逐一核验）。
7. 终态单 claim：terminated #57 上 `sup01/admin/biz01` 均 400「该订单已完成/已终止，不可接手或转交」✅。
8. 浏览器端到端：sup01 列表未分配行「分配」按钮 → 对话框「分配销售订单…请选择目标商务账号」→ 选 biz01 → 「确认分配」→ toast「分配成功，商务负责人已指定」→ 落库 owner=biz01 ✅。

### D. 财务只读（12/12 ✅）

- 读放行：bootstrap assets 全量(40)、`GET /assets/29/rs-items` 200、flows/logs 200 ✅。
- 写 403：`POST/PUT /assets`、`POST /cart`、`checkout`、`POST /projects`、`withdraw`、`claim`、`POST /outbounds`、`POST /entities` 全部 403（文案「财务账号为只读…」/「只读账号不可执行该操作」）✅。
- 主体：`GET /entities` 200 `[]`；bootstrap entities=0 ✅。
- 前端：菜单**仅「产品及服务」**（无销售管理/购物车/交付/公司主体/首页）；「登记产品」「加入购物车」按钮 disabled；直连 `/sales/projects`、`/cart`、`/settings/entities`、`/dashboard` 全部拦回 `/assets/embodied` + toast「财务账号仅可浏览「产品及服务」」✅。

### E. 回归（18/18 ✅）

1. **生态（eco01）完全不变**：下单 200；看自己单全状态（pending/delivering/terminated 均可见）；withdraw 200 `restored=1` 且回填购物车；终止自己 pending 200；refill-cart 200 `restored=1` ✅。`_can_withdraw` 口径不变：sup01 撤销 eco01 单 403「只能撤销自己提交的订单」、admin 撤销 200 ✅。
2. **admin 全权不变**：删项目 200、用户管理 200（35 用户）、审计 200、主体全量、全量可见 ✅；sup01 用户管理 403（`require_admin` 未放宽）✅。
3. **ADR-012 保留**：biz01 自接自己 creator 的无主单 200（落库 owner=biz01）；负责人转交 biz01→biz02 200；被分配商务 biz02 confirm（带 ADR-050 改价 price=1200 落库 + 合同级客户名「QA051改客户」落库 + Project.customer 重派生）200；sup01 兜底 confirm 200；biz01 reject 200 ✅。
4. **产品/交付/主体编辑权**：admin/supervisor/editor 三角色 `POST /assets` 200、`POST /outbounds` 200、`POST /entities` 200（主体已清理）✅。
5. **数量锁定不变量**：asset 26（可售 1）下单锁 1 后，biz01 confirm 改 qty=2 → **400「第 118 行可用库存不足（需 1，当前可售 0）」**，整事务回滚（项目仍 pending、locked 仍 1、明细 qty 仍 1，无半态）；reject 后 locked 归 0 ✅。

### F. UI（agent-browser 五角色实测，✅）

- 角色 tag：商务主管01=「商务主管」、财务01=「财务」、商务01=「商务人员」、生态01=「生态人员」、admin=「管理员」✅。
- 菜单：sup01 = 首页概览/产品及服务/销售管理（含购物车角标）；biz01 同 editor 现状；eco01 = 产品及服务/销售项目/购物车（不变）；admin 全量含账号与审计/公司主体 ✅。
- sup01 列表：未分配行显示「未指派」+「分配」「审核订单」按钮；已分配行显示「改派」；「全部商务负责人」筛选含「未指派 / 历史数据」档，筛出 7 条未分配单 ✅。
- 未分配 pending 审核页：顶部「分配」按钮 + 提示「该订单尚未分配商务负责人，请先由商务主管「分配」后再审核。」✅（截图 `/tmp/qa051/sup01-review-unassigned.png`）。
- biz01 列表：仅名下 12 条、0 个「分配/改派」按钮、未分配单（PG）不可见 ✅（截图 `/tmp/qa051/biz01-list.png`）。
- fin01：仅产品菜单 + 直连拦截（截图 `/tmp/qa051/fin01-menu.png`）✅。
- 账号与审计建号下拉：管理员/商务主管/商务人员/生态人员/财务 5 角色 ✅。
- 配色：`--primary-color=#1769d4`、表头 `#F8FAFC`、link 按钮 `rgb(23,105,212)`（is-link 未刷实心蓝底）——符合 core-holdings-ui，无新主色 ✅。
- 前端类型：`vue-tsc -p tsconfig.app.json --noEmit` EXIT=0 ✅。

### 观察项（不计缺陷）

- 手动 `POST /outbounds` 补录不受项目剩余数量上限约束：同一明细（qty=1）连续 3 次补录均 200（P1 产生 3 条 done 交付单，项目停留在 delivering）。为既有行为（非 ADR-051 引入，矩阵 A 交付端点验证时触发），如需「补录不超剩余」约束建议后续 ADR 明确。

## 2026-11-04 ｜ 全站金额输入框修复回归明细（7 框 × 5 症状 35/35 + 3 链路落库核对，无新缺陷）

### 执行方式

- **环境**：:5173（vite dev）+ :8000（测试库，可写），agent-browser 登录 `editor`；全部在真实数据页面操作。
- **每框 5 项症状**（用户原话复现口径）：T1 逐字键入 `1234.56`（不自动弹小数点/数字打得进/光标不乱跳）；T2 `keyboard inserttext` 粘贴 `1,234.56`（逗号被清）；T3 键入 `123456` 后连续 Backspace（逐位删除、不整段重写）；T4 中间态 `12.` / `0.`（小数点不被吞）；T5 键入 `1.1234567`（截断 6 位）。断言读 DOM `input.value`（`agent-browser get value` / `eval`）。
- **提交正确性**：改值保存后 `GET /api/bootstrap` 落库核对（number 本身、无 NaN、无 `"1,234.56"` 逗号串、≤6 位小数）。
- **约束遵守**：未改任何业务代码、未 build、未 commit。测试数据残留（可辨识）：项目 54「QA金额回归-0237」（pending）、出库 CK-0002、rs-item#1（新疆）price 27400→27400.123456 / priceMin null→1234.56。

### 结论：7 个输入框 35/35 通过 + 提交/展示/数量抽查全部通过

| # | 输入框（页面） | T1 逐字 | T2 粘贴 | T3 Backspace | T4 中间态 | T5 截断 | 证据 |
|---|---|---|---|---|---|---|---|
| 1 | 遥感明细单价（assets/detail，资产 29 明细 1 编辑弹窗） | ✅ 1234.56 | ✅ 1,234.56→1234.56 | ✅ 123456→12345→1234→123 | ✅ `12.`/`0.` 保留 | ✅ 1.1234567→1.123456 | 截图 `/tmp/qa-rs-price-1234.56.png` |
| 2 | 参考价下限（同上弹窗） | ✅ | ✅ | ✅ 123456→12345→1234 | ✅ `12.` 保留 | ✅ | 同上会话 |
| 3 | 参考价上限（同上弹窗） | ✅ | ✅ | ✅ | ✅ `12.` 保留 | ✅ | 同上会话 |
| 4 | 销售金额（sales/outbound 补录弹窗） | ✅ | ✅ | ✅ | ✅ `0.` 保留 | ✅ | 提交 CK-0002 |
| 5 | 单价行（sales/projects/create 明细行） | ✅ | ✅ | ✅ | ✅ `12.` 保留 | ✅ | 提交项目 54 |
| 6 | 参考价下限（assets/create） | ✅ | ✅ | ✅ | ✅ `0.` 保留 | ✅ | 截图 `/tmp/qa-assets-create-amounts.png` |
| 7 | 参考价上限（assets/create） | ✅ | ✅ | ✅ | ✅ `0.` 保留 | ✅ | 同上 |
| 8 | 销售单价（assets/create，frontend-dev 已测，复测确认） | ✅ | ✅ | ✅ | ✅ `0.` 保留 | ✅ | 同上 |

### 提交正确性（绑定口径未变，收到的值 = 输入的 number 本身）

| 链路 | 输入 | 落库核对（bootstrap） | 结果 |
|---|---|---|---|
| 遥感明细保存（`PUT /rs-items/1`） | 单价 `27400.123456`、下限 `1234.56`、上限清空 | `price=27400.123456`、`priceMin=1234.56`、`priceMax=None`（均 number，6 位小数完整） | ✅ |
| 出库登记（`POST /outbounds` → CK-0002） | 金额 `1234.56`、数量 2、产品 38 | `amount=1234.56`、`qty=2` | ✅ |
| 项目创建（`POST /projects` → 项目 54 / HT-2026110402373685） | 单价 `1234.56` × 数量 60 | 行 `price=1234.56`、`qty=60`、`amount=74073.6`、`contractAmount=74073.6` | ✅ |

### 只读展示与数量输入抽查（未受污染 / 未受影响）

- 只读展示：遥感明细列表 `¥27,400.123456（参考区间 ≥1234.56）`（千分位 + 最少 2 位/最多 6 位，ADR-048 口径）✅；新建项目页只读合同金额框 `74,073.60`（`amountDisplayFormatter`：千分位 + 两位小数）✅。
- 数量 `el-input-number`（outbound 补录，`:precision="0" :step="1"` 带步进、无金额 formatter）：键入 `12.7` 失焦 → `13`（取整正常）、`+`/`−` 步进 122→123→122 正常 ✅；create.vue 数量列同规格联动金额重算正常（60 × 1234.56 = 74073.60）✅。
- 全站使用点核对：`amountInputFormatter` 共 12 处 `el-input-number`（review 4 / detail 3 / create(assets) 3 / outbound 1 / create(projects) 1）+ 包量定价 `el-input`（sanitizeAmountInput）1 处，无残留旧 formatter；`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0。

### 备注（非缺陷）

- agent-browser 的 a11y 快照对 EP spinbutton 偶发报浮点噪声值（如 `1234.56005859375`、`74073.6015625`），与 DOM `input.value` / `aria-valuenow` 实测值（`1234.56` / `74,073.60`）不一致；已用 `eval` 直读 DOM 与重放序列排除应用侧问题，判定为辅助功能树读取时序产物，不影响用户可见值与提交值。

## 2026-11-03 ｜ ADR-050 回归验证明细（18/18 后端断言 + 前端类型检查 + 浏览器实测，无新缺陷）

### 执行方式

- **后端**：拷贝测试库（:8000 已运行，可读写），`POST /api/auth/login`（editor）拿 Bearer token；`POST /api/projects`（contracts 结构）独立建 15 个 pending 测试单（每 confirm 类用例独立项目，避免状态污染），`POST /api/projects/{id}/review` 逐项触发，`GET /api/bootstrap` 落库核对（合同/行/项目/资产 lockedQty/流水）。
- **前端**：`vue-tsc -p tsconfig.app.json --noEmit` 退出码 0；agent-browser 登录 editor 实测审核页（DOM 计算样式 + 截图 + XHR 钩子抓 review 请求体）。
- **约束遵守**：未改任何业务代码、未 build、未 commit；测试单保留在拷贝库中（项目名 `QA050-*`，可辨识清理）。

### 结论：A/B/C/D/E 全部通过

| # | 用例 | 结果 | 关键证据（节选） |
|---|---|---|---|
| A1 | 单合同总价 12000（3 行各 3000） | ✅ | `contract.contractAmount=12000`、Σ行=12000（1e-6 精确）、行单价重派生 1333.333333/1333.333333/400、`project.contractAmount=expectedAmount=12000`、项目/合同 active |
| A2 | 多合同（C55→3000、C56→5000） | ✅ | 两合同各自独立分摊互不影响（行 68 amount=3000 price=1500、行 69 amount=5000），项目总额=8000=Σ合同 |
| A3 | 四舍五入残差（总额 12000.000001，3 行均分） | ✅ | 每行 4000.000000333→4000.000000，残差 +1e-6 落金额最大行（并列取首行 65=4000.000001），Σ行=12000.000001 精确成立 |
| A4 | 边界：amount=0 / 7 位小数 / 留空 | ✅ | `0` 与 `1234.5678901` 均 400「销售金额须大于 0 且最多保留 6 位小数」；仅传 customer → 200，`contractAmount=1000`=Σ明细派生（不覆盖） |
| B5 | 改客户名落库 + `Project.customer` 重派生 | ✅ | 单客户=该值（P47 `QA-客D2`）；多客户不同名=空串（P48 `''`，前端显「N 位客户」口径） |
| B6 | 冲突守卫 | ✅ | 同客户名+明细集完全相同（两合同均 asset43）→ 400「客户「QA-客C1」下相同的销售明细不可重复（与 HT-… 冲突）」且事务回滚（项目仍 pending）；同客户名但明细集不同（{42} vs {43}）→ **200 放行（未被误拦）** |
| B7 | 客户名空白 / 129 字 | ✅ | 后端 400「客户名称不能为空」/「不能超过 128 字」，customer 未被污染；前端确认按钮 `disabled`（DOM 实测 `aria-disabled=true`）+ tooltip 提示 |
| C8 | unit 行改数量放大/缩小 | ✅ | 放大 2→5：amount=1000×5=5000、`lockedQty` 净 +3、`project_lock` 流水（qty=3, contractId）；缩小 5→2：amount=2000、`lockedQty` 净 −3、`cancel_release` 流水（qty=3） |
| C9 | 放大超可售 → 400 + 整事务回滚 | ✅ | 可售 4、delta=5 → 400「第 83 行可用库存不足（需 5，当前可售 4）」；回滚核对：项目/合同仍 pending、行 qty/amount/customer 未变、`lockedQty` 不变、**无新增流水**（无半态/无超卖） |
| C10 | amount 模式行改数量 | ✅ | 只传 qty 10→20 → 金额按比例缩放 3000→6000（price 派生 300）；传 qty+amount → amount 权威（8000，price 400） |
| C11 | repeatSale 行改数量 | ✅ | qty 3→8：amount=8000 随数量、`lockedQty` 0→0 不变、无锁定类流水（仅计次） |
| C12 | 遥感行传 qty=5 | ✅ | qty 恒 1（忽略传入）、仅 amount 生效（7000） |
| D13 | reject 带 contracts+items[].qty | ✅ | 全部忽略：项目/合同 terminated、`remark='驳回：QA驳回原因'`、customer/contractAmount/行 qty/amount 均未变、`lockedQty` 释放 2（cancel_release 流水 ref=合同 code、contractId=68） |
| D14 | 旧 payload（仅 price） | ✅ | 200、行为与 ADR-050 前一致（price=500 → amount=500） |
| D15 | ADR-049 / ADR-018 保持 | ✅ | 改价 500 < priceMin 900 仍放行（审核链路不走参考区间）；`assets.salePrice` 1000→1000 不回写、`origPrice/origAmount` 快照不变 |

### E. UI 实测（agent-browser，editor 账号，:5173）

| # | 用例 | 结果 | 关键证据 |
|---|---|---|---|
| E16 | 三处新输入 | ✅ | 合同总价 `el-input-number` `is-without-controls`（DOM 实测）+ 浅蓝 info-bar（`rgb(240,246,255)`=#F0F6FF）分摊提示「确认后按各明细行金额比例分摊到明细（总额权威）」；客户名 `el-input`（maxlength=128，空/129 字时确认按钮禁用+tooltip）；数量非遥感可编辑、**遥感行 `disabled` 恒 1**（DOM `disabled=true`）、数量列 `justify-content:center` 居中 |
| E17 | 只提交有变更项 | ✅ | XHR 抓包（项目 52，改合同 80 客户+总价、行 96 数量）：`{"action":"confirm","items":[{"itemId":96,"qty":15,"serviceStart":null,"serviceEnd":null}],"contracts":[{"contractId":80,"amount":5000,"customer":"QA-P2客户A改"}]}`——`contracts[]` 仅含改了的合同 80（未动的 81 不在）、`items[]` 仅含改了的行 96（未动的 95 不在）；落库核对：合同 80 amount=5000/客户已改、行 96 amount=1500（1000×15/10 比例缩放）、行 95 未变 |
| E18 | 配色/组件一致 | ✅ | 确认按钮主蓝 `rgb(23,105,212)`=#1769D4、7px 圆角；review.vue 无 EP 默认色板（grep 0 命中），唯一字面量 `#f8fafc` 为既有 token（表头/脚条底色）；复用 `.info-bar`/`.rv-*` 骨架，无新造色值 |

### 备注（非缺陷观察）

1. 前端 payload 对**有变更的行**恒带 `serviceStart/serviceEnd`（`base.serviceStart = l.serviceStart || null`，review.vue:296-297）——属 ADR-020/BUG-23「显式 null=清空」既有口径，原值为空时语义等价 no-op，非 ADR-050 引入。
2. 流水 `ref` 口径：`project_lock` 用项目 code（SP-…）、`cancel_release` 用合同 code（HT-…），与既有 ADR-012 口径一致，核对时按各自口径匹配。
3. 环境：`npx vue-tsc` 需绕开 IDE 注入的 `LD_LIBRARY_PATH`/`NODE_OPTIONS`（GLIBCXX 冲突），`env -u LD_LIBRARY_PATH -u NODE_OPTIONS /usr/bin/node node_modules/vue-tsc/bin/vue-tsc.js -p tsconfig.app.json --noEmit` → 退出码 0。

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
## 2026-11-04 ｜ ADR-053 产品域三处改动回归明细（A/B/C/D 全量，无新缺陷）

> 事实来源：`docs/adr/ADR-053.md` + `docs/backend/api.md` 产品接口（POST/PUT /assets、bootstrap `assets[]`）。验收基准 = 用户拍板三条口径（① 税点展示+录入（整数 %，可空 → `-`）；② 去「售卖数量」列（保留「重复售卖」tag）；③ 销售单价改采购单价对外不展示 + 展示区间下限 + 填采购价自动 ×1.01/×1.02 区间）。

**测试数据（保留供验收）**：admin 建 2 个产品——`QA053-税点13%`（id 54，taxPoint=13，salePrice=100，区间 101~102）、`QA053-自动区间200`（id 55，采购价 200，手改下限 202 + 自动上限 204，长期有效）；产生项目 80（`SP-2026110408371149` QA053-D3-正常下单，pending，金额 121，锁定 id=53 ×1）。id=53 回归后已恢复原值（salePrice=120、区间 121~122、taxPoint=6）。

### A. 税点（curl，真实 :8000 + 浏览器）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | admin `POST /assets` 带 `taxPoint:13` → 200 落库；列表税点列 `13%`；详情页 `13%` | ✅ | id=54；列表 cell `13%`（/tmp/qa053-list-taxpoint13.png）、详情 `税点 13%`（/tmp/qa053-detail-54.png） |
| A.2 | `PUT /assets/54` 只改 `remark` → taxPoint 保持 13（exclude_unset）；`PUT {"taxPoint":null}` → 清空 | ✅ | bootstrap 核对：改备注后 `taxPoint=13`；传 null 后 `taxPoint=None` |
| A.3 | 存量产品（id=52，无 taxPoint）列表/详情税点 `-`、销售单价 `-`，全页无 `undefined%` | ✅ | bootstrap 全部 47 产品均含 `taxPoint` 字段（存量=null）；列表/详情 cell `-`；snapshot grep `undefined%` = 0 |
| A.4 | `taxPoint:101` / `taxPoint:-1` → 422 | ✅ | 两次 `POST /assets` 均 HTTP 422（`ge=0, le=100`） |
| A.5 | fin01（财务）登录：产品列表可见税点列（只读）、值正确、可浏览；写操作 403 | ✅ | fin01 视角列表表头含「税点」、id=53 显示 `6%`（/tmp/qa053-list-fin01.png）；`POST /assets` → 403 `只读账号不可执行该操作` |
| A.6 | 编辑日志中文映射 | ✅ | id=53 操作记录显示 `税点: 13 → None`（非金额字段不带「元」） |

### B. 去「售卖数量」列（浏览器，4 板块表头逐项核对）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | software/satellite/embodied/hardware 列表表头均无「售卖数量」列 | ✅ | 四板块表头 = 选择/产品名称/类型/所在主体/产品总数/锁定数量/销售单价/税点/可用数量/状态/操作 |
| B.2 | 「重复售卖」tag 仍在（可用数量列内） | ✅ | 多行 `重复售卖` tag 可见（ADR050-T1 等） |
| B.3 | 快览抽屉「已交付/锁定/可售」进度仍正常 | ✅ | id=53 抽屉：`已交付 0 / 锁定 0 / 可售 10 / 总数量 10 套`（/tmp/qa053-drawer.png） |

### C. 销售单价→采购单价 + 自动区间（浏览器 + curl）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| C.1 | 列表「销售单价」列显示 priceMin + 区间追加；遥感容器/无区间显示 `-` | ✅ | id=53 `¥121.00（参考区间 121~122）`、id=54 `¥101.00（参考区间 101~102）`；id=52（无区间）`-`；遥感数据-2026（容器）`-` |
| C.2 | 详情页「销售单价」显示 priceMin（非采购价 120）；快览抽屉同 | ✅ | 详情 `¥121.00（参考区间 121~122）`（/tmp/qa053-detail-53.png）；抽屉 `¥121.00（参考区间 121~122）` |
| C.3 | 登记表单 label「采购单价（元）」+「税点（%）」输入 | ✅ | 新建/编辑表单均实测（卡片 hint 亦为「…与采购单价（元）」） |
| C.4 | 新建填采购价 100 → 区间自动 101~102（×1.01/×1.02） | ✅ | 输入 100 后下限/上限即时变 101/102 |
| C.5 | 手改下限 500 后再改采购价 → 下限保持 500、上限按 ×1.02 重算 | ✅ | 采购价 200 → 下限 500 不动、上限 204（=200×1.02） |
| C.6 | 编辑 id=53 初始加载不重算（保持 121~122，非 121.2/122.4）；改采购价 130 → 重算 131.3/132.6；手改下限 140 后再改采购价 150 → 下限保持 140、上限 153 | ✅ | 三步浏览器实测（显示 131.3/132.6 干净两位小数；spinbutton aria 的 float32 噪声 131.300003… 为 el-input-number 内部表示，展示层无影响） |
| C.7 | 遥感容器：编辑页无价格卡（无采购价/区间输入）→ 不自动生成区间；列表销售单价 `-` | ✅ | id=29 编辑页仅基本信息+有效期卡；卫星列表该行销售单价 `-` |
| C.8 | 采购价落库：保存后 bootstrap `salePrice` = 所填采购价（字段名未变） | ✅ | id=55：`salePrice=200.0, priceMin=202.0, priceMax=204.0` |

### D. 护栏回归

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| D.1 | ADR-052 双向区间仍生效：unit 产品金额低于下限/高于上限 → 400 | ✅ | id=53（区间 121~122）加购 amount=120 → 400 `销售金额超出该产品参考区间（121.00~122.00 元/套）`；amount=123 → 400 同文案 |
| D.2 | 可售金额统计切 priceMin：看板「当前可售」= Σ(可用数量×priceMin) | ✅ | 按 bootstrap 独立重算 vs 看板显示：embodied ¥82,522,555.00、satellite ¥36,996,836.31、software ¥7,016,201.00 逐分一致（口径含 repeatSale→0、amount 模式→0、容器→availableCount） |
| D.3 | 正常下单链路：加购 + 结算 → 生成销售项目金额正确 | ✅ | amount=121（区间内）加购 → checkout 200，项目 80 `expectedAmount=121.0`、item `price=121.0/amount=121.0/origPrice=120.0`（原价=采购价快照） |
| D.4 | 5 板块一致：embodied/satellite/software/hardware 三处改动一致；compute 不受影响 | ✅ | 四板块表头一致（无售卖数量、有税点、销售单价=priceMin）；compute 表头原样（产品编号/产品名称/服务到期/台数/累计已售服务/状态/备注，无单价/售卖列） |
| D.5 | 详情页其它 tab（交付物/销售关联/数量流水/操作记录）无回归 | ✅ | id=53 四个 tab 逐一打开渲染正常（数量流水 1 条登记、操作记录 4 条含税点变更留痕） |
| D.6 | stale 文案已修：参考区间提示为双向口径 | ✅ | 表单提示实测 `元/{unit}，选填（可只填一边）；下单时校验销售金额须在参考区间内（不得低于下限、不得高于上限），未设置则不限制`（无「上限不限制」旧文案） |
| D.7 | `vue-tsc -p tsconfig.app.json --noEmit` EXIT=0 | ✅ | 前台复跑 `EXIT=0`，无输出 |

### 备注（非缺陷观察）

1. `el-input-number` 的 spinbutton aria 值出现 float32 噪声（如 `131.3000030517578`），展示文本与落库值均为干净值（`131.3` / 6 位小数内），属组件内部表示，不影响用户与数据，不计缺陷。
2. 区间 400 文案为 `销售金额超出该产品参考区间（…）`（ADR-052 收口后口径），本次未改动、行为一致。

## 2026-11-04 ｜ ADR-055 销售项目列表服务端分页回归明细（A~F 全量，无新缺陷）

> 事实来源：`docs/adr/ADR-055.md` + `docs/backend/api.md`「GET /api/projects」小节。验收基准 = 用户 2 条需求（① /sales/projects 后端分页；② 分页/过滤后结果集与改前一致、可见性正确、bootstrap 13 消费点零回归）。

**测试数据（保留供验收）**：QA051-/QA052- 前缀存量测试项目；本轮写操作：`QA051-E5-超可售`（id 74，terminated）按 E1 用例删除；`QA052-eco01下单`（id 78）按 E2 用例改派 biz02→biz01。admin 可见项目总数 75→74。

### A. 分页（admin，/sales/projects）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | 进页第一页 20 条 + 分页器（共 75 条 / 4 页 / 20条每页） | ✅ | 表格 20 行（id 79~60）；截图 /tmp/qa055/a1_page1.png |
| A.2 | 翻页数据切换、无重复 id | ✅ | UI 第 2 页首行 SP-2026110404553592 ≠ 第 1 页任一行；curl 第 1 页 ids 79~60、第 2 页 59~40，两页交集为空 |
| A.3 | 切 10/50 条每页行数正确且回第 1 页 | ✅ | UI 切 10 → 10 行且第 1 页高亮；切 50 → 50 行；curl pageSize=10/50/100 → items 10/50/75 |
| A.4 | 超尾页 items 空且 total 不变 | ✅ | curl `page=99&pageSize=20` → `{"total":75,"items":[]}` |
| A.5 | 卡头「共 N 条」= 后端 total（admin 可见总数） | ✅ | UI 卡头与分页器均「共 75 条」= `GET /projects` total=75 = bootstrap projects 长度 75 |

### B. 过滤 + 分页联动

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | keyword 搜 name/code/customer → 结果正确 + 卡头 total 更新为过滤后数 + 自动回第 1 页 | ✅ | UI 搜 `QA0` → 「共 43 条」（卡头+分页器）、43 行、第 1 页；curl `keyword=QA0` total=43 |
| B.2 | 大小写敏感（对齐原 JS includes / 后端 instr）：`QA0` 有结果、`qa0` 无 | ✅ | UI `qa0` → 「共 0 条」空态（截图 /tmp/qa055/b2_qa0_empty.png）；curl `keyword=qa0` total=0 |
| B.3 | status / rep / businessOwner（含 `__none__`）单过滤 + 组合过滤 count 正确 | ✅ | UI 组合（待审核×未指派）→ 「共 2 条」2 行 = curl `status=pending&businessOwner=__none__` total=2；curl 单过滤：pending=17、`__none__`=8、rep=admin=1、businessOwner=admin=9，均与 bootstrap 本地同条件 filter 一致 |
| B.4 | 清空回全量 | ✅ | UI 清空搜索框/两个下拉 → 「共 75 条」 |

### C. 可见性（跨角色）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| C.1 | eco01(viewer)：total = 只自己 creator 的单（= bootstrap projects 长度） | ✅ | curl total=20 = bootstrap 20；`items` 全部 `creator==eco01`；UI「共 20 条」20 行（截图 /tmp/qa055/c1_eco01_list.png） |
| C.2 | biz01(editor)：total = 只自己 businessOwner 的单 | ✅ | curl total=13 全部 `businessOwner==biz01`（改派测试后 14，UI「共 14 条」一致，截图 /tmp/qa055/c2_biz01_list.png） |
| C.3 | admin / sup01：total = 全部可见 | ✅ | 两者 curl total 均 75 |
| C.4 | fin01(finance)：直访 /sales/projects 被守卫拦；接口 total=0 | ✅ | UI 提示「财务账号仅可浏览「产品及服务」」+ URL 重定向 /assets/embodied（截图 /tmp/qa055/c4_fin01_guard.png）；curl `GET /projects` total=0 |

### D. 对齐校验（服务端过滤 vs 改前前端本地过滤）

比对方法：对每角色取 `GET /projects?pageSize=100`（带同条件 query）的 `items[].code` 有序列表，与该角色 `GET /bootstrap` 的 `projects[]` 用**原前端 `list` computed 同语义**（`${name}${code}${customer}` 大小写敏感 includes / status 等值 / rep 等值 / owner `__none__`→空）本地 filter 后的 code 有序列表比对——集合相等、数量相等、total 口径（=本地 filter 长度）、顺序（id.desc）四项断言，脚本 /tmp/qa055/align.py。

| 角色 | 条件 | api total/items | bootstrap 本地 filter | 集合/数量/total/顺序 |
|---|---|---|---|---|
| admin | 无过滤 | 75/75 | 75 | ✅ 全等 |
| admin | keyword=QA0 | 43/43 | 43 | ✅ 全等 |
| admin | keyword=qa0 | 0/0 | 0 | ✅ 全等 |
| admin | businessOwner=__none__ | 8/8 | 8 | ✅ 全等 |
| admin | status=pending | 17/17 | 17 | ✅ 全等 |
| admin | pending+__none__ | 2/2 | 2 | ✅ 全等 |
| admin | rep=admin | 1/1 | 1 | ✅ 全等 |
| admin | businessOwner=admin | 9/9 | 9 | ✅ 全等 |
| eco01 | 无过滤 / QA0 / qa0 / __none__ / pending / 组合 | 20/16/0/6/5/1 | 同左 | ✅ 全等（6 组） |
| biz01 | 无过滤 / QA0 / qa0 / __none__ / pending / 组合 | 13/10/0/0/4/0 | 同左 | ✅ 全等（6 组） |

- total 口径：`pageSize=5&keyword=QA0` → total=43（过滤后全量，非切片后）、items=5 ✅
- 结论：20 组比对全部「集合相等=True 数量相等=True total口径=True 顺序一致=True」，**服务端分页/过滤与改前前端可见集合逐条一致**。

### E. 写操作后重载（不留 F5）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| E.1 | UI 删除项目 → 列表自动刷新（行消失、total -1） | ✅ | admin 列表「更多→删除项目」删 QA051-E5-超可售（id 74）→ 确认删除后该行 0 匹配、卡头 75→74，未 F5（截图 /tmp/qa055/e1_after_delete.png） |
| E.2 | 改派（留列表页写操作）→ 列表自动重载 + 下拉选项刷新 | ✅ | UI 改派 QA052-eco01下单 biz02→biz01 → 确认改派后行内负责人即时变「商务01」，与 curl `id=78 businessOwner=biz01` 一致（截图 /tmp/qa055/e2_after_claim.png）；改派后 owner 过滤下拉仍为全量名册、rep 下拉 12 项 |
| E.3 | 跳离列表（进详情）返回后数据正常（onMounted 重拉） | ✅ | 快览抽屉→查看详情（/sales/projects/77/detail 正常）→ 返回列表「共 74 条」20 行正常 |

### F. 护栏回归（bootstrap 13 消费点零影响）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| F.1 | 项目详情/编辑/审核页正常（db.projects.find(id) 不受影响） | ✅ | /77/detail 标题+数据正常；/77/edit「编辑销售项目」表单加载正常；/79/review「订单审核」正常（未分配单显示「该订单尚未分配商务负责人…」提示） |
| F.2 | 交付记录（outbound）项目下拉正常（仍读 db.projects 全量） | ✅ | 补录弹窗「关联项目」下拉 42 项 = bootstrap 74 项排除 terminated/pending 的精确口径（`activeProjects` computed 未改） |
| F.3 | 资产详情「销售关联」tab、看板统计正常 | ✅ | /assets/48/detail「销售关联（4）」列出 4 个关联项目（截图 /tmp/qa055/f3_asset_sales_tab.png）；/dashboard 三板块统计卡渲染正常（截图 /tmp/qa055/f3_dashboard.png） |
| F.4 | rep/owner 下拉选项完整（不随当前页缩减，仍取 db.projects/全量名册） | ✅ | 生态人员下拉 12 项 = admin bootstrap 全部可见 rep 值（admin/chaiyan/cliping/cyashi/eco01/hjialing/luojie/qa/xdiying/yqingqing/zjingren/自测）；商务负责人下拉 = 未指派 + 全量名册（含 biz01/biz02 等） |
| F.5 | `vue-tsc -p tsconfig.app.json --noEmit` EXIT=0 | ✅ | 前台复跑 `EXIT=0`，无输出 |
| F.6 | 参数边界与鉴权 | ✅ | `page=0`/`pageSize=0`/`pageSize=101`/`page=abc` → 422；无 token → 401 |

### 备注（非缺陷观察）

1. 本轮 E 组写操作改变了 2 条测试数据（id 74 删除、id 78 改派 biz02→biz01），属 QA 前缀测试数据，已在上表留痕；如需还原可由 admin 重新建单/改派回 biz02。
2. `GET /projects` 的 `items[]` 结构与 bootstrap `projects[]` 同构（ProjectOut），列表页表格渲染零适配差异。

## 2026-11-04 ｜ ADR-056 列表排序 / 详情页勾选驳回 / 产品统计页回归明细（A/B/C/D 全量，无阻断缺陷）

> 事实来源：`docs/adr/ADR-056.md` + `docs/backend/api.md`（GET /projects sortBy 小节 + POST /projects/{id}/reject-contracts 小节）。验收基准 = 用户 3 条需求（① 列表状态/金额/日期/编号可排序；② 详情页勾选订单驳回，部分驳回后可续审；③ 按主体呈现资产数量的产品统计页、viewer 不可见、可对比 Excel）。

**测试数据（保留供验收，QA056- 前缀）**：项目 86 `QA056-QA部分驳回`（合同 124/125 已驳回、126 已确认→项目 active）、87 `QA056-QA全部驳回`（合同 127/128 已驳回→项目 terminated）、88 `QA056-QA-UI驳回`（合同 129/130 UI 批量驳回、131 UI 单一驳回→项目 terminated）、89 `QA056-QA-审核回归-确认`（合同 132 已交付 delivered）、90 `QA056-QA-审核回归-整单驳回`（合同 133 整单驳回 terminated）；产品 50/51/52/29 锁定/交付数量已随上述流转变化（均为 QA 产品）。既有 QA056 数据（项目 80-85、合同 112-123）未动。

### A. 列表排序（admin，/sales/projects）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| A.1 | 状态排序按档位：asc 全序列 rank 非降（pending×19→active×41→delivering×2→terminated×18）、desc 反之；terminated 档内 id.desc；三终止子型（已撤销/已驳回/已终止）同聚 terminated 档 | ✅ | curl `sortBy=status` asc/desc pageSize=100 脚本断言（rank 映射+档内 id.desc 全 True）；UI 点表头 desc 首屏混排「已驳回/已终止」tag 同档 |
| A.2 | 金额/最近跟进/预计签约/编号 asc·desc 全对；非法 sortBy 按无排序（id.desc） | ✅ | curl 5 键×2 向逐位比对（amount min 500/max 32,720,000；date 空值 asc 最前；`sortBy=bogus` → ids 85..81） |
| A.3 | **翻页稳定**：5 键×2 向共 10 组合，`page=1+page=2`（pageSize=10）id 序列 == `pageSize=100` 全量前 20，无重复、无遗漏、total 恒 80 | ✅ | 脚本 10/10 输出 `dup=False missing=[] p1p2==full[:20]=True total 80/80` |
| A.4 | 第 2 页点排序回第 1 页；表头点击循环 asc→desc→取消（第三次回 id.desc 最新在前） | ✅ | 浏览器：page2 点「项目状态」→回第 1 页；XHR 抓包三连击 `sortBy=status&sortOrder=asc` → `desc` → 无 sortBy 参数（首行 id 85）；截图 /tmp/qa056_A_status_asc.png |
| A.5 | 排序+过滤组合：`status=pending&sortBy=amount` 仅 19 条 pending 且金额升序 | ✅ | curl 断言 all pending + amount asc True |

注：直接点表头**排序小箭头**（caret）会直达对应方向（Element Plus 原生行为：点升箭头=asc、点降箭头=desc），点表头文字才是 asc→desc→null 循环；两者均正确，非缺陷。

### B. 详情页勾选驳回（admin）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| B.1 | **部分驳回**：项目 86（3 pending 合同）勾 2 个批量驳回 → 124/125 `terminated`+remark「合同A｜驳回：…」（原备注保留）、**项目仍 pending**、126 仍 pending；再对 126 `review confirm` → 200，合同 126 active、**项目 active**（可续审闭环） | ✅ | curl 返回 `project status: pending`（items 139/140 released、141/142 locked）；bootstrap 复核 3 合同状态；confirm 后 project 86 active；UI 路径同断言（项目 88：批量驳回 2 条后页面「批量驳回（0）」禁用、剩 1 行待审核，截图 /tmp/qa056_B1_partial_after.png） |
| B.2 | 单一驳回：行内「驳回」1 条 → 该合同 terminated+remark、项目随之派生 | ✅ | UI 项目 88 合同 131 行内驳回 → POST 200；bootstrap：131 terminated「UI合同3｜驳回：QA056-QA 单一驳回：客户取消」、项目 88 terminated（全驳回） |
| B.3 | 全部驳回 → 项目 terminated | ✅ | curl 项目 87 两合同全驳 → 返回 `project status: terminated`；bootstrap 127/128 terminated |
| B.4 | 原因必填：空/纯空格 → 弹窗内拦截不发请求 | ✅ | 浏览器：空原因点「确认驳回」→ `No requests captured`、弹窗不关；纯空格同 |
| B.5 | 非 pending 项目无勾选列/无「批量驳回」；已确认合同「交付/终止/录入签订时间」保留 | ✅ | 项目 80（active）详情页无 selection 列、无批量驳回按钮，4 行均「交付 终止 录入签订时间」；项目 88（terminated）头部 tag「已驳回」、无勾选；截图 /tmp/qa056_B5_terminated_detail.png |
| B.6 | 守卫 11 项 | ✅ | viewer/finance → 403「只读账号不可执行该操作」；未分配项目 82 → 400「该订单尚未分配…」；非负责人 biz01 → 403「仅接手的商务负责人（admin）…」；非本项目合同 112@86 → 400「销售记录 112 不属于该项目」；已驳回合同再驳 → 400「…非待审核状态，不可驳回」；reason 缺/空串 → 422、纯空格 → 400「驳回原因不能为空」；contractIds 空 → 422；非 pending 项目 80 → 400「仅待审核项目可驳回订单」；99999 → 404 |
| B.7 | **下游数量**：驳回释放锁定（asset 52 locked 2→0、50 3→0；未驳合同的 51/29 锁定不动）；遥感合同驳回 → rsItem 9 回 `in_stock`；shippedQty/soldAmount 全程 0 不变 | ✅ | bootstrap 驳回前后字段级对比（基线 52:2/50:3/51:1/29:8 → 部分驳回后 52:0/50:0/51:1/29:8；项目 87 全驳后 52:0、29:8、rsItem9 in_stock） |
| B.8 | 回归：审核页整单确认/整单驳回不变；交付链路不回归 | ✅ | 项目 89 review confirm → active（锁定保留）；项目 90 review reject → terminated+remark「驳回：…」；合同 132 录签订时间（active→delivering）→ 交付（delivered，asset 50 locked 1→0 shipped 0→1，项目 delivered）；审核页 UI 渲染正常（截图 /tmp/qa056_B8_review_page.png） |

### C. 产品统计页（/statistics）

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| C.1 | 可见性：eco01(viewer) 菜单无「产品统计」+ 直访 /statistics 静默回 /assets/embodied；fin01(finance) 菜单有+页面可打开（7 主体 48 产品）+ /assets「登记产品」仍禁用（只读不回归）；admin/sup01/biz01 菜单可见 | ✅ | 五角色浏览器实测；截图 /tmp/qa056_C1_viewer_blocked.png、/tmp/qa056_C1_finance_stats.png；守卫代码 `financeAllowedPath` 含 `/statistics`、viewer 白名单不含 |
| C.2 | **聚合正确**：7 个主体 × 5 指标与手工对 db.assets 按 subject 求和**逐值全等**（如 安徽天枢智算 13/252/216/¥70,375,487.00/¥176,008,155.00；四川蜂云星座 8/588,657,247/588,657,242/¥110,285,731.55/¥110,472,881.55；测试主体 14/2620/2265/¥437,250.00/¥620,200.00）；当前无空 subject 资产，「(未设主体)」分组逻辑在代码中（置末位、不隐藏） | ✅ | 页面快照 vs Python 手工求和脚本（repeatSale→0、遥感容器 availableCount、其余 quantity-lockedQty-shippedQty）7/7 主体全等；概览条「共 7 个主体 · 48 个产品」与全量一致 |
| C.3 | 展开明细列口径：QA052-Unit-无区间（id 52）行 = 数量 100/剩余量 100/剩余金额 ¥10,000.00/采购单价 ¥100.00/采购总价 ¥10,000.00/可售，与 bootstrap 逐值一致；all_sold 产品显示「已售罄」 | ✅ | 展开「测试主体」明细核对；截图 /tmp/qa056_C3_expand.png |
| C.4 | 口径：剩余金额=剩余量×采购单价（采购口径）、金额千分位格式、空值兜底（repeatSale 剩余量 0、salePrice 空 `-`） | ✅ | 代码走查（statistics/index.vue：`availQty×salePrice`、`quantity×salePrice`、`?? 0` 兜底）+ 页面数值与 C.2 手工求和一致 |

### D. 护栏

| # | 断言 | 结果 | 证据 |
|---|---|---|---|
| D.1 | ADR-055 分页/过滤不回归 | ✅ | keyword=QA056 11 条全命中、rep=QA056 11 条、businessOwner=admin 19 条、`__none__` 8 条、status=terminated 21 条，各过滤字段 100% 匹配；翻页见 A.3 |
| D.2 | 详情/创建/审核/交付各页正常；合同展开行原卡片信息完整 | ✅ | 详情页（88/80）、创建页（biz01 渲染「新建销售项目」）、审核页（78）均正常；展开行含明细表（明细/数量/单价/服务期限/交付要求）+ 合同签订/预计交付/备注，原卡片信息无丢失（截图 /tmp/qa056_B_expand_row.png） |
| D.3 | 五角色可见性 + 路由守卫无冲突 | ✅ | 见 C.1；viewer 菜单（产品及服务/销售项目/购物车）与 finance（产品及服务/产品统计）均无「产品统计」越权/缺失 |
| D.4 | vue-tsc EXIT=0 | ✅ | `LD_LIBRARY_PATH=… npx vue-tsc -p tsconfig.app.json --noEmit` → EXIT=0 |

### 备注（非缺陷观察）

1. **OBS-ADR056-01**：详情页合同行「状态」tag 对已驳回合同显示「已终止」（`tagInfo(PROJECT_STATUS, row.status)` 原始 status 映射），非「已驳回」细分——与 ADR-056 前旧卡片展示口径完全一致（旧代码同用 `tagInfo(PROJECT_STATUS, c.status).label`），非本批引入；「已驳回」细分按 ADR-041 口径体现在**项目级**（列表状态列/抽屉/详情页头部 tag，实测项目 88 头部显示「已驳回」），合同级驳回原因在展开行 remark「…｜驳回：…」可见。若产品要求合同行也细分「已驳回」，建议后续 ADR 显式扩展 `projectOutcome` 到合同级。
2. 本轮 B 组写操作产生 QA056- 前缀测试数据（项目 86-90、合同 124-133）并流转了 QA 产品 50/51/52/29 的锁定/交付数量，均保留供验收；如需还原可由 admin 终止/撤销对应测试单。
