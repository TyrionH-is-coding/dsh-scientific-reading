from __future__ import annotations

import hashlib
from types import SimpleNamespace

from scientific_reading.background_models import BackgroundRequest, JobStatus
from scientific_reading.background_store import BackgroundJobStore
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.reading_pipeline import ReadingPipeline
from scientific_reading.reading_pipeline_models import ReadingPipelineState
from scientific_reading.worker import full_read_pipeline_handler_factory, run_job
from scientific_reading.workspace import PaperWorkspace


def _ingest(root, metadata: PaperMetadata) -> str:
    library = LibraryService(root)
    try:
        return library.ingest(metadata)["paper_id"]
    finally:
        library.close()


def _pdf_bytes(metadata: PaperMetadata, marker: str) -> bytes:
    return (
        "%PDF-1.4\n"
        f"{metadata.title}\nDOI: {metadata.doi}\n{marker}\n"
        "%%EOF\n"
    ).encode("utf-8")


def test_missing_pdf_parent_survives_lost_library_pointer(tmp_path, metadata):
    paper_id = _ingest(tmp_path, metadata)
    workspace = PaperWorkspace.create_for_paper_id(tmp_path, paper_id, metadata)
    content = _pdf_bytes(metadata, "attached source")
    sha = hashlib.sha256(content).hexdigest()
    pipeline = ReadingPipeline(tmp_path, stage_runner=lambda *_: {"status": "pdf_ready", "source_pdf_sha256": sha})
    first = pipeline.start(paper_id)
    workspace.source_pdf.write_bytes(content)
    pipeline.advance(first.parent_job_id)
    library = LibraryService(tmp_path)
    try:
        library.conn.execute("UPDATE items SET active_job_id=NULL WHERE paper_id=?", (paper_id,))
        library.conn.commit()
    finally:
        library.close()
    assert ReadingPipeline(tmp_path).start(paper_id).parent_job_id == first.parent_job_id
    competing = pipeline.job_store.create_or_get(pipeline._parent_request(paper_id, sha))
    library = LibraryService(tmp_path)
    try:
        library.update_full_read_state(paper_id, "queued", competing.job_id)
    finally:
        library.close()
    assert pipeline.start(paper_id, expected_parent_job_id=first.parent_job_id).parent_job_id == first.parent_job_id
    workspace.source_pdf.write_bytes(_pdf_bytes(metadata, "changed source"))
    import pytest
    with pytest.raises(RuntimeError, match="full_read_parent_mismatch"):
        pipeline.start(paper_id, expected_parent_job_id=first.parent_job_id)
    assert ReadingPipeline(tmp_path).start(paper_id).parent_job_id != first.parent_job_id


