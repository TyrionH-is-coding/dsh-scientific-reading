"""从 SQLite 生成 XLSX，并只回写三个明确的用户字段。"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter

from .library_service import library_path
from .library_schema import migrate_library

XLSX_COLUMNS = (
    "文献名", "作者", "主要研究单位", "年份", "期刊", "标签",
    "个人思考", "个人理解程度", "用户笔记", "影响因子", "学科领域",
    "主要内容", "解决方法", "实验假设", "创新", "不足之处", "文献链接", "DOI",
    "PMID", "文献 ID", "主文件夹", "Abstract (EN)", "Abstract (ZH)",
    "阅读状态", "PDF 路径", "精读 HTML", "图表资产路径", "创建时间", "更新时间",
)
USER_FIELDS = {
    "个人思考": "personal_thoughts",
    "个人理解程度": "understanding_level",
    "用户笔记": "user_notes",
}


class XlsxSnapshotService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.target = self.data_root / "library" / "scientific-reading.xlsx"

    def refresh(self) -> dict[str, Any]:
        if self.target.is_file():
            imported = self.import_user_fields()
            if imported.get("status") == "pending":
                return imported
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
                    row["title"], "; ".join(authors), "", row["year"], row["journal"], row["tags"] or "",
                    row["personal_thoughts"] or "", row["understanding_level"] or "", row["user_notes"] or "",
                    "", "", "", "", "", "", "", row["source_url"] or "", row["doi"], row["pmid"], row["paper_id"],
                    row["folder_name"] or "", row["abstract_en"] or "",
                    row["abstract_zh"] or "", row["status"], row["pdf_path"] or "", row["html_path"] or "", row["asset_paths"] or "",
                    row["created_at"], row["updated_at"],
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
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(XLSX_COLUMNS))}{max(1, sheet.max_row)}"
        sheet.row_dimensions[1].height = 28
        header_fill = PatternFill("solid", fgColor="1F4E78")
        user_fill = PatternFill("solid", fgColor="FFF2CC")
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        widths = {
            "文献名": 42, "作者": 24, "主要研究单位": 22, "期刊": 20, "标签": 18,
            "个人思考": 32, "个人理解程度": 16, "用户笔记": 32,
            "主要内容": 34, "解决方法": 30, "实验假设": 28, "创新": 26, "不足之处": 26,
            "文献链接": 34, "Abstract (EN)": 44, "Abstract (ZH)": 44,
            "PDF 路径": 34, "精读 HTML": 34, "图表资产路径": 34,
        }
        for column, name in enumerate(XLSX_COLUMNS, 1):
            sheet.column_dimensions[get_column_letter(column)].width = widths.get(name, 15)
            for cell in sheet.iter_cols(min_col=column, max_col=column, min_row=2):
                for value in cell:
                    value.alignment = Alignment(vertical="top", wrap_text=True)
                    if name in USER_FIELDS:
                        value.fill = user_fill
                        value.protection = Protection(locked=False)
        sheet.protection.sheet = True
        sheet.protection.autoFilter = False
        sheet.protection.selectUnlockedCells = False
        identity = workbook.create_sheet("_身份")
        identity.append(("row", "paper_id"))
        paper_id_column = XLSX_COLUMNS.index("文献 ID") + 1
        for row_number in range(2, sheet.max_row + 1):
            identity.append((row_number, sheet.cell(row_number, paper_id_column).value))
        identity.sheet_state = "veryHidden"
        note = workbook.create_sheet("说明")
        note.append(("说明",))
        note.append(("仅“个人思考、个人理解程度、用户笔记”三列会回写 SQLite；其余字段由系统维护。",))
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

    def import_user_fields(self) -> dict[str, Any]:
        if not self.target.is_file():
            return {"status": "success", "updated": 0, "conflicts": 0}
        try:
            workbook = load_workbook(self.target)
        except PermissionError as error:
            self._set_meta("1", "xlsx_read_permission_denied")
            return {"status": "pending", "path": str(self.target), "error": {"code": "xlsx_read_permission_denied", "detail": str(error)}}
        conflicts: list[dict[str, Any]] = []
        updates: list[tuple[str, str, str, str]] = []
        try:
            if "文献" not in workbook.sheetnames or "_身份" not in workbook.sheetnames:
                return {"status": "success", "updated": 0, "conflicts": 0}
            sheet = workbook["文献"]
            headers = {cell.value: cell.column for cell in sheet[1]}
            required = {"文献 ID", *USER_FIELDS}
            if not required.issubset(headers):
                raise ValueError("xlsx_user_columns_missing")
            expected = {
                int(row[0]): str(row[1])
                for row in workbook["_身份"].iter_rows(min_row=2, values_only=True)
                if isinstance(row[0], int) and isinstance(row[1], str)
            }
            seen: set[str] = set()
            for row_number in range(2, sheet.max_row + 1):
                paper_id = sheet.cell(row_number, headers["文献 ID"]).value
                if not isinstance(paper_id, str) or expected.get(row_number) != paper_id:
                    conflicts.append({"row": row_number, "code": "identity_changed"})
                    continue
                if paper_id in seen:
                    conflicts.append({"row": row_number, "code": "identity_duplicate"})
                    continue
                seen.add(paper_id)
                values = [sheet.cell(row_number, headers[name]).value for name in USER_FIELDS]
                updates.append(tuple("" if value is None else str(value) for value in values) + (paper_id,))
        finally:
            workbook.close()
        migrate_library(self.data_root)
        with sqlite3.connect(str(library_path(self.data_root))) as conn:
            known = {row[0] for row in conn.execute("SELECT paper_id FROM items")}
            valid = []
            for update in updates:
                if update[-1] not in known:
                    conflicts.append({"paper_id": update[-1], "code": "identity_unknown"})
                else:
                    valid.append(update)
            conn.executemany(
                "UPDATE items SET personal_thoughts=?, understanding_level=?, user_notes=? WHERE paper_id=?",
                valid,
            )
            conn.execute(
                "INSERT OR REPLACE INTO library_meta(key,value) VALUES('xlsx_conflicts',?)",
                (json.dumps(conflicts, ensure_ascii=False),),
            )
        return {"status": "success", "updated": len(valid), "conflicts": len(conflicts)}

    def locate(self, paper_id: str, *, opener=None) -> dict[str, Any]:
        if not isinstance(paper_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id) or ".." in paper_id:
            raise ValueError("paper_id_invalid")
        if not self.target.is_file():
            raise ValueError("xlsx_not_generated")
        workbook = load_workbook(self.target, read_only=True)
        try:
            sheet = workbook["文献"]
            headers = {cell.value: cell.column for cell in sheet[1]}
            column = headers.get("文献 ID")
            row_number = next((row for row in range(2, sheet.max_row + 1) if sheet.cell(row, column).value == paper_id), None) if column else None
        finally:
            workbook.close()
        if row_number is None:
            raise ValueError("xlsx_identity_not_found")
        selected = (opener or self._open_excel)(self.target, row_number)
        return {"status": "opened", "paper_id": paper_id, "row": row_number, "selected": bool(selected)}

    @staticmethod
    def _open_excel(path: Path, row_number: int) -> bool:
        try:
            import win32com.client  # type: ignore[import-not-found]

            excel = win32com.client.Dispatch("Excel.Application")
            workbook = excel.Workbooks.Open(str(path))
            workbook.Worksheets("文献").Cells(row_number, 1).Select()
            excel.Visible = True
            return True
        except (ImportError, OSError):
            if os.name != "nt":
                raise ValueError("excel_unavailable")
            os.startfile(path)  # type: ignore[attr-defined]
            return False

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
