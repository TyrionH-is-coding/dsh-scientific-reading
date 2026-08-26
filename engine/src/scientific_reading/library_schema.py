"""SQLite 文献库 schema 初始化与可恢复迁移。"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


TARGET_VERSION = 2

_V1_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  paper_id TEXT PRIMARY KEY,
  library_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  authors_json TEXT NOT NULL,
  doi TEXT, pmid TEXT,
  year INTEGER, journal TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
  paper_id TEXT PRIMARY KEY REFERENCES items(paper_id),
  rel_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER, validated_at TEXT
);
CREATE TABLE IF NOT EXISTS tags (tag TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS item_tags (
  paper_id TEXT REFERENCES items(paper_id),
  tag TEXT REFERENCES tags(tag),
  PRIMARY KEY (paper_id, tag)
);
CREATE TABLE IF NOT EXISTS collections (
  collection_id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_items (
  collection_id TEXT REFERENCES collections(collection_id),
  paper_id TEXT REFERENCES items(paper_id),
  PRIMARY KEY (collection_id, paper_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS fulltext USING fts5(paper_id UNINDEXED, content);
CREATE TABLE IF NOT EXISTS artifacts (
  paper_id TEXT, kind TEXT,
  rel_path TEXT, status TEXT, updated_at TEXT,
  PRIMARY KEY (paper_id, kind)
);
"""

_ITEM_COLUMNS = (
    ("source_url", "TEXT"),
    ("abstract_en", "TEXT"),
    ("abstract_zh", "TEXT"),
    ("abstract_status", "TEXT"),
    ("folder_id", "TEXT REFERENCES folders(folder_id)"),
    ("full_read_status", "TEXT"),
    ("active_job_id", "TEXT"),
    ("last_error", "TEXT"),
    ("feishu_sync_state", "TEXT"),
    ("feishu_record_id", "TEXT"),
    ("feishu_record_url", "TEXT"),
    ("feishu_error", "TEXT"),
    ("xlsx_sync_state", "TEXT"),
    ("xlsx_error", "TEXT"),
)

_V1_REQUIRED_COLUMNS = {
    "items": {
        "paper_id", "library_key", "title", "authors_json", "doi", "pmid",
        "year", "journal", "status", "created_at", "updated_at",
    },
    "attachments": {"paper_id", "rel_path", "sha256", "size", "validated_at"},
    "tags": {"tag"},
    "item_tags": {"paper_id", "tag"},
    "collections": {"collection_id", "name"},
    "collection_items": {"collection_id", "paper_id"},
    "fulltext": {"paper_id", "content"},
    "artifacts": {"paper_id", "kind", "rel_path", "status", "updated_at"},
}

_V2_REQUIRED_COLUMNS = {
    **_V1_REQUIRED_COLUMNS,
    "items": _V1_REQUIRED_COLUMNS["items"] | {name for name, _ in _ITEM_COLUMNS},
    "folders": {"folder_id", "name", "created_at", "updated_at"},
    "batch_operations": {
        "operation_id", "kind", "before_json", "after_json", "created_at", "undone_at",
    },
    "library_meta": {"key", "value"},
}

_V1_REQUIRED_FOREIGN_KEYS = {
    "attachments": {("paper_id", "items", "paper_id")},
    "item_tags": {
        ("paper_id", "items", "paper_id"),
        ("tag", "tags", "tag"),
    },
    "collection_items": {
        ("collection_id", "collections", "collection_id"),
        ("paper_id", "items", "paper_id"),
    },
}

_V1_REQUIRED_PRIMARY_KEYS = {
    "items": ("paper_id",),
    "attachments": ("paper_id",),
    "tags": ("tag",),
    "item_tags": ("paper_id", "tag"),
    "collections": ("collection_id",),
    "collection_items": ("collection_id", "paper_id"),
    "artifacts": ("paper_id", "kind"),
}

_V2_REQUIRED_PRIMARY_KEYS = {
    **_V1_REQUIRED_PRIMARY_KEYS,
    "folders": ("folder_id",),
    "batch_operations": ("operation_id",),
    "library_meta": ("key",),
}

_V1_REQUIRED_UNIQUE_KEYS = {"items": "library_key"}
_V2_REQUIRED_UNIQUE_KEYS = {**_V1_REQUIRED_UNIQUE_KEYS, "folders": "name"}


@dataclass(frozen=True, slots=True)
class MigrationResult:
    from_version: int
    to_version: int
    backup_path: Path | None
    warnings: tuple[str, ...]


def _library_path(data_root: Path) -> Path:
    return data_root / "library.sqlite"


