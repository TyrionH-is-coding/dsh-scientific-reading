"""可重建的 SQLite typed search 索引与查询辅助。"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from typing import Any


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _schema_object_exists(
    conn: sqlite3.Connection, object_type: str, name: str
) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
        (object_type, name),
    ).fetchone() is not None


def ensure_search_schema(conn: sqlite3.Connection) -> None:
    """幂等创建派生索引；仅首次建表时回填既有主记录。"""
    needs_backfill = not (
        _schema_object_exists(conn, "table", "library_search_documents")
        and _schema_object_exists(conn, "table", "library_search_fts")
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_search_documents (
          document_id TEXT PRIMARY KEY,
          paper_id TEXT NOT NULL REFERENCES items(paper_id) ON DELETE CASCADE,
          content_type TEXT NOT NULL CHECK (
            content_type IN ('metadata','abstract_en','abstract_zh','conclusion')
          ),
          content TEXT NOT NULL,
          conclusion_id TEXT,
          basis TEXT
        );
        CREATE INDEX IF NOT EXISTS library_search_documents_paper
          ON library_search_documents(paper_id, content_type);
        CREATE VIRTUAL TABLE IF NOT EXISTS library_search_fts USING fts5(
          document_id UNINDEXED,
          content,
          tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS library_search_documents_ai
        AFTER INSERT ON library_search_documents BEGIN
          INSERT INTO library_search_fts(document_id, content)
          VALUES (new.document_id, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS library_search_documents_au
        AFTER UPDATE ON library_search_documents BEGIN
          DELETE FROM library_search_fts WHERE document_id=old.document_id;
          INSERT INTO library_search_fts(document_id, content)
          VALUES (new.document_id, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS library_search_documents_ad
        AFTER DELETE ON library_search_documents BEGIN
          DELETE FROM library_search_fts WHERE document_id=old.document_id;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_items_ai
        AFTER INSERT ON items BEGIN
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          VALUES (
            'metadata:' || new.paper_id,
            new.paper_id,
            'metadata',
            trim(
              'Title: ' || coalesce(new.title, '') || char(10) ||
              'Authors: ' || coalesce(new.authors_json, '') || char(10) ||
              'DOI: ' || coalesce(new.doi, '') || char(10) ||
              'PMID: ' || coalesce(new.pmid, '') || char(10) ||
              'Year: ' || coalesce(CAST(new.year AS TEXT), '') || char(10) ||
              'Journal: ' || coalesce(new.journal, '') || char(10) ||
              'Source: ' || coalesce(new.source_url, '')
            ),
            NULL,
            NULL
          ) ON CONFLICT(document_id) DO UPDATE SET
            paper_id=excluded.paper_id,
            content_type=excluded.content_type,
            content=excluded.content,
            conclusion_id=excluded.conclusion_id,
            basis=excluded.basis;
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          SELECT 'abstract_en:' || new.paper_id, new.paper_id, 'abstract_en',
                 new.abstract_en, NULL, NULL
          WHERE trim(coalesce(new.abstract_en, '')) <> ''
          ON CONFLICT(document_id) DO UPDATE SET content=excluded.content;
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          SELECT 'abstract_zh:' || new.paper_id, new.paper_id, 'abstract_zh',
                 new.abstract_zh, NULL, NULL
          WHERE trim(coalesce(new.abstract_zh, '')) <> ''
          ON CONFLICT(document_id) DO UPDATE SET content=excluded.content;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_items_au
        AFTER UPDATE OF title, authors_json, doi, pmid, year, journal,
                        source_url, abstract_en, abstract_zh ON items BEGIN
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          VALUES (
            'metadata:' || new.paper_id,
            new.paper_id,
            'metadata',
            trim(
              'Title: ' || coalesce(new.title, '') || char(10) ||
              'Authors: ' || coalesce(new.authors_json, '') || char(10) ||
              'DOI: ' || coalesce(new.doi, '') || char(10) ||
              'PMID: ' || coalesce(new.pmid, '') || char(10) ||
              'Year: ' || coalesce(CAST(new.year AS TEXT), '') || char(10) ||
              'Journal: ' || coalesce(new.journal, '') || char(10) ||
              'Source: ' || coalesce(new.source_url, '')
            ),
            NULL,
            NULL
          ) ON CONFLICT(document_id) DO UPDATE SET
            paper_id=excluded.paper_id,
            content_type=excluded.content_type,
            content=excluded.content,
            conclusion_id=excluded.conclusion_id,
            basis=excluded.basis;
          DELETE FROM library_search_documents
          WHERE document_id='abstract_en:' || old.paper_id
            AND trim(coalesce(new.abstract_en, '')) = '';
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          SELECT 'abstract_en:' || new.paper_id, new.paper_id, 'abstract_en',
                 new.abstract_en, NULL, NULL
          WHERE trim(coalesce(new.abstract_en, '')) <> ''
          ON CONFLICT(document_id) DO UPDATE SET content=excluded.content;
          DELETE FROM library_search_documents
          WHERE document_id='abstract_zh:' || old.paper_id
            AND trim(coalesce(new.abstract_zh, '')) = '';
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          SELECT 'abstract_zh:' || new.paper_id, new.paper_id, 'abstract_zh',
                 new.abstract_zh, NULL, NULL
          WHERE trim(coalesce(new.abstract_zh, '')) <> ''
          ON CONFLICT(document_id) DO UPDATE SET content=excluded.content;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_items_ad
        AFTER DELETE ON items BEGIN
          DELETE FROM library_search_documents WHERE paper_id=old.paper_id;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_conclusions_ai
        AFTER INSERT ON review_conclusions BEGIN
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          VALUES (
            'conclusion:' || new.conclusion_id,
            new.paper_id,
            'conclusion',
            trim(new.conclusion_type || char(10) || new.conclusion_text),
            new.conclusion_id,
            new.basis
          ) ON CONFLICT(document_id) DO UPDATE SET
            paper_id=excluded.paper_id,
            content_type=excluded.content_type,
            content=excluded.content,
            conclusion_id=excluded.conclusion_id,
            basis=excluded.basis;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_conclusions_au
        AFTER UPDATE OF paper_id, conclusion_type, conclusion_text, basis
        ON review_conclusions BEGIN
          INSERT INTO library_search_documents
            (document_id, paper_id, content_type, content, conclusion_id, basis)
          VALUES (
            'conclusion:' || new.conclusion_id,
            new.paper_id,
            'conclusion',
            trim(new.conclusion_type || char(10) || new.conclusion_text),
            new.conclusion_id,
            new.basis
          ) ON CONFLICT(document_id) DO UPDATE SET
            paper_id=excluded.paper_id,
            content_type=excluded.content_type,
            content=excluded.content,
            conclusion_id=excluded.conclusion_id,
            basis=excluded.basis;
        END;

        CREATE TRIGGER IF NOT EXISTS library_search_conclusions_ad
        AFTER DELETE ON review_conclusions BEGIN
          DELETE FROM library_search_documents
          WHERE document_id='conclusion:' || old.conclusion_id;
        END;
        """
    )
    if needs_backfill:
        rebuild_search_index(conn)


