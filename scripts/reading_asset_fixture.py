"""整库恢复、定位和检索共用的离线合成验收样本。"""

import hashlib
import json
from pathlib import Path

from scientific_reading.background_models import BackgroundRequest
from scientific_reading.background_store import BackgroundJobStore
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.library_service import LibraryService
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.review_service import ReviewService
from scientific_reading.workspace import PaperWorkspace, atomic_write_json
from scripts.reader_review_fixtures import (
    FIXTURE_METHOD, FIXTURE_PARSER_VERSION, fixture_path, materialize_fixture_payload,
)


def seed_reading_assets(root: Path) -> dict:
    root = Path(root)
    metadata = PaperMetadata(title="Recoverable reading asset", authors=["Synthetic Fixture"], year=2026, journal="Fixture Review", doi="10.1234/reading.assets", abstract_en="IL-6 did not increase. aPS/PT was measured.", abstract_zh="血栓风险与抗磷脂抗体关联。")
    library = LibraryService(root)
    try:
        paper_id = library.ingest(metadata)["paper_id"]
        folder = library.create_folder("恢复样本")
        library.move_items([paper_id], folder["folder_id"])
        library.add_tags([paper_id], ["抗磷脂", "已读"])
        library.conn.execute("UPDATE items SET personal_thoughts=?, understanding_level=?, user_notes=? WHERE paper_id=?", ("关联尚需验证", "部分理解", "核对分母 n=12", paper_id))
        library.conn.commit()
    finally:
        library.close()
    base = PaperWorkspace.create_for_paper_id(root, paper_id, metadata)
    generations = []
    for case in ("superscript-text", "formula-outline"):
        payload = json.loads(fixture_path(case).read_text(encoding="utf-8"))
        payload["metadata"] = {key: getattr(metadata, key) for key in ("title", "authors", "journal", "year")}
        payload["content_items"][0]["text"] = metadata.title
        source = f"%PDF-1.4\n% deterministic reader review fixture\n% {case}\n".encode()
        sha = hashlib.sha256(source).hexdigest()
        generation = materialize_fixture_payload(payload, base.root / "generations" / sha[:16])
        base.source_pdf.write_bytes(generation.source_pdf.read_bytes())
        base.save_job(JobState(paper_id=paper_id, status="full_read_ready", stages={"paper_parse_upgrade": StageRecord(status="completed", result={"active_parsed_dir": "parsed/mineru", "active_workspace": f"generations/{sha[:16]}", "source_sha256": sha, "method": FIXTURE_METHOD, "mineru_version": FIXTURE_PARSER_VERSION})}))
        rendered = FullReadRenderer().render_completed(generation, paper_id=paper_id)
        reader = Path(rendered["reader_html"])
        library = LibraryService(root)
        try:
            library.record_pdf_attachment(paper_id, sha, len(source))
            library.publish_reader(paper_id, reader.relative_to(base.root).as_posix())
        finally:
            library.close()
        generations.append(generation.root.relative_to(root).as_posix())
    review = ReviewService(root)
    try:
        review.bind_session("fixture-parent", paper_id, "fixture-review")
        review.confirm_conclusions("fixture-review", [{"conclusion_type": "个人思考", "conclusion_text": "抗磷脂相关结果需要独立验证", "evidence_locator": "旧定位：结果部分"}])
    finally:
        review.close()
    jobs = BackgroundJobStore(root)
    handle = jobs.create_or_get(BackgroundRequest(paper_id, "xlsx_snapshot", "9" * 64, {"data_root": str(root), "workspace_root": str(base.root)}))
    jobs.transition(handle.root.name, "running", pid=99999999)
    atomic_write_json(handle.root / "launch.json", {"pid": 99999999})
    atomic_write_json(root / "jobs/downloads/job_1234567890abcdef.json", {"status": "running", "owner_pid": 99999999, "selection": [paper_id], "children": []})
    return {"paper_id": paper_id, "folder_id": folder["folder_id"], "generations": generations, "active_generation": generations[-1], "job_id": handle.root.name, "reader": reader.relative_to(root).as_posix()}
