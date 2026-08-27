# DSH Scientific Reading

面向 DSH 的个人文献库：通过对话快速入库，按需单篇或批量取得 PDF，生成可追溯的精读 HTML，并用 SQLite 与美观 Excel 长期维护。

## 首个发布版范围

当前仓库已有入库、全文任务、导航和资产基线；以下是首个正式发布版的收敛目标。尚未完成的调整以“发布目标”标记，不能视为当前已经交付。

### 1. 快速入库与 Abstract 浅读

- 用户主要在对话中入库；SQLite 本地事务先返回，题录补全、Abstract 翻译和 Excel 刷新在后台继续。
- DOI、PMID、arXiv ID 优先查重；没有稳定标识时只在题名、年份和作者组合明确时合并，歧义记录不会强行去重。
- 新文献未指定文件夹时进入【待归类】；文件夹为单归属，标签可多归属。
- 浅读只显示英文 Abstract 与逐段中文对照。找不到 Abstract 时明确标记【待补摘要】，不会根据题名生成内容。
- 文献页主要负责搜索、筛选、分页、文件夹/标签和打开已有资产；发布目标允许为缺失 PDF 的单篇或所选文献发起下载，但不把页面扩展为通用任务控制台。
- 发布目标使用两行式紧凑列表：常驻作者、年份、期刊、标签、PDF、HTML 和 Excel 定位；标题点击打开双语 Abstract 抽屉。
- 首次安装自动展示一次【设置与状态】页；机构、MinerU 和浏览器的真实验证只在用户点击【重新检测】后执行。

### 2. 按需全文精读与资产

- `sr_start_full_read` 为一篇文献创建或复用唯一 parent job；PDF 校验、MinerU 解析、逐块翻译、reader 发布和派生更新按持久阶段推进。
- 已校验的同一 PDF 会直接复用。自动合法获取失败时，单篇任务进入【需要用户处理】；批量任务先完成其他项目，再集中处理机构浏览器、可选增强包或本地 PDF。
- 机构浏览器是显式 user gate：插件不读取或保存账号、Cookie、验证码、MFA 或浏览器 Profile。
- 全文翻译和重点识别是 AI gate；agent 按来源块提交后继续原 parent job。确定性校验、文件整理、渲染和 Excel 刷新不依赖 agent。
- Windows 上由插件启动的 Python/worker 子进程使用隐藏窗口方式，不应周期性弹出终端。

正式 generation 路径：

```text
<data-root>/papers/<paper_id>/generations/<source_sha16>/
├─ source.pdf
├─ reading/
│  ├─ reader.html
│  └─ reader-manifest.json
└─ exports/
   ├─ figures/Fig_*.png
   ├─ tables/Table_*.png
   ├─ tables/Table_*.csv       # 仅可靠结构化源存在时
   ├─ captions.md
   └─ manifest.json
```

阅读路由优先打开 `reading/reader.html`，兼容回退同一 generation 的 `output/reader_full.html`。旧论文根级 reader 只有经过 `legacy-audit` 建立只读索引且 SHA 匹配时才可访问。PDF、reader、解析和导出 manifest 会校验 generation、路径边界与 SHA；不会按修改时间猜测活动产物。

【整理文章图表】导出 MinerU 明确标记的全部正文 Figure/Table，不判断“关键图”，也不使用 AI 猜测图注、bbox 或表格单元格。原始 MinerU 资产继续保留，导出包只是派生副本。

## 数据所有权

默认数据根位于仓库外：

```text
%USERPROFILE%\scientific-reading-data
```

可在插件设置的 `dataRoot` 改为其他绝对路径。SQLite 是系统事实来源；`metadata.json`、manifest 和 Excel 是派生视图或资产索引。

- Excel 固定生成到 `<data-root>/library/scientific-reading.xlsx`。发布目标只允许个人思考、个人理解程度和用户笔记从 Excel 白名单回写；系统字段不得覆盖 SQLite。
- 文件被 Excel 占用时记录 pending，稍后重试，不回滚入库、下载或精读。
- PDF、全文翻译、解析图表、Excel 和浏览器会话必须留在仓库外，不提交到 Git。

## 安装与启动

下面是从一台只有 Codex 的全新 Windows 10/11 x64 机器开始的完整流程。首次安装通常需要 10–20 分钟，最终访问地址是 `http://127.0.0.1:3080`。

- 本地题录入库和 Abstract 浅读不要求 MinerU 凭据。
- 生成全文精读 reader 需要经过验证的本机 MinerU，或有效的 MinerU API Key。
- DSH 模型凭据在首次启动后的【设置 → 模型】中配置，不要写进仓库。

### 1. 安装基础依赖

在 PowerShell 中执行：

```powershell
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
winget install --id OpenJS.NodeJS.22 -e --accept-package-agreements --accept-source-agreements
winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
```

安装完成后关闭并重新打开 PowerShell，检查版本：

```powershell
git --version
node --version       # 应为 v22.x
npm.cmd --version
py -3.11 --version  # 应为 Python 3.11.x
```

### 2. 安装 DSH

