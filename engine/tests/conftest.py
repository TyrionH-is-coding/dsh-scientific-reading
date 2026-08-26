"""共享测试 fixture。"""

from pathlib import Path
import json

import pytest

from scientific_reading.models import PaperMetadata


def _write_pdf(path: Path, pages: list[str]) -> Path:
    payload = "\n\f\n".join(pages).encode("utf-8")
    path.write_bytes(b"%PDF-1.4\n% offline fixture\n" + payload + b"\n%%EOF\n")
    return path


@pytest.fixture
def metadata() -> PaperMetadata:
    return PaperMetadata(
        title="Load Distribution in Modular Steel Bridges",
        authors=["Alex Rivera"],
        doi="10.5555/bridge.2024.1",
        year=2024,
        journal="Open Engineering Notes",
    )


@pytest.fixture
def metadata_json(tmp_path: Path, metadata: PaperMetadata) -> Path:
    path = tmp_path / "metadata-input.json"
    path.write_text(
        json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def engineering_pdf(tmp_path: Path) -> Path:
    return _write_pdf(
        tmp_path / "engineering.pdf",
        [
            "Load Distribution in Modular Steel Bridges\n"
            "Alex Rivera\nDOI: 10.5555/bridge.2024.1\nAbstract and introduction.",
            "Methods\nFinite element mesh and load cases.",
        ],
    )


@pytest.fixture
def other_pdf(tmp_path: Path) -> Path:
    return _write_pdf(
        tmp_path / "other.pdf",
        [
            "Marginal Notes in Fifteenth-Century Manuscripts\n"
            "DOI: 10.5555/manuscript.2020.9",
            "Discussion\nScribal practices and material evidence.",
        ],
    )


@pytest.fixture
def abstract_only_pdf(tmp_path: Path) -> Path:
    return _write_pdf(
        tmp_path / "abstract-only.pdf",
        [
            "Load Distribution in Modular Steel Bridges\n"
            "DOI: 10.5555/bridge.2024.1\nAbstract only."
        ],
    )
