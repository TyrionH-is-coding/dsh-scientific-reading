import json
import sqlite3
from pathlib import Path

import openpyxl
import pytest

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.review_service import ReviewService
from scientific_reading.xlsx_snapshot import REVIEW_COLUMNS, XlsxSnapshotService, XLSX_COLUMNS


def _seed(root: Path, count: int = 2) -> None:
    service = LibraryService(root)
    for i in range(count):
        service.ingest(PaperMetadata(title=f"中文文献 {i}", authors=[f"作者{i}"], year=2024 + i, journal="期刊", doi=f"10.1000/{i}", pmid=str(100+i), abstract_en="English", abstract_zh="中文摘要"))
    service.close()


@pytest.mark.parametrize("lock_name", ["~$scientific-reading.xlsx", ".~lock.scientific-reading.xlsx#"])
def test_open_spreadsheet_preserves_file_and_defers_import(tmp_path, lock_name):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    assert service.refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    sheet.cell(2, XLSX_COLUMNS.index("用户笔记") + 1, "已保存但仍在编辑")
    workbook.save(service.target)
    workbook.close()
    before = service.target.read_bytes()
    lock = service.target.with_name(lock_name)
    lock.write_text("office owner", encoding="utf-8")
    for action in (service.import_user_fields, service.refresh):
        result = action()
        assert result["status"] == "pending"
        assert result["error"]["code"] == "xlsx_in_use"
        assert service.target.read_bytes() == before
    with sqlite3.connect(tmp_path / "library.sqlite") as connection:
        assert not connection.execute("SELECT user_notes FROM items").fetchone()[0]
    lock.unlink()
    assert service.refresh()["status"] == "success"
    with sqlite3.connect(tmp_path / "library.sqlite") as connection:
        assert connection.execute("SELECT user_notes FROM items").fetchone()[0] == "已保存但仍在编辑"


