from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scientific_reading.environment_status import EnvironmentStatusService


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
        school="Example University",
        probes={
            "download": lambda: calls.append("download") or {"status": "ready"},
            "institution": lambda: calls.append("institution") or {"status": "logged_in"},
        },
        now=lambda: "2026-08-27T12:00:00+00:00",
    )

    result = service.recheck(("institution",))
    assert calls == ["institution"]
    assert result["institution"] == {
        "status": "logged_in",
        "school": "Example University",
        "checked_at": "2026-08-27T12:00:00+00:00",
    }
    assert result["download"]["status"] == "not_checked"
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
    assert library == {"status": "ready", "papers": 3, "xlsx_pending": 2}


def test_invalid_recheck_target_is_rejected(tmp_path: Path) -> None:
    service = EnvironmentStatusService(tmp_path)
    try:
        service.recheck(("network",))
    except ValueError as error:
        assert str(error) == "environment_target_invalid"
    else:
        raise AssertionError("invalid target must fail")
