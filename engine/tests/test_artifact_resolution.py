from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from scientific_reading.__main__ import _resolve_artifact
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace
from test_pipeline_excel_end_to_end import _publish_local_reader, _sha256


def _published_generation(root: Path) -> tuple[str, PaperWorkspace]:
    paper_id, reader = _publish_local_reader(root)
    base = PaperWorkspace(reader.parent.parent)
    metadata = PaperMetadata.from_dict(json.loads(base.metadata_path.read_text(encoding="utf-8")))
    source_sha = _sha256(base.source_pdf)
    generation = PaperWorkspace.create_generation(base, source_sha, metadata)
    shutil.copy2(base.source_pdf, generation.source_pdf)
    shutil.copytree(base.parsed_dir, generation.parsed_dir, dirs_exist_ok=True)
    shutil.copytree(base.reading_dir, generation.reading_dir, dirs_exist_ok=True)
    stage = StageRecord(status="completed", result={
        "source_sha256": source_sha, "active_parsed_dir": "parsed/mineru",
        "method": "auto", "mineru_version": "test-fixture",
    })
    nested = generation.load_job()
    nested.stages["paper_parse_upgrade"] = stage
    generation.save_job(nested)
    state = base.load_job()
    state.stages["paper_parse_upgrade"] = StageRecord(status="completed", result={
        **stage.result, "active_workspace": f"generations/{source_sha[:16]}",
    })
    base.save_job(state)
    library = LibraryService(root)
    try:
        library.publish_reader(paper_id, f"generations/{source_sha[:16]}/reading/reader.html")
    finally:
        library.close()
    return paper_id, generation


def test_generated_reader_resolves_without_republishing(tmp_path):
    paper_id, generation = _published_generation(tmp_path)
    with sqlite3.connect(tmp_path / "library.sqlite") as conn:
        before = list(conn.iterdump())
    result = _resolve_artifact(tmp_path, paper_id, "reader")
    assert result["rel_path"] == f"generations/{generation.root.name}/reading/reader.html"
    assert result["manifest"]["reader_sha256"] == _sha256(generation.reader_html)
    with sqlite3.connect(tmp_path / "library.sqlite") as conn:
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize("component", ["html", "manifest", "translations", "source"])
def test_reader_resolution_rejects_tampered_generation(tmp_path, component):
    paper_id, generation = _published_generation(tmp_path)
    target = {
        "html": generation.reader_html,
        "manifest": generation.reader_manifest,
        "translations": generation.reading_dir / "full/translations.json",
        "source": generation.source_pdf,
    }[component]
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        _resolve_artifact(tmp_path, paper_id, "reader")


def test_attached_pdf_opens_before_parsing(tmp_path):
    paper_id, reader = _publish_local_reader(tmp_path)
    base = PaperWorkspace(reader.parent.parent)
    state = base.load_job()
    state.stages.pop("paper_parse_upgrade")
    base.save_job(state)
    result = _resolve_artifact(tmp_path, paper_id, "pdf")
    assert result["rel_path"] == "source.pdf"
    assert result["sha256"] == _sha256(base.source_pdf)


def test_missing_reader_returns_not_ready_without_import_error(tmp_path):
    paper_id, reader = _publish_local_reader(tmp_path)
    reader.unlink()
    with pytest.raises(ValueError, match="artifact_not_ready"):
        _resolve_artifact(tmp_path, paper_id, "reader")


def test_matching_legacy_copy_requires_the_current_reader_manifest(tmp_path):
    paper_id, generation = _published_generation(tmp_path)
    legacy = generation.output_dir / "reader_full.html"
    shutil.copy2(generation.reader_html, legacy)
    generation.reader_html.unlink()
    result = _resolve_artifact(tmp_path, paper_id, "reader")
    assert result["manifest"]["reader_sha256"] == _sha256(legacy)


def test_unverified_legacy_copy_cannot_replace_missing_canonical_reader(tmp_path):
    paper_id, generation = _published_generation(tmp_path)
    generation.reader_html.unlink()
    legacy = generation.output_dir / "reader_full.html"
    legacy.write_text("<html>unverified replacement</html>", encoding="utf-8")
    with pytest.raises(ValueError):
        _resolve_artifact(tmp_path, paper_id, "reader")
