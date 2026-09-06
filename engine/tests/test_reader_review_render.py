from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scientific_reading.full_read_renderer import FullReadRenderer
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace, atomic_write_json
from scripts.reader_review_fixtures import (
    FIXTURE_METHOD,
    FIXTURE_PARSER_VERSION,
    fixture_path,
    materialize_fixture,
)
from scripts.reader_review_render import (
    ReviewRenderError,
    render_review_case,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _make_real_data_root(tmp_path: Path) -> tuple[Path, str, PaperWorkspace]:
    data_root = tmp_path / "data"
    paper_id = "fixture_real_paper"
    payload = json.loads(
        fixture_path("formula-outline").read_text(encoding="utf-8")
    )
    metadata = PaperMetadata.from_dict(payload["metadata"])
    base = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
    source_bytes = (
        "%PDF-1.4\n% deterministic reader review fixture\n"
        "% formula-outline\n"
    ).encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    generation = materialize_fixture(
        "formula-outline",
        base.root / "generations" / source_sha[:16],
    )
    base.save_job(
        JobState(
            paper_id=paper_id,
            status="full_read_ready",
            stages={
                "paper_parse_upgrade": StageRecord(
                    status="completed",
                    result={
                        "active_parsed_dir": "parsed/mineru",
                        "active_workspace": f"generations/{source_sha[:16]}",
                        "source_sha256": source_sha,
                        "method": FIXTURE_METHOD,
                        "mineru_version": FIXTURE_PARSER_VERSION,
                    },
                )
            },
        )
    )
    return data_root, paper_id, generation


def _make_legacy_preview_generation(
    generation: PaperWorkspace,
    *,
    paper_id: str,
) -> None:
    FullReadRenderer().render_completed(generation, paper_id=paper_id)
    parsed_root = generation.parsed_dir / "mineru"
    source_map_path = parsed_root / "source_map.json"
    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    source_map["version"] = "mineru-normalization-v2"
    for block in source_map["blocks"]:
        block.pop("section_path", None)
        block.pop("heading_level", None)
        block.pop("structure_source", None)
    atomic_write_json(source_map_path, source_map)

    report_path = parsed_root / "parse_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["version"] = "mineru-normalization-v2"
    report["provider"] = None
    report.pop("provider_version", None)
    atomic_write_json(report_path, report)

    state = generation.load_job()
    state.stages["full_read"].result["reader_build_version"] = (
        "reader-html-v2.3.1-mobile-sticky"
    )
    generation.save_job(state)

    reader_manifest = json.loads(
        generation.reader_manifest.read_text(encoding="utf-8")
    )
    reader_manifest["parser_manifest_sha256"] = _sha256(source_map_path)
    reader_manifest["reader_build_version"] = (
        "reader-html-v2.3.1-mobile-sticky"
    )
    atomic_write_json(generation.reader_manifest, reader_manifest)
    (generation.root / "package-manifest.json").unlink(missing_ok=True)


def test_new_session_captures_baseline_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_root = tmp_path / "review"
    first = render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
        case="formula-outline",
        new_session=True,
    )
    baseline_path = review_root / "baseline/formula-outline/reader.html"
    candidate_path = review_root / "candidate/formula-outline/reader.html"
    baseline = baseline_path.read_bytes()
    original = FullReadRenderer.render_preview_completed

    def marked_render(self, workspace, *, output, paper_id):
        result = original(
            self,
            workspace,
            output=output,
            paper_id=paper_id,
        )
        output.write_text(
            output.read_text(encoding="utf-8") + "\n<!-- candidate-v2 -->\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(
        FullReadRenderer,
        "render_preview_completed",
        marked_render,
    )
    second = render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
    )

    assert baseline_path.read_bytes() == baseline
    assert b"candidate-v2" in candidate_path.read_bytes()
    assert second["revision"] == first["revision"] + 1


