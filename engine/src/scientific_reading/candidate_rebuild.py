from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .assets import AssetManifest
from .data_guard import data_root_operation
from .export_service import ExportService
from .full_read_models import FULL_TRANSLATION_CONTRACT_VERSION, Translation
from .full_read_service import FullReadService
from .mineru_models import MINERU_NORMALIZATION_VERSION
from .mineru_normalizer import MineruNormalizer, render_mineru_markdown
from .models import AssetRecord, JobState, PaperMetadata, StageRecord
from .package_manifest import validate_generation_package_manifest
from .parse_models import ParseReport, SourceBlock
from .workspace import PaperWorkspace, atomic_write_json


REBUILD_PLAN_CONTRACT = "candidate-rebuild-plan-v1"
GENERATION_METHOD = "renormalize-verified-cached-raw-v1"
_PAPER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class CandidateRebuildError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_tree_snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    raw_root = Path(root).resolve()
    is_junction = getattr(Path(root), "is_junction", lambda: False)
    if Path(root).is_symlink() or is_junction() or not raw_root.is_dir():
        raise ValueError("raw_tree_invalid")
    files: list[tuple[str, str]] = []
    for path in sorted(raw_root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(raw_root).as_posix()
        is_junction = getattr(path, "is_junction", lambda: False)
        if path.is_symlink() or is_junction():
            raise ValueError("raw_tree_link_forbidden")
        if path.is_dir():
            continue
        if not path.is_file() or not path.resolve().is_relative_to(raw_root):
            raise ValueError("raw_tree_invalid")
        files.append((relative, _sha256(path)))
    if not files:
        raise ValueError("raw_tree_empty")
    return tuple(files)


def _raw_tree_sha256(snapshot: tuple[tuple[str, str], ...]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_raw_tree(
    root: Path, expected: tuple[tuple[str, str], ...]
) -> None:
    try:
        actual = _raw_tree_snapshot(root)
    except (OSError, ValueError) as error:
        raise CandidateRebuildError("historical_source_changed") from error
    if actual != expected:
        raise CandidateRebuildError("historical_source_changed")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError
    return value


def _load_json_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError
    return value, hashlib.sha256(raw).hexdigest()


def _validate_target(data_root: Path, target_root: Path) -> Path:
    target = Path(target_root)
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise CandidateRebuildError("candidate_target_invalid")
    resolved = target.resolve()
    if resolved == data_root or resolved.is_relative_to(data_root):
        raise CandidateRebuildError("candidate_target_not_isolated")
    if target.exists() and any(target.iterdir()):
        raise CandidateRebuildError("candidate_target_not_empty")
    return resolved


def _historical_rows(
    blocks: tuple[SourceBlock, ...], raw_items: list[Any]
) -> tuple[dict[str, Any], ...]:
    by_index: dict[int, SourceBlock] = {}
    block_ids: set[str] = set()
    for block in blocks:
        if block.source_index is None or block.source_index in by_index:
            raise ValueError
        if block.block_id in block_ids:
            raise ValueError
        by_index[block.source_index] = block
        block_ids.add(block.block_id)

    rows: list[dict[str, Any]] = []
    in_references = False
    for source_index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ValueError
        block = by_index.get(source_index)
        if block is not None:
            if block.source_type == "header" or block.heading_level is not None:
                in_references = bool(
                    re.fullmatch(
                        r"(?:\d+(?:\.\d+)*[.)]?\s*)?"
                        r"(?:references?(?:\s+and\s+notes)?|bibliography)",
                        block.text.strip(),
                        flags=re.IGNORECASE,
                    )
                )
            source_type = (
                "reference"
                if block.source_type == "ref_text"
                or in_references
                and block.heading_level is None
                and block.source_type != "header"
                else block.source_type
            )
            rows.append(
                {
                    "block_id": block.block_id,
                    "page": block.page,
                    "source_type": source_type,
                    "source_index": source_index,
                    "source_text": block.text,
                }
            )
        item_type = item.get("type")
        if item_type in {"image", "chart", "table"}:
            captions = item.get(f"{item_type}_caption", [])
            if not isinstance(captions, list):
                raise ValueError
            caption = "\n".join(
                value.strip()
                for value in captions
                if isinstance(value, str) and value.strip()
            )
            if caption:
                page = int(item["page_idx"]) + 1
                rows.append(
                    {
                        "block_id": f"p{page:04d}-c{source_index + 1:04d}",
                        "page": page,
                        "source_type": "caption",
                        "source_index": source_index,
                        "source_text": caption,
                    }
                )
    return tuple(rows)


def _candidate_rows(active: Any) -> tuple[dict[str, Any], ...]:
    by_id = {block.block_id: block for block in active.blocks}
    if len(by_id) != len(active.blocks):
        raise ValueError
    result: list[dict[str, Any]] = []
    for row in active.rows:
        block = by_id.get(row["block_id"])
        if block is not None:
            source_index = block.source_index
        else:
            match = re.fullmatch(r"p[0-9]{4}-c([0-9]{4})", row["block_id"])
            if match is None:
                raise ValueError
            source_index = int(match.group(1)) - 1
        if source_index is None:
            raise ValueError
        result.append(
            {
                "block_id": row["block_id"],
                "page": row["page"],
                "source_type": row["source_type"],
                "source_index": source_index,
                "source_text": row["english"],
            }
        )
    return tuple(result)


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        name: row[name]
        for name in ("block_id", "page", "source_type", "source_index")
    }


def _identity_key(source_sha256: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        source_sha256,
        row["block_id"],
        row["page"],
        row["source_type"],
        row["source_index"],
        row["source_text"],
    )


def _load_translations(
    path: Path,
    source_sha: str,
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], str]:
    try:
        payload, payload_sha256 = _load_json_snapshot(path)
        if (
            payload.get("contract_version")
            != FULL_TRANSLATION_CONTRACT_VERSION
            or payload.get("source_sha256") != source_sha
            or set(payload)
            != {"contract_version", "source_sha256", "translations"}
        ):
            raise ValueError
        raw_translations = payload["translations"]
        if not isinstance(raw_translations, list) or not raw_translations:
            raise ValueError
        source_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["block_id"] in source_by_id:
                raise ValueError
            source_by_id[row["block_id"]] = row
        translations: dict[tuple[Any, ...], dict[str, Any]] = {}
        translated_ids: set[str] = set()
        for raw_translation in raw_translations:
            if not isinstance(raw_translation, dict):
                raise ValueError
            row = source_by_id.get(raw_translation.get("block_id"))
            if row is None or row["block_id"] in translated_ids:
                raise ValueError
            translated_ids.add(row["block_id"])
            translation = Translation.from_dict(
                raw_translation,
                expected_source_text=row["source_text"],
                reference=row["source_type"] == "reference",
            )
            key = _identity_key(source_sha, row)
            if key in translations:
                raise ValueError
            translations[key] = {
                "block_id": translation.block_id,
                "source_text": translation.source_text,
                "translation_zh": translation.translation_zh,
                "highlight": translation.highlight,
            }
        return translations, payload_sha256
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CandidateRebuildError("historical_translation_invalid") from error


