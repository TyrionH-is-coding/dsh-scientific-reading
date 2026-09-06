from __future__ import annotations

import os
from pathlib import Path

from scientific_reading.background_launcher import BackgroundLauncher
from scientific_reading.background_models import BackgroundRequest


class FakeProcess:
    pid = 4242


def _enqueue(tmp_path: Path, popen) -> object:
    return BackgroundLauncher(tmp_path, popen=popen).enqueue(
        BackgroundRequest(
            paper_id="paper_token_probe",
            target_stage="full_read_pipeline",
            input_hash="a" * 64,
            payload={"data_root": str(tmp_path)},
        )
    )


def test_worker_receives_secure_store_token_without_mutating_host_or_launch_files(
    tmp_path: Path, monkeypatch
) -> None:
    token = "fictional-worker-token"
    captured: dict[str, object] = {}
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "scientific_reading.secret_store.resolve_mineru_token",
        lambda data_root: (token, "secure_store"),
    )

    def popen(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        return FakeProcess()

    launched = _enqueue(tmp_path, popen)
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["MINERU_API_TOKEN"] == token
    assert "MINERU_API_TOKEN" not in os.environ
    assert token not in str(captured["args"])
    launch_text = (tmp_path / "jobs" / launched.job_id / "launch.json").read_text(
        encoding="utf-8"
    )
    request_text = (tmp_path / "jobs" / launched.job_id / "request.json").read_text(
        encoding="utf-8"
    )
    assert token not in launch_text
    assert token not in request_text


def test_worker_does_not_invent_a_token_when_none_is_configured(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.delenv("MINERU_API_TOKEN", raising=False)
    monkeypatch.setattr(
        "scientific_reading.secret_store.resolve_mineru_token",
        lambda data_root: (None, "none"),
    )

    def popen(_args, **kwargs):
        captured["env"] = kwargs.get("env")
        return FakeProcess()

    _enqueue(tmp_path, popen)
    env = captured["env"]
    assert isinstance(env, dict)
    assert "MINERU_API_TOKEN" not in env
