from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scientific_reading.identifiers import stable_paper_id
from scientific_reading.mineru_provider import ProviderResult
from scientific_reading.mineru_service import MineruParseService
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace


class _PathLimitedProvider:
    provider_id = "mineru-local-v1"
    version = "3.4.5"

    def __init__(self, title: str) -> None:
        self.title = title
        self.raw_root: Path | None = None

    def parse(
        self,
        _pdf: Path,
        raw_root: Path,
        _method: str,
        _heartbeat,
    ) -> ProviderResult:
        self.raw_root = raw_root
        content = (
            raw_root
            / "paper"
            / "hybrid_auto"
            / "paper_content_list.json"
        )
        if len(str(content)) >= 260:
            raise OSError("simulated Windows MAX_PATH failure")
        content.parent.mkdir(parents=True)
        content.write_text(
            json.dumps(
                [
                    {
                        "type": "text",
                        "text": self.title,
                        "bbox": [72, 90, 520, 132],
                        "page_idx": 0,
                    },
                    {
                        "type": "text",
                        "text": "Synthetic path-length acceptance content.",
                        "bbox": [72, 150, 520, 190],
                        "page_idx": 0,
                    },
                ]
            ),
            encoding="utf-8",
        )
        return ProviderResult(
            provider_id=self.provider_id,
            version=self.version,
            raw_root=raw_root,
        )


def test_staging_is_shallow_when_final_generation_path_fits_max_path(
    tmp_path: Path,
    engineering_pdf: Path,
    metadata: PaperMetadata,
) -> None:
    source = engineering_pdf.read_bytes()
    source_sha256 = hashlib.sha256(source).hexdigest()
    relative_final_content = (
        Path("papers")
        / stable_paper_id(metadata)
        / "generations"
        / source_sha256[:16]
        / "parsed"
        / "mineru"
        / "raw"
        / "paper"
        / "hybrid_auto"
        / "paper_content_list.json"
    )
    padding_length = 250 - len(str(tmp_path)) - len(
        str(relative_final_content)
    ) - 2
    assert padding_length > 0
    data_root = tmp_path / ("d" * padding_length)
    base = PaperWorkspace.create(data_root, metadata)
    generation = PaperWorkspace.create_generation(
        base, source_sha256, metadata
    )
    generation.source_pdf.write_bytes(source)
    state = generation.load_job()
    state.status = "pdf_ready"
    state.stages["pdf_acquisition"] = StageRecord(
        status="completed",
        result={"sha256": source_sha256},
    )
    generation.save_job(state)
    final_content = (
        generation.parsed_dir
        / "mineru"
        / "raw"
        / "paper"
        / "hybrid_auto"
        / "paper_content_list.json"
    )
    legacy_content = (
        generation.parsed_dir
        / f".mineru-staging-{'0' * 32}"
        / "raw"
        / "paper"
        / "hybrid_auto"
        / "paper_content_list.json"
    )
    assert len(str(final_content)) < 260 <= len(str(legacy_content))
    provider = _PathLimitedProvider(metadata.title)

    result = MineruParseService(
        provider_factory=lambda *_args: provider
    ).run(
        data_root,
        metadata,
        "auto",
        heartbeat=lambda: None,
        paper_id=base.root.name,
        workspace=generation,
    )

    assert result.status == "parsed_mineru"
    assert provider.raw_root is not None
    assert provider.raw_root.parent.parent == data_root.resolve()
    assert provider.raw_root.parent.name.startswith(".mineru-staging-")
    shallow_content = (
        provider.raw_root
        / "paper"
        / "hybrid_auto"
        / "paper_content_list.json"
    )
    assert len(str(shallow_content)) < 260
    assert final_content.is_file()
    assert not provider.raw_root.parent.exists()
