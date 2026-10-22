# 缺陷跟踪（QA）

> 编号规则：`BUG-<批次>-<序号>`；严重程度：致命 / 高 / 中 / 低；状态流转：新建 → 修复中 → 已修复 → 已验证 → 关闭。

| 编号 | 日期 | 描述 | 严重程度 | 状态 | 指派 | 关联任务 | 备注 |
|---|---|---|---|---|---|---|---|
| BUG-ADR028-000 | 2026-10-21 | 本批次 13 条用例全部通过，无缺陷 | - | 关闭 | - | TASK-QA-034 / ADR-028 | 覆盖 A1–A5（权限）、B6–B9（撤销+留痕+删除护栏+重新提交幂等）、C10–C13（前端入口与文案）；后端接口在数据库副本验证，前端在真实 dev 栈 + 临时隔离栈浏览器实测验，证据见 `docs/qa/changelog.md` 同日明细 |
| BUG-FORMS20261022-000 | 2026-10-22 | FORMS-20261022 批次（ADR-036 产品登记规则 + ADR-037 生态人员购物车口径）独立回归复核：7 个重点回归面 44 项进程内断言 + 前端静态走查全部通过，无新缺陷 | - | 关闭 | - | FORMS-20261022 / ADR-036 + ADR-037 | 覆盖：viewer 区间分角色（改价/结算双向 + 遥感明细行）、viewer 历史 discountRate 忽略（金额权威不受折扣影响）、容器 repeatSale（新建 400 / 存量#29 编辑 false 不卡死 / type 变更路径）、inboundDate 自动生成（新建当天/空串当天/编辑原值保留两类型）、登记页表单重构静态走查（三形态字段 + 必填 rules + touchedMin/Max 逻辑）、购物车 viewer 折扣渲染条件 + editor/admin 路径零变化 + requestId 幂等未破坏、菜单「公司主体」改名一致 + 用户可见文案 0 残留；数据库副本 + TestClient 进程内断言，证据见 `docs/qa/changelog.md` 同日明细 |
| BUG-LAN-20261022-001 | 2026-10-22 | 局域网 IP 访问时购物车下单 `TypeError: crypto.randomUUID is not a function`：`crypto.randomUUID()` 为 secure-context-only API，`0.0.0.0:5173` 下经 `http://192.168.x.x:5173` 访问时该 API 不存在，`views/cart/index.vue` 结算时直接调用即抛错，下单 100% 失败（localhost / 127.0.0.1 不复现）。修复：`api/index.ts` 新增导出 `genRequestId()`（randomUUID → getRandomValues 手工构造 v4 → Math.random 三级降级），购物车调用点改用之；未改后端（`requestId` 仅 `len ≤ 64` 校验）与幂等语义 | 致命 | 已修复 | 前端 | BUG-LAN-20261022 / ADR-033 | 实测：临时 Node 脚本（算法从 `api/index.ts` 原样复制 + 分支命中计数探针）在四场景各生成 1000 个 id —— 场景 0 randomUUID 可用 / A 非安全上下文仅 getRandomValues / B 无 crypto 走 Math.random / C randomUUID 抛错降级 —— 全部匹配合法 UUIDv4 正则、长度 36、1000 内零重复、`len ≤ 64`，分支命中计数与预期逐项一致（1000/1000），退出码 0；`npx vue-tsc --noEmit` 退出码 0；`grep -rn randomUUID frontend/src` 已无直接调用点（仅 `genRequestId` 内部 1 处 + JSDoc/注释 3 处）；5173 dev server 未重启（HMR 已热更，`curl /` 返回 200）。未 build、未 commit |
| BUG-FIX20261022-000 | 2026-10-22 | FIX-20261022 全量修复批次独立回归复核：8 个重点回归面 88 项断言全部通过，无新缺陷 | - | 关闭 | - | FIX-20261022 / ADR-029~034 | 状态机（含项目级「全量或全不」与合同级既有路径）、终止回滚（含 BUG-04 原始场景与产品已删 400 分支）、checkout 幂等（含失败不消费 requestId）、可见性（files/logs/flows 三角色 + 文件 ACL 404）、权限与登录（403/429/tokenVersion 吊销/生产 fail-fast）、迁移幂等（二次 import 零变化）、前端静态走查（catch 补全/BUG-06 三处拦截/qtyBusy/refreshSeq/randomUUID）、契约一致性（410×2/review 显式 null/idempotent 字段名/400 文案）；数据库副本 + TestClient 进程内断言，证据见 `docs/qa/changelog.md` 同日明细 |

