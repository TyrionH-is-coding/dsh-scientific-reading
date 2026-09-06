import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scientific_reading.background_models import BackgroundRequest
from scientific_reading.background_store import BackgroundJobStore, stable_job_id
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.pdf_acquisition import TrustedPdfAcquisitionService


def setup_library(root):
    library = LibraryService(root)
    first = library.create_folder("分类甲")["folder_id"]
    second = library.create_folder("分类乙")["folder_id"]
    paper = library.ingest(PaperMetadata(title="scope fixture", doi="10.5555/scope"))["paper_id"]
    library.move_items([paper], first)
    return library, first, second, paper


def test_scoped_list_and_ingest_cannot_access_other_folder(tmp_path):
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": second}):
        assert library.list_items(page=1)["items"] == []
        with pytest.raises(ValueError, match="scope"):
            library.get_item(paper)
        with pytest.raises(ValueError, match="scope"):
            library.ingest(PaperMetadata(title="overwrite", doi="10.5555/scope"))
    assert library.get_item(paper)["title"] == "scope fixture"
    library.close()


def test_scoped_new_ingest_is_atomically_in_folder(tmp_path):
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        item = library.ingest(PaperMetadata(title="scoped new"))
        assert library.get_item(item["paper_id"])["folder_id"] == first
    library.close()


def test_job_scope_survives_reload_without_changing_content_identity(tmp_path):
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    request = BackgroundRequest(paper, "fixture", hashlib.sha256(b"source").hexdigest(), {})
    store = BackgroundJobStore(tmp_path)
    before = stable_job_id(request)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        created = store.create_or_get(request)
        duplicate = store.create_or_get(request)
    assert created.job_id == duplicate.job_id == before
    assert BackgroundJobStore(tmp_path).load_status(before).scope["scopeFolderId"] == first
    library.close()


@pytest.mark.parametrize("stage", ["derived_metadata", "derived_abstract", "derived_xlsx"])
def test_scoped_reading_start_can_coexist_with_global_derived_job(tmp_path, stage):
    from scientific_reading.reading_pipeline import ReadingPipeline
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    store = BackgroundJobStore(tmp_path)
    derived = store.create_or_get(BackgroundRequest(paper, stage, hashlib.sha256(stage.encode()).hexdigest(), {}))
    store.transition(derived.job_id, "running")
    library.update_active_job(paper, derived.job_id)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        reading = ReadingPipeline(tmp_path).start(paper)
    assert reading.parent_job_id != derived.job_id
    assert store.load_status(derived.job_id).scope is None
    assert store.load_status(derived.job_id).state == "running"
    assert store.load_status(reading.parent_job_id).scope["scopeFolderId"] == first
    library.close()


def test_scoped_reading_start_still_refuses_unfinished_global_reading_job(tmp_path):
    from scientific_reading.reading_pipeline import ReadingPipeline
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    pipeline = ReadingPipeline(tmp_path)
    original = pipeline.start(paper)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        with pytest.raises(ValueError, match="scope_job_conflict"):
            pipeline.start(paper)
    assert pipeline.job_store.load_status(original.parent_job_id).scope is None
    library.close()


def test_moved_paper_refuses_old_pdf_publication_and_preserves_bytes(tmp_path):
    from scientific_reading.scope import capture_scope, use_scope
    library, first, second, paper = setup_library(tmp_path)
    source = tmp_path / "old.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"old content " * 30)
    service = TrustedPdfAcquisitionService(tmp_path)
    result = service.attach_local(paper, source)
    old_bytes = result.path.read_bytes() if hasattr(result, "path") else (tmp_path / "papers" / paper / "source.pdf").read_bytes()
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        saved = capture_scope(tmp_path, paper)
    library.move_items([paper], second)
    replacement = tmp_path / "new.pdf"
    replacement.write_bytes(b"%PDF-1.7\n" + b"new content " * 30)
    with use_scope(saved), pytest.raises(ValueError, match="scope"):
        service.attach_local(paper, replacement)
    assert (tmp_path / "papers" / paper / "source.pdf").read_bytes() == old_bytes
    library.close()


