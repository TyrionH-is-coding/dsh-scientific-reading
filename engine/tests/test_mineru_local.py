from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scientific_reading.mineru_local import LocalMineruProvider
from scientific_reading.mineru_provider import MineruProviderError


def _data_root_mineru(data_root: Path) -> Path:
    if os.name == "nt":
        return data_root / ".mineru-venv" / "Scripts" / "mineru.exe"
    return data_root / ".mineru-venv" / "bin" / "mineru"


def test_probe_requires_executable_and_supported_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MINERU_EXECUTABLE", raising=False)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="mineru 2.1.0", stderr="")

    provider = LocalMineruProvider(executable="mineru", which=lambda _: "C:/tools/mineru.exe", runner=runner)
    probe = provider.probe()
    assert probe.status == "ready"
    assert probe.version == "2.1.0"
    assert calls == [["C:/tools/mineru.exe", "--version"]]

    missing = LocalMineruProvider(which=lambda _: None, runner=runner).probe()
    assert missing.status == "unavailable"


def test_probe_finds_data_root_venv_when_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MINERU_EXECUTABLE", raising=False)
    executable = _data_root_mineru(tmp_path)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mineru")
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="mineru 3.4.0", stderr="")

    probe = LocalMineruProvider(
        data_root=tmp_path, which=lambda _: None, runner=runner
    ).probe()
    assert probe.status == "ready"
    assert probe.version == "3.4.0"
    assert calls == [[str(executable.resolve()), "--version"]]


def test_probe_uses_mineru_executable_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "custom-mineru.exe"
    executable.write_bytes(b"mineru")
    monkeypatch.setenv("MINERU_EXECUTABLE", str(executable))

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="mineru 3.4.1", stderr="")

    probe = LocalMineruProvider(which=lambda _: None, runner=runner).probe()
    assert probe.status == "ready"
    assert probe.version == "3.4.1"


def test_probe_keeps_found_executable_ready_when_version_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MINERU_EXECUTABLE", raising=False)
    executable = _data_root_mineru(tmp_path)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"mineru")

    def runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))

    probe = LocalMineruProvider(
        data_root=tmp_path, which=lambda _: None, runner=runner
    ).probe()
    assert probe.status == "ready"
    assert probe.version == "unknown"


def test_parse_uses_argument_array_and_requires_unique_content_list(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfixture")
    raw = tmp_path / "raw"
    calls: list[tuple[list[str], dict]] = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        output = Path(args[args.index("-o") + 1]) / "paper" / "auto"
        output.mkdir(parents=True)
        (output / "paper_content_list.json").write_text(json.dumps([{"type": "text", "text": "hello", "page_idx": 0}]), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    provider = LocalMineruProvider(which=lambda _: "C:/tools/mineru.exe", runner=runner, version="2.1.0")
    result = provider.parse(pdf, raw, "auto", lambda: None)
    assert result.provider_id == "mineru-local-v1"
    assert result.raw_root == raw.resolve()
    args, kwargs = calls[0]
    assert args == ["C:/tools/mineru.exe", "-p", str(pdf.resolve()), "-o", str(raw.resolve()), "-m", "auto"]
    assert kwargs["shell"] is False
    assert kwargs["env"]["MINERU_FORMULA_CH_SUPPORT"] == "true"

    (raw / "duplicate_content_list.json").write_text("[]", encoding="utf-8")
    with pytest.raises(MineruProviderError, match="mineru_local_output_invalid"):
        provider.validate_output(raw)