当前插件实机验证的宿主是 `@deepseek-ai/dsh@0.1.0-rc.7`。首次安装固定这个版本，不要直接换成最新 RC：

```powershell
npm.cmd install --global pnpm@11 @deepseek-ai/dsh@0.1.0-rc.7
dsh --version
```

预期版本为 `0.1.0-rc.7`。以后升级 DSH 时，应重新构建插件并运行本文末尾的 Bundle/Profile 验收。

### 3. 克隆单一仓库

下面把源码放在 `%USERPROFILE%\scientific-reading-src`，文献数据仍放在独立的 `%USERPROFILE%\scientific-reading-data`：

```powershell
$src = Join-Path $env:USERPROFILE 'scientific-reading-src'
New-Item -ItemType Directory -Force -Path $src | Out-Null

git clone https://github.com/TyrionH-is-coding/dsh-scientific-reading.git (Join-Path $src 'dsh-scientific-reading')
```

如果目录已经存在，不要重复 `clone`；进入对应目录执行 `git pull --ff-only` 即可更新。

### 4. 构建并安装插件

仓库内的 `engine/` 会先构建成 Python wheel，再随插件 tarball 一起打包。无需克隆或配置第二个引擎仓库：

```powershell
$plugin = Join-Path $src 'dsh-scientific-reading'
Set-Location $plugin

npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
$pack = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$tarball = Join-Path $plugin $pack[0].filename

dsh plugin --profile web add $tarball --ignore-scripts
dsh --profile web --dump-config | Select-String '@dsh-external/dsh-scientific-reading'
```

最后一条命令应至少命中一次插件包名。`web` 与 `headless` 是独立 Profile，本插件默认安装到 `web`。

### 5. 配置可选凭据

发布完成后，普通用户在【设置与状态】页粘贴 MinerU API Key。Key 使用当前 Windows 用户作用域的 DPAPI 加密，不进入普通插件配置、SQLite、Excel、日志或任务状态。

环境变量继续作为开发和自动化环境的回退方式。以下命令会交互读取，不把 Token 写进仓库或命令历史：

```powershell
$env:MINERU_API_TOKEN = Read-Host '请输入 MinerU API Token'
[Environment]::SetEnvironmentVariable('MINERU_API_TOKEN', $env:MINERU_API_TOKEN, 'User')
```

安全存储的 Key 优先于环境变量。用户级环境变量只会自动出现在之后新开的进程中；上面的 `$env:` 赋值保证本次启动立即生效。首次运行 `sr_setup` 时，插件会把随 tarball 提供的 wheel 安装到 `<dataRoot>\.venv`；`enginePython` 只保留为开发调试覆盖项，普通安装不需要填写。

### 6. 首次启动

在希望作为默认工作区的目录中启动 DSH：

```powershell
dsh --profile web --host 127.0.0.1 --port 3080
```

DSH 默认打开 `http://127.0.0.1:3080`。插件首次安装后自动进入一次【设置与状态】页；页面初次展示不联网，用户点击【重新检测】后才验证机构会话、本机 MinerU 或 API。之后即使环境尚未配置，也不会每次启动强制跳回。首次进入后：

1. 打开【设置 → 模型】，配置 DeepSeek 或其他兼容模型；
2. 选择或添加工作区；
3. 检查左侧是否出现【文献】与【设置与状态】入口；
4. 先录入一篇只有题名/DOI 的非敏感测试文献，确认本地主库可用；
5. 验证本机 MinerU 或保存并验证 MinerU API Key 后，再启动全文精读。

按 `Ctrl+C` 可正常停止 DSH。新增、移除或更新插件 Bundle 后必须重启 Profile。

### 7. 更新、卸载与常见问题

更新插件源码后，重新构建并安装 tarball。内置引擎会随包同步更新：

```powershell
git -C $plugin pull --ff-only
Set-Location $plugin
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
$pack = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$tarball = Join-Path $plugin $pack[0].filename
dsh plugin --profile web add $tarball --ignore-scripts
```

卸载插件：

```powershell
dsh plugin --profile web remove @dsh-external/dsh-scientific-reading
```

常见问题：

- **找不到 `git`、`node`、`dsh` 或 `pnpm`**：关闭所有旧 PowerShell 窗口，重新打开后再检查版本。
- **插件没有出现在界面**：确认 `--dump-config` 能找到包名，并在安装 Bundle 后彻底重启 DSH。
- **提示找不到 Python 引擎**：先运行 `sr_setup`；再检查 `<dataRoot>\.venv\Scripts\python.exe` 是否存在。开发者才需要在插件设置中填写 `enginePython`。
- **环境变量没有生效**：`[Environment]::SetEnvironmentVariable(..., 'User')` 不会反向修改已经运行的 DSH；重启 DSH，必要时重新打开 PowerShell。
- **升级 DSH 后启动失败**：先退回已验证的 `npm.cmd install --global @deepseek-ai/dsh@0.1.0-rc.7`，再重新构建和安装插件。
- **端口 3080 已占用**：先关闭旧 DSH；不要同时运行两个写同一 `web` Profile 和数据根的实例。

