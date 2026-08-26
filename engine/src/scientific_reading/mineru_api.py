from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

from .workspace import atomic_write_json


API_CONTRACT_VERSION = "mineru-api-v4"
CHECKPOINT_VERSION = "mineru-api-checkpoint-v1"
DEFAULT_BASE_URL = "https://mineru.net"
DEFAULT_MODEL_VERSION = "pipeline"


class MineruApiError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(code if not message else f"{code}: {message}")


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
        body: str | bytes | Path | None = None,
        timeout: float = 60,
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(self, method, url, *, headers, body=None, timeout=60):
        if isinstance(body, Path):
            data = body.read_bytes()
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read())
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MineruApiError("mineru_api_unavailable") from error


@dataclass(frozen=True, slots=True)
class MineruApiResult:
    batch_id: str
    model_version: str
    result_zip_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract_zip(
    archive_path: Path,
    output_dir: Path,
    *,
    max_files: int = 10_000,
    max_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > max_files:
                raise MineruApiError("mineru_api_archive_unsafe")
            if sum(item.file_size for item in infos) > max_uncompressed_bytes:
                raise MineruApiError("mineru_api_archive_unsafe")
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                relative = PurePosixPath(normalized)
                mode = info.external_attr >> 16
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or (relative.parts and ":" in relative.parts[0])
                    or stat.S_ISLNK(mode)
                ):
                    raise MineruApiError("mineru_api_archive_unsafe")
                target = output.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
    except (zipfile.BadZipFile, OSError) as error:
        raise MineruApiError("mineru_api_result_invalid") from error


class MineruApiClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model_version: str = DEFAULT_MODEL_VERSION,
        transport: HttpTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 3.0,
        max_polls: int = 1200,
        timeout: float = 60.0,
    ) -> None:
        if not token.strip():
            raise MineruApiError("mineru_api_token_required")
        self._token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.model_version = model_version
        self.transport = transport or UrllibTransport()
        self.sleep = sleep
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _json_request(self, method: str, path: str, body=None) -> dict:
        response = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            body=(json.dumps(body, separators=(",", ":")) if body is not None else None),
            timeout=self.timeout,
        )
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MineruApiError("mineru_api_result_invalid") from error
        code = payload.get("code")
        if response.status in {401, 403} or code in {"A0202", "A0211"}:
            raise MineruApiError("mineru_api_auth_failed")
        if code in {-60018, -60019, "-60018", "-60019"} or response.status == 429:
            raise MineruApiError("mineru_api_quota_exceeded")
        if response.status >= 500 or code in {-10001, -60007, -60009, "-10001", "-60007", "-60009"}:
            raise MineruApiError("mineru_api_unavailable")
        if response.status != 200 or code != 0:
            raise MineruApiError("mineru_api_result_invalid")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MineruApiError("mineru_api_result_invalid")
        return data

    def request_upload(self, file_name: str, data_id: str) -> tuple[str, str]:
        data = self._json_request(
            "POST",
            "/api/v4/file-urls/batch",
            {
                "files": [{"name": file_name, "data_id": data_id}],
                "model_version": self.model_version,
                "enable_formula": True,
                "enable_table": True,
                "language": "en",
            },
        )
        batch_id = data.get("batch_id")
        urls = data.get("file_urls")
        if not isinstance(batch_id, str) or not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], str):
            raise MineruApiError("mineru_api_result_invalid")
        return batch_id, urls[0]

    def parse(
        self,
        source_pdf: Path,
        output_dir: Path,
        *,
        data_id: str,
        checkpoint_path: Path,
        heartbeat: Callable[[], None],
    ) -> MineruApiResult:
        source = Path(source_pdf).resolve()
        if not source.is_file():
            raise ValueError("source_pdf_required")
        source_hash = _sha256(source)
        checkpoint = self._load_checkpoint(checkpoint_path, source_hash, data_id)
        if checkpoint is None:
            batch_id, upload_url = self.request_upload(source.name, data_id)
            self._write_checkpoint(checkpoint_path, source_hash, data_id, batch_id, "upload_pending")
            upload = self.transport.request(
                "PUT",
                upload_url,
                headers={"Content-Type": ""},
                body=source,
                timeout=self.timeout,
            )
            if upload.status not in {200, 201, 204}:
                raise MineruApiError("mineru_api_unavailable")
            self._write_checkpoint(checkpoint_path, source_hash, data_id, batch_id, "uploaded")
        else:
            batch_id = checkpoint["batch_id"]

        result_url = None
        for poll in range(self.max_polls):
            heartbeat()
            data = self._json_request(
                "GET", f"/api/v4/extract-results/batch/{batch_id}"
            )
            results = data.get("extract_result")
            if not isinstance(results, list):
                raise MineruApiError("mineru_api_result_invalid")
            match = next(
                (item for item in results if isinstance(item, dict) and item.get("data_id") == data_id),
                results[0] if len(results) == 1 and isinstance(results[0], dict) else None,
            )
            if not isinstance(match, dict):
                raise MineruApiError("mineru_api_result_invalid")
            state = match.get("state")
            if state == "failed":
                raise MineruApiError("mineru_api_parse_failed")
            if state == "done":
                result_url = match.get("full_zip_url")
                if not isinstance(result_url, str):
                    raise MineruApiError("mineru_api_result_invalid")
                break
            if state not in {"waiting-file", "pending", "running", "converting"}:
                raise MineruApiError("mineru_api_result_invalid")
            if poll + 1 < self.max_polls:
                self.sleep(self.poll_interval)
        if result_url is None:
            raise MineruApiError("mineru_api_timeout")

        archive_response = self.transport.request(
            "GET", result_url, headers={}, timeout=self.timeout
        )
        if archive_response.status != 200:
            raise MineruApiError("mineru_api_unavailable")
        archive_path = Path(output_dir).parent / "mineru-result.zip"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(archive_response.body)
        archive_hash = _sha256(archive_path)
        try:
            safe_extract_zip(archive_path, output_dir)
        finally:
            archive_path.unlink(missing_ok=True)
        self._write_checkpoint(checkpoint_path, source_hash, data_id, batch_id, "done")
        return MineruApiResult(batch_id, self.model_version, archive_hash)

    def _load_checkpoint(self, path: Path, source_hash: str, data_id: str):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if (
            payload.get("contract_version") == CHECKPOINT_VERSION
            and payload.get("source_pdf_sha256") == source_hash
            and payload.get("data_id") == data_id
            and payload.get("model_version") == self.model_version
            and payload.get("state") in {"uploaded", "polling"}
            and isinstance(payload.get("batch_id"), str)
        ):
            return payload
        return None

    def _write_checkpoint(self, path, source_hash, data_id, batch_id, state):
        atomic_write_json(
            Path(path),
            {
                "contract_version": CHECKPOINT_VERSION,
                "source_pdf_sha256": source_hash,
                "data_id": data_id,
                "batch_id": batch_id,
                "model_version": self.model_version,
                "state": state,
            },
        )


def token_from_environment() -> str:
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if not token:
        raise MineruApiError("mineru_api_token_required")
    return token
