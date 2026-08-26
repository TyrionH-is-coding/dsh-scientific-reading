from __future__ import annotations

import hashlib
import json

from scientific_reading.package_manifest import (
    PACKAGE_MANIFEST_CONTRACT,
    refresh_generation_package_manifest,
    validate_generation_package_manifest,
)
from scientific_reading.workspace import PaperWorkspace, atomic_write_json


def test_generation_package_manifest_is_thin_and_hash_verified(
    tmp_path, metadata
) -> None:
    base = PaperWorkspace.create(tmp_path, metadata)
    source = b"%PDF-1.4 package manifest\n%%EOF"
    source_sha = hashlib.sha256(source).hexdigest()
    generation = PaperWorkspace.create_generation(base, source_sha, metadata)
    generation.source_pdf.write_bytes(source)
    atomic_write_json(generation.manifest_path, {"version": 1, "assets": [{"id": "not-copied"}]})
    atomic_write_json(generation.reader_manifest, {"contract": "reader-manifest-v1", "reader_sha256": "a" * 64, "assets": [{"id": "not-copied"}]})
    atomic_write_json(generation.exports_manifest, {"contract": "asset-export-v1", "assets": [{"id": "not-copied"}]})

    path = refresh_generation_package_manifest(generation)

    assert path == generation.root / "package-manifest.json"
    payload = validate_generation_package_manifest(generation)
    assert payload["contract"] == PACKAGE_MANIFEST_CONTRACT
    assert [entry["path"] for entry in payload["entries"]] == [
        "source.pdf",
        "manifest.json",
        "reading/reader-manifest.json",
        "exports/manifest.json",
    ]
    assert all(set(entry) == {"kind", "path", "contract", "version", "sha256"} for entry in payload["entries"])
    assert "not-copied" not in json.dumps(payload)


def test_legacy_generation_without_package_manifest_remains_compatible(
    tmp_path, metadata
) -> None:
    base = PaperWorkspace.create(tmp_path, metadata)
    generation = PaperWorkspace.create_generation(base, "b" * 64, metadata)

    assert validate_generation_package_manifest(generation, required=False) is None
