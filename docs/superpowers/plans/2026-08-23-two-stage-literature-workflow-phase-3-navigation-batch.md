# Phase 3：文献导航、批量操作与实机验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把【文献】页改成可快速查找、归类和跳转的导航主页，完成批量操作、旧数据兼容、Zotero 运行入口移除，并通过隔离 Profile 与最终 persistent Profile 实机验收。

**Architecture:** 服务端提供分页、筛选、批量父任务和稳定资产链接；前端保持“可收起文件夹树 + 宽列表 + 临时详情抽屉”，不复制业务状态。迁移只建立索引与兼容回退，不搬移已校验资产。

**Tech Stack:** TypeScript DSH routes/tools、原生 Web Component/DOM/CSS、Node 合同测试与浏览器 QA；Python SQLite/迁移审计/批量调度、pytest。

---

## 前置假设与成功条件

1. Phase 1/2 的引擎/API/父任务合同已通过；本阶段不重新设计数据层。
2. canonical 前端源是 `client/client.js`，`lib/client.js` 只能由 `scripts/build-client.mjs` 生成。
3. 页面第一版使用服务端分页（默认 50，最大 100），不引入虚拟列表框架。
4. 视觉延续已确认阅读风格：暖白背景、深色正文、克制边框；只用黄色/亮蓝重点和少量状态色，不给列名/标签做彩虹配色。
5. 浏览器打不开本地目录时，资产入口至少提供绝对路径与复制按钮；只有用户明确点击“在资源管理器中打开”才允许服务器发起本地打开动作。

完成的可验证定义：

- 左侧只有【全部文献】【待归类】和用户文件夹，并能收起；标签和最近入库仅作筛选；
- 宽列表可搜索/分页，题名打开 Abstract 抽屉，PDF/HTML/飞书/资产入口可用；
- 批量移动、标签、精读排队、重试和飞书重同步按 100 分块并有父汇总，不提供批量删除；
- 旧 PDF、MinerU、HTML、旧浅读均不移动且仍可访问；新运行入口中无 Zotero；
- 隔离 tarball Profile、HTTP、浏览器和重启恢复全部通过后，才更新当前 persistent Profile。

## Task 1：收敛导航与批量 HTTP 合同

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\routes.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\library_tools.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\papers.ts`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\navigation-contract.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\batch-contract.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\reading-routes.mjs`

- [x] **Step 1: 写 HTTP 失败合同**

固定端点：

```text
GET  /sr/api/library?page=1&page_size=50&q=&folder=&tags=&status=&recent_days=
GET  /sr/api/folders
GET  /sr/api/paper/<paper_id>
GET  /sr/api/paper/<paper_id>/abstract
GET  /sr/api/paper/<paper_id>/pdf
GET  /sr/api/paper/<paper_id>/assets
POST /sr/api/paper/<paper_id>/full-read
POST /sr/api/paper/<paper_id>/attach-pdf
POST /sr/api/paper/<paper_id>/export-assets
POST /sr/api/batch
GET  /sr/api/job/<job_id>
GET  /sr/reader/<paper_id>
```

测试 method 405、非法 page/size、路径穿越、body 超限、未知 action、批量空选择、超过 100 时引擎
父请求仍只收到一份完整 selection、错误无 stack/secret。

- [x] **Step 2: 固定列表响应**

```json
{
  "items": [{
    "paper_id": "...",
    "title": "...",
    "authors_short": "...",
    "year": 2017,
    "folder": null,
    "tags": ["NLP"],
    "abstract_status": "ready",
    "full_read_status": "not_started",
    "feishu_sync_state": "synced",
    "has_pdf": true,
    "has_reader": false,
    "feishu_record_url": "",
    "last_error": ""
  }],
  "page": 1,
  "page_size": 50,
  "total": 1,
  "jobs": {"running": 0, "queued": 0}
}
```

不要把 Abstract 全文或 job 内部 required_input 塞进列表；详情按需读取。

- [x] **Step 3: 固定批量 action 白名单**

