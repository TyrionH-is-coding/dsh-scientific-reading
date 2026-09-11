"""以 SQLite 的稳定 paperId 绑定原生 chat；历史文本仍由 DSH 保存。"""
from __future__ import annotations

import json
import uuid

from .data_guard import root_operation
from .library_service import LibraryService, _now
from .scope import current_scope, library_write, require_global


def create_schema(conn):
    conn.execute("""CREATE TABLE paper_chats (
        paper_id TEXT PRIMARY KEY REFERENCES items(paper_id),
        session_id TEXT NOT NULL UNIQUE,
        context_json TEXT, context_revision INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE legacy_chats (
        session_id TEXT PRIMARY KEY, folder_id TEXT, label TEXT NOT NULL,
        origin TEXT NOT NULL, created_at TEXT NOT NULL)""")


def validate_schema(conn):
    for table, columns in {
        "paper_chats": {"paper_id", "session_id", "context_json", "context_revision", "created_at", "updated_at"},
        "legacy_chats": {"session_id", "folder_id", "label", "origin", "created_at"},
    }.items():
        if not columns <= {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
            raise ValueError("invalid_v6_schema:" + table)
    indexes = conn.execute("PRAGMA index_list(paper_chats)").fetchall()
    if not any(row[2] and not row[4] and [x[2] for x in conn.execute(f"PRAGMA index_info('{row[1]}')")] == ["session_id"] for row in indexes):
        raise ValueError("invalid_v6_schema:session_unique")


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 300 or any(ord(c) < 32 for c in value):
        raise ValueError("chat_identifier_invalid")
    return value


class PaperChatService:
    def __init__(self, library: LibraryService):
        self.library = library
        self.conn = library.conn
        self.data_root = library.data_root

    def get(self, paper_id):
        from .library_views import LibraryViews
        item = self.library.get_item(paper_id)
        row = self.conn.execute("SELECT * FROM paper_chats WHERE paper_id=?", (paper_id,)).fetchone()
        reviews = [dict(r) for r in self.conn.execute(
            "SELECT parent_session_id,review_session_id,created_at FROM review_sessions WHERE paper_id=? AND review_session_id NOT IN (SELECT session_id FROM paper_chats) ORDER BY created_at", (paper_id,))]
        attachment = self.conn.execute("SELECT sha256 FROM attachments WHERE paper_id=?", (paper_id,)).fetchone()
        figure = json.loads(row["context_json"]) if row and row["context_json"] else None
        if figure and (not attachment or figure["source_pdf_sha256"] != attachment[0]):
            figure = {key: figure[key] for key in ("paper_id", "asset_id", "source_pdf_sha256", "revision")}
            figure.update({"image_status": "source_changed_requires_reselect", "instructions": "PDF 已改变。此图仅为旧选择身份，不得作为当前论文图像或正文证据。请重新打开 Reader 选图。"})
        conclusions = [dict(r) for r in self.conn.execute(
            "SELECT conclusion_id,conclusion_type,conclusion_text,evidence_locator,evidence_json,basis FROM review_conclusions WHERE paper_id=? ORDER BY created_at", (paper_id,))]
        return {"paper_id": paper_id, "session_id": row["session_id"] if row else None,
                "status": "bound" if row else "missing", "paper": item,
                "source_pdf_sha256": attachment[0] if attachment else None,
                "legacy_review_sessions": reviews, "confirmed_conclusions": conclusions,
                "active_figure": figure,
                "context_revision": row["context_revision"] if row else 0,
                "research_fields": LibraryViews(self.library).values(paper_id),
                "evidence_boundary": "会话中的用户讨论与模型推断不是论文事实；论文结论须核对原文证据。"}

    @root_operation
    @library_write
    def ensure(self, paper_id):
        require_global("paper_chat_bind")
        self.library.get_item(paper_id)
        now = _now()
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO paper_chats(paper_id,session_id,created_at,updated_at) VALUES (?,?,?,?)",
                (paper_id, "session-" + str(uuid.uuid4()), now, now))
            session_id = self.conn.execute("SELECT session_id FROM paper_chats WHERE paper_id=?", (paper_id,)).fetchone()[0]
            self.conn.execute("INSERT OR IGNORE INTO review_sessions VALUES (?,?,?,?,?)", (session_id, paper_id, session_id, now, now))
        return {**self.get(paper_id), "created": cursor.rowcount == 1}

    def scope(self, session_id):
        require_global("paper_chat_scope")
        row = self.conn.execute("SELECT paper_id FROM paper_chats WHERE session_id=?", (_identifier(session_id),)).fetchone()
        legacy = not row and (self.conn.execute("SELECT 1 FROM legacy_chats WHERE session_id=?", (session_id,)).fetchone()
                              or self.conn.execute("SELECT 1 FROM review_sessions WHERE review_session_id=?", (session_id,)).fetchone())
        return {"paper_id": row[0] if row else None, "legacy_read_only": bool(legacy)}

    @root_operation
    @library_write
    def register_legacy(self, entries):
        require_global("legacy_chat_register")
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError("legacy_chats_invalid")
        with self.conn:
            for entry in entries:
                self.conn.execute("INSERT OR IGNORE INTO legacy_chats VALUES (?,?,?,?,?)", (
                    _identifier(entry["session_id"]), entry.get("folder_id"),
                    str(entry.get("label") or "旧分类讨论"), "v0.1-category", _now()))
        return self.legacy()

    def legacy(self):
        require_global("legacy_chat_list")
        return {"sessions": [dict(r) for r in self.conn.execute("SELECT * FROM legacy_chats ORDER BY created_at")],
                "reviews": [dict(r) for r in self.conn.execute("""SELECT DISTINCT r.review_session_id AS session_id,r.paper_id,
                    '旧单篇 Review · ' || i.title AS label,'v0.1-review' AS origin,r.created_at
                    FROM review_sessions r JOIN items i USING(paper_id)
                    WHERE r.review_session_id NOT IN (SELECT session_id FROM paper_chats) ORDER BY r.created_at""")],
                "read_only": True, "evidence_boundary": "旧分类会话可能混合多篇论文讨论，未自动归属到任何单篇 chat。"}


