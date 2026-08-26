from __future__ import annotations

import math
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


PARSE_STATUSES = {"parsed_fast", "needs_mineru", "parsed_mineru"}


@dataclass(frozen=True, slots=True)
class SourceBlock:
    block_id: str
    page: int
    bbox: tuple[float, float, float, float]
    kind: str
    text: str
    source_type: str | None = None
    source_index: int | None = None
    section_path: tuple[str, ...] = ()
    heading_level: int | None = None
    structure_source: str | None = None

    def __post_init__(self) -> None:
        if not self.block_id.strip():
            raise ValueError("block_id 不能为空")
        if self.page < 1:
            raise ValueError("page 必须大于零")
        if len(self.bbox) != 4 or not all(
            math.isfinite(value) for value in self.bbox
        ):
            raise ValueError("bbox 必须包含四个有限数字")
        if self.kind != "text":
            raise ValueError("当前只支持 text 来源块")
        if not self.text.strip():
            raise ValueError("text 不能为空")
        if self.source_type is not None and not self.source_type.strip():
            raise ValueError("source_type 不能为空")
        if self.source_index is not None and self.source_index < 0:
            raise ValueError("source_index 不能为负数")
        if any(not item.strip() for item in self.section_path):
            raise ValueError("section_path 包含空标题")
        if self.heading_level is not None and self.heading_level < 1:
            raise ValueError("heading_level 必须大于零")
        if self.structure_source is not None and not self.structure_source.strip():
            raise ValueError("structure_source 不能为空")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["bbox"] = list(self.bbox)
        if self.source_type is None:
            value.pop("source_type")
        if self.source_index is None:
            value.pop("source_index")
        value["section_path"] = list(self.section_path)
        if self.heading_level is None:
            value.pop("heading_level")
        if self.structure_source is None:
            value.pop("structure_source")
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SourceBlock:
        try:
            bbox = tuple(float(item) for item in value["bbox"])
            return cls(
                block_id=str(value["block_id"]),
                page=int(value["page"]),
                bbox=bbox,
                kind=str(value["kind"]),
                text=str(value["text"]),
                source_type=(
                    str(value["source_type"])
                    if value.get("source_type") is not None
                    else None
                ),
                source_index=(
                    int(value["source_index"])
                    if value.get("source_index") is not None
                    else None
                ),
                section_path=tuple(
                    str(item)
                    for item in value.get("section_path", [])
                ),
                heading_level=(
                    int(value["heading_level"])
                    if value.get("heading_level") is not None
                    else None
                ),
                structure_source=(
                    str(value["structure_source"])
                    if value.get("structure_source") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("来源块无效") from error


@dataclass(frozen=True, slots=True)
class ParseReport:
    status: str
    page_count: int
    total_characters: int
    page_characters: list[int]
    empty_pages: list[int]
    low_text_pages: list[int]
    suspicious_character_ratio: float
    identity_anchor_found: bool
    block_count: int
    image_count: int
    table_count: int
    warnings: list[str]
    needs_mineru_reasons: list[str]

    def __post_init__(self) -> None:
        if self.status not in PARSE_STATUSES:
            raise ValueError("解析状态无效")
        counts = (
            self.page_count,
            self.total_characters,
            self.block_count,
            self.image_count,
            self.table_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("解析计数不能为负数")
        if len(self.page_characters) != self.page_count:
            raise ValueError("逐页字符数与页数不一致")
        if any(value < 0 for value in self.page_characters):
            raise ValueError("逐页字符数不能为负数")
        if not 0 <= self.suspicious_character_ratio <= 1:
            raise ValueError("异常字符比例无效")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ParseReport:
        try:
            return cls(
                status=str(value["status"]),
                page_count=int(value["page_count"]),
                total_characters=int(value["total_characters"]),
                page_characters=[
                    int(item) for item in value["page_characters"]
                ],
                empty_pages=[int(item) for item in value["empty_pages"]],
                low_text_pages=[
                    int(item) for item in value["low_text_pages"]
                ],
                suspicious_character_ratio=float(
                    value["suspicious_character_ratio"]
                ),
                identity_anchor_found=bool(
                    value["identity_anchor_found"]
                ),
                block_count=int(value["block_count"]),
                image_count=int(value["image_count"]),
                table_count=int(value["table_count"]),
                warnings=[str(item) for item in value["warnings"]],
                needs_mineru_reasons=[
                    str(item)
                    for item in value["needs_mineru_reasons"]
                ],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("解析报告无效") from error


def _suspicious_character_count(text: str) -> int:
    return sum(
        character == "\ufffd"
        or (
            unicodedata.category(character).startswith("C")
            and character not in "\n\r\t"
        )
        for character in text
    )


def assess_quality(
    *,
    page_characters: list[int],
    text: str,
    identity_anchor_found: bool,
    block_count: int,
    image_count: int,
    table_count: int,
    warnings: list[str] | None = None,
) -> ParseReport:
    empty_pages = [
        index
        for index, count in enumerate(page_characters, start=1)
        if count == 0
    ]
    low_text_pages = [
        index
        for index, count in enumerate(page_characters, start=1)
        if count < 80
    ]
    suspicious_ratio = (
        _suspicious_character_count(text) / len(text) if text else 0.0
    )
    reasons: list[str] = []
    if not text.strip():
        reasons.append("no_text")
    if (
        len(low_text_pages) >= 2
        and len(low_text_pages) / max(len(page_characters), 1) > 0.2
    ):
        reasons.append("sparse_pages")
    if suspicious_ratio > 0.01:
        reasons.append("suspicious_characters")
    if not identity_anchor_found:
        reasons.append("identity_anchor_missing")
    return ParseReport(
        status="needs_mineru" if reasons else "parsed_fast",
        page_count=len(page_characters),
        total_characters=sum(page_characters),
        page_characters=list(page_characters),
        empty_pages=empty_pages,
        low_text_pages=low_text_pages,
        suspicious_character_ratio=suspicious_ratio,
        identity_anchor_found=identity_anchor_found,
        block_count=block_count,
        image_count=image_count,
        table_count=table_count,
        warnings=list(warnings or []),
        needs_mineru_reasons=reasons,
    )
