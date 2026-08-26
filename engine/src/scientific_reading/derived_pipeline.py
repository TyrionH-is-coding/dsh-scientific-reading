"""持久、串行的文献派生阶段编排。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .background_launcher import BackgroundLaunchError, BackgroundLauncher, LaunchResult
from .background_models import BackgroundRequest
from .derived_updates import FeishuAutoSyncPolicy
from .feishu_builder import FeishuPayloadBuilder
from .feishu_service import feishu_sync_input_hash
from .models import PaperMetadata
from .workspace import PaperWorkspace


def _hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class DerivedPipeline:
    """仅在前一阶段完成后排入下一阶段；每个 job 仍由现有 SQLite/JSON store 持久化。"""

    def __init__(self, data_root: Path, *, launcher=None) -> None:
        self.data_root = Path(data_root).resolve()
        self.launcher = launcher or BackgroundLauncher(self.data_root)

    @staticmethod
    def metadata_request(
        data_root: Path,
        metadata: PaperMetadata,
        *,
        paper_id: str | None = None,
        feishu_config_path: Path | None = None,
    ) -> BackgroundRequest:
        payload: dict[str, Any] = {
            "data_root": str(Path(data_root).resolve()),
            "metadata": metadata.to_dict(),
            "derived_pipeline": True,
        }
        if feishu_config_path is not None:
            payload["feishu_config_path"] = str(feishu_config_path.resolve())
        workspace = (
            PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
            if paper_id is not None
            else PaperWorkspace.create(data_root, metadata)
        )
        return BackgroundRequest(
            workspace.root.name,
            "metadata_enrichment",
            _hash(payload),
            payload,
        )

    def enqueue(self, request: BackgroundRequest) -> LaunchResult:
        try:
            launched = self.launcher.enqueue(request)
        except BackgroundLaunchError as error:
            self._record_active_job(
                request.paper_id,
                error.job_id or self._stable_job_id(request),
                error=str(error),
            )
            raise
        self._record_active_job(request.paper_id, launched.job_id)
        return launched

    @staticmethod
    def _stable_job_id(request: BackgroundRequest) -> str:
        from .background_store import stable_job_id

        return stable_job_id(request)

    def _record_active_job(
        self, paper_id: str, job_id: str, *, error: str | None = None
    ) -> None:
        from .library_service import LibraryService

        library = LibraryService(self.data_root)
        try:
            library.update_active_job(
                paper_id,
                job_id,
                error=error,
                preserve_existing_error=error is None,
            )
        finally:
            library.close()

    def advance(
        self,
        request: BackgroundRequest,
        result: dict[str, Any],
        *,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        if request.payload.get("derived_pipeline") is not True:
            return {}
        latest = self._latest_metadata(request)
        if request.target_stage == "metadata_enrichment":
            return {"abstract_read_job_id": self._enqueue_abstract(request, latest, parent_job_id).job_id}
        if request.target_stage == "abstract_read":
            return {"xlsx_snapshot_job_id": self._enqueue_xlsx(request, latest, parent_job_id).job_id}
        if request.target_stage == "xlsx_snapshot":
            child = self._enqueue_feishu(request, latest, parent_job_id)
            return {"feishu_sync_job_id": child.job_id} if child is not None else {"feishu": "disabled"}
        return {}

    def _latest_metadata(self, request: BackgroundRequest) -> PaperMetadata:
        original = PaperMetadata.from_dict(request.payload["metadata"])
        workspace = PaperWorkspace.create_for_paper_id(
            self.data_root, request.paper_id, original
        )
        return PaperMetadata.from_dict(
            json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        )

    def _child_payload(
        self,
        request: BackgroundRequest,
        metadata: PaperMetadata,
        parent_job_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "data_root": str(self.data_root),
            "metadata": metadata.to_dict(),
            "derived_pipeline": True,
            "pipeline_parent_job_id": parent_job_id or request.paper_id,
        }
        config_path = request.payload.get("feishu_config_path")
        if isinstance(config_path, str) and config_path:
            payload["feishu_config_path"] = config_path
        return payload

    def _enqueue_abstract(self, parent: BackgroundRequest, metadata: PaperMetadata, parent_job_id: str | None) -> LaunchResult:
        payload = self._child_payload(parent, metadata, parent_job_id)
        request = BackgroundRequest(parent.paper_id, "abstract_read", _hash(payload), payload)
        return self.enqueue(request)

    def _enqueue_xlsx(self, parent: BackgroundRequest, metadata: PaperMetadata, parent_job_id: str | None) -> LaunchResult:
        payload = self._child_payload(parent, metadata, parent_job_id)
        request = BackgroundRequest(parent.paper_id, "xlsx_snapshot", _hash(payload), payload)
        return self.enqueue(request)

    def _enqueue_feishu(
        self, parent: BackgroundRequest, metadata: PaperMetadata, parent_job_id: str | None
    ) -> LaunchResult | None:
        policy = FeishuAutoSyncPolicy(self.data_root)
        active = policy.active_config()
        if active is None:
            return None
        config_path, config, revision = active
        payload = self._child_payload(parent, metadata, parent_job_id)
        workspace = PaperWorkspace.create_for_paper_id(
            self.data_root, parent.paper_id, metadata
        )
        sync_payload = FeishuPayloadBuilder().build(workspace, config)
        child_payload = {
            **payload,
            "config": config.to_dict(),
            "payload": sync_payload.to_dict(),
            "write_mode": "configured_auto",
            "activation_revision": revision,
            "feishu_config_path": str(config_path),
        }
        request = BackgroundRequest(
            parent.paper_id,
            "feishu_sync",
            feishu_sync_input_hash(config, sync_payload),
            child_payload,
        )
        return self.enqueue(request)
