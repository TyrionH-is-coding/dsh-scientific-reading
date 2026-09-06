from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from scientific_reading.assets import AssetManifest
from scientific_reading.export_service import ExportService
from scientific_reading.full_read_models import FULL_TRANSLATION_CONTRACT_VERSION
from scientific_reading.full_read_renderer import (
    READER_BUILD_VERSION,
    FullReadRenderer,
)
from scientific_reading.full_read_service import FullReadError, FullReadService
from scientific_reading.mineru_models import MINERU_NORMALIZATION_VERSION
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace, atomic_write_json
from scripts.reader_review_fixtures import (
    FIXTURE_CASES,
    fixture_path,
    materialize_fixture,
)


SESSION_CONTRACT = "reader-review-session-v1"
MANIFEST_CONTRACT = "reader-review-manifest-v1"
_CASE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LEGACY_NORMALIZATION_VERSION = "mineru-normalization-v2"
_REVIEW_CACHE_PROVIDER_VERSION = "reader-review-cache-v1"


class ReviewRenderError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewRenderError("review_session_invalid") from error
    if not isinstance(payload, dict):
        raise ReviewRenderError("review_session_invalid")
    return payload


def _git_commit(repository_root: Path) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=flags,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ReviewRenderError("repository_commit_unavailable")
    return value


def _validate_case_key(value: str) -> str:
    if _CASE_PATTERN.fullmatch(value) is None or ".." in value:
        raise ReviewRenderError("paper_id_invalid")
    return value


def _validate_review_root(
    review_root: Path,
    repository_root: Path,
    data_root: Path | None,
) -> Path:
    root = Path(review_root).resolve()
    repository = Path(repository_root).resolve()
    if root == repository or root.is_relative_to(repository):
        raise ReviewRenderError("review_root_inside_repository")
    if data_root is not None:
        data = Path(data_root).resolve()
        if root == data or root.is_relative_to(data):
            raise ReviewRenderError("review_root_inside_data_root")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _formal_reader(
    workspace: PaperWorkspace,
    *,
    paper_id: str,
    source_sha256: str,
) -> tuple[Path, str | None]:
    if workspace.reader_html.is_file():
        if not workspace.reader_manifest.is_file():
            raise ReviewRenderError("source_reader_manifest_missing")
        try:
            FullReadRenderer._validate_staged_reader(
                workspace.reader_html,
                workspace.reader_manifest,
            )
            manifest = _read_json(workspace.reader_manifest)
        except (OSError, ValueError) as error:
            raise ReviewRenderError("source_reader_invalid") from error
        if (
            manifest.get("paper_id") != paper_id
            or manifest.get("source_pdf_sha256") != source_sha256
        ):
            raise ReviewRenderError("source_reader_invalid")
        return workspace.reader_html, _sha256(workspace.reader_manifest)
    compatible = workspace.output_dir / "reader_full.html"
    if compatible.is_file():
        try:
            rendered = compatible.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ReviewRenderError("source_reader_invalid") from error
        if not FullReadRenderer._is_self_contained(rendered):
            raise ReviewRenderError("source_reader_invalid")
        stage = workspace.load_job().stages.get("full_read")
        if stage is None or stage.status != "completed":
            raise ReviewRenderError("source_reader_invalid")
        return compatible, None
    raise ReviewRenderError("source_reader_missing")


