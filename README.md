# DSH Scientific Reading

面向 DSH 的两段式个人文献工作流：先把题录快速写入本地文献库，再按需生成可追溯的全文精读产物。

## 当前能力

### 1. 快速入库与 Abstract 浅读

- `sr_ingest` 或文献页录入框先完成 SQLite 本地事务并返回；题录补全、Abstract 翻译、XLSX 和可选飞书同步在后台继续。
- DOI、PMID、arXiv ID 优先查重；没有稳定标识时只在题名、年份和作者组合明确时合并，歧义记录不会强行去重。
- 新文献未指定文件夹时进入【待归类】；文件夹为单归属，标签可多归属。
- 浅读只显示英文 Abstract 与逐段中文对照。找不到 Abstract 时明确标记【待补摘要】，不会根据题名生成内容。
- 文献页支持服务端搜索、筛选、分页、跨页选择、批量移动/标签/精读排队/失败重试/飞书重同步，以及一次完整归类撤销；没有批量删除。

### 2. 按需全文精读与资产

- `sr_start_full_read` 为一篇文献创建或复用唯一 parent job；PDF 校验、MinerU 解析、逐块翻译、reader 发布和派生更新按持久阶段推进。
- 已校验的同一 PDF 会直接复用。自动合法获取失败时，该文献进入【需要用户处理】，用户可逐篇选择机构浏览器或挂接本地 PDF。
- 机构浏览器是显式 user gate：插件不读取或保存账号、Cookie、验证码、MFA 或浏览器 Profile。
- 全文翻译和重点识别是 AI gate；agent 按来源块提交后继续原 parent job。确定性校验、文件整理、渲染、XLSX 和飞书不依赖 agent。
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

可在插件设置的 `dataRoot` 改为其他绝对路径。SQLite 是唯一事实来源；`metadata.json`、manifest、XLSX 和飞书都是派生或资产索引，不能反向覆盖主库。

- XLSX 固定生成到 `<data-root>/library/scientific-reading.xlsx`，是只读快照。文件被 Excel 占用时记录 pending，稍后重试，不回滚入库或精读。
- 飞书直接读取 SQLite，不经过 XLSX。
- PDF、全文翻译、解析图表、飞书配置和浏览器会话必须留在仓库外，不提交到 Git。

## 安装与启动

下面是从一台只有 Codex 的全新 Windows 10/11 x64 机器开始的完整流程。首次安装通常需要 10–20 分钟，最终访问地址是 `http://127.0.0.1:3080`。

- 本地题录入库和 Abstract 浅读不要求 MinerU 或飞书凭据。
- 生成全文精读 reader 需要有效的 `MINERU_API_TOKEN`。
- 飞书同步是可选功能，需要飞书自建应用凭据和仓库外配置文件。
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

### 3. 克隆两个仓库

下面把源码放在 `%USERPROFILE%\scientific-reading-src`，文献数据仍放在独立的 `%USERPROFILE%\scientific-reading-data`：

```powershell
$src = Join-Path $env:USERPROFILE 'scientific-reading-src'
New-Item -ItemType Directory -Force -Path $src | Out-Null

git clone https://github.com/TyrionH-is-coding/Scientific-Reading-for-Newbies.git (Join-Path $src 'Scientific-Reading-for-Newbies')
git clone https://github.com/TyrionH-is-coding/dsh-scientific-reading.git (Join-Path $src 'dsh-scientific-reading')
```

如果目录已经存在，不要重复 `clone`；进入对应目录执行 `git pull --ff-only` 即可更新。

### 4. 安装 Python 引擎

引擎使用独立 Python 3.11 虚拟环境：

```powershell
$engine = Join-Path $src 'Scientific-Reading-for-Newbies'
py -3.11 -m venv (Join-Path $engine '.venv')
$enginePython = Join-Path $engine '.venv\Scripts\python.exe'

& $enginePython -m pip install --upgrade pip
& $enginePython -m pip install -e $engine
& $enginePython -m scientific_reading --help
```

最后一条命令应显示 CLI 帮助且不报导入错误。

### 5. 构建并安装插件

必须安装构建后的真实 tarball；开发目录注入不能代替正式安装验收：

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

### 6. 配置引擎路径和可选凭据

先让当前 PowerShell 立即获得引擎路径，再写入用户级环境变量供以后启动使用：

```powershell
$env:SCIENTIFIC_READING_PYTHON = $enginePython
[Environment]::SetEnvironmentVariable('SCIENTIFIC_READING_PYTHON', $enginePython, 'User')
```

需要全文精读时，在当前 PowerShell 中设置 MinerU Token，并单独持久化到用户环境。以下命令会交互读取，不把 Token 写进仓库或命令历史：

```powershell
$env:MINERU_API_TOKEN = Read-Host '请输入 MinerU API Token'
[Environment]::SetEnvironmentVariable('MINERU_API_TOKEN', $env:MINERU_API_TOKEN, 'User')
```

飞书同步是可选项；需要时用同样方式设置：

```powershell
$env:FEISHU_APP_ID = Read-Host '请输入飞书 App ID'
$env:FEISHU_APP_SECRET = Read-Host '请输入飞书 App Secret'
[Environment]::SetEnvironmentVariable('FEISHU_APP_ID', $env:FEISHU_APP_ID, 'User')
[Environment]::SetEnvironmentVariable('FEISHU_APP_SECRET', $env:FEISHU_APP_SECRET, 'User')
```

