from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from .assets import AssetManifest
from .mineru_models import MINERU_NORMALIZATION_VERSION
from .mineru_normalizer import render_mineru_markdown
from .models import AssetRecord, PaperMetadata
from .parse_models import ParseReport, SourceBlock
from .workspace import PaperWorkspace, atomic_write_json

def active_parsed_root(workspace: PaperWorkspace) -> Path:
    state = workspace.load_job()
    stage = state.stages.get("paper_parse_upgrade")
    selected = (
        stage.result.get("active_parsed_dir")
        if stage is not None and stage.status == "completed"
        else None
    )
    if selected is None:
        return workspace.parsed_dir
    if selected != "parsed/mineru":
        raise ValueError("active parse 路径无效")
    return workspace.parsed_dir / "mineru"

class MineruArtifactValidator:

    @staticmethod

    def validate_mineru_artifacts(
            parsed_root: Path,
            source_sha256: str,
            *,
            method: str,
            mineru_version: str,
            manifest_path: Path | None = None,
            metadata: PaperMetadata | None = None,
        ) -> tuple[ParseReport, tuple[AssetRecord, ...]]:
            report_payload = json.loads(
                (parsed_root / "parse_report.json").read_text(encoding="utf-8")
            )
            source_map = json.loads(
                (parsed_root / "source_map.json").read_text(encoding="utf-8")
            )
            markdown = (parsed_root / "full.md").read_text(encoding="utf-8")
            raw_hash = report_payload.get("raw_content_list_sha256")
            for payload in (report_payload, source_map):
                if (
                    payload.get("version") != MINERU_NORMALIZATION_VERSION
                    or payload.get("parser") != "mineru"
                    or payload.get("parser_version") != mineru_version
                    or payload.get("source_sha256") != source_sha256
                    or payload.get("raw_content_list_sha256") != raw_hash
                    or payload.get("method") != method
                ):
                    raise ValueError("MinerU 契约或缓存身份不匹配")
            if (
                not isinstance(raw_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", raw_hash)
            ):
                raise ValueError("MinerU content list 哈希无效")
            provider = report_payload.get("provider")
            if provider != "mineru-api-v4":
                raise ValueError("MinerU 解析来源无效")
            if provider == "mineru-api-v4" and (
                not isinstance(report_payload.get("model_version"), str)
                or not report_payload["model_version"]
                or not isinstance(report_payload.get("batch_id"), str)
                or not report_payload["batch_id"]
                or not isinstance(
                    report_payload.get("result_zip_sha256"), str
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}", report_payload["result_zip_sha256"]
                )
            ):
                raise ValueError("MinerU API 解析来源不完整")
            candidates = [
                path
                for path in (parsed_root / "raw").rglob("*_content_list.json")
                if path.is_file() and not path.is_symlink()
            ]
            if len(candidates) != 1:
                raise ValueError("MinerU raw content list 不唯一")
            raw_root = (parsed_root / "raw").resolve()
            if not candidates[0].resolve().is_relative_to(raw_root):
                raise ValueError("MinerU raw content list 越界")
            if hashlib.sha256(candidates[0].read_bytes()).hexdigest() != raw_hash:
                raise ValueError("MinerU raw content list 已变化")

            report = ParseReport.from_dict(report_payload)
            if report.status != "parsed_mineru":
                raise ValueError("MinerU 状态无效")
            blocks = tuple(
                SourceBlock.from_dict(value)
                for value in source_map.get("blocks", [])
            )
            page_counts: dict[int, int] = {}
            previous_page = 0
            for block in blocks:
                if (
                    block.page > report.page_count
                    or block.page < previous_page
                    or block.source_type is None
                    or block.source_index is None
                ):
                    raise ValueError("MinerU 来源块顺序无效")
                previous_page = block.page
                page_counts[block.page] = page_counts.get(block.page, 0) + 1
                expected_id = (
                    f"p{block.page:04d}-m{page_counts[block.page]:04d}"
                )
                if block.block_id != expected_id:
                    raise ValueError("MinerU 来源块 ID 顺序无效")
            if (
                report.block_count != len(blocks)
                or markdown
                != render_mineru_markdown(blocks, report.page_count)
            ):
                raise ValueError("MinerU Markdown 与来源块不一致")

            assets = tuple(
                AssetRecord.from_dict(value)
                for value in report_payload.get("assets", [])
            )
            for asset in assets:
                AssetManifest._validate(asset)
                relative = Path(asset.relative_path).relative_to(
                    "parsed/mineru"
                )
                asset_path = parsed_root / relative
                if (
                    not asset_path.is_file()
                    or asset_path.is_symlink()
                    or not asset_path.resolve().is_relative_to(
                        parsed_root.resolve()
                    )
                ):
                    raise ValueError("MinerU 解析资产缺失")
            if (
                report.image_count
                != sum(asset.kind == "figure" for asset in assets)
                or report.table_count
                != sum(asset.kind == "table" for asset in assets)
            ):
                raise ValueError("MinerU 资产计数不一致")
            if manifest_path is not None:
                manifest_assets = {
                    asset.asset_id: asset
                    for asset in AssetManifest(manifest_path).load()
                }
                for asset in assets:
                    existing = manifest_assets.get(asset.asset_id)
                    if existing is None or existing.to_dict() != asset.to_dict():
                        raise ValueError("manifest 与 MinerU 报告不一致")
            if metadata is not None:
                MineruArtifactValidator._verify_mineru_normalization(
                    parsed_root,
                    source_sha256,
                    method,
                    mineru_version,
                    metadata,
                    assets,
                )
            return report, assets

    @staticmethod

    def _verify_mineru_normalization(
            parsed_root: Path,
            source_sha256: str,
            method: str,
            mineru_version: str,
            metadata: PaperMetadata,
            assets: tuple[AssetRecord, ...],
        ) -> None:
            from .mineru_normalizer import MineruNormalizer

            verification = (
                parsed_root.parent / f".mineru-verify-{uuid.uuid4().hex}"
            )
            try:
                regenerated = MineruNormalizer(mineru_version).normalize(
                    parsed_root / "raw",
                    verification,
                    metadata,
                    source_sha256,
                    materialize_assets=False,
                )
                for name in ("source_map.json", "parse_report.json"):
                    path = verification / name
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["method"] = method
                    atomic_write_json(path, payload)
                for name in ("full.md", "source_map.json"):
                    if (verification / name).read_bytes() != (
                        parsed_root / name
                    ).read_bytes():
                        raise ValueError("MinerU 规范化结果与 raw 不一致")
                stored_report = json.loads(
                    (parsed_root / "parse_report.json").read_text(
                        encoding="utf-8"
                    )
                )
                regenerated_report = json.loads(
                    (verification / "parse_report.json").read_text(
                        encoding="utf-8"
                    )
                )
                for key in (
                    "provider",
                    "model_version",
                    "batch_id",
                    "result_zip_sha256",
                ):
                    stored_report.pop(key, None)
                if regenerated_report != stored_report:
                    raise ValueError("MinerU 规范化结果与 raw 不一致")
                if regenerated.assets != assets:
                    raise ValueError("MinerU 规范化资产索引与 raw 不一致")
                MineruArtifactValidator._verify_mineru_asset_content(
                    parsed_root,
                    assets,
                )
            finally:
                if verification.exists():
                    shutil.rmtree(verification, ignore_errors=True)

    @staticmethod

    def _verify_mineru_asset_content(
            parsed_root: Path,
            assets: tuple[AssetRecord, ...],
        ) -> None:
            from .mineru_models import MineruContentItem

            raw_root = (parsed_root / "raw").resolve()
            candidates = list(raw_root.rglob("*_content_list.json"))
            payload = json.loads(candidates[0].read_text(encoding="utf-8"))
            expected: dict[str, bytes] = {}
            image_counts: dict[int, int] = {}
            table_counts: dict[int, int] = {}
            for index, value in enumerate(payload):
                item = MineruContentItem.from_dict(value, index=index)
                if item.item_type not in {"image", "table"}:
                    continue
                counts = (
                    image_counts
                    if item.item_type == "image"
                    else table_counts
                )
                counts[item.page] = counts.get(item.page, 0) + 1
                suffix = (
                    f"img{counts[item.page]:04d}"
                    if item.item_type == "image"
                    else f"table{counts[item.page]:04d}"
                )
                asset_id = f"mineru-p{item.page:04d}-{suffix}"
                source = (
                    candidates[0].parent / str(item.asset_path)
                ).resolve()
                if (
                    not source.is_relative_to(raw_root)
                    or not source.is_file()
                    or source.is_symlink()
                ):
                    raise ValueError("MinerU raw 资产越界")
                expected[asset_id] = source.read_bytes()
                if item.item_type == "table" and item.table_body:
                    expected[f"{asset_id}-html"] = (
                        item.table_body.rstrip() + "\n"
                    ).encode("utf-8")
            if set(expected) != {asset.asset_id for asset in assets}:
                raise ValueError("MinerU raw 资产索引不一致")
            for asset in assets:
                relative = Path(asset.relative_path).relative_to(
                    "parsed/mineru"
                )
                if (parsed_root / relative).read_bytes() != expected[asset.asset_id]:
                    raise ValueError("MinerU 规范化资产与 raw 不一致")
