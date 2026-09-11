"""从已验证的 Reader 提取选区及相邻原文，客户端不能替换论文内容。"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .reader_appearance import render


def text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def context(library, payload):
    paper_id = payload["paper_id"]
    view = render(library, {"paper_id": paper_id})
    soup = BeautifulSoup(view["html"], "html.parser")
    sha = soup.body.get("data-source-pdf-sha256")
    if not sha or payload.get("source_pdf_sha256") != sha:
        raise ValueError("reader_source_changed")
    rows = []
    for block in soup.select("article .reading-block[data-block]"):
        rows.append({"block_id": block["data-block"], "anchor": block.get("id", ""),
                     "source_en": text(block.select_one(".source-primary")),
                     "translation_zh": text(block.select_one(".translation-panel"))})
    selected = payload.get("selection") or {}
    ids, quote = selected.get("block_ids", []), selected.get("quote", "")
    if not isinstance(ids, list) or len(ids) > 12 or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("reader_selection_invalid")
    if not isinstance(quote, str) or len(quote) > 8000 or bool(ids) != bool(quote.strip()):
        raise ValueError("reader_selection_invalid")
    indexes = [index for index, row in enumerate(rows) if row["block_id"] in ids]
    if ids:
        if [rows[index]["block_id"] for index in indexes] != ids:
            raise ValueError("reader_selection_changed")
        normalized = " ".join(quote.split())
        if not any(normalized in " ".join(rows[index][field] for index in indexes)
                   for field in ("source_en", "translation_zh")):
            raise ValueError("reader_selection_changed")
        indexes = sorted({neighbor for index in indexes for neighbor in (index - 1, index, index + 1)
                          if 0 <= neighbor < len(rows)})
    else:
        # 无选区时提供导读及与问题字面相符的段落；明确不等于读取全部论文。
        terms = set(re.findall(r"[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,8}", str(payload.get("question", "")).lower()))
        scored = sorted(range(len(rows)), key=lambda index: -sum(term in
                        (rows[index]["source_en"] + rows[index]["translation_zh"]).lower() for term in terms))
        indexes = sorted(scored[:6])
    passages = [rows[index] for index in indexes]
    if sum(len(row["source_en"]) + len(row["translation_zh"]) for row in passages) > 60000:
        raise ValueError("reader_selection_too_large")
    item = library.get_item(paper_id)
    return {"paper_id": paper_id, "title": item["title"], "source_pdf_sha256": sha,
            "reader_sha256": view["base_sha256"], "quote": quote, "passages": passages,
            "guide": text(soup.select_one(".guide"))[:8000],
            "abstract_en": (item.get("abstract_en") or "")[:12000],
            "evidence_scope": "仅提供下列原文、译文和摘要；未读取全文其他段落或任何图像。"}