用户级环境变量只会自动出现在之后新开的进程中；上面的 `$env:` 赋值保证本次启动立即生效。插件设置中的 `enginePython` 也可以显式指向 `$enginePython`，但通常不需要。

### 7. 首次启动

在希望作为默认工作区的目录中启动 DSH：

```powershell
dsh --profile web --host 127.0.0.1 --port 3080
```

DSH 默认打开 `http://127.0.0.1:3080`。首次进入后：

1. 打开【设置 → 模型】，配置 DeepSeek 或其他兼容模型；
2. 选择或添加工作区；
3. 检查左侧是否出现【文献】入口；
4. 先录入一篇只有题名/DOI 的非敏感测试文献，确认本地主库可用；
5. 只有准备好 MinerU Token 后，再启动全文精读。

按 `Ctrl+C` 可正常停止 DSH。新增、移除或更新插件 Bundle 后必须重启 Profile。

### 8. 更新、卸载与常见问题

更新引擎和插件源码后，重新安装引擎并重建 tarball：

```powershell
git -C $engine pull --ff-only
& $enginePython -m pip install -e $engine

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
- **提示找不到 Python 引擎**：运行 `Test-Path $enginePython`，并检查 `$env:SCIENTIFIC_READING_PYTHON` 是否等于该绝对路径。
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
| `sr_feishu_resync` | 把所选或待同步记录重新排入飞书队列 |

ScanSci 相关工具只负责合法来源和逐篇用户操作：`sr_setup`、`sr_scansci_status`、`sr_scansci_fetch`、`sr_scansci_login`、`sr_scansci_set_school`。默认 `legalOnly=true`，不会启用 Sci-Hub/LibGen。

## MinerU API 配置

正式精读解析使用 MinerU 精准解析 API，不依赖本机 MinerU。把 Token 设置在启动 DSH 的宿主环境中，然后重启 DSH：

```ini
MINERU_API_TOKEN=你的MinerU_API_Token
```

插件不会保存或显示 Token，也不会把它写入命令参数、任务状态或日志。解析本地 PDF 时，文件会上传至 MinerU 官方服务器；含敏感内容的文档应先确认符合你的数据与隐私要求。缺少或失效凭证时任务会保留 PDF 和断点信息，并给出可恢复错误，不会静默改用本机 MinerU。

## 飞书配置与字段所有权

插件设置只保存仓库外 `feishu-config-v1` JSON 路径，文件包含 `app_token`、`table_id` 和 `field_map`。凭据只从启动 DSH 的宿主环境继承：

```ini
FEISHU_APP_ID=你的AppID
FEISHU_APP_SECRET=你的AppSecret
```

设置后需要重启 DSH。缺少任一凭据或有效配置时仅显示【飞书未配置】，不会联网。首次启用只记录 activation epoch，不自动回填全部历史库；历史记录需显式重新同步。

系统拥有字段包括题名、作者、期刊、年份、DOI/PMID/library key、来源链接、Abstract 英中、PDF/精读状态与路径、精读要点、更新时间和错误状态。`personal_thoughts`、`understanding_level`、`user_notes` 属于用户字段，永不进入更新 payload，也不回写 SQLite。旧配置中的稳定标识列只读兼容既有表结构，新流程统一使用本地 `library_key`。

App Secret 不写入配置、SQLite、XLSX、日志、job JSON 或 HTTP 响应。飞书失败只把该派生状态设为待同步，不改变本地入库/精读完成状态。

## 失败与恢复

- 所有后台 job 和阶段结果持久化；重复操作复用现有 job/产物。
- MinerU 与全文翻译重任务默认串行；批量请求按每组最多 100 篇分块，单篇失败不终止其他文献。
- 无效 PDF 不覆盖已校验原件；PDF SHA 改变时旧 reader 标为 stale。
- MinerU 失败保留 PDF；翻译从已发布批次继续；reader 渲染失败保留解析和翻译产物。
- XLSX/飞书失败不回滚 SQLite。关闭或重启 DSH 后可从已完成阶段恢复。

## 验证

所有自动测试应先清空真实 MinerU/飞书凭据，仅使用临时 data root、虚构工科题录、本地 PDF、fake MinerU/飞书；不会触发机构认证。

```powershell
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
Remove-Item Env:MINERU_API_TOKEN -ErrorAction SilentlyContinue
npm.cmd run typecheck
npm.cmd run test:offline
npm.cmd run verify:profile-bundle -- --dsh-bin "<DSH bin.js 绝对路径>"
npm.cmd run verify:profile-runtime -- --dsh-bin "<DSH bin.js 绝对路径>"
npm.cmd run verify:navigation-runtime -- --dsh-bin "<DSH bin.js 绝对路径>" --engine-python "<引擎 python.exe>"
npm.cmd run verify:restart-recovery
```

真实 Profile 验收必须使用实际 tarball，开发注入不能代替 Bundle 验收。

## 旧数据与当前限制

`legacy-audit` 只读索引已有 PDF、MinerU、旧 reader 和旧版结构化浅读；不移动、删除或无故重算资产。旧记录管理与旧 PDF acquisition 的运行入口已经移除；旧稳定字段只读兼容。旧浅读和旧分段精读的内部兼容符号仍可能为历史回归测试保留，但新 UI、主流程和本文档都不调用或提供其操作步骤。

当前不实现：SQLite/XLSX/飞书双向同步、飞书个人字段回写、批量删除、多个 MinerU/全文翻译任务并行、AI 自动挑选关键图、批量机构浏览器下载、在 DSH 页面内嵌整篇 reader、自动修改用户飞书表结构，以及推荐/引用网络/知识图谱。
