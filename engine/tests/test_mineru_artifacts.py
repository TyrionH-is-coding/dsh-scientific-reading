from __future__ import annotations

import json
import shutil
from pathlib import Path

from scientific_reading.mineru_artifacts import MineruArtifactValidator
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import PaperMetadata


def _write_content_list(raw_root: Path, items: list[dict]) -> Path:
    path = raw_root / "paper" / "auto" / "bridge_content_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _item(item_type: str, page: int, **values) -> dict:
    return {
        "type": item_type,
        "page_idx": page,
        "bbox": [72, 90, 520, 132],
        **values,
    }


def _published_mineru_tree(
    tmp_path: Path,
    metadata: PaperMetadata,
    *,
    provider_version: str | None = "pipeline",
    extra_asset_fields: dict | None = None,
) -> tuple[Path, str]:
    raw_root = tmp_path / "raw"
    parsed_root = tmp_path / "mineru"
    asset_root = raw_root / "paper" / "auto" / "images"
    asset_root.mkdir(parents=True)
    (asset_root / "beam.png").write_bytes(b"beam-image")
    _write_content_list(
        raw_root,
        [
            _item("header", 0, text=metadata.title, text_level=1),
            _item(
                "text",
                0,
                text="A modular bridge transfers wheel loads across beams.",
            ),
            _item(
                "image",
                1,
                img_path="images/beam.png",
                image_caption=["Bridge beam arrangement"],
                image_footnote=[],
            ),
        ],
    )
    source_sha = "a" * 64
    mineru_version = "mineru-api-v4:pipeline"
    MineruNormalizer(mineru_version).normalize(
        raw_root, parsed_root, metadata, source_sha
    )
    shutil.copytree(raw_root, parsed_root / "raw")
    for name in ("source_map.json", "parse_report.json"):
        path = parsed_root / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        if name == "parse_report.json":
            payload["provider"] = "mineru-api-v4"
            if provider_version is not None:
                payload["provider_version"] = provider_version
            payload["model_version"] = "pipeline"
            payload["batch_id"] = "batch-fixture"
            payload["result_zip_sha256"] = "b" * 64
            if extra_asset_fields:
                for asset in payload["assets"]:
                    asset.update(extra_asset_fields)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return parsed_root, source_sha


def test_validate_accepts_legacy_report_without_provider_version(
    tmp_path: Path, metadata: PaperMetadata
) -> None:
    parsed_root, source_sha = _published_mineru_tree(
        tmp_path, metadata, provider_version=None
    )

    report, assets = MineruArtifactValidator.validate_mineru_artifacts(
        parsed_root,
        source_sha,
        method="auto",
        mineru_version="mineru-api-v4:pipeline",
        metadata=metadata,
    )

    assert report.status == "parsed_mineru"
    assert assets


def test_validate_ignores_legacy_quick_read_flag_on_assets(
    tmp_path: Path, metadata: PaperMetadata
) -> None:
    parsed_root, source_sha = _published_mineru_tree(
        tmp_path,
        metadata,
        extra_asset_fields={"selected_for_quick_read": False},
    )

    report, _assets = MineruArtifactValidator.validate_mineru_artifacts(
        parsed_root,
        source_sha,
        method="auto",
        mineru_version="mineru-api-v4:pipeline",
        metadata=metadata,
    )

    assert report.status == "parsed_mineru"
