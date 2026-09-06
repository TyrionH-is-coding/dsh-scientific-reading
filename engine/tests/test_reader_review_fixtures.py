from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scientific_reading.full_read_renderer import FullReadRenderer
from scripts.reader_review_fixtures import (
    FIXTURE_CASES,
    fixture_path,
    materialize_fixture,
    materialize_fixture_payload,
)


EXPECTED_CASES = (
    "formula-outline",
    "superscript-text",
    "figures-captions",
)


def _semantic_tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and path.name != "job.json"
    }


def test_fixture_registry_is_fixed_and_small() -> None:
    assert FIXTURE_CASES == EXPECTED_CASES
    assert sum(fixture_path(case).stat().st_size for case in FIXTURE_CASES) < (
        200 * 1024
    )


@pytest.mark.parametrize("case", EXPECTED_CASES)
def test_materialize_fixture_is_deterministic(
    case: str,
    tmp_path: Path,
) -> None:
    first = materialize_fixture(case, tmp_path / "a")
    second = materialize_fixture(case, tmp_path / "b")

    assert _semantic_tree_hashes(first.root) == _semantic_tree_hashes(
        second.root
    )


def test_fixture_rejects_unknown_keys(tmp_path: Path) -> None:
    payload = json.loads(
        fixture_path("formula-outline").read_text(encoding="utf-8")
    )
    payload["unexpected"] = True

    with pytest.raises(ValueError, match="fixture_contract_invalid"):
        materialize_fixture_payload(payload, tmp_path / "workspace")


@pytest.mark.parametrize("case", EXPECTED_CASES)
def test_fixture_renders_with_production_preview(
    case: str,
    tmp_path: Path,
) -> None:
    workspace = materialize_fixture(case, tmp_path / "workspace")
    output = tmp_path / "output" / "reader.html"

    FullReadRenderer().render_preview_completed(
        workspace,
        output=output,
        paper_id=f"fixture_{case.replace('-', '_')}",
    )

    html = output.read_text(encoding="utf-8")
    assert 'data-reader-revision="' in html
    assert FullReadRenderer._is_self_contained(html)


def test_formula_fixture_preserves_three_level_outline_and_mathml(
    tmp_path: Path,
) -> None:
    workspace = materialize_fixture("formula-outline", tmp_path / "workspace")
    source_map = json.loads(
        (workspace.parsed_dir / "mineru/source_map.json").read_text(
            encoding="utf-8"
        )
    )
    attention = next(
        block
        for block in source_map["blocks"]
        if block["text"].startswith("3.2.1 Scaled Dot-Product")
    )
    assert attention["section_path"] == [
        "3 Model Architecture",
        "3.2 Attention",
        "3.2.1 Scaled Dot-Product Attention",
    ]
    output = tmp_path / "reader.html"
    FullReadRenderer().render_preview_completed(
        workspace,
        output=output,
        paper_id="fixture_formula_outline",
    )
    html = output.read_text(encoding="utf-8")
    assert "3.2.1 Scaled Dot-Product Attention" in html
    assert "<math" in html
    assert "\\frac" not in html


def test_superscript_fixture_renders_only_explicit_scripts(
    tmp_path: Path,
) -> None:
    workspace = materialize_fixture("superscript-text", tmp_path / "workspace")
    output = tmp_path / "reader.html"
    FullReadRenderer().render_preview_completed(
        workspace,
        output=output,
        paper_id="fixture_superscript_text",
    )
    html = output.read_text(encoding="utf-8")

    assert "<sup>*</sup>" in html
    assert "<sub>2</sub>" in html
    assert "modi<sup>fi</sup>ed" not in html
    assert "<sup>fi</sup>rmly" not in html
    assert "The level of β did not increase" in html
    assert "β 水平没有升高" in html
    assert "1.2 × 10<sup>−3</sup> mol L<sup>−1</sup>" in html
    assert "1.2 × 10⁻³ mol L⁻¹" in html
    assert "An association does not establish causation." in html
    assert "关联并不能确立因果关系。" in html


def test_figure_fixture_renders_assets_and_captions(tmp_path: Path) -> None:
    workspace = materialize_fixture("figures-captions", tmp_path / "workspace")
    output = tmp_path / "reader.html"
    FullReadRenderer().render_preview_completed(
        workspace,
        output=output,
        paper_id="fixture_figures_captions",
    )
    html = output.read_text(encoding="utf-8")

    assert "<figure" in html
    assert 'class="asset-caption"' in html
    assert "A deliberately long engineering caption" in html
    assert "data:image/svg+xml;base64," in html


def test_fixture_preview_preserves_every_source_file(tmp_path: Path) -> None:
    workspace = materialize_fixture("formula-outline", tmp_path / "workspace")
    before = {
        path.relative_to(workspace.root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(workspace.root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }

    FullReadRenderer().render_preview_completed(
        workspace,
        output=tmp_path / "candidate/reader.html",
        paper_id="fixture_formula_outline",
    )

    after = {
        path.relative_to(workspace.root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(workspace.root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    assert after == before
