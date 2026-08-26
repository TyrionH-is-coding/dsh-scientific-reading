from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path

import pytest

from scientific_reading.mineru_api import (
    HttpResponse,
    MineruApiClient,
    MineruApiError,
    safe_extract_zip,
)


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str], object]] = []

    def request(self, method, url, *, headers, body=None, timeout=60):
        self.requests.append((method, url, dict(headers), body))
        return self.responses.pop(0)


def response(payload: dict, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode("utf-8"))


def result_zip() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "paper/auto/paper_content_list.json",
            json.dumps([{"type": "text", "text": "Bridge", "page_idx": 0}]),
        )
        archive.writestr("paper/auto/full.md", "Bridge\n")
    return stream.getvalue()


def test_client_uploads_without_token_then_polls_and_extracts(tmp_path) -> None:
    pdf = tmp_path / "bridge.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    transport = FakeTransport(
        [
            response({"code": 0, "data": {"batch_id": "batch-1", "file_urls": ["https://signed.example/upload"]}}),
            HttpResponse(200, b""),
            response({"code": 0, "data": {"extract_result": [{"file_name": "bridge.pdf", "data_id": "paper-1", "state": "running"}]}}),
            response({"code": 0, "data": {"extract_result": [{"file_name": "bridge.pdf", "data_id": "paper-1", "state": "done", "full_zip_url": "https://cdn.example/result.zip"}]}}),
            HttpResponse(200, result_zip()),
        ]
    )
    sleeps: list[float] = []
    client = MineruApiClient(
        "secret-token",
        transport=transport,
        sleep=sleeps.append,
        poll_interval=0.25,
    )

    result = client.parse(
        pdf,
        tmp_path / "raw",
        data_id="paper-1",
        checkpoint_path=tmp_path / "checkpoint.json",
        heartbeat=lambda: None,
    )

    assert result.batch_id == "batch-1"
    assert result.model_version == "pipeline"
    assert result.result_zip_sha256
    assert (tmp_path / "raw/paper/auto/paper_content_list.json").is_file()
    create = transport.requests[0]
    assert create[0:2] == ("POST", "https://mineru.net/api/v4/file-urls/batch")
    assert create[2]["Authorization"] == "Bearer secret-token"
    create_payload = json.loads(create[3])
    assert create_payload["model_version"] == "pipeline"
    assert create_payload["enable_formula"] is True
    assert create_payload["enable_table"] is True
    upload = transport.requests[1]
    assert upload[0] == "PUT"
    assert "Authorization" not in upload[2]
    assert upload[2]["Content-Type"] == ""
    assert upload[3] == pdf
    assert sleeps == [0.25]
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["state"] == "done"
    assert "url" not in json.dumps(checkpoint).lower()


def test_client_resumes_uploaded_batch_without_requesting_new_url(tmp_path) -> None:
    pdf = tmp_path / "bridge.pdf"
    pdf.write_bytes(b"%PDF resume")
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps({
            "contract_version": "mineru-api-checkpoint-v1",
            "source_pdf_sha256": __import__("hashlib").sha256(pdf.read_bytes()).hexdigest(),
            "data_id": "paper-1",
            "batch_id": "batch-old",
            "model_version": "pipeline",
            "state": "uploaded",
        }),
        encoding="utf-8",
    )
    transport = FakeTransport([
        response({"code": 0, "data": {"extract_result": [{"data_id": "paper-1", "state": "done", "full_zip_url": "https://cdn.example/result.zip"}]}}),
        HttpResponse(200, result_zip()),
    ])

    result = MineruApiClient("token", transport=transport, sleep=lambda _: None).parse(
        pdf,
        tmp_path / "raw",
        data_id="paper-1",
        checkpoint_path=checkpoint,
        heartbeat=lambda: None,
    )

    assert result.batch_id == "batch-old"
    assert [request[0] for request in transport.requests] == ["GET", "GET"]


@pytest.mark.parametrize("code", ["A0202", "A0211"])
def test_auth_errors_are_stable_and_do_not_leak_token(code) -> None:
    transport = FakeTransport([response({"code": code, "msg": "bad token secret-token"})])
    client = MineruApiClient("secret-token", transport=transport)

    with pytest.raises(MineruApiError) as captured:
        client.request_upload("paper.pdf", "paper-1")

    assert captured.value.code == "mineru_api_auth_failed"
    assert "secret-token" not in str(captured.value)


def test_failed_parse_maps_to_stable_error(tmp_path) -> None:
    pdf = tmp_path / "bridge.pdf"
    pdf.write_bytes(b"%PDF")
    transport = FakeTransport([
        response({"code": 0, "data": {"batch_id": "b", "file_urls": ["https://signed.example/token"]}}),
        HttpResponse(200, b""),
        response({"code": 0, "data": {"extract_result": [{"data_id": "p", "state": "failed", "err_msg": "broken"}]}}),
    ])

    with pytest.raises(MineruApiError) as captured:
        MineruApiClient("token", transport=transport).parse(
            pdf, tmp_path / "raw", data_id="p", checkpoint_path=tmp_path / "cp.json", heartbeat=lambda: None
        )

    assert captured.value.code == "mineru_api_parse_failed"
    assert "signed.example" not in str(captured.value)


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:\\escape.txt"])
def test_safe_extract_rejects_traversal(tmp_path, name) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(name, "bad")

    with pytest.raises(MineruApiError, match="mineru_api_archive_unsafe"):
        safe_extract_zip(archive_path, tmp_path / "out")


def test_safe_extract_rejects_symlink(tmp_path) -> None:
    archive_path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "target")

    with pytest.raises(MineruApiError, match="mineru_api_archive_unsafe"):
        safe_extract_zip(archive_path, tmp_path / "out")
