from __future__ import annotations

from bs4 import BeautifulSoup

from reader.build_reader import build_reader


def _guide() -> dict[str, list[dict[str, object]]]:
    return {
        "research_question": [],
        "key_methods": [],
        "core_results": [],
        "limitations": [],
    }


def test_reader_only_folds_high_confidence_low_value_regions(tmp_path):
    source = tmp_path / "fold-source.html"
    output = tmp_path / "reader.html"
    source.write_text(
        '<html><head><title>T</title><style></style></head><body>'
        '<main class="paper"><div class="paper-meta"></div>'
        '<nav class="toc"><ul>'
        '<li><a href="#abstract">摘要</a></li>'
        '<li><a href="#intro">引言</a></li>'
        '<li><a href="#future">未来展望</a></li>'
        '<li><a href="#ack">致谢</a></li>'
        '<li><a href="#refs">参考文献</a></li>'
        '</ul></nav><article><h1>T</h1>'
        '<p>许可声明</p><details class="source-text" data-block="p0001-m0000" data-page="1">'
        '<summary>English</summary><p lang="en">Google grants permission to reproduce figures with attribution.</p></details>'
        '<p>重复题名</p><details class="source-text" data-block="p0001-m0000b" data-page="1">'
        '<summary>English</summary><p lang="en">T</p></details>'
        '<p>作者与单位</p><details class="source-text" data-block="p0001-m0001" data-page="1">'
        '<summary>English</summary><p lang="en">Ada Example, Department of Engineering, ada@example.org</p></details>'
        '<h2 id="abstract">摘要</h2><details class="source-text" data-block="p0001-m0002" data-page="1">'
        '<summary>English</summary><p lang="en">Abstract</p></details>'
        '<p>摘要正文</p><details class="source-text" data-block="p0001-m0003" data-page="1">'
        '<summary>English</summary><p lang="en">This study evaluates a bridge.</p></details>'
        '<h2 id="intro">引言</h2><details class="source-text" data-block="p0001-m0004" data-page="1">'
        '<summary>English</summary><p lang="en">1 Introduction</p></details>'
        '<p>核心正文</p><details class="source-text" data-block="p0001-m0005" data-page="1">'
        '<summary>English</summary><p lang="en">The bridge remained stable.</p></details>'
        '<h2 id="future">未来展望</h2><details class="source-text" data-block="p0002-m0001" data-page="2">'
        '<summary>English</summary><p lang="en">Future Perspectives</p></details>'
        '<p>仍属于正文</p><details class="source-text" data-block="p0002-m0002" data-page="2">'
        '<summary>English</summary><p lang="en">Future work should test larger spans.</p></details>'
        '<h2 id="ack">致谢</h2><details class="source-text" data-block="p0003-m0001" data-page="3">'
        '<summary>English</summary><p lang="en">Acknowledgements</p></details>'
        '<p>基金信息</p><details class="source-text" data-block="p0003-m0002" data-page="3">'
        '<summary>English</summary><p lang="en">Supported by Example Foundation.</p></details>'
        '<h2 id="refs">参考文献</h2><details class="source-text" data-block="p0004-m0001" data-page="4">'
        '<summary>English</summary><p lang="en">References</p></details>'
        '<p class="reading-block reference-block" data-block="p0004-m0002" data-page="4">[1] Example reference.</p>'
        '</article></main></body></html>',
        encoding="utf-8",
    )

    build_reader(
        source,
        output,
        {},
        guide=_guide(),
        paper_id="paper-folding",
        reader_revision="1" * 64,
    )

    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    regions = {
        node["data-kind"]: node
        for node in soup.select("details.low-value-region[data-kind]")
    }
    assert set(regions) == {"frontmatter", "acknowledgements", "references"}
    assert "作者与单位" in regions["frontmatter"].get_text(" ", strip=True)
    assert "grants permission" in regions["frontmatter"].get_text(" ", strip=True)
    assert "Acknowledgements" in regions["acknowledgements"].get_text(" ", strip=True)
    assert "[1] Example reference." in regions["references"].get_text(" ", strip=True)
    assert "题名页信息 · 3项" in regions["frontmatter"].summary.get_text(" ", strip=True)
    assert "致谢 · 2项" in regions["acknowledgements"].summary.get_text(" ", strip=True)
    assert "参考文献 · 2项" in regions["references"].summary.get_text(" ", strip=True)
    assert soup.select_one('#abstract:not(.low-value-region *)')
    assert soup.select_one('#intro:not(.low-value-region *)')
    assert soup.select_one('#future:not(.low-value-region *)')


def test_reader_persists_low_value_region_state_without_network(tmp_path):
    source = tmp_path / "fold-storage-source.html"
    output = tmp_path / "reader.html"
    source.write_text(
        '<html><head><title>T</title><style></style></head><body>'
        '<main class="paper"><div class="paper-meta"></div><nav class="toc"><ul>'
        '<li><a href="#refs">References</a></li></ul></nav><article><h1>T</h1>'
        '<p>Body</p><details class="source-text" data-block="p0001-m0001" data-page="1">'
        '<summary>English</summary><p lang="en">Body</p></details>'
        '<h2 id="refs">参考文献</h2><details class="source-text" data-block="p0002-m0001" data-page="2">'
        '<summary>English</summary><p lang="en">References</p></details>'
        '<p class="reading-block reference-block" data-block="p0002-m0002">[1] Reference.</p>'
        '</article></main></body></html>',
        encoding="utf-8",
    )
    build_reader(
        source,
        output,
        {},
        guide=_guide(),
        paper_id="paper-fold-state",
        reader_revision="2" * 64,
    )

    html = output.read_text(encoding="utf-8")
    assert "sr-reader-regions:${paperId}:${readerRevision}" in html
    assert "region.addEventListener('toggle'" in html
    assert "region.open = savedRegions.has(region.id)" in html
    assert "closest('details.low-value-region')" in html
    assert "fetch(" not in html
