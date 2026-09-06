from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scientific_reading.candidate_rebuild as candidate_rebuild
from scientific_reading.candidate_rebuild import (
    CandidateRebuildError,
    prepare_rebuild,
)
from scientific_reading.full_read_models import FULL_TRANSLATION_CONTRACT_VERSION
from scientific_reading.full_read_service import FullReadService
from scientific_reading.mineru_normalizer import MineruNormalizer
from scientific_reading.models import PaperMetadata
from scientific_reading.workspace import PaperWorkspace
from test_evidence_locator import _fixture as _source_fixture


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _patch_normalizer_stamps(parsed: Path) -> None:
    for name in ("source_map.json", "parse_report.json"):
        path = parsed / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["method"] = "auto"
        if name == "parse_report.json":
            payload.update(
                {
                    "provider": "mineru-local-v1",
                    "provider_version": "locator-fixture",
                }
            )
        _write_json(path, payload)


def _renormalize_history(generation: PaperWorkspace, source_sha: str) -> None:
    parsed = generation.parsed_dir / "mineru"
    raw = parsed / "raw"
    metadata = PaperMetadata.from_dict(
        json.loads(generation.metadata_path.read_text(encoding="utf-8"))
    )
    MineruNormalizer("mineru-local-v1:locator-fixture").normalize(
        raw, parsed, metadata, source_sha
    )
    _patch_normalizer_stamps(parsed)


def _write_history_translations(generation: PaperWorkspace) -> Path:
    active = FullReadService._inspect_active_mineru(generation)
    path = generation.reading_dir / "full" / "translations.json"
    _write_json(
        path,
        {
            "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
            "source_sha256": active.source_sha256,
            "translations": [
                {
                    "block_id": row["block_id"],
                    "source_text": row["english"],
                    "translation_zh": (
                        "" if row["source_type"] == "reference"
                        else f"旧译文::{row['block_id']}"
                    ),
                    "highlight": "none",
                }
                for row in active.rows
            ],
        },
    )
    return path


def _mutate_cached_raw_as_historical_delta(generation: PaperWorkspace) -> None:
    parsed = generation.parsed_dir / "mineru"
    content = next((parsed / "raw").rglob("*_content_list.json"))
    items = json.loads(content.read_text(encoding="utf-8"))
    items[1]["text"] = "The target block changed during normalization."
    items.extend(
        [
            {
                "type": "text",
                "page_idx": 0,
                "bbox": [10, 150, 500, 190],
                "text": "Control text.",
            },
            {
                "type": "text",
                "page_idx": 0,
                "bbox": [10, 200, 500, 240],
                "text": "A newly recovered body block.",
            },
            {
                "type": "ref_text",
                "page_idx": 1,
                "bbox": [10, 10, 500, 50],
                "text": "[1] Newly recovered reference.",
            },
        ]
    )
    _write_json(content, items)
    raw_sha = _sha256(content)
    for name in ("source_map.json", "parse_report.json"):
        path = parsed / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["raw_content_list_sha256"] = raw_sha
        _write_json(path, payload)


def _assert_code(code: str, call) -> None:
    with pytest.raises(CandidateRebuildError) as captured:
        call()
    assert captured.value.code == code


