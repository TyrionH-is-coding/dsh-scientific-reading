from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata


def _ingest(
    service: LibraryService,
    title: str,
    *,
    authors: tuple[str, ...] = (),
    doi: str | None = None,
) -> str:
    result = service.ingest(
        PaperMetadata(title=title, authors=authors, doi=doi)
    )
    return result["paper_id"]


def test_folders_are_single_assignment_and_tags_are_multi_assignment(
    tmp_path: Path,
) -> None:
    service = LibraryService(tmp_path)
    try:
        inbox = service.create_folder("Inbox")
        archive = service.create_folder("Archive")
        paper_id = _ingest(service, "Attention is all you need")

        service.move_items((paper_id,), inbox["folder_id"])
        service.move_items((paper_id,), archive["folder_id"])
        service.add_tags((paper_id,), ("NLP", "Transformer"))

        folders = service.list_folders()
        page = service.list_items(
            page=1,
            page_size=50,
            folder_id=archive["folder_id"],
            tags=("NLP", "Transformer"),
        )
    finally:
        service.close()

    assert [folder["name"] for folder in folders] == ["Archive", "Inbox"]
    assert page["total"] == 1
    assert page["items"][0]["folder_id"] == archive["folder_id"]
    assert page["items"][0]["tags"] == ["NLP", "Transformer"]


def test_unclassified_filter_is_explicit_and_none_does_not_filter(
    tmp_path: Path,
) -> None:
    service = LibraryService(tmp_path)
    try:
        folder = service.create_folder("Read")
        classified = _ingest(service, "Classified paper")
        unclassified = _ingest(service, "Unclassified paper")
        service.move_items((classified,), folder["folder_id"])

        all_items = service.list_items(page=1, page_size=50, folder_id=None)
        pending = service.list_items(
            page=1, page_size=50, folder_id="__unclassified__"
        )
    finally:
        service.close()

    assert {item["paper_id"] for item in all_items["items"]} == {
        classified,
        unclassified,
    }
    assert [item["paper_id"] for item in pending["items"]] == [unclassified]


@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("transformer", "Transformer models"),
        ("Lovelace", "Analytical engine"),
        ("10.1000/searchable", "DOI paper"),
        ("Immunology", "Tagged paper"),
    ],
)
def test_search_covers_title_authors_doi_and_tags(
    tmp_path: Path, query: str, expected_title: str
) -> None:
    service = LibraryService(tmp_path)
    try:
        _ingest(service, "Transformer models")
        _ingest(service, "Analytical engine", authors=("Ada Lovelace",))
        _ingest(service, "DOI paper", doi="10.1000/searchable")
        tagged = _ingest(service, "Tagged paper")
        service.add_tags((tagged,), ("Immunology",))

        result = service.list_items(page=1, page_size=50, query=query)
    finally:
        service.close()

    assert [item["title"] for item in result["items"]] == [expected_title]


def test_stable_sorting_pagination_status_and_recent_filter(tmp_path: Path) -> None:
    service = LibraryService(tmp_path)
    try:
        paper_ids = [_ingest(service, title) for title in ("B", "A", "C")]
        same_timestamp = datetime.now(UTC).isoformat()
        old_timestamp = (datetime.now(UTC) - timedelta(days=20)).isoformat()
        service.conn.execute(
            "UPDATE items SET updated_at = ?, status = ?",
            (same_timestamp, "待精读"),
        )
        service.conn.execute(
            "UPDATE items SET updated_at = ? WHERE paper_id = ?",
            (old_timestamp, paper_ids[0]),
        )
        service.conn.commit()

        first = service.list_items(
            page=1,
            page_size=1,
            status="待精读",
            recent_days=7,
        )
        second = service.list_items(
            page=2,
            page_size=1,
            status="待精读",
            recent_days=7,
        )
    finally:
        service.close()

    recent_ids = sorted(paper_ids[1:])
    assert first == {
        "items": [first["items"][0]],
        "page": 1,
        "page_size": 1,
        "total": 2,
    }
    assert first["items"][0]["paper_id"] == recent_ids[0]
    assert second["items"][0]["paper_id"] == recent_ids[1]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"page": 0}, "page_invalid"),
        ({"page_size": 0}, "page_size_invalid"),
        ({"page_size": 101}, "page_size_invalid"),
        ({"recent_days": 0}, "recent_days_invalid"),
        ({"tags": ("",)}, "tag_invalid"),
        ({"folder_id": "missing"}, "folder_not_found"),
    ],
)
def test_list_items_rejects_invalid_parameters(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    service = LibraryService(tmp_path)
    try:
        arguments = {"page": 1, "page_size": 50, **kwargs}
        with pytest.raises(ValueError, match=f"^{message}$"):
            service.list_items(**arguments)
    finally:
        service.close()


def test_folder_rename_move_and_tag_mutations_validate_and_read_back(
    tmp_path: Path,
) -> None:
    service = LibraryService(tmp_path)
    try:
        folder = service.create_folder("Draft")
        renamed = service.rename_folder(folder["folder_id"], "Final")
        paper_id = _ingest(service, "Paper")
        service.move_items((paper_id,), folder["folder_id"])
        service.add_tags((paper_id,), ("A", "B", "A"))
        service.remove_tags((paper_id,), ("A",))
        item = service.list_items(page=1, page_size=50)["items"][0]

        with pytest.raises(ValueError, match="^folder_name_exists$"):
            service.create_folder("Final")
        with pytest.raises(ValueError, match="^paper_not_found$"):
            service.move_items(("missing",), None)
    finally:
        service.close()

    assert renamed["name"] == "Final"
    assert item["folder_id"] == folder["folder_id"]
    assert item["folder_name"] == "Final"
    assert item["tags"] == ["B"]


def test_navigation_rows_include_fixed_status_and_asset_contract(tmp_path: Path) -> None:
    service = LibraryService(tmp_path)
    try:
        folder = service.create_folder("Reading")
        paper_id = _ingest(
            service,
            "Contract paper",
            authors=("Ada Lovelace", "Grace Hopper", "Edsger Dijkstra"),
        )
        service.move_items((paper_id,), folder["folder_id"])
        service.add_tags((paper_id,), ("Algorithms", "History"))
        service.conn.execute(
            "UPDATE items SET abstract_status=?, full_read_status=?, "
            "feishu_sync_state=?, feishu_record_url=?, last_error=? WHERE paper_id=?",
            ("ready", "queued", "pending", "https://example.test/record", "retry later", paper_id),
        )
        service.conn.execute(
            "INSERT INTO attachments (paper_id, rel_path, sha256) VALUES (?,?,?)",
            (paper_id, "source.pdf", "a" * 64),
        )
        service.conn.execute(
            "INSERT INTO artifacts (paper_id, kind, rel_path, status, updated_at) VALUES (?,?,?,?,?)",
            (paper_id, "reader", "generations/" + "b" * 16 + "/reading/reader.html", "ready", datetime.now(UTC).isoformat()),
        )
        service.conn.commit()

        item = service.list_items(page=1, page_size=50)["items"][0]
    finally:
        service.close()

    assert item["authors_short"] == "Ada Lovelace 等 3 位"
    assert item["folder"] == "Reading"
    assert item["tags"] == ["Algorithms", "History"]
    assert item["abstract_status"] == "ready"
    assert item["full_read_status"] == "queued"
    assert item["feishu_sync_state"] == "pending"
    assert item["has_pdf"] is True
    assert item["has_reader"] is True
    assert item["feishu_record_url"] == "https://example.test/record"
    assert item["last_error"] == "retry later"
