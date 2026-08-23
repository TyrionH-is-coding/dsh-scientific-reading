# Phase 1：主库与轻量入库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可迁移的 SQLite v2 主库，让单篇文献先快速出现，再异步补齐题录、Abstract 英中对照、XLSX 与飞书；同时完成文件夹、标签、分页和可撤销批量归类的领域契约。

**Architecture:** Python 引擎先提交本地事务并返回，再由插件启动轻量派生任务。主库不等待网络或 AI；Abstract 翻译通过明确的 agent gate；XLSX 与飞书失败只记录派生状态。旧 Zotero 字段只读兼容，不再参与运行链路。

**Tech Stack:** Python 3.11、SQLite/FTS5、urllib、openpyxl、pytest；TypeScript、DSH tools/web server、Node 合同测试。

---

## 前置假设与成功条件

1. 两个仓库当前 `main` 是本阶段基线；若工作树不干净，保留用户改动并建立独立 worktree。
2. 本阶段不删除旧 `quick_read.*`、Zotero 模块和测试；只停止新入口调用它们。物理删除延后到 Phase 3 的迁移验收，避免一次改动过大。
3. 只为稳定标识执行确定性题录补全：DOI、PMID、arXiv。只有题名时不做模糊网络搜索；使用用户/agent 已提供题录，Abstract 缺失则标记待补。
4. 默认 HTTP provider 只取题录和 Abstract，不下载全文；测试全部注入 fake provider。
5. 旧飞书 `zotero_key` 映射列可以继续承载本地 `library_key`，但新模板和内部逻辑统一叫 `library_key`。

完成的可验证定义：

- DOI 骨架记录的 SQLite 事务在本机隔离基准中小于 5 秒，返回前不发生 HTTP、AI、XLSX 或飞书调用；
- schema v1 可备份并迁移到 v2，现有文件路径和资产记录不变；
- Abstract 英中段落严格一一对应，无原文时不生成译文；
- XLSX 和飞书均可失败/重试而不改变本地入库成功；
- 文件夹、标签、分页、100 篇分块与批量归类撤销具备测试。

## Task 1：建立 SQLite v2 迁移与可恢复备份

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_schema.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_service.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_library_migration_v2.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_library_service.py`

- [ ] **Step 1: 写迁移失败测试**

在测试中手工建立当前 v1 schema 和一个既有条目，外加 PDF/HTML/旧浅读路径。覆盖：

```python
def test_v1_is_backed_up_and_migrated_without_moving_assets(tmp_path): ...
def test_backup_is_a_readable_sqlite_database(tmp_path): ...
def test_exactly_one_legacy_collection_becomes_primary_folder(tmp_path): ...
def test_multiple_legacy_collections_remain_unclassified_and_are_reported(tmp_path): ...
def test_failed_migration_restores_readable_v1_database(tmp_path, monkeypatch): ...
```

运行：

```powershell
$env:PYTHONPATH = "$PWD\src"
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_library_migration_v2.py -q
```

预期：因 `scientific_reading.library_schema` 不存在而失败。

- [ ] **Step 2: 实现最小 schema v2**

`library_schema.py` 暴露：

```python
@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_version: int
    to_version: int
    backup_path: Path | None
    warnings: tuple[str, ...]

