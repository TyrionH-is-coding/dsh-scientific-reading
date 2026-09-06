from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

from scientific_reading.assets import AssetManifest
from scientific_reading.full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
)
from scientific_reading.export_service import ExportService
from scientific_reading.full_read_service import FullReadService
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace


SOURCE_PDF = b"%PDF-1.4 current MinerU fixture\n%%EOF\n"
SOURCE_SHA256 = hashlib.sha256(SOURCE_PDF).hexdigest()
MINERU_VERSION = "mineru-local-v1:3.4.5"
FIGURE_CAPTION = (
    "Figure 1. Center deflection increases linearly with applied load."
)
REFERENCE = (
    "[1] Rivera A, Lee M. Synthetic beam fixture specification. "
    "Engineering software acceptance notes, 2026."
)


def _write_current_mineru_output(raw_root: Path, title: str) -> None:
    content_root = raw_root / "beam-acceptance" / "hybrid_auto"
    image_root = content_root / "images"
    image_root.mkdir(parents=True)
    Image.new("RGB", (2, 2), "white").save(
        image_root / "figure.jpg", format="JPEG"
    )
    payload = [
        {
            "type": "text",
            "text": title,
            "text_level": 1,
            "bbox": [72, 70, 540, 100],
            "page_idx": 0,
        },
        {
            "type": "text",
            "text": "Abstract",
            "text_level": 1,
            "bbox": [72, 120, 180, 145],
            "page_idx": 0,
        },
        {
            "type": "text",
            "text": "A synthetic beam was tested under increasing load.",
            "bbox": [72, 160, 540, 200],
            "page_idx": 0,
        },
        {
            "type": "chart",
            "img_path": "images/figure.jpg",
            "content": "",
            "chart_caption": [FIGURE_CAPTION],
            "chart_footnote": [],
            "bbox": [87, 250, 831, 530],
            "page_idx": 0,
        },
        {
            "type": "text",
            "text": "References",
            "text_level": 1,
            "bbox": [72, 70, 200, 100],
            "page_idx": 1,
        },
        {
            "type": "ref_text",
            "text": REFERENCE,
            "bbox": [78, 120, 505, 160],
            "page_idx": 1,
        },
    ]
    (content_root / "beam-acceptance_content_list.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _published_workspace(tmp_path: Path) -> PaperWorkspace:
    metadata = PaperMetadata(
        title="Synthetic Beam Load-Deflection Acceptance Study",
        authors=["Acceptance Fixture"],
    )
    workspace = PaperWorkspace.create(tmp_path, metadata)
    workspace.source_pdf.write_bytes(SOURCE_PDF)
    raw_root = tmp_path / "raw"
    _write_current_mineru_output(raw_root, metadata.title)
    parsed_root = workspace.parsed_dir / "mineru"
    result = MineruNormalizer(MINERU_VERSION).normalize(
        raw_root,
        parsed_root,
        metadata,
        SOURCE_SHA256,
    )
    shutil.copytree(raw_root, parsed_root / "raw")
    for name in ("source_map.json", "parse_report.json"):
        path = parsed_root / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        if name == "parse_report.json":
            payload.update(
                {
                    "provider": "mineru-local-v1",
                    "provider_version": "3.4.5",
                }
            )
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    manifest = AssetManifest(workspace.manifest_path)
    for asset in result.assets:
        manifest.upsert(asset)
    state = workspace.load_job()
    state.stages["paper_parse_upgrade"] = StageRecord(
        status="completed",
        result={
            "active_parsed_dir": "parsed/mineru",
            "source_sha256": SOURCE_SHA256,
            "method": "auto",
            "mineru_version": MINERU_VERSION,
        },
    )
    workspace.save_job(state)
    return workspace


def test_current_chart_and_ref_text_reach_batches_and_reader(
    tmp_path: Path,
) -> None:
    workspace = _published_workspace(tmp_path)
    report = json.loads(
        (workspace.parsed_dir / "mineru" / "parse_report.json").read_text(
            encoding="utf-8"
        )
    )
    source_map = json.loads(
        (workspace.parsed_dir / "mineru" / "source_map.json").read_text(
            encoding="utf-8"
        )
    )

    assert [(asset["kind"], asset["source_index"]) for asset in report["assets"]] == [
        ("figure", 3)
    ]
    assert [
        (block["source_type"], block["source_index"])
        for block in source_map["blocks"]
        if block["source_type"] == "ref_text"
    ] == [("ref_text", 5)]

    service = FullReadService()
    plan = service.prepare(workspace)
    source = json.loads(plan.batch_paths[0].read_text(encoding="utf-8"))
    rows = source["blocks"]
    assert [row["source_type"] for row in rows if row["english"] == REFERENCE] == [
        "reference"
    ]
    assert [row["source_type"] for row in rows if row["english"] == FIGURE_CAPTION] == [
        "caption"
    ]

    translations = []
    for row in rows:
        translations.append(
            {
                "block_id": row["block_id"],
                "source_text": row["english"],
                "translation_zh": (
                    ""
                    if row["source_type"] == "reference"
                    else f"中译：{row['english']}"
                ),
                "highlight": "none",
            }
        )
    service.save_translation_batch(
        workspace,
        {
            "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
            "batch_id": source["batch_id"],
            "source_sha256": SOURCE_SHA256,
            "translations": translations,
        },
    )
    body_id = next(
        row["block_id"]
        for row in rows
        if row["source_type"] == "text" and row["text_level"] is None
    )
    result = service.finalize(
        workspace,
        {
            "contract_version": FULL_REVIEW_CONTRACT_VERSION,
            "highlights": [],
            "guide": {
                "research_question": [
                    {
                        "text": "梁的载荷与挠度关系是什么？",
                        "source_block_ids": [body_id],
                    }
                ],
                "key_methods": [],
                "core_results": [],
                "limitations": [],
            },
        },
    )
    html = Path(result["reader_full_html"]).read_text(encoding="utf-8")
    assert "中译：" + FIGURE_CAPTION in html
    assert REFERENCE in html
    assert "中译：" + REFERENCE not in html
    assert "data:image/jpeg;base64," in html

    exported = ExportService().export(workspace)
    assert len(exported.figure_paths) == 1
    assert exported.figure_paths[0].name == "Fig_01.png"
    export_manifest = json.loads(
        workspace.exports_manifest.read_text(encoding="utf-8")
    )
    assert export_manifest["assets"][0]["caption"] == FIGURE_CAPTION
