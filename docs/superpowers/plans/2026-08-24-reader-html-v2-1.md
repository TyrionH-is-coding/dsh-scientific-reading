# 精读 HTML v2.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重做既有 v2 美术风格的前提下，为离线 `reader.html` 增加来源可追溯阅读导览、语义化黄蓝重点、英文总开关、图表放大和本地阅读位置恢复。

**Architecture:** 继续由 Python full-review agent gate 一次提交导览与重点，严格校验后交给确定性 renderer。`reader/build_reader.py` 只负责离线 DOM/CSS/JS 组装；SQLite、DSH 路由和资产路径不新增第二套状态。

**Tech Stack:** Python 3.11 dataclasses、BeautifulSoup、pytest；离线 HTML/CSS/原生 JavaScript、`<details>`、`<dialog>`、localStorage。

---

## 执行边界与文件责任

设计依据：

- `D:\Vibe Coding\dsh-scientific-reading\docs\superpowers\specs\2026-08-24-reader-html-v2-1-design.md`

本计划是 Phase 2 Task 4 的增量修订。保留当前 `07dc44e 阅读器：固定双语全文样式与来源清单`
及其完整性修复，在此基础上测试先行；不要回退 reader manifest、翻译代际、caption 关联或
SQLite 读回校验。

文件责任固定为：

- `src/scientific_reading/full_read_models.py`：新翻译/审查合同与导览来源验证；
- `src/scientific_reading/full_read_service.py`：agent gate context、密度上限、发布身份与 staged files；
- `src/scientific_reading/full_read_renderer.py`：把可信翻译、导览、revision 与资产交给 builder；
- `reader/build_reader.py`：离线 HTML 结构、CSS 和浏览器交互；
- `tests/test_full_read_models.py`：合同边界；
- `tests/test_full_read_service.py`：review/finalize/cache；
- `tests/test_reader_v2.py`：DOM、manifest、兼容和静态 JS/CSS 合同；
- `tests/test_pipeline_parse_translate.py`：父任务 agent gate 与完成回归。

本功能不修改 DSH 文献导航 UI，不写飞书，不触发 MinerU/网络，也不更新当前 3080。所有测试继续
使用 Phase 2 的虚构工科 fixture。

## Task 1：把 full-review 改为来源可追溯导览和语义重点

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_models.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pipeline_parse_translate.py`

- [ ] **Step 1: 写新合同失败测试**

在 `tests/test_full_read_models.py` 增加以下明确行为：

```python
def test_translation_v3_accepts_result_method_and_none():
    source = "The proposed scheduler reduced mean delay by 18%."
    for kind in ("result", "method", "none"):
        row = Translation.from_dict(
            {
                "block_id": "p0001-m0001",
                "source_text": source,
                "translation_zh": "该调度器将平均延迟降低了18%。",
                "highlight": kind,
            },
            expected_source_text=source,
            reference=False,
        )
        assert row.highlight == kind


def test_translation_v3_rejects_primary_secondary():
    with pytest.raises(ValueError, match="translation_highlight_invalid"):
        Translation.from_dict(
            {
                "block_id": "p0001-m0001",
                "source_text": "Method text.",
                "translation_zh": "方法文本。",
                "highlight": "primary",
            },
            expected_source_text="Method text.",
            reference=False,
        )


def test_full_review_v2_validates_guide_sources_and_limits():
    review = FullReviewSubmission.from_dict(
        {
            "contract_version": "full-review-v2",
            "highlights": [
                {
                    "block_id": "p0001-m0002",
                    "kind": "result",
                    "reason": "核心定量结果",
                }
            ],
            "guide": {
                "research_question": [
                    {
                        "text": "如何在资源受限时降低车间调度延迟？",
                        "source_block_ids": ["p0001-m0001"],
                    }
                ],
                "key_methods": [],
                "core_results": [
                    {
                        "text": "平均延迟降低18%。",
                        "source_block_ids": ["p0001-m0002"],
                    }
                ],
                "limitations": [],
            },
        },
        available_block_ids={"p0001-m0001", "p0001-m0002"},
        substantive_block_count=8,
    )
    assert review.guide.core_results[0].source_block_ids == ("p0001-m0002",)
    assert review.highlights[0].kind == "result"