def test_exact_historical_identity_is_reused_into_pending_candidate(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, source_sha = _source_fixture(data_root)
    translations = _write_history_translations(generation)
    source_map = generation.parsed_dir / "mineru" / "source_map.json"
    before = {
        "pdf": _sha256(generation.source_pdf),
        "source_map": _sha256(source_map),
        "translations": _sha256(translations),
    }
    target = tmp_path / "candidate"
    target.mkdir()

    result = prepare_rebuild(data_root, paper_id, target)

    assert result["status"] == "pending"
    assert result["counts"] == {
        "reused": 3,
        "pending_translation": 0,
        "pending_review": 0,
    }
    plan = json.loads((target / "rebuild-plan.json").read_text(encoding="utf-8"))
    assert plan["contract"] == "candidate-rebuild-plan-v1"
    assert plan["source"]["source_sha256"] == source_sha
    assert plan["candidate"]["generation_method"] == (
        "renormalize-verified-cached-raw-v1"
    )
    assert plan["candidate"]["full_review_reused"] is False
    assert plan["candidate"]["review_status"] == "pending"
    assert [row["translation"] for row in plan["reuse"]] == [
        {
            "block_id": row["identity"]["block_id"],
            "source_text": row["source_text"],
            "translation_zh": f"旧译文::{row['identity']['block_id']}",
            "highlight": "none",
        }
        for row in plan["reuse"]
    ]
    assert result["next_input"]["requires_full_review"] is True
    assert before == {
        "pdf": _sha256(generation.source_pdf),
        "source_map": _sha256(source_map),
        "translations": _sha256(translations),
    }


def test_changed_new_and_duplicate_text_rows_stay_pending(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    _mutate_cached_raw_as_historical_delta(generation)

    result = prepare_rebuild(data_root, paper_id, tmp_path / "candidate")

    assert result["counts"] == {
        "reused": 2,
        "pending_translation": 3,
        "pending_review": 1,
    }
    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
    reasons = {row["reason"] for row in plan["pending_translation"]}
    assert reasons == {"identity_or_source_changed", "new_source_block"}
    duplicate = next(
        row for row in plan["pending_translation"]
        if row["source_text"] == "Control text."
    )
    assert duplicate["identity"]["block_id"] == "p0001-m0004"
    reference = plan["pending_review"][0]
    assert reference["identity"]["source_type"] == "reference"
    assert reference["required_translation_zh"] == ""
    assert reference["required_highlight"] == "none"
    assert not (Path(result["candidate_root"]) / "reading").exists()


def test_reference_empty_translation_is_reused_only_with_exact_identity(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, source_sha = _source_fixture(data_root)
    content = next(
        (generation.parsed_dir / "mineru" / "raw").rglob(
            "*_content_list.json"
        )
    )
    items = json.loads(content.read_text(encoding="utf-8"))
    items.append(
        {
            "type": "ref_text",
            "page_idx": 1,
            "bbox": [10, 10, 500, 50],
            "text": "[1] Contract reference.",
        }
    )
    _write_json(content, items)
    _renormalize_history(generation, source_sha)
    _write_history_translations(generation)

    result = prepare_rebuild(data_root, paper_id, tmp_path / "candidate")
    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))

    reference = next(
        row for row in plan["reuse"]
        if row["identity"]["source_type"] == "reference"
    )
    assert reference["translation"]["translation_zh"] == ""
    assert reference["translation"]["highlight"] == "none"


def test_nonreference_empty_translation_cannot_bypass_gate(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    translations = _write_history_translations(generation)
    payload = json.loads(translations.read_text(encoding="utf-8"))
    payload["translations"][1]["translation_zh"] = ""
    _write_json(translations, payload)

    _assert_code(
        "historical_translation_invalid",
        lambda: prepare_rebuild(data_root, paper_id, tmp_path / "candidate"),
    )
    assert not (tmp_path / "candidate").exists()


def test_changed_source_pdf_is_rejected_before_candidate_creation(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    generation.source_pdf.write_bytes(b"%PDF-1.4\nchanged source\n%%EOF\n")

    _assert_code(
        "historical_source_invalid",
        lambda: prepare_rebuild(data_root, paper_id, tmp_path / "candidate"),
    )
    assert not (tmp_path / "candidate").exists()


def test_target_must_be_empty_and_outside_data_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    sentinel = nonempty / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    _assert_code(
        "candidate_target_not_empty",
        lambda: prepare_rebuild(data_root, paper_id, nonempty),
    )
    _assert_code(
        "candidate_target_not_isolated",
        lambda: prepare_rebuild(
            data_root, paper_id, data_root / "candidate"
        ),
    )
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_raw_tree_change_between_validation_and_copy_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    content = next(
        (generation.parsed_dir / "mineru" / "raw").rglob(
            "*_content_list.json"
        )
    )
    original_copytree = candidate_rebuild.shutil.copytree

    def changing_copytree(source, destination, *args, **kwargs):
        rows = json.loads(content.read_text(encoding="utf-8"))
        rows[1]["text"] = "Changed after validation but before copy."
        _write_json(content, rows)
        return original_copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(
        candidate_rebuild.shutil, "copytree", changing_copytree
    )
    _assert_code(
        "historical_source_changed",
        lambda: prepare_rebuild(data_root, paper_id, tmp_path / "candidate"),
    )
    assert not (tmp_path / "candidate").exists()


def test_raw_asset_change_between_validation_and_copy_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    asset = (
        generation.parsed_dir
        / "mineru"
        / "raw"
        / "paper"
        / "auto"
        / "images"
        / "figure.png"
    )
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"original raw asset")
    original_copytree = candidate_rebuild.shutil.copytree

    def changing_copytree(source, destination, *args, **kwargs):
        asset.write_bytes(b"changed raw asset")
        return original_copytree(source, destination, *args, **kwargs)

    monkeypatch.setattr(
        candidate_rebuild.shutil, "copytree", changing_copytree
    )
    _assert_code(
        "historical_source_changed",
        lambda: prepare_rebuild(data_root, paper_id, tmp_path / "candidate"),
    )
    assert not (tmp_path / "candidate").exists()


def test_content_list_change_before_raw_snapshot_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    raw_root = generation.parsed_dir / "mineru" / "raw"
    content = next(raw_root.rglob("*_content_list.json"))
    original_snapshot = candidate_rebuild._raw_tree_snapshot
    changed = False

    def changing_snapshot(root: Path):
        nonlocal changed
        if not changed and Path(root).resolve() == raw_root.resolve():
            changed = True
            rows = json.loads(content.read_text(encoding="utf-8"))
            rows[1]["text"] = "Changed after parsing but before snapshot."
            _write_json(content, rows)
        return original_snapshot(root)

    monkeypatch.setattr(
        candidate_rebuild, "_raw_tree_snapshot", changing_snapshot
    )
    _assert_code(
        "historical_source_changed",
        lambda: prepare_rebuild(data_root, paper_id, tmp_path / "candidate"),
    )
    assert changed is True
    assert not (tmp_path / "candidate").exists()


def test_plan_source_hashes_use_the_validated_input_snapshots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    translations = _write_history_translations(generation)
    parsed = generation.parsed_dir / "mineru"
    raw_root = parsed / "raw"
    paths = {
        "source_map_sha256": parsed / "source_map.json",
        "parse_report_sha256": parsed / "parse_report.json",
        "translations_sha256": translations,
    }
    validated_hashes = {name: _sha256(path) for name, path in paths.items()}
    original_snapshot = candidate_rebuild._raw_tree_snapshot
    changed = False

    def changing_snapshot(root: Path):
        nonlocal changed
        if not changed and Path(root).resolve() == raw_root.resolve():
            changed = True
            for path in paths.values():
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["changed_after_validation"] = True
                _write_json(path, payload)
        return original_snapshot(root)

    monkeypatch.setattr(
        candidate_rebuild, "_raw_tree_snapshot", changing_snapshot
    )
    result = prepare_rebuild(data_root, paper_id, tmp_path / "candidate")
    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))

    assert changed is True
    assert {
        name: plan["source"][name] for name in validated_hashes
    } == validated_hashes
    assert all(
        _sha256(paths[name]) != expected
        for name, expected in validated_hashes.items()
    )


