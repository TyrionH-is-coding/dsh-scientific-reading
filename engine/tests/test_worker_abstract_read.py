from scientific_reading.background_models import BackgroundRequest
from scientific_reading.background_store import BackgroundJobStore
import hashlib
import json

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.worker import abstract_read_handler_factory, run_job
from scientific_reading.workspace import PaperWorkspace, atomic_write_json


def _library_request(tmp_path, metadata):
    library = LibraryService(tmp_path)
    try:
        item = library.ingest(metadata)
    finally:
        library.close()
    store = BackgroundJobStore(tmp_path)
    request = BackgroundRequest(
        item["paper_id"],
        "abstract_read",
        "a" * 64,
        {"data_root": str(tmp_path), "metadata": metadata.to_dict()},
    )
    return store, store.create_or_get(request).job_id, item["paper_id"]


def _abstract_status(tmp_path, paper_id):
    with __import__("sqlite3").connect(tmp_path / "library.sqlite") as conn:
        return conn.execute(
            "SELECT status, abstract_status FROM items WHERE paper_id=?", (paper_id,)
        ).fetchone()

def test_worker_abstract_read_requires_translation_only_when_english_exists(tmp_path):
    store = BackgroundJobStore(tmp_path)
    request = BackgroundRequest("doi_10.1_x", "abstract_read", "a"*64, {"data_root":str(tmp_path), "metadata":{"title":"Fake","doi":"10.1/x","abstract_en":"One\n\nTwo"}})
    job = store.create_or_get(request).job_id
    assert run_job(store, job, handlers={"abstract_read": abstract_read_handler_factory()}) == 3
    status = store.load_status(job)
    assert status.reason_code == "translate_abstract"
    assert status.required_input["contract_version"] == "abstract-translation-v1"


def test_missing_abstract_updates_dedicated_status_without_overwriting_main_status(tmp_path):
    metadata = PaperMetadata(title="Missing abstract", doi="10.1/missing")
    store, job, paper_id = _library_request(tmp_path, metadata)

    assert run_job(store, job, handlers={"abstract_read": abstract_read_handler_factory()}) == 0

    assert _abstract_status(tmp_path, paper_id) == ("library_ready", "missing")


def test_waiting_agent_uses_dedicated_status(tmp_path):
    metadata = PaperMetadata(title="Available abstract", doi="10.1/available", abstract_en="One")
    store, job, paper_id = _library_request(tmp_path, metadata)

    assert run_job(store, job, handlers={"abstract_read": abstract_read_handler_factory()}) == 3

    assert _abstract_status(tmp_path, paper_id) == ("library_ready", "waiting_agent")


def test_published_abstract_maps_to_completed_without_overwriting_main_status(tmp_path):
    metadata = PaperMetadata(title="Published abstract", doi="10.1/published", abstract_en="One")
    store, job, paper_id = _library_request(tmp_path, metadata)
    workspace = PaperWorkspace.create(tmp_path, metadata)
    source_sha = hashlib.sha256(b"One").hexdigest()
    atomic_write_json(
        workspace.reading_dir / "abstract_read.json",
        {
            "contract_version": "abstract-translation-v1",
            "source_sha256": source_sha,
            "paragraphs": [{"index": 0, "source_en": "One", "translation_zh": "一"}],
        },
    )

    assert run_job(store, job, handlers={"abstract_read": abstract_read_handler_factory()}) == 0

    assert _abstract_status(tmp_path, paper_id) == ("library_ready", "completed")


def test_stale_abstract_retains_stale_dedicated_status_while_waiting(tmp_path):
    metadata = PaperMetadata(title="Stale abstract", doi="10.1/stale", abstract_en="New")
    store, job, paper_id = _library_request(tmp_path, metadata)
    workspace = PaperWorkspace.create(tmp_path, metadata)
    atomic_write_json(
        workspace.reading_dir / "abstract_read.json",
        {
            "contract_version": "abstract-translation-v1",
            "source_sha256": "b" * 64,
            "paragraphs": [],
        },
    )

    assert run_job(store, job, handlers={"abstract_read": abstract_read_handler_factory()}) == 3

    assert _abstract_status(tmp_path, paper_id) == ("library_ready", "stale")
