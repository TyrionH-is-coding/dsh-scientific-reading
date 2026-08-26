from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

from scientific_reading.__main__ import run_cli
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata


def _run(args: list[str], capsys) -> tuple[int, dict]:
    code = run_cli(args)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return code, json.loads(captured.out)


def test_folder_commands_and_library_list_v2_emit_single_json(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "data"
    prefix = ["--data-root", str(root)]
    code, created = _run(prefix + ["folder-create", "--name", "Inbox"], capsys)
    assert code == 0

    code, renamed = _run(
        prefix
        + [
            "folder-rename",
            "--folder-id",
            created["folder_id"],
            "--name",
            "Reading",
        ],
        capsys,
    )
    assert code == 0
    assert renamed["name"] == "Reading"

    code, folders = _run(prefix + ["folder-list"], capsys)
    assert code == 0
    assert folders == [renamed]

    library = LibraryService(root)
    try:
        paper_id = library.ingest(PaperMetadata(title="CLI paper"))["paper_id"]
        library.move_items((paper_id,), created["folder_id"])
        library.add_tags((paper_id,), ("CLI",))
    finally:
        library.close()

    code, page = _run(
        prefix
        + [
            "library-list-v2",
            "--page",
            "1",
            "--page-size",
            "25",
            "--folder-id",
            created["folder_id"],
            "--tag",
            "CLI",
        ],
        capsys,
    )
    assert code == 0
    assert page["total"] == 1
    assert page["items"][0]["paper_id"] == paper_id
    assert set(page["items"][0]) >= {
        "authors_short", "folder", "abstract_status", "full_read_status",
        "feishu_sync_state", "has_pdf", "has_reader", "feishu_record_url", "last_error",
    }


def test_classification_apply_file_and_undo_commands(tmp_path: Path, capsys) -> None:
    root = tmp_path / "data"
    library = LibraryService(root)
    try:
        paper_id = library.ingest(PaperMetadata(title="Classify me"))["paper_id"]
        library.create_folder("Target")
    finally:
        library.close()
    batch = tmp_path / "batch.json"
    batch.write_text(
        json.dumps(
            [
                {
                    "paper_id": paper_id,
                    "folder_name": "Target",
                    "tags": ["NLP"],
                    "confidence": 0.9,
                }
            ]
        ),
        encoding="utf-8",
    )
    prefix = ["--data-root", str(root)]

    code, applied = _run(
        prefix + ["classification-apply", "--input", str(batch)], capsys
    )
    assert code == 0
    assert applied["applied"] == [paper_id]

    code, undone = _run(
        prefix
        + [
            "classification-undo",
            "--operation-id",
            applied["operation_id"],
        ],
        capsys,
    )
    assert code == 0
    assert undone["restored"] == 1


def test_classification_apply_accepts_stdin(tmp_path: Path, capsys, monkeypatch) -> None:
    root = tmp_path / "data"
    library = LibraryService(root)
    try:
        paper_id = library.ingest(PaperMetadata(title="stdin paper"))["paper_id"]
    finally:
        library.close()
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                [
                    {
                        "paper_id": paper_id,
                        "folder_name": "Created",
                        "tags": [],
                        "confidence": 1,
                    }
                ]
            )
        ),
    )

    code, payload = _run(
        [
            "--data-root",
            str(root),
            "classification-apply",
            "--allow-new-folders",
        ],
        capsys,
    )

    assert code == 0
    assert payload["applied"] == [paper_id]


def test_navigation_cli_errors_are_safe_single_json(tmp_path: Path, capsys) -> None:
    private = tmp_path / "private-batch.json"
    private.write_text("{broken", encoding="utf-8")
    code, payload = _run(
        [
            "--data-root",
            str(tmp_path / "data"),
            "classification-apply",
            "--input",
            str(private),
        ],
        capsys,
    )

    assert code == 2
    assert payload == {
        "status": "failed",
        "error": {
            "code": "invalid_classification_json",
            "detail": "classification_json_malformed",
        },
    }
    assert str(private) not in json.dumps(payload)


def test_classification_cli_rejects_string_tags_without_writing(
    tmp_path: Path, capsys
) -> None:
    root = tmp_path / "data"
    library = LibraryService(root)
    try:
        paper_id = library.ingest(PaperMetadata(title="invalid tags"))["paper_id"]
    finally:
        library.close()

    monkeypatch_payload = json.dumps(
        [{"paper_id": paper_id, "folder_name": None, "tags": "NLP", "confidence": 1.0}]
    )
    import pytest

    # Keep stdin setup local to this test without changing the shared helper API.
    capsys.readouterr()
    from unittest.mock import patch

    with patch("sys.stdin", io.StringIO(monkeypatch_payload)):
        code = run_cli(["--data-root", str(root), "classification-apply"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "failed",
        "error": {
            "code": "invalid_classification",
            "detail": "classification_validation_failed",
        },
    }

    library = LibraryService(root)
    try:
        item = library.list_items(page=1, page_size=50)["items"][0]
    finally:
        library.close()
    assert item["tags"] == []


def test_navigation_cli_maps_sqlite_errors_to_safe_json(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    def fail(*args, **kwargs):
        raise sqlite3.Error("SELECT secret/path")

    monkeypatch.setattr(LibraryService, "list_folders", fail)
    code = run_cli(["--data-root", str(tmp_path / "data"), "folder-list"])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "status": "failed",
        "error": {"code": "operation_failed", "detail": "library_operation_failed"},
    }


def test_library_item_v2_returns_system_and_abstract_fields(tmp_path: Path, capsys) -> None:
    root = tmp_path / "data"
    library = LibraryService(root)
    try:
        item = library.ingest(
            PaperMetadata(title="Item detail", abstract_en="English", abstract_zh="中文")
        )
        library.update_abstract_status(item["paper_id"], "completed")
        library.update_active_job(item["paper_id"], "job_0123456789abcdef", error="detail")
    finally:
        library.close()

    code, payload = _run(
        ["--data-root", str(root), "library-item-v2", "--paper-id", item["paper_id"]],
        capsys,
    )
    assert code == 0
    assert payload["paper_id"] == item["paper_id"]
    assert payload["title"] == "Item detail"
    assert payload["abstract_en"] == "English"
    assert payload["abstract_zh"] == "中文"
    assert payload["abstract_status"] == "completed"
    assert payload["active_job_id"] == "job_0123456789abcdef"
    assert payload["last_error"] == "detail"


def test_library_item_v2_rejects_path_and_has_stable_not_found(tmp_path: Path, capsys) -> None:
    prefix = ["--data-root", str(tmp_path / "data"), "library-item-v2", "--paper-id"]
    code, invalid = _run(prefix + ["../private"], capsys)
    assert code == 2
    assert invalid["error"]["code"] == "paper_id_invalid"

    code, missing = _run(prefix + ["title_000000000000"], capsys)
    assert code == 2
    assert missing == {
        "status": "failed",
        "error": {"code": "paper_not_found", "detail": "library_item_not_found"},
    }
