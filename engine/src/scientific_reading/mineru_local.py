"""本机 MinerU CLI provider。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .mineru_provider import MineruProbe, MineruProviderError, ProviderResult
from .subprocess_utils import hidden_window_kwargs


def _data_root_executable(data_root: Path) -> Path:
    if os.name == "nt":
        return data_root / ".mineru-venv" / "Scripts" / "mineru.exe"
    return data_root / ".mineru-venv" / "bin" / "mineru"


class LocalMineruProvider:
    provider_id = "mineru-local-v1"

    def __init__(
        self,
        *,
        executable: str = "mineru",
        which=shutil.which,
        runner=subprocess.run,
        version: str | None = None,
        data_root: Path | None = None,
    ) -> None:
        self.executable = executable
        self.which = which
        self.runner = runner
        self.version = version or "unknown"
        self.data_root = Path(data_root).resolve() if data_root is not None else None
        self._resolved: str | None = None

    def _resolve_executable(self) -> str | None:
        candidates: list[str] = []
        explicit = self.executable.strip()
        if explicit and explicit not in {"mineru", "mineru.exe"}:
            candidates.append(explicit)
        env_path = os.environ.get("MINERU_EXECUTABLE", "").strip()
        if env_path:
            candidates.append(env_path)
        if self.data_root is not None:
            candidates.append(str(_data_root_executable(self.data_root)))
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file():
                return str(path.resolve())
        found = self.which(self.executable)
        return found if found else None

    def probe(self) -> MineruProbe:
        resolved = self._resolve_executable()
        if not resolved:
            return MineruProbe(self.provider_id, self.version, "unavailable")
        self._resolved = resolved
        if self.version != "unknown":
            return MineruProbe(self.provider_id, self.version, "ready")
        try:
            completed = self.runner(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
                shell=False,
                **hidden_window_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return MineruProbe(self.provider_id, "unknown", "ready")
        except (OSError, subprocess.SubprocessError):
            return MineruProbe(self.provider_id, "unknown", "unavailable")
        match = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)", f"{completed.stdout}\n{completed.stderr}")
        if completed.returncode != 0 or match is None:
            return MineruProbe(self.provider_id, "unknown", "unsupported")
        self.version = match.group(1)
        return MineruProbe(self.provider_id, self.version, "ready")

    def parse(self, pdf: Path, staging: Path, method: str, heartbeat) -> ProviderResult:
        probe = self.probe()
        if probe.status != "ready" or self._resolved is None:
            raise MineruProviderError("mineru_local_unavailable")
        source = Path(pdf).resolve()
        output = Path(staging).resolve()
        output.mkdir(parents=True, exist_ok=True)
        heartbeat()
        env = os.environ.copy()
        env["MINERU_FORMULA_CH_SUPPORT"] = "true"
        try:
            completed = self.runner(
                [self._resolved, "-p", str(source), "-o", str(output), "-m", method],
                # The CLI's API children can outlive it and retain inherited pipes.
                # Parsing consumes files, so no output pipe needs to stay open.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4 * 60 * 60,
                check=False,
                shell=False,
                env=env,
                **hidden_window_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MineruProviderError("mineru_local_failed") from error
        heartbeat()
        if completed.returncode != 0:
            raise MineruProviderError("mineru_local_failed")
        self.validate_output(output)
        return ProviderResult(self.provider_id, self.version, output)

    @staticmethod
    def validate_output(output: Path) -> None:
        root = Path(output).resolve()
        candidates = [
            path for path in root.rglob("*_content_list.json")
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)
        ]
        if len(candidates) != 1:
            raise MineruProviderError("mineru_local_output_invalid")
