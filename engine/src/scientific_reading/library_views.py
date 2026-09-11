"""显示方案和研究字段共用 SQLite；列名仅是稳定字段 ID 的显示属性。"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from .data_guard import root_operation
from .library_service import _now
from .personal_records import USER_FIELDS
from .scope import library_write, require_global
from .ui_themes import THEMES, preset


BUILTINS = (
    ("title", "文献名"), ("folder", "分类"), ("reading_state", "阅读进度"), ("project_relevance", "与课题的关系"),
    ("next_action", "下一步"), ("pdf", "PDF"), ("reader", "Reader"), ("reading_records", "阅读成果"), ("assets", "图表索引"),
    ("year", "年份"), ("journal", "期刊"), ("tags", "标签"), ("processing", "处理进度"), ("personal_updated_at", "个人记录更新时间"),
    ("understanding_level", "个人理解程度"), ("personal_thoughts", "个人思考"), ("user_notes", "用户笔记"),
    ("authors", "作者"), ("doi", "DOI"), ("pmid", "PMID"), ("abstract_en", "Abstract (EN)"), ("abstract_zh", "Abstract (ZH)"),
    ("source_url", "文献链接"), ("created_at", "入库时间"), ("updated_at", "处理更新时间"), ("paper_id", "文献 ID"), ("row_token", "行标识"),
)


def create_schema(conn):
    conn.execute("""CREATE TABLE research_fields(field_id TEXT PRIMARY KEY,label TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE research_values(paper_id TEXT NOT NULL REFERENCES items(paper_id),
        field_id TEXT NOT NULL REFERENCES research_fields(field_id),value TEXT NOT NULL,
        origin TEXT NOT NULL CHECK(origin IN ('manual','ai')),evidence_json TEXT NOT NULL,
        revision INTEGER NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(paper_id,field_id))""")
    conn.execute("""CREATE TABLE display_schemes(scheme_id TEXT PRIMARY KEY,kind TEXT NOT NULL,
        scope_folder_id TEXT NOT NULL,name TEXT NOT NULL,config_json TEXT NOT NULL,
        revision INTEGER NOT NULL,updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE display_defaults(kind TEXT NOT NULL,scope_folder_id TEXT NOT NULL,
        scheme_id TEXT NOT NULL REFERENCES display_schemes(scheme_id),PRIMARY KEY(kind,scope_folder_id))""")


def validate_schema(conn):
    for table, columns in {
        "research_fields": {"field_id", "label", "description", "created_at"},
        "research_values": {"paper_id", "field_id", "value", "origin", "evidence_json", "revision", "updated_at"},
        "display_schemes": {"scheme_id", "kind", "scope_folder_id", "name", "config_json", "revision", "updated_at"},
        "display_defaults": {"kind", "scope_folder_id", "scheme_id"},
    }.items():
        if not columns <= {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            raise ValueError("invalid_v6_schema:" + table)


def catalog(conn):
    hidden = {"paper_id", "row_token", "authors", "doi", "pmid", "abstract_en", "abstract_zh", "source_url", "created_at", "updated_at"}
    rows = [{"field_id": field, "key": label, "label": label, "editable": field in USER_FIELDS.values(), "custom": False, "default_hidden": field in hidden}
            for field, label in BUILTINS]
    rows.extend({"field_id": row[0], "key": row[0], "label": row[1], "description": row[2], "editable": True, "custom": True}
                for row in conn.execute("SELECT field_id,label,description FROM research_fields ORDER BY created_at,field_id"))
    return rows


def xlsx_columns(conn, scope_folder_id=""):
    fields = catalog(conn)
    default = conn.execute("""SELECT s.config_json FROM display_defaults d JOIN display_schemes s USING(scheme_id)
        WHERE d.kind='xlsx' AND d.scope_folder_id IN (?, '') ORDER BY (d.scope_folder_id=?) DESC LIMIT 1""",
                           (scope_folder_id, scope_folder_id)).fetchone()
    config = json.loads(default[0]) if default else {"columns": []}
    by_id = {row["field_id"]: row for row in fields}
    configured = config["columns"]
    seen = {row["field_id"] for row in configured}
    return [{**by_id[row["field_id"]], **row} for row in configured if row["field_id"] in by_id] + [row for row in fields if row["field_id"] not in seen]


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 80 or any(ord(c) < 32 for c in value):
        raise ValueError("view_label_invalid")
    return value.strip()


class LibraryViews:
    def __init__(self, library):
        self.library, self.conn, self.data_root = library, library.conn, library.data_root

    def theme(self):
        row = self.conn.execute("SELECT value FROM library_meta WHERE key='display.theme'").fetchone()
        return {**preset(row[0] if row else None), "custom": bool(row), "presets": list(THEMES)}

    @root_operation
    @library_write
    def theme_save(self, payload):
        require_global("display_theme_save")
        theme = payload.get("preset")
        if not isinstance(theme, str) or theme not in {item["id"] for item in THEMES}:
            raise ValueError("display_theme_invalid")
        with self.conn:
            self.conn.execute("INSERT INTO library_meta(key,value) VALUES('display.theme',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (theme,))
        return self.theme()

    def values(self, paper_id):
        item = self.library.get_item(paper_id)
        values = []
        attachment = self.conn.execute("SELECT sha256 FROM attachments WHERE paper_id=?", (paper_id,)).fetchone()
        for row in self.conn.execute("SELECT * FROM research_values WHERE paper_id=?", (paper_id,)):
            value = dict(row)
            value["evidence"] = json.loads(value.pop("evidence_json"))
            value["source_matches_current"] = all(
                hashlib.sha256((item.get("abstract_" + entry.get("language", "")) or "").encode()).hexdigest() == entry.get("sha256")
                if entry.get("kind") == "abstract" else bool(attachment and attachment[0] == entry.get("source_sha256"))
                for entry in value["evidence"])
            values.append(value)
        return {"paper_id": paper_id, "fields": [r for r in catalog(self.conn) if r["custom"]], "values": values,
                "abstract_sources": {language: {"sha256": hashlib.sha256(item["abstract_" + language].encode()).hexdigest()}
                                     for language in ("en", "zh") if item.get("abstract_" + language)}}

    @root_operation
    @library_write
    def field_save(self, payload):
        require_global("research_field_define")
        label = _label(payload.get("label"))
        if label in dict(BUILTINS).values():
            raise ValueError("research_field_label_duplicate")
        description = payload.get("description", "")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("research_field_description_invalid")
        field_id = payload.get("field_id")
        with self.conn:
            if field_id:
                if not self.conn.execute("SELECT 1 FROM research_fields WHERE field_id=?", (field_id,)).fetchone():
                    raise ValueError("research_field_missing")
                self.conn.execute("UPDATE research_fields SET label=?,description=? WHERE field_id=?", (label, description, field_id))
            else:
                field_id = "custom_" + uuid.uuid4().hex
                self.conn.execute("INSERT INTO research_fields VALUES(?,?,?,?)", (field_id, label, description, _now()))
        return {"field_id": field_id, "label": label, "description": description}

    def _evidence(self, paper_id, evidence):
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError("research_evidence_required")
        item = self.library.get_item(paper_id)
        for entry in evidence:
            if not isinstance(entry, dict):
                raise ValueError("research_evidence_invalid")
            if entry.get("kind") == "abstract":
                if entry.get("language") not in {"en", "zh"}:
                    raise ValueError("research_evidence_invalid")
                text = item.get("abstract_" + entry["language"]) or ""
                quote = entry.get("quote")
                if not isinstance(quote, str) or not 1 <= len(quote) <= 500 or quote not in text or hashlib.sha256(text.encode()).hexdigest() != entry.get("sha256"):
                    raise ValueError("research_abstract_evidence_changed")
            else:
                from .evidence_locator import resolve_locator
                resolve_locator(self.data_root, paper_id, entry)
        return evidence

    @root_operation
    @library_write
    def value_set(self, payload, *, origin):
        if origin == "manual":
            require_global("research_manual_update")
        paper_id, field_id = payload["paper_id"], payload["field_id"]
        self.library.get_item(paper_id)
        if not self.conn.execute("SELECT 1 FROM research_fields WHERE field_id=?", (field_id,)).fetchone():
            raise ValueError("research_field_missing")
        value, expected = payload.get("value"), payload.get("expected_revision")
        if not isinstance(value, str) or len(value) > 32767 or isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ValueError("research_value_invalid")
        evidence = self._evidence(paper_id, payload.get("evidence")) if origin == "ai" else []
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.conn.execute("SELECT revision,origin FROM research_values WHERE paper_id=? AND field_id=?", (paper_id, field_id)).fetchone()
            if (current[0] if current else 0) != expected:
                raise ValueError("research_value_conflict")
            if origin == "ai" and current and current[1] == "manual":
                raise ValueError("research_manual_value_protected")
            self.conn.execute("INSERT INTO research_values VALUES(?,?,?,?,?,?,?) ON CONFLICT(paper_id,field_id) DO UPDATE SET value=excluded.value,origin=excluded.origin,evidence_json=excluded.evidence_json,revision=excluded.revision,updated_at=excluded.updated_at",
                              (paper_id, field_id, value, origin, json.dumps(evidence, ensure_ascii=False), expected + 1, _now()))
            self.conn.execute("UPDATE items SET xlsx_sync_state='pending' WHERE paper_id=?", (paper_id,))
        return self.values(paper_id)

    def schemes(self, kind):
        require_global("display_scheme_list")
        return {"fields": catalog(self.conn), "schemes": [dict(row) | {"config": json.loads(row["config_json"])}
                for row in self.conn.execute("SELECT * FROM display_schemes WHERE kind=? ORDER BY name", (kind,))],
                "defaults": [dict(row) for row in self.conn.execute("SELECT * FROM display_defaults WHERE kind=?", (kind,))]}

    @root_operation
    @library_write
    def scheme_save(self, payload):
        require_global("display_scheme_save")
        kind, folder = payload.get("kind", "xlsx"), payload.get("scope_folder_id") or ""
        if folder and not self.conn.execute("SELECT 1 FROM folders WHERE folder_id=?", (folder,)).fetchone():
            raise ValueError("folder_not_found")
        config = payload.get("config")
        if kind == "reader":
            from .reader_appearance import validate
            config = validate(config)
        elif kind == "xlsx":
            if not isinstance(config, dict) or set(config) != {"columns"} or not isinstance(config["columns"], list):
                raise ValueError("display_scheme_invalid")
            fields = {row["field_id"]: row for row in catalog(self.conn)}
            seen, labels = set(), set()
            for column in config["columns"]:
                if not isinstance(column, dict) or not set(column) <= {"field_id", "label", "hidden", "width", "wrap"} or column.get("field_id") not in fields or column["field_id"] in seen:
                    raise ValueError("display_columns_invalid")
                seen.add(column["field_id"])
                label = _label(column.get("label", fields[column["field_id"]]["label"]))
                if label in labels or any(key in column and not isinstance(column[key], bool) for key in ("hidden", "wrap")):
                    raise ValueError("display_columns_invalid")
                if "width" in column and (isinstance(column["width"], bool) or not isinstance(column["width"], (float, int)) or not 6 <= column["width"] <= 120):
                    raise ValueError("display_column_width_invalid")
                labels.add(label)
            if labels & {row["label"] for field, row in fields.items() if field not in seen}:
                raise ValueError("display_column_label_duplicate")
        else:
            raise ValueError("display_scheme_kind_invalid")
        scheme_id, name = payload.get("scheme_id") or "view_" + uuid.uuid4().hex, _label(payload.get("name"))
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            current = self.conn.execute("SELECT revision,kind,scope_folder_id FROM display_schemes WHERE scheme_id=?", (scheme_id,)).fetchone()
            if current and (current[1], current[2]) != (kind, folder):
                raise ValueError("display_scheme_scope_mismatch")
            if payload.get("expected_revision", 0) != (current[0] if current else 0):
                raise ValueError("display_scheme_conflict")
            self.conn.execute("INSERT INTO display_schemes VALUES(?,?,?,?,?,?,?) ON CONFLICT(scheme_id) DO UPDATE SET name=excluded.name,config_json=excluded.config_json,revision=excluded.revision,updated_at=excluded.updated_at",
                              (scheme_id, kind, folder, name, json.dumps(config, ensure_ascii=False), (current[0] if current else 0) + 1, _now()))
        return {**self.schemes(kind), "saved_scheme_id": scheme_id}

    @root_operation
    @library_write
    def scheme_default(self, payload):
        require_global("display_scheme_default")
        kind, folder, scheme_id = payload.get("kind", "xlsx"), payload.get("scope_folder_id") or "", payload.get("scheme_id")
        if kind not in {"xlsx", "reader"}:
            raise ValueError("display_scheme_kind_invalid")
        if folder and not self.conn.execute("SELECT 1 FROM folders WHERE folder_id=?", (folder,)).fetchone():
            raise ValueError("folder_not_found")
        with self.conn:
            if scheme_id:
                row = self.conn.execute("SELECT 1 FROM display_schemes WHERE scheme_id=? AND kind=? AND scope_folder_id IN ('',?)", (scheme_id, kind, folder)).fetchone()
                if not row:
                    raise ValueError("display_scheme_scope_mismatch")
                self.conn.execute("INSERT INTO display_defaults VALUES(?,?,?) ON CONFLICT(kind,scope_folder_id) DO UPDATE SET scheme_id=excluded.scheme_id", (kind, folder, scheme_id))
            else:
                self.conn.execute("DELETE FROM display_defaults WHERE kind=? AND scope_folder_id=?", (kind, folder))
        return self.schemes(kind)


def execute(library, payload):
    service, action = LibraryViews(library), payload.get("action")
    if action in {"model_policy_get", "model_policy_save"}:
        from . import model_policy
        return model_policy.read(library) if action == "model_policy_get" else model_policy.save(library, payload)
    if action == "reader_context":
        from .reader_context import context
        return context(library, payload)
    if action == "theme_get":
        return service.theme()
    if action == "theme_save":
        return service.theme_save(payload)
    if action == "reader_render":
        from .reader_appearance import render
        return render(library, payload)
    if action == "reader_effective":
        from .reader_appearance import effective
        return effective(library, payload["paper_id"])
    if action == "values":
        return service.values(payload["paper_id"])
    if action in {"value_set", "ai_set"}:
        return service.value_set(payload, origin="ai" if action == "ai_set" else "manual")
    if action == "field_save":
        return service.field_save(payload)
    if action == "schemes":
        return service.schemes(payload.get("kind", "xlsx"))
    if action == "scheme_save":
        return service.scheme_save(payload)
    if action == "scheme_default":
        return service.scheme_default(payload)
    raise ValueError("library_view_action_invalid")
