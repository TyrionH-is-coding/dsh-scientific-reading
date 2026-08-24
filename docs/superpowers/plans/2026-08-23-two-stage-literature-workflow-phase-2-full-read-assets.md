# Phase 2：精读编排与图表资产 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 PDF、解析、逐块翻译和 HTML 能力收束到一个持久“开始精读”父任务，并提供可追溯的 Figure/Table 导出包。

**Architecture:** Python 引擎持有唯一父任务状态和阶段锁；插件只注入受信任的 `scansci-pdf` 获取适配并暴露单一入口。确定性阶段在 worker 中自动推进，只有全文翻译/重点识别暂停为 agent gate。现有解析器和阅读器复用，不重写。

**Tech Stack:** Python background worker、PyMuPDF、MinerU、现有 reader renderer、pytest；TypeScript DSH adapter、scansci wrapper、Node 合同与恢复测试。

---

## 前置假设与成功条件

1. Phase 1 已全部通过并已在两个阶段 worktree 中可引用；当前 3080 仍运行稳定旧包。
2. “一次点击”指用户只启动一次父任务；AI gate 仍由当前 DSH agent 满足。没有活跃 agent turn 时任务安全暂停为“等待翻译”，下次 agent 继续，不要求用户重新点击下载/解析。
3. 不引入新的全文下载来源。自动获取只复用插件已有 `scansci-pdf` 合法路径；机构浏览器和本地 PDF 是逐篇失败入口。
4. 不自动选择关键图。导出服务只整理解析器已经判定为正文 Figure/Table 的资产。
5. 新 HTML 规范路径是 `reading/reader.html`；旧 `reader_full.html` 不移动，路由按新路径优先、旧路径回退。

完成的可验证定义：

- `sr_start_full_read` 立即返回一个稳定 parent job；重复启动不产生并行父任务；
- 父任务自动复用或获取/校验 PDF，串行解析、翻译、渲染，宿主中断后继续；
- 自动获取失败只影响单篇，并给出机构浏览器/本地 PDF 两种 gate；
- reader manifest 可从 HTML 追溯到 PDF SHA、解析输入与翻译块；
- exports 同时包含 Figures、Tables、captions 与 manifest，CSV 仅来自可靠结构化源。

## Task 1：定义精读父任务和状态机

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\reading_pipeline_models.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\reading_pipeline.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\background_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\background_store.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\worker.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_service.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reading_pipeline.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_worker_reading_pipeline.py`

- [x] **Step 1: 写状态机失败测试**

覆盖：初始 parent job、每阶段单调转换、重复 start 返回同一 job、完成缓存、失败边界、同一文献锁、
跨文献重任务串行、宿主中断恢复、XLSX/飞书失败不改变 `精读完成`。

固定内部阶段：

```python
PIPELINE_STAGES = (
    "ensure_pdf",
    "parse_fast",
    "parse_mineru",
    "translate_full",
    "render_reader",
    "schedule_derived_updates",
)
```

固定用户状态映射：

```python
USER_STATUS = {
    "queued": "精读排队",
    "ensure_pdf": "获取 PDF",
    "parse_fast": "解析全文",
    "parse_mineru": "解析全文",
    "translate_full": "翻译与生成",
    "render_reader": "翻译与生成",
    "completed": "精读完成",
    "needs_user": "需要用户处理",
    "failed": "处理失败",
}
```

- [x] **Step 2: 实现父任务模型**

`ReadingPipelineState` 至少包含：`paper_id`、`parent_job_id`、`current_stage`、各阶段 job/output、
`source_pdf_sha256`、`reader_source_sha256`、`required_action`、`last_error`、时间戳。序列化使用明确
contract version，不把 secret/provider command 写入 state。

- [x] **Step 3: 实现幂等调度器**

```python
class ReadingPipeline:
    def start(self, paper_id: str) -> PipelineResult: ...
    def advance(self, parent_job_id: str, supplied_input: dict | None = None) -> PipelineResult: ...
    def inspect(self, parent_job_id: str) -> PipelineResult: ...
