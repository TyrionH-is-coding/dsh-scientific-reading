# Reader 快速审核闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before any completion claim.

**Goal:** 建立一个固定、只读、5–10 秒级的 `reader.html` 审核闭环，让开发者在同一 URL 比较 baseline/candidate、切换三种视口和三类案例，并在用户认可后运行离线代表性验收与隔离 DSH 实机验收。

**Architecture:** 在生产 `FullReadRenderer` 上增加一个窄的“可信完成资产 → 显式预览输出”边界；仓库外的临时审核会话保存 baseline、candidate 和原子 manifest；Node 内置 HTTP 服务只监听 loopback 并通过白名单提供审核页。快速循环只消费缓存资产，不调用 MinerU、LLM、飞书或认证；真实 DSH 仅在独立验收命令中用临时 Profile 和真实 tarball 启动。

**Tech Stack:** Python 3.11、现有 `scientific_reading` 引擎、Node.js 22 内置模块、原生 HTML/CSS/JavaScript、pytest、Node `assert` 测试、npm scripts、DSH CLI。

---

## 0. 实施不变量与成功标准

本计划落实 [Reader 快速预览、审核与反馈闭环设计](../specs/2026-09-02-reader-review-loop-design.md)，实施时不得改变以下边界：

1. 正式 generation 全程只读；不得覆盖正式 `reading/reader.html`、`reader-manifest.json`、`package-manifest.json` 或来源资产。
2. 快速路径不得联网，不得调用 MinerU API、LLM、飞书或机构认证。
3. baseline 只在新建审核会话时捕获；普通重渲染只原子替换 candidate。
4. 审核服务只监听 `127.0.0.1`；不得杀死占用 8895 的未知进程。
5. Windows 后台进程必须无可见终端窗口。
6. 新增审核脚本、审核 UI、fixture 和临时资产均不得进入 npm tarball。
7. 不引入新的生产依赖、浏览器下载、Playwright、Electron、WebSocket 或文件 watcher。
8. 第一版只覆盖 reader；不顺手修改 DSH 文献库、设置页、下载、MinerU provider 或论文管理。
9. 当前 `main` 有其他在途改动。执行代码前必须从包含所需上游改动的干净 commit 建立隔离 worktree；不得直接在脏 `main` 写代码或提交他人文件。
10. 所有提交信息使用中文，并保持每个提交可独立回退。

最终验收需要同时证明：

- `npm run reader:review -- --case formula-outline --new-session` 能启动/复用固定审核页；
- 对一个本机完成论文重渲染时，正式 generation 的逐文件 SHA-256 前后完全一致；
- baseline/candidate、三种视口和三个案例可切换；
- candidate 失败时保留上一个成功版本并显示 `stale/failed`；
- `npm run reader:acceptance` 在清空外部凭证后离线完成；
- `npm run acceptance:dsh` 使用真实 tarball、临时 Profile/data root 和正式 `/sr/reading/{paper_id}` 路由；
- `npm pack --dry-run --json` 不包含任何审核开发文件；
- 浏览器 Comment 指向当前 candidate revision；
- 修改 CSS 后的真实本机快速循环记录目标 5–10 秒，并如实报告实测值。

## 1. 固定的数据合同

### 1.1 审核目录

默认根目录由 `os.tmpdir()` / `tempfile.gettempdir()` 推导：

```text
%TEMP%/dsh-scientific-reading-review/
├─ session.json
├─ review-manifest.json
├─ server.json
├─ baseline/
│  ├─ formula-outline/reader.html
│  ├─ superscript-text/reader.html
│  └─ figures-captions/reader.html
├─ candidate/
│  ├─ formula-outline/reader.html
│  ├─ superscript-text/reader.html
│  └─ figures-captions/reader.html
└─ evidence/
   └─ acceptance-dsh/
```

真实论文的 case key 使用经过严格校验的 `paper_id`，仅允许 `[A-Za-z0-9._-]`，不得把任意路径片段当 case key。

### 1.2 `session.json`

```json
{
  "contract_version": "reader-review-session-v1",
  "session_id": "32位小写十六进制",
  "repository_root": "D:/Vibe Coding/dsh-scientific-reading",
  "baseline_commit": "40位 Git SHA",
  "created_at": "ISO-8601 UTC",
  "selected_case": "formula-outline",
  "cases": {
    "formula-outline": {
      "kind": "fixture",
      "fixture": "review/fixtures/formula-outline.json",
      "source_generation": null,
      "source_reader_sha256": "64位小写十六进制"
    }
  }
}
```

真实案例的 `source_generation` 必须是规范化后的绝对路径，并同时记录：

- `paper_id`；
- generation 相对 data root 的路径；
- `source_pdf_sha256`；
- 正式 `reader-manifest.json` 的 SHA-256；
- 正式 reader 的 SHA-256。

### 1.3 `review-manifest.json`

```json
{
  "contract_version": "reader-review-manifest-v1",
  "revision": 4,
  "status": "ready",
  "candidate_stale": false,
  "repository_commit": "40位 Git SHA",
  "built_at": "ISO-8601 UTC",
  "selected_case": "formula-outline",
  "cases": {
    "formula-outline": {
      "baseline_url": "/content/baseline/formula-outline/reader.html",
      "candidate_url": "/content/candidate/formula-outline/reader.html?revision=4",
      "candidate_sha256": "64位小写十六进制",
      "render_status": "passed",
      "error_code": null,
      "timings_ms": {
        "source_load": 12,
        "render": 418,
        "write": 7,
        "total": 437
      }
    }
  },
  "tests": {
    "status": "passed",
    "passed": 24,
    "failed": 0,
    "summary": "reader 定向测试通过"
  },
  "browser_qa": {
    "status": "pending",
    "checks": [
      {"id": "desktop", "label": "桌面布局", "status": "pending"},
      {"id": "tablet", "label": "平板布局", "status": "pending"},
      {"id": "mobile", "label": "手机布局", "status": "pending"}
    ]
  }
}
```

