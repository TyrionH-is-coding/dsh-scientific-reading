from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


FEISHU_CONFIG_CONTRACT_VERSION = "feishu-config-v1"
FEISHU_PAYLOAD_CONTRACT_VERSION = "feishu-sync-v1"
FEISHU_TEXT_LIMIT = 50_000

SYSTEM_MANAGED_FIELDS = frozenset(
    {
        "title",
        "doi",
        "pmid",
        "source_url",
        "authors",
        "journal",
        "year",
        "projects",
        "library_key",
        "pdf_status",
        "pdf_path",
        "reading_status",
        "abstract_en",
        "abstract_zh",
        "abstract_read",
        "full_read_status",
        "full_read_key_points",
        "full_read_html",
        "updated_at",
        "error_status",
    }
)
USER_MANAGED_FIELDS = {
    "personal_thoughts",
    "understanding_level",
    "user_notes",
}
# Kept as a broad parser allow-list so a v1 config can carry user-owned
# columns; the builder and payload boundary never write those columns.
SUPPORTED_LOGICAL_FIELDS = SYSTEM_MANAGED_FIELDS | USER_MANAGED_FIELDS
REQUIRED_FIELD_MAPPINGS = frozenset(
    {
        "title",
        "doi",
        "pmid",
        "library_key",
        "reading_status",
        "updated_at",
        "error_status",
    }
)
IDENTIFIER_FIELDS = ("doi", "pmid", "library_key")
SUPPORTED_FIELD_TYPES = frozenset({"text", "number", "multi_select"})


def _exact_keys(
    value: dict[str, Any],
    expected: set[str],
    error: str,
) -> None:
    if set(value) != expected:
        raise ValueError(error)


def _required_text(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error)
    return value.strip()


@dataclass(frozen=True, slots=True)
class FeishuFieldMapping:
    name: str
    field_type: str

    @classmethod
    def from_dict(cls, value: Any) -> FeishuFieldMapping:
        if not isinstance(value, dict):
            raise ValueError("feishu_field_mapping_invalid")
        _exact_keys(
            value,
            {"name", "type"},
            "feishu_field_mapping_unexpected_keys",
        )
        name = _required_text(
            value["name"],
            "feishu_field_mapping_name_required",
        )
        field_type = value["type"]
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise ValueError("feishu_field_type_invalid")
        return cls(name=name, field_type=field_type)

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "type": self.field_type}


@dataclass(frozen=True, slots=True)
class FeishuConfig:
    contract_version: str
    base_url: str
    app_token: str
    table_id: str
    field_map: dict[str, FeishuFieldMapping]

    @classmethod
    def from_dict(cls, value: Any) -> FeishuConfig:
        if not isinstance(value, dict):
            raise ValueError("feishu_config_invalid")
        _exact_keys(
            value,
            {
                "contract_version",
                "base_url",
                "app_token",
                "table_id",
                "field_map",
            },
            "feishu_config_unexpected_keys",
        )
        if value["contract_version"] != FEISHU_CONFIG_CONTRACT_VERSION:
            raise ValueError("feishu_config_contract_invalid")
        base_url = _required_text(
            value["base_url"],
            "feishu_config_base_url_invalid",
        ).rstrip("/")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("feishu_config_base_url_invalid")
        raw_map = value["field_map"]
        if not isinstance(raw_map, dict):
            raise ValueError("feishu_config_field_map_invalid")
        raw_map = dict(raw_map)
        unknown = set(raw_map) - SUPPORTED_LOGICAL_FIELDS
        if unknown:
            raise ValueError("feishu_config_logical_field_invalid")
        missing = REQUIRED_FIELD_MAPPINGS - set(raw_map)
        if missing:
            raise ValueError("feishu_config_required_mapping_missing")
        field_map = {
            logical_name: FeishuFieldMapping.from_dict(mapping)
            for logical_name, mapping in raw_map.items()
        }
        if field_map["reading_status"].field_type != "text":
            raise ValueError("feishu_field_type_invalid")
        column_names = [mapping.name for mapping in field_map.values()]
        if len(set(column_names)) != len(column_names):
            raise ValueError("feishu_config_duplicate_column_name")
        return cls(
            contract_version=FEISHU_CONFIG_CONTRACT_VERSION,
            base_url=base_url,
            app_token=_required_text(
                value["app_token"],
                "feishu_config_app_token_required",
            ),
            table_id=_required_text(
                value["table_id"],
                "feishu_config_table_id_required",
            ),
            field_map=field_map,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "base_url": self.base_url,
            "app_token": self.app_token,
            "table_id": self.table_id,
            "field_map": {
                logical_name: mapping.to_dict()
                for logical_name, mapping in self.field_map.items()
            },
        }


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("feishu_payload_text_invalid")
    normalized = value.strip()
    if len(normalized) > FEISHU_TEXT_LIMIT:
        raise ValueError("feishu_payload_text_too_long")
    return normalized