def test_start_does_not_resume_unfinished_parent_after_source_changes(
    tmp_path, metadata
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    workspace = PaperWorkspace.create_for_paper_id(tmp_path, paper_id, metadata)
    first_pdf = _pdf_bytes(metadata, "first source")
    second_pdf = _pdf_bytes(metadata, "replacement source")
    workspace.source_pdf.write_bytes(first_pdf)
    first_sha = hashlib.sha256(first_pdf).hexdigest()

    pipeline = ReadingPipeline(
        tmp_path,
        stage_runner=lambda *_: {
            "status": "pdf_ready",
            "source_pdf_sha256": first_sha,
        },
    )
    first = pipeline.start(paper_id)
    advanced = pipeline.advance(first.parent_job_id)
    assert advanced.source_pdf_sha256 == first_sha
    workspace.source_pdf.write_bytes(second_pdf)

    restarted = pipeline.start(paper_id)

    assert restarted.parent_job_id != first.parent_job_id
    assert restarted.current_stage == "ensure_pdf"
    assert pipeline.inspect(first.parent_job_id).source_pdf_sha256 == first_sha
    library = LibraryService(tmp_path)
    try:
        assert library.get_item(paper_id)["active_job_id"] == restarted.parent_job_id
    finally:
        library.close()


def test_new_source_can_start_with_a_different_provider_profile(
    tmp_path, metadata
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    workspace = PaperWorkspace.create_for_paper_id(tmp_path, paper_id, metadata)
    first_pdf = _pdf_bytes(metadata, "first source")
    workspace.source_pdf.write_bytes(first_pdf)
    first_sha = hashlib.sha256(first_pdf).hexdigest()
    pipeline = ReadingPipeline(
        tmp_path,
        stage_runner=lambda *_: {
            "status": "pdf_ready",
            "source_pdf_sha256": first_sha,
        },
    )
    first = pipeline.start(paper_id, "none")
    pipeline.advance(first.parent_job_id)
    workspace.source_pdf.write_bytes(_pdf_bytes(metadata, "replacement source"))

    restarted = pipeline.start(paper_id, "scansci")

    assert restarted.parent_job_id != first.parent_job_id


def test_default_schedule_stage_enqueues_xlsx_snapshot(
    tmp_path, metadata, monkeypatch
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    captured: dict[str, object] = {}

    class FakeLauncher:
        def __init__(self, data_root):
            captured["data_root"] = data_root

        def enqueue(self, request):
            captured["request"] = request
            return SimpleNamespace(
                job_id="job_0123456789abcdef",
                status=JobStatus(
                    job_id="job_0123456789abcdef",
                    state="queued",
                    created_at="2026-09-05T00:00:00+00:00",
                    updated_at="2026-09-05T00:00:00+00:00",
                ),
            )

    monkeypatch.setattr(
        "scientific_reading.background_launcher.BackgroundLauncher", FakeLauncher
    )
    pipeline = ReadingPipeline(tmp_path)
    state = ReadingPipelineState(
        paper_id=paper_id,
        parent_job_id="job_fedcba9876543210",
        current_stage="schedule_derived_updates",
        source_pdf_sha256="a" * 64,
        reader_source_sha256="a" * 64,
    )

    result = pipeline._default_stage_runner(
        "schedule_derived_updates", state, None
    )

    request = captured["request"]
    assert isinstance(request, BackgroundRequest)
    assert request.paper_id == paper_id
    assert request.target_stage == "xlsx_snapshot"
    assert request.payload == {"data_root": str(tmp_path.resolve())}
    assert result == {
        "status": "queued",
        "xlsx_job_id": "job_0123456789abcdef",
    }


def test_start_keeps_missing_generation_parent_after_pdf_attach(
    tmp_path, metadata
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    pipeline = ReadingPipeline(tmp_path)
    first = pipeline.start(paper_id)
    workspace = PaperWorkspace.create_for_paper_id(tmp_path, paper_id, metadata)
    pdf = _pdf_bytes(metadata, "attached source")
    workspace.source_pdf.write_bytes(pdf)
    library = LibraryService(tmp_path)
    try:
        library.conn.execute(
            "UPDATE items SET active_job_id=NULL WHERE paper_id=?", (paper_id,)
        )
        library.conn.commit()
    finally:
        library.close()

    orphaned = pipeline.start(paper_id)
    resumed = pipeline.start(paper_id, resume_job_id=first.parent_job_id)

    assert orphaned.parent_job_id == first.parent_job_id
    assert resumed.parent_job_id == first.parent_job_id


def test_worker_resumes_missing_parent_after_pdf_attach(tmp_path, metadata) -> None:
    paper_id = _ingest(tmp_path, metadata)
    pipeline = ReadingPipeline(tmp_path)
    first = pipeline.start(paper_id)
    workspace = PaperWorkspace.create_for_paper_id(tmp_path, paper_id, metadata)
    workspace.source_pdf.write_bytes(_pdf_bytes(metadata, "attached source"))
    library = LibraryService(tmp_path)
    try:
        library.conn.execute(
            "UPDATE items SET active_job_id=NULL WHERE paper_id=?", (paper_id,)
        )
        library.conn.commit()
    finally:
        library.close()

    class ResumeThenComplete:
        def start(self, *args, **kwargs):
            return pipeline.start(*args, **kwargs)

        def advance(self, parent_job_id, _supplied):
            return ReadingPipelineState(
                paper_id=paper_id,
                parent_job_id=parent_job_id,
                current_stage="completed",
                state="completed",
            )

    store = pipeline.job_store
    code = run_job(
        store,
        first.parent_job_id,
        handlers={
            "full_read_pipeline": full_read_pipeline_handler_factory(
                ResumeThenComplete()
            )
        },
    )

    assert code == 0
    assert store.load_status(first.parent_job_id).state == "completed"


def test_worker_fails_old_job_when_pipeline_selects_a_new_parent(
    tmp_path, metadata
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    store = BackgroundJobStore(tmp_path)
    request = BackgroundRequest(
        paper_id=paper_id,
        target_stage="full_read_pipeline",
        input_hash="a" * 64,
        payload={"data_root": str(tmp_path)},
    )
    handle = store.create_or_get(request)

    class DifferentParentPipeline:
        def start(self, _paper_id, _provider_profile, **_kwargs):
            return SimpleNamespace(parent_job_id="job_0123456789abcdef")

        def advance(self, *_args):
            raise AssertionError("a stale worker must not advance a new parent")

    code = run_job(
        store,
        handle.job_id,
        handlers={
            "full_read_pipeline": full_read_pipeline_handler_factory(
                DifferentParentPipeline()
            )
        },
    )

    assert code == 4
    status = store.load_status(handle.job_id)
    assert status.state == "failed"
    assert status.error == "full_read_parent_mismatch"


def test_pipeline_completion_preserves_published_reader_library_status(
    tmp_path, metadata
) -> None:
    paper_id = _ingest(tmp_path, metadata)
    library = LibraryService(tmp_path)
    try:
        library.update_status(paper_id, "full_read_ready")
    finally:
        library.close()
    store = BackgroundJobStore(tmp_path)
    request = BackgroundRequest(
        paper_id=paper_id,
        target_stage="full_read_pipeline",
        input_hash="b" * 64,
        payload={"data_root": str(tmp_path)},
    )
    handle = store.create_or_get(request)
    completed = ReadingPipelineState(
        paper_id=paper_id,
        parent_job_id=handle.job_id,
        current_stage="completed",
        state="completed",
    )

    class CompletedPipeline:
        def start(self, _paper_id, _provider_profile, **_kwargs):
            return SimpleNamespace(parent_job_id=handle.job_id)

        def advance(self, _parent_job_id, _supplied):
            return completed

    assert run_job(
        store,
        handle.job_id,
        handlers={
            "full_read_pipeline": full_read_pipeline_handler_factory(
                CompletedPipeline()
            )
        },
    ) == 0

    library = LibraryService(tmp_path)
    try:
        assert library.get_item(paper_id)["status"] == "full_read_ready"
    finally:
        library.close()
