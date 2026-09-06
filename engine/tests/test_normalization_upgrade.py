import json

import pytest

from scientific_reading.normalization_upgrade import upgrade_unfinished_normalization
from test_mineru_current_output import _published_workspace


def test_unfinished_legacy_parse_upgrades_once_and_preserves_backup(tmp_path):
    workspace = _published_workspace(tmp_path, "mineru-normalization-v3")
    assert upgrade_unfinished_normalization(workspace)
    report = workspace.parsed_dir / "mineru" / "parse_report.json"
    assert json.loads(report.read_text())["version"] == "mineru-normalization-v4"
    transaction, = workspace.root.glob(".normalization-upgrade-*")
    assert json.loads((transaction / "previous" / "parse_report.json").read_text())["version"] == "mineru-normalization-v3"
    assert not upgrade_unfinished_normalization(workspace)


def test_failed_publication_restores_legacy_parse_job_and_plan(tmp_path, monkeypatch):
    workspace = _published_workspace(tmp_path, "mineru-normalization-v3")
    original_job = workspace.job_path.read_bytes()
    plan = workspace.reading_dir / "full"
    plan.mkdir()
    (plan / "sentinel").write_text("previous plan")
    original_save = type(workspace).save_job

    def fail_new_state(self, state):
        if state.stages["paper_parse_upgrade"].result.get("normalization_version") == "mineru-normalization-v4":
            raise RuntimeError("injected_publication_failure")
        return original_save(self, state)

    monkeypatch.setattr(type(workspace), "save_job", fail_new_state)
    with pytest.raises(RuntimeError, match="injected_publication_failure"):
        upgrade_unfinished_normalization(workspace)
    assert workspace.job_path.read_bytes() == original_job
    assert (plan / "sentinel").read_text() == "previous plan"
    assert json.loads((workspace.parsed_dir / "mineru" / "parse_report.json").read_text())["version"] == "mineru-normalization-v3"
