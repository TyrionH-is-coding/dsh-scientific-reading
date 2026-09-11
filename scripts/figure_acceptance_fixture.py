"""创建带实际 PNG、合成译文与 Reader 的隔离验收论文。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine" / "tests"))
from test_figure_context import fixture
from reader_review_fixtures import _write_translation_batches
from scientific_reading.full_read_service import FullReadService
from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.library_service import LibraryService

root = Path(sys.argv[1])
paper, generation, sha = fixture(root)
service = FullReadService()
active = service._inspect_active_mineru(generation)
_write_translation_batches(service, generation, [
    {"block_id": row["block_id"], "translation_zh": "合成验收译文：" + row["english"], "highlight": "none"}
    for row in active.rows
])
block = active.blocks[1].block_id
service.finalize(generation, {"contract_version": "full-review-v2", "highlights": [], "guide": {
    name: [{"text": "仅用于验证图像传递和来源定位的合成样本。", "source_block_ids": [block]}]
    for name in ("research_question", "key_methods", "core_results", "limitations")
}})
result = FullReadRenderer().render_completed(generation, paper_id=paper)
library = LibraryService(root)
try:
    library.publish_reader(paper, Path(result["reader_html"]).relative_to(root / "papers" / paper).as_posix())
finally:
    library.close()
print(json.dumps({"paper_id": paper, "source_pdf_sha256": sha, "asset_id": "mineru-p0001-img0001"}))
