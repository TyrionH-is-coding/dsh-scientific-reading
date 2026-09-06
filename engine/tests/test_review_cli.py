from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from scientific_reading.__main__ import run_cli
from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata


def _run(root: Path, command: str, payload: dict, capsys, monkeypatch) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload, ensure_ascii=False)))
    code = run_cli(["--data-root", str(root), command])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    return code, json.loads(captured.out)


def test_review_cli_get_bind_context_and_confirm(tmp_path: Path, capsys, monkeypatch) -> None:
    root = tmp_path / "data"
    library = LibraryService(root)
    try:
        paper_id = library.ingest(PaperMetadata(title="Review target"))["paper_id"]
    finally:
        library.close()

    code, missing = _run(
        root,
        "review-session-get",
        {"parent_session_id": "parent-a", "paper_id": paper_id},
        capsys,
        monkeypatch,
    )
    assert code == 0
    assert missing == {
        "status": "missing",
        "parent_session_id": "parent-a",
        "paper_id": paper_id,
        "title": "Review target",
    }

    code, bound = _run(
        root,
        "review-session-bind",
        {
            "parent_session_id": "parent-a",
            "paper_id": paper_id,
            "review_session_id": "child-a",
        },
        capsys,
        monkeypatch,
    )
    assert code == 0
    assert bound["status"] == "created"

    code, context = _run(
        root,
        "review-context",
        {"review_session_id": "child-a"},
        capsys,
        monkeypatch,
    )
    assert code == 0
    assert context["paper"]["title"] == "Review target"

    code, confirmed = _run(
        root,
        "review-confirm",
        {
            "review_session_id": "child-a",
            "conclusions": [
                {
                    "conclusion_type": "主要发现",
                    "conclusion_text": "确认后的结论",
                    "evidence_locator": "Results",
                }
            ],
        },
        capsys,
        monkeypatch,
    )
    assert code == 0
    assert confirmed["status"] == "confirmed"
    assert confirmed["inserted"] == 1


def test_review_cli_rejects_unknown_paper_as_structured_error(tmp_path: Path, capsys, monkeypatch) -> None:
    code, payload = _run(
        tmp_path / "data",
        "review-session-get",
        {"parent_session_id": "parent-a", "paper_id": "missing"},
        capsys,
        monkeypatch,
    )

    assert code == 4
    assert payload == {"status": "failed", "error": "paper_not_found"}
