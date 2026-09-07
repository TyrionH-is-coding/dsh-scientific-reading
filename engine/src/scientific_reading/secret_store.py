"""Instance-scoped credentials in DPAPI, macOS Keychain or Linux Secret Service."""

from __future__ import annotations

import ctypes
import os
import sys
import hashlib
from pathlib import Path
from typing import Protocol


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...
    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDpapiProtector:
    def _transform(self, value: bytes, function_name: str) -> bytes:
        if os.name != "nt":
            raise RuntimeError("secure_store_unsupported")
        buffer = ctypes.create_string_buffer(value)
        source = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = _DataBlob()
        crypt32 = ctypes.windll.crypt32
        function = getattr(crypt32, function_name)
        function.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
        ] if function_name == "CryptProtectData" else [
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
        ]
        function.restype = ctypes.c_int
        if not function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)):
            raise OSError(ctypes.get_last_error(), "dpapi_failed")
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)

    def protect(self, value: bytes) -> bytes:
        return self._transform(value, "CryptProtectData")

    def unprotect(self, value: bytes) -> bytes:
        return self._transform(value, "CryptUnprotectData")


class MineruSecretStore:
    def __init__(self, data_root: Path, *, protector: SecretProtector | None = None, keyring_backend=None) -> None:
        self.data_root = Path(data_root).resolve()
        self.path = self.data_root / "secrets" / "mineru-api-key.dpapi"
        self.protector = protector or WindowsDpapiProtector()
        self.use_keyring = protector is None and sys.platform != "win32"
        self.keyring_backend = keyring_backend
        identity = hashlib.sha256(os.fsencode(str(self.data_root))).hexdigest()
        self.service = "deep-literature-for-codex:" + identity

    def _keyring(self):
        if self.keyring_backend is None:
            try:
                # Select only native secure backends, never third-party plaintext fallback.
                if sys.platform == "darwin":
                    from keyring.backends.macOS import Keyring
                elif sys.platform.startswith("linux"):
                    from keyring.backends.SecretService import Keyring
                else:
                    raise RuntimeError("secure_store_unsupported")
                self.keyring_backend = Keyring()
            except ImportError as error:
                raise RuntimeError("secure_store_dependency_missing") from error
        return self.keyring_backend

    def save(self, value: str) -> None:
        token = value.strip() if isinstance(value, str) else ""
        if not token:
            raise ValueError("mineru_api_token_required")
        if len(token) > 8192:
            raise ValueError("mineru_api_token_invalid")
        if self.use_keyring:
            try:
                self._keyring().set_password(self.service, "mineru-api-token", token)
            except Exception as error:
                raise RuntimeError("secure_store_unavailable") from None
        else:
            encrypted = self.protector.protect(token.encode("utf-8"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_bytes(encrypted)
            temporary.replace(self.path)
        from .environment_status import EnvironmentStatusService
        EnvironmentStatusService(self.data_root).recheck(("mineru_api",))

    def load(self) -> str | None:
        if self.use_keyring:
            try:
                value = self._keyring().get_password(self.service, "mineru-api-token")
                return value.strip() or None if isinstance(value, str) else None
            except Exception:
                # Headless Linux may have no unlocked desktop keyring. Explicit
                # environment credentials remain an engine-level fallback.
                return None
        if not self.path.is_file():
            return None
        try:
            value = self.protector.unprotect(self.path.read_bytes()).decode("utf-8").strip()
        except (OSError, UnicodeError, RuntimeError):
            return None
        return value or None

    def delete(self) -> None:
        if self.use_keyring:
            try:
                backend = self._keyring()
                if backend.get_password(self.service, "mineru-api-token") is not None:
                    backend.delete_password(self.service, "mineru-api-token")
            except Exception as error:
                raise RuntimeError("secure_store_unavailable") from None
        self.path.unlink(missing_ok=True)
        from .environment_status import EnvironmentStatusService
        EnvironmentStatusService(self.data_root).recheck(("mineru_api",))


def resolve_mineru_token(
    data_root: Path, *, store: MineruSecretStore | None = None
) -> tuple[str | None, str]:
    stored = (store or MineruSecretStore(data_root)).load()
    if stored:
        return stored, "secure_store"
    environment = os.environ.get("MINERU_API_TOKEN", "").strip()
    if environment:
        return environment, "environment"
    return None, "none"