只允许：`move_folder`、`add_tags`、`remove_tags`、`queue_full_read`、`retry_failed`、
`feishu_resync`。明确拒绝 `delete`。响应统一为 parent summary/job id；单篇错误保留在 children 中。

- [x] **Step 4: 实现路由并验证**

路由只做验证/转发。PDF 和 reader 使用已解析的 workspace 路径并校验必须位于 data root；飞书 URL
只从 SQLite 返回，不接受客户端注入。

```powershell
npm run build:ci
node tests/navigation-contract.mjs
node tests/batch-contract.mjs
node tests/reading-routes.mjs
git add src/routes.ts src/library_tools.ts src/papers.ts tests/navigation-contract.mjs tests/batch-contract.mjs tests/reading-routes.mjs
git commit -m "接口：固定文献导航与批量操作合同"
```

## Task 2：重做两栏导航骨架

**Required sub-skill:** 使用 `frontend-design`，但必须遵守本计划已确认的信息架构和配色边界，不重新做产品发散。

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\client\client.js`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\client-ui-contract.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\client-build.mjs`

- [x] **Step 1: 写 DOM/文案失败合同**

断言：

- 根布局只有 sidebar、main list、overlay drawer，不存在常驻第三栏；
- 存在【全部文献】【待归类】，不存在【收件箱】【待整理】；
- sidebar 可收起并用 `aria-expanded`；
- 顶部搜索、添加、批量粘贴、状态/标签/最近入库筛选；
- 表头包含题名、作者/年份、归类、状态、快捷入口；
- 不出现普通【下载 PDF】【解析】【生成浅读】阶段按钮；
- canonical `client/client.js` 与生成 `lib/client.js` 一致。

- [x] **Step 2: 实现布局与 design tokens**

在现有组件内定义少量 CSS variables，不引入 UI 框架：

```css
--sr-bg: #f6f3ec;
--sr-surface: #fffdf8;
--sr-text: #20332f;
--sr-muted: #6e7974;
--sr-line: #d9ddd6;
--sr-accent: #315f70;
--sr-highlight-yellow: #ffd84d;
--sr-highlight-blue: #3aa7ff;
```

sidebar 展开宽 240px、收起仅保留图标/开关；main 使用剩余宽度；普通桌面最小验收 1280×720。
不要给每个文件夹或列名分配不同颜色。

- [x] **Step 3: 实现服务器分页和筛选状态**

URL/query 状态由一个明确 store 管理；搜索 250ms debounce，切换文件夹/筛选回到第 1 页；请求
使用 AbortController 丢弃过时响应；加载/空/错误三态都有中文文案。

- [x] **Step 4: 构建、测试并提交**

```powershell
npm run build:client
npm run check:client
node tests/client-ui-contract.mjs
node tests/client-build.mjs
git add client/client.js lib/client.js tests/client-ui-contract.mjs tests/client-build.mjs
git commit -m "界面：改造为可收起的文献导航页"
```

## Task 3：文献行、Abstract 抽屉与快捷入口

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\client\client.js`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\client-ui-contract.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\client-actions.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\reading-routes.mjs`

- [x] **Step 1: 写交互失败合同**

覆盖：题名点击加载一次详情；drawer 可 Escape/遮罩/关闭按钮关闭并恢复焦点；Abstract 按英文→中文
逐段显示；missing 明确“待补摘要”；按钮按产物状态切换；失败才显示高级入口；飞书未配置/待同步/
已同步；路径复制；旧 HTML/旧浅读回退。

- [x] **Step 2: 实现文献行**

每行只显示：选择框、题名、简短作者/年份、主文件夹/最多两个标签、浅读/精读/飞书状态、
【浅读】【开始精读/阅读 HTML】【PDF】【飞书】和更多菜单。没有产物的按钮 disabled 并给原因，
不要让空链接可点击。

- [x] **Step 3: 实现详情 drawer**

drawer 内容：完整题录、Abstract 英中对照、阶段状态/失败原因、PDF/HTML/飞书/资产目录入口。
不内嵌 reader，不展示 MinerU 参数。若只有旧九节式浅读，在更多菜单给“查看历史浅读”，不能把它
当作新 Abstract 浅读。