```

再参数化覆盖：未知 source block、参考文献 block、单条无 source、文本为空/超过 240 字、研究问题
超过 1 条、方法超过 2 条、结果超过 3 条、局限超过 2 条、全部类别为空、未知 category、重复
highlight block、highlight kind 未知和总高亮超过 25%。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& .\.venv\Scripts\python.exe -m pytest tests\test_full_read_models.py -q
```

预期：旧合同仍要求 `key_points`，且 `result`/`method` 被拒绝。

- [ ] **Step 3: 实现 v3 翻译与 v2 审查模型**

在 `full_read_models.py` 使用以下稳定常量和类型：

```python
FULL_TRANSLATION_CONTRACT_VERSION = "full-translation-v3"
FULL_REVIEW_CONTRACT_VERSION = "full-review-v2"
HIGHLIGHT_KINDS = frozenset({"result", "method", "none"})
GUIDE_LIMITS = {
    "research_question": 1,
    "key_methods": 2,
    "core_results": 3,
    "limitations": 2,
}


@dataclass(frozen=True, slots=True)
class GuideEntry:
    text: str
    source_block_ids: tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        available_block_ids: set[str],
    ) -> "GuideEntry":
        if not isinstance(value, dict):
            raise ValueError("guide_entry_invalid")
        _exact_keys(value, {"text", "source_block_ids"})
        text = value["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("guide_text_required")
        text = text.strip()
        if len(text) > 240:
            raise ValueError("guide_text_too_long")
        block_ids = value["source_block_ids"]
        if (
            not isinstance(block_ids, list)
            or not 1 <= len(block_ids) <= 3
            or any(not isinstance(item, str) for item in block_ids)
        ):
            raise ValueError("guide_source_blocks_invalid")
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("guide_source_blocks_duplicate")
        if any(item not in available_block_ids for item in block_ids):
            raise ValueError("guide_source_block_unknown")
        return cls(text=text, source_block_ids=tuple(block_ids))


@dataclass(frozen=True, slots=True)
class ReadingGuide:
    research_question: tuple[GuideEntry, ...]
    key_methods: tuple[GuideEntry, ...]
    core_results: tuple[GuideEntry, ...]
    limitations: tuple[GuideEntry, ...]

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        available_block_ids: set[str],
    ) -> "ReadingGuide":
        if not isinstance(value, dict):
            raise ValueError("reading_guide_invalid")
        _exact_keys(value, set(GUIDE_LIMITS))
        parsed: dict[str, tuple[GuideEntry, ...]] = {}
        for category, maximum in GUIDE_LIMITS.items():
            rows = value[category]
            if not isinstance(rows, list) or len(rows) > maximum:
                raise ValueError(f"guide_{category}_limit")
            parsed[category] = tuple(
                GuideEntry.from_dict(
                    row,
                    available_block_ids=available_block_ids,
                )
                for row in rows
            )
        if not any(parsed.values()):
            raise ValueError("reading_guide_empty")
        return cls(**parsed)
```

把 `Translation.from_dict()` 的 highlight 白名单改成 `HIGHLIGHT_KINDS`。把
`FullReviewHighlight` 字段改为 `block_id/kind/reason`，kind 只允许 `result`/`method`。把
`FullReviewSubmission.key_points` 替换为 `guide: ReadingGuide`，精确 key 为
`contract_version/highlights/guide`。高亮限制使用：

```python
limit = max(1, int(substantive_block_count * 0.25))
```

- [ ] **Step 4: 更新序列化与父任务 fixture**