## 观察项（不计缺陷，供 Architect 排期参考）

| 编号 | 日期 | 描述 | 建议 | 关联任务 |
|---|---|---|---|---|
| OBS-QA-034-01 | 2026-10-21 | 仓库无自动化测试套件（无 `tests/`、无 pytest / vitest / playwright 配置），本次验收依赖临时脚本与人工浏览器实测，回归成本高且难复用 | 补后端 ADR-028 基线用例（viewer `PUT` 403、`DELETE` 留痕 403、`withdraw` 全链路），前端补列表/详情入口显隐的组件级用例 | TASK-QA-034 |
| OBS-QA-034-02 | 2026-10-21 | `review`（确认/驳回）要求订单已接手，admin 亦需先 `claim`；易被误判为回归 | 若业务希望 admin 直接审核，可在后续 ADR 中显式调整守卫；当前按既有口径（ADR-012 §5.1）记录不改 | ADR-012 §5.1 |
| OBS-FIX20261022-01（**已关闭 2026-10-22**） | 2026-10-22 | 5 条存量流水（`flows` id 78/136/160/164/212）`contractId` 指向现存合同但 `ref` 为已不存在的旧编号（`HT-0007`、`HT-2026101921532060` 等）——合同编号被历史清理脚本改过、流水 `ref` 未同步。可见性判定按 `contractId` 权威外键放行，无越权泄漏，仅展示层编号对不上 | 已由 `backend/scripts/backfill_flow_refs.py` 关闭：**同因存量实为 64 行**（QA 标记的 5 行属其中），已按 `contractId` 全量回填，复跑幂等 0 行，备份 `/tmp/flows-backup-1792638499.db` | FIX-20261022-OBS01 / ADR-031 |
| OBS-FIX20261022-02（**已关闭 2026-10-22**） | 2026-10-22 | ADR-034 §1 文档与实现口径漂移：ADR 正文写 dev「进程内随机密钥（重启即失效）」，实际按 FIX-20261022-FOLLOWUP 实现为持久化开发密钥文件 `backend/.jwt_secret`（0600，重启不换密钥） | 已关闭：ADR-034 Decision 1 已同步为持久化口径（含实施修正注记），实现未动 | FIX-20261022-FOLLOWUP / ADR-034 §1 |
| OBS-FORMS20261022-01 | 2026-10-22 | ADR-036 §3 区间自动同步「跟随」语义与实现略有出入：ADR 正文括注「重新填单价且区间仍为『上次自动值』时继续跟随」，实现采用 `touchedMin/touchedMax` 布尔标记（手改一次即永久停止跟随该边界，即使后续值恰好回到上次自动值也不再跟随）。极窄边界（手改区间后再改单价的叠加场景），changelog 已按标记口径记录「手改后不再自动覆盖」，功能无异常 | 建议下轮文档维护时统一 ADR §3 括注与实现口径（二选一：改 ADR 括注为「手改后不再跟随」，或实现改为按值比较恢复跟随） | FORMS-20261022 / ADR-036 §3 |
| OBS-FIX20261022-03（**已关闭 2026-10-22**） | 2026-10-22 | `api-contracts.md`「FIX-20261022 批次 §4」表格中「项目级批量交付」的 detail 为摘要口径（`合同 {code} 尚未录入签订时间，不可交付（可多条）`），实际文案为 `以下销售记录不满足交付条件，请先补齐后重试：{code} 尚未录入签订时间，不可交付` | 已关闭：契约表格该格已改为「以『以下销售记录不满足交付条件：』开头的全量清单（QA 实测文案为准）」 | FIX-20261022 / api-contracts §4 |