- [x] **Step 4: 实现单篇动作和轮询**

- 开始精读 POST 后按钮立刻显示排队；只轮询该 parent job，完成后刷新该行；
- needs_user 时才显示“使用机构浏览器”“挂接本地 PDF”；
- export 完成后显示 Figures/Tables 数量和路径；
- PDF/reader 使用服务器路由；飞书使用 `target=_blank` 和 `rel=noopener`；
- 组件卸载或 drawer 关闭时清理 timer/AbortController。

- [x] **Step 5: 测试并提交**

```powershell
npm run build:client
node tests/client-ui-contract.mjs
node tests/client-actions.mjs
node tests/reading-routes.mjs
git add client/client.js lib/client.js tests/client-ui-contract.mjs tests/client-actions.mjs tests/reading-routes.mjs
git commit -m "界面：加入Abstract抽屉与资产快捷入口"
```

## Task 4：批量选择、归类与队列反馈

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\classification_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\reading_pipeline.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\batch_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_batch_service.py`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\client\client.js`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\batch-contract.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\client-batch-actions.mjs`

- [x] **Step 1: 写引擎批量失败测试**

覆盖 0/1/100/101/250 篇，断言 101→2 chunks、250→3 chunks；重复/失败/needs_user 不终止其他；
queue_full_read 只排队不并行；retry 只选失败项；飞书 resync 只选 pending/用户指定项；父 summary
计数相加准确；无 delete action。

- [x] **Step 2: 实现 `BatchService`**

```python
ALLOWED_ACTIONS = {
    "move_folder", "add_tags", "remove_tags",
    "queue_full_read", "retry_failed", "feishu_resync",
}
CHUNK_SIZE = 100

class BatchService:
    def submit(self, action: str, paper_ids: Sequence[str], payload: dict) -> BatchResult: ...
    def inspect(self, parent_job_id: str) -> BatchResult: ...
```

父任务保存原选择顺序、chunks 和 children；逐条保存 created/reused/needs_user/failed。事务型移动/标签
操作可整体撤销；队列/重试不承诺撤销已开始的任务。

- [x] **Step 3: 写前端选择失败合同并实现**

选择集合以 paper_id 保存，翻页不丢；顶部只显示“已选 N 篇”和允许动作。批量工具栏不含删除。
提交后清空已成功项，保留失败项供重试；父 summary 用一条提示，不弹 N 个 toast。

AI 批量归类仍由对话工具发提案：默认只用现有 folders，低置信度留待归类；UI 只应用/撤销结果，
不在浏览器里实现分类算法。

- [x] **Step 4: 测试并分别提交**

引擎：

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_batch_service.py tests/test_classification_service.py tests/test_reading_pipeline.py -q
git add src/scientific_reading/batch_service.py src/scientific_reading/classification_service.py src/scientific_reading/reading_pipeline.py src/scientific_reading/__main__.py tests/test_batch_service.py
git commit -m "批量：按百篇分块并汇总独立结果"
```

插件：

```powershell
npm run build:client
node tests/batch-contract.mjs
node tests/client-batch-actions.mjs
git add client/client.js lib/client.js tests/batch-contract.mjs tests/client-batch-actions.mjs
git commit -m "界面：加入跨页批量操作与父任务反馈"
```

