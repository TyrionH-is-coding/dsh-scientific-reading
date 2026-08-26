from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from .feishu_builder import load_feishu_config, validate_feishu_config_path
from .library_schema import migrate_library


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FeishuAutoSyncPolicy:
    """本地、可审计的飞书自动同步开关。

    凭据只从当前进程环境读取；启用时间和 revision 进入本地 SQLite
    ``library_meta``，不进入配置、job、日志或同步 payload。
    """

    def __init__(
        self,
        data_root: Path,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.environ = os.environ if environ is None else environ

    def probe(self, config_path: Path) -> dict[str, object]:
        app_id = self.environ.get("FEISHU_APP_ID", "")
        app_secret = self.environ.get("FEISHU_APP_SECRET", "")
        if (
            not isinstance(app_id, str)
            or not app_id.strip()
            or not isinstance(app_secret, str)
            or not app_secret.strip()
        ):
            return {"enabled": False, "reason": "feishu_credentials_required"}
        try:
            validated = validate_feishu_config_path(Path(config_path))
            load_feishu_config(validated)
        except (OSError, ValueError, TypeError) as error:
            return {"enabled": False, "reason": str(error)}
        return {"enabled": True, "reason": None, "config_path": str(validated)}

    def initialize(self, config_path: Path) -> dict[str, object]:
        result = self.probe(config_path)
        if not result["enabled"]:
            raise ValueError(str(result["reason"]))
        self.data_root.mkdir(parents=True, exist_ok=True)
        migrate_library(self.data_root)
        with sqlite3.connect(self.data_root / "library.sqlite") as conn:
            existing = dict(
                conn.execute(
                    "SELECT key, value FROM library_meta WHERE key IN "
                    "('feishu_auto_activated_at', 'feishu_auto_revision', 'feishu_auto_config_path')"
                )
            )
            if existing.get("feishu_auto_revision"):
                revision = existing["feishu_auto_revision"]
                activated = False
                conn.execute(
                    "INSERT OR REPLACE INTO library_meta(key, value) VALUES (?, ?)",
                    ("feishu_auto_config_path", result["config_path"]),
                )
            else:
                revision = f"feishu-auto-{secrets.token_hex(8)}"
                conn.executemany(
                    "INSERT OR REPLACE INTO library_meta(key, value) VALUES (?, ?)",
                    [
                        ("feishu_auto_activated_at", _now()),
                        ("feishu_auto_revision", revision),
                        ("feishu_auto_config_path", result["config_path"]),
                    ],
                )
                activated = True
        return {
            "enabled": True,
            "activated": activated,
            "revision": revision,
        }

    def activation_revision(self) -> str | None:
        path = self.data_root / "library.sqlite"
        if not path.is_file():
            return None
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM library_meta WHERE key = 'feishu_auto_revision'"
            ).fetchone()
        return row[0] if row and isinstance(row[0], str) else None

    def config_path(self) -> Path | None:
        path = self.data_root / "library.sqlite"
        if not path.is_file():
            return None
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT value FROM library_meta WHERE key = 'feishu_auto_config_path'"
            ).fetchone()
        return Path(row[0]).resolve() if row and isinstance(row[0], str) and row[0] else None

    def active_config(self):
        """返回已启用且当前环境/配置仍有效的本地配置；不访问飞书。"""
        if not self.activation_revision():
            return None
        app_id = self.environ.get("FEISHU_APP_ID", "")
        app_secret = self.environ.get("FEISHU_APP_SECRET", "")
        if not isinstance(app_id, str) or not app_id.strip() or not isinstance(app_secret, str) or not app_secret.strip():
            return None
        config_path = self.config_path()
        if config_path is None:
            return None
        try:
            config = load_feishu_config(config_path)
        except (OSError, ValueError, TypeError):
            return None
        return config_path, config, self.activation_revision()

    def mark_system_change(self, paper_id: str) -> None:
        path = self.data_root / "library.sqlite"
        if not path.is_file():
            raise ValueError("library_unavailable")
        with sqlite3.connect(path) as conn:
            cursor = conn.execute(
                "UPDATE items SET feishu_sync_state = 'pending', feishu_error = NULL "
                "WHERE paper_id = ?",
                (paper_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("paper_not_found")

    def pending(self, paper_ids=None) -> list[str]:
        path = self.data_root / "library.sqlite"
        if not path.is_file():
            return []
        with sqlite3.connect(path) as conn:
            activated_row = conn.execute(
                "SELECT value FROM library_meta WHERE key = 'feishu_auto_activated_at'"
            ).fetchone()
            activated_at = activated_row[0] if activated_row else None
            predicate = "feishu_sync_state = 'pending'"
            params: tuple[object, ...] = ()
            if isinstance(activated_at, str) and activated_at:
                predicate += " OR created_at > ? OR updated_at > ?"
                params = (activated_at, activated_at)
            if paper_ids is None:
                rows = conn.execute(
                    f"SELECT paper_id FROM items WHERE ({predicate}) ORDER BY paper_id",
                    params,
                ).fetchall()
            else:
                ids = tuple(dict.fromkeys(paper_ids))
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT paper_id FROM items WHERE ({predicate}) "
                    f"AND paper_id IN ({placeholders}) ORDER BY paper_id",
                    (*params, *ids),
                ).fetchall()
        return [row[0] for row in rows]
