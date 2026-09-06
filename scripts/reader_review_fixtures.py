from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from scientific_reading.assets import AssetManifest
from scientific_reading.full_read_models import (
    FULL_TRANSLATION_CONTRACT_VERSION,
)
from scientific_reading.full_read_service import FullReadService
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.workspace import (
    PaperWorkspace,
    atomic_write_json,
)


FIXTURE_CASES = (
    "formula-outline",
    "superscript-text",
    "figures-captions",
)
FIXTURE_CONTRACT_VERSION = "reader-review-fixture-v1"
FIXTURE_PARSER_VERSION = "reader-review-fixture-1"
FIXTURE_METHOD = "auto"
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "review" / "fixtures"
_TOP_LEVEL_KEYS = {
    "contract_version",
    "case",
    "paper_id",
    "metadata",
    "content_items",
    "asset_files",
    "translations",
    "review",
}
_METADATA_KEYS = {"title", "authors", "year", "journal"}
_CONTENT_KEYS = {
    "type",
    "page_idx",
    "bbox",
    "text",
    "text_level",
    "img_path",
    "image_caption",
    "image_footnote",
    "table_caption",
    "table_footnote",
    "table_body",
    "list_items",
    "is_body",
}
_TRANSLATION_KEYS = {"block_id", "translation_zh", "highlight"}


def fixture_path(case: str) -> Path:
    if case not in FIXTURE_CASES:
        raise ValueError("fixture_case_invalid")
    return _FIXTURE_ROOT / f"{case}.json"


