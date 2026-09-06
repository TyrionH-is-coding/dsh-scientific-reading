import json

import pytest

from scientific_reading.full_read_service import FullReadService
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.reading_pipeline import ReadingPipeline
from test_mineru_current_output import _published_workspace


def test_review_v3_can_remove_excess_translation_highlights_and_reader_validates(tmp_path):
    workspace = _published_workspace(tmp_path)
    service = FullReadService()
    plan = service.prepare(workspace)
    source = json.loads(plan.batch_paths[0].read_text(encoding="utf-8"))
    service.save_translation_batch(workspace, {
        "contract_version": source["translation_contract_version"],
        "batch_id": source["batch_id"], "source_sha256": source["source_sha256"],
        "translations": [{
            "block_id": block["block_id"], "source_text": block["english"],
            "translation_zh": "" if block["source_type"] == "reference" else "测试译文",
            "highlight": "none" if block["source_type"] == "reference" else "method",
        } for block in source["blocks"]],
    })
    context = service.review_context(workspace)
    assert context["contract_version"] == "full-review-v3"
    assert ReadingPipeline._normalize_required_action(context) == context
    review = {
        "contract_version": "full-review-v2", "highlights": [],
        "guide": {
            "research_question": [{"text": "测试研究问题", "source_block_ids": [context["available_source_block_ids"][0]]}],
            "key_methods": [], "core_results": [], "limitations": [],
        },
    }
    with pytest.raises(ValueError, match="full_review_highlight_limit"):
        service.finalize(workspace, review)
    review["contract_version"] = "full-review-v3"
    result = service.finalize(workspace, review)
    assert result["highlight_count"] == 0
    FullReadRenderer().render_completed(workspace, paper_id=workspace.root.name)