```

每一阶段先检查已校验产物再决定执行；同一 paper 只有一个 active parent。全局 heavy lock 覆盖
MinerU 和全文翻译，轻量校验不占锁。状态同时写 job store 和 SQLite 的 `active_job_id`/
`full_read_status`，两者读回不一致时以可验证的 job artifact 修复 SQLite，不反向伪造产物。

- [x] **Step 4: worker 注册 `full_read_pipeline`**

父 handler 调用既有服务，不复制 parse/full-read 实现。遇到 AI 输入返回 `AgentRequired`；遇到 PDF
用户动作返回新的 `UserActionRequired`（或等价稳定 state），不得混成翻译 gate。

- [x] **Step 5: 测试并提交**

```powershell
$env:PYTHONPATH = "$PWD\src"
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_reading_pipeline.py tests/test_worker_reading_pipeline.py tests/test_background_store.py -q
git add src/scientific_reading/reading_pipeline_models.py src/scientific_reading/reading_pipeline.py src/scientific_reading/background_models.py src/scientific_reading/background_store.py src/scientific_reading/worker.py src/scientific_reading/library_service.py tests/test_reading_pipeline.py tests/test_worker_reading_pipeline.py
git commit -m "精读：建立可恢复的父任务状态机"
```

## Task 2：接入合法 PDF 获取与逐篇用户 fallback

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\pdf_acquisition.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\pdf_validation.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\reading_pipeline.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pipeline_pdf.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pdf_acquisition.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pdf_validation.py`

- [x] **Step 1: 写 PDF 失败测试**

使用本地最小 PDF 和 fake provider command。覆盖：已有有效 PDF 直接复用、非 `%PDF` 拒绝、SHA/页数
记录、provider 成功、provider 无访问权转 needs_user、本地挂接后恢复、坏文件不覆盖旧原件、命令
身份不写入 job JSON。

- [x] **Step 2: 把获取器改为通用受信任 provider**

去掉新流程对 `zotero_pdf_bridge` 的依赖，定义：

```python
class PdfProvider(Protocol):
    def acquire(self, metadata: PaperMetadata, destination: Path) -> AcquisitionResult: ...
```

worker 只接受启动时注入的 provider 对象/受信任配置，不接受用户 HTTP body 中的任意 shell 命令。
插件将在 Task 6 注入现有 scansci wrapper。Python 单测只使用 fake provider，不联网。

- [x] **Step 3: 固定原件发布规则**

- provider 下载到同目录 staging；`%PDF`、页数和 SHA-256 全部通过后才原子替换 `source.pdf`；
- 若已有有效 source.pdf 且数据库 SHA 相同，直接复用；
- 若新 SHA 不同，保存新原件并把已有 reader 标为 stale，不删除旧 reader；
- 获取失败返回 `required_action={"kind":"pdf", "options":["institution_browser","local_pdf"]}`；
- 不读取/保存账号、Cookie、验证码、MFA 或浏览器 profile 内容。

- [x] **Step 4: CLI 增加 start/resume/attach**

`full-read-pipeline-start` 只接收 paper_id 和引擎信任的 provider profile 名称；
`full-read-pipeline-resume` 接收 parent job 与 agent/user输入 JSON；`pdf-attach` 复用现有校验。

- [x] **Step 5: 测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_pipeline_pdf.py tests/test_pdf_acquisition.py tests/test_pdf_validation.py tests/test_worker_pdf.py -q
git add src/scientific_reading/pdf_acquisition.py src/scientific_reading/pdf_validation.py src/scientific_reading/reading_pipeline.py src/scientific_reading/library_service.py src/scientific_reading/__main__.py tests/test_pipeline_pdf.py tests/test_pdf_acquisition.py tests/test_pdf_validation.py
git commit -m "精读：串联PDF校验与用户处理入口"
```

## Task 3：复用解析与逐块翻译，移除九节浅读依赖

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\reading_pipeline.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\worker.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pipeline_parse_translate.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_worker_full_read.py`

- [x] **Step 1: 写恢复与来源失败测试**

覆盖：fast parse 后 MinerU 升级、MinerU 失败保留 PDF、翻译第 N 批中断从 N 恢复、块 source id/page
保留、图注翻译、参考文献不翻译、旧 quick_read 不存在仍可精读、旧 quick_read 高亮不再是必需输入。

- [x] **Step 2: 扩展全文翻译合同**

每个块的 agent 返回：

```json
{
  "block_id": "p3-b17",
  "source_text": "...",
  "translation_zh": "...",
  "highlight": "primary"
}
```

`highlight` 只允许 `primary`（黄色）、`secondary`（亮蓝）或 `none`。模型必须按全文重新判断重点；
可以参考 Abstract，但不能读取旧九节浅读作为事实。参考文献块只保留 `source_text`，不要求中文。

- [x] **Step 3: 复用现有服务推进父任务**

