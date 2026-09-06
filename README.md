# DSH Scientific Reading

面向 DSH 的个人文献库：通过对话快速入库，按需获取 OA 正文或补入本地 PDF，生成可追溯的精读 HTML，并用 SQLite 与 Excel 长期维护。

**0.1.0-rc.1 已撤回为草稿，暂未公开放行。** 修复源码已通过 CI，旧 tag 与最终放行提交仍需核对，见[发布修复记录](docs/releases/v0.1.0/RELEASE_GATE.md)。持有冻结构建包的测试用户可按[候选安装指南](docs/releases/v0.1.0/INSTALL.md)核对 SHA 后测试；[实现与验收状态](docs/releases/v0.1.0/IMPLEMENTATION_GAPS.md)分别记录原生插件 A 和独立 Codex 工作台 B。源码目录和 GitHub 自动生成的 Source code 压缩包不能代替安装包。

## 首个发布版范围

当前代码已整合入库、全文任务、导航、资产、设置页和 Reader 审核入口；本轮统一验收结果见[0.1 发布候选验收摘要](docs/releases/v0.1.0/ACCEPTANCE.md)。代码已整合不等于真实 DSH、浏览器、MinerU 或 Excel 场景均已验收。

### 1. 快速入库与 Abstract 浅读

- 用户主要在对话中入库；SQLite 本地事务先返回，题录补全、Abstract 翻译和 Excel 刷新在后台继续。
- DOI、PMID、arXiv ID 优先查重；没有稳定标识时只在题名、年份和作者组合明确时合并，歧义记录不会强行去重。
- 新文献未指定文件夹时进入【待归类】；文件夹为单归属，标签可多归属。
- 浅读只显示英文 Abstract 与逐段中文对照。找不到 Abstract 时明确标记【待补摘要】，不会根据题名生成内容。
- 文献页主要负责搜索、筛选、分页、文件夹/标签和打开已有资产；缺失 PDF 的单篇或所选文献可发起下载，不把页面扩展为通用任务控制台。
- 文献条目使用两行式紧凑列表：常驻作者、年份、期刊、标签、PDF、HTML 和 Excel 定位；标题点击打开双语 Abstract 抽屉。
- 首次安装自动展示一次【设置与状态】页；保留 MinerU Key、资产位置和必要能力检测，配置完成不表示真实 API 已调用。

### 2. 按需全文精读与资产

- `sr_start_full_read` 为一篇文献创建或复用唯一 parent job；PDF 校验、MinerU 解析、逐块翻译、reader 发布和派生更新按持久阶段推进。
- 已校验的同一 PDF 会直接复用。自动 OA 获取失败时，单篇任务进入【需要用户处理】；批量任务继续完成其他项目，待补本地 PDF。
- A 不提供机构或浏览器自动获取入口；可补入用户已合法取得的本地 PDF。
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

阅读路由优先打开 `reading/reader.html`，兼容回退同一 generation 的 `output/reader_full.html`。旧论文根级 reader 只有在引擎返回 `legacy_audited=true` 且 SHA 匹配时才可访问；`legacy_audited` 是路由状态字段，不是用户需要执行的 CLI 命令。PDF、reader、解析和导出 manifest 会校验 generation、路径边界与 SHA；不会按修改时间猜测活动产物。

【整理文章图表】导出 MinerU 明确标记的全部正文 Figure/Table，不判断“关键图”，也不使用 AI 猜测图注、bbox 或表格单元格。原始 MinerU 资产继续保留，导出包只是派生副本。

## 数据所有权

默认数据根位于仓库外：

```text
%USERPROFILE%\scientific-reading-data
```

高级部署可在 DSH 插件配置中指定 `dataRoot` 绝对路径；设置与状态页只读显示当前位置。已有库换位置应先做备份并恢复到新目录。SQLite 是系统事实来源；`metadata.json`、manifest 和 Excel 是派生视图或资产索引。

- Excel 固定生成到 `<data-root>/library/scientific-reading.xlsx`。当前代码只允许个人思考、个人理解程度和用户笔记从 Excel 白名单回写；系统字段不得覆盖 SQLite。
- 文件被 Excel 占用时记录 pending，稍后重试，不回滚入库、下载或精读。
- PDF、全文翻译、解析图表、Excel 和浏览器会话必须留在仓库外，不提交到 Git。

## 安装与启动

下面是 Windows 10/11 x64 的安装流程；耗时取决于本机依赖、DSH 和可选 MinerU 环境。默认访问地址是 `http://127.0.0.1:3080`。

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
py -3.11 -m venv engine\.venv
$env:PYTHON = (Resolve-Path 'engine\.venv\Scripts\python.exe').Path
$env:SCIENTIFIC_READING_PYTHON = $env:PYTHON
& $env:PYTHON -m pip install -e 'engine[dev]'
npm.cmd run build:ci
$pack = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$tarball = Join-Path $plugin $pack[0].filename

