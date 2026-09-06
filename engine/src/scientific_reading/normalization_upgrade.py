"""Upgrade unfinished v3 readings from verified raw data, preserving old artifacts."""
from __future__ import annotations

import json
import shutil
import uuid

from .scope import workspace_publication
from .mineru_artifacts import MineruArtifactValidator, active_parsed_root, _resolve_provider_version
from .mineru_models import MINERU_NORMALIZATION_VERSION
from .mineru_normalizer import MineruNormalizer
from .models import PaperMetadata
from .workspace import atomic_write_json


def upgrade_unfinished_normalization(workspace):
    recover_normalization_upgrade(workspace)
    target = active_parsed_root(workspace)
    report_path = target / "parse_report.json"
    if not report_path.is_file():
        return False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    state = workspace.load_job()
    if report.get("version") != "mineru-normalization-v3" or state.stages.get("full_read", None) and state.stages["full_read"].status == "completed":
        return False
    metadata = PaperMetadata.from_dict(json.loads(workspace.metadata_path.read_text(encoding="utf-8")))
    sha, method, parser = report["source_sha256"], report["method"], report["parser_version"]
    MineruArtifactValidator.validate_mineru_artifacts(target, sha, method=method, mineru_version=parser, metadata=metadata, manifest_path=workspace.manifest_path)
    if not target.resolve().is_relative_to(workspace.root.resolve()):
        raise ValueError("normalization_upgrade_path_invalid")
    transaction = workspace.root / (".normalization-upgrade-" + uuid.uuid4().hex)
    staging = transaction / "new"
    backup = transaction / "previous"
    old_plan = workspace.reading_dir / "full"
    transaction.mkdir()
    shutil.copyfile(workspace.job_path, transaction / "previous-job.json")
    atomic_write_json(transaction / "pending.json", {"target": target.relative_to(workspace.root).as_posix()})
    moved_parse = moved_plan = installed = False
    try:
        shutil.copytree(target / "raw", staging / "raw")
        MineruNormalizer(parser).normalize(staging / "raw", staging, metadata, sha)
        for name in ("source_map.json", "parse_report.json"):
            file = staging / name
            payload = json.loads(file.read_text(encoding="utf-8"))
            payload["method"] = method
            if name == "parse_report.json":
                for key in ("provider", "provider_version", "model_version", "batch_id", "result_zip_sha256"):
                    if key in report:
                        payload[key] = report[key]
            atomic_write_json(file, payload)
        MineruArtifactValidator.validate_mineru_artifacts(staging, sha, method=method, mineru_version=parser, metadata=metadata)
        with workspace_publication(workspace):
            target.rename(backup)
            moved_parse = True
            if old_plan.exists():
                old_plan.rename(transaction / "previous-full")
                moved_plan = True
            staging.rename(target)
            installed = True
            from .mineru_service import _cache_identity
            stage = state.stages["paper_parse_upgrade"]
            stage.input_hash = _cache_identity(sha, method, report["provider"], _resolve_provider_version(report, parser))
            stage.result["normalization_version"] = MINERU_NORMALIZATION_VERSION
            workspace.save_job(state)
        from .package_manifest import refresh_generation_package_manifest
        refresh_generation_package_manifest(workspace)
        (transaction / "pending.json").rename(transaction / "completed.json")
        return True
    except Exception:
        with workspace_publication(workspace):
            if installed:
                target.rename(transaction / "failed-new")
            if moved_parse:
                backup.rename(target)
            if moved_plan:
                (transaction / "previous-full").rename(old_plan)
            shutil.copyfile(transaction / "previous-job.json", workspace.job_path)
            (transaction / "pending.json").rename(transaction / "rolled-back.json")
        from .package_manifest import refresh_generation_package_manifest
        refresh_generation_package_manifest(workspace)
        raise


def recover_normalization_upgrade(workspace):
    for transaction in workspace.root.glob(".normalization-upgrade-*"):
        pending = transaction / "pending.json"
        if not pending.is_file():
            continue
        recorded = json.loads(pending.read_text(encoding="utf-8"))
        target = (workspace.root / recorded["target"]).resolve()
        if target != (workspace.parsed_dir / "mineru").resolve() or not transaction.resolve().is_relative_to(workspace.root.resolve()):
            raise ValueError("normalization_upgrade_path_invalid")
        with workspace_publication(workspace):
            if (transaction / "previous").exists():
                if target.exists():
                    target.rename(transaction / ("interrupted-new-" + uuid.uuid4().hex))
                (transaction / "previous").rename(target)
            old_plan = workspace.reading_dir / "full"
            if (transaction / "previous-full").exists():
                if old_plan.exists():
                    raise ValueError("normalization_upgrade_plan_conflict")
                (transaction / "previous-full").rename(old_plan)
            shutil.copyfile(transaction / "previous-job.json", workspace.job_path)
            pending.rename(transaction / "rolled-back.json")
        from .package_manifest import refresh_generation_package_manifest
        refresh_generation_package_manifest(workspace)
