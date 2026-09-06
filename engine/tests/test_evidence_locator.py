from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scientific_reading.evidence_locator import (
    EvidenceLocatorError,
    build_locator,
    resolve_locator,
)
from scientific_reading.library_service import LibraryService
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fixture(
    data_root: Path,
    *,
    duplicate_text: bool = False,
    repeated_quote_in_block: bool = False,
) -> tuple[str, PaperWorkspace, str]:
    metadata = PaperMetadata(
        title="Synthetic locator study",
        authors=["Fixture Author"],
        doi="10.5555/locator.fixture",
        year=2026,
        journal="Offline Fixtures",
    )
    library = LibraryService(data_root)
    try:
        paper_id = library.ingest(metadata)["paper_id"]
    finally:
        library.close()

    base = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
    source = b"%PDF-1.4\n% synthetic locator fixture\n%%EOF\n"
    base.source_pdf.write_bytes(source)
    source_sha = _sha256(base.source_pdf)
    generation = PaperWorkspace.create_generation(base, source_sha, metadata)
    generation.source_pdf.write_bytes(source)

    repeated = "Repeated evidence sentence." if duplicate_text else "Control text."
    items = [
        {
            "type": "header",
            "page_idx": 0,
            "bbox": [10, 10, 500, 40],
            "text": metadata.title,
            "text_level": 1,
        },
        {
            "type": "text",
            "page_idx": 0,
            "bbox": [10, 50, 500, 90],
            "text": (
                "The exact target quote supports the exact target quote."
                if repeated_quote_in_block
                else "The exact target quote supports the result."
            ),
        },
        {
            "type": "text",
            "page_idx": 0,
            "bbox": [10, 100, 500, 140],
            "text": repeated,
        },
    ]
    if duplicate_text:
        items.append(
            {
                "type": "text",
                "page_idx": 1,
                "bbox": [10, 10, 500, 50],
                "text": repeated,
            }
        )
    raw = generation.root / "raw-fixture"
    content = raw / "paper" / "auto" / "paper_content_list.json"
    content.parent.mkdir(parents=True)
    _write_json(content, items)
    parsed = generation.parsed_dir / "mineru"
    version = "mineru-local-v1:locator-fixture"
    MineruNormalizer(version).normalize(raw, parsed, metadata, source_sha)
    shutil.copytree(raw, parsed / "raw")
    for name in ("source_map.json", "parse_report.json"):
        path = parsed / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        if name == "parse_report.json":
            payload["provider"] = "mineru-local-v1"
            payload["provider_version"] = "locator-fixture"
        _write_json(path, payload)

    generation_job = generation.load_job()
    generation_job.stages["paper_parse_upgrade"] = StageRecord(
        status="completed",
        result={
            "active_parsed_dir": "parsed/mineru",
            "source_sha256": source_sha,
            "method": "auto",
            "mineru_version": version,
        },
    )
    generation.save_job(generation_job)
    base_job = base.load_job()
    base_job.stages["paper_parse_upgrade"] = StageRecord(
        status="completed",
        result={
            "active_parsed_dir": "parsed/mineru",
            "active_workspace": f"generations/{source_sha[:16]}",
            "source_sha256": source_sha,
            "method": "auto",
            "mineru_version": version,
        },
    )
    base.save_job(base_job)

    library = LibraryService(data_root)
    try:
        library.record_pdf_attachment(
            paper_id,
            source_sha,
            len(source),
        )
    finally:
        library.close()
    return paper_id, generation, source_sha


def _assert_code(code: str, call) -> None:
    with pytest.raises(EvidenceLocatorError) as captured:
        call()
    assert captured.value.code == code
    assert str(captured.value) == code


