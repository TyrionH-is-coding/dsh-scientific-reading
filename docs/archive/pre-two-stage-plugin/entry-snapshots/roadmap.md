# dsh-scientific-reading 技术路线文档（v0.2 定稿）

> 配套：`docs/design.md`（详细设计，含 CLI 契约、工具目录、gate 协议）。
> 本文是**执行路线图**：按阶段列出做什么、怎么做、怎么验收。
> 决策编号（D1…）供后续沟通引用。

---

## 1. 目标与原则

**目标**：把 [Scientific-Reading-for-Newbies](https://github.com/TyrionH-is-coding/Scientific-Reading-for-Newbies)
的完整文献工作流搬进 DSH，并**摒弃 Zotero Desktop**，让用户一句话完成
"下载 → 解析 → 入库 → 笔记"，在 DSH 对话栏的【文献】标签页里管理全部文献。

**原则**（全部沿用原项目纪律）：
1. **包装不重写**：解析/浅读/精读/飞书等引擎逻辑复用，只替换"存储/读回"层；
2. **确定性引擎 + agent 判断分离**：脚本不做歧义判断，agent 只在 gate 介入；
3. **合法优先**：默认只走合法来源（arXiv/OA/机构访问），灰色来源留开关（D1）；
4. **数据边界**：论文/笔记/任务状态全部在仓库外 `dataRoot`，插件不存数据；
5. **人工底线**：学校账号密码、验证码、MFA 只由用户输入；写飞书必须 preview + confirm。

---

## 2. 最终架构总览

```text
┌────────────────────────────────────────────────────────────┐
│ DSH 界面                                                    │
│  · 对话栏标签：对话 | 轨迹 | 【文献】(conversation.view slot)│
│  · 文献页三栏：左=分类/标签 · 中=论文表格 · 右=详情/操作      │
│  · 设置页：插件配置卡片（数据目录/学校/飞书密钥/开关）        │
├────────────────────────────────────────────────────────────┤
│ 插件（@dsh-external/dsh-scientific-reading）                │
│  · client：文献页 React 组件（dsh.client，Phase 2）          │
│  · host：sr_* 工具 + /sr/* 路由 + 设置 + cli.ts 适配器       │
│  · 引擎（pip 安装，位于独立 venv）：                        │
│     - scientific-reading（解析/浅读/精读/飞书/本地库）        │
│     - scansci-pdf（PDF 下载：OA/机构/CARSI/WebVPN）          │
├────────────────────────────────────────────────────────────┤
│ 数据层（`dataRoot`，仓库外）                               │
│  · library.sqlite     文献库（条目/标签/分类/全文索引）       │
│  · papers/<id>/       每篇论文全部产物（PDF/解析/笔记/HTML）  │
│  · jobs/<id>/         后台任务状态（断点续传）               │
│  · config/            飞书配置、scansci 配置                │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 关键技术决策

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | scansci-pdf 接入，**默认 `scihub_enabled=false`**（合法来源优先） | 原项目铁律"不绕过付费墙"；灰色来源留开关 |
| D2 | 文献库用 **SQLite + FTS5**，产物存磁盘文件 | Zotero 同款方案；搜索快；无网络依赖 |
| D3 | 【文献】= 对话栏**顶级标签页**（`conversation.view`, order: 20） | 已实测轨迹同款机制可行 |
| D4 | 引擎接入方式 = **CLI 子进程包装**（`python -m ...`） | 复用全部引擎逻辑；独立进程 + 磁盘状态，宿主重启不丢 |
| D5 | scansci-pdf 先走 CLI 包装；未来可切 `dsh-mcp-client` MCP 直连 | 当前安装版无 MCP 客户端装配；MCP 留作后路 |
| D6 | 学校认证 = scansci-pdf 真实浏览器登录（CARSI/WebVPN/Cookie），密码不经过插件 | 安全底线 |
| D7 | 飞书 = 自建应用密钥（App ID/Secret 仅由 DSH 宿主环境提供，preview + confirm 写） | 避免凭证进入插件设置或配置文件 |
| D8 | 引擎以 git submodule 锁版本；`sr_setup` 自动建 venv 安装 | 可复现 |
| D9 | Zotero 旧数据提供一次性迁移工具（Phase 3），默认不启用兼容层 | 平滑过渡 |

---

## 4. 数据模型草案（SQLite schema）

```sql
-- 条目（替代 Zotero items）
CREATE TABLE items (
  paper_id      TEXT PRIMARY KEY,   -- doi_xxx / pmid_xxx / title_xxx
  title         TEXT NOT NULL,
  authors_json  TEXT NOT NULL,      -- ["A","B"]
  doi           TEXT, pmid TEXT,
  year          INTEGER, journal TEXT,
  zotero_key    TEXT,               -- 迁移时保留旧 key
  status        TEXT NOT NULL,      -- library_ready/pdf_ready/parsed_fast/quick_read_ready/...
  created_at    TEXT, updated_at TEXT
);
-- 附件（PDF）
CREATE TABLE attachments (
  paper_id TEXT PRIMARY KEY REFERENCES items(paper_id),
  rel_path TEXT NOT NULL,           -- papers/<id>/source.pdf
  sha256   TEXT NOT NULL,
  size     INTEGER, validated_at TEXT
);
-- 标签 / 分类
CREATE TABLE tags (tag TEXT PRIMARY KEY);
CREATE TABLE item_tags (paper_id TEXT REFERENCES items(paper_id), tag TEXT REFERENCES tags(tag), PRIMARY KEY(paper_id, tag));
CREATE TABLE collections (collection_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE collection_items (collection_id TEXT, paper_id TEXT, PRIMARY KEY(collection_id, paper_id));
-- 全文索引（FTS5，搜 parsed/*/full.md 文本层）
CREATE VIRTUAL TABLE fulltext USING fts5(paper_id UNINDEXED, content);
-- 笔记/产物登记（只存路径与状态，内容在磁盘）
CREATE TABLE artifacts (
  paper_id TEXT, kind TEXT,          -- quick_read/full_read/parse
  rel_path TEXT, status TEXT, updated_at TEXT,
  PRIMARY KEY(paper_id, kind)
);
```

---

## 5. 认证方案

### 5.1 学校认证（Phase 0 提供登录工具）

| 方式 | 流程 | 何时用 |
|---|---|---|
| CARSI | 出版社页 → 选学校 → 学校统一认证页 → **用户登录** → 回跳 | 支持 CARSI 的高校（主流） |
| WebVPN | 学校 VPN 门户登录 → 下载走学校出口 | 校内 VPN 场景 |
| Cookie 提取 | 用户在自己浏览器登录 → 工具保存本地会话 cookie | 其他机构代理 |

插件职责：登录按钮（弹真实浏览器）、学校设置（`--school`）、会话健康检测（已登录/失效）。
用户职责：选学校、输账号、过验证码/MFA——密码只在浏览器页面内，插件不可见。

### 5.2 飞书（Phase 3）

1. 用户（一次性 5 分钟）：飞书开放平台建自建应用 → 拿 App ID/Secret → 开多维表格权限 → 建表并配置列；
2. 设置页填 ID/Secret（secret 字段，页面不回显）+ app_token/table_id/字段映射；
3. 插件：密钥只进子进程 env → 测试连接 → 零网络 preview → `confirm` 后幂等写入 → 读回比对。

---

## 6. 阶段路线图

### Phase 0 —— 下载段（scansci-pdf 接入）★ 当前开始

**任务清单**：
- [x] T0.1 插件工程骨架（package.json / tsconfig / build.sh / src）
- [x] T0.2 `config.ts`：dataRoot / python / scansciExe / school / legalOnly 等配置 + 校验
- [x] T0.3 `cli.ts`：子进程适配器（scansci-pdf 与 scientific-reading 两套 CLI 通用）
- [x] T0.4 `sr_setup`：检查/安装 scansci-pdf（pip/uv），探活
- [x] T0.5 `sr_scansci_fetch`：DOI/URL → PDF 落盘 + 元数据 JSON
- [x] T0.6 `sr_scansci_login`：机构登录（CARSI/WebVPN/Cookie）+ 会话检测
- [x] T0.7 构建 + 注入 DSH，工具可用（已注入并热重载验证）
- [x] T0.8 用开放论文实测下载成功（arXiv 10.48550/arXiv.1706.03762，full_text 命中）

**验收**：一篇 arXiv/OA 论文通过对话/工具实际下载到 `dataRoot`；登录工具可打开学校登录页；`sr_status` 显示引擎健康。（下载段已实测通过 ✅；登录工具待用户首次使用验证）

> Phase 0 实测记录（2026-08-21）：发现并修复 scansci-pdf 1.9.0 三个问题——
> ① 未配置机构时 Step 7 无条件弹浏览器并以空 URL 崩溃；② arXiv 源返回 key 为
> `file` 而 fetcher 读 `path`，PDF 落盘却永不认领；③ 中文 Windows 控制台 GBK
> 编码打印 JSON 报 UnicodeEncodeError。全部在插件自带垫片 `scripts/scansci_wrap.py`
> 内修复（未改扫描器安装），配置学校后走原逻辑。

### Phase 1 —— 文献库核心 + 闭环（替代 Zotero）

**任务清单**：
- [x] T1.1 引擎包新增 `library_service`（SQLite：§4 schema + CRUD + 查重 + FTS5）
- [x] T1.2 入库/读回改造：`zotero_ready → library_ready`；`pdf_ready` 读回改本地哈希校验
- [x] T1.3 工具改造：`sr_init`/查重/写入/PDF 登记 全部走本地库
- [x] T1.4 闭环：下载 → 校验 → 解析 → 浅读 → 笔记（原流程，读回改本地）
- [x] T1.5 断点恢复演练（独立 worker 跨父进程退出后可恢复读回）

**验收**：端到端演练（合成工科 PDF）：入库→下载→解析→浅读笔记 完成；全程零 Zotero。
（引擎侧已实测通过 ✅：library-ensure → pdf-attach → parse-paper → quick-read 到达 produce_quick_read gate，
全程零 Zotero；插件侧 sr_library_* 工具已注册并热重载。）

> Phase 1 实测记录（2026-08-21）：引擎新增 `library_service.py` + 4 个 CLI 命令
> （library-ensure[--check]/pdf-attach/library-list/library-search），389 测试通过；
> 插件新增 9 个工具（sr_init/sr_library_check/sr_library_ensure/sr_pdf_attach/
> sr_library_list/sr_library_search/sr_parse/sr_quick_read/sr_job_status）。
> 关键设计：library key（lib_xxx）写入 metadata.zotero_key 作为不透明 ID，
> 下游解析/浅读阶段零改动复用；确认机制：新建条目需 confirm=true（agent 先问用户）。

> T1.5 自动验收记录（2026-08-21）：`verify_restart_recovery.py` 使用真实
> `BackgroundLauncher` detached child、production `run_job`、job CLI 与 SQLite，
> 在临时数据根中证明启动父进程退出后仍可由新的 CLI 进程观察
> `running → completed → restart_probe_ready`。本验收没有重启用户当前 3080 DSH，
> 也不访问网络、真实论文或飞书；它验证所选 Python 运行时实际导入的引擎行为，
> 不等同于源码 commit 锁定。

### Phase 2 —— 文献标签页 UI（模拟 Zotero）

**任务清单**：
- [x] T2.1 client 模块注册 `conversation.view`（id: literature, order: 20, label: 文献；手写 ModuleLoader factory 格式，纯 DOM）
- [x] T2.2 三栏布局：左=搜索/筛选 · 中=论文表格（状态徽标/标题/年份/DOI）· 右=详情/笔记/操作
- [x] T2.3 页面动作直调宿主路由（下载/挂PDF/解析/浅读/打开笔记），"添加文献"（DOI/题名）走流水线
- [x] T2.4 设置卡片（settings.plugin.item，key=scientific-reading；纯 DOM 表单 + settingsScope 读写）

**验收**：对话栏出现【文献】标签；页面内完成 添加→下载→解析→浅读；重启无损；热重载即时生效。
（✅ 已通过 headless Chrome 真实浏览器验证：文献页 tab 渲染出论文表格，
设置页【插件】tab 渲染出"文献工作流设置"卡片（数据根目录/Python/学校/合法开关等字段）。
验证脚本 verify-live.mjs 已增强：校验 client 注册 id = 包名 + 组件为 React 桥接形式，
堵住"bundle 已服务但浏览器从未注册/渲染"的盲区。）

> 2026-08-21 实测：宿主 `webServer.register` 在重复 (kind,path) 时抛错——首版路由未挂
> ctx.effect 导致热重载残留死循环；已改 registerSafe（重复容忍 + effect 清理），
> 并补 tests/harness.mjs（挂载冒烟，含重复挂载回归）与 scripts/plugin-check.mjs（健康门禁）。

### Phase 3 —— 增强与收尾

- [x] 飞书 preview/sync 插件接入（sr_feishu_preview 零网络预览 + sr_feishu_sync 确认写；设置卡片只保存 feishuConfig 路径）
  （2026-08-21 实测：引擎 feishu-preview 对测试论文返回 preview_ready（payload_sha256 + dedupe_keys），
  sync 只继承 DSH 宿主启动时的 FEISHU_APP_ID/SECRET；配置真实 app_token/table_id 后走
  preview → confirm → sync 全链路。）
- [x] 精读全链路（sr_full_read 工具 + /sr/api/paper/<id>/full-read 路由 + 文献页精读按钮 + /sr/reader HTML 服务）
  （2026-08-21 实测：full-read 排队成功 → 后台准备 → waiting_agent（mineru_required_for_full_read），
  到达 agent gate 后提交 full-read-submit 批次 → reader_full.html 产出即由 /sr/reader 服务。
  同时修复历史遗留：job 状态路由原为 exact（/sr/api/job/<id> 永不命中），改 exact+prefix 双注册。）
- [x] Zotero 旧数据一次性迁移工具（引擎 zotero-migrate 命令 + 插件 sr_zotero_migrate 工具）
  （引擎：读 Zotero Desktop 本地 API 条目列表 → 批量 LibraryService.ensure_item 写入本地库，
  保留 zotero_key 不透明 ID（D9），--dry-run 只列不写；Zotero 未运行优雅报 zotero_unreachable。
  实测：dry-run 正确返回条目列表/连接拒绝；引擎 389 测试通过。真实迁移需用户本机运行 Zotero。）
- [ ] 可选：纯确定性部分 TS 移植（早期阶段脱离 Python）
- [ ] 文献页选型复核：better-sidebar 可装时做小 demo 对比（borrowed-ideas §3.1）
- [x] CI 冒烟 + 钉 DSH 版本（borrowed-ideas §4.3）

  （2026-08-21：已固定 `@deepseek-ai/dsh@0.1.0-rc.7` 测试基线、Node 22、
  Python 3.11 和 npm lockfile；Windows CI 自动执行 TypeScript/client 构建、
  DSH 兼容检查、挂载冒烟、飞书凭证边界、workflow 自检和 plugin-check。
  真实 DSH 读回与跨进程恢复继续作为本地集成门禁，不在无状态 CI 中运行。）
- [x] Profile Bundle 打包与隔离 profile 激活

  （2026-08-22：本机真实 DSH `0.1.0-rc.7` 验证返回 `profile_bundle_verified`，
  临时 profile `scientific-reading-test` 中唯一激活；用户 `.dsh/profiles` 验证前后均为
  156 个文件，逐文件路径、长度、mtime 与 SHA-256 差异为 0。）

---

## 7. DSH 集成点清单

| 集成点 | 机制 | 阶段 |
|---|---|---|
| 工具 | `ctx.tools.register(defineTool(...))`（@deepseek-ai/dsh-tools） | 0 |
| 设置 | `installSettingsSection(ctx, ns, Config, config, {...})` | 0 |
| 路由 | `ctx.webServer.register({kind, path, handler})`（/sr/*） | 1 |
| 标签页 | client 模块 `ctx.slots.inject('conversation.view', ...)` | 2 |
| 技能 | `skills/scientific-reading/SKILL.md`（会话 agent 操作手册） | 1 |
| 后台 | 引擎自带 worker 进程 + `jobs/<id>` 磁盘状态（不占用 DSH jobs） | 1 |

---

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| scansci-pdf 灰色来源误开 | 默认 `scihub_enabled=false`；设置页显式开关 + 首次启用提示 |
| 学校会话失效/IP 漂移 | 会话健康检测工具，明确提示"需重新登录"，不硬闯 |
| 飞书密钥泄露 | secret 字段只进 env；不进配置/日志/job；写前 preview |
| Python 环境缺失 | `sr_setup` 一键建 venv 安装；失败降级 `engine: missing` 不崩溃 |
| 引擎版本漂移 | submodule 锁 commit；升级显式进行 |
| 精读 token 成本 | 沿用 40 块/64 KiB 分批，提交即落盘可恢复 |

---

## 9. 里程碑检查点

- M0（Phase 0 完）：开放论文实际下载成功；登录工具可用；`sr_status` 健康
- M1（Phase 1 完）：零 Zotero 闭环（下载→解析→笔记）演练通过；重启无损
- M2（Phase 2 完）：【文献】标签页三栏可用；页面内完成全流程
- M3（Phase 3 完）：飞书/精读/迁移可用；文档与测试齐备
