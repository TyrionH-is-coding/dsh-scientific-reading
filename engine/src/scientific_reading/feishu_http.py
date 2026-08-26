from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return HttpResponse(
                    status=response.status,
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(status=error.code, body=error.read())


class FeishuApiError(RuntimeError):
    def __init__(self, operation: str, summary: str) -> None:
        self.operation = operation
        self.summary = summary[:220]
        super().__init__(
            f"feishu_api_error:{operation}:{self.summary}"
        )


def _redact(value: str, secrets: tuple[str, ...]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    result = re.sub(
        r"(?i)authorization\s*:\s*bearer\s+\S+",
        "[redacted]",
        result,
    )
    result = re.sub(r"(?i)authorization", "[redacted]", result)
    return " ".join(result.split())


class FeishuClient:
    def __init__(
        self,
        *,
        base_url: str,
        app_token: str,
        table_id: str,
        transport: HttpTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_token = app_token
        self.table_id = table_id
        self.transport = transport or UrllibTransport()
        self.timeout = timeout

    def get_tenant_token(
        self,
        app_id: str,
        app_secret: str,
    ) -> str:
        payload = self._request(
            "authenticate",
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            body={"app_id": app_id, "app_secret": app_secret},
            secrets=(app_id, app_secret),
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuApiError(
                "authenticate",
                "tenant_access_token_missing",
            )
        return token

    def search_records(
        self,
        token: str,
        field_name: str,
        value: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query = "?page_size=500"
            if page_token:
                query += f"&page_token={quote(page_token, safe='')}"
            payload = self._request(
                "search_records",
                "POST",
                self._records_path() + "/search" + query,
                token=token,
                body={
                    "filter": {
                        "conjunction": "and",
                        "conditions": [
                            {
                                "field_name": field_name,
                                "operator": "is",
                                "value": [value],
                            }
                        ],
                    }
                },
                secrets=(token,),
            )
            data = self._data(payload, "search_records")
            items = data.get("items", [])
            if not isinstance(items, list) or not all(
                isinstance(item, dict) for item in items
            ):
                raise FeishuApiError(
                    "search_records",
                    "records_invalid",
                )
            records.extend(items)
            if not data.get("has_more"):
                return records
            page_token = data.get("page_token")
            if not isinstance(page_token, str) or not page_token:
                raise FeishuApiError(
                    "search_records",
                    "page_token_missing",
                )

    def create_record(
        self,
        token: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._request(
            "create_record",
            "POST",
            self._records_path(),
            token=token,
            body={"fields": fields},
            secrets=(token,),
        )
        return self._record(payload, "create_record")

    def update_record(
        self,
        token: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        payload = self._request(
            "update_record",
            "PUT",
            f"{self._records_path()}/{quote(record_id, safe='')}",
            token=token,
            body={"fields": fields},
            secrets=(token,),
        )
        return self._record(payload, "update_record")

    def get_record(
        self,
        token: str,
        record_id: str,
    ) -> dict[str, Any]:
        payload = self._request(
            "get_record",
            "GET",
            f"{self._records_path()}/{quote(record_id, safe='')}",
            token=token,
            secrets=(token,),
        )
        return self._record(payload, "get_record")

    def _records_path(self) -> str:
        return (
            "/open-apis/bitable/v1/apps/"
            f"{quote(self.app_token, safe='')}/tables/"
            f"{quote(self.table_id, safe='')}/records"
        )

    @staticmethod
    def _data(
        payload: dict[str, Any],
        operation: str,
    ) -> dict[str, Any]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise FeishuApiError(operation, "response_data_invalid")
        return data

    @classmethod
    def _record(
        cls,
        payload: dict[str, Any],
        operation: str,
    ) -> dict[str, Any]:
        record = cls._data(payload, operation).get("record")
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("record_id"), str)
            or not isinstance(record.get("fields"), dict)
        ):
            raise FeishuApiError(operation, "record_invalid")
        return record

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        secrets: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        encoded = (
            json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if body is not None
            else None
        )
        try:
            response = self.transport.request(
                method,
                self.base_url + path,
                headers=headers,
                body=encoded,
                timeout=self.timeout,
            )
        except Exception as error:
            raise FeishuApiError(
                operation,
                _redact(str(error), secrets),
            ) from error
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FeishuApiError(
                operation,
                f"http_{response.status}:invalid_json",
            ) from error
        if not isinstance(payload, dict):
            raise FeishuApiError(operation, "response_invalid")
        code = payload.get("code")
        if not 200 <= response.status < 300 or code != 0:
            message = _redact(str(payload.get("msg", "")), secrets)
            raise FeishuApiError(
                operation,
                f"http_{response.status}:code_{code}:{message}",
            )
        return payload