## Task 5：停用 Zotero 运行链路并审计旧资产

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\migration_audit.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\worker.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\workspace.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_migration_audit.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_repository_boundaries.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_worker.py`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\library_tools.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\client\client.js`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\no-zotero-runtime.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\client-ui-contract.mjs`

- [x] **Step 1: 写旧库 fixture 与失败测试**

fixture 包含：旧 `metadata.zotero_key`、旧 PDF、MinerU 目录、`reader_full.html`、`quick_read.md/json`、
一个缺失路径。断言审计只建立引用/警告，不移动/删除/重算；legacy key 映射为 library_key；旧 reader
仍可路由；旧 quick read 仅更多菜单；新 CLI/worker/tools/UI 无 Zotero 入口。

- [x] **Step 2: 实现只读迁移审计**

`migration_audit.py` 扫描 SQLite 和 workspace，写 `library/migration-audit.json`：每篇现有资产、SHA
可读性、legacy 路径、缺失警告。已有可信 manifest/SHA 直接复用；只为缺 SHA 且文件存在的资产计算
SHA，不重解析 PDF。

- [x] **Step 3: 移除运行可达性，不做大规模源码删除**

- 从 `DEFAULT_HANDLERS` 移除 `zotero_record`；
- 从新 CLI parser 移除 Zotero 写入/迁移命令；若必须保留只读审计命令，命名为 `legacy-audit`；
- 插件不注册 `sr_zotero_*`，新 description/README/UI 不出现 Zotero；
- Python 旧模块暂留供历史测试和审计 import，避免在本阶段做无收益大删除。

- [x] **Step 4: 测试并分别提交**

```powershell
# 引擎
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_migration_audit.py tests/test_repository_boundaries.py tests/test_worker.py tests/test_workspace.py -q
git add src/scientific_reading/migration_audit.py src/scientific_reading/worker.py src/scientific_reading/__main__.py src/scientific_reading/workspace.py tests/test_migration_audit.py tests/test_repository_boundaries.py tests/test_worker.py
git commit -m "迁移：停用Zotero运行链路并审计旧资产"

# 插件
npm run build:client
node tests/no-zotero-runtime.mjs
node tests/client-ui-contract.mjs
git add src/library_tools.ts client/client.js lib/client.js tests/no-zotero-runtime.mjs tests/client-ui-contract.mjs
git commit -m "插件：移除Zotero入口并保留旧资产访问"
```

## Task 6：隔离 Profile 的功能和视觉实测

**Required sub-skill:** 在宣称完成前使用 `verification-before-completion`；视觉检查使用可用的浏览器控制技能。

**Files:**

- Create: `D:\Vibe Coding\dsh-scientific-reading\scripts\verify_navigation_runtime.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\navigation-runtime.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\profile-runtime-verifier.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\package.json`

- [x] **Step 1: 打包真实 tarball 并安装到隔离 Profile**

使用临时 `DSH_HOME`、临时 data root、独立端口（例如 3180）。`npm pack --dry-run` 先验证内容，再
安装实际 tarball。不得使用开发注入冒充 Bundle 验收。

- [x] **Step 2: HTTP 自动验收**

导入 60 篇虚构工科题录，断言第 1/2 页、搜索、待归类、文件夹、详情、Abstract、批量父任务、
reader/pdf/exports 路由。所有请求清空飞书凭证、scansci 用 fake provider。

- [x] **Step 3: 浏览器视觉与交互 QA**

在 1440×900、1280×720、窄宽 900×720 截图/检查：

- sidebar 展开/收起后列表宽度；
- 长题名不覆盖状态/按钮；
- drawer 不常驻挤压列表；
- 搜索/筛选/分页/跨页选择；
- 重点色仅黄/亮蓝，标签/列名无彩虹；
- 键盘焦点、Escape、按钮 disabled 原因；
- 处理中/排队汇总和 needs_user fallback。

发现视觉问题先写/更新 DOM 合同或 runtime assertion，再做最小 CSS 修复。

- [x] **Step 4: 关闭清理**

停止隔离 DSH 后断言端口释放、worker 无残留、临时 Profile 可删除。当前 3080 仍未变化。

- [x] **Step 5: 验证并提交**

```powershell
npm run typecheck
npm run test:offline
node tests/navigation-runtime.mjs
npm run verify:profile-bundle
npm run verify:profile-runtime
git add scripts/verify_navigation_runtime.mjs tests/navigation-runtime.mjs tests/profile-runtime-verifier.mjs package.json
git commit -m "验收：覆盖文献导航的隔离实机运行"
```

## Task 7：全量复核、本地合并与 persistent Profile 更新

**Required sub-skills:** 使用 `requesting-code-review` 做阶段性审核；如使用 subagent，按用户要求采用 medium 推理。随后使用 `finishing-a-development-branch` 和 `verification-before-completion`。

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\README.md`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\README.md`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\docs\superpowers\plans\2026-08-23-two-stage-literature-workflow-index.md`

