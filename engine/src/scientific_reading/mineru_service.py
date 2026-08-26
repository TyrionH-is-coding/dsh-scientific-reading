from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from . import __version__
from .assets import AssetManifest
from .background_models import AgentRequired
from .mineru_api import (
    API_CONTRACT_VERSION,
    DEFAULT_MODEL_VERSION,
    MineruApiClient,
    MineruApiError,
    token_from_environment,
)
from .mineru_models import MINERU_NORMALIZATION_VERSION
from .mineru_normalizer import MineruNormalizer
from .models import AssetRecord, PaperMetadata, StageRecord
from .mineru_artifacts import MineruArtifactValidator
from .package_manifest import refresh_generation_package_manifest
from .pdf_validation import validate_pdf
from .workspace import (
    PaperWorkspace,
    atomic_write_json,
    validate_explicit_workspace,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _api_cache_identity(source_sha256: str, method: str) -> str:
    payload = {
        "source_sha256": source_sha256,
        "provider": API_CONTRACT_VERSION,
        "model_version": DEFAULT_MODEL_VERSION,
        "method": method,
        "normalization_version": MINERU_NORMALIZATION_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@contextmanager
def _mineru_claim(workspace: PaperWorkspace):
    lock_path = workspace.parsed_dir / ".mineru-publish.lock"
    stream = lock_path.open("a+b")
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    acquired = False
    try:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
    except OSError as error:
        stream.close()
        raise AgentRequired(
            "mineru_publish_busy",
            {"paper_id": workspace.root.name},
        ) from error
    try:
        yield
    finally:
        if acquired:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            stream.close()
        except OSError:
            pass


@dataclass(frozen=True, slots=True)
class MineruParseResult:
    status: str
    source_sha256: str
    mineru_version: str
    method: str
    upgrade_reason: str
    raw_content_list_sha256: str
    assets: tuple[AssetRecord, ...]
    cached: bool
    provider: str = API_CONTRACT_VERSION
    model_version: str | None = None
    batch_id: str | None = None
    result_zip_sha256: str | None = None

    def to_dict(self) -> dict:
        value = asdict(self)
        value["assets"] = [asset.to_dict() for asset in self.assets]
        return value


class MineruParseService:
    def __init__(self, *, api_client_factory=None) -> None:
        self.api_client_factory = api_client_factory or (
            lambda token: MineruApiClient(token)
        )

    def run(
        self,
        data_root: Path,
        metadata: PaperMetadata,
        method: str,
        *,
        heartbeat: Callable[[], None],
        upgrade_reason: str = "quality",
        paper_id: str | None = None,
        workspace: PaperWorkspace | None = None,
    ) -> MineruParseResult:
        if method not in {"auto", "txt", "ocr"}:
            raise ValueError("mineru_method_invalid")
        if workspace is not None and paper_id is not None:
            validate_explicit_workspace(
                data_root, paper_id, metadata, workspace
            )
        if upgrade_reason not in {"quality", "full-read"}:
            raise ValueError("mineru_upgrade_reason_invalid")
        workspace = workspace or (
            PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
            if paper_id is not None
            else PaperWorkspace.create(data_root, metadata)
        )
        confirmed = PaperMetadata.from_dict(
            json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        )
        initial = workspace.load_job()
        allowed_statuses = {"pdf_ready", "mineru_running", "parsed_mineru"}
        if initial.status not in allowed_statuses:
            raise ValueError("MinerU 解析要求 pdf_ready")
        fast_stage = initial.stages.get("pdf_acquisition")
        registered_hash = (
            fast_stage.result.get("sha256")
            if fast_stage is not None
            else None
        )
        if fast_stage is None or fast_stage.status != "completed":
            raise ValueError("MinerU 解析要求 pdf_ready")
        validation = validate_pdf(workspace.source_pdf, confirmed)
        if validation.sha256 != registered_hash:
            raise ValueError("source.pdf 与 pdf_ready 登记哈希不一致")
        if not validation.valid:
            raise ValueError("source.pdf 正文验证失败")
        mineru_version = f"{API_CONTRACT_VERSION}:{DEFAULT_MODEL_VERSION}"
        identity = _api_cache_identity(validation.sha256, method)
        provider = API_CONTRACT_VERSION

        with _mineru_claim(workspace):
            cached = self._load_cache(
                workspace,
                confirmed,
                validation.sha256,
                method,
                mineru_version,
                identity,
                upgrade_reason,
            )
            if cached is not None:
                self._record_state(
                    workspace,
                    cached,
                    identity,
                    _now(),
                    _now(),
                )
                refresh_generation_package_manifest(workspace)
                return cached
            target = workspace.parsed_dir / "mineru"
            if target.exists():
                raise AgentRequired(
                    "mineru_artifact_inconsistent",
                    {"paper_id": workspace.root.name},
                )

            started_at = _now()
            started_clock = time.perf_counter()
            original_state = workspace.load_job()
            running_state = workspace.load_job()
            running_state.status = "mineru_running"
            running_state.stages["paper_parse_upgrade"] = StageRecord(
                status="running",
                started_at=started_at,
                input_hash=identity,
                tool_version=__version__,
                result={
                    "method": method,
                    "mineru_version": mineru_version,
                    "upgrade_reason": upgrade_reason,
                },
            )
            workspace.save_job(running_state)
            staging = (
                workspace.parsed_dir
                / f".mineru-staging-{uuid.uuid4().hex}"
            )
            manifest_backup = (
                workspace.manifest_path.read_bytes()
                if workspace.manifest_path.exists()
                else None
            )
            published = False
            try:
                raw_root = staging / "raw"
                api_result = None
                client = self.api_client_factory(token_from_environment())
                api_result = client.parse(
                    workspace.source_pdf,
                    raw_root,
                    data_id=workspace.root.name,
                    checkpoint_path=(
                        workspace.parsed_dir
                        / ".mineru-api-checkpoint.json"
                    ),
                    heartbeat=heartbeat,
                )
                normalized = MineruNormalizer(mineru_version).normalize(
                    raw_root,
                    staging,
                    confirmed,
                    validation.sha256,
                )
                for name in ("source_map.json", "parse_report.json"):
                    path = staging / name
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["method"] = method
                    if name == "parse_report.json":
                        payload["provider"] = provider
                        if api_result is not None:
                            payload["model_version"] = api_result.model_version
                            payload["batch_id"] = api_result.batch_id
                            payload["result_zip_sha256"] = (
                                api_result.result_zip_sha256
                            )
                    atomic_write_json(path, payload)
                report, assets = (
                    MineruArtifactValidator.validate_mineru_artifacts(
                        staging,
                        validation.sha256,
                        method=method,
                        mineru_version=mineru_version,
                    )
                )
                if (
                    assets != normalized.assets
                    or report.status != "parsed_mineru"
                ):
                    raise ValueError("MinerU staging 结构无效")
                staging.replace(target)
                published = True
                self._publish_manifest(workspace, assets)
                result = MineruParseResult(
                    status="parsed_mineru",
                    source_sha256=validation.sha256,
                    mineru_version=mineru_version,
                    method=method,
                    upgrade_reason=upgrade_reason,
                    raw_content_list_sha256=(
                        normalized.raw_content_list_sha256
                    ),
                    assets=assets,
                    cached=False,
                    provider=provider,
                    model_version=(
                        api_result.model_version if api_result else None
                    ),
                    batch_id=api_result.batch_id if api_result else None,
                    result_zip_sha256=(
                        api_result.result_zip_sha256 if api_result else None
                    ),
                )
                self._record_state(
                    workspace,
                    result,
                    identity,
                    started_at,
                    _now(),
                    duration_seconds=round(
                        time.perf_counter() - started_clock,
                        3,
                    ),
                )
                refresh_generation_package_manifest(workspace)
                return result
            except Exception as primary_error:
                raised_error = primary_error
                if published and target.exists():
                    try:
                        shutil.rmtree(target)
                    except OSError as rollback_error:
                        raised_error.add_note(
                            f"remove MinerU publication failed: "
                            f"{rollback_error}"
                        )
                try:
                    self._restore_manifest(workspace, manifest_backup)
                except OSError as rollback_error:
                    raised_error.add_note(
                        f"restore manifest failed: {rollback_error}"
                    )
                try:
                    workspace.save_job(original_state)
                except OSError as rollback_error:
                    raised_error.add_note(
                        f"restore job state failed: {rollback_error}"
                    )
                if raised_error is primary_error:
                    raise
                raise raised_error from primary_error
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _load_cache(
        workspace: PaperWorkspace,
        metadata: PaperMetadata,
        source_sha256: str,
        method: str,
        mineru_version: str,
        identity: str,
        upgrade_reason: str,
    ) -> MineruParseResult | None:
        target = workspace.parsed_dir / "mineru"
        if not target.exists():
            return None
        try:
            report_payload = json.loads(
                (target / "parse_report.json").read_text(encoding="utf-8")
            )
            _report, assets = MineruArtifactValidator.validate_mineru_artifacts(
                target,
                source_sha256,
                method=method,
                mineru_version=mineru_version,
                manifest_path=workspace.manifest_path,
                metadata=metadata,
            )
            stage = workspace.load_job().stages.get("paper_parse_upgrade")
            if stage is None or stage.input_hash != identity:
                raise ValueError("MinerU 缓存 identity 不匹配")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise AgentRequired(
                "mineru_artifact_inconsistent",
                {"paper_id": workspace.root.name},
            ) from error
        return MineruParseResult(
            status="parsed_mineru",
            source_sha256=source_sha256,
            mineru_version=mineru_version,
            method=method,
            upgrade_reason=upgrade_reason,
            raw_content_list_sha256=(
                report_payload["raw_content_list_sha256"]
            ),
            assets=assets,
            cached=True,
            provider=API_CONTRACT_VERSION,
            model_version=DEFAULT_MODEL_VERSION,
        )

    @staticmethod
    def _publish_manifest(
        workspace: PaperWorkspace,
        assets: tuple[AssetRecord, ...],
    ) -> None:
        existing = (
            AssetManifest(workspace.manifest_path).load()
            if workspace.manifest_path.exists()
            else []
        )
        by_id = {asset.asset_id: asset for asset in existing}
        for asset in assets:
            AssetManifest._validate(asset)
            by_id[asset.asset_id] = asset
        atomic_write_json(
            workspace.manifest_path,
            {
                "version": 1,
                "assets": [
                    asset.to_dict()
                    for asset in by_id.values()
                ],
            },
        )

    @staticmethod
    def _restore_manifest(
        workspace: PaperWorkspace,
        backup: bytes | None,
    ) -> None:
        if backup is None:
            workspace.manifest_path.unlink(missing_ok=True)
            return
        restore = workspace.root / f".manifest-{uuid.uuid4().hex}.restore"
        try:
            restore.write_bytes(backup)
            restore.replace(workspace.manifest_path)
        finally:
            restore.unlink(missing_ok=True)

    @staticmethod
    def _record_state(
        workspace: PaperWorkspace,
        result: MineruParseResult,
        identity: str,
        started_at: str,
        finished_at: str,
        *,
        duration_seconds: float = 0.0,
    ) -> None:
        state = workspace.load_job()
        state.status = "parsed_mineru"
        state.error = None
        state.stages["paper_parse_upgrade"] = StageRecord(
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            input_hash=identity,
            tool_version=__version__,
            result={
                "active_parsed_dir": "parsed/mineru",
                "status": result.status,
                "source_sha256": result.source_sha256,
                "mineru_version": result.mineru_version,
                "method": result.method,
                "upgrade_reason": result.upgrade_reason,
                "raw_content_list_sha256": (
                    result.raw_content_list_sha256
                ),
                "duration_seconds": duration_seconds,
                "provider": result.provider,
                "model_version": result.model_version,
                "batch_id": result.batch_id,
                "result_zip_sha256": result.result_zip_sha256,
            },
        )
        workspace.save_job(state)
