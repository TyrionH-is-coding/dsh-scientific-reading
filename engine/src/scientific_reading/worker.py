from __future__ import annotations

import argparse
import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Mapping

from .background_models import (
    AgentRequired,
    BackgroundRequest,
    UserActionRequired,
    UserRequired,
)
from .background_launcher import BackgroundLaunchError
from .background_store import BackgroundJobStore
from .full_read_service import FullReadError, FullReadService
from .models import PaperMetadata
from .metadata_enrichment import MetadataEnrichmentService
from .abstract_read_service import AbstractReadService, AbstractReadValidationError
from .derived_pipeline import DerivedPipeline
from .xlsx_snapshot import XlsxSnapshotService
from .workspace import PaperWorkspace
from .workspace import atomic_write_json
from .scope import use_scope, capture_scope, ScopeError, publication_guard


Handler = Callable[[BackgroundRequest, Callable[[], None]], dict]


def _sync_derived_job(
    request: BackgroundRequest, job_id: str, *, error: str | None = None
) -> None:
    if request.payload.get("derived_pipeline") is not True:
        return
    data_root = request.payload.get("data_root")
    if not isinstance(data_root, str) or not data_root.strip():
        return
    from .library_service import LibraryService

    library = LibraryService(Path(data_root))
    try:
        library.update_active_job(request.paper_id, job_id, error=error)
    finally:
        library.close()


def _set_abstract_status(request: BackgroundRequest, status: str) -> None:
    data_root = request.payload.get("data_root")
    if not isinstance(data_root, str) or not data_root.strip():
        return
    from .library_service import LibraryService

    service = LibraryService(Path(data_root))
    try:
        service.update_abstract_status(request.paper_id, status)
    finally:
        service.close()


def _workspace_for_request(
    request: BackgroundRequest, metadata: PaperMetadata
) -> PaperWorkspace:
    data_root = Path(request.payload["data_root"])
    if request.payload.get("derived_pipeline") is True:
        return PaperWorkspace.create_for_paper_id(data_root, request.paper_id, metadata)
    return PaperWorkspace.create(data_root, metadata)


def metadata_enrichment_handler_factory(service=None) -> Handler:
    def handler(request: BackgroundRequest, heartbeat: Callable[[], None]) -> dict:
        payload = request.payload
        metadata = PaperMetadata.from_dict(payload["metadata"])
        selected = service or MetadataEnrichmentService()
        heartbeat()
        result = selected.enrich(metadata)
        if result.status == "retry":
            raise AgentRequired("metadata_enrichment_retry", {"error": result.error or "provider_failed"})
        workspace = _workspace_for_request(request, metadata)
        if result.status == "enriched":
            workspace = _workspace_for_request(request, result.metadata)
            atomic_write_json(workspace.metadata_path, result.metadata.to_dict())
            from .library_service import LibraryService
            library = LibraryService(Path(payload["data_root"]))
            try:
                library.ingest(result.metadata)
            finally:
                library.close()
        if result.metadata.abstract_en and result.metadata.abstract_en.strip():
            _set_abstract_status(request, "available")
        elif result.status == "missing" or not result.metadata.abstract_en:
            _set_abstract_status(request, "missing")
        return {"status": result.status, "metadata_path": str(workspace.metadata_path), "abstract_en": result.metadata.abstract_en}
    return handler


def abstract_read_handler_factory(service=None) -> Handler:
    def handler(request: BackgroundRequest, heartbeat: Callable[[], None]) -> dict:
        payload = request.payload
        workspace = _workspace_for_request(
            request, PaperMetadata.from_dict(payload["metadata"])
        )
        selected = service or AbstractReadService()
        heartbeat()
        context = selected.inspect(workspace)
        if context["status"] == "missing":
            _set_abstract_status(request, "missing")
            return context
        if context["status"] == "published":
            _set_abstract_status(request, "completed")
            return {"status": "abstract_read_ready", "path": str(workspace.reading_dir / "abstract_read.json")}
        translation = payload.get("abstract_translation")
        if translation is None:
            _set_abstract_status(
                request,
                "stale" if context["status"] == "stale" else "waiting_agent",
            )
            raise AgentRequired("translate_abstract", {**context, "required_input": "abstract_translation"})
        try:
            result = selected.publish(workspace, translation)
            _set_abstract_status(request, "completed")
            return result
        except AbstractReadValidationError as error:
            _set_abstract_status(
                request,
                "stale" if context["status"] == "stale" else "waiting_agent",
            )
            raise AgentRequired("abstract_translation_revision_required", {**context, "validation_error": str(error)}) from error
    return handler


def xlsx_snapshot_handler_factory(service=None) -> Handler:
    def handler(request: BackgroundRequest, heartbeat: Callable[[], None]) -> dict:
        selected = service or XlsxSnapshotService(Path(request.payload["data_root"]))
        heartbeat()
        # XLSX is a system-derived whole-library snapshot, never a scoped query result.
        with publication_guard(Path(request.payload["data_root"]), request.paper_id), use_scope(None):
            result = selected.refresh()
        heartbeat()
        if result["status"] == "pending":
            raise UserRequired(result["error"]["code"], result)
        if result["status"] == "failed":
            raise RuntimeError(result["error"]["code"])
        return result

    return handler


