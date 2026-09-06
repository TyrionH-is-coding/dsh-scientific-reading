from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .export_service import ExportService
from .full_read_service import FullReadError, FullReadService
from .models import PaperMetadata
from .package_manifest import validate_generation_package_manifest
from .parse_models import SourceBlock
from .workspace import PaperWorkspace


LOCATOR_CONTRACT = "evidence-locator-v1"
_LOCATOR_KEYS = {
    "contract",
    "paper_id",
    "source_sha256",
    "generation",
    "source_map_sha256",
    "block_id",
    "page",
    "quote",
}
_PAPER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_QUOTE_LENGTH = 500


class EvidenceLocatorError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _SourceContext:
    generation: str
    source_sha256: str
    source_map_sha256: str
    blocks: tuple[SourceBlock, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_paper_id(paper_id: object) -> str:
    if (
        not isinstance(paper_id, str)
        or _PAPER_ID.fullmatch(paper_id) is None
        or ".." in paper_id
    ):
        raise EvidenceLocatorError("paper_id_invalid")
    return paper_id


def _block_ids(source_map_path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(source_map_path.read_text(encoding="utf-8"))
        rows = payload["blocks"]
        if not isinstance(rows, list):
            raise ValueError
        identifiers = tuple(
            row["block_id"]
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("block_id"), str)
        )
        if len(identifiers) != len(rows):
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise EvidenceLocatorError("source_map_invalid") from error
    if len(set(identifiers)) != len(identifiers):
        raise EvidenceLocatorError("block_id_ambiguous")
    return identifiers


def _load_current_context(
    data_root: Path,
    paper_id: str,
) -> _SourceContext:
    paper_id = _validate_paper_id(paper_id)
    root = Path(data_root).resolve()
    paper_root = (root / "papers" / paper_id).resolve()
    if not paper_root.is_relative_to(root):
        raise EvidenceLocatorError("paper_id_invalid")
    try:
        metadata = PaperMetadata.from_dict(
            json.loads(
                (paper_root / "metadata.json").read_text(encoding="utf-8")
            )
        )
        base = PaperWorkspace(paper_root)
        selected, source_sha256, _method, _version = (
            ExportService._active_workspace(base, metadata)
        )
        generation = selected.root.relative_to(paper_root).as_posix()
        expected_generation = f"generations/{source_sha256[:16]}"
        if generation != expected_generation:
            raise EvidenceLocatorError("active_generation_required")

        from .__main__ import _resolve_artifact

        pdf = _resolve_artifact(root, paper_id, "pdf")
        if (
            pdf.get("sha256") != source_sha256
            or pdf.get("rel_path") != f"{generation}/source.pdf"
        ):
            raise EvidenceLocatorError("source_asset_invalid")
        validate_generation_package_manifest(selected, required=False)
        source_map_path = selected.parsed_dir / "mineru" / "source_map.json"
        _block_ids(source_map_path)
        active = FullReadService._inspect_active_mineru(selected)
        if active.source_sha256 != source_sha256:
            raise EvidenceLocatorError("source_asset_invalid")
    except EvidenceLocatorError:
        raise
    except FullReadError as error:
        raise EvidenceLocatorError("source_map_invalid") from error
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise EvidenceLocatorError("source_asset_invalid") from error
    return _SourceContext(
        generation=generation,
        source_sha256=source_sha256,
        source_map_sha256=active.source_map_sha256,
        blocks=active.blocks,
    )


def _find_block(
    blocks: tuple[SourceBlock, ...],
    block_id: str,
) -> SourceBlock:
    matches = [block for block in blocks if block.block_id == block_id]
    if not matches:
        raise EvidenceLocatorError("block_not_found")
    if len(matches) != 1:
        raise EvidenceLocatorError("block_id_ambiguous")
    return matches[0]


def _quote_positions(text: str, quote: str) -> tuple[int, ...]:
    positions: list[int] = []
    start = 0
    while True:
        found = text.find(quote, start)
        if found < 0:
            return tuple(positions)
        positions.append(found)
        start = found + 1


def _validate_quote(block: SourceBlock, quote: object) -> tuple[str, int]:
    if not isinstance(quote, str) or not quote:
        raise EvidenceLocatorError("quote_invalid")
    if len(quote) > _MAX_QUOTE_LENGTH:
        raise EvidenceLocatorError("quote_too_long")
    positions = _quote_positions(block.text, quote)
    if not positions:
        raise EvidenceLocatorError("quote_not_found")
    if len(positions) != 1:
        raise EvidenceLocatorError("ambiguous_quote")
    return quote, positions[0]


def build_locator(
    data_root: Path,
    paper_id: str,
    block_id: str,
    quote: str,
    *,
    page: int | None = None,
) -> dict[str, Any]:
    context = _load_current_context(Path(data_root), paper_id)
    if not isinstance(block_id, str) or not block_id:
        raise EvidenceLocatorError("block_id_invalid")
    block = _find_block(context.blocks, block_id)
    if page is not None and (
        isinstance(page, bool) or not isinstance(page, int) or page != block.page
    ):
        raise EvidenceLocatorError("page_mismatch")
    quote, _position = _validate_quote(block, quote)
    return {
        "contract": LOCATOR_CONTRACT,
        "paper_id": paper_id,
        "source_sha256": context.source_sha256,
        "generation": context.generation,
        "source_map_sha256": context.source_map_sha256,
        "block_id": block.block_id,
        "page": block.page,
        "quote": quote,
    }


def _validate_locator(locator: object) -> dict[str, Any]:
    if not isinstance(locator, dict) or set(locator) != _LOCATOR_KEYS:
        raise EvidenceLocatorError("locator_invalid")
    source_sha256 = locator.get("source_sha256")
    source_map_sha256 = locator.get("source_map_sha256")
    generation = locator.get("generation")
    page = locator.get("page")
    quote = locator.get("quote")
    if isinstance(quote, str) and len(quote) > _MAX_QUOTE_LENGTH:
        raise EvidenceLocatorError("quote_too_long")
    if (
        locator.get("contract") != LOCATOR_CONTRACT
        or not isinstance(source_sha256, str)
        or _SHA256.fullmatch(source_sha256) is None
        or not isinstance(source_map_sha256, str)
        or _SHA256.fullmatch(source_map_sha256) is None
        or generation != f"generations/{source_sha256[:16]}"
        or not isinstance(locator.get("block_id"), str)
        or not locator["block_id"]
        or isinstance(page, bool)
        or not isinstance(page, int)
        or page < 1
        or not isinstance(quote, str)
        or not quote
    ):
        raise EvidenceLocatorError("locator_invalid")
    _validate_paper_id(locator.get("paper_id"))
    return locator


def _reject_changed_bound_files(
    data_root: Path,
    paper_id: str,
    locator: dict[str, Any],
) -> None:
    root = Path(data_root).resolve()
    paper_root = root / "papers" / paper_id
    generation_root = paper_root / Path(locator["generation"])
    current = root
    for part in ("papers", paper_id, *Path(locator["generation"]).parts):
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)
        if current.is_symlink() or is_junction():
            raise EvidenceLocatorError("locator_invalid")
    resolved_generation = generation_root.resolve()
    if (
        not resolved_generation.is_relative_to(root)
        or resolved_generation.parent != paper_root.resolve() / "generations"
    ):
        raise EvidenceLocatorError("locator_invalid")
    source_pdf = generation_root / "source.pdf"
    if (
        source_pdf.is_symlink()
        or not source_pdf.is_file()
        or _sha256(source_pdf) != locator["source_sha256"]
    ):
        raise EvidenceLocatorError("source_changed")
    source_map = generation_root / "parsed" / "mineru" / "source_map.json"
    if (
        source_map.is_symlink()
        or not source_map.is_file()
        or _sha256(source_map) != locator["source_map_sha256"]
    ):
        raise EvidenceLocatorError("source_map_changed")


