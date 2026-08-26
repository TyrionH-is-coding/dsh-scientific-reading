from __future__ import annotations

import json
from pathlib import Path

import pytest

from scientific_reading.classification_service import (
    ClassificationProposal,
    ClassificationService,
)
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata


def _paper(service: LibraryService, number: int) -> str:
    return service.ingest(PaperMetadata(title=f"Paper {number}"))["paper_id"]


def test_apply_skips_low_confidence_missing_papers_and_unknown_folders(
    tmp_path: Path,
) -> None:
    library = LibraryService(tmp_path)
    try:
        original = library.create_folder("Original")
        unknown_folder_paper = _paper(library, 1)
        low_confidence_paper = _paper(library, 2)
        library.move_items(
            (unknown_folder_paper, low_confidence_paper), original["folder_id"]
        )
        library.add_tags(
            (unknown_folder_paper, low_confidence_paper), ("existing",)
        )

        service = ClassificationService(library)
        result = service.apply(
            (
                ClassificationProposal(
                    unknown_folder_paper, "New", ("new",), 0.99
                ),
                ClassificationProposal(
                    low_confidence_paper, "Original", ("low",), 0.69
                ),
                ClassificationProposal("missing", "Original", ("tag",), 0.99),
            )
        )
        items = library.list_items(page=1, page_size=50)["items"]
        folders = library.list_folders()
    finally:
        library.close()

    assert result["operation_id"] is None
    assert result["applied"] == []
    assert {entry["reason"] for entry in result["skipped"]} == {
        "folder_not_found",
        "confidence_below_minimum",
        "paper_not_found",
    }
    assert [folder["name"] for folder in folders] == ["Original"]
    assert all(item["folder_id"] == original["folder_id"] for item in items)
    assert all(item["tags"] == ["existing"] for item in items)


def test_allow_new_folders_applies_valid_proposal_and_records_before_after(
    tmp_path: Path,
) -> None:
    library = LibraryService(tmp_path)
    try:
        paper_id = _paper(library, 1)
        service = ClassificationService(library)
        result = service.apply(
            (ClassificationProposal(paper_id, "Created", ("A", "B"), 0.7),),
            allow_new_folders=True,
        )
        row = library.conn.execute(
            "SELECT before_json, after_json FROM batch_operations "
            "WHERE operation_id = ?",
            (result["operation_id"],),
        ).fetchone()
        item = library.list_items(page=1, page_size=50)["items"][0]
    finally:
        library.close()

    assert result["applied"] == [paper_id]
    assert result["chunk_count"] == 1
    assert json.loads(row["before_json"]) == [
        {"paper_id": paper_id, "folder_id": None, "tags": []}
    ]
    assert json.loads(row["after_json"])[0]["tags"] == ["A", "B"]
    assert item["folder_name"] == "Created"
    assert item["tags"] == ["A", "B"]


def test_apply_chunks_at_100_and_one_undo_restores_entire_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = LibraryService(tmp_path)
    try:
        destination = library.create_folder("Destination")
        paper_ids = [_paper(library, number) for number in range(205)]
        service = ClassificationService(library)
        chunk_sizes: list[int] = []
        original_apply_chunk = service._apply_chunk

        def record_chunk(proposals, folder_ids):
            chunk_sizes.append(len(proposals))
            return original_apply_chunk(proposals, folder_ids)

        monkeypatch.setattr(service, "_apply_chunk", record_chunk)
        result = service.apply(
            tuple(
                ClassificationProposal(
                    paper_id, "Destination", ("bulk",), 1.0
                )
                for paper_id in paper_ids
            )
        )
        undo = service.undo(result["operation_id"])
        restored = library.list_items(
            page=1,
            page_size=100,
            folder_id="__unclassified__",
        )
        operation = library.conn.execute(
            "SELECT undone_at FROM batch_operations WHERE operation_id = ?",
            (result["operation_id"],),
        ).fetchone()
    finally:
        library.close()

    assert chunk_sizes == [100, 100, 5]
    assert result["chunk_count"] == 3
    assert len(result["applied"]) == 205
    assert undo == {"operation_id": result["operation_id"], "restored": 205}
    assert restored["total"] == 205
    assert operation["undone_at"] is not None


def test_undo_is_once_only_and_apply_rejects_invalid_proposals(tmp_path: Path) -> None:
    library = LibraryService(tmp_path)
    try:
        paper_id = _paper(library, 1)
        folder = library.create_folder("Folder")
        service = ClassificationService(library)
        result = service.apply(
            (ClassificationProposal(paper_id, "Folder", (), 1.0),)
        )
        service.undo(result["operation_id"])

        with pytest.raises(ValueError, match="^operation_already_undone$"):
            service.undo(result["operation_id"])
        with pytest.raises(ValueError, match="^minimum_confidence_invalid$"):
            service.apply((), minimum_confidence=1.1)
        with pytest.raises(ValueError, match="^duplicate_paper_proposal$"):
            service.apply(
                (
                    ClassificationProposal(paper_id, folder["name"], (), 1.0),
                    ClassificationProposal(paper_id, None, (), 1.0),
                )
            )
    finally:
        library.close()


def test_undo_rejects_stale_state_after_user_changes(tmp_path: Path) -> None:
    library = LibraryService(tmp_path)
    try:
        original = library.create_folder("Original")
        target = library.create_folder("Target")
        paper_id = _paper(library, 1)
        library.move_items((paper_id,), original["folder_id"])
        result = ClassificationService(library).apply(
            (ClassificationProposal(paper_id, "Target", ("proposed",), 1.0),)
        )

        library.move_items((paper_id,), original["folder_id"])
        library.add_tags((paper_id,), ("user-change",))

        with pytest.raises(ValueError, match="^classification_undo_conflict$"):
            ClassificationService(library).undo(result["operation_id"])
        current = library.list_items(page=1, page_size=50)["items"][0]
        operation = library.conn.execute(
            "SELECT undone_at FROM batch_operations WHERE operation_id = ?",
            (result["operation_id"],),
        ).fetchone()
    finally:
        library.close()

    assert current["folder_id"] == original["folder_id"]
    assert current["tags"] == ["proposed", "user-change"]
    assert operation["undone_at"] is None
