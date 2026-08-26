from __future__ import annotations

import json

from scientific_reading import __main__ as cli
from scientific_reading.export_service import ExportResult


def test_export_assets_cli_returns_structured_json(monkeypatch, tmp_path, capsys):
    class FakeService:
        def export_for_paper(self, data_root, paper_id, *, force=False):
            assert data_root == tmp_path
            assert paper_id == "paper-1"
            assert force is True
            return ExportResult("paper-1", tmp_path / "exports", (), (), False)
    monkeypatch.setattr(cli, "ExportService", FakeService)
    code = cli.run_cli(["--data-root", str(tmp_path), "export-assets", "--paper-id", "paper-1", "--force"])
    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"status":"exported","paper_id":"paper-1","exports_dir":str(tmp_path / "exports"),"figure_count":0,"table_count":0,"cached":False}


def test_export_assets_cli_returns_nonzero_structured_error(monkeypatch, tmp_path, capsys):
    class FakeService:
        def export_for_paper(self, *_args, **_kwargs):
            raise ValueError("active_mineru_required")
    monkeypatch.setattr(cli, "ExportService", FakeService)
    code = cli.run_cli(["--data-root", str(tmp_path), "export-assets", "--paper-id", "paper-1"])
    assert code == 4
    assert json.loads(capsys.readouterr().out) == {"status":"failed","error":"active_mineru_required"}