def test_plan_sha_is_computed_before_atomic_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    target = (tmp_path / "candidate").resolve()
    target.mkdir()
    final_plan = target / "rebuild-plan.json"
    original_sha = candidate_rebuild._sha256
    rejected_reads = 0

    def reject_final_read(path: Path) -> str:
        nonlocal rejected_reads
        if Path(path).resolve() == final_plan:
            rejected_reads += 1
            raise OSError("simulated final plan read failure")
        return original_sha(path)

    monkeypatch.setattr(candidate_rebuild, "_sha256", reject_final_read)
    result = prepare_rebuild(data_root, paper_id, target)

    assert rejected_reads == 0
    assert result["plan_sha256"] == hashlib.sha256(
        final_plan.read_bytes()
    ).hexdigest()
    assert final_plan.is_file()


@pytest.mark.parametrize("target_existed", [False, True])
def test_atomic_publish_failure_preserves_initial_target_state(
    tmp_path: Path,
    monkeypatch,
    target_existed: bool,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _source_fixture(data_root)
    _write_history_translations(generation)
    target = (tmp_path / "candidate").resolve()
    if target_existed:
        target.mkdir()
    original_replace = Path.replace

    def failing_replace(self: Path, destination: Path):
        destination = Path(destination).resolve()
        if (
            self.parent == target.parent
            and self.name.startswith(f".{target.name}.candidate-")
            and destination == target
        ):
            raise OSError("simulated candidate publish failure")
        return original_replace(self, destination)

    monkeypatch.setattr(Path, "replace", failing_replace)
    _assert_code(
        "candidate_rebuild_failed",
        lambda: prepare_rebuild(data_root, paper_id, target),
    )
    assert target.exists() is target_existed
    if target_existed:
        assert list(target.iterdir()) == []
