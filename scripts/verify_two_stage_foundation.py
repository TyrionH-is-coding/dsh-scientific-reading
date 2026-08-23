"""Phase 1 主库与轻量入库的完全离线集成验收。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    # The verifier never starts, restarts, injects, or writes the persistent 3080.
    return {"status": "skipped", "reason": "3080_health_probe_not_requested"}


def _assert_fake_config(config):
    from urllib.parse import urlsplit

    parsed = urlsplit(config.base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "fake.local"}:
        raise ValueError("feishu_base_url_must_be_localhost_or_fake")


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
        unchanged = before == after
        return _emit({"status": "passed" if all(value == "passed" for value in steps.values()) and unchanged else "failed", "steps": steps, "profile_3080_unchanged": unchanged, "runtime": {"before": before, "after": after}, "external_writes": external_writes, "data_root": "temporary_cleaned", "known_limits": ["未启动真实持久 Profile/3080；竞态以 Abstract source revision stale guard 验证"]})
    except Exception as error:
        return _emit({"status": "failed", "steps": steps, "error": str(error), "profile_3080_unchanged": False, "external_writes": external_writes})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _emit(value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    return 0 if value.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
