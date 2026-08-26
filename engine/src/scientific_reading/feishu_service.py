from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from . import __version__
from .feishu_http import FeishuApiError, FeishuClient
from .feishu_models import FeishuConfig, FeishuPayload
from .models import StageRecord
from .workspace import PaperWorkspace


def _now() -> str:
    return datetime.now(UTC).isoformat()


def feishu_sync_input_hash(
    config: FeishuConfig,
    payload: FeishuPayload,
) -> str:
    encoded = json.dumps(
        {
            "config": config.to_dict(),
            "payload": payload.to_dict(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FeishuSyncError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        record_ids: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.record_ids = record_ids
        super().__init__(code)


class FeishuSyncService:
    def run(
        self,
        workspace: PaperWorkspace,
        config: FeishuConfig,
        payload: FeishuPayload,
        *,
        client: FeishuClient,
        app_id: str,
        app_secret: str,
    ) -> dict[str, Any]:
        identity = feishu_sync_input_hash(config, payload)
        state = workspace.load_job()
        existing = state.stages.get("feishu_sync")
        local_record_id = self._local_record_id(workspace)
        started_at = (
            existing.started_at
            if existing is not None and existing.started_at
            else _now()
        )
        try:
            token = client.get_tenant_token(app_id, app_secret)
            if (
                existing is not None
                and existing.status == "completed"
                and existing.input_hash == identity
                and isinstance(
                    existing.result.get("record_id"),
                    str,
                )
            ):
                record_id = existing.result["record_id"]
                record = client.get_record(token, record_id)
                self._validate_readback(
                    record,
                    config,
                    payload,
                    record_id=record_id,
                )
                return {**existing.result, "cached": True}

            if local_record_id:
                record_ids = (local_record_id,)
            else:
                matches: dict[str, dict[str, Any]] = {}
                for _logical_name, field_name, value in payload.dedupe_keys(
                    config
                ):
                    for record in client.search_records(
                        token,
                        field_name,
                        value,
                    ):
                        record_id = record.get("record_id")
                        if not isinstance(record_id, str) or not record_id:
                            raise FeishuSyncError("feishu_sync_failed")
                        matches[record_id] = record
                record_ids = tuple(sorted(matches))
                if len(record_ids) > 1:
                    raise FeishuSyncError(
                        "ambiguous_feishu_record",
                        record_ids=record_ids,
                    )

            fields = payload.mapped_fields(config)
            if record_ids:
                record_id = record_ids[0]
                client.update_record(token, record_id, fields)
                action = "updated"
            else:
                created = client.create_record(token, fields)
                record_id = created.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise FeishuSyncError("feishu_sync_failed")
                action = "created"
            record = client.get_record(token, record_id)
            self._validate_readback(
                record,
                config,
                payload,
                record_id=record_id,
            )
            record_url = self._record_url(record, config, record_id)
        except FeishuSyncError as error:
            self._record_failure(
                workspace,
                identity,
                started_at,
                error,
            )
            raise
        except FeishuApiError as error:
            converted = FeishuSyncError("feishu_sync_failed")
            self._record_failure(
                workspace,
                identity,
                started_at,
                converted,
                detail={
                    "operation": error.operation,
                },
            )
            raise converted from error
        except Exception as error:
            converted = FeishuSyncError("feishu_sync_failed")
            self._record_failure(workspace, identity, started_at, converted)
            raise converted from error

        result = {
            "status": "completed",
            "record_id": record_id,
            "record_url": record_url,
            "action": action,
            "payload_sha256": payload.identity_hash(),
            "cached": False,
        }
        state = workspace.load_job()
        state.stages["feishu_sync"] = StageRecord(
            status="completed",
            started_at=started_at,
            finished_at=_now(),
            input_hash=identity,
            tool_version=__version__,
            result=result,
        )
        workspace.save_job(state)
        self._set_library_sync(workspace, "synced", record_id=record_id, url=record_url)
        return result

    @staticmethod
    def _local_record_id(workspace: PaperWorkspace) -> str | None:
        path = workspace.root.parents[1] / "library.sqlite"
        if not path.is_file():
            return None
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                "SELECT feishu_record_id FROM items WHERE paper_id = ?",
                (workspace.root.name,),
            ).fetchone()
        return row[0] if row and isinstance(row[0], str) and row[0] else None

    @staticmethod
    def _record_url(
        record: dict[str, Any], config: FeishuConfig, record_id: str
    ) -> str:
        for key in ("record_url", "url"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return (
            f"{config.base_url}/base/{config.app_token}"
            f"?table={config.table_id}&record={record_id}"
        )

    @staticmethod
    def _set_library_sync(
        workspace: PaperWorkspace,
        state: str,
        *,
        record_id: str | None = None,
        url: str | None = None,
        error: str | None = None,
    ) -> None:
        path = workspace.root.parents[1] / "library.sqlite"
        if not path.is_file():
            return
        with sqlite3.connect(path) as conn:
            if state == "synced":
                conn.execute(
                    "UPDATE items SET feishu_sync_state='synced', "
                    "feishu_record_id=?, feishu_record_url=?, feishu_error=NULL "
                    "WHERE paper_id=?",
                    (record_id, url, workspace.root.name),
                )
            else:
                conn.execute(
                    "UPDATE items SET feishu_sync_state='pending', feishu_error=? "
                    "WHERE paper_id=?",
                    (error, workspace.root.name),
                )

    @classmethod
    def _validate_readback(
        cls,
        record: dict[str, Any],
        config: FeishuConfig,
        payload: FeishuPayload,
        *,
        record_id: str,
    ) -> None:
        fields = record.get("fields")
        if not isinstance(fields, dict):
            raise FeishuSyncError(
                "feishu_readback_mismatch",
                record_ids=(record_id,),
            )
        for logical_name, expected in payload.fields.items():
            mapping = config.field_map[logical_name]
            actual = fields.get(mapping.name)
            if cls._normalized(actual, mapping.field_type) != cls._normalized(
                expected,
                mapping.field_type,
            ):
                raise FeishuSyncError(
                    "feishu_readback_mismatch",
                    record_ids=(record_id,),
                )

    @staticmethod
    def _normalized(value: Any, field_type: str) -> Any:
        if field_type == "text":
            return "" if value is None else str(value).strip()
        if field_type == "number":
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                return object()
            return value
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) for item in value
        ):
            return object()
        return tuple(sorted(set(item.strip() for item in value)))

    @staticmethod
    def _record_failure(
        workspace: PaperWorkspace,
        identity: str,
        started_at: str,
        error: FeishuSyncError,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        state = workspace.load_job()
        state.stages["feishu_sync"] = StageRecord(
            status="failed",
            started_at=started_at,
            finished_at=_now(),
            input_hash=identity,
            tool_version=__version__,
            result={
                "status": "failed",
                "reason_code": error.code,
                "record_ids": list(error.record_ids),
                **(detail or {}),
            },
            error=error.code,
        )
        workspace.save_job(state)
        FeishuSyncService._set_library_sync(
            workspace,
            "pending",
            error=error.code,
        )