def migrate_library(data_root: Path) -> MigrationResult: ...
```

迁移规则：

- 使用 `PRAGMA user_version`；现有无版本数据库按 v1 处理；目标为 v2。
- 迁移前使用 `sqlite3.Connection.backup()` 写入
  `backups/library-<UTC时间>-v1.sqlite3`，重新连接并执行 `PRAGMA integrity_check`。
- `items` 新增：`abstract_en`、`abstract_zh`、`abstract_status`、`folder_id`、
  `full_read_status`、`active_job_id`、`last_error`、`feishu_sync_state`、
  `feishu_record_id`、`feishu_record_url`、`feishu_error`、`xlsx_sync_state`、
  `xlsx_error`。字符串字段用空字符串或明确状态，不使用魔法 JSON。
- 新建 `folders(folder_id, name UNIQUE, created_at, updated_at)`、
  `batch_operations(operation_id, kind, before_json, after_json, created_at, undone_at)`、
  `library_meta(key PRIMARY KEY, value)`。
- 旧 `collection_items` 只有一个归属时迁入主文件夹；多个归属时 `folder_id=NULL`，在
  `library_meta.migration_warnings` 记录 paper_id，不静默选择。
- 保留旧 `collections`/`collection_items` 表供只读审计，本阶段不删除。
- 任一步失败：关闭连接、用已验证 backup 恢复，再抛出原错误；不删除 papers 目录。

- [ ] **Step 3: 在 `LibraryService` 打开数据库前执行迁移**

`LibraryService.__init__` 先调用 `migrate_library(data_root)`，再连接并启用外键。重复打开 v2
不得再次备份或执行 `ALTER TABLE`。

- [ ] **Step 4: 运行测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_library_migration_v2.py tests/test_library_service.py -q
git diff --check
git add src/scientific_reading/library_schema.py src/scientific_reading/library_service.py tests/test_library_migration_v2.py tests/test_library_service.py
git commit -m "主库：加入可恢复的SQLite v2迁移"
```

## Task 2：稳定身份、骨架入库与快速返回

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\identifiers.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_library_ingest_v2.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_identifiers.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_benchmark_fast_path.py`

- [ ] **Step 1: 写身份与性能失败测试**

覆盖：

```python
def test_doi_only_creates_skeleton_without_calling_network_or_ai(...): ...
def test_same_normalized_doi_reuses_item(...): ...
def test_same_title_year_author_reuses_only_when_unambiguous(...): ...
def test_ambiguous_title_does_not_merge(...): ...
def test_legacy_zotero_key_is_read_as_library_key_but_never_written_for_new_item(...): ...
def test_local_ingest_returns_under_five_seconds(...): ...
```

基准测试必须通过 spy 证明返回前没有调用 provider、XLSX 或飞书，而不只测墙钟时间。

- [ ] **Step 2: 扩展元数据契约**

`PaperMetadata` 新增向后兼容字段：

```python
library_key: str | None = None
abstract_en: str | None = None
abstract_zh: str | None = None
source_url: str | None = None
zotero_key: str | None = None  # 仅用于读取旧 metadata.json
```

`from_dict()` 使用 `library_key or zotero_key` 恢复旧数据；`to_dict()` 对新记录只写
`library_key`，只有输入本身含旧值且处于迁移读回时才保留 `legacy_zotero_key` 审计信息。

- [ ] **Step 3: 实现 `LibraryService.ingest()`**

接口：

```python
def ingest(self, metadata: PaperMetadata) -> dict[str, Any]:
    """仅做规范化、查重和本地事务，不做任何外部 I/O。"""
```

返回至少包含：

```json
{
  "paper_id": "doi_10.48550_arxiv.1706.03762",
  "library_key": "...",
  "created": true,
  "dedupe": "doi",
  "folder_id": null,
  "user_status": "生成浅读",
  "derived_updates": ["metadata_enrichment", "xlsx_snapshot"]
}
```

只有 DOI 的骨架记录允许题名暂空；列表显示时由调用方回退为 DOI，并标记“补齐题录中”。
不得把 DOI 字符串永久写成伪题名。

- [ ] **Step 4: CLI 增加 `library-ingest`，保留旧 `library-ensure` 兼容入口**

`library-ingest` 接受 metadata JSON 文件或 stdin，stdout 只输出一个 JSON。旧
`library-ensure` 转调新服务并输出 deprecation 字段，不再写 `metadata.zotero_key`。

- [ ] **Step 5: 运行测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_library_ingest_v2.py tests/test_identifiers.py tests/test_benchmark_fast_path.py tests/test_cli.py -q
git add src/scientific_reading/models.py src/scientific_reading/identifiers.py src/scientific_reading/library_service.py src/scientific_reading/__main__.py tests/test_library_ingest_v2.py tests/test_identifiers.py tests/test_benchmark_fast_path.py tests/test_cli.py
git commit -m "入库：先提交本地主库骨架记录"
```