`to_dict()` 必须完整输出 guide 四类及 source IDs。把 `tests/test_pipeline_parse_translate.py` 的 agent
review fixture 改为 `full-review-v2`，使用 `result`/`method`，并断言 required_input 明确包含：

```python
assert context["highlight_kinds"] == {
    "result": "核心结果、结论或创新",
    "method": "关键方法、实验设计或支撑证据",
}
assert context["guide_limits"] == {
    "research_question": 1,
    "key_methods": 2,
    "core_results": 3,
    "limitations": 2,
}
assert context["target_highlight_ratio"] == "10%-15%"
assert context["maximum_highlight_ratio"] == "25%"
```

- [ ] **Step 5: 运行合同测试并提交**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_full_read_models.py tests\test_pipeline_parse_translate.py -q
git diff --check
git add src/scientific_reading/full_read_models.py tests/test_full_read_models.py tests/test_pipeline_parse_translate.py
git commit -m "精读：语义化重点并约束阅读导览来源"
```

## Task 2：把导览、语义和 revision 纳入发布身份

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_renderer.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_service.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`

- [ ] **Step 1: 写发布与缓存失败测试**

先在测试文件增加可复用的真实 v2 review fixture：

```python
def _review_v2(*, result_text: str = "平均延迟降低18%。") -> dict:
    return {
        "contract_version": "full-review-v2",
        "highlights": [
            {
                "block_id": "p0001-m0002",
                "kind": "result",
                "reason": "核心定量结果",
            }
        ],
        "guide": {
            "research_question": [
                {
                    "text": "如何在资源受限时降低车间调度延迟？",
                    "source_block_ids": ["p0001-m0001"],
                }
            ],
            "key_methods": [],
            "core_results": [
                {
                    "text": result_text,
                    "source_block_ids": ["p0001-m0002"],
                }
            ],
            "limitations": [],
        },
    }


def _translated_workspace(tmp_path, metadata, *, block_count: int = 8):
    workspace = _active_mineru_workspace(
        tmp_path,
        metadata,
        block_count=block_count,
    )
    service = FullReadService()
    while (batch := service.next_batch(workspace)) is not None:
        service.save_next_translation(workspace, _translation(batch))
    return workspace, service
```

再增加完整行为测试：

```python
def test_review_context_describes_semantic_guide_contract(tmp_path, metadata):
    workspace, service = _translated_workspace(tmp_path, metadata)
    context = service.review_context(workspace)
    assert context["contract_version"] == "full-review-v2"
    assert context["highlight_kinds"]["result"] == "核心结果、结论或创新"
    assert context["guide_limits"]["core_results"] == 3
    assert context["maximum_highlight_ratio"] == "25%"


def test_finalize_writes_guide_and_reader_revision_to_manifest(tmp_path, metadata):
    workspace, service = _translated_workspace(tmp_path, metadata)
    result = service.finalize(workspace, _review_v2())
    manifest = json.loads(
        workspace.reader_manifest.read_text(encoding="utf-8")
    )
    assert len(result["reader_revision"]) == 64
    assert manifest["reader_revision"] == result["reader_revision"]
    assert manifest["review"]["guide"]["core_results"][0][
        "source_block_ids"
    ] == ["p0001-m0002"]


def test_guide_change_invalidates_completed_reader_cache(tmp_path, metadata):
    workspace, service = _translated_workspace(tmp_path, metadata)
    service.finalize(workspace, _review_v2())
    with pytest.raises(FullReadError, match="full_read_artifact_inconsistent"):
        service.finalize(
            workspace,
            _review_v2(result_text="平均延迟降低19%。"),
        )


def test_reader_build_version_change_invalidates_cache(
    monkeypatch,
    tmp_path,
    metadata,
):
    workspace, service = _translated_workspace(tmp_path, metadata)
    service.finalize(workspace, _review_v2())
    monkeypatch.setattr(
        "scientific_reading.full_read_service.READER_BUILD_VERSION",
        "reader-html-v2.2",
    )
    with pytest.raises(FullReadError, match="full_read_artifact_inconsistent"):
        FullReadService().finalize(workspace, _review_v2())


def test_guide_source_must_match_active_mineru_generation(tmp_path, metadata):
    workspace, service = _translated_workspace(tmp_path, metadata)
    review = _review_v2()
    review["guide"]["core_results"][0]["source_block_ids"] = [
        "p9999-m9999"
    ]
    with pytest.raises(ValueError, match="guide_source_block_unknown"):
        service.finalize(workspace, review)


def test_finalize_rejects_combined_highlights_over_25_percent(
    tmp_path,
    metadata,
):
    workspace = _active_mineru_workspace(
        tmp_path,
        metadata,
        block_count=8,
    )
    service = FullReadService()
    batch = service.next_batch(workspace)
    submission = _translation(batch)
    submission["translations"][1]["highlight"] = "result"
    submission["translations"][2]["highlight"] = "method"
    service.save_next_translation(workspace, submission)
    review = _review_v2()
    review["highlights"] = [
        {
            "block_id": "p0001-m0004",
            "kind": "result",
            "reason": "第三处重点超过四分之一上限",
        }
    ]
    with pytest.raises(ValueError, match="full_review_highlight_limit"):
        service.finalize(workspace, review)
```

