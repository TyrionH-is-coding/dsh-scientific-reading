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
from .data_guard import root_operation

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
REVIEW_COLUMNS = (
    "父会话 ID", "论文标题", "文献 ID", "整理子会话 ID", "结论类型",
    "确认结论", "证据位置", "确认时间",
)
ASSET_COLUMNS = (
    "文献 ID", "文献名", "资产 ID", "类型", "PDF 页码", "中文图注",
    "源文图注", "图片路径", "表格 HTML 路径", "精读定位",
)


class XlsxSnapshotService:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve()
        self.target = self.data_root / "library" / "scientific-reading.xlsx"

    @root_operation
    def refresh(self) -> dict[str, Any]:
        if self.target.is_file():
            imported = self.import_user_fields()
            if imported.get("status") == "pending":
                return imported
        rows = self._rows()
        review_rows = self._review_rows()
        asset_rows = self._asset_rows()
        self.target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            temporary = self._write_temp(rows, review_rows, asset_rows)
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

    def _review_rows(self) -> list[tuple[Any, ...]]:
        migrate_library(self.data_root)
        conn = sqlite3.connect(str(library_path(self.data_root)))
        try:
            return [
                tuple(row)
                for row in conn.execute(
                    "SELECT rc.parent_session_id, i.title, rc.paper_id, "
                    "rc.review_session_id, rc.conclusion_type, rc.conclusion_text, "
                    "rc.evidence_locator, rc.confirmed_at "
                    "FROM review_conclusions rc "
                    "JOIN items i ON i.paper_id=rc.paper_id "
                    "ORDER BY rc.confirmed_at, rc.rowid"
                )
            ]
        finally:
            conn.close()

    def _rows(self) -> list[tuple[Any, ...]]:
        migrate_library(self.data_root)
        conn = sqlite3.connect(str(library_path(self.data_root)))
        conn.row_factory = sqlite3.Row
        try:
            result: list[tuple[Any, ...]] = []
            query = (
                "SELECT i.*, f.name AS folder_name, a.rel_path AS pdf_path, "
                "(SELECT rel_path FROM artifacts WHERE paper_id=i.paper_id "
                "AND kind IN ('reader','full_read_html','full_read') AND status='ready' "
                "ORDER BY updated_at DESC LIMIT 1) AS html_path, "
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

    def _asset_rows(self) -> list[tuple[Any, ...]]:
        migrate_library(self.data_root)
        conn = sqlite3.connect(str(library_path(self.data_root)))
        conn.row_factory = sqlite3.Row
        try:
            papers = list(
                conn.execute(
                    "SELECT i.paper_id, i.title, a.rel_path AS pdf_path, "
                    "a.sha256 AS source_sha256, "
                    "(SELECT rel_path FROM artifacts WHERE paper_id=i.paper_id "
                    "AND kind IN ('reader','full_read_html','full_read') "
                    "AND status='ready' ORDER BY updated_at DESC LIMIT 1) AS html_path "
                    "FROM items i LEFT JOIN attachments a ON a.paper_id=i.paper_id "
                    "ORDER BY i.created_at, i.paper_id"
                )
            )
        finally:
            conn.close()
        result: list[tuple[Any, ...]] = []
        for paper in papers:
            source_sha = paper["source_sha256"]
            if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha):
                continue
            paper_root = self.data_root / "papers" / paper["paper_id"]
            generation_root = paper_root / "generations" / source_sha[:16]
            manifest = self._load_json(generation_root / "manifest.json")
            assets = manifest.get("assets") if isinstance(manifest, dict) else None
            if not isinstance(assets, list):
                continue
            generation_prefix = generation_root.relative_to(paper_root).as_posix()
            reader_rel = self._active_reader_rel(
                paper_root, generation_root, paper["html_path"]
            )
            reader_manifest = self._load_json(
                generation_root / "reading" / "reader-manifest.json"
            )
            caption_blocks: dict[str, str] = {}
            for asset in reader_manifest.get("assets", []) if isinstance(reader_manifest, dict) else []:
                if not isinstance(asset, dict):
                    continue
                logical_id = self._logical_asset_id(asset.get("id"), asset.get("path"))
                block_id = asset.get("caption_block_id")
                if logical_id and isinstance(block_id, str) and block_id:
                    caption_blocks.setdefault(logical_id, block_id)
            translations = self._load_json(
                generation_root / "reading" / "full" / "translations.json"
            )
            translated_captions = {
                item["block_id"]: item["translation_zh"]
                for item in translations.get("translations", [])
                if isinstance(item, dict)
                and isinstance(item.get("block_id"), str)
                and isinstance(item.get("translation_zh"), str)
            } if isinstance(translations, dict) else {}
            grouped: dict[str, dict[str, Any]] = {}
            for asset in assets:
                if not isinstance(asset, dict):
                    continue
                rel_path = self._safe_generation_file(
                    generation_root, asset.get("relative_path")
                )
                logical_id = self._logical_asset_id(
                    asset.get("asset_id"), asset.get("relative_path")
                )
                kind = asset.get("kind")
                if not logical_id or kind not in {"figure", "table"} or not rel_path:
                    continue
                row = grouped.setdefault(
                    logical_id,
                    {
                        "kind": kind,
                        "page": asset.get("page"),
                        "caption": asset.get("caption") or "",
                        "image": "",
                        "html": "",
                    },
                )
                suffix = Path(rel_path).suffix.lower()
                paper_rel = f"{generation_prefix}/{rel_path}"
                if suffix == ".html":
                    row["html"] = paper_rel
                else:
                    row["image"] = paper_rel
                structured = self._safe_generation_file(
                    generation_root, asset.get("structured_path")
                )
                if structured:
                    row["html"] = f"{generation_prefix}/{structured}"
                if not row["caption"] and asset.get("caption"):
                    row["caption"] = asset["caption"]
                if not row["page"] and asset.get("page"):
                    row["page"] = asset["page"]
            for asset_id, asset in grouped.items():
                caption_block = caption_blocks.get(asset_id, "")
                reader_locator = (
                    f"{reader_rel}#block-{caption_block}"
                    if reader_rel and caption_block else ""
                )
                result.append((
                    paper["paper_id"], paper["title"], asset_id,
                    "图" if asset["kind"] == "figure" else "表",
                    asset["page"], translated_captions.get(caption_block, ""),
                    asset["caption"], asset["image"], asset["html"], reader_locator,
                ))
        return result

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _logical_asset_id(asset_id: Any, rel_path: Any) -> str:
        if not isinstance(asset_id, str) or not asset_id:
            return ""
        if isinstance(rel_path, str) and Path(rel_path).suffix.lower() == ".html":
            return asset_id.removesuffix("-html")
        return asset_id

    @staticmethod
    def _safe_generation_file(generation_root: Path, rel_path: Any) -> str:
        if not isinstance(rel_path, str) or not rel_path or Path(rel_path).is_absolute():
            return ""
        root = generation_root.resolve()
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return ""
        return Path(rel_path).as_posix() if candidate.is_file() else ""

    @staticmethod
    def _active_reader_rel(
        paper_root: Path, generation_root: Path, rel_path: Any
    ) -> str:
        if not isinstance(rel_path, str) or not rel_path or Path(rel_path).is_absolute():
            return ""
        root = paper_root.resolve()
        generation = generation_root.resolve()
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(generation)
        except ValueError:
            return ""
        return Path(rel_path).as_posix() if candidate.is_file() else ""

    def _write_temp(
        self,
        rows: list[tuple[Any, ...]],
        review_rows: list[tuple[Any, ...]],
        asset_rows: list[tuple[Any, ...]],
    ) -> Path:
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
        headers = {cell.value: cell.column for cell in sheet[1]}
        asset_positions: dict[str, tuple[int, int]] = {}
        for asset_row_number, asset_row in enumerate(asset_rows, 2):
            paper_id = str(asset_row[0])
            if paper_id in asset_positions:
                first, count = asset_positions[paper_id]
                asset_positions[paper_id] = (first, count + 1)
            else:
                asset_positions[paper_id] = (asset_row_number, 1)
        for row_number in range(2, sheet.max_row + 1):
            paper_id = sheet.cell(row_number, headers["文献 ID"]).value
            for name in ("PDF 路径", "精读 HTML"):
                cell = sheet.cell(row_number, headers[name])
                target = self._paper_link(paper_id, cell.value)
                if target:
                    cell.hyperlink = target
                    cell.style = "Hyperlink"
            source_cell = sheet.cell(row_number, headers["文献链接"])
            if isinstance(source_cell.value, str) and source_cell.value.startswith(("http://", "https://")):
                source_cell.hyperlink = source_cell.value
                source_cell.style = "Hyperlink"
            if paper_id in asset_positions:
                first, count = asset_positions[paper_id]
                asset_cell = sheet.cell(row_number, headers["图表资产路径"])
                asset_cell.value = f"查看 {count} 项"
                asset_cell.hyperlink = f"#'图表资产'!A{first}"
                asset_cell.style = "Hyperlink"
        sheet.protection.sheet = True
        sheet.protection.autoFilter = False
        sheet.protection.selectUnlockedCells = False
        asset_sheet = workbook.create_sheet("图表资产")
        asset_sheet.append(ASSET_COLUMNS)
        for row in asset_rows:
            asset_sheet.append(row)
        asset_sheet.freeze_panes = "A2"
        asset_sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(ASSET_COLUMNS))}{max(1, asset_sheet.max_row)}"
        )
        asset_sheet.row_dimensions[1].height = 28
        asset_headers = {cell.value: cell.column for cell in asset_sheet[1]}
        for cell in asset_sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        asset_widths = (24, 42, 28, 10, 10, 38, 38, 42, 42, 42)
        for column, width in enumerate(asset_widths, 1):
            asset_sheet.column_dimensions[get_column_letter(column)].width = width
            for cells in asset_sheet.iter_cols(min_col=column, max_col=column, min_row=2):
                for cell in cells:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        for row_number in range(2, asset_sheet.max_row + 1):
            paper_id = asset_sheet.cell(row_number, asset_headers["文献 ID"]).value
            page = asset_sheet.cell(row_number, asset_headers["PDF 页码"]).value
            pdf_row = next((row for row in rows if row[19] == paper_id), None)
            if pdf_row is not None:
                page_cell = asset_sheet.cell(row_number, asset_headers["PDF 页码"])
                target = self._paper_link(paper_id, pdf_row[24], f"page={page}")
                if target:
                    page_cell.hyperlink = target
                    page_cell.style = "Hyperlink"
            for name in ("图片路径", "表格 HTML 路径", "精读定位"):
                cell = asset_sheet.cell(row_number, asset_headers[name])
                value = cell.value
                fragment = None
                if isinstance(value, str) and "#" in value:
                    value, fragment = value.split("#", 1)
                target = self._paper_link(paper_id, value, fragment)
                if target:
                    cell.hyperlink = target
                    cell.style = "Hyperlink"
        asset_sheet.protection.sheet = True
        asset_sheet.protection.autoFilter = False
        review_sheet = workbook.create_sheet("整理结论")
        review_sheet.append(REVIEW_COLUMNS)
        for row in review_rows:
            review_sheet.append(row)
        review_sheet.freeze_panes = "A2"
        review_sheet.auto_filter.ref = (
            f"A1:{get_column_letter(len(REVIEW_COLUMNS))}{max(1, review_sheet.max_row)}"
        )
        review_widths = (24, 42, 24, 24, 16, 52, 28, 24)
        for cell in review_sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True
            )
        for column, width in enumerate(review_widths, 1):
            review_sheet.column_dimensions[get_column_letter(column)].width = width
            for cells in review_sheet.iter_cols(
                min_col=column, max_col=column, min_row=2
            ):
                for cell in cells:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        review_sheet.protection.sheet = True
        review_sheet.protection.autoFilter = False
        identity = workbook.create_sheet("_身份")
        identity.append(("row", "paper_id"))
        paper_id_column = XLSX_COLUMNS.index("文献 ID") + 1
        for row_number in range(2, sheet.max_row + 1):
            identity.append((row_number, sheet.cell(row_number, paper_id_column).value))
        identity.sheet_state = "veryHidden"
        note = workbook.create_sheet("说明")
        note.append(("说明",))
        note.append(("仅“个人思考、个人理解程度、用户笔记”三列会回写 SQLite；其余字段由系统维护。",))
        note.append(("“整理结论”来自论文整理子会话中经用户明确确认的结论，只读展示且逐条保留。",))
        note.append(("“图表资产”从当前 PDF 对应的解析清单生成，为只读视图；路径可点击并保留为可复制文本。",))
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

    def _paper_link(
        self, paper_id: Any, rel_path: Any, fragment: str | None = None
    ) -> str:
        if not isinstance(paper_id, str) or not isinstance(rel_path, str) or not rel_path:
            return ""
        paper_root = (self.data_root / "papers" / paper_id).resolve()
        if Path(rel_path).is_absolute():
            return ""
        candidate = (paper_root / rel_path).resolve()
        try:
            candidate.relative_to(paper_root)
        except ValueError:
            return ""
        if not candidate.exists():
            return ""
        target = os.path.relpath(candidate, self.target.parent).replace(os.sep, "/")
        return f"{target}#{fragment}" if fragment else target

    @root_operation
    def import_user_fields(self) -> dict[str, Any]:
        if not self.target.is_file():
            return {"status": "success", "updated": 0, "conflicts": 0}
        try:
            workbook = load_workbook(self.target)
        except PermissionError as error:
            return self._pending_import("xlsx_read_permission_denied", str(error))
        except Exception as error:
            return self._pending_import("xlsx_read_failed", str(error))
        conflicts: list[dict[str, Any]] = []
        updates: list[tuple[str, str, str, str]] = []
        try:
            if "文献" not in workbook.sheetnames or "_身份" not in workbook.sheetnames:
                return self._pending_import(
                    "xlsx_required_sheets_missing",
                    "已保留原工作簿；请恢复“文献”和“_身份”工作表后重试。",
                )
            sheet = workbook["文献"]
            header_values = [cell.value for cell in sheet[1]]
            required = {"文献 ID", *USER_FIELDS}
            if not required.issubset(header_values):
                return self._pending_import(
                    "xlsx_user_columns_missing",
                    "已保留原工作簿；请恢复文献 ID、个人思考、个人理解程度和用户笔记列名后重试。",
                )
            if any(header_values.count(name) > 1 for name in required):
                return self._pending_import(
                    "xlsx_user_columns_ambiguous",
                    "已保留原工作簿；请删除文献 ID 或用户字段的重复表头后重试。",
                )
            headers = {cell.value: cell.column for cell in sheet[1]}
            identity = workbook["_身份"]
            if tuple(cell.value for cell in identity[1][:2]) != ("row", "paper_id"):
                return self._pending_import(
                    "xlsx_identity_columns_invalid",
                    "已保留原工作簿；请恢复身份表的 row 和 paper_id 列名后重试。",
                )
            expected: dict[int, str] = {}
            ambiguous_rows: set[int] = set()
            for row in identity.iter_rows(min_row=2, values_only=True):
                if not isinstance(row[0], int) or not isinstance(row[1], str):
                    continue
                row_number = int(row[0])
                if row_number in expected or row_number in ambiguous_rows:
                    expected.pop(row_number, None)
                    ambiguous_rows.add(row_number)
                else:
                    expected[row_number] = str(row[1])
            conflicts.extend(
                {"row": row_number, "code": "identity_ambiguous"}
                for row_number in sorted(ambiguous_rows)
            )
            conflicts.extend(
                {"row": row_number, "code": "identity_missing"}
                for row_number in sorted(set(expected).difference(range(2, sheet.max_row + 1)))
            )
            seen: set[str] = set()
            for row_number in range(2, sheet.max_row + 1):
                if row_number in ambiguous_rows:
                    continue
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
        result = {"status": "success", "updated": len(valid), "conflicts": len(conflicts)}
        if conflicts:
            result.update(self._pending_import(
                "xlsx_identity_conflict",
                "已保留原工作簿和冲突行笔记；请修正文献 ID 与行身份的冲突后重试。",
            ))
        return result

    def _pending_import(self, code: str, detail: str) -> dict[str, Any]:
        self._set_meta("1", code)
        return {
            "status": "pending",
            "path": str(self.target),
            "error": {"code": code, "detail": detail},
        }

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
