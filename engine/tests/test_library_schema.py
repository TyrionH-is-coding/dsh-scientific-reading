from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scientific_reading import library_schema
from scientific_reading.library_schema import migrate_library


def _create_v2_library(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    database = root / "library.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(library_schema._V1_SCHEMA)
        library_schema._create_v2_tables(connection)
        library_schema._add_v2_columns(connection)
        connection.execute(
            "INSERT INTO items (paper_id, library_key, title, authors_json, status, "
            "created_at, updated_at, personal_thoughts) VALUES (?,?,?,?,?,?,?,?)",
            (
                "library_alpha",
                "doi:10.1000/alpha",
                "Alpha paper",
                "[]",
                "ready",
                "2026-08-30T00:00:00+00:00",
                "2026-08-30T00:00:00+00:00",
                "保留我的原始思考",
            ),
        )
        connection.execute("PRAGMA user_version = 2")
    return database


def _create_v3_library(root: Path) -> Path:
    database = _create_v2_library(root)
    with sqlite3.connect(database) as connection:
        library_schema._create_v3_tables(connection)
        connection.execute(
            "INSERT INTO review_sessions "
            "(parent_session_id, paper_id, review_session_id, created_at, updated_at) "
            "VALUES ('parent-a', 'library_alpha', 'child-a', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO review_conclusions "
            "(conclusion_id, parent_session_id, paper_id, review_session_id, "
            "conclusion_type, conclusion_text, evidence_locator, confirmed_at, "
            "created_at, updated_at) VALUES "
            "('review-old', 'parent-a', 'library_alpha', 'child-a', "
            "'发现', '旧结论', 'Figure 2', 'now', 'now', 'now')"
        )
        connection.execute("PRAGMA user_version = 3")
    return database


def test_new_library_initializes_review_schema_v4(tmp_path: Path) -> None:
    result = migrate_library(tmp_path)

    assert result.from_version == 0
    assert result.to_version == 6
    with sqlite3.connect(tmp_path / "library.sqlite") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"review_sessions", "review_conclusions"} <= tables
        session_pk = tuple(
            row[1]
            for row in sorted(
                connection.execute("PRAGMA table_info(review_sessions)"),
                key=lambda row: row[5],
            )
            if row[5]
        )
        assert session_pk == ("parent_session_id", "paper_id")
        conclusion_columns = {
            row[1]: (row[2], row[3], row[4])
            for row in connection.execute(
                "PRAGMA table_info(review_conclusions)"
            )
        }
        assert conclusion_columns["evidence_json"] == ("TEXT", 0, None)
        assert conclusion_columns["basis"] == ("TEXT", 1, "'legacy'")


def test_v2_migration_backs_up_and_preserves_existing_items(tmp_path: Path) -> None:
    _create_v2_library(tmp_path)

    result = migrate_library(tmp_path)

    assert result.from_version == 2
    assert result.to_version == 6
    assert result.backup_path is not None
    assert result.backup_path.is_file()
    assert result.backup_path.name.endswith("-v2.sqlite3")
    with sqlite3.connect(tmp_path / "library.sqlite") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute(
            "SELECT title, personal_thoughts FROM items WHERE paper_id='library_alpha'"
        ).fetchone() == ("Alpha paper", "保留我的原始思考")


def test_v3_migration_preserves_legacy_evidence_locator(tmp_path: Path) -> None:
    database = _create_v3_library(tmp_path)

    result = migrate_library(tmp_path)

    assert result.from_version == 3
    assert result.to_version == 6
    assert result.backup_path is not None
    assert result.backup_path.name.endswith("-v3.sqlite3")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT evidence_locator, evidence_json, basis "
            "FROM review_conclusions WHERE conclusion_id='review-old'"
        ).fetchone() == ("Figure 2", None, "legacy")


def test_v3_migration_restores_backup_when_v4_step_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _create_v3_library(tmp_path)

    def fail_after_write(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN")
        library_schema._add_v4_columns(connection)
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
        raise RuntimeError("injected_v4_failure")

    monkeypatch.setattr(library_schema, "_migrate_v3", fail_after_write)

    with pytest.raises(RuntimeError, match="injected_v4_failure"):
        migrate_library(tmp_path)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(review_conclusions)"
            )
        }
        assert "evidence_json" not in columns
        assert "basis" not in columns
        assert connection.execute(
            "SELECT evidence_locator FROM review_conclusions "
            "WHERE conclusion_id='review-old'"
        ).fetchone()[0] == "Figure 2"


def test_review_schema_enforces_binding_identity_and_foreign_keys(tmp_path: Path) -> None:
    migrate_library(tmp_path)
    with sqlite3.connect(tmp_path / "library.sqlite") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO review_sessions "
                "(parent_session_id, paper_id, review_session_id, created_at, updated_at) "
                "VALUES ('parent-a', 'missing-paper', 'child-a', 'now', 'now')"
            )
        connection.execute(
            "INSERT INTO items (paper_id, library_key, title, authors_json, status, created_at, updated_at) "
            "VALUES ('library_alpha', 'key-alpha', 'Alpha', '[]', 'ready', 'now', 'now')"
        )
        connection.execute(
            "INSERT INTO review_sessions "
            "(parent_session_id, paper_id, review_session_id, created_at, updated_at) "
            "VALUES ('parent-a', 'library_alpha', 'child-a', 'now', 'now')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO review_sessions "
                "(parent_session_id, paper_id, review_session_id, created_at, updated_at) "
                "VALUES ('parent-b', 'library_alpha', 'child-a', 'now', 'now')"
            )
