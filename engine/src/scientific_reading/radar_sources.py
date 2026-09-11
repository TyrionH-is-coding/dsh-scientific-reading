"""公开元数据发现适配器；固定服务地址，不取得 PDF 或读取账号会话。"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from .identifiers import normalize_doi, normalize_pmid


SOURCES = {"europe_pmc": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
           "crossref": "https://api.crossref.org/works"}


def plain(value, limit=24000):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(value, "html.parser").get_text(" ")).strip()[:limit]


def query_for(config, source, lane, window_from=None, window_until=None, cursor=None, page_size=25):
    groups = config["focus_groups"]
    terms = [term for group in groups for term in group]
    if lane == "counter":
        terms += config["counter_terms"]
    if source == "europe_pmc":
        query = " AND ".join("(" + " OR ".join('"' + term.replace('"', ' ') + '"' for term in group) + ")" for group in groups)
        if lane == "counter":
            query += " AND (" + " OR ".join('"' + term.replace('"', ' ') + '"' for term in config["counter_terms"]) + ")"
        if window_from:
            query += f" AND UPDATE_DATE:[{window_from[:10]} TO {window_until[:10]}]"
        elif lane == "recent":
            query += f" AND FIRST_PDATE:[{config['recent_since']} TO {window_until[:10]}]"
        if lane in {"recent", "incremental"}:
            query += " sort_date:y"
        params = {"query": query, "format": "json", "resultType": "core", "pageSize": page_size, "cursorMark": cursor or "*"}
    elif source == "crossref":
        params = {"query.bibliographic": config.get("crossref_query") or " ".join(terms), "rows": page_size}
        if lane == "counter" and config.get("crossref_query"):
            params["query.bibliographic"] += " " + " ".join(config["counter_terms"])
        # Crossref cursor pages do not preserve the ranked discovery order.
        # Initial discovery is explicitly bounded; update windows use cursors until exhausted.
        params.update({"cursor": cursor or "*"} if lane == "incremental" else {"offset": 0})
        if window_from:
            params["filter"] = f"from-index-date:{window_from[:19]},until-index-date:{window_until[:19]}"
        elif lane == "recent":
            params["filter"] = f"from-pub-date:{config['recent_since']},until-pub-date:{window_until[:10]}"
        query = params["query.bibliographic"]
    else:
        raise ValueError("radar_source_invalid")
    return {"source": source, "lane": lane, "query": query, "params": params,
            "url": SOURCES[source] + "?" + urlencode(params), "window_from": window_from, "window_until": window_until}


def _epmc(row):
    doi, pmid = normalize_doi(row.get("doi")), normalize_pmid(row.get("pmid") or (row.get("id") if row.get("source") == "MED" else None))
    types = [plain(value, 160) for value in row.get("pubTypeList", {}).get("pubType", [])]
    flags = [value for value in types if any(term in value.casefold() for term in ("retract", "erratum", "correct", "preprint"))]
    if row.get("source") == "PPR" and "preprint" not in flags:
        flags.append("preprint")
    publication_date = row.get("firstPublicationDate") or ""
    authors = [author.get("fullName", "") for author in row.get("authorList", {}).get("author", []) if author.get("fullName")]
    return {"title": plain(row.get("title"), 2000), "doi": doi, "pmid": pmid, "authors": authors[:200],
            "journal": plain(row.get("journalInfo", {}).get("journal", {}).get("title"), 500),
            "year": int(row["pubYear"]) if str(row.get("pubYear", "")).isdigit() else None,
            "publication_date": publication_date, "abstract_en": plain(row.get("abstractText")),
            "publication_types": types, "status_flags": flags,
            "oa_status": "metadata_indicates_oa" if row.get("isOpenAccess") == "Y" else "unknown_or_non_oa",
            "fulltext_status": "not_requested", "cited_by_count": row.get("citedByCount"),
            "source_url": "https://doi.org/" + quote(doi, safe="/()") if doi else "https://europepmc.org/article/" + quote(str(row.get("source", "")), safe="") + "/" + quote(str(row.get("id", "")), safe=""),
            "source_record_id": str(row.get("source", "")) + ":" + str(row.get("id", ""))}


def _crossref(row):
    doi = normalize_doi(row.get("DOI"))
    parts = row.get("published", {}).get("date-parts", [[]])[0]
    types = [str(row.get("type", "unknown"))]
    flags = ["preprint"] if row.get("type") == "posted-content" else []
    flags += ["update_notice:" + str(update.get("type", "unknown")) for update in row.get("update-to", [])]
    if "is-preprint-of" in row.get("relation", {}):
        flags.append("preprint")
    licenses = [license.get("URL", "") for license in row.get("license", []) if isinstance(license, dict)]
    return {"title": plain((row.get("title") or [""])[0], 2000), "doi": doi, "pmid": None,
            "authors": [" ".join(filter(None, (a.get("given"), a.get("family")))) or a.get("name", "") for a in row.get("author", [])][:200],
            "journal": plain((row.get("container-title") or [""])[0], 500),
            "year": parts[0] if parts and type(parts[0]) is int else None,
            "publication_date": "-".join(str(n).zfill(4 if i == 0 else 2) for i, n in enumerate(parts[:3])),
            "abstract_en": plain(row.get("abstract")), "publication_types": types, "status_flags": flags,
            "oa_status": "open_license_hint_unverified" if any("creativecommons.org/licenses/" in url for url in licenses) else "unknown",
            "fulltext_status": "not_requested", "cited_by_count": row.get("is-referenced-by-count"),
            "source_url": "https://doi.org/" + quote(doi, safe="/()") if doi else "https://search.crossref.org/",
            "source_record_id": doi or ""}


def fetch_page(request, opener=urlopen):
    req = Request(request["url"], headers={"Accept": "application/json", "User-Agent": "DeepLiterature/0.2 (metadata radar)"})
    with opener(req, timeout=18) as response:
        if urlsplit(response.geturl()).hostname not in {"www.ebi.ac.uk", "api.crossref.org"}:
            raise ValueError("radar_source_redirect_forbidden")
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("radar_source_response_too_large")
    data = json.loads(raw)
    if request["source"] == "europe_pmc":
        if "resultList" not in data or "hitCount" not in data:
            raise ValueError("radar_source_response_invalid")
        rows = data["resultList"].get("result", [])
        items = [_epmc(row) for row in rows]
        cursor = data.get("nextCursorMark")
        total = int(data["hitCount"])
        limit = request["params"]["pageSize"]
    else:
        message = data.get("message", {})
        if data.get("status") != "ok" or not isinstance(message.get("items"), list):
            raise ValueError("radar_source_response_invalid")
        rows = message["items"]
        items = [_crossref(row) for row in rows]
        cursor = message.get("next-cursor")
        total = int(message.get("total-results", 0))
        limit = request["params"]["rows"]
    items = [row for row in items if row["title"] and row["source_record_id"]]
    more = bool(rows and len(rows) >= limit and cursor and cursor != request["params"].get("cursorMark", request["params"].get("cursor")))
    if request["source"] == "crossref" and "offset" in request["params"]:
        more = total > len(rows)
    return {"items": items, "total": total, "next_cursor": cursor if more else None,
            "has_more": more, "returned": len(rows), "skipped_invalid": len(rows) - len(items)}
