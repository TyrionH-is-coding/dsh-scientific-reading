"""SQLite-backed literature library for the current DSH workflow."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .identifiers import (
    normalize_arxiv,
    normalize_author,
    normalize_doi,
    normalize_pmid,
    normalize_title,
    stable_paper_id,
)
from .library_schema import migrate_library
from .models import PaperMetadata, StageRecord
from .pdf_validation import validate_pdf
from .workspace import PaperWorkspace, atomic_write_json

MAX_COMPONENT_LENGTH = 120
_WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')
_SAFE_LIBRARY_KEY = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_LIST_ITEMS_UNSET = object()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def library_path(data_root: Path) -> Path:
    return Path(data_root).resolve() / "library.sqlite"


def library_key_for(paper_id: str) -> str:
    """稳定不透明的本地主库条目 key。"""
    digest = hashlib.sha256(paper_id.encode("utf-8")).hexdigest()[:12]
    return f"lib_{digest}"


def _stored_source_url(value: str | None) -> str | None:
    arxiv = normalize_arxiv(value)
    if arxiv:
        return f"https://arxiv.org/abs/{arxiv}"
    return value


class LibraryService:
    """本地文献库服务：条目与附件的写入/查重/读回，全部走 SQLite。"""

    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        migrate_library(self.data_root)
        self.conn = sqlite3.connect(str(library_path(self.data_root)), timeout=1.0)
        self.conn.execute("PRAGMA busy_timeout = 1000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self.conn.close()
            raise RuntimeError("library_foreign_keys_not_enabled")
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    # ── 条目 ────────────────────────────────────────────────────────

    def ingest(self, metadata: PaperMetadata) -> dict[str, Any]:
        """只在本地规范化、查重并提交 skeleton，不触发任何派生工作。"""
        doi = normalize_doi(metadata.doi)
        if metadata.library_key is not None and (
            not isinstance(metadata.library_key, str)
            or not _SAFE_LIBRARY_KEY.fullmatch(metadata.library_key)
        ):
            raise ValueError("library_key_invalid")
        if not metadata.title.strip() and not doi:
            raise ValueError("title_required_without_doi")

        self._begin_ingest_transaction()
        try:
            return self._ingest_in_transaction(metadata, doi)
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def _ingest_in_transaction(
        self, metadata: PaperMetadata, doi: str | None
    ) -> dict[str, Any]:
        existing, dedupe, conflict = self._find_ingest_match(metadata)
        if conflict is not None:
            self.conn.rollback()
            return self._ingest_conflict(conflict)
        if existing is not None:
            self._update_item_from_ingest(existing["paper_id"], metadata)
            return self._ingest_result(existing, created=False, dedupe=dedupe)

        paper_id = self._unique_ingest_paper_id(metadata)
        key = metadata.library_key or library_key_for(paper_id)
        now = _now()
        self.conn.execute(
            "INSERT INTO items (paper_id, library_key, title, authors_json, doi, pmid,"
            " year, journal, source_url, status, created_at, updated_at, abstract_en, abstract_zh)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                paper_id,
                key,
                metadata.title.strip(),
                json.dumps(metadata.authors, ensure_ascii=False),
                doi,
                normalize_pmid(metadata.pmid),
                metadata.year,
                metadata.journal,
                _stored_source_url(metadata.source_url),
                "library_ready",
                now,
                now,
                metadata.abstract_en,
                metadata.abstract_zh,
            ),
        )
        self._index_fulltext(paper_id, metadata)
        self._store_identity_aliases(paper_id, metadata)
        self.conn.commit()
        row = self._select_item(paper_id)
        if row is None:
            raise RuntimeError("library_readback_failed")
        return self._ingest_result(row, created=True, dedupe="none")

    def _begin_ingest_transaction(self) -> None:
        for attempt in range(3):
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                return
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).casefold():
                    raise
                if self.conn.in_transaction:
                    self.conn.rollback()
                if attempt == 2:
                    raise RuntimeError("library_busy") from None
                time.sleep(0.05 * (attempt + 1))

    def check(self, metadata: PaperMetadata) -> dict[str, Any]:
        """只读查重：不写入。返回 dedupe = exact | ambiguous | none（none 表示将新建）。"""
        paper_id = self._paper_id(metadata)
        existing = self._select_item(paper_id)
        if existing is not None:
            return {
                "status": "library_ready",
                "paper_id": paper_id,
                "library_key": existing["library_key"],
                "dedupe": "exact",
            }
        conflict = self._find_conflict(metadata, paper_id)
        if conflict is not None:
            return {
                "status": "ambiguous_reference",
                "paper_id": paper_id,
                "library_key": library_key_for(paper_id),
                "dedupe": "ambiguous",
                "candidate_keys": [conflict],
            }
        return {
            "status": "would_create",
            "paper_id": paper_id,
            "library_key": library_key_for(paper_id),
            "dedupe": "none",
        }
    def ensure_item(self, metadata: PaperMetadata) -> dict[str, Any]:
        """查重 → 写入/更新条目 → 读回验证。

        返回：{status, paper_id, library_key, dedupe}
        - dedupe: "exact" 已存在且一致 | "created" 新建 |
          "ambiguous" 与其他条目冲突（调用方应转 agent gate）
        """
        paper_id = self._paper_id(metadata)
        existing = self._select_item(paper_id)
        if existing is not None:
            # 同一 paper_id：更新元数据后读回
            self._update_item(paper_id, metadata, existing["status"])
            row = self._select_item(paper_id)
            return self._item_result(row, "exact")

        conflict = self._find_conflict(metadata, paper_id)
        if conflict is not None:
            return {
                "status": "ambiguous_reference",
                "paper_id": paper_id,
                "library_key": library_key_for(paper_id),
                "dedupe": "ambiguous",
                "candidate_keys": [conflict],
            }

        key = library_key_for(paper_id)
        now = _now()
        self.conn.execute(
            "INSERT INTO items (paper_id, library_key, title, authors_json, doi, pmid,"
            " year, journal, source_url, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                paper_id, key, metadata.title,
                json.dumps(metadata.authors, ensure_ascii=False),
                normalize_doi(metadata.doi), metadata.pmid,
                metadata.year, metadata.journal, _stored_source_url(metadata.source_url),
                "library_ready", now, now,
            ),
        )
        self._index_fulltext(paper_id, metadata)
        self.conn.commit()
        row = self._select_item(paper_id)
        if row is None:
            raise RuntimeError("library_readback_failed")
        return self._item_result(row, "created")

    def item_by_key(self, library_key: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM items WHERE library_key = ?", (library_key,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def create_folder(self, name: str) -> dict[str, Any]:
        normalized = self._folder_name(name)
        now = _now()
        folder_id = f"folder_{uuid.uuid4().hex}"
        try:
            self.conn.execute(
                "INSERT INTO folders (folder_id, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (folder_id, normalized, now, now),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise ValueError("folder_name_exists") from None
        return {
            "folder_id": folder_id,
            "name": normalized,
            "created_at": now,
            "updated_at": now,
        }

    def rename_folder(self, folder_id: str, name: str) -> dict[str, Any]:
        if not isinstance(folder_id, str) or not folder_id:
            raise ValueError("folder_id_invalid")
        normalized = self._folder_name(name)
        now = _now()
        try:
            cursor = self.conn.execute(
                "UPDATE folders SET name = ?, updated_at = ? WHERE folder_id = ?",
                (normalized, now, folder_id),
            )
            if cursor.rowcount != 1:
                self.conn.rollback()
                raise ValueError("folder_not_found")
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise ValueError("folder_name_exists") from None
        row = self.conn.execute(
            "SELECT * FROM folders WHERE folder_id = ?", (folder_id,)
        ).fetchone()
        return dict(row)

    def list_folders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM folders ORDER BY name COLLATE NOCASE, folder_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def move_items(
        self, paper_ids: tuple[str, ...] | list[str], folder_id: str | None
    ) -> dict[str, Any]:
        ids = self._paper_ids(paper_ids)
        if folder_id is not None:
            if not isinstance(folder_id, str) or not folder_id:
                raise ValueError("folder_id_invalid")
            self._require_folder(folder_id)
        self._require_papers(ids)
        now = _now()
        self.conn.executemany(
            "UPDATE items SET folder_id = ?, updated_at = ? WHERE paper_id = ?",
            ((folder_id, now, paper_id) for paper_id in ids),
        )
        self.conn.commit()
        return {"paper_ids": list(ids), "folder_id": folder_id}

    def add_tags(
        self, paper_ids: tuple[str, ...] | list[str], tags: tuple[str, ...] | list[str]
    ) -> dict[str, Any]:
        ids = self._paper_ids(paper_ids)
        normalized_tags = self._tags(tags)
        self._require_papers(ids)
        self.conn.executemany(
            "INSERT OR IGNORE INTO tags (tag) VALUES (?)",
            ((tag,) for tag in normalized_tags),
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO item_tags (paper_id, tag) VALUES (?, ?)",
            (
                (paper_id, tag)
                for paper_id in ids
                for tag in normalized_tags
            ),
        )
        self.conn.commit()
        return {"paper_ids": list(ids), "tags": list(normalized_tags)}

    def remove_tags(
        self, paper_ids: tuple[str, ...] | list[str], tags: tuple[str, ...] | list[str]
    ) -> dict[str, Any]:
        ids = self._paper_ids(paper_ids)
        normalized_tags = self._tags(tags)
        self._require_papers(ids)
        self.conn.executemany(
            "DELETE FROM item_tags WHERE paper_id = ? AND tag = ?",
            (
                (paper_id, tag)
                for paper_id in ids
                for tag in normalized_tags
            ),
        )
        self.conn.commit()
        return {"paper_ids": list(ids), "tags": list(normalized_tags)}

    def list_items(
        self,
        page: int | object = _LIST_ITEMS_UNSET,
        page_size: int = 50,
        query: str | None = "",
        folder_id: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
        status: str | None = None,
        recent_days: int | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        legacy_call = page is _LIST_ITEMS_UNSET
        if legacy_call:
            rows = self.conn.execute(
                "SELECT * FROM items ORDER BY updated_at DESC, paper_id"
            ).fetchall()
            return [self._row_to_item(row) for row in rows]
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("page_invalid")
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= 100
        ):
            raise ValueError("page_size_invalid")
        if query is not None and not isinstance(query, str):
            raise ValueError("query_invalid")
        if status is not None and (
            not isinstance(status, str) or not status.strip()
        ):
            raise ValueError("status_invalid")
        if recent_days is not None and (
            isinstance(recent_days, bool)
            or not isinstance(recent_days, int)
            or recent_days < 1
        ):
            raise ValueError("recent_days_invalid")
        normalized_tags = self._tags(tags, allow_empty=True)

        where: list[str] = []
        parameters: list[Any] = []
        if folder_id == "__unclassified__":
            where.append("i.folder_id IS NULL")
        elif folder_id is not None:
            if not isinstance(folder_id, str) or not folder_id:
                raise ValueError("folder_id_invalid")
            self._require_folder(folder_id)
            where.append("i.folder_id = ?")
            parameters.append(folder_id)
        if status is not None:
            where.append("i.status = ?")
            parameters.append(status.strip())
        if recent_days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=recent_days)).isoformat()
            where.append("i.updated_at >= ?")
            parameters.append(cutoff)
        for tag in normalized_tags:
            where.append(
                "EXISTS (SELECT 1 FROM item_tags filter_tags "
                "WHERE filter_tags.paper_id = i.paper_id AND filter_tags.tag = ?)"
            )
            parameters.append(tag)
        if query is not None and query.strip():
            cleaned = re.sub(r'[^\w\u4e00-\u9fff\s-]+', " ", query).strip()
            tokens = [token for token in cleaned.split() if token]
            fts_query = " AND ".join(f'"{token}"' for token in tokens)
            pattern = f"%{query.strip()}%"
            search_parts = [
                "i.title LIKE ? COLLATE NOCASE",
                "i.authors_json LIKE ? COLLATE NOCASE",
                "i.doi LIKE ? COLLATE NOCASE",
                "EXISTS (SELECT 1 FROM item_tags search_tags "
                "WHERE search_tags.paper_id = i.paper_id "
                "AND search_tags.tag LIKE ? COLLATE NOCASE)",
            ]
            parameters.extend((pattern, pattern, pattern, pattern))
            if fts_query:
                search_parts.append(
                    "i.paper_id IN (SELECT paper_id FROM fulltext "
                    "WHERE fulltext MATCH ?)"
                )
                parameters.append(fts_query)
            where.append("(" + " OR ".join(search_parts) + ")")

        where_sql = " WHERE " + " AND ".join(where) if where else ""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM items i" + where_sql,
            parameters,
        ).fetchone()[0]
        rows = self.conn.execute(
            "SELECT i.*, f.name AS navigation_folder, "
            "COALESCE((SELECT json_group_array(ordered.tag) FROM "
            "(SELECT it.tag FROM item_tags it WHERE it.paper_id=i.paper_id "
            "ORDER BY it.tag COLLATE NOCASE, it.tag) ordered), '[]') AS navigation_tags, "
            "EXISTS(SELECT 1 FROM attachments a WHERE a.paper_id=i.paper_id) AS navigation_has_pdf, "
            "EXISTS(SELECT 1 FROM artifacts ar WHERE ar.paper_id=i.paper_id "
            "AND ar.kind='reader' AND ar.status='ready') AS navigation_has_reader "
            "FROM items i LEFT JOIN folders f ON f.folder_id=i.folder_id"
            + where_sql
            + " ORDER BY i.updated_at DESC, i.paper_id LIMIT ? OFFSET ?",
            (*parameters, page_size, (page - 1) * page_size),
        ).fetchall()
        return {
            "items": [self._navigation_row_to_item(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def search(self, query: str) -> list[dict[str, Any]]:
        """FTS5 全文搜索（标题/作者/DOI/全文内容）。"""
        cleaned = re.sub(r'[^\w\u4e00-\u9fff\s-]+', " ", query).strip()
        if not cleaned:
            return []
        try:
            rows = self.conn.execute(
                "SELECT i.*, f.content FROM fulltext f JOIN items i ON i.paper_id = f.paper_id"
                " WHERE fulltext MATCH ? ORDER BY rank LIMIT 50",
                (cleaned,),
            ).fetchall()
        except sqlite3.OperationalError:
            # 查询词含 FTS 特殊语法时降级为 LIKE
            pattern = f"%{cleaned}%"
            rows = self.conn.execute(
                "SELECT * FROM items WHERE title LIKE ? OR doi LIKE ?",
                (pattern, pattern),
            ).fetchall()
            return [self._row_to_item(row) for row in rows]
        return [self._row_to_item(row) for row in rows]

    def update_status(self, paper_id: str, status: str) -> None:
        """阶段完成后同步条目状态（worker 调用）。"""
        self.conn.execute(
            "UPDATE items SET status=?, updated_at=? WHERE paper_id=?",
            (status, _now(), paper_id),
        )
        self.conn.commit()

    def update_full_read_state(
        self,
        paper_id: str,
        status: str,
        active_job_id: str,
        *,
        error: str | None = None,
    ) -> bool:
        """原子对齐精读父任务状态；产物仍由父任务 artifact 证明。"""
        cursor = self.conn.execute(
            "UPDATE items SET full_read_status=?, active_job_id=?, last_error=?, updated_at=? "
            "WHERE paper_id=?",
            (status, active_job_id, error, _now(), paper_id),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    @staticmethod
    def _reading_parent_key(paper_id: str, source_sha256: str) -> str:
        return f"reading_parent.{paper_id}.{source_sha256}"

    def set_reading_parent(
        self, paper_id: str, source_sha256: str, parent_job_id: str
    ) -> None:
        self.get_item(paper_id)
        self.conn.execute(
            "INSERT OR REPLACE INTO library_meta (key, value) VALUES (?,?)",
            (self._reading_parent_key(paper_id, source_sha256), parent_job_id),
        )
        self.conn.commit()

    def get_reading_parent(
        self, paper_id: str, source_sha256: str
    ) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM library_meta WHERE key=?",
            (self._reading_parent_key(paper_id, source_sha256),),
        ).fetchone()
        return row[0] if row else None

    def clear_reading_parent(
        self, paper_id: str, source_sha256: str, parent_job_id: str
    ) -> None:
        self.conn.execute(
            "DELETE FROM library_meta WHERE key=? AND value=?",
            (self._reading_parent_key(paper_id, source_sha256), parent_job_id),
        )
        self.conn.commit()

    def get_item(self, paper_id: str) -> dict[str, Any]:
        """按已校验的 paper_id 返回 SQLite 中的单篇只读详情。"""
        if (
            not isinstance(paper_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id)
            or ".." in paper_id
        ):
            raise ValueError("paper_id_invalid")
        row = self.conn.execute(
            "SELECT * FROM items WHERE paper_id=?", (paper_id,)
        ).fetchone()
        if row is None:
            raise ValueError("paper_not_found")
        item = self._row_to_item(row)
        item.update(
            abstract_en=row["abstract_en"],
            abstract_zh=row["abstract_zh"],
            abstract_status=row["abstract_status"],
            full_read_status=row["full_read_status"],
            feishu_sync_state=row["feishu_sync_state"],
            feishu_record_id=row["feishu_record_id"],
            feishu_record_url=row["feishu_record_url"],
            feishu_error=row["feishu_error"],
            xlsx_sync_state=row["xlsx_sync_state"],
            xlsx_error=row["xlsx_error"],
        )
        return item

    def update_abstract_status(self, paper_id: str, status: str) -> bool:
        """原子更新摘要派生状态，不改变主阅读状态。"""
        if not isinstance(status, str) or not status.strip():
            raise ValueError("abstract_status_invalid")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                "UPDATE items SET abstract_status=?, updated_at=? WHERE paper_id=?",
                (status, _now(), paper_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return cursor.rowcount == 1

    def update_active_job(
        self,
        paper_id: str,
        job_id: str,
        *,
        error: str | None = None,
        preserve_existing_error: bool = False,
    ) -> bool:
        """把派生 job 及其启动错误写回主库，供插件和列表查询恢复。"""
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("active_job_id_invalid")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self.conn.execute(
                "UPDATE items SET active_job_id=?, "
                "last_error=CASE WHEN ? AND active_job_id=? AND ? IS NULL "
                "THEN last_error ELSE ? END, updated_at=? "
                "WHERE paper_id=?",
                (
                    job_id,
                    preserve_existing_error,
                    job_id,
                    error,
                    error,
                    _now(),
                    paper_id,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return cursor.rowcount == 1

    def canonical_metadata(self, paper_id: str) -> PaperMetadata:
        """从 SQLite 主库重建单篇元数据，作为派生管线唯一事实源。"""
        row = self.conn.execute(
            "SELECT title, authors_json, doi, pmid, year, journal, library_key, "
            "source_url, abstract_en, abstract_zh FROM items WHERE paper_id=?",
            (paper_id,),
        ).fetchone()
        if row is None:
            raise ValueError("paper_not_found")
        arxiv_alias = self.conn.execute(
            "SELECT key FROM library_meta WHERE value=?"
            " AND key LIKE 'identity.arxiv.%' ORDER BY key LIMIT 1",
            (paper_id,),
        ).fetchone()
        source_url = None
        if arxiv_alias is not None:
            source_url = (
                "https://arxiv.org/abs/"
                + arxiv_alias["key"].removeprefix("identity.arxiv.")
            )
        return PaperMetadata(
            title=row["title"] or "",
            authors=json.loads(row["authors_json"] or "[]"),
            doi=row["doi"],
            pmid=row["pmid"],
            year=row["year"],
            journal=row["journal"],
            library_key=row["library_key"],
            abstract_en=row["abstract_en"],
            abstract_zh=row["abstract_zh"],
            source_url=row["source_url"] or source_url,
        )

    # ── 附件 ────────────────────────────────────────────────────────

    def attach_pdf(self, metadata: PaperMetadata, pdf_path: Path) -> dict[str, Any]:
        """校验 PDF → 复制到 workspace.source.pdf → 登记附件 → 读回验证。

        返回：{status, paper_id, attachment_key, sha256, source_path}
        """
        workspace = PaperWorkspace.create(self.data_root, metadata)
        item = self._select_item(workspace.root.name)
        if item is None:
            raise RuntimeError("library_item_required")

        target = Path(pdf_path)
        validation = validate_pdf(target, metadata)
        if (
            not target.is_absolute()
            or target.suffix.casefold() != ".pdf"
            or not validation.valid
        ):
            raise ValueError("invalid_target_pdf")

        existing = self._select_attachment(workspace.root.name)
        if existing is not None and existing["sha256"] == validation.sha256:
            return {
                "status": "pdf_ready",
                "paper_id": workspace.root.name,
                "attachment_key": item["library_key"],
                "sha256": validation.sha256,
                "source_path": str(workspace.source_pdf),
            }

        if workspace.source_pdf.exists() and self._sha256(workspace.source_pdf) != validation.sha256:
            raise ValueError("source_pdf_conflict")
        shutil.copy2(target, workspace.source_pdf)

        now = _now()
        self.conn.execute(
            "INSERT INTO attachments (paper_id, rel_path, sha256, size, validated_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET"
            " rel_path=excluded.rel_path, sha256=excluded.sha256,"
            " size=excluded.size, validated_at=excluded.validated_at",
            (
                workspace.root.name,
                "source.pdf",
                validation.sha256,
                workspace.source_pdf.stat().st_size,
                now,
            ),
        )
        self.conn.execute(
            "UPDATE items SET status=?, updated_at=? WHERE paper_id=?",
            ("pdf_ready", now, workspace.root.name),
        )
        self.conn.commit()

        # 读回验证
        row = self._select_attachment(workspace.root.name)
        if row is None or row["sha256"] != validation.sha256:
            raise RuntimeError("attachment_readback_failed")
        return {
            "status": "pdf_ready",
            "paper_id": workspace.root.name,
            "attachment_key": item["library_key"],
            "sha256": validation.sha256,
            "source_path": str(workspace.source_pdf),
        }

    def pdf_attachment(self, paper_id: str) -> dict[str, Any] | None:
        self.get_item(paper_id)
        return self._select_attachment(paper_id)

    def record_pdf_attachment(self, paper_id: str, sha256: str, size: int) -> None:
        self.commit_pdf_publication(paper_id, sha256, size, source_changed=False)

    def commit_pdf_publication(
        self,
        paper_id: str,
        sha256: str,
        size: int,
        *,
        source_changed: bool,
        reader_paths: tuple[str, ...] = (),
    ) -> None:
        self.get_item(paper_id)
        now = _now()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                "INSERT INTO attachments (paper_id, rel_path, sha256, size, validated_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT(paper_id) DO UPDATE SET"
                " rel_path=excluded.rel_path, sha256=excluded.sha256,"
                " size=excluded.size, validated_at=excluded.validated_at",
                (paper_id, "source.pdf", sha256, size, now),
            )
            if source_changed:
                self.conn.execute(
                    "UPDATE artifacts SET status='stale', updated_at=?"
                    " WHERE paper_id=? AND kind IN"
                    " ('reader','full_read','full_read_html')",
                    (now, paper_id),
                )
                if reader_paths:
                    self.conn.execute(
                        "INSERT INTO artifacts"
                        " (paper_id, kind, rel_path, status, updated_at)"
                        " VALUES (?,?,?,?,?) ON CONFLICT(paper_id, kind) DO UPDATE SET"
                        " rel_path=excluded.rel_path, status=excluded.status,"
                        " updated_at=excluded.updated_at",
                        (paper_id, "reader", reader_paths[0], "stale", now),
                    )
                self.conn.execute(
                    "UPDATE items SET status=?, full_read_status=?, active_job_id=NULL,"
                    " last_error=NULL, updated_at=? WHERE paper_id=?",
                    ("pdf_ready", "精读排队", now, paper_id),
                )
            else:
                self.conn.execute(
                    "UPDATE items SET status=?, updated_at=? WHERE paper_id=?",
                    ("pdf_ready", now, paper_id),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def mark_reader_stale(self, paper_id: str) -> None:
        now = _now()
        cursor = self.conn.execute(
            "UPDATE artifacts SET status='stale', updated_at=?"
            " WHERE paper_id=? AND kind='reader'",
            (now, paper_id),
        )
        if cursor.rowcount == 0:
            paper_root = self.data_root / "papers" / paper_id
            for candidate in (
                paper_root / "reading" / "reader.html",
                paper_root / "output" / "reader_full.html",
                paper_root / "reader_full.html",
            ):
                if candidate.is_file():
                    self.conn.execute(
                        "INSERT INTO artifacts"
                        " (paper_id, kind, rel_path, status, updated_at)"
                        " VALUES (?,?,?,?,?)",
                        (
                            paper_id,
                            "reader",
                            candidate.relative_to(paper_root).as_posix(),
                            "stale",
                            now,
                        ),
                    )
                    break
        self.conn.commit()

    def publish_reader(self, paper_id: str, rel_path: str) -> None:
        self.get_item(paper_id)
        paper_root = (self.data_root / "papers" / paper_id).resolve()
        path = (paper_root / rel_path).resolve()
        manifest = path.with_name("reader-manifest.json")
        normalized_input = rel_path.replace("\\", "/")
        generation_match = re.fullmatch(
            r"generations/([0-9a-f]{16})/reading/reader\.html",
            normalized_input,
        )
        is_base_reader = normalized_input == "reading/reader.html"
        def validate_files() -> None:
            if (
                (generation_match is None and not is_base_reader)
                or not path.is_relative_to(paper_root)
                or not path.is_file()
                or not manifest.is_file()
            ):
                raise ValueError("reader_publication_invalid")
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("reader_publication_invalid") from error
            legacy_required = {
                "contract", "paper_id", "source_pdf_sha256",
                "parser_manifest_sha256", "translation_manifest_sha256",
                "reader_sha256", "generated_at", "source_blocks", "assets",
            }
            v21_required = legacy_required | {
                "reading_guide_sha256",
                "highlights_manifest_sha256",
                "reader_build_version",
                "reader_revision",
                "review",
            }
            manifest_keys = set(payload)
            v21_manifest = manifest_keys == v21_required
            attachment = self.conn.execute(
                "SELECT sha256 FROM attachments WHERE paper_id=?", (paper_id,)
            ).fetchone()
            hashes = (
                payload.get("source_pdf_sha256"),
                payload.get("parser_manifest_sha256"),
                payload.get("translation_manifest_sha256"),
                payload.get("reader_sha256"),
            )
            review = payload.get("review")
            v21_valid = (
                not v21_manifest
                or (
                    isinstance(payload.get("reader_build_version"), str)
                    and bool(payload["reader_build_version"])
                    and isinstance(payload.get("reader_revision"), str)
                    and re.fullmatch(
                        r"[0-9a-f]{64}", payload["reader_revision"]
                    )
                    is not None
                    and all(
                        isinstance(payload.get(key), str)
                        and re.fullmatch(r"[0-9a-f]{64}", payload[key])
                        is not None
                        for key in (
                            "reading_guide_sha256",
                            "highlights_manifest_sha256",
                        )
                    )
                    and isinstance(review, dict)
                    and review.get("contract_version") == "full-review-v2"
                    and isinstance(review.get("guide"), dict)
                    and set(review["guide"])
                    == {
                        "research_question",
                        "key_methods",
                        "core_results",
                        "limitations",
                    }
                )
            )
            if v21_manifest and v21_valid:
                try:
                    generation = PaperWorkspace(path.parent.parent)
                    generation_state = generation.load_job()
                    full_stage = generation_state.stages["full_read"]
                    guide_path = (
                        generation.reading_dir
                        / "full"
                        / "reading_guide.json"
                    )
                    highlights_path = (
                        generation.reading_dir / "full" / "highlights.json"
                    )
                    guide_payload = json.loads(
                        guide_path.read_text(encoding="utf-8")
                    )
                    rendered = path.read_text(encoding="utf-8")
                    revision = payload["reader_revision"]
                    stage_paths_match = all(
                        Path(full_stage.result[key]).resolve()
                        == expected.resolve()
                        for key, expected in (
                            ("reading_guide_json", guide_path),
                            ("highlights_json", highlights_path),
                        )
                    )
                    v21_valid = (
                        generation_match is not None
                        and generation_state.paper_id == generation_match.group(1)
                        and full_stage.status == "completed"
                        and full_stage.input_hash == revision
                        and full_stage.result.get("source_sha256")
                        == payload["source_pdf_sha256"]
                        and full_stage.result.get("reader_build_version")
                        == payload["reader_build_version"]
                        and full_stage.result.get("reader_revision")
                        == revision
                        and full_stage.result.get("review") == review
                        and stage_paths_match
                        and payload["reading_guide_sha256"]
                        == self._sha256(guide_path)
                        and payload["highlights_manifest_sha256"]
                        == self._sha256(highlights_path)
                        and guide_payload
                        == {
                            "contract_version": "full-review-v2",
                            "reader_revision": revision,
                            "guide": review["guide"],
                        }
                        and re.search(
                            r'<body\b[^>]*\bdata-reader-revision=["\']'
                            + re.escape(revision)
                            + r'["\']',
                            rendered,
                        )
                        is not None
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    v21_valid = False
            blocks = payload.get("source_blocks")
            assets = payload.get("assets")
            blocks_valid = isinstance(blocks, list) and bool(blocks) and all(
                isinstance(row, dict)
                and set(row) == {"block_id", "page", "source_type", "source_index"}
                and isinstance(row["block_id"], str)
                and type(row["page"]) is int and row["page"] > 0
                and isinstance(row["source_type"], str) and row["source_type"]
                and type(row["source_index"]) is int and row["source_index"] >= 0
                for row in blocks
            )
            assets_valid = isinstance(assets, list) and all(
                isinstance(row, dict)
                and set(row) == {"id", "kind", "page", "path", "sha256", "caption_block_id"}
                and isinstance(row["id"], str) and row["id"]
                and isinstance(row["kind"], str) and row["kind"]
                and type(row["page"]) is int and row["page"] > 0
                and isinstance(row["path"], str) and row["path"]
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None
                and (row["caption_block_id"] is None or isinstance(row["caption_block_id"], str))
                for row in assets
            )
            reader_workspace = (
                paper_root
                if is_base_reader
                else paper_root / "generations" / generation_match.group(1)
            ).resolve()
            parser_source = (
                reader_workspace / "parsed" / "mineru" / "source_map.json"
            ).resolve()
            translation_source = (
                reader_workspace / "reading" / "full" / "translations.json"
            ).resolve()
            source_files_valid = (
                parser_source.is_relative_to(reader_workspace)
                and translation_source.is_relative_to(reader_workspace)
                and parser_source.is_file()
                and translation_source.is_file()
                and self._sha256(parser_source)
                == payload.get("parser_manifest_sha256")
                and self._sha256(translation_source)
                == payload.get("translation_manifest_sha256")
            )
            asset_files_valid = assets_valid
            if assets_valid:
                for row in assets:
                    asset_path = (reader_workspace / row["path"]).resolve()
                    if (
                        not asset_path.is_relative_to(reader_workspace)
                        or not asset_path.is_file()
                        or self._sha256(asset_path) != row["sha256"]
                    ):
                        asset_files_valid = False
                        break
            try:
                job = json.loads(
                    (paper_root / "job.json").read_text(encoding="utf-8")
                )
                upgrade_stage = job["stages"]["paper_parse_upgrade"]
                upgrade_result = upgrade_stage["result"]
                active_workspace = upgrade_result.get("active_workspace")
                stage_source_sha = upgrade_result["source_sha256"]
                active_status = upgrade_stage["status"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                active_workspace = None
                stage_source_sha = None
                active_status = None
            expected_active_workspace = (
                f"generations/{generation_match.group(1)}"
                if generation_match is not None else None
            )
            if (
                frozenset(manifest_keys)
                not in {frozenset(legacy_required), frozenset(v21_required)}
                or payload.get("contract") != "reader-manifest-v1"
                or payload.get("paper_id") != paper_id
                or not isinstance(payload.get("generated_at"), str)
                or not payload["generated_at"]
                or not all(
                    isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value) is not None
                    for value in hashes
                )
                or attachment is None
                or payload["source_pdf_sha256"] != attachment["sha256"]
                or stage_source_sha != attachment["sha256"]
                or stage_source_sha != payload["source_pdf_sha256"]
                or (
                    generation_match is not None
                    and generation_match.group(1)
                    != payload["source_pdf_sha256"][:16]
                )
                or active_workspace != expected_active_workspace
                or active_status != "completed"
                or payload["reader_sha256"] != self._sha256(path)
                or not blocks_valid
                or not assets_valid
                or not v21_valid
                or not source_files_valid
                or not asset_files_valid
            ):
                raise ValueError("reader_publication_invalid")

        validate_files()
        normalized = path.relative_to(paper_root).as_posix()
        now = _now()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            validate_files()
            self.conn.execute(
                "INSERT INTO artifacts (paper_id, kind, rel_path, status, updated_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT(paper_id, kind) DO UPDATE SET"
                " rel_path=excluded.rel_path, status=excluded.status,"
                " updated_at=excluded.updated_at",
                (paper_id, "reader", normalized, "ready", now),
            )
            self.conn.execute(
                "UPDATE items SET status=?, full_read_status=?, last_error=NULL,"
                " updated_at=? WHERE paper_id=?",
                ("full_read_ready", "精读完成", now, paper_id),
            )
            row = self.conn.execute(
                "SELECT rel_path, status FROM artifacts"
                " WHERE paper_id=? AND kind='reader'",
                (paper_id,),
            ).fetchone()
            if row is None or tuple(row) != (normalized, "ready"):
                raise ValueError("reader_publication_invalid")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ── 内部 ────────────────────────────────────────────────────────

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _paper_id(metadata: PaperMetadata) -> str:
        return stable_paper_id(metadata)

    def _row_to_item(self, row: sqlite3.Row | tuple) -> dict[str, Any]:
        item = {
            "paper_id": row["paper_id"],
            "library_key": row["library_key"],
            "title": row["title"],
            "authors": json.loads(row["authors_json"] or "[]"),
            "doi": row["doi"],
            "pmid": row["pmid"],
            "year": row["year"],
            "journal": row["journal"],
            "source_url": row["source_url"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "folder_id": row["folder_id"],
            "active_job_id": row["active_job_id"],
            "last_error": row["last_error"],
        }
        folder = (
            self.conn.execute(
                "SELECT name FROM folders WHERE folder_id = ?", (row["folder_id"],)
            ).fetchone()
            if row["folder_id"] is not None
            else None
        )
        item["folder_name"] = folder["name"] if folder else None
        item["tags"] = [
            tag_row["tag"]
            for tag_row in self.conn.execute(
                "SELECT tag FROM item_tags WHERE paper_id = ? "
                "ORDER BY tag COLLATE NOCASE, tag",
                (row["paper_id"],),
            ).fetchall()
        ]
        item["display_title"] = item["title"] or item["doi"] or item["pmid"] or ""
        return item

    def _navigation_row_to_item(self, row: sqlite3.Row) -> dict[str, Any]:
        authors = json.loads(row["authors_json"] or "[]")
        if not authors:
            authors_short = ""
        elif len(authors) == 1:
            authors_short = authors[0]
        else:
            authors_short = f"{authors[0]} 等 {len(authors)} 位"
        return {
            "paper_id": row["paper_id"],
            "library_key": row["library_key"],
            "title": row["title"],
            "authors": authors,
            "authors_short": authors_short,
            "doi": row["doi"],
            "pmid": row["pmid"],
            "year": row["year"],
            "journal": row["journal"],
            "source_url": row["source_url"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "folder": row["navigation_folder"],
            "tags": json.loads(row["navigation_tags"]),
            "abstract_status": row["abstract_status"],
            "full_read_status": row["full_read_status"],
            "feishu_sync_state": row["feishu_sync_state"],
            "has_pdf": bool(row["navigation_has_pdf"]),
            "has_reader": bool(row["navigation_has_reader"]),
            "feishu_record_url": row["feishu_record_url"] or "",
            "last_error": row["last_error"],
            "folder_id": row["folder_id"],
            "folder_name": row["navigation_folder"],
            "active_job_id": row["active_job_id"],
            "display_title": row["title"] or row["doi"] or row["pmid"] or "",
        }

    @staticmethod
    def _folder_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("folder_name_invalid")
        return name.strip()

    @staticmethod
    def _paper_ids(paper_ids: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        if isinstance(paper_ids, (str, bytes)):
            raise ValueError("paper_ids_invalid")
        try:
            ids = tuple(dict.fromkeys(paper_ids))
        except (TypeError, AttributeError):
            raise ValueError("paper_ids_invalid") from None
        if not ids or any(not isinstance(value, str) or not value for value in ids):
            raise ValueError("paper_ids_invalid")
        return ids

    @staticmethod
    def _tags(
        tags: tuple[str, ...] | list[str], *, allow_empty: bool = False
    ) -> tuple[str, ...]:
        if isinstance(tags, (str, bytes)):
            raise ValueError("tag_invalid")
        try:
            normalized = tuple(
                dict.fromkeys(
                    tag.strip()
                    for tag in tags
                    if isinstance(tag, str) and tag.strip()
                )
            )
        except TypeError:
            raise ValueError("tag_invalid") from None
        try:
            original = tuple(tags)
        except TypeError:
            raise ValueError("tag_invalid") from None
        if len(normalized) != len(dict.fromkeys(original)) and any(
            not isinstance(tag, str) or not tag.strip() for tag in original
        ):
            raise ValueError("tag_invalid")
        if not allow_empty and not normalized:
            raise ValueError("tag_invalid")
        return normalized

    def _require_folder(self, folder_id: str) -> None:
        if self.conn.execute(
            "SELECT 1 FROM folders WHERE folder_id = ?", (folder_id,)
        ).fetchone() is None:
            raise ValueError("folder_not_found")

    def _require_papers(self, paper_ids: tuple[str, ...]) -> None:
        placeholders = ",".join("?" for _ in paper_ids)
        found = {
            row["paper_id"]
            for row in self.conn.execute(
                f"SELECT paper_id FROM items WHERE paper_id IN ({placeholders})",
                paper_ids,
            ).fetchall()
        }
        if found != set(paper_ids):
            raise ValueError("paper_not_found")

    def _select_item(self, paper_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM items WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        return self._row_to_item(row) if row else None

    def _select_attachment(self, paper_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM attachments WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None

    def _update_item(self, paper_id: str, metadata: PaperMetadata, status: str) -> None:
        now = _now()
        self.conn.execute(
            "UPDATE items SET title=?, authors_json=?, doi=?, pmid=?, year=?, journal=?,"
            " source_url=?, status=?, updated_at=? WHERE paper_id=?",
            (
                metadata.title,
                json.dumps(metadata.authors, ensure_ascii=False),
                normalize_doi(metadata.doi), metadata.pmid,
                metadata.year, metadata.journal,
                _stored_source_url(metadata.source_url), status, now, paper_id,
            ),
        )
        self._index_fulltext(paper_id, metadata)
        self.conn.commit()

    def _find_ingest_match(
        self, metadata: PaperMetadata
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        identities = {
            name: value
            for name, value in (
                ("library_key", metadata.library_key),
                ("doi", normalize_doi(metadata.doi)),
                ("pmid", normalize_pmid(metadata.pmid)),
                ("arxiv", normalize_arxiv(metadata.source_url)),
            )
            if value
        }
        matches = {
            name: items
            for name, value in identities.items()
            if (items := self._lookup_stable_identity(name, value))
        }
        matched_papers = {
            item["paper_id"]: item
            for items in matches.values()
            for item in items
        }
        if len(matched_papers) > 1:
            return None, "conflict", {
                "identifiers": list(identities),
                "paper_ids": sorted(matched_papers),
                "library_keys": sorted(
                    item["library_key"] for item in matched_papers.values()
                ),
            }
        if matched_papers:
            item = next(iter(matched_papers.values()))
            if self._stable_identity_conflicts(item, identities):
                return None, "conflict", {
                    "identifiers": list(identities),
                    "paper_ids": [item["paper_id"]],
                    "library_keys": [item["library_key"]],
                }
            dedupe = next(name for name in identities if name in matches)
            return item, dedupe, None

        if identities:
            return None, "none", None

        title = normalize_title(metadata.title)
        first_author = (
            normalize_author(metadata.authors[0]) if metadata.authors else ""
        )
        if not title or metadata.year is None or not first_author:
            return None, "none", None
        deterministic = self._select_item(stable_paper_id(metadata))
        if deterministic is not None:
            return deterministic, "title_year_author", None
        candidates = []
        for row in self.conn.execute("SELECT * FROM items").fetchall():
            authors = json.loads(row["authors_json"] or "[]")
            candidate_author = normalize_author(authors[0]) if authors else ""
            if (
                normalize_title(row["title"] or "") == title
                and row["year"] == metadata.year
                and candidate_author == first_author
            ):
                candidates.append(self._row_to_item(row))
        if len(candidates) == 1:
            return candidates[0], "title_year_author", None
        return None, "none", None

    def _lookup_stable_identity(
        self, name: str, value: str
    ) -> list[dict[str, Any]]:
        if name == "library_key":
            item = self.item_by_key(value)
            return [item] if item is not None else []
        if name in {"doi", "pmid"}:
            normalizer = normalize_doi if name == "doi" else normalize_pmid
            return [
                self._row_to_item(candidate)
                for candidate in self.conn.execute(
                    "SELECT * FROM items ORDER BY created_at"
                ).fetchall()
                if normalizer(candidate[name]) == value
            ]
        candidates: dict[str, dict[str, Any]] = {}
        alias = self.conn.execute(
            "SELECT value FROM library_meta WHERE key = ?",
            (f"identity.arxiv.{value}",),
        ).fetchone()
        if alias is not None:
            item = self._select_item(alias["value"])
            if item is not None:
                candidates[item["paper_id"]] = item
        arxiv_id = stable_paper_id(
            PaperMetadata(title="arXiv", source_url=f"arXiv:{value}")
        )
        item = self._select_item(arxiv_id)
        if item is not None:
            candidates[item["paper_id"]] = item
        return list(candidates.values())

    def _stable_identity_conflicts(
        self, item: dict[str, Any], identities: dict[str, str]
    ) -> bool:
        if (
            "library_key" in identities
            and identities["library_key"] != item["library_key"]
        ):
            return True
        for name, normalizer in (("doi", normalize_doi), ("pmid", normalize_pmid)):
            incoming = identities.get(name)
            stored = normalizer(item[name])
            if incoming and stored and incoming != stored:
                return True
        incoming_arxiv = identities.get("arxiv")
        stored_arxiv = {
            row["key"].removeprefix("identity.arxiv.")
            for row in self.conn.execute(
                "SELECT key FROM library_meta WHERE value = ?"
                " AND key LIKE 'identity.arxiv.%'",
                (item["paper_id"],),
            ).fetchall()
        }
        return bool(
            incoming_arxiv
            and stored_arxiv
            and incoming_arxiv not in stored_arxiv
        )

    def _unique_ingest_paper_id(self, metadata: PaperMetadata) -> str:
        base = stable_paper_id(metadata)
        if self._select_item(base) is None:
            return base
        suffix = 2
        while self._select_item(f"{base}_{suffix}") is not None:
            suffix += 1
        return f"{base}_{suffix}"

    def _update_item_from_ingest(
        self, paper_id: str, metadata: PaperMetadata
    ) -> None:
        row = self._select_item(paper_id)
        if row is None:
            raise RuntimeError("library_item_missing")
        title = metadata.title.strip() or row["title"]
        authors = metadata.authors or row["authors"]
        now = _now()
        self.conn.execute(
            "UPDATE items SET title=?, authors_json=?, doi=COALESCE(doi, ?),"
            " pmid=COALESCE(pmid, ?), year=COALESCE(?, year),"
            " journal=COALESCE(?, journal), source_url=COALESCE(?, source_url),"
            " abstract_en=COALESCE(?, abstract_en),"
            " abstract_zh=COALESCE(?, abstract_zh), updated_at=? WHERE paper_id=?",
            (
                title,
                json.dumps(authors, ensure_ascii=False),
                normalize_doi(metadata.doi),
                normalize_pmid(metadata.pmid),
                metadata.year,
                metadata.journal,
                _stored_source_url(metadata.source_url),
                metadata.abstract_en,
                metadata.abstract_zh,
                now,
                paper_id,
            ),
        )
        indexed = PaperMetadata(
            title=title,
            authors=authors,
            doi=normalize_doi(metadata.doi) or row["doi"],
            pmid=normalize_pmid(metadata.pmid) or row["pmid"],
            year=metadata.year or row["year"],
            journal=metadata.journal or row["journal"],
        )
        self._index_fulltext(paper_id, indexed)
        self._store_identity_aliases(paper_id, metadata)
        self.conn.commit()

    def _store_identity_aliases(
        self, paper_id: str, metadata: PaperMetadata
    ) -> None:
        arxiv = normalize_arxiv(metadata.source_url)
        if arxiv:
            self.conn.execute(
                "INSERT OR IGNORE INTO library_meta (key, value) VALUES (?, ?)",
                (f"identity.arxiv.{arxiv}", paper_id),
            )

    @staticmethod
    def _ingest_conflict(conflict: dict[str, Any]) -> dict[str, Any]:
        paper_ids = conflict["paper_ids"]
        library_keys = conflict["library_keys"]
        return {
            "status": "ambiguous_reference",
            "paper_id": paper_ids[0] if len(paper_ids) == 1 else None,
            "library_key": library_keys[0] if len(library_keys) == 1 else None,
            "created": False,
            "dedupe": "conflict",
            "folder_id": None,
            "user_status": "生成浅读",
            "derived_updates": ["metadata_enrichment", "xlsx_snapshot"],
            "conflict": {
                "reason": "stable_identity_conflict",
                **conflict,
            },
        }

    @staticmethod
    def _ingest_result(
        row: dict[str, Any], *, created: bool, dedupe: str
    ) -> dict[str, Any]:
        return {
            "paper_id": row["paper_id"],
            "library_key": row["library_key"],
            "created": created,
            "dedupe": dedupe,
            "folder_id": None,
            "user_status": "生成浅读",
            "derived_updates": ["metadata_enrichment", "xlsx_snapshot"],
        }

    def _find_conflict(self, metadata: PaperMetadata, paper_id: str) -> str | None:
        """按 DOI/PMID/规范化题名精确查重，返回冲突条目的 library_key。"""
        doi = normalize_doi(metadata.doi)
        pmid = metadata.pmid
        title = normalize_title(metadata.title)
        rows = self.conn.execute("SELECT paper_id, library_key, doi, pmid, title FROM items").fetchall()
        for row in rows:
            if row[0] == paper_id:
                continue
            if doi and row[2] and row[2].casefold() == doi.casefold():
                return row[1]
            if pmid and row[3] and row[3] == pmid:
                return row[1]
            if title and row[4] and normalize_title(row[4]) == title:
                return row[1]
        return None

    def _index_fulltext(self, paper_id: str, metadata: PaperMetadata) -> None:
        self.conn.execute("DELETE FROM fulltext WHERE paper_id = ?", (paper_id,))
        content = " ".join(
            [
                metadata.title or "",
                " ".join(metadata.authors),
                normalize_doi(metadata.doi) or "",
                metadata.journal or "",
            ]
        )
        self.conn.execute(
            "INSERT INTO fulltext (paper_id, content) VALUES (?,?)",
            (paper_id, content),
        )

    @staticmethod
    def _item_result(row: dict[str, Any], dedupe: str) -> dict[str, Any]:
        return {
            "status": "library_ready",
            "paper_id": row["paper_id"],
            "library_key": row["library_key"],
            "dedupe": dedupe,
        }
