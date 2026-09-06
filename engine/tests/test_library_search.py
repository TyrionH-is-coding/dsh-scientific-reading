from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scientific_reading.library_service import LibraryService, library_path
from scientific_reading.models import PaperMetadata
from scientific_reading.review_service import ReviewService


def _paper(
    service: LibraryService,
    title: str,
    *,
    abstract_en: str | None = None,
    abstract_zh: str | None = None,
    doi: str | None = None,
    pmid: str | None = None,
    source_url: str | None = None,
) -> str:
    return service.ingest(
        PaperMetadata(
            title=title,
            authors=["Ada Lovelace"],
            journal="Journal of Search",
            year=2026,
            doi=doi,
            pmid=pmid,
            source_url=source_url,
            abstract_en=abstract_en,
            abstract_zh=abstract_zh,
        )
    )["paper_id"]


@pytest.mark.parametrize(
    ("query", "content_type"),
    [
        ("interleukin", "abstract_en"),
        ("凝血", "abstract_zh"),
        ("抗磷脂综合征凝血悖论", "abstract_zh"),
        ("IL-6", "abstract_en"),
        ("aPS/PT", "abstract_zh"),
        ("10.1000/search.2026_01", "metadata"),
        ("98765432", "metadata"),
        ("example.org/source?id=IL6_2026", "metadata"),
    ],
)
def test_searches_metadata_and_bilingual_abstracts_with_literal_fallback(
    tmp_path: Path, query: str, content_type: str
) -> None:
    service = LibraryService(tmp_path)
    try:
        paper_id = _paper(
            service,
            "Cytokines and thrombosis",
            abstract_en="Interleukin signaling includes IL-6 in thrombosis.",
            abstract_zh="抗磷脂综合征凝血悖论涉及 aPS/PT 抗体。",
            doi="10.1000/search.2026_01",
            pmid="98765432",
            source_url="https://example.org/source?id=IL6_2026",
        )

        page = service.list_items(page=1, page_size=10, query=query)
    finally:
        service.close()

    assert [item["paper_id"] for item in page["items"]] == [paper_id]
    matches = page["items"][0]["search_matches"]
    assert content_type in {match["content_type"] for match in matches}
    assert all("<mark>" not in match["snippet"] for match in matches)
    assert all(len(match["snippet"]) <= 183 for match in matches)


def test_literal_percent_and_underscore_are_not_sql_wildcards(tmp_path: Path) -> None:
    service = LibraryService(tmp_path)
    try:
        exact = _paper(service, "A 100%_specific assay")
        _paper(service, "A 100XXspecific assay")

        page = service.list_items(page=1, page_size=10, query="100%_specific")
    finally:
        service.close()

    assert [item["paper_id"] for item in page["items"]] == [exact]


def test_search_preserves_filters_pagination_and_empty_result(tmp_path: Path) -> None:
    service = LibraryService(tmp_path)
    try:
        folder = service.create_folder("APS")
        selected = [
            _paper(service, f"Selected {index}", abstract_en="coagulation signal")
            for index in range(3)
        ]
        outside = _paper(service, "Outside", abstract_en="coagulation signal")
        service.move_items(selected, folder["folder_id"])
        service.add_tags(selected, ["Mechanism"])
        service.conn.execute(
            "UPDATE items SET status='ready' WHERE paper_id IN (?,?,?)", selected
        )
        service.conn.commit()

        first = service.list_items(
            page=1,
            page_size=2,
            query="coagulation",
            folder_id=folder["folder_id"],
            tags=["Mechanism"],
            status="ready",
        )
        second = service.list_items(
            page=2,
            page_size=2,
            query="coagulation",
            folder_id=folder["folder_id"],
            tags=["Mechanism"],
            status="ready",
        )
        empty = service.list_items(page=1, page_size=10, query="absent-term")
    finally:
        service.close()

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert outside not in {
        item["paper_id"] for item in first["items"] + second["items"]
    }
    assert empty == {"items": [], "page": 1, "page_size": 10, "total": 0}


