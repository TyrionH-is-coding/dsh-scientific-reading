from __future__ import annotations

import json
from pathlib import Path

from scientific_reading.full_read_models import FULL_TRANSLATION_CONTRACT_VERSION
from scientific_reading.full_read_service import (
    FULL_READ_PLAN_CONTRACT_VERSION,
    FULL_READ_SOURCE_CONTRACT_VERSION,
    FullReadPlanResult,
    FullReadService,
)
from scientific_reading.workspace import PaperWorkspace


def _batch_plan(batch_id: str) -> dict:
    return {
        "batch_id": batch_id,
        "source_file": f"batches/{batch_id}.source.json",
        "translation_file": f"batches/{batch_id}.translation.json",
        "block_ids": ["p0001-m0001"],
        "input_sha256": "c" * 64,
        "byte_count": 12,
        "oversized": False,
    }


def test_next_batch_skips_stale_translation_instead_of_failing(
    tmp_path: Path,
) -> None:
    workspace = PaperWorkspace(root=tmp_path)
    root = workspace.reading_dir / "full"
    batches = root / "batches"
    batches.mkdir(parents=True)
    source = {
        "contract_version": FULL_READ_SOURCE_CONTRACT_VERSION,
        "translation_contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
        "batch_id": "batch-0001",
        "source_sha256": "a" * 64,
        "blocks": [
            {
                "block_id": "p0001-m0001",
                "page": 1,
                "source_type": "text",
                "text_level": None,
                "english": "Current MinerU wording.",
            }
        ],
    }
    (batches / "batch-0001.source.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (batches / "batch-0001.translation.json").write_text(
        json.dumps(
            {
                "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
                "batch_id": "batch-0001",
                "source_sha256": "a" * 64,
                "translations": [
                    {
                        "block_id": "p0001-m0001",
                        "source_text": "Old MinerU wording.",
                        "translation_zh": "旧译文。",
                        "highlight": "none",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    service = FullReadService()
    service._prepared[workspace.root] = FullReadPlanResult(
        plan={
            "contract_version": FULL_READ_PLAN_CONTRACT_VERSION,
            "batches": [_batch_plan("batch-0001")],
        },
        batch_paths=(batches / "batch-0001.source.json",),
        cached=True,
    )

    pending = service.next_batch(workspace)

    assert pending["batch_id"] == "batch-0001"
    assert not (batches / "batch-0001.translation.json").exists()
    archived = list((root / "invalid").glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["translations"][0]["translation_zh"] == "旧译文。"
