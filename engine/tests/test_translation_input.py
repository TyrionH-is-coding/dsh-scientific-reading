from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest

from scientific_reading.__main__ import _validate_full_read_resume
from scientific_reading.full_read_models import FULL_TRANSLATION_CONTRACT_VERSION
from scientific_reading.full_read_service import FullReadError, FullReadPlanResult, FullReadService, _json_bytes
from scientific_reading.models import PaperMetadata
from scientific_reading.workspace import PaperWorkspace


@pytest.fixture
def prepared(tmp_path):
    workspace = PaperWorkspace.create(tmp_path, PaperMetadata(title="翻译提交测试", authors=["Fixture"]))
    root = workspace.reading_dir / "full"
    (root / "batches").mkdir(parents=True)
    blocks = [{"block_id": f"p0001-m{i:04}", "english": f"Exact source {i}: α ≥ β.",
               "source_type": "reference" if i == 3 else "text"} for i in range(1, 4)]
    source = FullReadService._source_payload("batch-0001", "a" * 64, blocks)
    raw = _json_bytes(source)
    sha = hashlib.sha256(raw).hexdigest()
    source_path = root / "batches/batch-0001.source.json"
    source_path.write_bytes(raw)
    plan = {"batch_id": "batch-0001", "source_file": "batches/batch-0001.source.json",
            "translation_file": "batches/batch-0001.translation.json", "block_ids": [row["block_id"] for row in blocks],
            "input_sha256": sha, "oversized": False}
    service = FullReadService()
    service._prepared[workspace.root] = FullReadPlanResult(plan={"batches": [plan]}, batch_paths=(source_path,), cached=True)
    value = {"contract_version": "full-translation-v4", "batch_id": "batch-0001", "source_sha256": "a" * 64,
             "batch_sha256": sha, "translations": [{"block_id": row["block_id"], "translation_zh": "" if i == 2 else f"译文 {i}"}
                                                       for i, row in enumerate(blocks)]}
    return service, workspace, root, source, value


def test_compact_input_binds_native_source_and_keeps_canonical_v3(prepared):
    service, workspace, root, source, value = prepared
    gate = service.next_batch(workspace)
    assert gate["submission_contract_version"] == "full-translation-v4"
    assert gate["batch_sha256"] == value["batch_sha256"]
    status = SimpleNamespace(state="waiting_agent", reason_code="translate_full_read")
    assert _validate_full_read_resume(status, {"full_translation": value})["full_translation"] == value
    destination = service.save_translation_batch(workspace, value)
    saved = json.loads(destination.read_text(encoding="utf-8"))
    assert saved["contract_version"] == FULL_TRANSLATION_CONTRACT_VERSION
    assert [row["source_text"] for row in saved["translations"]] == [row["english"] for row in source["blocks"]]
    assert all(row["highlight"] == "none" for row in saved["translations"])
    assert service.next_batch(workspace) is None
    assert service.save_translation_batch(workspace, value) == destination


def test_missing_translation_is_retained_as_a_draft_then_completed_after_restart(prepared):
    service, workspace, root, _, value = prepared
    incomplete = copy.deepcopy(value)
    incomplete["translations"][1]["translation_zh"] = ""
    service.save_translation_batch(workspace, incomplete)
    assert not (root / "batches/batch-0001.translation.json").exists()
    gate = service.next_batch(workspace)
    assert gate["remaining_block_ids"] == ["p0001-m0002"]
    assert gate["accepted_blocks"] == 2
    restored = FullReadService()
    restored._prepared = dict(service._prepared)
    remainder = {**value, "translations": [value["translations"][1]]}
    saved = json.loads(restored.save_translation_batch(workspace, remainder).read_text(encoding="utf-8"))
    assert len(saved["translations"]) == 3
    assert saved["translations"][0]["translation_zh"] == value["translations"][0]["translation_zh"]
    assert not (root / "batches/batch-0001.draft.json").exists()


@pytest.mark.parametrize("kind", ["source_sha", "batch_sha", "batch_id", "unknown", "duplicate", "reorder", "extra_field"])
def test_compact_input_rejects_wrong_binding_and_ambiguous_rows(prepared, kind):
    service, workspace, root, _, original = prepared
    value = copy.deepcopy(original)
    if kind == "source_sha": value["source_sha256"] = "b" * 64
    elif kind == "batch_sha": value["batch_sha256"] = "b" * 64
    elif kind == "batch_id": value["batch_id"] = "batch-9999"
    elif kind == "unknown": value["translations"][0]["block_id"] = "p0099-m9999"
    elif kind == "duplicate": value["translations"][1] = value["translations"][0]
    elif kind == "reorder": value["translations"].reverse()
    else: value["translations"][0]["source_text"] = "model must not echo source"
    with pytest.raises(ValueError): service.save_translation_batch(workspace, value)
    assert not list((root / "batches").glob("*.translation.json"))
    assert not list((root / "batches").glob("*.draft.json"))