## Task 3：文件夹、标签、分页与可撤销归类

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\library_service.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\classification_service.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_library_navigation.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_classification_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_cli_library_navigation.py`

- [ ] **Step 1: 写领域失败测试**

覆盖：主文件夹单归属、标签多归属、`folder_id=None` 对应待归类、全文搜索、稳定排序、分页、
低置信度不移动、默认不得创建新文件夹、100 条分块和一次完整撤销。

分页接口合同固定为：

```python
service.list_items(
    page=1,
    page_size=50,
    query="transformer",
    folder_id=None,       # None=不限定；"__unclassified__"=待归类
    tags=("NLP",),
    status="待精读",
    recent_days=None,
)
# -> {"items": [...], "page": 1, "page_size": 50, "total": 1}
```

- [ ] **Step 2: 实现最小文件夹/标签 API**

`LibraryService` 增加：

```python
create_folder(name: str) -> dict
rename_folder(folder_id: str, name: str) -> dict
list_folders() -> list[dict]
move_items(paper_ids: Sequence[str], folder_id: str | None) -> dict
add_tags(paper_ids: Sequence[str], tags: Sequence[str]) -> dict
remove_tags(paper_ids: Sequence[str], tags: Sequence[str]) -> dict
list_items(...) -> dict
```

删除文件夹不在本阶段 UI 范围；若为测试提供底层删除，只能把条目置为待归类，不删条目/资产。

- [ ] **Step 3: 实现确定性归类应用器和撤销**

AI 只提交提案，服务只校验并应用：

```python
@dataclass(frozen=True, slots=True)
class ClassificationProposal:
    paper_id: str
    folder_name: str | None
    tags: tuple[str, ...]
    confidence: float

ClassificationService.apply(
    proposals,
    minimum_confidence=0.70,
    allow_new_folders=False,
) -> BatchOperationResult

ClassificationService.undo(operation_id: str) -> BatchOperationResult
```

低于阈值或文件夹不存在时保持原值，并在结果列出 `skipped`；撤销使用数据库中保存的
before/after JSON，在一个事务中还原整个 operation。一个内部 chunk 最多 100，父调用汇总。

- [ ] **Step 4: 加入 CLI 并验证**

增加 `library-list-v2`、`folder-list/create/rename`、`classification-apply/undo`。所有批量输入
使用 JSON 文件/stdin，避免 PowerShell 转义中文路径和大 payload。

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_library_navigation.py tests/test_classification_service.py tests/test_cli_library_navigation.py -q
git add src/scientific_reading/library_service.py src/scientific_reading/classification_service.py src/scientific_reading/__main__.py tests/test_library_navigation.py tests/test_classification_service.py tests/test_cli_library_navigation.py
git commit -m "主库：加入文件夹标签与可撤销归类"
```

## Task 4：Abstract 题录补全与英中浅读

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\metadata_enrichment.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\abstract_read_models.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\abstract_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\worker.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_metadata_enrichment.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_abstract_read.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_worker_abstract_read.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_cli_abstract_read.py`

- [ ] **Step 1: 写 provider 与翻译契约失败测试**

使用虚构工科题录和固定 Abstract，覆盖 DOI/PMID/arXiv provider 注入、超时、HTML 清理、
Abstract 缺失、段落一一对应、源摘要哈希改变导致旧译文 stale、worker agent gate 与恢复。

翻译契约固定为：

```json
{
  "contract_version": "abstract-translation-v1",
  "source_sha256": "...",
  "paragraphs": [
    {"index": 0, "source_en": "...", "translation_zh": "..."}
  ]
}
```

- [ ] **Step 2: 实现确定性题录 provider**

定义可注入协议，不允许服务内部硬编码测试网络：

```python
class MetadataProvider(Protocol):
    def fetch(self, metadata: PaperMetadata) -> EnrichedMetadata | None: ...
