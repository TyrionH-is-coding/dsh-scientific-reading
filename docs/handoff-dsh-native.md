# DSH Scientific Reading 历史开发交接

> 本文保留早期工程快照。当前安装与验证请使用 [Deep Literature for DSH 开发指南](development.md)；原生插件现行下载范围是 OA 与本地 PDF，本文旧机构通道、Chrome 设置及 Windows 专用说明不作为当前产品合同。发布状态见[核对记录](release-readiness.md)。

这份文档面向下一位直接接手实现和验收的 agent。当前代码已整合设置页、文献模式、MinerU 工程化改动和 Reader 审核入口；代码已整合不等于真实 DSH、浏览器、MinerU 或 Excel 场景均已验收。统一验收结果见[可靠性整合验收记录](superpowers/executions/2026-09-05-reliability-integration.md)。

## 1. 一句话产品定义

这是一个 DSH 原生个人文献库插件。用户主要在对话中快速入库，系统用 SQLite 建档并在后台补充
Abstract；随后按需取得 PDF，经 MinerU、翻译和 reader builder 生成双语精读 HTML；【文献】页负责
导航、归类和打开资产，Excel 负责长期表格化查看及少数用户字段回写。

V1 只做好这条主链路：

```text
对话入库 → SQLite/Abstract → 单篇或批量 PDF → MinerU/翻译/HTML
        → 文献页导航与归类 → Excel 长期维护
```

以下内容已明确退出 V1：飞书、Zotero、文献推荐、引用网络、知识图谱、自动综述、逐篇 JSON 证据卡、
AI 自动挑选关键图、批量删除和多个全文重任务并行。文献发现/推荐与 JSON 证据卡属于 V2，不能顺手塞回 V1。

## 2. 当前工作状态

| 项目 | 当前状态 |
|---|---|
| 代码状态 | 设置页、文献模式、MinerU 工程化改动和 Reader 审核入口已整合到当前工作树 |
| Git 状态 | 当前工作树仍可能包含未提交改动；不要据此宣称已完成 Git merge、提交或推送 |
| 验收状态 | 统一验收结果和剩余宿主门禁见可靠性整合验收记录 |

不要 reset、checkout、stash 或清理其他 agent 的改动；提交前先按当前工作树重新核对改动归属和重叠路径。

## 3. 已整合的代码能力

### 3.1 单仓库运行与打包

- TypeScript DSH 插件与 Python `engine/` 已在同一仓库。
- `npm run build:ci` 会先把 `engine/` 构建为 wheel，再生成 TypeScript 和客户端产物。
- wheel 随 npm tarball 发布；普通用户不需要再克隆第二个引擎仓库。
- `client/client.js` 是前端源码，`lib/client.js` 是生成产物；只改前者，再运行 `npm run build:client`。

### 3.2 本地文献库

- SQLite 是系统事实来源；数据根默认是 `%USERPROFILE%\scientific-reading-data`，与仓库分离。
- 支持 DOI、PMID、arXiv ID、题名/作者入库，稳定标识优先去重。
- 入库本地事务先返回；题录补全、Abstract 英中对照和 Excel 刷新走后台任务。
- 支持全部文献、待归类、文件夹、标签、搜索、筛选、分页、跨页选择和批量归类/撤销。

### 3.3 文献页与设置页

- DSH 有同级【文献】和【设置与状态】页面。
- 文献列表已收敛为标题、作者、年份、期刊、标签、PDF、HTML 和 Excel 定位；标题打开 Abstract 抽屉。
- 缺 PDF 时可单篇或批量请求下载；复杂精读和异常处理仍应留在对话中。
- 设置页可读取状态快照、手动重新检测并保存/删除 MinerU API Key。
- API Key 保存/删除后会立即只重测 `mineru_api`，不会继续展示旧快照。
- PDF 列表和详情链接使用 `target="_blank"` 与 `rel="noopener"`；HTML 入口仍在当前标签页打开。

### 3.4 MinerU、精读与资产

- 已有自动、本机和 API provider 策略；本机/API 进入同一规范化、校验、manifest 和 generation 链。
- API Key 使用当前 Windows 用户作用域 DPAPI 存储；环境变量仅作开发/自动化回退。
- parent job 串联 PDF、校验、MinerU、全文翻译、reader 发布和派生更新，支持幂等与重启恢复。
- PDF 变化会使旧 reader stale；无效 PDF 不覆盖已校验原件。
- reader 具备双语正文、目录、重点、Figure/Table 和来源定位。
- 【整理文章图表】导出全部明确标记的 Figure/Table，不判断“关键图”；CSV 只来自可靠结构化源。

