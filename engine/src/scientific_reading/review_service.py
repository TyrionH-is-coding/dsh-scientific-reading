"""论文整理子会话与确认结论的 SQLite 服务。"""

from __future__ import annotations
from .scope import current_scope, require_paper, publication_guard, library_write, ScopeError

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data_guard import data_root_operation, root_operation
from .evidence_locator import EvidenceLocatorError, resolve_locator
from .library_schema import migrate_library
from .library_service import library_path


_BASES = {"paper", "personal", "inference", "question", "legacy"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(code)
    return value.strip()


class ReviewService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        with data_root_operation(self.data_root):
            migrate_library(self.data_root)
        self.conn = sqlite3.connect(library_path(self.data_root), timeout=1.0)
        self.conn.execute("PRAGMA busy_timeout = 1000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def _require_scope(self, parent_session_id: str, paper_id: str) -> None:
        require_paper(self.conn, paper_id)
        scope = current_scope()
        if scope is not None and parent_session_id != scope["scopeSessionId"]:
            raise ScopeError("scope_session_forbidden")

    def get_binding(
        self, parent_session_id: str, paper_id: str
    ) -> dict[str, str] | None:
        self._require_scope(parent_session_id, paper_id)
        row = self.conn.execute(
            "SELECT parent_session_id, paper_id, review_session_id "
            "FROM review_sessions WHERE parent_session_id=? AND paper_id=?",
            (parent_session_id, paper_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def open_state(self, parent_session_id: str, paper_id: str) -> dict[str, str]:
        parent_session_id = _required_text(parent_session_id, "parent_session_id_required")
        paper_id = _required_text(paper_id, "paper_id_required")
        self._require_scope(parent_session_id, paper_id)
        paper = self.conn.execute(
            "SELECT title FROM items WHERE paper_id=?", (paper_id,)
        ).fetchone()
        if paper is None:
            raise ValueError("paper_not_found")
        binding = self.get_binding(parent_session_id, paper_id)
        if binding is not None:
            return {"status": "bound", "title": paper["title"], **binding}
        return {
            "status": "missing",
            "parent_session_id": parent_session_id,
            "paper_id": paper_id,
            "title": paper["title"],
        }

    @root_operation
    @library_write
    def bind_session(
        self, parent_session_id: str, paper_id: str, review_session_id: str
    ) -> dict[str, str]:
        parent_session_id = _required_text(parent_session_id, "parent_session_id_required")
        paper_id = _required_text(paper_id, "paper_id_required")
        review_session_id = _required_text(review_session_id, "review_session_id_required")
        if self.conn.execute(
            "SELECT 1 FROM items WHERE paper_id=?", (paper_id,)
        ).fetchone() is None:
            raise ValueError("paper_not_found")

        existing = self.get_binding(parent_session_id, paper_id)
        if existing is not None:
            self.conn.execute(
                "UPDATE review_sessions SET updated_at=? "
                "WHERE parent_session_id=? AND paper_id=?",
                (_now(), parent_session_id, paper_id),
            )
            self.conn.commit()
            return {"status": "reused", **existing}

        now = _now()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO review_sessions "
                    "(parent_session_id, paper_id, review_session_id, created_at, updated_at) "
                    "VALUES (?,?,?,?,?)",
                    (parent_session_id, paper_id, review_session_id, now, now),
                )
        except sqlite3.IntegrityError as error:
            winner = self.get_binding(parent_session_id, paper_id)
            if winner is not None:
                return {"status": "reused", **winner}
            raise ValueError("review_session_already_bound") from error
        return {
            "status": "created",
            "parent_session_id": parent_session_id,
            "paper_id": paper_id,
            "review_session_id": review_session_id,
        }

    def context_for_session(self, review_session_id: str) -> dict[str, Any]:
        review_session_id = _required_text(
            review_session_id, "review_session_id_required"
        )
        row = self.conn.execute(
            "SELECT rs.parent_session_id, rs.paper_id, rs.review_session_id, "
            "i.title, i.authors_json, i.doi, i.abstract_en, i.abstract_zh, "
            "(SELECT rel_path FROM artifacts a WHERE a.paper_id=rs.paper_id "
            "AND a.kind IN ('reader','full_read_html','full_read') AND a.status='ready' "
            "ORDER BY a.updated_at DESC LIMIT 1) AS reader_path "
            "FROM review_sessions rs JOIN items i ON i.paper_id=rs.paper_id "
            "WHERE rs.review_session_id=?",
            (review_session_id,),
        ).fetchone()
        if row is None:
            raise ValueError("review_session_not_bound")
        self._require_scope(row["parent_session_id"], row["paper_id"])
        conclusions = [
            self._resolved_conclusion(item)
            for item in self.conn.execute(
                "SELECT conclusion_id, parent_session_id, paper_id, review_session_id, "
                "conclusion_type, conclusion_text, evidence_locator, evidence_json, "
                "basis, confirmed_at FROM review_conclusions WHERE review_session_id=? "
                "ORDER BY confirmed_at, rowid",
                (review_session_id,),
            )
        ]
        return {
            "parent_session_id": row["parent_session_id"],
            "review_session_id": row["review_session_id"],
            "paper": {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "authors": json.loads(row["authors_json"] or "[]"),
                "doi": row["doi"],
                "abstract_en": row["abstract_en"],
                "abstract_zh": row["abstract_zh"],
            },
            "reader_path": row["reader_path"],
            "confirmed_conclusions": conclusions,
        }

    def _resolved_conclusion(self, row: sqlite3.Row) -> dict[str, Any]:
        result = {
            "conclusion_id": row["conclusion_id"],
            "parent_session_id": row["parent_session_id"],
            "paper_id": row["paper_id"],
            "review_session_id": row["review_session_id"],
            "conclusion_type": row["conclusion_type"],
            "conclusion_text": row["conclusion_text"],
            "evidence_locator": row["evidence_locator"],
            "basis": row["basis"],
            "confirmed_at": row["confirmed_at"],
            "scientific_validity": "not_assessed",
        }
        evidence = None
        source = None
        links = None
        evidence_error = None
        if row["evidence_json"] is not None:
            try:
                evidence = json.loads(row["evidence_json"])
                resolved = resolve_locator(
                    self.data_root, row["paper_id"], evidence
                )
                source = resolved["source"]
                links = resolved["links"]
                evidence_status = "location_verified"
            except (EvidenceLocatorError, json.JSONDecodeError, TypeError) as error:
                evidence_status = "stale"
                evidence_error = getattr(error, "code", "evidence_json_invalid")
        elif row["basis"] == "legacy":
            evidence_status = "legacy_unverified"
        else:
            evidence_status = "not_provided"
        result.update(
            {
                "evidence": evidence,
                "evidence_status": evidence_status,
                "source": source,
                "links": links,
                "claim_support": (
                    "location_only"
                    if row["basis"] == "paper"
                    and evidence_status == "location_verified"
                    else "not_source_supported"
                ),
            }
        )
        if evidence_error is not None:
            result["evidence_error"] = evidence_error
        return result

    def resolve_conclusion(self, conclusion_id: str) -> dict[str, Any]:
        conclusion_id = _required_text(
            conclusion_id, "conclusion_id_required"
        )
        row = self.conn.execute(
            "SELECT conclusion_id, parent_session_id, paper_id, review_session_id, "
            "conclusion_type, conclusion_text, evidence_locator, evidence_json, "
            "basis, confirmed_at FROM review_conclusions WHERE conclusion_id=?",
            (conclusion_id,),
        ).fetchone()
        if row is None:
            raise ValueError("conclusion_not_found")
        self._require_scope(row["parent_session_id"], row["paper_id"])
        return self._resolved_conclusion(row)

    def _normalize_evidence(
        self,
        paper_id: str,
        item: dict[str, Any],
    ) -> tuple[str, str, str | None]:
        supplied_basis = item.get("basis")
        if supplied_basis is None:
            evidence_locator = item.get("evidence_locator", "")
            if not isinstance(evidence_locator, str):
                raise ValueError("evidence_locator_invalid")
            if item.get("evidence") is not None:
                raise ValueError("basis_required_for_structured_evidence")
            return "legacy", evidence_locator.strip(), None
        if not isinstance(supplied_basis, str) or supplied_basis not in _BASES:
            raise ValueError("basis_invalid")
        if supplied_basis == "legacy":
            evidence_locator = item.get("evidence_locator", "")
            if not isinstance(evidence_locator, str):
                raise ValueError("evidence_locator_invalid")
            if item.get("evidence") is not None:
                raise ValueError("legacy_evidence_must_be_text")
            return "legacy", evidence_locator.strip(), None
        if item.get("evidence_locator") not in (None, ""):
            raise ValueError("evidence_locator_legacy_only")
        evidence = item.get("evidence")
        if evidence is None:
            if supplied_basis == "paper":
                raise ValueError("paper_evidence_required")
            return supplied_basis, "", None
        if not isinstance(evidence, dict):
            raise ValueError("evidence_invalid")
        resolved = resolve_locator(self.data_root, paper_id, evidence)
        return (
            supplied_basis,
            "",
            json.dumps(
                resolved["locator"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    @root_operation
    def confirm_conclusions(
        self, review_session_id: str, conclusions: object
    ) -> dict[str, Any]:
        context = self.context_for_session(review_session_id)
        if not isinstance(conclusions, list) or not conclusions:
            raise ValueError("conclusions_required")
        normalized: list[tuple[str, str, str, str, str | None]] = []
        for item in conclusions:
            if not isinstance(item, dict):
                raise ValueError("conclusion_invalid")
            conclusion_type = _required_text(
                item.get("conclusion_type"), "conclusion_type_required"
            )
            conclusion_text = _required_text(
                item.get("conclusion_text"), "conclusion_text_required"
            )
            basis, evidence_locator, evidence_json = self._normalize_evidence(
                context["paper"]["paper_id"], item
            )
            normalized.append(
                (
                    conclusion_type,
                    conclusion_text,
                    evidence_locator,
                    basis,
                    evidence_json,
                )
            )

        now = _now()
        paper_id = context["paper"]["paper_id"]
        parent_session_id = context["parent_session_id"]
        inserted: list[str] = []
        with publication_guard(self.data_root, paper_id), self.conn:
            require_paper(self.conn, paper_id)
            for (
                conclusion_type,
                conclusion_text,
                evidence_locator,
                basis,
                evidence_json,
            ) in normalized:
                conclusion_id = "review_" + uuid.uuid4().hex
                self.conn.execute(
                    "INSERT INTO review_conclusions "
                    "(conclusion_id, parent_session_id, paper_id, review_session_id, "
                    "conclusion_type, conclusion_text, evidence_locator, evidence_json, "
                    "basis, confirmed_at, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        conclusion_id,
                        parent_session_id,
                        paper_id,
                        review_session_id,
                        conclusion_type,
                        conclusion_text,
                        evidence_locator,
                        evidence_json,
                        basis,
                        now,
                        now,
                        now,
                    ),
                )
                inserted.append(conclusion_id)
            self.conn.execute(
                "UPDATE review_sessions SET updated_at=? WHERE review_session_id=?",
                (now, review_session_id),
            )
        return {
            "status": "confirmed",
            "review_session_id": review_session_id,
            "paper_id": paper_id,
            "inserted": len(inserted),
            "conclusion_ids": inserted,
            "conclusions": [
                self.resolve_conclusion(conclusion_id)
                for conclusion_id in inserted
            ],
        }
