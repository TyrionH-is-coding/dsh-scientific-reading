from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scientific_reading.library_schema import migrate_library
from scientific_reading.evidence_locator import build_locator
from scientific_reading.review_service import ReviewService
from test_evidence_locator import (
    _fixture as _evidence_fixture,
    _reparse_same_source,
)


def _insert_paper(root: Path, paper_id: str = "library_alpha") -> None:
    migrate_library(root)
    with sqlite3.connect(root / "library.sqlite") as connection:
        connection.execute(
            "INSERT INTO items (paper_id, library_key, title, authors_json, doi, status, "
            "created_at, updated_at, abstract_en, abstract_zh) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                paper_id,
                "key_" + paper_id,
                "Alpha paper",
                '["A. Author"]',
                "10.1000/alpha",
                "ready",
                "2026-08-30T00:00:00+00:00",
                "2026-08-30T00:00:00+00:00",
                "English abstract.",
                "中文摘要。",
            ),
        )
        connection.execute(
            "INSERT INTO artifacts (paper_id, kind, rel_path, status, updated_at) "
            "VALUES (?, 'reader', 'papers/library_alpha/reading/reader.html', 'ready', 'now')",
            (paper_id,),
        )


def test_binding_is_idempotent_per_parent_and_paper(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        first = service.bind_session("parent-metabolism", "library_alpha", "child-a")
        second = service.bind_session("parent-metabolism", "library_alpha", "child-a")

        assert first["status"] == "created"
        assert second["status"] == "reused"
        assert service.get_binding("parent-metabolism", "library_alpha") == {
            "parent_session_id": "parent-metabolism",
            "paper_id": "library_alpha",
            "review_session_id": "child-a",
        }
    finally:
        service.close()


def test_same_paper_has_independent_bindings_under_different_parents(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-metabolism", "library_alpha", "child-metabolism")
        service.bind_session("parent-immunology", "library_alpha", "child-immunology")

        assert service.get_binding("parent-metabolism", "library_alpha")["review_session_id"] == "child-metabolism"
        assert service.get_binding("parent-immunology", "library_alpha")["review_session_id"] == "child-immunology"
    finally:
        service.close()


def test_child_session_cannot_be_bound_to_two_review_scopes(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", "library_alpha", "child-a")
        with pytest.raises(ValueError, match="review_session_already_bound"):
            service.bind_session("parent-b", "library_alpha", "child-a")
    finally:
        service.close()


def test_unknown_paper_is_rejected(tmp_path: Path) -> None:
    migrate_library(tmp_path)
    service = ReviewService(tmp_path)
    try:
        with pytest.raises(ValueError, match="paper_not_found"):
            service.bind_session("parent-a", "missing", "child-a")
    finally:
        service.close()


def test_context_is_resolved_from_real_child_session_binding(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", "library_alpha", "child-a")

        context = service.context_for_session("child-a")

        assert context["parent_session_id"] == "parent-a"
        assert context["review_session_id"] == "child-a"
        assert context["paper"] == {
            "paper_id": "library_alpha",
            "title": "Alpha paper",
            "authors": ["A. Author"],
            "doi": "10.1000/alpha",
            "abstract_en": "English abstract.",
            "abstract_zh": "中文摘要。",
        }
        assert context["reader_path"] == "papers/library_alpha/reading/reader.html"
        assert context["confirmed_conclusions"] == []
    finally:
        service.close()


def test_confirm_writes_all_conclusions_in_one_bound_scope(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", "library_alpha", "child-a")
        result = service.confirm_conclusions(
            "child-a",
            [
                {
                    "conclusion_type": "主要发现",
                    "conclusion_text": "结论一",
                    "evidence_locator": "Figure 2",
                },
                {
                    "conclusion_type": "局限",
                    "conclusion_text": "结论二",
                    "evidence_locator": "Discussion",
                },
            ],
        )

        assert result["status"] == "confirmed"
        assert result["inserted"] == 2
        stored = service.context_for_session("child-a")["confirmed_conclusions"]
        assert [(row["conclusion_type"], row["conclusion_text"]) for row in stored] == [
            ("主要发现", "结论一"),
            ("局限", "结论二"),
        ]
        assert all(row["parent_session_id"] == "parent-a" for row in stored)
        assert all(row["basis"] == "legacy" for row in stored)
        assert all(row["evidence_status"] == "legacy_unverified" for row in stored)
        assert [row["evidence_locator"] for row in stored] == [
            "Figure 2",
            "Discussion",
        ]
    finally:
        service.close()


def test_confirm_rejects_empty_batch_without_partial_writes(tmp_path: Path) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", "library_alpha", "child-a")
        with pytest.raises(ValueError, match="conclusions_required"):
            service.confirm_conclusions("child-a", [])
        with pytest.raises(ValueError, match="conclusion_text_required"):
            service.confirm_conclusions(
                "child-a",
                [
                    {"conclusion_type": "主要发现", "conclusion_text": "有效", "evidence_locator": "p.1"},
                    {"conclusion_type": "局限", "conclusion_text": "  ", "evidence_locator": "p.2"},
                ],
            )
        assert service.context_for_session("child-a")["confirmed_conclusions"] == []
    finally:
        service.close()


def test_paper_conclusion_stores_and_resolves_complete_locator(
    tmp_path: Path,
) -> None:
    paper_id, _generation, source_sha = _evidence_fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote", page=1
    )
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", paper_id, "child-a")
        result = service.confirm_conclusions(
            "child-a",
            [
                {
                    "conclusion_type": "主要发现",
                    "conclusion_text": "定位到论文原文，但科学有效性仍需审阅。",
                    "basis": "paper",
                    "evidence": locator,
                }
            ],
        )

        saved = result["conclusions"][0]
        assert saved["basis"] == "paper"
        assert saved["evidence"]["contract"] == "evidence-locator-v1"
        assert saved["evidence"]["source_sha256"] == source_sha
        assert saved["evidence_status"] == "location_verified"
        assert saved["scientific_validity"] == "not_assessed"
        assert saved["claim_support"] == "location_only"
        assert saved["source"]["block_id"] == "p0001-m0002"
        assert saved["links"]["pdf"]["page"] == 1
        assert service.resolve_conclusion(saved["conclusion_id"]) == saved
        assert service.context_for_session("child-a")["confirmed_conclusions"] == [
            saved
        ]
    finally:
        service.close()


@pytest.mark.parametrize("basis", ["personal", "inference", "question"])
def test_nonpaper_basis_may_omit_locator_without_claiming_source_support(
    tmp_path: Path,
    basis: str,
) -> None:
    _insert_paper(tmp_path)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", "library_alpha", "child-a")
        result = service.confirm_conclusions(
            "child-a",
            [
                {
                    "conclusion_type": "讨论",
                    "conclusion_text": "待讨论内容",
                    "basis": basis,
                }
            ],
        )

        saved = result["conclusions"][0]
        assert saved["basis"] == basis
        assert saved["evidence"] is None
        assert saved["evidence_status"] == "not_provided"
        assert saved["source"] is None
        assert saved["links"] is None
        assert saved["claim_support"] == "not_source_supported"
    finally:
        service.close()


def test_paper_basis_requires_valid_evidence_without_partial_write(
    tmp_path: Path,
) -> None:
    paper_id, _generation, _source_sha = _evidence_fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", paper_id, "child-a")
        with pytest.raises(ValueError, match="paper_evidence_required"):
            service.confirm_conclusions(
                "child-a",
                [
                    {
                        "conclusion_type": "发现",
                        "conclusion_text": "没有定位",
                        "basis": "paper",
                    }
                ],
            )
        with pytest.raises(ValueError, match="quote_not_found"):
            service.confirm_conclusions(
                "child-a",
                [
                    {
                        "conclusion_type": "发现",
                        "conclusion_text": "错误定位",
                        "basis": "paper",
                        "evidence": {
                            **locator,
                            "quote": "similar target quote",
                        },
                    }
                ],
            )
        assert service.context_for_session("child-a")["confirmed_conclusions"] == []
    finally:
        service.close()


def test_stale_locator_is_reported_without_rebinding(tmp_path: Path) -> None:
    paper_id, generation, _source_sha = _evidence_fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", paper_id, "child-a")
        result = service.confirm_conclusions(
            "child-a",
            [
                {
                    "conclusion_type": "发现",
                    "conclusion_text": "带定位结论",
                    "basis": "paper",
                    "evidence": locator,
                }
            ],
        )
        original = result["conclusions"][0]["evidence"]
        source_map = generation.parsed_dir / "mineru" / "source_map.json"
        source_map.write_bytes(source_map.read_bytes() + b"\n")

        stale = service.context_for_session("child-a")["confirmed_conclusions"][0]

        assert stale["evidence"] == original
        assert stale["evidence_status"] == "stale"
        assert stale["evidence_error"] == "source_map_changed"
        assert stale["source"] is None
        assert stale["links"] is None
    finally:
        service.close()


def test_confirm_rejects_locator_after_same_source_reparse(
    tmp_path: Path,
) -> None:
    paper_id, generation, source_sha = _evidence_fixture(tmp_path)
    locator = build_locator(
        tmp_path, paper_id, "p0001-m0002", "exact target quote"
    )
    _reparse_same_source(generation, source_sha)
    service = ReviewService(tmp_path)
    try:
        service.bind_session("parent-a", paper_id, "child-a")
        with pytest.raises(ValueError, match="source_map_changed"):
            service.confirm_conclusions(
                "child-a",
                [
                    {
                        "conclusion_type": "发现",
                        "conclusion_text": "不能静默换到新解析代",
                        "basis": "paper",
                        "evidence": locator,
                    }
                ],
            )
        assert service.context_for_session("child-a")["confirmed_conclusions"] == []
    finally:
        service.close()