def full_read_handler_factory(service=None) -> Handler:
    def handler(
        request: BackgroundRequest,
        heartbeat: Callable[[], None],
    ) -> dict:
        payload = request.payload
        metadata = PaperMetadata.from_dict(payload["metadata"])
        workspace = PaperWorkspace.create(
            Path(payload["data_root"]),
            metadata,
        )
        selected_service = service or FullReadService()
        heartbeat()
        try:
            selected_service.prepare(workspace)
        except FullReadError as error:
            if error.code == "mineru_required_for_full_read":
                raise AgentRequired(
                    error.code,
                    {
                        "metadata_path": str(workspace.metadata_path),
                        "upgrade_reason": "full-read",
                    },
                ) from error
            raise AgentRequired(
                "full_read_artifact_inconsistent",
                {"error": error.code},
            ) from error

        translation = payload.get("full_translation")
        if translation is not None:
            try:
                selected_service.save_next_translation(
                    workspace,
                    translation,
                )
            except FullReadError as error:
                raise AgentRequired(
                    "full_read_artifact_inconsistent",
                    {"error": error.code},
                ) from error
            except (TypeError, ValueError) as error:
                batch = selected_service.next_batch(workspace)
                raise AgentRequired(
                    "full_translation_revision_required",
                    {
                        **(batch or {}),
                        "validation_error": str(error),
                    },
                ) from error

        batch = selected_service.next_batch(workspace)
        if batch is not None:
            raise AgentRequired(
                "translate_full_read",
                {
                    **batch,
                    "source_file": str(
                        workspace.reading_dir
                        / "full"
                        / "batches"
                        / f"{batch['batch_id']}.source.json"
                    ),
                },
            )

        context = selected_service.review_context(workspace)
        review = payload.get("full_review")
        if review is None:
            raise AgentRequired("review_full_read", context)
        try:
            result = selected_service.finalize(workspace, review)
        except FullReadError as error:
            raise AgentRequired(
                "full_read_artifact_inconsistent",
                {"error": error.code, **context},
            ) from error
        except (TypeError, ValueError) as error:
            raise AgentRequired(
                "full_review_revision_required",
                {"validation_error": str(error), **context},
            ) from error
        heartbeat()
        return result

    return handler


_NO_PIPELINE_INPUT = object()


def full_read_pipeline_handler_factory(
    pipeline=None, *, pipeline_input=_NO_PIPELINE_INPUT
) -> Handler:
    def handler(request: BackgroundRequest, heartbeat: Callable[[], None]) -> dict:
        from .reading_pipeline import ReadingPipeline

        if pipeline is None:
            from .pdf_acquisition import ScansciJsonProvider

            provider = None
            if request.payload.get("provider_profile", "none") == "scansci":
                provider = ScansciJsonProvider.from_environ()
            selected = ReadingPipeline(Path(request.payload["data_root"]), pdf_provider=provider)
        else:
            selected = pipeline
        supplied = (
            pipeline_input
            if pipeline_input is not _NO_PIPELINE_INPUT
            else request.payload.get("pipeline_input")
        )
        if supplied is None and pipeline_input is _NO_PIPELINE_INPUT:
            resume_values = {
                key: value
                for key, value in request.payload.items()
                if key not in {"data_root", "provider_profile"}
            }
            supplied = resume_values or None
        from .background_store import stable_job_id

        identity_payload = {
            key: request.payload[key]
            for key in ("data_root", "provider_profile")
            if key in request.payload
        }
        expected_parent_job_id = stable_job_id(
            BackgroundRequest(
                paper_id=request.paper_id,
                target_stage=request.target_stage,
                input_hash=request.input_hash,
                payload=identity_payload,
            )
        )
        parent_job_id = selected.start(
            request.paper_id, str(request.payload.get("provider_profile", "none")),
            expected_parent_job_id=expected_parent_job_id,
        ).parent_job_id
        if parent_job_id != expected_parent_job_id:
            raise RuntimeError("full_read_parent_mismatch")
        while True:
            heartbeat()
            result = selected.advance(parent_job_id, supplied)
            supplied = None
            if result.state == "waiting_agent":
                action = result.required_action or {}
                raise AgentRequired(
                    action.get("reason_code", "agent_required"),
                    {k: v for k, v in action.items() if k != "reason_code"},
                )
            if result.state == "needs_user":
                action = result.required_action or {}
                raise UserActionRequired(
                    action.get("reason_code", "user_action_required"),
                    {k: v for k, v in action.items() if k != "reason_code"},
                )
            if result.state == "failed":
                raise RuntimeError(result.last_error or "full_read_pipeline_failed")
            if result.state == "completed":
                return result.to_dict()

    return handler


DEFAULT_HANDLERS: dict[str, Handler] = {
    "metadata_enrichment": metadata_enrichment_handler_factory(),
    "abstract_read": abstract_read_handler_factory(),
    "xlsx_snapshot": xlsx_snapshot_handler_factory(),
    "full_read": full_read_handler_factory(),
    "full_read_pipeline": full_read_pipeline_handler_factory(),
}


