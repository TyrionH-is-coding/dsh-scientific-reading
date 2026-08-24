# 两段式文献工作流：总执行索引 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 DSH 文献插件收缩为“快速入库 + 按需精读”两段式产品，并在不破坏已有资产、当前 Profile 与飞书用户字段的前提下完成迁移。

**Architecture:** `Scientific-Reading-for-Newbies` 负责 SQLite、任务、资产、XLSX 与飞书领域契约；`dsh-scientific-reading` 只负责 DSH 工具、合法 PDF 获取适配、HTTP 路由和导航 UI。SQLite 是唯一事实来源，其他文件和在线表格都是派生产物。

**Tech Stack:** Python 3.11、SQLite/FTS5、PyMuPDF、openpyxl、pytest；Node.js 22、TypeScript 5.9、DSH rc.7、原生 Web Component/DOM、Node 合同测试。

---

## 0. 执行入口

产品决策以设计文档为准：

- `docs/superpowers/specs/2026-08-23-two-stage-literature-workflow-design.md`

实现必须按以下顺序执行，不能先做 UI 再补数据契约：

1. `docs/superpowers/plans/2026-08-23-two-stage-literature-workflow-phase-1-foundation.md`
2. `docs/superpowers/plans/2026-08-23-two-stage-literature-workflow-phase-2-full-read-assets.md`
3. `docs/superpowers/plans/2026-08-23-two-stage-literature-workflow-phase-3-navigation-batch.md`

每一阶段都必须同时满足自己的验收门，才可进入下一阶段。发现设计与现状不一致时，先在对应计划的“执行记录”中写明证据和最小调整，不得静默扩大范围。

## 1. 两仓库责任边界

### Python 引擎

仓库：`D:\Vibe Coding\Scientific-Reading-for-Newbies`

只在这里实现：

- SQLite schema、迁移、查重、文件夹、标签、分页与批量操作日志；
- Abstract 英中对照契约与后台任务；
- 持久任务、状态转换、断点恢复；
- PDF/解析/全文翻译/HTML 的领域编排；
- 图表导出包与 manifest；
- XLSX 快照；
- 飞书字段所有权、payload、幂等与回写状态；
- 纯 Python CLI 入口及单元/集成测试。

### DSH 插件

仓库：`D:\Vibe Coding\dsh-scientific-reading`

只在这里实现：

- DSH 工具注册与参数校验；
- 调用 Python 引擎 CLI；
- 调用现有 `scansci-pdf` 合法获取 PDF，并把结果挂接给引擎；
- HTTP JSON/文件路由；
- 【文献】导航页、详情抽屉、批量交互与失败入口；
- Bundle、Profile、浏览器与打包合同测试。

插件不得复制 SQLite 业务逻辑；引擎不得依赖 DSH UI 或读取浏览器凭证。

## 2. 分支与工作区规则

- [x] 先在两个仓库分别运行 `git status --short`，记录基线 commit 和已有用户改动。
- [x] 使用 `superpowers:using-git-worktrees` 为每个阶段建立隔离 worktree；不要直接在当前 `main` 开发。
- [x] 不触碰当前 `http://127.0.0.1:3080/` 的已安装插件，直到三个阶段的隔离验收全部通过。
- [x] 跨仓库测试时通过 `PYTHONPATH=<引擎 worktree>\src` 指向待测引擎，不覆盖用户现有虚拟环境里的稳定安装。
- [x] 每个任务先写失败测试，再写最小实现；按计划给出的中文 commit message 小步提交。
- [x] 阶段完成后独立复核 `git diff --check`、目标测试和全量测试。
- [x] 最终验收通过后，分别本地合并回两个仓库的 `main`，在 `main` 重跑全量测试，再清理临时 worktree/分支。
- [x] 未经用户本轮另行要求，不 push GitHub。

## 3. 永久安全约束

### 飞书

- [x] 所有自动化测试启动前显式删除子进程中的 `FEISHU_APP_ID` 与 `FEISHU_APP_SECRET`。
- [x] 测试只使用 fake client 和仓库外临时配置；不得对真实飞书执行 create/update/search。
- [x] 首次识别到有效配置时不得扫描并同步历史库；仅新建/发生系统字段变化的记录自动排队。
- [x] `personal_thoughts`、`understanding_level`、`user_notes` 等用户字段永不进入更新 payload。
- [x] App Secret 不得写入配置、SQLite、XLSX、日志、job JSON 或 HTTP 响应。

PowerShell 测试前置命令：

```powershell
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
```

### 用户数据与资产

- [x] 所有开发测试使用 `$env:TEMP\sr-two-stage-*` 数据根。
- [x] schema 迁移前用 SQLite backup API 创建可读备份；不通过复制正在使用的 WAL 数据库冒充备份。
- [x] 不删除或重命名已有 PDF、MinerU、旧浅读和 HTML；新索引只引用现有路径。
- [x] 无效 PDF 不得覆盖已校验原件；新 PDF 哈希改变时旧 HTML 标为 stale。
- [x] 测试样本使用虚构工科题录与本地小 PDF，不使用医学文献，不调用机构认证。

## 4. 跨阶段稳定契约

### 用户可见动作

普通路径只暴露：

1. 入库；
2. 浅读（Abstract 英中对照）；
3. 开始精读 / 阅读 HTML；
4. PDF；
5. 飞书；
6. 更多菜单中的资产、导出与失败重试。

不得重新引入常驻的【下载】【解析】【生成九节浅读】按钮。

### 用户可见状态

```text
正在入库 → 生成浅读 → 待精读 → 精读排队 → 获取 PDF
          → 解析全文 → 翻译与生成 → 精读完成
          ↘ 需要用户处理 / 处理失败
```