`status` 只允许 `building | ready | failed`。candidate 构建失败时：

- 增加 manifest `revision`；
- `status=failed`、`candidate_stale=true`；
- 保留上一次成功 candidate 文件和 SHA；
- 记录稳定错误码和简短错误，不把绝对秘密或环境变量写入 manifest。

### 1.4 审核 HTTP 路由

只允许：

```text
GET /review
GET /review/index.html
GET /health
GET /api/review-manifest
GET /content/baseline/{case}/reader.html
GET /content/candidate/{case}/reader.html
```

其他方法返回 `405`；其他路径返回 `404`。`/content` 只服务经 manifest 登记的两个 HTML 路径；不提供任意目录浏览。

## Task 1: 建立隔离实施工作树与基线证据

**Files:**

- Create: `docs/superpowers/executions/2026-09-02-reader-review-loop.md`
- Do not modify: 当前脏 `main` 中尚未归属本任务的任何文件

**Step 1: 确认主工作树状态和本任务依赖提交**

在主仓库运行：

```powershell
. "$env:USERPROFILE\.codex\scripts\Enter-CodexUtf8.ps1"
git status --short --branch
git log --oneline -12
git diff --name-only
git ls-files --others --exclude-standard
```

Expected: 明确列出所有现有脏文件；不得把它们误认为本任务产生。

**Step 2: 选择干净基线并建立 worktree**

只有在本任务依赖的 renderer/highlighter/单仓库改动都已经成为可引用 commit 后执行；先把当时的 `main` 记录为固定基线：

```powershell
$BaselineSha = git rev-parse main
git worktree add ".worktrees/reader-review-loop" -b "feature/reader-review-loop" $BaselineSha
git -C ".worktrees/reader-review-loop" status --short --branch
```

Expected: 新 worktree 为干净状态；若必要上游改动仅存在于脏工作树，停止编码并先让其所有者形成独立 commit，不复制未提交文件。

**Step 3: 写执行记录头部**

记录：基线 SHA、worktree 路径、主工作树脏文件清单、Node/Python/DSH 版本、开始时间。执行记录只追加本任务事实，不复制设计文档。

**Step 4: 基线测试**

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m pytest -q engine/tests/test_full_read_renderer.py engine/tests/test_reader_interactions.py engine/tests/test_reader_content_folding.py engine/tests/test_reader_citations.py
node tests/package-contents.mjs
```

Expected: 全部通过。若失败，记录为基线缺陷并先判断是否阻断本功能，不静默修改无关代码。

**Step 5: 提交执行记录**

```powershell
git add docs/superpowers/executions/2026-09-02-reader-review-loop.md
git commit -m "记录：建立 Reader 审核闭环实施基线"
```

## Task 2: 增加只读的完成资产预览渲染边界

**Files:**

- Modify: `engine/src/scientific_reading/full_read_renderer.py`
- Create: `engine/tests/test_reader_preview.py`

**Step 1: 写失败测试——预览输出不改变正式 generation**

在 `test_reader_preview.py` 复用现有完成 full-read fixture 构造方式，添加：

```python
def test_render_preview_completed_writes_only_explicit_output(
    completed_workspace: PaperWorkspace,
    tmp_path: Path,
) -> None:
    before = tree_hashes(completed_workspace.root)
    output = tmp_path / "review" / "reader.html"

    result = FullReadRenderer().render_preview_completed(
        completed_workspace,
        output=output,
        paper_id="fixture_formula_outline",
    )

    assert result == output
    assert output.is_file()
    assert tree_hashes(completed_workspace.root) == before
```

`tree_hashes` 只在测试内计算普通文件的相对路径和 SHA-256；不得跟随 symlink。

**Step 2: 写失败测试——复用完整性校验**

添加以下行为：

```python
def test_render_preview_completed_rejects_tampered_translation(...):
    tamper_json(workspace.reading_dir / "full" / "translations.json")
    with pytest.raises(ValueError, match="translation_manifest_invalid"):
        renderer.render_preview_completed(...)

def test_render_preview_completed_rejects_stale_reader_identity(...):
    workspace_job_with_stale_reader_revision(...)
    with pytest.raises(ValueError, match="translation_manifest_invalid"):
        renderer.render_preview_completed(...)
```

**Step 3: 运行测试确认 RED**

```powershell
python -m pytest -q engine/tests/test_reader_preview.py
```

Expected: 因 `render_preview_completed` 不存在而失败；不是 fixture 自身错误。

**Step 4: 提取最小可信输入加载函数**

在 `FullReadRenderer` 内把 `_render_completed` 现有的 translation、guide、highlight、review、reader identity 验证原样提取为私有函数。推荐签名：

```python
def _load_completed_reader_inputs(
    self,
    workspace: PaperWorkspace,
) -> tuple[
    dict[str, Translation],
    dict[str, tuple[str, str]],
    FullReviewSubmission,
    str,
]:
    """Return trusted translations, highlights, review, reader_revision."""
```

约束：

- 不降低现有 contract、SHA、顺序、batch manifest、review identity 验证；
- `_render_completed` 改为调用该函数后继续原发布流程；
- 不改变正式发布的锁、staging、恢复、manifest 或 package manifest 行为；
- 若现有局部值仍被发布路径使用，最小化重复读取，不扩大重构。

**Step 5: 实现显式预览方法**

```python
def render_preview_completed(
    self,
    workspace: PaperWorkspace,
    *,
    output: Path,
    paper_id: str,
) -> Path:
    translations, highlights, review, reader_revision = (
        self._load_completed_reader_inputs(workspace)
    )
    return self.render(
        workspace,
        translations,
        highlights,
        output,
        review=review,
        reader_revision=reader_revision,
        paper_id=paper_id,
    )