`test_finalize_writes_guide_and_reader_revision_to_manifest` 必须读回：

```python
manifest = json.loads(workspace.reader_manifest.read_text(encoding="utf-8"))
assert manifest["reader_revision"] == result["reader_revision"]
assert manifest["review"]["guide"]["core_results"][0]["source_block_ids"] == [
    "p0001-m0002"
]
assert result["review"]["guide"] == manifest["review"]["guide"]
```

- [ ] **Step 2: 运行测试确认 RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_full_read_service.py tests\test_reader_v2.py -q
```

预期：当前 finalize 仍输出 `key_points`，manifest 无 revision/guide。

- [ ] **Step 3: 更新 review context 与 finalize**

`review_context()` 返回 active source block 清单、语义说明和 guide limits；不要求 agent 重新读取 PDF。
`finalize()` 合并翻译与 review highlights 时保留 kind/reason：

```python
highlights = {
    item.block_id: (item.highlight, "全文翻译标注")
    for item in translations.values()
    if item.highlight != "none"
}
for item in review.highlights:
    highlights.setdefault(item.block_id, (item.kind, item.reason))

highlight_limit = max(1, int(substantive_count * 0.25))
if len(highlights) > highlight_limit:
    raise ValueError("full_review_highlight_limit")
```

在 `final_identity` 加入 `reader_build_version` 和完整 `review.to_dict()`，再计算 revision：

```python
final_identity = {
    "reader_build_version": READER_BUILD_VERSION,
    "source_sha256": active.source_sha256,
    "source_map_sha256": active.source_map_sha256,
    "translations": translation_payload["translations"],
    "highlights": highlights_payload["highlights"],
    "review": review.to_dict(),
}
reader_revision = hashlib.sha256(_json_bytes(final_identity)).hexdigest()
```

将 `reader_revision` 传给 renderer，并写入 result。不要把最终 HTML SHA 嵌回 HTML；renderer 完成后
继续只把最终 `reader_sha256` 写进 manifest。

- [ ] **Step 4: 更新 markdown 和 staged publications**

`_write_full_markdown()` 用 guide 四类替换旧 `key_points`：缺失类别写“原文未明确说明”，每条附
`[source: p0001-m0001,p0001-m0002]` 形式的真实来源。新增 staged `reading_guide.json`，使用代码
直接构造，不写示例占位值：

```python
guide_payload = {
    "contract_version": FULL_REVIEW_CONTRACT_VERSION,
    "reader_revision": reader_revision,
    "guide": review.to_dict()["guide"],
}
_atomic_write_json_lf(staging / "reading_guide.json", guide_payload)
```

把文件纳入原子 publications 和 completed-cache 字节读回比较。

- [ ] **Step 5: 更新 renderer 参数与 manifest**

`FullReadRenderer.render()`/`render_completed()` 传递：

```python
FullReadRenderer().render(
    workspace,
    translations,
    highlights,
    review=review,
    reader_revision=reader_revision,
    destination=staging / "reader_full.html",
)
```

manifest 新增 `reader_build_version`、`reader_revision`、`review`。`stable_keys` 也必须包含这三项，
否则导览变化会错误命中缓存。

- [ ] **Step 6: 测试并提交**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_full_read_service.py tests\test_reader_v2.py tests\test_pipeline_parse_translate.py -q
git diff --check
git add src/scientific_reading/full_read_service.py src/scientific_reading/full_read_renderer.py tests/test_full_read_service.py tests/test_reader_v2.py tests/test_pipeline_parse_translate.py
git commit -m "阅读器：发布可追溯导览与稳定修订身份"
```

