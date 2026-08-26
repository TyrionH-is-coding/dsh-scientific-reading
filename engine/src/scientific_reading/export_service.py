from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PIL import Image

from .mineru_models import MineruContentItem
from .models import AssetRecord, PaperMetadata
from .assets import AssetManifest
from .mineru_artifacts import MineruArtifactValidator
from .workspace import PaperWorkspace, validate_explicit_workspace
from .package_manifest import refresh_generation_package_manifest


EXPORT_CONTRACT_VERSION = "asset-export-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class ExportResult:
    paper_id: str
    exports_dir: Path
    figure_paths: tuple[Path, ...]
    table_paths: tuple[Path, ...]
    cached: bool

    def to_dict(self) -> dict[str, Any]:
        return {"status": "exported", "paper_id": self.paper_id, "exports_dir": str(self.exports_dir), "figure_count": len(self.figure_paths), "table_count": len(self.table_paths), "cached": self.cached}


class ExportService:
    def export_for_paper(self, data_root: Path, paper_id: str, *, force: bool = False) -> ExportResult:
        if not isinstance(paper_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", paper_id) or ".." in paper_id:
            raise ValueError("paper_id_invalid")
        metadata_path = Path(data_root).resolve() / "papers" / paper_id / "metadata.json"
        try:
            metadata = PaperMetadata.from_dict(json.loads(metadata_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("paper_not_found") from error
        workspace = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
        return self.export(workspace, force=force)

    def export(self, workspace: PaperWorkspace, *, force: bool = False) -> ExportResult:
        metadata = PaperMetadata.from_dict(
            json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        )
        selected, source_sha, method, version = self._active_workspace(
            workspace, metadata
        )
        parsed = selected.parsed_dir / "mineru"
        try:
            _report, assets = MineruArtifactValidator.validate_mineru_artifacts(parsed, source_sha, method=method, mineru_version=version, manifest_path=selected.manifest_path, metadata=metadata)
            raw_manifest = AssetManifest(selected.manifest_path).load_raw()
            manifest_assets = tuple(
                AssetRecord.from_dict(value)
                for value in raw_manifest["assets"]
            )
            for asset in manifest_assets:
                AssetManifest._validate(asset)
            rows = self._source_rows(parsed, assets, manifest_assets)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError("active_mineru_invalid") from error
        staging = selected.root / f".exports-staging-{uuid.uuid4().hex}"
        try:
            result_rows = self._build(staging, selected, rows)
            manifest = {"contract": EXPORT_CONTRACT_VERSION, "paper_id": workspace.root.name, "source_pdf_sha256": source_sha, "assets": result_rows}
            self._write_text(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            self._write_text(staging / "captions.md", self._captions(result_rows))
            self._validate(staging, manifest)
            if selected.exports_dir.exists():
                if not force and self._same_package(selected.exports_dir, staging):
                    shutil.rmtree(staging)
                    refresh_generation_package_manifest(selected)
                    return self._result(workspace.root.name, selected, True)
                backup = selected.root / f".exports-backup-{uuid.uuid4().hex}"
                selected.exports_dir.replace(backup)
                try:
                    staging.replace(selected.exports_dir)
                    refresh_generation_package_manifest(selected)
                except Exception:
                    if selected.exports_dir.exists():
                        shutil.rmtree(selected.exports_dir)
                    backup.replace(selected.exports_dir)
                    raise
                shutil.rmtree(backup)
            else:
                staging.replace(selected.exports_dir)
                try:
                    refresh_generation_package_manifest(selected)
                except Exception:
                    shutil.rmtree(selected.exports_dir)
                    raise
            return self._result(workspace.root.name, selected, False)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _active_workspace(
        workspace: PaperWorkspace, metadata: PaperMetadata
    ) -> tuple[PaperWorkspace, str, str, str]:
        stage = workspace.load_job().stages.get("paper_parse_upgrade")
        if stage is None or stage.status != "completed":
            raise ValueError("active_mineru_required")
        source_sha = stage.result.get("source_sha256")
        method = stage.result.get("method")
        version = stage.result.get("mineru_version")
        relative = stage.result.get("active_workspace")
        if (
            not isinstance(source_sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
            or method not in {"auto", "txt", "ocr"}
            or not isinstance(version, str)
            or stage.result.get("active_parsed_dir") != "parsed/mineru"
        ):
            raise ValueError("active_mineru_required")
        if relative is None:
            selected = workspace
        else:
            if relative != f"generations/{source_sha[:16]}":
                raise ValueError("active_workspace_invalid")
            selected = PaperWorkspace((workspace.root / relative).resolve())
            if selected.root.parent != workspace.root / "generations":
                raise ValueError("active_workspace_invalid")
        data_root = workspace.root.parents[1]
        validate_explicit_workspace(
            data_root, workspace.root.name, metadata, selected
        )
        selected_stage = selected.load_job().stages.get(
            "paper_parse_upgrade"
        )
        if (
            selected_stage is None
            or selected_stage.status != "completed"
            or selected_stage.result.get("source_sha256") != source_sha
            or selected_stage.result.get("active_parsed_dir")
            != "parsed/mineru"
        ):
            raise ValueError("active_workspace_invalid")
        if not selected.source_pdf.is_file() or _sha256(selected.source_pdf) != source_sha:
            raise ValueError("source_pdf_sha256_mismatch")
        return selected, source_sha, method, version

    @staticmethod
    def _source_rows(
        parsed: Path,
        assets: tuple[AssetRecord, ...],
        manifest_assets: tuple[AssetRecord, ...],
    ) -> list[dict[str, Any]]:
        content_lists = [path for path in (parsed / "raw").rglob("*_content_list.json") if path.is_file() and not path.is_symlink()]
        if len(content_lists) != 1:
            raise ValueError("raw_content_list_invalid")
        payload = json.loads(content_lists[0].read_text(encoding="utf-8"))
        parsed_ids = {asset.asset_id for asset in assets}
        by_id = {asset.asset_id: asset for asset in manifest_assets}
        counts: dict[str, dict[int, int]] = {"figure": {}, "table": {}}
        rows = []
        for source_index, value in enumerate(payload):
            item = MineruContentItem.from_dict(value, index=source_index)
            if item.item_type not in {"image", "table"}:
                continue
            kind = "figure" if item.item_type == "image" else "table"
            page_counts = counts[kind]
            page_counts[item.page] = page_counts.get(item.page, 0) + 1
            suffix = "img" if kind == "figure" else "table"
            asset_id = f"mineru-p{item.page:04d}-{suffix}{page_counts[item.page]:04d}"
            asset = by_id.get(asset_id)
            if asset is None or asset_id not in parsed_ids:
                raise ValueError("mineru_asset_missing")
            legacy = (
                asset.source_index is None
                and asset.is_body is None
                and asset.source_sha256 is None
            )
            if legacy:
                source = ExportService._asset_path_from_root(
                    parsed, asset
                )
                explicit_body = value.get("is_body")
                has_body_evidence = isinstance(explicit_body, bool)
                asset = replace(
                    asset,
                    source_index=source_index,
                    is_body=(explicit_body if has_body_evidence else None),
                    is_body_source=(
                        "raw_explicit"
                        if has_body_evidence
                        else "legacy_missing"
                    ),
                    bbox=item.bbox,
                    source_sha256=_sha256(source),
                )
            elif asset.source_index != source_index:
                raise ValueError("source_index_mismatch")
            if asset.is_body is True:
                rows.append({"asset": asset, "source_index": source_index})
        known_ids = {row["asset"].asset_id for row in rows}
        rows.extend(
            {"asset": asset, "source_index": asset.source_index}
            for asset in manifest_assets
            if asset.asset_id not in parsed_ids
            and asset.asset_id not in known_ids
            and asset.kind in {"figure", "table"}
            and bool(asset.relative_path)
            and asset.is_body is True
            and asset.source_index is not None
        )
        return sorted(rows, key=lambda row: row["source_index"])

    def _build(self, staging: Path, workspace: PaperWorkspace, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counters = {"figure": 0, "table": 0}
        output = []
        for row in rows:
            asset = row["asset"]
            counters[asset.kind] += 1
            if not asset.relative_path:
                raise ValueError("mineru_asset_path_required")
            source = self._asset_path(workspace, asset)
            if asset.source_sha256 != _sha256(source):
                raise ValueError("source_sha256_mismatch")
            folder = "figures" if asset.kind == "figure" else "tables"
            stem = f"Fig_{counters[asset.kind]:02d}" if asset.kind == "figure" else f"Table_{counters[asset.kind]:02d}"
            destination = staging / folder / f"{stem}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                image.convert("RGB").save(
                    destination, format="PNG", optimize=False
                )
            warnings = [] if asset.caption else ["caption_missing"]
            record = {"asset_id": asset.asset_id, "kind": asset.kind, "page": asset.page, "source_index": row["source_index"], "source_path": asset.relative_path or "source.pdf", "source_sha256": _sha256(source), "export_path": destination.relative_to(staging).as_posix(), "export_sha256": _sha256(destination), "caption": asset.caption, "warnings": warnings}
            if asset.kind == "table" and asset.structured_reliable:
                structured_path = self._structured_path(workspace, asset)
                csv_path = staging / folder / f"{stem}.csv"
                self._structured_csv(structured_path, csv_path)
                record.update({"structured_source_path": asset.structured_path, "structured_source_sha256": _sha256(structured_path), "csv_path": csv_path.relative_to(staging).as_posix(), "csv_sha256": _sha256(csv_path)})
            elif asset.kind == "table":
                record["warnings"].append("structured_table_unreliable")
            output.append(record)
        return output

    @staticmethod
    def _asset_path(workspace: PaperWorkspace, asset: AssetRecord) -> Path:
        try:
            relative = Path(asset.relative_path).relative_to("parsed/mineru")
        except ValueError as error:
            raise ValueError("asset_path_invalid") from error
        root = (workspace.parsed_dir / "mineru").resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise ValueError("asset_path_invalid")
        return path

    @staticmethod
    def _asset_path_from_root(
        parsed_root: Path, asset: AssetRecord
    ) -> Path:
        try:
            relative = Path(asset.relative_path).relative_to(
                "parsed/mineru"
            )
        except ValueError as error:
            raise ValueError("asset_path_invalid") from error
        root = parsed_root.resolve()
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise ValueError("asset_path_invalid")
        return path

    @staticmethod
    def _structured_path(workspace: PaperWorkspace, asset: AssetRecord) -> Path:
        if not asset.structured_path or not asset.structured_sha256:
            raise ValueError("structured_table_invalid")
        root = workspace.root.resolve()
        path = (root / asset.structured_path).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or path.is_symlink()
            or path.suffix.casefold() not in {".csv", ".json"}
            or _sha256(path) != asset.structured_sha256
        ):
            raise ValueError("structured_table_invalid")
        return path

    @staticmethod
    def _structured_csv(source: Path, destination: Path) -> None:
        if source.suffix.casefold() == ".csv":
            shutil.copyfile(source, destination)
            return
        rows = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows or not all(
            isinstance(row, list) for row in rows
        ):
            raise ValueError("structured_table_invalid")
        with destination.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, lineterminator="\n").writerows(rows)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    @staticmethod
    def _captions(rows: list[dict[str, Any]]) -> str:
        sections = ["# Figures and Tables", ""]
        for row in rows:
            sections.extend((f"## {row['export_path']}", "", row.get("caption") or "(caption missing)", ""))
        return "\n".join(sections)

    @staticmethod
    def _validate(root: Path, manifest: dict[str, Any]) -> None:
        for row in manifest["assets"]:
            exported = root / row["export_path"]
            if not exported.is_file() or _sha256(exported) != row["export_sha256"]:
                raise ValueError("export_sha256_mismatch")
            if exported.suffix.casefold() == ".png":
                try:
                    with Image.open(exported) as image:
                        image.verify()
                except (OSError, ValueError) as error:
                    raise ValueError("export_image_invalid") from error
            csv_relative = row.get("csv_path")
            csv_sha = row.get("csv_sha256")
            if csv_relative is None and csv_sha is None:
                continue
            if (
                not isinstance(csv_relative, str)
                or not isinstance(csv_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", csv_sha)
            ):
                raise ValueError("export_csv_invalid")
            relative = Path(csv_relative)
            csv_path = (root / relative).resolve()
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not csv_path.is_relative_to(root.resolve())
                or not csv_path.is_file()
                or csv_path.is_symlink()
                or _sha256(csv_path) != csv_sha
            ):
                raise ValueError("export_csv_invalid")

    @staticmethod
    def _same_package(left: Path, right: Path) -> bool:
        def snapshot(root: Path) -> dict[str, bytes]:
            return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        return snapshot(left) == snapshot(right)

    @staticmethod
    def _result(paper_id: str, workspace: PaperWorkspace, cached: bool) -> ExportResult:
        return ExportResult(paper_id, workspace.exports_dir, tuple(sorted(workspace.exports_figures.glob("Fig_*.png"))), tuple(sorted(workspace.exports_tables.glob("Table_*.png"))), cached)