def test_move_out_and_back_revokes_original_job_scope(tmp_path):
    from scientific_reading.scope import capture_scope, use_scope
    library, first, second, paper = setup_library(tmp_path)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        original = capture_scope(tmp_path, paper)
    library.move_items([paper], second)
    library.move_items([paper], first)
    with use_scope(original), pytest.raises(ValueError, match="scope"):
        library.get_item(paper)
    library.close()


def test_restarted_worker_reads_job_scope_and_refuses_changed_folder(tmp_path):
    from scientific_reading.scope import use_scope
    from scientific_reading.worker import run_job
    library, first, second, paper = setup_library(tmp_path)
    request = BackgroundRequest(paper, "fixture", hashlib.sha256(b"worker").hexdigest(), {"data_root": str(tmp_path)})
    store = BackgroundJobStore(tmp_path)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        job = store.create_or_get(request)
    library.move_items([paper], second)
    called = []
    result = run_job(store, job.job_id, {"fixture": lambda *_: called.append(True) or {}})
    assert result == 4
    assert called == []
    assert store.load_status(job.job_id).error == "scope_changed"
    library.close()


def test_scope_checked_again_after_pdf_is_staged(tmp_path, monkeypatch):
    import scientific_reading.pdf_acquisition as acquisition
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    source = tmp_path / "old.pdf"
    source.write_bytes(b"%PDF-1.7\n" + b"old content " * 30)
    service = TrustedPdfAcquisitionService(tmp_path)
    service.attach_local(paper, source)
    destination = tmp_path / "papers" / paper / "source.pdf"
    old = destination.read_bytes()
    replacement = tmp_path / "new.pdf"
    replacement.write_bytes(b"%PDF-1.7\n" + b"new content " * 30)
    copy = acquisition.shutil.copyfile
    def move_after_staging(src, dst):
        result = copy(src, dst)
        with use_scope(None):
            library.move_items([paper], second)
        return result
    monkeypatch.setattr(acquisition.shutil, "copyfile", move_after_staging)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}), pytest.raises(ValueError, match="scope"):
        service.attach_local(paper, replacement)
    assert destination.read_bytes() == old
    library.close()


def test_reader_staged_then_moved_preserves_published_html_and_manifest(tmp_path, monkeypatch):
    from scripts.reader_review_fixtures import fixture_path, materialize_fixture
    from scientific_reading.full_read_renderer import FullReadRenderer
    from scientific_reading.models import StageRecord
    from scientific_reading.workspace import PaperWorkspace
    from scientific_reading.scope import capture_scope, use_scope
    metadata = PaperMetadata.from_dict(json.loads(fixture_path("formula-outline").read_text(encoding="utf-8"))["metadata"])
    library = LibraryService(tmp_path)
    paper = library.ingest(metadata)["paper_id"]
    first = library.create_folder("初始分类")["folder_id"]
    second = library.create_folder("目标分类")["folder_id"]
    library.move_items([paper], first)
    base = PaperWorkspace.create_for_paper_id(tmp_path, paper, metadata)
    source = b"%PDF-1.4\n% deterministic reader review fixture\n% formula-outline\n"
    sha = hashlib.sha256(source).hexdigest()
    generation = materialize_fixture("formula-outline", base.root / "generations" / sha[:16])
    shutil.copyfile(generation.source_pdf, base.source_pdf)
    state = base.load_job()
    state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={
        "active_workspace": f"generations/{sha[:16]}", "source_sha256": sha,
    })
    base.save_job(state)
    FullReadRenderer().render_completed(generation, paper_id=paper)
    library.record_pdf_attachment(paper, sha, len(source))
    library.publish_reader(paper, f"generations/{sha[:16]}/reading/reader.html")
    original = (generation.reader_html.read_bytes(), generation.reader_manifest.read_bytes())
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        scope = capture_scope(tmp_path, paper)
    moved = []
    def move_at_staging(stage, staging):
        assert stage == "reader_staged"
        with use_scope(None):
            library.move_items([paper], second)
        moved.append(True)
    renderer = FullReadRenderer(publish_hook=move_at_staging)
    original_html = renderer._base_html
    monkeypatch.setattr(renderer, "_base_html", lambda *a, **kw: original_html(*a, **kw).replace("<body", "<body data-scope-test='new'", 1))
    with use_scope(scope), pytest.raises(ValueError, match="scope"):
        renderer.render_completed(generation, paper_id=paper)
    assert moved == [True]
    assert (generation.reader_html.read_bytes(), generation.reader_manifest.read_bytes()) == original
    assert library.get_item(paper)["folder_id"] == second
    library.close()


