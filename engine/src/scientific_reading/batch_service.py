"""批量选择分块、逐项调度和父级汇总。"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

from .classification_service import ClassificationService
from .library_service import LibraryService
from .workspace import atomic_write_json

ALLOWED_ACTIONS = {
    "move_folder", "add_tags", "remove_tags",
    "queue_full_read", "retry_failed", "feishu_resync",
}
CHUNK_SIZE = 100
_RESULT_STATES = {"created", "reused", "needs_user", "failed"}


class BatchService:
    def __init__(
        self,
        data_root: Path,
        *,
        library: LibraryService | None = None,
        queue_full_read: Callable[[str], dict[str, Any]] | None = None,
        retry_failed: Callable[[str], dict[str, Any]] | None = None,
        feishu_resync: Callable[[str], dict[str, Any]] | None = None,
        persist: Callable[[Path, dict[str, Any]], None] = atomic_write_json,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.library = library
        self._owns_library = library is None
        self.queue_full_read = queue_full_read
        self.retry_failed = retry_failed
        self.feishu_resync = feishu_resync
        self.persist = persist

    def submit(self, action: str, paper_ids: Sequence[str], payload: dict) -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            raise ValueError("batch_action_invalid")
        if isinstance(paper_ids, (str, bytes)):
            raise ValueError("batch_selection_required")
        selection = list(dict.fromkeys(paper_ids))
        if not selection:
            raise ValueError("batch_selection_required")
        if not isinstance(payload, dict):
            raise ValueError("batch_payload_invalid")
        library = self.library or LibraryService(self.data_root)
        try:
            chunks = [selection[index:index + CHUNK_SIZE] for index in range(0, len(selection), CHUNK_SIZE)]
            parent_job_id = f"job_{uuid.uuid4().hex[:16]}"
            path = self._path(parent_job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            result = {
                "parent_job_id": parent_job_id,
                "status": "running",
                "action": action,
                "selection": selection,
                "chunks": chunks,
                "children": [{"paper_id": paper_id, "status": "pending"} for paper_id in selection],
                "summary": {"total": len(selection), "created": 0, "reused": 0, "needs_user": 0, "failed": 0, "pending": len(selection)},
            }
            self.persist(path, result)
            operation_id = None
            try:
                if action in {"move_folder", "add_tags", "remove_tags"}:
                    valid = []
                    missing = set()
                    for paper_id in selection:
                        try:
                            library.get_item(paper_id)
                            valid.append(paper_id)
                        except ValueError:
                            missing.add(paper_id)
                    if valid:
                        applied = ClassificationService(library).apply_direct(action, tuple(valid), payload)
                        operation_id = applied["operation_id"]
                        result["operation_id"] = operation_id
                    children = [
                        {"paper_id": paper_id, "status": "failed", "error": "paper_not_found"}
                        if paper_id in missing else {"paper_id": paper_id, "status": "created"}
                        for paper_id in selection
                    ]
                    result["children"] = children
                    result["summary"] = self._summary(children, len(selection))
                    self.persist(path, result)
                else:
                    children = []
                    for chunk in chunks:
                        for paper_id in chunk:
                            children.append(self._dispatch(library, action, paper_id, payload))
                            result["children"] = children + [
                                {"paper_id": remaining, "status": "pending"}
                                for remaining in selection[len(children):]
                            ]
                            result["summary"] = self._summary(result["children"], len(selection))
                            self.persist(path, result)
                result["children"] = children
                result["summary"] = self._summary(children, len(selection))
                result["status"] = "completed"
                self.persist(path, result)
            except Exception:
                result["status"] = "failed"
                result["error"] = "batch_operation_failed"
                if operation_id is not None:
                    result["operation_id"] = operation_id
                try:
                    self.persist(path, result)
                except Exception:
                    pass
            return result
        finally:
            if self._owns_library:
                library.close()

    def inspect(self, parent_job_id: str) -> dict[str, Any]:
        if not isinstance(parent_job_id, str) or not re.fullmatch(r"job_[0-9a-f]{16}", parent_job_id):
            raise ValueError("batch_parent_job_invalid")
        return json.loads(self._path(parent_job_id).read_text(encoding="utf-8"))

    def undo(self, operation_id: str) -> dict[str, Any]:
        library = self.library or LibraryService(self.data_root)
        try:
            return ClassificationService(library).undo_direct(operation_id)
        finally:
            if self._owns_library:
                library.close()

    def _dispatch(self, library: LibraryService, action: str, paper_id: str, payload: dict) -> dict[str, Any]:
        try:
            item = library.get_item(paper_id)
            if action == "retry_failed" and item.get("full_read_status") not in {"处理失败", "failed"}:
                return {"paper_id": paper_id, "status": "reused", "reason": "not_failed"}
            if action == "feishu_resync" and not payload.get("explicit") and item.get("feishu_sync_state") != "pending":
                return {"paper_id": paper_id, "status": "reused", "reason": "not_pending"}
            callback = {
                "queue_full_read": self.queue_full_read,
                "retry_failed": self.retry_failed,
                "feishu_resync": self.feishu_resync,
            }[action]
            if callback is None:
                raise ValueError("batch_action_unavailable")
            value = callback(paper_id)
            status = value.get("status") if isinstance(value, dict) else None
            if status not in _RESULT_STATES:
                return {"paper_id": paper_id, "status": "failed", "error": "batch_item_failed"}
            child = {"paper_id": paper_id, "status": status}
            if isinstance(value, dict):
                for key in ("job_id", "reason"):
                    if isinstance(value.get(key), str):
                        child[key] = value[key]
            return child
        except Exception as error:
            code = str(error)
            if code not in {"paper_not_found"}:
                code = "batch_item_failed"
            return {"paper_id": paper_id, "status": "failed", "error": code}

    @staticmethod
    def _summary(children: list[dict[str, Any]], total: int | None = None) -> dict[str, int]:
        result = {"total": len(children) if total is None else total, "created": 0, "reused": 0, "needs_user": 0, "failed": 0, "pending": 0}
        for child in children:
            result[child["status"]] += 1
        return result

    def _path(self, parent_job_id: str) -> Path:
        batches = self.data_root / "jobs" / "batches"
        resolved_root = self.data_root.resolve()
        resolved_batches = batches.resolve()
        if not resolved_batches.is_relative_to(resolved_root):
            raise ValueError("batch_storage_invalid")
        candidate = (batches / f"{parent_job_id}.json").resolve()
        if candidate.parent != resolved_batches:
            raise ValueError("batch_storage_invalid")
        return candidate