def _exact_keys(value: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("fixture_contract_invalid")
    return value


def _validate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("fixture_contract_invalid")
    cleaned = value.strip().replace("\\", "/")
    posix = PurePosixPath(cleaned)
    windows = PureWindowsPath(cleaned)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise ValueError("fixture_contract_invalid")
    return posix.as_posix()


def _validate_payload(value: object) -> dict[str, Any]:
    payload = _exact_keys(value, _TOP_LEVEL_KEYS)
    if payload["contract_version"] != FIXTURE_CONTRACT_VERSION:
        raise ValueError("fixture_contract_invalid")
    case = payload["case"]
    if case not in FIXTURE_CASES:
        raise ValueError("fixture_contract_invalid")
    expected_paper_id = f"fixture_{case.replace('-', '_')}"
    if payload["paper_id"] != expected_paper_id:
        raise ValueError("fixture_contract_invalid")
    metadata = _exact_keys(payload["metadata"], _METADATA_KEYS)
    if (
        not isinstance(metadata["title"], str)
        or not metadata["title"].strip()
        or not isinstance(metadata["authors"], list)
        or not metadata["authors"]
        or any(
            not isinstance(author, str) or not author.strip()
            for author in metadata["authors"]
        )
        or not isinstance(metadata["year"], int)
        or isinstance(metadata["year"], bool)
        or not isinstance(metadata["journal"], str)
        or not metadata["journal"].strip()
    ):
        raise ValueError("fixture_contract_invalid")
    content_items = payload["content_items"]
    if not isinstance(content_items, list) or not content_items:
        raise ValueError("fixture_contract_invalid")
    for item in content_items:
        if not isinstance(item, dict) or not set(item).issubset(_CONTENT_KEYS):
            raise ValueError("fixture_contract_invalid")
    asset_files = payload["asset_files"]
    if not isinstance(asset_files, dict) or any(
        not isinstance(contents, str)
        for contents in asset_files.values()
    ):
        raise ValueError("fixture_contract_invalid")
    for relative in asset_files:
        _validate_relative_path(relative)
    translations = payload["translations"]
    if not isinstance(translations, list) or not translations:
        raise ValueError("fixture_contract_invalid")
    for row in translations:
        parsed = _exact_keys(row, _TRANSLATION_KEYS)
        if (
            not isinstance(parsed["block_id"], str)
            or re.fullmatch(r"p[0-9]{4}-(?:m|c)[0-9]{4}", parsed["block_id"])
            is None
            or not isinstance(parsed["translation_zh"], str)
            or parsed["highlight"] not in {"result", "method", "none"}
        ):
            raise ValueError("fixture_contract_invalid")
    if not isinstance(payload["review"], dict):
        raise ValueError("fixture_contract_invalid")
    return payload


def _write_asset_files(
    raw_root: Path,
    asset_files: dict[str, str],
) -> None:
    resolved_root = raw_root.resolve()
    for relative, contents in asset_files.items():
        target = raw_root / _validate_relative_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        resolved_target = target.resolve()
        if not resolved_target.is_relative_to(resolved_root):
            raise ValueError("fixture_contract_invalid")
        target.write_text(contents, encoding="utf-8", newline="\n")


def _write_translation_batches(
    service: FullReadService,
    workspace: PaperWorkspace,
    translations: list[dict[str, Any]],
) -> None:
    configured = {row["block_id"]: row for row in translations}
    if len(configured) != len(translations):
        raise ValueError("fixture_contract_invalid")
    active = service._inspect_active_mineru(workspace)
    if set(configured) != {row["block_id"] for row in active.rows}:
        raise ValueError("fixture_translation_mismatch")
    plan = service.prepare(workspace)
    root = workspace.reading_dir / "full"
    for batch in plan.plan["batches"]:
        source = json.loads(
            (root / batch["source_file"]).read_text(encoding="utf-8")
        )
        service.save_translation_batch(
            workspace,
            {
                "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
                "batch_id": source["batch_id"],
                "source_sha256": source["source_sha256"],
                "translations": [
                    {
                        "block_id": row["block_id"],
                        "source_text": row["english"],
                        "translation_zh": configured[row["block_id"]][
                            "translation_zh"
                        ],
                        "highlight": configured[row["block_id"]][
                            "highlight"
                        ],
                    }
                    for row in source["blocks"]
                ],
            },
        )


def materialize_fixture_payload(
    value: object,
    target_root: Path,
) -> PaperWorkspace:
    payload = _validate_payload(value)
    target = Path(target_root).resolve()
    if target.exists() and any(target.iterdir()):
        raise ValueError("fixture_target_not_empty")
    target.mkdir(parents=True, exist_ok=True)
    workspace = PaperWorkspace(root=target)
    for directory in (
        workspace.parsed_images,
        workspace.parsed_tables,
        workspace.reading_dir,
        workspace.output_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    metadata = PaperMetadata.from_dict(payload["metadata"])
    atomic_write_json(workspace.metadata_path, metadata.to_dict())
    source_bytes = (
        "%PDF-1.4\n% deterministic reader review fixture\n"
        f"% {payload['case']}\n"
    ).encode("utf-8")
    workspace.source_pdf.write_bytes(source_bytes)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    parsed_root = workspace.parsed_dir / "mineru"
    raw_root = parsed_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        raw_root / "fixture_content_list.json",
        payload["content_items"],
    )
    _write_asset_files(raw_root, payload["asset_files"])
    normalized = MineruNormalizer(FIXTURE_PARSER_VERSION).normalize(
        raw_root,
        parsed_root,
        metadata,
        source_sha256,
    )
    for name in ("source_map.json", "parse_report.json"):
        path = parsed_root / name
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["method"] = FIXTURE_METHOD
        if name == "parse_report.json":
            artifact["provider"] = "mineru-local-v1"
            artifact["provider_version"] = FIXTURE_CONTRACT_VERSION
        atomic_write_json(path, artifact)
    manifest = AssetManifest(workspace.manifest_path)
    for asset in normalized.assets:
        manifest.upsert(asset)
    workspace.save_job(
        JobState(
            paper_id=workspace.root.name,
            status="parsed",
            stages={
                "paper_parse_upgrade": StageRecord(
                    status="completed",
                    result={
                        "active_parsed_dir": "parsed/mineru",
                        "source_sha256": source_sha256,
                        "method": FIXTURE_METHOD,
                        "mineru_version": FIXTURE_PARSER_VERSION,
                    },
                )
            },
        )
    )
    service = FullReadService()
    _write_translation_batches(
        service,
        workspace,
        payload["translations"],
    )
    service.finalize(workspace, payload["review"])
    return workspace


def materialize_fixture(case: str, target_root: Path) -> PaperWorkspace:
    path = fixture_path(case)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("fixture_contract_invalid") from error
    if not isinstance(payload, dict) or payload.get("case") != case:
        raise ValueError("fixture_contract_invalid")
    return materialize_fixture_payload(payload, target_root)
