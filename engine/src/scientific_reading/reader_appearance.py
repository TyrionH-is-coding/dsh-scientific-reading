"""在已验证 Reader 上应用显示方案；从不改写正文、译文或解析资产。"""
from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser

from bs4 import BeautifulSoup, NavigableString
import tinycss2


DEFAULT = {"theme": "paper", "font": "serif", "font_size": 18, "width": 1020,
           "layout": "original", "html_template": "{{content}}", "css": ""}
FONTS = {"serif": '"Noto Serif CJK SC","Songti SC",STSong,serif',
         "sans": '"Segoe UI","Microsoft YaHei",sans-serif',
         "mono": '"Cascadia Code","Microsoft YaHei",monospace'}
PALETTES = {"paper": ("#f3f1eb", "#fffef9", "#252822", "#6e726a", "#d9d6ca", "#405f54"),
            "light": ("#f3f5f7", "#ffffff", "#20252b", "#596470", "#dce1e6", "#285b8f"),
            "dark": ("#161b20", "#20272e", "#e4eaf0", "#a9b4be", "#48535e", "#9acbb8")}


class _TemplateParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.placeholders = [], 0

    def handle_starttag(self, tag, attrs):
        if tag not in {"div", "section", "header", "footer", "main", "aside", "p", "h1", "h2", "h3", "span", "strong", "em", "small", "hr"}:
            raise ValueError("reader_template_tag_forbidden")
        if any(key not in {"class", "title", "aria-label"} or "{{" in (value or "") for key, value in attrs):
            raise ValueError("reader_template_attribute_forbidden")
        if tag != "hr":
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("reader_template_unbalanced")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "hr":
            self.handle_endtag(tag)

    def handle_data(self, data):
        if "{{content}}" in data:
            if any(tag in {"p", "h1", "h2", "h3", "span", "strong", "em", "small"} for tag in self.stack):
                raise ValueError("reader_template_content_container_invalid")
            self.placeholders += data.count("{{content}}")

    def handle_decl(self, decl):
        raise ValueError("reader_template_fragment_required")

    def handle_pi(self, data):
        raise ValueError("reader_template_tag_forbidden")


def _check_tokens(tokens):
    for token in tokens:
        if token.type in {"error", "url", "bad-url"}:
            raise ValueError("reader_css_invalid_or_external")
        if token.type == "function" and token.lower_name in {"url", "src", "image", "image-set", "-webkit-image-set", "expression"}:
            raise ValueError("reader_css_external_forbidden")
        for attr in ("arguments", "content"):
            if hasattr(token, attr):
                _check_tokens(getattr(token, attr) or [])


def _check_rules(rules):
    for rule in rules:
        if rule.type == "at-rule" and rule.lower_at_keyword in {"media", "supports", "layer"} and rule.content is not None:
            _check_tokens(rule.prelude)
            _check_rules(tinycss2.parse_stylesheet(rule.content, skip_comments=True, skip_whitespace=True))
        elif rule.type == "qualified-rule":
            _check_tokens(rule.prelude)
            for declaration in tinycss2.parse_blocks_contents(rule.content, skip_comments=True, skip_whitespace=True):
                if declaration.type != "declaration" or declaration.lower_name in {"behavior", "-moz-binding"}:
                    raise ValueError("reader_css_declaration_invalid")
                _check_tokens(declaration.value)
        else:
            raise ValueError("reader_css_rule_invalid")