内部阶段名可以更细，但 API 必须统一映射为上述状态。XLSX/飞书失败只显示各自派生状态，不得把本地文献改成失败。

### 稳定身份

- 新记录使用 `paper_id` 与本地 `library_key`。
- DOI、PMID、arXiv ID 优先查重；标题只在规范化题名、年份、作者组合明确时合并。
- 旧 `zotero_key` 仅作为迁移期只读别名；不得发起 Zotero 网络/本地 API 调用。
- 飞书新配置优先映射 `library_key`；旧 `zotero_key` 列映射可继续承载同一个本地稳定 key，以避免自动修改用户现有表结构。

## 5. 阶段验收门

### Phase 1：主库与轻量入库

- [x] DOI 骨架记录在隔离环境 3–5 秒内可查询，Abstract/XLSX/飞书在后台。
- [x] schema v1 数据可备份并迁移，现有路径与旧文件不变。
- [x] 文件夹单归属、标签多归属、分页搜索和批量归类撤销通过。
- [x] 新浅读不依赖 PDF/MinerU；无 Abstract 时明确 `missing`，不生成内容。
- [x] XLSX 锁定不回滚入库；释放后可重试。
- [x] 飞书自动启用、系统字段白名单、首次不回填历史记录均由 fake client 验证。

### Phase 2：精读与资产

- [x] 一个父任务串联 PDF、校验、解析、逐块翻译、渲染，并可重启恢复。
- [x] 自动下载失败只把单篇置为【需要用户处理】。
- [x] HTML 与 PDF SHA 有可读 manifest 关系；PDF 改变会使 HTML stale。
- [x] Figure/Table 导出命名、caption、SHA、页码和可选 CSV 合同通过。
- [x] 不选择关键图，不用 AI 猜表格单元格。

### Phase 3：导航、批量与实机

- [x] 可收起文件夹树、宽列表、临时 Abstract 抽屉和快捷入口完成。
- [x] 【全部文献】【待归类】命名准确；标签与最近入库是筛选而非文件夹。
- [x] 批量内部按 100 分块，重任务串行，单篇失败不终止批次。
- [x] 旧资产/旧浅读仍可访问，Zotero UI/工具消失。
- [x] 隔离 Profile 的 tarball 安装、HTTP、浏览器布局和关闭清理通过。

## 6. 全量验证命令

在 Python 引擎 worktree：

```powershell
$env:PYTHONPATH = "$PWD\src"
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
git diff --check
```

在插件 worktree：

```powershell
npm run typecheck
npm run test:offline
git diff --check
```

最终 persistent Profile 验收只能在上述命令全部通过后执行：

```powershell
npm run verify:profile-bundle
npm run verify:profile-runtime
npm run verify:restart-recovery
```

## 7. 不在本轮实现的内容

- SQLite/XLSX/飞书双向同步；
- 飞书个人字段回写本地；
- 批量删除；
- 多个 MinerU/全文翻译任务并行；
- AI 自动挑选关键图；
- 批量机构浏览器下载；
- DSH 页面内嵌整篇 HTML；
- 自动修改用户飞书表结构；
- 第一版额外的推荐、引用网络或知识图谱功能。

## 8. 执行记录

实现 agent 在这里追加每阶段的分支名、基线 commit、完成 commit、验证命令和结果摘要。不要记录密钥、Cookie、验证码或真实个人数据。

### 三阶段隔离验收摘要（2026-08-25）

- 两仓库均在 `feature/two-stage-workflow` 隔离 worktree 开发。Phase 1 基线为引擎 `c4700538`、插件 `aa6aed95`；Task 7 Step 4 更新前 HEAD 为引擎 `1621276`、插件 `edfeda4`。
- Phase 1/2/3 计划中的产品任务与安全门已完成；最后一次引擎 worktree 全量为 `805 passed, 3 skipped`。插件 `build:ci`、`typecheck`、完整离线门禁、真实 Bundle/Profile verifier、导航 runtime 与 restart recovery 均已通过。
- 隔离实机使用真实 DSH `0.1.0-rc.7` tarball、临时 `web` Profile、独立 3180 端口和 60 篇虚构工科题录；HTTP 读回覆盖分页、搜索、待归类、文件夹、Abstract、批量 parent、正式 generation reader/PDF 和 PNG/CSV exports。
- 浏览器在 1440×900、1280×720、900×720 完成布局与交互 QA；关闭后验证宿主停止、端口释放、worker 无残留、临时根可清理。Windows 子进程无可见终端窗口。
- 两仓库已按依赖顺序本地合并回 `main`，任务 worktree/分支已清理；引擎 `main` 全量为 `810 passed, 3 skipped`，插件 `build:ci`、`typecheck` 与完整 `test:offline` 全部通过。最终兼容热修状态为引擎 `e1cb149`、插件 `998155d`。
- persistent Profile 已先完成 tarball/config/SQLite 备份，再安装 SHA-256 为 `a6e10061d0c5a94eeec7bc75e1afb66288b45a2d055a8e31ad15622befc360cb` 的真实 tarball。当前 3080 的主页、导航、列表、详情、Abstract、旧浅读和经审计旧 PDF 路由通过 HTTP 读回；1280×720 浏览器验收覆盖 sidebar、drawer、搜索、空状态、对话框、disabled 原因与无横向溢出，停止/重启后库与 PDF 路由恢复。
- 持久库只对现有一篇非医学工科文献执行 DOI 去重验证，未新增记录；未执行真实飞书写入、机构认证、网络下载或 GitHub push。尚未生成的精读 reader 正确保持 404；“期刊正文优先”生产 reader builder 迁移属于后续独立范围。
