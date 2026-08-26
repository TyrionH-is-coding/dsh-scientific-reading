"""验证并原子应用文件夹/标签归类提案。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from .library_service import LibraryService, _now


@dataclass(frozen=True, slots=True)
class ClassificationProposal:
    paper_id: str
    folder_name: str | None
    tags: tuple[str, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.paper_id, str) or not self.paper_id:
            raise ValueError("paper_id_invalid")
        if self.folder_name is not None:
            if not isinstance(self.folder_name, str) or not self.folder_name.strip():
                raise ValueError("folder_name_invalid")
            object.__setattr__(self, "folder_name", self.folder_name.strip())
        if not isinstance(self.tags, tuple):
            raise ValueError("tags_invalid")
        normalized = LibraryService._tags(self.tags, allow_empty=True)
        object.__setattr__(self, "tags", normalized)
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence_invalid")
        object.__setattr__(self, "confidence", float(self.confidence))


class ClassificationService:
    """SQLite 是唯一事实来源；AI 输出只能作为待验证提案。"""

    CHUNK_SIZE = 100

    def __init__(self, library: LibraryService) -> None:
        self.library = library
        self.conn = library.conn

    def apply(
        self,
        proposals: tuple[ClassificationProposal, ...] | list[ClassificationProposal],
        minimum_confidence: float = 0.70,
        allow_new_folders: bool = False,
    ) -> dict[str, Any]:
        if (
            isinstance(minimum_confidence, bool)
            or not isinstance(minimum_confidence, (int, float))
            or not 0 <= minimum_confidence <= 1
        ):
            raise ValueError("minimum_confidence_invalid")
        if not isinstance(allow_new_folders, bool):
            raise ValueError("allow_new_folders_invalid")
        if isinstance(proposals, (str, bytes)):
            raise ValueError("proposals_invalid")
        try:
            requested = tuple(proposals)
        except TypeError:
            raise ValueError("proposals_invalid") from None
        if any(not isinstance(proposal, ClassificationProposal) for proposal in requested):
            raise ValueError("proposals_invalid")
        paper_ids = [proposal.paper_id for proposal in requested]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("duplicate_paper_proposal")

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            folder_ids = {
                row["name"]: row["folder_id"]
                for row in self.conn.execute("SELECT folder_id, name FROM folders")
            }
            valid: list[ClassificationProposal] = []
            target_folder_ids: dict[str, str | None] = {}
            skipped: list[dict[str, str]] = []
            for proposal in requested:
                if proposal.confidence < minimum_confidence:
                    skipped.append(
                        {
                            "paper_id": proposal.paper_id,
                            "reason": "confidence_below_minimum",
                        }
                    )
                    continue
                if self.conn.execute(
                    "SELECT 1 FROM items WHERE paper_id = ?", (proposal.paper_id,)
                ).fetchone() is None:
                    skipped.append(
                        {"paper_id": proposal.paper_id, "reason": "paper_not_found"}
                    )
                    continue
                target_folder_id = None
                if proposal.folder_name is not None:
                    target_folder_id = folder_ids.get(proposal.folder_name)
                    if target_folder_id is None and not allow_new_folders:
                        skipped.append(
                            {
                                "paper_id": proposal.paper_id,
                                "reason": "folder_not_found",
                            }
                        )
                        continue
                    if target_folder_id is None:
                        target_folder_id = f"folder_{uuid.uuid4().hex}"
                        now = _now()
                        self.conn.execute(
                            "INSERT INTO folders "
                            "(folder_id, name, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?)",
                            (target_folder_id, proposal.folder_name, now, now),
                        )
                        folder_ids[proposal.folder_name] = target_folder_id
                valid.append(proposal)
                target_folder_ids[proposal.paper_id] = target_folder_id

            if not valid:
                self.conn.rollback()
                return {
                    "operation_id": None,
                    "applied": [],
                    "skipped": skipped,
                    "chunk_count": 0,
                }

            before = [self._state(proposal.paper_id) for proposal in valid]
            chunks = [
                valid[index : index + self.CHUNK_SIZE]
                for index in range(0, len(valid), self.CHUNK_SIZE)
            ]
            for chunk in chunks:
                self._apply_chunk(chunk, target_folder_ids)
            after = [self._state(proposal.paper_id) for proposal in valid]
            operation_id = f"classification_{uuid.uuid4().hex}"
            now = _now()
            self.conn.execute(
                "INSERT INTO batch_operations "
                "(operation_id, kind, before_json, after_json, created_at, undone_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    operation_id,
                    "classification",
                    json.dumps(before, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(after, ensure_ascii=False, separators=(",", ":")),
                    now,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "operation_id": operation_id,
            "applied": [proposal.paper_id for proposal in valid],
            "skipped": skipped,
            "chunk_count": len(chunks),
        }

    def undo(self, operation_id: str) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("operation_id_invalid")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            operation = self.conn.execute(
                "SELECT * FROM batch_operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if operation is None or operation["kind"] != "classification":
                raise ValueError("operation_not_found")
            if operation["undone_at"] is not None:
                raise ValueError("operation_already_undone")
            before = json.loads(operation["before_json"])
            after = json.loads(operation["after_json"])
            current = [self._state(state["paper_id"]) for state in after]
            if current != after:
                raise ValueError("classification_undo_conflict")
            for index in range(0, len(before), self.CHUNK_SIZE):
                self._restore_chunk(before[index : index + self.CHUNK_SIZE])
            self.conn.execute(
                "UPDATE batch_operations SET undone_at = ? WHERE operation_id = ?",
                (_now(), operation_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"operation_id": operation_id, "restored": len(before)}

    def apply_direct(
        self, action: str, paper_ids: tuple[str, ...], payload: dict[str, Any]
    ) -> dict[str, Any]:
        """原子应用用户明确指定的文件夹/标签批量操作。"""
        if action not in {"move_folder", "add_tags", "remove_tags"}:
            raise ValueError("classification_action_invalid")
        ids = self.library._paper_ids(paper_ids)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.library._require_papers(ids)
            before = [self._state(paper_id) for paper_id in ids]
            if action == "move_folder":
                folder_id = payload.get("folder_id")
                if folder_id is not None:
                    if not isinstance(folder_id, str) or not folder_id:
                        raise ValueError("folder_id_invalid")
                    self.library._require_folder(folder_id)
                now = _now()
                self.conn.executemany(
                    "UPDATE items SET folder_id=?, updated_at=? WHERE paper_id=?",
                    ((folder_id, now, paper_id) for paper_id in ids),
                )
            else:
                tags = self.library._tags(payload.get("tags", ()))
                if action == "add_tags":
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO tags(tag) VALUES (?)",
                        ((tag,) for tag in tags),
                    )
                    self.conn.executemany(
                        "INSERT OR IGNORE INTO item_tags(paper_id, tag) VALUES (?, ?)",
                        ((paper_id, tag) for paper_id in ids for tag in tags),
                    )
                else:
                    self.conn.executemany(
                        "DELETE FROM item_tags WHERE paper_id=? AND tag=?",
                        ((paper_id, tag) for paper_id in ids for tag in tags),
                    )
            after = [self._state(paper_id) for paper_id in ids]
            operation_id = f"batch_{uuid.uuid4().hex}"
            self.conn.execute(
                "INSERT INTO batch_operations "
                "(operation_id, kind, before_json, after_json, created_at, undone_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (
                    operation_id,
                    action,
                    json.dumps(before, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(after, ensure_ascii=False, separators=(",", ":")),
                    _now(),
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"operation_id": operation_id, "paper_ids": list(ids)}

    def undo_direct(self, operation_id: str) -> dict[str, Any]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT * FROM batch_operations WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None or row["kind"] not in {"move_folder", "add_tags", "remove_tags"}:
                raise ValueError("operation_not_found")
            if row["undone_at"] is not None:
                raise ValueError("operation_already_undone")
            before = json.loads(row["before_json"])
            after = json.loads(row["after_json"])
            if [self._state(state["paper_id"]) for state in after] != after:
                raise ValueError("classification_undo_conflict")
            self._restore_chunk(before)
            self.conn.execute(
                "UPDATE batch_operations SET undone_at=? WHERE operation_id=?",
                (_now(), operation_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {"operation_id": operation_id, "restored": len(before)}

    def _apply_chunk(
        self,
        proposals: list[ClassificationProposal],
        folder_ids: dict[str, str | None],
    ) -> None:
        now = _now()
        for proposal in proposals:
            self.conn.execute(
                "UPDATE items SET folder_id = ?, updated_at = ? WHERE paper_id = ?",
                (folder_ids[proposal.paper_id], now, proposal.paper_id),
            )
            self._replace_tags(proposal.paper_id, proposal.tags)

    def _restore_chunk(self, states: list[dict[str, Any]]) -> None:
        now = _now()
        for state in states:
            self.conn.execute(
                "UPDATE items SET folder_id = ?, updated_at = ? WHERE paper_id = ?",
                (state["folder_id"], now, state["paper_id"]),
            )
            self._replace_tags(state["paper_id"], tuple(state["tags"]))

    def _replace_tags(self, paper_id: str, tags: tuple[str, ...]) -> None:
        self.conn.execute("DELETE FROM item_tags WHERE paper_id = ?", (paper_id,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO tags (tag) VALUES (?)", ((tag,) for tag in tags)
        )
        self.conn.executemany(
            "INSERT INTO item_tags (paper_id, tag) VALUES (?, ?)",
            ((paper_id, tag) for tag in tags),
        )

    def _state(self, paper_id: str) -> dict[str, Any]:
        item = self.conn.execute(
            "SELECT folder_id FROM items WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        tags = [
            row["tag"]
            for row in self.conn.execute(
                "SELECT tag FROM item_tags WHERE paper_id = ? "
                "ORDER BY tag COLLATE NOCASE, tag",
                (paper_id,),
            ).fetchall()
        ]
        return {"paper_id": paper_id, "folder_id": item["folder_id"], "tags": tags}
