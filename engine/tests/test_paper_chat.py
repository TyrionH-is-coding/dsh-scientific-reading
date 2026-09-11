import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from scientific_reading.library_schema import migrate_library
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.paper_chat import PaperChatService, execute
from scientific_reading.scope import capture_scope, use_scope


def fixture(root):
    library = LibraryService(root)
    a = library.ingest(PaperMetadata(title="原始论文", doi="10.5555/chat-a"))["paper_id"]
    b = library.ingest(PaperMetadata(title="第二篇论文", doi="10.5555/chat-b"))["paper_id"]
    return library, PaperChatService(library), a, b


def test_chat_survives_deduplication_move_title_and_restart(tmp_path):
    library, chats, a, b = fixture(tmp_path)
    first = chats.ensure(a)
    assert first["session_id"] != chats.ensure(b)["session_id"]
    result = library.ingest(PaperMetadata(title="更新的标题", doi="https://doi.org/10.5555/CHAT-A"))
    assert result["paper_id"] == a
    folder = library.create_folder("移动后的分类")["folder_id"]
    library.move_items([a], folder)
    library.close()
    reopened = LibraryService(tmp_path)
    try:
        later = PaperChatService(reopened).ensure(a)
        assert later["session_id"] == first["session_id"]
        assert later["created"] is False
        assert later["paper"]["folder_id"] == folder
    finally:
        reopened.close()


def test_concurrent_binds_reserve_only_one_native_identity(tmp_path):
    library, _, a, _ = fixture(tmp_path)
    library.close()

    def bind(_):
        library = LibraryService(tmp_path)
        try:
            return PaperChatService(library).ensure(a)
        finally:
            library.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(bind, range(8)))
    assert len({r["session_id"] for r in rows}) == 1
    assert sum(r["created"] for r in rows) == 1


def test_child_context_uses_trusted_parent_scope(tmp_path):
    library, chats, a, b = fixture(tmp_path)
    parent, foreign = chats.ensure(a), chats.ensure(b)
    scope = {"instanceId": "fixture", "scopeSessionId": parent["session_id"], "scopeFolderId": "__paper__", "scopePaperId": a}
    with use_scope(scope):
        for session_id in ("session-native-child", foreign["session_id"]):
            assert execute(library, {"action": "context_for_session", "session_id": session_id})["paper_id"] == a
    with use_scope({**scope, "scopePaperId": b}):
        with pytest.raises(ValueError, match="scope"):
            execute(library, {"action": "context_for_session", "session_id": "session-native-child"})
    library.close()


def test_paper_scope_lists_only_its_paper_and_survives_move(tmp_path):
    library, chats, a, b = fixture(tmp_path)
    binding = chats.ensure(a)
    scope = {"instanceId": "fixture", "scopeSessionId": binding["session_id"], "scopeFolderId": "__paper__", "scopePaperId": a}
    with use_scope(scope):
        assert [r["paper_id"] for r in library.list_items(page=1)["items"]] == [a]
        assert capture_scope(tmp_path, a) == scope
        with pytest.raises(ValueError, match="scope"):
            chats.get(b)
        with pytest.raises(ValueError, match="scope"):
            chats.ensure(a)
        with pytest.raises(ValueError, match="scope"):
            library.update_personal_record(b, {"user_notes": "不能串篇"})
    folder = library.create_folder("新分类")["folder_id"]
    library.move_items([a], folder)
    with use_scope(scope):
        assert capture_scope(tmp_path, a) == scope
        assert chats.get(a)["paper"]["folder_id"] == folder
    with use_scope({**scope, "scopePaperId": b}):
        with pytest.raises(ValueError, match="scope"):
            chats.get(b)
    library.close()


def test_v5_migration_backs_up_notes_and_leaves_mixed_history_unassigned(tmp_path):
    library, _, a, _ = fixture(tmp_path)
    library.update_personal_record(a, {"user_notes": "我的旧笔记"})
    library.conn.execute("INSERT INTO review_sessions VALUES (?,?,?,?,?)", ("category-old", a, "review-old", "now", "now"))
    library.conn.execute("DROP TABLE paper_chats")
    library.conn.execute("DROP TABLE legacy_chats")
    for table in ("research_values", "research_fields", "display_defaults", "display_schemes", "radar_discoveries", "radar_direction_candidates", "radar_scans", "radar_candidates", "radar_directions"):
        library.conn.execute("DROP TABLE " + table)
    library.conn.execute("PRAGMA user_version = 5")
    library.conn.commit()
    library.close()
    migration = migrate_library(tmp_path)
    assert (migration.from_version, migration.to_version) == (5, 6)
    with sqlite3.connect(migration.backup_path) as backup:
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 5
        assert backup.execute("SELECT user_notes FROM items WHERE paper_id=?", (a,)).fetchone()[0] == "我的旧笔记"
    library = LibraryService(tmp_path)
    chats = PaperChatService(library)
    assert chats.get(a)["status"] == "missing"
    assert chats.ensure(a)["session_id"] not in {"category-old", "review-old"}
    chats.register_legacy([{"session_id": "category-old", "folder_id": "old", "label": "旧混合讨论"}])
    chats.register_legacy([{"session_id": "category-old"}])
    assert len(chats.legacy()["sessions"]) == 1
    assert chats.get(a)["legacy_review_sessions"][0]["review_session_id"] == "review-old"
    assert chats.get(a)["paper"]["user_notes"] == "我的旧笔记"
    library.close()
    assert migrate_library(tmp_path).backup_path is None


def test_invalid_v6_does_not_silently_regenerate_bindings(tmp_path):
    library, chats, a, _ = fixture(tmp_path)
    chats.ensure(a)
    library.conn.execute("DROP TABLE paper_chats")
    library.conn.commit()
    library.close()
    with pytest.raises(ValueError, match="invalid_v6_schema"):
        migrate_library(tmp_path)


def test_chat_cli_roundtrip_and_scope_denial(tmp_path, monkeypatch, capsys):
    import io
    from scientific_reading.__main__ import run_cli
    library, _, a, b = fixture(tmp_path)
    library.close()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"action": "ensure", "paper_id": a})))
    assert run_cli(["--data-root", str(tmp_path), "paper-chat"]) == 0
    result = json.loads(capsys.readouterr().out)
    with use_scope({"instanceId": "fixture", "scopeSessionId": result["session_id"], "scopeFolderId": "__paper__", "scopePaperId": a}):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"action": "get", "paper_id": b})))
        assert run_cli(["--data-root", str(tmp_path), "paper-chat"]) == 4
    assert "scope_paper_forbidden" in capsys.readouterr().out
