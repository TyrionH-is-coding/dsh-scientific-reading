from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scientific_reading.mineru_normalizer import (
    MineruNormalizer,
    render_mineru_markdown,
)


def _write_content_list(raw_root: Path, items: list[dict]) -> Path:
    path = raw_root / "paper" / "auto" / "bridge_content_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _item(item_type: str, page: int, **values) -> dict:
    return {
        "type": item_type,
        "page_idx": page,
        "bbox": [72, 90, 520, 132],
        **values,
    }


def test_normalize_builds_deterministic_blocks_assets_and_report(
    tmp_path,
    metadata,
) -> None:
    raw_root = tmp_path / "raw"
    output_root = tmp_path / "normalized"
    asset_root = raw_root / "paper" / "auto" / "images"
    asset_root.mkdir(parents=True)
    (asset_root / "beam.png").write_bytes(b"beam-image")
    (asset_root / "loads.png").write_bytes(b"table-image")
    content_path = _write_content_list(
        raw_root,
        [
            _item("header", 0, text=metadata.title, text_level=1),
            _item("page_number", 0, text="1"),
            _item(
                "text",
                0,
                text="A modular bridge transfers wheel loads across beams.",
            ),
            _item(
                "list",
                1,
                list_items=["Assemble modules.", "Apply the design load."],
            ),
            _item(
                "image",
                1,
                img_path="images/beam.png",
                image_caption=["Bridge beam arrangement"],
                image_footnote=[],
            ),
            _item(
                "table",
                1,
                img_path="images/loads.png",
                table_caption=["Load cases"],
                table_footnote=["Values are synthetic."],
                table_body="<table><tr><td>LC1</td></tr></table>",
            ),
            _item("equation", 1),
        ],
    )
    source_sha = "a" * 64

    result = MineruNormalizer().normalize(
        raw_root,
        output_root,
        metadata,
        source_sha,
    )

    assert [block.block_id for block in result.blocks] == [
        "p0001-m0001",
        "p0001-m0002",
        "p0002-m0001",
    ]
    assert [block.source_type for block in result.blocks] == [
        "header",
        "text",
        "list",
    ]
    assert [block.source_index for block in result.blocks] == [0, 2, 3]
    assert result.blocks[-1].text == (
        "- Assemble modules.\n- Apply the design load."
    )
    assert result.raw_content_list_sha256 == hashlib.sha256(
        content_path.read_bytes()
    ).hexdigest()
    assert result.report.identity_anchor_found is True
    assert result.report.page_count == 2
    assert result.report.warnings == ["unsupported_content_type:equation:6"]
    assert [asset.kind for asset in result.assets] == ["figure", "table", "table"]
    assert (
        output_root / "images" / "mineru-p0002-img0001.png"
    ).read_bytes() == (
        b"beam-image"
    )
    assert (
        output_root / "tables" / "mineru-p0002-table0001.png"
    ).read_bytes() == (
        b"table-image"
    )
    assert (
        output_root / "tables" / "mineru-p0002-table0001.html"
    ).read_text(encoding="utf-8") == (
        "<table><tr><td>LC1</td></tr></table>\n"
    )
    source_map = json.loads(
        (output_root / "source_map.json").read_text(encoding="utf-8")
    )
    assert source_map["raw_content_list_sha256"] == (
        result.raw_content_list_sha256
    )
    assert (output_root / "full.md").read_text(encoding="utf-8") == (
        render_mineru_markdown(result.blocks, 2)
    )


def test_normalize_500_blocks_preserves_page_and_item_order(
    tmp_path,
    metadata,
) -> None:
    raw_root = tmp_path / "raw"
    items = [
        _item(
            "text",
            index // 100,
            text=(
                metadata.title
                if index == 0
                else f"Synthetic engineering block {index}."
            ),
        )
        for index in range(500)
    ]
    _write_content_list(raw_root, items)

    result = MineruNormalizer().normalize(
        raw_root,
        tmp_path / "normalized",
        metadata,
        "b" * 64,
    )

    assert len(result.blocks) == 500
    assert result.blocks[0].block_id == "p0001-m0001"
    assert result.blocks[99].block_id == "p0001-m0100"
    assert result.blocks[100].block_id == "p0002-m0001"
    assert result.blocks[-1].block_id == "p0005-m0100"


