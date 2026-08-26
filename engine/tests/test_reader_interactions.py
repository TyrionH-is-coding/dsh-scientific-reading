from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup

from reader.build_reader import build_reader


@pytest.fixture()
def rendered_html(tmp_path) -> str:
    source = tmp_path / "base-interactions.html"
    output = tmp_path / "reader-interactions.html"
    source.write_text(
        '<html><head><title>T</title><style></style></head><body>'
        '<main class="paper"><div class="paper-meta"></div>'
        '<nav class="toc"><ul><li><a href="#section-a">Section A</a></li></ul></nav>'
        '<article><h1>T</h1><h2 id="section-a">Section A</h2>'
        '<p>正文</p><details class="source-text" data-block="p0001-m0001" '
        'data-page="1"><summary>English</summary><p lang="en">Source &lt;sup&gt;*&lt;/sup&gt; H&lt;sub&gt;2&lt;/sub&gt;O</p></details>'
        '<figure class="paper-asset figure" data-asset="figure-1">'
        '<img src="data:image/png;base64,QUJD" alt="Figure 1"><figcaption>Figure 1</figcaption></figure>'
        '<figure class="paper-asset table" data-asset="table-1">'
        '<table><tr><th>Case</th><th>Load</th></tr><tr><td>A</td><td>42</td></tr></table>'
        '<figcaption>Table 1</figcaption></figure>'
        '</article></main></body></html>',
        encoding="utf-8",
    )
    build_reader(
        source,
        output,
        {"p0001-m0001": ("result", "核心结果")},
        guide={
            "research_question": [],
            "key_methods": [],
            "core_results": [
                {
                    "text": "合成核心结果",
                    "source_block_ids": ["p0001-m0001"],
                }
            ],
            "limitations": [],
        },
        paper_id="paper-interactions",
        reader_revision="f" * 64,
    )
    return output.read_text(encoding="utf-8")


def test_reader_uses_one_offline_asset_dialog_without_copying_images(
    rendered_html,
):
    soup = BeautifulSoup(rendered_html, "html.parser")
    assert len(soup.select("dialog#asset-dialog")) == 1
    assert soup.select_one(
        'figure.figure button.asset-dialog-trigger[data-asset-kind="figure"] img'
    )
    table_button = soup.select_one(
        'figure.table button.asset-dialog-trigger[data-asset-kind="table"]'
    )
    assert table_button is not None
    assert table_button.get_text(" ", strip=True) == "放大表格"
    assert rendered_html.count("data:image/png;base64,QUJD") == 1
    assert re.search(r'(?:src|href)=["\']https?://', rendered_html) is None


def test_reader_uses_revision_not_self_hash_for_progress(rendered_html):
    assert "dataset.readerRevision" in rendered_html
    assert "reader_sha256" not in rendered_html


def test_reader_respects_url_hash_before_saved_position(rendered_html):
    assert "if (!location.hash && savedAtLoad)" in rendered_html


def test_reader_local_storage_failures_are_non_fatal(rendered_html):
    assert "try {" in rendered_html
    assert "localStorage.getItem" in rendered_html
    assert "localStorage.setItem" in rendered_html
    assert "catch (_error)" in rendered_html


def test_reader_throttles_progress_and_keeps_initial_resume_target(
    rendered_html,
):
    assert "requestAnimationFrame" in rendered_html
    assert "250" in rendered_html
    assert "readingAnchors" not in rendered_html
    assert "asset.dataset.progressAnchor" in rendered_html
    assert "getBoundingClientRect" not in rendered_html
    assert "restoreSavedPosition(savedAtLoad" in rendered_html
    assert "updatedAt: new Date().toISOString()" in rendered_html


def test_asset_dialog_restores_focus_and_handles_escape(rendered_html):
    assert "lastDialogTrigger.focus()" in rendered_html
    assert "addEventListener('cancel'" in rendered_html
    assert "event.key === 'Escape'" in rendered_html
    assert "replaceChildren" in rendered_html


def test_reader_has_wide_responsive_and_print_contract(rendered_html):
    soup = BeautifulSoup(rendered_html, "html.parser")
    css = soup.style.string
    assert "--text-width: 800px" in css
    assert "--asset-width: 1020px" in css
    assert "@media (max-width: 1000px)" in css
    assert "@media (max-width: 680px)" in css
    assert "overflow-x: auto" in css
    assert ".asset-dialog-trigger" in css
    assert "@media print" in css


def test_sidebar_toggle_exposes_expanded_state(rendered_html):
    soup = BeautifulSoup(rendered_html, "html.parser")
    button = soup.select_one("#toggle-sidebar")
    assert button is not None
    assert button.get("aria-expanded") == "true"
    assert "aria-pressed" not in button.attrs
    assert (
        "sidebarButton.setAttribute('aria-expanded', String(!collapsed))"
        in rendered_html
    )


def test_reader_outputs_periodical_controls_without_runtime_dom_rebuild(rendered_html):
    soup = BeautifulSoup(rendered_html, "html.parser")
    assert soup.body.get("class") == ["periodical-first"]
    assert [button.get_text(" ", strip=True) for button in soup.select(".language-controls button")] == [
        "英文", "中英",
    ]
    assert [button.get_text(" ", strip=True) for button in soup.select(".reading-controls button")] == [
        "全文", "无标记", "重点",
    ]
    script = soup.script.string
    assert "setLanguage" in script
    assert "setReadingMode" in script
    assert "toolbar.innerHTML" not in script
    assert "guide.cloneNode" not in script


def test_reader_defaults_to_english_and_keeps_translation_per_block(rendered_html):
    soup = BeautifulSoup(rendered_html, "html.parser")
    block = soup.select_one('.reading-block[data-block="p0001-m0001"]')

    assert soup.body["data-language"] == "en"
    assert block.select_one('.source-primary[lang="en"]').get_text(
        " ", strip=True
    ) == "Source * H 2 O"
    translation = block.select_one('.translation-panel[lang="zh-CN"]')
    assert translation.get_text(" ", strip=True) == "正文"
    assert translation.has_attr("hidden")
    assert [
        button.get_text(" ", strip=True)
        for button in soup.select(".language-controls button")
    ] == ["英文", "中英"]
    script = soup.script.string
    assert "setBlockTranslation" in script
    assert "window.getSelection" in script


def test_reader_renders_only_safe_escaped_superscript_and_subscript(rendered_html):
    soup = BeautifulSoup(rendered_html, "html.parser")
    source = soup.select_one('.source-primary[lang="en"]')

    assert source.select_one("sup").get_text(strip=True) == "*"
    assert source.select_one("sub").get_text(strip=True) == "2"
    assert "<sup>" not in source.get_text()
    assert "<sub>" not in source.get_text()