### 3.5 PDF 与 Excel

- 已有合法来源下载、PDF 校验、本地 PDF 挂接、单篇/批量任务与分层批次状态。
- 当前批量下载顺序是 OA/HTTP → 已配置的机构通道尝试一次 → 提示用户处理或手动挂接；CloakBrowser 不在当前自动批次链路中。
- SQLite 继续管理系统字段；Excel 仅允许个人思考、理解程度、用户笔记等白名单字段回写。
- Excel 被占用时应记录 pending，不回滚入库、下载或精读。

## 4. 当前代码与验收边界

当前代码已包含以下能力；它们仍需按验收记录区分离线合同与真实宿主门禁：

1. 后台 worker 从 DPAPI/环境变量解析 MinerU Token，并只注入 worker 的子进程环境，不修改宿主
   `os.environ`，也不把 Token 写进 argv、request 或 launch JSON。
2. 本机 MinerU 探测顺序增加 `MINERU_EXECUTABLE`、`<dataRoot>/.mineru-venv/`，最后再查 PATH；运行时注入
   `MINERU_FORMULA_CH_SUPPORT=true`。
3. 本机 MinerU 版本探测超时被视为“可执行但版本未知”，并把探测超时放宽到 60 秒。
4. 兼容旧 parse report 缺少 `provider_version`、旧资产含 `selected_for_quick_read` 的情况，同时仍保留
   provider 和原始结果一致性校验。
5. 解析 provider/认证类错误统一转为可恢复 agent gate，而不是直接终止 parent job。
6. 全文翻译发现旧/stale translation 时删除该派生文件并重新请求当前批次。
7. reader 从 MinerU 原始 `*_content_list.json` 补回 equation，并压缩 MinerU 拆散的 LaTeX 字符间空格后转
   MathML；图表和公式按 `source_index` 插入正文。
8. CLI stdout/stderr 显式使用 UTF-8，减少 Windows 中文输出乱码。

本轮统一测试、真实 tarball/Profile、浏览器、MinerU 和 Excel 验收状态只记录在可靠性整合验收记录中；不要从旧交接快照推断当前结果。

## 5. 后续发布验收

按优先级建议如下：

1. **已完成的工程门禁**：本轮已完成 `npm test`、完整重启恢复、tarball 内容、独立 wheel、临时 DSH Reader HTTP 和 Reader fixture 浏览器验收；修改相关代码后按验收记录复跑。
2. **完整宿主交互验收**：将已通过的临时 Profile HTTP 验收扩展到真实 DSH 文献模式中的设置页、列表、抽屉和 Excel 定位。当前 UI 合同通过不代表所有原生应用交互均已实测。
3. **真实本机/API MinerU 验收**：自动、仅本机、仅 API 三种策略都要验证；任务创建后 provider 不得静默切换。
4. **设置页信息补齐**：设计要求的 Chrome/机构状态、磁盘、版本、Excel 状态和脱敏诊断并非都已在当前简化页面展示。
5. **下载实机验收**：批量 OA/HTTP 已有合同测试，但系统 Chrome 专用 Profile、机构会话和反自动化子集需在
   明确授权的环境中实测；CloakBrowser 永远不是默认依赖。
6. **Excel 真实场景**：美观样式、Excel 占用 pending、释放后刷新、稳定 `paper_id` 定位和三个白名单字段回写
   需要使用真实工作簿验收。
7. **持续维护验收记录**：新结果记录到对应执行文档，避免把本轮未执行的真实服务场景误写成已通过。

不要在完成 V1 验收前开始 V2 推荐或证据卡。

## 6. 接手后的推荐动作

### 第一步：只读确认，不要清理工作树

```powershell
. "$env:USERPROFILE\.codex\scripts\Enter-CodexUtf8.ps1"
Set-Location -LiteralPath '<repository-root>'
git status --short
git diff --stat
git log --oneline -15
```

如果当前在制文件仍由另一个 agent 持有，先与其协调；不要并行修改相同文件。

### 第二步：定向验证当前在制 MinerU 改动

```powershell
Remove-Item Env:MINERU_API_TOKEN -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = (Resolve-Path 'engine\src').Path
$env:PYTHON = (Resolve-Path 'engine\.venv\Scripts\python.exe').Path
$env:SCIENTIFIC_READING_PYTHON = $env:PYTHON
& $env:PYTHON -m pip install -e 'engine[dev]'

& $env:PYTHON -m pytest -q `
  engine/tests/test_background_launcher.py `
  engine/tests/test_environment_status.py `
  engine/tests/test_mineru_local.py `
  engine/tests/test_mineru_artifacts.py `
  engine/tests/test_mineru_parse_gate.py `
  engine/tests/test_full_read_service.py `
  engine/tests/test_full_read_renderer.py