def _reparse_same_source(generation: PaperWorkspace, source_sha: str) -> None:
    raw = generation.parsed_dir / "mineru" / "raw"
    content = next(raw.rglob("*_content_list.json"))
    items = json.loads(content.read_text(encoding="utf-8"))
    items.append(
        {
            "type": "text",
            "page_idx": 1,
            "bbox": [10, 10, 500, 50],
            "text": "A newly normalized block from the same PDF.",
        }
    )
    _write_json(content, items)
    parsed = generation.parsed_dir / "mineru"
    version = "mineru-local-v1:locator-fixture"
    MineruNormalizer(version).normalize(raw, parsed, PaperMetadata.from_dict(
        json.loads(generation.metadata_path.read_text(encoding="utf-8"))
    ), source_sha)
    for name in ("source_map.json", "parse_report.json"):
        path = parsed / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        if name == "parse_report.json":
            payload.update(
                {
                    "provider": "mineru-local-v1",
                    "provider_version": "locator-fixture",
                }
            )
        _write_json(path, payload)


def test_build_and_resolve_bind_verified_source_identity(tmp_path: Path) -> None:
    paper_id, generation, source_sha = _fixture(tmp_path)

    locator = build_locator(
        tmp_path,
        paper_id,
        "p0001-m0002",
        "exact target quote",
        page=1,
    )
    resolved = resolve_locator(tmp_path, paper_id, locator)

    assert locator == {
        "contract": "evidence-locator-v1",
        "paper_id": paper_id,
        "source_sha256": source_sha,
        "generation": f"generations/{source_sha[:16]}",
        "source_map_sha256": _sha256(
            generation.parsed_dir / "mineru" / "source_map.json"
        ),
        "block_id": "p0001-m0002",
        "page": 1,
        "quote": "exact target quote",
    }
    assert resolved["status"] == "resolved"
    assert resolved["source"]["block_id"] == "p0001-m0002"
    assert resolved["source"]["page"] == 1
    assert resolved["source"]["fragment"] == (
        "The exact target quote supports the result."
    )
    assert resolved["source"]["quote_start"] == 4
    assert resolved["source"]["quote_end"] == 22
    assert resolved["source"]["quote_match_count"] == 1
    assert resolved["source"]["quote_ambiguous"] is False
    assert resolved["links"] == {
        "reader": {
            "artifact_kind": "reader",
            "available": False,
            "fragment": None,
            "block_id": "p0001-m0002",
        },
        "pdf": {
            "artifact_kind": "pdf",
            "available": True,
            "fragment": "page=1",
            "page": 1,
        },
    }


def test_same_pdf_reparse_cannot_silently_rebind_source_map(tmp_path: Path) -> None:
    paper_id, generation, source_sha = _fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    _reparse_same_source(generation, source_sha)

    _assert_code(
        "source_map_changed",
        lambda: resolve_locator(tmp_path, paper_id, locator),
    )
    assert _sha256(generation.source_pdf) == source_sha
    replacement = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    assert replacement["source_sha256"] == locator["source_sha256"]
    assert replacement["source_map_sha256"] != locator["source_map_sha256"]
    assert resolve_locator(tmp_path, paper_id, replacement)["status"] == "resolved"


def test_changed_pdf_is_rejected(tmp_path: Path) -> None:
    paper_id, generation, _source_sha = _fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    generation.source_pdf.write_bytes(b"%PDF-1.4\nchanged\n%%EOF\n")

    _assert_code(
        "source_changed",
        lambda: resolve_locator(tmp_path, paper_id, locator),
    )


def test_missing_block_wrong_quote_and_page_are_rejected(tmp_path: Path) -> None:
    paper_id, _generation, _source_sha = _fixture(tmp_path)

    _assert_code(
        "block_not_found",
        lambda: build_locator(tmp_path, paper_id, "p0001-m9999", "quote"),
    )
    _assert_code(
        "quote_not_found",
        lambda: build_locator(
            tmp_path, paper_id, "p0001-m0002", "similar target quote"
        ),
    )
    _assert_code(
        "page_mismatch",
        lambda: build_locator(
            tmp_path,
            paper_id,
            "p0001-m0002",
            "exact target quote",
            page=2,
        ),
    )


