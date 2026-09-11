"""可信调用作用域；文献事实仍由当前 SQLite 判断，后台作用域随 job 持久化。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from .data_guard import _file_lock, _key, workspace_data_root

_scope = ContextVar("scientific_reading_scope", default=None)
_held = ContextVar("scientific_reading_publication_lock", default=frozenset())


class ScopeError(ValueError):
    pass


def current_scope():
    value = _scope.get()
    return dict(value) if value is not None else None


@contextmanager
def use_scope(value):
    if value is not None:
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in ("instanceId", "scopeSessionId", "scopeFolderId")
        ):
            raise ScopeError("scope_invalid")
        allowed = {"instanceId", "scopeSessionId", "scopeFolderId", "scopePaperId", "scopePaperRevision"}
        if set(value) - allowed:
            raise ScopeError("scope_invalid")
        if "scopePaperId" in value and (not isinstance(value["scopePaperId"], str) or not value["scopePaperId"]):
            raise ScopeError("scope_invalid")
        if "scopePaperRevision" in value and (type(value["scopePaperRevision"]) is not int or value["scopePaperRevision"] < 0 or "scopePaperId" not in value):
            raise ScopeError("scope_invalid")
        value = dict(value)
    token = _scope.set(value)
    try:
        yield
    finally:
        _scope.reset(token)


def environment_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        value = os.environ.get("SR_SCOPE_CONTEXT")
        with use_scope(json.loads(value) if value else None):
            return function(*args, **kwargs)
    return wrapped


def require_global(action):
    if current_scope() is not None:
        raise ScopeError("scope_global_operation_forbidden:" + action)


def install_revision_trigger(conn):
    conn.execute("""CREATE TRIGGER IF NOT EXISTS csr_scope_membership_revision
        AFTER UPDATE OF folder_id ON items WHEN OLD.folder_id IS NOT NEW.folder_id
        BEGIN
          INSERT INTO library_meta(key,value) VALUES ('csr.scope.paper.' || NEW.paper_id, '1')
          ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT);
        END""")


def require_paper(conn, paper_id):
    scope = current_scope()
    if scope is None:
        return
    row = conn.execute("SELECT folder_id FROM items WHERE paper_id=?", (paper_id,)).fetchone()
    if scope["scopeFolderId"] == "__paper__":
        binding = conn.execute("SELECT paper_id FROM paper_chats WHERE session_id=?", (scope["scopeSessionId"],)).fetchone()
        if row is None or not binding or binding[0] != paper_id or scope.get("scopePaperId") != paper_id:
            raise ScopeError("scope_paper_forbidden")
        archived = conn.execute("SELECT value FROM library_meta WHERE key=?", ("csr.scope.archived." + str(row[0]),)).fetchone()
        if archived and archived[0] == "1":
            raise ScopeError("scope_changed")
        return
    archived = conn.execute("SELECT value FROM library_meta WHERE key=?", ("csr.scope.archived." + scope["scopeFolderId"],)).fetchone()
    if row is None or row[0] != scope["scopeFolderId"] or (archived and archived[0] == "1"):
        raise ScopeError("scope_changed")
    if scope.get("scopePaperId") not in (None, paper_id):
        raise ScopeError("scope_paper_forbidden")
    if "scopePaperRevision" in scope:
        revision = conn.execute("SELECT value FROM library_meta WHERE key=?", ("csr.scope.paper." + paper_id,)).fetchone()
        if int(revision[0] if revision else 0) != scope["scopePaperRevision"]:
            raise ScopeError("scope_changed")


def capture_scope(data_root, paper_id):
    value = current_scope()
    if value is None:
        return None
    with sqlite3.connect(Path(data_root) / "library.sqlite") as conn:
        require_paper(conn, paper_id)
        if value["scopeFolderId"] == "__paper__":
            return value
        revision = conn.execute("SELECT value FROM library_meta WHERE key=?", ("csr.scope.paper." + paper_id,)).fetchone()
    return {**value, "scopePaperId": paper_id, "scopePaperRevision": int(revision[0] if revision else 0)}


@contextmanager
def publication_lock(data_root):
    """短时提交锁；移动、撤销与文件发布共用，解析期间不持有。"""
    key = _key(Path(data_root))
    if key in _held.get():
        yield
        return
    with _file_lock(key, "scope-publication", exclusive=True, deadline=time.monotonic() + 30):
        token = _held.set(_held.get() | {key})
        try:
            yield
        finally:
            _held.reset(token)


@contextmanager
def publication_guard(data_root, paper_id):
    with publication_lock(data_root):
        if current_scope() is not None:
            with sqlite3.connect(Path(data_root) / "library.sqlite") as conn:
                require_paper(conn, paper_id)
        yield


@contextmanager
def workspace_publication(workspace):
    root = workspace_data_root(workspace)
    relative = Path(workspace.root).resolve().relative_to(root).parts
    paper_id = relative[1] if len(relative) > 1 and relative[0] == "papers" else Path(workspace.root).name
    with publication_guard(root, paper_id):
        yield


def paper_write(function):
    @wraps(function)
    def wrapped(self, paper_id, *args, **kwargs):
        with publication_guard(self.data_root, paper_id):
            return function(self, paper_id, *args, **kwargs)
    return wrapped


def library_write(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with publication_lock(self.data_root):
            return function(self, *args, **kwargs)
    return wrapped


def workspace_write(function):
    @wraps(function)
    def wrapped(self, workspace, *args, **kwargs):
        with workspace_publication(workspace):
            return function(self, workspace, *args, **kwargs)
    return wrapped


def classification_write(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        require_global("classification")
        root = getattr(self, "data_root", None) or self.library.data_root
        with publication_lock(root):
            return function(self, *args, **kwargs)
    return wrapped
