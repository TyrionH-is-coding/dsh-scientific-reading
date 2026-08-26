from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .abstract_read_models import ABSTRACT_TRANSLATION_CONTRACT_VERSION
from .library_service import LibraryService
from .models import PaperMetadata
from .workspace import PaperWorkspace, atomic_write_json


class AbstractReadValidationError(ValueError):
    pass


class _ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.parts: list[str] = []; self.breaks: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "section", "br", "li"}: self.parts.append("\n\n")
    def handle_endtag(self, tag):
        if tag in {"p", "div", "section", "li"}: self.parts.append("\n\n")
    def handle_data(self, data): self.parts.append(data)


def normalize_abstract(value: str) -> str:
    value = html.unescape(value)
    parser = _ParagraphParser(); parser.feed(value)
    text = "".join(parser.parts) if "<" in value else value
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return "\n\n".join(part.strip() for part in re.split(r"(?:\r?\n){2,}", text) if part.strip())


class AbstractReadService:
    def inspect(self, workspace: PaperWorkspace) -> dict[str, Any]:
        metadata = PaperMetadata.from_dict(json.loads(workspace.metadata_path.read_text(encoding="utf-8")))
        if not metadata.abstract_en or not metadata.abstract_en.strip():
            return {"status": "missing", "contract_version": ABSTRACT_TRANSLATION_CONTRACT_VERSION, "paragraphs": []}
        source = normalize_abstract(metadata.abstract_en)
        paragraphs = [{"index": i, "source_en": part, "translation_zh": ""} for i, part in enumerate(source.split("\n\n"))]
        sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
        path = workspace.reading_dir / "abstract_read.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        stale = existing is not None and existing.get("source_sha256") != sha
        if existing is not None and not stale:
            return {"status": "published", **existing}
        return {"status": "stale" if stale else "ready", "contract_version": ABSTRACT_TRANSLATION_CONTRACT_VERSION, "source_sha256": sha, "paragraphs": paragraphs}

    def publish(self, workspace: PaperWorkspace, payload: dict[str, Any]) -> dict[str, Any]:
        context = self.inspect(workspace)
        if context["status"] == "missing": raise AbstractReadValidationError("abstract_missing")
        if payload.get("contract_version") != ABSTRACT_TRANSLATION_CONTRACT_VERSION: raise AbstractReadValidationError("contract_version")
        if payload.get("source_sha256") != context["source_sha256"]: raise AbstractReadValidationError("source_sha256")
        paragraphs = payload.get("paragraphs")
        expected = context["paragraphs"]
        if not isinstance(paragraphs, list) or [p.get("index") for p in paragraphs] != list(range(len(expected))): raise AbstractReadValidationError("paragraph_indices")
        for actual, source in zip(paragraphs, expected):
            if actual.get("source_en") != source["source_en"]: raise AbstractReadValidationError("source_en")
            if not isinstance(actual.get("translation_zh"), str) or not actual["translation_zh"].strip(): raise AbstractReadValidationError("translation_zh")
        output = {"contract_version": ABSTRACT_TRANSLATION_CONTRACT_VERSION, "source_sha256": context["source_sha256"], "paragraphs": paragraphs}
        atomic_write_json(workspace.reading_dir / "abstract_read.json", output)
        metadata = PaperMetadata.from_dict(json.loads(workspace.metadata_path.read_text(encoding="utf-8")))
        metadata.abstract_zh = "\n\n".join(p["translation_zh"] for p in paragraphs)
        atomic_write_json(workspace.metadata_path, metadata.to_dict())
        library = LibraryService(workspace.root.parents[1]);
        try: library.ingest(metadata)
        finally: library.close()
        return {"status": "abstract_read_ready", "path": str(workspace.reading_dir / "abstract_read.json")}