def test_retry_does_not_replace_an_accepted_draft_translation(prepared):
    service, workspace, root, _, value = prepared
    first = {**value, "translations": value["translations"][:1]}
    service.save_translation_batch(workspace, first)
    draft = root / "batches/batch-0001.draft.json"
    before = draft.read_bytes()
    changed = copy.deepcopy(first)
    changed["translations"][0]["translation_zh"] = "不同译文"
    with pytest.raises(ValueError, match="translation_batch_conflict"):
        service.save_translation_batch(workspace, changed)
    assert draft.read_bytes() == before


def test_legacy_v3_can_complete_a_compact_draft_without_rewriting_source(prepared):
    service, workspace, root, source, value = prepared
    service.save_translation_batch(workspace, {**value, "translations": value["translations"][:1]})
    legacy = {key: val for key, val in value.items() if key != "batch_sha256"}
    legacy["contract_version"] = FULL_TRANSLATION_CONTRACT_VERSION
    legacy["translations"] = [{**row, "source_text": block["english"], "highlight": "none"}
                               for row, block in zip(value["translations"], source["blocks"])]
    conflicting = copy.deepcopy(legacy)
    conflicting["translations"][0]["translation_zh"] = "不得改写已经保存的译文"
    with pytest.raises(ValueError, match="translation_batch_conflict"):
        service.save_translation_batch(workspace, conflicting)
    service.save_translation_batch(workspace, legacy)
    assert service.next_batch(workspace) is None
    assert not (root / "batches/batch-0001.draft.json").exists()


def test_pipeline_limits_incomplete_batch_to_two_retries_and_preserves_draft(prepared, tmp_path):
    from scientific_reading.background_models import AgentRequired
    from scientific_reading.library_service import LibraryService
    from scientific_reading.reading_pipeline import ReadingPipeline
    from scientific_reading.reading_pipeline_models import ReadingPipelineState

    service, workspace, root, _, value = prepared
    library = LibraryService(tmp_path)
    try:
        paper_id = library.ingest(PaperMetadata(title="有限补试", authors=["Fixture"]))["paper_id"]
    finally:
        library.close()

    def runner(stage, state, supplied):
        if supplied and "full_translation" in supplied:
            service.save_translation_batch(workspace, supplied["full_translation"])
        batch = service.next_batch(workspace)
        if batch:
            raise AgentRequired("translate_full_read", ReadingPipeline._translation_gate(workspace, batch))
        raise AgentRequired("review_full_read", {"stage": "translate_full", "contract_version": "full-review-v3"})

    pipeline = ReadingPipeline(tmp_path, stage_runner=runner)
    state = pipeline.start(paper_id)
    state.current_stage = "translate_full"
    pipeline._save(state)
    state = pipeline.advance(state.parent_job_id)
    assert state.state == "waiting_agent"
    partial = {"full_translation": {**value, "translations": value["translations"][:1]}}
    for remaining in (2, 1, 0):
        state = pipeline.advance(state.parent_job_id, partial)
        assert state.required_action["automatic_retries_remaining"] == remaining
    assert state.state == "needs_user"
    assert state.required_action["reason_code"] == "translation_retry_limit"
    assert state.required_action["accepted_blocks"] == 1
    draft = (root / "batches/batch-0001.draft.json").read_bytes()
    restored = ReadingPipeline(tmp_path, stage_runner=runner)
    assert restored.advance(state.parent_job_id, partial).state == "needs_user"
    status = SimpleNamespace(state="waiting_user", reason_code="translation_retry_limit")
    with pytest.raises(ValueError, match="confirmation_required"):
        _validate_full_read_resume(status, partial)
    retry = _validate_full_read_resume(status, {"retry_translation": True})
    state = restored.advance(state.parent_job_id, retry)
    assert state.state == "waiting_agent"
    assert (root / "batches/batch-0001.draft.json").read_bytes() == draft
    state = restored.advance(state.parent_job_id, {"full_translation": {**value, "translations": value["translations"][1:]}})
    assert state.required_action["reason_code"] == "review_full_read"
    assert service.next_batch(workspace) is None
    assert ReadingPipelineState.from_dict(state.to_dict()).translation_attempts == {}


def test_compact_draft_rejects_changed_source_and_preserves_corrupt_draft(prepared):
    service, workspace, root, _, value = prepared
    source_path = root / "batches/batch-0001.source.json"
    original = source_path.read_bytes()
    source_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="translation_batch_sha_mismatch"):
        service.save_translation_batch(workspace, value)
    source_path.write_bytes(original)
    draft = root / "batches/batch-0001.draft.json"
    draft.write_text("{invalid draft", encoding="utf-8")
    with pytest.raises(FullReadError, match="translation_draft_invalid"):
        service.save_translation_batch(workspace, value)
    assert draft.read_text(encoding="utf-8") == "{invalid draft"
