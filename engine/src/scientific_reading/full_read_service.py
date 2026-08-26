from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reader.build_reader import READER_BUILD_VERSION

from . import __version__
from .full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
    FullReviewSubmission,
    Translation,
    TranslationBatchSubmission,
)
from .full_read_renderer import FullReadRenderer
from .identifiers import stable_paper_id
from .models import PaperMetadata, StageRecord
from .parse_models import SourceBlock
from .mineru_artifacts import MineruArtifactValidator, active_parsed_root
from .workspace import PaperWorkspace


FULL_READ_PLAN_CONTRACT_VERSION = "full-read-plan-v1"
FULL_READ_SOURCE_CONTRACT_VERSION = "full-read-source-v1"
FULL_READ_PROMPT_VERSION = "codex-full-translation-v1"
_MAX_BATCH_BLOCKS = 40
_MAX_BATCH_BYTES = 64 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write_json_lf(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        _json_bytes(value).decode("utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


class FullReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FullReadPlanResult:
    plan: dict[str, Any]
    batch_paths: tuple[Path, ...]
    cached: bool


@dataclass(frozen=True, slots=True)
class _ActiveMineru:
    metadata: PaperMetadata
    source_sha256: str
    source_map_sha256: str
    normalization_version: str
    mineru_parser_version: str
    blocks: tuple[SourceBlock, ...]
    rows: tuple[dict[str, Any], ...]


class FullReadService:
    def __init__(self) -> None:
        self._prepared: dict[Path, FullReadPlanResult] = {}

    def prepare(self, workspace: PaperWorkspace) -> FullReadPlanResult:
        active = self._inspect_active_mineru(workspace)
        batches = self._build_batches(active)
        plan = self._build_plan(active, batches)
        full_root = workspace.reading_dir / "full"
        if full_root.exists():
            self._validate_cache(full_root, plan, batches)
            self._record_plan_state(
                workspace,
                active,
                plan,
                cached=True,
            )
            result = FullReadPlanResult(
                plan=plan,
                batch_paths=tuple(
                    full_root / batch["source_file"]
                    for batch in plan["batches"]
                ),
                cached=True,
            )
            self._prepared[workspace.root] = result
            return result

        staging = (
            workspace.reading_dir / f".full-plan-{uuid.uuid4().hex}"
        )
        try:
            for batch in batches:
                path = staging / batch["source_file"]
                _atomic_write_json_lf(path, batch["payload"])
            _atomic_write_json_lf(staging / "translation_plan.json", plan)
            self._validate_cache(staging, plan, batches)
            staging.replace(full_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        self._record_plan_state(
            workspace,
            active,
            plan,
            cached=False,
        )
        result = FullReadPlanResult(
            plan=plan,
            batch_paths=tuple(
                full_root / batch["source_file"]
                for batch in plan["batches"]
            ),
            cached=False,
        )
        self._prepared[workspace.root] = result
        return result

    def next_batch(
        self,
        workspace: PaperWorkspace,
    ) -> dict[str, Any] | None:
        result = self._prepared.get(workspace.root)
        if result is None:
            result = self.prepare(workspace)
        root = workspace.reading_dir / "full"
        pending: dict[str, Any] | None = None
        for batch in result.plan["batches"]:
            source_path = root / batch["source_file"]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["oversized"] = bool(batch["oversized"])
            translation_path = root / batch["translation_file"]
            if not translation_path.exists():
                if pending is None:
                    pending = source
                continue
            if pending is not None:
                raise FullReadError("full_read_artifact_inconsistent")
            try:
                submission = TranslationBatchSubmission.from_dict(
                    json.loads(
                        translation_path.read_text(encoding="utf-8")
                    ),
                    expected_blocks=tuple(source["blocks"]),
                    expected_batch_id=batch["batch_id"],
                    expected_source_sha256=source["source_sha256"],
                )
            except (OSError, json.JSONDecodeError, ValueError) as error:
                raise FullReadError(
                    "full_read_artifact_inconsistent"
                ) from error
            if submission.to_dict() != json.loads(
                translation_path.read_text(encoding="utf-8")
            ):
                raise FullReadError("full_read_artifact_inconsistent")
        return pending

    def save_next_translation(
        self,
        workspace: PaperWorkspace,
        value: dict[str, Any],
    ) -> Path:
        source = self.next_batch(workspace)
        if source is None:
            raise ValueError("full_translation_already_complete")
        return self.save_translation_batch(workspace, value)

    def save_translation_batch(
        self,
        workspace: PaperWorkspace,
        value: dict[str, Any],
    ) -> Path:
        result = self._prepared.get(workspace.root) or self.prepare(workspace)
        batch_id = value.get("batch_id") if isinstance(value, dict) else None
        batch = next(
            (
                candidate
                for candidate in result.plan["batches"]
                if candidate["batch_id"] == batch_id
            ),
            None,
        )
        if batch is None:
            raise ValueError("translation_batch_mismatch")
        root = workspace.reading_dir / "full"
        source = json.loads(
            (root / batch["source_file"]).read_text(encoding="utf-8")
        )
        submission = TranslationBatchSubmission.from_dict(
            value,
            expected_blocks=tuple(source["blocks"]),
            expected_batch_id=source["batch_id"],
            expected_source_sha256=source["source_sha256"],
        )
        destination = (
            root / batch["translation_file"]
        )
        if destination.exists():
            first_missing = next(
                (
                    index
                    for index, candidate in enumerate(result.plan["batches"])
                    if not (root / candidate["translation_file"]).exists()
                ),
                len(result.plan["batches"]),
            )
            target_index = result.plan["batches"].index(batch)
            if target_index >= first_missing:
                raise ValueError("translation_batch_not_current")
        current = self.next_batch(workspace)
        if destination.exists():
            try:
                existing = json.loads(destination.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise FullReadError("full_read_artifact_inconsistent") from error
            if existing == submission.to_dict():
                return destination
            raise FullReadError("translation_batch_conflict")
        if current is None:
            raise ValueError("full_translation_already_complete")
        if current["batch_id"] != batch_id:
            raise ValueError("translation_batch_not_current")
        _atomic_write_json_lf(destination, submission.to_dict())
        state = workspace.load_job()
        state.status = (
            "reviewing_full_read"
            if self.next_batch(workspace) is None
            else "translating_full_read"
        )
        stage = state.stages.get("full_read")
        if stage is not None:
            stage.result["completed_batches"] = len(
                list(
                    (root / "batches").glob(
                        "*.translation.json"
                    )
                )
            )
        workspace.save_job(state)
        return destination

    def review_context(
        self,
        workspace: PaperWorkspace,
    ) -> dict[str, Any]:
        active, translations = self._collect_translations(workspace)
        destination = workspace.reading_dir / "full" / "translations.json"
        payload = {
            "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
            "source_sha256": active.source_sha256,
            "translations": [
                {
                    "block_id": translation.block_id,
                    "source_text": translation.source_text,
                    "translation_zh": translation.translation_zh,
                    "highlight": translation.highlight,
                }
                for translation in translations.values()
            ],
        }
        state = workspace.load_job()
        if state.status != "full_read_ready":
            _atomic_write_json_lf(destination, payload)
            state.status = "reviewing_full_read"
            stage = state.stages.get("full_read")
            if stage is not None:
                stage.result["status"] = state.status
                stage.result["completed_batches"] = len(
                    self._prepared[workspace.root].plan["batches"]
                )
            workspace.save_job(state)
        substantive_count = sum(
            row["source_type"] not in {"header", "reference"}
            for row in active.rows
        )
        available_source_block_ids = [
            row["block_id"]
            for row in active.rows
            if row["source_type"] not in {"header", "reference"}
        ]
        total_limit = int(substantive_count * 0.25)
        return {
            "contract_version": FULL_REVIEW_CONTRACT_VERSION,
            "translations_json": str(destination),
            "source_map_json": str(
                workspace.parsed_dir / "mineru" / "source_map.json"
            ),
            "translation_count": len(translations),
            "substantive_block_count": substantive_count,
            "maximum_full_review_highlights": total_limit,
            "available_source_block_ids": available_source_block_ids,
            "highlight_kinds": {
                "result": "核心结果、结论或创新",
                "method": "关键方法、实验设计或支撑证据",
            },
            "guide_limits": {
                "research_question": 1,
                "key_methods": 2,
                "core_results": 3,
                "limitations": 2,
            },
            "target_highlight_ratio": "10%-15%",
            "maximum_highlight_ratio": "25%",
        }

    def finalize(
        self,
        workspace: PaperWorkspace,
        review_value: dict[str, Any],
    ) -> dict[str, Any]:
        context = self.review_context(workspace)
        active, translations = self._collect_translations(workspace)
        substantive_count = context["substantive_block_count"]
        review = FullReviewSubmission.from_dict(
            review_value,
            available_block_ids={
                row["block_id"]
                for row in active.rows
                if row["source_type"] not in {"header", "reference"}
            },
            substantive_block_count=substantive_count,
        )
        highlights = {
            item.block_id: (item.highlight, "全文翻译标注")
            for item in translations.values()
            if item.highlight != "none"
        }
        for item in review.highlights:
            highlights.setdefault(
                item.block_id,
                (item.kind, item.reason),
            )
        if len(highlights) > int(substantive_count * 0.25):
            raise ValueError("full_review_highlight_limit")
        root = workspace.reading_dir / "full"
        highlights_payload = {
            "contract_version": FULL_REVIEW_CONTRACT_VERSION,
            "highlights": [
                {
                    "block_id": block_id,
                    "kind": kind,
                    "reason": reason,
                }
                for block_id, (kind, reason) in highlights.items()
            ],
        }
        output = workspace.output_dir / "reader_full.html"
        translation_payload = {
            "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
            "source_sha256": active.source_sha256,
            "translations": [
                {
                    "block_id": item.block_id,
                    "source_text": item.source_text,
                    "translation_zh": item.translation_zh,
                    "highlight": item.highlight,
                }
                for item in translations.values()
            ],
        }
        final_identity = {
            "reader_build_version": READER_BUILD_VERSION,
            "source_sha256": active.source_sha256,
            "source_map_sha256": active.source_map_sha256,
            "translations": translation_payload["translations"],
            "highlights": highlights_payload["highlights"],
            "review": review.to_dict(),
        }
        final_input_hash = hashlib.sha256(
            _json_bytes(final_identity)
        ).hexdigest()
        reader_revision = final_input_hash
        guide_payload = {
            "contract_version": FULL_REVIEW_CONTRACT_VERSION,
            "reader_revision": reader_revision,
            "guide": review.to_dict()["guide"],
        }
        staging = workspace.reading_dir / (
            f".full-publish-{uuid.uuid4().hex}"
        )
        staging.mkdir()
        try:
            _atomic_write_json_lf(
                staging / "translations.json",
                translation_payload,
            )
            _atomic_write_json_lf(
                staging / "highlights.json",
                highlights_payload,
            )
            _atomic_write_json_lf(
                staging / "reading_guide.json",
                guide_payload,
            )
            self._write_full_markdown(
                staging / "full_read.md",
                active.metadata,
                review,
                translations.values(),
            )
            self._write_translation_notes(
                staging / "translation_notes.md",
                translations.values(),
            )
            FullReadRenderer().render(
                workspace,
                translations,
                highlights,
                staging / "reader_full.html",
                review=review,
                reader_revision=reader_revision,
                paper_id=stable_paper_id(active.metadata),
            )
            publications = (
                (
                    staging / "translations.json",
                    root / "translations.json",
                ),
                (
                    staging / "highlights.json",
                    root / "highlights.json",
                ),
                (
                    staging / "reading_guide.json",
                    root / "reading_guide.json",
                ),
                (staging / "full_read.md", root / "full_read.md"),
                (
                    staging / "translation_notes.md",
                    root / "translation_notes.md",
                ),
                (staging / "reader_full.html", output),
            )
            state = workspace.load_job()
            terminal_stage = state.stages.get("full_read")
            if state.status == "full_read_ready":
                if (
                    terminal_stage is None
                    or terminal_stage.status != "completed"
                    or terminal_stage.input_hash != final_input_hash
                    or any(
                        not target.is_file()
                        or target.read_bytes() != source.read_bytes()
                        for source, target in publications
                    )
                ):
                    raise FullReadError(
                        "full_read_artifact_inconsistent"
                    )
                return {
                    **terminal_stage.result,
                    "cached": True,
                }
            self._publish_staged(staging, publications)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        finished_at = _now()
        state = workspace.load_job()
        stage = state.stages.get("full_read")
        started_at = stage.started_at if stage else finished_at
        result = {
            "status": "full_read_ready",
            "source_sha256": active.source_sha256,
            "translation_count": len(translations),
            "highlight_count": len(highlights),
            "reader_full_html": str(output),
            "full_read_markdown": str(root / "full_read.md"),
            "translations_json": str(root / "translations.json"),
            "highlights_json": str(root / "highlights.json"),
            "reading_guide_json": str(root / "reading_guide.json"),
            "reader_build_version": READER_BUILD_VERSION,
            "reader_revision": reader_revision,
            "review": review.to_dict(),
            "cached": False,
        }
        state.stages["full_read"] = StageRecord(
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            input_hash=final_input_hash,
            tool_version=__version__,
            result=result,
        )
        state.status = "full_read_ready"
        state.error = None
        workspace.save_job(state)
        return result

    @staticmethod
    def _publish_staged(
        staging: Path,
        publications: tuple[tuple[Path, Path], ...],
    ) -> None:
        backups: dict[Path, bytes | None] = {}
        published: list[Path] = []
        try:
            for source, target in publications:
                target.parent.mkdir(parents=True, exist_ok=True)
                backups[target] = (
                    target.read_bytes() if target.is_file() else None
                )
                source.replace(target)
                published.append(target)
        except OSError as primary_error:
            for target in reversed(published):
                backup = backups[target]
                try:
                    if backup is None:
                        target.unlink(missing_ok=True)
                    else:
                        restore = staging / (
                            f".restore-{uuid.uuid4().hex}"
                        )
                        restore.write_bytes(backup)
                        restore.replace(target)
                except OSError as rollback_error:
                    primary_error.add_note(
                        f"restore {target} failed: {rollback_error}"
                    )
            raise

    def _collect_translations(
        self,
        workspace: PaperWorkspace,
    ) -> tuple[_ActiveMineru, dict[str, Translation]]:
        result = self._prepared.get(workspace.root)
        if result is None:
            result = self.prepare(workspace)
        active = self._inspect_active_mineru(workspace)
        root = workspace.reading_dir / "full"
        translations: dict[str, Translation] = {}
        for batch in result.plan["batches"]:
            path = root / batch["translation_file"]
            if not path.is_file():
                raise ValueError("full_translation_incomplete")
            try:
                submission = TranslationBatchSubmission.from_dict(
                    json.loads(path.read_text(encoding="utf-8")),
                    expected_blocks=tuple(
                        json.loads(
                            (root / batch["source_file"]).read_text(
                                encoding="utf-8"
                            )
                        )["blocks"]
                    ),
                    expected_batch_id=batch["batch_id"],
                    expected_source_sha256=active.source_sha256,
                )
            except (
                OSError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as error:
                raise FullReadError(
                    "full_read_artifact_inconsistent"
                ) from error
            for item in submission.translations:
                translations[item.block_id] = item
        if tuple(translations) != tuple(
            row["block_id"] for row in active.rows
        ):
            raise FullReadError("full_read_artifact_inconsistent")
        return active, translations

    @staticmethod
    def _write_full_markdown(
        path: Path,
        metadata: PaperMetadata,
        review: FullReviewSubmission,
        translations: Any,
    ) -> None:
        guide_labels = {
            "research_question": "研究问题",
            "key_methods": "关键方法",
            "core_results": "核心结果",
            "limitations": "局限性",
        }
        lines = [
            f"# {metadata.title}",
            "",
            "## 阅读导览",
            "",
        ]
        for category, label in guide_labels.items():
            lines.extend([f"### {label}", ""])
            entries = getattr(review.guide, category)
            if entries:
                lines.extend(
                    f"- {entry.text} [source: {','.join(entry.source_block_ids)}]"
                    for entry in entries
                )
            else:
                lines.append("- 原文未明确说明")
            lines.append("")
        lines.extend(["## 全文翻译", ""])
        for item in translations:
            lines.extend(
                [
                    f"<!-- source:{item.block_id} -->",
                    "",
                    item.translation_zh or item.source_text,
                    "",
                ]
            )
        path.write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _write_translation_notes(
        path: Path,
        translations: Any,
    ) -> None:
        rows = [
            f"- `{item.block_id}`：{item.note}"
            for item in translations
            if item.note
        ]
        value = "# 翻译说明\n\n"
        value += "\n".join(rows) if rows else "无。\n"
        if rows:
            value += "\n"
        path.write_text(
            value,
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _inspect_active_mineru(
        workspace: PaperWorkspace,
    ) -> _ActiveMineru:
        state = workspace.load_job()
        upgrade = state.stages.get("paper_parse_upgrade")
        if (
            upgrade is None
            or upgrade.status != "completed"
            or upgrade.result.get("active_parsed_dir")
            != "parsed/mineru"
        ):
            raise FullReadError("mineru_required_for_full_read")
        metadata = PaperMetadata.from_dict(
            json.loads(
                workspace.metadata_path.read_text(encoding="utf-8")
            )
        )
        source_sha256 = upgrade.result.get("source_sha256")
        method = upgrade.result.get("method")
        mineru_version = upgrade.result.get("mineru_version")
        if not all(
            isinstance(value, str) and value
            for value in (source_sha256, method, mineru_version)
        ):
            raise FullReadError("full_read_artifact_inconsistent")
        root = active_parsed_root(workspace)
        try:
            MineruArtifactValidator.validate_mineru_artifacts(
                root,
                source_sha256,
                method=method,
                mineru_version=mineru_version,
                manifest_path=workspace.manifest_path,
                metadata=metadata,
            )
            source_map_path = root / "source_map.json"
            source_map = json.loads(
                source_map_path.read_text(encoding="utf-8")
            )
            normalization_version = source_map["version"]
            parser_version = source_map["parser_version"]
            if not all(
                isinstance(value, str) and value
                for value in (
                    normalization_version,
                    parser_version,
                )
            ):
                raise ValueError("MinerU 版本字段无效")
            blocks = tuple(
                SourceBlock.from_dict(value)
                for value in source_map["blocks"]
            )
            candidates = list(
                (root / "raw").rglob("*_content_list.json")
            )
            if len(candidates) != 1:
                raise ValueError("content list 不唯一")
            raw_items = json.loads(
                candidates[0].read_text(encoding="utf-8")
            )
            by_source_index = {
                block.source_index: block for block in blocks
            }
            rows_list: list[dict[str, Any]] = []
            in_references = False
            for source_index, item in enumerate(raw_items):
                block = by_source_index.get(source_index)
                if block is not None:
                    if block.source_type == "header":
                        in_references = bool(
                            re.fullmatch(
                                r"(?:\d+(?:\.\d+)*[.)]?\s*)?"
                                r"(?:references?(?:\s+and\s+notes)?|bibliography)",
                                block.text.strip(),
                                flags=re.IGNORECASE,
                            )
                        )
                    rows_list.append(
                        {
                            "block_id": block.block_id,
                            "page": block.page,
                            "source_type": (
                                "reference"
                                if in_references
                                and block.source_type != "header"
                                else block.source_type
                            ),
                            "text_level": item.get("text_level"),
                            "english": block.text,
                        }
                    )
                item_type = item.get("type")
                if item_type in {"image", "table"}:
                    prefix = "image" if item_type == "image" else "table"
                    captions = item.get(f"{prefix}_caption", [])
                    if isinstance(captions, list):
                        caption = "\n".join(
                            value.strip()
                            for value in captions
                            if isinstance(value, str) and value.strip()
                        )
                        if caption:
                            page = int(item["page_idx"]) + 1
                            rows_list.append(
                                {
                                    "block_id": (
                                        f"p{page:04d}-c{source_index + 1:04d}"
                                    ),
                                    "page": page,
                                    "source_type": "caption",
                                    "text_level": None,
                                    "english": caption,
                                }
                            )
            rows = tuple(rows_list)
        except (
            OSError,
            json.JSONDecodeError,
            IndexError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise FullReadError(
                "full_read_artifact_inconsistent"
            ) from error
        return _ActiveMineru(
            metadata=metadata,
            source_sha256=source_sha256,
            source_map_sha256=_sha256_bytes(
                source_map_path.read_bytes()
            ),
            normalization_version=normalization_version,
            mineru_parser_version=parser_version,
            blocks=blocks,
            rows=rows,
        )

    @staticmethod
    def _source_payload(
        batch_id: str,
        source_sha256: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "contract_version": FULL_READ_SOURCE_CONTRACT_VERSION,
            "translation_contract_version": (
                FULL_TRANSLATION_CONTRACT_VERSION
            ),
            "batch_id": batch_id,
            "source_sha256": source_sha256,
            "blocks": rows,
        }

    def _build_batches(
        self,
        active: _ActiveMineru,
    ) -> tuple[dict[str, Any], ...]:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for row in active.rows:
            candidate = [*current, row]
            batch_id = f"batch-{len(groups) + 1:04d}"
            size = len(
                _json_bytes(
                    self._source_payload(
                        batch_id,
                        active.source_sha256,
                        candidate,
                    )
                )
            )
            if current and (
                len(candidate) > _MAX_BATCH_BLOCKS
                or size > _MAX_BATCH_BYTES
            ):
                groups.append(current)
                current = [row]
            else:
                current = candidate
        if current:
            groups.append(current)

        batches: list[dict[str, Any]] = []
        for index, rows in enumerate(groups, start=1):
            batch_id = f"batch-{index:04d}"
            payload = self._source_payload(
                batch_id,
                active.source_sha256,
                rows,
            )
            encoded = _json_bytes(payload)
            batches.append(
                {
                    "batch_id": batch_id,
                    "source_file": f"batches/{batch_id}.source.json",
                    "translation_file": (
                        f"batches/{batch_id}.translation.json"
                    ),
                    "block_ids": [
                        row["block_id"] for row in rows
                    ],
                    "input_sha256": _sha256_bytes(encoded),
                    "byte_count": len(encoded),
                    "oversized": len(encoded) > _MAX_BATCH_BYTES,
                    "payload": payload,
                }
            )
        return tuple(batches)

    @staticmethod
    def _build_plan(
        active: _ActiveMineru,
        batches: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        return {
            "contract_version": FULL_READ_PLAN_CONTRACT_VERSION,
            "translation_contract_version": (
                FULL_TRANSLATION_CONTRACT_VERSION
            ),
            "prompt_version": FULL_READ_PROMPT_VERSION,
            "source_sha256": active.source_sha256,
            "source_map_sha256": active.source_map_sha256,
            "normalization_version": active.normalization_version,
            "mineru_parser_version": active.mineru_parser_version,
            "block_count": len(active.blocks),
            "batches": [
                {
                    key: value
                    for key, value in batch.items()
                    if key != "payload"
                }
                for batch in batches
            ],
        }

    @staticmethod
    def _validate_cache(
        root: Path,
        expected_plan: dict[str, Any],
        expected_batches: tuple[dict[str, Any], ...],
    ) -> None:
        try:
            plan = json.loads(
                (root / "translation_plan.json").read_text(
                    encoding="utf-8"
                )
            )
            if plan != expected_plan:
                raise ValueError("plan mismatch")
            for batch in expected_batches:
                path = root / batch["source_file"]
                if (
                    path.read_bytes() != _json_bytes(batch["payload"])
                    or _sha256_bytes(path.read_bytes())
                    != batch["input_sha256"]
                ):
                    raise ValueError("batch mismatch")
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise FullReadError(
                "full_read_artifact_inconsistent"
            ) from error

    @staticmethod
    def _record_plan_state(
        workspace: PaperWorkspace,
        active: _ActiveMineru,
        plan: dict[str, Any],
        *,
        cached: bool,
    ) -> None:
        state = workspace.load_job()
        if (
            state.status == "full_read_ready"
            and (terminal := state.stages.get("full_read")) is not None
            and terminal.status == "completed"
        ):
            return
        preserve_statuses = {
            "translating_full_read",
            "reviewing_full_read",
            "full_read_ready",
        }
        if state.status not in preserve_statuses:
            state.status = "full_read_planned"
        now = _now()
        stage = state.stages.get("full_read")
        completed_batches = (
            stage.result.get("completed_batches", 0)
            if stage is not None
            else 0
        )
        state.stages["full_read"] = StageRecord(
            status="running",
            started_at=stage.started_at if stage else now,
            input_hash=hashlib.sha256(
                _json_bytes(plan)
            ).hexdigest(),
            tool_version=__version__,
            result={
                "status": state.status,
                "source_sha256": active.source_sha256,
                "source_map_sha256": active.source_map_sha256,
                "batch_count": len(plan["batches"]),
                "completed_batches": completed_batches,
                "contract_version": FULL_READ_PLAN_CONTRACT_VERSION,
                "cached": cached,
            },
        )
        workspace.save_job(state)