def test_confirmed_conclusion_is_typed_and_resolved_dynamically(tmp_path: Path) -> None:
    library = LibraryService(tmp_path)
    review = ReviewService(tmp_path)
    try:
        paper_id = _paper(library, "Conclusion paper")
        review.bind_session("parent-a", paper_id, "review-a")
        confirmed = review.confirm_conclusions(
            "review-a",
            [
                {
                    "conclusion_type": "个人判断",
                    "conclusion_text": "需要复核微血栓分层",
                    "basis": "personal",
                }
            ],
        )["conclusions"][0]

        personal_page = library.list_items(
            page=1, page_size=10, query="微血栓"
        )
        personal_match = personal_page["items"][0]["search_matches"][0]

        review.conn.execute(
            "UPDATE review_conclusions SET basis='paper', evidence_json='{' "
            "WHERE conclusion_id=?",
            (confirmed["conclusion_id"],),
        )
        review.conn.commit()
        stale_page = library.list_items(page=1, page_size=10, query="微血栓")
        stale_match = stale_page["items"][0]["search_matches"][0]
    finally:
        review.close()
        library.close()

    assert personal_match["content_type"] == "conclusion"
    assert personal_match["conclusion_id"] == confirmed["conclusion_id"]
    assert personal_match["basis"] == "personal"
    assert personal_match["evidence_status"] == "not_provided"
    assert personal_match["scientific_validity"] == "not_assessed"
    assert personal_match["claim_support"] == "not_source_supported"
    assert stale_match["basis"] == "paper"
    assert stale_match["evidence_status"] == "stale"
    assert stale_match["scientific_validity"] == "not_assessed"


def test_item_updates_and_rebuild_replace_only_derived_search_rows(
    tmp_path: Path,
) -> None:
    service = LibraryService(tmp_path)
    try:
        paper_id = _paper(
            service,
            "Mutable abstract",
            doi="10.1000/mutable",
            abstract_en="obsolete biomarker",
        )
        service.ingest(
            PaperMetadata(
                title="Mutable abstract",
                doi="10.1000/mutable",
                abstract_en="current biomarker",
            )
        )
        assert service.list_items(page=1, page_size=10, query="obsolete")["total"] == 0
        assert service.list_items(page=1, page_size=10, query="current")["total"] == 1

        service.conn.execute("DELETE FROM library_search_documents")
        service.conn.commit()
        assert service.list_items(page=1, page_size=10, query="current")["total"] == 0

        rebuilt = service.rebuild_search_index()
        restored = service.list_items(page=1, page_size=10, query="current")
        item_count = service.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        service.close()

    assert rebuilt["papers"] == 1
    assert rebuilt["documents"] >= 2
    assert [item["paper_id"] for item in restored["items"]] == [paper_id]
    assert item_count == 1


def test_ensure_item_indexes_abstracts_supplied_at_creation(tmp_path: Path) -> None:
    service = LibraryService(tmp_path)
    try:
        paper_id = service.ensure_item(
            PaperMetadata(
                title="Ensure item abstract",
                abstract_en="complement activation marker",
                abstract_zh="补体激活标志物",
            )
        )["paper_id"]
        english = service.list_items(page=1, page_size=10, query="complement")
        chinese = service.list_items(page=1, page_size=10, query="补体")
    finally:
        service.close()

    assert [item["paper_id"] for item in english["items"]] == [paper_id]
    assert english["items"][0]["search_matches"][0]["content_type"] == "abstract_en"
    assert [item["paper_id"] for item in chinese["items"]] == [paper_id]
    assert chinese["items"][0]["search_matches"][0]["content_type"] == "abstract_zh"


def test_existing_v4_database_without_search_tables_is_repaired_on_open(
    tmp_path: Path,
) -> None:
    first = LibraryService(tmp_path)
    try:
        paper_id = _paper(first, "Legacy v4 paper", abstract_zh="旧版本摘要可检索")
    finally:
        first.close()

    with sqlite3.connect(library_path(tmp_path)) as conn:
        conn.executescript(
            "DROP TRIGGER IF EXISTS library_search_items_ai;"
            "DROP TRIGGER IF EXISTS library_search_items_au;"
            "DROP TRIGGER IF EXISTS library_search_items_ad;"
            "DROP TRIGGER IF EXISTS library_search_conclusions_ai;"
            "DROP TRIGGER IF EXISTS library_search_conclusions_au;"
            "DROP TRIGGER IF EXISTS library_search_conclusions_ad;"
            "DROP TABLE IF EXISTS library_search_fts;"
            "DROP TABLE IF EXISTS library_search_documents;"
        )
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4

    reopened = LibraryService(tmp_path)
    try:
        page = reopened.list_items(page=1, page_size=10, query="旧版本")
        version = reopened.conn.execute("PRAGMA user_version").fetchone()[0]
        legacy = reopened.search("旧版本")
    finally:
        reopened.close()

    assert version == 4
    assert [item["paper_id"] for item in page["items"]] == [paper_id]
    assert [item["paper_id"] for item in legacy] == [paper_id]
    assert legacy[0]["search_matches"][0]["content_type"] == "abstract_zh"
