"""本地环境状态快照；静态读取不执行网络探测。"""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


Probe = Callable[[], dict[str, object]]
_TARGETS = {"download", "mineru_local", "mineru_api"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EnvironmentStatusService:
    def __init__(
        self,
        data_root: Path,
        *,
        school: str = "",
        probes: dict[str, Probe] | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.path = self.data_root / "status" / "environment-status-v1.json"
        self.presented_path = self.data_root / "status" / "onboarding-v1.presented"
        self.now = now
        self.probes = {
            "download": self._probe_download,
            "mineru_local": self._probe_mineru_local,
            "mineru_api": self._probe_mineru_api,
            **(probes or {}),
        }

    def snapshot(self) -> dict[str, object]:
        saved = self._load_saved()
        download = self._status(saved.get("download"))
        download["mode"] = "oa_only"
        mineru_saved = saved.get("mineru") if isinstance(saved.get("mineru"), dict) else {}
        return {
            "contract_version": "environment-status-v1",
            "onboarding": {
                "show_settings": not self.presented_path.is_file(),
                "version": "v1",
            },
            "download": download,
            "mineru": {
                "local": self._status(mineru_saved.get("local")),
                "api": {
                    **self._status(mineru_saved.get("api")),
                    "api_call_verified": mineru_saved.get("api", {}).get("api_call_verified") is True
                    if isinstance(mineru_saved.get("api"), dict)
                    else False,
                },
                "strategy": "auto",
            },
            "library": self._library_status(),
        }

    def mark_presented(self, version: str) -> dict[str, object]:
        if version != "v1":
            raise ValueError("onboarding_version_invalid")
        self.presented_path.parent.mkdir(parents=True, exist_ok=True)
        self.presented_path.write_text("v1\n", encoding="utf-8")
        return self.snapshot()

    def recheck(self, targets: Iterable[str]) -> dict[str, object]:
        requested = tuple(dict.fromkeys(targets))
        if not requested or any(target not in _TARGETS for target in requested):
            raise ValueError("environment_target_invalid")
        result = self.snapshot()
        checked_at = self.now()
        for target in requested:
            value = self.probes[target]()
            status = value.get("status") if isinstance(value, dict) else None
            safe = {
                "status": status if isinstance(status, str) and status else "failed",
                "checked_at": checked_at,
            }
            if target == "download":
                safe["mode"] = "oa_only"
                result["download"] = safe
            elif target == "mineru_local":
                result["mineru"]["local"] = safe  # type: ignore[index]
            else:
                safe["api_call_verified"] = False
                result["mineru"]["api"] = safe  # type: ignore[index]
        self._write(result)
        return result

    def mark_mineru_api_verified(self) -> dict[str, object]:
        result = self.snapshot()
        api = result["mineru"]["api"] if isinstance(result.get("mineru"), dict) else {}
        if not isinstance(api, dict):
            api = {}
        api = {
            **api,
            "status": api.get("status") if isinstance(api.get("status"), str) else "configured",
            "api_call_verified": True,
            "checked_at": self.now(),
        }
        result["mineru"]["api"] = api  # type: ignore[index]
        self._write(result)
        return result

    @staticmethod
    def _status(value: object, *, school: str | None = None) -> dict[str, object]:
        source = value if isinstance(value, dict) else {}
        result: dict[str, object] = {
            "status": source.get("status") if isinstance(source.get("status"), str) else "not_checked",
            "checked_at": source.get("checked_at") if isinstance(source.get("checked_at"), str) else None,
        }
        if school is not None:
            result["school"] = school
        return result

    def _load_saved(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write(self, value: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def _library_status(self) -> dict[str, object]:
        database = self.data_root / "library.sqlite"
        location = {"data_root": str(self.data_root), "database": str(database)}
        if not database.is_file():
            return {**location, "status": "empty", "papers": 0, "xlsx_pending": 0}
        try:
            with sqlite3.connect(database) as connection:
                papers = int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])
                pending = int(connection.execute(
                    "SELECT COUNT(*) FROM items WHERE COALESCE(xlsx_sync_state, '') != 'ready'"
                ).fetchone()[0])
        except sqlite3.Error:
            return {**location, "status": "failed", "papers": 0, "xlsx_pending": 0}
        return {**location, "status": "ready", "papers": papers, "xlsx_pending": pending}

    @staticmethod
    def _probe_download() -> dict[str, object]:
        try:
            ready = version("scansci-pdf") == "1.9.0"
        except PackageNotFoundError:
            ready = False
        return {"status": "ready" if ready else "unavailable"}

    def _probe_mineru_local(self) -> dict[str, object]:
        from .mineru_local import LocalMineruProvider

        probe = LocalMineruProvider(data_root=self.data_root).probe()
        return {"status": probe.status}

    def _probe_mineru_api(self) -> dict[str, object]:
        from .secret_store import resolve_mineru_token

        token, source = resolve_mineru_token(self.data_root)
        return {"status": "configured" if token else "not_configured", "source": source}