def test_normalize_persists_three_level_outline_and_filters_title_noise(
    tmp_path, metadata
) -> None:
    raw_root = tmp_path / "raw"
    _write_content_list(raw_root, [
        _item("text", 0, text=metadata.title, text_level=1),
        _item("text", 0, text="author@example.org", text_level=1),
        _item("text", 0, text="Abstract", text_level=2),
        _item("text", 0, text="3 Model Architecture", text_level=2),
        _item("text", 1, text="3.2 Attention", text_level=2),
        _item("text", 1, text="3.2.1 Scaled Dot-Product Attention", text_level=2),
        _item("text", 1, text="Attention maps queries to outputs."),
    ])

    result = MineruNormalizer().normalize(
        raw_root, tmp_path / "normalized", metadata, "c" * 64
    )

    assert result.blocks[0].heading_level is None
    assert result.blocks[0].structure_source == "outline_noise_filtered"
    assert result.blocks[1].heading_level is None
    assert result.blocks[2].section_path == ("Abstract",)
    assert result.blocks[3].section_path == ("3 Model Architecture",)
    assert result.blocks[4].section_path == (
        "3 Model Architecture", "3.2 Attention"
    )
    assert result.blocks[5].section_path == (
        "3 Model Architecture",
        "3.2 Attention",
        "3.2.1 Scaled Dot-Product Attention",
    )
    assert result.blocks[6].section_path == result.blocks[5].section_path
    assert any("level_conflict" in warning for warning in result.report.warnings)
    reloaded = json.loads(
        (tmp_path / "normalized/source_map.json").read_text(encoding="utf-8")
    )
    assert reloaded["blocks"][5]["heading_level"] == 3
    assert reloaded["blocks"][5]["structure_source"] == "visible_section_number"


def test_normalize_skips_empty_text_placeholders_with_warning(
    tmp_path,
    metadata,
) -> None:
    raw_root = tmp_path / "raw"
    _write_content_list(
        raw_root,
        [
            _item("header", 0, text=metadata.title, text_level=1),
            _item("text", 0, text="   "),
            _item("text", 0, text="Synthetic engineering result."),
        ],
    )

    result = MineruNormalizer().normalize(
        raw_root,
        tmp_path / "normalized",
        metadata,
        "c" * 64,
    )

    assert [block.source_index for block in result.blocks] == [0, 2]
    assert result.report.warnings == ["empty_text_item:text:1"]


@pytest.mark.parametrize("candidates", [0, 2])
def test_normalize_requires_exactly_one_content_list(
    tmp_path,
    metadata,
    candidates,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    for index in range(candidates):
        path = raw_root / f"run-{index}" / f"x{index}_content_list.json"
        path.parent.mkdir()
        path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="唯一"):
        MineruNormalizer().normalize(
            raw_root,
            tmp_path / "normalized",
            metadata,
            "c" * 64,
        )


def test_normalize_rejects_empty_or_reverse_page_content(
    tmp_path,
    metadata,
) -> None:
    raw_root = tmp_path / "raw"
    _write_content_list(
        raw_root,
        [
            _item("text", 1, text=metadata.title),
            _item("text", 0, text="Earlier page appears later."),
        ],
    )

    with pytest.raises(ValueError, match="页码"):
        MineruNormalizer().normalize(
            raw_root,
            tmp_path / "normalized",
            metadata,
            "d" * 64,
        )


def test_normalize_rejects_missing_asset_and_asset_outside_raw_root(
    tmp_path,
    metadata,
) -> None:
    raw_root = tmp_path / "raw"
    _write_content_list(
        raw_root,
        [
            _item("text", 0, text=metadata.title),
            _item(
                "image",
                0,
                img_path="images/missing.png",
                image_caption=[],
                image_footnote=[],
            ),
        ],
    )

    with pytest.raises(ValueError, match="资产"):
        MineruNormalizer().normalize(
            raw_root,
            tmp_path / "normalized",
            metadata,
            "e" * 64,
        )


def test_normalize_requires_identity_anchor(tmp_path, metadata) -> None:
    raw_root = tmp_path / "raw"
    _write_content_list(
        raw_root,
        [_item("text", 0, text="Unrelated anonymous fragment.")],
    )

    with pytest.raises(ValueError, match="身份"):
        MineruNormalizer().normalize(
            raw_root,
            tmp_path / "normalized",
            metadata,
            "f" * 64,
        )
