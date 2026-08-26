from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .workspace import PaperWorkspace, atomic_write_json


PACKAGE_MANIFEST_CONTRACT = "generation-package-manifest-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_generation(workspace: PaperWorkspace) -> bool:
    return (
        workspace.root.parent.name == "generations"
        and re.fullmatch(r"[0-9a-f]{16}", workspace.root.name) is not None
    )


def _json_identity(path: Path, fallback_contract: str) -> tuple[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("generation_package_component_invalid")
    contract = payload.get("contract") or payload.get("contract_version") or fallback_contract
    version = payload.get("version", 1)
    return str(contract), version


def refresh_generation_package_manifest(
    workspace: PaperWorkspace,
) -> Path | None:
    if not _is_generation(workspace):
        return None
    candidates = [
        ("source_pdf", workspace.source_pdf, "source-pdf-v1"),
        ("parser_manifest", workspace.manifest_path, "asset-manifest-v1"),
        ("reader_manifest", workspace.reader_manifest, "reader-manifest-v1"),
        ("exports_manifest", workspace.exports_manifest, "asset-export-v1"),
    ]
    entries = []
    for kind, path, fallback_contract in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        if kind == "source_pdf":
            contract, version = fallback_contract, 1
        else:
            contract, version = _json_identity(path, fallback_contract)
        entries.append({
            "kind": kind,
            "path": path.relative_to(workspace.root).as_posix(),
            "contract": contract,
            "version": version,
            "sha256": _sha256(path),
        })
    target = workspace.root / "package-manifest.json"
    old = target.read_bytes() if target.is_file() else None
    try:
        atomic_write_json(target, {
            "contract": PACKAGE_MANIFEST_CONTRACT,
            "version": 1,
            "generation": workspace.root.name,
            "entries": entries,
        })
        validate_generation_package_manifest(workspace)
    except Exception:
        if old is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(old)
        raise
    return target


def validate_generation_package_manifest(
    workspace: PaperWorkspace,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    path = workspace.root / "package-manifest.json"
    if not path.is_file():
        if required:
            raise ValueError("generation_package_manifest_required")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("contract") != PACKAGE_MANIFEST_CONTRACT
            or payload.get("version") != 1
            or payload.get("generation") != workspace.root.name
            or not isinstance(payload.get("entries"), list)
        ):
            raise ValueError
        seen: set[str] = set()
        for entry in payload["entries"]:
            if not isinstance(entry, dict) or set(entry) != {
                "kind", "path", "contract", "version", "sha256"
            }:
                raise ValueError
            relative = entry["path"]
            if not isinstance(relative, str) or relative in seen:
                raise ValueError
            seen.add(relative)
            component = workspace.root / relative
            if (
                not component.is_file()
                or component.is_symlink()
                or _sha256(component) != entry["sha256"]
            ):
                raise ValueError
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
        raise ValueError("generation_package_manifest_invalid") from error
    return payload
