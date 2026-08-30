# 论文“整理入库”子会话 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task；每项按 TDD 红—绿—重构执行。

**Goal:** 从文献页创建或恢复论文专属 DSH 子会话，在用户明确确认后把全部关键结论写入 SQLite，并派生到 Excel“整理结论”表。

**Architecture:** TypeScript 宿主层通过 DSH `agents`/`subagents` 创建 continuable fork；Python 引擎负责 schema v3、绑定、结论和 XLSX。客户端只传当前父会话与论文，确认工具从 `ToolRunContext.agent.id` 获取真实子会话身份，杜绝模型伪造会话 ID。

**Tech Stack:** DSH `0.1.0-rc.7`、TypeScript、Cordis、Python 3.11、SQLite、openpyxl、Node 合同测试、pytest。

---

### Task 1: SQLite v3 与可恢复迁移

**Files:**
- Modify: `engine/src/scientific_reading/library_schema.py`
- Modify: `engine/tests/test_library_schema.py`

- [ ] 写失败测试：新库包含 `review_sessions`、`review_conclusions`、唯一键/外键；v2 升 v3 前生成可验证备份；迁移后原条目和用户字段不变。
- [ ] 运行 `python -m pytest engine\tests\test_library_schema.py -q` 确认因 v3 表缺失失败。
- [ ] 将 `TARGET_VERSION` 升至 3，新增 `_create_v3_tables()`、必需列/主键/唯一键/外键校验和 v2→v3 迁移；沿用现有锁、backup、restore 机制。
- [ ] 运行 schema 测试和 `PRAGMA foreign_key_check` 场景。
- [ ] 中文提交：`数据：加入整理会话与确认结论表`。

### Task 2: 整理会话与结论服务

**Files:**
- Create: `engine/src/scientific_reading/review_service.py`
- Create: `engine/tests/test_review_service.py`
- Modify: `engine/src/scientific_reading/__main__.py`
- Modify: `src/cli.ts`

- [ ] 写失败测试：
  - `(parent_session_id, paper_id)` 幂等绑定同一 `review_session_id`；
  - 同论文不同父会话可分别绑定；
  - 一个子会话不能绑定两处；
  - 未知论文拒绝；
  - 按 `review_session_id` 读取上下文；
  - 一次确认的多条结论在单事务中全部写入，空文本拒绝。
- [ ] 运行 `python -m pytest engine\tests\test_review_service.py -q` 确认模块不存在。
- [ ] 实现 `get_binding()`、`bind_session()`、`context_for_session()`、`confirm_conclusions()`；ID 用 `review_` 加随机十六进制，时间为 UTC ISO 8601。
- [ ] 增加 JSON stdin CLI：`review-session-get`、`review-session-bind`、`review-context`、`review-confirm`，并在 `src/cli.ts` 增加薄适配。
- [ ] 运行服务测试、CLI 测试和 typecheck。
- [ ] 中文提交：`功能：实现整理会话与结论服务`。

### Task 3: 创建/恢复真实 DSH 子会话

**Files:**
- Create: `src/review_sessions.ts`
- Modify: `src/index.ts`
- Modify: `package.json`
- Modify: `tests/harness.mjs`
- Create: `tests/review-session-routes.mjs`

- [ ] 写失败测试：已绑定返回 `reused` 且不启动子会话；未绑定从 SQLite 读取论文标题，调用一次 `subagents.startContinuable({ provider:'fork', label:title, ... })` 并保存；相同键并发请求只创建一次；父 Agent 不存在、论文不存在、跨源写请求均拒绝。
- [ ] 运行 `node tests\review-session-routes.mjs` 确认模块/路由不存在。
- [ ] 为宿主增加 rc.7 兼容的 `@deepseek-ai/dsh-agent`、`@deepseek-ai/dsh-subagent` peer/dev dependencies，并把 `agents`、`subagents` 加入 inject。
- [ ] 实现 `POST /sr/api/reviews/open`；首条 prompt 固定指定 paper ID、父会话分类、候选结论格式和“未经用户明确确认不得调用 `sr_review_confirm`”。
- [ ] 用按绑定键的 Promise map 单飞创建；成功或失败后都清理 map。
- [ ] 运行路由、harness、compat、typecheck。
- [ ] 中文提交：`功能：创建论文整理子会话`。