def _load_history(
    data_root: Path, paper_id: str
) -> tuple[PaperWorkspace, PaperMetadata, str, str, str, dict[str, Any]]:
    if (
        not isinstance(paper_id, str)
        or _PAPER_ID.fullmatch(paper_id) is None
        or ".." in paper_id
    ):
        raise CandidateRebuildError("paper_id_invalid")
    paper_root = (data_root / "papers" / paper_id).resolve()
    if not paper_root.is_relative_to(data_root):
        raise CandidateRebuildError("paper_id_invalid")
    try:
        metadata = PaperMetadata.from_dict(
            _load_json(paper_root / "metadata.json")
        )
        workspace, source_sha, method, version = ExportService._active_workspace(
            PaperWorkspace(paper_root), metadata
        )
        from .__main__ import _resolve_artifact

        pdf = _resolve_artifact(data_root, paper_id, "pdf")
        relative_pdf = workspace.source_pdf.relative_to(paper_root).as_posix()
        if pdf.get("sha256") != source_sha or pdf.get("rel_path") != relative_pdf:
            raise ValueError
        validate_generation_package_manifest(workspace, required=False)
        parsed = workspace.parsed_dir / "mineru"
        source_map_path = parsed / "source_map.json"
        report_path = parsed / "parse_report.json"
        source_map, source_map_sha256 = _load_json_snapshot(source_map_path)
        report, parse_report_sha256 = _load_json_snapshot(report_path)
        if (
            source_map.get("version") != MINERU_NORMALIZATION_VERSION
            or report.get("version") != MINERU_NORMALIZATION_VERSION
            or source_map.get("parser") != "mineru"
            or report.get("parser") != "mineru"
            or source_map.get("source_sha256") != source_sha
            or report.get("source_sha256") != source_sha
            or source_map.get("raw_content_list_sha256")
            != report.get("raw_content_list_sha256")
            or source_map.get("parser_version") != version
            or report.get("parser_version") != version
            or source_map.get("method") != method
            or report.get("method") != method
        ):
            raise ValueError
        parsed_report = ParseReport.from_dict(report)
        if parsed_report.status != "parsed_mineru":
            raise ValueError
        raw_candidates = [
            path
            for path in (parsed / "raw").rglob("*_content_list.json")
            if path.is_file() and not path.is_symlink()
        ]
        if len(raw_candidates) != 1:
            raise ValueError
        raw_path = raw_candidates[0]
        raw_bytes = raw_path.read_bytes()
        raw_content_list_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        if (
            not raw_path.resolve().is_relative_to((parsed / "raw").resolve())
            or raw_content_list_sha256
            != source_map["raw_content_list_sha256"]
        ):
            raise ValueError
        raw_items = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError
        blocks = tuple(SourceBlock.from_dict(row) for row in source_map["blocks"])
        if (
            parsed_report.block_count != len(blocks)
            or (parsed / "full.md").read_text(encoding="utf-8")
            != render_mineru_markdown(blocks, parsed_report.page_count)
        ):
            raise ValueError
        rows = _historical_rows(blocks, raw_items)

        manifest_assets = AssetManifest(workspace.manifest_path).load()
        report_assets = report.get("assets", [])
        if not isinstance(report_assets, list):
            raise ValueError
        by_manifest = {asset.asset_id: asset for asset in manifest_assets}
        if len(by_manifest) != len(manifest_assets):
            raise ValueError
        report_asset_ids: set[str] = set()
        for raw_asset in report_assets:
            asset = AssetRecord.from_dict(raw_asset)
            AssetManifest._validate(asset)
            if (
                asset.asset_id in report_asset_ids
                or by_manifest.get(asset.asset_id) != asset
            ):
                raise ValueError
            report_asset_ids.add(asset.asset_id)
            relative = Path(asset.relative_path).relative_to("parsed/mineru")
            asset_path = parsed / relative
            if (
                not asset_path.is_file()
                or asset_path.is_symlink()
                or not asset_path.resolve().is_relative_to(parsed.resolve())
            ):
                raise ValueError
            if asset.source_sha256 is not None and _sha256(
                asset_path
            ) != asset.source_sha256:
                raise ValueError
            if asset.structured_reliable:
                structured_path = workspace.root / str(asset.structured_path)
                if (
                    not structured_path.is_file()
                    or structured_path.is_symlink()
                    or not structured_path.resolve().is_relative_to(
                        workspace.root.resolve()
                    )
                    or _sha256(structured_path) != asset.structured_sha256
                ):
                    raise ValueError
        if (
            parsed_report.image_count
            != sum(asset.kind == "figure" for asset in manifest_assets)
            or parsed_report.table_count
            != sum(asset.kind == "table" for asset in manifest_assets)
        ):
            raise ValueError

        translations_path = workspace.reading_dir / "full" / "translations.json"
        translations, translations_sha256 = _load_translations(
            translations_path, source_sha, rows
        )
        raw_snapshot = _raw_tree_snapshot(parsed / "raw")
        relative_raw = raw_path.resolve().relative_to(
            (parsed / "raw").resolve()
        ).as_posix()
        if dict(raw_snapshot).get(relative_raw) != raw_content_list_sha256:
            raise CandidateRebuildError("historical_source_changed")
        history = {
            "rows": rows,
            "translations": translations,
            "source_map_sha256": source_map_sha256,
            "parse_report_sha256": parse_report_sha256,
            "translations_sha256": translations_sha256,
            "raw_content_list_sha256": raw_content_list_sha256,
            "raw_root": parsed / "raw",
            "raw_snapshot": raw_snapshot,
            "raw_tree_sha256": _raw_tree_sha256(raw_snapshot),
            "report_stamps": {
                stamp: report[stamp]
                for stamp in (
                    "provider",
                    "provider_version",
                    "model_version",
                    "batch_id",
                    "result_zip_sha256",
                )
                if stamp in report
            },
        }
        return workspace, metadata, source_sha, method, version, history
    except CandidateRebuildError:
        raise
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CandidateRebuildError("historical_source_invalid") from error


