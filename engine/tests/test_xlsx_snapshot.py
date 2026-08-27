import sqlite3
from pathlib import Path

import openpyxl

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.xlsx_snapshot import XlsxSnapshotService, XLSX_COLUMNS


def _seed(root: Path, count: int = 2) -> None:
    service = LibraryService(root)
    for i in range(count):
        service.ingest(PaperMetadata(title=f"中文文献 {i}", authors=[f"作者{i}"], year=2024 + i, journal="期刊", doi=f"10.1000/{i}", pmid=str(100+i), abstract_en="English", abstract_zh="中文摘要"))
    service.close()


def test_snapshot_has_fixed_columns_all_rows_and_readme_sheet(tmp_path):
    _seed(tmp_path, 3)
    result = XlsxSnapshotService(tmp_path).refresh()
    assert result["status"] == "success"
    workbook = openpyxl.load_workbook(tmp_path / "library" / "scientific-reading.xlsx")
    assert workbook.sheetnames == ["文献", "_身份", "说明"]
    sheet = workbook["文献"]
    assert tuple(cell.value for cell in next(sheet.iter_rows())) == XLSX_COLUMNS
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) == 4
    assert rows[1][0] == "中文文献 0"
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == f"A1:{sheet.cell(1, len(XLSX_COLUMNS)).column_letter}{sheet.max_row}"
    assert sheet.column_dimensions["A"].width >= 30
    assert sheet["A1"].fill.fill_type == "solid"
    assert sheet["A2"].alignment.wrap_text is True
    workbook.close()


def test_snapshot_preserves_source_url_from_sqlite(tmp_path):
    source_url = "https://publisher.example/papers/42"
    service = LibraryService(tmp_path)
    service.ingest(
        PaperMetadata(title="URL paper", doi="10.1000/url", source_url=source_url)
    )
    service.close()

    assert XlsxSnapshotService(tmp_path).refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(
        tmp_path / "library" / "scientific-reading.xlsx", read_only=True
    )
    rows = list(workbook["文献"].iter_rows(values_only=True))
    workbook.close()
    headers = {value: index for index, value in enumerate(rows[0])}
    assert rows[1][headers["文献链接"]] == source_url


def test_only_user_columns_are_imported_and_identity_conflicts_are_recorded(tmp_path):
    _seed(tmp_path, 2)
    service = XlsxSnapshotService(tmp_path)
    assert service.refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    first_id = sheet.cell(2, headers["文献 ID"]).value
    original_title = sheet.cell(2, headers["文献名"]).value
    sheet.cell(2, headers["个人思考"], "自己的判断")
    sheet.cell(2, headers["个人理解程度"], "基本理解")
    sheet.cell(2, headers["用户笔记"], "复习图 2")
    sheet.cell(2, headers["文献名"], "不得回写的题名")
    sheet.cell(3, headers["文献 ID"], "changed_identity")
    workbook.save(service.target)
    workbook.close()

    result = service.import_user_fields()
    assert result["updated"] == 1
    assert result["conflicts"] == 1
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM items WHERE paper_id=?", (first_id,)).fetchone()
    assert row["title"] == original_title
    assert row["personal_thoughts"] == "自己的判断"
    assert row["understanding_level"] == "基本理解"
    assert row["user_notes"] == "复习图 2"
    conflicts = conn.execute("SELECT value FROM library_meta WHERE key='xlsx_conflicts'").fetchone()[0]
    conn.close()
    assert "identity_changed" in conflicts


def test_permission_error_keeps_old_file_and_records_pending_then_retry(tmp_path, monkeypatch):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    target = tmp_path / "library" / "scientific-reading.xlsx"
    old = target.read_bytes()
    real_replace = __import__("os").replace
    def locked(src, dst):
        if str(dst) == str(target):
            raise PermissionError("locked")
        return real_replace(src, dst)
    monkeypatch.setattr("scientific_reading.xlsx_snapshot.os.replace", locked)
    result = service.refresh()
    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_replace_permission_denied"
    assert target.read_bytes() == old
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    meta = dict(conn.execute("SELECT key,value FROM library_meta"))
    conn.close()
    assert meta["xlsx_pending"] == "1"
    assert meta["xlsx_error"] == "xlsx_replace_permission_denied"
    monkeypatch.setattr("scientific_reading.xlsx_snapshot.os.replace", real_replace)
    assert service.refresh()["status"] == "success"
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    meta = dict(conn.execute("SELECT key,value FROM library_meta"))
    conn.close()
    assert meta.get("xlsx_pending") == "0"
    assert meta.get("xlsx_error") in (None, "")
