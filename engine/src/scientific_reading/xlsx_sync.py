"""带导出基线的逐字段回写；冲突时整批保留，旧工作簿保守迁移。"""

import hashlib
import json
import shutil
import sqlite3
from .library_service import _now

from openpyxl import load_workbook

from .personal_records import USER_FIELDS, normalize, update_personal


def archive_workbook(service):
    if not service.target.is_file():
        return None
    digest = hashlib.sha256(service.target.read_bytes()).hexdigest()
    path = service.data_root / "backups" / "xlsx" / f"{digest}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        shutil.copy2(service.target, path)
    return str(path)


def import_fields(service):
    if service._workbook_in_use():
        return service._pending_import("xlsx_in_use", "请保存并关闭表格软件后重试。")
    if not service.target.is_file():
        return {"status": "success", "updated": 0, "conflicts": 0}
    try:
        book = load_workbook(service.target)
    except PermissionError as error:
        return service._pending_import("xlsx_read_permission_denied", str(error))
    except Exception as error:
        return service._pending_import("xlsx_read_failed", str(error))
    try:
        modern = "_同步" in book.sheetnames
        if "文献" not in book.sheetnames or not modern and "_身份" not in book.sheetnames:
            return service._pending_import("xlsx_required_sheets_missing", "请恢复文献表及隐藏的同步/身份表。")
        sheet = book["文献"]
        names = [cell.value for cell in sheet[1]]
        fields = USER_FIELDS if modern else {name: USER_FIELDS[name] for name in ("个人思考", "个人理解程度", "用户笔记")}
        headers = {value: index + 1 for index, value in enumerate(names)}
        required = {"文献 ID", *fields} | ({"行标识"} if modern else set())
        display_required = required
        conflicts = []
        with sqlite3.connect(service.data_root / "library.sqlite") as conn:
            conn.row_factory = sqlite3.Row
            baseline = {}
            legacy_ids = {}
            if modern:
                meta = dict(book["_同步"].iter_rows(values_only=True))
                export = conn.execute("SELECT baseline_json FROM xlsx_exports WHERE export_id=?", (meta.get("export_id"),)).fetchone()
                if meta.get("contract") not in {"xlsx-library-v2", "xlsx-library-v3"} or export is None:
                    return service._pending_import("xlsx_baseline_missing", "此表的导出基线不在当前库；请恢复完整备份，不能直接覆盖笔记。")
                baseline = json.loads(export[0])
                if meta["contract"] == "xlsx-library-v3":
                    columns = baseline["columns"]
                    if json.loads(meta.get("columns_json", "null")) != columns or baseline.get("scope_folder_id", "") != (getattr(service, "folder_id", None) or ""):
                        return service._pending_import("xlsx_column_identity_changed", "列身份或分类范围与导出基线不一致；已保留原表。")
                    fields = {column["key"]: column["field_id"] for column in columns if column["editable"]}
                    required = {"文献 ID", "行标识", *fields}
                    display_required = {column["label"] for column in columns if column["key"] in required}
                    headers = {column["key"]: names.index(column["label"]) + 1 for column in columns if column["label"] in names}
                    baseline = baseline["rows"]
            else:
                identity = book["_身份"]
                if tuple(cell.value for cell in identity[1][:2]) != ("row", "paper_id"):
                    return service._pending_import("xlsx_identity_columns_invalid", "请恢复身份表的 row 与 paper_id 列名。")
                for row, paper_id, *_ in identity.iter_rows(min_row=2, values_only=True):
                    if not isinstance(row, int) or not isinstance(paper_id, str) or row in legacy_ids:
                        conflicts.append({"row": row, "code": "identity_ambiguous"})
                    else:
                        legacy_ids[row] = paper_id
            if not display_required.issubset(names):
                return service._pending_import("xlsx_user_columns_missing", "个人字段或身份列缺失/改名；请在工作台设置列名，已保留原工作簿。")
            if any(names.count(name) != 1 for name in display_required):
                return service._pending_import("xlsx_user_columns_ambiguous", "个人字段或身份列重复；已保留原工作簿。")
            conn.execute("BEGIN IMMEDIATE")
            seen_keys, seen_ids, updates, custom_updates = set(), set(), [], []
            for number in range(2, sheet.max_row + 1):
                paper_id = sheet.cell(number, headers["文献 ID"]).value
                key = sheet.cell(number, headers["行标识"]).value if modern else number
                expected_id = baseline.get(key, {}).get("paper_id") if modern else legacy_ids.get(number)
                if not paper_id or expected_id != paper_id:
                    conflicts.append({"row": number, "code": "identity_changed"})
                    continue
                if key in seen_keys or paper_id in seen_ids:
                    conflicts.append({"row": number, "code": "identity_duplicate"})
                    continue
                seen_keys.add(key)
                seen_ids.add(paper_id)
                current = conn.execute("SELECT * FROM items WHERE paper_id=?", (paper_id,)).fetchone()
                if current is None:
                    conflicts.append({"paper_id": paper_id, "code": "identity_unknown"})
                    continue
                changed = {}
                for label, field in fields.items():
                    cell = sheet.cell(number, headers[label])
                    excel = "" if cell.value is None else str(cell.value)
                    custom = field.startswith("custom_")
                    custom_row = conn.execute("SELECT value,revision FROM research_values WHERE paper_id=? AND field_id=?", (paper_id, field)).fetchone() if custom else None
                    database = (custom_row[0] if custom_row else "") if custom else normalize(field, current[field])
                    base = baseline[key]["custom"][field]["value"] if custom else baseline[key]["fields"][field] if modern else database
                    if cell.data_type == "f":
                        conflicts.append({"paper_id": paper_id, "field": field, "code": "personal_formula_not_supported"})
                        continue
                    if modern and (excel == base or excel == database):
                        continue
                    if not modern and excel == database:
                        continue
                    stale_custom = custom and (custom_row[1] if custom_row else 0) != baseline[key]["custom"][field]["revision"]
                    if stale_custom or (modern and database != base) or (not modern and database):
                        conflicts.append({"paper_id": paper_id, "field": field, "code": "field_conflict",
                                          "baseline": base if modern else None, "excel": excel, "database": database})
                    else:
                        if custom:
                            custom_updates.append((paper_id, field, excel, (custom_row[1] if custom_row else 0) + 1))
                        else:
                            changed[field] = excel
                if changed:
                    updates.append((paper_id, changed))
            expected_keys = set(baseline) if modern else set(legacy_ids)
            for missing in expected_keys - seen_keys:
                # 已报告的改错身份行，不重复计数。
                if not any(c.get("code") == "identity_changed" for c in conflicts):
                    conflicts.append({"key": missing, "code": "identity_missing"})
            if not conflicts:
                try:
                    for paper_id, changes in updates:
                        update_personal(conn, paper_id, changes)
                    for paper_id, field, value, revision in custom_updates:
                        if len(value) > 32767:
                            raise ValueError("research_value_invalid")
                        conn.execute("INSERT INTO research_values VALUES(?,?,?,'manual','[]',?,?) ON CONFLICT(paper_id,field_id) DO UPDATE SET value=excluded.value,origin='manual',evidence_json='[]',revision=excluded.revision,updated_at=excluded.updated_at",
                                     (paper_id, field, value, revision, _now()))
                        conn.execute("UPDATE items SET xlsx_sync_state='pending' WHERE paper_id=?", (paper_id,))
                except ValueError as error:
                    conn.rollback()
                    conflicts.append({"code": str(error)})
            if conflicts:
                conn.rollback()
            conn.execute("INSERT OR REPLACE INTO library_meta VALUES('xlsx_conflicts',?)", (json.dumps(conflicts, ensure_ascii=False),))
        if conflicts:
            code = "xlsx_field_conflict" if any(c["code"] == "field_conflict" for c in conflicts) else "xlsx_identity_conflict"
            return {**service._pending_import(code, "未回写或覆盖原表；请核对冲突中的论文和字段后重试。"),
                    "updated": 0, "conflicts": len(conflicts), "details": conflicts}
        return {"status": "success", "updated": len({paper for paper, _ in updates} | {paper for paper, *_ in custom_updates}), "conflicts": 0, "legacy_migrated": not modern}
    finally:
        book.close()
