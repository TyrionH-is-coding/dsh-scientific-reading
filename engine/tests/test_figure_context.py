import base64
import hashlib
import io

import pytest
from PIL import Image

from scientific_reading.figure_context import FigureContextService, figure_numbers, related_blocks
from scientific_reading.library_service import LibraryService
from scientific_reading.paper_chat import PaperChatService
from scientific_reading.parse_models import SourceBlock
from test_evidence_locator import _fixture


def fixture(root):
    images = {}
    for number, color in ((1, "red"), (2, "blue")):
        stream = io.BytesIO()
        Image.new("RGB", (80, 60), color).save(stream, format="PNG")
        images[f"images/fig{number}.png"] = stream.getvalue()
    items = [
        {"type": "header", "page_idx": 0, "bbox": [0, 0, 80, 10], "text": "Synthetic locator study", "text_level": 1},
        {"type": "text", "page_idx": 0, "bbox": [0, 0, 80, 20], "text": "Figure 1a–c shows the measured response."},
        {"type": "image", "page_idx": 0, "bbox": [0, 20, 80, 80], "img_path": "images/fig1.png", "image_caption": ["Figure 1. Three measured panels."], "is_body": True},
        {"type": "text", "page_idx": 1, "bbox": [0, 0, 80, 20], "text": "Figs. 1 and 2 are discussed across pages."},
        {"type": "image", "page_idx": 1, "bbox": [0, 20, 80, 80], "img_path": "images/fig2.png", "image_caption": ["Figure 2. Independent control."], "is_body": True},
        {"type": "text", "page_idx": 2, "bbox": [0, 0, 80, 20], "text": "Figure 10 should never match Figure 1 by substring."},
    ]
    return _fixture(root, content_items=items, asset_files=images)


def test_number_and_reference_boundaries():
    assert figure_numbers("Figs. 1a–c and 2; Figure S3B; 图 4。") == {"1", "2", "S3", "4"}
    assert figure_numbers("Fig. 10") == {"10"}
    blocks = (SourceBlock("b1", 1, (0, 0, 1, 1), "text", "No figure number appears here."),)
    assert related_blocks(blocks, "Figure 1. Caption.") == ([], ["1"], 0)


def test_real_image_sha_cross_page_and_replacement(tmp_path):
    paper_id, generation, sha = fixture(tmp_path)
    library = LibraryService(tmp_path)
    chats = PaperChatService(library)
    chat = chats.ensure(paper_id)
    service = FigureContextService(library)
    payload = {"paper_id": paper_id, "source_pdf_sha256": sha, "asset_id": "mineru-p0001-img0001"}
    first = service.select(payload)
    context = first["context"]
    assert first["session_id"] == chat["session_id"]
    assert hashlib.sha256(base64.b64decode(first["image"]["data"])).hexdigest() == context["image_sha256"]
    assert {row["page"] for row in context["passages"]} >= {1, 2}
    assert context["explicit_reference_count"] == 3
    assert context["image_status"] == "pending_delivery"
    service.delivered({"paper_id": paper_id, "revision": 1, "image_supplied": True})
    assert chats.get(paper_id)["active_figure"]["image_status"] == "supplied_to_native_chat"
    second = service.select({**payload, "asset_id": "mineru-p0002-img0001", "expected_revision": 1, "text_only": True})
    assert second["image"] is None
    assert second["context"]["image_sha256"] != context["image_sha256"]
    assert second["context"]["revision"] == 2
    assert chats.get(paper_id)["active_figure"]["asset_id"] == "mineru-p0002-img0001"
    with pytest.raises(ValueError, match="figure_context_changed"):
        service.select({**payload, "expected_revision": 1})
    with pytest.raises(ValueError, match="figure_pdf_changed"):
        service.select({**payload, "source_pdf_sha256": "0" * 64})
    with pytest.raises(ValueError, match="figure_asset_unavailable"):
        service.select({**payload, "asset_id": "other-paper-image"})
    library.close()
    reopened = LibraryService(tmp_path)
    assert PaperChatService(reopened).get(paper_id)["active_figure"]["revision"] == 2
    generation.source_pdf.write_bytes(b"changed")
    with pytest.raises(ValueError):
        FigureContextService(reopened).select(payload)
    assert PaperChatService(reopened).get(paper_id)["active_figure"]["revision"] == 2
    reopened.close()