@contextmanager
def _migration_lock(data_root: Path):
    lock_path = data_root / ".library.sqlite.migrate.lock"
    deadline = time.monotonic() + 60
    handle = None
    while handle is None:
        candidate = None
        try:
            candidate = lock_path.open("a+b")
            candidate.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(candidate.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle = candidate
        except OSError:
            if candidate is not None:
                candidate.close()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"library_migration_lock_timeout:{lock_path}")
            time.sleep(0.05)
    with handle:
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _create_v2_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS folders ("
        "folder_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS batch_operations ("
        "operation_id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
        "before_json TEXT NOT NULL, after_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL, undone_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS library_meta ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _add_v2_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    for name, declaration in _ITEM_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {declaration}")


def _store_warnings(conn: sqlite3.Connection, warnings: tuple[str, ...]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO library_meta (key, value) VALUES (?, ?)",
        ("migration_warnings", json.dumps(warnings, ensure_ascii=False)),
    )


def _validate_schema(
    conn: sqlite3.Connection,
    required: dict[str, set[str]],
    label: str,
) -> None:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    missing_tables = sorted(required.keys() - tables)
    missing_columns: dict[str, list[str]] = {}
    for table in required.keys() & tables:
        actual = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = sorted(required[table] - actual)
        if missing:
            missing_columns[table] = missing
    if missing_tables or missing_columns:
        details = json.dumps(
            {"missing_tables": missing_tables, "missing_columns": missing_columns},
            ensure_ascii=False,
            sort_keys=True,
        )
        raise sqlite3.DatabaseError(f"invalid_{label}_schema:{details}")
    _validate_structural_constraints(conn, label)


def _has_single_column_unique_index(
    conn: sqlite3.Connection, table: str, column: str
) -> bool:
    for index in conn.execute(f'PRAGMA index_list("{table}")'):
        if not index[2] or index[4]:
            continue
        indexed = [
            row[2] for row in conn.execute(f'PRAGMA index_info("{index[1]}")')
        ]
        if indexed == [column]:
            return True
    return False


def _foreign_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, str, str]]:
    return {
        (row[3], row[2], row[4])
        for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')
    }


def _validate_structural_constraints(conn: sqlite3.Connection, label: str) -> None:
    problems: list[str] = []
    required_primary_keys = (
        _V2_REQUIRED_PRIMARY_KEYS if label == "v2" else _V1_REQUIRED_PRIMARY_KEYS
    )
    for table, required in required_primary_keys.items():
        actual = tuple(
            row[1]
            for row in sorted(
                conn.execute(f'PRAGMA table_info("{table}")'), key=lambda row: row[5]
            )
            if row[5]
        )
        if actual != required:
            problems.append(f"{table}.primary_key:{actual!r}")

    required_unique_keys = (
        _V2_REQUIRED_UNIQUE_KEYS if label == "v2" else _V1_REQUIRED_UNIQUE_KEYS
    )
    for table, column in required_unique_keys.items():
        if not _has_single_column_unique_index(conn, table, column):
            problems.append(f"{table}.{column}_unique")

    fulltext_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'fulltext'"
    ).fetchone()
    if (
        fulltext_sql is None
        or not re.search(r"\bCREATE\s+VIRTUAL\s+TABLE\b", fulltext_sql[0], re.IGNORECASE)
        or not re.search(r"\bUSING\s+fts5\s*\(", fulltext_sql[0], re.IGNORECASE)
    ):
        problems.append("fulltext_fts5")

    required_foreign_keys = dict(_V1_REQUIRED_FOREIGN_KEYS)
    if label == "v2":
        required_foreign_keys["items"] = {("folder_id", "folders", "folder_id")}
    for table, required in required_foreign_keys.items():
        missing = required - _foreign_keys(conn, table)
        if missing:
            problems.append(f"{table}.foreign_keys:{sorted(missing)!r}")

    if problems:
        raise sqlite3.DatabaseError(
            f"invalid_{label}_schema:" + ";".join(problems)
        )


def _validate_foreign_keys(conn: sqlite3.Connection) -> None:
    failures = conn.execute("PRAGMA foreign_key_check").fetchall()
    if failures:
        raise sqlite3.DatabaseError(f"foreign_key_check_failed:{failures!r}")


def _initialize_v2(path: Path) -> MigrationResult:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_V1_SCHEMA)
        _create_v2_tables(conn)
        _add_v2_columns(conn)
        _store_warnings(conn, ())
        _validate_schema(conn, _V2_REQUIRED_COLUMNS, "v2")
        _validate_foreign_keys(conn)
        conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
        conn.commit()
    return MigrationResult(0, TARGET_VERSION, None, ())


