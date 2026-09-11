"""把当前 PDF 中的实际图片及可定位原文交给持久文献 chat。"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.parse import quote

from .data_guard import root_operation
from .evidence_locator import _load_current_context
from .export_service import ExportService
from .library_service import _now
from .paper_chat import PaperChatService
from .scope import library_write, require_global


_FIGURE = re.compile(r"(?:\bfig(?:ure)?s?\.?|图)\s*(S?\d+)(?:[a-z](?:\s*[-–]\s*[a-z])?)?(?![\d\w])", re.I)
_MORE = re.compile(r"\s*(?:,|and|&|及|和)\s*(S?\d+)(?:[a-z](?:\s*[-–]\s*[a-z])?)?(?![\d\w])", re.I)


def figure_numbers(text):
    numbers = set()
    for match in _FIGURE.finditer(text):
        numbers.add(match[1].upper())
        position = match.end()
        while more := _MORE.match(text, position):
            numbers.add(more[1].upper())
            position = more.end()
    return numbers


def related_blocks(blocks, caption):
    """明确图号引用优先；相邻段落仅标为上下文，不声称语义关联。"""
    numbers = figure_numbers(caption)
    direct = {i for i, block in enumerate(blocks)
              if block.source_type in {None, "text", "list"} and "-c" not in block.block_id
              and numbers & figure_numbers(block.text)}
    related = {}
    for index in direct:
        related[index] = "explicit_figure_reference"
        for neighbor in (index - 1, index + 1):
            if 0 <= neighbor < len(blocks) and neighbor not in direct:
                block = blocks[neighbor]
                if block.source_type in {None, "text", "list"} and "-c" not in block.block_id and block.section_path == blocks[index].section_path:
                    related.setdefault(neighbor, "adjacent_paragraph")
    ordered = sorted(related, key=lambda i: (i not in direct, i))
    return [(blocks[i], related[i]) for i in ordered], sorted(numbers), len(direct)


class FigureContextService:
    def __init__(self, library):
        self.library = library
        self.conn = library.conn
        self.data_root = library.data_root

    @root_operation
    @library_write
    def select(self, payload):
        require_global("figure_select")
        paper_id, asset_id = payload["paper_id"], payload["asset_id"]
        chat = PaperChatService(self.library).get(paper_id)
        if not chat["session_id"]:
            raise ValueError("paper_chat_missing")
        source = _load_current_context(self.data_root, paper_id)
        if source.source_sha256 != payload.get("source_pdf_sha256"):
            raise ValueError("figure_pdf_changed_reload_reader")
        exported = ExportService().export_for_paper(self.data_root, paper_id)
        manifest = json.loads((exported.exports_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest["source_pdf_sha256"] != source.source_sha256:
            raise ValueError("figure_pdf_changed_reload_reader")
        matches = [row for row in manifest["assets"] if row["asset_id"] == asset_id and row["kind"] == "figure"]
        if len(matches) != 1:
            raise ValueError("figure_asset_unavailable")
        asset = matches[0]
        image_path = exported.exports_dir / asset["export_path"]
        if image_path.is_symlink() or not image_path.resolve().is_relative_to(exported.exports_dir.resolve()):
            raise ValueError("figure_asset_invalid")
        image = image_path.read_bytes()
        if hashlib.sha256(image).hexdigest() != asset["export_sha256"] or not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("figure_image_invalid")
        text_only = payload.get("text_only", False)
        if not isinstance(text_only, bool):
            raise ValueError("figure_text_only_invalid")
        if len(image) > 20 * 1024 * 1024 and not text_only:
            raise ValueError("figure_image_too_large_choose_text_only")
        rows, numbers, reference_count = related_blocks(source.blocks, asset.get("caption") or "")
        base_url = f"/sr/api/paper/{quote(paper_id, safe='')}/"
        passages = []
        used = 0
        for block, relation in rows[:24]:
            text = block.text[:min(2400, 18000 - used)]
            if not text:
                break
            used += len(text)
            passages.append({"block_id": block.block_id, "page": block.page, "text": text,
                             "relation": relation, "section_path": list(block.section_path),
                             "truncated": len(text) < len(block.text),
                             "reader_url": "/sr/reader/" + quote(paper_id, safe='') + "#block-" + quote(block.block_id, safe=''),
                             "pdf_url": base_url + f"pdf#page={block.page}"})
        context = {"paper_id": paper_id, "asset_id": asset_id, "page": asset["page"],
                   "source_pdf_sha256": source.source_sha256, "generation": source.generation,
                   "source_map_sha256": source.source_map_sha256,
                   "image_sha256": asset["export_sha256"], "source_image_sha256": asset["source_sha256"],
                   "caption": asset.get("caption") or "", "figure_numbers": numbers,
                   "passages": passages, "explicit_reference_count": reference_count,
                   "omitted_passage_count": len(rows) - len(passages),
                   "pdf_url": base_url + f"pdf#page={asset['page']}",
                   "image_status": "text_only_not_supplied" if text_only else "pending_delivery",
                   "selected_at": _now(), "warnings": list(asset.get("warnings", [])),
                   "instructions": "当前 Figure 取代之前选择。回答标明图片直接可见事实、作者图注/正文结论和你的推断；正文的相邻段落仅为上下文。图片未收到时不能描述图像内容。引用必须注明页码、block_id 和来源链接。多子图分开说明；不凭图号补全缺失子图或跨页图片。"}
        if not reference_count:
            context["warnings"].append("no_explicit_body_reference")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            revision = self.conn.execute("SELECT context_revision FROM paper_chats WHERE paper_id=?", (paper_id,)).fetchone()[0]
            if payload.get("expected_revision", revision) != revision:
                raise ValueError("figure_context_changed")
            context["revision"] = revision + 1
            self.conn.execute("UPDATE paper_chats SET context_json=?,context_revision=?,updated_at=? WHERE paper_id=?",
                              (json.dumps(context, ensure_ascii=False), revision + 1, _now(), paper_id))
        return {"session_id": chat["session_id"], "context": context,
                "image": None if text_only else {"type": "image", "mediaType": "image/png", "data": base64.b64encode(image).decode("ascii"), "name": asset_id + ".png"}}

    @root_operation
    @library_write
    def delivered(self, payload):
        require_global("figure_receipt")
        self.library.get_item(payload["paper_id"])
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute("SELECT context_json,context_revision FROM paper_chats WHERE paper_id=?", (payload["paper_id"],)).fetchone()
            if not row or row[1] != payload["revision"]:
                raise ValueError("figure_context_changed")
            context = json.loads(row[0])
            context["image_status"] = "supplied_to_native_chat" if payload["image_supplied"] else "text_only_not_supplied"
            self.conn.execute("UPDATE paper_chats SET context_json=? WHERE paper_id=?", (json.dumps(context, ensure_ascii=False), payload["paper_id"]))
        return context