```

默认 registry 只按稳定标识调用 Crossref DOI、NCBI PMID、arXiv API；使用标准库
`urllib.request`、5 秒超时、明确 User-Agent。只取题录/Abstract，绝不下载 PDF。失败返回结构化
错误并留待重试；只有题名时不搜索。

- [ ] **Step 3: 实现 `AbstractReadService`**

- 英文原文按空行和 HTML 段落规范化，保留顺序；不对内容做总结。
- 无 Abstract：`abstract_status=missing`，不触发翻译 gate，不创建伪文本。
- 有英文无中文：worker 返回 `AgentRequired("translate_abstract", required_input)`。
- 发布时校验 `source_sha256`、索引连续、source_en 精确匹配；原子写
  `papers/<paper_id>/reading/abstract_read.json` 并更新 SQLite。
- 旧 `quick_read.json/md` 不修改、不覆盖；新入口只读 `abstract_read.json`。

- [ ] **Step 4: 注册 `metadata_enrichment` 与 `abstract_read` worker/CLI**

重复提交返回现有完成结果；宿主重启后从已写入英文 Abstract 或已完成段落继续。不要让新
handler 调用 `QuickReadService` 或要求 MinerU。

- [ ] **Step 5: 运行测试并提交**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_metadata_enrichment.py tests/test_abstract_read.py tests/test_worker_abstract_read.py tests/test_cli_abstract_read.py -q
git add src/scientific_reading/metadata_enrichment.py src/scientific_reading/abstract_read_models.py src/scientific_reading/abstract_read_service.py src/scientific_reading/worker.py src/scientific_reading/__main__.py tests/test_metadata_enrichment.py tests/test_abstract_read.py tests/test_worker_abstract_read.py tests/test_cli_abstract_read.py
git commit -m "浅读：改为Abstract逐段英中对照"
```

## Task 5：只读 XLSX 快照

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\pyproject.toml`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\xlsx_snapshot.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_xlsx_snapshot.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_cli_xlsx.py`

- [ ] **Step 1: 先写快照失败测试**

覆盖列顺序、全部页数据、中文 UTF-8、只读说明 sheet、临时文件原子替换、`os.replace`
抛 `PermissionError` 时保留旧文件并把 SQLite 标记 `pending`、释放后重试成功。

- [ ] **Step 2: 添加最小依赖**

在 runtime dependencies 加：

```toml
"openpyxl>=3.1,<4",
```

不要引入 pandas。

- [ ] **Step 3: 实现 `XlsxSnapshotService`**

输出固定为 `<data_root>/library/scientific-reading.xlsx`。系统字段列顺序：文献名、作者、主要
研究单位、年份、期刊、影响因子、学科领域、主要内容、解决方法、实验假设、创新、不足之处、
文献链接、DOI、PMID、文献 ID、主文件夹、标签、Abstract (EN)、Abstract (ZH)、阅读状态、
PDF 路径、精读 HTML、图表资产路径、飞书链接、创建时间、更新时间。

用户只在飞书维护的个人思考/理解程度不进入 XLSX，避免制造一个不完整的伪副本。第一个
sheet 为“文献”，第二个为“说明”，明确“只读派生快照，修改不会回写”。

流程：查询 SQLite → 写同目录临时 `.xlsx` → `fsync` → `os.replace`。被占用时更新
`library_meta.xlsx_pending=1` 和错误码，不抛到入库调用方。

- [ ] **Step 4: 增加 `xlsx-refresh` CLI 并验证**

```powershell
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_xlsx_snapshot.py tests/test_cli_xlsx.py -q
git add pyproject.toml src/scientific_reading/xlsx_snapshot.py src/scientific_reading/__main__.py tests/test_xlsx_snapshot.py tests/test_cli_xlsx.py
git commit -m "快照：从SQLite原子生成只读XLSX"
```