## Task 3：渲染导览、语义重点和图表目录标记

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\reader\build_reader.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\src\scientific_reading\full_read_renderer.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`

- [ ] **Step 1: 写 DOM 失败测试**

在 `test_reader_v2.py` 增加 fixture guide，并断言：

```python
assert soup.body["data-paper-id"] == metadata.paper_id
assert soup.body["data-reader-revision"] == "b" * 64
assert soup.select_one(".reading-guide")
assert [node.get_text(" ", strip=True) for node in soup.select(".guide-card h2")] == [
    "研究问题", "关键方法", "核心结果", "局限性"
]
assert soup.select_one('.guide-source[href="#block-p0001-m0002"]')
assert soup.select_one('[data-highlight-kind="result"] .highlight-label').get_text(
    " ", strip=True
).startswith("核心结果/结论")
assert soup.select_one('[data-highlight-kind="method"] .highlight-label').get_text(
    " ", strip=True
).startswith("方法/证据")
assert not soup.find(string=re.compile("主要重点|次要重点|primary|secondary"))
assert soup.select_one('.toc-mark.result[title="核心结果/结论"]')
assert soup.select_one('.toc-mark.method[title="方法/证据"]')
assert soup.select_one('.toc-mark.figure[title="图"]')
assert soup.select_one('.toc-mark.table[title="表"]')
```

另测：缺失 guide 类别显示“原文未明确说明”但不生成假 source link；guide 文本和恶意题录被 escape；
隐藏重点 CSS 不隐藏 `.toc-mark.figure/.toc-mark.table`；旧 highlight loader 将 primary/secondary 归一
为 result/method。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py -q
```

预期：当前 builder 仍输出主要/次要重点，无 guide 和图表目录 mark。

- [ ] **Step 3: 固定 builder 版本、签名与兼容映射**

在 `reader/build_reader.py` 定义：

```python
READER_BUILD_VERSION = "reader-html-v2.1"
ALLOWED_HIGHLIGHT_KINDS = frozenset({"result", "method"})
LEGACY_HIGHLIGHT_KIND_MAP = {
    "primary": "result",
    "secondary": "method",
    "quick_read": "result",
    "full_review": "method",
}


def normalize_highlight_kind(value: str) -> str:
    normalized = LEGACY_HIGHLIGHT_KIND_MAP.get(value, value)
    if normalized not in ALLOWED_HIGHLIGHT_KINDS:
        raise ValueError("highlight_kind_invalid")
    return normalized
```

保持旧 `ALLOWED_HIGHLIGHT_SOURCES` 名称为兼容 alias，但新 renderer 与 manifest 只写 kind。扩展函数
签名：

```python
def build_reader(
    source: Path,
    output: Path,
    highlights: dict[str, tuple[str, str]],
    *,
    guide: dict[str, list[dict[str, object]]],
    paper_id: str,
    reader_revision: str,
) -> None:
```