`ReadingPipeline` 调用现有 `ParseService`、`MineruService`、`FullReadService`。只补适配层：

- 已完成 stage/manifest 命中即跳过；
- fast parser 不能冒充 MinerU 完成；
- 翻译批次落盘后才推进 checkpoint；
- agent 提交 source_text 不匹配或 source SHA 改变时拒绝该批，不丢已完成批；
- 解析/翻译失败只更新当前 parent，其他 queued paper 继续。

- [x] **Step 4: 测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_pipeline_parse_translate.py tests/test_full_read_models.py tests/test_full_read_service.py tests/test_worker_full_read.py tests/test_mineru_service.py -q
git add src/scientific_reading/full_read_models.py src/scientific_reading/full_read_service.py src/scientific_reading/reading_pipeline.py src/scientific_reading/worker.py tests/test_pipeline_parse_translate.py tests/test_full_read_models.py tests/test_full_read_service.py tests/test_worker_full_read.py
git commit -m "精读：按来源块恢复全文翻译与重点"
```

## Task 4：生成可追溯 `reader.html`

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_renderer.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\assets.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\workspace.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_renderer.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_workspace.py`

- [x] **Step 1: 写 reader 合同失败测试**

断言：完整正文块顺序、段落英中对照、图表位置、图注双语、参考文献英语、可收起左目录、sticky
重点控件、只看/隐藏重点、目录黄色/亮蓝标记、短句合并、HTML 离线无外链资源、manifest PDF SHA、
新旧路径回退和 stale 标记。

- [x] **Step 2: 固定工作区路径而不移动旧资产**

`PaperWorkspace` 新增：

```python
@property
def reader_html(self) -> Path:
    return self.reading_dir / "reader.html"

def existing_reader_html(self) -> Path | None:
    # reader.html 优先；否则 reader_full.html
```

不得自动重命名或删除 `reader_full.html`。

- [x] **Step 3: 最小修改现有 renderer**

复用已确认的 v2 阅读 CSS/JS，不另造主题。重点颜色：primary 黄色、secondary 亮蓝；目录点使用高
饱和度同色。把连续短句/列表项合并为一个有序列表或一个翻译块，避免每句都插独立“英文原文”。
控件 sticky 固定顶部，目录可展开/收起。

新 `reader-manifest.json` 至少记录：contract、paper_id、source_pdf_sha256、parser manifest SHA、
translation manifest SHA、reader SHA、generated_at、source blocks、assets。渲染后读回 HTML 和
manifest，再更新 SQLite 完成状态。

- [x] **Step 4: 测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_reader_v2.py tests/test_full_read_renderer.py tests/test_workspace.py -q
git add src/scientific_reading/full_read_renderer.py src/scientific_reading/full_read_service.py src/scientific_reading/assets.py src/scientific_reading/workspace.py tests/test_reader_v2.py tests/test_full_read_renderer.py tests/test_workspace.py
git commit -m "阅读器：固定双语全文样式与来源清单"
```

## Task 5：按需整理 Figure 与 Table 导出包

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\export_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\assets.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\workspace.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_export_service.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_cli_export_assets.py`

- [x] **Step 1: 写导出失败测试**

构造两张 Figure、两张 Table、一个 logo 和一个页眉。断言只导出正文资产、编号按正文顺序、同名不
覆盖、PNG 可打开、caption/page/source/SHA 完整、可靠 CSV 保留、不可靠表不生成 CSV、重复导出
幂等、失败不破坏旧 exports。

- [x] **Step 2: 扩展工作区派生路径**

```python
exports_dir / "figures"
exports_dir / "tables"
exports_dir / "captions.md"
exports_dir / "manifest.json"
```

实际旧 parsed 路径保持原样；exports 是派生包，可以在 staging 完成后原子替换。

- [x] **Step 3: 实现纯确定性 `ExportService`**

- 只读取 active MinerU/asset manifest 中 `kind=figure|table` 且正文标志为真的记录；
- Figure 优先复制最高质量解析图；没有图但有可信 bbox 时用 PyMuPDF 从 source.pdf 2x crop；
- Table 优先复制原表图；没有图且有可信 page+bbox 时从 PDF crop，保持版式；
- 仅当源 manifest 明确标记 `structured_reliable=true` 且已有 CSV/结构化 JSON 时复制为 CSV；
- 不让 AI 补 label、caption、bbox 或单元格；缺字段写 warning；
- 文件命名 `Fig_01.png`、`Table_01.png`，manifest 保存原 label/序号。

