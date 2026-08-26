from pathlib import Path

from scientific_reading.models import PaperMetadata
from scientific_reading.pdf_validation import validate_pdf


def metadata() -> PaperMetadata:
    return PaperMetadata(title="Fictional Bridge Load Study", year=2026)


def test_pdf_preflight_only_requires_signature_size_and_hash(tmp_path: Path) -> None:
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\n" + b"not a locally parsed document" * 10)

    result = validate_pdf(pdf, metadata())

    assert result.valid is True
    assert result.sha256
    assert result.page_count == 0
    assert result.title_match is False
    assert result.doi_match is False


def test_pdf_preflight_rejects_non_pdf_and_empty_pdf(tmp_path: Path) -> None:
    html = tmp_path / "download.pdf"
    html.write_text("<html>login</html>", encoding="utf-8")
    assert validate_pdf(html, metadata()).failures == ["pdf_signature"]

    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"%PDF-")
    assert validate_pdf(empty, metadata()).failures == ["pdf_too_small"]