验证 paper_id 非空、revision 匹配 64 位十六进制、guide source 已存在。为每个 reading block 加
`id="block-<block_id>"` 和 `scroll-margin-top`。

- [ ] **Step 4: 渲染四类导览**

在 hero 与 article 之间插入 `.reading-guide`。类别配置固定为：

```python
GUIDE_LABELS = {
    "research_question": "研究问题",
    "key_methods": "关键方法",
    "core_results": "核心结果",
    "limitations": "局限性",
}
```

每个 entry 输出纯文本和一个或多个 `.guide-source` anchor，标签为“原文 1”“原文 2”。空类别只输出
`<p class="guide-empty">原文未明确说明</p>`。链接只使用已验证 block ID。

- [ ] **Step 5: 替换用户语义与目录标记**

- wrapper 属性改为 `data-highlight-kind=result|method`；
- 黄色 label 为“核心结果/结论 · reason”；蓝色为“方法/证据 · reason”；
- CSS 和 legend 只使用 `.result/.method`；
- 根据每个 `.paper-asset.figure/.table` 最近的前置 h2/h3，为对应目录项加入 Figure/Table mark；
- `body.highlights-off` 只隐藏 `.toc-mark.result,.toc-mark.method`，不隐藏图表 mark。

- [ ] **Step 6: 运行测试并提交**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py tests\test_full_read_renderer.py -q
git diff --check
git add reader/build_reader.py src/scientific_reading/full_read_renderer.py tests/test_reader_v2.py
git commit -m "阅读器：加入一屏导览与语义目录标记"
```

## Task 4：英文总开关与有语境的重点模式

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\reader\build_reader.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`

- [ ] **Step 1: 写控制合同失败测试**

静态 DOM/CSS/JS 断言：

```python
assert soup.select_one("#toggle-sources")
assert soup.select_one("#toggle-highlights")
assert soup.select_one("#focus-highlights")
assert soup.select_one("#resume-reading")
assert "details.source-text" in script
assert "source.open = expanded" in script
assert "focus-near-highlight" in css
assert "focus-heading" in css
assert "body.highlights-off .toc-mark.result" in css
assert "body.highlights-off .toc-mark.figure" not in css
```

构造高亮段落前后各一张图表，断言只给立即相邻图表加 `.focus-near-highlight`，不把整章所有图表
加入重点模式。构造连续 3 个短列表项，断言只生成一个 `.source-text-group` 英文入口。

- [ ] **Step 2: 运行测试确认 RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py -q
```

- [ ] **Step 3: 加入英文总开关**

工具条增加：

```html
<button id="toggle-sources" type="button" aria-pressed="false">展开全部英文</button>
```

脚本使用：

```javascript
const sourceButton = document.querySelector('#toggle-sources');
const sourceDetails = [...document.querySelectorAll('details.source-text')];
sourceButton.addEventListener('click', () => {
  const expanded = sourceButton.getAttribute('aria-pressed') !== 'true';
  sourceDetails.forEach((source) => { source.open = expanded; });
  sourceButton.setAttribute('aria-pressed', String(expanded));
  sourceButton.textContent = expanded ? '收起全部英文' : '展开全部英文';
});
```

单段手动开合不改变总按钮，直到用户再次点击总开关；中文始终留在 DOM。

- [ ] **Step 4: 为只看重点标注确定性语境**

生成时为每个高亮 block 的最近前置 h2/h3 加 `.focus-heading`；其立即前/后元素兄弟若为
`.paper-asset`，加 `.focus-near-highlight`。CSS focus-only 只保留：

```css
article.focus-only > * { display: none; }
article.focus-only > .reading-block.is-highlighted,
article.focus-only > .reading-group.has-highlight,
article.focus-only > .paper-asset.focus-near-highlight,
article.focus-only > .focus-heading { display: block; }
article.focus-only .reading-block.is-highlighted { break-inside: avoid; }
```

导览位于 article 外，因此重点模式始终保留。按钮文案只使用“只看重点”/“显示全部”。隐藏重点只
改变底色/label/语义目录点，不改变 focus 过滤状态。

- [ ] **Step 5: 测试并提交**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py -q
git diff --check
git add reader/build_reader.py tests/test_reader_v2.py
git commit -m "阅读器：加入英文总开关与重点语境"
```

