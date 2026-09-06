from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scientific_reading.environment_status import EnvironmentStatusService


def test_actual_api_success_persists_but_configuration_probe_does_not_verify(tmp_path):
    service = EnvironmentStatusService(tmp_path, probes={"mineru_api": lambda: {"status": "configured"}})
    assert service.recheck(("mineru_api",))["mineru"]["api"]["api_call_verified"] is False
    service.mark_mineru_api_verified()
    assert EnvironmentStatusService(tmp_path).snapshot()["mineru"]["api"]["api_call_verified"] is True
    assert service.recheck(("mineru_api",))["mineru"]["api"]["api_call_verified"] is False


def test_snapshot_is_static_and_onboarding_is_presented_once(tmp_path: Path) -> None:
    calls: list[str] = []
    service = EnvironmentStatusService(
        tmp_path,
        probes={"download": lambda: calls.append("download") or {"status": "ready"}},
    )

    first = service.snapshot()
    assert first["contract_version"] == "environment-status-v1"
    assert first["onboarding"] == {"show_settings": True, "version": "v1"}
    assert first["download"]["status"] == "not_checked"
    assert calls == []

    service.mark_presented("v1")
    assert service.snapshot()["onboarding"]["show_settings"] is False
    service.mark_presented("v1")
    assert service.snapshot()["onboarding"]["show_settings"] is False


def test_recheck_only_runs_requested_probes_and_persists_safe_snapshot(tmp_path: Path) -> None:
    calls: list[str] = []
    service = EnvironmentStatusService(
        tmp_path,
        probes={
            "download": lambda: calls.append("download") or {"status": "ready"},
        },
        now=lambda: "2026-08-27T12:00:00+00:00",
    )

    result = service.recheck(("download",))
    assert calls == ["download"]
    assert result["download"]["status"] == "ready"
    assert result["download"]["mode"] == "oa_only"
    assert "institution" not in result
    persisted = json.loads(service.path.read_text(encoding="utf-8"))
    assert persisted == result


def test_library_snapshot_reads_only_local_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "library.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE items (paper_id TEXT, xlsx_sync_state TEXT)")
        conn.executemany(
            "INSERT INTO items VALUES (?, ?)",
            (("p1", "ready"), ("p2", "pending"), ("p3", "failed")),
        )

    library = EnvironmentStatusService(tmp_path).snapshot()["library"]
    assert library == {"status": "ready", "papers": 3, "xlsx_pending": 2,
                       "data_root": str(tmp_path.resolve()), "database": str(db.resolve())}


def test_invalid_recheck_target_is_rejected(tmp_path: Path) -> None:
    service = EnvironmentStatusService(tmp_path)
    try:
        service.recheck(("network",))
    except ValueError as error:
        assert str(error) == "environment_target_invalid"
    else:
        raise AssertionError("invalid target must fail")


def test_mineru_local_probe_passes_data_root(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeLocal:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

        def probe(self):
            from scientific_reading.mineru_provider import MineruProbe

            return MineruProbe("mineru-local-v1", "3.4.0", "ready")

    monkeypatch.setattr(
        "scientific_reading.mineru_local.LocalMineruProvider", FakeLocal
    )
    result = EnvironmentStatusService(
        tmp_path, now=lambda: "2026-08-27T12:00:00+00:00"
    ).recheck(("mineru_local",))
    assert seen["data_root"] == tmp_path.resolve()
    assert result["mineru"]["local"]["status"] == "ready"


@pytest.mark.parametrize("target", ["cloak", "institution"])
def test_institution_and_browser_probe_targets_are_not_available(tmp_path: Path, target) -> None:
    service = EnvironmentStatusService(
        tmp_path,
        probes={"cloak": lambda: {"status": "not_installed"}},
        now=lambda: "2026-08-27T12:00:00+00:00",
    )

    assert target not in service.snapshot()
    with pytest.raises(ValueError, match="environment_target_invalid"):
        service.recheck((target,))


def test_mineru_configuration_is_not_an_api_verification(tmp_path: Path) -> None:
    service = EnvironmentStatusService(
        tmp_path, probes={"mineru_api": lambda: {"status": "configured", "api_key": "never-return"}}
    )
    result = service.recheck(("mineru_api",))
    assert result["mineru"]["api"]["status"] == "configured"
    assert result["mineru"]["api"]["api_call_verified"] is False
    assert "never-return" not in json.dumps(result)
