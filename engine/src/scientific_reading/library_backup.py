"""版本化整库快照；仅向空目录恢复，不自动继续任务或恢复凭据。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from . import __version__
from .data_guard import data_root_freeze
from .library_schema import TARGET_VERSION


CONTRACT = "scientific-reading-backup-v1"
MAX_FILES = 100_000
MAX_FILE_BYTES = 8 * 1024**3
MAX_TOTAL_BYTES = 256 * 1024**3
MAX_MANIFEST_BYTES = 32 * 1024**2
EXCLUDED_ROOTS = {"secrets", ".venv", ".acceptance-engine", "runtime", "downloads", ".uploads", "status", ".sr-apply-error.log"}
TEMP_PREFIXES = (".mineru-staging-", ".source.", ".full-plan-", ".reader-publish-", ".exports-staging-", ".exports-backup-", ".claim_", ".launch_claim", ".full_read_heavy")
PATH_KEYS = {"data_root", "workspace_root", "source_pdf", "pdf_path", "reader_html", "reader_path", "translations_json", "source_map_json", "full_read_md", "reading_guide_json", "highlights_json", "output_dir"}


def _now():
    return datetime.now(UTC).isoformat()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("backup_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError("backup_path_invalid")
    for part in path.parts:
        if part in {".", ".."} or re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((" ", ".")):
            raise ValueError("backup_path_invalid")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            raise ValueError("backup_path_invalid")
    return value


def _excluded(relative: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(relative).parts)
    return (
        parts[0] in EXCLUDED_ROOTS
        or parts[0] in {"library.sqlite", "library.sqlite-wal", "library.sqlite-shm", "library.sqlite-journal"}
        or any(p.endswith((".lock", ".tmp")) or p.startswith(TEMP_PREFIXES) for p in parts)
        or parts[0] == "jobs" and parts[-1] == "launch.json"
    )


def _inventory(root: Path) -> tuple[dict[str, dict], list[str]]:
    result = {}
    retained_directories = []
    for current, directories, files in os.walk(root, followlinks=False):
        for name in list(directories) + files:
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if _excluded(relative):
                if name in directories:
                    directories.remove(name)
                continue
            _relative(relative)
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.resolve().is_relative_to(root):
                raise ValueError("backup_link_not_supported")
            if path.is_dir():
                retained_directories.append(relative)
                continue
            if not path.is_file():
                raise ValueError("backup_special_file_not_supported")
            result[relative] = {"path": relative, "size": path.stat().st_size, "sha256": _sha(path)}
    return result, sorted(retained_directories)


def _database_check(path: Path) -> int:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("backup_database_invalid")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("backup_database_foreign_keys_invalid")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if not 1 <= version <= TARGET_VERSION:
            raise ValueError("backup_schema_version_unsupported")
        return version


def _discard_staging(stage: Path, parent: Path):
    resolved = stage.resolve()
    if resolved.parent != parent.resolve() or not resolved.name.startswith((".sr-backup-", ".sr-restore-")):
        raise ValueError("backup_staging_path_invalid")
    if resolved.exists():
        shutil.rmtree(resolved)


def backup_library(data_root: Path, output: Path, *, timeout: float = 30.0) -> dict:
    root, output = Path(data_root).resolve(), Path(output).resolve()
    if not (root / "library.sqlite").is_file():
        raise ValueError("library_not_found")
    if output.is_relative_to(root):
        raise ValueError("backup_output_must_be_outside_library")
    if output.exists():
        raise FileExistsError("backup_output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".sr-backup-", dir=output.parent))
    try:
        with data_root_freeze(root, timeout=timeout):
            # The root guard protects assets and all supported operations. The
            # reservation also rejects independent SQLite writers during capture.
            with closing(sqlite3.connect(root / "library.sqlite", timeout=1)) as reservation:
                reservation.execute("BEGIN IMMEDIATE")
                try:
                    inventory, directories = _inventory(root)
                    database = stage / "library.sqlite"
                    with closing(sqlite3.connect((root / "library.sqlite").as_uri() + "?mode=ro", uri=True)) as source:
                        with closing(sqlite3.connect(database)) as destination:
                            source.backup(destination)
                    schema = _database_check(database)
                    records = [{"path": "library.sqlite", "size": database.stat().st_size, "sha256": _sha(database)}] + list(inventory.values())
                    manifest = {
                        "contract": CONTRACT, "version": 1, "schema_version": schema,
                        "engine_version": __version__,
                        "created_at": _now(), "source_root": str(root), "files": records, "directories": directories,
                        "excluded_roots": sorted(EXCLUDED_ROOTS),
                        "excluded_temporary_prefixes": list(TEMP_PREFIXES),
                        "credentials": "excluded; configure credentials again after restore",
                        "unfinished_tasks": "preserved in archive; restore requires explicit resume",
                        "artifact_versions": {},
                    }
                    for relative in inventory:
                        if PurePosixPath(relative).name in {"reader-manifest.json", "package-manifest.json", "manifest.json"}:
                            artifact_bytes = (root / relative).read_bytes()
                            if hashlib.sha256(artifact_bytes).hexdigest() != inventory[relative]["sha256"]:
                                raise ValueError("backup_assets_changed")
                            payload = json.loads(artifact_bytes)
                            if isinstance(payload, dict):
                                manifest["artifact_versions"][relative] = {k: payload[k] for k in ("contract", "contract_version", "version", "reader_version", "build_version") if k in payload}
                    package = stage / "snapshot.zip"
                    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                        archive.write(database, "data/library.sqlite")
                        for relative in inventory:
                            archive.write(root / relative, "data/" + relative)
                        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                    if _inventory(root) != (inventory, directories):
                        raise ValueError("backup_assets_changed")
                    # Verify bytes actually archived, not only the preceding reads.
                    with zipfile.ZipFile(package) as archive:
                        _verify_archive(archive)
                    os.link(package, output)  # Atomic create; never replace an existing backup.
                finally:
                    reservation.rollback()
        return {"status": "completed", "path": str(output), "sha256": _sha(output), "files": len(records), "schema_version": schema, "contract": CONTRACT}
    finally:
        _discard_staging(stage, output.parent)


def _verify_archive(archive: zipfile.ZipFile, *, available_bytes: int | None = None) -> dict:
    infos = archive.infolist()
    names = [i.filename for i in infos]
    total = sum(i.file_size for i in infos)
    if len(infos) > MAX_FILES + 1 or any(i.file_size > MAX_FILE_BYTES for i in infos) or total > MAX_TOTAL_BYTES:
        raise ValueError("backup_resource_limit")
    if available_bytes is not None and total > available_bytes:
        raise ValueError("restore_disk_space_insufficient")
    if len(names) != len(set(name.casefold() for name in names)) or "manifest.json" not in names:
        raise ValueError("backup_archive_entries_invalid")
    if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
        raise ValueError("backup_manifest_too_large")
    manifest = json.loads(archive.read("manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("contract") != CONTRACT or manifest.get("version") != 1 or not isinstance(manifest.get("engine_version"), str) or not manifest["engine_version"].strip():
        raise ValueError("backup_format_unsupported")
    if not isinstance(manifest.get("source_root"), str) or not manifest["source_root"]:
        raise ValueError("backup_source_root_invalid")
    version = manifest.get("schema_version")
    if type(version) is not int or not 1 <= version <= TARGET_VERSION:
        raise ValueError("backup_schema_version_unsupported")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("backup_manifest_invalid")
    expected = {"manifest.json"}
    file_paths = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("backup_manifest_invalid")
        relative = _relative(record.get("path"))
        name = "data/" + relative
        if relative.casefold() in file_paths or (relative != "library.sqlite" and _excluded(relative)):
            raise ValueError("backup_manifest_path_invalid")
        expected.add(name)
        file_paths.add(relative.casefold())
        if type(record.get("size")) is not int or record["size"] < 0 or not re.fullmatch("[0-9a-f]{64}", str(record.get("sha256", ""))):
            raise ValueError("backup_manifest_invalid")
        try:
            info = archive.getinfo(name)
        except KeyError as error:
            raise ValueError("backup_file_missing") from error
        mode = info.external_attr >> 16
        if info.is_dir() or stat.S_ISLNK(mode) or info.file_size != record["size"]:
            raise ValueError("backup_file_invalid")
        with archive.open(info) as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != record["sha256"]:
                raise ValueError("backup_file_hash_mismatch")
    if set(names) != expected or "data/library.sqlite" not in expected:
        raise ValueError("backup_file_set_mismatch")
    directories = manifest.get("directories", [])
    if not isinstance(directories, list) or len(directories) > MAX_FILES:
        raise ValueError("backup_directories_invalid")
    directory_paths = set()
    for directory in directories:
        name = _relative(directory)
        if name.casefold() in directory_paths or name.casefold() in file_paths or _excluded(name):
            raise ValueError("backup_directory_collision")
        directory_paths.add(name.casefold())
    for path in directory_paths | file_paths:
        if any(p.as_posix() in file_paths for p in PurePosixPath(path).parents if p.as_posix() != "."):
            raise ValueError("backup_file_directory_collision")
    return manifest


def _rebase_paths(value, old_root: str, target: Path, key=""):
    if isinstance(value, dict):
        return {k: _rebase_paths(v, old_root, target, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebase_paths(v, old_root, target, key) for v in value]
    if isinstance(value, str) and key in PATH_KEYS:
        normalized = value.replace("\\", "/")
        original = old_root.replace("\\", "/").rstrip("/")
        if normalized.casefold() == original.casefold():
            return str(target)
        if normalized.casefold().startswith(original.casefold() + "/"):
            relative = _relative(normalized[len(original) + 1:])
            return str(target / relative)
        if key == "data_root":
            raise ValueError("restore_task_data_root_mismatch")
    return value


def _recover_tasks(root: Path, target: Path, old_root: str) -> list[dict]:
    recovered = []
    for request in sorted((root / "jobs").glob("job_*/request.json")):
        value = json.loads(request.read_text(encoding="utf-8"))
        rebased = _rebase_paths(value, old_root, target)
        if rebased != value:
            request.write_text(json.dumps(rebased, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        status_path = request.with_name("status.json")
        original_state = json.loads(status_path.read_text(encoding="utf-8"))
        state = _rebase_paths(original_state, old_root, target)
        previous = state["state"]
        if previous in {"running", "queued"}:
            state.update(state="interrupted", pid=None, heartbeat_at=None, error="restored_requires_resume", updated_at=_now())
            recovered.append({"job_id": request.parent.name, "from": previous, "to": "interrupted"})
        elif previous != "completed":
            state.update(pid=None, heartbeat_at=None)
        if state != original_state:
            status_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for filename in ("reading_pipeline.json", "resume.json"):
            path = request.with_name(filename)
            if path.is_file():
                original = json.loads(path.read_text(encoding="utf-8"))
                item = _rebase_paths(original, old_root, target)
                if filename == "reading_pipeline.json" and previous in {"running", "queued"} and item.get("state") != "completed":
                    item.update(state="queued", last_error="restored_requires_resume", updated_at=_now())
                if item != original:
                    path.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for kind in ("downloads", "batches"):
        for path in sorted((root / "jobs" / kind).glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status") in {"running", "queued"}:
                value.update(status="failed", owner_pid=None, updated_at=_now(), detail={"reason_code": "restored_requires_resubmit", "message": "库已恢复，请核对已完成结果后重新提交。"})
                path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                recovered.append({"job_id": path.stem, "to": "failed", "kind": kind})
    with closing(sqlite3.connect(root / "library.sqlite")) as conn:
        for row in recovered:
            conn.execute("UPDATE items SET last_error='restored_requires_resume' WHERE active_job_id=? AND status<>'full_read_ready'", (row["job_id"],))
        conn.commit()
    return recovered


def _rebase_workspace_jobs(root: Path, old_root: str, target: Path) -> list[str]:
    changed = []
    paths = list((root / "papers").glob("*/job.json")) + list((root / "papers").glob("*/generations/*/job.json"))
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        rebased = _rebase_paths(value, old_root, target)
        if rebased != value:
            path.write_text(json.dumps(rebased, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed.append(path.relative_to(root).as_posix())
    return changed


def _empty_target(target: Path):
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("restore_target_not_empty")


def restore_library(archive_path: Path, target: Path, *, timeout: float = 30.0) -> dict:
    if Path(target).is_symlink() or getattr(Path(target), "is_junction", lambda: False)():
        raise ValueError("restore_target_link_not_supported")
    archive_path, target = Path(archive_path).resolve(), Path(target).resolve()
    archive_sha256 = _sha(archive_path)
    _empty_target(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".sr-restore-", dir=target.parent))
    try:
        with data_root_freeze(target, timeout=timeout):
            _empty_target(target)
            with zipfile.ZipFile(archive_path) as archive:
                manifest = _verify_archive(archive, available_bytes=shutil.disk_usage(stage.parent).free)
                for relative in manifest.get("directories", []):
                    (stage / relative).mkdir(parents=True, exist_ok=True)
                for record in manifest["files"]:
                    destination = stage / record["path"]
                    if not destination.resolve().is_relative_to(stage.resolve()):
                        raise ValueError("backup_path_invalid")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open("data/" + record["path"]) as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    if _sha(destination) != record["sha256"]:
                        raise ValueError("backup_file_hash_mismatch")
            if _database_check(stage / "library.sqlite") != manifest["schema_version"]:
                raise ValueError("backup_schema_version_mismatch")
            from .library_schema import migrate_library
            migrate_library(stage)
            recovered = _recover_tasks(stage, target, manifest["source_root"])
            # Only execution metadata contains absolute paths. Scientific assets,
            # Reader bytes and their content hash manifests remain unchanged.
            rebased_jobs = _rebase_workspace_jobs(stage, manifest["source_root"], stage)
            _database_check(stage / "library.sqlite")
            from .__main__ import _resolve_artifact
            with closing(sqlite3.connect(stage / "library.sqlite")) as conn:
                for (paper_id,) in conn.execute("SELECT paper_id FROM attachments"):
                    _resolve_artifact(stage, paper_id, "pdf")
                for (paper_id,) in conn.execute("SELECT DISTINCT paper_id FROM artifacts WHERE kind IN ('reader','full_read','full_read_html') AND status='ready'"):
                    _resolve_artifact(stage, paper_id, "reader")
            _rebase_workspace_jobs(stage, str(stage), target)
            if _sha(archive_path) != archive_sha256:
                raise ValueError("backup_archive_changed")
            result = {"status": "completed", "data_root": str(target), "schema_version": TARGET_VERSION, "archive_sha256": archive_sha256, "recovered_tasks": recovered, "rebased_workspace_jobs": rebased_jobs, "credentials": "请重新配置凭据；未恢复 DPAPI 密钥。", "automatic_resume": False}
            (stage / ("restore-" + uuid.uuid4().hex + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            _empty_target(target)
            target_existed = target.exists()
            if target_existed:
                target.rmdir()
            try:
                stage.rename(target)
            except BaseException:
                if target_existed and not target.exists():
                    target.mkdir()
                raise
            return result
    finally:
        _discard_staging(stage, target.parent)
