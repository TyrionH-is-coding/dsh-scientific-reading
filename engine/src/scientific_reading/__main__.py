from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .background_launcher import BackgroundLaunchError, BackgroundLauncher
from .background_models import BackgroundRequest
from .background_store import (
    BackgroundJobStore,
    JobClaimUnavailable,
    stable_job_id,
    windows_pid_is_alive,
)
from .derived_pipeline import DerivedPipeline
from .derived_updates import FeishuAutoSyncPolicy
from .export_service import ExportService
from .feishu_builder import FeishuPayloadBuilder, load_feishu_config
from .feishu_service import feishu_sync_input_hash
from .foreground import ForegroundTimer
from .models import PaperMetadata
from .workspace import PaperWorkspace, atomic_write_json

def _load_metadata(path: Path) -> PaperMetadata:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return PaperMetadata.from_dict(payload)

def _load_derived_metadata(args) -> PaperMetadata:
    if args.paper_id:
        from .library_service import LibraryService

        library = LibraryService(args.data_root)
        try:
            metadata = library.canonical_metadata(args.paper_id)
        finally:
            library.close()
        workspace = PaperWorkspace.create_for_paper_id(
            args.data_root, args.paper_id, metadata
        )
        atomic_write_json(workspace.metadata_path, metadata.to_dict())
        return metadata
    if args.metadata is None:
        raise ValueError("metadata_or_paper_id_required")
    return _load_metadata(args.metadata)

def _record_derived_job(
    data_root: Path,
    paper_id: str,
    job_id: str,
    *,
    error: str | None = None,
) -> None:
    from .library_service import LibraryService

    library = LibraryService(data_root)
    try:
        library.update_active_job(paper_id, job_id, error=error)
    finally:
        library.close()

def _build_background_launcher(data_root: Path) -> BackgroundLauncher:
    return BackgroundLauncher(data_root)

def _job_foreground(store: BackgroundJobStore, job_id: str, timer: ForegroundTimer):
    status = store.load_status(job_id)
    request = store.load_request(job_id)
    detail = status.to_dict()
    if request.target_stage == "full_read_pipeline":
        from .reading_pipeline import ReadingPipeline

        try:
            pipeline = ReadingPipeline(store.data_root)._load(
                job_id, expected_paper_id=request.paper_id
            )
            detail["stage_timings"] = pipeline.stage_timings
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    next_action = "done"
    agent_required = False
    exit_code = 0
    if status.state in {"queued", "running"}:
        next_action = "poll"
    elif status.state == "waiting_agent":
        next_action = "agent"
        agent_required = True
        exit_code = 3
    elif status.state == "waiting_user":
        next_action = "user"
        exit_code = 2
    elif status.state in {"failed", "interrupted"}:
        exit_code = 4
    result = timer.finish(
        paper_id=request.paper_id,
        status=status.state,
        job_id=job_id,
        agent_required=agent_required,
        next_action=next_action,
        detail=detail,
    )
    return result, exit_code

def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        return windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True

