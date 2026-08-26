from __future__ import annotations

from pathlib import Path

from scientific_reading.background_models import BackgroundRequest
from scientific_reading.background_store import BackgroundJobStore
from scientific_reading.full_read_service import FullReadError
from scientific_reading.worker import full_read_handler_factory, run_job


class _Service:
    def __init__(self, *, mineru_missing: bool = False) -> None:
        self.translated = False
        self.mineru_missing = mineru_missing

    def prepare(self, _workspace):
        if self.mineru_missing:
            raise FullReadError("mineru_required_for_full_read")

    def next_batch(self, _workspace):
        if self.translated:
            return None
        return {
            "contract_version": "full-read-source-v1",
            "translation_contract_version": "full-translation-v2",
            "batch_id": "batch-0001",
            "source_sha256": "a" * 64,
            "blocks": [
                {
                    "block_id": "p0001-m0001",
                    "page": 1,
                    "source_type": "text",
                    "text_level": None,
                    "english": "Synthetic bridge paragraph.",
                }
            ],
        }

    def save_next_translation(self, _workspace, value):
        if value.get("batch_id") != "batch-0001":
            raise ValueError("translation_batch_mismatch")
        self.translated = True

    def review_context(self, _workspace):
        return {
            "contract_version": "full-review-v1",
            "translations_json": "D:/paper/translations.json",
            "source_map_json": "D:/paper/source_map.json",
            "translation_count": 1,
            "substantive_block_count": 1,
            "maximum_full_review_highlights": 1,
        }

    def finalize(self, _workspace, value):
        if value.get("contract_version") != "full-review-v1":
            raise ValueError("full_review_contract_invalid")
        return {
            "status": "full_read_ready",
            "reader_full_html": "D:/paper/reader_full.html",
        }


def _request(tmp_path: Path, metadata) -> BackgroundRequest:
    return BackgroundRequest(
        paper_id="doi_10.5555_bridge.2024.1",
        target_stage="full_read",
        input_hash="a" * 64,
        payload={
            "data_root": str(tmp_path),
            "metadata": metadata.to_dict(),
        },
    )


def test_worker_recovers_translation_then_review_gates(
    tmp_path,
    metadata,
) -> None:
    store = BackgroundJobStore(tmp_path)
    handle = store.create_or_get(_request(tmp_path, metadata))
    service = _Service()
    handlers = {"full_read": full_read_handler_factory(service)}

    assert run_job(store, handle.job_id, handlers=handlers) == 3
    status = store.load_status(handle.job_id)
    assert status.state == "waiting_agent"
    assert status.reason_code == "translate_full_read"
    assert status.required_input["batch_id"] == "batch-0001"

    store.save_resume_input(
        handle.job_id,
        {
            "full_translation": {
                "contract_version": "full-translation-v2",
                "batch_id": "batch-0001",
                "source_sha256": "a" * 64,
                "translations": [
                    {
                        "block_id": "p0001-m0001",
                        "source_text": "Synthetic bridge paragraph.",
                        "translation_zh": "合成桥梁段落。",
                        "highlight": "primary",
                    }
                ],
            }
        },
    )
    store.transition(handle.job_id, "queued")
    assert run_job(store, handle.job_id, handlers=handlers) == 3
    status = store.load_status(handle.job_id)
    assert status.reason_code == "review_full_read"
    assert status.required_input["translation_count"] == 1

    store.save_resume_input(
        handle.job_id,
        {
            "full_review": {
                "contract_version": "full-review-v1",
                "highlights": [],
                "key_points": ["合成关键点"],
            }
        },
    )
    store.transition(handle.job_id, "queued")
    assert run_job(store, handle.job_id, handlers=handlers) == 0
    status = store.load_status(handle.job_id)
    assert status.state == "completed"
    assert status.result["status"] == "full_read_ready"


def test_worker_reports_mineru_and_revision_gates(
    tmp_path,
    metadata,
) -> None:
    store = BackgroundJobStore(tmp_path)
    handle = store.create_or_get(_request(tmp_path, metadata))

    code = run_job(
        store,
        handle.job_id,
        handlers={
            "full_read": full_read_handler_factory(
                _Service(mineru_missing=True)
            )
        },
    )

    assert code == 3
    status = store.load_status(handle.job_id)
    assert status.reason_code == "mineru_required_for_full_read"
    assert status.required_input["upgrade_reason"] == "full-read"
