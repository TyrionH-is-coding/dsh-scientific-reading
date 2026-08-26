from __future__ import annotations

import json

from bs4 import BeautifulSoup

from reader.build_reader import build_reader


def _guide() -> dict[str, list[dict[str, object]]]:
    return {
        "research_question": [],
        "key_methods": [],
        "core_results": [],
        "limitations": [],
    }


def _render_citation_reader(tmp_path) -> str:
    source = tmp_path / "citation-source.html"
    output = tmp_path / "reader.html"
    source.write_text(
        '<html><head><title>T</title><style></style></head><body>'
        '<main class="paper"><div class="paper-meta"></div>'
        '<nav class="toc"><ul><li><a href="#intro">Introduction</a></li>'
        '<li><a href="#refs">References</a></li></ul></nav><article><h1>T</h1>'
        '<h2 id="intro">引言</h2><details class="source-text" data-block="p0001-m0001" data-page="1">'
        '<summary>English</summary><p lang="en">1 Introduction</p></details>'
        '<p>正文引用</p><details class="source-text" data-block="p0001-m0002" data-page="1">'
        '<summary>English</summary><p lang="en">We build on [1], compare [1, 2], span [1–2], use coalesced [3, 4], and keep [9] unresolved.</p></details>'
        '<pre>[1] code is not a citation</pre>'
        '<h2 id="refs">参考文献</h2><details class="source-text" data-block="p0002-m0001" data-page="2">'
        '<summary>English</summary><p lang="en">References</p></details>'
        '<p class="reading-block reference-block" data-block="p0002-m0002" data-page="2">'
        '[1] A. Alpha. Safe Systems. 2021. doi:10.1000/ALPHA.</p>'
        '<p class="reading-block reference-block" data-block="p0002-m0003" data-page="2">'
        '[2] B. Beta. Robust Models. arXiv:1234.56789v2 (2020). &lt;img src=x onerror=alert(1)&gt;</p>'
        '<p class="reading-block" data-block="p0002-m0004" data-page="2">'
        '[3] C. Gamma. Coalesced One. 2019. arXiv:1901.00001.[4] D. Delta. Coalesced Two. 2018.</p>'
        '</article></main></body></html>',
        encoding="utf-8",
    )
    build_reader(
        source,
        output,
        {},
        guide=_guide(),
        paper_id="paper-citations",
        reader_revision="3" * 64,
    )
    return output.read_text(encoding="utf-8")


def test_reader_links_known_numeric_citations_to_offline_reference_data(tmp_path):
    html = _render_citation_reader(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    triggers = soup.select(
        '.reading-block[data-block="p0001-m0002"] .citation-trigger'
    )

    assert [trigger.get_text(strip=True) for trigger in triggers] == [
        "[1]",
        "[1, 2]",
        "[1–2]",
        "[3, 4]",
    ]
    assert [trigger["data-references"] for trigger in triggers] == [
        "1",
        "1,2",
        "1,2",
        "3,4",
    ]
    assert "[9]" in soup.select_one(
        '.reading-block[data-block="p0001-m0002"] .source-primary'
    ).get_text(" ", strip=True)
    assert not soup.select(".reference-block .citation-trigger")
    assert not soup.select("pre .citation-trigger")

    payload = json.loads(soup.select_one("#reference-data").string)
    assert payload["contract_version"] == "reader-references-v1"
    assert payload["references"]["1"]["doi"] == "10.1000/alpha"
    assert payload["references"]["1"]["year"] == "2021"
    assert payload["references"]["2"]["arxiv_id"] == "1234.56789v2"
    assert payload["references"]["2"]["year"] == "2020"
    assert payload["references"]["3"]["arxiv_id"] == "1901.00001"
    assert payload["references"]["4"]["year"] == "2018"
    assert payload["references"]["2"]["raw_reference"].endswith(
        "<img src=x onerror=alert(1)>"
    )


def test_reader_uses_one_safe_citation_dialog(tmp_path):
    html = _render_citation_reader(tmp_path)
    soup = BeautifulSoup(html, "html.parser")

    assert len(soup.select("dialog#citation-dialog")) == 1
    assert soup.select_one('head meta[charset="utf-8"]')
    assert soup.select_one("#citation-dialog-content")
    assert soup.select_one("#close-citation-dialog")
    assert "referenceCard.textContent" in soup.script.string
    assert "rawReference.textContent" in soup.script.string
    assert "citationDialog.showModal()" in soup.script.string
    assert "citationContent.innerHTML" not in soup.script.string
    assert not soup.select("#reference-data img")
    assert "<img src=x onerror=alert(1)>" not in html


def test_reader_embeds_a_manual_exportable_next_reading_queue(tmp_path):
    html = _render_citation_reader(tmp_path)
    soup = BeautifulSoup(html, "html.parser")

    assert soup.select_one("button#open-reading-queue").get_text(
        " ", strip=True
    ) == "待读 0"
    assert len(soup.select("dialog#reading-queue-dialog")) == 1
    assert soup.select_one("#reading-queue-items")
    assert soup.select_one("#clear-reading-queue")
    assert soup.select_one("#export-reading-queue")
    dsh = soup.select_one("#submit-reading-queue")
    assert dsh.has_attr("disabled")
    assert "下一阶段接通" in dsh.get_text(" ", strip=True)
    script = soup.script.string
    assert "sr-next-reading:v1" in script
    assert "sr-next-reading-v1" in script
    assert "candidateKey" in script
    assert "source_contexts" in script
    assert "scientific-reading-queue.json" in script
    assert "URL.createObjectURL" in script
    assert "setTimeout(() => URL.revokeObjectURL(url), 1000)" in script
    assert "queueItem.textContent" in script
    assert "readingQueueItems.innerHTML" not in script
    assert "fetch(" not in html