def resume_job(
    store: BackgroundJobStore,
    job_id: str,
    *,
    launcher,
    resume_input: dict | None = None,
    now: datetime | None = None,
    stale_after_seconds: float = 60.0,
):
    with store.claim(job_id, "resume"):
        status = store.load_status(job_id)
        if status.state == "running":
            reference = status.heartbeat_at or status.updated_at
            heartbeat_at = datetime.fromisoformat(reference)
            current = now or datetime.now(timezone.utc)
            if (current - heartbeat_at).total_seconds() <= stale_after_seconds:
                raise ValueError("running 任务心跳尚未过期")
            if _pid_is_alive(status.pid):
                raise ValueError("running 任务进程仍存活，拒绝并行恢复")
            store.transition(job_id, "interrupted", error="stale_heartbeat")
            status = store.load_status(job_id)
        if status.state not in {
            "failed",
            "interrupted",
            "waiting_agent",
            "waiting_user",
        }:
            raise ValueError(f"任务状态 {status.state} 不允许恢复")
        values = resume_input or {}
        translation_reasons = {
            "translate_full_read",
            "full_translation_revision_required",
        }
        review_reasons = {
            "review_full_read",
            "full_review_revision_required",
        }
        if (
            status.state == "waiting_agent"
            and status.reason_code in translation_reasons
            and "full_translation" not in values
        ):
            raise ValueError("恢复全文翻译任务必须提交 full_translation")
        if "full_translation" in values and not (
            status.state == "waiting_agent"
            and status.reason_code in translation_reasons
        ):
            raise ValueError("当前任务不接受 full_translation 输入")
        if (
            status.state == "waiting_agent"
            and status.reason_code in review_reasons
            and "full_review" not in values
        ):
            raise ValueError("恢复全文复核任务必须提交 full_review")
        if "full_review" in values and not (
            status.state == "waiting_agent"
            and status.reason_code in review_reasons
        ):
            raise ValueError("当前任务不接受 full_review 输入")
        if (
            status.state == "waiting_user"
            and status.reason_code == "write_confirmation_required"
            and values.get("confirm_write") is not True
        ):
            raise ValueError("恢复该任务必须显式提供 confirm_write")
        if (
            status.state == "waiting_user"
            and status.reason_code == "choose_pdf_source"
        ):
            mode = values.get("mode")
            if mode == "chrome" and values.get("local_pdf") is None:
                pass
            elif mode == "local-file":
                local_pdf = Path(values.get("local_pdf", ""))
                if not local_pdf.is_absolute() or not local_pdf.is_file():
                    raise ValueError("恢复该任务必须提供绝对本地 PDF")
            else:
                raise ValueError("恢复该任务必须选择 Chrome 或本地 PDF")
        elif (
            status.state == "waiting_user"
            and status.reason_code == "authorize_chrome"
        ):
            local_value = values.get("local_pdf")
            local_pdf = (
                Path(local_value)
                if isinstance(local_value, (str, os.PathLike))
                else Path("")
            )
            if (
                values.get("mode") != "local-file"
                or not local_pdf.is_absolute()
                or not local_pdf.is_file()
            ):
                raise ValueError("当前任务不接受该 PDF 来源输入")
        elif "mode" in values or "local_pdf" in values:
            raise ValueError("当前任务不接受 PDF 来源输入")
        if values:
            store.save_resume_input(job_id, values)
        store.transition(job_id, "queued")
        return launcher.launch_existing(job_id)

def _run_library_ingest(args, metadata: PaperMetadata, *, deprecated: bool) -> int:
    from .library_service import LibraryService

    service = None
    try:
        try:
            service = LibraryService(args.data_root)
        except (OSError, sqlite3.Error):
            return _library_ingest_error(
                "library_unavailable", "library_initialization_failed"
            )
        try:
            result = (
                service.check(metadata)
                if deprecated and getattr(args, "check", False)
                else service.ingest(metadata)
            )
        except ValueError:
            return _library_ingest_error(
                "invalid_metadata", "metadata_validation_failed"
            )
    finally:
        if service is not None:
            service.close()
    if deprecated:
        result["deprecation"] = "library-ensure is deprecated; use library-ingest"
    print(json.dumps(result, ensure_ascii=False))
    return 0

