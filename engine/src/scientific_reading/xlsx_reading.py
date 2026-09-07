"""复用已发布导读和已确认结论；不给工作簿生成新的科学判断。"""

from .library_service import LibraryService
from .review_service import ReviewService


def reading_records(service):
    library = LibraryService(service.data_root)
    review = ReviewService(service.data_root)
    records = []
    try:
        papers = list(library.conn.execute(
            "SELECT i.paper_id,i.title,a.rel_path FROM items i LEFT JOIN artifacts a "
            "ON a.paper_id=i.paper_id AND a.kind='reader' AND a.status='ready' ORDER BY i.created_at,i.paper_id"
        ))
        readers = {}
        for paper_id, title, relative in papers:
            if not relative:
                continue
            try:
                library.validate_reader(paper_id, relative)
            except (OSError, ValueError):
                continue
            readers[paper_id] = relative
            root = service.data_root / "papers" / paper_id
            manifest = service._load_json((root / relative).with_name("reader-manifest.json"))
            guide = manifest.get("review", {}).get("guide", {})
            for category, label in (("research_question", "研究问题"), ("key_methods", "方法"),
                                    ("core_results", "关键结论"), ("limitations", "局限")):
                for index, entry in enumerate(guide.get(category, [])):
                    blocks = entry["source_block_ids"]
                    records.append({"文献名": title, "记录类别": label, "内容": entry["text"],
                                    "依据类型": "AI 导读", "确认状态": "待核对", "证据位置": "、".join(blocks),
                                    "打开原文": f"{relative}#block-{blocks[0]}", "更新时间": manifest.get("generated_at", ""),
                                    "文献 ID": paper_id, "记录 ID": f"guide:{manifest.get('reader_revision')}:{category}:{index}",
                                    "block_ids": blocks, "current": True})
        titles = {row[0]: row[1] for row in papers}
        for row in review.conn.execute("SELECT * FROM review_conclusions ORDER BY confirmed_at,conclusion_id"):
            resolved = review._resolved_conclusion(row)
            evidence = resolved.get("evidence") or {}
            current = resolved["evidence_status"] == "location_verified"
            block = evidence.get("block_id")
            link = (resolved.get("links") or {}).get("reader", {})
            relative = readers.get(row["paper_id"])
            target = f"{relative}#{link['fragment']}" if relative and link.get("available") else ""
            statuses = {"location_verified": "已确认 · 可定位", "stale": "已确认 · 证据需复核",
                        "legacy_unverified": "历史确认 · 证据未核对", "not_provided": "已确认 · 未提供原文证据"}
            records.append({"文献名": titles.get(row["paper_id"], row["paper_id"]), "记录类别": row["conclusion_type"],
                            "内容": row["conclusion_text"], "依据类型": {"paper": "原文依据", "personal": "个人判断",
                            "inference": "推论", "question": "待解决问题", "legacy": "历史记录"}.get(row["basis"], row["basis"]),
                            "确认状态": statuses[resolved["evidence_status"]], "证据位置": row["evidence_locator"] or (block or "未提供"),
                            "打开原文": target, "更新时间": row["confirmed_at"], "文献 ID": row["paper_id"],
                            "记录 ID": row["conclusion_id"], "block_ids": [block] if block else [], "current": current})
        return records
    finally:
        library.close()
        review.close()
