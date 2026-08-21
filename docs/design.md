# dsh-scientific-reading 插件技术设计（草案 v0.2）

> 目标：把 [Scientific-Reading-for-Newbies](https://github.com/TyrionH-is-coding/Scientific-Reading-for-Newbies)
> 的完整文献工作流搬进 DeepSeek Harness（DSH）GUI，让用户用一句话驱动
> **下载 → 解析 → 入库 → 笔记** 全流程，且每个阶段可断点恢复、可追溯、可审计。
>
> v0.2 方向修订（2026）：**摒弃 Zotero Desktop**，把"文献库"整个搬进 DSH——
> 在对话/轨迹旁边新增【文献】标签页模拟 Zotero 界面；条目存本地 SQLite，
> PDF/解析产物/笔记存仓库外数据目录。下载（scansci-pdf）、解析、浅读、精读、
> 飞书同步等 90% 代码不变，只替换"记录存哪、读回从哪读"这一层。
>
> 定位：**包装（wrap）而非重写**。Python CLI 是确定性引擎（18.6k 行、60+ 测试、
> P95 预算、飞书适配器）；插件是 TS 薄壳，把 CLI 命令包成 typed 工具；
> DSH 会话 agent 取代原项目中的 Codex 承担编排与判断。

---

## 0. 给小白看的一页（大白话导读）

**这个插件解决什么问题？**
你告诉它一个 DOI（或论文题名），它自动帮你：下载 PDF → 解析 → 生成中文笔记 → 存进 Zotero/飞书。全程在 DSH 对话里完成，不用记命令行。

**流水线长这样（每一段都有现成代码，插件只是把它们串起来）：**

```text
你给 DOI
 ① 下载 PDF    ← 第一步先做这个：接入 scansci-pdf（自动找合法来源）
 ② 校验        ← 确认下载的确实是这篇论文（原项目已有）
 ③ 解析        ← 把 PDF 拆成文字/图片/表格（原项目已有）
 ④ 中文浅读笔记 ← 生成 9 节式中文笔记（原项目已有）
 ⑤ 入库        ← 存进本地文献库（SQLite + 文件，替代 Zotero），可选同步飞书
```

**scansci-pdf 是什么？**
一个现成的"论文下载器"（PyPI 包，1.9.0）。给它 DOI，它自动试 arXiv、开放获取、
出版社直链、学校 WebVPN/CARSI 机构登录等来源，哪个快用哪个，下载后自动命名。
原项目文档早就预留了它的位置（Zotero 找不到 → ScanSci → 才轮到手动 Chrome）。

**一个默认开关（重要）：**
scansci-pdf 自带 Sci-Hub/LibGen 来源且默认开启。本项目铁律是"不绕过付费墙"，
所以插件**默认关掉灰色来源，只走合法来源**（arXiv、开放获取、学校机构访问），
灰色来源留一个开关由你决定是否打开。

**第一步（最小可用的下载段）：**
检查/安装 scansci-pdf → 下载工具（DOI → PDF）→ 机构登录工具（密码不经过插件）
→ 用一篇开放论文跑通。跑通后接上原有的校验/解析/笔记。

---

## 1. 架构总览

### 1.1 进程域

```text
┌──────────────────────────────────────────────────────────────────┐
│ DSH Host（Node/Cordis）                                           │
│                                                                  │
│  dsh-scientific-reading 插件                                      │
│   ├─ tools/  15+1 个 typed 工具（ctx.tools.register）            │
│   ├─ routes/ /sr/* HTTP 路由（ctx.webServer.register）            │
│   ├─ settings/ 配置（installSettingsSection）                     │
│   └─ cli.ts   子进程适配器 → python -m scientific_reading ...     │
└──────────────┬───────────────────────────────────────────────────┘
               │ 前台命令（P95 ≤ 2s，直接子进程同步调用）
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Python CLI 引擎（pip 安装的 scientific-reading-for-newbies）       │
│  ├─ 前台：init / validate-pdf / zotero-check / browser-download-*  │
│  │        job-status / job-resume / quick-read-submit / ...       │
│  └─ 后台：独立 worker 进程（--background 排队的任务）              │
│        状态/事件/心跳/恢复输入 → <dataRoot>/jobs/<job_id>/         │
└──────────────┬───────────────────────────────────────────────────┘
               │ 外部服务（只读/受控）
               ▼
   Zotero Desktop Local API :23119（只读）
   Zotero Connector（RIS 写入，--confirm-write）
   Zotero 桥接插件 POST 端点（pdf 全文查找/回挂）
   MinerU executable（本地，配置路径）
   Chrome（用户亲自操作，插件只做基线/认领）
   Feishu OpenAPI（凭据仅经环境变量注入）
```

### 1.2 关键决策

| 决策 | 理由 |
|---|---|
| 重活全部走 CLI 的 `--background` job 模型 | worker 是独立进程 + 磁盘状态，宿主重启/插件热重载不丢任务；比 DSH 进程内 `ctx.jobs` 更健壮 |
| 前台命令直接子进程调用 | CLI 设计预算 P95 ≤ 2s；插件工具同步等待并透传统一 JSON |
| gate 判断交给会话 agent | 原 SKILL.md 就是为此写的协议；DSH 会话模型即"Codex 角色" |
| 插件只做确定性动作 | 不自动化 Chrome、不代用户确认、不自行修正文献内容 |
| 数据仍在仓库外 `<dataRoot>/` | 沿用原项目数据边界纪律；仓库只装代码与规则 |

### 1.3 状态流（阶段状态机，原样保留）

```text
init → zotero_ready → pdf_ready → parsed_fast ─┬─> quick_read_ready ─┬─> full_read_ready
        (zotero_record)   (pdf_acquisition)    └─ needs_mineru ──> parsed_mineru ─┘
                                                                           └─> feishu_sync 完成
```

每个阶段对应一个后台 job（`target_stage`：`zotero_record` / `pdf_acquisition` /
`paper_parse` / `mineru_parse` / `quick_read` / `full_read` / `feishu_sync`）。

### 1.4 文献标签页（替代 Zotero 界面）【v0.2 新增】

DSH 网页是**三栏框架**（sidebar | conversation | details），对话区顶部有一排
**视图标签页**，注册插槽为 `conversation.view`。"轨迹"就是这个机制下的一个标签页
（`order: 10`）。【文献】照抄该模式，成为第三个标签页（`order: 20`）：

```ts
// client 模块（dsh.client，React）
ctx.slots.register({
  name: 'conversation.view',
  id: 'literature',
  order: 20,
  locale: NS,
  label: () => '文献',
  inject: (sessionId) => ({ /* session 绑定 */ }),
}, LiteratureView)
```

文献页内部采用 Zotero 式三栏布局：

```text
┌─────────────┬───────────────────────────────┬──────────────────────┐
│ 左栏         │ 中栏（论文表格）               │ 右栏（详情）          │
│ · 全部文献    │ 勾选｜标题｜作者｜年份｜期刊      │ · 元数据（可编辑）    │
│ · 分类（自建） │ 状态徽标（已下载/已解析/已读）  │ · PDF/解析产物链接    │
│ · 标签        │ 有PDF｜已读｜已同步飞书         │ · 笔记（浅读/精读）   │
│ · 搜索框(全文) │ 排序｜批量操作                 │ · 操作按钮：下载/解析  │
│               │                               │   /浅读/精读/同步飞书  │
└─────────────┴───────────────────────────────┴──────────────────────┘
```

- 中栏数据来自宿主路由 `/sr/api/library`（分页/搜索/过滤）；
- 右栏操作按钮 = 直接调用插件 `sr_*` 工具（同一套执行管线）；
- 顶栏另有"添加文献"（输入 DOI/题名 → 走下载流水线）；
- 客户端只做展示与动作触发，业务逻辑全部在宿主/引擎侧，保持"界面不掺和业务"。

### 1.5 文献库核心（替代 Zotero）【v0.2 新增】

新增 `library_service`（Python，放进引擎包），用 **SQLite + 磁盘文件** 复刻
Zotero 的职责：

| Zotero 能力 | 替代方案 |
|---|---|
| 条目存储（题名/作者/DOI/PMID/年份/期刊/key） | SQLite 表 `items`（含稳定 `paper_id`） |
| 附件（PDF） | `papers/<id>/source.pdf` + SQLite 记录 SHA-256 |
| 查重（DOI/PMID/规范化题名精确匹配） | **复用原 `zotero_matching` 逻辑**，查询目标改为 SQLite |
| 写入后读回确认 | 写入本地库 → 读回文件哈希/记录比对（同样严格，零网络） |
| 全文搜索 | SQLite FTS5 索引 `parsed/*/full.md` 文本层 |
| 标签/分类 | SQLite 表 `tags` / `collections` + 多对多 |
| 笔记 | 直接存 `reading/quick_read.md`、`reading/full/*`，库中登记路径与状态 |
| 导入既有 Zotero 数据 | 一次性迁移工具：读 Zotero Local API 或 RIS 文件导入 |

流程改动（原 `zotero_ready` / `pdf_ready` 的读回语义）：

```text
旧：RIS 写入 Zotero → Local API 读回唯一命中 → zotero_ready
新：写入本地库 → SQLite 读回唯一命中 → library_ready

旧：附件回挂 Zotero → Local API 读回同一 key + SHA-256 一致 → pdf_ready
新：登记 source.pdf 哈希 → SQLite 读回哈希一致 → pdf_ready
```

不再需要：Zotero 桥接插件（xpi）、Connector RIS 端点、Zotero Desktop 常驻。
引擎包的 `zotero_*` 模块改为可选兼容层（迁移用），默认路径走 `library_service`。

---

## 2. CLI 契约速查（插件适配的依据，已核实源码）

### 2.1 统一输出 JSON：`ForegroundResult`

除 `init`、`validate-pdf`、`feishu-preview` 外，所有命令 stdout 打印且仅打印一个 JSON：

```json
{
  "paper_id": "doi_10.5555_bridge.2024.1",
  "status": "queued",
  "job_id": "job_0123456789abcdef",
  "foreground_elapsed_ms": 42,
  "agent_required": false,
  "next_action": "poll",
  "detail": { }
}
```

- `next_action` ∈ `done | poll | agent | user`
- `status` = 阶段状态（如 `queued` / `waiting_agent` / `waiting_user` / `completed` / `failed`）或阶段产物状态（`pdf_ready` / `parsed_fast` / `quick_read_ready` …）

### 2.2 退出码语义

| 退出码 | 含义 | agent 处理 |
|---|---|---|
| 0 | 成功 | — |
| 1 | `validate-pdf` 校验不通过 | 向用户报告 failures |
| 2 | user gate（`next_action=user`） | 用 `ask_user_question` 问用户，拿到确认后 `sr_job_resume` |
| 3 | agent gate（`next_action=agent`） | agent 自己执行判断，产出结构化 JSON 后提交 |
| 4 | 失败（`detail.error`） | 读 error 决定重试/恢复/报告 |

### 2.3 `job-status` 的 `detail`（JobStatus.to_dict）

```json
{
  "job_id": "job_...", "state": "waiting_agent",
  "created_at": "...", "updated_at": "...", "pid": 12345,
  "heartbeat_at": "...", "reason_code": "produce_quick_read",
  "required_input": { }, "result": { }, "error": null
}
```

`state` ∈ `queued | running | waiting_agent | waiting_user | completed | failed | interrupted`。

### 2.4 非标准输出命令

| 命令 | 输出 |
|---|---|
| `init` | `{"paper_id": "...", "path": "<dataRoot>/papers/<id>"}` |
| `validate-pdf` | `{"valid": bool, "failures": [...], "sha256": "...", ...}` |
| `feishu-preview` | `{"status": "preview_ready", "path": ..., "payload_sha256": ..., "dedupe_keys": [...]}` |

### 2.5 ID 格式（路由安全校验用）

- `paper_id`：`^(pmid_|doi_|zotero_|title_)[A-Za-z0-9_.\-]+$`
- `job_id`：`^job_[0-9a-f]{16}$`

---

## 3. 插件包结构

```text
dsh-scientific-reading/
├── package.json              # name: @dsh-external/dsh-scientific-reading（示例）
│                             # peerDeps: @deepseek-ai/cordis, dsh-tools, dsh-settings
│                             # dsh.client（Phase 2 设置卡片用）
├── tsconfig.json
├── build.sh                  # tsc 编译 host；可选 build:client（tsdown）
├── src/
│   ├── index.ts              # apply(ctx, config)：装配 设置→探活→工具→路由
│   ├── config.ts             # 配置 schema + 默认值 + 校验
│   ├── cli.ts                # Python CLI 子进程适配器（核心）
│   ├── papers.ts             # 纯 TS 扫描 <dataRoot>/papers/*（sr_status 用，不调 CLI）
│   ├── tools/
│   │   ├── setup.ts          # sr_setup（建 venv / 安装 CLI / 探活）
│   │   ├── ingest.ts         # init / zotero-check / zotero-ensure
│   │   ├── pdf.ts            # pdf-acquire / browser-download-prepare|claim / job-resume
│   │   ├── parse.ts          # parse-paper / parse-upgrade
│   │   ├── quickread.ts      # quick-read / quick-read-submit
│   │   ├── fullread.ts       # full-read / full-read-submit / full-review-submit
│   │   ├── feishu.ts         # feishu-preview / feishu-sync
│   │   └── jobs.ts           # job-status / status（总览）
│   ├── routes.ts             # ctx.webServer 路由：/sr/*
│   └── gate.ts               # gate 结果 → render 文案 的公共辅助
├── skills/scientific-reading/SKILL.md   # 会话技能（改编自原仓库）
├── vendor/scientific-reading/           # 原仓库 git submodule（Phase 1 决策点，见 §12）
└── tests/                    # vitest：cli 适配器、schema、路由安全
```

---

## 4. 配置（settings schema）

命名空间：`scientificReading`（settingsNamespace 取同值，两端一致）。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `dataRoot` | string（绝对路径） | ✅ | 仓库外数据根；所有工具默认注入 `--data-root` |
| `python` | string | 否 | Python 解释器：绝对路径或 PATH 名；缺省 `python` |
| `cliModule` | string | 否 | 缺省 `scientific_reading` |
| `cliInstallDir` | string | 否 | 引擎源码/已安装位置；`sr_setup` 用 |
| `venvDir` | string | 否 | 缺省 `<dataRoot>/.venv` |
| `zoteroBaseUrl` | string | 否 | 缺省 `http://127.0.0.1:23119` |
| `mineruExe` | string | 否 | 本地 MinerU 3.4.x executable 绝对路径；也可用 env `SCIENTIFIC_READING_MINERU` |
| `feishuConfig` | object | 否 | appToken/tableId/fieldMap；由插件物化为 `<dataRoot>/config/feishu.json` |
| `feishuAppId` | string(secret) | 否 | 只进子进程 env `FEISHU_APP_ID` |
| `feishuAppSecret` | string(secret) | 否 | 只进子进程 env `FEISHU_APP_SECRET` |
| `browserDownloadDir` | string | 否 | Chrome 下载目录（`browser-download-prepare` 缺省值） |

校验规则（写拒绝而非用时报错）：
- `dataRoot` 必须绝对路径且不允许是插件包目录；
- `python` 若为绝对路径必须存在；
- secret 字段永不进响应、日志、job 文件；只注入子进程 env。

---

## 5. CLI 适配器（cli.ts）

### 5.1 解释器解析顺序

1. 配置 `python`（绝对路径优先）；
2. 否则 `venvDir/Scripts/python.exe`（Windows）若存在；
3. 否则 PATH 上的 `python`。

### 5.2 调用与输出

```ts
type CliResult =
  | { ok: true; json: Record<string, unknown>; exitCode: 0 }
  | { ok: false; kind: 'user-gate' | 'agent-gate' | 'validation-fail' | 'error';
      exitCode: number; json: Record<string, unknown>; stderr?: string }
```

- stdout 必须恰好一个 JSON 对象（按命令白名单解析对应形状）；
- 退出码 2/3/4 → 结构化 `kind`，不抛原始异常；
- env 透传：宿主环境变量 + `SCIENTIFIC_READING_MINERU` + 飞书凭据；
- 超时：前台命令 10s（CLI 预算 2s，留余量）；超时视为 error 并提示可重试；
- 串行化：per-`dataRoot` 的 promise 队列（`init` 并发写同一 workspace 会竞态；CLI 自身已按稳定 job id 去重，但前台写操作仍应串行）；
- 工作目录：`dataRoot`（不依赖宿主 cwd）。

### 5.3 健康探针

`apply` 时异步执行 `python -m scientific_reading --help`：

- 成功 → 工具可用；`sr_status` 返回 `engine: ok` + CLI 版本；
- 失败 → 插件照常加载，`sr_status` 返回 `engine: missing` + 修复指引（运行 `sr_setup`）；
- `sr_setup`：建 venv → `pip install -e <cliInstallDir> [dev]` → 再探活。

---

## 6. 工具目录（15 + 2 个）

通用约定：
- 工具命名统一前缀 `sr_`；
- `paper_id` 一律由工具自己映射到绝对 `metadata.json`（agent 不必拼路径）；
- 需要绝对路径的参数（本地 PDF、提交输入文件）由 agent 从 gate 的 `required_input` 或用户处取得；
- 每个工具 `output.schema` = 透传的 CLI JSON（canonical），`output.render` = 中文 prose；
- 写操作（zotero-ensure / feishu-sync / job-resume 带确认）的 schema 必须含 `confirm: boolean` 参数，agent 仅在用户确认后传 `true`。

### 6.1 总览与安装

| 工具 | 参数 | 输出 | 说明 |
|---|---|---|---|
| `sr_status` | — | 见下 | 纯 TS 扫描：引擎健康、论文列表（id/标题/状态/活跃 job/next_action）、job 队列 |
| `sr_setup` | `cliInstallDir?`, `force?` | `{status, engine, version?}` | 建 venv、安装引擎、探活（幂等） |

`sr_status` 输出：

```json
{
  "engine": { "ok": true, "version": "0.1.0", "python": "D:/.../python.exe" },
  "papers": [{ "paper_id": "...", "title": "...", "status": "parsed_fast",
               "stages": { "pdf_acquisition": { "status": "completed", ... } },
               "next_action": "poll", "job_id": "job_..." }],
  "jobs": [{ "job_id": "...", "state": "running", "reason_code": null }]
}
```

### 6.2 入库阶段（ingest.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_init` | `init` | `title`(必), `authors[]`, `doi?`, `pmid?`, `year?`, `journal?` | 无 |
| `sr_zotero_check` | `zotero-check` | `paper_id` | 返回 `detail`（命中/未命中/candidates） |
| `sr_zotero_ensure` | `zotero-ensure` | `paper_id`, `confirm`(必) | 未确认 → `user-gate: write_confirmation_required`；歧义 → `agent-gate: ambiguous_reference`（`detail.candidate_keys`） |

> 设计选择：agent 流程固定为 `check`（只读查重）→ 若未命中 → `ask_user_question` 询问是否入库 → `ensure(confirm: true)`。`ensure` 用后台排队（`--background`），返回 `poll`。

### 6.3 PDF 获取（pdf.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_pdf_acquire` | `pdf-acquire` | `paper_id`, `mode`(auto|local-file), `pdf?`(local-file 必填绝对路径) | 返回 `poll`；worker 内可能转 `user-gate: choose_pdf_source` / `authorize_chrome` |
| `sr_dl_prepare` | `browser-download-prepare` | `job_id`, `download_dir?` | 仅限 `authorize_chrome` 状态任务 |
| `sr_dl_claim` | `browser-download-claim` | `job_id` | 歧义 → `agent-gate: ambiguous_browser_download`（detail.candidates）；缺失 → `user-gate` |
| `sr_job_resume` | `job-resume` | `job_id`, `confirm?`, `pdf_source?`, `pdf?` | 参数合法性由 CLI 状态机校验 |

Chrome 流程（安全底线，原样保留）：
1. `sr_job_status` → `authorize_chrome`，`required_input.target_url` = DOI resolver；
2. agent 向用户说明站点/动作并取得**当次**授权（`ask_user_question`）；
3. 用户亲自登录/下载（登录、MFA、许可确认绝不代劳）；
4. 下载前 `sr_dl_prepare`（记录非递归基线），下载后 `sr_dl_claim`；
5. `sr_job_resume(pdf_source: 'local-file', pdf: <claimed 绝对路径>)`。

### 6.4 解析（parse.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_parse` | `parse-paper` | `paper_id` | 前置不满足 → error `pdf_ready_required` |
| `sr_parse_upgrade` | `parse-upgrade` | `paper_id`, `method?`(auto|txt|ocr), `reason?`(quality|full-read), `mineru_exe?` | 缺 exe → error `mineru_executable_required`（提示配置或 `sr_setup`） |

### 6.5 浅读（quickread.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_quick_read` | `quick-read` | `paper_id`, `project_context?` | 前置不满足 → `parsed_fast_required` / `mineru_required`（先 upgrade 再回来） |
| `sr_quick_read_submit` | `quick-read-submit` | `job_id`, `proposal`(对象) | **agent gate 的核心**：`proposal` 必须符合 `quick-read-v1` 契约；插件把对象物化为临时 JSON 文件再调 CLI（`--input` 需绝对路径） |

`sr_quick_read_submit.proposal` schema（= quick-read-v1，已核实 `quick_read_models.py`）：
- `contract_version: "quick-read-v1"`, `language: "zh-CN"`；
- `one_sentence_conclusion` / `research_question_background` / `methods` / `conclusions_limitations`：`{text, source_blocks[]}`；
- `main_results[]`：3–6 条，`{result_id: "R1".., text, source_blocks[], english_evidence?, evidence_status: {claim_strength: speculative|observed|supported|strong, limitation, contradictory_evidence?, allowed_wording}}`；
- `key_figures[]`：0–3 条，`{asset_id, explanation, source_blocks[]}`；
- `project_relevance`：`{status: matched|context_missing|... , text, source_blocks[]}`；
- `key_sources[]`：3–12 条，`{page, source_blocks[], reason}`。
- 校验失败 → CLI 返回 `quick_read_revision_required`，agent 只改 `validation_errors` 指出的字段重交。

### 6.6 精读（fullread.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_full_read` | `full-read` | `paper_id` | 需 active MinerU 解析；否则 `mineru_required_for_full_read` |
| `sr_full_read_submit` | `full-read-submit` | `job_id`, `batch_index?`, `translation`(对象) | gate: `translate_full_read` / `full_translation_revision_required`；契约 `full-translation-v1` |
| `sr_full_review_submit` | `full-review-submit` | `job_id`, `review`(对象) | gate: `review_full_read` / `full_review_revision_required`；契约 `full-review-v1`（补充重点受 10% 上限约束） |

批量翻译：worker 按 ≤40 块 / 64 KiB 生成可恢复批次；每次 gate 返回 `batch_index` + 批次内容路径；agent 逐批翻译提交，全部通过后只有一次 review。

### 6.7 飞书（feishu.ts）

| 工具 | CLI | 参数 | gate 行为 |
|---|---|---|---|
| `sr_feishu_preview` | `feishu-preview` | `paper_id`, `projects[]?` | 零网络、确定性；输出 `preview_ready` + payload_sha256 |
| `sr_feishu_sync` | `feishu-sync` | `paper_id`, `projects[]?`, `confirm`(必) | 缺凭据 → `user-gate: feishu_credentials_required`（配置后 `sr_job_resume` 直接恢复） |

### 6.8 任务（jobs.ts）

| 工具 | CLI | 参数 | 说明 |
|---|---|---|---|
| `sr_job_status` | `job-status` | `job_id` | 轮询主入口；返回 `next_action` 路由 |
| `sr_job_resume` | `job-resume` | 见 6.3 | 所有 user/agent gate 的恢复入口（confirm / pdf_source / 提交类走各自的 submit 工具） |

### 6.9 UI 呈现约定（presentation）

- 所有工具 `presentCall` 用 `generic` card，`locations` 指向本次影响的文件（`<dataRoot>/papers/<id>/metadata.json`、`job.json`、提交的提案文件）；
- `sr_dl_*` 用 `generic`（不冒充 terminal）；
- `sr_status` 的结果卡片列出论文清单与状态徽标；
- 不把 UI 格式化塞进 canonical value（契约要求）。

---

## 7. Agent gate 协议（会话技能核心）

工具返回 `next_action` 后，agent 按此表行动：

| next_action | agent 行为 |
|---|---|
| `done` | 读 `detail` / 产物文件，向用户汇报 |
| `poll` | 隔若干秒调 `sr_job_status`（同一 job），直到非 poll |
| `user` | 用 `ask_user_question` 呈现 `reason_code` + `required_input`；用户选择后 `sr_job_resume`（写操作必须带用户确认的 `confirm: true`） |
| `agent` | 按 `reason_code` 执行对应判断（下表） |

| reason_code（agent gate） | agent 动作 | 产出/提交 |
|---|---|---|
| `ambiguous_reference` | 向用户列出 `candidate_keys`，请其选择 | 选定后 `sr_zotero_ensure` 重试或换元数据 |
| `produce_quick_read` / `quick_read_revision_required` | 用 read 工具读 gate 列出的本地文件（`metadata.json`、`source_map.json`、`full.md`、`parse_report.json`、`manifest.json`）；**默认不联网** | `quick-read-v1` JSON → `sr_quick_read_submit` |
| `translate_full_read` / `full_translation_revision_required` | 读批次内容，逐批翻译 | `full-translation-v1` → `sr_full_read_submit` |
| `review_full_read` / `full_review_revision_required` | 通读全部译文，补 ≤10% 上限的蓝色重点 | `full-review-v1` → `sr_full_review_submit` |
| `mineru_required` / `mineru_required_for_full_read` | 不硬凑浅读；`sr_parse_upgrade` 成功后恢复原 job | — |
| `ambiguous_browser_download` | 把 `candidates` 给用户选 | 选定路径 `sr_job_resume(pdf_source: local-file)` |
| `parse_artifact_inconsistent` 等一致性 gate | 报告并询问是否重建 | — |

铁律（写入 SKILL.md 与工具 description）：
1. 每条浅读主张必须绑定真实 `source_blocks`；禁止凭空补充论文内容；
2. `claim_strength` 只降不升；`allowed_wording` 是最强允许措辞；
3. 无法可靠定位关键图时留空，不猜测；
4. 用户授权**当次有效**，跨轮次/跨站点不继承。

---

## 8. Web 路由（ctx.webServer）

| 路由 | kind | 行为 |
|---|---|---|
| `/sr` | exact | 自包含仪表盘 HTML（vanilla JS，无远程资源）：论文卡片、状态、next_action、产物链接 |
| `/sr/api/papers` | exact | JSON：同 `sr_status`（纯文件扫描） |
| `/sr/reader/<paperId>` | exact | 服务 `<dataRoot>/papers/<id>/reading/full/output/reader_full.html`（单文件、data: URI 内嵌、零远程依赖）；不存在 → 404 |
| `/sr/reading/<paperId>/quick_read.md` | exact | 浅读笔记以 text/html 呈现 |

安全规则：
- `paperId` 必须匹配 §2.5 的 ID 格式（正则白名单），否则 404；
- 只允许读取 `<dataRoot>/papers/<paperId>/` 之内的产物路径，禁止 `..` 与符号链接逃逸（resolve 后校验前缀）；
- 路由只读，不提供删除/写入端点；
- 仪表盘不内嵌任何密钥。

---

## 9. 生命周期

- `apply(ctx, config)`：注册设置 → 启动健康探针（异步，不阻塞加载）→ 注册工具 → 注册路由；所有注册走 `ctx`，卸载自动清理（含 HMR：改插件源码即热替换，工具/路由自动重挂）。
- 后台 worker 是独立进程，插件 dispose 不影响进行中的任务；`sr_status` 扫描磁盘即恢复全景。
- 工具执行中若插件被卸载：子进程调用以 `exec.signal` 取消等待，已排队的 CLI job 不受影响（可继续 `sr_job_status`）。

---

## 10. 会话技能集成

- 把原仓库 `skills/scientific-reading/SKILL.md` 改编为插件的 `skills/scientific-reading/SKILL.md`：
  - 把 `python -m scientific_reading ...` 命令替换为对应 `sr_*` 工具调用；
  - 保留九节浅读规范、证据纪律、Chrome 授权流程、恢复规则；
  - 新增"DSH 会话专属"节：poll 间隔、ask_user_question 时机、错误恢复表。
- 实现期验证 DSH 技能挂载机制（插件内技能 vs 用户技能目录），作为 Phase 1 收尾项。

---

## 11. 阶段划分与验收（v0.2 修订）

### Phase 0 —— 下载段先行（scansci-pdf 接入）
交付：检查/安装工具（`sr_setup` 扩展）、下载工具（`sr_scansci_fetch`：
DOI → PDF 落盘 + 元数据 JSON）、机构登录工具（`sr_scansci_login`，密码不经过插件）、
合法来源默认配置（`scihub_enabled=false`）。
验收：用一篇开放获取论文（如 arXiv DOI）实际下载成功；下载目录出现
`作者年份_标题.pdf`；登录工具能打开学校登录页。

### Phase 1 —— 文献库核心 + 闭环（替代 Zotero）
交付：
- 引擎包新增 `library_service`（SQLite：items/tags/collections/attachments + FTS5），
  `zotero_ready` 改为 `library_ready`，`pdf_ready` 读回改本地哈希校验；
- 适配器 + 全部 `sr_*` 工具 + 设置 + `/sr/*` 路由 + 技能文档；
- `sr_setup` 一键装两个引擎（venv + pip install -e）。

验收（端到端演练，用合成工科 PDF，不动真实医学文献）：
1. `sr_init` + 本地查重 → 未命中 → 确认 → 写入本地库 → `library_ready`；
2. `sr_pdf_acquire(mode: local-file)`（或 `sr_scansci_fetch` 产物）→ 校验 + 登记哈希 → `pdf_ready`；
3. `sr_parse` → `parsed_fast` → `sr_quick_read` → agent 产提案 → `sr_quick_read_submit` → `quick_read_ready`；
4. 重启宿主/热重载插件 → `sr_status` 全景无损；
5. 文献页可查、可搜（全文 FTS）、详情与操作可用。

### Phase 2 —— 文献标签页 UI（模拟 Zotero 界面）
交付：
- client 模块（dsh.client + React）注册 `conversation.view`（id: `literature`, order: 20）；
- 三栏布局：左=分类/标签，中=论文表格（分页/搜索/排序/状态徽标），右=详情/笔记/操作；
- 添加文献（DOI/题名）→ 走 Phase 0 下载流水线；右栏操作直调 `sr_*` 工具；
- 设置卡片（settings plugin card）。

验收：打开对话栏第三个标签【文献】；添加→下载→解析→浅读全流程可在页面内完成；
重启后库与状态无损；热重载即时生效。

### Phase 3 —— 增强与收尾
- 飞书 preview/sync；精读全链路（`reader_full.html` 路由）；
- 从既有 Zotero 数据一次性迁移工具；
- 可选：纯确定性部分 TS 移植（早期阶段脱离 Python）。

---

## 12. 风险与待决问题

| 问题 | 选项 | 倾向 |
|---|---|---|
| 引擎 vendoring | git submodule / git subtree / `pip install git+https` | submodule（可复现 + 跟随版本），`sr_setup` 用 `pip install -e` |
| CLI 版本跟随 | 插件固定锁 submodule commit；升级显式进行 | 锁版本 |
| 插件命名与 scope | `@dsh-external/dsh-scientific-reading` | 遵循现有惯例 |
| DSH 技能挂载机制 | 插件内 skills 目录 vs 用户 `~/.dsh` 技能目录 | 实现期验证，先文档化 |
| 文献页 = 顶级标签 vs 独立路由页 | 顶级标签（`conversation.view`，已实测可行，轨迹同款） | **顶级标签**；独立路由页仅作兜底/分享用 |
| 文献库存储 | SQLite（库）+ 磁盘文件（产物） | SQLite + FTS5 |
| Zotero 兼容层 | `zotero_*` 模块降级为可选迁移工具 | 默认不启用 |
| scansci-pdf 接入方式 | CLI 子进程包装（现在）→ 未来可切 `dsh-mcp-client` MCP 直连 | CLI 先行，MCP 留作后路 |
| Python 环境缺失 | `sr_setup` 自动化；失败则 `engine: missing` 降级提示 | 降级不崩溃 |
| 精读 token 成本 | 沿用 40 块/64 KiB 分批；提交即落盘可恢复 | 接受 |

## 13. 附：实现顺序建议（v0.2）

1. Phase 0：`config.ts` + `cli.ts` 适配器（scansci-pdf 下载段）→ 2. `sr_setup`/下载/登录工具 → 3. 开放论文实测下载 → 4. Phase 1：引擎加 `library_service`（SQLite）→ 5. ingest/pdf/parse/quickread 工具改造（读回改本地）→ 6. 闭环演练 → 7. Phase 2：client 模块 + 文献标签页 UI → 8. 设置卡片 → 9. Phase 3：飞书/精读/迁移/可选 TS 移植 → 10. 测试与演练。