def _sync_library_status(request: BackgroundRequest, state: str, values: dict) -> None:
    """阶段结束后把 job 状态同步进本地文献库。"""
    data_root = request.payload.get("data_root")
    if not isinstance(data_root, str) or not data_root.strip():
        return
    root = Path(data_root)
    if not root.is_dir():
        return
    from .library_service import LibraryService

    status = (
        values.get("status")
        if isinstance(values, dict) and isinstance(values.get("status"), str)
        else state
    )
    if request.target_stage not in {
        "metadata_enrichment",
        "abstract_read",
        "xlsx_snapshot",
        "full_read_pipeline",
    }:
        service = LibraryService(root)
        try:
            service.update_status(request.paper_id, status)
        finally:
            service.close()
    if request.target_stage == "full_read" and state == "completed":
        with sqlite3.connect(root / "library.sqlite") as conn:
            conn.execute(
                "UPDATE items SET full_read_status='completed' WHERE paper_id=?",
                (request.paper_id,),
            )
def run_job(
    store: BackgroundJobStore,
    job_id: str,
    handlers: dict[str, Handler] | None = None,
    *,
    heartbeat_interval: float = 5.0,
) -> int:
    from .data_guard import data_root_operation

    # Includes heartbeat writes and external parser subprocess output until they stop.
    with data_root_operation(store.data_root, timeout=300), use_scope(store.load_status(job_id).scope):
        try:
            capture_scope(store.data_root, store.load_request(job_id).paper_id)
        except ScopeError as error:
            status = store.load_status(job_id)
            if status.state == "queued":
                store.transition(job_id, "running", pid=os.getpid())
            store.transition(job_id, "failed", error=str(error))
            return 4
        return _run_job(store, job_id, handlers, heartbeat_interval=heartbeat_interval)


def _run_job(
    store: BackgroundJobStore,
    job_id: str,
    handlers: dict[str, Handler] | None = None,
    *,
    heartbeat_interval: float = 5.0,
) -> int:
    request = store.load_request(job_id)
    resume_exists = store.handle(job_id).resume_path.exists()
    resume_input = store.load_resume_input(job_id)
    if resume_exists:
        request = BackgroundRequest(
            paper_id=request.paper_id,
            target_stage=request.target_stage,
            input_hash=request.input_hash,
            payload=(
                {**request.payload, **resume_input}
                if resume_input
                else {**request.payload, "pipeline_input": {}}
            ),
        )
    selected = (handlers or DEFAULT_HANDLERS).get(request.target_stage)
    if selected is None:
        store.transition(job_id, "failed", error="unsupported_target_stage")
        return 4

    pid = os.getpid()
    store.transition(job_id, "running", pid=pid)
    stopped = threading.Event()

    def heartbeat() -> None:
        # run_job owns the root operation until this thread is joined.
        store._heartbeat(job_id, pid=pid)

    def heartbeat_loop() -> None:
        while not stopped.wait(heartbeat_interval):
            heartbeat()

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    state = "completed"
    values: dict = {}
    reason_code = None
    error = None
    exit_code = 0
    try:
        _sync_derived_job(request, job_id)
        capture_scope(store.data_root, request.paper_id)
        values = selected(request, heartbeat)
    except AgentRequired as gate:
        state = "waiting_agent"
        reason_code = gate.reason_code
        values = gate.required_input
        exit_code = 3
    except UserRequired as gate:
        state = "waiting_user"
        reason_code = gate.reason_code
        values = gate.required_input
        exit_code = 2
    except KeyboardInterrupt:
        state = "interrupted"
        error = "worker_interrupted"
        exit_code = 130
    except Exception as caught:
        state = "failed"
        error = str(caught)
        exit_code = 4
    finally:
        stopped.set()
        thread.join()

    if state == "completed":
        try:
            _sync_library_status(request, state, values)
            if request.payload.get("derived_pipeline") is True:
                values = {
                    **values,
                    "derived": DerivedPipeline(
                        Path(request.payload["data_root"])
                    ).advance(request, values, parent_job_id=job_id),
                }
        except Exception as caught:
            if isinstance(caught, ScopeError):
                store.transition(job_id, "failed", error=str(caught))
                return 4
            if not isinstance(caught, BackgroundLaunchError):
                _sync_derived_job(request, job_id, error=str(caught))
            store.transition(
                job_id,
                "failed",
                error=f"library_status_sync_failed:{caught}",
            )
            return 4
        store.transition(job_id, state, result=values)
    elif state in {"waiting_agent", "waiting_user"}:
        _sync_derived_job(request, job_id)
        store.transition(
            job_id,
            state,
            reason_code=reason_code,
            required_input=values,
        )
    else:
        if not (error and error.startswith("scope_")):
            _sync_derived_job(request, job_id, error=error)
        store.transition(job_id, state, error=error)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scientific Reading 后台 worker")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    from .data_guard import data_root_operation

    with data_root_operation(args.data_root, timeout=300):
        store = BackgroundJobStore(args.data_root)
        raise SystemExit(run_job(store, args.job_id))


if __name__ == "__main__":
    main()