def execute(library, payload):
    service = PaperChatService(library)
    action = payload.get("action")
    if action in {"figure_select", "figure_delivered"}:
        from .figure_context import FigureContextService
        figures = FigureContextService(library)
        return figures.select(payload) if action == "figure_select" else figures.delivered(payload)
    if action in {"selection_save", "selection_get"}:
        require_global("chat_selection")
        if action == "selection_save":
            selection, question = payload.get("selection"), payload.get("question")
            if not isinstance(selection, list) or not 1 <= len(selection) <= 20 or not isinstance(question, str) or not question.strip() or len(question) > 8000:
                raise ValueError("chat_selection_invalid")
            ids = [row["paper_id"] for row in selection]
            if len(set(ids)) != len(ids):
                raise ValueError("chat_selection_invalid")
            for paper_id in ids:
                if not service.get(paper_id)["session_id"]:
                    raise ValueError("paper_chat_missing")
            saved = {"selection": [{"paper_id": p} for p in ids], "question": question, "updated_at": _now()}
            with library.conn:
                library.conn.execute("INSERT INTO library_meta VALUES ('chat.selection',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(saved, ensure_ascii=False),))
        row = library.conn.execute("SELECT value FROM library_meta WHERE key='chat.selection'").fetchone()
        return json.loads(row[0]) if row else {"selection": [], "question": ""}
    if action == "get":
        return service.get(payload["paper_id"])
    if action == "ensure":
        return service.ensure(payload["paper_id"])
    if action == "scope":
        return service.scope(payload["session_id"])
    if action == "context_for_session":
        scope = current_scope()
        session_id = scope["scopeSessionId"] if scope and scope["scopeFolderId"] == "__paper__" else payload["session_id"]
        row = library.conn.execute("SELECT paper_id FROM paper_chats WHERE session_id=?", (_identifier(session_id),)).fetchone()
        if row is None:
            raise ValueError("paper_chat_missing")
        return service.get(row[0])
    if action == "legacy_register":
        return service.register_legacy(payload["entries"])
    if action == "legacy_list":
        return service.legacy()
    raise ValueError("paper_chat_action_invalid")