def _normalize_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("feishu_payload_number_invalid")
    return value


def _normalize_multi_select(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("feishu_payload_multi_select_invalid")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("feishu_payload_multi_select_invalid")
        normalized = item.strip()
        if len(normalized) > FEISHU_TEXT_LIMIT:
            raise ValueError("feishu_payload_text_too_long")
        if normalized not in result:
            result.append(normalized)
    return result


@dataclass(frozen=True, slots=True)
class FeishuPayload:
    contract_version: str
    fields: dict[str, Any]

    @classmethod
    def from_logical_values(
        cls,
        config: FeishuConfig,
        values: Any,
    ) -> FeishuPayload:
        if not isinstance(values, dict):
            raise ValueError("feishu_payload_fields_invalid")
        if set(values) - SUPPORTED_LOGICAL_FIELDS:
            raise ValueError("feishu_payload_logical_field_invalid")
        if set(values) & USER_MANAGED_FIELDS:
            raise ValueError("feishu_payload_user_managed_field")
        if set(values) - set(config.field_map):
            raise ValueError("feishu_payload_mapping_missing")
        normalized: dict[str, Any] = {}
        for logical_name, value in values.items():
            field_type = config.field_map[logical_name].field_type
            if field_type == "text":
                normalized[logical_name] = _normalize_text(value)
            elif field_type == "number":
                normalized[logical_name] = _normalize_number(value)
            else:
                normalized[logical_name] = _normalize_multi_select(value)
        if not any(normalized.get(name) for name in IDENTIFIER_FIELDS):
            raise ValueError("feishu_payload_identifier_required")
        return cls(
            contract_version=FEISHU_PAYLOAD_CONTRACT_VERSION,
            fields=normalized,
        )

    @classmethod
    def from_dict(
        cls,
        config: FeishuConfig,
        value: Any,
    ) -> FeishuPayload:
        if not isinstance(value, dict):
            raise ValueError("feishu_payload_invalid")
        _exact_keys(
            value,
            {"contract_version", "fields"},
            "feishu_payload_unexpected_keys",
        )
        if value["contract_version"] != FEISHU_PAYLOAD_CONTRACT_VERSION:
            raise ValueError("feishu_payload_contract_invalid")
        return cls.from_logical_values(config, value["fields"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "fields": self.fields,
        }

    def mapped_fields(self, config: FeishuConfig) -> dict[str, Any]:
        return {
            config.field_map[logical_name].name: value
            for logical_name, value in self.fields.items()
        }

    def dedupe_keys(
        self,
        config: FeishuConfig,
    ) -> tuple[tuple[str, str, str], ...]:
        return tuple(
            (
                logical_name,
                config.field_map[logical_name].name,
                self.fields[logical_name],
            )
            for logical_name in IDENTIFIER_FIELDS
            if self.fields.get(logical_name)
        )

    def identity_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