## Task 5：图表放大、响应式目录和阅读位置恢复

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\reader\build_reader.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_interactions.py`

- [ ] **Step 1: 写离线交互失败测试**

用 BeautifulSoup/字符串合同断言：唯一 `<dialog id="asset-dialog">`、每张 Figure 有放大触发按钮、
每张 Table 有【放大表格】、无新增 base64 图片副本、无 http(s) 资源、body 有 paper/revision、脚本包含
hash 优先、safe localStorage、滚动节流、focus return 和 Esc 关闭。

`test_reader_interactions.py` 固定检查：

```python
def test_reader_uses_revision_not_self_hash_for_progress(rendered_html):
    assert 'dataset.readerRevision' in rendered_html
    assert 'reader_sha256' not in rendered_html


def test_reader_respects_url_hash_before_saved_position(rendered_html):
    assert "if (!location.hash && savedAtLoad)" in rendered_html


def test_reader_local_storage_failures_are_non_fatal(rendered_html):
    assert "try {" in rendered_html
    assert "localStorage.getItem" in rendered_html
    assert "catch (_error)" in rendered_html
```

- [ ] **Step 2: 运行测试确认 RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py tests\test_reader_interactions.py -q
```

- [ ] **Step 3: 实现单一离线 dialog**

builder 在 body 尾部创建一个空 dialog、关闭按钮和内容容器。每个 Figure 图片/表格按钮只保存触发器；
点击时 clone 当前 DOM 节点到 dialog，不复制 base64 字符串到生成 HTML。关闭时清空容器并
`lastDialogTrigger.focus()`。dialog 不支持时按钮仍不影响原位置图表阅读。

- [ ] **Step 4: 实现安全进度状态**

脚本保存对象：

```javascript
{
  paperId,
  readerRevision,
  blockId,
  scrollRatio,
  updatedAt: new Date().toISOString()
}
```

key 为 ``sr-reader:${paperId}``。用 `requestAnimationFrame` 加 250ms 时间门限节流；最近 block 从当前
视口上缘附近的 `[data-block]`/heading 选择，不在每个 scroll 重新查询 DOM。加载时先缓存
`savedAtLoad`：有 URL hash 不恢复；revision 相同时优先 block、缺 block 用 ratio；revision 不同时只
尝试同 block，禁止用旧 ratio。【返回上次阅读位置】始终使用 `savedAtLoad`，不读取刚刚覆盖的新值。

所有 JSON parse、getItem/setItem 和 scrollTo 都放在 try/catch；失败时按钮 disabled，正文不受影响。

- [ ] **Step 5: 完成响应式和打印规则**

- 桌面 sidebar 240–260px，正文 `width: min(1080px, 100%)`；
- `<1000px` 使用现有 `.mobile-nav` details，桌面 sidebar 隐藏；
- `<680px` 工具条换行，不遮题名；
- Table 原位容器水平滚动；
- print 隐藏目录、工具条、progress、dialog trigger；只打印已展开英文。