### Task 4: 子会话上下文与确认工具

**Files:**
- Create: `src/review_tools.ts`
- Modify: `src/preset.ts`
- Create: `tests/review-tools.mjs`

- [ ] 写失败测试：工具执行从 `exec.agent.id` 取子会话；普通父会话/未知子会话调用失败；`sr_review_context` 返回绑定论文资产和已有确认结论；`sr_review_confirm` 不接受会话 ID 参数并把全部条目交给引擎。
- [ ] 运行 `node tests\review-tools.mjs` 确认工具不存在。
- [ ] 注册 `sr_review_context` 和 `sr_review_confirm` 到文献 preset；确认工具描述写明仅在用户明确同意当前版本后调用。
- [ ] 确认成功后同步调用 `xlsx-snapshot`；Excel pending 时返回 `sqlite_status: confirmed` 与 `xlsx_status: pending`，不回滚结论。
- [ ] 运行工具、harness、安全边界和 typecheck。
- [ ] 中文提交：`功能：加入结论确认与入库工具`。

### Task 5: Excel“整理结论”派生表

**Files:**
- Modify: `engine/src/scientific_reading/xlsx_snapshot.py`
- Modify: `engine/tests/test_xlsx_snapshot.py`

- [ ] 写失败测试：工作簿包含“整理结论”；多父会话、多条结论各占一行；列顺序与设计一致；原“文献”一篇一行和三个用户字段回写保持不变。
- [ ] 运行 `python -m pytest engine\tests\test_xlsx_snapshot.py -q` 确认 sheet 缺失失败。
- [ ] 从 SQLite 查询确认结论并联接论文标题，生成筛选、冻结首行、换行和合适列宽；该 sheet 全部锁定且不参与 `import_user_fields()`。
- [ ] 更新“说明”表，说明整理结论由确认工具写入 SQLite 后派生。
- [ ] 运行 XLSX、schema、review service 测试。
- [ ] 中文提交：`功能：导出整理结论到 Excel`。

### Task 6: 文献页【整理入库】入口

**Files:**
- Modify: `client/client.js`
- Modify: `tests/client-actions.mjs`
- Modify: `tests/client-ui-contract.mjs`

- [ ] 写失败测试：每篇论文动作区存在【整理入库】；调用体包含当前 `ctx.sessions.list.current` 和 paper ID；成功后依次 `refreshSubagents(parent)`、`openSubagent(address)`；按钮忙碌时不可重复提交；非文献模式不挂载入口。
- [ ] 运行客户端测试确认失败。
- [ ] 将 `sessions` 传入文献页渲染依赖，增加 review action controller；接口返回后打开 exact continuable address。
- [ ] 创建/恢复失败时在论文行显示可理解错误，不改变当前会话或选择状态。
- [ ] 运行客户端构建、UI 合同、动作测试和离线回归。
- [ ] 中文提交：`界面：加入整理入库子会话入口`。

### Task 7: 跨层验收

**Files:**
- Modify: `docs/superpowers/plans/2026-08-30-paper-review-child-session.md`（只追加执行记录）

- [ ] 自动化集成：同父同论文重复打开复用；异父同论文分离；未确认无结论；确认多条后 SQLite 与 XLSX 一致。
- [ ] 在真实 DSH rc.7 文献模式会话点击【整理入库】，验证子会话标题为论文标题、普通顶层列表不出现、首轮主动给出候选结论。
- [ ] 关闭并重启 DSH 后再次点击，验证恢复同一 child session 并可继续讨论。
- [ ] 在第二个父会话打开同论文，验证 child ID 和结论均独立；Excel 能按父会话筛选并同时看到两组记录。
- [ ] 运行 `npm.cmd test`、`git diff --check`、package contents 检查；确认不包含 SQLite、XLSX、cookie、浏览器 profile 或 API Key。