def _build_candidate(
    staging: Path,
    target_name: str,
    workspace: PaperWorkspace,
    metadata: PaperMetadata,
    source_sha: str,
    method: str,
    version: str,
    history: dict[str, Any],
) -> tuple[PaperWorkspace, Any]:
    candidate = PaperWorkspace(staging)
    shutil.copyfile(workspace.source_pdf, candidate.source_pdf)
    if _sha256(candidate.source_pdf) != source_sha:
        raise ValueError("candidate_source_pdf_invalid")
    atomic_write_json(candidate.metadata_path, metadata.to_dict())
    raw_root = candidate.parsed_dir / "mineru" / "raw"
    shutil.copytree(history["raw_root"], raw_root)
    _verify_raw_tree(history["raw_root"], history["raw_snapshot"])
    _verify_raw_tree(raw_root, history["raw_snapshot"])
    parsed = candidate.parsed_dir / "mineru"
    normalized = MineruNormalizer(version).normalize(
        raw_root, parsed, metadata, source_sha
    )
    for name in ("source_map.json", "parse_report.json"):
        path = parsed / name
        payload = _load_json(path)
        payload["method"] = method
        if name == "parse_report.json":
            payload.update(history["report_stamps"])
        atomic_write_json(path, payload)
    manifest = AssetManifest(candidate.manifest_path)
    atomic_write_json(candidate.manifest_path, {"version": 1, "assets": []})
    for asset in normalized.assets:
        manifest.upsert(asset)
    state = JobState(paper_id=target_name, status="parsed_mineru")
    state.stages["paper_parse_upgrade"] = StageRecord(
        status="completed",
        result={
            "active_parsed_dir": "parsed/mineru",
            "source_sha256": source_sha,
            "method": method,
            "mineru_version": version,
            "generation_method": GENERATION_METHOD,
        },
    )
    atomic_write_json(candidate.job_path, state.to_dict())
    active = FullReadService._inspect_active_mineru(candidate)
    return candidate, active


