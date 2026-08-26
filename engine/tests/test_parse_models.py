import pytest

from scientific_reading.parse_models import (
    ParseReport,
    SourceBlock,
    assess_quality,
)


def test_source_block_round_trip() -> None:
    block = SourceBlock(
        block_id="p0001-b0001",
        page=1,
        bbox=(72.0, 90.0, 520.0, 132.0),
        kind="text",
        text="Bridge load distribution",
    )

    assert SourceBlock.from_dict(block.to_dict()) == block


def test_source_block_rejects_invalid_page_and_bbox() -> None:
    with pytest.raises(ValueError):
        SourceBlock.from_dict(
            {
                "block_id": "p0000-b0001",
                "page": 0,
                "bbox": [0, 0, 10, 10],
                "kind": "text",
                "text": "invalid",
            }
        )
    with pytest.raises(ValueError):
        SourceBlock.from_dict(
            {
                "block_id": "p0001-b0001",
                "page": 1,
                "bbox": [0, 0, float("inf"), 10],
                "kind": "text",
                "text": "invalid",
            }
        )


def test_quality_requires_mineru_for_sparse_pages() -> None:
    report = assess_quality(
        page_characters=[1200, 0, 0, 900],
        text="Paper title\nusable text",
        identity_anchor_found=True,
        block_count=2,
        image_count=0,
        table_count=0,
    )

    assert report.status == "needs_mineru"
    assert "sparse_pages" in report.needs_mineru_reasons


def test_quality_accepts_text_with_identity_anchor() -> None:
    report = assess_quality(
        page_characters=[900, 1100],
        text="Paper title\nclean text",
        identity_anchor_found=True,
        block_count=3,
        image_count=1,
        table_count=0,
    )

    assert report.status == "parsed_fast"
    assert report.needs_mineru_reasons == []
    assert ParseReport.from_dict(report.to_dict()) == report


@pytest.mark.parametrize(
    ("text", "identity_anchor_found", "reason"),
    [
        ("", True, "no_text"),
        ("\ufffd" * 2 + "clean", True, "suspicious_characters"),
        ("clean text", False, "identity_anchor_missing"),
    ],
)
def test_quality_reports_other_upgrade_reasons(
    text: str,
    identity_anchor_found: bool,
    reason: str,
) -> None:
    report = assess_quality(
        page_characters=[len(text)],
        text=text,
        identity_anchor_found=identity_anchor_found,
        block_count=1 if text else 0,
        image_count=0,
        table_count=0,
    )

    assert report.status == "needs_mineru"
    assert reason in report.needs_mineru_reasons