- [x] **Step 4: 增加 `export-assets` CLI 并验证**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_export_service.py tests/test_cli_export_assets.py tests/test_assets.py -q
git add src/scientific_reading/export_service.py src/scientific_reading/assets.py src/scientific_reading/workspace.py src/scientific_reading/__main__.py tests/test_export_service.py tests/test_cli_export_assets.py
git commit -m "资产：按原顺序导出全文图表包"
```

## Task 6：接入插件单一精读入口和 scansci provider

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\cli.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\library_tools.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\routes.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\scripts\scansci_wrap.py`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\full-read-pipeline.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\asset-export-routes.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\reading-routes.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\harness.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\package.json`

- [ ] **Step 1: 写插件失败合同**

验证：`sr_start_full_read` 只返回 parent job；重复调用同 job；scansci wrapper 仅由插件配置注入；
provider 失败映射两种用户选项；本地 PDF 恢复；`sr_continue_full_read` 只接受当前 gate 合同；
`sr_export_assets` 和 `/sr/api/paper/<id>/exports`；读取 reader 新路径并回退旧路径。

- [ ] **Step 2: 收敛工具**

新增普通工具：

```text
sr_start_full_read
sr_continue_full_read
sr_attach_pdf
sr_export_assets
sr_job_status
```

旧 `sr_parse`、`sr_quick_read`、`sr_full_read` 保留为 internal/legacy 到 Phase 3，但新 agent 提示和 UI
不得调用它们。所有输入经过 paper/job ID 校验。

- [ ] **Step 3: 把 scansci 包装为受信任 provider**

wrapper 接收结构化 JSON（稳定标识、目标 staging path、legal_only=true），stdout 仅 JSON。插件从自身
已打包路径解析 wrapper，不接受浏览器/用户传入可执行路径。下载结果仍由 Python 引擎做 `%PDF`、
页数和 SHA 二次验证。

- [ ] **Step 4: 路由与错误映射**

新增 POST start/continue/attach/export，GET job/reader/assets。机构浏览器入口只在 parent
`needs_user` 时显示；点击后复用现有 Chrome 授权下载流程，逐篇执行，插件不读取浏览器秘密。

- [ ] **Step 5: 测试并提交**

```powershell
npm run typecheck
node tests/full-read-pipeline.mjs
node tests/asset-export-routes.mjs
node tests/reading-routes.mjs
node tests/harness.mjs
git add src/cli.ts src/library_tools.ts src/routes.ts scripts/scansci_wrap.py tests/full-read-pipeline.mjs tests/asset-export-routes.mjs tests/reading-routes.mjs tests/harness.mjs package.json
git commit -m "插件：收敛为单一精读与图表导出入口"
```

## Task 7：Phase 2 中断恢复与完整性验收

**Files:**

- Create: `D:\Vibe Coding\dsh-scientific-reading\scripts\verify_full_read_pipeline.py`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\full-read-integration.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\scripts\verify_restart_recovery.py`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\package.json`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\README.md`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\README.md`

- [ ] **Step 1: 构造离线工程论文 fixture**

用本地 3–5 页测试 PDF，包含正文段落、两图、一表、参考文献。fake MinerU 输出带 page/block/bbox，
fake agent 分两批翻译并打黄/蓝重点；不联网、不使用医学内容。

- [ ] **Step 2: 在每个边界注入一次中断**

分别在 PDF 发布后、MinerU 后、翻译第一批后、reader staging 后终止 worker，再重启。断言已完成
阶段不重复、最终仅一个 active reader、PDF SHA/reader manifest 对齐、导出包完整。

- [ ] **Step 3: 验证不提前注入当前 Profile**

全程使用隔离 data root 与 Profile，当前 3080 不重启。记录现有安装包 SHA 前后相同。

- [ ] **Step 4: 全量测试**

```powershell
# 引擎 worktree
$env:PYTHONPATH = "$PWD\src"
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
git diff --check