def test_archive_cli_revokes_worker_scope_and_requires_global_caller(tmp_path, capsys):
    from scientific_reading.__main__ import run_cli
    from scientific_reading.scope import capture_scope, use_scope
    library, first, second, paper = setup_library(tmp_path)
    scope = {"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}
    with use_scope(scope):
        saved = capture_scope(tmp_path, paper)
        assert run_cli(["--data-root", str(tmp_path), "scope-folder-state", "--folder-id", first, "--archived", "true"]) == 4
    assert run_cli(["--data-root", str(tmp_path), "scope-folder-state", "--folder-id", first, "--archived", "true"]) == 0
    with use_scope(saved), pytest.raises(ValueError, match="scope"):
        library.get_item(paper)
    assert run_cli(["--data-root", str(tmp_path), "scope-folder-state", "--folder-id", first, "--archived", "false"]) == 0
    with use_scope(saved), pytest.raises(ValueError, match="scope"):
        library.get_item(paper)
    capsys.readouterr()
    library.close()


def test_review_binding_and_context_require_live_folder_and_root_session(tmp_path):
    from scientific_reading.review_service import ReviewService
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    review = ReviewService(tmp_path)
    review.bind_session("session-a", paper, "review-a")
    review.bind_session("session-b", paper, "review-b")
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        assert review.context_for_session("review-a")["paper"]["paper_id"] == paper
        with pytest.raises(ValueError, match="scope"):
            review.context_for_session("review-b")
        with pytest.raises(ValueError, match="scope"):
            review.get_binding("session-b", paper)
    library.move_items([paper], second)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        for operation in (
            lambda: review.get_binding("session-a", paper),
            lambda: review.open_state("session-a", paper),
            lambda: review.bind_session("session-a", paper, "review-new"),
        ):
            with pytest.raises(ValueError, match="scope"):
                operation()
    review.close()
    library.close()


def test_review_move_during_normalization_refuses_final_conclusion_write(tmp_path, monkeypatch):
    from scientific_reading.review_service import ReviewService
    from scientific_reading.scope import use_scope
    library, first, second, paper = setup_library(tmp_path)
    review = ReviewService(tmp_path)
    review.bind_session("session-a", paper, "review-a")
    normalize = review._normalize_evidence
    def move_after_normalizing(*args):
        result = normalize(*args)
        with use_scope(None):
            library.move_items([paper], second)
        return result
    monkeypatch.setattr(review, "_normalize_evidence", move_after_normalizing)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}), pytest.raises(ValueError, match="scope"):
        review.confirm_conclusions("review-a", [{"conclusion_type": "fixture", "conclusion_text": "must not publish", "basis": "personal"}])
    assert review.context_for_session("review-a")["confirmed_conclusions"] == []
    review.close()
    library.close()


def test_repeating_unarchived_state_keeps_current_worker_scope(tmp_path, capsys):
    from scientific_reading.__main__ import run_cli
    from scientific_reading.scope import capture_scope, use_scope
    library, first, second, paper = setup_library(tmp_path)
    with use_scope({"instanceId": "fixture", "scopeSessionId": "session-a", "scopeFolderId": first}):
        saved = capture_scope(tmp_path, paper)
    assert run_cli(["--data-root", str(tmp_path), "scope-folder-state", "--folder-id", first, "--archived", "false"]) == 0
    with use_scope(saved):
        assert library.get_item(paper)["folder_id"] == first
    capsys.readouterr()
    library.close()
