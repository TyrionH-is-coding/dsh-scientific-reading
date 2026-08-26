from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .assets import AssetManifest
from .feishu_models import (
    FeishuConfig,
    FeishuPayload,
    SYSTEM_MANAGED_FIELDS,
)
from .full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
)
from .full_read_service import FullReadError, FullReadService
from .identifiers import normalize_doi, normalize_pmid
from .models import AssetRecord, JobState, PaperMetadata, StageRecord
from .workspace import PaperWorkspace


_CONTENT_STAGES = (
    "pdf_acquisition",
    "paper_parse",
    "paper_parse_upgrade",
    "full_read",
)


def validate_feishu_config_path(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("absolute_feishu_config_required")
    resolved = path.resolve(strict=True)
    repository_root = Path(__file__).resolve().parents[2]
    try:
        resolved.relative_to(repository_root)
    except ValueError:
        return resolved
    raise ValueError("feishu_config_must_be_outside_repository")


def load_feishu_config(path: Path) -> FeishuConfig:
    validated = validate_feishu_config_path(path)
    return FeishuConfig.from_dict(
        json.loads(validated.read_text(encoding="utf-8"))
    )


def _json_hash(value: Any) -> str:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _completed_stage(
    state: JobState,
    name: str,
) -> StageRecord | None:
    stage = state.stages.get(name)
    if stage is None or stage.status != "completed":
        return None
    return stage


def _latest_content_time(state: JobState) -> str:
    values = [
        stage.finished_at
        for name in _CONTENT_STAGES
        if (stage := _completed_stage(state, name)) is not None
        and isinstance(stage.finished_at, str)
        and stage.finished_at
    ]
    return max(values) if values else ""


def _join_numbered(values: Iterable[str]) -> str:
    return "\n".join(
        f"{index}. {value}"
        for index, value in enumerate(values, start=1)
    )


def _asset_directory_lines(
    workspace: PaperWorkspace,
    assets: Iterable[AssetRecord],
) -> list[str]:
    root = workspace.root.resolve()
    directories = {"figure": set(), "table": set()}
    for asset in assets:
        if asset.kind not in directories:
            continue
        path = (root / asset.relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if not path.is_file() or not path.parent.is_dir():
            continue
        directories[asset.kind].add(path.parent)
    return [
        f"{label} | {directory}"
        for kind, label in (("figure", "图片目录"), ("table", "表格目录"))
        for directory in sorted(directories[kind], key=str)
    ]


class FeishuPayloadBuilder:
    def build(
        self,
        workspace: PaperWorkspace,
        config: FeishuConfig,
        *,
        projects: Iterable[str] = (),
    ) -> FeishuPayload:
        metadata = PaperMetadata.from_dict(
            json.loads(
                workspace.metadata_path.read_text(encoding="utf-8")
            )
        )
        state = workspace.load_job()
        library = self._library_values(workspace)
        values: dict[str, Any] = {
            "title": library.get("title", metadata.title),
            "doi": normalize_doi(library.get("doi", metadata.doi)) or "",
            "pmid": normalize_pmid(library.get("pmid", metadata.pmid)) or "",
            "source_url": library.get("source_url", metadata.source_url) or "",
            "authors": library.get("authors", metadata.authors),
            "journal": library.get("journal", metadata.journal) or "",
            "year": library.get("year", metadata.year),
            "projects": list(projects),
            "library_key": library.get("library_key", metadata.library_key) or "",
            "pdf_status": (
                "pdf_ready"
                if _completed_stage(state, "pdf_acquisition")
                is not None
                and workspace.source_pdf.is_file()
                else "pdf_missing"
            ),
            "pdf_path": (
                str(workspace.source_pdf.resolve())
                if workspace.source_pdf.is_file()
                else ""
            ),
            "reading_status": library.get("status", state.status),
            "abstract_en": library.get("abstract_en", metadata.abstract_en) or "",
            "abstract_zh": library.get("abstract_zh", metadata.abstract_zh) or "",
            "abstract_read": library.get("abstract_read", ""),
            "full_read_status": library.get("full_read_status", "") or "",
            "full_read_key_points": "",
            "full_read_html": "",
            "updated_at": library.get("updated_at", _latest_content_time(state)),
            "error_status": library.get("last_error", state.error) or "",
        }
        # Full-read artifacts are system-owned only after the local library
        # explicitly records completion.  A job stage alone is not enough.
        full_completed = values["full_read_status"] in {
            "completed",
            "精读完成",
        }
        full_workspace = workspace
        full_stage = None
        if full_completed:
            full_workspace, full_stage = self._completed_full_read(
                workspace,
                state,
            )
        if full_stage is not None and full_completed:
            values.update(
                self._full_values(full_workspace, full_stage)
            )
        selected = {
            logical_name: self._adapt_value(
                values[logical_name],
                mapping.field_type,
            )
            for logical_name, mapping in config.field_map.items()
            if logical_name in SYSTEM_MANAGED_FIELDS
            and (
                logical_name not in {"full_read_key_points", "full_read_html"}
                or full_completed
            )
        }
        return FeishuPayload.from_logical_values(config, selected)

    @staticmethod
    def _completed_full_read(
        workspace: PaperWorkspace,
        state: JobState,
    ) -> tuple[PaperWorkspace, StageRecord | None]:
        upgrade = _completed_stage(state, "paper_parse_upgrade")
        relative = (
            upgrade.result.get("active_workspace")
            if upgrade is not None
            else None
        )
        if relative is not None:
            source_sha256 = upgrade.result.get("source_sha256")
            if (
                not isinstance(source_sha256, str)
                or len(source_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in source_sha256
                )
                or relative != f"generations/{source_sha256[:16]}"
            ):
                raise ValueError("feishu_full_read_inconsistent")
            generation_root = (workspace.root / relative).resolve()
            expected_root = (
                workspace.root / "generations" / source_sha256[:16]
            ).resolve()
            if generation_root != expected_root:
                raise ValueError("feishu_full_read_inconsistent")
            generation = PaperWorkspace(generation_root)
            try:
                generation_state = generation.load_job()
            except (OSError, json.JSONDecodeError, ValueError) as error:
                raise ValueError("feishu_full_read_inconsistent") from error
            nested = _completed_stage(generation_state, "full_read")
            if (
                generation_state.paper_id != source_sha256[:16]
                or nested is None
                or nested.result.get("source_sha256") != source_sha256
            ):
                raise ValueError("feishu_full_read_inconsistent")
            return generation, nested
        direct = _completed_stage(state, "full_read")
        return workspace, direct

    @staticmethod
    def _library_values(workspace: PaperWorkspace) -> dict[str, Any]:
        """Read only the local SQLite row and abstract artifact."""
        path = workspace.root.parents[1] / "library.sqlite"
        if not path.is_file():
            return {"_row_missing": True}
        try:
            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM items WHERE paper_id = ?",
                    (workspace.root.name,),
                ).fetchone()
        except sqlite3.Error as error:
            raise ValueError("feishu_library_read_failed") from error
        if row is None:
            return {"_row_missing": True}
        values: dict[str, Any] = dict(row)
        try:
            values["authors"] = json.loads(row["authors_json"] or "[]")
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("feishu_library_read_failed") from error
        abstract_path = workspace.reading_dir / "abstract_read.json"
        if abstract_path.is_file():
            try:
                artifact = json.loads(abstract_path.read_text(encoding="utf-8"))
                paragraphs = artifact.get("paragraphs", [])
                if isinstance(paragraphs, list):
                    values["abstract_read"] = "\n\n".join(
                        f"{item.get('source_en', '')}\n{item.get('translation_zh', '')}".strip()
                        for item in paragraphs
                        if isinstance(item, dict)
                    )
                    translated = "\n\n".join(
                        str(item.get("translation_zh", "")).strip()
                        for item in paragraphs
                        if isinstance(item, dict) and item.get("translation_zh")
                    )
                    if translated:
                        values["abstract_zh"] = translated
            except (OSError, TypeError, json.JSONDecodeError) as error:
                raise ValueError("feishu_abstract_read_inconsistent") from error
        return values

    @staticmethod
    def _adapt_value(value: Any, field_type: str) -> Any:
        if field_type == "multi_select":
            if value is None:
                return []
            if isinstance(value, (list, tuple)):
                return list(value)
            return [str(value)] if str(value).strip() else []
        if field_type == "text":
            if value is None:
                return ""
            if isinstance(value, (list, tuple)):
                return "、".join(str(item) for item in value)
            return str(value)
        return value

    @staticmethod
    def _full_values(
        workspace: PaperWorkspace,
        stage: StageRecord,
    ) -> dict[str, str]:
        root = workspace.reading_dir / "full"
        translations_path = root / "translations.json"
        highlights_path = root / "highlights.json"
        markdown_path = root / "full_read.md"
        guide_path = root / "reading_guide.json"
        html_path = workspace.output_dir / "reader_full.html"
        try:
            translations = json.loads(
                translations_path.read_text(encoding="utf-8")
            )
            highlights = json.loads(
                highlights_path.read_text(encoding="utf-8")
            )
            markdown_path.read_text(encoding="utf-8")
            guide_path.read_text(encoding="utf-8")
            html_path.read_text(encoding="utf-8")
            review = stage.result["review"]
            if (
                translations.get("contract_version")
                != FULL_TRANSLATION_CONTRACT_VERSION
                or highlights.get("contract_version")
                != FULL_REVIEW_CONTRACT_VERSION
                or review.get("contract_version")
                != FULL_REVIEW_CONTRACT_VERSION
                or not isinstance(review.get("guide"), dict)
                or translations.get("source_sha256")
                != stage.result.get("source_sha256")
            ):
                raise ValueError("full contract mismatch")
            finalized = FullReadService().finalize(workspace, review)
            review = finalized["review"]
            source_map_path = workspace.parsed_dir / "mineru" / "source_map.json"
            source_map_sha256 = hashlib.sha256(
                source_map_path.read_bytes()
            ).hexdigest()
            identity = {
                "reader_build_version": stage.result[
                    "reader_build_version"
                ],
                "source_sha256": translations["source_sha256"],
                "source_map_sha256": source_map_sha256,
                "translations": translations["translations"],
                "highlights": highlights["highlights"],
                "review": review,
            }
            if stage.input_hash != _json_hash(identity):
                raise ValueError("full identity mismatch")
            expected_paths = {
                "reader_full_html": html_path,
                "full_read_markdown": markdown_path,
                "translations_json": translations_path,
                "highlights_json": highlights_path,
                "reading_guide_json": guide_path,
            }
            if any(
                Path(stage.result.get(key, "")).resolve()
                != path.resolve()
                for key, path in expected_paths.items()
            ):
                raise ValueError("full path mismatch")
        except (
            OSError,
            FullReadError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ValueError("feishu_full_read_inconsistent") from error
        labels = {
            "research_question": "研究问题",
            "key_methods": "关键方法",
            "core_results": "核心结果",
            "limitations": "局限性",
        }
        points = [
            f"{labels[category]}：{entry['text'].strip()}"
            for category in labels
            for entry in review["guide"][category]
        ]
        return {
            "full_read_key_points": _join_numbered(points),
            "full_read_html": str(html_path.resolve()),
        }
