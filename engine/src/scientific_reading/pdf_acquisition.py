from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from . import __version__
from .background_models import AgentRequired, UserRequired
from .models import PaperMetadata, StageRecord
from .pdf_validation import PdfValidationResult, validate_pdf
from .subprocess_utils import hidden_window_kwargs
from .workspace import PaperWorkspace
from .workspace import atomic_write_json


class PdfAcquisitionError(RuntimeError):
    """PDF acquisition failed before a trusted source was published."""


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    status: str
    attachment_key: str
    sha256: str
    source_path: Path
    page_count: int = 0
    reused: bool = False


class PdfProvider(Protocol):
    """新版精读流程可注入的受信任 PDF 获取器。"""

    def acquire(
        self, metadata: PaperMetadata, destination: Path
    ) -> AcquisitionResult: ...


class ScansciJsonProvider:
    """由宿主环境注入的固定 wrapper；请求与响应均为单一 JSON。"""

    def __init__(self, python: Path, wrapper: Path) -> None:
        self.python = Path(python).resolve()
        self.wrapper = Path(wrapper).resolve()
        if not self.python.is_file() or not self.wrapper.is_file():
            raise ValueError("trusted_provider_unavailable")

    @classmethod
    def from_environ(cls) -> "ScansciJsonProvider":
        python = os.environ.get("SR_SCANSCI_PROVIDER_PYTHON", "")
        wrapper = os.environ.get("SR_SCANSCI_PROVIDER_WRAPPER", "")
        if not python or not wrapper:
            raise ValueError("trusted_provider_unavailable")
        return cls(Path(python), Path(wrapper))

    def acquire(self, metadata: PaperMetadata, destination: Path) -> AcquisitionResult:
        identifier = metadata.doi or metadata.pmid or metadata.title
        payload = {
            "identifier": identifier,
            "destination": str(Path(destination).resolve()),
            "legal_only": True,
        }
        completed = subprocess.run(
            [str(self.python), str(self.wrapper)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            check=False,
            env={
                key: value
                for key, value in os.environ.items()
                if key not in {"FEISHU_APP_ID", "FEISHU_APP_SECRET"}
            },
            **hidden_window_kwargs(),
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("trusted_provider_invalid_response") from error
        if (
            completed.returncode != 0
            or not isinstance(response, dict)
            or response.get("status") != "success"
            or Path(str(response.get("path", ""))).resolve()
            != Path(destination).resolve()
        ):
            raise ValueError("trusted_provider_failed")
        return AcquisitionResult("downloaded", "", "", Path(destination).resolve())


class TrustedPdfAcquisitionService:
    """按 SQLite paper_id 校验并原子发布精读原件。"""

    def __init__(
        self,
        data_root: Path,
        provider: PdfProvider | None = None,
        *,
        claim_timeout: float = 10.0,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.provider = provider
        self.claim_timeout = claim_timeout

    def ensure_pdf(self, paper_id: str) -> AcquisitionResult:
        from .background_models import UserActionRequired
        from .library_service import LibraryService

        library = LibraryService(self.data_root)
        try:
            metadata = library.canonical_metadata(paper_id)
            workspace = PaperWorkspace.create_for_paper_id(
                self.data_root, paper_id, metadata
            )
            with self._claim(workspace):
                return self._ensure_locked(library, paper_id, metadata, workspace)
        finally:
            library.close()

    def _ensure_locked(self, library, paper_id, metadata, workspace):
        from .background_models import UserActionRequired

        self._remove_orphan_staging(workspace)
        if workspace.source_pdf.is_file():
            validation = validate_pdf(workspace.source_pdf, metadata)
            if validation.valid:
                previous = library.pdf_attachment(paper_id)
                reader_paths = self._reader_paths(workspace)
                changed = bool(
                    previous and previous["sha256"] != validation.sha256
                )
                if changed and reader_paths:
                    self._write_stale_manifest(
                        workspace, validation.sha256, reader_paths, previous["sha256"]
                    )
                library.commit_pdf_publication(
                    paper_id,
                    validation.sha256,
                    workspace.source_pdf.stat().st_size,
                    source_changed=changed,
                    reader_paths=reader_paths,
                )
                return AcquisitionResult(
                    "pdf_ready",
                    library.get_item(paper_id)["library_key"],
                    validation.sha256,
                    workspace.source_pdf,
                    validation.page_count,
                    True,
                )
        if self.provider is None:
            raise self._required()
        staging = workspace.root / f".source.{uuid.uuid4().hex}.pdf.staging"
        try:
            result = self.provider.acquire(metadata, staging)
            if Path(result.source_path).resolve() != staging.resolve():
                raise ValueError("provider_destination_invalid")
            validation = validate_pdf(staging, metadata)
            if not validation.valid:
                raise ValueError("invalid_provider_pdf")
            return self._publish(
                library, paper_id, metadata, workspace, validation, staging
            )
        except UserActionRequired:
            raise
        except Exception as error:
            raise self._required() from error
        finally:
            staging.unlink(missing_ok=True)

    def attach_local(self, paper_id: str, pdf_path: Path) -> AcquisitionResult:
        from .library_service import LibraryService

        target = Path(pdf_path)
        if not target.is_absolute() or target.suffix.casefold() != ".pdf":
            raise ValueError("invalid_target_pdf")
        library = LibraryService(self.data_root)
        try:
            metadata = library.canonical_metadata(paper_id)
            validation = validate_pdf(target, metadata)
            if not validation.valid:
                raise ValueError("invalid_target_pdf")
            workspace = PaperWorkspace.create_for_paper_id(
                self.data_root, paper_id, metadata
            )
            with self._claim(workspace):
                self._remove_orphan_staging(workspace)
                staging = workspace.root / f".source.{uuid.uuid4().hex}.pdf.staging"
                try:
                    shutil.copyfile(target, staging)
                    staged = validate_pdf(staging, metadata)
                    if not staged.valid or staged.sha256 != validation.sha256:
                        raise ValueError("pdf_staging_readback_failed")
                    return self._publish(
                        library, paper_id, metadata, workspace, staged, staging
                    )
                finally:
                    staging.unlink(missing_ok=True)
        finally:
            library.close()

    @staticmethod
    def _required():
        from .background_models import UserActionRequired

        return UserActionRequired(
            "pdf_required",
            {"kind": "pdf", "options": ["institution_browser", "local_pdf"]},
        )

    @staticmethod
    def _publish(library, paper_id, metadata, workspace, validation, staging):
        previous = library.pdf_attachment(paper_id)
        previous_sha = previous["sha256"] if previous else None
        current_valid = False
        if workspace.source_pdf.is_file():
            current = validate_pdf(workspace.source_pdf, metadata)
            current_valid = current.valid
            if current_valid:
                previous_sha = previous_sha or current.sha256
        if current_valid and _sha256(workspace.source_pdf) == validation.sha256:
            staging.unlink(missing_ok=True)
            reused = True
        else:
            staging.replace(workspace.source_pdf)
            reused = False
        readback = validate_pdf(workspace.source_pdf, metadata)
        if not readback.valid or readback.sha256 != validation.sha256:
            raise ValueError("pdf_publish_readback_failed")
        changed = bool(previous_sha and previous_sha != validation.sha256)
        reader_paths = TrustedPdfAcquisitionService._reader_paths(workspace)
        if changed and reader_paths:
            TrustedPdfAcquisitionService._write_stale_manifest(
                workspace, validation.sha256, reader_paths, previous_sha
            )
        library.commit_pdf_publication(
            paper_id,
            validation.sha256,
            workspace.source_pdf.stat().st_size,
            source_changed=changed,
            reader_paths=reader_paths,
        )
        persisted = library.pdf_attachment(paper_id)
        if persisted is None or persisted["sha256"] != _sha256(workspace.source_pdf):
            raise ValueError("pdf_database_readback_failed")
        return AcquisitionResult(
            "pdf_ready",
            library.get_item(paper_id)["library_key"],
            validation.sha256,
            workspace.source_pdf,
            validation.page_count,
            reused,
        )

    @staticmethod
    def _reader_paths(workspace: PaperWorkspace) -> tuple[str, ...]:
        candidates = (
            workspace.reading_dir / "reader.html",
            workspace.reading_dir / "reader_full.html",
            workspace.output_dir / "reader.html",
            workspace.output_dir / "reader_full.html",
            workspace.root / "reader.html",
            workspace.root / "reader_full.html",
        )
        return tuple(
            path.relative_to(workspace.root).as_posix()
            for path in candidates
            if path.is_file()
        )

    @staticmethod
    def _write_stale_manifest(
        workspace: PaperWorkspace,
        source_sha256: str,
        reader_paths: tuple[str, ...],
        previous_source_sha256: str | None,
    ) -> None:
        atomic_write_json(
            workspace.reading_dir / "reader-stale.json",
            {
                "contract_version": "reader-stale-v1",
                "active_source_pdf_sha256": source_sha256,
                "stale_reader_source_sha256": previous_source_sha256,
                "reader_paths": list(reader_paths),
                "stale_at": _now(),
            },
        )

    @staticmethod
    def _remove_orphan_staging(workspace: PaperWorkspace) -> None:
        for path in workspace.root.glob(".source.*.pdf.staging"):
            path.unlink(missing_ok=True)

    @contextmanager
    def _claim(self, workspace: PaperWorkspace):
        lock = workspace.root / ".pdf.lock"
        deadline = time.monotonic() + self.claim_timeout
        handle = None
        while True:
            candidate = None
            try:
                candidate = lock.open("a+b")
                self._try_advisory_lock(candidate)
                handle = candidate
                break
            except OSError:
                if candidate is not None:
                    candidate.close()
            if time.monotonic() >= deadline:
                raise PdfAcquisitionError("pdf_publication_busy") from None
            time.sleep(0.01)
        try:
            yield
        finally:
            if handle is not None:
                try:
                    self._release_advisory_lock(handle)
                finally:
                    handle.close()

    @staticmethod
    def _try_advisory_lock(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release_advisory_lock(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