def _submit_abstract_read(args, timer: ForegroundTimer) -> int:
    store = BackgroundJobStore(args.data_root); request = store.load_request(args.job_id)
    try:
        status = store.load_status(args.job_id)
        if request.target_stage != "abstract_read" or status.state != "waiting_agent" or status.reason_code not in {"translate_abstract", "abstract_translation_revision_required"}:
            raise ValueError("abstract_read_agent_gate_required")
        if str(args.input) == "-":
            value = json.load(sys.stdin)
        else:
            if not args.input.is_absolute() or not args.input.is_file():
                raise ValueError("absolute_abstract_read_input_required")
            value = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(value, dict): raise ValueError("abstract_read_input_must_be_object")
        resume_job(store, args.job_id, launcher=_build_background_launcher(args.data_root), resume_input={"abstract_translation": value})
    except (BackgroundLaunchError, JobClaimUnavailable, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        result = timer.finish(paper_id=request.paper_id, status="failed", job_id=args.job_id, agent_required=False, next_action="done", detail={"error": str(error)})
        print(json.dumps(result.to_dict(), ensure_ascii=False)); return 4
    print(json.dumps(timer.finish(paper_id=request.paper_id, status="queued", job_id=args.job_id, agent_required=False, next_action="poll", detail={}).to_dict(), ensure_ascii=False)); return 0

def _library_ingest_error(code: str, detail: str) -> int:
    print(
        json.dumps(
            {"status": "failed", "error": {"code": code, "detail": detail}},
            ensure_ascii=False,
        )
    )
    return 2

def _run_full_read_pipeline(args) -> int:
    from .reading_pipeline import ReadingPipeline
    from .background_launcher import BackgroundLauncher

    try:
        pipeline = ReadingPipeline(args.data_root)
        store = pipeline.job_store
        if args.command == "full-read-pipeline-start":
            state = pipeline.start(args.paper_id, args.provider_profile)
            status = store.load_status(state.parent_job_id)
            if status.state in {"queued", "failed", "interrupted"}:
                if status.state in {"failed", "interrupted"} and not store.handle(state.parent_job_id).resume_path.exists():
                    store.save_resume_input(state.parent_job_id, {})
                BackgroundLauncher(args.data_root).launch_existing(state.parent_job_id)
        else:
            with store.claim(args.job_id, "resume"):
                supplied = {}
                if args.input is not None:
                    if str(args.input) == "-":
                        supplied = json.load(sys.stdin)
                    elif not args.input.is_absolute() or not args.input.is_file():
                        raise ValueError("absolute_pipeline_input_required")
                    else:
                        supplied = json.loads(args.input.read_text(encoding="utf-8"))
                    if not isinstance(supplied, dict):
                        raise ValueError("pipeline_input_must_be_object")
                status = store.load_status(args.job_id)
                if status.state not in {"waiting_user", "waiting_agent", "failed", "interrupted"}:
                    raise ValueError("full_read_pipeline_gate_required")
                if status.state in {"failed", "interrupted"} and supplied:
                    raise ValueError("terminal_resume_input_invalid")
                supplied = _validate_full_read_resume(status, supplied)
                store.save_resume_input(args.job_id, supplied)
                (store.handle(args.job_id).root / "launch.json").unlink(missing_ok=True)
                store.transition(args.job_id, "queued")
                BackgroundLauncher(args.data_root).launch_existing(args.job_id)
                state = pipeline.inspect(args.job_id)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 4
    print(json.dumps(state.to_dict(), ensure_ascii=False))
    return 0

def _run_full_read_pdf_attach_resume(args) -> int:
    from .background_launcher import BackgroundLauncher
    from .pdf_acquisition import TrustedPdfAcquisitionService

    store = BackgroundJobStore(args.data_root)
    try:
        with store.claim(args.job_id, "resume"):
            request = store.load_request(args.job_id)
            status = store.load_status(args.job_id)
            if request.target_stage != "full_read_pipeline" or request.paper_id != args.paper_id:
                raise ValueError("full_read_parent_mismatch")
            if status.state != "waiting_user" or status.reason_code != "pdf_required":
                raise ValueError("pdf_gate_required")
            result = TrustedPdfAcquisitionService(args.data_root).attach_local(args.paper_id, args.pdf)
            store.save_resume_input(args.job_id, {"pdf_attached": True})
            (store.handle(args.job_id).root / "launch.json").unlink(missing_ok=True)
            store.transition(args.job_id, "queued")
            BackgroundLauncher(args.data_root).launch_existing(args.job_id)
        print(json.dumps({
            "paper_id": args.paper_id,
            "parent_job_id": args.job_id,
            "status": "queued",
            "sha256": result.sha256,
            "page_count": result.page_count,
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, JobClaimUnavailable) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 4

def _validated_artifact(data_root: Path, paper_id: str, rel_path: str, kind: str, expected_source_sha256: str | None = None, *, allow_audited_root: bool = False) -> dict:
    import re

    paper_root = (Path(data_root).resolve() / "papers" / paper_id).resolve()
    normalized = rel_path.replace("\\", "/")
    allowed = (
        re.fullmatch(r"generations/[0-9a-f]{16}/reading/reader\.html", normalized)
        or re.fullmatch(r"generations/[0-9a-f]{16}/output/reader_full\.html", normalized)
        or (allow_audited_root and normalized == "reader_full.html")
    ) if kind == "reader" else re.fullmatch(r"generations/[0-9a-f]{16}/exports", normalized)
    candidate = paper_root / normalized
    try:
        relative_parts = candidate.relative_to(paper_root).parts
    except ValueError:
        relative_parts = ()
    current = paper_root
    has_symlink = False
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            has_symlink = True
            break
    path = candidate.resolve()
    if not allowed or not relative_parts or has_symlink or not path.is_relative_to(paper_root) or not path.exists():
        raise ValueError("artifact_invalid")
    manifest_path = path.with_name("reader-manifest.json") if kind == "reader" else path / "manifest.json"
    if kind == "reader" and (normalized.endswith("/output/reader_full.html") or normalized == "reader_full.html"):
        result = {
            "paper_id": paper_id,
            "kind": kind,
            "rel_path": normalized,
            "legacy": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if normalized == "reader_full.html":
            result["legacy_audited"] = True
        return result
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("artifact_invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if kind == "reader":
        from .migration_audit import validate_reader_manifest_shape

        if not validate_reader_manifest_shape(manifest):
            raise ValueError("artifact_invalid")
        if manifest.get("paper_id") != paper_id or manifest.get("source_pdf_sha256") != expected_source_sha256 or hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get("reader_sha256"):
            raise ValueError("artifact_invalid")
    else:
        from .export_service import ExportService

        if set(manifest) != {"contract", "paper_id", "source_pdf_sha256", "assets"} or manifest.get("contract") != "asset-export-v1" or manifest.get("paper_id") != paper_id or manifest.get("source_pdf_sha256") != expected_source_sha256 or not isinstance(manifest.get("assets"), list):
            raise ValueError("artifact_invalid")
        for row in manifest["assets"]:
            if not isinstance(row, dict):
                raise ValueError("artifact_invalid")
            required_row = {"asset_id", "kind", "page", "source_index", "source_path", "source_sha256", "export_path", "export_sha256", "caption", "warnings"}
            optional_row = {"structured_source_path", "structured_source_sha256", "csv_path", "csv_sha256"}
            if not required_row.issubset(row) or not set(row).issubset(required_row | optional_row) or (("csv_path" in row) != ("csv_sha256" in row)):
                raise ValueError("artifact_invalid")
            for path_key in ("export_path", "csv_path"):
                relative = row.get(path_key)
                if relative is None:
                    continue
                expected_pattern = r"(?:figures|tables)/[A-Za-z0-9_.-]+\.png" if path_key == "export_path" else r"tables/[A-Za-z0-9_.-]+\.csv"
                hash_key = "export_sha256" if path_key == "export_path" else "csv_sha256"
                if not isinstance(relative, str) or re.fullmatch(expected_pattern, relative) is None or re.fullmatch(r"[0-9a-f]{64}", str(row.get(hash_key, ""))) is None:
                    raise ValueError("artifact_invalid")
                raw_target = path / relative
                target = raw_target.resolve()
                if raw_target.parent.is_symlink() or raw_target.is_symlink() or not target.is_relative_to(path.resolve()) or not target.is_file():
                    raise ValueError("artifact_invalid")
        ExportService._validate(path, manifest)
    return {"paper_id": paper_id, "kind": kind, "rel_path": normalized, "legacy": False, "manifest": manifest}

def _validated_pdf_artifact(
    data_root: Path,
    paper_id: str,
    rel_path: str,
    expected_source_sha256: str,
    *,
    allow_audited_root: bool = False,
) -> dict:
    if (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id) is None
        or ".." in paper_id
        or re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256) is None
    ):
        raise ValueError("artifact_not_ready")
    normalized = rel_path.replace("\\", "/")
    match = re.fullmatch(r"generations/([0-9a-f]{16})/source\.pdf", normalized)
    audited_root = allow_audited_root and normalized == "source.pdf"
    if not audited_root and (
        match is None or match.group(1) != expected_source_sha256[:16]
    ):
        raise ValueError("artifact_not_ready")

    raw_data_root = Path(data_root).absolute()
    paper_root = raw_data_root / "papers" / paper_id
    candidate = paper_root / normalized
    current = raw_data_root
    for part in ("papers", paper_id, *Path(normalized).parts):
        current = current / part
        is_junction = getattr(current, "is_junction", lambda: False)
        if current.is_symlink() or is_junction():
            raise ValueError("artifact_not_ready")

    resolved_data_root = raw_data_root.resolve()
    resolved_paper_root = paper_root.resolve()
    resolved = candidate.resolve()
    if (
        not resolved_paper_root.is_relative_to(resolved_data_root)
        or not resolved.is_relative_to(resolved_paper_root)
        or not resolved.is_file()
        or hashlib.sha256(resolved.read_bytes()).hexdigest()
        != expected_source_sha256
    ):
        raise ValueError("artifact_not_ready")

    database = resolved_data_root / "library.sqlite"
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        attachment = connection.execute(
            "SELECT rel_path, sha256, size FROM attachments WHERE paper_id=?",
            (paper_id,),
        ).fetchone()
    finally:
        connection.close()
    if (
        attachment is None
        or attachment[0] != "source.pdf"
        or attachment[1] != expected_source_sha256
        or attachment[2] != resolved.stat().st_size
    ):
        raise ValueError("artifact_not_ready")
    result = {
        "paper_id": paper_id,
        "kind": "pdf",
        "rel_path": normalized,
        "legacy": audited_root,
        "sha256": expected_source_sha256,
    }
    if audited_root:
        result["legacy_audited"] = True
    return result

def _resolve_artifact(data_root: Path, paper_id: str, kind: str) -> dict:
    from .export_service import ExportService
    from .workspace import PaperWorkspace

    paper_root = Path(data_root).resolve() / "papers" / paper_id
    if kind == "pdf":
        try:
            if (
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id) is None
                or ".." in paper_id
            ):
                raise ValueError("paper_id_invalid")
            metadata = PaperMetadata.from_dict(
                json.loads((paper_root / "metadata.json").read_text(encoding="utf-8"))
            )
            base = PaperWorkspace(paper_root)
            upgrade_stage = base.load_job().stages.get("paper_parse_upgrade")
            if upgrade_stage is None:
                selected = None
                source_sha = None
            else:
                selected, source_sha, *_ = ExportService._active_workspace(base, metadata)
            if selected is None or selected.root == base.root:
                from .migration_audit import audited_legacy_pdf_sha

                audited_sha = audited_legacy_pdf_sha(data_root, paper_id)
                return _validated_pdf_artifact(
                    data_root,
                    paper_id,
                    "source.pdf",
                    audited_sha,
                    allow_audited_root=True,
                )
            relative = selected.root.relative_to(base.root).as_posix()
            if relative != f"generations/{source_sha[:16]}":
                raise ValueError("active_generation_required")
            return _validated_pdf_artifact(
                data_root,
                paper_id,
                f"{relative}/source.pdf",
                source_sha,
            )
        except (
            OSError,
            sqlite3.Error,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError("artifact_not_ready") from error
    metadata = PaperMetadata.from_dict(json.loads((paper_root / "metadata.json").read_text(encoding="utf-8")))
    base = PaperWorkspace(paper_root)
    if kind == "reader":
        try:
            selected, source_sha, *_ = ExportService._active_workspace(base, metadata)
        except (OSError, ValueError):
            selected = None
            source_sha = None
        if selected is not None:
            active = selected.root.relative_to(base.root).as_posix()
            if re.fullmatch(r"generations/[0-9a-f]{16}", active):
                for suffix in ("reading/reader.html", "output/reader_full.html"):
                    candidate = f"{active}/{suffix}"
                    if (paper_root / candidate).is_file():
                        return _validated_artifact(data_root, paper_id, candidate, kind, source_sha)
        try:
            from .migration_audit import audited_legacy_reader_sha

            audit_sha = audited_legacy_reader_sha(data_root, paper_id)
            resolved = _validated_artifact(data_root, paper_id, "reader_full.html", kind, allow_audited_root=True)
            if audit_sha == resolved.get("sha256"):
                return resolved
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            pass
        raise ValueError("artifact_not_ready")
    selected, source_sha, *_ = ExportService._active_workspace(base, metadata)
    rel_path = selected.exports_dir.relative_to(base.root).as_posix()
    return _validated_artifact(data_root, paper_id, rel_path, kind, source_sha)

def _validate_full_read_resume(status, supplied: dict) -> dict:
    if getattr(status, "state", None) in {"failed", "interrupted"}:
        if supplied:
            raise ValueError("terminal_resume_input_invalid")
        return {}
    reason = status.reason_code
    if reason == "pdf_required":
        if not supplied:
            return {}
        if supplied == {"pdf_attached": True}:
            return supplied
        raise ValueError("pdf_resume_input_invalid")
    if reason == "reading_stage_not_connected":
        if supplied:
            raise ValueError("reading_stage_resume_input_invalid")
        return {}
    if reason in {
        "translate_full_read",
        "full_translation_revision_required",
    }:
        if set(supplied) != {"full_translation"}:
            raise ValueError("full_translation_resume_input_invalid")
        translation = supplied["full_translation"]
        if (
            not isinstance(translation, dict)
            or set(translation)
            != {
                "contract_version",
                "batch_id",
                "source_sha256",
                "translations",
            }
            or translation.get("contract_version")
            != FULL_TRANSLATION_CONTRACT_VERSION
            or not isinstance(translation.get("batch_id"), str)
            or not isinstance(translation.get("source_sha256"), str)
            or not isinstance(translation.get("translations"), list)
            or not translation["translations"]
            or any(
                not isinstance(row, dict)
                or set(row)
                != {
                    "block_id",
                    "source_text",
                    "translation_zh",
                    "highlight",
                }
                for row in translation["translations"]
            )
        ):
            raise ValueError("full_translation_resume_input_invalid")
        return {"full_translation": translation}
    if reason in {
        "review_full_read",
        "full_review_revision_required",
        "full_read_artifact_inconsistent",
    }:
        if set(supplied) != {"full_review"}:
            raise ValueError("full_review_resume_input_invalid")
        review = supplied["full_review"]
        if (
            not isinstance(review, dict)
            or set(review) != {"contract_version", "highlights", "guide"}
            or review.get("contract_version")
            != FULL_REVIEW_CONTRACT_VERSION
            or not isinstance(review.get("highlights"), list)
            or not isinstance(review.get("guide"), dict)
        ):
            raise ValueError("full_review_resume_input_invalid")
        return {"full_review": review}
    if reason == "mineru_runtime_required":
        if supplied:
            raise ValueError("mineru_resume_input_invalid")
        return {}
    raise ValueError("full_read_resume_contract_not_supported")

def _navigation_error(code: str, detail: str) -> int:
    print(
        json.dumps(
            {"status": "failed", "error": {"code": code, "detail": detail}},
            ensure_ascii=False,
        )
    )
    return 2

def _classification_payload(args) -> list[dict]:
    if args.input is None or str(args.input) == "-":
        payload = json.load(sys.stdin)
    else:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("proposals")
    if not isinstance(payload, list) or any(
        not isinstance(entry, dict) for entry in payload
    ):
        raise ValueError("proposals_invalid")
    return payload

def _run_navigation_command(args) -> int:
    from .classification_service import (
        ClassificationProposal,
        ClassificationService,
    )
    from .library_service import LibraryService

    proposals = None
    if args.command == "classification-apply":
        try:
            proposals = _classification_payload(args)
        except FileNotFoundError:
            return _navigation_error(
                "classification_file_not_found", "classification_file_missing"
            )
        except OSError:
            return _navigation_error(
                "classification_read_failed", "classification_file_unreadable"
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _navigation_error(
                "invalid_classification_json", "classification_json_malformed"
            )
        except ValueError:
            return _navigation_error(
                "invalid_classification", "classification_validation_failed"
            )

    service = None
    try:
        try:
            service = LibraryService(args.data_root)
        except (OSError, sqlite3.Error):
            return _navigation_error(
                "library_unavailable", "library_initialization_failed"
            )
        try:
            if args.command == "library-list-v2":
                result = service.list_items(
                    page=args.page,
                    page_size=args.page_size,
                    query=args.query,
                    folder_id=args.folder_id,
                    tags=tuple(args.tag),
                    status=args.status,
                    recent_days=args.recent_days,
                )
            elif args.command == "library-item-v2":
                result = service.get_item(args.paper_id)
            elif args.command == "folder-list":
                result = service.list_folders()
            elif args.command == "folder-create":
                result = service.create_folder(args.name)
            elif args.command == "folder-rename":
                result = service.rename_folder(args.folder_id, args.name)
            elif args.command == "classification-apply":
                try:
                    for entry in proposals:
                        raw_tags = entry.get("tags", ())
                        if not isinstance(raw_tags, (list, tuple)) or any(
                            not isinstance(tag, str) for tag in raw_tags
                        ):
                            raise ValueError("tags_invalid")
                    parsed = tuple(
                        ClassificationProposal(
                            paper_id=entry["paper_id"],
                            folder_name=entry.get("folder_name"),
                            tags=tuple(entry.get("tags", ())),
                            confidence=entry["confidence"],
                        )
                        for entry in proposals
                    )
                except (KeyError, TypeError, ValueError):
                    return _navigation_error(
                        "invalid_classification", "classification_validation_failed"
                    )
                result = ClassificationService(service).apply(
                    parsed,
                    minimum_confidence=args.minimum_confidence,
                    allow_new_folders=args.allow_new_folders,
                )
            else:
                result = ClassificationService(service).undo(args.operation_id)
        except ValueError as error:
            if args.command == "library-item-v2" and str(error) in {
                "paper_id_invalid",
                "paper_not_found",
            }:
                code = str(error)
                detail = (
                    "library_item_not_found"
                    if code == "paper_not_found"
                    else "library_paper_id_invalid"
                )
                return _navigation_error(code, detail)
            return _navigation_error(
                "invalid_library_request", "library_request_rejected"
            )
        except sqlite3.Error:
            return _navigation_error(
                "operation_failed", "library_operation_failed"
            )
    finally:
        if service is not None:
            service.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0

def _queued_job_result(handle, store) -> dict[str, str]:
    status = store.load_status(handle.job_id)
    if status.state in {"failed", "interrupted"}:
        store.save_resume_input(handle.job_id, {})
        store.transition(handle.job_id, "queued")
        return {"status": "created", "job_id": handle.job_id}
    if status.state == "waiting_user":
        return {"status": "needs_user", "job_id": handle.job_id}
    if status.state in {"queued", "running", "completed"}:
        return {"status": "created" if handle.created else "reused", "job_id": handle.job_id}
    return {"status": "failed", "reason": "batch_job_state_invalid"}

def _pipeline_batch_result(state, store, previous_job_id, *, retry: bool) -> dict[str, str]:
    status = store.load_status(state.parent_job_id)
    if status.state in {"failed", "interrupted"}:
        if not retry:
            return {"status": "failed", "reason": "retry_required"}
        store.save_resume_input(state.parent_job_id, {})
        store.transition(state.parent_job_id, "queued")
        return {"status": "created", "job_id": state.parent_job_id}
    if status.state == "waiting_user" or state.state == "needs_user":
        return {"status": "needs_user", "job_id": state.parent_job_id}
    if status.state == "queued":
        return {"status": "reused" if previous_job_id == state.parent_job_id else "created", "job_id": state.parent_job_id}
    if status.state in {"running", "completed"}:
        return {"status": "reused", "job_id": state.parent_job_id}
    return {"status": "failed", "reason": "batch_job_state_invalid"}

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DSH Scientific Reading")
    parser.add_argument("--data-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("library-ingest")
    listing = commands.add_parser("library-list-v2")
    listing.add_argument("--page", type=int, default=1)
    listing.add_argument("--page-size", type=int, default=50)
    listing.add_argument("--query")
    listing.add_argument("--folder-id")
    listing.add_argument("--tag", action="append", default=[])
    listing.add_argument("--status")
    listing.add_argument("--recent-days", type=int)
    item = commands.add_parser("library-item-v2")
    item.add_argument("--paper-id", required=True)
    commands.add_parser("folder-list")
    folder_create = commands.add_parser("folder-create")
    folder_create.add_argument("--name", required=True)
    folder_rename = commands.add_parser("folder-rename")
    folder_rename.add_argument("--folder-id", required=True)
    folder_rename.add_argument("--name", required=True)
    apply = commands.add_parser("classification-apply")
    apply.add_argument("--input", type=Path)
    apply.add_argument("--minimum-confidence", type=float, default=0.70)
    apply.add_argument("--allow-new-folders", action="store_true")
    undo = commands.add_parser("classification-undo")
    undo.add_argument("--operation-id", required=True)

    derived = commands.add_parser("derived-enqueue")
    derived.add_argument("--paper-id")
    derived.add_argument("--metadata", type=Path)
    derived.add_argument("--feishu-config", type=Path)
    abstract_submit = commands.add_parser("abstract-read-submit")
    abstract_submit.add_argument("--job-id", required=True)
    abstract_submit.add_argument("--input", type=Path, required=True)

    status = commands.add_parser("job-status")
    status.add_argument("--job-id", required=True)
    start = commands.add_parser("full-read-pipeline-start")
    start.add_argument("--paper-id", required=True)
    start.add_argument("--provider-profile", choices=("none", "scansci"), default="none")
    resume = commands.add_parser("full-read-pipeline-resume")
    resume.add_argument("--job-id", required=True)
    resume.add_argument("--input", type=Path)
    attach = commands.add_parser("full-read-pdf-attach-resume")
    attach.add_argument("--paper-id", required=True)
    attach.add_argument("--job-id", required=True)
    attach.add_argument("--pdf", type=Path, required=True)
    export = commands.add_parser("export-assets")
    export.add_argument("--paper-id", required=True)
    export.add_argument("--force", action="store_true")
    artifact = commands.add_parser("artifact-resolve")
    artifact.add_argument("--paper-id", required=True)
    artifact.add_argument("--kind", choices=("pdf", "reader", "exports"), required=True)

    batch = commands.add_parser("batch-submit")
    probe = commands.add_parser("feishu-probe")
    probe.add_argument("--config", type=Path, required=True)
    resync = commands.add_parser("feishu-resync")
    resync.add_argument("--config", type=Path, required=True)
    resync.add_argument("--paper-id", action="append", default=[])
    return parser

def _run_batch(args) -> int:
    from .batch_service import BatchService
    from .library_service import LibraryService
    from .reading_pipeline import ReadingPipeline

    request = json.load(sys.stdin)
    library = LibraryService(args.data_root)
    pipeline = ReadingPipeline(args.data_root)
    try:
        result = BatchService(
            args.data_root,
            library=library,
            queue_full_read=lambda paper_id: _pipeline_batch_result(
                pipeline.start(paper_id), pipeline.job_store, None, retry=False
            ),
            retry_failed=lambda paper_id: _pipeline_batch_result(
                pipeline.start(paper_id), pipeline.job_store, None, retry=True
            ),
            feishu_resync=lambda paper_id: {
                "status": "needs_user",
                "reason": "use_feishu_resync",
                "paper_id": paper_id,
            },
        ).submit(request.get("action"), request.get("selection", ()), request.get("payload", {}))
    finally:
        library.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0

def _run_derived(args) -> int:
    request = None
    try:
        metadata = _load_derived_metadata(args)
        request = DerivedPipeline.metadata_request(
            args.data_root,
            metadata,
            paper_id=args.paper_id,
            feishu_config_path=args.feishu_config,
        )
        launched = DerivedPipeline(
            args.data_root,
            launcher=_build_background_launcher(args.data_root),
        ).enqueue(request)
    except (BackgroundLaunchError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        detail = {"status": "failed", "error": str(error)}
        if request is not None:
            detail["job_id"] = stable_job_id(request)
            _record_derived_job(args.data_root, request.paper_id, detail["job_id"], error=str(error))
        print(json.dumps(detail, ensure_ascii=False))
        return 4
    print(json.dumps({
        "status": launched.status.state,
        "job_id": launched.job_id,
        "target_stage": request.target_stage,
        "process_started": launched.process_started,
    }, ensure_ascii=False))
    return 0

def _run_feishu(args) -> int:
    policy = FeishuAutoSyncPolicy(args.data_root)
    try:
        if args.command == "feishu-probe":
            result = policy.probe(args.config)
        else:
            config = load_feishu_config(args.config)
            paper_ids = args.paper_id or policy.pending()
            revision = policy.activation_revision()
            if not revision:
                raise ValueError("feishu_auto_not_initialized")
            launcher = _build_background_launcher(args.data_root)
            jobs = []
            from .library_service import LibraryService
            library = LibraryService(args.data_root)
            try:
                for paper_id in paper_ids:
                    metadata = library.canonical_metadata(paper_id)
                    workspace = PaperWorkspace.create_for_paper_id(args.data_root, paper_id, metadata)
                    payload = FeishuPayloadBuilder().build(workspace, config)
                    request = BackgroundRequest(
                        paper_id=paper_id,
                        target_stage="feishu_sync",
                        input_hash=feishu_sync_input_hash(config, payload),
                        payload={
                            "data_root": str(Path(args.data_root).resolve()),
                            "metadata": metadata.to_dict(),
                            "config": config.to_dict(),
                            "payload": payload.to_dict(),
                            "write_mode": "configured_auto",
                            "activation_revision": revision,
                        },
                    )
                    launched = launcher.enqueue(request)
                    jobs.append({"paper_id": paper_id, "job_id": launched.job_id, "process_started": launched.process_started})
            finally:
                library.close()
            result = {"status": "resync_queued", "jobs": jobs}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 4
    print(json.dumps(result, ensure_ascii=False))
    return 0

def run_cli(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    timer = ForegroundTimer()
    try:
        if args.command == "library-ingest":
            metadata = PaperMetadata.from_dict(json.load(sys.stdin))
            return _run_library_ingest(args, metadata, deprecated=False)
        if args.command in {
            "library-list-v2", "library-item-v2", "folder-list", "folder-create",
            "folder-rename", "classification-apply", "classification-undo",
        }:
            return _run_navigation_command(args)
        if args.command == "derived-enqueue":
            return _run_derived(args)
        if args.command == "abstract-read-submit":
            return _submit_abstract_read(args, timer)
        if args.command == "job-status":
            result, code = _job_foreground(BackgroundJobStore(args.data_root), args.job_id, timer)
            print(json.dumps(result.to_dict(), ensure_ascii=False))
            return code
        if args.command in {"full-read-pipeline-start", "full-read-pipeline-resume"}:
            return _run_full_read_pipeline(args)
        if args.command == "full-read-pdf-attach-resume":
            return _run_full_read_pdf_attach_resume(args)
        if args.command == "export-assets":
            result = ExportService().export_for_paper(args.data_root, args.paper_id, force=args.force)
            print(json.dumps(result.to_dict(), ensure_ascii=False))
            return 0
        if args.command == "artifact-resolve":
            result = _resolve_artifact(args.data_root, args.paper_id, args.kind)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "batch-submit":
            return _run_batch(args)
        if args.command in {"feishu-probe", "feishu-resync"}:
            return _run_feishu(args)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 4
    raise AssertionError("unreachable")

def main() -> None:
    raise SystemExit(run_cli())

if __name__ == "__main__":
    main()
