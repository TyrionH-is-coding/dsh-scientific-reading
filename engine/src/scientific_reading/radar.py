"""经确认方向驱动的候选雷达。发现、评估、反馈与正式纳入各自留痕。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re
import uuid
from urllib.parse import quote

from .data_guard import root_operation
from .identifiers import normalize_doi, normalize_pmid, normalize_title, normalize_author
from .models import PaperMetadata
from .radar_sources import SOURCES, fetch_page, query_for
from .scope import require_global, library_write


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _now():
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def create_schema(conn):
    conn.execute("""CREATE TABLE radar_directions(direction_id TEXT PRIMARY KEY,name TEXT NOT NULL,
        config_json TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,confirmed_revision INTEGER,
        confirmed_at TEXT,next_scan_at TEXT,incremental_json TEXT NOT NULL,lease_until TEXT,
        created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE radar_scans(scan_id TEXT PRIMARY KEY,direction_id TEXT NOT NULL REFERENCES radar_directions(direction_id),
        config_revision INTEGER NOT NULL,mode TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,
        config_json TEXT NOT NULL,queries_json TEXT NOT NULL,summary_json TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE radar_candidates(candidate_id TEXT PRIMARY KEY,identity_key TEXT NOT NULL UNIQUE,
        doi TEXT,pmid TEXT,title_key TEXT NOT NULL,metadata_json TEXT NOT NULL,metadata_sha TEXT NOT NULL,
        first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,library_paper_id TEXT REFERENCES items(paper_id))""")
    conn.execute("CREATE INDEX radar_candidate_doi ON radar_candidates(doi)")
    conn.execute("CREATE INDEX radar_candidate_pmid ON radar_candidates(pmid)")
    conn.execute("""CREATE TABLE radar_direction_candidates(direction_id TEXT NOT NULL REFERENCES radar_directions(direction_id),
        candidate_id TEXT NOT NULL REFERENCES radar_candidates(candidate_id),state TEXT NOT NULL,feedback_json TEXT NOT NULL,
        assessment_json TEXT NOT NULL,assessment_revision INTEGER NOT NULL,notified_at TEXT,updated_at TEXT NOT NULL,
        PRIMARY KEY(direction_id,candidate_id))""")
    conn.execute("""CREATE TABLE radar_discoveries(scan_id TEXT NOT NULL REFERENCES radar_scans(scan_id),
        candidate_id TEXT NOT NULL REFERENCES radar_candidates(candidate_id),source TEXT NOT NULL,lane TEXT NOT NULL,
        record_id TEXT NOT NULL,query_json TEXT NOT NULL,metadata_json TEXT NOT NULL,discovered_at TEXT NOT NULL,
        PRIMARY KEY(scan_id,candidate_id,source,lane,record_id))""")


def validate_schema(conn):
    for table, columns in {
        "radar_directions": {"direction_id", "config_json", "revision", "status", "confirmed_revision", "incremental_json", "lease_until"},
        "radar_scans": {"scan_id", "direction_id", "config_revision", "config_json", "summary_json", "status"},
        "radar_candidates": {"candidate_id", "identity_key", "metadata_sha", "metadata_json", "library_paper_id"},
        "radar_direction_candidates": {"direction_id", "candidate_id", "state", "feedback_json", "assessment_json", "assessment_revision", "notified_at"},
        "radar_discoveries": {"scan_id", "candidate_id", "source", "lane", "record_id", "query_json", "metadata_json"},
    }.items():
        if not columns <= {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            raise ValueError("invalid_v6_schema:" + table)


def _text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in "\n\t" for c in value) or required and not value.strip():
        raise ValueError("radar_text_invalid")
    return value.strip()


def _terms(value, limit=20):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("radar_terms_invalid")
    return list(dict.fromkeys(_text(term, 160, True) for term in value))


def validate_config(config, library):
    allowed = {"question", "goal", "focus_groups", "crossref_query", "inclusion", "exclusion", "research_types", "seed_paper_ids", "sources", "recent_since", "include_classics", "counter_terms", "interval_hours", "page_size"}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError("radar_config_invalid")
    groups = config.get("focus_groups")
    if not isinstance(groups, list) or not 1 <= len(groups) <= 6:
        raise ValueError("radar_focus_required")
    groups = [_terms(group, 8) for group in groups]
    if any(not group for group in groups):
        raise ValueError("radar_focus_required")
    seeds = _terms(config.get("seed_paper_ids", []), 10)
    for paper_id in seeds:
        library.get_item(paper_id)
    sources = _terms(config.get("sources", list(SOURCES)), 2)
    if not sources or set(sources) - SOURCES.keys():
        raise ValueError("radar_source_invalid")
    since = config.get("recent_since", (date.today() - timedelta(days=730)).isoformat())
    if not isinstance(since, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since) or date.fromisoformat(since) > date.today():
        raise ValueError("radar_date_invalid")
    interval, size = config.get("interval_hours", 0), config.get("page_size", 20)
    if type(interval) is not int or not 0 <= interval <= 8760 or type(size) is not int or not 5 <= size <= 100:
        raise ValueError("radar_frequency_or_page_invalid")
    classic = config.get("include_classics", True)
    if type(classic) is not bool:
        raise ValueError("radar_config_invalid")
    return {"question": _text(config.get("question"), 2000, True), "goal": _text(config.get("goal", ""), 2000),
            "focus_groups": groups, "inclusion": _terms(config.get("inclusion", [])), "exclusion": _terms(config.get("exclusion", [])),
            "crossref_query": _text(config.get("crossref_query", ""), 500),
            "research_types": _terms(config.get("research_types", [])), "seed_paper_ids": seeds, "sources": sources,
            "recent_since": since, "include_classics": classic, "counter_terms": _terms(config.get("counter_terms", ["no association", "no effect", "negative", "contradictory"]), 8),
            "interval_hours": interval, "page_size": size}


def _initial_assessment(metadata, config):
    abstract, title = metadata.get("abstract_en", ""), metadata["title"]
    text = (title + " " + abstract).casefold()
    matched = [[term for term in group if term.casefold() in text] for group in config["focus_groups"]]
    excluded = [term for term in config["exclusion"] if term.casefold() in text]
    counter = [term for term in config["counter_terms"] if term.casefold() in text]
    old = bool(metadata.get("year") and metadata["year"] < int(config["recent_since"][:4]))
    return {"origin": "metadata_screen", "verdict": "uncertain", "basis": "abstract_only" if abstract else "metadata_only",
            "relevance": {"question": config["question"], "matched_focus_terms": matched, "exclusion_hints": excluded,
                          "reason": "已按确认方向发现；关键词命中仅是线索，需核对研究对象与问题。"},
            "design": {"label": "；".join(metadata.get("publication_types", [])) or "来源未报告", "limitation": "来源文献类型不等于研究质量或偏倚评估。"},
            "reading_value": {"reason": "请结合研究问题、纳入范围与证据完整度评估阅读价值。", "counterevidence_hints": counter},
            "timeliness": {"publication_date": metadata.get("publication_date"), "role": "较早研究，经典价值待核对" if old else "近期范围内或日期待核对"},
            "limitations": ["未读取全文，属于候选初筛。", "未标记撤稿不代表已经排除撤稿或更正。"],
            "metadata_sha": _sha(metadata), "config_sha": _sha(config)}


class RadarService:
    def __init__(self, library, fetcher=fetch_page):
        self.library, self.conn, self.data_root, self.fetcher = library, library.conn, library.data_root, fetcher

    def direction(self, direction_id):
        require_global("radar_direction")
        row = self.conn.execute("SELECT * FROM radar_directions WHERE direction_id=?", (direction_id,)).fetchone()
        if not row:
            raise ValueError("radar_direction_not_found")
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        result["incremental"] = json.loads(result.pop("incremental_json"))
        result["seed_context"] = [{key: self.library.get_item(paper_id).get(key) for key in ("paper_id", "title", "doi", "abstract_en")}
                                  for paper_id in result["config"]["seed_paper_ids"]]
        return result

    def list(self):
        require_global("radar_list")
        return {"directions": [self.direction(row[0]) for row in self.conn.execute("SELECT direction_id FROM radar_directions ORDER BY updated_at DESC")],
                "sources": list(SOURCES), "policy": "先保存草稿并确认方向，再检索公开元数据。候选不会自动纳入、下载或解析。"}

    @root_operation
    @library_write
    def draft(self, payload):
        require_global("radar_draft")
        config, now = validate_config(payload.get("config"), self.library), _now()
        direction_id = payload.get("direction_id") or "radar_" + uuid.uuid4().hex
        name = _text(payload.get("name"), 80, True)
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            old = self.conn.execute("SELECT * FROM radar_directions WHERE direction_id=?", (direction_id,)).fetchone()
            if old and old["lease_until"] and old["lease_until"] > now:
                raise ValueError("radar_scan_running")
            if payload.get("expected_revision", 0) != (old["revision"] if old else 0):
                raise ValueError("radar_direction_conflict")
            self.conn.execute("""INSERT INTO radar_directions VALUES(?,?,?,'draft',?,NULL,NULL,NULL,'{}',NULL,?,?)
                ON CONFLICT(direction_id) DO UPDATE SET name=excluded.name,config_json=excluded.config_json,status='draft',
                revision=excluded.revision,confirmed_revision=NULL,next_scan_at=NULL,updated_at=excluded.updated_at""",
                              (direction_id, name, _json(config), (old["revision"] if old else 0) + 1, now, now))
        return self.preview(direction_id)

    def preview(self, direction_id):
        direction, until = self.direction(direction_id), _now()
        config = direction["config"]
        lanes = ["recent"] + (["classics"] if config["include_classics"] else []) + (["counter"] if config["counter_terms"] else [])
        return {**direction, "outbound_queries": [query_for(config, source, lane, window_until=until, page_size=config["page_size"])
                                                  for source in config["sources"] for lane in lanes],
                "confirmation": "这些查询词将发送给所选公开元数据服务。纳入/排除范围、研究类型由本地与 Agent 评估，不保证检索完整性。定期扫描仅在工作台运行时执行，未完成分页每分钟续接；相关性需管理员评估，只有新的相关候选会提示。"}

    @root_operation
    @library_write
    def confirm(self, payload):
        require_global("radar_confirm")
        if payload.get("confirmed") is not True:
            raise ValueError("radar_user_confirmation_required")
        direction = self.direction(payload["direction_id"])
        if direction["revision"] != payload.get("expected_revision") or direction["status"] != "draft":
            raise ValueError("radar_direction_conflict")
        now, interval = _now(), direction["config"]["interval_hours"]
        since = (datetime.fromisoformat(now) - timedelta(days=7)).isoformat()
        streams = {source: {"watermark": since} for source in direction["config"]["sources"]}
        with self.conn:
            changed = self.conn.execute("""UPDATE radar_directions SET status='confirmed',confirmed_revision=revision,confirmed_at=?,
                next_scan_at=?,incremental_json=?,updated_at=? WHERE direction_id=? AND revision=? AND status='draft'""",
                (now, (datetime.fromisoformat(now) + timedelta(hours=interval)).isoformat() if interval else None,
                 _json(streams), now, direction["direction_id"], direction["revision"])).rowcount
            if not changed:
                raise ValueError("radar_direction_conflict")
        return self.direction(direction["direction_id"])

    @root_operation
    @library_write
    def pause(self, payload):
        require_global("radar_schedule")
        direction = self.direction(payload["direction_id"])
        if direction["confirmed_revision"] != direction["revision"] or type(payload.get("paused")) is not bool:
            raise ValueError("radar_direction_not_confirmed")
        with self.conn:
            self.conn.execute("UPDATE radar_directions SET status=?,updated_at=? WHERE direction_id=?", ("paused" if payload["paused"] else "confirmed", _now(), direction["direction_id"]))
        return self.direction(direction["direction_id"])

    def _candidate(self, metadata, direction, scan_id, request, now):
        metadata = dict(metadata)
        metadata["doi"], metadata["pmid"] = normalize_doi(metadata.get("doi")), normalize_pmid(metadata.get("pmid"))
        source_metadata = dict(metadata)
        doi, pmid = metadata["doi"], metadata["pmid"]
        title_key = normalize_title(metadata["title"])
        identity = "doi:" + doi if doi else "pmid:" + pmid if pmid else request["source"] + ":" + metadata["source_record_id"]
        metadata.pop("source_record_id", None)
        metadata.pop("cited_by_count", None)
        metadata["primary_metadata_source"] = request["source"]
        if doi:
            metadata["source_url"] = "https://doi.org/" + quote(doi, safe="/()")
        found = self.conn.execute("SELECT * FROM radar_candidates WHERE identity_key=? OR (doi IS NOT NULL AND doi=?) OR (pmid IS NOT NULL AND pmid=?)", (identity, doi, pmid)).fetchall()
        if not found and metadata.get("year") and metadata.get("authors"):
            title_matches = []
            for row in self.conn.execute("SELECT * FROM radar_candidates WHERE title_key=?", (title_key,)):
                previous = json.loads(row["metadata_json"])
                if (previous.get("year") == metadata["year"] and previous.get("authors") and
                        normalize_author(previous["authors"][0]) == normalize_author(metadata["authors"][0]) and
                        not any(row[key] and metadata[key] and row[key] != metadata[key] for key in ("doi", "pmid"))):
                    title_matches.append(row)
            if len(title_matches) == 1:
                found = title_matches
        conflict = len(found) > 1 or bool(found and any(found[0][key] and metadata[key] and found[0][key] != metadata[key] for key in ("doi", "pmid")))
        if conflict:
            metadata["identity_conflict"] = True
            identity = "conflict:" + _sha([doi, pmid])
            found = self.conn.execute("SELECT * FROM radar_candidates WHERE identity_key=?", (identity,)).fetchall()
        elif not found and not doi and not pmid and metadata.get("year") and metadata.get("authors"):
            identity = "title:" + _sha([title_key, metadata["year"], normalize_author(metadata["authors"][0])])
            found = self.conn.execute("SELECT * FROM radar_candidates WHERE identity_key=?", (identity,)).fetchall()
        candidate_id = found[0]["candidate_id"] if found else "candidate_" + uuid.uuid4().hex
        if found and not conflict:
            previous = json.loads(found[0]["metadata_json"])
            preferred = {"crossref": 0, "europe_pmc": 1}
            incoming_primary = preferred[request["source"]] >= preferred[previous["primary_metadata_source"]]
            merged = previous | {key: value for key, value in metadata.items() if value not in (None, "", []) and (incoming_primary or previous.get(key) in (None, "", []))}
            merged["status_flags"] = sorted(set(previous.get("status_flags", []) + metadata.get("status_flags", [])))
            merged["publication_types"] = sorted(set(previous.get("publication_types", []) + metadata.get("publication_types", [])))
            merged["abstract_en"] = max((previous.get("abstract_en", ""), metadata.get("abstract_en", "")), key=len)
            oa_order = {"unknown": 0, "unknown_or_non_oa": 0, "open_license_hint_unverified": 1, "metadata_indicates_oa": 2}
            merged["oa_status"] = max((previous.get("oa_status", "unknown"), metadata.get("oa_status", "unknown")), key=lambda status: oa_order[status])
            metadata = merged
        match, _, library_conflict = self.library._find_ingest_match(PaperMetadata.from_dict(metadata))
        if not match and not library_conflict:
            fallback, _, _ = self.library._find_ingest_match(PaperMetadata(title=metadata["title"], year=metadata.get("year"), authors=metadata.get("authors", [])))
            if fallback and not any(fallback.get(key) and metadata.get(key) and fallback[key] != metadata[key] for key in ("doi", "pmid")):
                match = fallback
        if library_conflict:
            metadata["library_identity_conflict"] = library_conflict
        paper_id = match["paper_id"] if match else found[0]["library_paper_id"] if found else None
        self.conn.execute("""INSERT INTO radar_candidates VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET
            doi=excluded.doi,pmid=excluded.pmid,metadata_json=excluded.metadata_json,metadata_sha=excluded.metadata_sha,last_seen=excluded.last_seen,library_paper_id=excluded.library_paper_id""",
            (candidate_id, identity, metadata.get("doi"), metadata.get("pmid"), title_key, _json(metadata), _sha(metadata), now, now, paper_id))
        joined = self.conn.execute("SELECT assessment_json FROM radar_direction_candidates WHERE direction_id=? AND candidate_id=?", (direction["direction_id"], candidate_id)).fetchone()
        self.conn.execute("""INSERT OR IGNORE INTO radar_direction_candidates VALUES(?,?,?,'[]',?,0,NULL,?)""",
            (direction["direction_id"], candidate_id, "in_library" if paper_id else "unreviewed", _json(_initial_assessment(metadata, direction["config"])), now))
        if joined and json.loads(joined[0]).get("origin") == "metadata_screen":
            self.conn.execute("UPDATE radar_direction_candidates SET assessment_json=? WHERE direction_id=? AND candidate_id=?", (_json(_initial_assessment(metadata, direction["config"])), direction["direction_id"], candidate_id))
        self.conn.execute("INSERT OR IGNORE INTO radar_discoveries VALUES(?,?,?,?,?,?,?,?)", (scan_id, candidate_id, request["source"], request["lane"], source_metadata["source_record_id"], _json(request), _json(source_metadata), now))
        return candidate_id, not joined, bool(paper_id)

    @root_operation
    @library_write
    def scan(self, payload):
        require_global("radar_scan")
        direction, now = self.direction(payload["direction_id"]), _now()
        if direction["status"] not in {"confirmed", "paused"} or direction["confirmed_revision"] != direction["revision"]:
            raise ValueError("radar_direction_not_confirmed")
        if payload.get("expected_revision", direction["revision"]) != direction["revision"]:
            raise ValueError("radar_direction_conflict")
        mode = payload.get("mode", "discovery")
        if mode not in {"discovery", "incremental"}:
            raise ValueError("radar_scan_mode_invalid")
        config, streams = direction["config"], direction["incremental"]
        requests = []
        for source in config["sources"]:
            if mode == "incremental":
                stream = streams[source]
                requests.append(query_for(config, source, "incremental", stream["watermark"], stream.get("until") or now, stream.get("cursor"), config["page_size"]))
            else:
                lanes = ["recent"] + (["classics"] if config["include_classics"] else []) + (["counter"] if config["counter_terms"] else [])
                requests += [query_for(config, source, lane, window_until=now, page_size=config["page_size"]) for lane in lanes]
        scan_id = "scan_" + uuid.uuid4().hex
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            changed = self.conn.execute("UPDATE radar_directions SET lease_until=? WHERE direction_id=? AND revision=? AND status IN ('confirmed','paused') AND (lease_until IS NULL OR lease_until<=?)",
                ((datetime.fromisoformat(now) + timedelta(minutes=3)).isoformat(), direction["direction_id"], direction["revision"], now)).rowcount
            if not changed:
                raise ValueError("radar_scan_running_or_changed")
            self.conn.execute("UPDATE radar_scans SET status='interrupted',finished_at=? WHERE direction_id=? AND status='running'", (now, direction["direction_id"]))
            self.conn.execute("INSERT INTO radar_scans VALUES(?,?,?,?,?,NULL,'running',?,?,?)", (scan_id, direction["direction_id"], direction["revision"], mode, now, _json(config), _json(requests), '{}'))
        pages, errors, new_ids, known = [], [], [], 0
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self.fetcher, request): request for request in requests}
                for future in as_completed(futures):
                    request = futures[future]
                    try:
                        pages.append((request, future.result()))
                    except Exception as error:
                        errors.append({"source": request["source"], "lane": request["lane"], "error": type(error).__name__, "detail": str(error)[:200]})
            coverage = []
            with self.conn:
                for request, page in pages:
                    for metadata in page["items"]:
                        candidate_id, fresh, existing = self._candidate(metadata, direction, scan_id, request, now)
                        if fresh and not existing:
                            new_ids.append(candidate_id)
                        known += int(existing)
                    coverage.append({"source": request["source"], "lane": request["lane"], "total": page["total"], "returned": page["returned"], "has_more": page["has_more"], "skipped_invalid": page["skipped_invalid"]})
                    if mode == "incremental":
                        streams[request["source"]] = ({"watermark": request["window_from"], "until": request["window_until"], "cursor": page["next_cursor"]} if page["has_more"]
                            else {"watermark": (datetime.fromisoformat(request["window_until"]) - timedelta(days=1)).isoformat()})
                status = "failed" if not pages else "partial" if errors or any(row["has_more"] or row["skipped_invalid"] for row in coverage) else "complete"
                summary = {"new_candidate_ids": sorted(set(new_ids)), "already_in_library_hits": known, "coverage": coverage, "errors": errors,
                           "discovery_is_bounded": mode == "discovery", "notice": "候选尚需评估；仅摘要或元数据初筛。未启动下载、解析或正式入库。"}
                finished = _now()
                continuing = mode == "incremental" and any(stream.get("cursor") for stream in streams.values())
                delay = timedelta(minutes=1) if continuing else timedelta(hours=config["interval_hours"])
                self.conn.execute("UPDATE radar_scans SET finished_at=?,status=?,summary_json=? WHERE scan_id=?", (finished, status, _json(summary), scan_id))
                self.conn.execute("UPDATE radar_directions SET incremental_json=?,lease_until=NULL,next_scan_at=?,updated_at=? WHERE direction_id=? AND revision=?",
                    (_json(streams), (datetime.fromisoformat(finished) + delay).isoformat() if config["interval_hours"] else None,
                     finished, direction["direction_id"], direction["revision"]))
        except Exception:
            with self.conn:
                self.conn.execute("UPDATE radar_scans SET status='failed',finished_at=? WHERE scan_id=?", (_now(), scan_id))
                self.conn.execute("UPDATE radar_directions SET lease_until=NULL WHERE direction_id=?", (direction["direction_id"],))
            raise
        return {"scan_id": scan_id, "direction_id": direction["direction_id"], "status": status, **summary}

    def candidates(self, payload):
        direction = self.direction(payload["direction_id"])
        limit, offset = payload.get("limit", 25), payload.get("offset", 0)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError("radar_page_invalid")
        state = payload.get("state")
        conditions, params = "dc.direction_id=?", [direction["direction_id"]]
        if state:
            conditions += " AND dc.state=?"
            params.append(state)
        if payload.get("candidate_id"):
            conditions += " AND c.candidate_id=?"
            params.append(payload["candidate_id"])
        rows = self.conn.execute("SELECT c.*,dc.state,dc.feedback_json,dc.assessment_json,dc.assessment_revision,dc.notified_at FROM radar_candidates c JOIN radar_direction_candidates dc USING(candidate_id) WHERE " + conditions + """ ORDER BY
            (dc.state IN ('irrelevant','later')) ASC,(dc.state='relevant') DESC,
            (json_extract(dc.assessment_json,'$.verdict')='relevant' AND json_extract(dc.assessment_json,'$.metadata_sha')=c.metadata_sha AND json_extract(dc.assessment_json,'$.config_sha')=?) DESC,
            c.first_seen DESC,c.candidate_id LIMIT ? OFFSET ?""", (*params, _sha(direction["config"]), limit, offset)).fetchall()
        candidates = []
        for row in rows:
            value = dict(row)
            for name in ("metadata", "feedback", "assessment"):
                value[name] = json.loads(value.pop(name + "_json"))
            value["assessment_current"] = value["assessment"].get("metadata_sha") == value["metadata_sha"] and value["assessment"].get("config_sha") == _sha(direction["config"])
            value["discoveries"] = [dict(item) | {"query": json.loads(item["query_json"])} for item in self.conn.execute("SELECT d.scan_id,d.source,d.lane,d.record_id,d.query_json,d.discovered_at FROM radar_discoveries d JOIN radar_scans s USING(scan_id) WHERE d.candidate_id=? AND s.direction_id=? ORDER BY d.discovered_at DESC", (value["candidate_id"], direction["direction_id"]))]
            candidates.append(value)
        total = self.conn.execute("SELECT COUNT(*) FROM radar_candidates c JOIN radar_direction_candidates dc USING(candidate_id) WHERE " + conditions, params).fetchone()[0]
        scans = [dict(row) | {"summary": json.loads(row["summary_json"])} for row in self.conn.execute("SELECT scan_id,mode,started_at,finished_at,status,summary_json FROM radar_scans WHERE direction_id=? ORDER BY started_at DESC LIMIT 10", (direction["direction_id"],))]
        return {"direction": direction, "candidates": candidates, "total": total, "offset": offset, "next_offset": offset + limit if offset + limit < total else None, "scans": scans}

    def _membership(self, payload):
        direction = self.direction(payload["direction_id"])
        row = self.conn.execute("SELECT c.*,dc.assessment_revision,dc.state FROM radar_candidates c JOIN radar_direction_candidates dc USING(candidate_id) WHERE c.candidate_id=? AND dc.direction_id=?", (payload["candidate_id"], direction["direction_id"])).fetchone()
        if not row:
            raise ValueError("radar_candidate_not_found")
        return direction, row, json.loads(row["metadata_json"])

    @root_operation
    @library_write
    def assess(self, payload):
        require_global("radar_assess")
        direction, row, metadata = self._membership(payload)
        if payload.get("metadata_sha") != row["metadata_sha"] or payload.get("config_revision") != direction["revision"]:
            raise ValueError("radar_assessment_source_changed")
        assessment = payload.get("assessment")
        if not isinstance(assessment, dict) or assessment.get("verdict") not in {"relevant", "uncertain", "not_relevant"}:
            raise ValueError("radar_assessment_invalid")
        clean = {"verdict": assessment["verdict"]}
        discoveries = [dict(item) for item in self.conn.execute("SELECT d.source,d.record_id,d.scan_id,d.metadata_json FROM radar_discoveries d JOIN radar_scans s USING(scan_id) WHERE d.candidate_id=? AND s.direction_id=? ORDER BY d.discovered_at DESC", (row["candidate_id"], direction["direction_id"]))]
        for field in ("relevance", "design", "reading_value", "timeliness"):
            item = assessment.get(field)
            if not isinstance(item, dict):
                raise ValueError("radar_assessment_dimension_required")
            evidence = item.get("evidence", [])
            if not isinstance(evidence, list) or not 1 <= len(evidence) <= 5:
                raise ValueError("radar_assessment_evidence_required")
            verified = []
            for entry in evidence:
                if not isinstance(entry, dict) or entry.get("field") not in {"title", "abstract_en", "publication_types", "publication_date", "year"}:
                    raise ValueError("radar_assessment_evidence_invalid")
                quote = _text(entry.get("quote"), 500, True)
                source = metadata.get(entry["field"])
                if quote not in (source if isinstance(source, str) else _json(source)):
                    raise ValueError("radar_assessment_quote_not_found")
                sources = {}
                for discovery in discoveries:
                    original = json.loads(discovery["metadata_json"])
                    value = original.get(entry["field"])
                    if quote in (value if isinstance(value, str) else _json(value)):
                        sources.setdefault((discovery["source"], discovery["record_id"]), {key: discovery[key] for key in ("source", "record_id", "scan_id")} | {"metadata_sha": _sha(original)})
                if not sources:
                    raise ValueError("radar_assessment_source_unavailable")
                verified.append({"field": entry["field"], "quote": quote, "sources": list(sources.values())})
            clean[field] = {"reason": _text(item.get("reason"), 1600, True), "evidence": verified}
        clean.update({"origin": "ai", "basis": "abstract_only" if metadata.get("abstract_en") else "metadata_only", "limitations": _terms(assessment.get("limitations", []), 10),
                      "metadata_sha": row["metadata_sha"], "config_sha": _sha(direction["config"]), "assessed_at": _now()})
        with self.conn:
            changed = self.conn.execute("UPDATE radar_direction_candidates SET assessment_json=?,assessment_revision=assessment_revision+1,updated_at=? WHERE direction_id=? AND candidate_id=? AND assessment_revision=?",
                (_json(clean), _now(), direction["direction_id"], row["candidate_id"], payload.get("expected_revision"))).rowcount
            if not changed:
                raise ValueError("radar_assessment_conflict")
        return {"candidate_id": row["candidate_id"], "assessment": clean, "assessment_revision": row["assessment_revision"] + 1}

    @root_operation
    @library_write
    def feedback(self, payload):
        direction, row, _ = self._membership(payload)
        state = payload.get("state")
        if state not in {"relevant", "irrelevant", "later", "unreviewed"} or row["library_paper_id"]:
            raise ValueError("radar_feedback_state_invalid")
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            history = json.loads(self.conn.execute("SELECT feedback_json FROM radar_direction_candidates WHERE direction_id=? AND candidate_id=?", (direction["direction_id"], row["candidate_id"])).fetchone()[0])
            history.append({"state": state, "reason": _text(payload.get("reason", ""), 2000), "at": _now()})
            self.conn.execute("UPDATE radar_direction_candidates SET state=?,feedback_json=?,updated_at=? WHERE direction_id=? AND candidate_id=?",
                (state, _json(history), _now(), direction["direction_id"], row["candidate_id"]))
        return {"candidate_id": row["candidate_id"], "state": state, "feedback": history}

    @root_operation
    @library_write
    def admit(self, payload):
        require_global("radar_admit")
        if payload.get("confirmed") is not True:
            raise ValueError("radar_admission_confirmation_required")
        direction, row, metadata = self._membership(payload)
        if payload.get("metadata_sha") != row["metadata_sha"]:
            raise ValueError("radar_candidate_changed")
        if metadata.get("identity_conflict") or metadata.get("library_identity_conflict"):
            raise ValueError("radar_identity_conflict_requires_review")
        folder = payload.get("folder_id")
        if folder:
            self.library._require_folder(folder)
        incoming = PaperMetadata.from_dict(metadata)
        if row["library_paper_id"]:
            incoming.library_key = self.library.get_item(row["library_paper_id"])["library_key"]
        result = self.library.ingest(incoming)
        if result.get("dedupe") == "conflict":
            raise ValueError("radar_identity_conflict_requires_review")
        paper_id = result["paper_id"]
        if folder and result.get("created"):
            self.library.move_items([paper_id], folder)
        with self.conn:
            self.conn.execute("UPDATE radar_candidates SET library_paper_id=? WHERE candidate_id=?", (paper_id, row["candidate_id"]))
            self.conn.execute("UPDATE radar_direction_candidates SET state='admitted',updated_at=? WHERE direction_id=? AND candidate_id=?", (_now(), direction["direction_id"], row["candidate_id"]))
        return {"paper_id": paper_id, "candidate_id": row["candidate_id"], "ingest": result,
                "next_action": "打开本篇 chat 补充摘要、取得合规 PDF 并继续精读；发现或纳入本身不自动下载。"}

    @root_operation
    @library_write
    def notifications(self, payload):
        require_global("radar_notifications")
        rows = self.conn.execute("SELECT dc.*,c.metadata_json,c.metadata_sha,c.library_paper_id,d.config_json FROM radar_direction_candidates dc JOIN radar_candidates c USING(candidate_id) JOIN radar_directions d USING(direction_id) WHERE dc.notified_at IS NULL AND dc.state NOT IN ('irrelevant','later','admitted','in_library')").fetchall()
        fresh = []
        for row in rows:
            assessment, config = json.loads(row["assessment_json"]), json.loads(row["config_json"])
            if row["library_paper_id"] or assessment.get("verdict") != "relevant" or assessment.get("metadata_sha") != row["metadata_sha"] or assessment.get("config_sha") != _sha(config):
                continue
            fresh.append({"direction_id": row["direction_id"], "candidate_id": row["candidate_id"], "title": json.loads(row["metadata_json"])["title"]})
        if payload.get("acknowledge") is True:
            with self.conn:
                self.conn.executemany("UPDATE radar_direction_candidates SET notified_at=? WHERE direction_id=? AND candidate_id=?", [(_now(), row["direction_id"], row["candidate_id"]) for row in fresh])
        return {"new_relevant_candidates": fresh, "unchanged_is_quiet": True}

    def tick(self):
        require_global("radar_tick")
        now = _now()
        row = self.conn.execute("SELECT direction_id,revision FROM radar_directions WHERE status='confirmed' AND next_scan_at<=? AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_scan_at LIMIT 1", (now, now)).fetchone()
        return self.scan({"direction_id": row[0], "expected_revision": row[1], "mode": "incremental"}) if row else {"status": "idle"}


def execute(library, payload):
    service = RadarService(library)
    action = payload.get("action")
    if action == "list":
        return service.list()
    if action == "preview":
        return service.preview(payload["direction_id"])
    if action == "tick":
        return service.tick()
    if action in {"draft", "confirm", "pause", "scan", "candidates", "assess", "feedback", "admit", "notifications"}:
        return getattr(service, action)(payload)
    raise ValueError("radar_action_invalid")
