import json
from pathlib import Path

import pytest

from scientific_reading.workspace import atomic_write_json, read_json_file


def test_windows_reader_contention_retries_atomic_replacement(tmp_path, monkeypatch):
    original = Path.replace
    calls = []

    def busy_once(source, target):
        calls.append(target)
        if len(calls) == 1:
            error = PermissionError("sharing violation")
            error.winerror = 32
            raise error
        return original(source, target)

    monkeypatch.setattr(Path, "replace", busy_once)
    atomic_write_json(tmp_path / "state.json", {"state": "ready"})
    assert json.loads((tmp_path / "state.json").read_text()) == {"state": "ready"}
    assert len(calls) == 2


def test_permanent_permission_error_is_not_hidden(tmp_path, monkeypatch):
    def denied(*_args):
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        atomic_write_json(tmp_path / "state.json", {})


def test_status_reader_retries_pending_windows_replacement(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"state":"completed"}')
    original = Path.read_text
    calls = []

    def busy_once(source, *args, **kwargs):
        calls.append(source)
        if len(calls) == 1:
            error = PermissionError("pending replacement")
            error.winerror = 5
            raise error
        return original(source, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", busy_once)
    assert read_json_file(path) == {"state": "completed"}
    assert len(calls) == 2
