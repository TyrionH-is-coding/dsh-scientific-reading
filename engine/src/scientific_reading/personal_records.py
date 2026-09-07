"""Excel 和对话共用的固定个人字段；调用方负责事务与文献作用域。"""

from datetime import UTC, datetime
import sqlite3


USER_FIELDS = {
    "阅读进度": "reading_state", "与课题的关系": "project_relevance", "下一步": "next_action",
    "个人理解程度": "understanding_level", "个人思考": "personal_thoughts", "用户笔记": "user_notes",
}
READING_STATES = ("未读", "在读", "已读", "待复读")


def normalize(field, value):
    return (value or "未读") if field == "reading_state" else (value or "")


def update_personal(conn: sqlite3.Connection, paper_id: str, fields: dict, *, expected=None):
    if not isinstance(fields, dict) or not fields or not set(fields) <= set(USER_FIELDS.values()):
        raise ValueError("personal_fields_invalid")
    if any(not isinstance(value, str) or len(value) > 32767 for value in fields.values()):
        raise ValueError("personal_value_invalid")
    if "reading_state" in fields and fields["reading_state"] not in READING_STATES:
        raise ValueError("reading_state_invalid")
    names = tuple(USER_FIELDS.values())
    row = conn.execute(f"SELECT {','.join(names)}, personal_updated_at FROM items WHERE paper_id=?", (paper_id,)).fetchone()
    if row is None:
        raise ValueError("paper_not_found")
    current = {name: normalize(name, value) for name, value in zip(names, row)}
    if expected is not None:
        if not isinstance(expected, dict) or set(expected) != set(fields):
            raise ValueError("personal_expected_invalid")
        if any(current[name] != value for name, value in expected.items()):
            raise ValueError("personal_record_conflict")
    changes = {name: value for name, value in fields.items() if current[name] != value}
    stamp = row[-1]
    if changes:
        stamp = datetime.now(UTC).isoformat()
        conn.execute(
            "UPDATE items SET " + ','.join(f"{name}=?" for name in changes)
            + ",personal_updated_at=?,xlsx_sync_state='pending' WHERE paper_id=?",
            (*changes.values(), stamp, paper_id),
        )
    return {"paper_id": paper_id, "fields": {**current, **changes}, "personal_updated_at": stamp, "changed": bool(changes)}