- [x] **Step 1: 对照设计逐项审查**

检查 11 条验收标准和“不在本轮实现”清单。重点搜索：

```powershell
rg -n "Zotero|收件箱|待整理|关键图|生成浅读|下载 PDF|解析" src client tests README.md
rg -n "FEISHU_APP_SECRET|personal_thoughts|understanding_level|user_notes" src tests
```

允许测试/迁移说明中的预期命中；任何新 UI/运行工具命中必须解释或删除。

- [x] **Step 2: 独立代码审核**

审核者检查：schema 回滚、路径边界、飞书首次启用、用户字段 payload、任务幂等/恢复、重任务串行、
前端 timer/AbortController 清理、旧资产不移动。只修本项目问题，不顺手重构邻近代码。

- [x] **Step 3: 两仓库 worktree 全量验证**

```powershell
# Python 引擎
$env:PYTHONPATH = "$PWD\src"
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
git diff --check

# DSH 插件
npm run typecheck
npm run test:offline
npm run verify:profile-bundle
npm run verify:profile-runtime
npm run verify:restart-recovery
git diff --check
```

- [x] **Step 4: 更新中文 README 与执行记录**

README 只描述真实完成的两段式流程、启动、数据目录、飞书/XLSX所有权、资产导出、失败恢复和限制。
总索引追加 commit/测试结果，不记录凭证和真实用户数据。

- [x] **Step 5: 本地合并回 main 并在 main 重测**

分别按依赖顺序先合并 Python 引擎，再合并插件。禁止 `git reset --hard`/`git checkout --` 清除
用户改动。main 上重跑 Step 3 全套测试，结果必须与 worktree 一致；完成后清理临时 worktree/分支。

- [x] **Step 6: 最后才更新当前 persistent Profile**

记录旧 tarball/config/数据 DB 备份与 SHA；安装 main 构建的真实 tarball，重启当前 Profile。先做只读
启动/列表/详情/路由验证，再用一篇合法开放、非医学测试论文验证本地入库。没有本轮单独授权时，
不执行真实飞书写入和机构认证下载。

- [x] **Step 7: 最终实机读回**

浏览器检查当前 3080 的全部文献、待归类、长题名、Abstract 抽屉、已有 PDF/旧 HTML 入口。停止/
重启一次，确认任务和路由恢复；记录 package SHA、HTTP assertion、浏览器截图路径和已知限制。

## Phase 3 执行记录

实现 agent 追加隔离 Profile 路径/端口、tarball SHA、HTTP 与视觉 QA 结果、两仓库 main merge commit、
main 全量测试结果、persistent Profile 版本和未执行的外部写入项。不得记录飞书 secret、Cookie、
验证码或个人文献内容。

- Task 1 已完成（commits `7134c23`、`672521e`、`5b6130f`）：固定导航/批量 HTTP 合同、严格字段类型与脱敏、1 MiB body 上限与 405；六种 action 白名单，101 篇选择由路由完整单次转发，批量分块仍留给 Task 4。generation 资产路由覆盖 PDF、reader、assets，并校验 SHA 与 symlink 边界。最终规范审核与质量审核均为 `APPROVED`。`build:ci`、`typecheck`、计划指定 3 项测试、library、full-read、assets、Phase 1 与 harness 全部 `PASS`。本任务未改引擎/UI/v2.1，未操作 3080、网络或飞书。

- Task 2 已完成（commits `4a1063d`、`1be8e0e`、`997377b`）：实现可收起 sidebar、宽主列表与隐藏 overlay drawer 骨架，接入服务器分页、搜索和筛选；folders 顶层数组使用 `folder_id`，待归类使用 `__unclassified__`。无 DOM 依赖的 mount-controller 生命周期 harness 覆盖稳定 ref 重渲染、卸载清理与同节点重挂。规范审核与质量审核均为 `APPROVED`；`build:ci`、`typecheck`、`client-ui`、`client-build`、完整 `offline` 与 `git diff --check` 均通过。未提前实现 Task 3，未联网、未操作 3080，也未启动真实 worker。

