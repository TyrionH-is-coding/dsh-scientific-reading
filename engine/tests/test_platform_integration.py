from pathlib import Path
import os
import subprocess
import sys
import time
import pytest
from scientific_reading.secret_store import MineruSecretStore
from scientific_reading.xlsx_snapshot import XlsxSnapshotService
from scientific_reading.background_store import BackgroundJobStore


class MemoryKeyring:
    def __init__(self):
        self.items = {}

    def set_password(self, service, account, value):
        self.items[(service, account)] = value

    def get_password(self, service, account):
        return self.items.get((service, account))

    def delete_password(self, service, account):
        self.items.pop((service, account), None)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_native_keyring_is_scoped_to_instance_without_secret_file(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    backend = MemoryKeyring()
    first = MineruSecretStore(tmp_path / "first", keyring_backend=backend)
    second = MineruSecretStore(tmp_path / "second", keyring_backend=backend)
    first.save("synthetic-first")
    second.save("synthetic-second")
    assert first.load() == "synthetic-first"
    assert second.load() == "synthetic-second"
    first.delete()
    assert first.load() is None
    assert second.load() == "synthetic-second"
    assert not first.path.exists() and not second.path.exists()


def test_locked_keyring_never_falls_back_to_plaintext(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    class Locked(MemoryKeyring):
        def set_password(self, *args):
            raise RuntimeError("keyring locked")
    store = MineruSecretStore(tmp_path, keyring_backend=Locked())
    with pytest.raises(RuntimeError, match="^secure_store_unavailable$"):
        store.save("synthetic-do-not-write")
    assert not store.path.exists()


def test_unconfigured_instance_does_not_open_or_unlock_the_keyring(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    class Unavailable:
        def get_password(self, *args):
            raise AssertionError("must not touch the desktop keyring before configuration")
    store = MineruSecretStore(tmp_path, keyring_backend=Unavailable())
    assert store.load() is None
    store.delete()


@pytest.mark.parametrize("platform,command", [("darwin", "/usr/bin/open"), ("linux", "/usr/bin/xdg-open")])
def test_spreadsheet_opener_preserves_path_and_does_not_claim_row_selection(tmp_path, monkeypatch, platform, command):
    from scientific_reading import xlsx_snapshot
    book = tmp_path / "a file with spaces.xlsx"
    calls = []
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(xlsx_snapshot.shutil, "which", lambda name: command)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    assert XlsxSnapshotService._open_excel(book, 8) is False
    assert calls[0][0] == [command, str(book)]
    assert calls[0][1]["check"] is True


def test_headless_spreadsheet_open_failure_is_actionable(tmp_path, monkeypatch):
    from scientific_reading import xlsx_snapshot
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(xlsx_snapshot.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="spreadsheet_opener_unavailable"):
        XlsxSnapshotService._open_excel(tmp_path / "library.xlsx", 2)


@pytest.mark.skipif(os.name == "nt", reason="Unix zombie lifecycle")
def test_exited_unreaped_worker_does_not_block_job_retry():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and BackgroundJobStore._pid_is_alive(child.pid):
            time.sleep(0.02)
        # Do not poll/wait before checking: the child is deliberately unreaped.
        assert not BackgroundJobStore._pid_is_alive(child.pid)
    finally:
        child.wait(timeout=5)


@pytest.mark.skipif(os.environ.get("SR_NATIVE_KEYRING_TEST") != "1", reason="requires unlocked OS credential service")
def test_real_native_credential_service_roundtrip(tmp_path):
    store = MineruSecretStore(tmp_path)
    try:
        store.save("synthetic-native-credential-check")
        assert store.load() == "synthetic-native-credential-check"
    finally:
        store.delete()
    assert store.load() is None
