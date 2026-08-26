from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import PaperMetadata


MINIMUM_PDF_BYTES = 64


@dataclass(slots=True)
class PdfValidationResult:
    valid: bool
    page_count: int = 0
    sha256: str = ""
    title_match: bool = False
    doi_match: bool = False
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(path: Path, _metadata: PaperMetadata) -> PdfValidationResult:
    """Perform a cheap upload preflight without parsing or rendering the PDF."""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        return PdfValidationResult(valid=False, failures=["file_missing"])

    sha256 = _sha256(pdf_path)
    with pdf_path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        return PdfValidationResult(
            valid=False,
            sha256=sha256,
            failures=["pdf_signature"],
        )
    if pdf_path.stat().st_size < MINIMUM_PDF_BYTES:
        return PdfValidationResult(
            valid=False,
            sha256=sha256,
            failures=["pdf_too_small"],
        )
    return PdfValidationResult(valid=True, sha256=sha256)