```

该方法不获取 publish claim，不触发 publish hook，不写 manifest。

**Step 6: 运行定向测试和原发布回归**

```powershell
python -m pytest -q engine/tests/test_reader_preview.py engine/tests/test_full_read_renderer.py engine/tests/test_full_read_service.py
```

Expected: 全部通过。

**Step 7: 提交**

```powershell
git add engine/src/scientific_reading/full_read_renderer.py engine/tests/test_reader_preview.py
git commit -m "功能：增加只读 Reader 预览渲染边界"
```

## Task 3: 建立三个小型、可重复的审核 fixture

**Files:**

- Create: `review/fixtures/formula-outline.json`
- Create: `review/fixtures/superscript-text.json`
- Create: `review/fixtures/figures-captions.json`
- Create: `scripts/reader_review_fixtures.py`
- Create: `engine/tests/test_reader_review_fixtures.py`

**Step 1: 固定 fixture JSON 合同**

每个 fixture 使用 `reader-review-fixture-v1`：

```json
{
  "contract_version": "reader-review-fixture-v1",
  "case": "formula-outline",
  "paper_id": "fixture_formula_outline",
  "metadata": {
    "title": "A Compact Review Fixture for Structured Equations",
    "authors": ["Ada Example", "Lin Test"],
    "year": 2026,
    "journal": "Offline Engineering Fixtures"
  },
  "blocks": [],
  "assets": [],
  "review": {
    "guide": {},
    "highlights": []
  }
}
```

具体内容必须覆盖：

- `formula-outline`：h1/h2/h3 路径、行内公式、块级公式、引用；
- `superscript-text`：合法作者 `*`/`†`、`H2O`/`x2` 上下标、普通 `modified`/`firmly` 不得被错误角标、缺失空格修正后的正文；
- `figures-captions`：两张微型 SVG/PNG data payload、长图注、表格、图表弹窗和邻近重点。

fixture 只使用虚构工科内容；不放完整论文、PDF 或用户数据。微型图使用短 base64 或由 materializer 确定性生成的 SVG。

**Step 2: 写失败测试——严格 schema 和确定性 materialization**

```python
@pytest.mark.parametrize(
    "case",
    ["formula-outline", "superscript-text", "figures-captions"],
)
def test_materialize_fixture_is_deterministic(case: str, tmp_path: Path) -> None:
    first = materialize_fixture(case, tmp_path / "a")
    second = materialize_fixture(case, tmp_path / "b")
    assert semantic_tree_hashes(first.root) == semantic_tree_hashes(second.root)

def test_fixture_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fixture_contract_invalid"):
        materialize_fixture_payload({"contract_version": "reader-review-fixture-v1", "extra": True}, tmp_path)
```

`semantic_tree_hashes` 排除时间戳，其他内容必须字节确定。

**Step 3: 运行测试确认 RED**

```powershell
$env:PYTHONPATH='engine/src'
python -m pytest -q engine/tests/test_reader_review_fixtures.py
```

Expected: 模块不存在或 materializer 不存在。

**Step 4: 实现最小 materializer**

`scripts/reader_review_fixtures.py`：

- 用 `json`、`hashlib`、`pathlib` 和现有模型构建临时 `PaperWorkspace`；
- 写出生产 renderer 所需的最小可信 metadata、job stage、`parsed/mineru/source_map.json`、assets、translations、guide、highlights 和 review identity；
- 所有 SHA 和 revision 由输入内容确定性计算；
- 不 import 测试模块，不复制现有真实 generation；
- 只允许三个仓库内 fixture 名；
- 对未知 key、重复 block id、非法层级、资产越界和不一致 caption link 失败关闭。

materializer 只负责测试/审核输入，不新增生产数据合同。

**Step 5: 验证三个 fixture 能走生产预览 renderer**

```python
@pytest.mark.parametrize("case", CASES)
def test_fixture_renders_with_production_preview(case: str, tmp_path: Path) -> None:
    workspace = materialize_fixture(case, tmp_path / "workspace")
    output = tmp_path / "output" / "reader.html"
    FullReadRenderer().render_preview_completed(
        workspace,
        output=output,
        paper_id=workspace.load_metadata()["paper_id"],
    )
    html = output.read_text(encoding="utf-8")
    assert "https://" not in html
    assert "http://" not in html
    assert "reader-revision" in html
```

**Step 6: 运行测试与包体体积检查**

```powershell
python -m pytest -q engine/tests/test_reader_review_fixtures.py engine/tests/test_reader_preview.py
Get-ChildItem -LiteralPath review/fixtures -File | Measure-Object -Property Length -Sum
```

Expected: 测试通过；fixture 总大小保持在 200 KB 以下。

**Step 7: 提交**

```powershell
git add review/fixtures scripts/reader_review_fixtures.py engine/tests/test_reader_review_fixtures.py
git commit -m "测试：增加 Reader 三类离线审核样例"
```

## Task 4: 实现审核会话、baseline/candidate 和原子 manifest

**Files:**

- Create: `scripts/reader_review_render.py`
- Create: `engine/tests/test_reader_review_render.py`

**Step 1: 写失败测试——新会话捕获 baseline，普通刷新不覆盖**

```python
def test_new_session_captures_baseline_once(tmp_path: Path) -> None:
    first = run_review_render(case="formula-outline", new_session=True, review_root=tmp_path)
    baseline = (tmp_path / "baseline/formula-outline/reader.html").read_bytes()

    change_renderer_marker_for_test()
    second = run_review_render(case="formula-outline", new_session=False, review_root=tmp_path)

    assert (tmp_path / "baseline/formula-outline/reader.html").read_bytes() == baseline
    assert first["revision"] + 1 == second["revision"]
    assert second["cases"]["formula-outline"]["candidate_sha256"] != sha256(baseline)
