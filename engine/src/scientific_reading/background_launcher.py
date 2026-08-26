from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .background_models import BackgroundRequest, JobStatus
from .background_store import BackgroundJobStore, JobClaimUnavailable
from .workspace import atomic_write_json


def process_start_identity(pid: int) -> str | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process = kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        try:
            if not kernel32.GetProcessTimes(
                process,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return f"windows:{created.dwHighDateTime:08x}{created.dwLowDateTime:08x}"
        finally:
            kernel32.CloseHandle(process)
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = stat[stat.rfind(")") + 2 :].split()
            return f"linux:{fields[19]}"
        except (OSError, IndexError):
            return None
    return None


class BackgroundLaunchError(RuntimeError):
    def __init__(self, message: str, *, job_id: str | None = None) -> None:
        super().__init__(message)
        self.job_id = job_id


@dataclass(frozen=True, slots=True)
class LaunchResult:
    job_id: str
    status: JobStatus
    process_started: bool


class BackgroundLauncher:
    def __init__(
        self,
        data_root: Path,
        *,
        popen: Callable = subprocess.Popen,
    ) -> None:
        self.data_root = Path(data_root).resolve()
        self.store = BackgroundJobStore(self.data_root)
        self.popen = popen

    def enqueue(self, request: BackgroundRequest) -> LaunchResult:
        handle = self.store.create_or_get(request)
        return self._start(handle.job_id, recover_terminal=not handle.created)

    def launch_existing(self, job_id: str) -> LaunchResult:
        return self._start(job_id, recover_terminal=True, strict=True)

    @staticmethod
    def _marker_is_fresh(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(value["started_at"])
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return False
        age = (datetime.now(timezone.utc) - started_at).total_seconds()
        return 0 <= age <= 60

    def _start(
        self,
        job_id: str,
        *,
        recover_terminal: bool = False,
        strict: bool = False,
    ) -> LaunchResult:
        handle = self.store.handle(job_id)
        try:
            with self.store.launch_claim(job_id):
                status = self.store.load_status(job_id)
                ignore_marker = False
                if status.state in {"failed", "interrupted"}:
                    if not recover_terminal:
                        if strict:
                            raise BackgroundLaunchError(
                                f"任务状态不是 queued：{status.state}"
                            )
                        return LaunchResult(job_id, status, False)
                    self.store.transition(job_id, "queued")
                    ignore_marker = True
                elif status.state != "queued":
                    if strict:
                        raise BackgroundLaunchError(
                            f"任务状态不是 queued：{status.state}"
                        )
                    return LaunchResult(job_id, status, False)

                launch_marker = handle.root / "launch.json"
                if not ignore_marker and self._marker_is_fresh(launch_marker):
                    try:
                        marker = json.loads(
                            launch_marker.read_text(encoding="utf-8")
                        )
                        marker_pid = marker.get("pid")
                    except (OSError, ValueError, json.JSONDecodeError):
                        marker = {}
                        marker_pid = None
                    if (
                        isinstance(marker_pid, int)
                        and not isinstance(marker_pid, bool)
                        and marker_pid > 0
                        and self.store._pid_is_alive(marker_pid)
                    ):
                        recorded_identity = marker.get("process_start_identity")
                        current_identity = process_start_identity(marker_pid)
                        identity_mismatch = (
                            isinstance(recorded_identity, str)
                            and bool(recorded_identity.strip())
                            and isinstance(current_identity, str)
                            and bool(current_identity.strip())
                            and recorded_identity != current_identity
                        )
                        if not identity_mismatch:
                            return LaunchResult(
                                job_id=job_id,
                                status=self.store.load_status(job_id),
                                process_started=False,
                            )
                    launch_marker.unlink(missing_ok=True)

                args = [
                    sys.executable,
                    "-m",
                    "scientific_reading.worker",
                    "--data-root",
                    str(self.data_root),
                    "--job-id",
                    job_id,
                ]
                creationflags = 0
                if os.name == "nt":
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                atomic_write_json(
                    launch_marker,
                    {"started_at": datetime.now(timezone.utc).isoformat(), "pid": None},
                )
                with handle.log_path.open("ab") as log_handle:
                    process = self.popen(
                        args,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        shell=False,
                        start_new_session=os.name != "nt",
                        creationflags=creationflags,
                    )
                atomic_write_json(
                    launch_marker,
                    {
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "pid": getattr(process, "pid", None),
                        "process_start_identity": process_start_identity(
                            getattr(process, "pid", 0)
                        ),
                    },
                )
        except JobClaimUnavailable:
            return LaunchResult(
                job_id=job_id,
                status=self.store.load_status(job_id),
                process_started=False,
            )
        except OSError as error:
            (handle.root / "launch.json").unlink(missing_ok=True)
            self.store.transition(job_id, "failed", error=str(error))
            raise BackgroundLaunchError(str(error), job_id=job_id) from error

        return LaunchResult(
            job_id=job_id,
            status=self.store.load_status(job_id),
            process_started=True,
        )