def _resolve_real_source(
    data_root: Path,
    paper_id: str,
) -> tuple[PaperWorkspace, Path, dict[str, Any]]:
    validated_id = _validate_case_key(paper_id)
    root = Path(data_root).resolve()
    base_root = root / "papers" / validated_id
    if base_root.is_symlink():
        raise ReviewRenderError("source_generation_invalid")
    try:
        metadata = PaperMetadata.from_dict(
            json.loads((base_root / "metadata.json").read_text(encoding="utf-8"))
        )
        base = PaperWorkspace(base_root)
        stage = base.load_job().stages.get("paper_parse_upgrade")
        if stage is None:
            raise ValueError("active_generation_required")
        relative = stage.result.get("active_workspace")
        if not isinstance(relative, str):
            raise ValueError("active_generation_required")
        candidate = base.root / relative
        if candidate.is_symlink():
            raise ValueError("active_generation_symlink")
        selected, source_sha, _method, _version = ExportService._active_workspace(
            base,
            metadata,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise ReviewRenderError("source_generation_invalid") from error
    generation_root = (base.root / "generations").resolve()
    if (
        selected.root == base.root
        or selected.root.parent != generation_root
        or selected.root.name != source_sha[:16]
    ):
        raise ReviewRenderError("source_generation_invalid")
    reader, reader_manifest_sha = _formal_reader(
        selected,
        paper_id=validated_id,
        source_sha256=source_sha,
    )
    record = {
        "kind": "paper",
        "fixture": None,
        "paper_id": validated_id,
        "data_root": str(root),
        "source_generation": str(selected.root),
        "generation_relative": selected.root.relative_to(base.root).as_posix(),
        "source_pdf_sha256": source_sha,
        "source_reader_sha256": _sha256(reader),
        "source_reader_manifest_sha256": reader_manifest_sha,
    }
    return selected, reader, record


def _load_legacy_preview_source(
    workspace: PaperWorkspace,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    parsed_root = workspace.parsed_dir / "mineru"
    source_map_path = parsed_root / "source_map.json"
    report_path = parsed_root / "parse_report.json"
    translation_path = workspace.reading_dir / "full" / "translations.json"
    guide_path = workspace.reading_dir / "full" / "reading_guide.json"
    highlights_path = workspace.reading_dir / "full" / "highlights.json"
    try:
        source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        translations = json.loads(
            translation_path.read_text(encoding="utf-8")
        )
        reader_manifest = json.loads(
            workspace.reader_manifest.read_text(encoding="utf-8")
        )
        state = workspace.load_job()
        parse_stage = state.stages["paper_parse_upgrade"]
        full_stage = state.stages["full_read"]
        source_sha = _sha256(workspace.source_pdf)
        raw_hash = source_map["raw_content_list_sha256"]
        raw_root = parsed_root / "raw"
        candidates = [
            path
            for path in raw_root.rglob("*_content_list.json")
            if path.is_file() and not path.is_symlink()
        ]
        raw_files = [path for path in raw_root.rglob("*") if path.is_file()]
        resolved_raw = raw_root.resolve()
        if (
            not isinstance(source_map, dict)
            or not isinstance(report, dict)
            or not isinstance(translations, dict)
            or not isinstance(reader_manifest, dict)
            or parse_stage.status != "completed"
            or full_stage.status != "completed"
            or reader_manifest.get("contract") != "reader-manifest-v1"
            or reader_manifest.get("source_pdf_sha256") != source_sha
            or reader_manifest.get("parser_manifest_sha256")
            != _sha256(source_map_path)
            or reader_manifest.get("translation_manifest_sha256")
            != _sha256(translation_path)
            or reader_manifest.get("reading_guide_sha256")
            != _sha256(guide_path)
            or reader_manifest.get("highlights_manifest_sha256")
            != _sha256(highlights_path)
            or reader_manifest.get("reader_revision")
            != full_stage.result.get("reader_revision")
            or reader_manifest.get("reader_build_version")
            != full_stage.result.get("reader_build_version")
            or reader_manifest.get("review") != full_stage.result.get("review")
            or translations.get("contract_version")
            != FULL_TRANSLATION_CONTRACT_VERSION
            or translations.get("source_sha256") != source_sha
            or not isinstance(translations.get("translations"), list)
            or len(candidates) != 1
            or not isinstance(raw_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", raw_hash) is None
            or _sha256(candidates[0]) != raw_hash
            or any(
                path.is_symlink()
                or not path.resolve().is_relative_to(resolved_raw)
                for path in raw_files
            )
        ):
            raise ValueError("legacy preview identity mismatch")
        identity = {
            "version": source_map.get("version"),
            "parser": "mineru",
            "parser_version": parse_stage.result.get("mineru_version"),
            "source_sha256": source_sha,
            "raw_content_list_sha256": raw_hash,
            "method": parse_stage.result.get("method"),
        }
        if any(
            payload.get(key) != value
            for payload in (source_map, report)
            for key, value in identity.items()
        ):
            raise ValueError("legacy preview parser identity mismatch")
        review = full_stage.result.get("review")
        if not isinstance(review, dict):
            raise ValueError("legacy preview review missing")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise ReviewRenderError("legacy_preview_source_invalid") from error
    return source_map, translations, reader_manifest, review


def _write_preview_translation_batches(
    service: FullReadService,
    workspace: PaperWorkspace,
    translations: dict[str, Any],
) -> None:
    configured = {
        row["block_id"]: row for row in translations["translations"]
    }
    if len(configured) != len(translations["translations"]):
        raise ValueError("legacy preview translation identity mismatch")
    active = service._inspect_active_mineru(workspace)
    if [
        (row["block_id"], row["english"]) for row in active.rows
    ] != [
        (row["block_id"], row["source_text"])
        for row in translations["translations"]
    ]:
        raise ValueError("legacy preview translation identity mismatch")
    plan = service.prepare(workspace)
    full_root = workspace.reading_dir / "full"
    for batch in plan.plan["batches"]:
        source = json.loads(
            (full_root / batch["source_file"]).read_text(encoding="utf-8")
        )
        service.save_translation_batch(
            workspace,
            {
                "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
                "batch_id": source["batch_id"],
                "source_sha256": source["source_sha256"],
                "translations": [
                    {
                        "block_id": row["block_id"],
                        "source_text": row["english"],
                        "translation_zh": configured[row["block_id"]][
                            "translation_zh"
                        ],
                        "highlight": configured[row["block_id"]]["highlight"],
                    }
                    for row in source["blocks"]
                ],
            },
        )


def _rehydrate_preview_workspace(
    source: PaperWorkspace,
    target_root: Path,
    *,
    paper_id: str,
) -> PaperWorkspace:
    source_map, translations, reader_manifest, review = (
        _load_legacy_preview_source(source)
    )
    if source_map.get("version") not in {
        _LEGACY_NORMALIZATION_VERSION,
        MINERU_NORMALIZATION_VERSION,
    }:
        raise ReviewRenderError("legacy_preview_source_invalid")
    try:
        target_root.mkdir()
        workspace = PaperWorkspace(root=target_root)
        for directory in (
            workspace.parsed_images,
            workspace.parsed_tables,
            workspace.reading_dir,
            workspace.output_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.metadata_path, workspace.metadata_path)
        shutil.copy2(source.source_pdf, workspace.source_pdf)
        parsed_root = workspace.parsed_dir / "mineru"
        raw_root = parsed_root / "raw"
        shutil.copytree(source.parsed_dir / "mineru" / "raw", raw_root)
        metadata = PaperMetadata.from_dict(
            json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        )
        source_sha = _sha256(workspace.source_pdf)
        parser_version = source_map["parser_version"]
        method = source_map["method"]
        normalized = MineruNormalizer(parser_version).normalize(
            raw_root,
            parsed_root,
            metadata,
            source_sha,
        )
        for name in ("source_map.json", "parse_report.json"):
            path = parsed_root / name
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["method"] = method
            if name == "parse_report.json":
                payload["provider"] = "mineru-local-v1"
                payload["provider_version"] = _REVIEW_CACHE_PROVIDER_VERSION
            atomic_write_json(path, payload)
        manifest = AssetManifest(workspace.manifest_path)
        for asset in normalized.assets:
            manifest.upsert(asset)
        workspace.save_job(
            JobState(
                paper_id=paper_id,
                status="parsed",
                stages={
                    "paper_parse_upgrade": StageRecord(
                        status="completed",
                        result={
                            "active_parsed_dir": "parsed/mineru",
                            "source_sha256": source_sha,
                            "method": method,
                            "mineru_version": parser_version,
                        },
                    )
                },
            )
        )
        service = FullReadService()
        _write_preview_translation_batches(service, workspace, translations)
        service.finalize(workspace, review)
        FullReadRenderer().render_completed(workspace, paper_id=paper_id)
        rebuilt_manifest = json.loads(
            workspace.reader_manifest.read_text(encoding="utf-8")
        )
        if (
            rebuilt_manifest.get("source_pdf_sha256")
            != reader_manifest.get("source_pdf_sha256")
            or rebuilt_manifest.get("source_blocks")
            != reader_manifest.get("source_blocks")
            or rebuilt_manifest.get("assets") != reader_manifest.get("assets")
        ):
            raise ValueError("legacy preview normalized identity mismatch")
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        FullReadError,
    ) as error:
        raise ReviewRenderError("legacy_preview_source_invalid") from error
    return workspace


@contextmanager
def _preview_workspace(
    source: PaperWorkspace,
    source_record: dict[str, Any],
) -> Iterator[PaperWorkspace]:
    if source_record["kind"] != "paper":
        yield source
        return
    try:
        source_map = json.loads(
            (source.parsed_dir / "mineru" / "source_map.json").read_text(
                encoding="utf-8"
            )
        )
        full_stage = source.load_job().stages["full_read"]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
    ) as error:
        raise ReviewRenderError("source_generation_invalid") from error
    if (
        source_map.get("version") == MINERU_NORMALIZATION_VERSION
        and full_stage.result.get("reader_build_version")
        == READER_BUILD_VERSION
    ):
        yield source
        return
    temporary_parent = Path(tempfile.gettempdir()) / (
        f"srp-{uuid.uuid4().hex[:8]}"
    )
    try:
        temporary_parent.mkdir()
        yield _rehydrate_preview_workspace(
            source,
            temporary_parent / source_record["paper_id"],
            paper_id=source_record["paper_id"],
        )
    finally:
        resolved_parent = temporary_parent.resolve()
        resolved_temp = Path(tempfile.gettempdir()).resolve()
        if (
            temporary_parent.exists()
            and resolved_parent.parent == resolved_temp
            and temporary_parent.name.startswith("srp-")
        ):
            shutil.rmtree(temporary_parent)


@contextmanager
def _fixture_source(
    review_root: Path,
    case: str,
) -> Iterator[tuple[PaperWorkspace, Path, dict[str, Any]]]:
    if case not in FIXTURE_CASES:
        raise ReviewRenderError("fixture_case_invalid")
    source_parent = review_root / ".sources"
    source_parent.mkdir(parents=True, exist_ok=True)
    temporary = source_parent / f"source-{uuid.uuid4().hex}"
    try:
        workspace = materialize_fixture(case, temporary)
        reader = workspace.output_dir / "reader_full.html"
        record = {
            "kind": "fixture",
            "fixture": fixture_path(case).relative_to(
                Path(__file__).resolve().parents[1]
            ).as_posix(),
            "paper_id": f"fixture_{case.replace('-', '_')}",
            "data_root": None,
            "source_generation": None,
            "generation_relative": None,
            "source_pdf_sha256": _sha256(workspace.source_pdf),
            "source_reader_sha256": _sha256(reader),
            "source_reader_manifest_sha256": None,
        }
        yield workspace, reader, record
    finally:
        resolved_parent = source_parent.resolve()
        resolved_temporary = temporary.resolve()
        if (
            temporary.exists()
            and resolved_temporary.parent == resolved_parent
            and temporary.name.startswith("source-")
        ):
            shutil.rmtree(temporary)


@contextmanager
def _review_source(
    *,
    review_root: Path,
    case: str | None,
    paper_id: str | None,
    data_root: Path | None,
    previous_session: dict[str, Any] | None,
) -> Iterator[tuple[str, PaperWorkspace, Path, dict[str, Any]]]:
    selected_case = case or paper_id
    previous_record: dict[str, Any] | None = None
    if selected_case is None:
        if previous_session is None:
            raise ReviewRenderError("review_source_required")
        selected_case = previous_session.get("selected_case")
        if not isinstance(selected_case, str):
            raise ReviewRenderError("review_session_invalid")
        cases = previous_session.get("cases")
        if not isinstance(cases, dict) or not isinstance(
            cases.get(selected_case), dict
        ):
            raise ReviewRenderError("review_session_invalid")
        previous_record = cases[selected_case]
    selected_case = _validate_case_key(selected_case)
    if case is not None or (
        previous_record is not None and previous_record.get("kind") == "fixture"
    ):
        if case is None:
            fixture_value = previous_record.get("fixture")
            if not isinstance(fixture_value, str):
                raise ReviewRenderError("review_session_invalid")
            case = Path(fixture_value).stem
        with _fixture_source(review_root, case) as source:
            workspace, reader, record = source
            yield selected_case, workspace, reader, record
        return
    if paper_id is None:
        if previous_record is None or previous_record.get("kind") != "paper":
            raise ReviewRenderError("review_session_invalid")
        paper_id = previous_record.get("paper_id")
        stored_data_root = previous_record.get("data_root")
        if not isinstance(paper_id, str) or not isinstance(stored_data_root, str):
            raise ReviewRenderError("review_session_invalid")
        data_root = Path(stored_data_root)
    if data_root is None:
        raise ReviewRenderError("data_root_required")
    workspace, reader, record = _resolve_real_source(data_root, paper_id)
    yield selected_case, workspace, reader, record


def _default_tests() -> dict[str, Any]:
    return {
        "status": "pending",
        "passed": 0,
        "failed": 0,
        "summary": "尚未运行 reader 定向测试",
    }


def _default_browser_qa() -> dict[str, Any]:
    return {
        "status": "pending",
        "checks": [
            {"id": "desktop", "label": "桌面布局", "status": "pending"},
            {"id": "tablet", "label": "平板布局", "status": "pending"},
            {"id": "mobile", "label": "手机布局", "status": "pending"},
        ],
    }


def _load_existing(
    review_root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    session_path = review_root / "session.json"
    manifest_path = review_root / "review-manifest.json"
    if not session_path.exists() and not manifest_path.exists():
        return None, None
    if not session_path.is_file() or not manifest_path.is_file():
        raise ReviewRenderError("review_session_invalid")
    session = _read_json(session_path)
    manifest = _read_json(manifest_path)
    if (
        session.get("contract_version") != SESSION_CONTRACT
        or manifest.get("contract_version") != MANIFEST_CONTRACT
        or not isinstance(session.get("cases"), dict)
        or not isinstance(manifest.get("cases"), dict)
        or not isinstance(manifest.get("revision"), int)
    ):
        raise ReviewRenderError("review_session_invalid")
    return session, manifest


def render_review_case(
    *,
    review_root: Path,
    repository_root: Path,
    case: str | None = None,
    paper_id: str | None = None,
    data_root: Path | None = None,
    new_session: bool = False,
) -> dict[str, Any]:
    if case is not None and paper_id is not None:
        raise ReviewRenderError("review_source_ambiguous")
    repository = Path(repository_root).resolve()
    if not (repository / "package.json").is_file():
        raise ReviewRenderError("repository_root_invalid")
    root = _validate_review_root(review_root, repository, data_root)
    previous_session, previous_manifest = _load_existing(root)
    if new_session and case is None and paper_id is None and previous_session is None:
        raise ReviewRenderError("review_source_required")
    commit = _git_commit(repository)
    started = time.perf_counter()
    target_revision = (
        int(previous_manifest["revision"]) + 1
        if previous_manifest is not None
        else 1
    )
    session = (
        {
            "contract_version": SESSION_CONTRACT,
            "session_id": uuid.uuid4().hex,
            "repository_root": str(repository),
            "baseline_commit": commit,
            "created_at": _now(),
            "selected_case": "",
            "cases": {},
        }
        if new_session or previous_session is None
        else json.loads(json.dumps(previous_session))
    )
    manifest = (
        {
            "contract_version": MANIFEST_CONTRACT,
            "revision": target_revision,
            "status": "building",
            "candidate_stale": False,
            "repository_commit": commit,
            "built_at": _now(),
            "selected_case": "",
            "cases": {},
            "tests": _default_tests(),
            "browser_qa": _default_browser_qa(),
        }
        if new_session or previous_manifest is None
        else json.loads(json.dumps(previous_manifest))
    )
    manifest["revision"] = target_revision
    manifest["status"] = "building"
    manifest["candidate_stale"] = False
    manifest["repository_commit"] = commit
    manifest["built_at"] = _now()
    build_root = root / f".build-{uuid.uuid4().hex}"
    build_root.mkdir()
    selected_case = ""
    source_load_finished = started
    try:
        with _review_source(
            review_root=root,
            case=case,
            paper_id=paper_id,
            data_root=data_root,
            previous_session=previous_session,
        ) as (selected_case, workspace, source_reader, source_record):
            source_load_finished = time.perf_counter()
            candidate_staging = build_root / "reader.html"
            render_started = time.perf_counter()
            with _preview_workspace(
                workspace,
                source_record,
            ) as preview_workspace:
                FullReadRenderer().render_preview_completed(
                    preview_workspace,
                    output=candidate_staging,
                    paper_id=source_record["paper_id"],
                )
            render_finished = time.perf_counter()
            candidate_text = candidate_staging.read_text(encoding="utf-8")
            if not FullReadRenderer._is_self_contained(candidate_text):
                raise ReviewRenderError("candidate_remote_resource_forbidden")
            candidate_payload = candidate_staging.read_bytes()
            baseline_target = root / "baseline" / selected_case / "reader.html"
            candidate_target = root / "candidate" / selected_case / "reader.html"
            case_exists = selected_case in session["cases"]
            if not new_session and case_exists and not baseline_target.is_file():
                raise ReviewRenderError("baseline_missing")
            needs_baseline = (
                new_session
                or not case_exists
            )
            if needs_baseline:
                baseline_payload = source_reader.read_bytes()
                try:
                    baseline_text = baseline_payload.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ReviewRenderError("source_reader_invalid") from error
                if not FullReadRenderer._is_self_contained(baseline_text):
                    raise ReviewRenderError("source_reader_invalid")
                _atomic_write_bytes(baseline_target, baseline_payload)
            _atomic_write_bytes(candidate_target, candidate_payload)
            write_finished = time.perf_counter()
            source_record["source_reader_sha256"] = _sha256(source_reader)
            session["selected_case"] = selected_case
            session["cases"][selected_case] = source_record
            manifest["selected_case"] = selected_case
            manifest["status"] = "ready"
            manifest["candidate_stale"] = False
            manifest["cases"][selected_case] = {
                "baseline_url": (
                    f"/content/baseline/{selected_case}/reader.html"
                ),
                "candidate_url": (
                    f"/content/candidate/{selected_case}/reader.html"
                    f"?revision={target_revision}"
                ),
                "candidate_sha256": hashlib.sha256(
                    candidate_payload
                ).hexdigest(),
                "render_status": "passed",
                "error_code": None,
                "timings_ms": {
                    "source_load": round(
                        (source_load_finished - started) * 1000
                    ),
                    "render": round(
                        (render_finished - render_started) * 1000
                    ),
                    "write": round(
                        (write_finished - render_finished) * 1000
                    ),
                    "total": round((write_finished - started) * 1000),
                },
            }
            manifest["tests"] = _default_tests()
            manifest["browser_qa"] = _default_browser_qa()
            _atomic_write_json(root / "session.json", session)
            _atomic_write_json(root / "review-manifest.json", manifest)
            return manifest
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        if previous_manifest is None or new_session:
            if isinstance(error, ReviewRenderError):
                raise
            raise ReviewRenderError("candidate_render_failed") from error
        failed = json.loads(json.dumps(previous_manifest))
        failed["revision"] = target_revision
        failed["status"] = "failed"
        failed["candidate_stale"] = True
        failed["repository_commit"] = commit
        failed["built_at"] = _now()
        if selected_case:
            failed["selected_case"] = selected_case
            entry = failed.get("cases", {}).get(selected_case)
            if isinstance(entry, dict):
                entry["render_status"] = "failed"
                entry["error_code"] = (
                    error.code
                    if isinstance(error, ReviewRenderError)
                    else "candidate_render_failed"
                )
                timings = entry.get("timings_ms")
                if isinstance(timings, dict):
                    timings["total"] = round(
                        (time.perf_counter() - started) * 1000
                    )
        _atomic_write_json(root / "review-manifest.json", failed)
        return failed
    finally:
        resolved_root = root.resolve()
        resolved_build = build_root.resolve()
        if (
            build_root.exists()
            and resolved_build.parent == resolved_root
            and build_root.name.startswith(".build-")
        ):
            shutil.rmtree(build_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成 Reader 开发审核候选")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--case", choices=FIXTURE_CASES)
    source.add_argument("--paper-id")
    source.add_argument("--current-session", action="store_true")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "dsh-scientific-reading-review",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--new-session", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = render_review_case(
            review_root=args.review_root,
            repository_root=args.repository_root,
            case=args.case,
            paper_id=args.paper_id,
            data_root=args.data_root,
            new_session=args.new_session,
        )
    except ReviewRenderError as error:
        print(
            json.dumps(
                {"ok": False, "error_code": error.code},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0 if manifest["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