def test_failed_render_keeps_last_successful_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_root = tmp_path / "review"
    first = render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
        case="superscript-text",
        new_session=True,
    )
    candidate = review_root / "candidate/superscript-text/reader.html"
    before = candidate.read_bytes()

    def fail_render(*_args, **_kwargs):
        raise ValueError("synthetic_render_failure")

    monkeypatch.setattr(
        FullReadRenderer,
        "render_preview_completed",
        fail_render,
    )
    failed = render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
    )

    assert candidate.read_bytes() == before
    assert failed["status"] == "failed"
    assert failed["candidate_stale"] is True
    assert failed["revision"] == first["revision"] + 1
    assert failed["cases"]["superscript-text"]["candidate_sha256"] == (
        hashlib.sha256(before).hexdigest()
    )


def test_missing_baseline_requires_a_new_session(tmp_path: Path) -> None:
    review_root = tmp_path / "review"
    render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
        case="formula-outline",
        new_session=True,
    )
    baseline = review_root / "baseline/formula-outline/reader.html"
    baseline.unlink()

    failed = render_review_case(
        review_root=review_root,
        repository_root=Path.cwd(),
    )

    assert failed["status"] == "failed"
    assert failed["candidate_stale"] is True
    assert failed["cases"]["formula-outline"]["error_code"] == (
        "baseline_missing"
    )
    assert not baseline.exists()


def test_real_generation_is_read_only(tmp_path: Path) -> None:
    data_root, paper_id, generation = _make_real_data_root(tmp_path)
    before = _tree_hashes(generation.root)

    result = render_review_case(
        review_root=tmp_path / "review",
        repository_root=Path.cwd(),
        paper_id=paper_id,
        data_root=data_root,
        new_session=True,
    )

    assert result["status"] == "ready"
    assert _tree_hashes(generation.root) == before
    session = json.loads(
        (tmp_path / "review/session.json").read_text(encoding="utf-8")
    )
    recorded = session["cases"][paper_id]
    assert Path(recorded["source_generation"]) == generation.root.resolve()
    assert recorded["source_pdf_sha256"] == _sha256(generation.source_pdf)


def test_legacy_generation_is_rehydrated_for_read_only_preview(
    tmp_path: Path,
) -> None:
    data_root, paper_id, generation = _make_real_data_root(tmp_path)
    _make_legacy_preview_generation(generation, paper_id=paper_id)
    before = _tree_hashes(generation.root)

    result = render_review_case(
        review_root=tmp_path / "review",
        repository_root=Path.cwd(),
        paper_id=paper_id,
        data_root=data_root,
        new_session=True,
    )

    assert result["status"] == "ready"
    assert _tree_hashes(generation.root) == before
    candidate = (
        tmp_path / f"review/candidate/{paper_id}/reader.html"
    ).read_text(encoding="utf-8")
    assert "3.2 Attention" in candidate


def test_legacy_generation_rejects_tampered_raw_cache(tmp_path: Path) -> None:
    data_root, paper_id, generation = _make_real_data_root(tmp_path)
    _make_legacy_preview_generation(generation, paper_id=paper_id)
    content_list = next(
        (generation.parsed_dir / "mineru/raw").rglob("*_content_list.json")
    )
    content_list.write_text("[]\n", encoding="utf-8")

    with pytest.raises(
        ReviewRenderError,
        match="legacy_preview_source_invalid",
    ):
        render_review_case(
            review_root=tmp_path / "review",
            repository_root=Path.cwd(),
            paper_id=paper_id,
            data_root=data_root,
            new_session=True,
        )


def test_invalid_paper_id_is_rejected_before_path_lookup(tmp_path: Path) -> None:
    with pytest.raises(ReviewRenderError, match="paper_id_invalid"):
        render_review_case(
            review_root=tmp_path / "review",
            repository_root=Path.cwd(),
            paper_id="../escape",
            data_root=tmp_path / "data",
            new_session=True,
        )


def test_python_cli_prints_one_json_summary(tmp_path: Path) -> None:
    repository_root = Path.cwd()
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(repository_root / "engine/src"),
                str(repository_root / "engine"),
                str(repository_root),
            ]
        ),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/reader_review_render.py",
            "--case",
            "figures-captions",
            "--new-session",
            "--review-root",
            str(tmp_path / "review"),
            "--repository-root",
            str(repository_root),
        ],
        cwd=repository_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary["status"] == "ready"
    assert summary["selected_case"] == "figures-captions"