## Task 6：飞书自动启用与字段所有权

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\feishu_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\feishu_builder.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\feishu_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\worker.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\derived_updates.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\__main__.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_feishu_auto_sync.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_feishu_builder.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_worker_feishu.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_cli_feishu_sync.py`

- [ ] **Step 1: 清空真实凭证并写失败测试**

每个测试用 `monkeypatch.delenv` 清空两项凭证。fake client 记录调用但不联网。覆盖：

```python
def test_missing_any_enablement_part_disables_auto_sync(...): ...
def test_first_enable_records_epoch_without_scheduling_history(...): ...
def test_new_item_after_enable_is_scheduled(...): ...
def test_changed_system_field_is_scheduled_but_personal_field_is_never_sent(...): ...
def test_stored_record_id_is_preferred_for_update(...): ...
def test_v1_zotero_mapping_accepts_local_library_key(...): ...
def test_sync_success_persists_record_id_and_url(...): ...
def test_sync_failure_leaves_local_item_complete_and_pending(...): ...
def test_secret_is_absent_from_logs_jobs_database_and_result(...): ...
```

- [ ] **Step 2: 固定字段所有权白名单**

在 `feishu_models.py` 定义显式集合：

```python
SYSTEM_MANAGED_FIELDS = frozenset({...})
USER_MANAGED_FIELDS = frozenset({
    "personal_thoughts", "understanding_level", "user_notes"
})
```

builder 只能遍历 `SYSTEM_MANAGED_FIELDS & config.field_map.keys()`；即使调用方 payload 带用户
字段也拒绝/丢弃并记录测试可见原因。新逻辑字段是 `library_key`；若 v1 config 只有
`zotero_key`，把同一本地 key 映射到该列，不发起 Zotero 调用。

新 Abstract 字段取 `abstract_read.json`/SQLite；旧九节式 `quick_read` 和 `key_figures` 不再写入
新自动同步 payload。精读字段只有 `full_read_status=completed` 后才构建。

- [ ] **Step 3: 实现启用策略与调度**

`derived_updates.py` 暴露：

```python
class FeishuAutoSyncPolicy:
    def probe(self, config_path: Path | None) -> Enablement: ...
    def initialize(self, config_path: Path) -> Enablement: ...
    def mark_system_change(self, paper_id: str) -> None: ...
    def pending(self, paper_ids: Sequence[str] | None = None) -> list[str]: ...