def _backup_v1(conn: sqlite3.Connection, data_root: Path) -> Path:
    backup_dir = data_root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    while True:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        token = uuid.uuid4().hex[:12]
        backup_path = backup_dir / f"library-{timestamp}-{token}-v1.sqlite3"
        try:
            descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        os.close(descriptor)
        break
    with closing(sqlite3.connect(backup_path)) as destination:
        conn.backup(destination)
    with closing(sqlite3.connect(backup_path)) as verification:
        result = verification.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise sqlite3.DatabaseError(f"library_backup_integrity_check_failed:{result}")
    return backup_path


def _restore_backup(backup_path: Path, library: Path) -> None:
    with closing(sqlite3.connect(backup_path)) as source:
        with closing(sqlite3.connect(library)) as destination:
            source.backup(destination)
    with closing(sqlite3.connect(library)) as verification:
        result = verification.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise sqlite3.DatabaseError(f"library_restore_integrity_check_failed:{result}")


def _legacy_warnings(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT paper_id, GROUP_CONCAT(collection_id, ',') AS collection_ids "
        "FROM (SELECT DISTINCT paper_id, collection_id FROM collection_items "
        "ORDER BY paper_id, collection_id) GROUP BY paper_id HAVING COUNT(*) > 1"
    ).fetchall()
    return tuple(
        f"paper_id={paper_id}: multiple legacy collections ({collection_ids}); folder_id left NULL"
        for paper_id, collection_ids in rows
    )


def _migrate_folders(conn: sqlite3.Connection, now: str) -> tuple[str, ...]:
    used_names: set[str] = set()
    warnings: list[str] = []
    rows = conn.execute(
        "SELECT collection_id, name FROM collections ORDER BY collection_id"
    ).fetchall()
    for collection_id, original_name in rows:
        name = original_name
        if name in used_names:
            base = f"{original_name} [{collection_id}]"
            name = base
            suffix = 2
            while name in used_names:
                name = f"{base} #{suffix}"
                suffix += 1
            warnings.append(
                f"collection_id={collection_id}: duplicate legacy folder name "
                f"{original_name!r}; renamed to {name!r}"
            )
        used_names.add(name)
        conn.execute(
            "INSERT INTO folders (folder_id, name, created_at, updated_at) VALUES (?,?,?,?)",
            (collection_id, name, now, now),
        )
    return tuple(warnings)


def _migrate_v1(conn: sqlite3.Connection) -> tuple[str, ...]:
    conn.execute("BEGIN")
    try:
        _create_v2_tables(conn)
        _add_v2_columns(conn)
        _validate_schema(conn, _V2_REQUIRED_COLUMNS, "v2")
        now = datetime.now(UTC).isoformat()
        warnings = _migrate_folders(conn, now) + _legacy_warnings(conn)
        conn.execute(
            "UPDATE items SET folder_id = ("
            "SELECT MIN(collection_id) FROM collection_items "
            "WHERE collection_items.paper_id = items.paper_id"
            ") WHERE (SELECT COUNT(DISTINCT collection_id) FROM collection_items "
            "WHERE collection_items.paper_id = items.paper_id) = 1"
        )
        _store_warnings(conn, warnings)
        _validate_schema(conn, _V2_REQUIRED_COLUMNS, "v2")
        _validate_foreign_keys(conn)
        conn.execute(f"PRAGMA user_version = {TARGET_VERSION}")
        conn.commit()
        return warnings
    except Exception:
        conn.rollback()
        raise


def _migrate_library_locked(root: Path) -> MigrationResult:
    library = _library_path(root)
    if not library.exists():
        return _initialize_v2(library)

    conn = sqlite3.connect(library)
    backup_path: Path | None = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        raw_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if raw_version == TARGET_VERSION:
            _create_v2_tables(conn)
            _add_v2_columns(conn)
            _validate_schema(conn, _V2_REQUIRED_COLUMNS, "v2")
            _validate_foreign_keys(conn)
            conn.commit()
            return MigrationResult(TARGET_VERSION, TARGET_VERSION, None, ())
        if raw_version not in (0, 1):
            raise sqlite3.DatabaseError(f"unsupported_library_schema_version:{raw_version}")
        backup_path = _backup_v1(conn, root)
        _validate_schema(conn, _V1_REQUIRED_COLUMNS, "v1")
        _validate_foreign_keys(conn)
        warnings = _migrate_v1(conn)
        return MigrationResult(1, TARGET_VERSION, backup_path, warnings)
    except Exception as original:
        if backup_path is not None:
            conn.close()
            try:
                _restore_backup(backup_path, library)
            except Exception as restore_error:
                original.add_note(f"library restore failed: {restore_error}")
        raise
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def migrate_library(data_root: Path) -> MigrationResult:
    """初始化新库，或在可验证备份保护下将既有 v1 库迁移到 v2。"""
    root = Path(data_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _migration_lock(root):
        return _migrate_library_locked(root)