```

不要真的修改源码；测试通过注入 renderer/fake build marker 产生不同 candidate。

**Step 2: 写失败测试——失败保留上一成功 candidate**

```python
def test_failed_render_keeps_last_successful_candidate(tmp_path: Path) -> None:
    success = run_success(...)
    candidate_before = candidate_path(tmp_path).read_bytes()
    failed = run_with_failing_renderer(...)

    assert candidate_path(tmp_path).read_bytes() == candidate_before
    assert failed["status"] == "failed"
    assert failed["candidate_stale"] is True
    assert failed["cases"][CASE]["candidate_sha256"] == sha256(candidate_before)
```

**Step 3: 写失败测试——真实来源只读和 containment**

覆盖：

- 合法 `paper_id` 通过现有活动 generation 选择逻辑解析；
- `../paper`、绝对路径和 symlink generation 被拒绝；
- 来源 reader/manifest/SHA 不一致被拒绝；
- 预览前后 generation 逐文件 SHA 相同；
- 未找到完成 reader 时返回 `source_generation_invalid`，不猜其他目录。

**Step 4: 运行测试确认 RED**

```powershell
$env:PYTHONPATH='engine/src'
python -m pytest -q engine/tests/test_reader_review_render.py
```

Expected: CLI/module 尚不存在。

**Step 5: 实现 Python CLI**

支持：

```text
python scripts/reader_review_render.py --case formula-outline --new-session --review-root %TEMP%/dsh-scientific-reading-review
python scripts/reader_review_render.py --paper-id doi_10.48550_arxiv.1706.03762 --data-root D:/Vibe Coding/s3 --review-root %TEMP%/dsh-scientific-reading-review
python scripts/reader_review_render.py --current-session --review-root %TEMP%/dsh-scientific-reading-review
```

实现规则：

1. `--case` 与 `--paper-id` 互斥；无参数仅能复用已有 session。
2. 真实论文通过现有 metadata/active generation 合同选择；不得搜索“看起来像”完成产物的目录。
3. `--new-session` 先在 sibling 临时目录完整生成 session、baseline、candidate、manifest，再原子切换会话文件；不得先删除旧会话。
4. candidate 写到同目录临时文件，完成 self-contained 校验后 `os.replace`。
5. JSON 用 `ensure_ascii=False`、排序 key、UTF-8、结尾换行，并以临时文件 `flush + fsync + os.replace` 发布。
6. stdout 最后一行只输出 JSON 摘要；诊断写 stderr；不得输出 secret 或完整论文正文。
7. 记录 `source_load/render/write/total` 毫秒数。
8. 所有错误转为稳定 code，但保留非零退出码。

建议将 IO 函数保持窄小：

```python
def atomic_write_bytes(path: Path, payload: bytes) -> None: ...
def atomic_write_json(path: Path, payload: dict[str, object]) -> None: ...
def render_case(request: ReviewRequest) -> dict[str, object]: ...
```

不要增加通用任务框架或插件 API。

**Step 6: 运行定向测试**

```powershell
python -m pytest -q engine/tests/test_reader_review_render.py engine/tests/test_reader_review_fixtures.py engine/tests/test_reader_preview.py
```

Expected: 全部通过。

**Step 7: 提交**

```powershell
git add scripts/reader_review_render.py engine/tests/test_reader_review_render.py
git commit -m "功能：实现 Reader 审核会话与原子候选渲染"
```

## Task 5: 实现 loopback 审核服务器与进程所有权

**Files:**

- Create: `scripts/reader-review-server.mjs`
- Create: `tests/reader-review-server.mjs`

**Step 1: 写失败测试——路由白名单和安全边界**

测试用 `--port 0` 启动子进程并读取握手 JSON，覆盖：

```javascript
assert.equal((await request('/health')).status, 200)
assert.equal((await request('/review')).status, 200)
assert.equal((await request('/api/review-manifest')).status, 200)
assert.equal((await request('/../session.json')).status, 404)
assert.equal((await request('/content/candidate/%2e%2e/session.json')).status, 404)
assert.equal((await request('/unknown.txt')).status, 404)
assert.equal((await request('/review', { method: 'POST' })).status, 405)
```

另测 content symlink 指向审核根外时返回 `404`，且服务器不读取目标。

**Step 2: 写失败测试——端口冲突不杀未知进程**

先启动一个占用随机端口的 sentinel server，再运行审核 server。断言：

- 审核 server 非零退出并报告 `review_port_in_use`；
- sentinel 仍可响应；
- 没有调用 `taskkill` 或结束未知 PID。

**Step 3: 写失败测试——所有者 metadata**

`server.json` 必须记录：

```json
{
  "contract_version": "reader-review-server-v1",
  "pid": 1234,
  "port": 8895,
  "repository_root": "规范绝对路径",
  "session_id": "32位十六进制",
  "started_at": "ISO UTC",
  "token": "随机健康检查 token"
}
```

只有 `/health` 返回相同 repository/session/token 的现存进程才可复用。陈旧 PID 文件只允许删除 metadata，不得根据 PID 直接杀进程。

**Step 4: 运行测试确认 RED**

```powershell
node tests/reader-review-server.mjs
```

Expected: server 脚本不存在。

**Step 5: 用 Node 内置模块实现服务器**

只使用：

```javascript
import http from 'node:http'
import fs from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
```

安全实现要点：

- `host: '127.0.0.1'`；
- URL 先解析、再按完整 route matcher 匹配，不把 URL 直接拼文件路径；
- content case 必须存在于 manifest 且严格匹配 case regex；
- `realpath(file)` 必须 containment 于 `realpath(reviewRoot)`；
- HTML/JSON 显式 MIME，`X-Content-Type-Options: nosniff`；
- 审核页 `Cache-Control: no-store`，candidate URL 自带 revision；
- reader iframe 允许同源脚本正常运行，不添加会破坏单文件 reader 的 CSP；
- SIGINT/SIGTERM 只清理本进程拥有且 token 匹配的 `server.json`。

**Step 6: 运行服务器测试和 syntax check**

```powershell
node --check scripts/reader-review-server.mjs
node tests/reader-review-server.mjs
```

Expected: 全部通过，测试结束后没有残留 Node 进程。

**Step 7: 提交**

```powershell
git add scripts/reader-review-server.mjs tests/reader-review-server.mjs
git commit -m "功能：增加安全的本地 Reader 审核服务"
```

## Task 6: 实现统一审核页

**Files:**

- Create: `review/index.html`
- Create: `tests/reader-review-ui.mjs`

**Step 1: 写静态合同测试**

验证审核页具备且只具备第一版控件：

```javascript
for (const id of [
  'case-select',
  'version-baseline',
  'version-candidate',
  'viewport-desktop',
  'viewport-tablet',
  'viewport-mobile',
  'build-status',
  'test-status',
  'reader-frame',
]) assert.match(html, new RegExp(`id=["']${id}["']`))

