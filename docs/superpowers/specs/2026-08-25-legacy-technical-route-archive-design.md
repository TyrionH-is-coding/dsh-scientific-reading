# 旧技术路线文档归档设计

## 1. 目标

清除两个仓库中仍把 Zotero 主库、九节式浅读、旧 reader 路径或旧阶段状态描述为当前方案的文档入口，同时保留历史设计和实施证据，便于追溯迁移原因。

本次只整理文档，不修改 Python/TypeScript 代码、SQLite、论文资产、persistent Profile、3080 或外部系统。

## 2. 文档权威顺序

整理后，当前运行合同按以下顺序解释：

1. 两个仓库根目录 `README.md`；
2. 插件 `docs/design.md`、`docs/features.md`、`docs/roadmap.md` 和 `docs/handoff-dsh-native.md`；
3. `2026-08-23-two-stage-literature-workflow-*` 两阶段/三阶段设计、计划和执行记录；
4. `2026-08-24-reader-html-*` 阅读器设计与计划；
5. `docs/archive/` 下的文件只用于历史追溯，不定义当前行为。

出现冲突时，代码和通过验收的当前 README 优先于归档文件。

## 3. 归档而非删除

### 3.1 插件仓库

以下原始文件进入 `docs/archive/pre-two-stage-plugin/`：

- `docs/design.md`、`docs/features.md`、`docs/roadmap.md`、`docs/handoff-dsh-native.md` 的旧版本；
- `docs/borrowed-ideas.md`；
- `docs/superpowers/` 中 2026-08-21、2026-08-22 的 specs/plans；
- `2026-08-23-live-qa-repair` 的 spec/plan。

四个稳定入口路径 `docs/design.md`、`docs/features.md`、`docs/roadmap.md`、`docs/handoff-dsh-native.md` 随后写入当前版本，避免外部链接失效。

以下文件保留在原位置：

- `2026-08-23-two-stage-literature-workflow-*`；
- `2026-08-24-reader-html-v2-1*`；
- `2026-08-24-reader-html-periodical-first*` 与演示计划。

### 3.2 Python 引擎仓库

以下文件进入 `docs/archive/legacy-zotero-workflow/`，保留原来的 plans/specs 子目录结构：

- `docs/superpowers/plans/` 与 `docs/superpowers/specs/` 当前全部旧阶段文件；
- 旧版 `docs/scansci-pdf-integration.md`。

`docs/scansci-pdf-integration.md` 在原路径重写为当前 provider 合同：ScanSci 只负责合法 PDF 候选，PDF 由精读 parent job 校验并登记到本地 generation，不再回挂或读回 Zotero。

根目录 `README.md` 和 `reader/README.md` 保留。后者描述当前仍被 `full_read_renderer.py` 调用的独立渲染组件，不能因路线归档而删除。

## 4. 当前入口文档的内容边界

### `docs/design.md`

只描述当前架构：DSH 插件是薄壳，Python 引擎拥有 SQLite、任务和资产合同；SQLite 是唯一事实来源；快速入库与按需精读是两个用户阶段；Zotero 仅作为旧字段兼容来源，不存在运行入口。

### `docs/features.md`

使用“已完成 / 当前限制”列出真实能力，不再保留 Phase 0、下一步、九节式笔记或模拟 Zotero 三栏等旧状态。

### `docs/roadmap.md`

把已完成的两阶段/三阶段基线压缩为一页，并只列仍未实现的独立后续范围：期刊正文优先 reader builder 迁移、首次获授权的真实飞书写入验收，以及明确不在当前范围的双向同步等事项。

### `docs/handoff-dsh-native.md`

记录当前仓库职责、构建/测试命令、真实 Bundle 门禁、数据边界和安全限制。删除易失效的旧 commit、工具数量、测试数量、飞书表记录数和旧论文状态快照。

## 5. 归档索引

两个仓库分别新增 `docs/archive/README.md`，说明：

- 归档原因和日期；
- 当前文档入口；
- 归档内容不得作为实现指令；
- 文件未被改写，必要时可通过 Git 历史追溯原路径。

根 README 或 `docs/README.md` 提供当前文档索引，不从当前导航直接链接到具体旧方案。

## 6. 验收标准

1. 当前入口文档不再声称 Zotero 是主库、需要 Zotero Desktop、生成九节式浅读，或使用 `reading/full/output/reader_full.html` 作为正式路径。
2. 当前入口统一描述正式 reader 为 `papers/<paper_id>/generations/<sha16>/reading/reader.html`，只读兼容回退为同 generation 的 `output/reader_full.html`。
3. 旧路线文件均位于明确命名的 `docs/archive/` 目录；历史内容不逐句改写。
4. 两仓库均有清晰的当前文档入口和归档说明，内部 Markdown 链接不存在断链。
5. 只产生文档差异；不运行真实飞书、机构认证或网络下载，不更新 persistent Profile，也不 push GitHub。
6. 两仓库通过 Markdown 链接检查、旧路线关键词门禁和 `git diff --check`。

## 7. 实施方式

在两个隔离 worktree 中完成移动和重写，分别使用中文 commit。验证通过后本地合并回各自 `main`，在 `main` 重跑文档门禁并清理本任务 worktree/分支。用户未跟踪的 `docs/survey.html` 及 reader v2.1 独立工作树保持不动。