class _ReaderAnchorParser(HTMLParser):
    def __init__(self, block_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.block_id = block_id
        self.target_id = f"block-{block_id}"
        self.target_count = 0
        self.scroll_anchor_count = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id") != self.target_id:
            return
        self.target_count += 1
        classes = (values.get("class") or "").split()
        if (
            tag == "section"
            and "reading-block" in classes
            and values.get("data-block") == self.block_id
        ):
            self.scroll_anchor_count += 1


def _reader_link(
    data_root: Path,
    paper_id: str,
    block_id: str,
) -> dict[str, Any]:
    try:
        from .__main__ import _resolve_artifact

        artifact = _resolve_artifact(data_root, paper_id, "reader")
        manifest = artifact["manifest"]
        matches = [
            row
            for row in manifest.get("source_blocks", [])
            if isinstance(row, dict) and row.get("block_id") == block_id
        ]
        relative = artifact["rel_path"]
        if not isinstance(relative, str):
            raise ValueError
        paper_root = (Path(data_root).resolve() / "papers" / paper_id).resolve()
        reader_path = paper_root / relative
        resolved_reader = reader_path.resolve()
        if (
            reader_path.is_symlink()
            or not resolved_reader.is_relative_to(paper_root)
            or not resolved_reader.is_file()
        ):
            raise ValueError
        content = resolved_reader.read_bytes()
        expected_sha = manifest.get("reader_sha256")
        if not isinstance(expected_sha, str) or hashlib.sha256(
            content
        ).hexdigest() != expected_sha:
            raise ValueError
        parser = _ReaderAnchorParser(block_id)
        parser.feed(content.decode("utf-8"))
        available = (
            len(matches) == 1
            and parser.target_count == 1
            and parser.scroll_anchor_count == 1
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        available = False
    return {
        "artifact_kind": "reader",
        "available": available,
        "fragment": f"block-{block_id}" if available else None,
        "block_id": block_id,
    }


def _source_fragment(text: str, quote: str, position: int) -> tuple[str, int]:
    start = max(0, position - 160)
    end = min(len(text), position + len(quote) + 160)
    return text[start:end], position - start


def resolve_locator(
    data_root: Path,
    paper_id: str,
    locator: dict[str, Any],
) -> dict[str, Any]:
    paper_id = _validate_paper_id(paper_id)
    locator = _validate_locator(locator)
    if locator["paper_id"] != paper_id:
        raise EvidenceLocatorError("paper_id_mismatch")
    _reject_changed_bound_files(Path(data_root), paper_id, locator)
    context = _load_current_context(Path(data_root), paper_id)
    if context.source_sha256 != locator["source_sha256"]:
        raise EvidenceLocatorError("source_changed")
    if context.generation != locator["generation"]:
        raise EvidenceLocatorError("generation_changed")
    if context.source_map_sha256 != locator["source_map_sha256"]:
        raise EvidenceLocatorError("source_map_changed")

    block = _find_block(context.blocks, locator["block_id"])
    if block.page != locator["page"]:
        raise EvidenceLocatorError("page_mismatch")
    quote, position = _validate_quote(block, locator["quote"])
    quote_match_count = sum(
        len(_quote_positions(candidate.text, quote))
        for candidate in context.blocks
    )
    fragment, quote_start = _source_fragment(block.text, quote, position)
    source: dict[str, Any] = {
        "paper_id": paper_id,
        "source_sha256": context.source_sha256,
        "generation": context.generation,
        "source_map_sha256": context.source_map_sha256,
        "block_id": block.block_id,
        "page": block.page,
        "bbox": list(block.bbox),
        "source_type": block.source_type,
        "source_index": block.source_index,
        "fragment": fragment,
        "quote_start": quote_start,
        "quote_end": quote_start + len(quote),
        "quote_match_count": quote_match_count,
        "quote_ambiguous": quote_match_count > 1,
    }
    if quote_match_count > 1:
        source["disambiguated_by"] = "block_id"
    return {
        "status": "resolved",
        "locator": dict(locator),
        "source": source,
        "links": {
            "reader": _reader_link(Path(data_root), paper_id, block.block_id),
            "pdf": {
                "artifact_kind": "pdf",
                "available": True,
                "fragment": f"page={block.page}",
                "page": block.page,
            },
        },
    }
