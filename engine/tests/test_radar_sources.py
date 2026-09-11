import json

import pytest

from scientific_reading.radar_sources import fetch_page, query_for


CONFIG = {"focus_groups": [["antiphospholipid", "APS"], ["single cell"]],
          "counter_terms": ["no association"], "recent_since": "2024-01-01"}
UNTIL = "2026-09-09T00:00:00+00:00"


class Response:
    def __init__(self, data, url):
        self.raw, self.url = json.dumps(data).encode(), url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.raw[:size]

    def geturl(self):
        return self.url


def test_crossref_ranked_discovery_and_cursor_keep_same_query_window():
    discovery = query_for(CONFIG, "crossref", "recent", window_until=UNTIL, page_size=5)
    assert discovery["params"]["offset"] == 0 and "cursor" not in discovery["params"]
    first = query_for(CONFIG, "crossref", "incremental", "2026-09-08T00:00:00+00:00", UNTIL, page_size=5)
    second = query_for(CONFIG, "crossref", "incremental", first["window_from"], first["window_until"], "page-two", 5)
    assert second["params"] == first["params"] | {"cursor": "page-two"}
    assert "sort" not in first["params"] and "until-index-date:2026-09-09T00:00:00" in first["params"]["filter"]
    epmc = query_for(CONFIG, "europe_pmc", "counter", window_until=UNTIL)
    assert '("antiphospholipid" OR "APS") AND ("single cell")' in epmc["query"]
    assert '"no association"' in epmc["query"]


def test_public_metadata_status_and_pages_do_not_claim_pdf_or_fulltext():
    request = query_for(CONFIG, "crossref", "recent", window_until=UNTIL, page_size=5)
    row = {"DOI": "10.5555/EXAMPLE", "title": ["<b>Study</b>"], "abstract": "<p>Source abstract.</p>",
           "type": "posted-content", "published": {"date-parts": [[2025, 4, 3]]},
           "update-to": [{"type": "retraction"}], "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}]}
    page = fetch_page(request, lambda *args, **kwargs: Response({"status": "ok", "message": {"items": [row], "total-results": 6}}, request["url"]))
    item = page["items"][0]
    assert item["doi"] == "10.5555/example" and item["title"] == "Study"
    assert item["fulltext_status"] == "not_requested" and item["oa_status"] == "open_license_hint_unverified"
    assert item["status_flags"] == ["preprint", "update_notice:retraction"] and page["has_more"]
    with pytest.raises(ValueError, match="redirect_forbidden"):
        fetch_page(request, lambda *args, **kwargs: Response({}, "https://unknown.example/"))