def _seed_ready_reader_with_assets(root: Path) -> tuple[str, str]:
    service = LibraryService(root)
    try:
        paper_id = service.ingest(
            PaperMetadata(title="图表索引论文", authors=["作者甲"], year=2026)
        )["paper_id"]
    finally:
        service.close()
    source_sha = "a" * 64
    generation = source_sha[:16]
    paper_root = root / "papers" / paper_id
    generation_root = paper_root / "generations" / generation
    (paper_root / "source.pdf").parent.mkdir(parents=True, exist_ok=True)
    (paper_root / "source.pdf").write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    figure = generation_root / "parsed" / "mineru" / "images" / "figure.jpg"
    table_image = generation_root / "parsed" / "mineru" / "tables" / "table.jpg"
    table_html = generation_root / "parsed" / "mineru" / "tables" / "table.html"
    reader = generation_root / "reading" / "reader.html"
    for path in (figure, table_image, table_html, reader):
        path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_bytes(b"figure")
    table_image.write_bytes(b"table-image")
    table_html.write_text("<table><tr><td>1</td></tr></table>", encoding="utf-8")
    reader.write_text(
        '<html><body><div id="block-figure-caption"></div>'
        '<div id="block-table-caption"></div></body></html>',
        encoding="utf-8",
    )
    (generation_root / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "asset_id": "figure-1",
                        "kind": "figure",
                        "page": 1,
                        "relative_path": "parsed/mineru/images/figure.jpg",
                        "caption": "Figure 1. Source caption.",
                    },
                    {
                        "asset_id": "table-1",
                        "kind": "table",
                        "page": 2,
                        "relative_path": "parsed/mineru/tables/table.jpg",
                        "caption": "Table 1. Source caption.",
                    },
                    {
                        "asset_id": "table-1-html",
                        "kind": "table",
                        "page": 2,
                        "relative_path": "parsed/mineru/tables/table.html",
                        "caption": "Table 1. Source caption.",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (generation_root / "reading" / "reader-manifest.json").write_text(
        json.dumps(
            {
                "assets": [
                    {"id": "figure-1", "caption_block_id": "figure-caption"},
                    {"id": "table-1", "caption_block_id": "table-caption"},
                    {"id": "table-1-html", "caption_block_id": "table-caption"},
                ]
            }
        ),
        encoding="utf-8",
    )
    translations = generation_root / "reading" / "full" / "translations.json"
    translations.parent.mkdir(parents=True, exist_ok=True)
    translations.write_text(
        json.dumps(
            {
                "translations": [
                    {"block_id": "figure-caption", "translation_zh": "图 1：中文图注。"},
                    {"block_id": "table-caption", "translation_zh": "表 1：中文图注。"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with sqlite3.connect(root / "library.sqlite") as conn:
        conn.execute(
            "INSERT INTO attachments(paper_id,rel_path,sha256,size,validated_at) "
            "VALUES(?, 'source.pdf', ?, 24, '2026-09-05T00:00:00+00:00')",
            (paper_id, source_sha),
        )
        conn.execute(
            "INSERT INTO artifacts(paper_id,kind,rel_path,status,updated_at) "
            "VALUES(?, 'reader', ?, 'ready', '2026-09-05T00:00:00+00:00')",
            (paper_id, f"generations/{generation}/reading/reader.html"),
        )
    return paper_id, generation


def test_snapshot_links_pdf_reader_and_indexes_each_parsed_asset(tmp_path):
    paper_id, generation = _seed_ready_reader_with_assets(tmp_path)

    result = XlsxSnapshotService(tmp_path).refresh()

    assert result["status"] == "success"
    workbook = openpyxl.load_workbook(tmp_path / "library" / "scientific-reading.xlsx")
    assert workbook.sheetnames == ["文献", "阅读成果", "图表索引", "说明", "_同步"]
    papers = workbook["文献"]
    paper_headers = {cell.value: cell.column for cell in papers[1]}
    assert papers.cell(2, paper_headers["PDF"]).hyperlink.target == (
        f"../papers/{paper_id}/source.pdf"
    )
    assert papers.cell(2, paper_headers["Reader"]).hyperlink.target == (
        f"../papers/{paper_id}/generations/{generation}/reading/reader.html"
    )
    assert '"查看 2 项"' in papers.cell(2, paper_headers["图表索引"]).value
    assert "MATCH(" in papers.cell(2, paper_headers["图表索引"]).value
    assets = workbook["图表索引"]
    headers = {cell.value: cell.column for cell in assets[1]}
    assert assets.max_row == 3
    assert assets.cell(2, headers["资产 ID"]).value == "figure-1"
    assert assets.cell(2, headers["PDF 页码"]).value == 1
    assert assets.cell(2, headers["图注"]).value == "图 1：中文图注。"
    assert assets.cell(2, headers["原图"]).hyperlink.target.endswith("images/figure.jpg")
    assert assets.cell(2, headers["结构表格"]).value in (None, "", "未就绪")
    assert assets.cell(3, headers["资产 ID"]).value == "table-1"
    assert assets.cell(3, headers["PDF 页码"]).value == 2
    assert assets.cell(3, headers["原图"]).hyperlink.target.endswith("tables/table.jpg")
    assert assets.cell(3, headers["结构表格"]).hyperlink.target.endswith("tables/table.html")
    assert assets.cell(3, headers["结构表格"]).hyperlink.target.endswith(
        "tables/table.html"
    )
    assert assets.cell(3, headers["打开原文"]).hyperlink.target.endswith(
        "reader.html#block-table-caption"
    )
    workbook.close()


def test_asset_index_uses_active_source_generation_before_reader_is_ready(tmp_path):
    paper_id, _generation = _seed_ready_reader_with_assets(tmp_path)
    old_reader = (
        tmp_path / "papers" / paper_id / "generations" / ("b" * 16)
        / "reading" / "reader.html"
    )
    old_reader.parent.mkdir(parents=True, exist_ok=True)
    old_reader.write_text("<html>旧来源精读</html>", encoding="utf-8")
    with sqlite3.connect(tmp_path / "library.sqlite") as conn:
        conn.execute(
            "UPDATE artifacts SET rel_path=?, status='ready' "
            "WHERE paper_id=? AND kind='reader'",
            (f"generations/{'b' * 16}/reading/reader.html", paper_id),
        )

    assert XlsxSnapshotService(tmp_path).refresh()["status"] == "success"

    workbook = openpyxl.load_workbook(tmp_path / "library" / "scientific-reading.xlsx")
    assets = workbook["图表索引"]
    headers = {cell.value: cell.column for cell in assets[1]}
    assert [assets.cell(row, headers["资产 ID"]).value for row in (2, 3)] == [
        "figure-1", "table-1"
    ]
    assert all(
        assets.cell(row, headers["打开原文"]).value == "未就绪" for row in (2, 3)
    )
    workbook.close()


def test_snapshot_has_fixed_columns_all_rows_and_readme_sheet(tmp_path):
    _seed(tmp_path, 3)
    result = XlsxSnapshotService(tmp_path).refresh()
    assert result["status"] == "success"
    workbook = openpyxl.load_workbook(tmp_path / "library" / "scientific-reading.xlsx")
    assert workbook.sheetnames == ["文献", "阅读成果", "图表索引", "说明", "_同步"]
    sheet = workbook["文献"]
    assert tuple(cell.value for cell in next(sheet.iter_rows())) == XLSX_COLUMNS
    rows = list(sheet.iter_rows(values_only=True))
    assert len(rows) == 4
    assert rows[1][0] == "中文文献 0"
    assert sheet.freeze_panes == "B2"
    assert sheet.tables["Literature"].ref == f"A1:{sheet.cell(1, len(XLSX_COLUMNS)).column_letter}{sheet.max_row}"
    assert sheet.auto_filter.ref is None
    assert sheet.column_dimensions["A"].width >= 30
    assert sheet["A1"].fill.fill_type == "solid"
    assert sheet["A2"].alignment.wrap_text is True
    workbook.close()


def test_snapshot_lists_every_confirmed_review_conclusion_with_parent_scope(tmp_path):
    service = LibraryService(tmp_path)
    try:
        paper_id = service.ingest(
            PaperMetadata(title="代谢论文", authors=["作者甲"])
        )["paper_id"]
    finally:
        service.close()
    review = ReviewService(tmp_path)
    try:
        review.bind_session("metabolism-parent", paper_id, "review-child")
        review.confirm_conclusions(
            "review-child",
            [
                {
                    "conclusion_type": "机制",
                    "conclusion_text": "结论一",
                    "evidence_locator": "Figure 2",
                },
                {
                    "conclusion_type": "局限",
                    "conclusion_text": "结论二",
                    "evidence_locator": "Discussion",
                },
            ],
        )
    finally:
        review.close()

    assert XlsxSnapshotService(tmp_path).refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(
        tmp_path / "library" / "scientific-reading.xlsx"
    )
    sheet = workbook["阅读成果"]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == REVIEW_COLUMNS
    assert len(rows) == 3
    assert rows[1][1:6] == ("机制", "结论一", "历史记录", "历史确认 · 证据未核对", "Figure 2")
    assert rows[2][1:3] == ("局限", "结论二")
    assert rows[1][8] == paper_id
    assert "父会话 ID" not in rows[0]
    assert sheet.freeze_panes == "B2"
    assert sheet.protection.sheet is False
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
    assert result["updated"] == 0
    assert result["conflicts"] == 1
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM items WHERE paper_id=?", (first_id,)).fetchone()
    assert row["title"] == original_title
    assert not row["personal_thoughts"]
    assert not row["understanding_level"]
    assert not row["user_notes"]
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
    assert meta.get("xlsx_error") in (None, "", "未就绪")


def test_refresh_preserves_conflicting_notes_until_identity_is_repaired(tmp_path):
    _seed(tmp_path, 2)
    service = XlsxSnapshotService(tmp_path)
    assert service.refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    paper_id = sheet.cell(3, headers["文献 ID"]).value
    sheet.cell(2, headers["用户笔记"], "正常行的笔记")
    sheet.cell(3, headers["文献 ID"], "changed_identity")
    sheet.cell(3, headers["用户笔记"], "身份待修复，但笔记必须保留")
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_identity_conflict"
    assert result["updated"] == 0
    assert result["conflicts"] == 1
    assert service.target.read_bytes() == original
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    notes = dict(conn.execute("SELECT paper_id, user_notes FROM items"))
    meta = dict(conn.execute("SELECT key,value FROM library_meta"))
    conn.close()
    assert "正常行的笔记" not in notes.values()
    assert not notes[paper_id]
    assert meta["xlsx_pending"] == "1"
    assert meta["xlsx_error"] == "xlsx_identity_conflict"

    workbook = openpyxl.load_workbook(service.target)
    workbook["文献"].cell(3, headers["文献 ID"], paper_id)
    workbook.save(service.target)
    workbook.close()
    assert service.refresh()["status"] == "success"
    workbook = openpyxl.load_workbook(service.target)
    assert workbook["文献"].cell(3, headers["用户笔记"]).value == "身份待修复，但笔记必须保留"
    workbook.close()
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    assert conn.execute("SELECT user_notes FROM items WHERE paper_id=?", (paper_id,)).fetchone()[0] == "身份待修复，但笔记必须保留"
    meta = dict(conn.execute("SELECT key,value FROM library_meta"))
    conn.close()
    assert meta["xlsx_pending"] == "0"
    assert "xlsx_error" not in meta
    assert meta["xlsx_conflicts"] == "[]"


@pytest.mark.parametrize("sheet_name", ["文献", "_同步"])
def test_refresh_preserves_workbook_when_required_sheet_is_missing(tmp_path, sheet_name):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    workbook.create_sheet("个人记录").append(["不能覆盖的个人记录"])
    del workbook[sheet_name]
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_required_sheets_missing"
    assert service.target.read_bytes() == original


def test_refresh_reports_missing_user_columns_without_overwriting_workbook(tmp_path):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    column = XLSX_COLUMNS.index("用户笔记") + 1
    sheet.cell(1, column, "改过名字的笔记列")
    sheet.cell(2, column, "表头错误也不能丢失笔记")
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_user_columns_missing"
    assert service.target.read_bytes() == original


@pytest.mark.parametrize("column", [1, 2])
def test_refresh_preserves_workbook_when_identity_header_is_invalid(tmp_path, column):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    workbook["_同步"].cell(1, column, "invalid_header")
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_baseline_missing"
    assert service.target.read_bytes() == original


def test_refresh_preserves_workbook_when_last_paper_row_is_missing(tmp_path):
    _seed(tmp_path, 2)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    workbook["文献"].delete_rows(3)
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_identity_conflict"
    assert result["conflicts"] == 1
    assert service.target.read_bytes() == original


def test_refresh_preserves_handwritten_note_when_user_header_is_duplicated(tmp_path):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    note_column = XLSX_COLUMNS.index("用户笔记") + 1
    sheet.cell(2, note_column, "不能从重复表头的错误列读取")
    sheet.cell(1, sheet.max_column + 1, "用户笔记")
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_user_columns_ambiguous"
    assert service.target.read_bytes() == original


def test_refresh_does_not_misattribute_notes_when_identity_row_is_duplicated(tmp_path):
    _seed(tmp_path, 2)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    workbook = openpyxl.load_workbook(service.target)
    sheet = workbook["文献"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    first_id = sheet.cell(2, headers["文献 ID"]).value
    second_id = sheet.cell(3, headers["文献 ID"]).value
    sheet.cell(2, headers["文献 ID"], second_id)
    sheet.cell(2, headers["用户笔记"], "属于第一行的笔记")
    sheet.cell(3, headers["用户笔记"], "属于第二行的笔记")
    sheet.cell(2, headers["行标识"], sheet.cell(3, headers["行标识"]).value)
    workbook.save(service.target)
    workbook.close()
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_identity_conflict"
    assert service.target.read_bytes() == original
    conn = sqlite3.connect(tmp_path / "library.sqlite")
    notes = dict(conn.execute("SELECT paper_id, user_notes FROM items"))
    conn.close()
    assert notes[first_id] is None
    assert not notes[second_id]


def test_refresh_preserves_unreadable_workbook_and_allows_file_repair(tmp_path):
    _seed(tmp_path, 1)
    service = XlsxSnapshotService(tmp_path)
    service.refresh()
    valid = service.target.read_bytes()
    service.target.write_bytes(b"not an xlsx archive")
    original = service.target.read_bytes()

    result = service.refresh()

    assert result["status"] == "pending"
    assert result["error"]["code"] == "xlsx_read_failed"
    assert service.target.read_bytes() == original
    moved = service.target.with_suffix(".broken")
    service.target.replace(moved)
    moved.replace(service.target)
    service.target.write_bytes(valid)
    assert service.refresh()["status"] == "success"
