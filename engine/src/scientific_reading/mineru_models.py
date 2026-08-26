from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Any


MINERU_NORMALIZATION_VERSION = "mineru-normalization-v3"
_KNOWN_TYPES = {
    "text",
    "header",
    "aside_text",
    "list",
    "image",
    "table",
    "page_number",
    "page_footnote",
}
_TEXT_TYPES = {"text", "header", "aside_text", "page_number", "page_footnote"}


def _clean_strings(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{name} 必须是列表")
    result = tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if len(result) != len(value):
        raise ValueError(f"{name} 包含非文本值")
    return result


def _relative_asset_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("img_path 不能为空")
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
        raise ValueError("img_path 必须位于 MinerU 输出目录内")
    return posix.as_posix()


@dataclass(frozen=True, slots=True)
class MineruContentItem:
    index: int
    item_type: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str | None = None
    text_level: int | None = None
    asset_path: str | None = None
    caption: tuple[str, ...] = ()
    footnote: tuple[str, ...] = ()
    table_body: str | None = None
    list_items: tuple[str, ...] = ()
    supported: bool = True
    is_body: bool = True
    is_body_source: str = "mineru_candidate_default"
    structured_reliable: bool = False
    structured_path: str | None = None
    structured_sha256: str | None = None

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        index: int,
    ) -> MineruContentItem:
        if not isinstance(value, dict):
            raise ValueError("content item 必须是对象")
        item_type = value.get("type")
        if not isinstance(item_type, str) or not item_type.strip():
            raise ValueError("type 不能为空")
        item_type = item_type.strip()
        page_idx = value.get("page_idx")
        if (
            isinstance(page_idx, bool)
            or not isinstance(page_idx, int)
            or page_idx < 0
        ):
            raise ValueError("page_idx 必须是非负整数")
        raw_bbox = value.get("bbox")
        if (
            not isinstance(raw_bbox, list)
            or len(raw_bbox) != 4
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in raw_bbox
            )
        ):
            raise ValueError("bbox 必须包含四个有限数字")
        bbox = tuple(float(item) for item in raw_bbox)

        text = None
        if item_type in _TEXT_TYPES:
            raw_text = value.get("text")
            if not isinstance(raw_text, str):
                raise ValueError("text 不能为空")
            text = raw_text.strip() or None

        asset_path = None
        caption: tuple[str, ...] = ()
        footnote: tuple[str, ...] = ()
        table_body = None
        if item_type in {"image", "table"}:
            asset_path = _relative_asset_path(value.get("img_path"))
            prefix = "image" if item_type == "image" else "table"
            caption = _clean_strings(
                value.get(f"{prefix}_caption", []),
                f"{prefix}_caption",
            )
            footnote = _clean_strings(
                value.get(f"{prefix}_footnote", []),
                f"{prefix}_footnote",
            )
            if item_type == "table":
                raw_body = value.get("table_body")
                if raw_body is not None and not isinstance(raw_body, str):
                    raise ValueError("table_body 必须是文本")
                table_body = raw_body.strip() if raw_body else None

        structured_reliable = value.get("structured_reliable") is True
        structured_path = None
        structured_sha256 = None
        if structured_reliable:
            structured_path = _relative_asset_path(
                value.get("structured_path")
            )
            structured_sha256 = value.get("structured_sha256")
            if not isinstance(structured_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", structured_sha256
            ):
                raise ValueError("structured_sha256 无效")

        list_items: tuple[str, ...] = ()
        if item_type == "list":
            list_items = _clean_strings(
                value.get("list_items"),
                "list_items",
            )
            if not list_items:
                raise ValueError("list_items 不能为空")

        text_level = value.get("text_level")
        if text_level is not None and (
            isinstance(text_level, bool)
            or not isinstance(text_level, int)
            or text_level < 1
        ):
            raise ValueError("text_level 无效")
        return cls(
            index=index,
            item_type=item_type,
            page=page_idx + 1,
            bbox=bbox,
            text=text,
            text_level=text_level,
            asset_path=asset_path,
            caption=caption,
            footnote=footnote,
            table_body=table_body,
            list_items=list_items,
            supported=item_type in _KNOWN_TYPES,
            is_body=(
                value["is_body"]
                if isinstance(value.get("is_body"), bool)
                else True
            ),
            is_body_source=(
                "raw_explicit"
                if isinstance(value.get("is_body"), bool)
                else "mineru_candidate_default"
            ),
            structured_reliable=structured_reliable,
            structured_path=structured_path,
            structured_sha256=structured_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.item_type,
            "page": self.page,
            "bbox": list(self.bbox),
            "text": self.text,
            "text_level": self.text_level,
            "asset_path": self.asset_path,
            "caption": list(self.caption),
            "footnote": list(self.footnote),
            "table_body": self.table_body,
            "list_items": list(self.list_items),
            "supported": self.supported,
        }