def prepare_rebuild(
    data_root: Path, paper_id: str, target_root: Path
) -> dict[str, Any]:
    root = Path(data_root).resolve()
    with data_root_operation(root):
        target = _validate_target(root, Path(target_root))
        target_existed = target.exists()
        workspace, metadata, source_sha, method, version, history = (
            _load_history(root, paper_id)
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.candidate-", dir=target.parent
            )
        )
        published = False
        try:
            candidate, active = _build_candidate(
                staging,
                target.name,
                workspace,
                metadata,
                source_sha,
                method,
                version,
                history,
            )
            candidate_rows = _candidate_rows(active)
            historical_ids = {row["block_id"] for row in history["rows"]}
            historical_keys = {
                _identity_key(source_sha, row) for row in history["rows"]
            }
            reuse: list[dict[str, Any]] = []
            pending_translation: list[dict[str, Any]] = []
            pending_review: list[dict[str, Any]] = []
            for row in candidate_rows:
                key = _identity_key(source_sha, row)
                translation = history["translations"].get(key)
                common = {
                    "identity": _identity(row),
                    "source_text": row["source_text"],
                }
                if translation is not None:
                    reuse.append({**common, "translation": translation})
                elif row["source_type"] == "reference":
                    pending_review.append(
                        {
                            **common,
                            "reason": (
                                "historical_translation_missing"
                                if key in historical_keys
                                else "reference_identity_or_source_changed"
                            ),
                            "required_translation_zh": "",
                            "required_highlight": "none",
                        }
                    )
                else:
                    pending_translation.append(
                        {
                            **common,
                            "reason": (
                                "historical_translation_missing"
                                if key in historical_keys
                                else "identity_or_source_changed"
                                if row["block_id"] in historical_ids
                                else "new_source_block"
                            ),
                        }
                    )

            parsed = candidate.parsed_dir / "mineru"
            counts = {
                "reused": len(reuse),
                "pending_translation": len(pending_translation),
                "pending_review": len(pending_review),
            }
            next_input = {
                "requires_translation": bool(pending_translation),
                "requires_block_review": bool(pending_review),
                "requires_full_review": True,
                "publishable": False,
            }
            plan = {
                "contract": REBUILD_PLAN_CONTRACT,
                "paper_id": paper_id,
                "source": {
                    "generation": workspace.root.name,
                    "source_sha256": source_sha,
                    "source_map_sha256": history["source_map_sha256"],
                    "parse_report_sha256": history["parse_report_sha256"],
                    "translations_sha256": history["translations_sha256"],
                    "raw_content_list_sha256": history[
                        "raw_content_list_sha256"
                    ],
                    "raw_tree_sha256": history["raw_tree_sha256"],
                },
                "candidate": {
                    "generation_method": GENERATION_METHOD,
                    "source_sha256": source_sha,
                    "source_map_sha256": _sha256(parsed / "source_map.json"),
                    "parse_report_sha256": _sha256(parsed / "parse_report.json"),
                    "full_markdown_sha256": _sha256(parsed / "full.md"),
                    "manifest_sha256": _sha256(candidate.manifest_path),
                    "raw_content_list_sha256": _load_json(
                        parsed / "source_map.json"
                    )["raw_content_list_sha256"],
                    "raw_tree_sha256": history["raw_tree_sha256"],
                    "full_review_reused": False,
                    "review_status": "pending",
                },
                "counts": counts,
                "reuse": reuse,
                "pending_translation": pending_translation,
                "pending_review": pending_review,
                "next_input": next_input,
            }
            plan_path = candidate.root / "rebuild-plan.json"
            atomic_write_json(plan_path, plan)
            plan_sha256 = _sha256(plan_path)
            result = {
                "status": "pending",
                "candidate_root": str(target),
                "plan_path": str(target / "rebuild-plan.json"),
                "plan_sha256": plan_sha256,
                "counts": counts,
                "next_input": next_input,
            }
            if target.exists():
                target.rmdir()
            try:
                staging.replace(target)
            except BaseException:
                if target_existed and not target.exists():
                    target.mkdir()
                raise
            published = True
            return result
        except CandidateRebuildError:
            raise
        except Exception as error:
            raise CandidateRebuildError("candidate_rebuild_failed") from error
        finally:
            if not published and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
