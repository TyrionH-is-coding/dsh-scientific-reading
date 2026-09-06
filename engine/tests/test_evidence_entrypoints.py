from __future__ import annotations

import json
from pathlib import Path
from zipfile import BadZipFile

from scientific_reading.__main__ import run_cli
from scientific_reading.review_service import ReviewService
from test_candidate_rebuild import _write_history_translations
from test_evidence_locator import _fixture


def _run(root: Path, arguments: list[str], capsys) -> tuple[int, dict]:
    code = run_cli(["--data-root", str(root), *arguments])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return code, json.loads(captured.out)


def test_evidence_locate_and_resolve_conclusion_cli(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "data"
    paper_id, _generation, _source_sha = _fixture(data_root)

    code, locator = _run(
        data_root,
        [
            "evidence-locate",
            "--paper-id",
            paper_id,
            "--block-id",
            "p0001-m0002",
            "--quote",
            "exact target quote",
            "--page",
            "1",
        ],
        capsys,
    )
    assert code == 0
    assert locator["contract"] == "evidence-locator-v1"

    review = ReviewService(data_root)
    try:
        review.bind_session("parent-a", paper_id, "child-a")
        saved = review.confirm_conclusions(
            "child-a",
            [
                {
                    "conclusion_type": "result",
                    "conclusion_text": "A stored conclusion",
                    "basis": "paper",
                    "evidence": locator,
                }
            ],
        )
        conclusion_id = saved["conclusion_ids"][0]
    finally:
        review.close()

    code, resolved = _run(
        data_root,
        ["resolve-conclusion", "--conclusion-id", conclusion_id],
        capsys,
    )
    assert code == 0
    assert resolved["conclusion_id"] == conclusion_id
    assert resolved["evidence_status"] == "location_verified"
    assert resolved["claim_support"] == "location_only"


def test_candidate_rebuild_and_search_rebuild_cli(
    tmp_path: Path,
    capsys,
) -> None:
    data_root = tmp_path / "data"
    paper_id, generation, _source_sha = _fixture(data_root)
    _write_history_translations(generation)
    target = tmp_path / "candidate"

    code, candidate = _run(
        data_root,
        [
            "candidate-rebuild",
            "--paper-id",
            paper_id,
            "--target-root",
            str(target),
        ],
        capsys,
    )
    assert code == 0
    assert candidate["status"] == "pending"
    assert candidate["counts"]["reused"] == 3
    assert Path(candidate["plan_path"]).is_file()
    assert not (target / "reading").exists()

    code, rebuilt = _run(
        data_root,
        ["library-search-rebuild"],
        capsys,
    )
    assert code == 0
    assert rebuilt["papers"] == 1
    assert rebuilt["documents"] >= 1


def test_bad_zip_restore_is_structured_json_failure(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    from scientific_reading import library_backup

    def bad_restore(*_args, **_kwargs):
        raise BadZipFile("invalid archive")

    monkeypatch.setattr(library_backup, "restore_library", bad_restore)
    code, result = _run(
        tmp_path / "data",
        [
            "library-restore",
            "--archive",
            str(tmp_path / "bad.zip"),
            "--target",
            str(tmp_path / "restored"),
        ],
        capsys,
    )
    assert code == 4
    assert result == {"status": "failed", "error": "invalid archive"}
