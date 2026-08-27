from __future__ import annotations

from pathlib import Path
import os

from scientific_reading.secret_store import MineruSecretStore, resolve_mineru_token


class FakeProtector:
    def protect(self, value: bytes) -> bytes:
        return b"protected:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"protected:")
        return value.removeprefix(b"protected:")[::-1]


def test_secret_is_encrypted_loaded_and_deleted(tmp_path: Path) -> None:
    store = MineruSecretStore(tmp_path, protector=FakeProtector())
    store.save("fictional-key")
    assert b"fictional-key" not in store.path.read_bytes()
    assert store.load() == "fictional-key"
    store.delete()
    assert store.load() is None


def test_secure_store_precedes_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_API_TOKEN", "environment-key")
    store = MineruSecretStore(tmp_path, protector=FakeProtector())
    store.save("stored-key")
    assert resolve_mineru_token(tmp_path, store=store) == ("stored-key", "secure_store")


def test_environment_is_fallback_without_secure_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_API_TOKEN", "environment-key")
    store = MineruSecretStore(tmp_path, protector=FakeProtector())
    assert resolve_mineru_token(tmp_path, store=store) == ("environment-key", "environment")


def test_empty_secret_is_rejected(tmp_path: Path) -> None:
    store = MineruSecretStore(tmp_path, protector=FakeProtector())
    try:
        store.save("  ")
    except ValueError as error:
        assert str(error) == "mineru_api_token_required"
    else:
        raise AssertionError("empty secret must fail")


def test_windows_dpapi_roundtrip(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    store = MineruSecretStore(tmp_path)
    store.save("fictional-dpapi-roundtrip")
    assert b"fictional-dpapi-roundtrip" not in store.path.read_bytes()
    assert store.load() == "fictional-dpapi-roundtrip"