dsh plugin --profile web add $tarball --ignore-scripts
dsh --profile web --dump-config | Select-String '@dsh-external/dsh-scientific-reading'
```

最后一条命令应至少命中一次插件包名。`web` 与 `headless` 是独立 Profile，本插件默认安装到 `web`。

### 5. 配置可选凭据

普通用户在【设置与状态】页粘贴 MinerU API Key。Key 使用当前 Windows 用户作用域的 DPAPI 加密，不进入普通插件配置、SQLite、Excel、日志或任务状态。

环境变量仅作为现有受控开发/自动化流程的回退方式；不要把 MinerU Token 写入用户级永久环境变量。普通用户只在【设置与状态】页保存、替换或删除 Key，由 Windows DPAPI 保护。首次运行 `sr_setup` 时，插件会把随 tarball 提供的 wheel 安装到 `<dataRoot>\.venv`；`enginePython` 只保留为开发调试覆盖项，普通安装不需要填写。使用 `sr_setup(force=true)` 会按随包的 `scripts/oa-requirements.txt` 校验 SHA 并安装固定 OA 依赖到同一托管虚拟环境，不更改用户级 ScanSci。

### 6. 首次启动

在希望作为默认工作区的目录中启动 DSH：

```powershell
dsh --profile web --host 127.0.0.1 --port 3080
```

DSH 默认打开 `http://127.0.0.1:3080`。当前代码通过 onboarding 状态控制【设置与状态】页的一次性展示；页面初次展示不联网，用户点击【重新检测】后只检查 OA 依赖、本机 MinerU 和 API Key 配置；真实 API 结果以论文任务为准。真实宿主首启行为仍需按统一验收记录确认。首次进入后：

1. 打开【设置 → 模型】，配置 DeepSeek 或其他兼容模型；
2. 选择或添加工作区；
3. 新建会话并在对话栏模式菜单选择【文献模式】；只有该模式才显示【文献】与【设置与状态】，并启用文献工具；
4. 标准 / PTC / 极简 / 创造等其它模式不显示这两栏，模型也看不到 `sr_*` 工具；
5. 先录入一篇只有题名/DOI 的非敏感测试文献，确认本地主库可用；
6. 检测本机 MinerU 能力或保存 MinerU API Key 后，再用一篇文献实际验证全文精读。

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

普通卸载不会删除已安装的【文献模式】预设。确认 `DSH_HOME` 指向当前 Profile 后可单独删除：

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.dsh\.agent-presets\scientific-reading"
```

常见问题：

- **找不到 `git`、`node`、`dsh` 或 `pnpm`**：关闭所有旧 PowerShell 窗口，重新打开后再检查版本。
- **模式菜单没有【文献模式】**：安装或更新 Bundle 后必须彻底退出并重启 DSH；新会话才能选到该预设。
- **标准 / PTC / 极简 / 创造模式下模型没有 `sr_*` 工具**：这是预期行为。文献工具只在【文献模式】启用。
- **插件没有出现在界面**：确认 `--dump-config` 能找到包名，并在安装 Bundle 后彻底重启 DSH。
- **提示找不到 Python 引擎**：先运行 `sr_setup`；再检查 `<dataRoot>\.venv\Scripts\python.exe` 是否存在。开发者才需要在插件设置中填写 `enginePython`。
- **受控自动化环境变量没有生效**：环境变量只在启动时读取；重启对应的 DSH/自动化进程后再检查。普通用户请使用设置页的 DPAPI 密钥，不要把 Token 写入永久用户环境变量。
- **升级 DSH 后启动失败**：先退回已验证的 `npm.cmd install --global @deepseek-ai/dsh@0.1.0-rc.7`，再重新构建和安装插件。
- **端口 3080 已占用**：先关闭旧 DSH；不要同时运行两个写同一 `web` Profile 和数据根的实例。

`client/client.js` 是唯一前端源码，`lib/client.js` 由 `npm run build:client` 生成；不要直接修改生成文件。若同名插件仍由开发注入注册，注入会覆盖 tarball，持久安装前需先注销该开发目录。

## 开发者：快速审核 Reader

Reader 样式或渲染规则修改后，不需要重跑 PDF 下载、MinerU API 或全文翻译。开发审核命令直接读取三个离线工科样例，或本机已经完成的 generation，在临时目录生成固定 baseline 和可反复刷新的 candidate：

```powershell
# 第一次建立审核会话，或主动重置“修改前”基线
npm.cmd run reader:review -- --case formula-outline --new-session

# 也可以审核本机已经完成的论文；只读来源 generation
npm.cmd run reader:review -- --paper-id doi_10.48550_arxiv.1706.03762 --data-root "<data-root>" --new-session