# 插件 worktree
npm run typecheck
npm run test:offline
node tests/full-read-integration.mjs
npm run verify:restart-recovery
git diff --check
```

- [ ] **Step 5: 更新中文 README 并提交**

只声明经过测试的自动阶段、AI gate、fallback、reader 与导出包；明确机构浏览器仍是用户逐篇动作。

```powershell
git add README.md scripts/verify_full_read_pipeline.py scripts/verify_restart_recovery.py tests/full-read-integration.mjs package.json
git commit -m "验收：覆盖精读全链路与中断恢复"
```

## Phase 2 执行记录

实现 agent 追加 parent job 样例状态、每个中断点恢复结果、reader/manifest SHA 校验、导出数量和
尚未进入 UI 阶段的限制。不得附真实论文、机构认证信息或真实飞书响应。

### Task 1 执行记录

- 引擎提交链最终 HEAD：`da3a11905f9033a7c916ffafdd19dfc4a6059ec7`。
- 聚焦测试：`50 passed`；引擎全量测试：`602 passed, 1 skipped`。
- 双低思考强度 Sol 阶段审查：`APPROVED`。
- 本任务只建立并验证精读父任务状态机；PDF 获取、MinerU 解析和全文翻译尚未接入。
- 验证期间未联网、未写飞书、未触发机构认证，也未触碰 persistent Profile 或当前 3080。

### Task 2 执行记录

- 引擎最终 HEAD：`1a02e693a73077d1c545538644cc58c7fefdd5f5`。
- 主代理引擎全量测试：`631 passed, 1 skipped`，耗时 `68.13s`。
- 双低思考强度 Sol 阶段审查：`APPROVED`。
- 已完成受信任 `PdfProvider`、合法 fallback、本地 PDF 挂接与恢复、SHA-256 生成、OS advisory lock、SQLite O(1) 父任务索引，以及 reader stale manifest 标记。
- scansci 的实际适配仍留在 Task 6，当前状态为 unavailable；本任务未提前接入。
- 验证期间未联网、未触发机构认证、未写飞书，也未触碰 persistent Profile 或当前 3080。

### Task 3 执行记录

- 引擎最终 HEAD：`c0ddb5167c4469e61a211a5e0590fdfded5803dd`。
- 主代理引擎全量测试：`672 passed, 1 skipped in 64.81s`。
- 规范与质量低思考强度 Sol 审查：`APPROVED`。
- 已完成显式 `paper_id`、按 source SHA 分代及 `active_workspace` 指针、v2 逐块翻译合同、参考文献仅保留英文且禁止高亮、严格 CLI resume 白名单、翻译批 checkpoint 幂等与 gap 防护，以及 mutable metadata 兼容。
- 验证期间未联网、未写飞书、未触发机构认证，也未触碰 persistent Profile 或当前 3080。
- `render_reader` 仍保持明确 gate，留待 Task 4 接入。

### Task 4 执行记录

- 引擎提交链：`07dc44e`、`58df064`、`71416d2`、`b0b88aa`、`a78d3d1`。
- 聚焦测试：`70 passed`；fresh 引擎全量测试：`689 passed, 1 skipped`。
- 规格审查与质量审查：`APPROVED`。
- 已完成首次 base workspace 与 source-SHA generation 两种 reader 发布路径；图表按来源顺序渲染，
  同一逻辑 Table 优先可读 HTML companion 且不重复展示，manifest 仍保留全部来源资产。
- primary/secondary 图注重点会标记父 Figure/Table，`focus-only` 保留完整相邻图表；参考文献只显示
  一份英文，reader 保持离线、自包含、可追溯。
- publication 会读回并核对 PDF、parser manifest、translation manifest、reader 和逐项 asset 的实际
  SHA、路径 containment、active workspace 与 SQLite artifact/status；失败不把旧 artifact 错标为 ready。
- 本任务未引入 v2.1，未联网、未写飞书、未触发机构认证，也未触碰 persistent Profile/3080；旧
  PDF、MinerU、HTML、quick_read 与 stale 资产均未移动或删除。

### Task 5 执行记录

- 引擎提交链：`ce2f007`、`168382e`、`18224c3`、`ce03613`。
- fresh 引擎全量测试：`709 passed, 1 skipped`；规格审查与独立质量审查均为 `APPROVED`。
- 导出服务仅整理显式正文 Figure/Table；旧 MinerU 缓存保持只读，缺少正文证据时 fail-closed，
  不重写旧 manifest、parse report 或 content list，也不重跑解析。
- Figure/Table 固定发布为可读 PNG；仅在可信 page+bbox 明示时从当前 source PDF 做 2× crop。
  CSV 只接受显式可靠、路径受限且 SHA 匹配的 CSV/结构化 JSON，不从 HTML、截图或 AI 推断单元格。
- staging 在完整读回 PNG、CSV、路径与 SHA 后原子发布；验证或发布失败保留旧 exports，重复导出
  字节幂等。执行期间未联网、未写飞书、未触碰当前 3080，也未进入 reader v2.1。