def validate(config):
    if not isinstance(config, dict) or set(config) - set(DEFAULT):
        raise ValueError("reader_appearance_invalid")
    value = DEFAULT | config
    if value["theme"] not in PALETTES or value["font"] not in FONTS or value["layout"] not in {"original", "interleaved", "side_by_side", "chinese"}:
        raise ValueError("reader_appearance_invalid")
    for key, low, high in (("font_size", 14, 26), ("width", 640, 1600)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("reader_appearance_size_invalid")
    html, css = value["html_template"], value["css"]
    if not isinstance(html, str) or not isinstance(css, str) or len(html) > 64000 or len(css) > 64000:
        raise ValueError("reader_template_size_invalid")
    if html.count("{{content}}") != 1 or re.search(r"{{(?!content}})", html):
        raise ValueError("reader_template_content_required")
    parser = _TemplateParser()
    parser.feed(html)
    parser.close()
    if parser.stack or parser.placeholders != 1:
        raise ValueError("reader_template_unbalanced")
    if "\x00" in css or re.search(r"</style", css, re.IGNORECASE):
        raise ValueError("reader_css_invalid")
    structure = re.sub(r'/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '', css)
    if structure.count("{") != structure.count("}"):
        raise ValueError("reader_css_unbalanced")
    _check_rules(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    return value


def effective(library, paper_id):
    item = library.get_item(paper_id)
    row = library.conn.execute("""SELECT s.* FROM display_defaults d JOIN display_schemes s USING(scheme_id)
        WHERE d.kind='reader' AND d.scope_folder_id IN ('',?) ORDER BY (d.scope_folder_id=?) DESC LIMIT 1""",
                               (item.get("folder_id") or "", item.get("folder_id") or "")).fetchone()
    return {"paper_id": paper_id, "scheme_id": row["scheme_id"] if row else None,
            "revision": row["revision"] if row else 0,
            "config": validate(json.loads(row["config_json"])) if row else dict(DEFAULT)}


def render_html(html, config, accent_color=None, *, palette=None, paper_id=None, source_pdf_sha256=None):
    config = validate(config)
    soup = BeautifulSoup(html, "html.parser")
    shell = soup.select_one(".reader-shell")
    if not soup.body or not soup.head or not shell or not soup.select_one("article"):
        raise ValueError("reader_template_base_unsupported")
    original_ids = [node["id"] for node in soup.select("[id]")]
    if paper_id and re.fullmatch(r"[a-f0-9]{64}", source_pdf_sha256 or ""):
        from reader.build_reader import add_figure_discussion, FIGURE_DISCUSSION_SCRIPT

        inserted = False
        for figure in soup.select('figure[data-asset]'):
            if 'table' not in figure.get('class', []) and not figure.select_one('.figure-discuss-trigger'):
                add_figure_discussion(soup, figure)
                inserted = True
        soup.body['data-paper-id'] = paper_id
        soup.body['data-source-pdf-sha256'] = source_pdf_sha256
        if inserted:
            script = soup.new_tag('script')
            script.string = '(()=>{const body=document.body;const paperId=body.dataset.paperId;' + FIGURE_DISCUSSION_SCRIPT + '})();'
            soup.body.append(script)
    template = BeautifulSoup(config["html_template"], "html.parser")
    marker = next((node for node in template.find_all(string=True) if "{{content}}" in str(node)), None)
    if marker is None:
        raise ValueError("reader_template_content_required")
    holder = soup.new_tag("div", attrs={"class": "reader-presentation"})
    shell.insert_before(holder)
    before, after = str(marker).split("{{content}}")
    marker.insert_before(NavigableString(before))
    marker.insert_before(shell.extract())
    marker.insert_before(NavigableString(after))
    marker.extract()
    for child in list(template.contents):
        holder.append(child.extract())
    if [node["id"] for node in soup.select("[id]")] != original_ids:
        raise ValueError("reader_presentation_anchor_mismatch")
    canvas, paper, ink, muted, line, accent = PALETTES[config["theme"]]
    if palette:
        canvas, paper, ink, muted, line, accent = (palette[key] for key in ("canvas", "paper", "ink", "muted", "line", "accent"))
    if accent_color:
        accent = accent_color
    rgb = [int(accent[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    accent_ink = "#172a31" if sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722))) > .179 else "#ffffff"
    style = soup.new_tag("style", id="reader-display-style")
    scheme = palette["scheme"] if palette else ('dark' if config['theme'] == 'dark' else 'light')
    style.string = f""":root{{--canvas:{canvas};--paper:{paper};--paper-muted:{canvas};--ink:{ink};--muted:{muted};--line:{line};--accent:{accent};--accent-ink:{accent_ink};--text-width:{config['width'] - 80}px;--asset-width:{config['width']}px;color-scheme:{scheme};}}
body{{background:{canvas};color:{ink};font-family:{FONTS[config['font']]};}}
.reader-shell{{width:min({config['width'] + 324}px,calc(100% - 40px));}}
article,.translation-panel{{font-size:{config['font_size']}px;line-height:1.85;color:var(--ink);}}
.paper-card,.paper-hero{{background:var(--paper);color:var(--ink);}}
article h2,article h3,.paper-hero h1,.original-title,.reader-mark strong,.reader-toolbar button{{color:var(--ink);}}
.reader-toolbar,.control-group,.low-value-region{{background:var(--paper);border-color:var(--line);color:var(--ink);}}
.translation-panel{{background:var(--canvas);border-color:var(--line);font-family:inherit;}}
.sidebar-guide-item summary strong,.sidebar-guide-jump,.toc a,.toc .toc-h3 a,.low-value-region>summary,article th,.asset-caption,figcaption{{color:var(--ink);}}
.toc a.active{{background:var(--canvas);color:var(--ink);border-left:3px solid var(--accent);}}
.reader-toolbar .control-group button[aria-pressed='true']{{background:var(--accent);color:{accent_ink};}}
.is-highlighted .highlight-ink{{color:#20252b;}}
body[data-reader-layout='side_by_side'] .reading-block:has(>.translation-panel){{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;}}
body[data-reader-layout='side_by_side'] .translation-panel{{margin:0;padding:0 0 0 16px;border-left:1px solid var(--line);}}
body[data-reader-layout='chinese'] .reading-block:has(>.translation-panel)>.source-primary{{display:none;}}
@media(max-width:800px){{body[data-reader-layout='side_by_side'] .reading-block:has(>.translation-panel){{display:block;}}.reader-shell{{width:calc(100% - 24px);}}}}
""" + config["css"]
    soup.head.append(style)
    soup.body["data-reader-layout"] = config["layout"]
    soup.body["data-reader-preferred-layout"] = config["layout"]
    if config["layout"] != "original":
        soup.body["data-language"] = "bilingual"
    # Built-in language buttons may still collapse translations. Keep the chosen layout in sync.
    script = soup.new_tag("script")
    script.string = "document.querySelectorAll('button[data-language]').forEach(b=>b.addEventListener('click',()=>{document.body.dataset.readerLayout=b.dataset.language==='en'?'original':document.body.dataset.readerPreferredLayout;}));"
    soup.body.append(script)
    return str(soup)


def render(library, payload):
    from .__main__ import _resolve_artifact
    from .library_views import LibraryViews

    paper_id = payload["paper_id"]
    selected = effective(library, paper_id)
    config = validate(payload["config"]) if "config" in payload else selected["config"]
    artifact = _resolve_artifact(library.data_root, paper_id, "reader")
    path = library.data_root / "papers" / paper_id / artifact["rel_path"]
    raw = path.read_bytes()
    base_sha = hashlib.sha256(raw).hexdigest()
    if base_sha != (artifact.get("sha256") or artifact.get("manifest", {}).get("reader_sha256")):
        raise ValueError("reader_sha_mismatch")
    theme = LibraryViews(library).theme()
    html = render_html(raw.decode("utf-8"), config, palette=theme if theme["custom"] else None,
                       paper_id=paper_id, source_pdf_sha256=artifact.get("manifest", {}).get("source_pdf_sha256"))
    # Recheck publication after rendering, without running parsing or translation.
    current = _resolve_artifact(library.data_root, paper_id, "reader")
    if (current.get("sha256") or current.get("manifest", {}).get("reader_sha256")) != base_sha or current["rel_path"] != artifact["rel_path"]:
        raise ValueError("reader_changed_during_preview")
    return {**selected, "config": config, "html": html, "base_sha256": base_sha,
            "display_sha256": hashlib.sha256(html.encode()).hexdigest(), "persisted_artifacts_changed": False}