# 修改代码后只刷新 candidate，baseline 保持不变
npm.cmd run reader:review
```

三条命令都使用固定地址 `http://127.0.0.1:8895/review`。首次运行启动本地审核服务，后续运行复用同一服务和 PID；不自动打开外部浏览器。用 Codex 应用内浏览器打开该地址，可切换修改前/修改后和桌面/平板/手机宽度，并直接用 Browser Comment 标出需要继续调整的位置。完成后可用 `npm.cmd run reader:review -- --stop` 结束该审核服务。

baseline 是新审核会话建立时的正式旧 HTML，只写一次；candidate 是当前代码的预览结果，可反复覆盖。预览使用正式 Reader renderer 的只读入口，不发布、不改写来源 generation。快速循环显式清空 MinerU、飞书和机构认证变量，因此不会上传 PDF、调用 LLM、消耗 MinerU 配额或触发登录。

用户认可视觉结果后，依次运行分层验收：

```powershell
# 第一层：三个 fixture、Reader 定向测试和 HTML 静态结构预检
npm.cmd run reader:acceptance

# 第二层：真实 tarball + 临时 DSH Profile + 正式 HTTP Reader 路由
npm.cmd run acceptance:dsh
```

第一层通常只需数秒，结果会写回审核页；桌面、平板、手机的真实浏览器 QA 仍显示为 `pending`，静态检查不会冒充视觉验收。第二层只复用本机已有 DSH，固定临时 Profile 名 `reader-review-acceptance`，使用随机 loopback 端口，不触碰 3080 或持久 `web` Profile；找不到本机运行时时明确返回 `dsh_runtime_missing`，不会联网安装。成功现场自动清理，失败现场路径会在 JSON 的 `evidence_root` 中返回，确认问题后再删除。

默认审核目录是 `%TEMP%\dsh-scientific-reading-review`；`--review-root <绝对路径>` 可用于隔离并行实验。三个 fixture、审核页、审核脚本和验收测试只属于源码开发工具，受打包测试保护，不进入用户安装的 `.tgz`。真实 DSH 启动验收也不属于普通 `npm test`，必须显式执行上面的第二层命令。

## 常用入口

普通用户主要通过【文献】页和 DSH 对话操作。可供 agent 调用的主流程工具包括：

| 工具 | 用途 |
|---|---|
| `sr_ingest` | 快速创建或复用本地记录，随后排入轻量派生任务 |
| `sr_library_list` | 搜索、筛选和分页读取文献库 |
| `sr_library_backup` / `sr_library_restore` | 整库备份与新目录恢复，保留用户记录和历史阅读资产 |
| `sr_library_search_rebuild` | 从 SQLite 重建元数据、摘要、已确认结论的派生索引 |
| `sr_evidence_locate` | 取得绑定 PDF 与原文集合版本的原文块定位 |
| `sr_candidate_rebuild` | 用已校验缓存准备重建计划，列出可复用译文和待完成内容 |
| `sr_folder_manage` | 创建、列出或重命名文件夹 |
| `sr_classification_apply` / `sr_classification_undo` | 应用或撤销一次归类提案 |
| `sr_start_full_read` | 创建或复用精读 parent job |
| `sr_continue_full_read` | 提交当前 AI/user gate 的输入并继续 |
| `sr_attach_pdf` | 校验并挂接本地 PDF 后继续精读 |
| `sr_export_assets` | 生成 Figure/Table 导出包 |
| `sr_job_status` | 查询持久后台任务 |

OA 工具为 `sr_setup`、`sr_scansci_status`、`sr_scansci_fetch`。仅调用 arXiv、Europe PMC 明确标注的 OA PDF；用户显式配置 `UNPAYWALL_EMAIL` 时可启用 Unpaywall。无可用 OA 时等待本地文件；旧 `legalOnly=false` 或学校参数不会放宽来源。

## MinerU 解析后端

首个发布版提供【自动】【仅本机】【仅 API】三种策略，默认自动选择经过验证的本机 MinerU，否则使用经过验证的 API。插件只检测并调用用户已有的本机环境，不自动安装 MinerU、CUDA 或模型。本机和 API 输出进入同一规范化、资产校验和 generation 发布流程。

本机探测会按顺序查看 `MINERU_EXECUTABLE`、`<dataRoot>/.mineru-venv/`（Windows 为 `Scripts/mineru.exe`，Unix 为 `bin/mineru`），再回退到 PATH 上的 `mineru`。插件不自动安装 MinerU。启动本机 CLI 时固定注入 `MINERU_FORMULA_CH_SUPPORT=true`，避免官方模型包漏掉 unimernet 公式权重导致首次解析失败。

如果使用环境变量回退，把 Token 设置在启动 DSH 的宿主环境中，然后重启 DSH：