```

启用条件必须同时满足：两个非空环境变量、仓库外绝对配置、配置合同有效。首次
`initialize()` 只写 `feishu_auto_activated_at`，不遍历历史 items。以后只有启用状态下发生的
system change 标为 pending。显式“同步所选/全部待同步”才扫描用户选择或 pending 集合。

worker 不再要求逐篇 UI `confirm=true`；自动请求必须带引擎内部生成的
`write_mode="configured_auto"` 和 activation revision。任意外部裸请求仍拒绝，防止绕过启用策略。

- [ ] **Step 4: 保存同步结果而不污染本地主状态**

成功后写 `feishu_record_id`、可用 record URL、`feishu_sync_state=synced`；失败写 pending/error。
不得修改 `full_read_status` 或本地完成状态。

- [ ] **Step 5: 运行测试并提交**

```powershell
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest tests/test_feishu_auto_sync.py tests/test_feishu_builder.py tests/test_worker_feishu.py tests/test_cli_feishu_sync.py -q
git add src/scientific_reading/feishu_models.py src/scientific_reading/feishu_builder.py src/scientific_reading/feishu_service.py src/scientific_reading/worker.py src/scientific_reading/derived_updates.py src/scientific_reading/__main__.py tests/test_feishu_auto_sync.py tests/test_feishu_builder.py tests/test_worker_feishu.py tests/test_cli_feishu_sync.py
git commit -m "飞书：按环境配置自动同步系统字段"
```

## Task 7：接入 DSH 工具与轻量 API

**Files:**

- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\cli.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\library_tools.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\routes.ts`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\src\papers.ts`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\two-stage-ingest.mjs`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\library-navigation-api.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\harness.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\feishu-env-only.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\package.json`

- [ ] **Step 1: 写插件失败合同**

用 fake engine executable 验证：

- `sr_ingest` 在收到 `library-ingest` JSON 后立即返回，不等待派生进程；
- 派生调用只在返回后启动 `metadata-enrich-submit`、`abstract-read-submit`、`xlsx-refresh`，飞书仅在
  probe enabled 时启动；
- `sr_library_list` 支持 page/page_size/query/folder/tags/status；
- `sr_classification_apply/undo` 使用 JSON stdin；
- HTTP `/sr/api/library`、`/sr/api/folders`、`/sr/api/abstract/<paper_id>` 返回稳定 JSON；
- 所有 paper_id 规则接受新 `library_`/既有 DOI 等 ID，但拒绝路径穿越。

运行：

```powershell
npm run build:ci
node tests/two-stage-ingest.mjs
node tests/library-navigation-api.mjs
```

预期：新工具/路由尚不存在而失败。

- [ ] **Step 2: 实现最小 CLI 适配**

复用现有 Python 启动与 JSON 解析，不建立第二套 domain model。新增：

```ts
engineJson(config, args, input?)
engineStartDetached(config, args, input?)
```

stdin 用临时 UTF-8 JSON 文件或流，结束后清理；日志不得输出环境变量值。

- [ ] **Step 3: 注册新工具**

普通 agent 工具：`sr_ingest`、`sr_library_list`、`sr_folder_manage`、
`sr_classification_apply`、`sr_classification_undo`、`sr_feishu_resync`、`sr_job_status`。

保留旧底层工具供 Phase 2/迁移测试，但在 description 标为 legacy/internal，不让新 UI 调用。
`sr_feishu_preview` 和逐篇 confirm 不进入新流程。

- [ ] **Step 4: 实现轻量 JSON API**

路由只做 method/body/path 校验和 engine 转发。写操作限制 JSON body 大小；批量最多接受一个
用户父请求，引擎负责拆成 100。任何错误用稳定 `{error, detail?}`，不返回堆栈或 secret。

- [ ] **Step 5: 把派生任务放到响应之后**

`sr_ingest`/POST route 先发送本地 ingest 结果，再排 metadata/abstract/XLSX；飞书先 probe。派生
启动失败写日志/SQLite pending，但已经发送的本地成功不变。不得用 `await` 等待网络任务。

- [ ] **Step 6: 运行插件测试并提交**

```powershell
npm run typecheck
node tests/two-stage-ingest.mjs
node tests/library-navigation-api.mjs
node tests/harness.mjs
node tests/feishu-env-only.mjs
git diff --check
git add src/cli.ts src/library_tools.ts src/routes.ts src/papers.ts tests/two-stage-ingest.mjs tests/library-navigation-api.mjs tests/harness.mjs tests/feishu-env-only.mjs package.json
git commit -m "插件：接入快速入库与轻量主库接口"
```

## Task 8：Phase 1 集成验收与阶段提交

**Files:**

- Create: `D:\Vibe Coding\dsh-scientific-reading\scripts\verify_two_stage_foundation.py`
- Create: `D:\Vibe Coding\dsh-scientific-reading\tests\foundation-integration.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\package.json`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\README.md`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\README.md`

- [ ] **Step 1: 写离线端到端 verifier**

使用临时 data root、虚构论文《A Deterministic Scheduling Method for Small Workshops》、固定 Abstract、
fake translation 和 fake Feishu。顺序验证：骨架出现 → 后台题录/Abstract → XLSX → fake 飞书 →
移动文件夹/标签 → 批量撤销。输出一行 JSON 总结，并在 `finally` 清理临时进程/目录。

- [ ] **Step 2: 验证飞书和当前 Profile 未被触碰**

verifier 强制清空凭证并拒绝非 localhost/fake base URL。执行前后记录当前 Profile 插件 tarball SHA
和 3080 健康状态；两者应不变。

- [ ] **Step 3: 更新中文 README**

只写已完成能力、运行方式、数据所有权和本阶段限制；不要把 Phase 2/3 写成已完成。明确 XLSX
只读、飞书个人字段不回写、Zotero 新流程已停用。

- [ ] **Step 4: 全量验证**

引擎：

```powershell
$env:PYTHONPATH = "$PWD\src"
& "$env:USERPROFILE\scientific-reading-data\.venv\Scripts\python.exe" -m pytest -q
git diff --check
```

插件：

```powershell
npm run typecheck
npm run test:offline
node tests/foundation-integration.mjs
git diff --check
```

预期：引擎全量无失败；插件全量无失败；没有真实网络写入；当前 3080 与安装包 SHA 不变。

- [ ] **Step 5: 提交文档和 verifier**

```powershell
git add README.md scripts/verify_two_stage_foundation.py tests/foundation-integration.mjs package.json
git commit -m "验收：补全两段式入库离线验证"
```

## Phase 1 执行记录

实现 agent 在完成后追加：两个 worktree/分支、基线与完成 commit、测试数量/结果、性能分位数、
迁移备份读回结果、以及未进入 Phase 2 的已知限制。不得写真实飞书 ID 或个人文献内容。
