import threading
import time

import pytest

from scientific_reading.background_launcher import BackgroundLauncher
from scientific_reading.background_models import BackgroundRequest
from scientific_reading.background_store import BackgroundJobStore
from scientific_reading.data_guard import DataRootBusy, data_root_freeze, data_root_operation
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.pdf_acquisition import TrustedPdfAcquisitionService
from scientific_reading.reading_pipeline import ReadingPipeline
from scientific_reading.worker import run_job
from scientific_reading.xlsx_snapshot import XlsxSnapshotService


def _request(stage="fixture"):
    return BackgroundRequest("paper_fixture", stage, "0" * 64)


def _freeze_in_thread(root, entered, release, errors):
    try:
        with data_root_freeze(root, timeout=2):
            entered.set()
            release.wait(5)
    except Exception as error:  # pragma: no cover - surfaced by the caller
        errors.append(error)
        entered.set()


def test_precreated_store_and_library_reject_writes_during_cross_thread_freeze(tmp_path):
    store = BackgroundJobStore(tmp_path)
    handle = store.create_or_get(_request("seed"))
    library = LibraryService(tmp_path)
    paper_id = library.ingest(PaperMetadata(title="Freeze fixture"))["paper_id"]
    entered = threading.Event()
    release = threading.Event()
    errors = []
    freezer = threading.Thread(
        target=_freeze_in_thread, args=(tmp_path, entered, release, errors)
    )
    freezer.start()
    try:
        assert entered.wait(2)
        assert not errors
        with pytest.raises(DataRootBusy):
            BackgroundJobStore(tmp_path)
        store_calls = [
            lambda: store.create_or_get(_request()),
            lambda: store.transition(handle.job_id, "running"),
            lambda: store.heartbeat(handle.job_id),
            lambda: store.save_resume_input(handle.job_id, {"value": 1}),
        ]
        for call in store_calls:
            with pytest.raises(DataRootBusy):
                call()
        with pytest.raises(DataRootBusy):
            with store.claim(handle.job_id, "fixture"):
                pytest.fail("claim entered a frozen root")
        with pytest.raises(DataRootBusy):
            with store.launch_claim(handle.job_id):
                pytest.fail("launch claim entered a frozen root")
        with pytest.raises(DataRootBusy):
            library.update_status(paper_id, "changed")
    finally:
        release.set()
        freezer.join(5)
        library.close()
    assert not freezer.is_alive()
    assert not errors


def test_public_service_entries_reject_cross_thread_freeze(tmp_path):
    launcher = BackgroundLauncher(tmp_path, popen=lambda *args, **kwargs: None)
    pipeline = ReadingPipeline(tmp_path)
    acquisition = TrustedPdfAcquisitionService(tmp_path)
    snapshot = XlsxSnapshotService(tmp_path)
    calls = [
        lambda: launcher.enqueue(_request()),
        lambda: launcher.launch_existing("job_" + "0" * 16),
        lambda: pipeline.start("paper_fixture"),
        lambda: pipeline.advance("job_" + "0" * 16),
        lambda: pipeline.inspect("job_" + "0" * 16),
        lambda: acquisition.ensure_pdf("paper_fixture"),
        lambda: acquisition.attach_local("paper_fixture", tmp_path / "fixture.pdf"),
        snapshot.refresh,
        snapshot.import_user_fields,
    ]
    entered = threading.Event()
    release = threading.Event()
    errors = []
    freezer = threading.Thread(
        target=_freeze_in_thread, args=(tmp_path, entered, release, errors)
    )
    freezer.start()
    try:
        assert entered.wait(2)
        assert not errors
        for call in calls:
            with pytest.raises(DataRootBusy):
                call()
    finally:
        release.set()
        freezer.join(5)
    assert not freezer.is_alive()
    assert not errors


def test_worker_heartbeat_finishes_while_backup_waits_for_worker(tmp_path):
    heartbeat_seen = threading.Event()
    handler_started = threading.Event()
    finish_handler = threading.Event()
    freeze_entered = threading.Event()
    release_freeze = threading.Event()
    worker_errors = []
    freeze_errors = []

    class TrackingStore(BackgroundJobStore):
        def heartbeat(self, job_id, *, pid=None):
            raise AssertionError("worker heartbeat must use its guarded private path")

        def _heartbeat(self, job_id, *, pid=None):
            status = super()._heartbeat(job_id, pid=pid)
            heartbeat_seen.set()
            return status

    store = TrackingStore(tmp_path)
    handle = store.create_or_get(_request())

    def handler(_request, _heartbeat):
        handler_started.set()
        assert finish_handler.wait(5)
        return {"status": "ok"}

    def worker():
        try:
            result = run_job(
                store,
                handle.job_id,
                {"fixture": handler},
                heartbeat_interval=0.01,
            )
            assert result == 0
        except Exception as error:  # pragma: no cover - surfaced below
            worker_errors.append(error)

    worker_thread = threading.Thread(target=worker)
    worker_thread.start()
    assert handler_started.wait(2)

    freezer = threading.Thread(
        target=_freeze_in_thread,
        args=(tmp_path, freeze_entered, release_freeze, freeze_errors),
    )
    freezer.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            with data_root_operation(tmp_path):
                pass
        except DataRootBusy:
            break
        time.sleep(0.01)
    else:
        pytest.fail("backup did not close admission while worker was active")

    assert not freeze_entered.is_set()
    assert heartbeat_seen.wait(2)
    finish_handler.set()
    assert freeze_entered.wait(2)
    release_freeze.set()
    worker_thread.join(5)
    freezer.join(5)

    assert not worker_thread.is_alive()
    assert not freezer.is_alive()
    assert not worker_errors
    assert not freeze_errors
    assert store.load_status(handle.job_id).state == "completed"