assert.doesNotMatch(html, /评论系统|截图上传|WebSocket|Playwright/)
```

另用 `vm` + 极小 DOM fake 或提取的纯函数测试：

- manifest case 列表更新；
- 默认 candidate；
- 三种宽度分别为 `100%`、`900px`、`390px`；
- revision 增加才刷新；
- 切换 baseline/candidate 保留 case/viewport；
- failed/stale 显示但不丢弃旧 iframe URL。

**Step 2: 运行测试确认 RED**

```powershell
node tests/reader-review-ui.mjs
```

Expected: 页面不存在。

**Step 3: 实现单文件审核页**

页面规则：

- 简洁顶部工具栏，视觉上与 reader 区分但不抢占正文；
- 默认 candidate + desktop；
- iframe `title="Reader 审核内容"`；
- `setInterval` 每 800 ms 拉取小 manifest，使用 `cache: 'no-store'`；
- 刷新前从 same-origin iframe 尝试记录：URL hash、`scrollY / (scrollHeight - innerHeight)`、最近可见 `[id]` 或 `[data-block-id]`；
- 刷新后优先恢复 block/hash，失败再恢复滚动比例；跨 baseline/candidate 同理；
- iframe 未加载或 DOM 不可访问时降级，不阻塞刷新；
- 状态栏显示 commit 前 7 位、构建时间、测试计数和 stale/failed；
- 不向 candidate DOM 注入任何生产功能。

核心刷新函数保持可测试：

```javascript
function candidateUrl(entry, revision) {
  const url = new URL(entry.candidate_url, location.origin)
  url.searchParams.set('revision', String(revision))
  return url.pathname + url.search
}
```

**Step 4: 运行静态测试**

```powershell
node tests/reader-review-ui.mjs
node tests/reader-review-server.mjs
```

Expected: 通过。

**Step 5: 首次真实浏览器 QA**

用临时 manifest/candidate 启动服务器，打开：

```text
http://127.0.0.1:8895/review
```

人工验证：

- 1440×900：工具栏一行、正文无横向溢出；
- 900×900：平板 iframe 宽度正确；
- 390×844：审核控件可换行且 candidate 可读；
- baseline/candidate 保留阅读位置；
- manifest revision 更新后自动刷新；
- failed/stale 状态清晰且旧 candidate 仍可查看。

把结果和截图路径追加到执行记录，不把截图提交到 Git。

**Step 6: 提交**

```powershell
git add review/index.html tests/reader-review-ui.mjs docs/superpowers/executions/2026-09-02-reader-review-loop.md
git commit -m "界面：增加固定 Reader 审核页"
```

## Task 7: 串联 `npm run reader:review`

**Files:**

- Create: `scripts/reader-review.mjs`
- Create: `tests/reader-review-cli.mjs`
- Modify: `package.json`

**Step 1: 写失败测试——参数、JSON 输出和无网络环境**

测试 fake Python renderer 与 fake server，覆盖：

- `--case formula-outline --new-session`；
- `--paper-id fixture_real --data-root` 指向测试创建的临时 data root；
- 无参数复用当前 session；
- 无 session 且无参数时返回 `review_source_required` 并列出三个 fixture；
- stdout 最后一行是：

```json
{
  "ok": true,
  "url": "http://127.0.0.1:8895/review",
  "revision": 1,
  "case": "formula-outline",
  "server": "started"
}
```

- child env 中 `MINERU_API_TOKEN`、`MINERU_API_KEY`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、机构认证变量均为空；
- Windows spawn options 含 `windowsHide: true`；
- 没有 shell string 拼接用户参数。

**Step 2: 写失败测试——服务器复用与外部端口占用**

覆盖：

- 健康 token、repository root、session id 全匹配时复用 PID；
- PID 存在但 health 不匹配时不复用；
- 8895 被未知服务占用时失败且未知服务仍存活；
- 重复运行只保留一个审核 server。

**Step 3: 运行测试确认 RED**

```powershell
node tests/reader-review-cli.mjs
```

Expected: CLI 不存在或 npm script 不存在。

**Step 4: 实现 orchestrator**

`reader-review.mjs` 负责：

1. 严格解析参数；
2. 找到当前仓库 Python（优先当前环境，Windows 可用 `py -3.11`，不得联网安装）；
3. 用参数数组运行 `reader_review_render.py`，`shell:false`；
4. 注入 `PYTHONPATH` 为当前仓库绝对路径下的 `engine/src`，并设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`；
5. 显式清空外部凭证；
6. 健康检查并复用/启动审核 server；
7. Windows 启动统一使用：

```javascript
const child = spawn(process.execPath, serverArgs, {
  cwd: repoRoot,
  detached: true,
  stdio: 'ignore',
  windowsHide: true,
  shell: false,
})
child.unref()
```

8. 等待最多 5 秒的 `/health` 就绪；不做无限轮询；
9. 输出固定 URL 和单行 JSON。

