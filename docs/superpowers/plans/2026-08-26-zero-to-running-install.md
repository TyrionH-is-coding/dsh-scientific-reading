# 全新 Windows 机器安装 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把插件仓库 README 改成一条可从全新 Windows 机器完成 DSH、引擎和插件安装的可复制流程，并记录下一阶段文献发现路线。

**Architecture:** 文档以已验证版本为主路径：Node.js 22、Python 3.11、DSH 0.1.0-rc.7；插件通过源码构建的 tarball 安装到 `web` Profile。路线图只记录检索数据流和产品边界，不提前实现检索代码。

**Tech Stack:** Windows PowerShell、winget、Git、Node.js/npm/pnpm、Python venv、DeepSeek Harness CLI、Markdown。

---

### Task 1: README 零基础安装主路径

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在“安装与启动”前加入安装总览**

写明目标平台为 Windows 10/11 x64，首次安装需要约 10–20 分钟；本地浅读不要求 MinerU 或飞书凭据，精读需要 `MINERU_API_TOKEN`，飞书同步需要对应 App 凭据。

- [ ] **Step 2: 写入基础依赖安装与版本检查命令**

```powershell
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id OpenJS.NodeJS.22 -e --accept-package-agreements --accept-source-agreements
winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
```

要求用户重新打开 PowerShell，然后执行：

```powershell
git --version
node --version
npm --version
py -3.11 --version
```

- [ ] **Step 3: 写入 DSH 固定版本安装命令**

```powershell
npm.cmd install --global pnpm@11 @deepseek-ai/dsh@0.1.0-rc.7
dsh --version
```

解释 `0.1.0-rc.7` 是当前插件已验证宿主；升级 DSH 前应重新运行插件验收。

- [ ] **Step 4: 写入两个仓库的安装命令**

```powershell
$src = Join-Path $env:USERPROFILE 'scientific-reading-src'
New-Item -ItemType Directory -Force -Path $src | Out-Null
git clone https://github.com/TyrionH-is-coding/Scientific-Reading-for-Newbies.git (Join-Path $src 'Scientific-Reading-for-Newbies')
git clone https://github.com/TyrionH-is-coding/dsh-scientific-reading.git (Join-Path $src 'dsh-scientific-reading')

$engine = Join-Path $src 'Scientific-Reading-for-Newbies'
py -3.11 -m venv (Join-Path $engine '.venv')
& (Join-Path $engine '.venv\Scripts\python.exe') -m pip install --upgrade pip
& (Join-Path $engine '.venv\Scripts\python.exe') -m pip install -e $engine
& (Join-Path $engine '.venv\Scripts\python.exe') -m scientific_reading --help
```

- [ ] **Step 5: 写入插件构建与真实 tarball 安装命令**

```powershell
$plugin = Join-Path $src 'dsh-scientific-reading'
Set-Location $plugin
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
$pack = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$tarball = Join-Path $plugin $pack[0].filename
dsh plugin --profile web add $tarball --offline --ignore-scripts
dsh --profile web --dump-config | Select-String '@dsh-external/dsh-scientific-reading'
```

- [ ] **Step 6: 写入环境变量、启动和最小验收**

使用当前进程变量保证首次启动立即生效，并给出可选的用户级持久化命令：

```powershell
$enginePython = Join-Path $engine '.venv\Scripts\python.exe'
$env:SCIENTIFIC_READING_PYTHON = $enginePython
[Environment]::SetEnvironmentVariable('SCIENTIFIC_READING_PYTHON', $enginePython, 'User')
dsh --profile web --host 127.0.0.1 --port 3080
```

明确界面中还需配置模型、选择工作区，并检查左侧“文献”入口。MinerU 和飞书变量仅使用占位说明，不写示例密钥值。

- [ ] **Step 7: 添加更新、卸载和故障排查**

覆盖 `dsh`/`pnpm` 找不到、插件入口未出现、Python 引擎未找到、环境变量只对新进程生效，以及 DSH 版本升级后的重新构建/验收。

- [ ] **Step 8: 检查 README 文本**

Run:

```powershell
rg -n "OpenJS.NodeJS.22|Python.Python.3.11|@deepseek-ai/dsh@0.1.0-rc.7|SCIENTIFIC_READING_PYTHON|MINERU_API_TOKEN|FEISHU_APP_ID|dsh plugin --profile web add" README.md
```

Expected: 每个固定依赖、环境变量和安装入口至少命中一次。

### Task 2: 记录后续文献发现路线

**Files:**
- Modify: `docs/roadmap.md`

- [ ] **Step 1: 增加未实现的“文献发现与待读循环”阶段**

记录以下数据流：研究问题 → AI 查询扩展 → OpenAlex/Semantic Scholar/PubMed/arXiv/Crossref/Zotero → 标识符规范化与来源去重 → 候选收件箱 → 用户选择 → 现有下载/MinerU/reader/飞书 → 引用网络扩展。

- [ ] **Step 2: 固定产品边界**

明确 AI 相关性只影响排序，不自动下载；初版不整体嵌入 ARIS、ScholarQA、OpenScholar 或其他大型框架；Citation Gecko 和 ASReview 分别只作为引用网络与反馈排序参考。

- [ ] **Step 3: 检查路线图内容**

Run:

```powershell
rg -n "OpenAlex|Semantic Scholar|候选文献|引用网络|不自动.*下载|ARIS|Citation Gecko|ASReview" docs/roadmap.md
```

Expected: 搜索来源、候选队列、人工门禁和借鉴边界都有明确命中。

### Task 3: 验证、提交并推送

**Files:**
- Verify: `README.md`
- Verify: `docs/roadmap.md`
- Verify: `docs/superpowers/specs/2026-08-26-zero-to-running-install-design.md`
- Verify: `docs/superpowers/plans/2026-08-26-zero-to-running-install.md`

- [ ] **Step 1: 验证外部命令和仓库地址**

```powershell
npm.cmd view @deepseek-ai/dsh@0.1.0-rc.7 version
git ls-remote https://github.com/TyrionH-is-coding/Scientific-Reading-for-Newbies.git HEAD
git ls-remote https://github.com/TyrionH-is-coding/dsh-scientific-reading.git HEAD
```

Expected: npm 返回 `0.1.0-rc.7`；两个仓库均返回一个 HEAD SHA。

- [ ] **Step 2: 执行文档和泄漏检查**

```powershell
git diff --check
rg -n "(sk-|Bearer )[A-Za-z0-9_-]{12,}|FEISHU_APP_SECRET=\S+|MINERU_API_TOKEN=\S+" README.md docs/roadmap.md
```

Expected: `git diff --check` 无输出；凭据扫描无真实值命中。

- [ ] **Step 3: 确认提交范围**

```powershell
git status --short
```

Expected: 只暂存 README、路线图和本计划；不暂存 `docs/coding-backlog.md`、`docs/survey.html`。

- [ ] **Step 4: 中文提交并推送**

```powershell
git add README.md docs/roadmap.md docs/superpowers/plans/2026-08-26-zero-to-running-install.md
git commit -m "文档：补充全新机器安装与检索路线"
git push origin main
```

- [ ] **Step 5: 读回 GitHub 状态**

```powershell
git status --short --branch
git ls-remote origin refs/heads/main
git rev-parse HEAD
```

Expected: 本地 `HEAD` 与远端 `main` SHA 相同；仅保留用户原有未跟踪文件。

