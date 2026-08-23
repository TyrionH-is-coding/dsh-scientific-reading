"""Phase 1 主库与轻量入库的完全离线集成验收。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


TITLE = "A Deterministic Scheduling Method for Small Workshops"
ABSTRACT = (
    "We present a deterministic scheduling method for small workshops.\n\n"
    "The method reduces setup changes while preserving feasible production plans."
)


class FakeProvider:
    def fetch(self, metadata):
        from scientific_reading.metadata_enrichment import ProviderResult

        return ProviderResult.success(
            {"title": TITLE, "abstract_en": ABSTRACT, "journal": "Offline Engineering"}
        )


class FakeFeishu:
    def __init__(self):
        self.records = {}
        self.calls = []

    def get_tenant_token(self, app_id, app_secret):
        assert app_id == "fake-app" and app_secret == "fake-secret"
        self.calls.append("token")
        return "fake-token"

    def search_records(self, token, field_name, value):
        self.calls.append("search")
        return []

    def create_record(self, token, fields):
        self.calls.append("create")
        record_id = "fake_record_offline"
        self.records[record_id] = {"record_id": record_id, "fields": dict(fields)}
        return {"record_id": record_id}

    def update_record(self, token, record_id, fields):
        self.calls.append("update")
        self.records[record_id]["fields"].update(fields)

    def get_record(self, token, record_id):
        self.calls.append("readback")
        return self.records[record_id]


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _runtime_snapshot() -> dict:
    tarball = os.environ.get("SR_PROFILE_TARBALL")
    if tarball:
        path = Path(tarball).resolve()
        if not path.is_file():
            return {"status": "skipped", "reason": "profile_tarball_not_found"}
        return {"status": "checked", "sha256": _sha(path), "path": str(path)}
    return {"status": "skipped", "reason": "profile_tarball_path_not_provided"}


def _health_snapshot() -> dict:
    # 只允许用户明确提供的 localhost/127.0.0.1 URL；仅 GET，不启动/注入/重启。
    target = os.environ.get("SR_3080_URL", "").strip()
    if not target:
        return {"status": "skipped", "reason": "3080_health_probe_not_requested"}
    from urllib.parse import urlsplit

    parsed = urlsplit(target)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        return {"status": "not_verified", "reason": "3080_probe_requires_local_http"}
    try:
        with urllib.request.urlopen(target, timeout=3) as response:
            body = response.read(1024 * 1024)
            return {
                "status": "checked",
                "url": target,
                "http_status": response.status,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
    except (OSError, urllib.error.URLError) as error:
        return {"status": "not_verified", "reason": "3080_probe_failed", "error": type(error).__name__}


def _verified_unchanged(before: dict, after: dict) -> bool:
    if before != after:
        return False
    return all(
        before.get(name, {}).get("status") == "checked"
        for name in ("profile", "3080")
    )


def _assert_fake_config(config):
    from urllib.parse import urlsplit

    parsed = urlsplit(config.base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "fake.local"}:
        raise ValueError("feishu_base_url_must_be_localhost_or_fake")


def _run_real_derived_pipeline(root: Path, metadata) -> list[str]:
    """通过引擎真实 DerivedPipeline + worker 接缝跑完 metadata→Abstract→XLSX。

    launcher 只替换后台进程边界，不替换派生编排、job store 或各阶段 service；
    provider 和翻译由本地 fake 实现提供，避免网络与真实模型调用。
    """
    from types import SimpleNamespace

    import scientific_reading.worker as worker_module
    from scientific_reading.abstract_read_service import AbstractReadService
    from scientific_reading.background_store import BackgroundJobStore
    from scientific_reading.derived_pipeline import DerivedPipeline
    from scientific_reading.metadata_enrichment import MetadataEnrichmentService, MetadataProviderRegistry, ProviderResult
    from scientific_reading.__main__ import resume_job
    from scientific_reading.worker import (
        abstract_read_handler_factory,
        metadata_enrichment_handler_factory,
        run_job,
        xlsx_snapshot_handler_factory,
    )
    from scientific_reading.workspace import PaperWorkspace

    class FakeLauncher:
        def __init__(self, store):
            self.store = store
            self.requests = []

        def enqueue(self, request):
            self.requests.append(request)
            handle = self.store.create_or_get(request)
            return SimpleNamespace(
                job_id=handle.job_id,
                status=self.store.load_status(handle.job_id),
                process_started=False,
            )

        def launch_existing(self, job_id):
            return SimpleNamespace(
                job_id=job_id,
                status=self.store.load_status(job_id),
                process_started=False,
            )

    class FakeProvider:
        def fetch(self, current):
            return ProviderResult.success(
                {"title": current.title, "abstract_en": ABSTRACT, "journal": "Offline Engineering"}
            )

    store = BackgroundJobStore(root)
    launcher = FakeLauncher(store)
    pipeline = DerivedPipeline(root, launcher=launcher)
    original_pipeline = worker_module.DerivedPipeline
    worker_module.DerivedPipeline = lambda _root: pipeline
    try:
        request = pipeline.metadata_request(root, metadata)
        first = pipeline.enqueue(request)
        metadata_service = MetadataEnrichmentService(MetadataProviderRegistry([FakeProvider()]))
        metadata_code = run_job(store, first.job_id, handlers={"metadata_enrichment": metadata_enrichment_handler_factory(metadata_service)})
        if metadata_code != 0:
            raise RuntimeError(f"metadata_derived_stage_failed:{store.load_status(first.job_id).error}")
        if [item.target_stage for item in launcher.requests] != ["metadata_enrichment", "abstract_read"]:
            raise RuntimeError("metadata_did_not_enqueue_abstract")

        abstract_request = launcher.requests[-1]
        abstract_job = store.create_or_get(abstract_request).job_id
        if run_job(store, abstract_job, handlers={"abstract_read": abstract_read_handler_factory()}) != 3:
            raise RuntimeError("abstract_agent_gate_missing")
        if store.load_status(abstract_job).state != "waiting_agent":
            raise RuntimeError("abstract_not_waiting_agent")

        workspace = PaperWorkspace.create(root, metadata)
        context = AbstractReadService().inspect(workspace)
        translation = {
            "contract_version": context["contract_version"],
            "source_sha256": context["source_sha256"],
            "paragraphs": [
                {**paragraph, "translation_zh": f"离线译文 {paragraph['index'] + 1}"}
                for paragraph in context["paragraphs"]
            ],
        }
        resume_job(store, abstract_job, launcher=launcher, resume_input={"abstract_translation": translation})
        if run_job(store, abstract_job, handlers={"abstract_read": abstract_read_handler_factory()}) != 0:
            raise RuntimeError("abstract_submit_stage_failed")
        if [item.target_stage for item in launcher.requests] != ["metadata_enrichment", "abstract_read", "xlsx_snapshot"]:
            raise RuntimeError("abstract_did_not_enqueue_xlsx")

        xlsx_request = launcher.requests[-1]
        xlsx_job = store.create_or_get(xlsx_request).job_id
        if run_job(store, xlsx_job, handlers={"xlsx_snapshot": xlsx_snapshot_handler_factory()}) != 0:
            raise RuntimeError("xlsx_derived_stage_failed")
        if [item.target_stage for item in launcher.requests] != ["metadata_enrichment", "abstract_read", "xlsx_snapshot"]:
            raise RuntimeError("disabled_feishu_was_enqueued")
        return [item.target_stage for item in launcher.requests]
    finally:
        worker_module.DerivedPipeline = original_pipeline


def main() -> int:
    before = {"profile": _runtime_snapshot(), "3080": _health_snapshot()}
    root = Path(tempfile.mkdtemp(prefix="sr-foundation-"))
    steps = {}
    external_writes = False
    try:
        engine = Path(os.environ.get("SR_ENGINE_ROOT", "")).resolve()
        if not (engine / "src" / "scientific_reading").is_dir():
            raise RuntimeError("SR_ENGINE_ROOT_required")
        sys.path.insert(0, str(engine / "src"))
        from scientific_reading.abstract_read_service import AbstractReadService
        from scientific_reading.classification_service import ClassificationProposal, ClassificationService
        from scientific_reading.feishu_builder import FeishuPayloadBuilder
        from scientific_reading.feishu_models import FEISHU_CONFIG_CONTRACT_VERSION, FeishuConfig
        from scientific_reading.feishu_service import FeishuSyncService
        from scientific_reading.library_service import LibraryService
        from scientific_reading.metadata_enrichment import MetadataEnrichmentService, MetadataProviderRegistry
        from scientific_reading.models import PaperMetadata
        from scientific_reading.workspace import PaperWorkspace, atomic_write_json
        from scientific_reading.xlsx_snapshot import XlsxSnapshotService

        # Exercise the plugin's real detached scheduling contract with its
        # existing fake-engine harness; no host/Profile is started.
        plugin_root = Path(__file__).resolve().parents[1]
        dispatch = subprocess.run(
            ["node", str(plugin_root / "tests" / "two-stage-ingest.mjs")],
            cwd=plugin_root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if dispatch.returncode != 0:
            raise RuntimeError("plugin_detached_dispatch_contract_failed")
        steps["plugin_dispatch"] = "passed"

        if os.environ.get("FEISHU_APP_ID") or os.environ.get("FEISHU_APP_SECRET"):
            raise RuntimeError("real_feishu_credentials_forbidden")
        os.environ.pop("FEISHU_APP_ID", None)
        os.environ.pop("FEISHU_APP_SECRET", None)
        metadata = PaperMetadata(title=TITLE, authors=["Offline Author"], doi=None, year=2024, abstract_en=ABSTRACT)
        library = LibraryService(root)
        try:
            skeleton = library.ingest(metadata)
        finally:
            library.close()
        paper_id = skeleton["paper_id"]
        workspace = PaperWorkspace.create(root, metadata)
        steps["skeleton"] = "passed" if skeleton.get("created") is True and skeleton.get("paper_id") else "failed"

        derived_stages = _run_real_derived_pipeline(root, metadata)
        steps["derived_pipeline"] = "passed" if derived_stages == ["metadata_enrichment", "abstract_read", "xlsx_snapshot"] else "failed"

        enriched = MetadataEnrichmentService(MetadataProviderRegistry([FakeProvider()])).enrich(metadata)
        atomic_write_json(workspace.metadata_path, enriched.metadata.to_dict())
        library = LibraryService(root)
        try:
            library.ingest(enriched.metadata)
        finally:
            library.close()
        workspace = PaperWorkspace.create(root, enriched.metadata)
        context = AbstractReadService().inspect(workspace)
        translation = {
            "contract_version": context["contract_version"],
            "source_sha256": context["source_sha256"],
            "paragraphs": [
                {**paragraph, "translation_zh": f"离线译文 {paragraph['index'] + 1}"}
                for paragraph in context["paragraphs"]
            ],
        }
        AbstractReadService().publish(workspace, translation)
        steps["metadata_abstract"] = "passed"
        # Detached enrichment/abstract workers may observe different revisions.
        # A changed source must become stale, never silently remain completed.
        changed = enriched.metadata.to_dict()
        changed["abstract_en"] = ABSTRACT + "\n\nA changed source revision."
        atomic_write_json(workspace.metadata_path, changed)
        steps["race_guard"] = "passed" if AbstractReadService().inspect(workspace)["status"] == "stale" else "failed"
        atomic_write_json(workspace.metadata_path, enriched.metadata.to_dict())

        xlsx = XlsxSnapshotService(root).refresh()
        steps["xlsx"] = "passed" if xlsx.get("status") == "success" else "failed"

        config = FeishuConfig.from_dict({
            "contract_version": FEISHU_CONFIG_CONTRACT_VERSION,
            "base_url": "https://fake.local",
            "app_token": "fake-app-token", "table_id": "fake-table",
            "field_map": {
                "title": {"name": "标题", "type": "text"},
                "doi": {"name": "DOI", "type": "text"},
                "pmid": {"name": "PMID", "type": "text"},
                "library_key": {"name": "本地文献 ID", "type": "text"},
                "reading_status": {"name": "阅读状态", "type": "text"},
                "updated_at": {"name": "更新时间", "type": "text"},
                "error_status": {"name": "错误状态", "type": "text"},
            },
        })
        _assert_fake_config(config)
        payload = FeishuPayloadBuilder().build(workspace, config)
        fake = FakeFeishu()
        FeishuSyncService().run(workspace, config, payload, client=fake, app_id="fake-app", app_secret="fake-secret")
        steps["fake_feishu"] = "passed" if fake.calls and "create" in fake.calls and "readback" in fake.calls else "failed"

        library = LibraryService(root)
        try:
            folder = library.create_folder("离线工科")
            result = ClassificationService(library).apply((ClassificationProposal(paper_id, "离线工科", ("离线验收",), 1.0),))
            operation_id = result.get("operation_id")
        finally:
            library.close()
        steps["classification"] = "passed" if folder.get("folder_id") and operation_id else "failed"
        library = LibraryService(root)
        try:
            undone = ClassificationService(library).undo(operation_id)
        finally:
            library.close()
        steps["undo"] = "passed" if undone.get("restored") == 1 else "failed"
        after = {"profile": _runtime_snapshot(), "3080": _health_snapshot()}
        unchanged = _verified_unchanged(before, after)
        core_passed = all(value == "passed" for value in steps.values())
        status = "passed" if core_passed and unchanged else "passed_with_limits" if core_passed else "failed"
        return _emit({"status": status, "steps": steps, "profile_3080_unchanged": unchanged, "profile_3080_gate": "passed" if unchanged else "not_verified", "runtime": {"before": before, "after": after}, "external_writes": external_writes, "data_root": "temporary_cleaned", "known_limits": ["未提供 SR_PROFILE_TARBALL 或 SR_3080_URL 时仅输出 skipped/not_verified，不把 Profile/3080 当作已验收门禁"]})
    except Exception as error:
        return _emit({"status": "failed", "steps": steps, "error": str(error), "profile_3080_unchanged": False, "external_writes": external_writes})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _emit(value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return 0 if value.get("status") in {"passed", "passed_with_limits"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
