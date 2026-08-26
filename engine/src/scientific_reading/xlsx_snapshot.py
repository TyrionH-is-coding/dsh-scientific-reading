"""从本地 SQLite 生成只读 XLSX 派生快照。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook

from .library_service import library_path
from .library_schema import migrate_library

XLSX_COLUMNS = (
    "文献名", "作者", "主要研究单位", "年份", "期刊", "影响因子", "学科领域",
    "主要内容", "解决方法", "实验假设", "创新", "不足之处", "文献链接", "DOI",
    "PMID", "文献 ID", "主文件夹", "标签", "Abstract (EN)", "Abstract (ZH)",
    "阅读状态", "PDF 路径", "精读 HTML", "图表资产路径", "飞书链接", "创建时间", "更新时间",
)


class XlsxSnapshotService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.target = self.data_root / "library" / "scientific-reading.xlsx"

    def refresh(self) -> dict[str, Any]:
        rows = self._rows()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            temporary = self._write_temp(rows)
            os.replace(temporary, self.target)
        except PermissionError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            self._set_meta("1", "xlsx_replace_permission_denied")
            return {
                "status": "pending",
                "path": str(self.target),
                "error": {"code": "xlsx_replace_permission_denied", "detail": str(error)},
            }
        except (OSError, sqlite3.Error, ValueError) as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            self._set_meta("1", "xlsx_snapshot_failed")
            return {
                "status": "failed",
                "path": str(self.target),
                "error": {"code": "xlsx_snapshot_failed", "detail": str(error)},
            }
        self._set_meta("0", None)
        return {"status": "success", "path": str(self.target), "rows": len(rows)}

    def _rows(self) -> list[tuple[Any, ...]]:
        migrate_library(self.data_root)
        conn = sqlite3.connect(str(library_path(self.data_root)))
        conn.row_factory = sqlite3.Row
        try:
            result: list[tuple[Any, ...]] = []
            query = (
                "SELECT i.*, f.name AS folder_name, a.rel_path AS pdf_path, "
                "(SELECT rel_path FROM artifacts WHERE paper_id=i.paper_id "
                "AND kind IN ('full_read_html','full_read') ORDER BY updated_at DESC LIMIT 1) AS html_path, "
                "(SELECT GROUP_CONCAT(rel_path) FROM artifacts WHERE paper_id=i.paper_id "
                "AND kind IN ('figure_asset','table_asset','asset')) AS asset_paths, "
                "GROUP_CONCAT(DISTINCT it.tag) AS tags "
                "FROM items i LEFT JOIN folders f ON f.folder_id=i.folder_id "
                "LEFT JOIN attachments a ON a.paper_id=i.paper_id "
                "LEFT JOIN item_tags it ON it.paper_id=i.paper_id "
                "GROUP BY i.paper_id ORDER BY i.created_at, i.paper_id"
            )
            for row in conn.execute(query):
                authors = json.loads(row["authors_json"] or "[]")
                result.append((
                    row["title"], "; ".join(authors), "", row["year"], row["journal"], "", "",
                    "", "", "", "", "", row["source_url"] or "", row["doi"], row["pmid"], row["paper_id"],
                    row["folder_name"] or "", row["tags"] or "", row["abstract_en"] or "",
                    row["abstract_zh"] or "", row["status"], row["pdf_path"] or "", row["html_path"] or "", row["asset_paths"] or "",
                    row["feishu_record_url"] or "", row["created_at"], row["updated_at"],
                ))
            return result
        finally:
            conn.close()

    def _write_temp(self, rows: list[tuple[Any, ...]]) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "文献"
        sheet.append(XLSX_COLUMNS)
        for row in rows:
            sheet.append(row)
        note = workbook.create_sheet("说明")
        note.append(("说明",))
        note.append(("本文件是从 SQLite 生成的只读派生快照；修改本文件不会回写主库。",))
        handle, name = tempfile.mkstemp(prefix=".scientific-reading-", suffix=".xlsx", dir=self.target.parent)
        os.close(handle)
        path = Path(name)
        try:
            workbook.save(path)
            with path.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            workbook.close()
        return path

    def _set_meta(self, pending: str, error: str | None) -> None:
        conn = sqlite3.connect(str(library_path(self.data_root)))
        try:
            conn.execute("INSERT OR REPLACE INTO library_meta(key,value) VALUES('xlsx_pending',?)", (pending,))
            if error:
                conn.execute("INSERT OR REPLACE INTO library_meta(key,value) VALUES('xlsx_error',?)", (error,))
            else:
                conn.execute("DELETE FROM library_meta WHERE key='xlsx_error'")
            conn.commit()
        finally:
            conn.close()