def rebuild_search_index(conn: sqlite3.Connection) -> dict[str, int]:
    """从 SQLite 主记录重建派生 rows；不改 items/review_conclusions。"""
    conn.execute("DELETE FROM library_search_documents")
    conn.execute(
        "INSERT INTO library_search_documents "
        "(document_id, paper_id, content_type, content, conclusion_id, basis) "
        "SELECT 'metadata:' || paper_id, paper_id, 'metadata', "
        "trim('Title: ' || coalesce(title, '') || char(10) || "
        "'Authors: ' || coalesce(authors_json, '') || char(10) || "
        "'DOI: ' || coalesce(doi, '') || char(10) || "
        "'PMID: ' || coalesce(pmid, '') || char(10) || "
        "'Year: ' || coalesce(CAST(year AS TEXT), '') || char(10) || "
        "'Journal: ' || coalesce(journal, '') || char(10) || "
        "'Source: ' || coalesce(source_url, '')), NULL, NULL FROM items"
    )
    conn.execute(
        "INSERT INTO library_search_documents "
        "(document_id, paper_id, content_type, content, conclusion_id, basis) "
        "SELECT 'abstract_en:' || paper_id, paper_id, 'abstract_en', "
        "abstract_en, NULL, NULL FROM items "
        "WHERE trim(coalesce(abstract_en, '')) <> ''"
    )
    conn.execute(
        "INSERT INTO library_search_documents "
        "(document_id, paper_id, content_type, content, conclusion_id, basis) "
        "SELECT 'abstract_zh:' || paper_id, paper_id, 'abstract_zh', "
        "abstract_zh, NULL, NULL FROM items "
        "WHERE trim(coalesce(abstract_zh, '')) <> ''"
    )
    conn.execute(
        "INSERT INTO library_search_documents "
        "(document_id, paper_id, content_type, content, conclusion_id, basis) "
        "SELECT 'conclusion:' || conclusion_id, paper_id, 'conclusion', "
        "trim(conclusion_type || char(10) || conclusion_text), conclusion_id, basis "
        "FROM review_conclusions"
    )
    return {
        "papers": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "documents": conn.execute(
            "SELECT COUNT(*) FROM library_search_documents"
        ).fetchone()[0],
    }


