import hashlib
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.full_read_service import FullReadService
from scientific_reading.library_service import LibraryService
from scientific_reading.library_views import LibraryViews
from scientific_reading.reader_appearance import DEFAULT, effective, render, render_html, validate
from scripts.reader_review_fixtures import _write_translation_batches
from test_figure_context import fixture


def ready(root):
    paper, generation, sha = fixture(root)
    service = FullReadService()
    active = service._inspect_active_mineru(generation)
    _write_translation_batches(service, generation, [
        {"block_id": row["block_id"], "translation_zh": "合成译文：" + row["english"], "highlight": "none"}
        for row in active.rows
    ])
    service.finalize(generation, {"contract_version": "full-review-v2", "highlights": [], "guide": {
        name: [{"text": "合成样本", "source_block_ids": [active.blocks[1].block_id]}]
        for name in ("research_question", "key_methods", "core_results", "limitations")}})
    result = FullReadRenderer().render_completed(generation, paper_id=paper)
    library = LibraryService(root)
    path = Path(result["reader_html"])
    library.publish_reader(paper, path.relative_to(root / "papers" / paper).as_posix())
    return library, paper, generation, path


@pytest.mark.parametrize("change", [
    {"html_template": "<section>Missing content</section>"},
    {"html_template": "<section>{{content}}"},
    {"html_template": "{{content}}<script>alert(1)</script>"},
    {"html_template": '<div onclick="x()">{{content}}</div>'},
    {"html_template": "<p>{{content}}</p>"},
    {"css": 'body{background:u\\72l("https://example.org/leak")}'},
    {"css": '@import "https://example.org/remote.css";'},
    {"css": "p{color:red"}, {"css": "p{color red;}"},
    {"css": "</style><script>alert(1)</script>"}, {"font_size": True}, {"width": 1},
])
def test_invalid_template_is_rejected_before_publication(change):
    with pytest.raises(ValueError):
        validate(DEFAULT | change)


def test_css_selectors_and_media_comparisons_are_valid():
    css = '.reader-custom > header { color: var(--ink); } @media (width < 800px) { article { padding: 8px; } }'
    assert validate(DEFAULT | {"css": css})["css"] == css


def test_global_presets_change_reader_palette_without_changing_source(tmp_path):
    library, paper, _generation, path = ready(tmp_path)
    before = path.read_bytes()
    views = LibraryViews(library)
    for theme in views.theme()["presets"]:
        views.theme_save({"preset": theme["id"]})
        result = render(library, {"paper_id": paper})
        assert f"--paper:{theme['paper']}" in result["html"]
        assert f"--ink:{theme['ink']}" in result["html"]
        assert f"color-scheme:{theme['scheme']}" in result["html"]
        assert path.read_bytes() == before


def test_old_reader_gets_discussion_controls_without_regenerating_its_content():
    raw='<html><head></head><body><main class="reader-shell"><article id="body"><p id="block-a">Original text</p><figure data-asset="fig1"><img src="data:image/png;base64,AAAA"><figcaption>Figure 1.</figcaption></figure></article></main></body></html>'
    displayed=render_html(raw,DEFAULT,paper_id='p1',source_pdf_sha256='a'*64)
    soup=BeautifulSoup(displayed,'html.parser')
    assert soup.select_one('#block-a').text=='Original text'
    assert len(soup.select('.figure-discuss-trigger'))==2
    assert soup.body['data-source-pdf-sha256']=='a'*64
    assert 'figureChatBound' in displayed and 'figure-discuss-trigger' not in raw


def test_preview_apply_restore_preserves_all_source_assets(tmp_path, monkeypatch):
    library, paper, generation, path = ready(tmp_path)
    base = path.read_bytes()
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in generation.root.rglob('*') if p.is_file()}
    monkeypatch.setattr(FullReadRenderer, "render_completed", lambda *args, **kwargs: pytest.fail("appearance reran content generation"))
    views = LibraryViews(library)
    config = DEFAULT | {"theme": "dark", "font": "sans", "font_size": 20, "width": 1200, "layout": "side_by_side",
                        "html_template": '<div class="lab-reader"><header>课题阅读</header>{{content}}</div>',
                        "css": '@media(min-width:900px){.lab-reader {padding:8px;}}'}
    preview = render(library, {"paper_id": paper, "config": config})
    assert views.schemes('reader')['schemes'] == []
    assert preview['base_sha256'] == hashlib.sha256(base).hexdigest()
    assert preview['display_sha256'] != preview['base_sha256']
    a, b = BeautifulSoup(base, 'html.parser'), BeautifulSoup(preview['html'], 'html.parser')
    for selector in ('.source-primary', '.translation-panel', 'article img', 'article table', 'article math'):
        assert [str(row) for row in a.select(selector)] == [str(row) for row in b.select(selector)]
    assert b.body['data-language'] == 'bilingual' and b.body['data-reader-layout'] == 'side_by_side'
    saved = views.scheme_save({'name':'全局夜读','kind':'reader','config':config})
    scheme_id = saved['saved_scheme_id']
    views.scheme_default({'kind':'reader','scheme_id':scheme_id})
    assert render(library, {'paper_id':paper})['html'] == preview['html']
    with pytest.raises(ValueError):
        views.scheme_save({'name':'坏模板','kind':'reader','config':config|{'css':'@import "evil.css";'},'scheme_id':scheme_id,'expected_revision':1})
    assert effective(library,paper)['revision'] == 1
    with pytest.raises(ValueError,match='conflict'):
        views.scheme_save({'name':'并发旧版本','kind':'reader','config':config,'scheme_id':scheme_id,'expected_revision':0})
    folder = library.create_folder('分类阅读')['folder_id']
    library.move_items([paper],folder)
    local = views.scheme_save({'name':'分类排版','kind':'reader','scope_folder_id':folder,'config':config|{'layout':'chinese'}})
    views.scheme_default({'kind':'reader','scope_folder_id':folder,'scheme_id':local['saved_scheme_id']})
    assert effective(library,paper)['config']['layout'] == 'chinese'
    views.scheme_default({'kind':'reader','scope_folder_id':folder,'scheme_id':None})
    assert effective(library,paper)['scheme_id'] == scheme_id
    views.scheme_default({'kind':'reader','scheme_id':None})
    assert effective(library,paper)['config'] == DEFAULT
    assert path.read_bytes() == base
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in generation.root.rglob('*') if p.is_file()} == before
    library.close()