def test_duplicate_text_requires_explicit_block_and_is_marked(
    tmp_path: Path,
) -> None:
    paper_id, _generation, _source_sha = _fixture(
        tmp_path, duplicate_text=True
    )

    locator = build_locator(
        tmp_path,
        paper_id,
        "p0001-m0003",
        "Repeated evidence sentence.",
    )
    resolved = resolve_locator(tmp_path, paper_id, locator)

    assert resolved["source"]["quote_match_count"] == 2
    assert resolved["source"]["quote_ambiguous"] is True
    assert resolved["source"]["disambiguated_by"] == "block_id"


def test_repeated_quote_inside_one_block_is_rejected(tmp_path: Path) -> None:
    paper_id, _generation, _source_sha = _fixture(
        tmp_path, repeated_quote_in_block=True
    )

    _assert_code(
        "ambiguous_quote",
        lambda: build_locator(
            tmp_path, paper_id, "p0001-m0002", "exact target quote"
        ),
    )


def test_quote_length_is_bounded(tmp_path: Path) -> None:
    paper_id, _generation, _source_sha = _fixture(tmp_path)

    _assert_code(
        "quote_too_long",
        lambda: build_locator(
            tmp_path,
            paper_id,
            "p0001-m0002",
            "x" * 501,
        ),
    )


def test_reader_link_requires_a_real_unique_scroll_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from scientific_reading import __main__ as cli
    from scientific_reading.evidence_locator import _reader_link

    paper_id = "paper_reader_anchor"
    relative = "generations/" + "a" * 16 + "/reading/reader.html"
    reader = tmp_path / "papers" / paper_id / Path(relative)
    reader.parent.mkdir(parents=True)
    manifest = {
        "reader_sha256": "unused-by-fake",
        "source_blocks": [{"block_id": "p0001-m0002"}],
    }

    def resolved(_root, _paper_id, _kind):
        manifest["reader_sha256"] = _sha256(reader)
        return {"rel_path": relative, "manifest": dict(manifest)}

    monkeypatch.setattr(cli, "_resolve_artifact", resolved)
    reader.write_text(
        '<article><section class="reading-block" '
        'data-block="p0001-m0002">x</section></article>',
        encoding="utf-8",
    )
    assert _reader_link(
        tmp_path, paper_id, "p0001-m0002"
    )["available"] is False

    reader.write_text(
        '<article><section id="block-p0001-m0002" '
        'class="reading-block" data-block="p0001-m0002">x</section>'
        '</article>',
        encoding="utf-8",
    )
    link = _reader_link(tmp_path, paper_id, "p0001-m0002")
    assert link["available"] is True
    assert link["fragment"] == "block-p0001-m0002"


def test_duplicate_block_ids_are_rejected(tmp_path: Path) -> None:
    paper_id, generation, _source_sha = _fixture(tmp_path)
    source_map = generation.parsed_dir / "mineru" / "source_map.json"
    payload = json.loads(source_map.read_text(encoding="utf-8"))
    payload["blocks"][2]["block_id"] = payload["blocks"][1]["block_id"]
    _write_json(source_map, payload)

    _assert_code(
        "block_id_ambiguous",
        lambda: build_locator(
            tmp_path, paper_id, "p0001-m0002", "exact target quote"
        ),
    )


def test_locator_paths_and_paper_identity_cannot_escape(tmp_path: Path) -> None:
    paper_id, _generation, _source_sha = _fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )

    _assert_code(
        "paper_id_invalid",
        lambda: build_locator(tmp_path, "../outside", "x", "quote"),
    )
    escaped = {**locator, "generation": "../outside"}
    _assert_code(
        "locator_invalid",
        lambda: resolve_locator(tmp_path, paper_id, escaped),
    )
    wrong_paper = {**locator, "paper_id": "other-paper"}
    _assert_code(
        "paper_id_mismatch",
        lambda: resolve_locator(tmp_path, paper_id, wrong_paper),
    )