`client/client.js` 是唯一前端源码，`lib/client.js` 由 `npm run build:client` 生成；不要直接修改生成文件。若同名插件仍由开发注入注册，注入会覆盖 tarball，持久安装前需先注销该开发目录。

## 常用入口

普通用户主要通过【文献】页和 DSH 对话操作。可供 agent 调用的主流程工具包括：

| 工具 | 用途 |
|---|---|
| `sr_ingest` | 快速创建或复用本地记录，随后排入轻量派生任务 |
| `sr_library_list` | 搜索、筛选和分页读取文献库 |
| `sr_folder_manage` | 创建、列出或重命名文件夹 |
| `sr_classification_apply` / `sr_classification_undo` | 应用或撤销一次归类提案 |
| `sr_start_full_read` | 创建或复用精读 parent job |
| `sr_continue_full_read` | 提交当前 AI/user gate 的输入并继续 |
| `sr_attach_pdf` | 校验并挂接本地 PDF 后继续精读 |
| `sr_export_assets` | 生成 Figure/Table 导出包 |
| `sr_job_status` | 查询持久后台任务 |

ScanSci 相关工具只负责合法来源下载和需要用户参与的机构认证：`sr_setup`、`sr_scansci_status`、`sr_scansci_fetch`、`sr_scansci_login`、`sr_scansci_set_school`。默认 `legalOnly=true`，不会启用 Sci-Hub/LibGen；批量编排由文献工作流统一负责。

## MinerU 解析后端

首个发布版提供【自动】【仅本机】【仅 API】三种策略，默认自动选择经过验证的本机 MinerU，否则使用经过验证的 API。插件只检测并调用用户已有的本机环境，不自动安装 MinerU、CUDA 或模型。本机和 API 输出进入同一规范化、资产校验和 generation 发布流程。

如果使用环境变量回退，把 Token 设置在启动 DSH 的宿主环境中，然后重启 DSH：

```ini
MINERU_API_TOKEN=你的MinerU_API_Token
```

设置页保存的 Key 使用 DPAPI 加密且只允许替换或删除，页面不会再次显示内容。Key 不进入命令参数、任务状态或日志。API 解析会上传 PDF 至 MinerU 官方服务；含敏感内容的文档应先确认符合数据与隐私要求。provider 在任务创建时固定，运行中失败不会静默切换；任务保留 PDF 和断点，等待用户决定是否换后端重试。

## Excel 字段所有权

系统字段包括题名、作者、主要研究单位、期刊、年份、DOI/PMID/arXiv ID、来源链接、Abstract 英中、PDF/精读状态与路径、更新时间和错误状态。它们从 SQLite 生成，Excel 中的修改不得覆盖主库。

首个发布版只允许 `personal_thoughts`、`understanding_level` 和 `user_notes` 三类用户字段从 Excel 回写。每行使用稳定 `paper_id` 关联；身份缺失、重复或被修改时停止该行回写并报告。文件夹和标签继续通过文献页或对话维护。

飞书退出产品路线。仓库中的现存飞书实现属于迁移期遗留代码，后续会连同入口、配置和测试依赖一起删除，不属于首个发布版能力。

## 失败与恢复

- 所有后台 job 和阶段结果持久化；重复操作复用现有 job/产物。
- MinerU 与全文翻译重任务默认串行；批量请求按每组最多 100 篇分块，单篇失败不终止其他文献。
- 无效 PDF 不覆盖已校验原件；PDF SHA 改变时旧 reader 标为 stale。
- MinerU 失败保留 PDF；翻译从已发布批次继续；reader 渲染失败保留解析和翻译产物。
- Excel 刷新或回写失败不回滚 SQLite。关闭或重启 DSH 后可从已完成阶段恢复。

## 验证

所有自动测试应先清空真实 MinerU 凭据，仅使用临时 data root、虚构工科题录、本地 PDF 和 fake MinerU；不会触发机构认证。

```powershell
Remove-Item Env:MINERU_API_TOKEN -ErrorAction SilentlyContinue
npm.cmd run typecheck
npm.cmd test
npm.cmd run verify:restart-recovery
```

`npm test` 会构建内置 wheel、运行 MinerU provider/引擎测试、插件/路由测试，并把 wheel 安装到临时虚拟环境执行 CLI 冒烟。真实 Profile 验收仍必须使用实际 tarball，开发注入不能代替 Bundle 验收。

## 旧数据与当前限制

既有 PDF、MinerU 结果与 reader 保留在数据根中；升级不会移动、删除或无故重算用户资产。首个发布版只围绕本地库、合法 PDF 下载、本机/API MinerU、精读 HTML、资产导出和 Excel 维护交付。

首个发布版不实现：任意字段双向同步、批量删除、多个 MinerU/全文翻译任务并行、AI 自动挑选关键图、在 DSH 页面内嵌整篇 reader、文献推荐、引用网络、知识图谱或逐篇 JSON 证据卡。上游发现/推荐和下游证据卡留到下一版本。
