import threading

import pytest

from scientific_reading.data_guard import (
    DataRootBusy,
    data_root_freeze,
    workspace_data_root,
)
from scientific_reading.export_service import ExportService
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.full_read_service import FullReadService
from scientific_reading.library_schema import migrate_library
from scientific_reading.mineru_service import MineruParseService
from scientific_reading.models import JobState, PaperMetadata
from scientific_reading.workspace import PaperWorkspace


def _hold_freeze(root, entered, release, errors):
    try:
        with data_root_freeze(root, timeout=2):
            entered.set()
            release.wait(5)
    except Exception as error:  # pragma: no cover - surfaced by the caller
        errors.append(error)
        entered.set()


def _invoke(name, root, workspace, metadata):
    full = FullReadService()
    renderer = FullReadRenderer()
    if name == "migrate_library":
        return migrate_library(root)
    if name == "workspace_create":
        return PaperWorkspace.create(root, PaperMetadata(title="New paper"))
    if name == "workspace_create_for_paper_id":
        return PaperWorkspace.create_for_paper_id(root, "new-paper", metadata)
    if name == "workspace_create_generation":
        return PaperWorkspace.create_generation(workspace, "1" * 64, metadata)
    if name == "workspace_save_job":
        return workspace.save_job(JobState(paper_id=workspace.root.name))
    if name == "full_prepare":
        return full.prepare(workspace)
    if name == "full_next_batch":
        return full.next_batch(workspace)
    if name == "full_save_next_translation":
        return full.save_next_translation(workspace, {})
    if name == "full_save_translation_batch":
        return full.save_translation_batch(workspace, {})
    if name == "full_review_context":
        return full.review_context(workspace)
    if name == "full_finalize":
        return full.finalize(workspace, {})
    if name == "renderer_completed":
        return renderer.render_completed(workspace, paper_id=workspace.root.name)
    if name == "renderer_preview":
        return renderer.render_preview_completed(
            workspace, output=root / "preview.html", paper_id=workspace.root.name
        )
    if name == "renderer_render":
        return renderer.render(
            workspace,
            {},
            {},
            root / "reader.html",
            review=None,
            reader_revision="0" * 64,
            paper_id=workspace.root.name,
        )
    if name == "export_for_paper":
        return ExportService().export_for_paper(root, workspace.root.name)
    if name == "export_workspace":
        return ExportService().export(workspace)
    if name == "mineru_run":
        return MineruParseService().run(
            root,
            metadata,
            "auto",
            heartbeat=lambda: None,
            paper_id=workspace.root.name,
            workspace=workspace,
        )
    raise AssertionError(name)


@pytest.mark.parametrize(
    "entry",
    [
        "migrate_library",
        "workspace_create",
        "workspace_create_for_paper_id",
        "workspace_create_generation",
        "workspace_save_job",
        "full_prepare",
        "full_next_batch",
        "full_save_next_translation",
        "full_save_translation_batch",
        "full_review_context",
        "full_finalize",
        "renderer_completed",
        "renderer_preview",
        "renderer_render",
        "export_for_paper",
        "export_workspace",
        "mineru_run",
    ],
)
def test_public_asset_writer_rejects_cross_thread_freeze_before_work(entry, tmp_path):
    root = tmp_path / "library"
    metadata = PaperMetadata(title="Guard fixture")
    workspace = PaperWorkspace.create_for_paper_id(root, "paper-fixture", metadata)
    entered = threading.Event()
    release = threading.Event()
    errors = []
    freezer = threading.Thread(target=_hold_freeze, args=(root, entered, release, errors))
    freezer.start()
    try:
        assert entered.wait(2)
        assert not errors
        with pytest.raises(DataRootBusy):
            _invoke(entry, root, workspace, metadata)
    finally:
        release.set()
        freezer.join(5)
    assert not freezer.is_alive()
    assert not errors


def test_workspace_root_recognizes_only_supported_tail_shapes(tmp_path):
    base = PaperWorkspace(tmp_path / "library" / "papers" / "paper-fixture")
    generation = PaperWorkspace(base.root / "generations" / ("1" * 16))
    nested_fixture = PaperWorkspace(
        tmp_path / "fixtures" / "papers" / "paper-fixture" / "nested"
    )
    assert workspace_data_root(base) == (tmp_path / "library").resolve()
    assert workspace_data_root(generation) == (tmp_path / "library").resolve()
    assert workspace_data_root(nested_fixture) == nested_fixture.root.resolve()