- Task 3 已完成（engine commits `7bfed70`、`18156d5`；plugin commits `a1e3adb`、`b0297ae`、`52b39fd`、`80efa93`）：实现文献行、按需单次详情读取的 Abstract overlay drawer、安全 PDF/reader/飞书/历史浅读入口、资产目录与图表导出反馈，以及相互隔离的行级精读轮询和 drawer 生命周期。规范审核与质量审核均为 `APPROVED`；root 在清空 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 后重跑完整 `npm run test:offline` 全部 `PASS`，engine targeted tests 为 `48 passed`。最小计划偏差：为满足固定导航合同，engine 使用单条 set-based SQLite 查询补齐列表字段，未在插件逐行启动子进程；未开放根目录 legacy `reader_full.html`，正式 reader 仍只允许同 generation 的 `reading/reader.html`，并回退同 generation 的 `output/reader_full.html`，根旧资产留给 Task 5 migration audit 建立只读索引。本任务未执行外部写入、3080 操作、网络访问或真实飞书同步。

- Task 4 已完成（engine commits `9bbfe2a`、`e10bc95`、`a38952c`、`0a240e3`、`f30a211`、`93134d4`；plugin commits `f4d14c1`、`5018067`、`89e4c0a`）：实现批量选择稳定去重与按 100 篇分块、逐篇独立结果、父任务增量持久化与脱敏失败收束、事务型文件夹/标签操作及完整撤销句柄；精读与飞书动作只创建或复用持久队列，不在批量调用中启动重 worker。前端按 `paper_id` 跨页保留选择，以选择 revision 隔离晚响应，同一时刻只允许一个副作用提交；仅移除 `created/reused`，并用独立 `aria-live` 父汇总区分完成、失败和处理中状态。Windows 越界门禁实际创建 directory junction 并验证拒绝，且子进程使用 `CREATE_NO_WINDOW`。最终规范审核与质量审核均为 `APPROVED`；engine worktree 全量为 `778 passed, 1 skipped`，root 独立定向复核为 `70 passed`，plugin 完整 `npm run test:offline` 全部 `PASS`。最小计划偏差：未修改 `reading_pipeline.py`，而是复用既有 `start`/resume 合同，并以真实 worker 回归证明失败阶段可恢复且不重复已完成重阶段。本任务未操作 3080/persistent Profile，未联网，未执行真实飞书写入、机构认证或其他外部操作。

- Task 5 已完成（engine commits `a43fcac`、`1b6b1e3`、`ed5737f`、`26082cd`、`264925d`；plugin commit `2e38ce7`）：旧库 fixture 覆盖 legacy key、PDF、MinerU、旧 reader/浅读和缺失路径；迁移审计以完整 manifest、SHA、路径 containment、hardlink/junction 边界验证现有资产，仅建立索引与警告，不移动、删除或重算旧产物。Zotero record、旧 PDF acquisition CLI/default handler 及插件运行入口已移除，旧源码只为只读兼容保留。最终独立审核为 `APPROVED`；engine 定向复核为 `100 passed, 2 skipped`，worktree 全量为 `798 passed, 3 skipped`，插件离线测试全部通过。审计只保证单用户数据根中的陈旧/误改可检测性；拥有本地完整写权限并同时篡改资产与审计文件的恶意写者不属于本轮密码学信任边界。

