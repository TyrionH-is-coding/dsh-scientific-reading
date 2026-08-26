from __future__ import annotations

import json

import pytest

from scientific_reading.feishu_http import (
    FeishuApiError,
    FeishuClient,
    HttpResponse,
)


class FakeTransport:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, body, timeout):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(value, status=200):
    return HttpResponse(
        status=status,
        body=json.dumps(value, ensure_ascii=False).encode("utf-8"),
    )


def _client(transport):
    return FeishuClient(
        base_url="https://open.feishu.cn",
        app_token="app_123",
        table_id="tbl_123",
        transport=transport,
    )


def test_authentication_uses_current_internal_tenant_token_shape() -> None:
    transport = FakeTransport(
        [
            _response(
                {
                    "code": 0,
                    "msg": "ok",
                    "tenant_access_token": "tenant-secret",
                    "expire": 7200,
                }
            )
        ]
    )

    token = _client(transport).get_tenant_token(
        "cli_app",
        "app-secret",
    )

    call = transport.calls[0]
    assert token == "tenant-secret"
    assert call["method"] == "POST"
    assert call["url"].endswith(
        "/open-apis/auth/v3/tenant_access_token/internal"
    )
    assert json.loads(call["body"]) == {
        "app_id": "cli_app",
        "app_secret": "app-secret",
    }
    assert "Authorization" not in call["headers"]


def test_search_records_paginates_with_exact_filter_and_bearer() -> None:
    transport = FakeTransport(
        [
            _response(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"record_id": "rec_1", "fields": {"DOI": "x"}}
                        ],
                        "has_more": True,
                        "page_token": "next page",
                    },
                }
            ),
            _response(
                {
                    "code": 0,
                    "data": {
                        "items": [
                            {"record_id": "rec_2", "fields": {"DOI": "x"}}
                        ],
                        "has_more": False,
                    },
                }
            ),
        ]
    )

    records = _client(transport).search_records(
        "tenant-secret",
        "DOI",
        "10.1000/example",
    )

    assert [record["record_id"] for record in records] == ["rec_1", "rec_2"]
    assert len(transport.calls) == 2
    assert transport.calls[0]["headers"]["Authorization"] == (
        "Bearer tenant-secret"
    )
    assert transport.calls[0]["url"].endswith(
        "/records/search?page_size=500"
    )
    assert transport.calls[1]["url"].endswith(
        "/records/search?page_size=500&page_token=next%20page"
    )
    assert json.loads(transport.calls[0]["body"]) == {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {
                    "field_name": "DOI",
                    "operator": "is",
                    "value": ["10.1000/example"],
                }
            ],
        }
    }


def test_create_update_and_get_use_record_endpoints() -> None:
    transport = FakeTransport(
        [
            _response(
                {
                    "code": 0,
                    "data": {
                        "record": {
                            "record_id": "rec_1",
                            "fields": {"标题": "Synthetic"},
                        }
                    },
                }
            ),
            _response(
                {
                    "code": 0,
                    "data": {
                        "record": {
                            "record_id": "rec_1",
                            "fields": {"标题": "Updated"},
                        }
                    },
                }
            ),
            _response(
                {
                    "code": 0,
                    "data": {
                        "record": {
                            "record_id": "rec_1",
                            "fields": {"标题": "Updated"},
                        }
                    },
                }
            ),
        ]
    )
    client = _client(transport)

    created = client.create_record(
        "tenant-secret",
        {"标题": "Synthetic"},
    )
    updated = client.update_record(
        "tenant-secret",
        "rec_1",
        {"标题": "Updated"},
    )
    fetched = client.get_record("tenant-secret", "rec_1")

    assert created["record_id"] == updated["record_id"] == "rec_1"
    assert fetched["fields"]["标题"] == "Updated"
    assert [call["method"] for call in transport.calls] == [
        "POST",
        "PUT",
        "GET",
    ]
    assert json.loads(transport.calls[0]["body"]) == {
        "fields": {"标题": "Synthetic"}
    }
    assert transport.calls[1]["url"].endswith("/records/rec_1")
    assert transport.calls[2]["body"] is None


@pytest.mark.parametrize(
    "response",
    [
        _response({"code": 0}, status=503),
        _response({"code": 1254001, "msg": "invalid parameter"}),
        HttpResponse(status=200, body=b"not-json"),
    ],
)
def test_api_failures_raise_bounded_sanitized_error(response) -> None:
    transport = FakeTransport([response])

    with pytest.raises(FeishuApiError) as captured:
        _client(transport).get_record("tenant-secret", "rec_1")

    message = str(captured.value)
    assert captured.value.operation == "get_record"
    assert "tenant-secret" not in message
    assert "Authorization" not in message
    assert len(message) <= 300


def test_transport_error_does_not_leak_credentials() -> None:
    transport = FakeTransport(
        [
            TimeoutError(
                "timeout app-secret tenant-secret "
                "Authorization: Bearer tenant-secret"
            )
        ]
    )
    client = _client(transport)

    with pytest.raises(FeishuApiError) as captured:
        client.get_tenant_token("cli_app", "app-secret")

    message = str(captured.value)
    assert "app-secret" not in message
    assert "Authorization" not in message
