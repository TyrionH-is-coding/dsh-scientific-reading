from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from .identifiers import metadata_identity_anchor_found
from .mineru_models import (
    MINERU_NORMALIZATION_VERSION,
    MineruContentItem,
)
from .models import AssetRecord, PaperMetadata
from .parse_models import ParseReport, SourceBlock, assess_quality
from .workspace import atomic_write_json


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def render_mineru_markdown(
    blocks: tuple[SourceBlock, ...] | list[SourceBlock],
    page_count: int,
) -> str:
    by_page: dict[int, list[SourceBlock]] = {}
    for block in blocks:
        by_page.setdefault(block.page, []).append(block)
    parts: list[str] = []
    for page in range(1, page_count + 1):
        parts.append(f"## Page {page}\n")
        for block in by_page.get(page, []):
            parts.append(
                f"<!-- source:{block.block_id} -->\n\n"
                f"{block.text}\n"
            )
    return "\n".join(parts).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class MineruNormalizeResult:
    source_sha256: str
    raw_content_list_sha256: str
    report: ParseReport
    blocks: tuple[SourceBlock, ...]
    assets: tuple[AssetRecord, ...]


class MineruNormalizer:
    def __init__(self, parser_version: str = "3.4.0") -> None:
        if not parser_version.strip():
            raise ValueError("MinerU 版本不能为空")
        self.parser_version = parser_version.strip()

    def normalize(
        self,
        raw_root: Path,
        output_root: Path,
        metadata: PaperMetadata,
        source_sha256: str,
        *,
        materialize_assets: bool = True,
    ) -> MineruNormalizeResult:
        raw = Path(raw_root).resolve()
        output = Path(output_root)
        if (
            len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("source_sha256 无效")
        candidates = [
            path
            for path in raw.rglob("*_content_list.json")
            if path.is_file()
        ]
        if len(candidates) != 1:
            raise ValueError("MinerU 输出必须包含唯一 content list")
        content_path = candidates[0]
        resolved_content = content_path.resolve()
        if not resolved_content.is_relative_to(raw):
            raise ValueError("content list 必须位于 raw 目录内")
        payload = json.loads(resolved_content.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not payload:
            raise ValueError("content list 不能为空")

        items = tuple(
            MineruContentItem.from_dict(value, index=index)
            for index, value in enumerate(payload)
        )
        previous_page = 0
        page_counts: dict[int, int] = {}
        blocks: list[SourceBlock] = []
        assets: list[AssetRecord] = []
        warnings: list[str] = []
        page_characters: dict[int, int] = {}
        first_pages: list[str] = []
        image_counts: dict[int, int] = {}
        table_counts: dict[int, int] = {}
        heading_stack: list[str] = []
        outline_base_level: int | None = None

        output.mkdir(parents=True, exist_ok=True)
        for item in items:
            if item.page < previous_page:
                raise ValueError("content list 页码顺序无效")
            previous_page = item.page
            if (
                item.item_type
                in {
                    "text",
                    "header",
                    "aside_text",
                    "page_number",
                    "page_footnote",
                }
                and item.text is None
            ):
                warnings.append(
                    f"empty_text_item:{item.item_type}:{item.index}"
                )
            if not item.supported:
                warnings.append(
                    f"unsupported_content_type:{item.item_type}:{item.index}"
                )
                continue
            text = self._block_text(item)
            if text is not None:
                heading_level = None
                structure_source = None
                if item.text_level is not None:
                    if self._outline_heading(text, metadata, item.page):
                        if outline_base_level is None:
                            outline_base_level = item.text_level
                        heading_level = max(
                            1,
                            item.text_level - outline_base_level + 1,
                        )
                        structure_source = "mineru_text_level"
                        numbered_level = self._numbered_heading_level(text)
                        if (
                            numbered_level is not None
                            and numbered_level != heading_level
                        ):
                            warnings.append(
                                f"outline_incomplete:{item.index}:level_conflict"
                            )
                            heading_level = numbered_level
                            structure_source = "visible_section_number"
                        if heading_level > len(heading_stack) + 1:
                            warnings.append(
                                f"outline_incomplete:{item.index}:level_{heading_level}"
                            )
                        heading_stack[heading_level - 1 :] = []
                        heading_stack.append(text)
                    else:
                        structure_source = "outline_noise_filtered"
                elif item.item_type == "header" and text != metadata.title:
                    structure_source = "outline_incomplete"
                    warnings.append(
                        f"outline_incomplete:{item.index}:missing_level"
                    )
                page_counts[item.page] = page_counts.get(item.page, 0) + 1
                block = SourceBlock(
                    block_id=(
                        f"p{item.page:04d}-"
                        f"m{page_counts[item.page]:04d}"
                    ),
                    page=item.page,
                    bbox=item.bbox,
                    kind="text",
                    text=text,
                    source_type=item.item_type,
                    source_index=item.index,
                    section_path=tuple(heading_stack),
                    heading_level=heading_level,
                    structure_source=structure_source,
                )
                blocks.append(block)
                page_characters[item.page] = (
                    page_characters.get(item.page, 0) + len(text)
                )
                if item.page <= 3:
                    first_pages.append(text)
            if item.item_type == "image":
                image_counts[item.page] = image_counts.get(item.page, 0) + 1
                asset_id = (
                    f"mineru-p{item.page:04d}-"
                    f"img{image_counts[item.page]:04d}"
                )
                assets.append(
                    self._copy_asset(
                        item,
                        resolved_content.parent,
                        raw,
                        output,
                        asset_id,
                        "images",
                        "figure",
                        materialize_assets,
                    )
                )
            elif item.item_type == "table":
                table_counts[item.page] = table_counts.get(item.page, 0) + 1
                asset_id = (
                    f"mineru-p{item.page:04d}-"
                    f"table{table_counts[item.page]:04d}"
                )
                assets.append(
                    self._copy_asset(
                        item,
                        resolved_content.parent,
                        raw,
                        output,
                        asset_id,
                        "tables",
                        "table",
                        materialize_assets,
                    )
                )
                if item.table_body:
                    html_path = output / "tables" / f"{asset_id}.html"
                    if materialize_assets:
                        _write_text(
                            html_path,
                            item.table_body.rstrip() + "\n",
                        )
                    assets.append(
                        AssetRecord(
                            asset_id=f"{asset_id}-html",
                            kind="table",
                            page=item.page,
                            relative_path=(
                                f"parsed/mineru/tables/{asset_id}.html"
                            ),
                            label="HTML",
                            caption="\n".join(item.caption) or None,
                            source_index=item.index,
                            is_body=item.is_body,
                            is_body_source=item.is_body_source,
                            bbox=item.bbox,
                        )
                    )

        if not blocks:
            raise ValueError("MinerU 输出没有正文块")
        page_count = max(item.page for item in items)
        page_counts_list = [
            page_characters.get(page, 0)
            for page in range(1, page_count + 1)
        ]
        all_text = "\n".join(block.text for block in blocks)
        identity_found = metadata_identity_anchor_found(
            "\n".join(first_pages),
            metadata,
        )
        if not identity_found:
            raise ValueError("MinerU 正文缺少论文身份锚点")
        report = assess_quality(
            page_characters=page_counts_list,
            text=all_text,
            identity_anchor_found=True,
            block_count=len(blocks),
            image_count=sum(asset.kind == "figure" for asset in assets),
            table_count=sum(asset.kind == "table" for asset in assets),
            warnings=warnings,
        )
        report = replace(
            report,
            status="parsed_mineru",
            needs_mineru_reasons=[],
        )
        raw_hash = _sha256(resolved_content)
        source_map = {
            "version": MINERU_NORMALIZATION_VERSION,
            "parser": "mineru",
            "parser_version": self.parser_version,
            "source_sha256": source_sha256,
            "raw_content_list_sha256": raw_hash,
            "blocks": [block.to_dict() for block in blocks],
        }
        report_payload = {
            "version": MINERU_NORMALIZATION_VERSION,
            "parser": "mineru",
            "parser_version": self.parser_version,
            "source_sha256": source_sha256,
            "raw_content_list_sha256": raw_hash,
            **report.to_dict(),
            "assets": [asset.to_dict() for asset in assets],
        }
        atomic_write_json(output / "source_map.json", source_map)
        _write_text(
            output / "full.md",
            render_mineru_markdown(blocks, page_count),
        )
        atomic_write_json(output / "parse_report.json", report_payload)
        return MineruNormalizeResult(
            source_sha256=source_sha256,
            raw_content_list_sha256=raw_hash,
            report=report,
            blocks=tuple(blocks),
            assets=tuple(assets),
        )

    @staticmethod
    def _outline_heading(
        text: str,
        metadata: PaperMetadata,
        page: int,
    ) -> bool:
        normalized = " ".join(text.split()).casefold()
        if normalized == " ".join(metadata.title.split()).casefold():
            return False
        if len(normalized) > 240 or "@" in normalized:
            return False
        if page == 1 and any(
            normalized == " ".join(author.split()).casefold()
            for author in metadata.authors
        ):
            return False
        return sum(character.isalpha() for character in normalized) >= 2

    @staticmethod
    def _numbered_heading_level(text: str) -> int | None:
        match = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.)]|\s+)", text)
        if match is None:
            return None
        return match.group(1).count(".") + 1

    @staticmethod
    def _block_text(item: MineruContentItem) -> str | None:
        if item.item_type in {"text", "header", "aside_text"}:
            return item.text
        if item.item_type == "list":
            return "\n".join(f"- {value}" for value in item.list_items)
        return None

    @staticmethod
    def _copy_asset(
        item: MineruContentItem,
        content_parent: Path,
        raw_root: Path,
        output_root: Path,
        asset_id: str,
        target_folder: str,
        kind: str,
        materialize: bool,
    ) -> AssetRecord:
        source = (content_parent / str(item.asset_path)).resolve()
        if not source.is_relative_to(raw_root) or not source.is_file():
            raise ValueError("MinerU 资产缺失或越出 raw 目录")
        suffix = source.suffix.casefold()
        if not suffix or len(suffix) > 10:
            raise ValueError("MinerU 资产扩展名无效")
        destination = output_root / target_folder / f"{asset_id}{suffix}"
        if materialize:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        structured_path = None
        if kind == "table" and item.structured_reliable:
            structured_source = (
                content_parent / str(item.structured_path)
            ).resolve()
            structured_suffix = structured_source.suffix.casefold()
            if (
                not structured_source.is_relative_to(raw_root)
                or not structured_source.is_file()
                or structured_suffix not in {".csv", ".json"}
                or _sha256(structured_source) != item.structured_sha256
            ):
                raise ValueError("MinerU 结构化表来源无效")
            structured_destination = (
                output_root
                / target_folder
                / f"{asset_id}{structured_suffix}"
            )
            if materialize:
                shutil.copyfile(
                    structured_source, structured_destination
                )
            structured_path = (
                f"parsed/mineru/{target_folder}/"
                f"{asset_id}{structured_suffix}"
            )
        return AssetRecord(
            asset_id=asset_id,
            kind=kind,
            page=item.page,
            relative_path=(
                f"parsed/mineru/{target_folder}/{asset_id}{suffix}"
            ),
            caption="\n".join(item.caption) or None,
            source_index=item.index,
            is_body=item.is_body,
            is_body_source=item.is_body_source,
            bbox=item.bbox,
            source_sha256=_sha256(source),
            structured_reliable=item.structured_reliable,
            structured_path=structured_path,
            structured_sha256=item.structured_sha256,
        )
