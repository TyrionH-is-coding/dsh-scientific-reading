from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .background_models import AgentRequired, BackgroundRequest, UserActionRequired
from .background_store import BackgroundJobStore, JobClaimUnavailable
from .identifiers import metadata_identity_compatible
from .library_service import LibraryService
from .models import PaperMetadata, StageRecord
from .reading_pipeline_models import (
    PIPELINE_STAGES,
    USER_STATUS,
    PipelineResult,
    ReadingPipelineState,
)
from .workspace import PaperWorkspace, atomic_write_json


StageRunner = Callable[
    [str, ReadingPipelineState, dict[str, Any] | None], dict[str, Any]
]
_HEAVY_STAGES = {"parse_mineru", "translate_full"}
_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "cookie",
    "password",
    "authorization",
    "credential",
    "session",
    "command",
)
_SENSITIVE_VALUE_MARKERS = (
    "authorization=",
    "authorization:",
    "bearer ",
    "token=",
    "secret=",
    "password=",
    "cookie=",
    "credential=",
    "session=",
)
_STAGE_OUTPUT_FIELDS = {
    "ensure_pdf": {
        "status",
        "job_id",
        "source_pdf_sha256",
        "source_path",
        "page_count",
        "reused",
    },
    "parse_mineru": {"status", "job_id", "output_path", "manifest_path", "source_sha256"},
    "translate_full": {
        "status",
        "job_id",
        "output_path",
        "manifest_path",
        "source_sha256",
        "completed_batches",
    },
    "render_reader": {
        "status",
        "job_id",
        "reader_html",
        "manifest_path",
        "reader_source_sha256",
    },
    "schedule_derived_updates": {
        "status",
        "job_id",
        "xlsx_job_id",
        "feishu_job_id",
        "error",
    },
}
_OUTPUT_INTEGER_FIELDS = {"page_count", "completed_batches"}
_OUTPUT_BOOLEAN_FIELDS = {"reused"}
_REQUIRED_ACTION_FIELDS = {
    "kind",
    "options",
    "batch",
    "batch_id",
    "stage",
    "source_sha256",
    "source_manifest_path",
    "contract_version",
    "translations_json",
    "source_map_json",
    "translation_count",
    "substantive_block_count",
    "maximum_full_review_highlights",
    "available_source_block_ids",
    "highlight_kinds",
    "guide_limits",
    "target_highlight_ratio",
    "maximum_highlight_ratio",
    "validation_error",
    "error",
}
_REQUIRED_ACTION_INTEGER_FIELDS = {
    "batch",
    "translation_count",
    "substantive_block_count",
    "maximum_full_review_highlights",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReadingPipeline:
    def __init__(
        self,
        data_root: Path,
        *,
        stage_runner: StageRunner | None = None,
        pdf_provider=None,
        mineru_service=None,
        full_read_service=None,
        reader_renderer=None,
        init_claim_timeout: float = 1.0,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.job_store = BackgroundJobStore(self.data_root)
        self.pdf_provider = pdf_provider
        self.mineru_service = mineru_service
        self.full_read_service = full_read_service
        self.reader_renderer = reader_renderer
        self.stage_runner = stage_runner or self._default_stage_runner
        self.init_claim_timeout = init_claim_timeout

    @staticmethod
    def _stage_not_connected(
        stage: str,
        _state: ReadingPipelineState,
        _input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raise RuntimeError(f"reading_stage_not_connected:{stage}")

    def _default_stage_runner(
        self,
        stage: str,
        state: ReadingPipelineState,
        supplied_input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        library = LibraryService(self.data_root)
        try:
            metadata = library.canonical_metadata(state.paper_id)
        finally:
            library.close()
        workspace = PaperWorkspace.create_for_paper_id(
            self.data_root, state.paper_id, metadata
        )
        if json.loads(
            workspace.metadata_path.read_text(encoding="utf-8")
        ) != metadata.to_dict():
            atomic_write_json(workspace.metadata_path, metadata.to_dict())
        if stage == "ensure_pdf":
            from .pdf_acquisition import TrustedPdfAcquisitionService

            result = TrustedPdfAcquisitionService(
                self.data_root, self.pdf_provider
            ).ensure_pdf(state.paper_id)
            workspace_state = workspace.load_job()
            workspace_state.status = "pdf_ready"
            workspace_state.stages["pdf_acquisition"] = StageRecord(
                status="completed",
                input_hash=result.sha256,
                result={
                    "sha256": result.sha256,
                    "page_count": result.page_count,
                    "source_path": str(result.source_path),
                },
            )
            workspace.save_job(workspace_state)
            return {
                "status": result.status,
                "source_pdf_sha256": result.sha256,
                "source_path": str(result.source_path),
                "page_count": result.page_count,
                "reused": result.reused,
            }
        if stage == "parse_mineru":
            from .mineru_api import MineruApiError
            from .mineru_service import MineruParseService

            stage_workspace = self._stage_workspace(
                workspace,
                metadata,
                state.source_pdf_sha256,
                "paper_parse_upgrade",
            )
            try:
                result = (self.mineru_service or MineruParseService()).run(
                    self.data_root,
                    metadata,
                    "auto",
                    heartbeat=lambda: None,
                    upgrade_reason="full-read",
                    paper_id=state.paper_id,
                    workspace=stage_workspace,
                )
            except MineruApiError as error:
                if error.code in {
                    "mineru_api_token_required",
                    "mineru_api_auth_failed",
                    "mineru_api_quota_exceeded",
                    "mineru_api_timeout",
                    "mineru_api_unavailable",
                }:
                    raise AgentRequired(
                        error.code, {"stage": "parse_mineru"}
                    ) from error
                raise
            self._adopt_workspace_stage(
                workspace, stage_workspace, "paper_parse_upgrade"
            )
            return {
                "status": result.status,
                "source_sha256": result.source_sha256,
                "output_path": str(
                    stage_workspace.parsed_dir / "mineru" / "full.md"
                ),
                "manifest_path": str(
                    stage_workspace.parsed_dir / "mineru" / "source_map.json"
                ),
                "provider": result.provider,
                "model_version": result.model_version,
            }
        if stage == "translate_full":
            from .full_read_service import FullReadError, FullReadService

            service = self.full_read_service or FullReadService()
            stage_workspace = self._stage_workspace(
                workspace,
                metadata,
                state.source_pdf_sha256,
                "paper_parse_upgrade",
                require_stage=True,
            )
            prepared = service.prepare(stage_workspace)
            translation = (
                supplied_input.get("full_translation")
                if isinstance(supplied_input, dict)
                else None
            )
            if translation is not None:
                try:
                    service.save_translation_batch(stage_workspace, translation)
                except (FullReadError, TypeError, ValueError) as error:
                    batch = service.next_batch(stage_workspace)
                    raise AgentRequired(
                        "full_translation_revision_required",
                        self._translation_gate(stage_workspace, batch),
                    ) from error
            batch = service.next_batch(stage_workspace)
            if batch is not None:
                raise AgentRequired(
                    "translate_full_read",
                    self._translation_gate(stage_workspace, batch),
                )
            context = service.review_context(stage_workspace)
            review = (
                supplied_input.get("full_review")
                if isinstance(supplied_input, dict)
                else None
            )
            if review is None:
                raise AgentRequired("review_full_read", context)
            try:
                service.finalize(stage_workspace, review)
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
            return {
                "status": "translated_full",
                "source_sha256": prepared.plan["source_sha256"],
                "output_path": context["translations_json"],
                "manifest_path": context["translations_json"],
                "completed_batches": len(prepared.plan["batches"]),
            }
        if stage == "render_reader":
            from .full_read_renderer import FullReadRenderer

            stage_workspace = self._stage_workspace(
                workspace,
                metadata,
                state.source_pdf_sha256,
                "paper_parse_upgrade",
                require_stage=True,
            )
            result = (self.reader_renderer or FullReadRenderer()).render_completed(
                stage_workspace, paper_id=state.paper_id
            )
            relative = Path(result["reader_html"]).resolve().relative_to(
                workspace.root.resolve()
            ).as_posix()
            library = LibraryService(self.data_root)
            try:
                library.publish_reader(state.paper_id, relative)
            finally:
                library.close()
            return {
                "status": result["status"],
                "reader_html": relative,
                "manifest_path": Path(result["manifest_path"]).resolve().relative_to(
                    workspace.root.resolve()
                ).as_posix(),
                "reader_source_sha256": result["reader_source_sha256"],
            }
        raise AgentRequired("reading_stage_not_connected", {"stage": stage})

    def _stage_workspace(
        self,
        workspace: PaperWorkspace,
        metadata,
        source_sha256: str | None,
        pointer_stage: str,
        *,
        require_stage: bool = False,
    ) -> PaperWorkspace:
        if source_sha256 is None:
            return workspace
        state = workspace.load_job()
        pointer = state.stages.get(pointer_stage)
        pointer_sha = (
            pointer.result.get("source_sha256") if pointer is not None else None
        )
        relative = pointer.result.get("active_workspace") if pointer else None
        if pointer_sha == source_sha256 and relative is None:
            if require_stage and pointer.status != "completed":
                raise ValueError("active_workspace_invalid")
            return workspace
        if pointer is None and require_stage:
            raise ValueError("active_workspace_invalid")
        expected_root = (
            workspace.root / "generations" / source_sha256[:16]
        ).resolve()
        existed = expected_root.exists()
        generation = (
            PaperWorkspace(expected_root)
            if existed
            else PaperWorkspace.create_generation(
                workspace, source_sha256, metadata
            )
        )
        try:
            confirmed = PaperMetadata.from_dict(
                json.loads(
                    generation.metadata_path.read_text(encoding="utf-8")
                )
            )
            generation_state = generation.load_job()
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("generation_workspace_conflict") from error
        if (
            not metadata_identity_compatible(confirmed, metadata)
            or generation_state.paper_id != source_sha256[:16]
        ):
            raise ValueError("generation_workspace_conflict")
        if (
            hashlib.sha256(workspace.source_pdf.read_bytes()).hexdigest()
            != source_sha256
        ):
            raise ValueError("generation_source_conflict")
        if generation.source_pdf.exists():
            if (
                hashlib.sha256(generation.source_pdf.read_bytes()).hexdigest()
                != source_sha256
            ):
                raise ValueError("generation_source_conflict")
        else:
            temporary = generation.source_pdf.with_suffix(".pdf.tmp")
            shutil.copyfile(workspace.source_pdf, temporary)
            temporary.replace(generation.source_pdf)
        nested_stage = generation_state.stages.get(pointer_stage)
        if nested_stage is not None and (
            nested_stage.result.get("source_sha256") != source_sha256
        ):
            raise ValueError("generation_workspace_conflict")
        if require_stage and (
            nested_stage is None or nested_stage.status != "completed"
        ):
            raise ValueError("generation_workspace_conflict")
        if (
            pointer_stage in {"paper_parse", "paper_parse_upgrade"}
            and nested_stage is None
            and not require_stage
        ):
            generation_state.status = "pdf_ready"
            pdf_stage = state.stages.get("pdf_acquisition")
            if pdf_stage is not None:
                generation_state.stages["pdf_acquisition"] = StageRecord.from_dict(
                    asdict(pdf_stage)
                )
        generation.save_job(generation_state)
        return generation

    @staticmethod
    def _adopt_workspace_stage(
        workspace: PaperWorkspace,
        stage_workspace: PaperWorkspace,
        stage_name: str,
    ) -> None:
        if stage_workspace.root == workspace.root:
            return
        source_state = stage_workspace.load_job()
        stage = source_state.stages[stage_name]
        adopted = StageRecord.from_dict(asdict(stage))
        adopted.result["active_workspace"] = stage_workspace.root.relative_to(
            workspace.root
        ).as_posix()
        state = workspace.load_job()
        state.stages[stage_name] = adopted
        state.status = source_state.status
        state.error = source_state.error
        workspace.save_job(state)

    @staticmethod
    def _translation_gate(
        workspace: PaperWorkspace, batch: dict[str, Any] | None
    ) -> dict[str, Any]:
        if batch is None:
            return {"stage": "translate_full"}
        batch_id = batch["batch_id"]
        return {
            "stage": "translate_full",
            "batch_id": batch_id,
            "source_sha256": batch["source_sha256"],
            "source_manifest_path": str(
                workspace.reading_dir
                / "full"
                / "batches"
                / f"{batch_id}.source.json"
            ),
        }

    def start(self, paper_id: str, provider_profile: str = "none") -> PipelineResult:
        if provider_profile not in {"none", "scansci"}:
            raise ValueError("trusted_provider_profile_invalid")
        library = LibraryService(self.data_root)
        try:
            item = library.get_item(paper_id)
            metadata = library.canonical_metadata(paper_id)
            workspace = PaperWorkspace.create_for_paper_id(
                self.data_root, paper_id, metadata
            )
            current_sha = self._validated_source_sha(workspace.source_pdf, metadata)
            active_job_id = item.get("active_job_id")
            generation = current_sha
            if isinstance(active_job_id, str):
                try:
                    active = self._load(active_job_id, expected_paper_id=paper_id)
                    active_profile = self.job_store.load_request(active_job_id).payload.get("provider_profile", "none")
                    if active_profile != provider_profile:
                        raise RuntimeError("provider_profile_conflict")
                    if active.current_stage != "completed":
                        self._sync_library(active)
                        return active
                    if active.source_pdf_sha256 == current_sha:
                        self._sync_library(active)
                        return active
                    if current_sha is None:
                        generation = (
                            "missing-after:"
                            + (active.source_pdf_sha256 or active.parent_job_id)
                        )
                except (FileNotFoundError, ValueError, json.JSONDecodeError):
                    pass
            if current_sha is not None:
                indexed_job_id = library.get_reading_parent(paper_id, current_sha)
                if indexed_job_id is not None:
                    try:
                        indexed = self._load(
                            indexed_job_id, expected_paper_id=paper_id
                        )
                        indexed_status = self.job_store.load_status(indexed_job_id)
                        if (
                            indexed_status.state == "completed"
                            and indexed.current_stage == "completed"
                            and indexed.source_pdf_sha256 == current_sha
                        ):
                            self._sync_library(indexed)
                            return indexed
                    except (
                        FileNotFoundError,
                        OSError,
                        ValueError,
                        json.JSONDecodeError,
                    ):
                        pass
                    library.clear_reading_parent(
                        paper_id, current_sha, indexed_job_id
                    )
            request = self._parent_request(paper_id, generation, provider_profile)
            handle = self.job_store.create_or_get(request)
            with self._init_claim(handle.job_id):
                state_path = handle.reading_pipeline_path
                if state_path.exists():
                    try:
                        state = self._load(handle.job_id, expected_paper_id=paper_id)
                    except (ValueError, json.JSONDecodeError) as error:
                        status = self.job_store.load_status(handle.job_id)
                        state = self._recover_completed_state(status, paper_id)
                        if state is None:
                            raise ValueError(
                                "reading_pipeline_artifact_inconsistent"
                            ) from error
                        self._save(state)
                    self._sync_library(state)
                    return state

                status = self.job_store.load_status(handle.job_id)
                state = self._recover_completed_state(status, paper_id)
                if state is not None:
                    self._save(state)
                    self._sync_library(state)
                    return state
                if status.state != "queued":
                    raise ValueError("reading_pipeline_artifact_inconsistent")
                now = _now()
                state = ReadingPipelineState(
                    paper_id=paper_id,
                    parent_job_id=handle.job_id,
                    created_at=now,
                    updated_at=now,
                )
                self._save(state)
                library.update_full_read_state(
                    paper_id, USER_STATUS["queued"], handle.job_id
                )
                if current_sha is not None:
                    library.set_reading_parent(
                        paper_id, current_sha, handle.job_id
                    )
                return state
        finally:
            library.close()

    def advance(
        self, parent_job_id: str, supplied_input: dict | None = None
    ) -> PipelineResult:
        with self.job_store.claim(parent_job_id, "reading_pipeline"):
            state = self._load(parent_job_id)
            if state.current_stage == "completed":
                self._sync_library(state)
                return state
            if (
                state.state in {"failed", "needs_user", "waiting_agent"}
                and supplied_input is None
            ):
                return state

            stage = state.current_stage
            state.state = stage
            state.required_action = None
            state.last_error = None
            if stage not in state.stage_timings:
                state.stage_timings[stage] = {
                    "started_at": _now(),
                    "finished_at": None,
                }
            state.updated_at = _now()
            self._save(state)
            self._sync_library(state)
            try:
                runner_state = ReadingPipelineState.from_dict(state.to_dict())
                if stage in _HEAVY_STAGES:
                    with self._heavy_claim():
                        output = self.stage_runner(stage, runner_state, supplied_input)
                else:
                    output = self.stage_runner(stage, runner_state, supplied_input)
                if not isinstance(output, dict):
                    raise ValueError("stage_output_not_json")
                normalized_output = self._normalize_stage_output(stage, output)
            except UserActionRequired as gate:
                return self._persist_gate(state, "needs_user", gate)
            except AgentRequired as gate:
                return self._persist_gate(state, "waiting_agent", gate)
            except Exception as error:
                if stage == "schedule_derived_updates":
                    state.stage_timings[stage]["finished_at"] = _now()
                    state.stage_outputs[stage] = {
                        "status": "failed",
                        "error": self._safe_error(error),
                    }
                    state.last_error = self._safe_error(error)
                    return self._complete(state)
                state.state = "failed"
                state.last_error = self._safe_error(error)
                return self._persist(state)

            state.stage_timings[stage]["finished_at"] = _now()
            state.stage_outputs[stage] = normalized_output
            stage_job = state.stage_outputs[stage].get("job_id")
            if isinstance(stage_job, str):
                state.stage_jobs[stage] = stage_job
            source_sha = state.stage_outputs[stage].get("source_pdf_sha256")
            reader_sha = state.stage_outputs[stage].get("reader_source_sha256")
            if isinstance(source_sha, str):
                state.source_pdf_sha256 = source_sha
                library = LibraryService(self.data_root)
                try:
                    library.set_reading_parent(
                        state.paper_id, source_sha, state.parent_job_id
                    )
                finally:
                    library.close()
            if isinstance(reader_sha, str):
                state.reader_source_sha256 = reader_sha
            index = PIPELINE_STAGES.index(stage)
            if index == len(PIPELINE_STAGES) - 1:
                return self._complete(state)
            state.current_stage = PIPELINE_STAGES[index + 1]
            state.state = "queued"
            return self._persist(state)

    def inspect(self, parent_job_id: str) -> PipelineResult:
        state = self._load(parent_job_id)
        status = self.job_store.load_status(parent_job_id)
        if (
            status.state == "running"
            and status.pid
            and not self.job_store._pid_is_alive(status.pid)
        ):
            self.job_store.transition(
                parent_job_id, "interrupted", error="worker_interrupted"
            )
            self.job_store.transition(parent_job_id, "queued")
            if state.state not in {"completed", "failed", "needs_user", "waiting_agent"}:
                state.state = "queued"
                self._save(state)
        self._sync_library(state)
        return state

    def _complete(self, state: ReadingPipelineState) -> ReadingPipelineState:
        state.current_stage = "completed"
        state.state = "completed"
        state.completed_at = _now()
        return self._persist(state)

    def _persist(self, state: ReadingPipelineState) -> ReadingPipelineState:
        state.updated_at = _now()
        self._save(state)
        self._sync_library(state)
        return state

    def _state_path(self, parent_job_id: str) -> Path:
        return self.job_store.handle(parent_job_id).reading_pipeline_path

    def _save(self, state: ReadingPipelineState) -> None:
        atomic_write_json(self._state_path(state.parent_job_id), state.to_dict())

    def _load(
        self,
        parent_job_id: str,
        *,
        expected_paper_id: str | None = None,
    ) -> ReadingPipelineState:
        value = json.loads(self._state_path(parent_job_id).read_text(encoding="utf-8"))
        if value.get("contract_version") != "reading-pipeline-v1":
            raise ValueError("reading_pipeline_contract_invalid")
        state = ReadingPipelineState.from_dict(value)
        self._validate_state(
            state,
            parent_job_id,
            expected_paper_id=expected_paper_id,
            job_state=self.job_store.load_status(parent_job_id).state,
        )
        return state

    def _parent_request(
        self, paper_id: str, source_pdf_sha256: str | None = None,
        provider_profile: str = "none",
    ) -> BackgroundRequest:
        generation = source_pdf_sha256 or "missing"
        return BackgroundRequest(
            paper_id=paper_id,
            target_stage="full_read_pipeline",
            input_hash=hashlib.sha256(
                f"{paper_id}\0{generation}".encode("utf-8")
            ).hexdigest(),
            payload={"data_root": str(self.data_root), "provider_profile": provider_profile},
        )

    @staticmethod
    def _validated_source_sha(path: Path, metadata) -> str | None:
        if not path.is_file():
            return None
        from .pdf_validation import validate_pdf

        result = validate_pdf(path, metadata)
        return result.sha256 if result.valid else None

    @classmethod
    def _validate_state(
        cls,
        state: ReadingPipelineState,
        parent_job_id: str,
        *,
        expected_paper_id: str | None,
        job_state: str,
    ) -> None:
        stages = set(PIPELINE_STAGES)
        allowed_states = stages | {
            "queued",
            "waiting_agent",
            "needs_user",
            "failed",
            "completed",
        }
        invalid = (
            state.parent_job_id != parent_job_id
            or (expected_paper_id is not None and state.paper_id != expected_paper_id)
            or state.current_stage not in stages | {"completed"}
            or state.state not in allowed_states
            or (state.current_stage == "completed") != (state.state == "completed")
            or (state.state in stages and state.state != state.current_stage)
        )
        expected_terminal = {
            "completed": "completed",
            "failed": "failed",
            "waiting_agent": "waiting_agent",
            "waiting_user": "needs_user",
        }.get(job_state)
        if expected_terminal is not None and state.state != expected_terminal:
            invalid = True
        if (
            not isinstance(state.stage_outputs, dict)
            or not isinstance(state.stage_jobs, dict)
            or any(
                stage not in stages
                or not isinstance(output, dict)
                or cls._normalize_stage_output(stage, output) != output
                for stage, output in state.stage_outputs.items()
            )
            or any(
                stage not in stages or not isinstance(job_id, str)
                for stage, job_id in state.stage_jobs.items()
            )
        ):
            invalid = True
        if not isinstance(state.stage_timings, dict):
            invalid = True
        else:
            try:
                for stage, timing in state.stage_timings.items():
                    if (
                        stage not in stages
                        or not isinstance(timing, dict)
                        or set(timing) != {"started_at", "finished_at"}
                        or not isinstance(timing["started_at"], str)
                    ):
                        invalid = True
                        break
                    started_at = datetime.fromisoformat(timing["started_at"])
                    finished_value = timing["finished_at"]
                    if started_at.tzinfo is None:
                        invalid = True
                        break
                    if finished_value is not None:
                        if not isinstance(finished_value, str):
                            invalid = True
                            break
                        finished_at = datetime.fromisoformat(finished_value)
                        if finished_at.tzinfo is None or finished_at < started_at:
                            invalid = True
                            break
            except (TypeError, ValueError):
                invalid = True
        if state.required_action is not None:
            try:
                reason_code = state.required_action.get("reason_code")
                required = {
                    key: value
                    for key, value in state.required_action.items()
                    if key != "reason_code"
                }
                if (
                    not isinstance(reason_code, str)
                    or cls._safe_output(reason_code) != reason_code
                    or cls._normalize_required_action(required) != required
                ):
                    invalid = True
            except (AttributeError, TypeError, ValueError):
                invalid = True
        if invalid:
            raise ValueError("reading_pipeline_state_invalid")

    def _recover_completed_state(
        self, status, paper_id: str
    ) -> ReadingPipelineState | None:
        if status.state != "completed" or not isinstance(status.result, dict):
            return None
        try:
            state = ReadingPipelineState.from_dict(self._safe_output(status.result))
            self._validate_state(
                state,
                status.job_id,
                expected_paper_id=paper_id,
                job_state=status.state,
            )
        except (TypeError, ValueError):
            return None
        if (
            state.contract_version != "reading-pipeline-v1"
            or state.paper_id != paper_id
            or state.parent_job_id != status.job_id
            or state.current_stage != "completed"
            or state.state != "completed"
        ):
            return None
        return state

    @contextmanager
    def _init_claim(self, parent_job_id: str):
        deadline = time.monotonic() + self.init_claim_timeout
        while True:
            claim = self.job_store.claim(parent_job_id, "reading_pipeline_init")
            try:
                claim.__enter__()
            except JobClaimUnavailable:
                if time.monotonic() >= deadline:
                    raise JobClaimUnavailable("精读父任务初始化忙") from None
                time.sleep(0.01)
                continue
            try:
                yield
            finally:
                claim.__exit__(None, None, None)
            return

    def _persist_gate(
        self, state: ReadingPipelineState, target_state: str, gate
    ) -> ReadingPipelineState:
        try:
            required = self._normalize_required_action(gate.required_input)
            reason_code = self._safe_output(gate.reason_code)
        except ValueError as error:
            state.state = "failed"
            state.required_action = None
            state.last_error = str(error)
            return self._persist(state)
        state.state = target_state
        state.required_action = {"reason_code": reason_code, **required}
        return self._persist(state)

    @classmethod
    def _normalize_stage_output(
        cls, stage: str, value: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = cls._safe_output(value)
        allowed = _STAGE_OUTPUT_FIELDS[stage]
        result = {key: item for key, item in normalized.items() if key in allowed}
        for key, item in result.items():
            if key in _OUTPUT_INTEGER_FIELDS:
                valid = isinstance(item, int) and not isinstance(item, bool)
            elif key in _OUTPUT_BOOLEAN_FIELDS:
                valid = isinstance(item, bool)
            else:
                valid = isinstance(item, str)
            if not valid:
                raise ValueError("stage_output_contract_invalid")
        return result

    @classmethod
    def _normalize_required_action(cls, value: Any) -> dict[str, Any]:
        normalized = cls._safe_output(value)
        if not isinstance(normalized, dict) or set(normalized) - _REQUIRED_ACTION_FIELDS:
            raise ValueError("required_action_contract_invalid")
        for key, item in normalized.items():
            if key == "options":
                valid = isinstance(item, list) and all(
                    isinstance(option, str) for option in item
                )
            elif key == "available_source_block_ids":
                valid = isinstance(item, list) and all(
                    isinstance(block_id, str) for block_id in item
                )
            elif key == "highlight_kinds":
                valid = (
                    isinstance(item, dict)
                    and set(item) == {"result", "method"}
                    and all(isinstance(value, str) for value in item.values())
                )
            elif key == "guide_limits":
                valid = (
                    isinstance(item, dict)
                    and set(item)
                    == {
                        "research_question",
                        "key_methods",
                        "core_results",
                        "limitations",
                    }
                    and all(
                        type(value) is int and value >= 0
                        for value in item.values()
                    )
                )
            elif key in _REQUIRED_ACTION_INTEGER_FIELDS:
                valid = isinstance(item, int) and not isinstance(item, bool)
            else:
                valid = isinstance(item, str)
            if not valid:
                raise ValueError("required_action_contract_invalid")
        return normalized

    @classmethod
    def _safe_output(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("stage_output_not_json")
                if any(part in key.casefold() for part in _SENSITIVE_KEY_PARTS):
                    continue
                normalized[key] = cls._safe_output(item)
            return normalized
        if isinstance(value, list):
            return [cls._safe_output(item) for item in value]
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, str):
            folded = value.casefold()
            if any(marker in folded for marker in _SENSITIVE_VALUE_MARKERS):
                raise ValueError("sensitive_stage_output")
            return value
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("stage_output_not_json")
        if value is None or isinstance(value, (bool, int, float)):
            return value
        raise ValueError("stage_output_not_json")

    @staticmethod
    def _safe_error(error: Exception) -> str:
        message = str(error)
        if any(part in message.casefold() for part in _SENSITIVE_KEY_PARTS):
            return "reading_stage_failed"
        return message

    def _sync_library(self, state: ReadingPipelineState) -> None:
        key = (
            state.state
            if state.state in {"queued", "needs_user", "failed"}
            else state.current_stage
        )
        if state.current_stage == "completed":
            key = "completed"
        library = LibraryService(self.data_root)
        try:
            library.update_full_read_state(
                state.paper_id,
                USER_STATUS.get(key, USER_STATUS["queued"]),
                state.parent_job_id,
                error=state.last_error,
            )
        finally:
            library.close()

    @contextmanager
    def _heavy_claim(self):
        lock = self.data_root / "jobs" / ".full_read_heavy"
        while True:
            try:
                lock.mkdir()
                atomic_write_json(
                    lock / "owner.json",
                    {"pid": os.getpid(), "created_at": _now()},
                )
                break
            except FileExistsError:
                if self.job_store._stale_pid_lock(lock):
                    stale = lock.with_name(f"{lock.name}.{uuid.uuid4().hex}.stale")
                    try:
                        lock.replace(stale)
                        shutil.rmtree(stale, ignore_errors=True)
                        continue
                    except OSError:
                        pass
                time.sleep(0.01)
        try:
            yield
        finally:
            shutil.rmtree(lock, ignore_errors=True)
