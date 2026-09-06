from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from reader.build_reader import build_reader
from scientific_reading.full_read_models import Translation
from scientific_reading.full_read_renderer import (
    FullReadRenderer,
    _compact_mineru_latex,
    _render_rich_text,
)
from scientific_reading.models import PaperMetadata
from scientific_reading.parse_models import SourceBlock
from scientific_reading.workspace import PaperWorkspace


def test_compact_mineru_latex_removes_character_spacing() -> None:
    assert _compact_mineru_latex(r"\mathrm { A t t e n t i o n }") == (
        r"\mathrm{Attention}"
    )
    assert _compact_mineru_latex(r"\frac { 1 } { \sqrt { d _ { k } } }") == (
        r"\frac{1}{\sqrt{d_{k}}}"
    )


def test_render_rich_text_converts_spaced_inline_latex_to_mathml() -> None:
    html = _render_rich_text(
        r"Dot-product attention uses $\frac { 1 } { \sqrt { d _ { k } } }$."
    )
    assert "<math" in html
    assert r"\frac" not in html
    assert "Dot-product attention uses " in html


def test_math_compaction_keeps_control_word_boundaries() -> None:
    rendered = _render_rich_text(r"$P (X \geq n) = C (K, n) / C (N, n)$")
    soup = BeautifulSoup(rendered, "html.parser")
    assert soup.find("mo", string="≥") is not None
    assert not any("\\" in node.get_text() for node in soup.select("mi, mo"))
    assert _compact_mineru_latex(r"\alpha x + \beta y") == r"\alpha{}x+\beta{}y"


def test_repeated_pdf_headers_stay_traceable_without_splitting_references(tmp_path):
    metadata = PaperMetadata(title="Example paper", authors=["Test"])
    workspace = PaperWorkspace.create(tmp_path, metadata)
    rows = [
        (1, "References", "text", 1),
        (1, "[13] A. B-cell receptors of the", "ref_text", None),
        (1, "Author et al.", "header", None),
        (2, "ACPA response. 2021. doi:10.1000/example.", "ref_text", None),
        (2, "Author et al.", "header", None),
    ]
    blocks = tuple(SourceBlock(
        block_id=f"p{page:04}-m{index:04}", page=page, bbox=(1, 2, 3, 4),
        kind="text", text=text, source_type=kind, source_index=index,
        heading_level=level,
    ) for index, (page, text, kind, level) in enumerate(rows))
    translations = {block.block_id: Translation(
        block_id=block.block_id, source_text=block.text,
        translation_zh="" if block.source_type == "ref_text" else "译文",
        highlight="none",
    ) for block in blocks}
    source = tmp_path / "source.html"
    output = tmp_path / "reader.html"
    source.write_text(FullReadRenderer()._base_html(
        workspace, metadata, blocks, translations, (),
    ), encoding="utf-8")
    build_reader(source, output, {}, guide={
        "research_question": [], "key_methods": [], "core_results": [], "limitations": [],
    }, paper_id="headers", reader_revision="1" * 64)
    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    assert "Author et al." not in soup.select_one(".toc").get_text()
    assert not any(node.get_text() == "Author et al." for node in soup.select("h2, h3"))
    headers = soup.select('details[data-kind="page_headers"] .reading-block')
    assert len(headers) == 2
    assert {node["data-block"] for node in headers} == {blocks[2].block_id, blocks[4].block_id}
    references = json.loads(soup.select_one("#reference-data").string)["references"]
    assert references["13"]["raw_reference"].endswith("ACPA response. 2021. doi:10.1000/example.")
    assert references["13"]["doi"] == "10.1000/example"


def test_base_html_inserts_display_equations_by_source_index(
    tmp_path: Path,
) -> None:
    metadata = PaperMetadata(title="Attention paper", authors=["Test"])
    workspace = PaperWorkspace.create(tmp_path, metadata)
    raw = workspace.parsed_dir / "mineru" / "raw"
    raw.mkdir(parents=True)
    (raw / "paper_content_list.json").write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "Before the formula.",
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 0,
                },
                {
                    "type": "equation",
                    "text": "$$\n\\mathrm { A t t e n t i o n } ( Q , K , V )\n$$",
                    "text_format": "latex",
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "After the formula.",
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 0,
                },
                {
                    "type": "chart",
                    "text": "should stay dropped",
                    "bbox": [1, 2, 3, 4],
                    "page_idx": 0,
                },
            ]
        ),
        encoding="utf-8",
    )
    before = SourceBlock(
        block_id="p0001-m0001",
        page=1,
        bbox=(1, 2, 3, 4),
        kind="text",
        text="Before the formula.",
        source_type="text",
        source_index=0,
    )
    after = SourceBlock(
        block_id="p0001-m0002",
        page=1,
        bbox=(1, 2, 3, 4),
        kind="text",
        text="After the formula.",
        source_type="text",
        source_index=2,
    )
    translations = {
        before.block_id: Translation(
            block_id=before.block_id,
            source_text=before.text,
            translation_zh="公式之前。",
            highlight="none",
        ),
        after.block_id: Translation(
            block_id=after.block_id,
            source_text=after.text,
            translation_zh="公式之后。",
            highlight="none",
        ),
    }

    html = FullReadRenderer()._base_html(
        workspace, metadata, (before, after), translations, ()
    )

    before_at = html.index("公式之前。")
    equation_at = html.index('class="equation"')
    after_at = html.index("公式之后。")
    assert before_at < equation_at < after_at
    equation = html[equation_at : after_at]
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">' in equation
    assert "should stay dropped" not in html
    assert r"\mathrm { A t t e n t i o n }" not in html
    assert r"\mathrm{Attention}" not in html
