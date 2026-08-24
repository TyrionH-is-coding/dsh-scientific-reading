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

### 1. 安装 Python 引擎

先在 `Scientific-Reading-for-Newbies` 仓库安装引擎：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

在 DSH 插件设置中把 `enginePython` 指向该 `.venv\Scripts\python.exe`。留空时插件会尝试从环境变量或 ScanSci 环境中探测已安装的引擎。

### 2. 构建并安装真实 Bundle

已测试宿主为 `@deepseek-ai/dsh@0.1.0-rc.7`，Node 22、Python 3.11。

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd pack --ignore-scripts
dsh plugin --profile web add .\dsh-external-dsh-scientific-reading-0.0.1.tgz --offline --ignore-scripts
dsh --profile web --dump-config
dsh --profile web --host 127.0.0.1 --port 3080
```

`client/client.js` 是唯一前端源码，`lib/client.js` 由 `npm run build:client` 生成；不要直接修改生成文件。`web` 与 `headless` 是独立 Profile。若同名插件仍由开发注入注册，注入会覆盖 tarball，持久安装前需先注销该开发目录。

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

所有自动测试应先清空真实飞书凭据，仅使用临时 data root、虚构工科题录、本地 PDF、fake MinerU/飞书；不会触发机构认证。

```powershell
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
npm.cmd run typecheck
npm.cmd run test:offline
npm.cmd run verify:profile-bundle -- --dsh-bin "<DSH bin.js 绝对路径>"
npm.cmd run verify:profile-runtime -- --dsh-bin "<DSH bin.js 绝对路径>"
npm.cmd run verify:navigation-runtime -- --dsh-bin "<DSH bin.js 绝对路径>" --engine-python "<引擎 python.exe>"
npm.cmd run verify:restart-recovery
```

真实 Profile 验收必须使用实际 tarball，开发注入不能代替 Bundle 验收。

## 旧数据与当前限制

`legacy-audit` 只读索引已有 PDF、MinerU、旧 reader 和旧九节式浅读；不移动、删除或无故重算资产。旧记录管理与旧 PDF acquisition 的运行入口已经移除；旧稳定字段只读兼容。九节浅读和旧分段精读的内部兼容符号仍可能为历史回归测试保留，但新 UI、主流程和本文档都不调用或提供其操作步骤。

当前不实现：SQLite/XLSX/飞书双向同步、飞书个人字段回写、批量删除、多个 MinerU/全文翻译任务并行、AI 自动挑选关键图、批量机构浏览器下载、在 DSH 页面内嵌整篇 reader、自动修改用户飞书表结构，以及推荐/引用网络/知识图谱。
