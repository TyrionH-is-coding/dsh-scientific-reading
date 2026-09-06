from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from reader.build_reader import READER_BUILD_VERSION
from scientific_reading.full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
    FullReviewSubmission,
    Translation,
)
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.full_read_service import FullReadService
from scientific_reading.models import JobState, StageRecord
from scientific_reading.workspace import PaperWorkspace


BLOCK_ID = "p0001-m0001"
SOURCE_SHA = "a" * 64
READER_REVISION = "b" * 64
SOURCE_TEXT = "A deterministic engineering fixture."


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _review_value() -> dict[str, object]:
    return {
        "contract_version": FULL_REVIEW_CONTRACT_VERSION,
        "highlights": [],
        "guide": {
            "research_question": [
                {
                    "text": "Which deterministic behavior is being tested?",
                    "source_block_ids": [BLOCK_ID],
                }
            ],
            "key_methods": [],
            "core_results": [],
            "limitations": [],
        },
    }


def _completed_input_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PaperWorkspace, Translation, FullReviewSubmission]:
    workspace = PaperWorkspace(root=tmp_path / "generation")
    full = workspace.reading_dir / "full"
    full.mkdir(parents=True)
    translation = Translation(
        block_id=BLOCK_ID,
        source_text=SOURCE_TEXT,
        translation_zh="一个确定性的工程测试样例。",
        highlight="none",
    )
    review_value = _review_value()
    review = FullReviewSubmission.from_dict(
        review_value,
        available_block_ids={BLOCK_ID},
        substantive_block_count=1,
    )
    (full / "translations.json").write_text(
        json.dumps(
            {
                "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
                "source_sha256": SOURCE_SHA,
                "translations": [
                    {
                        "block_id": BLOCK_ID,
                        "source_text": SOURCE_TEXT,
                        "translation_zh": translation.translation_zh,
                        "highlight": "none",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (full / "reading_guide.json").write_text(
        json.dumps(
            {
                "contract_version": FULL_REVIEW_CONTRACT_VERSION,
                "reader_revision": READER_REVISION,
                "guide": review_value["guide"],
            }
        ),
        encoding="utf-8",
    )
    (full / "highlights.json").write_text(
        json.dumps(
            {
                "contract_version": FULL_REVIEW_CONTRACT_VERSION,
                "highlights": [],
            }
        ),
        encoding="utf-8",
    )
    workspace.save_job(
        JobState(
            paper_id=workspace.root.name,
            stages={
                "full_read": StageRecord(
                    status="completed",
                    result={
                        "reader_revision": READER_REVISION,
                        "reader_build_version": READER_BUILD_VERSION,
                        "review": review_value,
                    },
                )
            },
        )
    )
    active = SimpleNamespace(
        source_sha256=SOURCE_SHA,
        rows=(
            {
                "block_id": BLOCK_ID,
                "english": SOURCE_TEXT,
                "source_type": "text",
            },
        ),
    )
    monkeypatch.setattr(
        FullReadService,
        "_inspect_active_mineru",
        staticmethod(lambda _workspace: active),
    )
    monkeypatch.setattr(
        FullReadService,
        "_collect_translations",
        lambda _self, _workspace: (active, {BLOCK_ID: translation}),
    )
    return workspace, translation, review


def test_render_preview_completed_writes_only_explicit_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, translation, review = _completed_input_workspace(
        tmp_path, monkeypatch
    )
    formal_reader = workspace.reading_dir / "reader.html"
    formal_reader.write_text("formal reader", encoding="utf-8")
    before = _tree_hashes(workspace.root)
    output = tmp_path / "review" / "reader.html"
    renderer = FullReadRenderer(
        publish_hook=lambda _stage, _path: pytest.fail(
            "preview must not call publish hook"
        )
    )

    def fake_render(
        received_workspace: PaperWorkspace,
        translations: dict[str, Translation],
        highlights: dict[str, tuple[str, str]],
        received_output: Path,
        *,
        review: FullReviewSubmission,
        reader_revision: str,
        paper_id: str,
    ) -> Path:
        assert received_workspace == workspace
        assert translations == {BLOCK_ID: translation}
        assert highlights == {}
        assert review == expected_review
        assert reader_revision == READER_REVISION
        assert paper_id == "fixture_preview"
        received_output.parent.mkdir(parents=True)
        received_output.write_text("candidate reader", encoding="utf-8")
        return received_output

    expected_review = review
    monkeypatch.setattr(renderer, "render", fake_render)

    result = renderer.render_preview_completed(
        workspace,
        output=output,
        paper_id="fixture_preview",
    )

    assert result == output
    assert output.read_text(encoding="utf-8") == "candidate reader"
    assert _tree_hashes(workspace.root) == before


def test_completed_input_loader_rejects_tampered_translation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, _translation, _review = _completed_input_workspace(
        tmp_path, monkeypatch
    )
    translation_path = workspace.reading_dir / "full" / "translations.json"
    payload = json.loads(translation_path.read_text(encoding="utf-8"))
    payload["source_sha256"] = "c" * 64
    translation_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="translation_manifest_invalid"):
        FullReadRenderer()._load_completed_reader_inputs(workspace)