```ini
MINERU_API_TOKEN=你的MinerU_API_Token
```

设置页保存的 Key 使用 DPAPI 加密且只允许替换或删除，页面不会再次显示内容。Key 不进入命令参数、任务状态或日志。API 解析会上传 PDF 至 MinerU 官方服务；含敏感内容的文档应先确认符合数据与隐私要求。provider 在任务创建时固定，运行中失败不会静默切换；任务保留 PDF 和断点，等待用户决定是否换后端重试。

## Excel 字段所有权

系统字段包括题名、作者、主要研究单位、期刊、年份、DOI/PMID/arXiv ID、来源链接、Abstract 英中、PDF/精读状态与路径、更新时间和错误状态。它们从 SQLite 生成，Excel 中的修改不得覆盖主库。

首个发布版只允许 `personal_thoughts`、`understanding_level` 和 `user_notes` 三类用户字段从 Excel 回写。每行使用稳定 `paper_id` 关联；身份缺失、重复或被修改时停止该行回写并报告。文件夹和标签继续通过文献页或对话维护。

飞书退出当前产品路线；现行运行面不提供飞书入口、配置或同步能力，数据库遗留列和历史文档仅作兼容与追溯。

## 失败与恢复

整库备份通过 `sr_library_backup` 指定库外的新绝对路径；它会阻止新写入并等待活动写入结束，超时则返回可重试的失败。`sr_library_restore` 只接受新建或空的目标目录，先校验清单、版本、路径、数据库和 SHA，再发布恢复库。恢复不会切换当前 `dataRoot`；检查恢复库后，可在设置中切换。运行环境和凭据不随包恢复，未完成任务需要显式继续。

文献页搜索覆盖元数据、已有中英文摘要和已确认结论，结果显示内容类型。论文结论的定位同时绑定 PDF 和原文集合的 SHA；原文重新解析后旧定位会失效，点击时再次校验。旧自由文本定位保持“旧版未验证”，个人判断、推断和问题不会显示为论文事实。定位有效只证明位置与引文对应。

旧 Reader 与当前原文块不匹配时，可用 `sr_candidate_rebuild` 在库外生成待完成计划。只有 PDF、块身份和完整原文均一致的译文才会复用；新增内容与参考文献需完成各自门禁，旧审核结论不复用。该工具不会自动调用模型、生成完整 Reader 或替换旧资产。

- 所有后台 job 和阶段结果持久化；重复操作复用现有 job/产物。
- MinerU 与全文翻译重任务默认串行；批量请求按每组最多 100 篇分块，单篇失败不终止其他文献。
- 无效 PDF 不覆盖已校验原件；PDF SHA 改变时旧 reader 标为 stale。
- MinerU 失败保留 PDF；翻译从已发布批次继续；reader 渲染失败保留解析和翻译产物。
- Excel 刷新或回写失败不回滚 SQLite。关闭或重启 DSH 后可从已完成阶段恢复。

## 验证

所有自动测试应先清空真实 MinerU 凭据，仅使用临时 data root、虚构工科题录、本地 PDF 和 fake MinerU；不会触发机构认证。代码已整合，统一验收结果见[0.1 发布候选验收摘要](docs/releases/v0.1.0/ACCEPTANCE.md)。

```powershell
Remove-Item Env:MINERU_API_TOKEN -ErrorAction SilentlyContinue
$env:PYTHON = (Resolve-Path 'engine\.venv\Scripts\python.exe').Path
$env:SCIENTIFIC_READING_PYTHON = $env:PYTHON
& $env:PYTHON -m pip install -e 'engine[dev]'
npm.cmd run typecheck
npm.cmd test
npm.cmd run verify:restart-recovery
```

开发者先在仓库内创建专用 `engine/.venv`，再从仓库根目录执行上述命令；若脚本需要显式解释器，使用 `PYTHON` 或 `SCIENTIFIC_READING_PYTHON` 指向该环境。`npm test` 会构建内置 wheel、运行 MinerU provider/引擎测试、插件/路由测试，并把 wheel 安装到临时虚拟环境执行 CLI 冒烟。真实 Profile 验收仍必须使用实际 tarball，开发注入不能代替 Bundle 验收。

## 旧数据与当前限制

既有 PDF、MinerU 结果与 reader 保留在数据根中；升级不会移动、删除或无故重算用户资产。首个发布版只围绕本地库、合法 PDF 下载、本机/API MinerU、精读 HTML、资产导出和 Excel 维护交付。

首个发布版不实现：任意字段双向同步、批量删除、多个 MinerU/全文翻译任务并行、AI 自动挑选关键图、在 DSH 页面内嵌整篇 reader、文献推荐、引用网络、知识图谱或逐篇 JSON 证据卡。上游发现/推荐和下游证据卡留到下一版本。