def _fts_query(query: str) -> str:
    tokens = _TOKEN.findall(query)
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def literal_like_pattern(query: str) -> str:
    return _like_pattern(" ".join(query.strip().split()))


def search_predicate(paper_alias: str, query: str) -> tuple[str, list[str]]:
    """返回 paper 查询条件与参数，同时保留精确字面子串回退。"""
    literal = " ".join(query.strip().split())
    fts = _fts_query(literal)
    matches = ["sd.content LIKE ? ESCAPE '\\' COLLATE NOCASE"]
    parameters = [literal_like_pattern(literal)]
    if fts:
        matches.insert(
            0,
            "sd.document_id IN (SELECT document_id FROM library_search_fts "
            "WHERE library_search_fts MATCH ?)",
        )
        parameters.insert(0, fts)
    return (
        "EXISTS (SELECT 1 FROM library_search_documents sd "
        f"WHERE sd.paper_id={paper_alias}.paper_id AND ("
        + " OR ".join(matches)
        + "))",
        parameters,
    )


def _plain_snippet(content: str, query: str, limit: int = 180) -> str:
    plain = " ".join(content.split())
    if len(plain) <= limit:
        return plain
    folded = plain.casefold()
    position = folded.find(query.casefold())
    if position < 0:
        for token in _TOKEN.findall(query):
            position = folded.find(token.casefold())
            if position >= 0:
                break
    if position < 0:
        position = 0
    start = max(0, position - limit // 3)
    end = min(len(plain), start + limit)
    start = max(0, end - limit)
    return ("…" if start else "") + plain[start:end] + ("…" if end < len(plain) else "")


def fetch_search_matches(
    conn: sqlite3.Connection, query: str, paper_ids: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    ids = tuple(paper_ids)
    if not ids:
        return {}
    fts = _fts_query(query)
    clauses = ["d.content LIKE ? ESCAPE '\\' COLLATE NOCASE"]
    parameters: list[str] = [_like_pattern(" ".join(query.strip().split()))]
    if fts:
        clauses.insert(
            0,
            "d.document_id IN (SELECT document_id FROM library_search_fts "
            "WHERE library_search_fts MATCH ?)",
        )
        parameters.insert(0, fts)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT d.paper_id, d.content_type, d.content, d.conclusion_id, d.basis "
        "FROM library_search_documents d WHERE ("
        + " OR ".join(clauses)
        + f") AND d.paper_id IN ({placeholders}) "
        "ORDER BY CASE d.content_type "
        "WHEN 'metadata' THEN 0 WHEN 'abstract_en' THEN 1 "
        "WHEN 'abstract_zh' THEN 2 ELSE 3 END, d.document_id",
        (*parameters, *ids),
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {paper_id: [] for paper_id in ids}
    for row in rows:
        match: dict[str, Any] = {
            "content_type": row["content_type"],
            "snippet": _plain_snippet(row["content"], query),
        }
        if row["content_type"] == "conclusion":
            match["conclusion_id"] = row["conclusion_id"]
            match["basis"] = row["basis"]
        result[row["paper_id"]].append(match)
    return result