- [ ] **Step 6: 测试并提交**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_reader_v2.py tests\test_reader_interactions.py -q
git diff --check
git add reader/build_reader.py tests/test_reader_v2.py tests/test_reader_interactions.py
git commit -m "阅读器：加入图表放大与阅读位置恢复"
```

## Task 6：完整性、兼容和浏览器验收

**Files:**

- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_full_read_renderer.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_reader_v2.py`
- Modify: `D:\Vibe Coding\Scientific-Reading-for-Newbies\tests\test_pipeline_parse_translate.py`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\tests\reading-routes.mjs`
- Modify: `D:\Vibe Coding\dsh-scientific-reading\docs\superpowers\plans\2026-08-23-two-stage-literature-workflow-phase-2-full-read-assets.md`

- [ ] **Step 1: 补兼容与失败回归**

覆盖：旧 `primary/secondary` JSON 输入只在 legacy loader 归一；旧 `reader_full.html` 路由不变；旧 HTML
文件 bytes/SHA 不被新测试改写；新合同缓存不命中旧 v1/v2 产物；guide/source/revision/HTML 任一被
篡改均不写 SQLite completed；参考文献仍为英文；caption source map/序号回归保持通过。

- [ ] **Step 2: 跑引擎目标测试**

```powershell
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe -m pytest `
  tests\test_full_read_models.py `
  tests\test_full_read_service.py `
  tests\test_full_read_renderer.py `
  tests\test_reader_v2.py `
  tests\test_reader_interactions.py `
  tests\test_pipeline_parse_translate.py -q
```

预期：全部通过，无网络、无飞书调用。

- [ ] **Step 3: 跑引擎全量测试**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

预期：在当前基线 `686 passed` 的基础上只增加测试，无失败；若测试总数因并行开发变化，以实际全量
零失败为准，并在 Phase 2 执行记录写明新数字。

- [ ] **Step 4: 在插件隔离 worktree 验证 reader 路由**

先用 `SR_ENGINE_ROOT` 指向引擎 worktree，再执行：

```powershell
$env:SR_ENGINE_ROOT = "D:\Vibe Coding\Scientific-Reading-for-Newbies\.worktrees\two-stage-workflow"
npm.cmd run build:ci
npm.cmd run typecheck
node tests\reading-routes.mjs
npm.cmd run test:offline
git diff --check
```

`reading-routes.mjs` 只需新增新 reader HTML 可服务、旧路径仍回退、HTML 中无远程资源的断言；不要
把 renderer 逻辑复制到 TypeScript。

- [ ] **Step 5: 隔离浏览器 QA**

在 Phase 2 的假工程论文、独立 Profile/端口完成：

- 1440×900：目录展开/收起、正文宽度、导览一屏附近；
- 1280×720：长题名和 sticky 工具条不重叠；
- 900×720：目录变移动抽屉；
- 中英总开关、隐藏重点、只看重点/显示全部；
- 导览 source link、黄/蓝/图/表目录标记；
- Figure/Table dialog、Esc 关闭与焦点返回；
- 关闭再打开恢复位置；带 hash 打开不被旧位置覆盖；
- localStorage 禁用后仍完整阅读；
- 浏览器 console error 为 0。

不更新当前 3080，不使用真实论文、飞书或机构认证。

- [ ] **Step 6: 更新原 Phase 2 执行记录并提交**

记录 v2.1 commit、目标/全量测试、三个 viewport、reader revision/HTML/PDF SHA、旧 reader bytes 不变。

```powershell
git add tests/reading-routes.mjs docs/superpowers/plans/2026-08-23-two-stage-literature-workflow-phase-2-full-read-assets.md
git commit -m "验收：记录精读HTML v2.1离线实测"
```

## 最终自检

- 新 reader 不出现“primary”“secondary”“主要重点”“次要重点”；
- 只有黄/蓝两种正文高亮，局限性只在导览；
- 导览所有可见内容都有当前代际 source block；
- 英文默认收起且可全局切换；
- 只看重点保留完整段落、标题和紧邻图表；
- 目录有语义和图表标记；
- localStorage 只存位置元数据；
- HTML 仍离线单文件；
- manifest 同时保存 reader revision 与最终 HTML SHA；
- 旧 reader 不移动、不删除、不自动重渲染；
- 当前 3080、飞书和用户数据未被测试触碰。