- Task 6 已完成（engine commits `3b624d1`、`1621276`；plugin commits `1c1f05b`、`ffd9a13`、`93cd41c`、`8a9b973`、`9129dff`、`972bd3f`、`55c0069`）：使用真实 DSH `0.1.0-rc.7` tarball、临时 `web` Profile、独立 3180 端口和 60 篇虚构工科文献完成隔离实机验收；HTTP 读回覆盖两页列表、搜索、待归类、文件夹、详情、英中 Abstract、批量父任务、正式 generation reader、活动代次 PDF 及真实 PNG/CSV 资产。浏览器在 1440×900、1280×720、900×720 三档检查录入 modal、搜索/筛选/分页、跨页选择、overlay drawer、Escape/焦点恢复、disabled 原因、排队汇总与 `needs_user` fallback；视觉仅使用黄色/亮蓝重点。QA 发现并以合同测试驱动修复文献列表内部滚动和宿主 composer 遮挡。关闭门禁逐项验证宿主停止、端口释放、worker 身份与清理、临时根删除；任一步失败都会保留现场，且后续清理仍继续执行。真实导航运行返回 `navigation_runtime_verified`，真实 Bundle/Profile verifier 均通过，engine 全量为 `805 passed, 3 skipped`；当前 3080/persistent Profile 未动，未执行真实飞书写入或机构认证。

- Task 7 Steps 1-4 已完成（engine commits `2e49f23`、`cd859b8`；plugin commits `5d1a9f9`、`e55aa41`、`125f7c3`）：逐项审查后为 MinerU 探测/执行及 scansci provider 的生产子进程统一补齐 Windows `CREATE_NO_WINDOW`，并以直接拦截三个真实启动点的测试验证；插件停用旧 `POST /sr/api/paper`、parse、quick-read 写入路由，旧请求统一 404 且不泄露异常，同时保留批准的 library/detail/full-read/PDF/assets/reader 路由。中文 README 已与实际两段式合同一致。独立低推理 Sol 复核为 `APPROVED`，无 Critical/Important/Minor；插件 `typecheck` 与完整 `test:offline` 全部通过，引擎 worktree 独占全量为 `808 passed, 3 skipped`（69.12 秒），两仓库 `git diff --check` 通过。尚未执行本地合并、persistent Profile 更新或任何外部写入。

- Task 7 Steps 5-7 已完成：引擎与插件按依赖顺序本地合并回 `main`，并在 `main` 分别通过引擎全量 `810 passed, 3 skipped`、插件 `build:ci`、`typecheck` 与完整 `test:offline`。最终合并及兼容热修状态为引擎 `e1cb149`、插件 `998155d`；热修只开放由迁移审计、数据库 attachment 与当前文件 SHA 三方一致证明的旧根目录 `source.pdf`，活动 generation 声明损坏时仍关闭回退。更新前备份位于 `C:\Users\15694\.dsh\backups\scientific-reading-20260825T004359`，SQLite 使用 backup API 且完整性为 `ok`。persistent Profile 安装包为 `dsh-external-dsh-scientific-reading-0.0.1-A6E10061D0C5A94E.tgz`，SHA-256 为 `a6e10061d0c5a94eeec7bc75e1afb66288b45a2d055a8e31ad15622befc360cb`；迁移审计 SHA-256 为 `df36cea28d61065963a511f3193af1a0ca0bbef300da4ba4cff2d87a92eeaf75`。

- 当前 3080 完成只读 HTTP、浏览器与停止/重启验收：主页、文献导航、列表、详情、Abstract 与旧浅读均为 200；审计旧 PDF 返回 2,215,244 字节且 SHA 与数据库一致；未生成的精读 reader 正确返回 404。同一篇工科题录重复入库命中 DOI 去重并返回原 `paper_id`，未新增记录。浏览器 1280×720 下验证 sidebar 展开/收起、overlay drawer、Escape 焦点归还、作者搜索、空状态、录入与批量对话框及禁用原因，无页面级横向溢出；最终截图 `persistent-3080-final.png` 的 SHA-256 为 `a4a73bfa05635493270561ba0adfbd4ace7a6f7cb907c14d67a74a413f8cbec8`。停止后端口释放，重启后库中 1 篇记录与 PDF 路由恢复。任务 worktree/分支已清理，其他 reader v2.1 工作树及用户未跟踪的 `docs/survey.html` 保持不动。本轮未真实写飞书、未执行机构认证或网络下载、未 push GitHub。