不要自动调用浏览器命令；Codex 通过应用内浏览器打开 URL，避免脚本绑定具体宿主。

**Step 5: 增加 npm script**

```json
"reader:review": "node scripts/reader-review.mjs"
```

**Step 6: 运行端到端 fixture 快速循环**

```powershell
npm run reader:review -- --case formula-outline --new-session
npm run reader:review -- --case formula-outline
```

Expected:

- 两次都输出 `http://127.0.0.1:8895/review`；
- 第二次 `server=reused`；
- manifest revision 增加；
- baseline SHA 不变；
- candidate 成功刷新；
- Windows 不弹终端窗口。

**Step 7: 提交**

```powershell
git add scripts/reader-review.mjs tests/reader-review-cli.mjs package.json
git commit -m "功能：串联 Reader 一键快速审核命令"
```

## Task 8: 实现离线代表性验收命令

**Files:**

- Create: `scripts/reader-acceptance.mjs`
- Create: `tests/reader-acceptance.mjs`
- Modify: `package.json`

**Step 1: 写失败测试——强制离线和三案例覆盖**

fake child runner 记录命令和环境，断言：

- 三个 fixture 都渲染；
- 若 session 有真实案例，再额外渲染该案例；
- 凭证变量被清空；
- 不执行含 `mineru`, `download`, `feishu`, `curl`, `Invoke-WebRequest`, `npm install` 的外部命令；
- 任一测试失败时非零退出，并把 manifest tests 设为 failed；
- 成功时生成完整 browser QA pending 清单。

**Step 2: 运行测试确认 RED**

```powershell
node tests/reader-acceptance.mjs
```

Expected: 脚本不存在。

**Step 3: 实现验收编排**

依次运行：

```text
1. 三个 fixture candidate render
2. 当前真实案例 candidate render（若有）
3. Python reader/renderer/fixture 定向测试
4. Node reader review server/UI/CLI 静态测试
5. HTML 结构预检
6. 原子写 manifest tests + browser_qa
```

Python 定向测试命令固定为：

```powershell
python -m pytest -q `
  engine/tests/test_reader_preview.py `
  engine/tests/test_reader_review_fixtures.py `
  engine/tests/test_reader_review_render.py `
  engine/tests/test_full_read_renderer.py `
  engine/tests/test_reader_interactions.py `
  engine/tests/test_reader_content_folding.py `
  engine/tests/test_reader_citations.py
```

Node 定向测试：

```powershell
node tests/reader-review-server.mjs
node tests/reader-review-ui.mjs
node tests/reader-review-cli.mjs
node tests/reader-acceptance.mjs --self-check
```

HTML 预检至少验证：

- 每个输出为 self-contained；
- 目录包含 fixture 约定的层级标题；
- 公式容器存在且无未转义的原始 LaTeX 占位；
- 普通单词不产生非法 `sup`；
- figure/table/caption 绑定存在；
- reader 本身不包含审核工具栏 ID；
- 固定宽度下不存在明显的静态宽度溢出规则。

静态预检不能冒充真实浏览器 QA；manifest 中浏览器项保持 `pending`。

**Step 4: 增加 npm script**

```json
"reader:acceptance": "node scripts/reader-acceptance.mjs"
```

**Step 5: 运行离线验收**

```powershell
$env:MINERU_API_TOKEN='must-not-be-used'
$env:FEISHU_APP_SECRET='must-not-be-used'
npm run reader:acceptance
```

Expected: 成功；子进程看不到凭证；三个案例均为 passed；browser QA 为 pending。

**Step 6: 提交**

```powershell
git add scripts/reader-acceptance.mjs tests/reader-acceptance.mjs package.json
git commit -m "测试：增加 Reader 离线代表性验收命令"
```

## Task 9: 实现真实 tarball 的隔离 DSH 验收

**Files:**

- Create: `scripts/acceptance-dsh.mjs`
- Create: `tests/acceptance-dsh.mjs`
- Modify: `package.json`

**Step 1: 写 fake DSH 失败测试**

构造临时 fake `dsh` 可执行文件，记录 argv/env 并提供最小 HTTP 路由。测试断言：

- 先 `npm run build` 和 `npm pack --json`；
- 安装的是刚生成的真实 `.tgz`，不是源码链接；
- `DSH_HOME`/profile/data root 都位于本命令拥有的临时目录；
- profile 名固定为 `reader-review-acceptance`；
- 使用随机可用 loopback port，不触碰 3080/持久 Profile；
- 启动 `windowsHide:true`、`shell:false`；
- 只结束握手确认且由本命令创建的 PID；
- 失败时保留 evidence 路径，不递归删除未验证路径；
- 环境中真实飞书、MinerU、机构认证凭证为空。

**Step 2: 写路由验收断言**

fake host 与后续真实 host 均需满足：

```text
GET /sr/reading/{paper_id} -> 200 text/html
页面包含 reader revision
页面不包含审核 toolbar ID
不存在远程资源 URL
非法 paper_id / traversal -> 4xx
```

若 DSH 正式路由需要先把 fixture generation 放到临时 data root，应调用现有插件/引擎公开入口或复制 materializer 生成的完整临时 generation；不得改持久 data root。

**Step 3: 运行测试确认 RED**

```powershell
node tests/acceptance-dsh.mjs
```

Expected: 脚本不存在。

**Step 4: 实现隔离验收脚本**

实现阶段：

```text
preflight -> build -> pack -> inspect tarball -> temp DSH_HOME
-> plugin add tarball --ignore-scripts -> materialize fixture data
-> start DSH -> HTTP acceptance -> stop owned process -> report evidence
```

约束：

- 仅使用本机已有 `dsh`；缺失时返回 `dsh_runtime_missing`，不联网下载；
- `npm pack --json` 解析输出得到 tarball，禁止 glob 猜最新文件；
- 启动前确认临时根的 resolved path 位于 `os.tmpdir()`；
- 使用项目 token/随机 nonce 进行健康握手；
- 终止前重新核对 PID、启动时间和命令身份；
- Windows 先温和结束 owned process，超时后才对同一已验证 PID 强制结束；
- 不运行真实飞书写入、机构认证或 MinerU API；
- 默认清理成功临时目录，失败保留 evidence 并打印路径；
- 不修改当前 3080 监听进程。

**Step 5: 增加 npm script**

```json
"acceptance:dsh": "node scripts/acceptance-dsh.mjs"
```

**Step 6: 先 fake、再真实本机 DSH 验收**

```powershell
node tests/acceptance-dsh.mjs
npm run acceptance:dsh
```

Expected:

- fake 合同测试通过；
- 若本机 DSH 可用，真实 tarball 安装和正式 reader 路由通过；
- 当前 3080/persistent Profile 的 PID、启动时间、配置和响应前后不变；
- 若本机缺少 DSH，明确报告 `dsh_runtime_missing`，不得把它写成通过。

**Step 7: 提交**

```powershell
git add scripts/acceptance-dsh.mjs tests/acceptance-dsh.mjs package.json
git commit -m "测试：增加隔离 DSH 实机验收命令"
```

## Task 10: 保证审核工具不进入发布包并补充中文文档

**Files:**

- Modify: `tests/package-contents.mjs`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `docs/superpowers/executions/2026-09-02-reader-review-loop.md`

**Step 1: 写失败测试——明确禁止发布的路径**

扩展 `tests/package-contents.mjs`：

```javascript
for (const forbidden of [
  'package/review/',
  'package/tests/reader-review-',
  'package/scripts/reader-review',
  'package/scripts/reader_review_',
  'package/scripts/reader-acceptance.mjs',
  'package/scripts/acceptance-dsh.mjs',
]) {
  assert.equal(files.some((name) => name.startsWith(forbidden)), false, forbidden)
}
```

保留现有发布白名单，不把 review 目录加入 `files`。

**Step 2: 运行打包测试确认现状**

```powershell
node tests/package-contents.mjs
npm pack --dry-run --json
```

Expected: 新增审核文件全部不在 tarball；若当前 `files` 白名单已自然排除，测试可直接通过，但该断言仍作为回归合同保留。

**Step 3: 把审核测试纳入离线套件**

将以下快速静态/合同测试加入 `test:offline`：

```text
tests/reader-review-server.mjs
tests/reader-review-ui.mjs
tests/reader-review-cli.mjs
tests/reader-acceptance.mjs --self-check
tests/acceptance-dsh.mjs --self-check
```

`acceptance:dsh` 的真实启动不进入普通 `npm test`，避免 CI 依赖本机 DSH。

**Step 4: README 增加“开发者：快速审核 Reader”**

用中文写清：

```powershell
# 第一次或主动重置 baseline
npm run reader:review -- --case formula-outline --new-session