```

### 第三步：全量验证

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run verify:restart-recovery
git diff --check
```

所有自动测试必须使用虚构工科题录、本地测试 PDF、fake provider 和临时 data root；不得消费真实 MinerU
额度，不得触发机构认证，也不得读写用户真实论文库。

### 第四步：提交和安装

- 提交信息使用中文。
- 只暂存本任务实际修改的文件；不要把未相关的临时文件或生成物顺带提交。
- 只有用户明确要求时才 `git push origin main`；提交和推送状态以执行时的 Git 检查为准。
- 安装真实 tarball 时使用唯一文件名，避免 pnpm 对同版本、同路径 tarball 的缓存让旧 client 被重复安装。

参考命令：

```powershell
$packed = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$source = Join-Path (Get-Location) $packed[0].filename
$dest = Join-Path "$env:USERPROFILE\.dsh\packages" `
  ("dsh-scientific-reading-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.tgz')
Copy-Item -LiteralPath $source -Destination $dest
dsh plugin --profile web add $dest --ignore-scripts
dsh --profile web --host 127.0.0.1 --port 3080
```

## 7. 关键文件地图

| 位置 | 责任 |
|---|---|
| `client/client.js` | DSH 文献页、设置页和浏览器交互源码 |
| `lib/client.js` | 生成的客户端产物，不直接编辑 |
| `src/index.ts` | 插件挂载和注册入口 |
| `src/library_tools.ts` | 对话工具、精读 gate 和用户可见状态 |
| `src/download_batch.ts` | 单篇/批量 PDF 编排 |
| `src/status_routes.ts` | 设置状态、重新检测和 MinerU Key HTTP 边界 |
| `engine/src/scientific_reading/library_service.py` | SQLite 文献库 |
| `engine/src/scientific_reading/background_*` | 持久后台任务与 worker 启动 |
| `engine/src/scientific_reading/reading_pipeline.py` | PDF→解析→翻译→reader 父任务 |
| `engine/src/scientific_reading/mineru_{local,api,service,artifacts}.py` | MinerU provider、规范化和资产校验 |
| `engine/src/scientific_reading/full_read_*` | 翻译批次与 reader 渲染 |
| `engine/src/scientific_reading/xlsx_snapshot.py` | Excel 派生视图与回写边界 |
| `docs/design.md` | V1 当前产品/技术合同 |
| `docs/roadmap.md` | V1 与 V2 边界 |
| `docs/superpowers/specs/2026-08-27-v1-settings-library-ui-design.md` | 设置页、MinerU、文献页详细验收合同 |

## 8. 永久安全与资产边界

- 不在仓库、普通配置、SQLite、Excel、日志、argv、job JSON、HTTP 响应或诊断报告中保存 MinerU Key。
- 不记录或读取机构账号、Cookie、验证码、MFA；不要读取用户日常 Chrome Profile。
- PDF、MinerU 原始包、翻译、reader、Figure/Table、Excel 和浏览器会话都保存在仓库外。
- SQLite 是事实源；manifest 和 Excel 是派生视图。不要通过修改时间猜测“最新 generation”。
- 不移动、删除或无故重算旧 PDF、MinerU、reader 和用户资产。
- 不把算法输出或 AI 重点判断冒充论文事实；reader 和未来证据卡都必须保留原文定位和来源 SHA。
- Windows 子进程保持隐藏窗口参数，避免 worker 每隔几秒弹出终端。

## 9. 交接完成标准

下一位 agent 在声称 V1 完成前，至少要给出以下新鲜证据：

- 工作树中在制 MinerU 改动的归属和最终提交清楚；
- Python 全量测试、TypeScript 类型检查和 `npm test` 全部通过；
- npm tarball 只携带预期文件和一个内置 engine wheel；
- 临时 DSH Profile 能从真实 tarball 启动，停止/重启后任务和资产可读；
- 浏览器验证设置页、文献列表、Abstract 抽屉、PDF 新标签页、HTML 和 Excel 定位；
- 虚构工科样本走通入库、PDF、MinerU、翻译、reader、资产和 Excel；
- 未触发真实机构认证、真实外部写入或未授权 MinerU 消费；
- 用户未跟踪文件和仓库外资产保持不变。

当前产品合同请同时阅读[技术设计](design.md)、[功能清单](features.md)与[发布路线](roadmap.md)。历史方案只在
[归档目录](archive/README.md)中追溯，不定义当前运行行为。