# 使用本机已完成论文
npm run reader:review -- --paper-id doi_10.48550_arxiv.1706.03762 --data-root "D:\Vibe Coding\s3" --new-session

# 修改后刷新 candidate
npm run reader:review

# 用户认可后
npm run reader:acceptance
npm run acceptance:dsh
```

同时说明：

- 固定审核地址；
- 快速循环不调用 MinerU/LLM；
- baseline 语义；
- 浏览器 Comment 反馈方式；
- 三层验收边界；
- 临时目录位置和清理方式；
- 真实 DSH 验收缺少 runtime 时的明确状态；
- 审核工具不进入用户安装包。

不要重写无关 README 段落；若 README 在主线有在途改动，合并时做最小上下文适配。

**Step 5: 运行文档/包/离线测试**

```powershell
node tests/package-contents.mjs
npm run test:offline
git diff --check
```

Expected: 全部通过，无 whitespace error。

**Step 6: 提交**

```powershell
git add package.json tests/package-contents.mjs README.md docs/superpowers/executions/2026-09-02-reader-review-loop.md
git commit -m "文档：补充 Reader 快速审核与分层验收流程"
```

## Task 11: 真实论文快速循环、浏览器 QA 与性能证据

**Files:**

- Modify: `docs/superpowers/executions/2026-09-02-reader-review-loop.md`
- No formal generation files may change

**Step 1: 选择一个已完成、非敏感的真实论文 generation**

优先使用现有《Attention Is All You Need》：

```text
paper_id = doi_10.48550_arxiv.1706.03762
data_root = D:\Vibe Coding\s3
```

运行前对其正式 generation 建立逐文件 SHA-256 清单，保存在审核临时 evidence，不提交完整路径内容到发布包。

**Step 2: 新建真实审核会话并计时**

```powershell
Measure-Command {
  npm run reader:review -- --paper-id doi_10.48550_arxiv.1706.03762 --data-root "D:\Vibe Coding\s3" --new-session
}
Measure-Command {
  npm run reader:review
}
```

Expected: 第二次属于正常快速循环；目标 5–10 秒。若超过目标，先读取 manifest 的阶段耗时定位，不通过跳过校验或缓存陈旧 HTML“优化”。

**Step 3: 验证正式 generation 完全未变**

重新计算逐文件 SHA-256，并与 Step 1 比较。Expected: 路径集合、大小、SHA 全相同；包括正式 reader、reader manifest 和 package manifest。

**Step 4: 应用内浏览器 QA**

打开固定地址并检查：

- baseline/candidate 即时切换；
- desktop/tablet/mobile 三种审核宽度；
- 目录折叠、三级跳转和阅读位置恢复；
- 英文默认正文、点击段落展开中文；
- 低价值区域默认折叠；
- 公式、角标、缺失空格修正；
- 图表、长图注、图表弹窗；
- 全文/无标记/重点；
- 个人荧光笔创建、刷新恢复、换色、删除；
- 待读浮球及引用弹窗（若当前 reader 已包含）；
- 无横向溢出和明显字号/行距问题。

在 candidate 元素添加一条临时 Codex Browser Comment，确认 URL 含当前 revision、目标 selector 和 viewport；无需在审核页另存反馈。

**Step 5: 跑代表性验收并完成三 viewport 真实 QA**

```powershell
npm run reader:acceptance
```

由 Codex 实际打开三种 fixture，在 1440×900、900×900、390×844 下完成清单。完成后用审核工具的受控命令或专用 manifest 更新入口把 browser QA 状态原子写为 passed；不得手工编辑一半 manifest。

**Step 6: 运行隔离 DSH**

```powershell
npm run acceptance:dsh
```

记录 tarball 名称/SHA、临时 Profile、端口、HTTP 断言、owned PID 清理证据，以及持久 3080 前后身份不变证据。

**Step 7: 提交验收记录**

只提交简洁证据，不提交截图、临时 manifest、完整论文路径清单或用户数据：

```powershell
git add docs/superpowers/executions/2026-09-02-reader-review-loop.md
git commit -m "验证：完成 Reader 快速审核闭环实机验收"
```

## Task 12: 全量验证、审查、合并与清理

**Files:**

- No new implementation files unless a verified defect requires a focused fix

**Step 1: 运行完整验证**

先清空外部凭证：

```powershell
$env:MINERU_API_TOKEN=''
$env:MINERU_API_KEY=''
$env:FEISHU_APP_ID=''
$env:FEISHU_APP_SECRET=''
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
npm test
npm run reader:acceptance
npm run acceptance:dsh
git diff --check
git status --short --branch
```

Expected: `npm test`、离线验收通过；真实 DSH 通过或以 `dsh_runtime_missing` 明确阻塞，不能伪装成通过；工作树只包含预期内容。

**Step 2: 复核安全与范围**

```powershell
rg -n "MINERU_API|FEISHU_APP|http://|https://|taskkill|Stop-Process|kill\(" scripts/reader* scripts/acceptance-dsh.mjs review tests/reader* tests/acceptance-dsh.mjs
npm pack --dry-run --json
$BaselineSha = (Get-Content -LiteralPath docs/superpowers/executions/2026-09-02-reader-review-loop.md -Encoding utf8 | Select-String '^基线 SHA: ').Line.Split(':', 2)[1].Trim()
git diff "$BaselineSha...HEAD" --stat
git diff "$BaselineSha...HEAD" --name-only
```

人工确认：

- 清空凭证的测试不存在真实外部写入；
- 仅 owned PID 可被结束；
- 审核 server 未绑定 `0.0.0.0`/`::`；
- 发布包无 review/scripts/tests；
- 无无关重构；
- 没有把临时产物或真实论文提交到 Git。

**Step 3: 按 verification-before-completion 重新取得新鲜证据**

不得引用开发中途的旧通过结果。记录最终命令、exit code、测试计数、耗时和实机 URL。

**Step 4: 本地合并回 `main`**

合并前再次保存主工作树所有者状态。若主工作树仍有无关脏改动，先使用安全的独立暂存/所有权方案，不覆盖它们。按用户默认约定：

```powershell
git switch main
git merge --no-ff feature/reader-review-loop -m "合并：Reader 快速审核闭环"
```

禁止自动 push；除非用户在完成后另行要求。

**Step 5: 在 main 重跑全量与实机验证**

```powershell
npm test
npm run reader:acceptance
npm run acceptance:dsh
git status --short --branch
```

Expected: 与功能分支一致；主工作树原有用户改动仍在，内容未丢失。

**Step 6: 清理本任务 worktree/分支**

只有 main 合并和复验成功后：

```powershell
git worktree remove ".worktrees/reader-review-loop"
git branch -d "feature/reader-review-loop"
git worktree list
```

不得删除审核临时 evidence，直到最终报告已提取所需证据；之后只删除已验证位于系统 temp 下且属于本项目 token 的目录。

## 最终交付模板

```text
本轮修改：只读预览边界、固定审核页、三类 fixture、离线验收、隔离 DSH 验收
快速预览：通过/失败；真实二次渲染 X.XX 秒
正式 generation：逐文件 SHA 前后一致/不一致
代表性论文：3/3 通过/失败
移动端与交互：通过/失败
隔离 DSH：通过/失败/本机运行时缺失
完整 MinerU 链路：按影响面无需运行（本功能未改 MinerU 输入/状态）
外部写入：未执行飞书、机构认证和真实 MinerU API
审核地址：http://127.0.0.1:8895/review
分支/main commit：填写最终 SHA
未解决限制：如实列出；没有则写“无”
```

## 计划自审清单

- [ ] 设计的 12 条验收标准均映射到至少一个自动测试或真实 QA 步骤。
- [ ] 所有生产改动仅限 `FullReadRenderer` 的窄预览边界。
- [ ] baseline/candidate/session/manifest 合同明确且可原子恢复。
- [ ] 三个 fixture 各自覆盖公式目录、角标文本、图表图注。
- [ ] server 路由、loopback、path containment、symlink 和 PID 所有权都有测试。
- [ ] Windows 所有后台 spawn 都明确 `windowsHide:true`。
- [ ] 快速/代表性验收明确清空 MinerU/飞书/认证凭证。
- [ ] candidate 构建失败不会覆盖上次成功文件。
- [ ] DSH 验收使用真实 tarball 和临时 Profile/data root，不动 3080。
- [ ] 审核工具和 fixture 通过 package test 证明不进入 npm 包。
- [ ] 浏览器 QA 没有被静态测试替代。
- [ ] 完整 MinerU API 是否运行按影响面报告，不把未运行写成通过。
- [ ] 计划没有引入新依赖、Playwright、评论系统、WebSocket 或 watcher。
- [ ] 执行阶段只提交本任务文件，中文 commit，可独立回退。
